from __future__ import annotations

import ctypes
import os
import subprocess
import time
import threading
from ctypes import wintypes

import psutil


_cpu_sample = threading.local()


def cpu_usage():
    # 每个采样线程保留至少一秒的统计窗口，额外状态读取不缩短窗口。
    now = time.monotonic()
    if now >= getattr(_cpu_sample, "deadline", 0):
        _cpu_sample.value = round(psutil.cpu_percent())
        _cpu_sample.deadline = now + 1.0
    return _cpu_sample.value


def telemetry():
    battery = psutil.sensors_battery()
    memory=psutil.virtual_memory()
    clock=psutil.cpu_freq()
    return {"MemoryUsed":memory.used,"MemoryTotal":memory.total,"CPUClock":round(clock.current) if clock else None,
            "CPUUsage": cpu_usage(), "MemoryUsage": round(memory.percent),
            "BatteryLevel": round(battery.percent) if battery else None,
            "ACConnected": battery.power_plugged if battery else True}


def foreground(include_self=False):
    if os.name != "nt":
        return None
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    hwnd = user.GetForegroundWindow()
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value or (pid.value == os.getpid() and not include_self):
        return None
    try:
        return psutil.Process(pid.value).exe()
    except (psutil.Error, OSError):
        return None


def open_keyboard():
    target = os.path.join(os.environ.get("CommonProgramFiles", r"C:\Program Files\Common Files"), r"Microsoft Shared\ink\TabTip.exe")
    if not os.path.isfile(target):
        raise FileNotFoundError("Windows touch keyboard is unavailable")
    subprocess.Popen([target], creationflags=subprocess.CREATE_NO_WINDOW)


class XInputState(ctypes.Structure):
    _fields_ = [("packet", wintypes.DWORD), ("buttons", wintypes.WORD),
                ("lt", ctypes.c_ubyte), ("rt", ctypes.c_ubyte),
                ("lx", ctypes.c_short), ("ly", ctypes.c_short),
                ("rx", ctypes.c_short), ("ry", ctypes.c_short)]


class Gamepad:
    """调用 Windows 控制器 API。"""

    def __init__(self):
        self.dll = ctypes.WinDLL("xinput1_4", use_last_error=True) if os.name == "nt" else None
        if self.dll:
            self.dll.XInputGetState.argtypes = [wintypes.DWORD, ctypes.POINTER(XInputState)]
            self.dll.XInputGetState.restype = wintypes.DWORD

    def read(self):
        if self.dll:
            for index in range(4):
                state = XInputState()
                if self.dll.XInputGetState(index, ctypes.byref(state)) == 0:
                    return state
        return None
