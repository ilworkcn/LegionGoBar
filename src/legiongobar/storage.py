from __future__ import annotations

import json
import copy
import os
import tempfile
from pathlib import Path
from threading import RLock


class Store:
    """独立于 UWP 设置的本地原子持久化。"""

    def __init__(self, directory: Path | None = None):
        self.directory = directory or Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "LegionGoBar"
        self.path = self.directory / "settings.json"
        self.lock = RLock()
        self.data = {"version": 1, "settings": {}, "profiles": {}, "quick_tiles": [], "global_profile": {"settings": {}}}
        if self.path.exists():
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict) or loaded.get("version") != 1:
                raise ValueError(f"Unsupported settings format: {self.path}")
            self.data.update(loaded)

    def save(self):
        with self.lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=self.directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    json.dump(self.data, file, indent=2, ensure_ascii=False)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, self.path)
            finally:
                Path(temporary).unlink(missing_ok=True)

    def set(self, key, value):
        with self.lock:
            self.data["settings"][key] = value
            self.save()

    def get(self, key, default=None):
        with self.lock:
            return self.data["settings"].get(key, default)

    def export_profiles(self, path: Path):
        path.write_text(json.dumps({"version": 1, "profiles": self.data["profiles"], "global_profile": self.data["global_profile"]}, indent=2, ensure_ascii=False), encoding="utf-8")

    def import_profiles(self, path: Path):
        if path.suffix.lower() == ".xml":
            from .profile_xml import read_profiles
            imported = read_profiles(path)
        else:
            imported = json.loads(path.read_text(encoding="utf-8"))
        profiles = imported.get("profiles") if isinstance(imported, dict) else None
        if not isinstance(imported, dict) or imported.get("version") != 1 or not isinstance(profiles, dict):
            raise ValueError("Expected LegionGoBar profile export version 1")
        from .profiles import validate_record, canonical
        normalized = {}
        for key, profile in profiles.items():
            if not isinstance(key, str) or not key:
                raise ValueError("Invalid profile path")
            validate_record(profile)
            normalized[canonical(key)] = profile
        if "global_profile" in imported:
            validate_record(imported["global_profile"])
        # 完整校验后一次性保存，写盘失败时恢复内存数据。
        with self.lock:
            previous = copy.deepcopy(self.data)
            try:
                self.data["profiles"].update(normalized)
                if "global_profile" in imported:
                    self.data["global_profile"] = imported["global_profile"]
                self.save()
            except Exception:
                self.data = previous
                raise

        records = [*normalized.values(), imported.get("global_profile", {})]
        return sum(len(record.get("upstream_xml", {})) for record in records)
