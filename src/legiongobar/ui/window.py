from __future__ import annotations

import time
import sys
from pathlib import Path
from importlib.resources import files

from PySide6.QtCore import Qt, Signal, QObject, QSignalBlocker, QRunnable, QThreadPool, QTimer, QEvent, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QKeyEvent
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
                               QGridLayout, QPushButton, QStackedWidget, QScrollArea, QSystemTrayIcon,
                               QMenu, QAbstractButton, QSlider, QComboBox, QLineEdit, QSpinBox, QSizeGrip, QDialog, QDialogButtonBox, QKeySequenceEdit, QMessageBox, QFileDialog, QInputDialog)

from .reference import Renderer, Toggle, load_reference
from .profiles import ProfilesPage
from ..profiles import Profiles
from .tile import Tile
from .slider import Slider
from .chrome import TitleBar
from .theme import configure_font, stylesheet, FONT_FAMILY
from ..i18n import I18n
from ..native.system import Gamepad, foreground, telemetry


class Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Job(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = Signals()

    def run(self):
        try:
            self.signals.done.emit(self.function())
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class Window(QMainWindow):
    def __init__(self, backend, store, no_tray=False, windowed=False, i18n=None):
        super().__init__()
        configure_font(QApplication.instance())
        self.backend, self.store = backend, store
        self.profiles = Profiles(store)
        self.hotkey_manager = None
        self.shortcut_buttons = 0
        self.i18n = i18n or I18n(store.get("Language", "auto"), self)
        self.windowed = windowed
        if not windowed:
            self.setWindowFlag(Qt.FramelessWindowHint)
        self.i18n.changed.connect(self.retranslate)
        self.reference = load_reference()
        self.snapshot = {"capabilities": {}, "values": {}, "demo": backend.demo}
        self.renderer = Renderer(self.reference, self.apply_setting, self.action, self.i18n)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.jobs = set()
        self.busy = set()
        self.exit_requested = False
        self.setWindowTitle("LegionGoBar")
        self.resize(600, 670)
        self.setMinimumSize(560, 480)
        self.setStyleSheet(stylesheet())
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        if not windowed:
            layout.addWidget(TitleBar(self, self.i18n))
        nav = QHBoxLayout()
        nav.setSpacing(2)
        left = self.trigger_hint("LT")
        nav.addWidget(left)
        self.nav = []
        # 开发电脑也可查看设备分页，控件可用性由实际设备能力决定。
        self.tab_ids = [t["id"] for t in self.reference["tabs"] if t["id"] != "GPD"]
        for tab in self.reference["tabs"]:
            if tab["id"] not in self.tab_ids:
                continue
            button = self.i18n.bind(QPushButton(), tab["label"])
            button.setProperty("role", "nav")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, key=tab["id"]: self.select(key))
            nav.addWidget(button)
            self.nav.append(button)
        right = self.trigger_hint("RT")
        nav.addWidget(right)
        layout.addLayout(nav)
        self.pages = QStackedWidget()
        self.page_widgets = {}
        layout.addWidget(self.pages, 1)
        footer = QHBoxLayout()
        self.metrics = self.i18n.bind(QLabel(), "CPU --  ·  RAM --  ·  Battery --")
        self.metrics.setProperty("role", "caption")
        footer.addWidget(self.metrics, 1)
        self.device = self.i18n.bind(QLabel(), "Detecting device…")
        self.device.setProperty("role", "caption")
        self.device.setWordWrap(True)
        self.metrics.setWordWrap(True)
        footer.addWidget(self.device)
        if not windowed:
            footer.addWidget(QSizeGrip(self))
        layout.addLayout(footer)
        self.status = self.i18n.bind(QLabel(), "Preview mode" if backend.demo else "Initializing native adapters…")
        self.status.setWordWrap(True)
        self.status.setProperty("role", "caption")
        layout.addWidget(self.status)
        self.select("Quick")
        self.submit(backend.discover, self.discovered)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(250)
        self.gamepad = Gamepad()
        self.previous_buttons = 0
        self.previous_triggers = (False, False)
        self.repeat_deadline = 0
        self.gamepad_timer = QTimer(self)
        self.gamepad_timer.timeout.connect(self.poll_gamepad)
        self.gamepad_timer.start(30)
        self.tray = None
        if not no_tray and QSystemTrayIcon.isSystemTrayAvailable():
            self.setup_tray()
        QApplication.instance().installEventFilter(self)
        self.retranslate()

    def submit(self, function, done=None):
        job = Job(function)
        self.jobs.add(job)
        job.signals.done.connect(lambda result, j=job: self.finished(j, result, done))
        job.signals.failed.connect(lambda error, j=job: self.failed(j, error))
        self.pool.start(job)

    def finished(self, job, result, done):
        self.jobs.discard(job)
        if done:
            done(result)

    def failed(self, job, error):
        self.jobs.discard(job)
        self.busy.clear()
        self.i18n.bind(self.status, "Failed: {error}", error=error)
        self.snapshot = self.backend.snapshot()
        self.renderer.update(self.snapshot)
        self.refresh_quick()

    def discovered(self, snapshot):
        self.snapshot = snapshot
        self.i18n.bind(self.device, snapshot["values"].get("DeviceDisplayName", "Unknown device"))
        self.renderer.update(snapshot)
        self.refresh_quick()
        supported = sum(bool(v) for v in snapshot["capabilities"].values())
        self.i18n.bind(self.status, "Preview mode" if self.backend.demo else "Ready · {count} controls available", count=supported)
        self.enable_actions()

    def enable_actions(self):
        for name,key in (("LosslessScalingSaveSettingsButton","LosslessScalingSaveAndRestart"),
                         ("LaunchLosslessScalingButton","LosslessScalingLaunch"),
                         ("ShowLosslessScalingWindowButton","LosslessScalingBringToForeground"),
                         ("LosslessScalingCreateProfileButton","LosslessScalingCreateProfile"),
                         ("LosslessScalingResetProfileButton","LosslessScalingResetProfile")):
            button = self.renderer.named.get(name)
            if button: button.setEnabled(bool(self.snapshot["capabilities"].get(key)))

    def select(self, key):
        if key not in self.page_widgets:
            if key == "Quick":
                widget = self.quick_page()
            elif key == "Game":
                widget = ProfilesPage(self.store, lambda: self.snapshot, self.i18n)
                widget.apply_profile.connect(self.apply_profile)
                widget.setting_changed.connect(self.apply_setting)
            else:
                widget = self.renderer.render(self.reference["pages"][key], parent=self.pages)
                self.renderer.update(self.snapshot)
                self.enable_actions()
            if key == "System":
                self.add_language_settings(widget)
            self.page_widgets[key] = widget
            self.pages.addWidget(widget)
        self.pages.setCurrentWidget(self.page_widgets[key])
        self.page_widgets[key].show()
        for index, button in enumerate(self.nav):
            button.setChecked(self.tab_ids[index] == key)
        self.current_tab = key
        if key == "Game":
            self.refresh_quick()

    def trigger_hint(self, name):
        hint = QWidget()
        hint.setObjectName("trigger_" + name.lower())
        hint.setFixedWidth(28)
        column = QVBoxLayout(hint)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        icon = QLabel(hint)
        icon.setObjectName("trigger_icon_" + name.lower())
        icon.setAlignment(Qt.AlignCenter)
        path = str(files("legiongobar").joinpath("assets/glyphs/" + name.lower() + ".svg"))
        icon.setPixmap(QIcon(path).pixmap(QSize(24, 24), self.devicePixelRatioF()))
        icon.setFixedHeight(24)
        column.addWidget(icon)
        return hint

    def quick_page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        self.profile_label = self.i18n.bind(QLabel(), "Global Settings")
        self.profile_label.setProperty("role", "value")
        layout.addWidget(self.profile_label)
        layout.addWidget(self.i18n.bind(QLabel(), "Quick Settings"))
        grid = QGridLayout()
        self.quick_grid = grid
        self.quick_editing = False
        self.quick_selected = None
        grid.setSpacing(10)
        self.tiles = []
        definitions = [("TDP Mode", "LegionPerformanceMode", [1, 2, 3, 255], ["Quiet", "Balanced", "Performance", "Custom"], "⚡"),
                       ("Lossless Scaling", "LosslessScalingEnabled", [False, True], ["Off", "On"], "↗"),
                       ("RSR", "AMDRadeonSuperResolutionEnabled", [False, True], ["Off", "On"], "▣"),
                       ("Anti-Lag", "AMDRadeonAntiLagEnabled", [False, True], ["Off", "On"], "◷"),
                       ("Chill", "AMDRadeonChillEnabled", [False, True], ["Off", "On"], "❄"),
                       ("Keyboard", "OnScreenKeyboard", [True], ["Open"], "⌨"),
                       ("CPU Boost", "CPUBoost", [False, True], ["Off", "On"], "⇈"),
                       ("EPP", "CPUEPP", [0, 30, 80, 100], ["0", "30", "80", "100"], "◉"),
                       ("Overlay", "OSD", [0, 1, 2, 3], ["Off", "1", "2", "3"], "▤")]
        for index, definition in enumerate(definitions):
            glyphs = ["\uE945", "\uE740", "\uE8B3", "\uE916", "\uE9CA", "\uE765", "\uE7F4", "\uE83E", "\uE7B3"]
            button = Tile(glyphs[index])
            button.setProperty("role", "tile")
            button.setEnabled(False)
            button.clicked.connect(lambda checked=False, d=definition: self.quick_clicked(d))
            grid.addWidget(button, index // 3, index % 3)
            self.tiles.append((button, definition))
        layout.addLayout(grid)
        customize = self.i18n.bind(QPushButton(), "Customize")
        customize.setCheckable(True)
        customize.toggled.connect(self.edit_quick)
        layout.addWidget(customize)
        self.quick_editor = QWidget(body)
        editor = QVBoxLayout(self.quick_editor)
        hint = self.i18n.bind(QLabel(), "Tap tile to select, tap another to swap. Tap same tile to toggle visibility.")
        hint.setWordWrap(True)
        editor.addWidget(hint)
        row = QHBoxLayout()
        row.addWidget(self.i18n.bind(QLabel(), "Columns:"))
        columns = QComboBox()
        columns.addItems(["3", "4", "5"])
        columns.setCurrentText(str(self.store.get("quick_columns", 3)))
        columns.currentTextChanged.connect(lambda value: self.quick_option("quick_columns", int(value)))
        row.addWidget(columns)
        editor.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(self.i18n.bind(QLabel(), "Show Brightness Slider"), 1)
        show_brightness = Toggle()
        show_brightness.setChecked(self.store.get("quick_brightness", True))
        show_brightness.toggled.connect(lambda value: self.quick_option("quick_brightness", value))
        row.addWidget(show_brightness)
        editor.addLayout(row)
        shortcuts = self.i18n.bind(QPushButton(), "Tile shortcuts")
        shortcuts.clicked.connect(self.edit_tile_shortcuts)
        editor.addWidget(shortcuts)
        self.quick_editor.setVisible(False)
        layout.addWidget(self.quick_editor)
        brightness = self.i18n.bind(QLabel(), "Brightness")
        self.brightness_label = brightness
        brightness.setProperty("role", "title")
        layout.addWidget(brightness)
        self.brightness = Slider(Qt.Horizontal)
        self.brightness.setRange(0, 100)
        self.brightness.setEnabled(False)
        self.brightness.sliderReleased.connect(lambda: self.apply_setting("PanelBrightness", self.brightness.value()))
        layout.addWidget(self.brightness)
        self.brightness.actionTriggered.connect(lambda action: self.apply_setting("PanelBrightness", self.brightness.sliderPosition()) if not self.brightness.isSliderDown() else None)
        self.layout_quick()
        layout.addStretch()
        scroll.setWidget(body)
        self.refresh_quick()
        return scroll

    def tile_shortcut(self, key):
        definition = next((definition for _,definition in getattr(self,"tiles",[]) if definition[1] == key),None)
        if definition is not None:self.cycle(definition)

    def edit_tile_shortcuts(self):
        from ..tile_hotkeys import COMBOS, validate
        from PySide6.QtGui import QKeySequence
        dialog = QDialog(self)
        dialog.setWindowTitle(self.i18n.text("Tile shortcuts"))
        layout = QVBoxLayout(dialog)
        grid = QGridLayout()
        fields = {}
        saved = self.store.get("TileHotkeyConfig", {})
        for index,(_,definition) in enumerate(self.tiles):
            label,key = definition[:2]
            grid.addWidget(self.i18n.bind(QLabel(),label),index,0)
            keyboard = QKeySequenceEdit()
            keyboard.setMaximumSequenceLength(1)
            keyboard.setKeySequence(QKeySequence(saved.get(key,{}).get("keyboard","")))
            grid.addWidget(keyboard,index,1)
            gamepad = QComboBox()
            gamepad.addItem(self.i18n.text("None"),"")
            for combo in COMBOS:gamepad.addItem(combo,combo)
            gamepad.setCurrentIndex(max(0,gamepad.findData(saved.get(key,{}).get("gamepad",""))))
            grid.addWidget(gamepad,index,2)
            fields[key] = (keyboard,gamepad)
        layout.addLayout(grid)
        buttons = QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        self.i18n.bind(buttons.button(QDialogButtonBox.Save),"Save")
        self.i18n.bind(buttons.button(QDialogButtonBox.Cancel),"Cancel")
        def save():
            config = {key:{"keyboard":keyboard.keySequence().toString(QKeySequence.PortableText),"gamepad":gamepad.currentData()}
                      for key,(keyboard,gamepad) in fields.items()}
            try:
                validate(config)
                if self.hotkey_manager:self.hotkey_manager.set_bindings(config,self.tile_shortcut)
                try:
                    self.store.set("TileHotkeyConfig",config)
                except Exception:
                    if self.hotkey_manager:self.hotkey_manager.set_bindings(saved,self.tile_shortcut)
                    raise
                dialog.accept()
            except (ValueError,OSError) as exc:
                QMessageBox.warning(dialog,self.i18n.text("Shortcut could not be saved"),str(exc))
        buttons.accepted.connect(save)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        dialog.deleteLater()

    def quick_option(self, key, value):
        self.store.set(key, value)
        self.layout_quick()

    def edit_quick(self, enabled):
        self.quick_editing = enabled
        self.quick_selected = None
        self.quick_editor.setVisible(enabled)
        self.layout_quick()
        self.refresh_quick()

    def layout_quick(self):
        order = self.store.get("quick_order", [])
        hidden = self.store.get("quick_hidden", [])
        tiles = sorted(self.tiles, key=lambda tile: order.index(tile[1][1]) if tile[1][1] in order else len(order)+self.tiles.index(tile))
        while self.quick_grid.count():
            self.quick_grid.takeAt(0)
        columns = max(3, min(5, int(self.store.get("quick_columns", 3))))
        for column in range(5):
            self.quick_grid.setColumnStretch(column, 1 if column < columns else 0)
        index = 0
        for button, definition in tiles:
            visible = self.quick_editing or definition[1] not in hidden
            button.setVisible(visible)
            button.setProperty("edit_selected", definition[1] == self.quick_selected)
            if visible:
                self.quick_grid.addWidget(button, index // columns, index % columns)
                index += 1
            button.update()
        for widget in (self.brightness_label, self.brightness):
            widget.setVisible(self.store.get("quick_brightness", True))

    def quick_clicked(self, definition):
        if not self.quick_editing:
            self.cycle(definition)
            return
        key = definition[1]
        if self.quick_selected == key:
            hidden = list(self.store.get("quick_hidden", []))
            hidden.remove(key) if key in hidden else hidden.append(key)
            self.store.set("quick_hidden", hidden)
            self.quick_selected = None
        elif self.quick_selected:
            order = self.store.get("quick_order", [])
            order = [k for k in order if k in {d[1] for _, d in self.tiles}]
            order += [d[1] for _, d in self.tiles if d[1] not in order]
            a, b = order.index(self.quick_selected), order.index(key)
            order[a], order[b] = order[b], order[a]
            self.store.set("quick_order", order)
            self.quick_selected = None
        else:
            self.quick_selected = key
        self.layout_quick()
        self.refresh_quick()

    def refresh_quick(self):
        profiles_page = self.page_widgets.get("Game")
        if isinstance(profiles_page, ProfilesPage):
            for box, key in ((profiles_page.automatic, "PerGameProfile"), (profiles_page.power_source, "PowerSourceProfile")):
                with QSignalBlocker(box):
                    box.setChecked(bool(self.snapshot["values"].get(key)))
        if not hasattr(self, "tiles"):
            return
        values, caps = self.snapshot["values"], self.snapshot["capabilities"]
        for button, (label, key, options, labels, glyph) in self.tiles:
            enabled = bool(caps.get(key))
            button.setEnabled(self.quick_editing or (enabled and key not in self.busy))
            value = values.get(key)
            text = "Open" if key == "OnScreenKeyboard" else labels[options.index(value)] if value in options else "--"
            button.visual_state = "trigger" if key == "OnScreenKeyboard" else "active" if key in ("LegionPerformanceMode", "CPUEPP") else "on" if value else "off"
            if self.quick_editing and key in self.store.get("quick_hidden", []):
                text = "Hidden"
            button.set_display(self.i18n.text(label), self.i18n.text(text))
            self.i18n.bind(button, "" if enabled else "Unavailable on this device", "setToolTip")
        self.brightness.setEnabled(bool(caps.get("PanelBrightness")))
        self.brightness.setValue(values.get("PanelBrightness", 0))

    def cycle(self, definition):
        _, key, options, _, _ = definition
        current = self.snapshot["values"].get(key)
        index = options.index(current) if current in options else -1
        self.apply_setting(key, options[(index + 1) % len(options)])

    def apply_setting(self, key, value):
        if key in self.busy:
            return
        self.busy.add(key)
        self.i18n.bind(self.status, "Applying {key}…", key=key)
        self.refresh_quick()

        def finish(result):
            applied, snapshot = result
            if not self.backend.demo:
                self.profiles.remember(key, applied.value, telemetry()["ACConnected"])
            self.busy.discard(key)
            self.snapshot = snapshot
            self.renderer.update(snapshot)
            self.enable_actions()
            self.refresh_quick()
            self.i18n.bind(self.status, "{key}: {value} · {message}", key=key, value=applied.value, message=applied.message)

        def operation():
            result = self.backend.apply(key, value)
            return result, self.backend.snapshot()

        self.submit(operation, finish)

    def apply_profile(self, settings, plan=None):
        def operation():
            successes, failures = [], []
            pending = dict(settings)
            if pending.get("LegionPerformanceMode", self.backend.values.get("LegionPerformanceMode")) != 255:
                for field in ("TDP", "TDPBoostEnabled", "TDPBoostSPPT", "TDPBoostFPPT"):
                    pending.pop(field, None)
                if "StickyTDPEnabled" in pending:
                    pending["StickyTDPEnabled"] = False
            if not self.backend.demo and "Resolution" in pending and "RefreshRate" in pending:
                resolution, refresh = pending.pop("Resolution"), pending.pop("RefreshRate")
                try:
                    actual = self.backend.display.set_mode(resolution, refresh)
                    self.backend.values.update(actual)
                    self.backend.values["RefreshRates"] = sorted({hz for w, h, hz in self.backend.display.modes()
                                                                  if f"{w}x{h}" == actual["Resolution"]})
                    for key in ("Resolution", "RefreshRate"):
                        self.store.set(key, actual[key])
                        successes.append(key)
                except Exception as exc:
                    failures.append(f"Display: {exc}")
            def order(item):
                key, value = item
                if key == "LegionPerformanceMode":return 0
                if key == "AutoTDPEnabled":return 7 if value else 1
                if key == "AutoTDPMaxTDP":return 2 if value >= self.backend.values.get(key, 30) else 4
                if key == "AutoTDPMinTDP":return 3
                if key == "StickyTDPEnabled":return 6
                return 5
            for key, value in sorted(pending.items(), key=order):
                try:
                    self.backend.apply(key, value)
                    successes.append(key)
                except Exception as exc:
                    failures.append(f"{key}: {exc}")
            return successes, failures, self.backend.snapshot()

        def finish(result):
            successes, failures, snapshot = result
            if plan is not None:
                self.profiles.complete(plan, not failures)
                if not failures:
                    self.backend.values["ActiveProfile"] = plan["name"]
                    snapshot["values"]["ActiveProfile"] = plan["name"]
                    self.i18n.bind(self.profile_label, plan["name"])
            self.snapshot = snapshot
            self.renderer.update(snapshot)
            self.refresh_quick()
            self.i18n.bind(self.status, "Profile: {success} applied, {failed} failed{detail}", success=len(successes), failed=len(failures), detail=f" · {failures[0]}" if failures else "")

        self.submit(operation, finish)

    def action(self, name):
        actions = {"LosslessScalingSaveSettingsButton":"LosslessScalingSaveAndRestart",
                   "LaunchLosslessScalingButton":"LosslessScalingLaunch",
                   "ShowLosslessScalingWindowButton":"LosslessScalingBringToForeground",
                   "LosslessScalingResetProfileButton":"LosslessScalingResetProfile"}
        if name == "LosslessScalingCreateProfileButton":
            path,_ = QFileDialog.getOpenFileName(self,self.i18n.text("Select game executable"),"","Programs (*.exe)")
            if not path: return
            title,ok = QInputDialog.getText(self,self.i18n.text("Create profile"),self.i18n.text("Profile name"),text=Path(path).stem)
            if ok and title.strip(): self.apply_setting("LosslessScalingCreateProfile",title.strip()+"<||>"+path)
        elif name in actions:
            self.apply_setting(actions[name], True)
        else:
            self.i18n.bind(self.status, "{name}: unavailable", name=name)

    def maintenance_done(self, snapshot):
        if snapshot == self.snapshot:
            return
        self.snapshot = snapshot
        self.renderer.update(snapshot)
        self.enable_actions()
        self.refresh_quick()
        if snapshot["values"].get("MaintenanceError"):
            self.i18n.bind(self.status, "Failed: {error}", error=snapshot["values"]["MaintenanceError"])

    def tick(self):
        data = telemetry()
        battery = f"{data['BatteryLevel']}%" if data["BatteryLevel"] is not None else "--"
        self.i18n.bind(self.metrics, "CPU {cpu}%  ·  RAM {ram}%  ·  Battery {battery}", cpu=data["CPUUsage"], ram=data["MemoryUsage"], battery=battery)
        if not self.backend.demo and not self.jobs and not self.busy and not self.exit_requested:
            plan = self.profiles.plan(foreground(), data["ACConnected"], self.snapshot, own_path=sys.executable)
            if plan:
                self.apply_profile(plan["settings"], plan)
            else:
                self.submit(self.backend.maintain, self.maintenance_done)

    def poll_gamepad(self):
        state = self.gamepad.read()
        from ..tile_hotkeys import fired
        current = state.buttons if state else 0
        actions = fired(self.store.get("TileHotkeyConfig", {}), self.shortcut_buttons, current)
        self.shortcut_buttons = current
        for key in actions:self.tile_shortcut(key)
        if actions:return
        if not state or not self.isVisible() or not self.isActiveWindow():
            self.previous_buttons = 0
            self.previous_triggers = (False, False)
            return
        buttons = state.buttons
        pressed = buttons & ~self.previous_buttons
        now = time.monotonic()
        if buttons & 0xF and now >= self.repeat_deadline:
            pressed |= buttons & 0xF
            self.repeat_deadline = now + (0.3 if buttons != self.previous_buttons else 0.12)
        directions = {1: Qt.Key_Up, 2: Qt.Key_Down, 4: Qt.Key_Left, 8: Qt.Key_Right}
        for bit, key in directions.items():
            if pressed & bit:
                self.navigate(key)
        if pressed & 0x1000:
            focus = QApplication.focusWidget()
            if QApplication.activePopupWidget() and focus:
                QApplication.sendEvent(focus, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
            elif isinstance(focus, QAbstractButton):
                focus.click()
            elif isinstance(focus, QComboBox):
                focus.showPopup()
        if pressed & 0x2000:
            focus = QApplication.focusWidget()
            if focus:
                QApplication.sendEvent(focus, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        triggers = (state.lt > 160, state.rt > 160)
        index = self.tab_ids.index(self.current_tab)
        if triggers[0] and not self.previous_triggers[0]:
            self.select(self.tab_ids[(index - 1) % len(self.tab_ids)])
        elif triggers[1] and not self.previous_triggers[1]:
            self.select(self.tab_ids[(index + 1) % len(self.tab_ids)])
        self.previous_buttons, self.previous_triggers = buttons, triggers

    def navigate(self, key):
        focus = QApplication.focusWidget()
        if QApplication.activePopupWidget() and focus:
            QApplication.sendEvent(focus, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
            return
        if isinstance(focus, (QComboBox, QSlider)) and key in (Qt.Key_Left, Qt.Key_Right):
            QApplication.sendEvent(focus, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
            return
        candidates = [w for w in self.centralWidget().findChildren(QWidget) if w.isVisible() and w.isEnabled() and w.focusPolicy() & Qt.TabFocus]
        if not candidates:
            return
        if focus is None or focus not in candidates:
            candidates[0].setFocus()
            return
        origin = focus.mapToGlobal(focus.rect().center())
        options = []
        for widget in candidates:
            if widget == focus:
                continue
            target = widget.mapToGlobal(widget.rect().center())
            dx, dy = target.x() - origin.x(), target.y() - origin.y()
            primary, secondary = ((-dy, dx) if key == Qt.Key_Up else (dy, dx) if key == Qt.Key_Down else (-dx, dy) if key == Qt.Key_Left else (dx, dy))
            if primary > 0:
                options.append((primary + abs(secondary) * 3, widget))
        if options:
            target = min(options, key=lambda pair: pair[0])[1]
            target.setFocus(Qt.TabFocusReason)
            page = self.pages.currentWidget()
            if isinstance(page, QScrollArea):
                page.ensureWidgetVisible(target, 24, 36)

    def eventFilter(self, obj, event):
        if isinstance(obj, QWidget) and obj.window() != self:
            return False
        from .fan import FanCurve
        if isinstance(obj, FanCurve):
            return False
        if QApplication.activePopupWidget():
            return False
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right) and not isinstance(obj, (QLineEdit, QSpinBox)):
            if isinstance(obj, (QComboBox, QSlider)) and event.key() in (Qt.Key_Left, Qt.Key_Right):
                return False
            if isinstance(obj, QComboBox) and obj.view().isVisible():
                return False
            self.navigate(event.key())
            return True
        return False

    def setup_tray(self):
        image = QPixmap(32, 32)
        image.fill(QColor("#25282C"))
        painter = QPainter(image)
        painter.setPen(QColor("#58C8ED"))
        painter.setFont(QFont(FONT_FAMILY, 18, QFont.Bold))
        painter.drawText(image.rect(), Qt.AlignCenter, "L")
        painter.end()
        icon = QIcon(image)
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("LegionGoBar")
        menu = QMenu()
        self.i18n.bind(menu.addAction("", self.reveal), "Open LegionGoBar")
        self.i18n.bind(menu.addAction("", self.quit), "Exit")
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.reveal() if reason == QSystemTrayIcon.Trigger else None)
        self.tray.show()
        self.tray_menu = menu

    def add_language_settings(self, page):
        body = page.widget() if isinstance(page, QScrollArea) else page
        card = QWidget(body)
        card.setProperty("role", "card")
        row = QHBoxLayout(card)
        row.addWidget(self.i18n.bind(QLabel(), "Language"), 1)
        self.language_combo = QComboBox(card)
        for label, value in (("Follow system", "auto"), ("简体中文", "zh_CN"), ("English", "en_US")):
            self.language_combo.addItem(label, value)
        self.i18n.combo(self.language_combo, ["Follow system", "简体中文", "English"])
        self.language_combo.setCurrentIndex(self.language_combo.findData(self.i18n.requested))
        self.language_combo.activated.connect(self.change_language)
        row.addWidget(self.language_combo)
        body.layout().insertWidget(0, card)

    def change_language(self):
        language = self.language_combo.currentData()
        self.store.set("Language", language)
        self.i18n.set_language(language)

    def retranslate(self):
        self.i18n.retranslate(self)
        if getattr(self, "tray_menu", None):
            self.i18n.retranslate(self.tray_menu)
        if hasattr(self, "language_combo"):
            self.language_combo.setCurrentIndex(self.language_combo.findData(self.i18n.requested))
        self.refresh_quick()

    def reveal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit(self):
        self.exit_requested = True
        self.close()

    def closeEvent(self, event):
        if self.tray and not self.exit_requested:
            self.hide()
            event.ignore()
        else:
            self.timer.stop()
            self.gamepad_timer.stop()
            if self.tray:
                self.tray.hide()
            event.accept()
