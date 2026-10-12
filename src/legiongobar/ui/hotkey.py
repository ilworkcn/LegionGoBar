from __future__ import annotations

import ctypes as C
import os
from ctypes import wintypes as W

from PySide6.QtCore import QAbstractNativeEventFilter


class Hotkey(QAbstractNativeEventFilter):
    """通过 Ctrl+Alt+G 从桌面应用唤出窗口。"""

    def __init__(self, application, reveal):
        super().__init__()
        self.application, self.reveal = application, reveal
        self.registered = False
        self.bindings = {}
        self.callbacks = {}
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
        if msg.message == 0x0312 and msg.wParam in self.callbacks:
            self.callbacks[msg.wParam]()
            return True, 0
        if msg.message == 0x0312 and msg.wParam == 0x4C47:
            self.reveal()
            return True, 0
        return False, 0

    def set_bindings(self, bindings, callback):
        from ..tile_hotkeys import validate, native_key
        validate(bindings)
        desired = {key: native_key(value['keyboard']) for key,value in bindings.items() if value.get('keyboard')}
        if not self.registered:
            raise OSError("Global hotkey registration is unavailable")
        previous = dict(self.bindings)
        def unregister():
            for identifier in self.callbacks:self.user.UnregisterHotKey(None, identifier)
            self.callbacks.clear()
        def register(values):
            for index,(key,(mods,vk)) in enumerate(sorted(values.items())):
                identifier = 0x4C48 + index
                if not self.user.RegisterHotKey(None,identifier,mods|0x4000,vk):
                    raise OSError("Keyboard shortcut is occupied by another application")
                self.callbacks[identifier] = lambda k=key:callback(k)
        unregister()
        try:
            register(desired)
        except Exception as error:
            unregister()
            try:register(previous)
            except Exception as restore:
                raise OSError(f"{error}; previous shortcuts could not be restored: {restore}") from error
            raise
        self.bindings = desired

    def close(self):
        if self.registered:
            for identifier in self.callbacks:self.user.UnregisterHotKey(None,identifier)
            self.callbacks.clear()
            self.application.removeNativeEventFilter(self)
            self.user.UnregisterHotKey(None, 0x4C47)
            self.registered = False
