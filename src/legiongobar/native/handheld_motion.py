"""通过 Windows 原生传感器 API 读取机身 IMU，不依赖 Xbox。"""
import time
from .viiper_reports import clamp


class HandheldMotion:
    def __init__(self):
        import winrt.runtime as runtime
        from winrt.windows.devices.sensors import Gyrometer,Accelerometer
        self.runtime=runtime;self.sensors=[];self.last=None;self.fresh=time.monotonic();self.closed=False
        runtime.init_apartment(runtime.ApartmentType.MULTI_THREADED)
        try:
            self.gyro=Gyrometer.get_default();self.accel=Accelerometer.get_default()
            if self.gyro is None:raise RuntimeError('Windows did not detect a handheld gyrometer')
            for sensor in (self.gyro,self.accel):
                if sensor is None:continue
                previous=sensor.report_interval;requested=max(4,sensor.minimum_report_interval)
                sensor.report_interval=requested
                self.sensors.append((sensor,previous,requested))
        except Exception:self.close();raise

    def read(self,now):
        gyro=self.gyro.get_current_reading()
        if gyro is None:
            if now-self.fresh>2:raise RuntimeError('Handheld motion sensor timed out')
            return None
        if gyro.timestamp!=self.last:self.last=gyro.timestamp;self.fresh=now
        if now-self.fresh>2:raise RuntimeError('Handheld motion sensor timed out')
        if now-self.fresh>.2:return None
        accel=self.accel.get_current_reading() if self.accel else None
        values=[gyro.angular_velocity_x*16,gyro.angular_velocity_y*16,gyro.angular_velocity_z*16]
        values += [getattr(accel,'acceleration_'+axis)*4096 for axis in 'xyz'] if accel else [0,0,0]
        return tuple(clamp(round(value)) for value in values)

    def close(self):
        if self.closed:return
        self.closed=True
        try:
            for sensor,previous,requested in self.sensors:
                try:
                    if sensor.report_interval==requested:sensor.report_interval=previous
                except OSError:pass
            self.sensors.clear()
            self.gyro=self.accel=None
        finally:self.runtime.uninit_apartment()
