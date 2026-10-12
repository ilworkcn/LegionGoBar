import math
import pytest
from legiongobar.autotdp import AutoTdp
from legiongobar.tile_hotkeys import validate,native_key,fired
from legiongobar.backend import Backend
from legiongobar.storage import Store


def test_pid_low_fps_bounded_and_capped():
    controller=AutoTdp();current=15
    for index in range(100):
        value=controller.decide(index*.25,30,current,60,8,20)
        if value is not None:
            assert current-2<=value<=current+1 and 8<=value<=20
            current=value
    assert current==20


def test_pid_probes_at_cap_and_recovers_from_failed_probe():
    controller=AutoTdp();current=20;probed=False;restored=False
    for index in range(70):
        value=controller.decide(index*.25,60 if not probed else 35,current,60,8,30)
        if value is not None:
            if value<current:probed=True
            if probed and value>current:restored=True;break
            current=value
    assert probed and restored


def test_pid_ignores_nonfinite_and_menu_spikes():
    controller=AutoTdp()
    for index in range(10):controller.decide(index*.25,60,20,60,8,30)
    assert controller.decide(3,200,20,60,8,30) is None
    assert controller.decide(4,math.nan,20,60,8,30) is None


class Wmi:
    def __init__(self):self.mode=255;self.tdp=15;self.writes=[]
    def get(self,key):return self.mode if key=='LegionPerformanceMode' else self.tdp
    def set_tdp(self,slow,fast,peak):
        self.tdp=slow;self.writes.append((slow,fast,peak))
        return {'LegionCustomTDPSlow':slow,'LegionCustomTDPFast':fast,'LegionCustomTDPPeak':peak}


def test_auto_runtime_restores_after_lost_fps_without_changing_profile_target(tmp_path,monkeypatch):
    monkeypatch.setattr('legiongobar.native.system.foreground',lambda:'C:/game.exe')
    backend=Backend(Store(tmp_path));backend.wmi=Wmi()
    backend.values.update({'TDP':20,'AutoTDPEnabled':True,'RTSSRunning':True,
                          'FrameSamples':[{'name':'C:/game.exe','pid':12,'fps':30}]})
    for index in range(10):backend.maintain_auto(index*.25)
    assert backend.auto_active and backend.values['TDP']==20
    backend.values['FrameSamples']=[];backend.maintain_auto(3)
    assert backend.wmi.writes[-1]==(20,20,20) and not backend.auto_active


def test_auto_external_preset_stops_without_writing_custom_mode(tmp_path,monkeypatch):
    monkeypatch.setattr('legiongobar.native.system.foreground',lambda:'C:/game.exe')
    backend=Backend(Store(tmp_path));backend.wmi=Wmi();backend.wmi.mode=2
    backend.auto_active=True;backend.values.update(TDP=20,AutoTDPEnabled=True,RTSSRunning=True,FrameSamples=[])
    backend.maintain_auto(1)
    assert not backend.wmi.writes and not backend.auto_active


def test_shortcut_duplicate_reserved_and_missing_modifier_rejected():
    assert native_key('Ctrl+Alt+F8')==(3,0x77)
    with pytest.raises(ValueError):validate({'TDP':{'keyboard':'Ctrl+Alt+G'}})
    with pytest.raises(ValueError):validate({'A':{'keyboard':'Alt+F1'},'B':{'keyboard':'Alt+F1'}})
    with pytest.raises(ValueError):validate({'A':{'gamepad':'View + A'},'B':{'gamepad':'View + A'}})
    with pytest.raises(ValueError):native_key('G')


def test_controller_shortcuts_are_edge_triggered():
    bindings={'CPUBoost':{'gamepad':'View + A'}}
    assert fired(bindings,0,0x1020)==['CPUBoost']
    assert fired(bindings,0x1020,0x1020)==[]
    assert fired(bindings,0x20,0x1020)==['CPUBoost']
