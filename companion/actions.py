"""固定操作白名单。绝不接受客户端传入的任意命令。"""
import os
import subprocess
import ctypes
import psutil
from . import media

ALLOWED_ACTIONS = {
    # 系统面板
    "task_manager", "network_settings", "windows_settings",
    "bluetooth_settings", "display_settings", "sound_settings",
    "camera_settings", "power_settings", "show_desktop", "lock_screen",
    # 内存
    "memory_optimize",
    # 媒体&音量
    "media_play_pause", "media_next", "media_prev",
    "volume_up", "volume_down", "volume_mute", "volume_set",
    # 电源
    "system_sleep", "system_restart", "system_shutdown",
}

# 无需二次确认的低影响操作
LOW_RISK_ACTIONS = {
    "task_manager", "network_settings", "windows_settings",
    "bluetooth_settings", "display_settings", "sound_settings",
    "camera_settings", "power_settings", "show_desktop", "lock_screen",
    "memory_optimize",
    "media_play_pause", "media_next", "media_prev",
    "volume_up", "volume_down", "volume_mute",
}


def get_volume() -> dict:
    """读取当前主音量与静音状态（供状态/客户端展示）。"""
    return media.read_volume()


def set_volume(level: int = None, delta: int = None) -> tuple:
    """设置音量：level 为直接目标百分比（0-100），delta 为增减量。
    统一返回 (dict, status_code)，与 http_api 的 volume_set 分支保持解包一致。"""
    if level is not None:
        level = max(0, min(100, int(level)))
        current = media.read_volume().get("volume_pct") or 0
        delta = level - current
        media.clamp_volume(delta)
        return {"ok": True, "message": f"音量已设为 {level}%", "volume": media.read_volume()}, 200
    if delta is not None:
        new = media.clamp_volume(int(delta))
        return {"ok": True, "message": f"音量已调整，当前约 {new}%", "volume": media.read_volume()}, 200
    return {"ok": False, "message": "缺少音量参数"}, 400

