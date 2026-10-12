from __future__ import annotations

import json
import re
from importlib.resources import files
from ..i18n import I18n
from .. import __version__
from .slider import Slider

from PySide6.QtCore import Qt, Signal, QSignalBlocker, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QIcon
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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(48, 28)
        self.setFocusPolicy(Qt.StrongFocus)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#A0A0A0" if self.isEnabled() else "#50555C"), 1))
        painter.setBrush(QColor("#58C8ED" if self.isChecked() else "#30343A"))
        painter.drawRoundedRect(4, 4, 40, 20, 10, 10)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#25282C" if self.isChecked() else "#A0A0A0"))
        painter.drawEllipse(28 if self.isChecked() else 8, 8, 12, 12)
        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor("white"), 2))
            painter.drawRoundedRect(1, 1, 46, 26, 4, 4)


class ClickFrame(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class Renderer:
    """将原始 XAML 结构转换为 Qt 控件，保留基准供复刻对照。"""
    def __init__(self, reference, apply, action, i18n=None):
        self.reference, self.apply, self.action = reference, apply, action
        self.i18n = i18n or I18n("en_US")
        self.named = {}
        self.bound = []
        self.pending_bindings = []
        self.rendered = set()
        self.mapping_values = {}

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
        self.i18n.bind(widget, "Unavailable on this device", "setToolTip")
        if key:
            if key == "LosslessScalingSize":
                signal.connect(lambda *args: self.apply(key, "PERFORMANCE" if extract() else "BALANCED"))
            elif key.startswith("LegionButton") and isinstance(widget, QComboBox):
                signal.connect(lambda *args: self.mapping_changed(key, "gamepad", widget))
            else:
                signal.connect(lambda *args: self.apply(key, extract()))

    def render(self, node, parent=None):
        kind, attrs = node["type"], self.attrs(node)
        children = [c for c in node["children"] if "." not in c["type"]]
        if "." in kind or kind in ("DataTemplate", "ItemsPanelTemplate", "ControlTemplate", "Style", "Setter", "RowDefinition", "ColumnDefinition", "Run", "LineBreak"):
            return None
        if attrs.get("Name") == "AboutContent":
            widget = QWidget(parent)
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(0, 12, 0, 0)
            for label, value in (("Version", __version__), ("Author", "SUNNYQUAN")):
                row = QHBoxLayout()
                row.addWidget(self.i18n.bind(QLabel(), label), 1)
                row.addWidget(QLabel(value))
                layout.addLayout(row)
            layout.addWidget(self.i18n.bind(QLabel(), "Credits"))
            link = QLabel('<a style="color: #78D8FF; text-decoration: underline;" href="https://github.com/corando98/GoTweaks">corando98/GoTweaks</a>')
            link.setOpenExternalLinks(True)
            link.setObjectName("credits_link")
            link.setTextInteractionFlags(Qt.TextBrowserInteraction)
            link.setFocusPolicy(Qt.StrongFocus)
            layout.addWidget(link)
        elif kind == "TextBlock":
            text = attrs.get("Text", node.get("text", ""))
            if text.startswith("{"):
                text = ""
            if not text:
                text = "".join(c["attrs"].get("Text", "") for c in children if c["type"] == "Run")
            if attrs.get("Name") == "AboutVersionText":
                text = __version__
            text = {"LtChipotle": "SUNNYQUAN", "Special Thanks": "Credits", "Mute, GameTechPlanet": "corando98/GoTweaks"}.get(text, text)
            widget = self.i18n.bind(QLabel(parent=parent), text)
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
                widget.setProperty("glyph", True)
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
            widget = Toggle(parent)
            widget.setChecked(attrs.get("IsOn") == "True")
            self.bind(widget, node, widget.toggled, widget.isChecked)
        elif kind in ("CheckBox", "RadioButton"):
            widget = self.i18n.bind(QCheckBox(parent=parent), attrs.get("Content", ""))
            widget.setChecked(attrs.get("IsChecked") == "True")
            self.bind(widget, node, widget.toggled, widget.isChecked)
        elif kind == "Slider":
            widget = Slider(Qt.Horizontal, parent)
            step = float(attrs.get("StepFrequency", 1))
            scale = 100 if step < 0.1 else 10 if step < 1 else 1
            widget.setProperty("scale", scale)
            widget.setMinimum(round(float(attrs.get("Minimum", 0)) * scale))
            widget.setMaximum(round(float(attrs.get("Maximum", 100)) * scale))
            widget.setSingleStep(max(1, round(step * scale)))
            widget.setValue(round(float(attrs.get("Value", 0)) * scale))
            tick = max(1, round(float(attrs.get("TickFrequency", step)) * scale))
            widget.setTickInterval(tick)
            placement = attrs.get("TickPlacement", "None")
            widget.setTickPosition({"Outside": QSlider.TicksBothSides, "BottomRight": QSlider.TicksBelow, "TopLeft": QSlider.TicksAbove}.get(placement, QSlider.NoTicks))
            widget.snap_interval = tick if attrs.get("SnapsTo") == "Ticks" else widget.singleStep()
            widget.setSingleStep(widget.snap_interval)
            widget.setPageStep(widget.snap_interval * 10)
            self.bind(widget, node, widget.sliderReleased, lambda w=widget, s=scale: w.value() / s if s != 1 else w.value())
            # 键盘与手柄方向键调整也需要提交实际设置值。
            widget.actionTriggered.connect(lambda action, w=widget, n=node: self.slider_action(w, n, action))
            if attrs.get("Name") == "TDPSlider":
                widget.valueChanged.connect(lambda value: self.show_tdp_value(value))
        elif kind == "ComboBox":
            widget = QComboBox(parent)
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
            mapping = re.fullmatch(r"(LegionButton(?:Y1|Y2|Y3|M1|M2|M3|Desktop|Page))(Type|Mouse|Key)?ComboBox", attrs.get("Name", ""))
            if mapping:
                key, part = mapping[1], mapping[2] or "gamepad"
                from ..native.legion_hid import GAMEPAD_ACTIONS, KEYBOARD_KEYS
                if part == "Type":
                    while widget.count() > 3:
                        widget.removeItem(3)
                elif part == "Mouse":
                    for i in range(widget.count()):
                        widget.setItemData(i, i+1)
                elif part == "Key":
                    for i in range(widget.count()):
                        code = KEYBOARD_KEYS.get(widget.itemText(i))
                        widget.setItemData(i, code)
                        if code is None and i != 0:
                            widget.model().item(i).setEnabled(False)
                else:
                    for i in range(min(widget.count(), len(GAMEPAD_ACTIONS))):
                        widget.setItemData(i, GAMEPAD_ACTIONS[i])
                if part != "gamepad":
                    widget.activated.connect(lambda index, k=key, p=part, w=widget: self.mapping_changed(k, p, w))
            self.i18n.combo(widget, [widget.itemText(i) for i in range(widget.count())])
            widget.setCurrentIndex(int(attrs.get("SelectedIndex", 0)))
            widget.setProperty("minimum_combo_width", min(180, int(float(attrs.get("MinWidth", 100)))))
            widget.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            widget.setMinimumContentsLength(9)
            self.i18n.combo(widget)
            self.bind(widget, node, widget.activated, widget.currentData)
        elif kind in ("TextBox", "NumberBox"):
            if kind == "TextBox":
                widget = QLineEdit(attrs.get("Text", ""), parent)
                self.i18n.bind(widget, attrs.get("PlaceholderText", ""), "setPlaceholderText")
                self.bind(widget, node, widget.editingFinished, widget.text)
            else:
                widget = QDoubleSpinBox(parent)
                widget.setRange(float(attrs.get("Minimum", 0)), float(attrs.get("Maximum", 100)))
                widget.setValue(float(attrs.get("Value", 0)))
                self.bind(widget, node, widget.editingFinished, widget.value)
        elif kind in ("Button", "ColorPicker"):
            if kind == "ColorPicker":
                widget = self.i18n.bind(QPushButton(parent=parent), "Choose color")
                key = function_for(attrs.get("Name", ""), self.reference["functions"])
                self.bound.append((widget, key, node))
                widget.setEnabled(False)
                widget.clicked.connect(lambda: self.pick_color(key, widget))
            else:
                text = attrs.get("Content", "")
                widget = self.i18n.bind(QPushButton(parent=parent), text if text and not text.startswith("{") else "Select")
                self.rendered.add(attrs.get("Name", ""))
                if "Expand" in attrs.get("Name", ""):
                    self.i18n.bind(widget, "")
                    widget.setProperty("role", "disclosure")
                    widget.setIcon(QIcon(str(files("legiongobar").joinpath("assets/ui/chevron-down.svg"))))
                    widget.setIconSize(QSize(14, 14))
                    widget.clicked.connect(lambda: self.expand(attrs.get("Name", "")))
                else:
                    widget.setEnabled(False)
                    widget.clicked.connect(lambda: self.action(attrs.get("Name", "")))
        elif kind == "ScrollViewer":
            widget = QScrollArea(parent)
            widget.setWidgetResizable(True)
            widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            widget.setFrameShape(QFrame.NoFrame)
            if children:
                content = self.render(children[0], parent=widget)
                if content:
                    widget.setWidget(content)
        elif kind == "Expander":
            widget = QWidget(parent)
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            header_node = next((c for c in node["children"] if c["type"].endswith(".Header")), None)
            title = next((c["attrs"].get("Text", "Details") for c in walk(header_node) if c["type"] == "TextBlock"), "Details") if header_node else "Details"
            header = self.i18n.bind(QPushButton(parent=widget), title)
            header.setIcon(QIcon(str(files("legiongobar").joinpath("assets/ui/chevron-down.svg"))))
            header.setIconSize(QSize(14, 14))
            header.setProperty("translation_header", title)
            content = QWidget(widget)
            body = QVBoxLayout(content)
            body.setContentsMargins(0, 0, 0, 0)
            for child in children:
                rendered = self.render(child, parent=widget)
                if rendered is not None:
                    body.addWidget(rendered)
            content.setVisible(attrs.get("IsExpanded") == "True")
            header.clicked.connect(lambda: content.setVisible(content.isHidden()))
            layout.addWidget(header)
            layout.addWidget(content)
        elif kind == "Canvas" and attrs.get("Name") == "FanCurveCanvas":
            from .fan import FanCurve
            widget = FanCurve(parent)
            self.bound.append((widget, "LegionFanCurveData", node))
            widget.edited.connect(lambda value: self.apply("LegionFanCurveData", value))
            widget.setEnabled(False)
        elif kind in ("Image", "Ellipse", "Rectangle", "Path", "Line", "ProgressRing", "ProgressBar"):
            return None
        else:
            widget = ClickFrame(parent) if kind == "Border" else QWidget(parent)
            if kind == "Border" and "CardStyle" in attrs.get("Style", ""):
                widget.setProperty("role", "card")
            if kind == "Grid":
                layout = QGridLayout(widget)
                cells = {}
                for child in children:
                    rendered = self.render(child, parent=widget)
                    if rendered is not None:
                        a = self.attrs(child)
                        cell = (int(a.get("Grid.Row", 0)), int(a.get("Grid.Column", 0)), int(a.get("Grid.RowSpan", 1)), int(a.get("Grid.ColumnSpan", 1)))
                        cells.setdefault(cell, []).append((rendered, a))
                for cell, items in cells.items():
                    # XAML 常把标题与右侧数值叠放在同一格；Qt 用独立横排保留间距。
                    if len(items) > 1 and all(isinstance(w, QLabel) for w, _ in items):
                        row_widget = QWidget(widget)
                        row_layout = QHBoxLayout(row_widget)
                        row_layout.setContentsMargins(0, 0, 0, 0)
                        row_layout.setSpacing(12)
                        for child_widget, a in items:
                            right = a.get("HorizontalAlignment") == "Right"
                            if right:
                                child_widget.setWordWrap(False)
                                child_widget.setMinimumHeight(child_widget.fontMetrics().height())
                                child_widget.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                            row_layout.addWidget(child_widget, 0 if right else 1)
                        layout.addWidget(row_widget, *cell)
                    else:
                        for child_widget, a in items:
                            alignment = Qt.AlignmentFlag(0)
                            if a.get("HorizontalAlignment") == "Right":
                                alignment |= Qt.AlignRight
                            if a.get("VerticalAlignment") == "Center":
                                alignment |= Qt.AlignVCenter
                            layout.addWidget(child_widget, *cell, alignment)
                definitions = next((c for c in node["children"] if c["type"] == "Grid.ColumnDefinitions"), None)
                if definitions:
                    for index, child in enumerate(definitions["children"]):
                        if "*" in child["attrs"].get("Width", "*"):
                            layout.setColumnStretch(index, 1)
            else:
                layout = QHBoxLayout(widget) if attrs.get("Orientation") == "Horizontal" else QVBoxLayout(widget)
                for child in children:
                    rendered = self.render(child, parent=widget)
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

    def mapping_changed(self, key, part, widget):
        mapping = dict(self.mapping_values.get(key, {"type": 1, "mappings": [0]}))
        if part == "Type":
            mapping = {"type": widget.currentIndex()+1, "mappings": [0] if widget.currentIndex() == 0 else [] if widget.currentIndex() == 1 else [1]}
        elif part == "Key":
            code = widget.currentData()
            if code is None:
                return
            codes = list(mapping["mappings"]) if mapping["type"] == 2 else []
            if code not in codes and len(codes) < 16:
                codes.append(code)
            mapping = {"type": 2, "mappings": codes}
            with QSignalBlocker(widget):
                widget.setCurrentIndex(0)
        else:
            mapping = {"type": 3 if part == "Mouse" else 1, "mappings": [widget.currentData()]}
        self.mapping_values[key] = mapping
        self.apply(key, json.dumps(mapping))

    def remove_mapping_key(self, key, code):
        mapping = self.mapping_values[key]
        mapping = {"type": 2, "mappings": [value for value in mapping["mappings"] if value != code]}
        self.mapping_values[key] = mapping
        self.apply(key, json.dumps(mapping))

    def update_mappings(self, snapshot):
        from ..native.legion_hid import BUTTONS, KEYBOARD_KEYS
        for button in BUTTONS:
            key = "LegionButton" + button
            enabled = bool(snapshot["capabilities"].get(key))
            value = snapshot["values"].get(key, {"type": 1, "mappings": [0]})
            value = json.loads(value) if isinstance(value, str) else value
            self.mapping_values[key] = value
            mapping_type = value["type"]
            for suffix in ("TypeComboBox", "ComboBox", "MouseComboBox", "KeyComboBox"):
                widget = self.named.get(key+suffix)
                if widget is None:
                    continue
                widget.setEnabled(enabled)
                self.i18n.bind(widget, "" if enabled else "Unavailable on this device", "setToolTip")
                with QSignalBlocker(widget):
                    if suffix == "TypeComboBox":
                        widget.setCurrentIndex(mapping_type-1)
                    elif suffix != "KeyComboBox" and value["mappings"]:
                        widget.setCurrentIndex(widget.findData(value["mappings"][0]))
                if suffix in ("ComboBox", "MouseComboBox"):
                    widget.setVisible(mapping_type == (1 if suffix == "ComboBox" else 3))
            panel = self.named.get(key+"KeyboardPanel")
            if panel:
                panel.setVisible(mapping_type == 2)
            for suffix in ("Picker", "KeyPicker", "MousePicker"):
                picker = self.named.get(key+suffix)
                if picker:
                    picker.hide()
            tags = self.named.get(key+"KeyTags")
            if tags:
                layout = tags.layout()
                while layout.count():
                    item = layout.takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()
                if mapping_type == 2:
                    for code in value["mappings"]:
                        label = next((name for name, usage in KEYBOARD_KEYS.items() if usage == code), str(code))
                        chip = self.i18n.bind(QPushButton(tags), "{key} ×", key=self.i18n.text(label))
                        chip.setProperty("translation_key", label)
                        chip.setEnabled(enabled)
                        chip.clicked.connect(lambda checked=False, k=key, c=code: self.remove_mapping_key(k,c))
                        layout.addWidget(chip)

    def show_tdp_value(self, value):
        label = self.named.get("TDPValueText")
        if label:
            self.i18n.bind(label, "{value}", value=f"{value:g} W")

    def slider_action(self, widget, node, action):
        if not widget.isSliderDown():
            key = function_for(node["attrs"].get("Name", ""), self.reference["functions"])
            if key:
                scale = widget.property("scale") or 1
                self.apply(key, widget.sliderPosition() / scale if scale != 1 else widget.sliderPosition())

    def pick_color(self, key, widget):
        color = QColorDialog.getColor(parent=widget, title=self.i18n.text("Choose color"), options=QColorDialog.DontUseNativeDialog)
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
            self.i18n.bind(widget, "" if supported else "Unavailable on this device", "setToolTip")
            if key not in values:
                continue
            value = values[key]
            with QSignalBlocker(widget):
                if isinstance(widget, (Toggle, QCheckBox)):
                    widget.setChecked(value == "PERFORMANCE" if key == "LosslessScalingSize" else bool(value))
                elif isinstance(widget, QSlider):
                    if not widget.isSliderDown():
                        widget.setValue(round(float(value) * (widget.property("scale") or 1)))
                elif isinstance(widget, QComboBox):
                    if key in ("Resolution", "RefreshRate"):
                        options = values.get("Resolutions" if key == "Resolution" else "RefreshRates", [])
                        widget.clear()
                        for option in options:
                            widget.addItem(str(option), option)
                        self.i18n.combo(widget, [str(option) for option in options])
                    widget.setCurrentIndex(widget.findData(value))
                elif isinstance(widget, QLineEdit):
                    widget.setText(str(value))
                elif widget.objectName() == "FanCurveCanvas":
                    widget.set_data(value)
        self.update_mappings(snapshot)
        section = self.named.get("TDPSliderSection")
        if section:
            section.setVisible(values.get("LegionPerformanceMode") == 255)
        for name, key in (("CurrentTDPValueText", "CurrentTDP"), ("TDPValueText", "TDP"), ("ActiveProfileText", "ActiveProfile")):
            widget = self.named.get(name)
            if isinstance(widget, QLabel) and key in values:
                if key == "TDP":
                    slider = self.named.get("TDPSlider")
                    self.show_tdp_value(slider.value() if slider and slider.isSliderDown() else values[key])
                else:
                    self.i18n.bind(widget, "{value}", value=f"{values[key]:g} W" if key == "CurrentTDP" else values[key])
        # 原界面中由开关驱动的可见性绑定。
        for widget, binding in self.pending_bindings:
            match = re.search(r"ElementName=(\w+), Path=IsOn", binding)
            if match and isinstance(self.named.get(match[1]), Toggle):
                visible = self.named[match[1]].isChecked()
                widget.setVisible(not visible if "Inverse" in binding else visible)


def walk(node):
    yield node
    for child in node["children"]:
        yield from walk(child)
