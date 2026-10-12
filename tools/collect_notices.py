"""收集依赖许可证并放入源码与便携分发目录。"""
from importlib import metadata
from pathlib import Path
import shutil
import sys


def collect(output):
    output = Path(output)
    for name in ("PySide6-Essentials", "shiboken6", "psutil", "hidapi", "pywin32", "pyinstaller", "atomics", "cffi", "pycparser"):
        distribution = metadata.distribution(name)
        for file in distribution.files or []:
            if "/licenses/" in str(file).lower() or file.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    folder = output / name
                    folder.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, folder / source.name)
    for name in ("LICENSE.txt", "LICENSE"):
        source = Path(sys.base_prefix) / name
        if source.is_file():
            folder = output / "Python"
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, folder / source.name)


if __name__ == "__main__":
    collect(sys.argv[1])
