import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import pytest
from PySide6.QtCore import QObject, QEvent, Qt, QSignalBlocker
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QComboBox
from legiongobar.app import build_parser
from legiongobar.backend import Backend
from legiongobar.storage import Store
from legiongobar.i18n import I18n, normalize_language
from legiongobar.ui.window import Window

@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])

def make_window(tmp_path, **options):
    store = Store(tmp_path)
    window = Window(Backend(store, demo=True), store, no_tray=True, **options)
    window.pool.waitForDone()
    QApplication.processEvents()
    return window

def dispose(app, window):
    window.quit()
    window.pool.waitForDone()
    app.processEvents()
    app.removeEventFilter(window)
    window.deleteLater()
    app.processEvents()

def test_page_switch_does_not_show_transient_windows(app, tmp_path):
    class Tracker(QObject):
        def __init__(self):
            super().__init__()
            self.windows = []
        def eventFilter(self, obj, event):
            if event.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow():
                self.windows.append(obj.objectName() or type(obj).__name__)
            return False
    window = make_window(tmp_path)
    tracker = Tracker()
    window.show()
    app.processEvents()
    app.installEventFilter(tracker)
    try:
        for key in window.tab_ids * 2:
            window.select(key)
            app.processEvents()
        assert tracker.windows == []
    finally:
        app.removeEventFilter(tracker)
        dispose(app, window)

def test_frameless_default_and_debug_frame(app, tmp_path):
    frameless = make_window(tmp_path/'normal')
    debug = make_window(tmp_path/'debug', windowed=True)
    try:
        assert frameless.windowFlags() & Qt.FramelessWindowHint
        assert not debug.windowFlags() & Qt.FramelessWindowHint
        args = build_parser().parse_args(["--debug-window", "--lang", "zh-CN"])
        assert args.windowed and args.lang == "zh_CN"
    finally:
        dispose(app, frameless)
        dispose(app, debug)

def test_switch_language_preserves_device_values_and_pages(app, tmp_path):
    language = I18n("en_US")
    window = make_window(tmp_path, i18n=language)
    try:
        window.select("Legion")
        combo = window.renderer.named["LegionLightModeComboBox"]
        combo.setCurrentIndex(2)
        combo.activated.emit(2)
        # 等待异步应用回读后再验证语言切换，避免使用初始化占位值。
        window.pool.waitForDone()
        app.processEvents()
        payload = combo.currentData()
        page = window.page_widgets["Legion"]
        language.set_language("zh_CN")
        assert combo.itemText(0) == "关闭"
        assert combo.currentData() == payload
        assert window.page_widgets["Legion"] is page
        assert window.nav[0].text() == "设置"
        window.select("Scaling")
        enums = [c for c in window.findChildren(QComboBox) if isinstance(c.currentData(), str)]
        before = [(c, [c.itemData(i) for i in range(c.count())]) for c in enums]
        language.set_language("en_US")
        assert combo.itemText(0) == "Off" and combo.currentData() == payload
        assert all([c.itemData(i) for i in range(c.count())] == values for c, values in before)
        window.select("System")
        window.language_combo.setCurrentIndex(window.language_combo.findData("zh_CN"))
        window.change_language()
        assert Store(tmp_path).get("Language") == "zh_CN"
        assert language.requested == "zh_CN"
    finally:
        dispose(app, window)

def test_about_author_and_credit_link(app, tmp_path):
    window = make_window(tmp_path)
    try:
        window.select("System")
        about = window.renderer.named["AboutContent"]
        labels = [label.text() for label in about.findChildren(QLabel)]
        assert "SUNNYQUAN" in labels
        assert any("https://github.com/corando98/GoTweaks" in text for text in labels)
        assert all("LtChipotle" not in text for text in labels)
    finally:
        dispose(app, window)

def test_language_alias_and_fallback(app):
    assert normalize_language("en-US") == "en_US"
    assert normalize_language("zh") == "zh_CN"
    with pytest.raises(ValueError):
        normalize_language("bad")
    language = I18n("zh_CN")
    assert language.text("Driver error: 123") == "Driver error: 123"
    assert language.text("Ready · {count} controls available", count=4) == "已就绪 · 4 项设置可用"

def test_keyboard_and_mouse_mapping_use_protocol_values(app, tmp_path):
    language = I18n("zh_CN")
    window = make_window(tmp_path, i18n=language)
    try:
        window.pool.waitForDone()
        app.processEvents()
        window.select("Legion")
        renderer = window.renderer
        calls = []
        renderer.apply = lambda key, value: calls.append((key, json.loads(value)))
        types = renderer.named["LegionButtonM2TypeComboBox"]
        types.setCurrentIndex(1)
        types.activated.emit(1)
        assert types.count() == 3
        keys = renderer.named["LegionButtonM2KeyComboBox"]
        for code in (0xE0, 0x04):
            keys.setCurrentIndex(keys.findData(code))
            keys.activated.emit(keys.currentIndex())
        assert calls[-1] == ("LegionButtonM2", {"type": 2, "mappings": [0xE0, 0x04]})
        renderer.remove_mapping_key("LegionButtonM2", 0xE0)
        assert calls[-1][1] == {"type": 2, "mappings": [0x04]}
        mouse = renderer.named["LegionButtonM2MouseComboBox"]
        mouse.setCurrentIndex(4)
        mouse.activated.emit(4)
        assert calls[-1][1] == {"type": 3, "mappings": [5]}
        from legiongobar.backend import Backend
        packet = Backend.hid_commands(*calls[-1], {})[0]
        assert packet[:11] == bytes.fromhex("05 00 12 0A 04 01 11 01 21 03 05")
    finally:
        dispose(app, window)
