"""第一代 Legion Go HID 协议；设备筛选和数据包布局以 GoTweaks 基准为准。"""
from __future__ import annotations

import re
import struct
import time

LEFT, RIGHT = 0x03, 0x04
FAN_FLOORS = [44, 48, 55, 60, 71, 79, 87, 87, 100, 100]
BUTTONS = {"Y1": 0x1C, "Y2": 0x1D, "Y3": 0x1E, "M1": 0x20, "M2": 0x21, "M3": 0x22, "Desktop": 0x25, "Page": 0x26}
GAMEPAD_ACTIONS = [0, *range(3, 17), *range(0x12, 0x1A), 0x23, 0x24, 0x25, 0x26]
# 键名对应上游 KeyboardKey 枚举中的 HID 用法值。
KEYBOARD_KEYS = {chr(65+i): 0x04+i for i in range(26)}
KEYBOARD_KEYS.update({str(i): 0x1D+i for i in range(1,10)})
KEYBOARD_KEYS.update({f"F{i}": 0x39+i for i in range(1,13)})
KEYBOARD_KEYS.update({"0": 0x27, "Enter": 0x28, "Esc": 0x29, "Backspace": 0x2A, "Tab": 0x2B,
                     "Space": 0x2C, "[": 0x2F, "]": 0x30, "PrintScr": 0x46, "Pause": 0x48,
                     "Insert": 0x49, "Home": 0x4A, "PgUp": 0x4B, "Delete": 0x4C, "End": 0x4D,
                     "PgDn": 0x4E, "Right": 0x4F, "Left": 0x50, "Down": 0x51, "Up": 0x52,
                     "LCtrl": 0xE0, "LShift": 0xE1, "LAlt": 0xE2, "LWin": 0xE3,
                     "RCtrl": 0xE4, "RShift": 0xE5, "RAlt": 0xE6, "RWin": 0xE7})

ACTIVATION_BUTTONS = [0, 0x16, 0x17, 0x18, 0x19, 0x1C, 0x1D, 0x21, 0x22]


def bounded(value, lower, upper):
    if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
        raise ValueError(f"Expected integer {lower}..{upper}: {value!r}")
    return value


def report(*payload):
    if len(payload) > 63:
        raise ValueError("HID payload exceeds 63 bytes")
    return bytes([5, *payload]).ljust(64, b"\0")


def matching_devices(devices):
    return [d for d in devices if d["vendor_id"] == 0x17EF and (d["product_id"] & 0xFFF0) == 0x6180 and d.get("usage_page") == 0xFFA0]


def deadzone(side, value):
    return report(6, 0x3F, 6, side, bounded(value, 0, 50), 1)


def trigger(side, start, end):
    bounded(start, 0, 100)
    bounded(end, 0, 100)
    return report(0, 0x0A, 2, side, start, end)


def rgb(mode, color, brightness, speed):
    bounded(mode, 0, 4)
    bounded(brightness, 0, 100)
    bounded(speed, 0, 100)
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError("Expected #RRGGBB color")
    if mode == 0:
        return [report(6, 0x70, 2, side, 0, 1) for side in (LEFT, RIGHT)]
    red, green, blue = bytes.fromhex(color[1:])
    return [report(0x0C, 0x72, 1, side, mode, red, green, blue, brightness, 100 - speed, 3, 1) for side in (LEFT, RIGHT)] + [report(6, 0x73, 2, side, 3, 1) for side in (LEFT, RIGHT)]


def gyro_settings(mapping, x, y, invert_x, invert_y):
    return report(0, 0x0E, 3, RIGHT, 0, 0, bounded(mapping, 0, 1) + 1,
                  bounded(x, 1, 100), bounded(y, 1, 100), 255, 255, 255, 255,
                  2 if invert_x else 1, 2 if invert_y else 1)


def gyro_activation(mode, index):
    bounded(mode, 0, 1)
    bounded(index, 0, 8)
    button = ACTIVATION_BUTTONS[index]
    return report(0, 0x0E, 5, RIGHT, mode + 2, button) if button else report(0, 0x0E, 5, RIGHT, 1)


def button_mapping(button, mapping_type, mappings):
    code = BUTTONS[button]
    side = LEFT if button in ("Y1", "Y2", "Desktop", "Page") else RIGHT
    bounded(mapping_type, 1, 3)
    if not isinstance(mappings, list) or len(mappings) > 16:
        raise ValueError("Expected at most 16 mapping bytes")
    for byte in mappings:
        bounded(byte, 0, 255)
    return report(0, 0x12, 0x0A, side, 1, 0x11, 1, code, mapping_type, *mappings)


def fan_table(values):
    if len(values) != 10:
        raise ValueError("Fan curve requires exactly ten values")
    for value in values:
        bounded(value, 0, 100)
    return struct.pack("<BBI10H", 1, 0, 0, *values).ljust(64, b"\0")


def parse_status(response):
    if len(response) < 32 or bytes(response[:5]) != b"\x04\x00\xb0\x01\x00":
        return None
    result = {"LegionTouchpadEnabled": response[18] == 1,
              "ControllerBatteryLeft": response[21] or None, "ControllerBatteryRight": response[22] or None,
              "ControllerFirmware": bytes([response[30], response[29], response[28], response[31]]).hex().upper()}
    if response[12] == 255:
        result["LegionLightMode"] = 0
    elif 0 <= response[12] <= 3:
        result.update({"LegionLightMode": response[12] + 1, "LegionLightColor": "#" + bytes(response[8:11]).hex(),
                       "LegionLightBrightness": response[11], "LegionLightSpeed": max(0, min(100, 100 - response[13]))})
    return result


class LegionHid:
    def __init__(self, hid_module=None):
        if hid_module is None:
            import hid as hid_module
        self.hid = hid_module

    def available(self):
        return bool(matching_devices(self.hid.enumerate(0x17EF, 0)))

    def send(self, commands, read_status=False):
        devices = matching_devices(self.hid.enumerate(0x17EF, 0))
        if not devices:
            raise RuntimeError("Legion Go HID interface is disconnected")
        device = self.hid.device()
        try:
            device.open_path(devices[0]["path"])
            for command in commands:
                if len(command) != 64 or command[0] != 5:
                    raise ValueError("Invalid Legion Go output report")
                if device.write(command) != len(command):
                    raise OSError("Incomplete HID write; hardware state is uncertain")
                time.sleep(0.05)
            if read_status:
                request = report(0xB0, 1, 0)
                if device.write(request) != len(request):
                    raise OSError("Incomplete HID status request")
                deadline = time.monotonic() + 0.6
                while time.monotonic() < deadline:
                    response = device.read(64, 100)
                    parsed = parse_status(response)
                    if parsed is not None:
                        return parsed
                return None
        finally:
            device.close()

    def read_status(self):
        return self.send([], read_status=True)
