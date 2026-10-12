import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QSlider
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent

from legiongobar.backend import Backend
from legiongobar.storage import Store
from legiongobar.ui.reference import Renderer, load_reference
from legiongobar.ui.window import Window


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


def test_reference_is_pinned_and_all_controls_have_source_inventory():
    reference = load_reference()
    assert reference["reference"]["commit"] == "99ed5f5f8c22bb78bfffee9b37f9a04094f30482"
    assert len(reference["controls"]) == 535 and len(reference["functions"]) == 375
    assert reference["functions"]["TDP"] == 2


def test_all_reference_pages_render_and_string_enum_items_survive(application):
    reference = load_reference()
    renderer = Renderer(reference, lambda *args: None, lambda *args: None)
    widgets = [renderer.render(page) for page in reference["pages"].values()]
    assert len(widgets) == 9
    light = renderer.named["LegionLightModeComboBox"]
    assert light.count() == 5 and light.itemText(0) == "Off"
    touchpad = renderer.named["LegionTouchpadVibrationComboBox"]
    assert touchpad.count() == 4 and touchpad.itemData(2) == 3
    for widget in widgets:
        widget.deleteLater()


def test_slider_keyboard_event_has_no_recursive_navigation(application, tmp_path):
    window = Window(Backend(Store(tmp_path), demo=True), Store(tmp_path), no_tray=True)
    window.select("Performance")
    slider = window.renderer.named["CPUEPPSlider"]
    slider.setEnabled(True)
    slider.setValue(30)
    QApplication.sendEvent(slider, QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))
    assert slider.value() > 30
    window.quit()
    window.pool.waitForDone()
    application.removeEventFilter(window)
