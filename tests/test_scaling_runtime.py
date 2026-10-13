import xml.etree.ElementTree as ET
import pytest
from legiongobar.native import scaling as module
from legiongobar.native.scaling import Scaling, hotkey

@pytest.fixture
def scaling(tmp_path, monkeypatch):
    monkeypatch.setattr(module,'find_executable',lambda:None)
    monkeypatch.setattr(module,'running',lambda:[])
    path=tmp_path/'Settings.xml'
    path.write_text('<Settings><Hotkey>S</Hotkey><HotkeyModifierKeys>Control Alt</HotkeyModifierKeys><GameProfiles><Profile><Title>Default</Title><Sharpness>50</Sharpness><Unknown>keep</Unknown></Profile></GameProfiles></Settings>')
    adapter=Scaling(path)
    adapter.discover()
    return adapter

def test_creation_preserves_source_and_rejects_duplicates(scaling):
    scaling.stage('LosslessScalingSharpness',80)
    scaling.create_profile('Example',r'C:\Games\example.exe')
    assert scaling.profile_name=='Example'
    root=ET.fromstring(scaling.path.read_bytes())
    assert len(list(root.iter('Profile')))==2
    assert scaling.profile(root).findtext('Unknown')=='keep'
    assert scaling.profile(root).findtext('Sharpness')=='50'
    with pytest.raises(ValueError,match='already exists'):
        scaling.create_profile('Renamed',r'c:\games\EXAMPLE.exe')
    assert scaling.select_game(r'C:\Games\other.exe')
    scaling.discover()
    assert scaling.pending['Sharpness']==80
    scaling.save()
    assert scaling.profile(ET.fromstring(scaling.path.read_bytes())).findtext('Sharpness')=='80'

def test_drafts_and_external_edit_conflict(scaling):
    scaling.create_profile('Example',r'C:\Games\example.exe')
    scaling.discover()
    scaling.stage('LosslessScalingSharpness',70)
    scaling.select_game(r'C:\Games\other.exe')
    scaling.discover()
    scaling.path.write_text(scaling.path.read_text().replace('50','60'))
    scaling.select_game(r'C:\Games\example.exe')
    with pytest.raises(RuntimeError,match='changed externally'):scaling.discover()
    with pytest.raises(RuntimeError,match='changed externally'):scaling.save()

def test_reset_is_staged(scaling):
    before=scaling.path.read_bytes()
    values=scaling.reset()
    assert values['LosslessScalingCaptureApi']=='WGC'
    assert values['LosslessScalingSharpness']==50
    assert scaling.path.read_bytes()==before
    scaling.save()
    root=ET.fromstring(scaling.path.read_bytes())
    assert scaling.profile(root).findtext('CaptureApi')=='WGC'
    assert scaling.profile(root).findtext('Unknown')=='keep'

def test_hotkey_configuration_validation():
    assert hotkey(ET.fromstring('<Settings/>'))==[17,18,83]
    assert hotkey(ET.fromstring('<Settings><Hotkey>F12</Hotkey><HotkeyModifierKeys>Alt, Control Shift</HotkeyModifierKeys></Settings>'))==[18,17,16,123]
    with pytest.raises(ValueError):hotkey(ET.fromstring('<Settings><Hotkey>F25</Hotkey></Settings>'))
    with pytest.raises(ValueError):hotkey(ET.fromstring('<Settings><HotkeyModifierKeys>Unknown</HotkeyModifierKeys></Settings>'))

def test_missing_settings_can_still_launch(scaling,monkeypatch):
    scaling.path.unlink()
    monkeypatch.setattr(module,'find_executable',lambda:scaling.path.parent/'LosslessScaling.exe')
    caps,values=scaling.discover()
    assert caps['LosslessScalingLaunch']
    assert not caps['LosslessScalingSaveAndRestart']
    assert not values['LosslessScalingEnabled']

def test_creation_conflict_and_relative_path(scaling):
    with pytest.raises(ValueError):scaling.create_profile('Game','game.exe')
    scaling.path.write_text(scaling.path.read_text().replace('50','65'))
    with pytest.raises(RuntimeError,match='changed externally'):
        scaling.create_profile('Game',r'C:\Game\game.exe')


