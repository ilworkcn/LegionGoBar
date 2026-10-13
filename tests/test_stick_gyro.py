import math
import os
import pytest
from legiongobar.native.stick_gyro import StickGyro,DEFAULTS,axis,curve,merge,pressed,validate
from legiongobar.native.viiper_reports import Input


class Fusion:
    def reset(self):pass
    def update(self,imu,dt):return tuple(v/16 for v in imu[:3])
    def project(self,world=False):return (4,5) if world else (2,3)


def options(**settings):
    values={**DEFAULTS,'ViiperStickGyroEnabled':True,'ControllerEmulationStickGyroAntiDeadzone':0,'ControllerEmulationStickGyroAntiDeadzoneThreshold':0,'ControllerEmulationStickGyroSmoothing':0}
    values.update({'ControllerEmulation'+key:value for key,value in settings.items()})
    return values


def test_gyro_axes_conversions_and_physical_merge():
    imu=(16,32,48,0,4096,0)
    for conversion,expected in enumerate(((-2000,1000),(-3000,1000),(-2500,1000),(-2000,3000),(-4000,5000))):
        output=StickGyro(Fusion()).apply(Input(),imu,1,options(StickConversion=conversion))
        assert (output.rx,output.ry)==expected
    output=StickGyro(Fusion()).apply(Input(lx=10,ly=20),imu,1,options(StickSelect=0,StickOrientationV2=1,StickInvertY=True))
    assert (output.lx,output.ly)==(3010,-980)
    assert math.hypot(*merge(30000,30000,10000,10000))<=32767


def test_gyro_activation_toggle_and_touch_holdoff():
    processor=StickGyro(Fusion());imu=(0,16,0,0,4096,0);cfg=options(GyroActivationMode=2)
    assert processor.apply(Input(),imu,0,cfg).rx==0
    assert processor.apply(Input(rt=31),imu,.004,cfg).rx==-1000
    assert processor.apply(Input(rt=31),imu,.008,cfg).rx==-1000
    processor.apply(Input(),imu,.012,cfg)
    assert processor.apply(Input(rt=31),imu,.016,cfg).rx==0
    cfg=options(StickGyroTouchDeactivateEnabled=True)
    assert processor.apply(Input(rx=10000),imu,1,cfg).rx==10000
    assert processor.apply(Input(),imu,1.1,cfg).rx==0
    assert processor.apply(Input(),imu,1.3,cfg).rx==-1000
    assert pressed(Input(aux=8),17) and pressed(Input(aux=4),22)


def test_gyro_curve_noise_gate_and_validation():
    assert curve(10,0)==1 and curve(10,1)==.4
    assert curve(124*48,2)==1.7
    assert axis(.1,1000,0,0,100,0,.3)==0
    assert axis(.3,1000,0,0,100,10,.3)==3546
    for key,value in [('ControllerEmulationStickSensitivityV2',401),('ViiperStickGyroEnabled',1),('ViiperGyroBias',[math.nan,0,0,1])]:
        with pytest.raises(ValueError):validate(key,value)


def test_native_motion_bias_survives_orientation_reset():
    if os.name!='nt':pytest.skip('Windows native fusion library')
    from legiongobar.native.motion import Motion
    motion=Motion([1,2,3,10])
    try:
        assert motion.vector('GetCalibrationOffset')==pytest.approx((1,2,3))
        motion.reset()
        assert motion.vector('GetCalibrationOffset')==pytest.approx((1,2,3))
        gyro=motion.update((32,64,96,0,4096,0),.004)
        assert gyro==pytest.approx((1,2,3))
        assert all(math.isfinite(value) for value in motion.project())
    finally:motion.close()
