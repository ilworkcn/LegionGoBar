"""界面翻译与语言切换；原始控件值和设备协议保持不变。"""
from importlib.resources import files
import json

from PySide6.QtCore import QObject, Signal, QLocale, QLibraryInfo, QTranslator
from PySide6.QtWidgets import QApplication, QComboBox

LANGUAGES = ("auto", "zh_CN", "en_US")

def normalize_language(value):
    value = value.replace("-", "_")
    aliases = {"en": "en_US", "zh": "zh_CN"}
    value = aliases.get(value, value)
    if value not in LANGUAGES:
        raise ValueError(f"Unsupported language: {value}")
    return value

class I18n(QObject):
    changed = Signal()

    def __init__(self, language="en_US", parent=None):
        super().__init__(parent)
        self.qt_translator = None
        self.set_language(language)

    def set_language(self, language):
        self.requested = normalize_language(language)
        self.language = self.requested
        if self.language == "auto":
            self.language = "zh_CN" if QLocale.system().name().startswith("zh") else "en_US"
        self.catalog = json.loads(files("legiongobar").joinpath(f"locales/{self.language}.json").read_text(encoding="utf-8"))
        app = QApplication.instance()
        if app:
            if self.qt_translator:
                app.removeTranslator(self.qt_translator)
                self.qt_translator.deleteLater()
            self.qt_translator = QTranslator(self)
            if self.language == "zh_CN" and self.qt_translator.load("qtbase_zh_CN", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
                app.installTranslator(self.qt_translator)
        self.changed.emit()

    def text(self, source, **values):
        if isinstance(values.get("message"), str):
            values["message"] = self.catalog.get(values["message"], values["message"])
        return self.catalog.get(source, source).format(**values) if values else self.catalog.get(source, source)

    def bind(self, obj, source, method="setText", **values):
        obj.setProperty("translation_" + method, {"source": source, "values": values})
        getattr(obj, method)(self.text(source, **values))
        return obj

    def combo(self, obj, labels=None):
        if labels is not None:
            obj.setProperty("translation_items", labels)
        for index, source in enumerate(obj.property("translation_items") or []):
            obj.setItemText(index, self.text(source))
        # 下拉箭头与边距单独占宽，按显示文字计算最小宽度。
        text_width = max((obj.fontMetrics().horizontalAdvance(obj.itemText(i)) for i in range(obj.count())), default=0)
        minimum = obj.property("minimum_combo_width") or 100
        obj.setMinimumWidth(min(240, max(minimum, text_width + 56)))

    def retranslate(self, root):
        for obj in [root, *root.findChildren(QObject)]:
            for method in ("setText", "setToolTip", "setPlaceholderText", "setAccessibleName", "setWindowTitle"):
                entry = obj.property("translation_" + method)
                if entry:
                    getattr(obj, method)(self.text(entry["source"], **entry["values"]))
            if obj.property("translation_header"):
                obj.setText(self.text(obj.property("translation_header")))
            if obj.property("translation_key"):
                obj.setText(self.text(obj.property("translation_key")) + " ×")
            if isinstance(obj, QComboBox):
                self.combo(obj)
