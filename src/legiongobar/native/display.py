from __future__ import annotations


class WindowsDisplay:
    def __init__(self):
        import win32api
        import win32con
        self.api, self.con = win32api, win32con

    def modes(self):
        result = set()
        index = 0
        while True:
            try:
                mode = self.api.EnumDisplaySettings(None, index)
            except self.api.error:
                break
            result.add((mode.PelsWidth, mode.PelsHeight, mode.DisplayFrequency))
            index += 1
        return sorted(result)

    def current(self):
        mode = self.api.EnumDisplaySettings(None, self.con.ENUM_CURRENT_SETTINGS)
        return {"Resolution": f"{mode.PelsWidth}x{mode.PelsHeight}", "RefreshRate": mode.DisplayFrequency, "DisplayOrientation": mode.DisplayOrientation}

    def set(self, key, value):
        mode = self.api.EnumDisplaySettings(None, self.con.ENUM_CURRENT_SETTINGS)
        if key == "Resolution":
            width, height = map(int, value.split("x"))
            available = [m for m in self.modes() if m[:2] == (width, height)]
            if not available:
                raise ValueError("Resolution not advertised by the display driver")
            if (width, height, mode.DisplayFrequency) not in available:
                raise ValueError("Select a refresh rate supported at this resolution first")
            mode.PelsWidth, mode.PelsHeight = width, height
            mode.Fields = self.con.DM_PELSWIDTH | self.con.DM_PELSHEIGHT
        elif key == "RefreshRate":
            if (mode.PelsWidth, mode.PelsHeight, value) not in self.modes():
                raise ValueError("Refresh rate not supported at the current resolution")
            mode.DisplayFrequency = value
            mode.Fields = self.con.DM_DISPLAYFREQUENCY
        else:
            raise ValueError(key)
        result = self.api.ChangeDisplaySettingsEx(None, mode, self.con.CDS_TEST)
        if result != self.con.DISP_CHANGE_SUCCESSFUL:
            raise OSError(f"Display mode test failed: {result}")
        result = self.api.ChangeDisplaySettingsEx(None, mode, 0)
        if result != self.con.DISP_CHANGE_SUCCESSFUL:
            raise OSError(f"Display mode apply failed: {result}")
        return self.current()[key]
