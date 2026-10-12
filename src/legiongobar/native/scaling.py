from __future__ import annotations

import copy
import ntpath
import re
import hashlib
import os
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import psutil

FIELDS = {name: name for name in ("ScalingType", "Sharpness", "FSROptimize", "Anime4KSize", "Anime4KVRS", "ScaleMode",
          "ScaleFactor", "AspectRatio", "LSFG3Multiplier", "LSFG3Target", "LSFG2Mode", "AutoScale", "AutoScaleDelay",
          "SyncMode", "CaptureApi", "DrawFps", "HdrSupport", "GsyncSupport", "ResizeBeforeScaling", "LS1Type", "MaxFrameLatency")}
FIELDS.update({"FrameGenType": "FrameGeneration", "LSFG3Mode": "LSFG3Mode1", "FlowScale": "LSFGFlowScale", "Size": "LSFGSize"})
BOOL = {"FSROptimize", "Anime4KVRS", "AutoScale", "DrawFps", "HdrSupport", "GsyncSupport", "ResizeBeforeScaling"}
NUMERIC = {"Sharpness": (0, 100), "ScaleFactor": (1, 5), "LSFG3Multiplier": (2, 4), "LSFG3Target": (30, 1000),
           "FlowScale": (25, 100), "AutoScaleDelay": (0, 60000), "MaxFrameLatency": (0, 4)}
ENUMS = {"ScalingType": {"Off", "LS1", "FSR", "NIS", "SGSR", "BCAS", "Anime4K", "xBR", "SharpBilinear", "Integer", "NearestNeighbor"},
         "Anime4KSize": {"Small", "Medium", "Large", "VeryLarge", "UltraLarge"}, "ScaleMode": {"Auto", "Custom"},
         "AspectRatio": {"Aspect Ratio", "AspectRatio", "Fullscreen"}, "FrameGenType": {"Off", "LSFG1", "LSFG2", "LSFG3"},
         "LSFG3Mode": {"FIXED", "ADAPTIVE"}, "LSFG2Mode": {"X2", "X3", "X4"}, "Size": {"PERFORMANCE", "BALANCED"},
         "SyncMode": {"OFF", "DEFAULT", "VSYNC1", "VSYNC2", "VSYNC3", "VSYNC4"}, "CaptureApi": {"DXGI", "WGC", "GDI"}, "LS1Type": {"BALANCED", "PERFORMANCE"}}


def running():
    result = []
    for process in psutil.process_iter(["name", "exe"]):
        try:
            if (process.info["name"] or "").casefold() == "losslessscaling.exe":
                result.append(process)
        except psutil.Error:
            pass
    return result


DEFAULTS = dict(ScalingType="Off", Sharpness=50, FSROptimize=False, Anime4KSize="Medium",
    Anime4KVRS=False, ScaleMode="Auto", ScaleFactor=2, AspectRatio="Aspect Ratio", FrameGenType="Off",
    LSFG3Mode="FIXED", LSFG3Multiplier=2, LSFG3Target=120, LSFG2Mode="X2", FlowScale=50,
    Size="BALANCED", AutoScale=False, AutoScaleDelay=0, SyncMode="OFF", CaptureApi="WGC",
    DrawFps=False, HdrSupport=False, GsyncSupport=False, ResizeBeforeScaling=False,
    LS1Type="BALANCED", MaxFrameLatency=1)
ACTION_KEYS = {"LosslessScaling" + name for name in ("Launch", "BringToForeground", "CreateProfile", "ResetProfile", "SaveAndRestart")}


def find_executable():
    for process in running():
        try:
            return Path(process.exe())
        except psutil.Error:
            pass
    import winreg
    roots = []
    for hive, key, name in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
        try:
            with winreg.OpenKey(hive, key) as handle:
                roots.append(Path(winreg.QueryValueEx(handle, name)[0]))
        except OSError:
            pass
    libraries = list(roots)
    for root in roots:
        vdf = root / "steamapps/libraryfolders.vdf"
        if vdf.is_file():
            for value in re.findall(r'"path"\s+"([^"\r\n]+)"', vdf.read_text(encoding="utf-8")):
                libraries.append(Path(value.replace(chr(92)*2, chr(92))))
    return next((library / "steamapps/common/Lossless Scaling/LosslessScaling.exe" for library in libraries
                 if (library / "steamapps/common/Lossless Scaling/LosslessScaling.exe").is_file()), None)


