import pytest
from legiongobar.fps_sync import FpsSync


class Rtss:
    def __init__(self):self.value=90;self.fail=False
    def read(self):return self.value
    def set(self,value):
        if self.fail:raise OSError('write failed')
        self.value=value;return value


def test_sync_target_changes_and_restores_previous_limit():
    sync=FpsSync();rtss=Rtss()
    assert sync.update(True,60,rtss)==60
    assert sync.update(True,40,rtss)==40
    assert sync.update(False,40,rtss)==90
    assert sync.previous is None
    rtss.value=0;sync.update(True,60,rtss)
    assert sync.update(False,0,rtss)==0


def test_sync_keeps_external_changes_and_retries_failed_restore():
    sync=FpsSync();rtss=Rtss();sync.update(True,60,rtss)
    rtss.fail=True
    with pytest.raises(OSError):sync.update(False,0,rtss)
    assert sync.previous==90
    rtss.fail=False;rtss.value=75
    assert sync.update(False,0,rtss)==75
