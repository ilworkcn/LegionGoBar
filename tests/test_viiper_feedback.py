import struct
import pytest
from legiongobar.native.viiper_reports import Input
from legiongobar.native.viiper_feedback import Guide,Lightbar,pair_motion


def test_guide_wakes_independent_overlay_once_per_press():
    guide=Guide();state=Input(buttons=0x1400)
    output,wake=guide.apply(state,'GameBar')
    assert wake and output.buttons==0x1000
    assert not guide.apply(state,'GameBar')[1]
    guide.apply(Input(),'GameBar')
    assert guide.apply(state,'GameBar')[1]
    assert guide.apply(state,'Native')[0].buttons==0x1400


def test_lightbar_initial_black_throttle_and_restore():
    light=Lightbar();writes=[];settings={'LegionLightMode':1,'LegionLightColor':'#123456','LegionLightBrightness':50,'LegionLightSpeed':25}
    light.update((0,0,0),0,writes.append,settings)
    assert not writes
    light.update((10,20,30),1,writes.append,settings)
    assert len(writes)==4 and writes[0][6:9]==bytes((10,20,30))
    light.update((0,0,0),1.01,writes.append,settings)
    assert len(writes)==4
    light.update((0,0,0),1.2,writes.append,settings)
    assert len(writes)==8
    light.restore(writes.append,settings)
    assert writes[-4][6:9]==bytes.fromhex('123456')
    count=len(writes);light.restore(writes.append,settings)
    assert len(writes)==count


def test_joycon_pair_imu_uses_each_half_and_clamps_negation():
    packet=bytes(range(24));motion=(-32768,2,3,4,5,6)
    left=pair_motion(packet,motion);right=pair_motion(packet,motion,True)
    assert left[:12]==right[:12]==packet[:12]
    assert struct.unpack_from('<6h',left,12)==(3,-32768,2,6,4,5)
    assert struct.unpack_from('<6h',right,12)==(-3,32767,2,-6,-4,5)
