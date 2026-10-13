"""虚拟手柄的前台唤起、灯效反馈和成对 Joy-Con 运动数据。"""
from dataclasses import replace
import struct
from .viiper_reports import clamp


class Guide:
    def __init__(self):self.pressed=False

    def apply(self,state,mode):
        pressed=bool(state.buttons&0x400)
        # 沿用导入配置中的 GameBar 键值，实际唤起独立 LegionGoBar 窗口。
        wake=mode=='GameBar' and pressed and not self.pressed
        self.pressed=pressed
        return (replace(state,buttons=state.buttons&~0x400) if mode=='GameBar' else state),wake


class Lightbar:
    def __init__(self):self.last=None;self.next_write=0.;self.changed=False

    def update(self,color,now,write,settings):
        if color is None or color==self.last or now<self.next_write:return
        if self.last is None and color==(0,0,0):self.last=color;return
        from .legion_hid import rgb
        for packet in rgb(1,'#'+bytes(color).hex(),settings.get('LegionLightBrightness',100),50):write(packet)
        self.last=color;self.next_write=now+.125;self.changed=True

    def restore(self,write,settings):
        if not self.changed:return
        from .legion_hid import rgb
        for packet in rgb(settings.get('LegionLightMode',1),settings.get('LegionLightColor','#00ADEF'),
                          settings.get('LegionLightBrightness',100),settings.get('LegionLightSpeed',50)):write(packet)
        self.changed=False;self.last=None


def pair_motion(packet,motion,right=False):
    gx,gy,gz,ax,ay,az=motion
    if right:gx,gz,ax,az=-gx,-gz,-ax,-az
    result=bytearray(packet)
    struct.pack_into('<6h',result,12,*map(clamp,(gz,gx,gy,az,ax,ay)))
    return bytes(result)
