"""直接通过 ctypes 调用上游 ADLX C ABI，原生接口由同一基准中的头文件确定。"""
from __future__ import annotations

import ctypes as C
from importlib.resources import files

FEATURES = {
    "AMDRadeonSuperResolution": ("RadeonSuperResolution", "RadeonSuperResolution", False),
    "AMDRadeonAntiLag": ("AntiLag", "AntiLag", True),
    "AMDRadeonBoost": ("Boost", "Boost", True),
    "AMDRadeonChill": ("Chill", "Chill", True),
    "AMDImageSharpening": ("ImageSharpening", "ImageSharpening", True),
}
COLOR_FIELDS = {"AMDDisplay" + name: name for name in ("Brightness", "Contrast", "Saturation", "Temperature")}

FIELDS = {
    "AMDRadeonBoostResolution": ("AMDRadeonBoost", "Resolution"),
    "AMDRadeonSuperResolutionSharpness": ("AMDRadeonSuperResolution", "Sharpness"),
    "AMDImageSharpeningSharpness": ("AMDImageSharpening", "Sharpness"),
    "AMDRadeonChillMinFPS": ("AMDRadeonChill", "MinFPS"),
    "AMDRadeonChillMaxFPS": ("AMDRadeonChill", "MaxFPS"),
    "AMDFluidMotionFrameAlgorithm": ("AMDFluidMotionFrameV1", "Algorithm"),
    "AMDFluidMotionFrameSearchMode": ("AMDFluidMotionFrameV1", "SearchMode"),
    "AMDFluidMotionFramePerformanceMode": ("AMDFluidMotionFrameV1", "PerformanceMode"),
    "AMDFluidMotionFrameFastMotionResponse": ("AMDFluidMotionFrameV1", "FastMotionResponse"),
}


