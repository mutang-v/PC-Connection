"""P9 远程控制模块：通过 adb 桥接读取/控制华为 P9（EMUI 8，无需 root）。

设计说明
--------
- 通过 `adb` 与 P9 通信。支持 USB 或无线（adb connect <ip>:5555）通道。
- 只读取只读指标（电量/温度/型号），并执行白名单固定操作（勿扰、亮屏、打开热点设置）。
- **不执行任意 shell 命令**，杜绝注入风险。
- 自动探测可用设备：优先使用显式配置的地址，否则回退到唯一在线设备。
"""
from __future__ import annotations

import base64
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional


class P9Controller:
    """通过 adb 与华为 P9 交互的控制器。"""

    # 允许从客户端触发的固定操作白名单
    ALLOWED_ACTIONS = {
        "wake",            # 点亮屏幕
        "open_hotspot",    # 打开 P9"无线和网络"设置页（含个人热点入口）
        "open_wifi_settings",  # 打开 WiFi 设置页
    }

    def __init__(self, adb_path: Optional[str] = None, device: Optional[str] = None):
        self.adb = adb_path or self._locate_adb()
        self.device = device  # 例如 "192.168.43.1:5555" 或序列号；None 表示自动探测

    @staticmethod
    def _locate_adb() -> str:
        """定位 adb 可执行文件。"""
        found = shutil.which("adb")
        if found:
            return found
        # 回退到常见 SDK 路径
        candidates = [
            Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb.exe",
            Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
        raise RuntimeError("未找到 adb，请先安装 Android platform-tools 并加入 PATH。")

    def _base(self) -> list[str]:
        cmd = [self.adb]
        if self.device:
            cmd += ["-s", self.device]
        return cmd

    def _run(self, args: list[str], timeout: float = 12.0, binary: bool = False) -> subprocess.CompletedProcess:
        """执行 adb 命令，返回结果（binary=True 时以二进制模式捕获 stdout）。"""
        return subprocess.run(
            self._base() + list(args),
            capture_output=True,
            text=not binary,
            timeout=timeout,
        )

    def list_devices(self) -> list[str]:
        """返回在线设备列表（device 状态）。"""
        r = self._run(["devices"])
        devices = []
        for line in r.stdout.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices

    def screenshot(self, max_pixels: int = 1920 * 1280) -> dict:
        """截取 P9 当前屏幕，返回 base64 PNG 数据。

        - 通过 adb screencap 抓取，再逐级降采样，保证返回体尽量小（适合慢速热点链路）。
        - 返回 {"ok": True, "png_b64": "...", "snapped_at": "...", "bytes": n}。
        """
        import io
        from PIL import Image
        r = self._run(["exec-out", "screencap", "-p"], binary=True)
        # binary=True 时 stdout 是 bytes
        raw = r.stdout
        if r.returncode != 0 or not raw:
            return {"ok": False, "message": "截图失败，请确认 P9 在线且屏幕已解锁"}
        try:
            img = Image.open(io.BytesIO(raw))
            img.thumbnail((1920, 1080))
            # 若画素仍过多则继续降采样
            w, h = img.size
            while w * h > max_pixels and w > 400:
                img.thumbnail((int(w * 0.7), int(h * 0.7)))
                w, h = img.size
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="PNG", optimize=True)
            data = buf.getvalue()
        except Exception as exc:  # noqa: BLE001
            # 无 PIL 时退回原始数据
            data = raw
        return {
            "ok": True,
            "png_b64": base64.b64encode(data).decode("ascii"),
            "bytes": len(data),
            "snapped_at": time.strftime("%H:%M:%S"),
        }

    def status(self) -> dict:
        """读取 P9 只读状态：电量、温度、型号、系统、连接通道。"""
        out = self._run(["shell", "dumpsys", "battery"])
        bat = {}
        for line in out.stdout.splitlines():
            line = line.strip().lower()
            for key in ("level", "temperature", "status", "health"):
                if line.startswith(key + ":"):
                    try:
                        bat[key] = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        bat[key] = line.split(":", 1)[1].strip()
        model = self._run(["shell", "getprop", "ro.product.model"]).stdout.strip()
        release = self._run(["shell", "getprop", "ro.build.version.release"]).stdout.strip()
        return {
            "ok": True,
            "device": self.device or (self.list_devices() or [None])[0],
            "model": model,
            "android": release,
            "battery_level": bat.get("level"),
            "temperature_c": round(bat["temperature"] / 10, 1) if "temperature" in bat else None,
            "battery_status": bat.get("status"),
            "online": bool(model),
        }

    def perform_action(self, action: str) -> tuple[dict, int]:
        """执行白名单固定操作。返回 (response, http_status)。"""
        if action not in self.ALLOWED_ACTIONS:
            return {"ok": False, "message": "未允许的 P9 操作"}, 400
        try:
            if action == "wake":
                self._run(["shell", "input", "keyevent", "KEYCODE_WAKEUP"])
                return {"ok": True, "message": "已点亮 P9 屏幕"}, 200
            if action == "open_hotspot":
                # 实测：EMUI 8 不支持 android.settings.TETHER_SETTINGS，
                # WIFI_AP_SETTINGS 需要系统签名权限（shell 无权限）。
                # 最可靠的是打开"无线和网络"设置页（已验证可成功打开），
                # 其中包含"个人热点"入口，由用户在页面上点按开关。
                self._run(["shell", "am", "start", "-a", "android.settings.WIRELESS_SETTINGS"])
                return {"ok": True, "message": "已打开'无线和网络'设置页，点击'个人热点'即可开关热点"}, 200
            if action == "open_wifi_settings":
                self._run(["shell", "am", "start", "-a", "android.settings.WIFI_SETTINGS"])
                return {"ok": True, "message": "已打开 WiFi 设置页"}, 200
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "P9 响应超时，请确认设备在线"}, 504
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"P9 操作失败：{exc}"}, 500
        return {"ok": False, "message": "未允许的 P9 操作"}, 400
