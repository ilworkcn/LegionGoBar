import ctypes as C
import pytest
from legiongobar.backend import Backend, PERFORMANCE_KEYS, TDP_KEYS
from legiongobar.storage import Store
from legiongobar.native.rtss import Rtss


class FakeHooks:
    def __init__(self):
        self.value = 60
        self.events = []
        self.reject = None
    def LoadProfile(self, name): self.events.append(('load', name))
    def SaveProfile(self, name): self.events.append(('save', name))
    def UpdateProfiles(self): self.events.append(('update',))
    def GetProfileProperty(self, name, pointer, size):
        assert name == b'FramerateLimit' and size == 4
        C.cast(pointer, C.POINTER(C.c_int32))[0] = self.value
        return 1
    def SetProfileProperty(self, name, pointer, size):
        value = C.cast(pointer, C.POINTER(C.c_int32))[0]
        self.events.append(('write', value))
        if value == self.reject: return 0
        self.value = value
        return 1


def test_rtss_native_write_readback_and_disable(monkeypatch):
    rtss = Rtss(); rtss.dll = FakeHooks()
    monkeypatch.setattr(rtss, 'is_running', lambda: True)
    assert rtss.set(90) == 90
    assert ('save', b'') in rtss.dll.events and ('update',) in rtss.dll.events
    assert rtss.set(0) == 0
    rtss.dll.reject = 120
    with pytest.raises(OSError, match='write failed'): rtss.set(120)
    assert rtss.read() == 0
    monkeypatch.setattr(rtss, 'is_running', lambda: False)
    count = len(rtss.dll.events)
    with pytest.raises(RuntimeError, match='running'): rtss.set(60)
    assert len(rtss.dll.events) == count


@pytest.mark.parametrize('value', [-1, 145, True, 60.5])
def test_rtss_invalid_values_do_not_touch_dll(value):
    rtss = Rtss(); rtss.dll = FakeHooks()
    with pytest.raises(ValueError): rtss.set(value)
    assert not rtss.dll.events


class FakeWmi:
    def __init__(self):
        self.state = dict(zip(('LegionPerformanceMode', 'LegionCustomTDPSlow', 'LegionCustomTDPFast', 'LegionCustomTDPPeak'), (255, 20, 21, 23)))
        self.writes = []
        self.fail = False
    def get(self, key):
        if self.fail: raise OSError('WMI read failed')
        return self.state[key]
    def set_tdp(self, *values):
        self.writes.append(values)
        result = dict(zip(('LegionCustomTDPSlow', 'LegionCustomTDPFast', 'LegionCustomTDPPeak'), values))
        self.state.update(result)
        return result


def sticky_backend(tmp_path):
    b = Backend(Store(tmp_path))
    b.capabilities.update({k: True for k in PERFORMANCE_KEYS | TDP_KEYS})
    b.values.update({'LegionPerformanceMode': 255, 'StickyTDPEnabled': True, 'StickyTDPInterval': 5,
                     'TDP': 20, 'TDPBoostEnabled': True, 'TDPBoostSPPT': 1, 'TDPBoostFPPT': 3})
    b.wmi = FakeWmi()
    b.next_rtss = float('inf')
    return b


def test_sticky_reads_all_limits_only_restores_drift_and_obeys_interval(tmp_path):
    b = sticky_backend(tmp_path)
    b.maintain(10)
    assert not b.wmi.writes
    b.wmi.state['LegionCustomTDPFast'] = 25
    b.maintain(11)
    assert not b.wmi.writes
    b.maintain(15)
    assert b.wmi.writes == [(20, 21, 23)]
    assert b.values['TDP'] == 20
    assert b.values['CurrentTDP'] == 'SPL:20W SPPT:21W FPPT:23W'
    assert not b.store.path.exists()


