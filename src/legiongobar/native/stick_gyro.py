"""按原项目参数与公式将传感器角速度转换为摇杆输入。"""
from dataclasses import replace
import math

PREFIX='ControllerEmulation'
OPTIONS={'GyroSource':(0,0,3),'StickSelect':(1,0,1),'GyroActivationMode':(0,0,2),'GyroActivationButton':(1,0,22),
 'StickSensitivityV2':(100,1,400),'StickOrientationV2':(0,0,1),'StickConversion':(0,0,4),
 'StickGyroAntiDeadzone':(10,0,30),'StickGyroAntiDeadzoneThreshold':(3,0,50),'StickGyroVerticalRatio':(100,10,200),
 'StickGyroCurvePreset':(0,0,2),'StickGyroTightenThreshold':(0,0,500),'StickGyroTightenGain':(100,100,300),
 'StickGyroTouchDeactivateThreshold':(15,0,50),'StickGyroTouchDeactivateHoldoff':(250,0,1000),'StickGyroSmoothing':(30,0,90)}
DEFAULTS={PREFIX+k:v[0] for k,v in OPTIONS.items()}
DEFAULTS.update({PREFIX+k:False for k in ('StickInvertX','StickInvertY','StickGyroTouchDeactivateEnabled')})
DEFAULTS['ViiperStickGyroEnabled']=False
DEFAULTS['ViiperGyroBias']=[]
UI={name:PREFIX+key for name,key in {
 'ActivationMode':'GyroActivationMode','ActivationButton':'GyroActivationButton','Sensitivity':'StickSensitivityV2',
 'Orientation':'StickOrientationV2','Conversion':'StickConversion','Select':'StickSelect','InvertX':'StickInvertX','InvertY':'StickInvertY',
 'AntiDeadzone':'StickGyroAntiDeadzone','AntiDeadzoneThreshold':'StickGyroAntiDeadzoneThreshold','VerticalRatio':'StickGyroVerticalRatio',
 'CurvePreset':'StickGyroCurvePreset','TightenThreshold':'StickGyroTightenThreshold','TightenGain':'StickGyroTightenGain',
 'TouchDeactivate':'StickGyroTouchDeactivateEnabled','TouchThreshold':'StickGyroTouchDeactivateThreshold',
 'TouchHoldoff':'StickGyroTouchDeactivateHoldoff','Smoothing':'StickGyroSmoothing'}.items()}


def validate(key,value):
    if key=='ViiperGyroBias':
        if not isinstance(value,list) or len(value) not in (0,4) or any(type(v) not in (int,float) or not math.isfinite(v) for v in value):raise ValueError('Invalid gyro bias')
        if value and (any(abs(v)>2000 for v in value[:3]) or not 0<=value[3]<=1000000):raise ValueError('Invalid gyro calibration range')
    elif type(DEFAULTS[key]) is bool:
        if type(value) is not bool:raise ValueError('Expected boolean')
    else:
        _,lo,hi=OPTIONS[key.removeprefix(PREFIX)]
        if type(value) is not int or not lo<=value<=hi:raise ValueError('Invalid gyro setting range')


def pressed(state,index):
    if index in (1,2):return (state.rt if index==1 else state.lt)>30
    bits=(0x200,0x100,0x1000,0x2000,0x4000,0x8000,0x80,0x40,1,2,4,8,0x10,0x20)
    if 3<=index<=16:return bool(state.buttons&bits[index-3])
    if 17<=index<=22:return bool(state.aux&(8,16,32,1,2,4)[index-17])
    return False


def curve(value,preset):
    def node(i):
        if preset==1:return .2 if i<=5 else .2+.3*(i-5)/10 if i<=15 else .5
        if preset==2:return .2 if i<=3 else .2+.3*(i-3)/7 if i<=10 else .5 if i<=25 else .5+.35*(i-25)/15 if i<=40 else .85
        return .5
    position=min(48,abs(value)/124);lo=int(position);fraction=position-lo
    return 2*(node(lo)*(1-fraction)+node(min(48,lo+1))*fraction)


