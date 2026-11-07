# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Per-user settings, kept as JSON in the user's configuration folder.

Loading never fails: a missing, unreadable or damaged file, an unknown key or
a value of the wrong type falls back to the default. An unknown key is gone
from the file the next time it is saved, as the entries of the window's layout
that older versions kept.
"""

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .files import write_file

# The monospaced font of the editor, the tables and the message panes, then the closest ones for
# a system without it (see installed_family), and its size in points: 12 pixels at 96 dots per
# inch (Tk on macOS counts points as pixels).
if sys.platform == "win32":
    CODE_FAMILIES = ("Courier New",)
    DEFAULT_SIZE = 9
elif sys.platform == "darwin":
    CODE_FAMILIES = ("Courier New", "Menlo", "Monaco")
    DEFAULT_SIZE = 12
else:
    CODE_FAMILIES = ("Courier New", "Liberation Mono", "Cousine", "Nimbus Mono PS", "FreeMono",
                     "DejaVu Sans Mono")
    DEFAULT_SIZE = 9
DEFAULT_FONT = CODE_FAMILIES[0]

FONT_SIZES = range(6, 73)
TAB_SIZES = range(1, 17)


@dataclass
class Settings:
    # Settings menu
    show_labels: bool = False
    assemble_on_open: bool = False
    hex_addresses: bool = True
    hex_values: bool = True
    require_capitals: bool = True
    popup_input: bool = False
    backstep_while_running: bool = False
    # Settings > Editor Font...
    font_family: str = DEFAULT_FONT
    font_size: int = DEFAULT_SIZE
    tab_size: int = 4
    tab_spaces: bool = True             # the Tab key inserts spaces
    show_line_numbers: bool = True
    # Restore Defaults keeps this. The window's size and dividers are not settings: every start
    # takes the defaults.
    last_folder: str = ""

    @classmethod
    def load(cls, path):
        """Settings from the file at path, with defaults for anything missing or invalid."""
        settings = cls()
        try:
            # utf-8-sig: a file saved by an editor with a byte-order mark is read too.
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except Exception:               # any damage, even nesting too deep for json
            return settings
        if isinstance(data, dict):
            for f in fields(cls):
                value = data.get(f.name)
                if value is not None and _valid(f.name, value):
                    setattr(settings, f.name, value)
        return settings

    def save(self, path):
        """Write the settings to path, creating its folder; False when that fails."""
        path = Path(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_file(path, json.dumps(asdict(self), indent=2).encode("utf-8"))
        except OSError:
            return False
        return True

    def restore_defaults(self):
        """Reset every setting except the last folder."""
        defaults = Settings()
        for f in fields(self):
            if f.name not in KEPT:
                setattr(self, f.name, getattr(defaults, f.name))


KEPT = frozenset(("last_folder",))
_RANGES = {"font_size": FONT_SIZES, "tab_size": TAB_SIZES}


def _valid(name, value):
    kind = Settings.__dataclass_fields__[name].type
    if kind is bool:
        return isinstance(value, bool)
    if kind is int:
        return type(value) is int and value in _RANGES[name]
    if not isinstance(value, str) or len(value) > 1000:
        return False
    if name == "font_family":
        return value.strip() != ""
    return True


def installed_family(family, installed):
    """The family to draw with: family itself, or for the default family on a system without it,
    the closest of CODE_FAMILIES among the families in installed."""
    if family != DEFAULT_FONT or family in installed:
        return family
    return next((name for name in CODE_FAMILIES if name in installed), family)


def default_path():
    """settings.json in the per-user configuration folder of ARES."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "ARES" / "settings.json"
