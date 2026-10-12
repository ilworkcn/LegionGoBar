from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from ..i18n import I18n
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QFileDialog, QMessageBox, QCheckBox

PROFILE_KEYS = {"TDP", "CPUBoost", "CPUEPP", "TDPBoostEnabled", "TDPBoostSPPT", "TDPBoostFPPT", "OSPowerMode", "Resolution", "RefreshRate"}


class ProfilesPage(QWidget):
    apply_profile = Signal(dict)

    def __init__(self, store, snapshot, i18n=None):
        super().__init__()
        self.store, self.snapshot = store, snapshot
        self.i18n = i18n or I18n("en_US", self)
        self.layout = QVBoxLayout(self)
        title = self.i18n.bind(QLabel(), "Per-Game Profiles")
        title.setProperty("role", "title")
        self.layout.addWidget(title)
        self.layout.addWidget(self.i18n.bind(QLabel(), "Automatically apply your settings when a matching executable is in focus."))
        self.automatic = self.i18n.bind(QCheckBox(), "Use per-game profile")
        self.automatic.setChecked(store.get("PerGameProfile", False))
        self.automatic.toggled.connect(lambda checked: store.set("PerGameProfile", checked))
        self.layout.addWidget(self.automatic)
        self.games = QListWidget()
        self.layout.addWidget(self.games)
        row = QHBoxLayout()
        for label, handler in (("Save current settings", self.add), ("Apply", self.apply), ("Delete", self.delete), ("Export", self.export), ("Import", self.import_file)):
            button = self.i18n.bind(QPushButton(), label)
            button.clicked.connect(handler)
            row.addWidget(button)
        self.layout.addLayout(row)
        self.notice = self.i18n.bind(QLabel(), "Select a game and save its current settings.")
        self.notice.setWordWrap(True)
        self.notice.setProperty("role", "caption")
        self.layout.addWidget(self.notice)
        self.refresh()

    def refresh(self):
        self.games.clear()
        self.keys = sorted(self.store.data["profiles"])
        for key in self.keys:
            self.games.addItem(f"{self.store.data['profiles'][key].get('name', Path(key).stem)}\n{key}")

    def selected(self):
        index = self.games.currentRow()
        return self.keys[index] if 0 <= index < len(self.keys) else None

    def add(self):
        path, _ = QFileDialog.getOpenFileName(self, self.i18n.text("Select game executable"), "", self.i18n.text("Executables (*.exe)"), options=QFileDialog.DontUseNativeDialog)
        if not path:
            return
        snapshot = self.snapshot()
        settings = {k: v for k, v in snapshot["values"].items() if snapshot["capabilities"].get(k) and (k in PROFILE_KEYS or k.startswith(("AMD", "LegionButton", "LegionGyro", "LegionLight", "LegionLeft", "LegionRight")) or k in ("LegionNintendoLayout", "LegionVibration", "LegionVibrationMode", "LegionPerformanceMode", "LegionJoystickAsMouseMode", "LegionJoystickMouseSens"))}
        key = str(Path(path).resolve()).casefold()
        self.store.data["profiles"][key] = {"name": Path(path).stem, "settings": settings}
        self.store.save()
        self.refresh()

    def apply(self):
        key = self.selected()
        if key:
            self.apply_profile.emit(self.store.data["profiles"][key]["settings"])

    def delete(self):
        key = self.selected()
        if key:
            del self.store.data["profiles"][key]
            self.store.save()
            self.refresh()

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, self.i18n.text("Export profiles"), "profiles.json", "JSON (*.json)", options=QFileDialog.DontUseNativeDialog)
        if path:
            self.store.export_profiles(Path(path))

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, self.i18n.text("Import profiles"), "", "JSON (*.json)", options=QFileDialog.DontUseNativeDialog)
        if path:
            try:
                self.store.import_profiles(Path(path))
                self.refresh()
            except (ValueError, OSError, AttributeError) as exc:
                QMessageBox.warning(self, self.i18n.text("Import failed"), str(exc))
