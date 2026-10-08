"""系统级辅助功能：剪贴板互通、桌面通知、进程结束。

所有操作均为白名单内的固定行为，不接受任意命令注入。
"""
import os
import subprocess
import ctypes
from ctypes import wintypes
import psutil

try:
    import pyperclip
    HAS_PYPERCLIP = True
except Exception:  # noqa: BLE001
    HAS_PYPERCLIP = False

USER32 = ctypes.windll.user32


# ---------------- 剪贴板 ----------------
def read_clipboard() -> dict:
    """读取 Windows 剪贴板文本。"""
    if HAS_PYPERCLIP:
        try:
            text = pyperclip.paste()
            return {"ok": True, "text": text or "", "length": len(text or "")}
        except Exception:  # noqa: BLE001
            pass
    # 回退：CF_UNICODETEXT Win32 读取
    try:
        CF_UNICODETEXT = 13
        if not USER32.OpenClipboard(0):
            return {"ok": False, "message": "无法打开剪贴板"}
        try:
            h = USER32.GetClipboardData(CF_UNICODETEXT)
            if not h:
                return {"ok": True, "text": "", "length": 0}
            ptr = ctypes.windll.kernel32.GlobalLock(h)
            try:
                text = ctypes.wstring_at(ptr)
            finally:
                ctypes.windll.kernel32.GlobalUnlock(h)
            return {"ok": True, "text": text or "", "length": len(text or "")}
        finally:
            USER32.CloseClipboard()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"读取剪贴板失败：{exc}"}


def write_clipboard(text: str) -> dict:
    """写入文本到 Windows 剪贴板。"""
    if not isinstance(text, str):
        return {"ok": False, "message": "剪贴板内容必须是文本"}, 400
    if len(text) > 1_000_000:
        return {"ok": False, "message": "剪贴板内容过长"}, 400
    if HAS_PYPERCLIP:
        try:
            pyperclip.copy(text)
            return {"ok": True, "message": "已写入电脑剪贴板", "length": len(text)}
        except Exception:  # noqa: BLE001
            pass
    # 回退：CF_UNICODETEXT Win32 写入（修复 64 位指针被截断导致的 access violation）
    try:
        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002
        kernel32 = ctypes.windll.kernel32
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        if not USER32.OpenClipboard(0):
            return {"ok": False, "message": "无法打开剪贴板"}, 500
        try:
            USER32.EmptyClipboard()
            data = text.encode("utf-16-le") + b"\x00\x00"
            h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not h:
                return {"ok": False, "message": "分配剪贴板内存失败"}, 500
            ptr = kernel32.GlobalLock(h)
            if not ptr:
                return {"ok": False, "message": "锁定剪贴板内存失败"}, 500
            try:
                ctypes.memmove(ptr, data, len(data))
            finally:
                kernel32.GlobalUnlock(h)
            if not USER32.SetClipboardData(CF_UNICODETEXT, h):
                return {"ok": False, "message": "设置剪贴板数据失败"}, 500
        finally:
            USER32.CloseClipboard()
        return {"ok": True, "message": "已写入电脑剪贴板", "length": len(text)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"写入剪贴板失败：{exc}"}, 500


# ---------------- 桌面通知 ----------------
def notify(title: str, message: str = "") -> dict:
    """在 Windows 桌面弹出通知（Toast）。

    优先使用 winotify（标准 Windows 通知中心机制，跨版本可靠），
    若未安装则回退到 PowerShell + Windows.UI.Notifications。
    均为异步触发，不阻塞主流程。
    """
    title = (title or "电脑伴侣")[:64]
    message = (message or "")[:256]

    # 方案一：winotify（推荐）
    try:
        from winotify import Notification
        n = Notification(
            app_id="电脑伴侣",
            title=title,
            msg=message,
            duration="short",
        )
        n.show()
        return {"ok": True, "message": "已向电脑桌面发送通知"}
    except Exception:  # noqa: BLE001
        pass

    # 方案二：PowerShell Windows.UI.Notifications Toast
    ps = (
        "$e=[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime];"
        "$t=[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime];"
        f"$x=New-Object Windows.Data.Xml.Dom.XmlDocument;"
        f"$x.LoadXml('<toast><visual><binding template=\"ToastGeneric\"><text>{_xml_esc(title)}</text><text>{_xml_esc(message)}</text></binding></visual></toast>');"
        "$n=[Windows.UI.Notifications.ToastNotification]::new($x);"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('电脑伴侣').Show($n)"
    )
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return {"ok": True, "message": "已向电脑桌面发送通知"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"发送通知失败：{exc}"}


def _xml_esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


# ---------------- 结束进程 ----------------
# 受保护系统进程名：永远不可结束
PROTECTED_PROCESSES = {
    "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "services.exe",
    "lsass.exe", "winlogon.exe", "svchost.exe", "dwm.exe", "explorer.exe",
    "fontdrvhost.exe", "sihost.exe", "taskhostw.exe", "runtimebroker.exe",
    "searchhost.exe", "audiodg.exe", "conhost.exe",
}


def kill_process(pid=None, name=None, confirm: bool = False) -> dict:
    """结束单个进程。必须二次确认；受保护系统进程一律拒绝。"""
    if not confirm:
        return {"ok": False, "message": "该操作需要二次确认"}, 400
    try:
        if pid is not None:
            procs = [psutil.Process(int(pid))]
        elif name:
            procs = [p for p in psutil.process_iter(["name"]) if (p.info.get("name") or "").casefold() == name.casefold()]
        else:
            return {"ok": False, "message": "缺少进程标识"}, 400
        if not procs:
            return {"ok": False, "message": "未找到该进程"}, 404
        proc = procs[0]
        pname = (proc.info.get("name") or "").casefold() if pid is None else (proc.name() or "").casefold()
        if pname in PROTECTED_PROCESSES:
            return {"ok": False, "message": "受保护系统进程，已拒绝终止"}, 403
        # 不结束自身（后端服务）
        if proc.pid == os.getpid():
            return {"ok": False, "message": "不能结束电脑伴侣服务自身"}, 400
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except psutil.TimeoutExpired:
            proc.kill()
        return {"ok": True, "message": f"已结束进程：{proc.name() or pname} (PID {proc.pid})"}, 200
    except psutil.NoSuchProcess:
        return {"ok": False, "message": "进程已不存在"}, 404
    except psutil.AccessDenied:
        return {"ok": False, "message": "权限不足，无法结束该进程"}, 403
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"结束进程失败：{exc}"}, 500
