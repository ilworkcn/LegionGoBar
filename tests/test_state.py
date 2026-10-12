import json

import pytest

from legiongobar.backend import Backend
from legiongobar.storage import Store
from legiongobar.native.wmi import LenovoWmi
from legiongobar.native.scaling import Scaling


def test_failed_adapter_does_not_persist_requested_value(tmp_path):
    store = Store(tmp_path)
    backend = Backend(store)
    backend.capabilities["CPUBoost"] = True
    backend.values["CPUBoost"] = False
    class FailedPower:
        def set(self, *args): raise OSError("Driver rejected request")
    backend.power = FailedPower()
    with pytest.raises(OSError):
        backend.apply("CPUBoost", True)
    assert backend.values["CPUBoost"] is False
    assert store.get("CPUBoost") is None
    assert not store.path.exists()


def test_preview_never_calls_hardware_or_saves_preferences(tmp_path):
    store = Store(tmp_path)
    backend = Backend(store, demo=True)
    backend.discover()
    result = backend.apply("LegionPerformanceMode", 255)
    assert result.value == 255 and not result.verified
    assert backend.wmi is None and not store.path.exists()


def test_unsupported_and_invalid_values_never_reach_driver(tmp_path):
    backend = Backend(Store(tmp_path))
    with pytest.raises(RuntimeError, match="unavailable"):
        backend.apply("ViiperGyroSource", 0)
    backend.capabilities["LegionCustomTDPSlow"] = True
    with pytest.raises(ValueError):
        backend.apply("LegionCustomTDPSlow", 200)


def test_profile_import_validates_entire_file_before_mutation(tmp_path):
    store = Store(tmp_path)
    document = tmp_path / "profiles.json"
    document.write_text(json.dumps({"version": 1, "profiles": {"good": {"settings": {"CPUBoost": False}}, "bad": {"settings": []}}}))
    with pytest.raises(ValueError):
        store.import_profiles(document)
    assert store.data["profiles"] == {} and not store.path.exists()


def test_atomic_store_roundtrip(tmp_path):
    store = Store(tmp_path)
    store.set("CPUEPP", 80)
    assert Store(tmp_path).get("CPUEPP") == 80
    assert not list(tmp_path.glob("*.tmp"))


def test_tdp_partial_failure_restores_all_limits_and_mode():
    class Wmi(LenovoWmi):
        state = {"LegionPerformanceMode": 2, "LegionCustomTDPSlow": 15, "LegionCustomTDPFast": 15, "LegionCustomTDPPeak": 15}
        def get(self, key): return self.state[key]
        def set(self, key, value):
            if key == "LegionCustomTDPFast" and value == 21:
                raise OSError("Fast limit failed")
            self.state[key] = value
            return value
    wmi = Wmi()
    previous = dict(wmi.state)
    with pytest.raises(RuntimeError, match="previous settings restored"):
        wmi.set_tdp(20, 21, 23)
    assert wmi.state == previous


def test_scaling_preserves_unknown_fields_and_makes_backup(tmp_path):
    file = tmp_path / "Settings.xml"
    original = '<Settings><GameProfiles><Profile><Title>Default</Title><ScalingType>Off</ScalingType><Sharpness>50</Sharpness><Unknown>keep</Unknown></Profile></GameProfiles></Settings>'
    file.write_text(original)
    scaling = Scaling(file)
    caps, values = scaling.discover()
    scaling.stage("LosslessScalingSharpness", 80)
    assert "<Sharpness>50</Sharpness>" in file.read_text()
    scaling.save()
    assert "<Unknown>keep</Unknown>" in file.read_text()
    assert "<Sharpness>80</Sharpness>" in file.read_text()
    assert file.with_suffix(".xml.legiongobar.bak").read_text() == original


def test_scaling_external_edit_is_not_overwritten(tmp_path):
    file = tmp_path / "Settings.xml"
    file.write_text('<Settings><Profile><Title>Default</Title><Sharpness>50</Sharpness></Profile></Settings>')
    scaling = Scaling(file)
    scaling.discover()
    scaling.stage("LosslessScalingSharpness", 80)
    file.write_text(file.read_text().replace("50", "60"))
    with pytest.raises(RuntimeError, match="changed externally"):
        scaling.save()
    assert "<Sharpness>60</Sharpness>" in file.read_text()
