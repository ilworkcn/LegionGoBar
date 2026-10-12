from __future__ import annotations

import json
import re
from importlib.resources import files

from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QWidget, QLabel, QFrame, QGridLayout, QVBoxLayout, QHBoxLayout,
                               QPushButton, QCheckBox, QComboBox, QSlider, QLineEdit, QSpinBox,
                               QDoubleSpinBox, QScrollArea, QColorDialog, QAbstractButton, QSizePolicy)

ALIASES = {"TDPModeComboBox": "LegionPerformanceMode", "LegionTouchpadToggle": "LegionTouchpadEnabled",
           "TDPBoostToggle": "TDPBoostEnabled",
           "LegionJoystickAsMouseComboBox": "LegionJoystickAsMouseMode", "LegionControllerSleepComboBox": "Settings_LegionControllerSleepMinutes",
           "LegionBrightnessSlider": "LegionLightBrightness", "LegionSpeedSlider": "LegionLightSpeed",
           "LegionColorPicker": "LegionLightColor", "RefreshRatesComboBox": "RefreshRate",
           "AMDRadeonSuperResolutionToggle": "AMDRadeonSuperResolutionEnabled", "AMDFluidMotionFrameToggle": "AMDFluidMotionFrameEnabled",
           "AMDRadeonAntiLagToggle": "AMDRadeonAntiLagEnabled", "AMDRadeonBoostToggle": "AMDRadeonBoostEnabled",
           "AMDRadeonChillToggle": "AMDRadeonChillEnabled", "AMDImageSharpeningToggle": "AMDImageSharpeningEnabled",
           "AMDImageSharpeningSlider": "AMDImageSharpeningSharpness", "LegionTouchpadVibrationComboBox": "LegionTouchpadVibration",
           "PerformanceOverlayComboBox": "OSD", "PerformanceOverlaySlider": "OSD"}
ALIASES.update({"LosslessScalingResizeBeforeToggle": "LosslessScalingResizeBeforeScaling"})
STRING_COMBOS = {"LosslessScaling" + name for name in ("ScalingType", "Anime4KSize", "ScaleMode", "AspectRatio", "FrameGenType", "LSFG3Mode", "LSFG2Mode", "SyncMode", "CaptureApi", "LS1Type")}


def load_reference():
    return json.loads(files("legiongobar").joinpath("assets/reference.json").read_text(encoding="utf-8"))


def function_for(name, functions):
    if name in ALIASES:
        return ALIASES[name]
    stem = re.sub(r"(?:ComboBox|Slider|Toggle|CheckBox|ColorPicker|TextBox|NumberBox)$", "", name)
    return stem if stem in functions else None


def thickness(text):
    try:
        parts = [int(float(x)) for x in text.split(",")]
        if len(parts) == 1:
            return (parts[0],) * 4
        if len(parts) == 2:
            return parts[0], parts[1], parts[0], parts[1]
        if len(parts) == 4:
            return tuple(parts)
    except ValueError:
        pass
    return 0, 0, 0, 0


class Toggle(QAbstractButton):
    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setFixedSize(44, 24)
        self.setFocusPolicy(Qt.StrongFocus)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#50555C"), 1))
        painter.setBrush(QColor("#58C8ED" if self.isChecked() else "#30343A"))
        painter.drawRoundedRect(1, 2, 41, 20, 10, 10)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#25282C" if self.isChecked() else "#A0A0A0"))
        painter.drawEllipse(25 if self.isChecked() else 5, 6, 12, 12)
        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor("white"), 2))
            painter.drawRoundedRect(1, 1, 42, 22, 11, 11)


