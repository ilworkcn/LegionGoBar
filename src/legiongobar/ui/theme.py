"""统一字体和平滑策略，兼容源码运行与便携包。"""
import os
from pathlib import Path
from importlib.resources import files
from PySide6.QtGui import QFont, QFontDatabase

FONT_FAMILY = "Noto Sans CJK SC"


def text_font(size=14):
    font = QFont(FONT_FAMILY)
    font.setPixelSize(size)
    # 优先使用轮廓和平滑渲染，小字号使用完整像素对齐，提高笔画清晰度。
    font.setStyleStrategy(QFont.PreferAntialias | QFont.PreferOutline)
    font.setHintingPreference(QFont.PreferFullHinting)
    return font


def configure_font(app):
    if app.property("legion_fonts_ready"):
        return
    for weight in ("Regular", "Medium", "Bold"):
        path = files("legiongobar").joinpath(f"assets/fonts/NotoSansCJKsc-{weight}.otf")
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0 or FONT_FAMILY not in QFontDatabase.applicationFontFamilies(font_id):
            raise RuntimeError("Bundled Noto Sans CJK SC font could not be loaded")
    icons = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segmdl2.ttf"
    if icons.exists():
        QFontDatabase.addApplicationFont(str(icons))
    app.setFont(text_font())
    app.setProperty("legion_fonts_ready", True)


def stylesheet():
    assets = files("legiongobar").joinpath("assets")
    return assets.joinpath("theme.qss").read_text(encoding="utf-8").replace("__UI_ASSETS__", str(assets.joinpath("ui")).replace(chr(92), "/"))
