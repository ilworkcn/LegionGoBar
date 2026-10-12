"""Capture the checked-out GoTweaks UI and its exact source provenance.

Run explicitly when updating the reference, never at application startup.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

NAME = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"
KINDS = {"Button", "ToggleSwitch", "Slider", "ComboBox", "TextBox", "NumberBox", "RadioButton", "CheckBox", "ColorPicker"}


def tag(e):
    return e.tag.rsplit("}", 1)[-1]


def convert(e):
    return {"type": tag(e), "attrs": {k.rsplit("}", 1)[-1]: v for k, v in e.attrib.items()}, "text": (e.text or "").strip(), "children": [convert(c) for c in e]}


def git(root, *args):
    return subprocess.check_output(["git", f"--git-dir={root / '.git'}", *args], text=True).strip()


def capture(root: Path, output: Path):
    ui = root / "XboxGamingBar/GamingWidget.xaml"
    raw = ui.read_bytes()
    doc = ET.fromstring(raw)
    parents = {c: e for e in doc.iter() for c in e}
    functions = {}
    value = -1
    text = (root / "Shared/Enums/Function.cs").read_text(encoding="utf-8-sig")
    text = re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)
    body = text.split("enum Function", 1)[1].split("{", 1)[1].split("}", 1)[0]
    for entry in body.split(","):
        m = re.fullmatch(r"\s*(\w+)(?:\s*=\s*(\d+))?\s*", entry)
        if m:
            value = int(m[2]) if m[2] else value + 1
            functions[m[1]] = value
    nav = next(e for e in doc.iter() if e.get(NAME) == "MainNavPanel")
    tabs = [{"id": e.get("Tag"), "label": e.get("Content"), "source_name": e.get(NAME)} for e in nav if tag(e) == "RadioButton"]
    pages = {}
    for e in doc.iter():
        name = e.get(NAME, "")
        if tag(e) == "ScrollViewer":
            key = name.removesuffix("ScrollViewer")
            if key == "QuickSettings":
                key = "Quick"
            pages[key] = convert(e)
    controls = []
    # Include static controls, template controls, hidden panels and auxiliary names.
    for e in doc.iter():
        if tag(e) not in KINDS:
            continue
        p = e
        page = "Resources"
        while p in parents:
            p = parents[p]
            if tag(p) == "ScrollViewer":
                page = p.get(NAME, "").removesuffix("ScrollViewer")
                break
        name = e.get(NAME, "")
        controls.append({"name": name, "type": tag(e), "page": page, "attrs": convert(e)["attrs"],
                         "source_line": next((i for i, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1) if name and f'x:Name="{name}"' in line), None)})
    styles = {}
    for e in doc.iter():
        if tag(e) == "Style":
            key = e.get("{http://schemas.microsoft.com/winfx/2006/xaml}Key")
            styles[key] = {c.get("Property"): c.get("Value") for c in e if tag(c) == "Setter" and c.get("Value")}
    data = {"reference": {"branch": git(root, "branch", "--show-current"), "commit": git(root, "rev-parse", "HEAD"),
                         "ui_sha256": hashlib.sha256(raw).hexdigest(), "ui_path": "XboxGamingBar/GamingWidget.xaml"},
            "tabs": tabs, "pages": pages, "styles": styles, "functions": functions, "controls": controls}
    output.mkdir(parents=True, exist_ok=True)
    (output / "reference.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    refs = output.parents[2] / "reference"
    refs.mkdir(exist_ok=True)
    for file in [ui, root / "Shared/Enums/Function.cs", root / "LICENSE"]:
        shutil.copy2(file, refs / ("GoTweaks-LICENSE.txt" if file.name == "LICENSE" else file.name))
    glyphs = root / "XboxGamingBar/Assets/ButtonGlyphs"
    if glyphs.exists():
        shutil.copytree(glyphs, output / "glyphs", dirs_exist_ok=True)
    print(json.dumps({"tabs": len(tabs), "controls": len(controls), "functions": len(functions), **data["reference"]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).parents[1] / "src/legiongobar/assets")
    args = parser.parse_args()
    capture(args.source, args.output)
