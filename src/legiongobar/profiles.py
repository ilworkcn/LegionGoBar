"""游戏、全局和电源配置的保存及选择，独立于界面与硬件调用。"""
import copy
import json
import ntpath
import time

PROFILE_KEYS = {"AutoTDPEnabled", "AutoTDPTargetFPS", "AutoTDPMinTDP", "AutoTDPMaxTDP", "AutoTDPPauseWhenUnfocused", "OSD", "HDREnabled", "FPSLimit", "StickyTDPEnabled", "StickyTDPInterval", "TDP", "CPUBoost", "CPUEPP",
                "TDPBoostEnabled", "TDPBoostSPPT", "TDPBoostFPPT", "OSPowerMode", "Resolution", "RefreshRate",
                "LegionNintendoLayout", "LegionVibration", "LegionVibrationMode", "LegionPerformanceMode",
                "LegionJoystickAsMouseMode", "LegionJoystickMouseSens"}
PREFIXES = ("AMD", "LegionButton", "LegionGyro", "LegionLight", "LegionLeft", "LegionRight")


def profile_key(key):
    return key in PROFILE_KEYS or key.startswith(PREFIXES)


def canonical(path):
    return ntpath.normcase(ntpath.normpath(str(path)))


def capture(snapshot):
    return {key: copy.deepcopy(value) for key, value in snapshot['values'].items()
            if snapshot['capabilities'].get(key) and profile_key(key)}


def merged(record, on_ac, split):
    result = dict(record.get('settings', {}))
    if split:
        result.update(record.get('ac' if on_ac else 'dc', {}))
    return result


def validate_record(record):
    if not isinstance(record, dict) or not isinstance(record.get('settings'), dict):
        raise ValueError('Invalid profile record')
    if 'enabled' in record and type(record['enabled']) is not bool:
        raise ValueError('Invalid profile enabled flag')
    if 'name' in record and not isinstance(record['name'], str):
        raise ValueError('Invalid profile name')
    for scope in ('settings', 'ac', 'dc'):
        values = record.get(scope, {})
        if not isinstance(values, dict):
            raise ValueError('Invalid power source profile')
        for key, value in values.items():
            if not isinstance(key, str) or not profile_key(key):
                raise ValueError('Invalid profile setting key')
            if not isinstance(value, (str, int, float, bool, list, dict)):
                raise ValueError('Invalid profile setting value')
            # 在导入阶段拒绝 NaN/Infinity；协议值仍由各硬件适配器验证。
            json.dumps(value, allow_nan=False)


class Profiles:
    def __init__(self, store):
        self.store = store
        self.active = None
        self.on_ac = None
        self.signature = None
        self.retry_after = 0.0
        self.failed_signature = None
        self.failures = 0

    def save(self, key, snapshot, scope='settings', name=None):
        if scope not in ('settings', 'ac', 'dc'):
            raise ValueError('Invalid profile scope')
        with self.store.lock:
            if key is None:
                record = self.store.data.setdefault('global_profile', {'settings': {}})
            else:
                key = canonical(key)
                record = self.store.data['profiles'].setdefault(key, {'name': name or ntpath.basename(key), 'settings': {}})
            captured = capture(snapshot)
            if key is not None:
                from .profile_fields import selected
                captured = {k: v for k, v in captured.items() if selected(k, self.store.get('ProfileSaveFlags', {}))}
            record[scope] = captured
            self.store.save()
        self.signature = None

    def settings_for(self, key, on_ac):
        split = self.store.get('PowerSourceProfile', False)
        settings = merged(self.store.data.get('global_profile', {}), on_ac, split)
        if key is not None:
            settings.update(merged(self.store.data['profiles'].get(canonical(key), {}), on_ac, split))
        return settings

    def plan(self, path, on_ac, snapshot, own_path=None, now=None):
        now = time.monotonic() if now is None else now
        if now < self.retry_after or on_ac is None:
            return None
        enabled = self.store.get('PerGameProfile', False)
        split = self.store.get('PowerSourceProfile', False)
        key = canonical(path) if path else None
        # 前台暂不可读或正在本程序中操作时，保留当前游戏；电源切换仍然处理。
        if not path or (own_path and key == canonical(own_path)):
            key = self.active
        if not enabled or key not in self.store.data['profiles'] or not self.store.data['profiles'][key].get('enabled', True):
            key = None
        if not enabled and not split and self.active is None and self.signature is None:
            return None
        record = self.store.data.get('global_profile', {})
        if self.on_ac is None:
            baseline = capture(snapshot)
            baseline.update(record.get('settings', {}))
            with self.store.lock:
                self.store.data.setdefault('global_profile', {'settings': {}})['settings'] = baseline
                self.store.save()
        settings = self.settings_for(key, on_ac)
        name = self.store.data['profiles'][key].get('name', ntpath.basename(key)) if key else 'Global Settings'
        # 预设模式由固件管理 TDP，避免把自定义瓦数强行写进预设。
        if settings.get('LegionPerformanceMode', snapshot['values'].get('LegionPerformanceMode')) != 255:
            for field in ('TDP', 'TDPBoostEnabled', 'TDPBoostSPPT', 'TDPBoostFPPT'):
                settings.pop(field, None)
            settings['StickyTDPEnabled'] = False
        available = {k: v for k, v in settings.items() if snapshot['capabilities'].get(k)}
        signature = (key, bool(on_ac), enabled, split, json.dumps(available, sort_keys=True))
        if signature == self.signature or (signature == self.failed_signature and self.failures >= 3):
            return None
        power_changed = self.on_ac is not None and self.on_ac != bool(on_ac)
        mode_changed = 'LegionPerformanceMode' in available and available['LegionPerformanceMode'] != snapshot['values'].get('LegionPerformanceMode')
        changes = {k: v for k, v in available.items() if power_changed or mode_changed or snapshot['values'].get(k) != v}
        return {'key': key, 'on_ac': bool(on_ac), 'name': name, 'signature': signature, 'settings': changes}

    def complete(self, plan, success, now=None):
        if success:
            self.active, self.on_ac, self.signature = plan['key'], plan['on_ac'], plan['signature']
            self.retry_after = 0
            self.failed_signature, self.failures = None, 0
        else:
            self.failures = self.failures + 1 if self.failed_signature == plan['signature'] else 1
            self.failed_signature = plan['signature']
            self.retry_after = (time.monotonic() if now is None else now) + 10

    def remember(self, key, value, on_ac):
        from .profile_fields import selected
        if not profile_key(key) or (self.active and not selected(key, self.store.get('ProfileSaveFlags', {}))):
            return
        scope = ('ac' if on_ac else 'dc') if self.store.get('PowerSourceProfile', False) else 'settings'
        with self.store.lock:
            if self.active and self.store.get('PerGameProfile', False):
                record = self.store.data['profiles'].get(self.active)
                if record is None:
                    return
            else:
                record = self.store.data.setdefault('global_profile', {'settings': {}})
            record.setdefault(scope, {})[key] = copy.deepcopy(value)
            self.store.save()
        self.signature = None
