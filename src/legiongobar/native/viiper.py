"""VIIPER 的原生接口及独立轮询进程。驱动操作只在用户启用时发生。"""
from __future__ import annotations

import ctypes as C
import multiprocessing as mp
import os
from pathlib import Path
import queue
import re
import socket
import subprocess
import time
from importlib.resources import files
from .viiper_reports import Input, Feedback, report, STEAM, SONY, NINTENDO

TYPES = {'xbox360','gordon'} | STEAM | SONY | NINTENDO
DEFAULTS={'ViiperDeviceType':'xbox360','ViiperSonySubDevice':'dualsense','ViiperSteamSubDevice':'steam-deck','ViiperNintendoSubDevice':'switchpro','ViiperSwapRumbleMotors':False,'ViiperRumbleIntensity':100,'ViiperAlternateGyroConvention':False}


def selected_type(settings):
    family=settings['ViiperDeviceType']
    kind=settings.get({'sony':'ViiperSonySubDevice','nintendo':'ViiperNintendoSubDevice','steam-generic':'ViiperSteamSubDevice'}.get(family,''),family)
    return {'dualsense-edge':'dualsenseedge','switchpro2':'ns2pro'}.get(kind,kind)


def validate_setting(key,value):
    from .stick_gyro import DEFAULTS as GYRO_DEFAULTS,validate
    if key in GYRO_DEFAULTS:validate(key,value);return
    if key in ("ViiperGyroTuning","ViiperAccelTuning"):
        from .viiper_tuning import parse
        parse(value)
    if key in ("ViiperDesktopButtonTarget","ViiperPageButtonTarget") and value not in ('none','guide','touchpad','share','options','l3','r3'):raise ValueError('Invalid front button target')
    if key=="ViiperStickTriggerConfig":
        from .stick_shaping import parse
        parse(value)
    choices={'ViiperGuideButtonMode':{'Native','GameBar'},'ViiperInputSource':{'XInput','LegionHid'},'ViiperGyroSource':{'None','Left','Right','Mixed','Handheld'},'ViiperDeviceType':{'xbox360','sony','nintendo','steam-generic'},'ViiperSonySubDevice':{'dualshock4','dualsense','dualsense-edge'},'ViiperNintendoSubDevice':{'switchpro','switchpro2','joycon-left','joycon-right','joycon-pair'},'ViiperSteamSubDevice':STEAM|{'gordon'}}
    if key in choices and (not isinstance(value,str) or value not in choices[key]):raise ValueError('Invalid virtual controller selection')
    if key in ('ViiperSwapRumbleMotors','ViiperAlternateGyroConvention','ControllerEmulationEnabled','ViiperMirrorLightbarToStick','ViiperJoyconGyroPerHalf') and type(value) is not bool:raise ValueError('Expected a boolean')
    if key=='ViiperRumbleIntensity' and (type(value) is not int or not 0<=value<=200):raise ValueError('Rumble intensity must be between 0 and 200')
DEFAULTS.update({'ViiperGuideButtonMode':'Native','ViiperMirrorLightbarToStick':False,'ViiperJoyconGyroPerHalf':False})
DEFAULTS.update({"ViiperDesktopButtonTarget":"guide","ViiperPageButtonTarget":"touchpad","ViiperGyroTuning":"","ViiperAccelTuning":"","ViiperStickTriggerConfig":"","ViiperInputSource":"XInput","ViiperGyroSource":"None"})
from .stick_gyro import DEFAULTS as GYRO_DEFAULTS
DEFAULTS.update(GYRO_DEFAULTS)
FEEDBACK = C.CFUNCTYPE(None,C.c_uint32,C.c_uint32,C.c_void_p,C.c_int,C.c_void_p)


def driver_path():
    for root in ('ProgramFiles','ProgramFiles(x86)'):
        candidate=Path(os.environ.get(root,r'C:\Program Files'))/'USBip/usbip.exe'
        if candidate.is_file():return candidate
    return None


def dll_path():
    return Path(str(files('legiongobar').joinpath('assets/native/libviiper.dll')))


