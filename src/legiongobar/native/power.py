from __future__ import annotations

import ctypes as C
import uuid
from ctypes import wintypes as W

CPU = "54533251-82be-4824-96c1-47b60b740d00"
BOOST = "be337238-0d82-4146-a960-4f3749d470c7"
EPP = "36687f9e-e3a5-4dbf-b1dc-15eb381c6863"
BUTTONS = "4f971e89-eebd-4455-a8de-9e59040e7347"
POWER_BUTTON = "7648efa3-dd9c-4e3e-b566-50f929386280"
VIDEO = "7516b95f-f776-4464-8c53-06167f40cc99"
VIDEO_IDLE = "3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e"
POWER_FIELDS = {"PowerButtonActionAC": (POWER_BUTTON, BUTTONS, True), "PowerButtonActionDC": (POWER_BUTTON, BUTTONS, False),
                "DisplayTimeoutAC": (VIDEO_IDLE, VIDEO, True), "DisplayTimeoutDC": (VIDEO_IDLE, VIDEO, False)}
OVERLAYS = ["961cc777-2547-4f9d-8174-7d86181b8a7a", "00000000-0000-0000-0000-000000000000", "ded574b5-45a0-4f42-8737-46345c09c238"]


class Guid(C.Structure):
    _fields_ = [("data", C.c_ubyte * 16)]

    @classmethod
    def parse(cls, value):
        return cls((C.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le))


class WindowsPower:
    def __init__(self):
        self.dll = C.WinDLL("PowrProf", use_last_error=True)
        pointer = C.POINTER(Guid)
        self.dll.PowerGetActiveScheme.argtypes = [W.HANDLE, C.POINTER(pointer)]
        self.dll.PowerGetActiveScheme.restype = W.DWORD
        self.dll.PowerSetActiveScheme.argtypes = [W.HANDLE, pointer]
        self.dll.PowerSetActiveScheme.restype = W.DWORD
        for source in ("AC", "DC"):
            read = getattr(self.dll, f"PowerRead{source}ValueIndex")
            read.argtypes = [W.HANDLE, pointer, pointer, pointer, C.POINTER(W.DWORD)]
            read.restype = W.DWORD
            write = getattr(self.dll, f"PowerWrite{source}ValueIndex")
            write.argtypes = [W.HANDLE, pointer, pointer, pointer, W.DWORD]
            write.restype = W.DWORD
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        self.kernel.LocalFree.argtypes = [W.HLOCAL]
        self.kernel.LocalFree.restype = W.HLOCAL

    @staticmethod
    def check(code):
        if code:
            raise OSError(code, C.FormatError(code))

    def scheme(self):
        pointer = C.POINTER(Guid)()
        self.check(self.dll.PowerGetActiveScheme(None, C.byref(pointer)))
        try:
            return Guid.from_buffer_copy(C.string_at(pointer, C.sizeof(Guid)))
        finally:
            self.kernel.LocalFree(C.cast(pointer, W.HLOCAL))

    def read(self, setting, ac=True, subgroup=CPU):
        scheme, subgroup, field = self.scheme(), Guid.parse(subgroup), Guid.parse(setting)
        result = W.DWORD()
        self.check(getattr(self.dll, f"PowerRead{'AC' if ac else 'DC'}ValueIndex")(None, C.byref(scheme), C.byref(subgroup), C.byref(field), C.byref(result)))
        return result.value

    def set(self, setting, value, ac, subgroup=CPU):
        subgroup_name = subgroup
        scheme, subgroup, field = self.scheme(), Guid.parse(subgroup_name), Guid.parse(setting)
        write = getattr(self.dll, f"PowerWrite{'AC' if ac else 'DC'}ValueIndex")
        self.check(write(None, C.byref(scheme), C.byref(subgroup), C.byref(field), value))
        self.check(self.dll.PowerSetActiveScheme(None, C.byref(scheme)))
        actual = self.read(setting, ac, subgroup_name)
        if actual != value:
            raise OSError(f"Power setting readback mismatch: {actual} != {value}")
        return actual

    def get_mode(self):
        function = self.dll.PowerGetEffectiveOverlayScheme
        function.argtypes = [C.POINTER(Guid)]
        function.restype = W.DWORD
        result = Guid()
        self.check(function(C.byref(result)))
        value = str(uuid.UUID(bytes_le=bytes(result.data)))
        if value not in OVERLAYS:
            raise RuntimeError(f"Unknown Windows overlay scheme: {value}")
        return OVERLAYS.index(value)

    def set_mode(self, value):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < len(OVERLAYS):
            raise ValueError("OS power mode must be 0..2")
        function = self.dll.PowerSetActiveOverlayScheme
        function.argtypes = [Guid]
        function.restype = W.DWORD
        self.check(function(Guid.parse(OVERLAYS[value])))
        actual = self.get_mode()
        if actual != value:
            raise RuntimeError("OS power mode did not change")
        return actual
