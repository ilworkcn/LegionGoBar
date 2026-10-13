"""读取独立 PresentMon 的 CSV 帧事件；只管理本程序创建的捕获会话。"""
import csv
import math
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid


class Metrics:
    def __init__(self,pid):
        self.pid=pid;self.lock=threading.Lock();self.last=None
        self.app=[];self.display=[];self.generated=0;self.app_ewma=0.;self.display_ewma=0.
        self.result={'pid':pid,'live':False}

    def push(self,row,now=None,generated_pid=None):
        try:pid=int(row.get('ProcessID',''))
        except (ValueError,TypeError):return
        if pid!=self.pid and pid!=generated_pid:return
        def number(*names):
            for name in names:
                try:value=float(row[name])
                except (KeyError,ValueError,TypeError):continue
                if math.isfinite(value) and value>=0:return value
            return 0.
        interval=number('FrameTime','MsBetweenPresents')
        if not 0<interval<10000:return
        kind=row.get('FrameType','Application')
        generated=pid==generated_pid or kind in ('AMD_AFMF','Intel_XEFG')
        with self.lock:
            self.last=time.monotonic() if now is None else now
            self.display.append(interval)
            if generated:self.generated+=1
            if not generated and kind not in ('Repeated','AMD_AFMF','Intel_XEFG'):
                self.app.append((interval,number('CPUBusy','MsCPUBusy'),number('GPUBusy','MsGPUBusy')))
            # 即使维护线程暂时停顿也限制采样内存。
            self.display=self.display[-8192:];self.app=self.app[-8192:]

    def snapshot(self,now=None):
        now=time.monotonic() if now is None else now
        with self.lock:
            live=self.last is not None and now-self.last<=3
            if not live:
                self.result={'pid':self.pid,'live':False};self.app_ewma=self.display_ewma=0.
            else:
                self.result['live']=True
                if self.app:
                    count=len(self.app);avg=sum(row[0] for row in self.app)/count
                    self.app_ewma=(avg+self.app_ewma)/2 if self.app_ewma else avg
                    self.result.update(rendered_fps=round(1000/self.app_ewma),
                        cpu_busy=min(100,sum(row[1] for row in self.app)/count/self.app_ewma*100),
                        gpu_busy=min(100,sum(row[2] for row in self.app)/count/self.app_ewma*100))
                if self.display:
                    avg=sum(self.display)/len(self.display)
                    self.display_ewma=(avg+self.display_ewma)/2 if self.display_ewma else avg
                    displayed=round(1000/self.display_ewma)
                    self.result.update(displayed_fps=displayed,generated_fps=max(0,displayed-self.result.get('rendered_fps',0)) if self.generated else 0)
            self.app.clear();self.display.clear();self.generated=0
            return dict(self.result)


class Capture:
    def __init__(self,executable=None):
        self.executable=Path(executable) if executable else Path(__file__).resolve().parents[1]/'assets/native/PresentMon.exe'
        self.process=None;self.metrics=None;self.session=None;self.error='';self.retry_at=0.;self.failures=0
        self.reader=None;self.target=None

    def _read(self,process,metrics):
        try:
            for row in csv.DictReader(process.stdout):metrics.push(row)
        except (OSError,ValueError,csv.Error) as error:self.error=str(error)
        finally:process.stdout.close()

    def update(self,pid,now=None):
        now=time.monotonic() if now is None else now
        if self.target!=pid:
            self.close();self.failures=0;self.retry_at=0;self.target=pid
        if not pid:
            self.close();return {'live':False}
        if self.process and self.process.poll() is not None:
            code=self.process.returncode;self.close();self.failures+=1
            self.retry_at=now+min(60,5*self.failures);self.error=f'PresentMon exited ({code})'
        if not self.process and now>=self.retry_at and self.failures<3 and self.executable.is_file():
            self.session=f'LegionGoBar_PMon_{os.getpid()}_{uuid.uuid4().hex}'
            args=[str(self.executable),'--session_name',self.session,'--output_stdout','--no_console_stats',
                  '--track_frame_type','--terminate_on_proc_exit','--process_id',str(int(pid))]
            try:
                self.process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                    text=True,encoding='utf-8-sig',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                self.metrics=Metrics(pid);self.error=''
                self.reader=threading.Thread(target=self._read,args=(self.process,self.metrics),daemon=True);self.reader.start()
            except OSError as error:
                self.error=str(error);self.failures+=1;self.retry_at=now+10;self.session=None
        return self.metrics.snapshot(now) if self.metrics else {'live':False,'pid':pid}

    def close(self):
        process,self.process=self.process,None
        session,self.session=self.session,None
        if session:
            try:
                subprocess.run([str(self.executable),'--session_name',session,'--terminate_existing_session'],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=False)
            except (OSError,subprocess.TimeoutExpired):pass
        if process:
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
        if self.reader:self.reader.join(timeout=1)
        self.reader=None;self.metrics=None
