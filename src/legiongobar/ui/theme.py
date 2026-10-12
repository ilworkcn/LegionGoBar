"""统一正文字体和资源路径，兼容源码运行与便携包。"""
import os
from pathlib import Path
from importlib.resources import files
from PySide6.QtGui import QFont, QFontDatabase

FONT_FAMILY = "Microsoft YaHei"

def configure_font(app):
    if app.property("legion_fonts_ready"):
        return
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    # 加载 Windows 内置微软雅黑；图标字体只用于原始符号。
    for name in ("msyh.ttc", "msyhbd.ttc", "segmdl2.ttf"):
        if (fonts/name).exists():
            QFontDatabase.addApplicationFont(str(fonts/name))
    font = QFont(FONT_FAMILY)
    font.setPixelSize(14)
    app.setFont(font)
    app.setProperty("legion_fonts_ready", True)

def stylesheet():
    assets = files("legiongobar").joinpath("assets")
    return assets.joinpath("theme.qss").read_text(encoding="utf-8").replace("__UI_ASSETS__", str(assets.joinpath("ui")).replace("\\", "/"))
