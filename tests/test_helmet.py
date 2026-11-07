# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""ARES's icon: the two pixel grids of the helmet, and every size it is shown at."""

import struct
import zlib

import pytest

from ares.gui import icons

COLOURS = {"K": (0, 0, 0), "R": (255, 0, 0), "M": (128, 0, 0), "O": (128, 128, 0),
           "Y": (255, 255, 0), "W": (255, 255, 255)}
# The grids' checksums, to catch one changed by accident.
CHECKSUMS = {"HELMET_32": 0xA7570891, "HELMET_16": 0x641C53B5}


def rows_of(data):
    """The pixels of a PNG image from ares.gui.icons: rows of (r, g, b), None when transparent."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    start = data.index(b"IDAT") + 4
    length = struct.unpack(">I", data[start - 8:start - 4])[0]
    raw = zlib.decompress(data[start:start + length])
    stride = 1 + 4 * width
    rows = []
    for y in range(height):
        line = raw[y * stride + 1:(y + 1) * stride]
        rows.append([tuple(line[i:i + 3]) if line[i + 3] else None
                     for i in range(0, len(line), 4)])
    return rows


def expected(grid, factor, square=None):
    """The rows the grid must give: each letter factor x factor pixels, in the middle."""
    size = len(grid) * factor
    square = square or size
    inset = (square - size) // 2
    rows = [[None] * square for _ in range(square)]
    for y in range(size):
        for x in range(size):
            letter = grid[y // factor][x // factor]
            rows[inset + y][inset + x] = COLOURS.get(letter)
    return rows


@pytest.mark.parametrize("grid, size", [(icons.HELMET_32, 32), (icons.HELMET_16, 16)])
def test_the_grids_are_square_and_use_the_palette(grid, size):
    assert len(grid) == size and {len(row) for row in grid} == {size}
    assert set("".join(grid)) == set("KRMOYW.")
    assert {colour for colour in icons.HELMET_COLOURS.values()} <= set(icons.PALETTE)


def test_the_colours_are_the_helmets():
    assert icons.HELMET_COLOURS == COLOURS


def test_the_grids_have_not_changed():
    assert zlib.crc32("".join(icons.HELMET_32).encode()) == CHECKSUMS["HELMET_32"]
    assert zlib.crc32("".join(icons.HELMET_16).encode()) == CHECKSUMS["HELMET_16"]


@pytest.mark.parametrize("grid, factor", [(icons.HELMET_32, 1), (icons.HELMET_32, 2),
                                          (icons.HELMET_32, 4), (icons.HELMET_16, 1),
                                          (icons.HELMET_16, 3)])
def test_a_pixel_of_the_grid_becomes_a_square_of_one_colour(grid, factor):
    assert rows_of(icons.helmet_png(grid, factor)) == expected(grid, factor)


def test_the_window_pictures_have_their_sizes():
    assert icons.WINDOW_PICTURES == {
        16: (icons.HELMET_16, 1), 32: (icons.HELMET_32, 1), 48: (icons.HELMET_16, 3),
        64: (icons.HELMET_32, 2), 128: (icons.HELMET_32, 4)}


@pytest.mark.parametrize("wanted, grid, factor", [
    (16, icons.HELMET_16, 1),           # 100 %: the title bar
    (32, icons.HELMET_32, 1),           # 100 %: the taskbar; 200 %: the title bar
    (20, icons.HELMET_16, 1),           # 125 %
    (24, icons.HELMET_16, 1),           # 150 %
    (36, icons.HELMET_32, 1),           # 225 %
    (40, icons.HELMET_32, 1),
    (48, icons.HELMET_16, 3),
    (64, icons.HELMET_32, 2),
    (72, icons.HELMET_32, 2),
    (96, icons.HELMET_32, 2),
    (128, icons.HELMET_32, 4),
    (256, icons.HELMET_32, 4),
])
def test_a_place_of_any_size_gets_a_whole_enlargement_on_a_transparent_square(wanted, grid,
                                                                              factor):
    assert rows_of(icons.window_png(wanted)) == expected(grid, factor, wanted)


def test_a_place_too_small_gets_the_smallest_picture():
    assert rows_of(icons.window_png(12)) == expected(icons.HELMET_16, 1)


def test_a_square_too_small_is_refused():
    with pytest.raises(ValueError):
        icons.helmet_png(icons.HELMET_32, 2, 60)


@pytest.mark.parametrize("scale, factor, whole", [(1.0, 2, 2), (1.25, 2, 2), (1.5, 2, 3),
                                                  (2.25, 2, 4), (1.0, 4, 4), (2.25, 4, 9),
                                                  (0.4, 1, 1)])
def test_the_design_factor_is_a_whole_number_that_follows_the_display(monkeypatch, scale, factor,
                                                                      whole):
    monkeypatch.setattr(icons, "scale", lambda widget: scale)
    assert icons.design_factor(None, factor) == whole


def test_the_photos_show_the_same_pixels(tk_root):
    photo = icons.helmet_photo(tk_root, icons.HELMET_16, 3)
    want = expected(icons.HELMET_16, 3)
    assert (photo.width(), photo.height()) == (48, 48)
    assert [[None if photo.transparency_get(x, y) else photo.get(x, y) for x in range(48)]
            for y in range(48)] == want
