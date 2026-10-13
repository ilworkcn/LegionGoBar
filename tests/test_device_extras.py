import hashlib
import io
import pytest
from legiongobar.backend import Backend,HID_DEFAULTS
from legiongobar.storage import Store
from legiongobar.native import dependencies,wmi


def test_installer_checksum_failure_preserves_cached_file(monkeypatch,tmp_path):
    target=tmp_path/'downloads/USBip-0.9.7.8-x64.exe';target.parent.mkdir();target.write_bytes(b'old')
    monkeypatch.setattr(dependencies.urllib.request,'urlopen',lambda *a,**k:io.BytesIO(b'corrupt'))
    with pytest.raises(ValueError,match='checksum'):dependencies.download_usbip(tmp_path)
    assert target.read_bytes()==b'old' and not target.with_suffix('.download').exists()
    monkeypatch.setattr(dependencies,'USBIP_SHA256',hashlib.sha256(b'corrupt').hexdigest())
    assert dependencies.download_usbip(tmp_path).read_bytes()==b'corrupt'
    monkeypatch.setattr(dependencies.urllib.request,'urlopen',lambda *a,**k:pytest.fail('Cache must not be downloaded again'))
    assert dependencies.download_usbip(tmp_path)==target


def test_install_uses_exact_package_and_readback(monkeypatch,tmp_path):
    states=iter([{'HidHide':False},{'HidHide':True}]);calls=[]
    monkeypatch.setattr(dependencies,'status',lambda:next(states))
    monkeypatch.setattr(dependencies.shutil,'which',lambda name:'winget.exe')
    def run(args,**kwargs):
        calls.append((args,kwargs))
        return type('Result',(),{'returncode':0})()
    monkeypatch.setattr(dependencies.subprocess,'run',run)
    dependencies.install('HidHide',tmp_path)
    assert calls[0][0][:5]==['winget.exe','install','--id','NefariusSoftwareSolutions.HidHide','--exact']
    assert not calls[0][1].get('shell')
    with pytest.raises(ValueError):dependencies.install('anything',tmp_path)


def test_readonly_backend_never_restores_hidhide(monkeypatch,tmp_path):
    backend=Backend(Store(tmp_path),read_only=True)
    backend.emulation=type('Emulation',(),{'stop':lambda self:pytest.fail('Read-only close must not alter device rules')})()
    with pytest.raises(RuntimeError,match='read-only'):backend.apply('TDP',20)
    backend.close()


def test_power_light_readback_and_trigger_restore(monkeypatch):
    state={'brightness':1};calls=[]
    def invoke(cls,method,args):
        calls.append((cls,method,args))
        if method.startswith('Set_'):state['brightness']=args['Current_Brightness_Level'];return {}
        return {'Current_Brightness_Level':state['brightness']}
    monkeypatch.setattr(wmi,'invoke',invoke)
    power=wmi.LenovoWmi()
    assert not power.get('LegionPowerLight')
    assert power.set('LegionPowerLight',True)
    assert calls[-2][2]=={'Lighting_ID':4,'Current_State_Type':0,'Current_Brightness_Level':2}
    cfg={**HID_DEFAULTS,'LegionLeftTriggerEnd':45,'LegionRightTriggerEnd':50}
    enabled=Backend.hid_commands('LegionHairTriggers',True,cfg)
    restored=Backend.hid_commands('LegionHairTriggers',False,cfg)
    assert enabled[0][5:7]==bytes((0,1))
    assert restored[0][5:7]==bytes((0,45)) and restored[1][5:7]==bytes((0,50))
