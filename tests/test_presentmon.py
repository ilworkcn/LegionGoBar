import math
from legiongobar.native.presentmon import Metrics,Capture
from legiongobar.osd import render,edit,editor_values


def test_presentmon_ewma_filter_and_staleness():
    metrics=Metrics(42)
    row={'ProcessID':'42','FrameTime':'20','CPUBusy':'5','GPUBusy':'10','FrameType':'Application'}
    metrics.push(dict(row,ProcessID='43'),0)
    assert not metrics.snapshot(0)['live']
    metrics.push(row,1);result=metrics.snapshot(1)
    assert result=={'pid':42,'live':True,'rendered_fps':50,'displayed_fps':50,'generated_fps':0,'cpu_busy':25,'gpu_busy':50}
    assert metrics.snapshot(3)['rendered_fps']==50
    assert not metrics.snapshot(4.01)['live']
    metrics.push(dict(row,FrameTime='NaN'),5)
    assert not metrics.snapshot(5)['live']
    metrics.push(dict(row,FrameTime='10'),6)
    assert metrics.snapshot(6)['rendered_fps']==100
    metrics.push(row,7)
    assert metrics.snapshot(7)['rendered_fps']==67


def test_presentmon_generated_frames_and_legacy_headers():
    metrics=Metrics(42)
    metrics.push({'ProcessID':'42','MsBetweenPresents':'20','MsCPUBusy':'4','MsGPUBusy':'8'},1)
    metrics.push({'ProcessID':'42','MsBetweenPresents':'5','FrameType':'AMD_AFMF'},1)
    result=metrics.snapshot(1)
    assert result['rendered_fps']==50 and result['displayed_fps']==80 and result['generated_fps']==30
    assert result['cpu_busy']==20 and result['gpu_busy']==40
    text=render(2,'L2:FPS,FrameBudget',{}, {'PresentMon':result})
    assert '50/80 FPS [FG]' in text and 'CPU 20%' in text and 'GPU 40%' in text
    assert 'BND' not in render(2,'L2:FrameBudget',{}, {})


def test_capture_stops_only_its_session_and_resets_retry(monkeypatch,tmp_path):
    calls=[]
    monkeypatch.setattr('legiongobar.native.presentmon.subprocess.run',lambda args,**kw:calls.append(args))
    capture=Capture(tmp_path/'missing.exe');capture.session='LegionGoBar_PMon_123_abc';capture.close()
    assert calls==[[str(tmp_path/'missing.exe'),'--session_name','LegionGoBar_PMon_123_abc','--terminate_existing_session']]
    capture.target=42;capture.failures=3;capture.retry_at=99
    assert capture.update(43,10)=={'live':False,'pid':43}
    assert capture.failures==0 and capture.retry_at==0


def test_osd_dynamic_colors_and_default_labels():
    config=edit('L1:Battery,FPS',1,'OSDTextColorDynamic',True)
    assert editor_values(config,1)['OSDTextColorDynamic']
    text=render(1,config,{'BatteryLevel':10},{})
    assert '<C=008B8B>BATT <C=FF0000>10%' in text
    assert '<B=' not in text and '\b' not in text
    config=edit(config,1,'OSDLabelColorDefault',True)
    assert editor_values(config,1)['OSDLabelColorDefault']
