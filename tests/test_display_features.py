import ctypes as C
from types import SimpleNamespace
import pytest
from legiongobar.native.hdr import Hdr, DisplayPath, Header, ColorInfo, ColorState
from legiongobar.native.adlx import Adlx


class FakeHdr(Hdr):
    def __init__(self, mismatch=False, supported=True):
        self.enabled=False;self.supported=supported;self.mismatch=mismatch;self.writes=[]
    def target(self):return object()
    def status(self,target=None):return {'HDRSupported':self.supported,'HDREnabled':self.enabled}
    def write(self,target,value):
        self.writes.append(value)
        if not self.mismatch:self.enabled=value


def test_hdr_structures_and_toggle_readback():
    assert (C.sizeof(DisplayPath),C.sizeof(Header),C.sizeof(ColorInfo),C.sizeof(ColorState))==(72,20,32,24)
    hdr=FakeHdr();assert hdr.set(True) is True
    assert hdr.set(True) is True and hdr.writes==[True]
    assert hdr.set(False) is False


def test_hdr_unsupported_and_bad_values_never_write():
    hdr=FakeHdr(supported=False)
    with pytest.raises(OSError):hdr.set(True)
    with pytest.raises(ValueError):hdr.set(1)
    assert hdr.writes==[]


def test_hdr_mismatch_rolls_back():
    hdr=FakeHdr(mismatch=True)
    with pytest.raises(OSError,match='readback'):hdr.set(True)
    assert hdr.writes==[True,False]


@pytest.mark.parametrize('field,value,limits',[('Brightness',10,(-100,100,1)),('Contrast',110,(0,200,1)),('Saturation',120,(0,200,1)),('Temperature',6600,(1000,10000,100))])
def test_adlx_color_roundtrip_and_bounds(field,value,limits):
    amd=Adlx.__new__(Adlx);amd.color=1;amd.color_ranges={'AMDDisplay'+field:limits}
    state={'value':limits[0]};calls=[]
    amd.color_read=lambda pointer,method:state['value']
    def call(name,args,types):
        calls.append(name);state['value']=args[1];return 0
    amd.call=call
    assert amd.set_color('AMDDisplay'+field,value)==value
    with pytest.raises(ValueError):amd.set_color('AMDDisplay'+field,limits[1]+1)
    assert calls==['IADLXDisplayCustomColor_Set'+field]


def test_adlx_color_failed_readback_restores_previous():
    amd=Adlx.__new__(Adlx);amd.color=1;amd.color_ranges={'AMDDisplayBrightness':(-100,100,1)}
    amd.color_read=lambda *args:0
    writes=[];amd.call=lambda name,args,types:writes.append(args[1]) or 0
    with pytest.raises(RuntimeError,match='readback'):amd.set_color('AMDDisplayBrightness',10)
    assert writes==[10,0]


def test_system_power_and_hdr_controls_have_real_bindings():
    from legiongobar.ui.reference import load_reference,function_for
    reference=load_reference()
    expected={'HDRToggle':'HDREnabled','PowerButtonActionACComboBox':'PowerButtonActionAC',
              'PowerButtonActionDCComboBox':'PowerButtonActionDC','DisplayTimeoutACComboBox':'DisplayTimeoutAC',
              'DisplayTimeoutDCComboBox':'DisplayTimeoutDC'}
    for name,key in expected.items():assert function_for(name,reference['functions'])==key


def test_boost_range_and_rollback():
    from legiongobar.native.adlx import Adlx
    adapter=Adlx.__new__(Adlx)
    adapter.features={"AMDRadeonBoost":(1,"Boost")}
    adapter.field_ranges={"AMDRadeonBoostResolution":(50,100,5)}
    adapter.read=lambda *args:75
    writes=[]
    adapter.call=lambda name,args,types: writes.append(args[1]) or 0
    import pytest
    with pytest.raises(ValueError):adapter.set("AMDRadeonBoostResolution",51)
    assert writes==[]
    with pytest.raises(RuntimeError,match="readback mismatch"):adapter.set("AMDRadeonBoostResolution",80)
    assert writes==[80,75]
