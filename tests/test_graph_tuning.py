import struct
from legiongobar.native.rtss_memory import SharedBuffer,SIGNATURE
from legiongobar.native.viiper_tuning import apply,edit,field_values
from legiongobar.native.viiper_reports import Input
from legiongobar.osd import render,edit as osd_edit


def test_rtss_graph_objects_and_slot_lifetime():
    size=266752;data=bytearray(64+size*3+300)
    struct.pack_into('<9I',data,0,SIGNATURE,0x2000e,300,64+size*3,1,size,64,3,0)
    buffer=SharedBuffer(data);ours=64+size
    buffer.publish('owner','<G=<FT>> <G=<FR>>')
    assert bytes(data[ours+512:ours+541]).startswith(b'<OBJ=00000000> <OBJ=00000024>')
    header=struct.unpack_from('<IIiiiIffI',data,ours+4608)
    assert header==(0x47523030,36,-32,-2,1,4,0,50000,0)
    assert struct.unpack_from('<I',data,ours+4608+36+20)[0]==2
    buffer.publish('owner',None)
    assert not any(data[ours:ours+size])


def test_pinned_graph_and_statistics():
    config=osd_edit('L2:FPS,FrametimeGraph',2,'FrametimeGraphPinned',True)
    text=render(2,config,{}, {'FrameSamples':[{'frame_min':10,'frame_avg':16.7,'frame_max':30}]})
    assert '<G=<FT>>' in text and '16.7ms' in text and '30.0ms' in text


def test_per_source_tuning_and_front_mapping():
    settings={'ViiperGyroSource':'Left'}
    key,value=edit(settings,'ViiperGyroMatrixX','Z');settings[key]=value
    key,value=edit(settings,'ViiperGyroInvertX',True);settings[key]=value
    state=Input(aux=0xc3,imu=(1,2,3,4,5,6))
    tuned=apply(state,settings)
    assert tuned.buttons==0x400 and tuned.click and tuned.aux==3
    assert tuned.imu==(-3,2,3,4,5,6)
    assert field_values(settings)['ViiperGyroMatrixX']=='Z'
    settings['ViiperGyroSource']='Right'
    assert apply(state,settings).imu==state.imu
