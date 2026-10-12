from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .native import legion_hid as hid
from .native.system import telemetry
from .native.wmi import FEATURES
from .native.power import POWER_FIELDS
from .osd import UI_FIELDS as OSD_UI_FIELDS
from .autotdp import AutoTdp, DEFAULTS as AUTO_DEFAULTS

HID_DEFAULTS = {"LegionLightMode": 0, "LegionLightColor": "#00ADEF", "LegionLightBrightness": 100, "LegionLightSpeed": 50,
                "LegionGyroMappingType": 0, "LegionGyroSensitivityX": 50, "LegionGyroSensitivityY": 50,
                "LegionGyroInvertX": False, "LegionGyroInvertY": False, "LegionGyroActivationMode": 0,
                "LegionGyroActivationButton": 0, "LegionLeftTriggerStart": 0, "LegionLeftTriggerEnd": 6,
                "LegionRightTriggerStart": 0, "LegionRightTriggerEnd": 6,
                "LegionJoystickAsMouseMode": 0, "LegionJoystickMouseSens": 50}
HID_KEYS = set(HID_DEFAULTS) | {"LegionTouchpadEnabled", "LegionTouchpadVibration", "LegionVibration", "LegionVibrationMode",
                               "LegionNintendoLayout", "LegionLeftStickDeadzone", "LegionRightStickDeadzone",
                               "LegionGyroTarget", "LegionGyroDeadzone", "Settings_LegionControllerSleepMinutes"}
HID_KEYS |= {f"LegionButton{name}" for name in hid.BUTTONS}
TDP_KEYS = {"TDP", "TDPBoostEnabled", "TDPBoostSPPT", "TDPBoostFPPT"}
LOCAL_KEYS = {"PerGameProfile", "PowerSourceProfile", "ScreenSaverEnabled", "HibernateTimeoutAC", "HibernateTimeoutDC"}
SYSTEM_ALIASES = {"System" + name: name for name in ("PowerButtonActionAC", "PowerButtonActionDC", "DisplayTimeoutAC", "DisplayTimeoutDC", "HibernateTimeoutAC", "HibernateTimeoutDC")}
PERFORMANCE_KEYS = {"FPSLimit", "FPSLimitEnabled", "StickyTDPEnabled", "StickyTDPInterval"}


@dataclass(frozen=True)
class Applied:
    value: object
    verified: bool = True
    message: str = "Read back from hardware"


