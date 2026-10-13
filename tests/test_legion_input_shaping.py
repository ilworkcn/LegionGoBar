import struct
import pytest
from legiongobar.native.legion_input import Decoder
from legiongobar.native.viiper_reports import Input
from legiongobar.native.stick_shaping import parse,serialize,edit,values,transform,stick,trigger,defaults


@pytest.mark.parametrize('shift,endian',[(0,'<'),(2,'>')])
def test_legion_report_formats_have_matching_axes_and_buttons(shift,endian):
    data=bytearray(64);data[:3]=b'\x04\x00\xa1' if not shift else b'\x04\x3c\x74'
    data[12+shift:16+shift]=bytes((128,0,255,128))
    data[16+shift:19+shift]=bytes((0x88,0x80,0xc0))
    data[20+shift:22+shift]=bytes((255,9))
    data[24+shift:28+shift]=bytes((255,3,0,2))
    struct.pack_into(endian+'6h',data,33+shift,10,20,30,40,50,60)
    data[32+shift]=1
    state,motion=Decoder().parse(bytes(data))
    assert (state.buttons,state.aux)==(0x1001,0x43)
    assert (state.lx,state.ly,state.rx,state.ry)==(0,32767,32767,0)
    assert (state.lt,state.rt,state.x,state.y,state.touch)==(255,9,1023,512,True)
    assert motion[0]==(-40*2000/32768*16,-60*2000/32768*16,50*2000/32768*16,10,30,20)


def test_gyro_torn_sample_and_redundant_sensor_rejection():
    d=Decoder()
    assert [d.filter(0,1000) for _ in range(4)]==[0,0,0,1000]
    stable=((100,200,300,1,2,3),(-100,-200,300,1,2,-3))
    assert d.select(stable,'Mixed','dualsense')==(100,200,300,1,2,3)
    spike=((100,200,300,1,2,3),(-16000,-200,300,1,2,-3))
    assert d.select(spike,'Mixed','dualsense')==(100,200,300,1,2,3)
    assert d.parse(b'\x04\x00\xb0'+bytes(61)) is None


def test_shaping_roundtrip_deadzone_and_trigger_range():
    text='LS:Shape=2;DX=0.25;DY=0.1;ADX=0.1;ADY=0;CX=1;CY=0|LT:DZ=0.2;RM=0.5;AD=0.1;C=0'
    cfg=parse(text)
    assert parse(serialize(cfg))==cfg
    assert values(edit(text,'ViiperLSDX',50))['ViiperLSDX']==50
    assert stick(8192,0,cfg['LS'])==(0,0)
    assert stick(16384,0,cfg['LS'])[0]==6553
    assert trigger(51,cfg['LT'])==0
    assert trigger(255,cfg['LT'])==127
    state=Input(lx=-32768,ly=32767,lt=255)
    assert transform(state,defaults()) is state
    for invalid in ('LS:DX=nan','LS:Shape=3','LT:RM=2','LS:CX=1.5'):
        with pytest.raises(ValueError):parse(invalid)