class ClickFrame(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class Renderer:
    """Translate structural XAML elements without loading any UWP runtime.

    The immutable reference retains unhandled templates for the parity audit.
    Qt controls approximate UWP styling; pixel parity remains an acceptance item.
    """
    def __init__(self, reference, apply, action):
        self.reference, self.apply, self.action = reference, apply, action
        self.named = {}
        self.bound = []
        self.pending_bindings = []
        self.rendered = set()

    def attrs(self, node):
        attrs = node["attrs"]
        style = re.search(r"StaticResource (\w+)", attrs.get("Style", ""))
        defaults = self.reference["styles"].get(style[1], {}) if style else {}
        return {**defaults, **attrs}

    def register(self, widget, node):
        name = node["attrs"].get("Name", "")
        if name:
            widget.setObjectName(name)
            self.named[name] = widget
            widget.setAccessibleName(name)
        return widget

    def bind(self, widget, node, signal, extract):
        name = node["attrs"].get("Name", "")
        key = function_for(name, self.reference["functions"])
        self.rendered.add(name)
        self.bound.append((widget, key, node))
        widget.setEnabled(False)
        widget.setToolTip(f"{name}\n{key or 'Interaction'}: pending port or device capability detection")
        if key:
            if key == "LosslessScalingSize":
                signal.connect(lambda *args: self.apply(key, "PERFORMANCE" if extract() else "BALANCED"))
            elif key.startswith("LegionButton") and isinstance(widget, QComboBox):
                from ..native.legion_hid import GAMEPAD_ACTIONS
                def mapped():
                    index = widget.currentIndex()
                    if 0 <= index < len(GAMEPAD_ACTIONS):
                        self.apply(key, json.dumps({"type": 1, "mappings": [GAMEPAD_ACTIONS[index]]}))
                signal.connect(mapped)
            else:
                signal.connect(lambda *args: self.apply(key, extract()))

    def render(self, node):
        kind, attrs = node["type"], self.attrs(node)
        children = [c for c in node["children"] if "." not in c["type"]]
        if "." in kind or kind in ("DataTemplate", "ItemsPanelTemplate", "ControlTemplate", "Style", "Setter", "RowDefinition", "ColumnDefinition", "Run", "LineBreak"):
            return None
        if kind == "TextBlock":
            text = attrs.get("Text", "")
            if text.startswith("{"):
                text = ""
            if not text:
                text = "".join(c["attrs"].get("Text", "") for c in children if c["type"] == "Run")
            widget = QLabel(text)
            widget.setWordWrap(True)
            widget.setTextFormat(Qt.PlainText)
            style = attrs.get("Style", "")
            if "CardTitleStyle" in style:
                widget.setProperty("role", "title")
            elif "Caption" in style:
                widget.setProperty("role", "caption")
            elif "Value" in style:
                widget.setProperty("role", "value")
            if attrs.get("FontFamily", "").startswith("Segoe MDL2"):
                widget.setFont(QFont("Segoe MDL2 Assets", 14))
            if "FontSize" in attrs:
                font = widget.font()
                try:
                    font.setPixelSize(int(attrs["FontSize"]))
                except ValueError:
                    pass
                font.setBold(attrs.get("FontWeight") in ("Bold", "SemiBold"))
                widget.setFont(font)
            foreground = attrs.get("Foreground", "")
            if re.fullmatch(r"#[a-fA-F0-9]{6}|White|Black", foreground):
                widget.setStyleSheet(f"color: {foreground}; background: transparent;")
        elif kind == "ToggleSwitch":
            widget = Toggle()
            widget.setChecked(attrs.get("IsOn") == "True")
            self.bind(widget, node, widget.toggled, widget.isChecked)
        elif kind in ("CheckBox", "RadioButton"):
            widget = QCheckBox(attrs.get("Content", ""))
            widget.setChecked(attrs.get("IsChecked") == "True")
            self.bind(widget, node, widget.toggled, widget.isChecked)
        elif kind == "Slider":
            widget = QSlider(Qt.Horizontal)
            step = float(attrs.get("StepFrequency", 1))
            scale = 100 if step < 0.1 else 10 if step < 1 else 1
            widget.setProperty("scale", scale)
            widget.setMinimum(round(float(attrs.get("Minimum", 0)) * scale))
            widget.setMaximum(round(float(attrs.get("Maximum", 100)) * scale))
            widget.setSingleStep(max(1, round(step * scale)))
            widget.setValue(round(float(attrs.get("Value", 0)) * scale))
            widget.setMinimumHeight(28)
            self.bind(widget, node, widget.sliderReleased, lambda w=widget, s=scale: w.value() / s if s != 1 else w.value())
            # Keyboard and gamepad arrows must also commit values.
            widget.actionTriggered.connect(lambda action, w=widget, n=node: self.slider_action(w, n, action))
        elif kind == "ComboBox":
            widget = QComboBox()
            for index, child in enumerate(children):
                if child["type"] in ("ComboBoxItem", "String"):
                    a = child["attrs"]
                    value = a.get("Tag", index)
                    if function_for(attrs.get("Name", ""), self.reference["functions"]) in STRING_COMBOS:
                        value = a.get("Tag", a.get("Content", child.get("text", "")))
                    if attrs.get("Name") == "LegionTouchpadVibrationComboBox":
                        value = index + 1
                    try:
                        value = int(value)
                    except (ValueError, TypeError):
                        pass
                    widget.addItem(a.get("Content", child.get("text") or str(value)), value)
            widget.setCurrentIndex(int(attrs.get("SelectedIndex", 0)))
            widget.setMinimumWidth(min(180, int(float(attrs.get("MinWidth", 100)))))
            self.bind(widget, node, widget.activated, widget.currentData)
        elif kind in ("TextBox", "NumberBox"):
            if kind == "TextBox":
                widget = QLineEdit(attrs.get("Text", ""))
                widget.setPlaceholderText(attrs.get("PlaceholderText", ""))
                self.bind(widget, node, widget.editingFinished, widget.text)
            else:
                widget = QDoubleSpinBox()
                widget.setRange(float(attrs.get("Minimum", 0)), float(attrs.get("Maximum", 100)))
                widget.setValue(float(attrs.get("Value", 0)))
                self.bind(widget, node, widget.editingFinished, widget.value)
        elif kind in ("Button", "ColorPicker"):
            if kind == "ColorPicker":
                widget = QPushButton("Choose color")
                key = function_for(attrs.get("Name", ""), self.reference["functions"])
                self.bound.append((widget, key, node))
                widget.setEnabled(False)
                widget.clicked.connect(lambda: self.pick_color(key, widget))
            else:
                text = attrs.get("Content", "")
                widget = QPushButton(text if text and not text.startswith("{") else "Select")
                self.rendered.add(attrs.get("Name", ""))
                if "Expand" in attrs.get("Name", ""):
                    widget.setText("⌄")
                    widget.setFixedWidth(34)
                    widget.clicked.connect(lambda: self.expand(attrs.get("Name", "")))
                else:
                    widget.setEnabled(False)
                    widget.clicked.connect(lambda: self.action(attrs.get("Name", "")))
        elif kind == "ScrollViewer":
            widget = QScrollArea()
            widget.setWidgetResizable(True)
            widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            widget.setFrameShape(QFrame.NoFrame)
            if children:
                content = self.render(children[0])
                if content:
                    widget.setWidget(content)
        elif kind == "Expander":
            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            header_node = next((c for c in node["children"] if c["type"].endswith(".Header")), None)
            title = next((c["attrs"].get("Text", "Details") for c in walk(header_node) if c["type"] == "TextBlock"), "Details") if header_node else "Details"
            header = QPushButton(title + "  ⌄")
            content = QWidget()
            body = QVBoxLayout(content)
            body.setContentsMargins(0, 0, 0, 0)
            for child in children:
                rendered = self.render(child)
                if rendered is not None:
                    body.addWidget(rendered)
            content.setVisible(attrs.get("IsExpanded") == "True")
            header.clicked.connect(lambda: content.setVisible(content.isHidden()))
            layout.addWidget(header)
            layout.addWidget(content)
        elif kind == "Canvas" and attrs.get("Name") == "FanCurveCanvas":
            from .fan import FanCurve
            widget = FanCurve()
            self.bound.append((widget, "LegionFanCurveData", node))
            widget.edited.connect(lambda value: self.apply("LegionFanCurveData", value))
            widget.setEnabled(False)
        elif kind in ("Image", "Ellipse", "Rectangle", "Path", "Line", "ProgressRing", "ProgressBar"):
            return None
        else:
            widget = ClickFrame() if kind == "Border" else QWidget()
            if kind == "Border" and "CardStyle" in attrs.get("Style", ""):
                widget.setProperty("role", "card")
            if kind == "Grid":
                layout = QGridLayout(widget)
                for child in children:
                    rendered = self.render(child)
                    if rendered is not None:
                        a = child["attrs"]
                        row, column = int(a.get("Grid.Row", 0)), int(a.get("Grid.Column", 0))
                        alignment = Qt.AlignmentFlag(0)
                        if a.get("HorizontalAlignment") == "Right":
                            alignment |= Qt.AlignRight
                        if a.get("VerticalAlignment") == "Center":
                            alignment |= Qt.AlignVCenter
                        layout.addWidget(rendered, row, column, int(a.get("Grid.RowSpan", 1)), int(a.get("Grid.ColumnSpan", 1)), alignment)
                definitions = next((c for c in node["children"] if c["type"] == "Grid.ColumnDefinitions"), None)
                if definitions:
                    for index, child in enumerate(definitions["children"]):
                        if "*" in child["attrs"].get("Width", "*"):
                            layout.setColumnStretch(index, 1)
            else:
                layout = QHBoxLayout(widget) if attrs.get("Orientation") == "Horizontal" else QVBoxLayout(widget)
                for child in children:
                    rendered = self.render(child)
                    if rendered is not None:
                        layout.addWidget(rendered)
                if kind == "StackPanel" and attrs.get("Orientation") != "Horizontal":
                    layout.setAlignment(Qt.AlignTop)
            layout.setContentsMargins(*thickness(attrs.get("Padding", "0")))
            layout.setSpacing(int(float(attrs.get("Spacing", 4))))
            if isinstance(widget, ClickFrame):
                collapsed = [c["attrs"].get("Name") for c in walk(node) if c["attrs"].get("Visibility") == "Collapsed" and c["attrs"].get("Name", "").endswith("Content")]
                if collapsed:
                    widget.setCursor(Qt.PointingHandCursor)
                    widget.clicked.connect(lambda: self.toggle_named(collapsed))
        self.register(widget, node)
        if attrs.get("Visibility") == "Collapsed":
            widget.hide()
        if attrs.get("Visibility", "").startswith("{Binding"):
            self.pending_bindings.append((widget, attrs["Visibility"]))
        widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        if kind == "Slider":
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if kind not in ("ScrollViewer", "StackPanel", "Grid", "Border"):
            widget.setMaximumWidth(560)
        return widget

    def slider_action(self, widget, node, action):
        if not widget.isSliderDown():
            key = function_for(node["attrs"].get("Name", ""), self.reference["functions"])
            if key:
                scale = widget.property("scale") or 1
                self.apply(key, widget.sliderPosition() / scale if scale != 1 else widget.sliderPosition())

    def pick_color(self, key, widget):
        color = QColorDialog.getColor(parent=widget)
        if color.isValid() and key:
            self.apply(key, color.name())

    def toggle_named(self, names):
        for name in names:
            widget = self.named.get(name)
            if widget:
                widget.setVisible(widget.isHidden())

    def expand(self, name):
        mapping = {"ColorSettingsExpandButton": "ColorSettingsContent", "LegionColorExpandButton": "LegionColorPicker"}
        target = mapping.get(name, name.replace("ExpandButton", "Picker"))
        self.toggle_named([target])

    def update(self, snapshot):
        caps, values = snapshot["capabilities"], snapshot["values"]
        for widget, key, node in self.bound:
            if not key:
                continue
            supported = bool(caps.get(key))
            widget.setEnabled(supported)
            widget.setToolTip("" if supported else f"{key}: device unavailable or pending migration")
            if key not in values:
                continue
            value = values[key]
            with QSignalBlocker(widget):
                if isinstance(widget, (Toggle, QCheckBox)):
                    widget.setChecked(value == "PERFORMANCE" if key == "LosslessScalingSize" else bool(value))
                elif isinstance(widget, QSlider):
                    widget.setValue(round(float(value) * (widget.property("scale") or 1)))
                elif isinstance(widget, QComboBox):
                    if key in ("Resolution", "RefreshRate"):
                        options = values.get("Resolutions" if key == "Resolution" else "RefreshRates", [])
                        widget.clear()
                        for option in options:
                            widget.addItem(str(option), option)
                    widget.setCurrentIndex(widget.findData(value))
                elif isinstance(widget, QLineEdit):
                    widget.setText(str(value))
                elif widget.objectName() == "FanCurveCanvas":
                    widget.set_data(value)
        section = self.named.get("TDPSliderSection")
        if section:
            section.setVisible(values.get("LegionPerformanceMode") == 255)
        for name, key in (("CurrentTDPValueText", "CurrentTDP"), ("TDPValueText", "TDP"), ("ActiveProfileText", "ActiveProfile")):
            widget = self.named.get(name)
            if isinstance(widget, QLabel) and key in values:
                widget.setText(str(values[key]))
        # Update source bindings for visibility driven by toggle state.
        for widget, binding in self.pending_bindings:
            match = re.search(r"ElementName=(\w+), Path=IsOn", binding)
            if match and isinstance(self.named.get(match[1]), Toggle):
                visible = self.named[match[1]].isChecked()
                widget.setVisible(not visible if "Inverse" in binding else visible)


def walk(node):
    yield node
    for child in node["children"]:
        yield from walk(child)
