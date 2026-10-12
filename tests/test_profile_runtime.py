import copy
import json
import pytest
from legiongobar.profiles import Profiles, canonical
from legiongobar.storage import Store


def setup(tmp_path):
    store=Store(tmp_path)
    store.set('PerGameProfile', True)
    store.set('PowerSourceProfile', True)
    store.data['profiles'][canonical('C:/Games/a.exe')]={'name':'Game A','settings':{'TDP':20},'ac':{'CPUEPP':10},'dc':{'TDP':10,'CPUEPP':80}}
    snapshot={'values':{'TDP':15,'LegionPerformanceMode':255,'CPUEPP':50,'CPUBoost':False},
              'capabilities':{k:True for k in ('TDP','LegionPerformanceMode','CPUEPP','CPUBoost','StickyTDPEnabled')}}
    return store,Profiles(store),snapshot


def complete(manager, plan, snapshot):
    snapshot['values'].update(plan['settings'])
    manager.complete(plan, True)


def test_game_ac_dc_switch_self_focus_and_restore_global(tmp_path):
    store,manager,snapshot=setup(tmp_path)
    plan=manager.plan('C:/Games/A.exe',True,snapshot,now=1)
    assert plan['settings']['TDP']==20 and plan['settings']['CPUEPP']==10
    complete(manager,plan,snapshot)
    assert manager.plan('C:/Games/a.exe',True,snapshot,now=2) is None
    assert manager.plan('C:/Apps/LegionGoBar.exe',True,snapshot,own_path='C:/Apps/LegionGoBar.exe',now=2) is None
    plan=manager.plan('C:/Apps/LegionGoBar.exe',False,snapshot,own_path='C:/Apps/LegionGoBar.exe',now=3)
    assert plan['settings']['TDP']==10 and plan['settings']['CPUEPP']==80
    complete(manager,plan,snapshot)
    plan=manager.plan('C:/Windows/explorer.exe',False,snapshot,now=4)
    assert plan['key'] is None and plan['settings']['TDP']==15 and plan['settings']['CPUEPP']==50
    complete(manager,plan,snapshot)
    assert store.data['global_profile']['settings']['TDP']==15
    assert manager.plan('C:/Windows/explorer.exe',False,snapshot,now=5) is None


def test_disabling_profiles_restores_global_and_missing_path_keeps_game(tmp_path):
    store,manager,snapshot=setup(tmp_path)
    plan=manager.plan('C:/Games/a.exe',True,snapshot,now=1);complete(manager,plan,snapshot)
    assert manager.plan(None,True,snapshot,now=2) is None
    store.set('PerGameProfile',False)
    plan=manager.plan('C:/Games/a.exe',True,snapshot,now=3)
    assert plan['key'] is None and plan['settings']['TDP']==15


def test_failed_transition_retries_bounded_and_does_not_claim_active(tmp_path):
    store,manager,snapshot=setup(tmp_path)
    for now in (1,11,21):
        plan=manager.plan('C:/Games/a.exe',True,snapshot,now=now)
        assert plan is not None
        manager.complete(plan,False,now=now)
        assert manager.active is None
        assert manager.plan('C:/Games/a.exe',True,snapshot,now=now+1) is None
    assert manager.plan('C:/Games/a.exe',True,snapshot,now=40) is None
    store.data['profiles'][canonical('C:/Games/a.exe')]['ac']['TDP']=22
    assert manager.plan('C:/Games/a.exe',True,snapshot,now=41) is not None


def test_manual_changes_stay_in_active_power_branch(tmp_path):
    store,manager,snapshot=setup(tmp_path)
    plan=manager.plan('C:/Games/a.exe',False,snapshot,now=1);complete(manager,plan,snapshot)
    manager.remember('TDP',12,False)
    record=Store(tmp_path).data['profiles'][canonical('C:/Games/a.exe')]
    assert record['dc']['TDP']==12 and record['settings']['TDP']==20
    assert store.data['global_profile']['settings']['TDP']==15
    manager.remember('OnScreenKeyboard',True,False)
    assert 'OnScreenKeyboard' not in record['dc']


