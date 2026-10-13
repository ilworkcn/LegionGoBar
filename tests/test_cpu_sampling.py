"""额外状态轮询不能缩短 CPU 的一秒统计窗口。"""
import threading
from legiongobar.native import system


def test_cpu_sampling_one_second_window(monkeypatch):
    clock = [10.0]
    calls = []
    monkeypatch.setattr(system, '_cpu_sample', threading.local())
    monkeypatch.setattr(system.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(system.psutil, 'cpu_percent', lambda: calls.append(clock[0]) or len(calls)*10)
    assert system.cpu_usage() == 10
    for moment in (10.01, 10.25, 10.5, 10.75, 10.999):
        clock[0] = moment
        assert system.cpu_usage() == 10
    clock[0] = 11.0
    assert system.cpu_usage() == 20
    assert calls == [10.0, 11.0]
