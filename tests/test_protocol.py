import struct

import pytest

from legiongobar.backend import Backend, HID_DEFAULTS
from legiongobar.native import legion_hid as hid


def test_back_button_packet_matches_reference_y1_keyboard():
    # GoTweaks SetButtonMappingWithType command; Ctrl+A HID usages E0,04.
    packet = hid.button_mapping("Y1", 2, [0xE0, 0x04])
    assert packet[:12] == bytes.fromhex("05 00 12 0A 03 01 11 01 1C 02 E0 04")
    assert len(packet) == 64 and packet[12:] == bytes(52)


def test_light_packets_use_percent_brightness_and_inverted_speed():
    packets = hid.rgb(2, "#1264ff", 73, 88)
    assert packets[0][:13] == bytes.fromhex("05 0C 72 01 03 02 12 64 FF 49 0C 03 01")
    assert packets[1][4] == 4
    assert packets[2][:7] == bytes.fromhex("05 06 73 02 03 03 01")


def test_light_mode_enables_leds_before_profile_and_color_off_is_cached():
    settings = {**HID_DEFAULTS, "LegionLightMode": 1}
    packets = Backend.hid_commands("LegionLightMode", 1, settings)
    assert packets[0][:7] == bytes.fromhex("05 06 70 02 03 01 01")
    assert Backend.hid_commands("LegionLightColor", "#ff0000", {**settings, "LegionLightMode": 0}) == []


def test_gyro_ui_indices_are_translated_to_firmware_codes():
    settings = {**HID_DEFAULTS, "LegionGyroMappingType": 1, "LegionGyroInvertX": True}
    packet = Backend.hid_commands("LegionGyroMappingType", 1, settings)[0]
    assert packet[:16] == bytes.fromhex("05 00 0E 03 04 00 00 02 32 32 FF FF FF FF 02 01")
    assert hid.gyro_activation(1, 2)[:7] == bytes.fromhex("05 00 0E 05 04 03 17")


def test_fan_table_matches_firmware_64_byte_layout():
    values = [44, 48, 55, 60, 71, 79, 87, 87, 100, 100]
    table = hid.fan_table(values)
    assert len(table) == 64 and table[:6] == b"\x01\0\0\0\0\0"
    assert struct.unpack_from("<10H", table, 6) == tuple(values)
    assert table[26:] == bytes(38)


@pytest.mark.parametrize("value", [-1, 51, True, "4"])
def test_invalid_deadzone_cannot_create_a_report(value):
    with pytest.raises(ValueError):
        hid.deadzone(hid.LEFT, value)


def test_device_matching_excludes_go_s_go2_and_gamepad_collection():
    devices = [{"vendor_id": 0x17EF, "product_id": product, "usage_page": usage} for product, usage in
               [(0x6182, 0xFFA0), (0x61E2, 0xFFA0), (0x6182, 1), (0x618F, 0xFFA0)]]
    assert [device["product_id"] for device in hid.matching_devices(devices)] == [0x6182, 0x618F]


def test_status_decodes_firmware_byte_order_and_off_sentinel():
    response = bytearray(64)
    response[:5] = bytes.fromhex("04 00 B0 01 00")
    response[8:14] = bytes([18, 100, 255, 73, 1, 12])
    response[18], response[21], response[22] = 1, 65, 0
    response[28:32] = bytes.fromhex("31 60 02 0A")
    parsed = hid.parse_status(response)
    assert parsed["ControllerFirmware"] == "0260310A"
    assert parsed["LegionLightColor"] == "#1264ff"
    assert parsed["LegionLightMode"] == 2 and parsed["LegionLightSpeed"] == 88
    assert parsed["ControllerBatteryRight"] is None
    response[12] = 255
    assert hid.parse_status(response)["LegionLightMode"] == 0
    assert "LegionLightColor" not in hid.parse_status(response)
    assert hid.parse_status(b"\x04\0\xa1") is None


def test_partial_hid_write_fails_and_closes_handle():
    class Device:
        closed = False
        def open_path(self, path): pass
        def write(self, packet): return 12
        def close(self): self.closed = True
    device = Device()
    class Module:
        def enumerate(self, *args):
            return [{"vendor_id": 0x17EF, "product_id": 0x6182, "usage_page": 0xFFA0, "path": b"test"}]
        def device(self): return device
    with pytest.raises(OSError, match="Incomplete"):
        hid.LegionHid(Module()).send([hid.deadzone(hid.LEFT, 4)])
    assert device.closed
