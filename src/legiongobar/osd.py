"""生成 RTSS 文本，配置格式沿用原项目的分号键值格式。"""
import datetime
import re

ITEMS=('AppName','Time','FPS','Battery','ControllerBattery','Memory','VRAM','CPU','CPUClock','GPU','GPUClock','FrameBudget','Fan','AutoTDP','TDPLimits','FrametimeGraph')
DEFAULTS={1:('Time','FPS','Battery'),2:('Time','FPS','Battery','CPU','GPU','FrameBudget','Fan','FrametimeGraph'),3:tuple(item for item in ITEMS if item!='TDPLimits')}


def parse(config):
    if not isinstance(config,str) or len(config)>8192:raise ValueError('Invalid OSD configuration')
    result={}
    for part in config.split(';'):
        if not part:continue
        key,separator,value=part.partition(':')
        if not separator:raise ValueError('OSD configuration requires key:value')
        if key in ('TextColor','LabelColor','BackgroundColor') or key.endswith('_Color'):
            sentinel='DYNAMIC' if key=='TextColor' else 'DEFAULT' if key=='LabelColor' or key.endswith('_Color') else ''
            if value!=sentinel and not re.fullmatch(r'[0-9a-fA-F]{6}|[0-9a-fA-F]{8}',value):raise ValueError('Invalid OSD color')
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
    present=values.get('PresentMon',{})
    if present.get('live'):
        rendered=present.get('rendered_fps',0)
        shown['FPS']=f"{rendered} FPS  <FT> ms"
        if present.get('generated_fps',0)>0:
            shown['FPS']=f"{rendered}/{present['displayed_fps']} FPS [FG]  <FT> ms"
        shown['FrameBudget']=f"CPU {present.get('cpu_busy',0):.0f}% | GPU {present.get('gpu_busy',0):.0f}%"
    else:shown.pop('FrameBudget',None)
    def unit(key,suffix,source=values):
        value=source.get(key)
        return f'{value:g}{suffix}' if isinstance(value,(int,float)) else ''
    for item in ('CPU','GPU'):
        usage=unit(item+'Usage','%',metrics if item=='CPU' else values) or '--'
        shown[item]=' '.join(filter(None,(usage,unit(item+'Power','W'),unit(item+'Temperature','°C'),
            unit(item+'Clock',' MHz',metrics if item=='CPU' else values) if item+'Clock' in enabled else '')))
    for item in ('CPUClock','GPUClock'):shown.pop(item,None)
    if metrics.get('MemoryTotal'):
        shown['Memory']+=f" {metrics['MemoryUsed']/2**30:.1f}/{metrics['MemoryTotal']/2**30:.1f} GB"
    if values.get('VRAMUsage') is not None:
        shown['VRAM']=f"{values['VRAMUsage']/1024:.1f} GB"
        if values.get('VRAMClock') is not None:shown['VRAM']+=f" {values['VRAMClock']} MHz"
    opacity=int(options.get('Opacity',100))/100
    def color(value):
        value=value[-6:]
        return ''.join(f'{int(int(value[i:i+2],16)*opacity):02X}' for i in (0,2,4))
    dynamic=options.get('TextColor')=='DYNAMIC'
    text_color=color('FFFFFF' if dynamic else options.get('TextColor','FFFFFF'))
    label_color=options.get('LabelColor','DEFAULT')
    labels={'Battery':'BATT','ControllerBattery':'Ctrl','Memory':'RAM','FrameBudget':'BND','Fan':'FAN','TDPLimits':'Limits'}
    palette={'Battery':'008B8B','ControllerBattery':'008B8B','CPU':'40E0D0','GPU':'7CFC00','Memory':'800080',
             'VRAM':'00FFFF','Fan':'00FFFF','AutoTDP':'00BFFF','TDPLimits':'FFA500','FrameBudget':'FFA500'}
    def dynamic_color(item):
        value=battery if item=='Battery' else metrics.get(item+'Usage') if item in ('CPU','Memory') else values.get(item+'Usage')
        if not dynamic or value is None:return text_color
        thresholds=(15,30,50,70) if item=='Battery' else (30,50,70,85)
        colors=('FF0000','FF8000','FFFF00','80FF00','00FF00') if item=='Battery' else ('00FF00','80FF00','FFFF00','FF8000','FF0000')
        return color(colors[next((i for i,t in enumerate(thresholds) if value<t),4)])
    graph=f'<C={text_color}><G=<FT>><C>'
    samples=values.get('FrameSamples',[])
    if len(samples)==1:
        sample=samples[0]
        if all(key in sample for key in ('frame_min','frame_avg','frame_max')):
            graph+=f"\n<S=50><C={color('808080')}>min:<C={color('00FF00')}>{sample['frame_min']:.1f}ms <C={color('808080')}>avg:<C={color('FFFF00')}>{sample['frame_avg']:.1f}ms <C={color('808080')}>max:<C={color('FF6600')}>{sample['frame_max']:.1f}ms<C><S={options.get('TextSize',100)}>"
    pinned=options.get('FrametimeGraphPinned','false').lower() in ('true','1')
    cells=[]
    for item in order:
        if item=='FrametimeGraph' and item in enabled:
            if not pinned:cells.append(graph)
            continue
        if item not in enabled or item not in shown:continue
        label=options.get(f'L{level}_{item}_Color',label_color)
        if label=='DEFAULT':label=palette.get(item,'FFFFFF')
        if item in ('Time','AppName'):
            cells.append(f"<C={color('FF0000') if item=='AppName' else text_color}>{shown[item]}")
        else:cells.append(f'<C={color(label)}>{labels.get(item,item)} <C={dynamic_color(item)}>{shown[item]}')
    columns=int(options.get(f'L{level}_Columns',3 if level==1 else 1))
    custom=options.get(f'L{level}_Custom','')
    if custom:cells.append(custom)
    rows=[' | '.join(cells[i:i+columns]) for i in range(0,len(cells),columns)]
    if pinned and 'FrametimeGraph' in enabled:rows.append(graph)
    return f'<S={options.get("TextSize",100)}>'+ '\n'.join(rows)+'<S><C>'


