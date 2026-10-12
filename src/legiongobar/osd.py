"""生成 RTSS 文本，配置格式沿用原项目的分号键值格式。"""
import datetime
import re

ITEMS=('AppName','Time','FPS','Battery','ControllerBattery','Memory','VRAM','CPU','CPUClock','GPU','GPUClock','FrameBudget','Fan','AutoTDP','TDPLimits')
DEFAULTS={1:('Time','FPS','Battery'),2:('Time','FPS','Battery','CPU','GPU','FrameBudget','Fan'),3:ITEMS}


def parse(config):
    if not isinstance(config,str) or len(config)>8192:raise ValueError('Invalid OSD configuration')
    result={}
    for part in config.split(';'):
        if not part:continue
        key,separator,value=part.partition(':')
        if not separator:raise ValueError('OSD configuration requires key:value')
        if key in ('TextColor','LabelColor','BackgroundColor') or key.endswith('_Color'):
            if value!='DEFAULT' and not re.fullmatch(r'[0-9a-fA-F]{6}|[0-9a-fA-F]{8}',value):raise ValueError('Invalid OSD color')
        if key in ('TextSize','Opacity') or key.endswith('_Columns'):
            number=int(value)
            low,high=(50,300) if key=='TextSize' else (10,100) if key=='Opacity' else (1,10)
            if not low<=number<=high:raise ValueError('Invalid OSD numeric option')
        result[key]=value
    return result


def render(level,config,metrics,values):
    if not level:return None
    options=parse(config)
    enabled=options.get(f'L{level}',','.join(DEFAULTS[level])).split(',')
    order=options.get(f'L{level}_Order',','.join(ITEMS)).split(',')
    order+= [key for key in enabled if key not in order]
    battery=metrics.get('BatteryLevel')
    clock=datetime.datetime.now().strftime('%H:%M' if options.get('Clock24Hour','false').lower() in ('1','true') else '%I:%M %p')
    shown={
        'AppName':'<APP>','Time':clock,'FPS':'<FR> FPS  <FT> ms',
        'Battery':f'{battery}%' if battery is not None else '--',
        'Memory':f"{metrics.get('MemoryUsage','--')}%",'CPU':f"{metrics.get('CPUUsage','--')}%",
        'CPUClock':str(values.get('CPUClock','--')),'GPU':str(values.get('GPUUsage','--')),
        'GPUClock':str(values.get('GPUClock','--')),'VRAM':str(values.get('VRAMUsage','--')),
        'FrameBudget':'<FT> ms','Fan':str(values.get('LegionCPUFanRPM','--'))+' RPM',
        'TDPLimits':str(values.get('CurrentTDP','--')),'AutoTDP':str(values.get('AutoTDPMLStatus','--')),
        'ControllerBattery':f"L {values.get('ControllerBatteryLeft','--')}% R {values.get('ControllerBatteryRight','--')}%",
    }
    opacity=int(options.get('Opacity',100))/100
    def color(value):
        value=value[-6:]
        return ''.join(f'{round(int(value[i:i+2],16)*opacity):02X}' for i in (0,2,4))
    text_color=color(options.get('TextColor','FFFFFF'))
    label_color=options.get('LabelColor','58C8ED')
    if label_color=='DEFAULT':label_color='58C8ED'
    cells=[]
    for item in order:
        if item not in enabled or item not in shown:continue
        label=options.get(f'L{level}_{item}_Color',label_color)
        if label=='DEFAULT':label=label_color
        cells.append(f'<C={color(label)}>{item} <C={text_color}>{shown[item]}')
    columns=int(options.get(f'L{level}_Columns',3 if level==1 else 1))
    rows=[' | '.join(cells[i:i+columns]) for i in range(0,len(cells),columns)]
    custom=options.get(f'L{level}_Custom','')
    if custom:rows.append(custom)
    background=options.get('BackgroundColor','80000000')
    return f'<P=0,0><L0><C={background}><B=0,0>\b<C><S={options.get("TextSize",100)}>'+ '\n'.join(rows)+'<S><C>'


UI_FIELDS={'OSDColumns':'_Columns','OSDTextSize':'TextSize','OSDTextColor':'TextColor',
           'OSDLabelColor':'LabelColor','OSDOpacity':'Opacity','OSDCustomTags':'_Custom','Osd24HourClock':'Clock24Hour'}


def editor_values(config,level):
    options=parse(config)
    defaults={'OSDColumns':3 if level==1 else 1,'OSDTextSize':100,'OSDTextColor':'#FFFFFF',
              'OSDLabelColor':'#58C8ED','OSDOpacity':100,'OSDCustomTags':'','Osd24HourClock':False}
    for key,field in UI_FIELDS.items():
        value=options.get(f'L{level}'+field if field.startswith('_') else field)
        if value is None:continue
        if key in ('OSDColumns','OSDTextSize','OSDOpacity'):value=int(value)
        elif key=='Osd24HourClock':value=value.lower() in ('1','true')
        elif key.endswith('Color'):value='#'+(value if value!='DEFAULT' else '58C8ED')
        defaults[key]=value
    return defaults


def edit(config,level,key,value):
    options=parse(config)
    field=UI_FIELDS[key]
    if key.endswith('Color'):value=str(value).lstrip('#').upper()
    if key=='Osd24HourClock':
        if type(value) is not bool:raise ValueError('Clock option requires boolean')
        value=str(value).lower()
    if ';' in str(value):raise ValueError('OSD value cannot contain a semicolon')
    options[f'L{level}'+field if field.startswith('_') else field]=str(value)
    result=';'.join(f'{k}:{v}' for k,v in options.items())
    parse(result)
    return result
