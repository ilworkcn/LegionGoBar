"""原项目配置保存范围，使用字段分组而非新增配置框架。"""
GROUPS={
    'TDP':('TDP','TDPBoostEnabled','TDPBoostSPPT','TDPBoostFPPT','LegionPerformanceMode'),
    'CPU Boost':('CPUBoost',),'CPU EPP':('CPUEPP',),'AMD features':('AMD*',),
    'FPS limit':('FPSLimit',),'Auto TDP':('AutoTDP*',),'OS power mode':('OSPowerMode',),
    'HDR':('HDREnabled',),'Resolution':('Resolution',),'Refresh rate':('RefreshRate',),
    'Sticky TDP':('StickyTDPEnabled','StickyTDPInterval'),'Performance overlay':('OSD',),
    'Nintendo layout':('LegionNintendoLayout',),'Vibration':('LegionVibration','LegionVibrationMode'),
    'Lighting':('LegionLight*','LegionPowerLight'),
    'Controller mappings':('LegionButton*','LegionGyro*','LegionLeft*','LegionRight*','LegionJoystick*'),
}


def selected(key, flags):
    for group,fields in GROUPS.items():
        if any(key.startswith(field[:-1]) if field.endswith('*') else key==field for field in fields):
            return flags.get(group,True)
    return True
