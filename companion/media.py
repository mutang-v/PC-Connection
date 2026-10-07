"""媒体播放与音量控制（Windows）。

- 媒体控制：通过 SendInput 发送多媒体键（播放/暂停、上一首、下一首）。
- 音量控制：通过 Windows Core Audio（pycaw）读取真实的系统主音量与静音状态，
  并支持将音量**绝对值设置**到指定百分比（任务栏音量的精确设置）。
- 静音状态读取：真实读取 muted 状态。
"""
import ctypes
import time
from ctypes import wintypes

USER32 = ctypes.windll.user32

# 多媒体虚拟键码
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1

# Core Audio 相关对象（延迟导入，避免无 pycaw 环境下 module 加载失败）
_audio = None  # IAudioEndpointVolume 指针


def _get_endpoint():
    """获取并缓存 IAudioEndpointVolume 接口（系统默认扬声器）。"""
    global _audio
    if _audio is not None:
        return _audio
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    devices = AudioUtilities.GetSpeakers()
    # 新版 pycaw 的 AudioDevice 封装了 EndpointVolume 属性
    try:
        _audio = devices.EndpointVolume
    except Exception:
        # 老版本走 Activate 路径
        _audio = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        _audio = cast(_audio, POINTER(IAudioEndpointVolume))
    return _audio


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUT_UNION)]


def _send_media_key(vk: int):
    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    extra = ctypes.c_ulong(0)

    def _one(flags):
        inp = _INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki.wVk = vk
        inp.union.ki.wScan = 0
        inp.union.ki.dwFlags = flags
        inp.union.ki.time = 0
        inp.union.ki.dwExtraInfo = ctypes.pointer(extra)
        return USER32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

    _one(0)
    time.sleep(0.03)
    _one(KEYEVENTF_KEYUP)


def read_volume() -> dict:
    """返回当前真实的系统主音量百分比与静音状态（Core Audio）。"""
    result = {"volume_pct": None, "muted": None, "ok": False}
    try:
        ep = _get_endpoint()
        pct = ep.GetMasterVolumeLevelScalar() * 100
        muted = bool(ep.GetMute())
        result["volume_pct"] = max(0, min(100, round(pct)))
        result["muted"] = muted
        result["ok"] = True
        return result
    except Exception:  # noqa: BLE001
        return result


def set_volume_absolute(level: int) -> dict:
    """把主音量**绝对值**设置到 level（0-100），返回读取到的实际音量与静音状态。"""
    result = {"volume_pct": None, "muted": None, "ok": False}
    try:
        level = max(0, min(100, int(level)))
        ep = _get_endpoint()
        ep.SetMasterVolumeLevelScalar(level / 100.0, None)
        # 若目标 >0 则取消静音，便于用户感知设置成功
        if level > 0:
            ep.SetMute(0, None)
        result["ok"] = True
    except Exception:  # noqa: BLE001
        pass
    result.update(read_volume())
    return result


def change_volume(delta_pct: int) -> dict:
    """把主音量在当前真实值基础上增减 delta_pct（-100..100），并做绝对设置。"""
    current = read_volume().get("volume_pct") or 0
    target = max(0, min(100, current + int(delta_pct)))
    return set_volume_absolute(target)


def set_muted(muted: bool) -> dict:
    """设置静音状态（True=静音，False=取消静音）。"""
    try:
        ep = _get_endpoint()
        ep.SetMute(1 if muted else 0, None)
    except Exception:  # noqa: BLE001
        pass
    return read_volume()


def toggle_mute() -> dict:
    """切换静音状态，返回操作后的音量。"""
    try:
        ep = _get_endpoint()
        current = bool(ep.GetMute())
        ep.SetMute(0 if current else 1, None)
    except Exception:  # noqa: BLE001
        pass
    return read_volume()


def clamp_volume(delta_pct: int) -> int:
    """（兼容保留）把主音量增减 delta_pct，返回操作后的音量百分比。"""
    return change_volume(delta_pct).get("volume_pct")
