"""媒体播放与音量控制（Windows）。

- 媒体控制：通过 SendInput 发送多媒体键（播放/暂停、上一首、下一首）。
- 音量控制：读取系统主音量（waveOutGetVolume），并通过 SendInput 按多媒体音量键增减/静音。
- 静音状态读取：本模块返回一个尽力而为的结果，取不到时返回 None 而非报错。
"""
import ctypes
import time
from ctypes import wintypes

USER32 = ctypes.windll.user32
WINMM = ctypes.windll.winmm

# 多媒体虚拟键码
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_VOLUME_UP = 0xAF
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_MUTE = 0xAD


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
    """返回当前系统主音量百分比与静音状态（尽力而为）。"""
    result = {"volume_pct": None, "muted": None, "ok": False}
    try:
        # 主混音器（waveOut）音量，0..0xFFFF
        vol = wintypes.DWORD(0)
        if WINMM.waveOutGetVolume(0, ctypes.byref(vol)) != 0:
            return result
        left = vol.value & 0xFFFF
        right = (vol.value >> 16) & 0xFFFF
        # 取左右声道平均，换算为百分比
        avg = (left + right) / 2 / 0xFFFF
        result["volume_pct"] = max(0, min(100, round(avg * 100)))
        result["ok"] = True
        # 静音状态：通过多媒体键状态尽力获取，无法可靠取得时置 None
        key_state = USER32.GetKeyState(VK_VOLUME_MUTE) & 0x0001
        result["muted"] = bool(key_state)
        return result
    except Exception:  # noqa: BLE001
        return result


def clamp_volume(delta_pct: int) -> int:
    """把主音量增减 delta_pct（可接受 -100..100），返回操作后的估算音量。"""
    # 先读出当前音量，路径数较少时按步进。为兼容多数场景，用多媒体键实现（增量键）。
    # 判断符号：正数用 VOLUME_UP，负数用 VOLUME_DOWN
    count = max(1, abs(delta_pct))
    key = VK_VOLUME_UP if delta_pct > 0 else VK_VOLUME_DOWN
    # 每次键对应大约 2% 的典型步进；为精确起见我们对每个百分点发送一次，但需限帧
    steps = min(count, 50)
    for _ in range(steps):
        _send_media_key(key)
        time.sleep(0.02)
    return read_volume().get("volume_pct")
