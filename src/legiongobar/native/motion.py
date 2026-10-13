"""原版 GamepadMotion 原生传感器融合接口。"""
import ctypes as C
from pathlib import Path


class Motion:
    def __init__(self,bias=None):
        self.bias=bias
        self.dll=C.CDLL(str(Path(__file__).resolve().parents[1]/'assets/native/GamepadMotion.dll'))
        pointer=C.c_void_p;fp=C.POINTER(C.c_float)
        signatures={'CreateGamepadMotion':([],pointer),'DeleteGamepadMotion':([pointer],None),
            'ResetGamepadMotion':([pointer],None),'ProcessMotion':([pointer]+[C.c_float]*7,None),
            'SetCalibrationMode':([pointer,C.c_int],None),'SetCalibrationOffset':([pointer]+[C.c_float]*3+[C.c_int],None),
            'GetCalibrationOffset':([pointer,fp,fp,fp],None),'GetCalibratedGyro':([pointer,fp,fp,fp],None),
            'GetPlayerSpaceGyro':([pointer,fp,fp,C.c_float],None),'GetWorldSpaceGyro':([pointer,fp,fp,C.c_float],None),
            'ResetContinuousCalibration':([pointer],None),'GetAutoCalibrationConfidence':([pointer],C.c_float)}
        for name,(args,result) in signatures.items():
            fn=getattr(self.dll,name);fn.argtypes=args;fn.restype=result
        self.handle=self.dll.CreateGamepadMotion()
        if not self.handle:raise RuntimeError('GamepadMotion allocation failed')
        self.dll.SetCalibrationMode(self.handle,3)
        if bias:self.set_bias(bias)

    def set_bias(self,bias):
        self.bias=list(bias)
        self.dll.SetCalibrationOffset(self.handle,*bias[:3],int(bias[3]))
        self.dll.SetCalibrationMode(self.handle,0)

    def vector(self,name):
        values=[C.c_float() for _ in range(3)]
        getattr(self.dll,name)(self.handle,*(C.byref(value) for value in values))
        return tuple(value.value for value in values)

    def update(self,imu,dt):
        self.dll.ProcessMotion(self.handle,*(v/16 for v in imu[:3]),*(v/4096 for v in imu[3:]),max(.001,min(.1,dt)))
        return self.vector('GetCalibratedGyro')

    def project(self,world=False):
        pitch,yaw=C.c_float(),C.c_float()
        getattr(self.dll,'GetWorldSpaceGyro' if world else 'GetPlayerSpaceGyro')(self.handle,C.byref(pitch),C.byref(yaw),.125 if world else 1.41)
        return -yaw.value,pitch.value

    def reset(self):
        self.dll.ResetGamepadMotion(self.handle)
        if self.bias:self.set_bias(self.bias)
    def close(self):
        if self.handle:self.dll.DeleteGamepadMotion(self.handle);self.handle=None