UI_FIELDS={'OSDTextColorDynamic':'TextColor','OSDLabelColorDefault':'LabelColor','OSDColumns':'_Columns','OSDTextSize':'TextSize','OSDTextColor':'TextColor',
           'OSDLabelColor':'LabelColor','OSDOpacity':'Opacity','OSDCustomTags':'_Custom','Osd24HourClock':'Clock24Hour','FrametimeGraphPinned':'FrametimeGraphPinned'}


def editor_values(config,level):
    options=parse(config)
    defaults={'OSDColumns':3 if level==1 else 1,'OSDTextSize':100,'OSDTextColor':'#FFFFFF',
              'OSDLabelColor':'#58C8ED','OSDOpacity':100,'OSDCustomTags':'','Osd24HourClock':False,'FrametimeGraphPinned':False}
    defaults.update(OSDTextColorDynamic=options.get('TextColor')=='DYNAMIC',OSDLabelColorDefault=options.get('LabelColor','DEFAULT')=='DEFAULT')
    for key,field in UI_FIELDS.items():
        if key in ('OSDTextColorDynamic','OSDLabelColorDefault'):continue
        value=options.get(f'L{level}'+field if field.startswith('_') else field)
        if value is None:continue
        if key in ('OSDColumns','OSDTextSize','OSDOpacity'):value=int(value)
        elif key in ('Osd24HourClock','FrametimeGraphPinned'):value=value.lower() in ('1','true')
        elif key.endswith('Color'):value='#'+(value if value not in ('DEFAULT','DYNAMIC') else 'FFFFFF')
        defaults[key]=value
    return defaults


def edit(config,level,key,value):
    options=parse(config)
    field=UI_FIELDS[key]
    if key in ('OSDTextColorDynamic','OSDLabelColorDefault'):
        if type(value) is not bool:raise ValueError('Color mode requires boolean')
        value=('DYNAMIC' if key=='OSDTextColorDynamic' else 'DEFAULT') if value else 'FFFFFF'
    if key.endswith('Color'):value=str(value).lstrip('#').upper()
    if key in ('Osd24HourClock','FrametimeGraphPinned'):
        if type(value) is not bool:raise ValueError('Clock option requires boolean')
        value=str(value).lower()
    if ';' in str(value):raise ValueError('OSD value cannot contain a semicolon')
    options[f'L{level}'+field if field.startswith('_') else field]=str(value)
    result=';'.join(f'{k}:{v}' for k,v in options.items())
    parse(result)
    return result
