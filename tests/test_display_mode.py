from types import SimpleNamespace
from copy import deepcopy
import pytest
from legiongobar.native.display import WindowsDisplay


def display(test_result=0, apply_result=0, mismatch=False):
    device=WindowsDisplay.__new__(WindowsDisplay)
    device.con=SimpleNamespace(ENUM_CURRENT_SETTINGS=-1,DM_PELSWIDTH=1,DM_PELSHEIGHT=2,
                               DM_DISPLAYFREQUENCY=4,CDS_TEST=2,DISP_CHANGE_SUCCESSFUL=0)
    old=SimpleNamespace(PelsWidth=2560,PelsHeight=1600,DisplayFrequency=144,DisplayOrientation=0,Fields=7)
    state={'mode':old,'calls':[]}
    def change(unused,mode,flags):
        state['calls'].append((mode.PelsWidth,mode.PelsHeight,mode.DisplayFrequency,flags))
        if flags==2:return test_result
        if mode.PelsWidth==1280:
            if not mismatch:state['mode']=deepcopy(mode)
            return apply_result
        state['mode']=deepcopy(mode)
        return 0
    device.api=SimpleNamespace(EnumDisplaySettings=lambda *args:deepcopy(state['mode']),ChangeDisplaySettingsEx=change)
    device.modes=lambda:[(2560,1600,144),(1280,800,60)]
    return device,state


def test_display_pair_is_tested_and_applied_together():
    device,state=display()
    assert device.set_mode('1280x800',60)['RefreshRate']==60
    assert state['calls']==[(1280,800,60,2),(1280,800,60,0)]


@pytest.mark.parametrize('kwargs',[{'apply_result':-1},{'mismatch':True}])
def test_failed_pair_restores_previous_mode(kwargs):
    device,state=display(**kwargs)
    with pytest.raises(OSError):device.set_mode('1280x800',60)
    assert state['calls'][-1]==(2560,1600,144,0)
    assert device.current()['Resolution']=='2560x1600'


def test_rejected_pair_never_changes_mode():
    device,state=display(test_result=-2)
    with pytest.raises(OSError):device.set_mode('1280x800',60)
    assert state['calls']==[(1280,800,60,2)]
    with pytest.raises(ValueError):device.set_mode('1280x800',144)
    assert len(state['calls'])==1
