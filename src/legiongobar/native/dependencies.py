"""首次设置中可选组件的检测和安装。"""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request

USBIP_URL='https://github.com/vadimgrn/usbip-win2/releases/download/v.0.9.7.8/USBip-0.9.7.8-x64.exe'
USBIP_SHA256='44451fe06f4186125c2a5ecd25b099c5560a61a60b1e56f5a0758e77a60afa44'
PACKAGES={'HidHide':'NefariusSoftwareSolutions.HidHide','Rtss':'Guru3D.RTSS'}


def status():
    from .viiper import driver_path
    from .hidhide import cli_path
    from .rtss import Rtss
    rtss=Rtss();rtss.discover()
    return {'Usbip':driver_path() is not None,'HidHide':cli_path() is not None,'Rtss':rtss.installed}


def download_usbip(directory):
    path=Path(directory)/'downloads/USBip-0.9.7.8-x64.exe';path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==USBIP_SHA256:return path
    temporary=path.with_suffix('.download')
    try:
        request=urllib.request.Request(USBIP_URL,headers={'User-Agent':'LegionGoBar'})
        digest=hashlib.sha256();size=0
        with urllib.request.urlopen(request,timeout=30) as response,temporary.open('wb') as output:
            while chunk:=response.read(1024*1024):
                size+=len(chunk)
                if size>256*1024*1024:raise ValueError('Installer exceeds expected size')
                digest.update(chunk);output.write(chunk)
        if digest.hexdigest()!=USBIP_SHA256:raise ValueError('USBip installer checksum does not match the official release')
        os.replace(temporary,path);return path
    finally:temporary.unlink(missing_ok=True)


def elevated_installer(path):
    class Execute(C.Structure):
        _fields_=[('cbSize',W.DWORD),('fMask',W.ULONG),('hwnd',W.HWND),('lpVerb',W.LPCWSTR),('lpFile',W.LPCWSTR),('lpParameters',W.LPCWSTR),('lpDirectory',W.LPCWSTR),('nShow',C.c_int),('hInstApp',W.HINSTANCE),('lpIDList',C.c_void_p),('lpClass',W.LPCWSTR),('hkeyClass',W.HKEY),('dwHotKey',W.DWORD),('hIcon',W.HANDLE),('hProcess',W.HANDLE)]
    shell=C.WinDLL('shell32',use_last_error=True);kernel=C.WinDLL('kernel32',use_last_error=True)
    shell.ShellExecuteExW.argtypes=[C.POINTER(Execute)];shell.ShellExecuteExW.restype=W.BOOL
    kernel.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];kernel.WaitForSingleObject.restype=W.DWORD
    kernel.GetExitCodeProcess.argtypes=[W.HANDLE,C.POINTER(W.DWORD)];kernel.GetExitCodeProcess.restype=W.BOOL
    kernel.CloseHandle.argtypes=[W.HANDLE];kernel.CloseHandle.restype=W.BOOL
    info=Execute();info.cbSize=C.sizeof(info);info.fMask=0x40;info.lpVerb='runas';info.lpFile=str(path);info.lpParameters='/NORESTART';info.nShow=1
    if not shell.ShellExecuteExW(C.byref(info)):raise C.WinError(C.get_last_error())
    try:
        if kernel.WaitForSingleObject(info.hProcess,600000)!=0:raise RuntimeError('Installer is still running; finish it before retrying')
        code=W.DWORD()
        if not kernel.GetExitCodeProcess(info.hProcess,C.byref(code)):raise C.WinError(C.get_last_error())
        if code.value not in (0,3010):raise RuntimeError(f'Installer exited with code {code.value}')
    finally:kernel.CloseHandle(info.hProcess)


def install(name,directory):
    if name not in ('Usbip',*PACKAGES):raise ValueError('Unknown dependency')
    if status()[name]:return
    if name=='Usbip':elevated_installer(download_usbip(directory))
    else:
        executable=shutil.which('winget')
        if not executable:raise RuntimeError('Install Windows App Installer to use winget')
        result=subprocess.run([executable,'install','--id',PACKAGES[name],'--exact','--source','winget','--accept-package-agreements','--accept-source-agreements','--silent','--disable-interactivity'],capture_output=True,encoding='utf-8',errors='replace',timeout=600,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode not in (0,3010):raise RuntimeError(result.stdout.strip() or result.stderr.strip() or 'Dependency installation failed')
    if not status()[name]:raise RuntimeError('Installation completed; restart Windows to finish driver setup')
