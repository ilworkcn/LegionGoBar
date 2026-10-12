from __future__ import annotations

import time
import gc
import struct

from .legion_hid import fan_table

FEATURES = {"LegionCustomTDPFast": 0x0101FF00, "LegionCustomTDPSlow": 0x0102FF00,
            "LegionCustomTDPPeak": 0x0103FF00, "LegionFanFullSpeed": 0x04020000,
            "LegionChargeLimit": 0x03010001, "LegionCPUFanRPM": 0x04030001,
            "LegionCPUCurrentTemp": 0x05040000, "LegionFanSensorTemp": 0x05010000}


def call_service(namespace, operation):
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    locator = service = None
    error = None
    result = None
    try:
        locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
        service = locator.ConnectServer(".", namespace)
        service.Security_.ImpersonationLevel = 3
        result = operation(service)
    except Exception as exc:
        error = str(exc)
    finally:
        service = None
        locator = None
        # COM 代理可能形成循环引用，在 COM 仍初始化时释放。
        gc.collect()
        pythoncom.CoUninitialize()
    if error is not None:
        raise RuntimeError(error)
    return result


def query(class_name, namespace=r"root\WMI"):
    def operation(service):
        return [{p.Name: p.Value for p in item.Properties_} for item in service.ExecQuery(f"SELECT * FROM {class_name}")]
    return call_service(namespace, operation)


def invoke(class_name, method, args=None):
    def operation(service):
        objects = list(service.ExecQuery(f"SELECT * FROM {class_name}"))
        if not objects:
            raise RuntimeError(f"{class_name} is unavailable on this device")
        obj = objects[0]
        parameters = None
        if args:
            parameters = obj.Methods_.Item(method).InParameters.SpawnInstance_()
            for key, value in args.items():
                parameters.Properties_.Item(key).Value = value
        result = obj.ExecMethod_(method, parameters)
        values = {p.Name: p.Value for p in result.Properties_}
        if values.get("ReturnValue", 0) not in (0, None):
            raise OSError(f"Lenovo {method} returned {values['ReturnValue']}")
        return values
    return call_service(r"root\WMI", operation)


class LenovoWmi:
    def available(self):
        try:
            return bool(query("LENOVO_OTHER_METHOD"))
        except Exception:
            return False

    def get(self, function):
        if function == "LegionFanCurveData":
            data = bytes(invoke("LENOVO_FAN_METHOD", "Fan_Get_Table")["FanTable"])
            if len(data) < 26:
                raise RuntimeError("Truncated fan table readback")
            return ",".join(map(str, struct.unpack_from("<10H", data, 6)))
        if function == "LegionPerformanceMode":
            return int(invoke("LENOVO_GAMEZONE_DATA", "GetSmartFanMode")["Data"])
        if function == "PanelBrightness":
            return int(query("WmiMonitorBrightness")[0]["CurrentBrightness"])
        value = int(invoke("LENOVO_OTHER_METHOD", "GetFeatureValue", {"IDs": FEATURES[function]})["Value"])
        return bool(value) if function in ("LegionFanFullSpeed", "LegionChargeLimit") else value

    def set(self, function, value):
        if function == "LegionPerformanceMode":
            invoke("LENOVO_GAMEZONE_DATA", "SetSmartFanMode", {"Data": value})
        elif function == "PanelBrightness":
            invoke("WmiMonitorBrightnessMethods", "WmiSetBrightness", {"Timeout": 0, "Brightness": value})
        elif function == "LegionFanCurveData":
            values = [int(v) for v in value.split(",")]
            if self.get("LegionPerformanceMode") != 255:
                raise RuntimeError("WMI fan curve applies only in Custom performance mode")
            invoke("LENOVO_FAN_METHOD", "Fan_Set_Table", {"FanTable": list(fan_table(values))})
        else:
            invoke("LENOVO_OTHER_METHOD", "SetFeatureValue", {"IDs": FEATURES[function], "value": int(value)})
        deadline = time.monotonic() + 0.8
        while True:
            actual = self.get(function)
            if actual == value:
                return actual
            if time.monotonic() >= deadline:
                raise OSError(f"Readback mismatch: requested {value}, device reports {actual}")
            time.sleep(0.08)

    def set_tdp(self, slow, fast, peak):
        keys = ("LegionCustomTDPSlow", "LegionCustomTDPFast", "LegionCustomTDPPeak")
        previous = {key: self.get(key) for key in keys}
        previous_mode = self.get("LegionPerformanceMode")
        try:
            if previous_mode != 255:
                self.set("LegionPerformanceMode", 255)
            for key, value in zip(keys, (slow, fast, peak)):
                self.set(key, value)
        except Exception as exc:
            rollback_failures = []
            for key in keys:
                try:
                    self.set(key, previous[key])
                except Exception as rollback:
                    rollback_failures.append(f"{key}: {rollback}")
            if previous_mode != 255:
                try:
                    self.set("LegionPerformanceMode", previous_mode)
                except Exception as rollback:
                    rollback_failures.append(str(rollback))
            suffix = "; rollback failed: " + "; ".join(rollback_failures) if rollback_failures else "; previous settings restored"
            raise RuntimeError(str(exc) + suffix) from exc
        return {key: self.get(key) for key in keys}
