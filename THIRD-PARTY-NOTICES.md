# Third-party notices

LegionGoBar-original Python source is covered by the root MIT LICENSE.

The GoTweaks UI reference, control names, wording and adapted Lenovo protocols originate from GoTweaks, reference commit `99ed5f5f8c22bb78bfffee9b37f9a04094f30482`. The upstream MIT notice is preserved in `reference/GoTweaks-LICENSE.txt`. Upstream: https://github.com/corando98/GoTweaks .

`src/legiongobar/assets/native/ADLXCSharpBind.dll` is the native x64 ADLX binding from that same checkout. It is called with ctypes; no managed C# runtime is loaded. The matching SWIG interface and generated ABI declaration are preserved in `reference/adlx/`. The AMD ADLX SDK agreement is preserved as `reference/adlx/ADLX SDK License Agreement.pdf`. The binding uses AMD's installed driver runtime. Corresponding upstream SDK and build source are in the source checkout's `ADLX/` directory and https://github.com/GPUOpen-LibrariesAndSDKs/ADLX .

Qt/PySide6, psutil, hidapi and pywin32 retain their own licenses. Dependency license texts are collected explicitly into `reference/licenses/` and included with the portable build, including Python and the PyInstaller bootloader notice. Windows fonts are loaded from the Windows installation and are not bundled. The distribution also includes this document and the reference notices.

VIIPER, PawnIO, WinRing0 and the GoTweaks helper executable are not bundled or launched by this version. Their features must not be described as implemented here.