def test_sticky_does_not_override_external_preset_and_backs_off_on_error(tmp_path):
    b = sticky_backend(tmp_path)
    b.wmi.state['LegionPerformanceMode'] = 2
    b.maintain(10)
    assert not b.wmi.writes and not b.values['StickyTDPEnabled']
    assert b.values['LegionPerformanceMode'] == 2
    b.values.update({'StickyTDPEnabled': True, 'LegionPerformanceMode': 255})
    b.wmi.fail = True
    b.maintain(20)
    assert b.next_sticky == 35 and 'WMI read failed' in b.values['MaintenanceError']
    assert not b.wmi.writes


def test_performance_preview_never_writes_or_maintains(tmp_path):
    b = Backend(Store(tmp_path), demo=True); b.discover()
    with pytest.raises(RuntimeError, match='Custom'): b.apply('StickyTDPEnabled', True)
    b.apply('LegionPerformanceMode',255)
    b.apply('StickyTDPEnabled',True)
    b.apply('FPSLimitEnabled',True)
    assert b.values['FPSLimit']==60
    b.apply('FPSLimit',90)
    b.maintain(100)
    assert b.values['FPSLimitEnabled'] and b.wmi is None and b.rtss is None
    assert not b.store.path.exists()


def test_backend_fps_failure_is_not_saved_and_last_limit_is_restored(tmp_path):
    b = Backend(Store(tmp_path)); b.capabilities.update({'FPSLimit':True,'FPSLimitEnabled':True})
    class Adapter:
        def set(self,value):
            if value==100: raise OSError('readback failed')
            return value
    b.rtss = Adapter()
    b.apply('FPSLimit',90)
    b.apply('FPSLimitEnabled',False)
    assert b.values['FPSLimit']==0
    b.apply('FPSLimitEnabled',True)
    assert b.values['FPSLimit']==90
    with pytest.raises(OSError): b.apply('FPSLimit',100)
    assert b.values['FPSLimit']==90 and b.store.get('FPSLimit')==90


def test_ui_accepts_real_tdp_text_and_wires_performance_controls(tmp_path):
    from PySide6.QtWidgets import QApplication
    from legiongobar.ui.reference import Renderer,load_reference
    app = QApplication.instance() or QApplication([])
    calls=[];r=Renderer(load_reference(),lambda *args:calls.append(args),lambda *args:None)
    pages=[r.render(node) for node in r.reference['pages'].values()]
    b=Backend(Store(tmp_path),demo=True); b.discover()
    b.values.update({'LegionPerformanceMode':255,'CurrentTDP':'SPL:20W SPPT:21W FPPT:23W','FPSLimit':90,'FPSLimitEnabled':True})
    r.update(b.snapshot())
    assert r.named['CurrentTDPValueText'].text()==b.values['CurrentTDP']
    assert r.named['FPSLimitToggle'].isChecked()
    assert r.named['FPSLimitSlider'].value()==90
    r.named['StickyTDPToggle'].click()
    assert calls[-1]==('StickyTDPEnabled',True)
    r.named['FPSLimitToggle'].click()
    assert calls[-1]==('FPSLimitEnabled',False)
    for page in pages: page.deleteLater()


def test_rtss_start_stop_detection_changes_availability(tmp_path):
    b = Backend(Store(tmp_path))
    class Adapter:
        installed = True
        running = True
        def discover(self): return 72 if self.running else None
    b.rtss = Adapter()
    b.maintain(5)
    assert b.supported('FPSLimit') and b.values['FPSLimit']==72
    b.rtss.running = False
    b.maintain(10)
    assert not b.supported('FPSLimit') and not b.values['RTSSRunning']
    b.rtss.running = True
    b.maintain(15)
    assert b.supported('FPSLimit')


def test_rtss_readback_mismatch_restores_previous_limit(monkeypatch):
    class WrongHooks(FakeHooks):
        def SetProfileProperty(self, name, pointer, size):
            result = super().SetProfileProperty(name, pointer, size)
            if self.value == 90: self.value = 89
            return result
    rtss = Rtss(); rtss.dll = WrongHooks()
    monkeypatch.setattr(rtss, 'is_running', lambda: True)
    with pytest.raises(OSError, match='readback mismatch'): rtss.set(90)
    assert rtss.read() == 60
