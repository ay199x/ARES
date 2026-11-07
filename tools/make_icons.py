# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Make the program's icon files, ARES.ico and ARES.icns, from ARES's icon grids.

usage: python tools/make_icons.py <folder>

Each size is a grid at a whole factor, with no smoothing, as in the windows' own icons. Both
formats hold their pictures as PNG files, which every Windows and macOS that runs ARES reads.
"""

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ares.gui import icons  # noqa: E402

# Side in pixels: the grid and its factor.
PICTURES = {
    16: (icons.HELMET_16, 1),
    32: (icons.HELMET_32, 1),
    48: (icons.HELMET_16, 3),
    64: (icons.HELMET_32, 2),
    128: (icons.HELMET_32, 4),
    256: (icons.HELMET_32, 8),
    512: (icons.HELMET_32, 16),
    1024: (icons.HELMET_32, 32),
}
ICO_SIDES = (16, 32, 48, 64, 128, 256)
# The four-letter types of an .icns file, by the side of their picture; the "2x" types of the
# smaller sizes are the same pictures again.
ICNS_TYPES = ((b"icp4", 16), (b"ic11", 32), (b"icp5", 32), (b"icp6", 64), (b"ic12", 64),
              (b"ic07", 128), (b"ic08", 256), (b"ic13", 256), (b"ic09", 512), (b"ic14", 512),
              (b"ic10", 1024))


def picture(side):
    """The PNG file of the helmet, side pixels high and wide."""
    grid, factor = PICTURES[side]
    return icons.helmet_png(grid, factor)


def ico():
    """The contents of ARES.ico."""
    pictures = [picture(side) for side in ICO_SIDES]
    place = 6 + 16 * len(pictures)
    header = struct.pack("<HHH", 0, 1, len(pictures))
    directory = b""
    for side, data in zip(ICO_SIDES, pictures):
        byte = side % 256                       # 0 stands for 256
        directory += struct.pack("<BBBBHHII", byte, byte, 0, 0, 1, 32, len(data), place)
        place += len(data)
    return header + directory + b"".join(pictures)


def icns():
    """The contents of ARES.icns."""
    entries = b""
    for kind, side in ICNS_TYPES:
        data = picture(side)
        entries += kind + struct.pack(">I", len(data) + 8) + data
    return b"icns" + struct.pack(">I", len(entries) + 8) + entries


def write_all(folder):
    """Write both files into folder; their paths."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    made = folder / "ARES.ico", folder / "ARES.icns"
    made[0].write_bytes(ico())
    made[1].write_bytes(icns())
    return made


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        raise SystemExit(__doc__)
    for path in write_all(arguments[0]):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