class Backend:
    def __init__(self, store, demo=False):
        self.store, self.demo = store, demo
        self.capabilities = {}
        self.values = {}
        self.capabilities.update({key: True for key in LOCAL_KEYS})
        self.values.update({key: self.store.get(key, False) for key in LOCAL_KEYS})
        self.wmi = self.controller = self.power = self.display = self.amd = self.scaling = None
        self.rtss = None
        self.rtss_memory = None
        self.values.update({"OSD": self.store.get("OSD", 0), "OSDConfig": self.store.get("OSDConfig", "")})
        self.hdr = None
        self.idle = None
        self.next_idle = 0.0
        self.next_scaling = 0.0
        for key in ("HibernateTimeoutAC", "HibernateTimeoutDC"):
            self.values[key] = self.store.get(key, 0)
        self.next_sticky = self.next_rtss = 0.0
        self.auto = AutoTdp()
        self.auto_active = False
        self.next_auto = 0.0
        self.auto_game = None
        self.values.update({key: self.store.get(key, value) for key, value in AUTO_DEFAULTS.items()})
        self.values["AutoTDPEnabled"] = False
        self.values.update({"StickyTDPEnabled": False, "StickyTDPInterval": self.store.get("StickyTDPInterval", 5),
                            "FPSLimit": 0, "FPSLimitEnabled": False})

    def discover(self):
        if self.demo:
            self.capabilities = {key: True for key in HID_KEYS | set(FEATURES) | {"CPUBoost", "CPUEPP", "LegionPerformanceMode", "PanelBrightness", "Resolution", "RefreshRate", "OnScreenKeyboard"}}
            self.capabilities.update({key: True for key in TDP_KEYS | PERFORMANCE_KEYS | LOCAL_KEYS | set(AUTO_DEFAULTS) | {"OSD", "OSDConfig", "HDREnabled"}})
            from .native.scaling import DEFAULTS as LS_DEFAULTS, ACTION_KEYS as LS_ACTIONS
            self.capabilities.update({key: True for key in LS_ACTIONS | {"LosslessScalingEnabled"}})
            self.capabilities.update({"LosslessScaling"+key:True for key in LS_DEFAULTS})
            self.values.update({"LosslessScaling"+key:value for key,value in LS_DEFAULTS.items()})
            self.values.update({"LosslessScalingCurrentProfile":"Default", "LosslessScalingEnabled":False, "LosslessScalingInstalled":True, "LosslessScalingRunning":False})
            self.capabilities["AutoTDPControllerType"] = False
            self.values.update(HID_DEFAULTS)
            self.values.update({"DeviceDisplayName": "Legion Go · Preview", "LegionPerformanceMode": 2, "CPUBoost": False, "CPUEPP": 30,
                                "TDP": 15, "PanelBrightness": 70, "Resolution": "2560x1600", "RefreshRate": 144,
                                "Resolutions": ["1280x800", "1920x1200", "2560x1600"], "RefreshRates": [60, 144]})
            return self.snapshot()
        if os.name != "nt":
            self.values["DeviceDisplayName"] = "Windows hardware APIs unavailable"
            return self.snapshot()
        from .native.display import WindowsDisplay
        from .native.power import WindowsPower, BOOST, EPP, POWER_FIELDS
        from .native.wmi import LenovoWmi, query
        errors = []
        try:
            self.power = WindowsPower()
            ac = telemetry()["ACConnected"]
            for key, field in (("CPUBoost", BOOST), ("CPUEPP", EPP)):
                self.values[key] = self.power.read(field, ac)
                if key == "CPUBoost":
                    self.values[key] = bool(self.values[key])
                self.capabilities[key] = True
            for key, (field, subgroup, ac) in POWER_FIELDS.items():
                try:
                    self.values[key] = self.power.read(field, ac, subgroup)
                    self.capabilities[key] = True
                except Exception as exc:
                    errors.append(f"{key}: {exc}")
            try:
                self.values["OSPowerMode"] = self.power.get_mode()
                self.capabilities["OSPowerMode"] = True
            except Exception as exc:
                errors.append(f"OSPowerMode: {exc}")
        except Exception as exc:
            errors.append(str(exc))
        try:
            system = query("Win32_ComputerSystem", r"root\cimv2")[0]
            self.values["DeviceDisplayName"] = f"{system.get('Manufacturer', '')} {system.get('Model', '')}".strip()
            self.values["DeviceModel"] = system.get("Model", "")
        except Exception as exc:
            errors.append(str(exc))
        self.wmi = LenovoWmi()
        if self.wmi.available():
            for key in [*FEATURES, "LegionPerformanceMode"]:
                try:
                    self.values[key] = self.wmi.get(key)
                    self.capabilities[key] = key not in ("LegionCPUFanRPM", "LegionCPUCurrentTemp", "LegionFanSensorTemp")
                except Exception as exc:
                    errors.append(f"{key}: {exc}")
            try:
                self.values["LegionFanCurveData"] = self.wmi.get("LegionFanCurveData")
                self.capabilities["LegionFanCurveData"] = True
            except Exception:
                pass
        try:
            self.values["PanelBrightness"] = self.wmi.get("PanelBrightness")
            self.capabilities["PanelBrightness"] = True
        except Exception:
            pass
        if all(self.capabilities.get(key) for key in ("LegionCustomTDPSlow", "LegionCustomTDPFast", "LegionCustomTDPPeak", "LegionPerformanceMode")):
            self.capabilities.update({key: True for key in TDP_KEYS})
            self.values["TDP"] = self.values["LegionCustomTDPSlow"]
            self.capabilities.update({"StickyTDPEnabled": True, "StickyTDPInterval": True})
            self.values["StickyTDPEnabled"] = self.store.get("StickyTDPEnabled", False) and self.values.get("LegionPerformanceMode") == 255
            for key, default in (("TDPBoostEnabled", False), ("TDPBoostSPPT", 1), ("TDPBoostFPPT", 3)):
                self.values[key] = self.store.get(key, default)
        try:
            self.controller = hid.LegionHid()
            if self.controller.available():
                self.capabilities.update({key: True for key in HID_KEYS})
                self.values["DeviceDisplayName"] = "Legion Go"
                # 保存的请求值不作为已确认的设备状态。
                self.values.update({key: self.store.get(key, value) for key, value in HID_DEFAULTS.items()})
                status = self.controller.read_status()
                if status:
                    self.values.update(status)
        except Exception as exc:
            errors.append(str(exc))
        try:
            self.display = WindowsDisplay()
            self.values.update(self.display.current())
            self.values["Resolutions"] = sorted({f"{w}x{h}" for w, h, _ in self.display.modes()})
            self.values["RefreshRates"] = sorted({hz for w, h, hz in self.display.modes() if f"{w}x{h}" == self.values["Resolution"]})
            self.capabilities.update({"Resolution": True, "RefreshRate": True})
        except Exception as exc:
            errors.append(str(exc))
        try:
            from .native.hdr import Hdr
            self.hdr = Hdr()
            self.values.update(self.hdr.status())
            self.capabilities["HDREnabled"] = self.values["HDRSupported"]
        except Exception as exc:
            errors.append(f"HDR: {exc}")
        self.capabilities["OnScreenKeyboard"] = True
        try:
            from .native.adlx import Adlx
            self.amd = Adlx()
            caps, values = self.amd.discover()
            self.capabilities.update(caps)
            self.values.update(values)
        except Exception as exc:
            errors.append(f"AMD: {exc}")
        from .native.scaling import Scaling
        self.scaling = Scaling()
        try:
            caps, values = self.scaling.discover()
            self.capabilities.update(caps)
            self.values.update(values)
        except Exception as exc:
            errors.append(f"Lossless Scaling: {exc}")
        try:
            self.refresh_rtss()
        except Exception as exc:
            errors.append(f"RTSS: {exc}")
        try:
            from .native.idle import IdleMonitor
            self.idle = IdleMonitor()
            self.capabilities.update({"HibernateTimeoutAC": self.idle.available(), "HibernateTimeoutDC": self.idle.available()})
        except Exception as exc:
            self.capabilities.update({"HibernateTimeoutAC": False, "HibernateTimeoutDC": False, "ScreenSaverEnabled": False})
            errors.append(f"Idle: {exc}")
        self.values["DiscoveryErrors"] = errors
        return self.snapshot()

    def refresh_rtss(self):
        if self.rtss is None:
            from .native.rtss import Rtss
            self.rtss = Rtss()
        self.capabilities.update({"FPSLimit": False, "FPSLimitEnabled": False})
        value = self.rtss.discover()
        self.capabilities.update({"OSD": False, "OSDConfig": False})
        self.values.update({"RTSSInstalled": self.rtss.installed, "RTSSRunning": self.rtss.running})
        if value is not None:
            self.capabilities.update({"FPSLimit": True, "FPSLimitEnabled": True})
            self.values.update({"FPSLimit": value, "FPSLimitEnabled": value > 0})
            try:
                if self.rtss_memory is None:
                    from .native.rtss_memory import RtssMemory
                    self.rtss_memory = RtssMemory()
                with self.rtss_memory.mapped() as shared:
                    usable = shared.version >= 0x2000e
                self.capabilities.update({"OSD": usable, "OSDConfig": usable})
            except (OSError, ValueError):
                pass

    def maintain(self, now=None):
        """在串行工作线程检查外部进程及 TDP，避免阻塞界面或重复排队。"""
        if self.demo:
            return self.snapshot()
        now = time.monotonic() if now is None else now
        errors = []
        if self.scaling and now >= self.next_scaling:
            self.next_scaling = now + 2
            try:
                known = set(self.store.data["profiles"]) | {entry["name"] for entry in self.values.get("FrameSamples", [])}
                path = self.scaling.remember_foreground(known)
                changed = self.scaling.select_game(path)
                if changed or not self.scaling.pending:
                    caps, values = self.scaling.discover()
                    self.capabilities.update(caps)
                    self.values.update(values)
            except Exception as exc:
                self.next_scaling = now + 15
                errors.append(f"Lossless Scaling: {exc}")
        if now >= self.next_rtss:
            self.next_rtss = now + 5
            try:
                self.refresh_rtss()
            except Exception as exc:
                errors.append(str(exc))
        if not self.auto_active and self.values.get("StickyTDPEnabled") and self.supported("TDP") and now >= self.next_sticky:
            self.next_sticky = now + self.values["StickyTDPInterval"]
            try:
                mode = self.wmi.get("LegionPerformanceMode")
                self.values["LegionPerformanceMode"] = mode
                if mode != 255:
                    self.values["StickyTDPEnabled"] = False
                else:
                    keys = ("LegionCustomTDPSlow", "LegionCustomTDPFast", "LegionCustomTDPPeak")
                    actual = tuple(self.wmi.get(key) for key in keys)
                    base = self.values["TDP"]
                    expected = (base, base + (self.values.get("TDPBoostSPPT", 1) if self.values.get("TDPBoostEnabled") else 0),
                                base + (self.values.get("TDPBoostFPPT", 3) if self.values.get("TDPBoostEnabled") else 0))
                    if actual != expected:
                        # 直接重写目标值，无需原 helper 的临时降功率再升回技巧。
                        self.values.update(self.wmi.set_tdp(*expected))
                        actual = tuple(self.values[key] for key in keys)
                        if actual != expected:
                            raise OSError("Sticky TDP readback mismatch")
                    self.values["CurrentTDP"] = f"SPL:{actual[0]}W SPPT:{actual[1]}W FPPT:{actual[2]}W"
            except Exception as exc:
                self.next_sticky = now + max(15, self.values["StickyTDPInterval"])
                errors.append(str(exc))
        if self.rtss_memory and self.values.get("RTSSRunning"):
            try:
                self.values["FrameSamples"] = self.rtss_memory.samples()
                if self.values.get("OSD") and self.supported("OSD"):
                    from .osd import render
                    self.rtss_memory.publish(render(self.values["OSD"], self.values["OSDConfig"], telemetry(), self.values))
            except BlockingIOError:
                pass
            except (OSError, ValueError) as exc:
                self.values["FrameSamples"] = []
                errors.append(str(exc))
        auto_available = self.supported("TDP") and bool(self.rtss_memory) and self.values.get("RTSSRunning", False)
        self.capabilities.update({key: bool(auto_available) for key in AUTO_DEFAULTS if key != "AutoTDPControllerType"})
        try:
            if now >= self.next_auto:
                self.maintain_auto(now)
        except Exception as exc:
            self.values["AutoTDPEnabled"] = False
            self.next_auto = now + 15
            errors.append(f"Auto TDP: {exc}")
        if self.idle and now >= self.next_idle:
            self.next_idle = now + 5
            try:
                from .native.system import foreground
                from .profiles import canonical
                path = foreground(include_self=True)
                # 前台不可读时不触发休眠；避免把受保护游戏误认为桌面。
                foreground_game = not path or canonical(path) in self.store.data["profiles"] or any(canonical(entry["name"]) == canonical(path) for entry in self.values.get("FrameSamples", []))
                ac = telemetry()["ACConnected"]
                minutes = self.values.get("HibernateTimeoutAC" if ac else "HibernateTimeoutDC", 0)
                self.idle.update(ac, minutes, self.values.get("ScreenSaverEnabled", False), foreground_game)
            except Exception as exc:
                errors.append(str(exc))
        self.values["MaintenanceError"] = "; ".join(errors)
        return self.snapshot()

    def auto_power(self, base):
        fast = base + (self.values.get("TDPBoostSPPT", 1) if self.values.get("TDPBoostEnabled") else 0)
        peak = base + (self.values.get("TDPBoostFPPT", 3) if self.values.get("TDPBoostEnabled") else 0)
        actual = self.wmi.set_tdp(base, fast, peak)
        self.values.update(actual)
        self.values["CurrentTDP"] = f"SPL:{base}W SPPT:{fast}W FPPT:{peak}W"
        self.values["AutoTDPCurrentPower"] = base

    def maintain_auto(self, now):
        if not self.values.get("AutoTDPEnabled") and not self.auto_active:
            return
        from .native.system import foreground
        from .profiles import canonical
        path = foreground()
        samples = self.values.get("FrameSamples", []) if self.values.get("RTSSRunning") else []
        # 只按完整路径识别，避免把另一个同名进程的帧率用于当前游戏。
        sample = next((entry for entry in samples if path and canonical(entry["name"]) == canonical(path)), None)
        if not path or not self.values.get("AutoTDPPauseWhenUnfocused", True):
            sample = sample or next((entry for entry in samples if entry["pid"] == self.auto_game), None)
        mode = self.wmi.get("LegionPerformanceMode")
        self.values["LegionPerformanceMode"] = mode
        active = self.values.get("AutoTDPEnabled") and sample is not None and mode == 255
        if not active:
            if self.auto_active and mode == 255:
                self.auto_power(self.values["TDP"])
            self.auto_active = False
            self.auto = AutoTdp()
            self.values["AutoTDPMLStatus"] = "Paused" if self.values.get("AutoTDPEnabled") else "Off"
            return
        if sample["pid"] != self.auto_game:
            if self.auto_active:
                self.auto_power(self.values["TDP"])
            self.auto = AutoTdp()
            self.auto_game = sample["pid"]
        current = self.wmi.get("LegionCustomTDPSlow")
        self.values["AutoTDPCurrentFPS"] = round(sample["fps"])
        wanted = self.auto.decide(now, sample["fps"], current, self.values["AutoTDPTargetFPS"],
                                  self.values["AutoTDPMinTDP"], self.values["AutoTDPMaxTDP"])
        self.auto_active = True
        if wanted is not None and wanted != current:
            self.auto_power(wanted)
        self.values["AutoTDPMLStatus"] = self.auto.status

    def snapshot(self):
        from .osd import editor_values
        level = self.values.get("OSDCustomizeLevel", self.store.get("OSDCustomizeLevel", 1))
        self.values["OSDCustomizeLevel"] = level
        self.values.update(editor_values(self.values.get("OSDConfig", ""), level))
        self.capabilities.update({key: self.supported("OSDConfig") for key in (*OSD_UI_FIELDS, "OSDCustomizeLevel")})
        for alias,key in SYSTEM_ALIASES.items():
            self.capabilities[alias] = self.supported(key)
            if key in self.values:self.values[alias] = self.values[key]
        return {"capabilities": dict(self.capabilities), "values": dict(self.values), "demo": self.demo}

    def supported(self, key):
        return bool(self.capabilities.get(key))

    def validate(self, key, value):
        ranges = {"AutoTDPTargetFPS": (15, 144), "AutoTDPMinTDP": (4, 35), "AutoTDPMaxTDP": (4, 35), "OSD": (0, 3), "HibernateTimeoutAC": (0, 1440), "HibernateTimeoutDC": (0, 1440), "StickyTDPInterval": (3, 15), "FPSLimit": (0, 144), "CPUEPP": (0, 100), "PanelBrightness": (0, 100),
                  "TDP": (4, 35), "TDPBoostSPPT": (0, 10), "TDPBoostFPPT": (0, 15),
                  "PowerButtonActionAC": (0, 3), "PowerButtonActionDC": (0, 3), "OSPowerMode": (0, 2),
                  "DisplayTimeoutAC": (0, 86400), "DisplayTimeoutDC": (0, 86400),
                  "LegionCustomTDPSlow": (4, 35), "LegionCustomTDPFast": (4, 45), "LegionCustomTDPPeak": (4, 50),
                  "LegionVibration": (0, 3), "LegionVibrationMode": (1, 5), "LegionGyroTarget": (0, 3),
                  "LegionTouchpadVibration": (1, 4),
                  "LegionGyroDeadzone": (1, 100), "LegionJoystickAsMouseMode": (0, 2), "LegionJoystickMouseSens": (10, 100),
                  "LegionGyroSensitivityX": (1, 100), "LegionGyroSensitivityY": (1, 100),
                  "LegionLightMode": (0, 4), "LegionLightBrightness": (0, 100), "LegionLightSpeed": (0, 100),
                  "LegionGyroMappingType": (0, 1), "LegionGyroActivationMode": (0, 1), "LegionGyroActivationButton": (0, 8),
                  "LegionLeftStickDeadzone": (0, 50), "LegionRightStickDeadzone": (0, 50),
                  "LegionLeftTriggerStart": (0, 100), "LegionLeftTriggerEnd": (0, 100),
                  "LegionRightTriggerStart": (0, 100), "LegionRightTriggerEnd": (0, 100), "Settings_LegionControllerSleepMinutes": (0, 60)}
        if key in ("AutoTDPMinTDP", "AutoTDPMaxTDP"):
            proposed = {**self.values, key: value}
            if proposed["AutoTDPMinTDP"] > proposed["AutoTDPMaxTDP"]:
                raise ValueError("Auto TDP minimum exceeds maximum")
        if key == "OSDConfig":
            from .osd import parse
            parse(value)
        if key.startswith("LegionButton"):
            mapping = json.loads(value) if isinstance(value, str) else value
            if not isinstance(mapping, dict) or set(mapping) != {"type", "mappings"}:
                raise ValueError("Invalid button mapping")
            hid.button_mapping(key.removeprefix("LegionButton"), mapping["type"], mapping["mappings"])
        if key in ranges:
            hid.bounded(value, *ranges[key])
        if key == "LegionPerformanceMode" and value not in (1, 2, 3, 255):
            raise ValueError("Invalid Lenovo performance mode")
        boolean = {"AutoTDPEnabled", "AutoTDPPauseWhenUnfocused", "ScreenSaverEnabled", "HDREnabled", "PowerSourceProfile", "StickyTDPEnabled", "FPSLimitEnabled", "PerGameProfile", "CPUBoost", "TDPBoostEnabled", "LegionFanFullSpeed", "LegionChargeLimit", "LegionTouchpadEnabled", "LegionNintendoLayout", "LegionGyroInvertX", "LegionGyroInvertY"}
        if key in boolean and not isinstance(value, bool):
            raise ValueError(f"{key} requires a boolean")
        if key == "LegionFanCurveData":
            from .native.legion_hid import FAN_FLOORS as FLOORS
            values = [int(v) for v in value.split(",")]
            hid.fan_table(values)
            if any(v < floor for v, floor in zip(values, FLOORS)):
                raise ValueError("Fan curve is below the reference firmware minimum")

    def apply(self, key, value):
        key = SYSTEM_ALIASES.get(key, key)
        if not self.supported(key):
            raise RuntimeError(f"{key} is unavailable or has not yet been ported")
        self.validate(key, value)
        if key in ("StickyTDPEnabled", "AutoTDPEnabled") and value and self.values.get("LegionPerformanceMode") != 255:
            raise RuntimeError("Select Custom TDP mode before enabling Sticky TDP")
        if self.demo:
            if key in OSD_UI_FIELDS:
                from .osd import edit
                self.values["OSDConfig"] = edit(self.values["OSDConfig"], self.values.get("OSDCustomizeLevel", 1), key, value)
            if key == "FPSLimitEnabled":
                self.values["FPSLimit"] = 60 if value else 0
            if key == "FPSLimit":
                self.values["FPSLimitEnabled"] = value > 0
            self.values[key] = value
            if key == "LegionPerformanceMode" and value != 255:
                self.values["StickyTDPEnabled"] = False
            return Applied(value, False, "Preview only; no hardware write")
        if key == "OSDCustomizeLevel":
            if type(value) is not int or value not in (1,2,3):
                raise ValueError("Invalid OSD level")
            result = Applied(value, True, "Preference saved")
        elif key in OSD_UI_FIELDS:
            from .osd import edit
            config = edit(self.values["OSDConfig"], self.store.get("OSDCustomizeLevel", 1), key, value)
            self.apply("OSDConfig", config)
            result = Applied(value, True, "Preference saved")
        elif key in LOCAL_KEYS:
            result = Applied(value, True, "Preference saved")
        elif key in AUTO_DEFAULTS:
            if key == "AutoTDPControllerType" and value != 0:
                raise ValueError("This build supports the PID controller only")
            if key == "AutoTDPEnabled" and value and self.values.get("LegionPerformanceMode") != 255:
                raise ValueError("Select Custom TDP mode before enabling Auto TDP")
            if key == "AutoTDPEnabled" and not value and self.auto_active:
                if self.wmi.get("LegionPerformanceMode") == 255:
                    self.auto_power(self.values["TDP"])
                self.auto_active = False
            self.auto = AutoTdp()
            result = Applied(value, True, "Preference saved")
        elif key in ("OSD", "OSDConfig"):
            from .osd import render
            proposed = {**self.values, key: value}
            self.rtss_memory.publish(render(proposed["OSD"], proposed["OSDConfig"], telemetry(), proposed))
            result = Applied(value, False, "RTSS OSD published")
        elif key in ("StickyTDPEnabled", "StickyTDPInterval"):
            self.next_sticky = time.monotonic() + (value if key == "StickyTDPInterval" else self.values["StickyTDPInterval"])
            result = Applied(value, True, "Preference saved")
        elif key in ("FPSLimit", "FPSLimitEnabled"):
            target = (self.store.get("FPSLimitLast", 60) if value else 0) if key == "FPSLimitEnabled" else value
            actual = self.rtss.set(target)
            self.values.update({"FPSLimit": actual, "FPSLimitEnabled": actual > 0})
            if actual > 0:
                self.store.set("FPSLimitLast", actual)
            result = Applied(actual > 0 if key == "FPSLimitEnabled" else actual)
        elif key in TDP_KEYS:
            if self.values.get("LegionPerformanceMode") != 255:
                if key == "TDP":
                    raise RuntimeError("Select Custom TDP mode before changing power limits")
                self.values[key] = value
                self.store.set(key, value)
                return Applied(value, False, "Saved; applies in Custom TDP mode")
            proposed = {**self.values, key: value}
            base = proposed["TDP"]
            fast = base + (proposed.get("TDPBoostSPPT", 1) if proposed.get("TDPBoostEnabled", False) else 0)
            peak = base + (proposed.get("TDPBoostFPPT", 3) if proposed.get("TDPBoostEnabled", False) else 0)
            for field, v in (("LegionCustomTDPSlow", base), ("LegionCustomTDPFast", fast), ("LegionCustomTDPPeak", peak)):
                self.validate(field, v)
            self.values.update(self.wmi.set_tdp(base, fast, peak))
            self.values["LegionPerformanceMode"] = 255
            self.values["CurrentTDP"] = f"SPL:{base}W SPPT:{fast}W FPPT:{peak}W"
            result = Applied(value)
        elif key in ("CPUBoost", "CPUEPP"):
            from .native.power import BOOST, EPP
            ac = telemetry()["ACConnected"]
            field = BOOST if key == "CPUBoost" else EPP
            actual = self.power.set(field, (2 if value else 0) if key == "CPUBoost" else value, ac)
            result = Applied(bool(actual) if key == "CPUBoost" else actual)
        elif key in POWER_FIELDS:
            field, subgroup, ac = POWER_FIELDS[key]
            result = Applied(self.power.set(field, value, ac, subgroup))
        elif key == "OSPowerMode":
            result = Applied(self.power.set_mode(value))
        elif key in FEATURES or key in ("LegionPerformanceMode", "PanelBrightness", "LegionFanCurveData"):
            result = Applied(self.wmi.set(key, value))
        elif key == "HDREnabled":
            result = Applied(self.hdr.set(value))
        elif key in ("Resolution", "RefreshRate"):
            result = Applied(self.display.set(key, value))
            self.values.update(self.display.current())
            self.values["RefreshRates"] = sorted({hz for w, h, hz in self.display.modes() if f"{w}x{h}" == self.values["Resolution"]})
        elif key.startswith("AMD"):
            result = Applied(self.amd.set(key, value))
        elif key.startswith("LosslessScaling"):
            if key == "LosslessScalingSaveAndRestart":
                return Applied(True, False, self.scaling.save_and_restart())
            if key == "LosslessScalingEnabled":
                result = Applied(self.scaling.set_enabled(value), False, "Scaling hotkey sent; state follows commands from this app")
            elif key in ("LosslessScalingLaunch", "LosslessScalingBringToForeground", "LosslessScalingResetProfile", "LosslessScalingCreateProfile"):
                if key.endswith("Launch"): self.scaling.launch()
                elif key.endswith("BringToForeground"): self.scaling.bring_to_foreground()
                elif key.endswith("ResetProfile"): self.values.update(self.scaling.reset())
                else:
                    name, path = value.split("<||>",1)
                    self.scaling.create_profile(name,path)
                caps, values = self.scaling.discover()
                self.capabilities.update(caps)
                self.values.update(values)
                return Applied(False, False, "Lossless Scaling action completed")
            else:
                result = Applied(self.scaling.stage(key, value), False, "Staged; use Apply and Restart to save")
        elif key == "OnScreenKeyboard":
            from .native.system import open_keyboard
            open_keyboard()
            return Applied(True, False, "Keyboard launch requested")
        elif key in HID_KEYS:
            settings = {**HID_DEFAULTS, **{k: self.store.get(k, v) for k, v in HID_DEFAULTS.items()}, **self.values, key: value}
            commands = self.hid_commands(key, value, settings)
            readback = self.controller.send(commands, read_status=key.startswith("LegionLight") or key == "LegionTouchpadEnabled") if commands else None
            if readback:
                self.values.update(readback)
            if readback and key in readback:
                actual = readback[key]
                matches = actual.casefold() == value.casefold() if isinstance(actual, str) and isinstance(value, str) else actual == value
                if not matches:
                    raise OSError(f"HID readback mismatch: requested {value}, device reports {actual}")
                result = Applied(actual)
            else:
                result = Applied(value, False, "HID command sent; response not verified" if commands else "Saved for next light enable; lighting remains off")
        else:
            raise RuntimeError(f"No adapter for {key}")
        self.values[key] = result.value
        self.store.set(key, result.value)
        if key == "LegionPerformanceMode":
            self.values["StickyTDPEnabled"] = self.store.get("StickyTDPEnabled", False) and result.value == 255
        return result

    @staticmethod
    def hid_commands(key, value, settings):
        if key.startswith("LegionLight"):
            if key != "LegionLightMode" and settings["LegionLightMode"] == 0:
                return []
            commands = hid.rgb(settings["LegionLightMode"], settings["LegionLightColor"], settings["LegionLightBrightness"], settings["LegionLightSpeed"])
            if key == "LegionLightMode" and value != 0:
                commands = [hid.report(6, 0x70, 2, side, 1, 1) for side in (hid.LEFT, hid.RIGHT)] + commands
            return commands
        if key == "LegionTouchpadEnabled":
            return [hid.report(6, 0x6B, 2, 4, int(value), 1)]
        if key == "LegionTouchpadVibration":
            return [hid.report(0, 6, 6, 0, value)]
        if key == "LegionVibration":
            return [hid.report(6, 0x67, 2, side, value, 1) for side in (hid.LEFT, hid.RIGHT)]
        if key == "LegionVibrationMode":
            return [hid.report(0, 6, 4, 3, value)]
        if key == "LegionNintendoLayout":
            codes = [(0x12, 0x13), (0x13, 0x12), (0x14, 0x15), (0x15, 0x14)]
            return [hid.report(0, 0x12, 0x0A, 4, 1, 0x11, 1, source, 1, target if value else source) for source, target in codes]
        if key in ("LegionLeftStickDeadzone", "LegionRightStickDeadzone"):
            return [hid.deadzone(hid.LEFT if "Left" in key else hid.RIGHT, value)]
        if key.startswith(("LegionLeftTrigger", "LegionRightTrigger")):
            side = "Left" if "Left" in key else "Right"
            return [hid.trigger(hid.LEFT if side == "Left" else hid.RIGHT, settings[f"Legion{side}TriggerStart"], settings[f"Legion{side}TriggerEnd"])]
        if key == "Settings_LegionControllerSleepMinutes":
            return [hid.report(6, 0x33, 1, side, value, 1) for side in (hid.LEFT, hid.RIGHT)]
        if key in ("LegionJoystickAsMouseMode", "LegionJoystickMouseSens"):
            mode, sensitivity = settings["LegionJoystickAsMouseMode"], settings["LegionJoystickMouseSens"]
            return [hid.report(0, 0x0C, 7, side, enabled, 0, 0, sensitivity, enabled) for side, selected in ((hid.LEFT, 1), (hid.RIGHT, 2)) for enabled in [2 if mode == selected else 1]]
        if key == "LegionGyroTarget":
            return [hid.report(0, 0x0E, 2, 4, value + 1)]
        if key == "LegionGyroDeadzone":
            return [hid.report(5, 0x6A, 0x13, 4, value, 1)]
        if key.startswith("LegionGyroActivation"):
            return [hid.gyro_activation(settings["LegionGyroActivationMode"], settings["LegionGyroActivationButton"])]
        if key.startswith("LegionGyro"):
            return [hid.gyro_settings(settings["LegionGyroMappingType"], settings["LegionGyroSensitivityX"], settings["LegionGyroSensitivityY"], settings["LegionGyroInvertX"], settings["LegionGyroInvertY"])]
        if key.startswith("LegionButton"):
            mapping = json.loads(value) if isinstance(value, str) else value
            return [hid.button_mapping(key.removeprefix("LegionButton"), mapping["type"], mapping["mappings"])]
        raise ValueError(f"No HID protocol implementation for {key}")

    def close(self):
        if self.auto_active and self.wmi:
            try:
                if self.wmi.get("LegionPerformanceMode") == 255:
                    self.auto_power(self.values["TDP"])
            except Exception as exc:
                self.values["MaintenanceError"] = f"Auto TDP restore: {exc}"
            finally:
                self.auto_active = False
        if self.rtss_memory:
            self.rtss_memory.close()
        if self.amd:
            self.amd.close()