def hotkey(root):
    name = root.findtext("Hotkey", "S").upper()
    if len(name) == 1 and name.isascii() and name.isalnum():
        key = ord(name)
    elif name.startswith("F") and name[1:].isdigit() and 1 <= int(name[1:]) <= 24:
        key = 0x70 + int(name[1:]) - 1
    else:
        key = {"SPACE":32, "INSERT":45, "DELETE":46, "HOME":36, "END":35,
               "PAGEUP":33, "PAGEDOWN":34, "NUMPAD0":96}.get(name)
        if key is None:
            raise ValueError("Unsupported Lossless Scaling hotkey")
    aliases = {"CONTROL":17, "CTRL":17, "ALT":18, "MENU":18, "SHIFT":16, "WINDOWS":91, "WIN":91}
    modifiers = []
    for name in re.split(r"[ ,]+", root.findtext("HotkeyModifierKeys", "Control Alt").upper().strip()):
        if name not in aliases:
            raise ValueError("Unsupported Lossless Scaling hotkey modifier")
        if aliases[name] not in modifiers:
            modifiers.append(aliases[name])
    return modifiers + [key]


def send_hotkey(keys):
    import ctypes as c
    from ctypes import wintypes as w
    class Keyboard(c.Structure):
        _fields_ = [("vk",w.WORD),("scan",w.WORD),("flags",w.DWORD),("time",w.DWORD),("extra",c.c_size_t)]
    class Payload(c.Union):
        _fields_ = [("keyboard",Keyboard),("padding",c.c_ubyte*32)]
    class Input(c.Structure):
        _fields_ = [("type",w.DWORD),("payload",Payload)]
    user = c.WinDLL("user32", use_last_error=True)
    user.SendInput.argtypes = [w.UINT,c.POINTER(Input),c.c_int]
    user.SendInput.restype = w.UINT
    user.GetAsyncKeyState.argtypes = [c.c_int]
    user.GetAsyncKeyState.restype = c.c_short
    # 不释放用户实际按住的按键，也避免叠加意外的修饰键。
    if any(user.GetAsyncKeyState(key) & 0x8000 for key in set(keys) | {16,17,18,91,92}):
        raise RuntimeError("Release keyboard modifiers before toggling scaling")
    def events(sequence):
        return (Input * len(sequence))(*(Input(1, Payload(keyboard=Keyboard(key,0,flag,0,0))) for key,flag in sequence))
    data = events([(key,0) for key in keys] + [(key,2) for key in reversed(keys)])
    count = user.SendInput(len(data), data, c.sizeof(Input))
    if count != len(data):
        release = events([(key,2) for key in reversed(keys)])
        user.SendInput(len(release), release, c.sizeof(Input))
        raise OSError("Windows rejected the Lossless Scaling hotkey")


