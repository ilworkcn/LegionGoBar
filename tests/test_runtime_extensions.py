import json
import struct
from pathlib import Path
import pytest
from legiongobar.native.idle import IdlePolicy
from legiongobar.native.rtss_memory import SharedBuffer,SIGNATURE
from legiongobar.storage import Store
from legiongobar.profiles import Profiles,canonical
from legiongobar.osd import parse,render


def test_idle_timeout_requires_both_input_sources_idle_and_rearms_after_resume():
    policy=IdlePolicy()
    assert policy.next_action(0,999,999,True,1,False,False) is None
    for now in range(5,61,5):
        assert policy.next_action(now,now,0,True,1,False,False) is None
    assert policy.next_action(65,65,65,True,1,False,True) is None
    assert policy.next_action(70,70,70,True,1,False,False)=='hibernate'
    assert policy.next_action(75,75,75,True,1,False,False) is None
    assert policy.next_action(500,500,500,True,1,False,False) is None


def test_idle_ac_dc_changes_start_new_timer_and_screen_off_once():
    policy=IdlePolicy()
    for now in range(0,60,5):assert policy.next_action(now,now,now,True,0,True,False) is None
    assert policy.next_action(60,60,60,True,0,True,False)=='screen_off'
    assert policy.next_action(65,65,65,True,0,True,False) is None
    assert policy.next_action(70,70,70,False,1,True,False) is None


def shared():
    data=bytearray(64+4608*3+300)
    struct.pack_into('<9I',data,0,SIGNATURE,0x2000e,300,64+4608*3,1,4608,64,3,0)
    return data,SharedBuffer(data)


def test_rtss_slot_ownership_and_release_only_own_slot():
    data,buffer=shared()
    other=64+4608
    data[other+256:other+261]=b'other'
    data[other+512:other+517]=b'hello'
    before=bytes(data[other:other+4608])
    assert buffer.publish('ours','<FR> FPS')
    ours=other+4608
    assert data[ours+512:ours+520]==b'<FR> FPS'
    assert bytes(data[other:other+4608])==before
    assert buffer.publish('ours',None)
    assert not any(data[ours:ours+4608])
    assert bytes(data[other:other+4608])==before
    assert not buffer.publish('ours',None)


def test_rtss_samples_reject_stale_data_and_invalid_offsets():
    data,buffer=shared();offset=buffer.app_offset
    struct.pack_into('<I',data,offset,123)
    data[offset+4:offset+12]=b'game.exe'
    struct.pack_into('<5I',data,offset+264,8,1000,2000,60,16667)
    assert buffer.samples(2100)[0]['fps']==60
    assert buffer.samples(6000)==[]
    struct.pack_into('<I',data,12,len(data)+1)
    with pytest.raises(ValueError):SharedBuffer(data)


def test_osd_config_and_text_no_invented_metrics():
    text=render(1,'L1:FPS,Battery;TextSize:150',{'BatteryLevel':None},{})
    assert '<FR> FPS' in text and 'Battery' in text and '--' in text
    assert render(0,'',{}, {}) is None
    with pytest.raises(ValueError):parse('TextColor:<script>')
    with pytest.raises(ValueError):parse('L1_Columns:0')


def test_upstream_xml_import_dc_global_disabled_and_retained_fields(tmp_path):
    path=tmp_path/'profiles.xml'
    path.write_text('''<GoTweaksProfiles Version="2"><GlobalProfile><GameId><Name>global</Name><Path>global</Path></GameId><TDP>15</TDP></GlobalProfile><GameProfiles><GameProfile><GameId><Name>Demo</Name><Path>C:\\Games\\Demo.exe</Path></GameId><Use>false</Use><TDP>22</TDP><TDP_DC>12</TDP_DC><CPUBoost>false</CPUBoost><StickyTDP>true</StickyTDP><FutureField>hello</FutureField></GameProfile></GameProfiles></GoTweaksProfiles>''')
    store=Store(tmp_path/'data');assert store.import_profiles(path)==1
    record=store.data['profiles'][canonical('C:/Games/Demo.exe')]
    assert record['settings']=={'TDP':22,'CPUBoost':False,'StickyTDPEnabled':True}
    assert record['dc']['TDP']==12 and not record['enabled']
    assert store.data['global_profile']['settings']['TDP']==15
    before=json.dumps(store.data,sort_keys=True)
    path.write_text('<!DOCTYPE x [<!ENTITY x "bad">]><GameProfile/>')
    with pytest.raises(ValueError):store.import_profiles(path)
    assert json.dumps(store.data,sort_keys=True)==before


def test_saved_field_selection_keeps_global_and_inherits(tmp_path):
    store=Store(tmp_path);manager=Profiles(store)
    snapshot={'values':{'TDP':20,'CPUEPP':50},'capabilities':{'TDP':True,'CPUEPP':True}}
    store.set('ProfileSaveFlags',{'TDP':False})
    manager.save(None,snapshot);manager.save('C:/game.exe',snapshot)
    assert 'TDP' not in store.data['profiles'][canonical('C:/game.exe')]['settings']
    assert manager.settings_for('C:/game.exe',True)['TDP']==20
