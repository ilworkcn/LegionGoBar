"""Windows 活动显示路径的 HDR 状态读写；结构布局来自上游 User32 与 Windows SDK。"""
import ctypes as C

U32=C.c_uint32
I32=C.c_int32


class Luid(C.Structure):
    _fields_=[('low',U32),('high',I32)]


class Source(C.Structure):
    _fields_=[('adapter',Luid),('id',U32),('mode',U32),('status',U32)]


class Target(C.Structure):
    _fields_=[('adapter',Luid),('id',U32),('mode',U32),('technology',U32),('rotation',U32),
              ('scaling',U32),('numerator',U32),('denominator',U32),('ordering',U32),
              ('available',I32),('status',U32)]


class DisplayPath(C.Structure):
    _fields_=[('source',Source),('target',Target),('flags',U32)]


class Header(C.Structure):
    _fields_=[('type',U32),('size',U32),('adapter',Luid),('id',U32)]


class ColorInfo(C.Structure):
    _fields_=[('header',Header),('flags',U32),('encoding',U32),('bits',U32)]


class ColorState(C.Structure):
    _fields_=[('header',Header),('enabled',U32)]


class Hdr:
    def __init__(self, api=None):
        self.api=api or C.WinDLL('user32',use_last_error=True)
        if api is None:
            self.api.GetDisplayConfigBufferSizes.argtypes=[U32,C.POINTER(U32),C.POINTER(U32)]
            self.api.QueryDisplayConfig.argtypes=[U32,C.POINTER(U32),C.POINTER(DisplayPath),C.POINTER(U32),C.c_void_p,C.c_void_p]
            self.api.DisplayConfigGetDeviceInfo.argtypes=[C.c_void_p]
            self.api.DisplayConfigSetDeviceInfo.argtypes=[C.c_void_p]
            for name in ('GetDisplayConfigBufferSizes','QueryDisplayConfig','DisplayConfigGetDeviceInfo','DisplayConfigSetDeviceInfo'):
                getattr(self.api,name).restype=I32

    @staticmethod
    def check(code):
        if code:raise OSError(code,'Windows display configuration call failed')

    def target(self):
        # 插拔显示器会使两次查询间的长度改变，只针对缓冲区不足重试。
        for _ in range(3):
            paths,modes=U32(),U32()
            self.check(self.api.GetDisplayConfigBufferSizes(2,C.byref(paths),C.byref(modes)))
            if paths.value>128 or modes.value>4096:raise OSError('Invalid display configuration size')
            items=(DisplayPath*paths.value)()
            buffer=(C.c_uint64*(8*modes.value))()
            code=self.api.QueryDisplayConfig(2,C.byref(paths),items,C.byref(modes),buffer,None)
            if code==122:continue
            self.check(code)
            if not paths.value:raise OSError('No active display')
            # 掌机优先使用内屏；外接显示环境使用第一条活动路径。
            return next((p.target for p in items[:paths.value] if p.target.technology==0x80000000),items[0].target)
        raise OSError('Display topology keeps changing')

    def status(self,target=None):
        target=target or self.target()
        info=ColorInfo(Header(9,C.sizeof(ColorInfo),target.adapter,target.id))
        self.check(self.api.DisplayConfigGetDeviceInfo(C.byref(info)))
        return {'HDRSupported':bool(info.flags&1) and not bool(info.flags&8),'HDREnabled':bool(info.flags&2)}

    def write(self,target,value):
        packet=ColorState(Header(10,C.sizeof(ColorState),target.adapter,target.id),int(value))
        self.check(self.api.DisplayConfigSetDeviceInfo(C.byref(packet)))

    def set(self,value):
        if type(value) is not bool:raise ValueError('HDR requires a boolean')
        target=self.target()
        before=self.status(target)
        if not before['HDRSupported']:raise OSError('HDR is unavailable on this display')
        if before['HDREnabled']==value:return value
        try:
            self.write(target,value)
            if self.status(target)['HDREnabled']!=value:raise OSError('HDR readback mismatch')
        except Exception as error:
            try:
                self.write(target,before['HDREnabled'])
                if self.status(target)['HDREnabled']!=before['HDREnabled']:raise OSError('HDR restore readback mismatch')
            except Exception as restore:
                raise OSError(f'{error}; restore failed: {restore}') from error
            raise
        return value
