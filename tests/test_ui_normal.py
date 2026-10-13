"""正常模式非预设读回值、能力缺失和连续刷新回归。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from legiongobar.backend import Backend
from legiongobar.storage import Store
from legiongobar.ui.window import Window
from legiongobar.i18n import I18n


def test_normal_readbacks_and_missing_capabilities(tmp_path):
    app = QApplication.instance() or QApplication([])
    backend = Backend(Store(tmp_path), demo=False, read_only=True)
    # 保留正常模式，只替换硬件边界，覆盖非演示值与能力缺失。
    backend.discover = lambda: {"demo": False, "capabilities": {"CPUEPP": True, "Resolution": True},
        "values": {"CPUEPP": 42, "DeviceDisplayName": "Long device name " * 12,
                   "Resolution": "1920x1080", "Resolutions": ["1920x1080", "2560x1440"]}}
    window = Window(backend, backend.store, no_tray=True, i18n=I18n("zh_CN"))
    window.timer.stop(); window.gamepad_timer.stop()
    window.pool.waitForDone(); app.processEvents()
    try:
        assert not window.snapshot["demo"] and window.discovery_complete
        epp = next(button for button, definition in window.tiles if definition[1] == "CPUEPP")
        assert epp.state == "42"
        assert not window.device.wordWrap()
        assert window.device.toolTip() == "Long device name " * 12
        window.select("Performance")
        mode = window.renderer.named["TDPModeComboBox"]
        assert not mode.isEnabled() and mode.currentIndex() == -1
        assert mode.placeholderText() == "不可用"
        window.select("AMD")
        combo = next(widget for widget,key,_ in window.renderer.bound if key == "Resolution")
        removed = []
        combo.model().rowsRemoved.connect(lambda *args: removed.append(True))
        window.renderer.update(window.snapshot)
        window.renderer.update(window.snapshot)
        assert not removed
        assert combo.currentData() == "1920x1080"
    finally:
        window.quit(); window.pool.waitForDone(); backend.close()
        app.removeEventFilter(window)
