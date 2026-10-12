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
FIELDS = {
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
                        capabilities[key] = True
                    except (RuntimeError, AttributeError):
                        pass
            return capabilities, values
        except Exception:
            self.close()
            raise

    def set(self, key, value):
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
        pointer, interface = self.features[prefix]
        self.check(self.call(f"IADLX3D{interface}_Set{field}", [pointer, value], [C.c_void_p, C.c_int]))
        actual = self.read(prefix, "IsEnabled" if boolean else "Get" + field, boolean)
        if actual != value:
            raise RuntimeError(f"AMD readback mismatch: {actual} != {value}")
        return actual

    def close(self):
        for pointer in reversed(self.interfaces):
            self.call("IADLXInterface_Release", [pointer], [C.c_void_p])
        self.interfaces.clear()
        if self.helper:
            self.call("ADLXHelper_Terminate", [self.helper], [C.c_void_p])
            self.call("delete_ADLXHelper", [self.helper], [C.c_void_p], None)
            self.helper = None
