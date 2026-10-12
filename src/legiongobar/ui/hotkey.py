from __future__ import annotations

import ctypes as C
import os
from ctypes import wintypes as W

from PySide6.QtCore import QAbstractNativeEventFilter


class Hotkey(QAbstractNativeEventFilter):
    """Ctrl+Alt+G opens the independent window from any desktop application."""

    def __init__(self, application, reveal):
        super().__init__()
        self.application, self.reveal = application, reveal
        self.registered = False
        if os.name == "nt":
            self.user = C.WinDLL("user32", use_last_error=True)
            self.user.RegisterHotKey.argtypes = [W.HWND, C.c_int, W.UINT, W.UINT]
            self.user.RegisterHotKey.restype = W.BOOL
            self.user.UnregisterHotKey.argtypes = [W.HWND, C.c_int]
            self.user.UnregisterHotKey.restype = W.BOOL
            self.registered = bool(self.user.RegisterHotKey(None, 0x4C47, 0x4000 | 1 | 2, ord("G")))
            if self.registered:
                application.installNativeEventFilter(self)

    def nativeEventFilter(self, event_type, message):
        msg = W.MSG.from_address(int(message))
        if msg.message == 0x0312 and msg.wParam == 0x4C47:
            self.reveal()
            return True, 0
        return False, 0

    def close(self):
        if self.registered:
            self.application.removeNativeEventFilter(self)
            self.user.UnregisterHotKey(None, 0x4C47)
            self.registered = False
