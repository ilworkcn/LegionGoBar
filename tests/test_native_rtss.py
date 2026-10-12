"""使用独立命名内存验证 Windows ABI，不接触运行中的 RTSS。"""
import ctypes as C
import struct
import uuid
from legiongobar.native.rtss_memory import RtssMemory,SIGNATURE


def test_native_mapping_atomic_write_and_busy_release():
    name='Local\\LegionGoBar-test-'+uuid.uuid4().hex
    memory=RtssMemory(name)
    kernel=memory.kernel
    kernel.CreateFileMappingW.argtypes=[C.c_void_p,C.c_void_p,C.c_uint32,C.c_uint32,C.c_uint32,C.c_wchar_p]
    kernel.CreateFileMappingW.restype=C.c_void_p
    handle=kernel.CreateFileMappingW(C.c_void_p(-1),None,4,0,16384,name)
    assert handle
    address=kernel.MapViewOfFile(handle,6,0,0,16384)
    assert address
    try:
        data=bytearray(16384)
        struct.pack_into('<9I',data,0,SIGNATURE,0x2000e,300,14000,1,4608,64,3,0)
        C.memmove(address,bytes(data),len(data))
        assert memory.publish('LegionGoBar test')
        assert C.c_uint32.from_address(address+36).value==0
        assert C.string_at(address+64+4608+512).startswith(b'LegionGoBar test')
        C.c_uint32.from_address(address+36).value=1
        import pytest
        with pytest.raises(BlockingIOError):memory.publish('blocked')
        assert C.c_uint32.from_address(address+36).value==1
        C.c_uint32.from_address(address+36).value=0
        with pytest.raises(ValueError):memory.publish('x'*5000)
        assert C.c_uint32.from_address(address+36).value==0
        memory.close()
        assert C.string_at(address+64+4608+256)==b''
    finally:
        kernel.UnmapViewOfFile(address)
        kernel.CloseHandle(handle)
