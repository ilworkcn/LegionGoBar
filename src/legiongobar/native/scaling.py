from __future__ import annotations

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


class Scaling:
    def __init__(self, path=None):
        self.path = path or Path(os.environ.get("LOCALAPPDATA", "")) / "Lossless Scaling/Settings.xml"
        self.pending = {}
        self.source_hash = None
        self.profile_name = "Default"

    def load(self):
        data = self.path.read_bytes()
        self.source_hash = hashlib.sha256(data).hexdigest()
        return ET.fromstring(data)

    def profile(self, root):
        matches = [p for p in root.iter("Profile") if p.findtext("Title") == self.profile_name]
        if len(matches) != 1:
            raise ValueError(f"Expected one Lossless Scaling profile named {self.profile_name!r}")
        return matches[0]

    def discover(self):
        profile = self.profile(self.load())
        values, capabilities = {"LosslessScalingCurrentProfile": self.profile_name}, {}
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
            values[key], capabilities[key] = value, True
        capabilities["LosslessScalingSaveAndRestart"] = True
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
        backup = self.path.with_suffix(".xml.legiongobar.bak")
        backup.write_bytes(data)
        fd, temporary = tempfile.mkstemp(prefix="LS-", suffix=".xml", dir=self.path.parent)
        try:
            with os.fdopen(fd, "wb") as file:
                ET.ElementTree(root).write(file, encoding="utf-8", xml_declaration=True)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        self.source_hash = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.pending.clear()

    def save_and_restart(self):
        self.save()
        processes = running()
        if not processes:
            return "Settings saved; Lossless Scaling is not running"
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
        subprocess.Popen([executable], creationflags=subprocess.CREATE_NO_WINDOW)
        return "Settings saved and Lossless Scaling restart requested"
