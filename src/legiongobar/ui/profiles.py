from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from ..i18n import I18n
from ..profiles import Profiles, canonical
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QFileDialog, QMessageBox, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout

class ProfilesPage(QWidget):
    apply_profile = Signal(dict)
    setting_changed = Signal(str, object)

    def __init__(self, store, snapshot, i18n=None):
        super().__init__()
        self.store, self.snapshot = store, snapshot
        self.profiles = Profiles(store)
        self.i18n = i18n or I18n("en_US", self)
        self.layout = QVBoxLayout(self)
        title = self.i18n.bind(QLabel(), "Per-Game Profiles")
        title.setProperty("role", "title")
        self.layout.addWidget(title)
        description = self.i18n.bind(QLabel(), "Automatically apply your settings when a matching executable is in focus.")
        description.setWordWrap(True)
        self.layout.addWidget(description)
        self.automatic = self.i18n.bind(QCheckBox(), "Use per-game profile")
        self.automatic.setChecked(store.get("PerGameProfile", False))
        self.automatic.toggled.connect(lambda checked: self.setting_changed.emit("PerGameProfile", checked))
        self.layout.addWidget(self.automatic)
        self.power_source = self.i18n.bind(QCheckBox(), "Power source profiles")
        self.power_source.setChecked(store.get("PowerSourceProfile", False))
        self.power_source.toggled.connect(lambda checked: self.setting_changed.emit("PowerSourceProfile", checked))
        self.layout.addWidget(self.power_source)
        row = QHBoxLayout()
        add = self.i18n.bind(QPushButton(), "Add game")
        add.clicked.connect(self.add)
        row.addWidget(add)
        self.scope = QComboBox()
        for text, key in (("Shared settings", "settings"), ("Plugged in (AC)", "ac"), ("On battery (DC)", "dc")):
            self.scope.addItem(text, key)
        self.i18n.combo(self.scope, [self.scope.itemText(i) for i in range(self.scope.count())])
        row.addWidget(self.scope, 1)
        fields = self.i18n.bind(QPushButton(), "Saved fields")
        fields.clicked.connect(self.edit_fields)
        row.addWidget(fields)
        self.layout.addLayout(row)
        self.games = QListWidget()
        self.layout.addWidget(self.games)
        row = QHBoxLayout()
        for label, handler in (("Save current settings", self.save_selected), ("Apply", self.apply), ("Delete", self.delete), ("Export", self.export), ("Import", self.import_file)):
            button = self.i18n.bind(QPushButton(), label)
            button.clicked.connect(handler)
            row.addWidget(button)
        self.layout.addLayout(row)
        self.notice = self.i18n.bind(QLabel(), "Select a game and save its current settings.")
        self.notice.setWordWrap(True)
        self.notice.setProperty("role", "caption")
        self.layout.addWidget(self.notice)
        self.refresh()
        self.i18n.changed.connect(self.refresh)

    def refresh(self):
        selected = self.selected() if hasattr(self, "keys") else None
        self.games.clear()
        self.keys = [None, *sorted(self.store.data["profiles"])]
        for key in self.keys:
            if key is None:
                self.games.addItem(self.i18n.text("Global Settings"))
                continue
            self.games.addItem(f"{self.store.data['profiles'][key].get('name', Path(key).stem)}\n{key}")

        self.games.setCurrentRow(self.keys.index(selected) if selected in self.keys else 0)

    def selected(self):
        index = self.games.currentRow()
        return self.keys[index] if 0 <= index < len(self.keys) else None

    def add(self):
        path, _ = QFileDialog.getOpenFileName(self, self.i18n.text("Select game executable"), "", self.i18n.text("Executables (*.exe)"), options=QFileDialog.DontUseNativeDialog)
        if not path:
            return
        key = canonical(path)
        self.profiles.save(key, self.snapshot(), self.scope.currentData(), Path(path).stem)
        self.refresh()
        self.games.setCurrentRow(self.keys.index(key))

    def edit_fields(self):
        from ..profile_fields import GROUPS
        dialog = QDialog(self)
        dialog.setWindowTitle(self.i18n.text("Saved fields"))
        layout = QVBoxLayout(dialog)
        description = self.i18n.bind(QLabel(), "Unchecked fields inherit global settings when saving a game profile.")
        description.setWordWrap(True)
        layout.addWidget(description)
        grid = QGridLayout()
        flags = self.store.get("ProfileSaveFlags", {})
        boxes = {}
        for index, name in enumerate(GROUPS):
            box = self.i18n.bind(QCheckBox(), name)
            box.setChecked(flags.get(name, True))
            boxes[name] = box
            grid.addWidget(box, index // 2, index % 2)
        layout.addLayout(grid)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.i18n.bind(buttons.button(QDialogButtonBox.Save), "Save")
        self.i18n.bind(buttons.button(QDialogButtonBox.Cancel), "Cancel")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.Accepted:
            self.store.set("ProfileSaveFlags", {name: box.isChecked() for name, box in boxes.items()})
        dialog.deleteLater()

    def save_selected(self):
        self.profiles.save(self.selected(), self.snapshot(), self.scope.currentData())
        self.refresh()
        self.i18n.bind(self.notice, "Profile saved")

    def apply(self):
        from ..native.system import telemetry
        settings = self.profiles.settings_for(self.selected(), telemetry()["ACConnected"])
        self.apply_profile.emit(settings)

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
        path, _ = QFileDialog.getOpenFileName(self, self.i18n.text("Import profiles"), "", "Profiles (*.json *.xml)", options=QFileDialog.DontUseNativeDialog)
        if path:
            try:
                retained = self.store.import_profiles(Path(path))
                self.refresh()
                self.i18n.bind(self.notice, "Profiles imported; {count} upstream fields retained without applying", count=retained)
            except (ValueError, OSError, AttributeError) as exc:
                QMessageBox.warning(self, self.i18n.text("Import failed"), str(exc))
