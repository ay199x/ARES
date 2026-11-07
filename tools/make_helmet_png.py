# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Make docs/ares-helmet.png, the picture at the top of the README, from ARES's icon grids.

usage: python tools/make_helmet_png.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ares.gui import icons  # noqa: E402

TARGET = ROOT / "docs" / "ares-helmet.png"
FACTOR = 4                      # each pixel of the 32 x 32 grid becomes 4 x 4 pixels


def picture():
    """The PNG image of the README's helmet."""
    return icons.helmet_png(icons.HELMET_32, FACTOR)


def main():
    TARGET.parent.mkdir(exist_ok=True)
    TARGET.write_bytes(picture())
    print(TARGET)
    return 0


if __name__ == "__main__":
    sys.exit(main())
