import struct
import pytest
from legiongobar.native.viiper_reports import Input,report,Feedback
from legiongobar.native.viiper import ports,selected_type,validate_setting,DEFAULTS


def test_xbox_wire_preserves_signed_axes_and_buttons():
    state=Input(0x1421,255,128,-32768,32767,-1234,2345)
    assert report('xbox360',state)==bytes.fromhex('21140000ff800080ff7f2efb2909000000000000')


def test_sony_wire_guide_dpad_touch_and_motion():
    s=Input(buttons=0x1409,lt=255,rt=8,lx=-32768,ly=-32768,rx=32767,ry=32767,click=True,touch=True,x=1023,y=1023,imu=(1,2,3,4,5,6))
    wire=report('dualshock4',s)
    assert len(wire)==31
    assert wire[:14]==bytes.fromhex('807f7f80230009ff087f07ae0301')
    assert struct.unpack_from('<6h',wire,19)==(1,3,-2,8,-12,10)
    edge=report('dualsenseedge',Input(buttons=0x1000,aux=15))
    assert struct.unpack_from('<I',edge,4)[0]==0xf00020
    assert edge[8]==0


def test_nintendo_trigger_boundary_and_axes():
    s=Input(buttons=0x1001,lt=128,rt=129,lx=-32768,ly=32767,imu=(1,2,3,4,5,6))
    wire=report('switchpro',s)
    assert struct.unpack_from('<I',wire)[0]==0x20084
    assert struct.unpack_from('<6h',wire,12)==(2,-1,3,-5,-4,-6)
    assert struct.unpack_from('<6h',report('joycon-left',s),12)==(-3,-2,-1,6,5,-4)
    ns=report('ns2pro',s)
    assert struct.unpack_from('<4H',ns,4)==(0,4095,2048,2048)
    assert ns[-3:]==bytes((9,0,1))


def test_steam_packet_and_frame_wrap():
    s=Input(buttons=0x1000,lt=255,rt=128,lx=-32768,ly=32767,aux=15,touch=True,click=True,x=1023,y=0,imu=(1,2,3,4,5,6))
    wire=report('legion-go',s,2**32+7)
    assert wire[:8]==bytes.fromhex('0100094007000000')
    assert wire[8:11]==bytes((0x83,0x80,0x15))
    assert struct.unpack_from('<6h',wire,24)==(16,-24,20,1,-3,2)
    assert struct.unpack_from('<2H',wire,44)==(32767,16447)
    assert struct.unpack_from('<h',wire,22)[0]==32767


def test_feedback_retains_other_motor_and_decays_pulses():
    f=Feedback()
    pulse=lambda side,count:bytes((0x8f,0,side))+struct.pack('<3Hb',600,400,count,0)
    assert f.read('steamdeck',pulse(0,100),1)==(153,0)
    assert f.read('steamdeck',pulse(1,10),1.01)==(153,153)
    assert f.decay(1.04)==(153,0)
    assert f.decay(1.11)==(0,0)
    assert f.read('dualshock4',bytes((10,30,40,50,60)),2)==(30,10)
    assert f.color==(40,50,60)


def test_usbip_ownership_is_exact():
    text='''Port 03: working
       42-1 -> usbip://127.0.0.1:3241/42-1
Port 04: working
       42-2 -> usbip://example127.0.0.1:3241/42-2
Port 05: working
       42-3 -> usbip://127.0.0.1:3242/42-3
Port 06: working
       1-1 -> usbip://localhost:3241/1-1
'''
    assert ports(text)=={'42-1':[3],'1-1':[6]}


def test_setting_validation_and_device_aliases():
    assert selected_type({**DEFAULTS,'ViiperDeviceType':'sony','ViiperSonySubDevice':'dualsense-edge'})=='dualsenseedge'
    for key,value in [('ViiperRumbleIntensity',201),('ViiperRumbleIntensity',True),('ControllerEmulationEnabled',1),('ViiperDeviceType','invalid')]:
        with pytest.raises(ValueError):validate_setting(key,value)


def test_native_abi_loads_without_starting_server():
    import os
    if os.name!='nt':pytest.skip('Windows native DLL')
    import subprocess,sys
    from pathlib import Path
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    result=subprocess.run([sys.executable,'-c','from legiongobar.native.viiper import Native,dll_path; n=Native(dll_path()); assert not n.active; n.close()'],env=env,capture_output=True,timeout=15)
    assert result.returncode==0,result.stderr.decode(errors='replace')
