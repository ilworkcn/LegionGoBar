"""前置按键映射以及按传感器来源保存的陀螺仪、加速度计轴向设置。"""
from dataclasses import replace
from .viiper_reports import clamp

SOURCES=('Left','Right','Mixed','Handheld')
IDENTITY=('X','Y','Z','0','0','0')
FIELDS={f'Viiper{sensor}{part}{axis}':(sensor,part,axis) for sensor in ('Gyro','Accel') for part in ('Matrix','Invert') for axis in 'XYZ'}


def parse(text):
    result={source:IDENTITY for source in SOURCES}
    if not isinstance(text,str) or len(text)>2048:raise ValueError('Invalid sensor tuning')
    for block in text.split('|'):
        if not block:continue
        source,csv=block.split('=',1);parts=tuple(csv.split(','))
        if source not in result or len(parts)!=6 or any(v not in 'XYZ' or len(v)!=1 for v in parts[:3]) or any(v not in ('0','1') for v in parts[3:]):raise ValueError('Invalid sensor axis mapping')
        result[source]=parts
    return result


def field_values(settings):
    source=settings.get('ViiperGyroSource','Left')
    if source not in SOURCES:source='Left'
    configs={sensor:parse(settings.get('Viiper'+sensor+'Tuning',''))[source] for sensor in ('Gyro','Accel')}
    return {name:configs[sensor]['XYZ'.index(axis)] if part=='Matrix' else configs[sensor][3+'XYZ'.index(axis)]=='1' for name,(sensor,part,axis) in FIELDS.items()}


def edit(settings,name,value):
    sensor,part,axis=FIELDS[name];key='Viiper'+sensor+'Tuning';config=parse(settings.get(key,''))
    source=settings.get('ViiperGyroSource','Left')
    if source not in SOURCES:source='Left'
    row=list(config[source]);index='XYZ'.index(axis)
    if part=='Matrix':
        if value not in ('X','Y','Z'):raise ValueError('Invalid sensor axis')
        row[index]=value
    else:
        if type(value) is not bool:raise ValueError('Expected a boolean')
        row[index+3]='1' if value else '0'
    config[source]=row
    return key,'|'.join(name+'='+','.join(row) for name,row in config.items())


def apply(state,settings):
    buttons=state.buttons;click=state.click
    for bit,key,default in ((0x40,'ViiperDesktopButtonTarget','guide'),(0x80,'ViiperPageButtonTarget','touchpad')):
        if not state.aux&bit:continue
        target=settings.get(key,default)
        if target=='touchpad':click=True
        else:buttons|={'guide':0x400,'share':0x20,'options':0x10,'l3':0x40,'r3':0x80,'none':0}[target]
    imu=state.imu
    if imu:
        source=settings.get('ViiperGyroSource','None')
        output=[]
        for sensor,offset in (('Gyro',0),('Accel',3)):
            tuning=parse(settings.get('Viiper'+sensor+'Tuning','')).get(source,IDENTITY)
            output.extend(clamp(imu[offset+'XYZ'.index(axis)]*(-1 if inverse=='1' else 1)) for axis,inverse in zip(tuning[:3],tuning[3:]))
        imu=tuple(output)
    return replace(state,buttons=buttons,click=click,aux=state.aux&~0xc0,imu=imu)