class Scaling:
    def __init__(self, path=None):
        self.path = path or Path(os.environ.get("LOCALAPPDATA", "")) / "Lossless Scaling/Settings.xml"
        self.pending = {}
        self.source_hash = None
        self.profile_name = "Default"
        self.drafts = {}
        self.enabled = False
        self.target_path = None
        self.target_hwnd = None
        self.executable = None

    def load(self):
        data = self.path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if self.pending and self.source_hash and digest != self.source_hash:
            raise RuntimeError("Lossless Scaling settings changed externally; reload before applying")
        self.source_hash = digest
        if len(data) > 16 * 1024 * 1024 or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
            raise ValueError("Invalid Lossless Scaling settings XML")
        return ET.fromstring(data)

    def profile(self, root):
        matches = [p for p in root.iter("Profile") if p.findtext("Title") == self.profile_name]
        if len(matches) != 1:
            raise ValueError(f"Expected one Lossless Scaling profile named {self.profile_name!r}")
        return matches[0]

    def discover(self):
        self.executable = find_executable()
        processes = running()
        if not processes:
            self.enabled = False
        values = {"LosslessScalingCurrentProfile": self.profile_name, "LosslessScalingEnabled": self.enabled,
                  "LosslessScalingRunning": bool(processes), "LosslessScalingInstalled": bool(self.executable)}
        capabilities = {key: bool(self.executable) for key in ("LosslessScalingLaunch", "LosslessScalingBringToForeground", "LosslessScalingEnabled")}
        if not self.path.is_file():
            return capabilities, values
        profile = self.profile(self.load())
        for name, field in FIELDS.items():
            text = profile.findtext(field)
            if text is None:
                continue
            if name in BOOL:
                value = text.casefold() == "true"
            elif name in NUMERIC:
                value = float(text) if name == "ScaleFactor" else int(text)
            else:
                value = text
            key = "LosslessScaling" + name
            values[key], capabilities[key] = self.pending.get(name, value), True
        capabilities.update({key: True for key in ACTION_KEYS if key not in ("LosslessScalingLaunch", "LosslessScalingBringToForeground")})
        return capabilities, values

    def stage(self, key, value):
        name = key.removeprefix("LosslessScaling")
        if name not in FIELDS:
            raise ValueError(key)
        if name in BOOL and not isinstance(value, bool):
            raise ValueError("Expected a boolean")
        if name in NUMERIC:
            low, high = NUMERIC[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
                raise ValueError(f"{name} must be {low}..{high}")
        if name in ENUMS and value not in ENUMS[name]:
            raise ValueError(f"Invalid {name}: {value}")
        self.pending[name] = value
        return value

    def save(self):
        data = self.path.read_bytes()
        if hashlib.sha256(data).hexdigest() != self.source_hash:
            raise RuntimeError("Lossless Scaling settings changed externally; reopen the app before applying")
        root = ET.fromstring(data)
        profile = self.profile(root)
        for name, value in self.pending.items():
            field = FIELDS[name]
            element = profile.find(field)
            if element is None:
                element = ET.SubElement(profile, field)
            element.text = str(value).lower() if isinstance(value, bool) else str(value)
        self.write(root, data)
        self.pending.clear()
        self.drafts.pop(self.profile_name, None)
        self.drafts = {key:(draft,self.source_hash) for key,(draft,_) in self.drafts.items()}

    def write(self, root, original):
        if self.path.read_bytes() != original:
            raise RuntimeError("Lossless Scaling settings changed externally; reload before applying")
        self.path.with_suffix(".xml.legiongobar.bak").write_bytes(original)
        fd, temporary = tempfile.mkstemp(prefix="LS-", suffix=".xml", dir=self.path.parent)
        try:
            with os.fdopen(fd, "wb") as file:
                ET.ElementTree(root).write(file, encoding="utf-8", xml_declaration=True)
                file.flush()
                os.fsync(file.fileno())
            # 再检查一次，避免准备临时文件期间覆盖 LS 自己保存的设置。
            if self.path.read_bytes() != original:
                raise RuntimeError("Lossless Scaling settings changed externally; reload before applying")
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        self.source_hash = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def select_game(self, path):
        if not path or not self.path.is_file():
            return False
        root = ET.fromstring(self.path.read_bytes())
        matches = [profile for profile in root.iter("Profile")
                   if profile.findtext("Path") and ntpath.normcase(ntpath.normpath(profile.findtext("Path"))) == ntpath.normcase(ntpath.normpath(path))]
        name = matches[0].findtext("Title") if len(matches) == 1 else "Default"
        if name == self.profile_name:
            return False
        self.drafts[self.profile_name] = (dict(self.pending),self.source_hash)
        self.profile_name = name
        pending, digest = self.drafts.get(name, ({},hashlib.sha256(self.path.read_bytes()).hexdigest()))
        self.pending = dict(pending)
        self.source_hash = digest
        return True

    def reset(self):
        self.pending = dict(DEFAULTS)
        return {"LosslessScaling"+key:value for key,value in self.pending.items()}

    def create_profile(self, name, path):
        if not name.strip() or not ntpath.isabs(path) or ntpath.splitext(path)[1].lower() != ".exe":
            raise ValueError("A profile name and absolute executable path are required")
        data = self.path.read_bytes()
        if hashlib.sha256(data).hexdigest() != self.source_hash:
            raise RuntimeError("Lossless Scaling settings changed externally; reload before applying")
        root = ET.fromstring(data)
        profiles = root.find(".//GameProfiles")
        default = next((p for p in root.iter("Profile") if p.findtext("Title") == "Default"), None)
        if profiles is None or default is None:
            raise ValueError("Lossless Scaling default profile is missing")
        for profile in root.iter("Profile"):
            if profile.findtext("Title", "").casefold() == name.strip().casefold() or (profile.findtext("Path") and ntpath.normcase(ntpath.normpath(profile.findtext("Path"))) == ntpath.normcase(ntpath.normpath(path))):
                raise ValueError("Lossless Scaling profile already exists")
        profile = copy.deepcopy(default)
        for key,value in (("Title",name.strip()),("Path",path)):
            element = profile.find(key)
            if element is None: element = ET.SubElement(profile,key)
            element.text = value
        profiles.append(profile)
        self.write(root,data)
        self.drafts = {key:(draft,self.source_hash) for key,(draft,_) in self.drafts.items()}
        self.select_game(path)

    def launch(self):
        if running(): return
        executable = self.executable or find_executable()
        if not executable:
            raise FileNotFoundError("Lossless Scaling is not installed in a Steam library")
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 7
        subprocess.Popen([str(executable)], cwd=str(executable.parent), startupinfo=startup)
        for _ in range(30):
            if running():
                self.enabled = False
                return
            time.sleep(.1)
        raise RuntimeError("Lossless Scaling did not start")

    def bring_to_foreground(self):
        import win32gui
        import win32process
        ids = {process.pid for process in running()}
        windows = []
        win32gui.EnumWindows(lambda hwnd,_: windows.append(hwnd) if win32process.GetWindowThreadProcessId(hwnd)[1] in ids and win32gui.IsWindowVisible(hwnd) else None, None)
        if not windows: raise RuntimeError("Lossless Scaling has no visible window")
        win32gui.ShowWindow(windows[0],9)
        win32gui.SetForegroundWindow(windows[0])

    def remember_foreground(self, known):
        import win32gui
        import win32process
        hwnd = win32gui.GetForegroundWindow()
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        if not pid or pid == os.getpid(): return None
        try:
            process = psutil.Process(pid)
            if process.name().casefold() in ("losslessscaling.exe", "explorer.exe", "searchhost.exe", "startmenuexperiencehost.exe"):
                return None
            path = process.exe()
            profile_paths = {profile.findtext("Path") for profile in ET.fromstring(self.path.read_bytes()).iter("Profile") if profile.findtext("Path")} if self.path.is_file() else set()
            allowed = {ntpath.normcase(ntpath.normpath(item)) for item in set(known) | profile_paths}
            if ntpath.normcase(ntpath.normpath(path)) in allowed:
                self.target_path, self.target_hwnd = path, hwnd
            else:
                self.target_path = self.target_hwnd = None
            return path
        except psutil.Error:
            return None

    def set_enabled(self, value):
        if type(value) is not bool: raise ValueError("Expected a boolean")
        if not running():
            self.enabled = False
            if not value: return False
            self.launch()
        if self.enabled == value: return value
        import win32gui
        import win32process
        if not self.target_hwnd or not win32gui.IsWindow(self.target_hwnd):
            raise RuntimeError("Select a game window before toggling scaling")
        pid = win32process.GetWindowThreadProcessId(self.target_hwnd)[1]
        if ntpath.normcase(psutil.Process(pid).exe()) != ntpath.normcase(self.target_path):
            raise RuntimeError("The previous game window is no longer available")
        # 只向已验证的目标窗口发送配置中的快捷键；不把界面本身送去缩放。
        win32gui.SetForegroundWindow(self.target_hwnd)
        if win32gui.GetForegroundWindow() != self.target_hwnd:
            raise RuntimeError("Windows did not activate the game window")
        send_hotkey(hotkey(ET.fromstring(self.path.read_bytes())))
        self.enabled = value
        return value

    def save_and_restart(self):
        self.save()
        processes = running()
        if not processes:
            self.launch()
            return "Settings saved and Lossless Scaling restart requested"
        import win32gui
        import win32process
        import win32con
        executable = processes[0].exe()
        ids = {process.pid for process in processes}
        def close(hwnd, context):
            if win32process.GetWindowThreadProcessId(hwnd)[1] in ids:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        win32gui.EnumWindows(close, None)
        _, alive = psutil.wait_procs(processes, timeout=4)
        if alive:
            raise RuntimeError("Settings saved; Lossless Scaling did not exit. Restart it manually")
        self.executable = Path(executable)
        self.launch()
        return "Settings saved and Lossless Scaling restart requested"