class Adlx:
    def __init__(self, library=None):
        path = library or files("legiongobar").joinpath("assets/native/ADLXCSharpBind.dll")
        self.dll = C.CDLL(str(path))
        self.helper = None
        self.interfaces = []
        self.features = {}
        self.color = None
        self.monitor = self.gpu = None
        self.color_ranges = {}
        self.field_ranges = {}

    def call(self, name, args, types, result=C.c_int):
        function = getattr(self.dll, f"CSharp_{name}")
        function.argtypes = types
        function.restype = result
        return function(*args)

    @staticmethod
    def check(result):
        if result != 0:
            raise RuntimeError(f"ADLX status {result}")

    def out_pointer(self, name, *args, types=None):
        result = C.c_void_p()
        self.check(self.call(name, [*args, C.byref(result)], (types or [C.c_void_p] * len(args)) + [C.POINTER(C.c_void_p)]))
        if not result.value:
            raise RuntimeError(f"{name} returned a null interface")
        self.interfaces.append(result)
        return result

    def query_interface(self, pointer, interface):
        iid = self.call(interface + "_IID", [], [], C.c_void_p)
        return self.out_pointer("IADLXInterface_QueryInterface", pointer, iid)

    def read(self, prefix, method, boolean=False):
        pointer, interface = self.features[prefix]
        output = C.c_bool() if boolean else C.c_int()
        self.check(self.call(f"IADLX3D{interface}_{method}", [pointer, C.byref(output)], [C.c_void_p, C.POINTER(type(output))]))
        return output.value

    def discover(self):
        self.helper = self.call("new_ADLXHelper", [], [], C.c_void_p)
        if not self.helper:
            raise RuntimeError("Could not construct ADLX helper")
        try:
            self.check(self.call("ADLXHelper_Initialize", [self.helper], [C.c_void_p]))
            system = self.call("ADLXHelper_GetSystemServices", [self.helper], [C.c_void_p], C.c_void_p)
            if not system:
                raise RuntimeError("ADLX system services unavailable")
            services = self.out_pointer("IADLXSystem_Get3DSettingsServices", system)
            gpu_list = self.out_pointer("IADLXSystem_GetGPUs", system)
            gpu = self.out_pointer("IADLXGPUList_At", gpu_list, 0, types=[C.c_void_p, C.c_uint])
            self.gpu = gpu
            try:
                self.monitor = self.out_pointer("IADLXSystem_GetPerformanceMonitoringServices",system)
            except (RuntimeError,AttributeError):
                self.monitor = None
            capabilities, values = {}, {}
            for prefix, (interface, getter, needs_gpu) in FEATURES.items():
                try:
                    args = [services, gpu] if needs_gpu else [services]
                    pointer = self.out_pointer(f"IADLX3DSettingsServices_Get{getter}", *args)
                    self.features[prefix] = pointer, interface
                    supported = self.read(prefix, "IsSupported", True)
                    values[prefix + "Supported"] = supported
                    if supported:
                        capabilities[prefix + "Enabled"] = True
                        values[prefix + "Enabled"] = self.read(prefix, "IsEnabled", True)
                except (RuntimeError, AttributeError):
                    values[prefix + "Supported"] = False
            try:
                extended = self.query_interface(services, "IADLX3DSettingsServices1")
                pointer = self.out_pointer("IADLX3DSettingsServices1_GetAMDFluidMotionFrames", extended)
                self.features["AMDFluidMotionFrame"] = pointer, "AMDFluidMotionFrames"
                supported = self.read("AMDFluidMotionFrame", "IsSupported", True)
                values["AMDFluidMotionFrameSupported"] = supported
                if supported:
                    capabilities["AMDFluidMotionFrameEnabled"] = True
                    values["AMDFluidMotionFrameEnabled"] = self.read("AMDFluidMotionFrame", "IsEnabled", True)
                    try:
                        v1 = self.query_interface(pointer, "IADLX3DAMDFluidMotionFrames1")
                        self.features["AMDFluidMotionFrameV1"] = v1, "AMDFluidMotionFrames1"
                        values["AMDFluidMotionFrameV1Supported"] = True
                    except (RuntimeError, AttributeError):
                        pass
            except (RuntimeError, AttributeError):
                values["AMDFluidMotionFrameSupported"] = False
            for key, (prefix, field) in FIELDS.items():
                if capabilities.get(prefix + "Enabled") or (prefix == "AMDFluidMotionFrameV1" and values.get("AMDFluidMotionFrameV1Supported")):
                    try:
                        values[key] = self.read(prefix, "Get" + field)
                        if key == "AMDRadeonBoostResolution":
                            pointer = self.call("new_ADLX_IntRange", [], [], C.c_void_p)
                            if not pointer: raise RuntimeError("ADLX range allocation failed")
                            try:
                                self.check(self.call("IADLX3DBoost_GetResolutionRange", [self.features[prefix][0],pointer], [C.c_void_p,C.c_void_p]))
                                limits = tuple(self.call("ADLX_IntRange_"+part+"_get",[pointer],[C.c_void_p]) for part in ("minValue","maxValue","step"))
                                self.field_ranges[key] = values[key+"Range"] = limits
                            finally:
                                self.call("delete_ADLX_IntRange",[pointer],[C.c_void_p],None)
                        capabilities[key] = True
                    except (RuntimeError, AttributeError):
                        pass
            try:
                displays = self.out_pointer("IADLXSystem_GetDisplaysServices", system)
                display_list = self.out_pointer("IADLXDisplayServices_GetDisplays", displays)
                count = self.call("IADLXList_Size", [display_list], [C.c_void_p], C.c_uint)
                for index in range(count):
                    display = self.out_pointer("IADLXDisplayList_At", display_list, index, types=[C.c_void_p, C.c_uint])
                    try:
                        color = self.out_pointer("IADLXDisplayServices_GetCustomColor", displays, display)
                        found = {}
                        for key, field in COLOR_FIELDS.items():
                            if self.color_read(color, "Is" + field + "Supported", True):
                                found[key] = self.color_read(color, "Get" + field)
                        if found:
                            self.color = color
                            for key, value in found.items():
                                self.color_ranges[key] = self.color_range(COLOR_FIELDS[key])
                                capabilities[key], values[key], values[key + "Supported"] = True, value, True
                                values[key + "Range"] = self.color_ranges[key]
                            break
                    except (RuntimeError, AttributeError):
                        continue
            except (RuntimeError, AttributeError):
                pass
            return capabilities, values
        except Exception:
            self.close()
            raise

    def color_read(self, pointer, method, boolean=False):
        output = C.c_bool() if boolean else C.c_int()
        self.check(self.call("IADLXDisplayCustomColor_" + method, [pointer, C.byref(output)], [C.c_void_p, C.POINTER(type(output))]))
        return output.value

    def color_range(self, field):
        pointer = self.call("new_ADLX_IntRange", [], [], C.c_void_p)
        if not pointer:
            raise RuntimeError("ADLX range allocation failed")
        try:
            self.check(self.call("IADLXDisplayCustomColor_Get" + field + "Range", [self.color, pointer], [C.c_void_p, C.c_void_p]))
            return tuple(self.call("ADLX_IntRange_" + part + "_get", [pointer], [C.c_void_p]) for part in ("minValue", "maxValue", "step"))
        finally:
            self.call("delete_ADLX_IntRange", [pointer], [C.c_void_p], None)

    def set_color(self, key, value):
        if type(value) is not int:
            raise ValueError("AMD color setting requires an integer")
        low, high, step = self.color_ranges[key]
        if not low <= value <= high or (step > 0 and (value-low) % step):
            raise ValueError("AMD color value is outside the driver range")
        field = COLOR_FIELDS[key]
        previous = self.color_read(self.color, "Get" + field)
        def write(target):
            self.check(self.call("IADLXDisplayCustomColor_Set" + field, [self.color, target], [C.c_void_p, C.c_int]))
        try:
            write(value)
            actual = self.color_read(self.color, "Get" + field)
            if actual != value:
                raise RuntimeError("AMD color readback mismatch")
        except Exception as error:
            try:
                write(previous)
                if self.color_read(self.color, "Get" + field) != previous:
                    raise RuntimeError("AMD color restore readback mismatch")
            except Exception as restore:
                raise RuntimeError(f"{error}; restore failed: {restore}") from error
            raise
        return actual

    def set(self, key, value):
        if key in COLOR_FIELDS:
            return self.set_color(key, value)
        if key.endswith("Enabled"):
            if not isinstance(value, bool):
                raise ValueError("AMD enable flag requires a boolean")
            prefix, field, boolean = key.removesuffix("Enabled"), "Enabled", True
        else:
            prefix, field = FIELDS[key]
            boolean = False
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("AMD setting requires an integer")
            if field == "Sharpness" and not 0 <= value <= 100:
                raise ValueError("Sharpness must be 0..100")
            if field.endswith("FPS") and not 30 <= value <= 300:
                raise ValueError("Chill frame limit must be 30..300")
        if key == "AMDRadeonBoostResolution":
            low, high, step = self.field_ranges[key]
            if not low <= value <= high or (step > 0 and (value-low) % step):
                raise ValueError("Radeon Boost value is outside the driver range")
        pointer, interface = self.features[prefix]
        method = "IsEnabled" if boolean else "Get" + field
        previous = self.read(prefix, method, boolean)
        def write(target):
            self.check(self.call(f"IADLX3D{interface}_Set{field}", [pointer,target], [C.c_void_p,C.c_int]))
        try:
            write(value)
            actual = self.read(prefix, method, boolean)
            if actual != value:
                raise RuntimeError(f"AMD readback mismatch: {actual} != {value}")
        except Exception as error:
            try:
                write(previous)
                if self.read(prefix, method, boolean) != previous:
                    raise RuntimeError("AMD restore readback mismatch")
            except Exception as restore:
                raise RuntimeError(f"{error}; restore failed: {restore}") from error
            raise
        return actual

    def metrics(self):
        if not self.monitor or not self.gpu:return {}
        pointer = C.c_void_p()
        self.check(self.call("IADLXPerformanceMonitoringServices_GetCurrentGPUMetrics",
                            [self.monitor,self.gpu,C.byref(pointer)], [C.c_void_p,C.c_void_p,C.POINTER(C.c_void_p)]))
        if not pointer.value:raise RuntimeError("ADLX metrics returned null")
        values = {}
        try:
            for key,field,kind in (("GPUUsage","GPUUsage",C.c_double),("GPUClock","GPUClockSpeed",C.c_int),
                                   ("GPUTemperature","GPUTemperature",C.c_double),("GPUPower","GPUPower",C.c_double),
                                   ("VRAMUsage","GPUVRAM",C.c_int),("VRAMClock","GPUVRAMClockSpeed",C.c_int)):
                value = kind()
                result = self.call("IADLXGPUMetrics_"+field,[pointer,C.byref(value)],[C.c_void_p,C.POINTER(kind)])
                if result == 0:
                    import math
                    if math.isfinite(value.value) and value.value>=0:values[key]=round(value.value,1)
            return values
        finally:
            # 每次采样单独释放接口，不能塞进生命周期列表造成持续增长。
            self.call("IADLXInterface_Release",[pointer],[C.c_void_p])

    def close(self):
        for pointer in reversed(self.interfaces):
            self.call("IADLXInterface_Release", [pointer], [C.c_void_p])
        self.interfaces.clear()
        if self.helper:
            self.call("ADLXHelper_Terminate", [self.helper], [C.c_void_p])
            self.call("delete_ADLXHelper", [self.helper], [C.c_void_p], None)
            self.helper = None
