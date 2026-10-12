# LegionGoBar

以 Python + PySide6 为主要框架、面向第一代 Lenovo Legion Go 的独立桌面控制程序。窗口、托盘、前台进程检测、配置、交互和硬件适配都由 Python 执行；AMD 通过一个原生 C ABI DLL 调用驱动。无需 Xbox Game Bar、Xbox App、UWP/MSIX 注册、GoTweaks helper 或 .NET 运行时。

**当前为迁移开发版，不是已经通过“100% 复刻”验收的发行版。** 原始控件已经建立完整可追溯的基准，但一部分功能仍未接入，Qt 与 UWP 的像素差异、动态配置卡片和掌机硬件行为还需逐项验证。不可用的控件会禁用，不会假装已修改硬件。

## 固定基准

- 源仓库：用户指定的 GoTweaks-Desktop 当前检出。
- 分支：`release/v0.3.98.0`。
- 提交：`99ed5f5f8c22bb78bfffee9b37f9a04094f30482`。
- 原始 XAML：`reference/GamingWidget.xaml`；其 SHA-256、9 个分页、535 条控件记录、375 个功能标识保存在 `src/legiongobar/assets/reference.json`。
- 当前窗口暴露 8 个目标相关分页；GPD 分页保留在基准中，尚未接入产品窗口。

运行时使用仓库内基准，不需要源仓库留在电脑上。更新基准必须显式执行 `tools/import_reference.py`。

## 运行

Windows x64、Python 3.11 或更新版本：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m legiongobar
```

也可以使用打包后的 `LegionGoBar.exe`。`Ctrl+Alt+G` 唤出窗口；窗口关闭时收进托盘，托盘菜单中选择 Exit 才退出。手柄方向键导航、A 操作、B 返回，LT/RT 切换分页。这里的 XInput 是 Windows 控制器 API，不需要 Xbox 应用或 Game Bar。

```powershell
# 强制预览：不写设备、不执行真实游戏配置切换，设置使用临时目录
.venv\Scripts\python.exe -m legiongobar --demo
# 只读诊断：读取设备能力，不修改功率、风扇、灯光或电源计划
.venv\Scripts\python.exe -m legiongobar --diagnose
# 便携 EXE 可将只读诊断直接保存为文件
LegionGoBar.exe --diagnostic-output .\diagnostics.json
# 渲染全部目标分页并退出，强制预览
.venv\Scripts\python.exe -m legiongobar --smoke --data-dir .\build\smoke-data
```

正常设置保存到 `%LOCALAPPDATA%\LegionGoBar\settings.json`。需要管理员权限的 WMI 操作会由 Windows 返回结果，程序不会启动时自动提权或写入系统设置。

## 已接入的适配

| 范围 | 实现 | 验证边界 |
| --- | --- | --- |
| Windows | CPU Boost、EPP、OS 电源模式、AC/DC 电源键动作、熄屏时间、亮度、分辨率与刷新率 | 支持查询与写后回读；亮度依赖 WMI 内置屏 |
| Legion Go WMI | 四种性能模式、SPL/SPPT/FPPT、TDP Boost、全速风扇、80% 充电限制、温度/RPM 查询、Custom 模式风扇曲线 | 多个功率限制部分失败时回滚；掌机实测未完成 |
| Legion Go HID | 灯光、触控板、触控板触感、震动、背键/前键协议、Nintendo 布局、摇杆死区、扳机行程、摇杆鼠标、陀螺仪配置、手柄休眠时间 | 数据包已单测；灯光/触控板支持 b0:01 回读；其他项目明确显示发送而未确认 |
| AMD | RSR、Anti-Lag、Boost、Chill、锐化，AFMF 与扩展控制按驱动能力检测 | 本机 AMD 的部分只读查询已成功；不支持的驱动功能保持禁用 |
| Lossless Scaling | Default 配置的已有 XML 字段编辑，备份、冲突检测、Apply and Restart | 修改先暂存；保留未知字段；重启采用正常关闭，不强杀进程；多游戏匹配和热键开关仍待迁移 |
| 配置 | 按可执行文件路径匹配、保存已接入设置、JSON 导入导出、前台切换应用 | 原始 GoTweaks 配置格式、全局回退、完整 AC/DC 配置逻辑尚未等价 |

底层背键协议支持 gamepad/keyboard/mouse；当前常规控件仅连接 gamepad 动作选择，键盘组合与鼠标选择 UI 仍待完成。这不等于所有手柄功能已经验收。

## 剩余复刻工作

详细差异以 `docs/parity.json` 和 `docs/PARITY.md` 为准。主要未完成项：原生 RTSS OSD/帧时间图、FPS 限制、AutoTDP PID/学习策略、Sticky TDP、HDR、自适应亮度、AMD 显示颜色、完整快捷键与磁贴定制、动态游戏卡片与原配置兼容、VIIPER 虚拟手柄、灯光/触感实验功能、EC 解锁风扇及逐模式保存、驱动检查/更新与安装流程。

复刻判定需要原程序与独立程序在同一掌机、相同 Windows 缩放和分辨率下逐页面对照，还需要逐项操作的设备回读与物理响应。已有单测与预览不能替代这些验收。

## 测试与打包

```powershell
.venv\Scripts\python.exe -m pytest -q
powershell -ExecutionPolicy Bypass -File tools\build.ps1 -Python .venv\Scripts\python.exe
```

测试覆盖原始 HID 数据包、灯光状态与固件字节序、风扇表格式、设备筛选、部分写入失败、TDP 回滚、设置持久化、XML 冲突保护、控件基准与页面渲染、键盘导航回归。测试不对真实硬件执行设置写入。

Qt for Python 官方资料：[Qt for Python](https://doc.qt.io/qtforpython-6/)。许可与来源见 `THIRD-PARTY-NOTICES.md`。
