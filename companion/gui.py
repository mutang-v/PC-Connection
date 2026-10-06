"""电脑伴侣 Windows 图形控制面板（Tkinter + 系统托盘）。

提供了 server.py 之外的可视化入口：
- 主窗口显示服务状态 / 本机 IP / 端口 / 当前配对码 / 手机访问地址 / 配对二维码
- 一键打开网页控制台、复制配对码、停止/重启服务
- 关闭窗口时隐藏到系统托盘，服务在后台持续运行，托盘图标可随时唤出面板
"""

from __future__ import annotations

import io
import os
import queue
import threading
import webbrowser
from http.server import ThreadingHTTPServer

import tkinter as tk
from tkinter import messagebox

from .config import settings
from .http_api import CompanionHandler, local_lan_ip, make_pair_qr_png
from .qr_text import qr_payload

# 托盘是否可用（pystray 为可选依赖；缺失时退化为纯窗口模式）
try:
    import pystray
    from PIL import Image, ImageDraw
    _TRAY_OK = True
except Exception:  # pragma: no cover - 环境差异
    _TRAY_OK = False


class CompanionServer:
    """在后台线程运行 HTTP 服务的轻量封装。"""

    def __init__(self):
        self.handler = CompanionHandler
        self.server = None
        self.thread = None

    @property
    def running(self) -> bool:
        return self.server is not None

    def start(self) -> bool:
        if self.running:
            return True
        try:
            self.server = ThreadingHTTPServer((settings.host, settings.port), self.handler)
        except OSError as exc:
            self.server = None
            raise RuntimeError(f"无法在端口 {settings.port} 启动服务：{exc}") from exc
        self.handler.auth.ensure_pair_code()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="http")
        self.thread.start()
        return True

    def stop(self, join: bool = False) -> None:
        if self.server is not None:
            try:
                self.server.shutdown()
                self.server.server_close()
            finally:
                self.server = None
            if join and self.thread is not None:
                self.thread.join(timeout=3)
                self.thread = None


def _make_tray_image() -> "Image.Image":
    """生成一个简单的托盘图标（64x64 圆角方块，含字母 P）。"""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((4, 4, 60, 60), radius=14, fill=(30, 144, 255, 255))
    draw.text((16, 12), "P", fill=(255, 255, 255, 255), font=None)
    return img