def test_profile_import_roundtrip_and_invalid_branch_is_atomic(tmp_path):
    store,manager,snapshot=setup(tmp_path)
    manager.save(None,snapshot)
    document=tmp_path/'export.json';store.export_profiles(document)
    target=Store(tmp_path/'target');target.import_profiles(document)
    assert target.data['profiles']==store.data['profiles']
    assert target.data['global_profile']==store.data['global_profile']
    before=copy.deepcopy(target.data)
    record=json.loads(document.read_text());record['profiles']['bad']={'settings':{},'dc':{'OnScreenKeyboard':True}}
    document.write_text(json.dumps(record))
    with pytest.raises(ValueError):target.import_profiles(document)
    assert target.data==before


def test_legacy_profile_import_and_late_adapter_availability(tmp_path):
    store,manager,snapshot=setup(tmp_path)
    doc=tmp_path/'old.json';doc.write_text(json.dumps({'version':1,'profiles':{'C:/Games/legacy.exe':{'settings':{'CPUBoost':True}}}}))
    store.import_profiles(doc)
    assert canonical('C:/Games/legacy.exe') in store.data['profiles']
    store.data['profiles'][canonical('C:/Games/a.exe')]['settings']['FPSLimit']=60
    plan=manager.plan('C:/Games/a.exe',True,snapshot,now=1);complete(manager,plan,snapshot)
    snapshot['capabilities']['FPSLimit']=True
    plan=manager.plan('C:/Games/a.exe',True,snapshot,now=2)
    assert plan['settings']['FPSLimit']==60


def test_partial_global_record_captures_missing_restore_fields(tmp_path):
    store,manager,snapshot=setup(tmp_path)
    store.data['global_profile']={'settings':{'CPUEPP':70}}
    manager.plan('C:/Games/a.exe',True,snapshot,now=1)
    assert store.data['global_profile']['settings']['TDP']==15
    assert store.data['global_profile']['settings']['CPUEPP']==70


def test_profile_page_switches_are_connected(tmp_path):
    from PySide6.QtWidgets import QApplication
    from legiongobar.backend import Backend
    from legiongobar.ui.window import Window
    app=QApplication.instance() or QApplication([])
    store=Store(tmp_path);w=Window(Backend(store,demo=True),store,no_tray=True)
    w.pool.waitForDone();app.processEvents();w.select('Game')
    page=w.page_widgets['Game'];page.power_source.click()
    w.pool.waitForDone();app.processEvents()
    assert w.snapshot['values']['PowerSourceProfile'] is True
    page.scope.setCurrentIndex(2);page.save_selected()
    assert 'dc' in store.data['global_profile']
    w.quit();w.pool.waitForDone();app.removeEventFilter(w)


def test_preset_excludes_custom_power_fields_and_custom_mode_reapplies(tmp_path):
    store,manager,snapshot=setup(tmp_path)
    snapshot['values'].update(TDPBoostEnabled=True,TDPBoostSPPT=25,TDPBoostFPPT=30)
    snapshot['capabilities'].update({k:True for k in ('TDPBoostEnabled','TDPBoostSPPT','TDPBoostFPPT')})
    record=store.data['profiles'][canonical('C:/Games/a.exe')]
    record['settings']['LegionPerformanceMode']=2
    plan=manager.plan('C:/Games/a.exe',True,snapshot,now=1)
    assert not {'TDP','TDPBoostEnabled','TDPBoostSPPT','TDPBoostFPPT'}.intersection(plan['settings'])
    complete(manager,plan,snapshot)
    record['settings']['LegionPerformanceMode']=255
    snapshot['values']['TDP']=20
    plan=manager.plan('C:/Games/a.exe',True,snapshot,now=2)
    assert plan['settings']['TDP']==20
    assert plan['settings']['TDPBoostSPPT']==25
