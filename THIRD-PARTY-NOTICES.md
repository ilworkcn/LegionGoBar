# Third-party notices

LegionGoBar is authored by **SUNNYQUAN**. Original Python code in this project is distributed under the root [MIT License](LICENSE).

## GoTweaks

Credits: **[corando98/GoTweaks](https://github.com/corando98/GoTweaks)**.

GoTweaks provides the UI reference, control names and adapted Lenovo device protocols for this project. The local `GoTweaks-Desktop` checkout is a fork used as the porting baseline, at commit `99ed5f5f8c22bb78bfffee9b37f9a04094f30482`. The original notice is preserved in `reference/GoTweaks-LICENSE.txt`; copied reference files retain their original attribution. These credits identify the upstream project and do not change LegionGoBar's author.

## AMD ADLX

`src/legiongobar/assets/native/ADLXCSharpBind.dll` is the native x64 ADLX binding from the reference checkout. LegionGoBar calls its C ABI through ctypes. The corresponding interface and ABI declaration are retained in `reference/adlx/`, together with `ADLX SDK License Agreement.pdf`. The binding uses AMD's installed driver runtime. SDK source: [GPUOpen-LibrariesAndSDKs/ADLX](https://github.com/GPUOpen-LibrariesAndSDKs/ADLX).

## Runtime dependencies

Python, Qt/PySide6, shiboken6, psutil, hidapi, pywin32 and the PyInstaller bootloader retain their respective licenses. License texts are included in `reference/licenses/` and in the portable distribution. Windows fonts are loaded from the system installation and are not bundled.

## Noto Sans CJK SC

界面内置 Noto Sans CJK SC 静态字体，依据 SIL Open Font License 1.1 分发。
来源：https://github.com/notofonts/noto-cjk/tree/main/Sans
完整许可：`src/legiongobar/assets/fonts/OFL.txt`（便携包位于 `_internal/legiongobar/assets/fonts/OFL.txt`）。


## RTSS shared memory and atomics

RTSS 共享内存布局参考 [RTSSSharedMemoryNET SDK header](https://github.com/spencerhakim/RTSSSharedMemoryNET/blob/master/RTSSSharedMemoryNET/RTSSSharedMemory.h) 与 [RTSS SDK header](https://github.com/jaxFF/RTSSTweaks/blob/master/thirdparty/rtss-sdk/Include/RTSSSharedMemory.h)。Python 实现不加载 RTSSSharedMemoryNET.dll。

原子操作使用 [atomics](https://github.com/doodspav/atomics)（MIT）及其 patomic、cffi 依赖，发行包包含相应依赖许可。RTSS 本体需要用户自行安装。


## VIIPER

Controller emulation includes the native VIIPER library from the GoTweaks fork,
revision `7805d80b32cf6a27319276599e7fd76dd96d2a6c` (Alia5/VIIPER and contributors).
VIIPER is licensed under GPL-3.0; the combined distribution is provided under
GPL-3.0. LegionGoBar source retains its own MIT license. The full GPL text is in
`reference/licenses/VIIPER-GPLv3.txt`; corresponding VIIPER source is included in
`reference/vendor/VIIPER-7805d80-source.zip`, including its module manifests and
native-library build instructions in `clib/main.go`.
Upstream: https://github.com/Alia5/VIIPER
Fork: https://github.com/corando98/VIIPER

## PresentMon 2.4.1

Copyright (C) 2017-2024 Intel Corporation. MIT License.

Source: https://github.com/GameTechDev/PresentMon/tree/v2.4.1

License: `reference/licenses/PresentMon-MIT.txt`. The native capture executable is distributed with LegionGoBar.

## GamepadMotionHelpers

Copyright (c) 2020-2023 Julian "Jibb" Smart. MIT License.

Native sensor fusion library and C export shim from the reference project.
License: `reference/licenses/GamepadMotion-MIT.txt`; corresponding sources: `reference/vendor/GamepadMotion`.

## PyWinRT 3.2.1

Windows Runtime Python bindings. MIT License.
Source: https://github.com/pywinrt/pywinrt/tree/v3.2.1

License: `reference/licenses/PyWinRT-MIT.txt`.
