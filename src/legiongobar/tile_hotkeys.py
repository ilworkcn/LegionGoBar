"""快捷磁贴的键盘和手柄组合；只在组合按下沿触发一次。"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence

COMBOS={'Menu + Up':0x11,'Menu + Down':0x12,'Menu + Left':0x14,'Menu + Right':0x18,
        'View + A':0x1020,'View + B':0x2020,'View + X':0x4020,'View + Y':0x8020}


def native_key(text):
    sequence=QKeySequence.fromString(text,QKeySequence.PortableText)
    if sequence.count()!=1 or sequence.isEmpty():raise ValueError('Use one keyboard shortcut')
    combination=sequence[0];key=combination.key();modifiers=combination.keyboardModifiers()
    mods=0
    for flag,value in ((Qt.AltModifier,1),(Qt.ControlModifier,2),(Qt.ShiftModifier,4),(Qt.MetaModifier,8)):
        if modifiers & flag:mods|=value
    if Qt.Key_A<=key<=Qt.Key_Z or Qt.Key_0<=key<=Qt.Key_9:vk=int(key)
    elif Qt.Key_F1<=key<=Qt.Key_F24:vk=0x70+int(key)-int(Qt.Key_F1)
    else:
        mapping={Qt.Key_Space:0x20,Qt.Key_Up:0x26,Qt.Key_Down:0x28,Qt.Key_Left:0x25,Qt.Key_Right:0x27,
                 Qt.Key_Home:0x24,Qt.Key_End:0x23,Qt.Key_PageUp:0x21,Qt.Key_PageDown:0x22}
        if key not in mapping:raise ValueError('Unsupported shortcut key')
        vk=mapping[key]
    if not mods:raise ValueError('Shortcut requires Ctrl, Alt, Shift or Win')
    return mods,vk


def validate(bindings):
    if not isinstance(bindings,dict):raise ValueError('Invalid shortcut configuration')
    keyboard={(3,ord('G'))};gamepad=set()
    for value in bindings.values():
        if not isinstance(value,dict):raise ValueError('Invalid shortcut binding')
        if value.get('keyboard'):
            native=native_key(value['keyboard'])
            if native in keyboard:raise ValueError('Keyboard shortcut is already assigned')
            keyboard.add(native)
        combo=value.get('gamepad','')
        if combo:
            if combo not in COMBOS:raise ValueError('Unknown controller shortcut')
            if combo in gamepad:raise ValueError('Controller shortcut is already assigned')
            gamepad.add(combo)


def fired(bindings,previous,current):
    result=[]
    for key,value in bindings.items():
        mask=COMBOS.get(value.get('gamepad',''),0)
        if mask and current & mask==mask and previous & mask!=mask:result.append(key)
    return result
