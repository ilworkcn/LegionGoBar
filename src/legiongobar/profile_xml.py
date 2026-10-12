"""读取原项目 GameProfile / GoTweaksProfiles XML，保留未移植字段以便后续迁移。"""
import json
import xml.etree.ElementTree as ET
from pathlib import PureWindowsPath
from .profiles import canonical, profile_key, validate_record

ALIASES={'StickyTDP':'StickyTDPEnabled','OverlayLevel':'OSD'}


def scalar(element):
    if element.attrib.get('{http://www.w3.org/2001/XMLSchema-instance}nil')=='true':return None
    text=(element.text or '').strip()
    if not text:return None
    if text.lower() in ('true','false'):return text.lower()=='true'
    try:return int(text)
    except ValueError:return text


def parse_profile(element,global_profile=False):
    game_id=element.find('GameId')
    path=game_id.findtext('Path','') if game_id is not None else ''
    name=game_id.findtext('Name','') if game_id is not None else ''
    if not global_profile and (name=='global' or path=='global'):global_profile=True
    if not global_profile and (not path or not PureWindowsPath(path).is_absolute()):
        raise ValueError('GoTweaks game profile requires an absolute executable path')
    record={'name':name or PureWindowsPath(path).stem,'settings':{},'dc':{},'enabled':True}
    unconverted={}
    for item in element:
        tag=item.tag
        if tag=='GameId':continue
        if tag=='Use':
            value=scalar(item)
            if type(value) is not bool:raise ValueError('Invalid GoTweaks Use value')
            record['enabled']=value
            continue
        scope='dc' if tag.endswith('_DC') else 'settings'
        key=ALIASES.get(tag.removesuffix('_DC'),tag.removesuffix('_DC'))
        value=scalar(item)
        if value is None:continue
        if profile_key(key):
            if key.startswith('LegionButton'):
                try:
                    value=json.loads(value) if isinstance(value,str) else value
                    if not isinstance(value,dict) or set(value)!={'type','mappings'}:raise ValueError()
                except (ValueError,TypeError):
                    unconverted[tag]=ET.tostring(item,encoding='unicode');continue
            record[scope][key]=value
        else:unconverted[tag]=ET.tostring(item,encoding='unicode')
    if unconverted:record['upstream_xml']=unconverted
    validate_record(record)
    return None if global_profile else canonical(path),record


def read_profiles(path):
    data=path.read_bytes()
    if len(data)>16*1024*1024:raise ValueError('Profile file is too large')
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():raise ValueError('XML entities are not supported')
    try:root=ET.fromstring(data)
    except ET.ParseError as exc:raise ValueError('Invalid profile XML') from exc
    result={'version':1,'profiles':{}}
    if root.tag=='GameProfile':
        entries=[(root,False)]
    elif root.tag=='GoTweaksProfiles':
        if root.get('Version','1') not in ('1','2'):raise ValueError('Unsupported GoTweaks export version')
        entries=[(entry,False) for entry in root.findall('GameProfiles/GameProfile')]
        global_element=root.find('GlobalProfile')
        if global_element is not None:entries.insert(0,(global_element,True))
    else:raise ValueError('Expected GoTweaksProfiles or GameProfile XML')
    for element,is_global in entries:
        key,record=parse_profile(element,is_global)
        if key is None:result['global_profile']=record
        else:
            if key in result['profiles']:raise ValueError('Duplicate executable profile')
            result['profiles'][key]=record
    if not entries:raise ValueError('No profiles in XML')
    return result