def ports(text):
    """仅解析本程序监听端点，避免清理其他服务器导入的设备。"""
    result={}
    blocks=re.split(r'(?im)^\s*Port\s+(\d+)\s*:',text)
    for i in range(1,len(blocks)-1,2):
        match=re.search(r'usbip://(?:127\.0\.0\.1|localhost):3241/(\d+-\d+)\b',blocks[i+1],re.I)
        if match:result.setdefault(match[1],[]).append(int(blocks[i]))
    return result


class Usbip:
    def __init__(self,path=None):
        self.path=Path(path) if path else driver_path()
        if self.path is None:raise RuntimeError('Install USBip to enable controller emulation')

    def run(self,*args):
        result=subprocess.run([str(self.path),*map(str,args)],capture_output=True,encoding='utf-8',errors='replace',timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise RuntimeError((result.stderr or result.stdout).strip() or 'USBip command failed')
        return result.stdout

    def attached(self):return ports(self.run('-t','3241','port'))

    def attach(self,busid):
        # 原生自动连接可能延迟枚举，先等待，确认缺失后只补发一次。
        for _ in range(10):
            if busid in self.attached():return
            time.sleep(.15)
        self.run('-t','3241','attach','-r','127.0.0.1','-b',busid)
        for _ in range(20):
            if busid in self.attached():return
            time.sleep(.15)
        raise RuntimeError('USBip device did not appear after attachment')

    def detach(self,bus):
        for busid,indices in self.attached().items():
            if busid.split('-')[0]==str(bus):
                for index in indices:self.run('detach','-p',index)


class Native:
    def __init__(self,path):
        self.dll=C.CDLL(str(path));self.active=False;self.callbacks=[]
        signatures={
            'init':([C.c_char_p],C.c_int),'shutdown':([],None),
            'bus_create':([C.c_uint32],C.c_int),'bus_remove':([C.c_uint32],C.c_int),
            'device_add':([C.c_uint32,C.c_char_p,C.POINTER(C.c_uint32)],C.c_int),
            'device_remove':([C.c_uint32,C.c_uint32],C.c_int),
            'device_set_input':([C.c_uint32,C.c_uint32,C.c_void_p,C.c_int],C.c_int),
            'device_set_feedback_callback':([C.c_uint32,C.c_uint32,FEEDBACK,C.c_void_p],C.c_int),
            'last_error':([],C.c_void_p),'free_string':([C.c_void_p],None)}
        for name,(args,result) in signatures.items():
            fn=getattr(self.dll,'viiper_'+name);fn.argtypes=args;fn.restype=result

    def call(self,name,*args):
        result=getattr(self.dll,'viiper_'+name)(*args)
        if result is not None and result!=0:
            ptr=self.dll.viiper_last_error()
            try:message=C.string_at(ptr).decode('utf-8','replace') if ptr else 'VIIPER native call failed'
            finally:
                if ptr:self.dll.viiper_free_string(ptr)
            raise RuntimeError(message)

    def start(self,bus):
        self.call('init',b'127.0.0.1:3241');self.active=True
        self.call('bus_create',bus)

    def add(self,bus,kind,feedback):
        device=C.c_uint32();self.call('device_add',bus,kind.encode('ascii'),C.byref(device))
        callback=FEEDBACK(lambda b,d,data,size,_: feedback(b,d,C.string_at(data,size)) if 0<size<=4096 else None)
        self.callbacks.append(callback)
        self.call('device_set_feedback_callback',bus,device.value,callback,None)
        return device.value

    def send(self,bus,device,data):
        buf=C.create_string_buffer(data);self.call('device_set_input',bus,device,buf,len(data))

    def close(self):
        if self.active:self.call('shutdown');self.active=False
        self.callbacks.clear()


class XInput:
    def __init__(self):
        self.dll=C.WinDLL('xinput1_4.dll')
        self.dll.XInputGetState.argtypes=[C.c_uint32,C.c_void_p];self.dll.XInputGetState.restype=C.c_uint32
        self.dll.XInputSetState.argtypes=[C.c_uint32,C.c_void_p];self.dll.XInputSetState.restype=C.c_uint32
        self.caps=self.dll[108];self.caps.argtypes=[C.c_uint32,C.c_uint32,C.c_uint32,C.c_void_p];self.caps.restype=C.c_uint32
        candidates=[(i,self.identity(i)) for i in range(4)]
        self.index,self.fingerprint=next(((i,v) for i,v in candidates if v is not None),(None,None))
        if self.index is None:raise RuntimeError('Connect a physical XInput controller before enabling emulation')

    def identity(self,index):
        buf=C.create_string_buffer(32)
        if self.caps(1,index,1,buf):return None
        # 记录型号身份，设备断开后不切换到新出现的虚拟手柄。
        return bytes(buf.raw[20:28])

    def read(self):
        import struct
        if self.identity(self.index)!=self.fingerprint:raise RuntimeError('Physical controller disconnected')
        buf=C.create_string_buffer(16)
        if self.dll.XInputGetState(self.index,buf):raise RuntimeError('Physical controller disconnected')
        return Input(*struct.unpack_from('<HBB4h',buf.raw,4))

    def rumble(self,motors):
        if self.identity(self.index)==self.fingerprint:
            buf=(C.c_uint16*2)(*(max(0,min(65535,round(v*257))) for v in motors))
            self.dll.XInputSetState(self.index,buf)


def _worker(pipe,bus,kind,settings,path,usbip_path):
    from .stick_shaping import parse,transform
    from .viiper_tuning import apply as tune
    from .viiper_feedback import Guide,Lightbar,pair_motion
    guide=Guide();light=Lightbar();baseline=dict(settings)
    shaping=parse(settings.get("ViiperStickTriggerConfig",""))
    handheld=None
    motion=gyro=None;next_live=0;calibration=None;calibration_phase=None;calibration_sample=None
    native=source=legion=None;client=Usbip(usbip_path);feedback=queue.Queue(maxsize=128)
    try:
        from .legion_input import LegionInput
        import hid
        from .legion_hid import matching_devices
        required=settings.get("ViiperInputSource")=="LegionHid" or settings.get("ViiperGyroSource","None") not in ("None","Handheld") or settings.get("ViiperJoyconGyroPerHalf") or settings.get("ViiperMirrorLightbarToStick") or settings.get("ViiperStickGyroEnabled")
        if required or matching_devices(hid.enumerate()):legion=LegionInput()
        if settings.get('ViiperGyroSource')=='Handheld':
            from .handheld_motion import HandheldMotion
            handheld=HandheldMotion()
        if legion:
            from .motion import Motion
            from .stick_gyro import StickGyro
            motion=Motion(settings.get('ViiperGyroBias'));gyro=StickGyro(motion)
        try:source=XInput()
        except (RuntimeError,OSError):
            if settings.get("ViiperInputSource")!="LegionHid":raise
        native=Native(path);native.start(bus)
        def receive(b,d,data):
            try:feedback.put_nowait((b,d,data))
            except queue.Full:pass
        devices=[]
        for target in (('joycon-left','joycon-right') if kind=='joycon-pair' else (kind,)):
            device=native.add(bus,target,receive);devices.append(device);client.attach(f'{bus}-{device}')
        pipe.send(('ready',devices));rumble={device:Feedback() for device in devices};previous=None;start=time.monotonic()
        while True:
            if pipe.poll():
                command=pipe.recv()
                if command is None:break
                if isinstance(command,tuple) and command[0]=='calibrate':
                    if motion is None:
                        pipe.send(('calibration',{'phase':'unavailable','remaining':0}));continue
                    if command[1]=='reset':
                        motion.bias=None;motion.reset();motion.dll.SetCalibrationMode(motion.handle,3)
                        settings['ViiperGyroBias']=[];pipe.send(('bias',[]));calibration=None
                        pipe.send(('calibration',{'phase':'reset','remaining':0}));continue
                    calibration=time.monotonic()+3;calibration_phase=None;calibration_sample=None
                    continue
                settings=command
                shaping=parse(settings.get("ViiperStickTriggerConfig",""))
            now=time.monotonic()
            from dataclasses import replace
            hid_state=legion.read("None" if handheld else settings.get("ViiperGyroSource","None"),kind,now) if legion else None
            if settings.get("ViiperInputSource")=="LegionHid":state=hid_state
            else:
                state=source.read()
                if hid_state:state=replace(state,aux=hid_state.aux,touch=hid_state.touch,click=hid_state.click,x=hid_state.x,y=hid_state.y,imu=hid_state.imu)
            if handheld:state=replace(state,imu=handheld.read(now))
            if gyro and legion.latest and now-legion.timestamp<=.2:
                source_name={0:'Mixed',1:'Right',2:'Left',3:'Mixed'}[settings.get('ControllerEmulationGyroSource',0)]
                imu=legion.decoder.select(legion.latest[1],source_name,'joycon-right' if source_name=='Right' else kind)
                if calibration is not None:
                    import math
                    phase='preparing' if now<calibration else 'capturing' if now<calibration+5 else 'done'
                    remaining=math.ceil((calibration if phase=='preparing' else calibration+5)-now) if phase!='done' else 0
                    if phase=='capturing':
                        if calibration_phase is None or calibration_phase[0]!='capturing':
                            motion.bias=None;motion.reset();motion.dll.ResetContinuousCalibration(motion.handle);motion.dll.SetCalibrationMode(motion.handle,3)
                        if calibration_sample!=legion.timestamp:
                            motion.update(imu,.004 if calibration_sample is None else legion.timestamp-calibration_sample)
                            calibration_sample=legion.timestamp
                    if phase=='done':
                        confidence=motion.dll.GetAutoCalibrationConfidence(motion.handle)
                        if confidence>0:
                            bias=[*motion.vector('GetCalibrationOffset'),round(confidence*10)]
                            motion.set_bias(bias);settings['ViiperGyroBias']=bias;pipe.send(('bias',bias))
                        else:
                            phase='low_confidence'
                            if settings.get('ViiperGyroBias'):motion.set_bias(settings['ViiperGyroBias'])
                        calibration=None
                    if (phase,remaining)!=calibration_phase:
                        pipe.send(('calibration',{'phase':phase,'remaining':remaining}));calibration_phase=(phase,remaining)
                elif kind not in SONY and kind not in ('joycon-pair','ns2pro'):
                    state=gyro.apply(state,imu,now,settings)
                if now>=next_live:
                    pipe.send(('gyro',gyro.live));next_live=now+.1
            state=transform(tune(state,settings),shaping)
            state,wake=guide.apply(state,settings.get('ViiperGuideButtonMode','Native'))
            if wake:pipe.send(('overlay',True))
            packet=report(kind,state,int((now-start)*250),settings.get('ViiperAlternateGyroConvention',False))
            for index,device in enumerate(devices):
                device_packet=packet
                if kind=='joycon-pair' and settings.get('ViiperJoyconGyroPerHalf') and legion and legion.latest and now-legion.timestamp<=.2:
                    source_name='Right' if index else 'Left'
                    motion=legion.decoder.select(legion.latest[1],source_name,kind)
                    # 每个半柄先应用各自的轴矩阵，再转成原版 Joy-Con 坐标。
                    tuned=tune(replace(state,imu=motion),dict(settings,ViiperGyroSource=source_name))
                    device_packet=pair_motion(packet,tuned.imu,bool(index))
                native.send(bus,device,device_packet)
            while not feedback.empty():
                try:b,d,data=feedback.get_nowait()
                except queue.Empty:break
                if b==bus and d in rumble:rumble[d].read('switchpro' if kind=='joycon-pair' else kind,data,now)
            if legion:
                if settings.get('ViiperMirrorLightbarToStick'):
                    color=next((feedback.color for feedback in rumble.values() if feedback.color is not None),None)
                    light.update(color,now,legion.device.write,settings)
                else:light.restore(legion.device.write,baseline)
            outputs=[value.decay(now) for value in rumble.values()]
            motors=tuple(max(output[i] for output in outputs) for i in range(2))
            if settings.get('ViiperSwapRumbleMotors',False):motors=motors[::-1]
            strength=settings.get('ViiperRumbleIntensity',100)/100
            motors=tuple(min(255,round(v*strength)) for v in motors)
            if source and motors!=previous:source.rumble(motors);previous=motors
            time.sleep(.004)
    except Exception as error:
        try:pipe.send(('error',str(error)))
        except (OSError,EOFError):pass
    finally:
        if handheld:handheld.close()
        if motion:motion.close()
        if legion:
            try:light.restore(legion.device.write,baseline)
            except Exception:pass
            legion.close()
        if source:
            try:source.rumble((0,0))
            except Exception:pass
        try:
            if native:native.close()
        finally:
            try:client.detach(bus)
            except Exception:pass
        pipe.close()


class Emulation:
    """将可能阻塞的第三方驱动调用隔离，主程序退出时可回收。"""
    def __init__(self,directory):
        from .hidhide import Hide
        self.hide=Hide(directory)
        self.process=None;self.pipe=None;self.bus=os.getpid()%60000+1;self.error='';self.kind=None;self.overlay_count=0;self.gyro_live=None;self.calibration={};self.bias_update=None

    def available(self):return os.name=='nt' and driver_path() is not None and dll_path().is_file()

    def start(self,kind,settings):
        if kind not in TYPES:raise ValueError('Unsupported virtual controller type')
        if self.process:self.stop()
        if not self.available():raise RuntimeError('Install USBip to enable controller emulation')
        # 避免接管其他程序的服务器或残留导入端口。
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            try:probe.bind(('127.0.0.1',3241))
            except OSError as error:raise RuntimeError('VIIPER port 3241 is already in use') from error
        if any(key.startswith(str(self.bus)+'-') for key in Usbip().attached()):raise RuntimeError('A previous virtual controller still occupies this bus')
        from .hidhide import devices
        physical=devices()
        if physical:self.hide.enable(physical)
        child=None
        try:
            context=mp.get_context('spawn');parent,child=context.Pipe()
            self.pipe=parent;self.kind=kind;self.error=''
            self.process=context.Process(target=_worker,args=(child,self.bus,kind,dict(settings),str(dll_path()),str(driver_path())),daemon=True)
            self.process.start();child.close();child=None
            if not parent.poll(20):raise RuntimeError('Virtual controller startup timed out')
            status,value=parent.recv()
            if status!='ready':raise RuntimeError(value)
        except Exception:
            self.stop();raise
        finally:
            if child:child.close()

    def status(self):
        if self.pipe:
            try:
                while self.pipe.poll():
                    status,value=self.pipe.recv()
                    if status=='error':self.error=value
                    elif status=='overlay':self.overlay_count+=1
                    elif status=='gyro':self.gyro_live=value
                    elif status=='calibration':self.calibration=value
                    elif status=='bias':self.bias_update=value
            except (OSError,EOFError):pass
        active=bool(self.process and self.process.is_alive() and not self.error)
        if self.process and not active:self.stop()
        return active,self.error

    def calibrate(self,reset=False):
        if not self.process or not self.process.is_alive():raise RuntimeError('Enable controller emulation before calibration')
        self.pipe.send(('calibrate','reset' if reset else 'start'))

    def configure(self,settings):
        if self.process and self.process.is_alive():self.pipe.send(dict(settings))

    def stop(self):
        if not self.process:
            if self.pipe:self.pipe.close();self.pipe=None
            self.hide.restore()
            return
        try:
            try:self.pipe.send(None)
            except (OSError,EOFError):pass
            if self.process.pid is not None:self.process.join(3)
            if self.process.is_alive():self.process.terminate();self.process.join(3)
            try:Usbip().detach(self.bus)
            except Exception as error:self.error=str(error)
        finally:
            self.pipe.close();self.pipe=None
            try:
                if self.process.is_alive():self.process.kill();self.process.join(3)
                self.process.close()
            finally:
                self.process=None
                self.hide.restore()