def test_scaling_focus_failure_does_not_inject(scaling,monkeypatch):
    import win32gui, win32process
    from types import SimpleNamespace
    monkeypatch.setattr(module,'running',lambda:[object()])
    scaling.target_hwnd,scaling.target_path=123,r'C:\Game\game.exe'
    monkeypatch.setattr(win32gui,'IsWindow',lambda hwnd:True)
    monkeypatch.setattr(win32gui,'SetForegroundWindow',lambda hwnd:None)
    monkeypatch.setattr(win32gui,'GetForegroundWindow',lambda:456)
    monkeypatch.setattr(win32process,'GetWindowThreadProcessId',lambda hwnd:(1,2))
    monkeypatch.setattr(module.psutil,'Process',lambda pid:SimpleNamespace(exe=lambda:scaling.target_path))
    sent=[]
    monkeypatch.setattr(module,'send_hotkey',lambda keys:sent.append(keys))
    with pytest.raises(RuntimeError,match='activate'):scaling.set_enabled(True)
    assert sent==[] and not scaling.enabled
    monkeypatch.setattr(win32gui,'GetForegroundWindow',lambda:123)
    assert scaling.set_enabled(True)
    assert sent==[[17,18,83]]
    assert scaling.set_enabled(True)
    assert len(sent)==1


def test_scaling_reused_window_does_not_inject(scaling,monkeypatch):
    import win32gui, win32process
    from types import SimpleNamespace
    monkeypatch.setattr(module,'running',lambda:[object()])
    scaling.target_hwnd,scaling.target_path=123,r'C:\Game\game.exe'
    monkeypatch.setattr(win32gui,'IsWindow',lambda hwnd:True)
    monkeypatch.setattr(win32process,'GetWindowThreadProcessId',lambda hwnd:(1,2))
    monkeypatch.setattr(module.psutil,'Process',lambda pid:SimpleNamespace(exe=lambda:r'C:\Other\other.exe'))
    sent=[]
    monkeypatch.setattr(module,'send_hotkey',lambda keys:sent.append(keys))
    with pytest.raises(RuntimeError,match='no longer available'):scaling.set_enabled(True)
    assert sent==[] and not scaling.enabled


def test_localized_default_and_current_xml_roundtrip(scaling):
    scaling.path.write_text("""<Settings><GameProfiles><Profile><Title>默认</Title>
    <ScalingMode>Auto</ScalingMode><ScalingFitMode>AspectRatio</ScalingFitMode>
    <Anime4kType>S</Anime4kType><VRS>false</VRS><Sharpness>5</Sharpness>
    <Unknown>preserved</Unknown></Profile></GameProfiles></Settings>""", encoding="utf-8")
    caps, values = scaling.discover()
    assert values['LosslessScalingCurrentProfile'] == '默认'
    assert values['LosslessScalingScaleMode'] == 'Auto'
    assert values['LosslessScalingAspectRatio'] == 'Aspect Ratio'
    assert values['LosslessScalingAnime4KSize'] == 'Small'
    assert caps['LosslessScalingScaleMode'] and caps['LosslessScalingAnime4KVRS']
    scaling.stage('LosslessScalingScaleMode', 'Custom')
    scaling.stage('LosslessScalingAspectRatio', 'Fullscreen')
    scaling.stage('LosslessScalingAnime4KSize', 'Large')
    scaling.stage('LosslessScalingAnime4KVRS', True)
    scaling.save()
    profile = scaling.profile(ET.fromstring(scaling.path.read_bytes()))
    assert profile.findtext('ScalingMode') == 'Custom'
    assert profile.findtext('ScalingFitMode') == 'Fullscreen'
    assert profile.findtext('Anime4kType') == 'L'
    assert profile.findtext('VRS') == 'true'
    assert profile.findtext('Unknown') == 'preserved'
    assert profile.find('ScaleMode') is None and profile.find('Anime4KVRS') is None
    scaling.create_profile('游戏', r'C:\Games\example.exe')
    assert scaling.select_game(r'C:\Games\other.exe')
    caps, values = scaling.discover()
    assert values['LosslessScalingCurrentProfile'] == '默认'


def test_invalid_xml_retains_launch_and_reports_failure(scaling, monkeypatch):
    monkeypatch.setattr(module, 'find_executable', lambda: scaling.path.parent/'LosslessScaling.exe')
    scaling.path.write_text('<Settings>')
    caps, values = scaling.discover()
    assert caps['LosslessScalingLaunch']
    assert not caps['LosslessScalingSharpness']
    assert values['LosslessScalingError']
    assert values['LosslessScalingStatus'] == 'Lossless Scaling settings could not be read'
