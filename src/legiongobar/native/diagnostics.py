"""在独立子进程验证随程序分发的运行库，不连接或修改设备。"""
import multiprocessing as mp


def _probe(pipe):
    try:
        from .viiper import Native,dll_path
        native=Native(dll_path());native.close()
        from .motion import Motion
        motion=Motion()
        try:motion.update((0,0,0,0,4096,0),.004)
        finally:motion.close()
        from winrt.windows.devices.sensors import Gyrometer
        pipe.send({'spawn_worker':True,'viiper_library':True,'motion_fusion':True,'windows_sensor_bindings':True})
    except Exception as error:pipe.send({'spawn_worker':False,'native_runtime_error':str(error)})
    finally:pipe.close()


def probe():
    context=mp.get_context('spawn');parent,child=context.Pipe(duplex=False)
    process=context.Process(target=_probe,args=(child,),daemon=True)
    try:
        process.start();child.close()
        if not parent.poll(15):raise RuntimeError('Native runtime check timed out')
        result=parent.recv();process.join(3)
        if process.exitcode!=0:raise RuntimeError(f'Native runtime worker exit: {process.exitcode}')
        return result
    except Exception as error:return {'spawn_worker':False,'native_runtime_error':str(error)}
    finally:
        parent.close();child.close()
        if process.pid is not None:
            if process.is_alive():process.terminate();process.join(3)
            if process.is_alive():process.kill();process.join(3)
        process.close()