def perform_action(action: str, confirm: bool = False):
    if action not in ALLOWED_ACTIONS:
        return {"ok": False, "message": "未允许的操作"}, 400
    if os.name != "nt":
        return {"ok": False, "message": "此功能目前仅支持 Windows 电脑"}, 400
    # 电源类操作属于高影响操作，必须显式确认，防止误触
    if action in {"system_sleep", "system_restart", "system_shutdown"} and not confirm:
        return {"ok": False, "message": "该操作需要二次确认"}, 400
    try:
        if action == "task_manager":
            subprocess.Popen(["taskmgr.exe"], close_fds=True)
            return {"ok": True, "message": "已请求打开任务管理器"}, 200
        if action == "network_settings":
            os.startfile("ms-settings:network-status")
            return {"ok": True, "message": "已请求打开 Windows 网络设置"}, 200
        if action == "windows_settings":
            os.startfile("ms-settings:")
            return {"ok": True, "message": "已请求打开 Windows 设置"}, 200
        if action == "bluetooth_settings":
            os.startfile("ms-settings:bluetooth")
            return {"ok": True, "message": "已请求打开蓝牙设置"}, 200
        if action == "display_settings":
            os.startfile("ms-settings:display")
            return {"ok": True, "message": "已请求打开显示设置"}, 200
        if action == "sound_settings":
            os.startfile("ms-settings:sound")
            return {"ok": True, "message": "已请求打开声音设置"}, 200
        if action == "camera_settings":
            os.startfile("ms-settings:privacy-webcam")
            return {"ok": True, "message": "已请求打开隐私相机设置"}, 200
        if action == "power_settings":
            os.startfile("ms-settings:powersleep")
            return {"ok": True, "message": "已请求打开电源与睡眠设置"}, 200
        if action == "show_desktop":
            # 显示桌面：发送 Win+D
            ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)  # Win down
            ctypes.windll.user32.keybd_event(0x44, 0, 0, 0)  # D
            ctypes.windll.user32.keybd_event(0x44, 0, 2, 0)  # D up
            ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)  # Win up
            return {"ok": True, "message": "已显示桌面"}, 200
        if action == "lock_screen":
            ctypes.windll.user32.LockWorkStation()
            return {"ok": True, "message": "电脑已锁定"}, 200
        if action in {
            "media_play_pause", "media_next", "media_prev",
            "volume_up", "volume_down", "volume_mute",
        }:
            _MEDIA_VK = {
                "media_play_pause": media.VK_MEDIA_PLAY_PAUSE,
                "media_next": media.VK_MEDIA_NEXT_TRACK,
                "media_prev": media.VK_MEDIA_PREV_TRACK,
                "volume_up": media.VK_VOLUME_UP,
                "volume_down": media.VK_VOLUME_DOWN,
                "volume_mute": media.VK_VOLUME_MUTE,
            }
            media._send_media_key(_MEDIA_VK[action])
            labels = {
                "media_play_pause": "播放/暂停", "media_next": "下一首",
                "media_prev": "上一首", "volume_up": "音量增大",
                "volume_down": "音量减小", "volume_mute": "静音切换",
            }
            return {"ok": True, "message": f"已发送：{labels[action]}"}, 200
        if action == "system_sleep":
            ctypes.windll.powrprof.SetSuspendState(False, True, False)
            return {"ok": True, "message": "电脑已请求进入睡眠"}, 200
        if action == "system_restart":
            subprocess.Popen(["shutdown", "/r", "/t", "3"], close_fds=True)
            return {"ok": True, "message": "电脑将在 3 秒后重启"}, 200
        if action == "system_shutdown":
            subprocess.Popen(["shutdown", "/s", "/t", "5"], close_fds=True)
            return {"ok": True, "message": "电脑将在 5 秒后关机（可用 shutdown /a 取消）"}, 200
        if action == "memory_optimize":
            # Conservative working-set trim: only current user's larger ordinary apps.
            # Never terminate processes, clear caches, or accept arbitrary process IDs.
            before = psutil.virtual_memory()
            trimmed = 0
            skipped = 0
            current_pid = os.getpid()
            try:
                current_user = (psutil.Process().username() or "").casefold()
            except Exception:
                current_user = ""
            protected_names = {
                "system", "registry", "smss.exe", "csrss.exe", "wininit.exe",
                "services.exe", "lsass.exe", "winlogon.exe", "svchost.exe",
                "dwm.exe", "fontdrvhost.exe", "explorer.exe", "sihost.exe",
                "taskhostw.exe", "runtimebroker.exe", "searchhost.exe",
            }
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            OpenProcess = kernel32.OpenProcess
            OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
            OpenProcess.restype = ctypes.c_void_p
            EmptyWorkingSet = psapi.EmptyWorkingSet
            EmptyWorkingSet.argtypes = [ctypes.c_void_p]
            EmptyWorkingSet.restype = ctypes.c_int
            CloseHandle = kernel32.CloseHandle
            CloseHandle.argtypes = [ctypes.c_void_p]
            PROCESS_QUERY_INFORMATION = 0x0400
            PROCESS_SET_QUOTA = 0x0100
            minimum_rss = 128 * 1024 * 1024
            for proc in psutil.process_iter(["pid", "name", "username", "memory_info"]):
                try:
                    info = proc.info
                    pid = int(info.get("pid") or 0)
                    name = (info.get("name") or "").casefold()
                    username = (info.get("username") or "").casefold()
                    rss_info = info.get("memory_info")
                    rss = rss_info.rss if rss_info else 0
                    if pid in (0, 4, current_pid) or name in protected_names:
                        skipped += 1
                        continue
                    if not current_user or username != current_user or rss < minimum_rss:
                        skipped += 1
                        continue
                    handle = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, 0, pid)
                    if not handle:
                        skipped += 1
                        continue
                    try:
                        if EmptyWorkingSet(handle):
                            trimmed += 1
                        else:
                            skipped += 1
                    finally:
                        CloseHandle(handle)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
                    skipped += 1
            after = psutil.virtual_memory()
            return {"ok": True, "message": "已尝试整理当前用户部分普通应用的工作集。", "trimmed_processes": trimmed, "skipped_processes": skipped, "available_before_gb": round(before.available / 1024**3, 2), "available_after_gb": round(after.available / 1024**3, 2), "available_delta_gb": round((after.available-before.available) / 1024**3, 2), "warning": "不会结束进程；相关应用可能短暂卡顿。工作集回收不等于增加物理内存，也不保证提升性能。"}, 200
    except Exception as exc:
        return {"ok": False, "message": f"操作失败：{exc}"}, 500
    return {"ok": False, "message": "未允许的操作"}, 400
