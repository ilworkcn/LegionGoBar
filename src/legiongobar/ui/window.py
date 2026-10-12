from __future__ import annotations

import time
from pathlib import Path
from importlib.resources import files

from PySide6.QtCore import Qt, Signal, QObject, QRunnable, QThreadPool, QTimer, QEvent
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QKeyEvent
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
                               QGridLayout, QPushButton, QStackedWidget, QScrollArea, QSystemTrayIcon,
                               QMenu, QAbstractButton, QSlider, QComboBox, QLineEdit, QSpinBox, QSizeGrip)

from .reference import Renderer, Toggle, load_reference
from .profiles import ProfilesPage
from .tile import Tile
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
        self.last_profile = None
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
        left = QLabel("LT")
        left.setProperty("role", "caption")
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
        right = QLabel("RT")
        right.setProperty("role", "caption")
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
        self.timer.start(1000)
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
        button = self.renderer.named.get("LosslessScalingSaveSettingsButton")
        if button:
            button.setEnabled(bool(self.snapshot["capabilities"].get("LosslessScalingSaveAndRestart")))

    def select(self, key):
        if key not in self.page_widgets:
            if key == "Quick":
                widget = self.quick_page()
            elif key == "Game":
                widget = ProfilesPage(self.store, lambda: self.snapshot, self.i18n)
                widget.apply_profile.connect(self.apply_profile)
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
            button.clicked.connect(lambda checked=False, d=definition: self.cycle(d))
            grid.addWidget(button, index // 3, index % 3)
            self.tiles.append((button, definition))
        layout.addLayout(grid)
        brightness = self.i18n.bind(QLabel(), "Brightness")
        brightness.setProperty("role", "title")
        layout.addWidget(brightness)
        self.brightness = QSlider(Qt.Horizontal)
        self.brightness.setRange(0, 100)
        self.brightness.setEnabled(False)
        self.brightness.sliderReleased.connect(lambda: self.apply_setting("PanelBrightness", self.brightness.value()))
        layout.addWidget(self.brightness)
        layout.addStretch()
        scroll.setWidget(body)
        self.refresh_quick()
        return scroll

    def refresh_quick(self):
        if not hasattr(self, "tiles"):
            return
        values, caps = self.snapshot["values"], self.snapshot["capabilities"]
        for button, (label, key, options, labels, glyph) in self.tiles:
            enabled = bool(caps.get(key))
            button.setEnabled(enabled and key not in self.busy)
            value = values.get(key)
            text = labels[options.index(value)] if value in options else "--"
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
            self.busy.discard(key)
            self.snapshot = snapshot
            self.renderer.update(snapshot)
            self.refresh_quick()
            self.i18n.bind(self.status, "{key}: {value} · {message}", key=key, value=applied.value, message=applied.message)

        def operation():
            result = self.backend.apply(key, value)
            return result, self.backend.snapshot()

        self.submit(operation, finish)

    def apply_profile(self, settings):
        def operation():
            successes, failures = [], []
            for key, value in settings.items():
                try:
                    self.backend.apply(key, value)
                    successes.append(key)
                except Exception as exc:
                    failures.append(f"{key}: {exc}")
            return successes, failures, self.backend.snapshot()

        def finish(result):
            successes, failures, snapshot = result
            self.snapshot = snapshot
            self.renderer.update(snapshot)
            self.refresh_quick()
            self.i18n.bind(self.status, "Profile: {success} applied, {failed} failed{detail}", success=len(successes), failed=len(failures), detail=f" · {failures[0]}" if failures else "")

        self.submit(operation, finish)

    def action(self, name):
        if name == "LosslessScalingSaveSettingsButton":
            self.apply_setting("LosslessScalingSaveAndRestart", True)
        else:
            self.i18n.bind(self.status, "{name}: unavailable", name=name)

    def tick(self):
        data = telemetry()
        battery = f"{data['BatteryLevel']}%" if data["BatteryLevel"] is not None else "--"
        self.i18n.bind(self.metrics, "CPU {cpu}%  ·  RAM {ram}%  ·  Battery {battery}", cpu=data["CPUUsage"], ram=data["MemoryUsage"], battery=battery)
        if self.store.get("PerGameProfile", False) and not self.backend.demo:
            path = foreground()
            if path:
                key = str(Path(path).resolve()).casefold()
                if key != self.last_profile:
                    self.last_profile = key
                    profile = self.store.data["profiles"].get(key)
                    if profile:
                        self.i18n.bind(self.profile_label, "{name}", name=profile.get("name", Path(key).stem))
                        self.apply_profile(profile["settings"])

    def poll_gamepad(self):
        state = self.gamepad.read()
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
