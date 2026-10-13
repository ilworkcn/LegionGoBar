"""VIIPER 原生输入格式；坐标与按键位遵循 GoTweaks 的转发器。"""
from dataclasses import dataclass
import struct

STEAM = {'steamdeck','steam-deck','steamdeck-generic','steam-generic','legion-go','legion-go-s','legion-go-2','msi-claw','rog-ally','zotac-zone'}
SONY = {'dualshock4','dualsense','dualsenseedge'}
NINTENDO = {'switchpro','joycon-left','joycon-right','joycon-pair','ns2pro'}


@dataclass(frozen=True)
class Input:
    buttons: int = 0
    lt: int = 0
    rt: int = 0
    lx: int = 0
    ly: int = 0
    rx: int = 0
    ry: int = 0
    aux: int = 0
    touch: bool = False
    click: bool = False
    x: int = 512
    y: int = 512
    imu: tuple | None = None


def clamp(value):
    return max(-32768, min(32767, int(value)))


def mapped(buttons, pairs):
    return sum(dst for src, dst in pairs if buttons & src)


def report(kind, state, frame=0, alternate=False):
    kind = {'dualsense-edge':'dualsenseedge','switchpro2':'ns2pro'}.get(kind,kind)
    s=state; b=s.buttons; a=s.aux
    sticks=tuple(clamp(v) for v in (s.lx,s.ly,s.rx,s.ry))
    lt,rt=(max(0,min(255,int(v))) for v in (s.lt,s.rt))
    imu=tuple(clamp(v) for v in (s.imu or (0,)*6))
    gx,gy,gz,ax,ay,az=imu
    if kind=='xbox360':
        return struct.pack('<IBB4h6x',b & 0xFFFF,lt,rt,*sticks)
    if kind in SONY:
        ds4=kind=='dualshock4'; out=bytearray(31 if ds4 else 33)
        out[:4]=bytes((clamp(v)>>8)&255 for v in (s.lx,-s.ly,s.rx,-s.ry))
        buttons=mapped(b,((0x1000,0x20),(0x2000,0x40),(0x4000,0x10),(0x8000,0x80),(0x100,0x100),(0x200,0x200),(0x20,0x1000),(0x10,0x2000),(0x40,0x4000),(0x80,0x8000)))
        guide=bool(b&0x400 or a&0x40)
        if ds4:
            struct.pack_into('<H',out,4,buttons | int(guide) | (int(s.click)<<1))
            out[6]=b & 15
            offset=7
        else:
            buttons |= int(guide)<<16 | int(s.click)<<17
            if kind=='dualsenseedge': buttons |= mapped(a,((1,0x100000),(2,0x400000),(4,0x200000),(8,0x800000)))
            struct.pack_into('<I',out,4,buttons);out[8]=b & 15;offset=9
        out[offset:offset+2]=bytes((lt,rt))
        if s.touch:struct.pack_into('<HHB',out,offset+2,max(0,min(1023,s.x))*(1919 if ds4 else 1920)//1023,max(0,min(1023,s.y))*(942 if ds4 else 1080)//1023,1)
        if s.imu:
            struct.pack_into('<6h',out,offset+12,*map(clamp,(gx,-gz if alternate else gz,gy if alternate else -gy,ax*2,-az*2,ay*2)))
        return bytes(out)
    if kind in NINTENDO:
        if kind=='ns2pro':
            out=bytearray(27)
            buttons=mapped(b,((0x1000,1),(0x2000,2),(0x4000,4),(0x8000,8),(0x200,0x10),(0x10,0x40),(0x80,0x80),(2,0x100),(8,0x200),(4,0x400),(1,0x800),(0x100,0x1000),(0x20,0x4000),(0x40,0x8000),(0x400,0x10000)))
            buttons |= (0x20 if rt>128 else 0)|(0x2000 if lt>128 else 0)|(1<<19 if a&3 else 0)|(1<<18 if a&12 else 0)
            struct.pack_into('<I4H6h3B',out,0,buttons,*((v+32768)>>4 for v in sticks),ax,ay,az,gx,gy,gz,9,0,1)
            return bytes(out)
        out=bytearray(24)
        buttons=mapped(b,((0x1000,4),(0x2000,8),(0x4000,1),(0x8000,2),(0x100,0x400000),(0x200,0x40),(0x20,0x100),(0x10,0x200),(0x400,0x1000),(0x40,0x800),(0x80,0x400),(1,0x20000),(2,0x10000),(4,0x80000),(8,0x40000)))
        buttons |= (0x800000 if lt>128 else 0)|(0x80 if rt>128 else 0)
        if kind=='joycon-left': buttons |= mapped(a,((1,0x200000),(2,0x100000)))
        if kind=='joycon-right': buttons |= mapped(a,((4,0x20),(8,0x10)))
        motion=imu if alternate else {'switchpro':(gy,-gx,gz,-ay,-ax,-az),'joycon-pair':(-gy,gx,gz,-ay,-ax,-az),'joycon-left':(-gz,-gy,-gx,az,ay,-ax),'joycon-right':(gx,-gz,gy,az,ay,-ax)}[kind]
        struct.pack_into('<I4h6h',out,0,buttons,*sticks,*map(clamp,motion))
        return bytes(out)
    if kind in STEAM or kind=='gordon':
        deck=kind in STEAM; out=bytearray(64);out[:4]=bytes((1,0,9 if deck else 1,0x40 if deck else 0x3c))
        struct.pack_into('<I',out,4,frame & 0xFFFFFFFF)
        out[8]=mapped(b,((0x1000,0x80),(0x4000,0x40),(0x2000,0x20),(0x8000,0x10),(0x100,8),(0x200,4)))|(2 if lt>30 else 0)|(1 if rt>30 else 0)
        out[9]=mapped(b,((1,1),(8,2),(4,4),(2,8),(0x10,0x40 if deck else 0x10),(0x20,0x10 if deck else 0x40)))|(0x20 if b&0x400 or a&0x40 else 0)|(0x80 if a&2 else 0)
        out[10]=(0x40 if b&0x40 else 0)|(1 if a&8 else 0)|(0x10 if s.touch else 0)
        if deck:
            out[10]|=4 if s.click else 0;out[11]=4 if b&0x80 else 0
            out[13]=(2 if a&1 else 0)|(4 if a&4 else 0);out[14]=4 if a&0x80 else 0
            struct.pack_into('<2h',out,20,clamp((s.x-512)*64),clamp((512-s.y)*64))
            motion=(ax*4,ay*4,az*4,gx,gy,gz) if alternate else (ax*4,-az*4,ay*4,gx,-gz,gy)
            struct.pack_into('<6h',out,24,*map(clamp,motion))
            struct.pack_into('<2H4h',out,44,lt*32767//255,rt*32767//255,*sticks)
            struct.pack_into('<H',out,58,0x4000 if s.click else 0)
        else:
            out[10]|=(2 if a&1 else 0)|(4 if a&4 else 0);out[11:13]=bytes((lt,rt))
            struct.pack_into('<2h2H6h',out,20,*sticks[2:],lt*257,rt*257,ax,ay,az,gx,gy,gz)
            struct.pack_into('<2H2h',out,50,lt*257,rt*257,*sticks[:2])
        return bytes(out)
    raise ValueError('Unsupported VIIPER device: '+kind)


class Feedback:
    """保存两侧马达各自的截止时间，避免右侧反馈意外停止左侧。"""
    def __init__(self):
        self.motors=[0,0];self.expires=[0.,0.];self.color=None

    def read(self,kind,data,now):
        if kind in SONY and len(data)>=2:
            self.motors[:]=[data[1],data[0]];self.expires[:]=[float('inf')]*2
            if len(data)>=5:self.color=tuple(data[2:5])
        elif kind in {'xbox360','switchpro','joycon-left','joycon-right'} and len(data)>=2:
            self.motors[:]=data[:2];self.expires[:]=[float('inf')]*2
        elif kind in STEAM or kind=='gordon':
            if len(data)>=10 and data[0]==0x8f:
                duration,interval,count=struct.unpack_from('<3H',data,3);gain=struct.unpack_from('<b',data,9)[0]
                strength=(duration*255//(duration+interval)) if duration and count else 0
                if gain<0:strength >>= min(8,(-gain+3)//6)
                self._side(data[2],strength,now+max(.020,count*(duration+interval)/1e6))
            elif len(data)>=9 and data[0]==0xeb:
                self.motors[:]=[v//257 for v in struct.unpack_from('<2H',data,5)];self.expires[:]=[float('inf')]*2
            elif len(data)>=5 and data[0]==0xea:
                self._side(data[2],min(255,data[4]*64) if data[3] else 0,float('inf'))
        elif kind=='ns2pro':
            if len(data)>=10 and data[0] in (0x10,0x11):values=(max(data[3],data[5]),max(data[7],data[9]));expiry=now+.120
            elif len(data)>=32:values=(max(data[:16]),max(data[16:32]));expiry=now+.032
            else:values=(0,0);expiry=now
            for i,value in enumerate(values):
                if value:self.motors[i]=value;self.expires[i]=expiry
        return self.decay(now)

    def _side(self,side,strength,expires):
        for i in ((side,) if side in (0,1) else (0,1)):
            self.motors[i]=strength;self.expires[i]=expires

    def decay(self,now):
        for i in range(2):
            if now>=self.expires[i]:self.motors[i]=0
        return tuple(self.motors)
