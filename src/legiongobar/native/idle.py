"""与上游一致的空闲熄屏、AC/DC 休眠计时，键鼠和四个手柄槽均计入活动。"""
import ctypes as C
import time
from .system import Gamepad, XInputState


class LastInput(C.Structure):
    _fields_=[('size',C.c_uint32),('tick',C.c_uint32)]


class IdlePolicy:
    def __init__(self):
        self.baseline=None;self.previous=None;self.screen_off=False;self.hibernate=False
        self.source=None;self.limit=None

    def next_action(self, now, keyboard_idle, gamepad_idle, on_ac, minutes, screen_saver, foreground_game):
        # 恢复后首次轮询与变更超时策略都重新起算，避免刚唤醒就再次休眠。
        if self.previous is None or now-self.previous>15 or self.source!=on_ac or self.limit!=minutes:
            self.baseline=now;self.hibernate=False;self.screen_off=False
        self.previous=now;self.source=on_ac;self.limit=minutes
        idle=min(keyboard_idle,gamepad_idle,now-self.baseline)
        if idle<60:self.screen_off=False
        if not minutes or idle<minutes*60:self.hibernate=False
        if minutes and idle>=minutes*60 and not foreground_game and not self.hibernate:
            self.hibernate=True;return 'hibernate'
        if screen_saver and idle>=60 and not self.screen_off:
            self.screen_off=True;return 'screen_off'
        return None


class IdleMonitor:
    def __init__(self):
        self.policy=IdlePolicy();self.gamepad=Gamepad();self.packets={};self.last_gamepad=time.monotonic()
        self.user=C.WinDLL('user32',use_last_error=True)
        self.user.GetLastInputInfo.argtypes=[C.POINTER(LastInput)];self.user.GetLastInputInfo.restype=C.c_int32
        self.user.PostMessageW.argtypes=[C.c_void_p,C.c_uint32,C.c_size_t,C.c_ssize_t];self.user.PostMessageW.restype=C.c_int32
        self.kernel=C.WinDLL('kernel32');self.kernel.GetTickCount.restype=C.c_uint32
        self.power=C.WinDLL('PowrProf',use_last_error=True)
        self.power.SetSuspendState.argtypes=[C.c_ubyte,C.c_ubyte,C.c_ubyte];self.power.SetSuspendState.restype=C.c_ubyte
        self.power.IsPwrHibernateAllowed.argtypes=[];self.power.IsPwrHibernateAllowed.restype=C.c_ubyte

    def available(self):return bool(self.power.IsPwrHibernateAllowed())

    def update(self, on_ac, minutes, screen_saver, foreground_game):
        now=time.monotonic()
        info=LastInput(C.sizeof(LastInput),0)
        if not self.user.GetLastInputInfo(C.byref(info)):raise OSError('Last input query failed')
        keyboard_idle=((self.kernel.GetTickCount()-info.tick)&0xffffffff)/1000
        if self.gamepad.dll:
            for slot in range(4):
                state=XInputState()
                if self.gamepad.dll.XInputGetState(slot,C.byref(state))==0:
                    if self.packets.get(slot)!=state.packet:self.last_gamepad=now
                    self.packets[slot]=state.packet
                else:self.packets.pop(slot,None)
        action=self.policy.next_action(now,keyboard_idle,now-self.last_gamepad,on_ac,minutes,screen_saver,foreground_game)
        if action=='hibernate':
            if not self.available() or not self.power.SetSuspendState(1,0,0):
                raise OSError('Windows hibernation is unavailable or failed')
            self.policy=IdlePolicy()
        elif action=='screen_off':
            if not self.user.PostMessageW(0xffff,0x112,0xf170,2):raise OSError('Monitor power command failed')
