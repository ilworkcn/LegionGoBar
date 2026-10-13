"""复刻原版摇杆、扳机死区及响应曲线，配置格式可直接互换。"""
from dataclasses import replace
import math

STICK={'Shape':0,'DX':0.,'DY':0.,'ADX':0.,'ADY':0.,'CX':0,'CY':0}
TRIGGER={'DZ':0.,'RM':1.,'AD':0.,'C':0}
FIELDS={}
for side in ('LS','RS','LT','RT'):
    for key,value in (STICK if side.endswith('S') else TRIGGER).items():
        field={'CX':'CurveX','CY':'CurveY','C':'Curve'}.get(key,key)
        FIELDS['Viiper'+side+field]=(side,key)


def defaults():return {side:dict(STICK if side.endswith('S') else TRIGGER) for side in ('LS','RS','LT','RT')}


def parse(text):
    result=defaults()
    if not isinstance(text,str) or len(text)>4096:raise ValueError('Invalid stick and trigger configuration')
    for block in text.split('|'):
        if not block:continue
        side,body=block.split(':',1)
        if side not in result:raise ValueError('Unknown stick or trigger')
        for pair in body.split(';'):
            key,raw=pair.split('=',1)
            if key not in result[side]:raise ValueError('Unknown shaping field')
            value=float(raw)
            if not math.isfinite(value):raise ValueError('Shaping values must be finite')
            if key in ('Shape','CX','CY','C'):
                if value!=int(value) or not 0<=value<=(2 if key=='Shape' else 5):raise ValueError('Invalid response curve')
                value=int(value)
            elif not 0<=value<=1:raise ValueError('Shaping percentages must be between 0 and 100')
            result[side][key]=value
    return result


def serialize(config):
    return '|'.join(side+':'+ ';'.join(f'{key}={value:g}' for key,value in values.items()) for side,values in config.items())


def values(text):
    cfg=parse(text)
    return {name:round(cfg[side][key]*100) if key not in ('Shape','CX','CY','C') else cfg[side][key] for name,(side,key) in FIELDS.items()}


def edit(text,name,value):
    cfg=parse(text);side,key=FIELDS[name]
    if type(value) is not int:raise ValueError('Expected an integer shaping value')
    cfg[side][key]=value if key in ('Shape','CX','CY','C') else value/100
    encoded=serialize(cfg);parse(encoded)
    return encoded


def curve(value,kind):
    magnitude=abs(value)
    if kind==1:magnitude*=magnitude
    elif kind==2:magnitude=math.sqrt(magnitude)
    elif kind==3:magnitude=1 if magnitude>.02 else 0
    elif kind==4:magnitude=magnitude*magnitude*(3-2*magnitude)
    elif kind==5:magnitude=0 if magnitude<.3 else (magnitude-.3)/.7
    return math.copysign(magnitude,value)


def stick(x,y,cfg):
    x/=32768;y/=32768;dz=max(cfg['DX'],cfg['DY']);mag=math.hypot(x,y)
    if cfg['Shape'] in (0,1):
        if mag<=dz or mag<=1e-6:x=y=0.
        elif cfg['Shape']==0:
            scale=(mag-dz)/(max(1e-6,1-dz)*mag);x*=scale;y*=scale
    else:
        x=math.copysign(max(0,abs(x)-cfg['DX'])/max(1e-6,1-cfg['DX']),x)
        y=math.copysign(max(0,abs(y)-cfg['DY'])/max(1e-6,1-cfg['DY']),y)
    output=[]
    for value,axis in ((x,'X'),(y,'Y')):
        value=curve(value,cfg['C'+axis]);anti=cfg['AD'+axis]
        if value and anti:value=math.copysign(anti+(1-anti)*abs(value),value)
        output.append(int(max(-1,min(1,value))*32767))
    return tuple(output)


def trigger(raw,cfg):
    value=raw/255
    if value<=cfg['DZ']:return 0
    value=curve((value-cfg['DZ'])/max(1e-6,1-cfg['DZ']),cfg['C'])
    value=cfg['AD']+(1-cfg['AD'])*value
    return int(max(0,min(1,value*cfg['RM']))*255)


def transform(state,config):
    # 默认配置保持原始整数不变，避免仅开启虚拟手柄便损失摇杆满量程。
    if config==defaults():return state
    lx,ly=stick(state.lx,state.ly,config['LS']);rx,ry=stick(state.rx,state.ry,config['RS'])
    return replace(state,lx=lx,ly=ly,rx=rx,ry=ry,lt=trigger(state.lt,config['LT']),rt=trigger(state.rt,config['RT']))