class CompanionGUI:
    """主界面：把服务生命周期与 Tkinter 面板、系统托盘串起来。"""

    REFRESH_MS = 4000  # 配对码 / 状态刷新间隔

    def __init__(self):
        self.server = CompanionServer()
        self._ui_q = queue.Queue()  # 托盘线程 -> 主线程的通知队列

        self.root = tk.Tk()
        self.root.title(f"电脑伴侣 · 控制台  v1.1.0")
        self.root.geometry("440x520")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._tray: "pystray.Icon | None" = None
        self._build_widgets()
        self._init_tray()

    # ---------- UI 构建 ----------
    def _build_widgets(self) -> None:
        pad = {"padx": 14, "pady": 6}
        self.root.columnconfigure(0, weight=1)

        head = tk.Label(self.root, text="电脑伴侣 · 电脑端控制台", font=("Microsoft YaHei", 15, "bold"), fg="#1E90FF")
        head.pack(anchor="w", **pad)

        # 服务状态
        self.var_status = tk.StringVar(value="状态：启动中…")
        tk.Label(self.root, textvariable=self.var_status, font=("Microsoft YaHei", 11)).pack(anchor="w", padx=14, pady=(2, 0))

        self.var_ip = tk.StringVar(value="本机 IP：--")
        tk.Label(self.root, textvariable=self.var_ip, font=("Consolas", 11)).pack(anchor="w", **pad)

        # 配对码区
        mail = tk.Frame(self.root)
        mail.pack(fill="x", **pad)
        tk.Label(mail, text="手机配对码（10 分钟有效，过期自动刷新）", font=("Microsoft YaHei", 10), fg="#555").pack(anchor="w")
        self.var_code = tk.StringVar(value="加载中…")
        code_lbl = tk.Label(mail, textvariable=self.var_code, font=("Consolas", 26, "bold"), fg="#0a8f3c")
        code_lbl.pack(side="left", anchor="w")
        tk.Button(mail, text="复制", command=self._copy_code).pack(side="left", padx=(12, 0))
        tk.Button(mail, text="刷新", command=self._refresh_code).pack(side="left", padx=(6, 0))

        # 二维码
        self.qr_canvas = tk.Label(self.root, text="扫描上方配对码以连接", font=("Microsoft YaHei", 9), fg="#888", bg="white")
        self.qr_canvas.pack(pady=(4, 0))

        # 操作按钮
        btns = tk.Frame(self.root)
        btns.pack(fill="x", **pad)
        tk.Button(btns, text="打开网页控制台", command=self._open_web, width=16).pack(side="left")
        tk.Button(btns, text="重启服务", command=self._restart, width=12).pack(side="left", padx=(8, 0))
        tk.Button(btns, text="退出", command=self._quit, width=10, fg="white", bg="#d9534f").pack(side="right")

        note = tk.Label(
            self.root,
            text="关闭窗口后程序会最小化到系统托盘继续运行。\n请仅在可信局域网使用；防火墙需允许本程序通过。",
            font=("Microsoft YaHei", 9), fg="#888", justify="left",
        )
        note.pack(anchor="w", **pad)

    # ---------- 托盘 ----------
    def _init_tray(self) -> None:
        if not _TRAY_OK:
            return
        menu = pystray.Menu(
            pystray.MenuItem("显示面板", self._tray_show, default=True),
            pystray.MenuItem("打开网页控制台", self._tray_web),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._tray_quit),
        )
        self._tray = pystray.Icon("pccompanion", _make_tray_image(), "电脑伴侣", menu)
        self._tray.run_detached()

    def _tray_show(self, icon=None, item=None) -> None:
        self._ui_q.put("show")
        self._notify("电脑伴侣正在后台运行，已隐藏到托盘。")

    def _tray_web(self, icon=None, item=None) -> None:
        self._ui_q.put("web")

    def _tray_quit(self, icon=None, item=None) -> None:
        self._ui_q.put("quit")

    def _notify(self, msg: str) -> None:
        if self._tray is not None:
            try:
                self._tray.notify(msg, "电脑伴侣")
            except Exception:  # noqa: BLE001 - 通知失败不致命
                pass

    # ---------- 动作 ----------
    def _copy_code(self) -> None:
        code = self.var_code.get()
        if code and code.isdigit():
            self.root.clipboard_clear()
            self.root.clipboard_append(code)
            self._toast("配对码已复制")

    def _refresh_code(self) -> None:
        try:
            self.server.handler.auth.ensure_pair_code()
            self._load_static()
        except Exception as exc:  # noqa: BLE001
            self._toast(f"刷新失败：{exc}")

    def _open_web(self) -> None:
        webbrowser.open(f"http://127.0.0.1:{settings.port}")

    def _restart(self) -> None:
        try:
            self.server.stop(join=True)
            self.server.start()
            self._load_static()
            self._toast("服务已重启")
        except Exception as exc:  # noqa: BLE001
            self._toast(f"重启失败：{exc}")

    def _quit(self) -> None:
        if messagebox.askokcancel("退出", "确定退出电脑伴侣并停止服务吗？"):
            self._shutdown()

    # ---------- 生命周期 ----------
    def _on_close(self) -> None:
        """点关闭按钮：隐藏到托盘（而非退出）。"""
        if self._tray is not None:
            self.root.withdraw()
            self._notify("已最小化到系统托盘，双击托盘图标可恢复。")
        else:
            # 无托盘环境：直接询问退出
            self._quit()

    def _shutdown(self) -> None:
        try:
            self.server.stop()
        finally:
            if self._tray is not None:
                try:
                    self._tray.stop()
                except Exception:  # noqa: BLE001
                    pass
            self.root.destroy()

    # ---------- 数据加载 / 刷新 ----------
    def _load_static(self) -> None:
        """填充不常变化的静态信息（IP / 配对码 / 二维码）。"""
        try:
            ip = local_lan_ip()
            self.var_ip.set(f"手机访问：http://{ip}:{settings.port}  (WLAN IPv4)")
            auth = self.server.handler.auth
            code = auth.pair_code if not auth.pair_consumed and auth.pair_expires - __import__("time").time() > 0 else ""
            self.var_code.set(code if code else "已配对/待刷新")
            self._load_qr(ip, code)
        except Exception:  # noqa: BLE001
            pass

    def _load_qr(self, host: str, code: str) -> None:
        try:
            if not code:
                self.qr_canvas.config(text="配对码已使用，若重装 App 请点“刷新”。", bg="white")
                return
            payload = qr_payload(host=host, code=code)
            png = make_pair_qr_png(payload, box_size=5, border=2)
            img = Image.open(io.BytesIO(png))
            photo = self._pil_to_photo(img)
            self.qr_canvas.config(image=photo, text="", bg="white")
            self.qr_canvas.image = photo
        except Exception:  # noqa: BLE001
            self.qr_canvas.config(text="二维码生成失败", bg="white")

    @staticmethod
    def _pil_to_photo(img) -> "tk.PhotoImage":
        from PIL import ImageTk
        return ImageTk.PhotoImage(img)

    def _tick(self) -> None:
        """周期刷新：处理托盘线程命令 + 动态状态。"""
        self._drain_queue()
        self.var_status.set("状态：运行中  ·  端口 %d" % settings.port)
        self.root.after(self.REFRESH_MS, self._tick)

    def _drain_queue(self) -> None:
        try:
            while True:
                cmd = self._ui_q.get_nowait()
                if cmd == "show":
                    self.root.deiconify()
                    self.root.lift()
                    self.root.focus_force()
                elif cmd == "web":
                    self._open_web()
                elif cmd == "quit":
                    self._shutdown()
        except queue.Empty:
            pass

    def _toast(self, msg: str) -> None:
        # 轻提示：用标题栏右侧状态简单呈现，避免弹窗打断
        self.root.title(f"电脑伴侣 · {msg}")

    # ---------- 入口 ----------
    def run(self) -> None:
        try:
            self.server.start()
        except RuntimeError as exc:
            messagebox.showerror("启动失败", str(exc))
            self.root.destroy()
            return
        self._load_static()
        self._tick()
        self.root.mainloop()


def main() -> int:
    gui = CompanionGUI()
    gui.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