def axis(value,sensitivity,preset,threshold,gain,anti,noise):
    boost=1+(gain/100-1)*min(1,max(0,(abs(value)-threshold)/(threshold*2))) if threshold>0 and gain>100 else 1
    scaled=value*curve(value,preset)*sensitivity*boost
    if noise>0 and abs(value)<noise*.5:return 0
    if anti>0:
        ramp=min(1,max(0,(abs(value)-noise*.5)/(noise*.5))) if noise>0 else 1
        offset=anti/100*32767*ramp
        scaled=math.copysign(offset+abs(scaled)*(1-offset/32767),scaled)
    return int(max(-32768,min(32767,scaled)))


def merge(x,y,gx,gy):
    x+=gx;y+=gy;magnitude=math.hypot(x,y)
    if magnitude>32767:x*=32767/magnitude;y*=32767/magnitude
    return int(x),int(y)


class StickGyro:
    def __init__(self,motion):
        self.motion=motion;self.previous=False;self.toggled=False;self.smoothed=None;self.last=None;self.touch_until=0.;self.signature=None
        self.live=(0.,0.,0,0,False)

    def apply(self,state,imu,now,settings):
        get=lambda key:settings.get(PREFIX+key,DEFAULTS[PREFIX+key])
        signature=tuple(get(k) for k in ('StickConversion','StickOrientationV2','StickGyroSmoothing','GyroSource','GyroActivationMode','GyroActivationButton'))
        if signature!=self.signature:
            self.motion.reset();self.smoothed=None;self.last=None;self.toggled=False;self.previous=False;self.signature=signature
        down=pressed(state,get('GyroActivationButton'));mode=get('GyroActivationMode')
        if mode==2 and down and not self.previous:self.toggled=not self.toggled
        self.previous=down
        active=mode==0 or (down if mode==1 else self.toggled)
        if not settings.get('ViiperStickGyroEnabled') or imu is None:
            self.live=(0.,0.,0,0,False);return state
        gyro=self.motion.update(imu,now-self.last if self.last is not None else .004);self.last=now
        if self.smoothed is not None and max(map(abs,self.smoothed))<5 and max(map(abs,gyro))>60:gyro=self.smoothed
        smooth=get('StickGyroSmoothing')/100
        if smooth:
            if self.smoothed is not None:gyro=tuple(smooth*a+(1-smooth)*b for a,b in zip(self.smoothed,gyro))
            self.smoothed=gyro
        x,y,z=gyro
        if get('StickOrientationV2'):y,z=-z,-y
        conversion=get('StickConversion')
        horizontal,vertical=self.motion.project(conversion==4) if conversion>=3 else ((z if conversion==1 else (y+z)/2 if conversion==2 else y),x)
        horizontal=-horizontal
        if get('StickInvertX'):horizontal=-horizontal
        if get('StickInvertY'):vertical=-vertical
        left=get('StickSelect')==0;px,py=(state.lx,state.ly) if left else (state.rx,state.ry)
        if get('StickGyroTouchDeactivateEnabled'):
            if math.hypot(px,py)/32767*100>=get('StickGyroTouchDeactivateThreshold'):self.touch_until=now+get('StickGyroTouchDeactivateHoldoff')/1000
            if now<self.touch_until:active=False
        params=(get('StickGyroCurvePreset'),get('StickGyroTightenThreshold'),get('StickGyroTightenGain'),get('StickGyroAntiDeadzone'),get('StickGyroAntiDeadzoneThreshold')/10)
        sensitivity=get('StickSensitivityV2')*10
        gx=axis(horizontal,sensitivity,*params) if active else 0
        gy=axis(vertical,sensitivity*get('StickGyroVerticalRatio')/100,*params) if active else 0
        self.live=(horizontal,vertical,gx,gy,active)
        if not active:return state
        mx,my=merge(px,py,gx,gy)
        return replace(state,**({'lx':mx,'ly':my} if left else {'rx':mx,'ry':my}))
