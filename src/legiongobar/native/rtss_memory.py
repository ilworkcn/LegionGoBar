"""RTSS v2 共享内存：读取游戏帧率，发布独立 OSD 槽位。

布局依据 RTSS SDK RTSSSharedMemory.h；按头部偏移访问，不假定数组容量。
"""
import ctypes as C
import os
import struct
from contextlib import contextmanager

SIGNATURE=0x52545353


class SharedBuffer:
    def __init__(self, buffer):
        self.buffer=buffer
        if len(buffer)<40:raise ValueError('RTSS header is incomplete')
        signature,self.version,self.app_size,self.app_offset,self.apps,self.osd_size,self.osd_offset,self.slots=struct.unpack_from('<8I',buffer)
        if signature!=SIGNATURE or self.version>>16!=2:raise ValueError('RTSS memory is unavailable or incompatible')
        for size,offset,count,minimum in ((self.app_size,self.app_offset,self.apps,284),(self.osd_size,self.osd_offset,self.slots,512)):
            if size<minimum or offset<40 or count>4096 or offset+size*count>len(buffer):
                raise ValueError('RTSS array is outside the mapped memory')

    def samples(self, now_ms):
        result=[]
        for index in range(self.apps):
            offset=self.app_offset+index*self.app_size
            pid=struct.unpack_from('<I',self.buffer,offset)[0]
            if not pid:continue
            flags,start,end,frames,frame_us=struct.unpack_from('<5I',self.buffer,offset+264)
            elapsed=(end-start)&0xffffffff
            if not start or not elapsed or ((now_ms-end)&0xffffffff)>3000:continue
            name=bytes(self.buffer[offset+4:offset+264]).split(b'\0',1)[0].decode('mbcs',errors='replace')
            result.append({'pid':pid,'name':name,'fps':1000*frames/elapsed,'frame_ms':frame_us/1000,'flags':flags})
        return result

    def publish(self, owner, text):
        owner=owner.encode('ascii')
        if not owner or len(owner)>255:raise ValueError('Invalid OSD owner')
        entries=[self.osd_offset+i*self.osd_size for i in range(1,self.slots)]
        def owned(offset):return bytes(self.buffer[offset+256:offset+512]).split(b'\0',1)[0]
        own=next((offset for offset in entries if owned(offset)==owner),None)
        if text is None:
            if own is None:return False
            self.buffer[own:own+512]=bytes(512)
            if self.version>=0x20007 and self.osd_size>=4608:self.buffer[own+512:own+4608]=bytes(4096)
        else:
            if own is None:own=next((offset for offset in entries if not owned(offset)),None)
            if own is None:raise OSError('No free RTSS OSD slot')
            extended=self.version>=0x20007 and self.osd_size>=4608
            size=4096 if extended else 256
            encoded=text.encode('mbcs',errors='replace')
            if len(encoded)>=size:raise ValueError('OSD text is too long')
            self.buffer[own+256:own+512]=owner.ljust(256,b'\0')
            start=own+512 if extended else own
            self.buffer[start:start+size]=encoded.ljust(size,b'\0')
        if self.version >= 0x20014 and self.osd_size >= 299520:
            self.buffer[own+266752:own+299520]=bytes(32768)
        struct.pack_into('<I',self.buffer,32,(struct.unpack_from('<I',self.buffer,32)[0]+1)&0xffffffff)
        return True


class MemoryInfo(C.Structure):
    _fields_=[('base',C.c_void_p),('allocation',C.c_void_p),('allocation_protect',C.c_uint32),
              ('partition',C.c_uint16),('size',C.c_size_t),('state',C.c_uint32),('protect',C.c_uint32),('type',C.c_uint32)]


class RtssMemory:
    def __init__(self, memory_name='RTSSSharedMemoryV2'):
        self.memory_name=memory_name
        self.owner=f'LegionGoBar-{os.getpid()}'
        self.kernel=C.WinDLL('kernel32',use_last_error=True)
        signatures={
            'OpenFileMappingW':([C.c_uint32,C.c_int32,C.c_wchar_p],C.c_void_p),
            'MapViewOfFile':([C.c_void_p,C.c_uint32,C.c_uint32,C.c_uint32,C.c_size_t],C.c_void_p),
            'UnmapViewOfFile':([C.c_void_p],C.c_int32),'CloseHandle':([C.c_void_p],C.c_int32),
            'VirtualQuery':([C.c_void_p,C.POINTER(MemoryInfo),C.c_size_t],C.c_size_t),
            'GetTickCount':([],C.c_uint32),
        }
        for name,(args,result) in signatures.items():
            function=getattr(self.kernel,name);function.argtypes=args;function.restype=result

    @contextmanager
    def mapped(self, write=False):
        access=6 if write else 4
        handle=self.kernel.OpenFileMappingW(access,0,self.memory_name)
        if not handle:raise OSError('RTSS shared memory is unavailable')
        address=None;view=None
        try:
            address=self.kernel.MapViewOfFile(handle,access,0,0,0)
            if not address:raise OSError('RTSS memory mapping failed')
            info=MemoryInfo()
            if not self.kernel.VirtualQuery(address,C.byref(info),C.sizeof(info)):raise OSError('RTSS memory size query failed')
            if info.size<40 or info.size>64*1024*1024:raise OSError('Invalid RTSS mapping size')
            view=memoryview((C.c_ubyte*info.size).from_address(address)).cast('B')
            buffer=SharedBuffer(view)
            if write:
                if buffer.version<0x2000e:raise OSError('OSD writing requires RTSS shared memory 2.14 or newer')
                import atomics
                with atomics.atomicview(buffer=view[36:40],atype=atomics.INT) as busy:
                    if not busy.cmpxchg_strong(expected=0,desired=1).success:
                        raise BlockingIOError('RTSS OSD is busy')
                    try:
                        yield buffer
                    finally:
                        busy.store(0)
            else:
                yield buffer
        finally:
            if view is not None:view.release()
            if address:self.kernel.UnmapViewOfFile(address)
            self.kernel.CloseHandle(handle)

    def samples(self):
        with self.mapped() as buffer:return buffer.samples(self.kernel.GetTickCount())

    def publish(self,text):
        with self.mapped(write=True) as buffer:return buffer.publish(self.owner,text)

    def close(self):
        try:self.publish(None)
        except (OSError, ValueError):pass
