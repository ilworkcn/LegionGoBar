from __future__ import annotations

import time
from pathlib import Path
from importlib.resources import files

from PySide6.QtCore import Qt, Signal, QObject, QRunnable, QThreadPool, QTimer, QEvent
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QKeyEvent
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
                               QGridLayout, QPushButton, QStackedWidget, QScrollArea, QSystemTrayIcon,
                               QMenu, QAbstractButton, QSlider, QComboBox, QLineEdit, QSpinBox)

from .reference import Renderer, Toggle, load_reference
from .profiles import ProfilesPage
from .tile import Tile
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
    def __init__(self, backend, store, no_tray=False):
        super().__init__()
        self.backend, self.store = backend, store
        self.reference = load_reference()
        self.snapshot = {"capabilities": {}, "values": {}, "demo": backend.demo}
        self.renderer = Renderer(self.reference, self.apply_setting, self.action)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.jobs = set()
        self.busy = set()
        self.last_profile = None
        self.exit_requested = False
        self.setWindowTitle("LegionGoBar")
        self.resize(600, 670)
        self.setMinimumSize(460, 420)
        self.setStyleSheet(files("legiongobar").joinpath("assets/theme.qss").read_text(encoding="utf-8"))
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        nav = QHBoxLayout()
        nav.setSpacing(2)
        left = QLabel("LT")
        left.setProperty("role", "caption")
        nav.addWidget(left)
        self.nav = []
        # Device tabs remain inspectable on a developer PC; hardware controls are gated.
        self.tab_ids = [t["id"] for t in self.reference["tabs"] if t["id"] != "GPD"]
        for tab in self.reference["tabs"]:
            if tab["id"] not in self.tab_ids:
                continue
            button = QPushButton(tab["label"])
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
        self.metrics = QLabel("CPU --  ·  RAM --  ·  Battery --")
        self.metrics.setProperty("role", "caption")
        footer.addWidget(self.metrics, 1)
        self.device = QLabel("Detecting device…")
        self.device.setProperty("role", "caption")
        footer.addWidget(self.device)
        layout.addLayout(footer)
        self.status = QLabel("Preview · No hardware writes" if backend.demo else "Initializing native adapters…")
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
        self.status.setText(f"Failed: {error}")
        self.snapshot = self.backend.snapshot()
        self.renderer.update(self.snapshot)
        self.refresh_quick()

    def discovered(self, snapshot):
        self.snapshot = snapshot
        self.device.setText(snapshot["values"].get("DeviceDisplayName", "Unknown device"))
        self.renderer.update(snapshot)
        self.refresh_quick()
        supported = sum(bool(v) for v in snapshot["capabilities"].values())
        self.status.setText("Preview · No hardware writes" if self.backend.demo else f"Native adapters ready · {supported} controls available")
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
                widget = ProfilesPage(self.store, lambda: self.snapshot)
                widget.apply_profile.connect(self.apply_profile)
            else:
                widget = self.renderer.render(self.reference["pages"][key])
                widget.show()
                self.renderer.update(self.snapshot)
                self.enable_actions()
            self.page_widgets[key] = widget
            self.pages.addWidget(widget)
        self.pages.setCurrentWidget(self.page_widgets[key])
        for index, button in enumerate(self.nav):
            button.setChecked(self.tab_ids[index] == key)
        self.current_tab = key

    def quick_page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        self.profile_label = QLabel("Global Settings")
        self.profile_label.setProperty("role", "value")
        layout.addWidget(self.profile_label)
        layout.addWidget(QLabel("Quick Settings"))
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
        brightness = QLabel("Brightness")
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
            button.set_display(label, text)
            button.setToolTip("" if enabled else "Device unavailable or pending migration")
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
        self.status.setText(f"Applying {key}…")
        self.refresh_quick()

        def finish(result):
            applied, snapshot = result
            self.busy.discard(key)
            self.snapshot = snapshot
            self.renderer.update(snapshot)
            self.refresh_quick()
            self.status.setText(f"{key}: {applied.value} · {applied.message}")

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
            self.status.setText(f"Profile: {len(successes)} applied, {len(failures)} failed" + (f" · {failures[0]}" if failures else ""))

        self.submit(operation, finish)

    def action(self, name):
        if name == "LosslessScalingSaveSettingsButton":
            self.apply_setting("LosslessScalingSaveAndRestart", True)
        else:
            self.status.setText(f"{name}: pending migration")

    def tick(self):
        data = telemetry()
        battery = f"{data['BatteryLevel']}%" if data["BatteryLevel"] is not None else "--"
        self.metrics.setText(f"CPU {data['CPUUsage']}%  ·  RAM {data['MemoryUsage']}%  ·  Battery {battery}")
        if self.store.get("PerGameProfile", False) and not self.backend.demo:
            path = foreground()
            if path:
                key = str(Path(path).resolve()).casefold()
                if key != self.last_profile:
                    self.last_profile = key
                    profile = self.store.data["profiles"].get(key)
                    if profile:
                        self.profile_label.setText(profile.get("name", Path(key).stem))
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
        painter.setFont(QFont("Segoe UI", 18, QFont.Bold))
        painter.drawText(image.rect(), Qt.AlignCenter, "L")
        painter.end()
        icon = QIcon(image)
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("LegionGoBar")
        menu = QMenu()
        menu.addAction("Open LegionGoBar", self.reveal)
        menu.addAction("Exit", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.reveal() if reason == QSystemTrayIcon.Trigger else None)
        self.tray.show()
        self.tray_menu = menu

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
