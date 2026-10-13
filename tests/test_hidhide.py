from legiongobar.native.hidhide import Hide,is_gamepad
import pytest

PAD=r'USB\VID_17EF&PID_6182&MI_00\7&12345&0&0000'
OTHER=r'HID\VID_045E&PID_028E\7&ABCDE&0&0000'


class Driver:
    def __init__(self):self.hidden={OTHER};self.apps=set();self.cloak=False;self.fail=False
    def __call__(self,*args):
        key=args[0]
        if key=='--inv-state':return '--inv-off'
        if key=='--cloak-state':return '--cloak-on' if self.cloak else '--cloak-off'
        if key=='--dev-list':return '\n'.join(f'--dev-hide "{v}"' for v in self.hidden)
        if key=='--app-list':return '\n'.join(f'--app-reg "{v}"' for v in self.apps)
        if key=='--dev-hide':
            if self.fail:raise RuntimeError('driver rejected write')
            self.hidden.add(args[1])
        if key=='--dev-unhide':self.hidden.discard(args[1])
        if key=='--app-reg':self.apps.add(args[1])
        if key=='--app-unreg':self.apps.discard(args[1])
        if key=='--cloak-on':self.cloak=True
        if key=='--cloak-off':self.cloak=False
        return ''


def test_only_controller_interfaces_qualify():
    assert is_gamepad(PAD)
    assert not is_gamepad(PAD.replace('&MI_00','&MI_03'))
    assert not is_gamepad(PAD.replace('&MI_00',''))
    assert not is_gamepad(OTHER)


def test_hidhide_restores_baseline_and_recovers_failed_start(tmp_path):
    driver=Driver();hide=Hide(tmp_path,driver)
    hide.enable([PAD]);assert driver.hidden=={OTHER,PAD} and driver.cloak
    # 模拟退出前重建对象，验证恢复不依赖内存中的状态。
    Hide(tmp_path,driver).restore()
    assert driver.hidden=={OTHER} and not driver.cloak and not driver.apps
    driver.fail=True
    with pytest.raises(RuntimeError):hide.enable([PAD])
    assert driver.hidden=={OTHER} and not driver.cloak and not driver.apps
    assert not hide.journal.exists()


def test_other_apps_added_rules_are_preserved(tmp_path):
    driver=Driver();hide=Hide(tmp_path,driver);hide.enable([PAD])
    driver.hidden.add('another tool rule')
    hide.restore()
    assert driver.hidden=={OTHER,'another tool rule'} and driver.cloak
