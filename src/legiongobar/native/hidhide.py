"""仅隐藏 Legion Go 的游戏手柄接口，并记录本次新增规则以便恢复。"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def cli_path():
    for root in ('ProgramFiles','ProgramFiles(x86)'):
        base=Path(os.environ.get(root,r'C:\Program Files'))/'Nefarius Software Solutions e.U./HidHide'
        for suffix in ('x64/HidHideCLI.exe','HidHideCLI.exe','CLI/HidHideCLI.exe'):
            path=base/suffix
            if path.is_file():return path
    return None


def is_gamepad(identifier):
    # 排除厂商命令、键盘、鼠标以及整个复合 USB 父设备。
    return bool(re.fullmatch(r'(?:HID|USB)\\VID_17EF&PID_618[0-9A-F](?:&[A-Z0-9_]+)*\\[^\r\n"\\]+',identifier,re.I) and re.search(r'&(?:MI_00|IG_[0-9A-F]{2})(?:&|\\)',identifier,re.I))


def devices():
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        service=win32com.client.GetObject(r'winmgmts:\\.\root\cimv2')
        return [item.PNPDeviceID for item in service.ExecQuery("SELECT PNPDeviceID FROM Win32_PnPEntity WHERE PNPDeviceID LIKE '%VID_17EF&PID_618%'") if is_gamepad(item.PNPDeviceID)]
    finally:pythoncom.CoUninitialize()


class Hide:
    def __init__(self,directory,runner=None):
        self.path=cli_path();self.journal=Path(directory)/'hidhide-session.json';self.runner=runner

    def run(self,*args):
        if self.runner:return self.runner(*args)
        if not self.path:raise RuntimeError('Install HidHide to hide the physical controller')
        result=subprocess.run([str(self.path),*args],capture_output=True,encoding='utf-8',errors='replace',timeout=8,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise RuntimeError(result.stderr.strip() or 'HidHide command failed')
        return result.stdout

    def listed(self,option,command):return set(re.findall(re.escape(command)+r'\s+"([^"]+)"',self.run(option),re.I))

    def save(self,state):
        self.journal.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.journal.with_suffix('.tmp');temporary.write_text(json.dumps(state),encoding='utf-8');os.replace(temporary,self.journal)

    def enable(self,identifiers=None):
        if self.journal.exists():self.restore()
        if '--inv-on' in self.run('--inv-state'):raise RuntimeError('HidHide inverse application mode must be disabled before emulation')
        ids=set(devices() if identifiers is None else identifiers)
        if not ids or not all(is_gamepad(value) for value in ids):raise RuntimeError('No Legion Go gamepad interface is available to hide')
        hidden=self.listed('--dev-list','--dev-hide');apps=self.listed('--app-list','--app-reg')
        executable=str(Path(sys.executable).resolve())
        state={'devices':sorted(ids-hidden),'baseline':sorted(hidden),'app':executable if executable.casefold() not in {v.casefold() for v in apps} else None,'cloak': '--cloak-on' in self.run('--cloak-state')}
        # 先记录再修改，即使中途失败也能恢复已经提交的操作。
        self.save(state)
        try:
            if state['app']:self.run('--app-reg',executable)
            for identifier in state['devices']:self.run('--dev-hide',identifier)
            if not state['cloak']:self.run('--cloak-on')
            current=self.listed('--dev-list','--dev-hide')
            if not ids.issubset(current) or '--cloak-on' not in self.run('--cloak-state'):raise RuntimeError('HidHide readback did not match requested state')
        except Exception:
            self.restore();raise

    def restore(self):
        if not self.journal.exists():return
        state=json.loads(self.journal.read_text(encoding='utf-8'))
        if not isinstance(state,dict) or not isinstance(state.get('devices'),list) or not all(isinstance(v,str) and is_gamepad(v) for v in state['devices']) or type(state.get('cloak')) is not bool:raise ValueError('Invalid HidHide recovery record')
        hidden=self.listed('--dev-list','--dev-hide')
        for identifier in state['devices']:
            if identifier in hidden:self.run('--dev-unhide',identifier)
        remaining=self.listed('--dev-list','--dev-hide')
        if any(identifier in remaining for identifier in state['devices']):raise RuntimeError('HidHide recovery did not remove the session rules')
        # 其他工具在运行期间增加隐藏规则时，保留它们的全局隐藏状态。
        if not state['cloak'] and remaining==set(state.get('baseline',[])):self.run('--cloak-off')
        if state.get('app')==str(Path(sys.executable).resolve()) and state['app'] in self.listed('--app-list','--app-reg'):self.run('--app-unreg',state['app'])
        self.journal.unlink()
