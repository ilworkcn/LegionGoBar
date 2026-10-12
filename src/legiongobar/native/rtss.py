"""通过已安装的 RTSS 原生接口读写全局帧率限制。"""
import ctypes as C
import time
from pathlib import Path
import psutil


class Rtss:
    def __init__(self):
        self.dll = None
        self.path = None
        self.installed = False
        self.running = False

    def discover(self):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Unwinder\RTSS", 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
                directory = Path(winreg.QueryValueEx(key, "InstallDir")[0])
            self.installed = (directory/'RTSS.exe').is_file() and (directory/'RTSSHooks64.dll').is_file()
        except OSError:
            self.installed = False
        self.running = self.installed and self.is_running()
        if not self.running:
            return None
        if self.dll is None or self.path != directory:
            dll = C.WinDLL(str(directory/'RTSSHooks64.dll'))
            for name in ('LoadProfile', 'SaveProfile'):
                function = getattr(dll, name)
                function.argtypes, function.restype = [C.c_char_p], None
            dll.UpdateProfiles.argtypes, dll.UpdateProfiles.restype = [], None
            for name in ('GetProfileProperty', 'SetProfileProperty'):
                function = getattr(dll, name)
                function.argtypes = [C.c_char_p, C.c_void_p, C.c_uint32]
                function.restype = C.c_int32
            self.dll, self.path = dll, directory
        return self.read()

    @staticmethod
    def is_running():
        for process in psutil.process_iter(['name', 'create_time']):
            if (process.info['name'] or '').casefold() == 'rtss.exe':
                if time.time() - (process.info['create_time'] or time.time()) >= 2:
                    return True
        return False

    def read(self):
        if self.dll is None or not self.is_running():
            raise RuntimeError('RTSS must be installed and running')
        self.dll.LoadProfile(b'')
        value = C.c_int32()
        if not self.dll.GetProfileProperty(b'FramerateLimit', C.byref(value), C.sizeof(value)):
            raise OSError('RTSS frame limit read failed')
        return value.value

    def _write(self, value):
        data = C.c_int32(value)
        if not self.dll.SetProfileProperty(b'FramerateLimit', C.byref(data), C.sizeof(data)):
            raise OSError('RTSS frame limit write failed')
        self.dll.SaveProfile(b'')
        self.dll.UpdateProfiles()

    def set(self, value):
        if type(value) is not int or not 0 <= value <= 144:
            raise ValueError('FPS limit must be an integer from 0 to 144')
        previous = self.read()
        try:
            self._write(value)
            actual = self.read()
            if actual != value:
                raise OSError(f'RTSS readback mismatch: {actual} != {value}')
        except Exception as error:
            try:
                self.dll.LoadProfile(b'')
                self._write(previous)
                if self.read() != previous:
                    raise OSError('RTSS rollback readback mismatch')
            except Exception as rollback:
                raise RuntimeError(f'{error}; rollback failed: {rollback}') from error
            raise
        return actual
