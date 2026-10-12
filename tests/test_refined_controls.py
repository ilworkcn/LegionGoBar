import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QApplication, QSlider
from legiongobar.ui.slider import Slider
from legiongobar.ui.window import Window
from legiongobar.storage import Store
from legiongobar.backend import Backend


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_slider_pointer_snaps_and_releases_once(app):
    slider = Slider()
    slider.resize(240, 36)
    slider.setRange(30, 144)
    slider.snap_interval = 5
    slider.setSingleStep(5)
    slider.show()
    released = QSignalSpy(slider.sliderReleased)
    QTest.mousePress(slider, Qt.LeftButton, pos=QPoint(80, 16))
    QTest.mouseMove(slider, QPoint(160, 16))
    assert slider.isSliderDown()
    assert (slider.value()-30) % 5 == 0
    QTest.mouseRelease(slider, Qt.LeftButton, pos=QPoint(239, 16))
    assert slider.value() == 144 and released.count() == 1
    QTest.mouseClick(slider, Qt.LeftButton, pos=QPoint(0, 16))
    assert slider.value() == 30
    QTest.keyClick(slider, Qt.Key_Right)
    assert slider.value() == 35
    slider.setLayoutDirection(Qt.RightToLeft)
    assert slider.position_value(0) == 144
    slider.close()


def test_quick_edit_persists_without_applying_device_settings(app, tmp_path):
    store = Store(tmp_path)
    window = Window(Backend(store, demo=True), store, no_tray=True)
    window.pool.waitForDone()
    app.processEvents()
    applied = []
    window.apply_setting = lambda *args: applied.append(args)
    first, second = window.tiles[0][1], window.tiles[1][1]
    window.edit_quick(True)
    window.quick_clicked(first)
    window.quick_clicked(second)
    window.quick_clicked(first)
    window.quick_clicked(first)
    window.quick_option("quick_columns", 5)
    window.quick_option("quick_brightness", False)
    window.edit_quick(False)
    assert not applied
    restored = Store(tmp_path)
    assert restored.get("quick_order")[:2] == [second[1], first[1]]
    assert restored.get("quick_hidden") == [first[1]]
    assert restored.get("quick_columns") == 5
    assert restored.get("quick_brightness") is False
    assert window.tiles[0][0].isHidden() and window.brightness.isHidden()
    window.edit_quick(True)
    window.quick_clicked(first)
    window.quick_clicked(first)
    window.edit_quick(False)
    assert not window.tiles[0][0].isHidden()
    window.quick_clicked(first)
    assert applied and applied[0][0] == first[1]
    window.quit()
    window.pool.waitForDone()
    app.removeEventFilter(window)


@pytest.mark.parametrize("columns", [3, 4, 5])
def test_quick_columns_fit_small_window(app, tmp_path, columns):
    store = Store(tmp_path)
    window = Window(Backend(store, demo=True), store, no_tray=True)
    window.resize(560, 480)
    window.show()
    window.quick_option("quick_columns", columns)
    window.edit_quick(True)
    app.processEvents()
    for button, _ in window.tiles:
        assert button.width() >= 80
        assert button.geometry().right() < button.parentWidget().width()
    window.quit()
    window.pool.waitForDone()
    app.removeEventFilter(window)


@pytest.mark.parametrize("width", [560, 600, 800])
def test_tdp_drag_value_does_not_overlap_title_or_reset(app, tmp_path, width):
    from PySide6.QtWidgets import QLabel
    store = Store(tmp_path)
    window = Window(Backend(store, demo=True), store, no_tray=True)
    window.show()
    window.pool.waitForDone()
    app.processEvents()
    window.select("Performance")
    window.resize(width, 670)
    window.snapshot["values"]["LegionPerformanceMode"] = 255
    window.renderer.update(window.snapshot)
    app.processEvents()
    slider = window.renderer.named["TDPSlider"]
    value = window.renderer.named["TDPValueText"]
    applied = []
    window.renderer.apply = lambda *args: applied.append(args)
    slider.setSliderDown(True)
    slider.setValue(35)
    window.renderer.update(window.snapshot)
    app.processEvents()
    assert value.text() == "35 W" and slider.value() == 35
    assert not applied
    labels = value.parentWidget().findChildren(QLabel, options=Qt.FindDirectChildrenOnly)
    for label in labels:
        if label is not value:
            assert not label.geometry().intersects(value.geometry())
    slider.setSliderDown(False)
    assert applied == [("TDP", 35)]
    assert not any(label.text() in ("LT", "RT") for label in window.findChildren(QLabel))
    window.quit()
    window.pool.waitForDone()
    app.removeEventFilter(window)
