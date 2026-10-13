"""第一代 Legion Go 原生输入、背键、触控板和双陀螺仪报告。"""
from dataclasses import replace
import struct
import time
from .legion_hid import matching_devices
from .viiper_reports import Input,clamp,mapped


class Decoder:
    def __init__(self):
        self.previous=[[0,0,0] for _ in range(6)]
        self.merged=None

    def filter(self,index,value):
        a,b,count=self.previous[index];result=value
        if count<3 and abs(value-a)>100 and abs(value-b)>100 and abs(a-b)<30:result=int((a+b)/2);count+=1
        else:count=0
        self.previous[index]=[result,a,count]
        return result

    def parse(self,data):
        if len(data)<32 or data[:3] not in (b'\x04\x00\xa1',b'\x04\x3c\x74'):return None
        shift=0 if data[1]==0 else 2;stick=12+shift;button=16+shift;touch=24+shift;base=32+shift
        b0,b1,b2=data[button:button+3]
        buttons=mapped(b0,((0x20,0x40),(0x10,0x80),(8,1),(4,2),(2,4),(1,8)))
        buttons|=mapped(b1,((0x80,0x1000),(0x40,0x2000),(0x20,0x4000),(0x10,0x8000),(8,0x100),(2,0x200)))
        buttons|=mapped(b2,((2,0x20),(1,0x10)))
        aux=mapped(b0,((0x80,0x40),(0x40,0x80)))|mapped(b2,((0x80,1),(0x40,2),(0x20,4),(0x10,0x10),(4,8),(8,0x20)))
        def axis(raw,invert):
            value=(raw-128)/(127 if raw>128 else 128)
            return clamp(round(value*(-32767 if invert else 32767)))
        xr,xa,yr,ya=data[touch:touch+4];active=not ((xa|ya)&0xfc) and bool(xr|xa|yr|ya)
        state=Input(buttons,data[20+shift],data[21+shift],*(axis(value,i%2) for i,value in enumerate(data[stick:stick+4])),aux,active,bool(data[19+shift]&0x80),((xa&3)<<8)|xr,((ya&3)<<8)|yr)
        motion=[]
        for side in range(2):
            start=base+side*13
            if len(data)>=start+13 and any(data[start:start+13]):
                read=lambda offset:struct.unpack_from('>h' if shift else '<h',data,start+offset)[0]
                raw=[read(i) for i in ((7,11,9) if side==0 else (9,11,7))]
                gyro=[self.filter(side*3+i,value) for i,value in enumerate(raw)]
                if side==0:gyro[0]*=-1;gyro[1]*=-1
                accel=[read(i) for i in ((1,5,3) if side==0 else (3,5,1))]
                motion.append(tuple(gyro[i]*2000/32768*16 for i in range(3))+tuple(accel))
            else:
                offset=28+side*2
                motion.append(((data[offset+1]-128)*250,(data[offset]-128)*250,0,0,0,0))
        return state,motion

    def select(self,motion,source,kind):
        if source=='None':return None
        left,right=motion
        corrected=tuple(value*sign for value,sign in zip(right,(-1,-1,1,1,1,-1)))
        if source=='Left':result=left
        elif source=='Right':result=right if kind=='joycon-right' else corrected
        else:
            result=[]
            for i,(l,r) in enumerate(zip(left,corrected)):
                if i<3 and self.merged is not None and abs(l-r)>60*16:result.append(l if abs(l-self.merged[i])<=abs(r-self.merged[i]) else r)
                else:result.append((l+r)*.5)
            self.merged=result
        return tuple(clamp(round(v)) for v in result)


class LegionInput:
    def __init__(self):
        import hid
        devices=matching_devices(hid.enumerate())
        if not devices:raise RuntimeError('Legion Go native controller is unavailable')
        self.device=hid.device();self.device.open_path(devices[0]['path']);self.device.set_nonblocking(True)
        self.decoder=Decoder();self.latest=None;self.timestamp=time.monotonic();self.heartbeat=0
        try:
            self.write(5,0,1,4)
            for mode,value in ((2,1),(7,2)):
                for side in (3,4):self.write(5,6,0x6a,mode,side,value,1)
            self.write(5,0,4,0x11,0,2)
            # 保持 XInput 和厂商输入流共存，退出后实体手柄仍可使用。
            for side in (0,3,4):self.write(5,0,4,0x0f,side,1)
            for side in (3,4):self.write(5,0,4,0x10,side,1)
        except Exception:self.close();raise

    def write(self,*values):
        if self.device.write(bytes(values).ljust(64,b'\0'))!=64:raise OSError('Controller command was not completely written')

    def read(self,source,kind,now):
        if now>=self.heartbeat:self.write(5,0,1,4);self.heartbeat=now+3
        for _ in range(64):
            data=bytes(self.device.read(64))
            if not data:break
            parsed=self.decoder.parse(data)
            if parsed:self.latest=parsed;self.timestamp=now
        if now-self.timestamp>2:raise RuntimeError('Legion Go native input timed out')
        if not self.latest:return Input()
        state,motion=self.latest
        if now-self.timestamp>.2:return Input()
        return replace(state,imu=self.decoder.select(motion,source,kind))

    def close(self):
        if self.device:self.device.close();self.device=None
