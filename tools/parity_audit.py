from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
from legiongobar.backend import HID_KEYS, TDP_KEYS, LOCAL_KEYS
from legiongobar.native.adlx import FEATURES as AMD_FEATURES, FIELDS as AMD_FIELDS
from legiongobar.native.wmi import FEATURES as WMI_FEATURES
from legiongobar.native.power import POWER_FIELDS
from legiongobar.native.scaling import FIELDS as LS_FIELDS
from legiongobar.ui.reference import load_reference, function_for


def audit():
    reference = load_reference()
    implemented = HID_KEYS | TDP_KEYS | LOCAL_KEYS | set(WMI_FEATURES) | set(POWER_FIELDS) | {
        "LegionPerformanceMode", "LegionFanCurveData", "PanelBrightness", "CPUBoost", "CPUEPP", "OSPowerMode", "Resolution", "RefreshRate"}
    implemented |= {prefix + "Enabled" for prefix in AMD_FEATURES} | set(AMD_FIELDS) | {"AMDFluidMotionFrameEnabled"}
    implemented |= {"LosslessScaling" + name for name in LS_FIELDS} | {"LosslessScalingSaveAndRestart"}
    # 适配器存在、交互完整和硬件验证是三个不同的状态。
    controls = []
    for control in reference["controls"]:
        key = function_for(control["name"], reference["functions"])
        connected = key in implemented if key else False
        if key and key.startswith("LegionButton"):
            connected = control["type"] == "ComboBox" and control["name"] == key + "ComboBox"
        import re
        mapping = re.fullmatch(r"(LegionButton(?:Y1|Y2|Y3|M1|M2|M3|Desktop|Page))(Type|Mouse|Key)ComboBox", control["name"])
        if mapping:
            key, connected = mapping[1], True
        if control["name"] == "LosslessScalingSaveSettingsButton":
            key, connected = "LosslessScalingSaveAndRestart", True
        controls.append({"name": control["name"], "page": control["page"], "type": control["type"],
                         "source_line": control["source_line"], "function": key,
                         "interaction": "adapter_connected" if connected else "pending_or_local_presentation",
                         "pixel_parity_verified": False, "legion_go_physical_verified": False})
    functions = [{"name": name, "wire_id": identifier, "adapter": "ported" if name in implemented else "pending",
                  "legion_go_physical_verified": False} for name, identifier in reference["functions"].items()]
    result = {"reference": reference["reference"], "full_parity_accepted": False,
              "scope": "First-generation Legion Go; 8 target tabs; GPD remains reference-only",
              "counts": {"reference_controls": len(controls), "reference_functions": len(functions),
                         "adapter_functions": sum(row["adapter"] == "ported" for row in functions),
                         **dict(Counter(row["interaction"] for row in controls))},
              "controls": controls, "functions": functions}
    folder = ROOT / "docs"
    folder.mkdir(exist_ok=True)
    (folder / "parity.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    text = "# 复刻验收状态\n\n**尚未通过 100% 复刻验收。** 适配器数量不能直接解释为功能完成百分比。\n\n"
    text += f"基准提交：`{reference['reference']['commit']}`。共有 {len(controls)} 个原始控件记录、{len(functions)} 个功能标识。当前有 {result['counts']['adapter_functions']} 个功能标识具备 Python 适配路径，但控件接线、动态行为和物理验证须独立核对。\n\n"
    text += "原始屏幕截图版本可能早于当前分支，视觉基准优先采用本分支 XAML；同一设备上的原程序运行截图尚未完成采集。\n\n"
    text += "| 验收维度 | 当前状态 |\n| --- | --- |\n| 独立进程，不加载 Xbox/UWP/helper | 已实现启动路径，portable smoke 验证另行记录 |\n| 原文案、颜色、控件参数 | 已导入可追溯 XAML 基准；Qt 渲染仍存在差异 |\n| 所有原始 UI、动态卡片、弹窗与交互 | 未完成 |\n| 所有硬件与外部工具功能 | 未完成，逐功能见 parity.json |\n| 第一代 Legion Go 物理响应 | 未实测，当前开发机器为台式机 |\n| 数据包、失败行为与 UI 回归 | 有单元和离屏集成测试 |\n\n"
    text += "## 逐项核对方式\n\n1. 相同 Windows 缩放、主题、显示模式下打开原程序和 LegionGoBar，核对每页默认状态、展开内容、焦点、弹窗和控件尺寸。\n2. 首先运行只读 `--diagnose`，保存 WMI/HID/AMD 可用能力。\n3. 在掌机上逐项操作，记录请求值、实际回读、物理响应、重启后持久化、游戏切换与 AC/DC 切换。\n4. 对不具备回读协议的操作记录物理证据，不以“已发送”当作成功。\n5. 只有全部必需项通过才能将 full_parity_accepted 改为 true；目前不应修改此标记。\n"
    (folder / "PARITY.md").write_text(text, encoding="utf-8")
    print(json.dumps(result["counts"]))


if __name__ == "__main__":
    audit()
