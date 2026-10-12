"""检查 Qt 所需 ICU ABI，移除构建目录中不兼容的私有 DLL，使用 Windows 系统实现。"""
import sys
from pathlib import Path

import pefile


def fix(folder):
    root = Path(folder).resolve()
    candidate = root / "_internal/icuuc.dll"
    core = root / "_internal/PySide6/Qt6Core.dll"
    if not candidate.exists() or not core.exists():
        return
    required = set()
    core_pe = pefile.PE(str(core))
    try:
        for entry in core_pe.DIRECTORY_ENTRY_IMPORT:
            if entry.dll.lower() == b"icuuc.dll":
                required.update(item.name for item in entry.imports if item.name)
    finally:
        core_pe.close()
    candidate_pe = pefile.PE(str(candidate))
    try:
        exported = {item.name for item in candidate_pe.DIRECTORY_ENTRY_EXPORT.symbols if item.name}
    finally:
        candidate_pe.close()
    if required - exported:
        if root not in candidate.resolve().parents:
            raise RuntimeError("Generated ICU path escaped the output directory")
        candidate.unlink()
        print("Removed incompatible generated ICU copy; Qt uses Windows ICU")


if __name__ == "__main__":
    fix(sys.argv[1])
