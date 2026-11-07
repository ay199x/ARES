# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""ARES's icons: the shaded toolbar, the pixel art of the others, disabled pictures, Tk images."""

import binascii
import struct
import time
import zlib

import pytest
from conftest import new_root

from ares.gui import icons, style, widgets
from ares.gui.app import CLOSE_ICON_SIZE, ICON_SIZE, PAGE_ICON_SIZE
from ares.gui.dialogs import DIALOG_ICON_SIZE

NAMES = icons.TOOLBAR + icons.OTHER
SCALES = (1, 1.25, 1.5, 1.75, 2, 2.25, 2.5, 3)
TOOLBAR_SCALES = (1, 1.5, 2.25)
SHADOWED = ("message_error", "message_information", "message_warning", "message_question")
RUN = ("go", "step", "backstep", "pause", "stop", "reset")
ROUND = ("go", "pause", "stop", "reset")       # the run controls on the same large disc
# The 16 colours of the Windows 98 palette, written out here and not taken from the
# module, so that a wrong value there is caught; one letter each, for the pinned pictures.
LETTERS = {"K": (0, 0, 0), "W": (255, 255, 255), "S": (192, 192, 192), "D": (128, 128, 128),
           "M": (128, 0, 0), "R": (255, 0, 0), "O": (128, 128, 0), "Y": (255, 255, 0),
           "G": (0, 128, 0), "L": (0, 255, 0), "T": (0, 128, 128), "C": (0, 255, 255),
           "N": (0, 0, 128), "B": (0, 0, 255), "P": (128, 0, 128), "F": (255, 0, 255)}
BLACK, WHITE, SILVER, GRAY = LETTERS["K"], LETTERS["W"], LETTERS["S"], LETTERS["D"]
MAROON, RED, OLIVE, YELLOW = LETTERS["M"], LETTERS["R"], LETTERS["O"], LETTERS["Y"]
GREEN, LIME, TEAL, AQUA = LETTERS["G"], LETTERS["L"], LETTERS["T"], LETTERS["C"]
NAVY, BLUE, PURPLE, FUCHSIA = LETTERS["N"], LETTERS["B"], LETTERS["P"], LETTERS["F"]
# The style's colours of a raised button: close_active's only.
FACE, LIGHT, SHADOW = (0xEE, 0xEE, 0xEE), (0xF7, 0xF7, 0xF7), (0x8E, 0x8E, 0x8E)


def chunks(data):
    """The (kind, payload) chunks of a PNG file, checking the signature and every CRC."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    result = []
    pos = 8
    while pos < len(data):
        length, = struct.unpack(">I", data[pos:pos + 4])
        kind, payload = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + length]
        crc, = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])
        assert binascii.crc32(kind + payload) == crc, kind
        result.append((kind, payload))
        pos += 12 + length
    return result


def decode(data):
    """The pixels of an icon PNG as rows of (red, green, blue, alpha) tuples."""
    parts = chunks(data)
    assert parts[0][0] == b"IHDR" and parts[-1] == (b"IEND", b"")
    width, height, depth, color_type, compression, filters, interlace = struct.unpack(
        ">IIBBBBB", parts[0][1])
    assert (depth, color_type, compression, filters, interlace) == (8, 6, 0, 0, 0)
    raw = zlib.decompress(b"".join(payload for kind, payload in parts if kind == b"IDAT"))
    stride = 1 + 4 * width
    assert len(raw) == height * stride
    rows = []
    for y in range(height):
        line = raw[y * stride:(y + 1) * stride]
        assert line[0] == 0                         # filter type None
        rows.append([tuple(line[i:i + 4]) for i in range(1, stride, 4)])
    return rows


def size_at(name, scale):
    """The icon's size in pixels at a display scale, as the window asks for it."""
    return round(icons.BASES[name] * scale)


def outline(name, size):
    """k: the width of the icon's outlines at size, in pixels."""
    return max(1, round(size / icons.BASES[name]))


def picture(name, scale=1, disabled=False):
    """The icon at a display scale: rows of (red, green, blue), None where transparent."""
    return pixels(icons.png(name, size_at(name, scale), disabled))


def pixels(data):
    """The pixels of an icon PNG: rows of (red, green, blue), None where transparent."""
    return [[pixel[:3] if pixel[3] else None for pixel in row] for row in decode(data)]


def extent(rows):
    """(left, top, right, bottom) of the opaque pixels of a picture, inclusive."""
    found = [(x, y) for y, row in enumerate(rows) for x, pixel in enumerate(row)
             if pixel is not None]
    return (min(x for x, y in found), min(y for x, y in found),
            max(x for x, y in found), max(y for x, y in found))


def pieces(rows, colour):
    """The number of pieces of colour: groups of its pixels joined left, right, up or down."""
    size = len(rows)
    seen = set()
    count = 0
    for start in ((x, y) for y in range(size) for x in range(size) if rows[y][x] == colour):
        if start in seen:
            continue
        count += 1
        seen.add(start)
        todo = [start]
        while todo:
            x, y = todo.pop()
            for near in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if (0 <= near[0] < size and 0 <= near[1] < size and near not in seen
                        and rows[near[1]][near[0]] == colour):
                    seen.add(near)
                    todo.append(near)
    return count


def runs(line):
    """The runs of equal pixels along a line: [(colour, length)]."""
    result = []
    for pixel in line:
        if result and result[-1][0] == pixel:
            result[-1] = (pixel, result[-1][1] + 1)
        else:
            result.append((pixel, 1))
    return result


def assert_edged(line, inside, k):
    """Each shape crossed by line is k black pixels, then inside, then k black pixels."""
    shapes = [[]]
    for colour, length in runs(line):
        if colour is None:
            shapes.append([])
        else:
            shapes[-1].append((colour, length))
    shapes = [shape for shape in shapes if shape]
    assert shapes
    for shape in shapes:
        assert shape[0] == (BLACK, k) and shape[-1] == (BLACK, k), shape
        assert shape[1][0] == inside and shape[-2][0] == inside, shape


# The set of icons ----------------------------------------------------------

def test_the_icons_and_their_grids():
    assert icons.TOOLBAR == ("new", "open", "save", "save_as", "undo", "redo", "cut", "copy",
                             "paste", "find", "assemble", "go", "step", "backstep", "pause",
                             "stop", "reset", "help")
    assert icons.OTHER == ("close", "close_active", "page_previous", "page_next",
                           "message_error", "message_information", "message_warning",
                           "message_question")
    # Each icon's grid is as many units wide as the window shows it in design pixels.
    assert {icons.BASES[name] for name in icons.TOOLBAR} == {ICON_SIZE}
    assert icons.BASES["close"] == icons.BASES["close_active"] == CLOSE_ICON_SIZE
    assert icons.BASES["page_previous"] == icons.BASES["page_next"] == PAGE_ICON_SIZE
    assert {icons.BASES[name] for name in SHADOWED} == {DIALOG_ICON_SIZE}
    assert set(icons.BASES) == set(NAMES)


@pytest.mark.parametrize("name", ["compile", "checkbox", "checkbox_on"])
def test_unknown_name_raises_key_error(tk_root, name):
    with pytest.raises(KeyError):
        icons.png(name, 24)
    with pytest.raises(KeyError):
        icons.photo(tk_root, name, 24)


@pytest.mark.parametrize("disabled", [False, True])
@pytest.mark.parametrize("size", [8, 16, 24, 54, 72])
@pytest.mark.parametrize("name", NAMES)
def test_every_icon_is_a_square_rgba_png(name, size, disabled):
    rows = decode(icons.png(name, size, disabled))
    assert len(rows) == size and all(len(row) == size for row in rows)
    assert any(pixel[3] for row in rows for pixel in row)


@pytest.mark.parametrize("size", [8, 256])
def test_smallest_and_largest_sizes(size):
    assert len(decode(icons.png("go", size))) == size
    assert len(decode(icons.png("message_question", size, disabled=True))) == size


@pytest.mark.parametrize("size", [0, 7, 257])
def test_size_out_of_range_is_refused(size):
    with pytest.raises(ValueError):
        icons.png("go", size)


@pytest.mark.parametrize("name", NAMES)
def test_output_is_deterministic(name):
    assert icons.png(name, 36) == icons.png(name, 36)
    assert icons.png(name, 36, disabled=True) == icons.png(name, 36, disabled=True)


# The toolbar: shaded pictures, with soft edges only where a side is not straight ---------

def picture_at(name, size, disabled=False):
    """The icon at size pixels: rows of (red, green, blue), None where transparent."""
    return pixels(icons.png(name, size, disabled))


def rgba(name, scale, disabled=False):
    """Every pixel of the icon at a display scale, as (x, y, red, green, blue, alpha)."""
    rows = decode(icons.png(name, size_at(name, scale), disabled))
    return [(x, y, *pixel) for y, row in enumerate(rows) for x, pixel in enumerate(row)]


def solid(name, scale, disabled=False):
    """The pixels of the icon that are nearly opaque, as (x, y, red, green, blue)."""
    return [pixel[:5] for pixel in rgba(name, scale, disabled) if pixel[5] >= 192]


def share(found, test):
    """The share of the pixels found, as (x, y, red, green, blue), that test(r, g, b) accepts."""
    return sum(test(*pixel[2:5]) for pixel in found) / len(found)


def is_green(red, green, blue):
    return green > red + 24 and green > blue + 24


def is_blue(red, green, blue):
    return blue > red + 24 and blue >= green


def is_yellow(red, green, blue):
    return red > 192 and green > 160 and blue < 128


def is_brown(red, green, blue):
    return red > green + 24 > blue + 48


def is_ink(red, green, blue):
    return max(red, green, blue) < 80


def is_white(red, green, blue):
    return min(red, green, blue) >= 216


@pytest.mark.parametrize("disabled", [False, True])
@pytest.mark.parametrize("scale", TOOLBAR_SCALES)
@pytest.mark.parametrize("name", icons.TOOLBAR)
def test_toolbar_icon_has_its_size_and_is_not_empty(name, scale, disabled):
    rows = decode(icons.png(name, size_at(name, scale), disabled))
    size = size_at(name, scale)
    assert len(rows) == size and all(len(row) == size for row in rows)
    opaque = sum(pixel[3] >= 192 for row in rows for pixel in row)
    assert opaque >= size * size // 6


@pytest.mark.parametrize("disabled", [False, True])
@pytest.mark.parametrize("scale", TOOLBAR_SCALES)
def test_toolbar_icons_are_distinct(scale, disabled):
    drawn = [icons.png(name, size_at(name, scale), disabled) for name in icons.TOOLBAR]
    assert len({zlib.decompress(chunks(data)[1][1]) for data in drawn}) == len(drawn)


@pytest.mark.parametrize("scale", TOOLBAR_SCALES)
@pytest.mark.parametrize("name", icons.TOOLBAR)
def test_toolbar_icons_are_shaded(name, scale):
    # Soft shading: more colours than the 16 of the Windows 98 palette.
    assert len({pixel[2:5] for pixel in rgba(name, scale) if pixel[5]}) > 16


@pytest.mark.parametrize("scale", TOOLBAR_SCALES)
@pytest.mark.parametrize("name", icons.TOOLBAR)
def test_a_disabled_toolbar_icon_is_a_gray_ghost(name, scale):
    normal, ghost = rgba(name, scale), rgba(name, scale, disabled=True)
    assert ghost != normal
    assert all(red == green == blue for _, _, red, green, blue, alpha in ghost if alpha)
    # The same shape, every pixel lighter than half way to black.
    assert [pixel[5] for pixel in ghost] == [pixel[5] for pixel in normal]
    assert all(red >= 128 for _, _, red, _, _, alpha in ghost if alpha)


@pytest.mark.parametrize("scale", TOOLBAR_SCALES)
def test_run_controls_stay_distinct_when_disabled(scale):
    shapes = [rgba(name, scale, disabled=True) for name in RUN]
    assert all(a != b for i, a in enumerate(shapes) for b in shapes[i + 1:])


@pytest.mark.parametrize("scale", TOOLBAR_SCALES)
def test_the_large_run_controls_share_their_disc(scale):
    # Only the mark in the middle tells them apart.
    alphas = {tuple(pixel[5] for pixel in rgba(name, scale)) for name in ROUND}
    assert len(alphas) == 1
    size = size_at("go", scale)
    assert alphas.pop()[(size // 2) * size + size // 2] == 255


@pytest.mark.parametrize("scale", TOOLBAR_SCALES)
@pytest.mark.parametrize("name", ROUND + ("step",))
def test_run_controls_are_green_discs_with_a_white_mark(name, scale):
    found = solid(name, scale)
    assert share(found, is_green) >= 0.4
    assert share(found, is_white) >= 0.1


def stem_side(name, scale):
    """Where the 1 of a step is: the mean x of its ink in the lower half, over size."""
    size = size_at(name, scale)
    dark = [pixel[0] for pixel in solid(name, scale)
            if pixel[1] >= size * 11 // 24 and is_ink(*pixel[2:5])]
    return sum(dark) / len(dark) / size


@pytest.mark.parametrize("scale", TOOLBAR_SCALES)
def test_the_1_of_step_is_at_the_right_and_of_backstep_at_the_left(scale):
    assert stem_side("step", scale) > 0.7
    assert stem_side("backstep", scale) < 0.3


def mean_x(found):
    return sum(pixel[0] for pixel in found) / len(found)


@pytest.mark.parametrize("scale", TOOLBAR_SCALES)
def test_step_and_backstep_point_opposite_ways(scale):
    # The white triangle's narrow rows, at its top and bottom, are on the side of its base.
    def lean(name):
        whites = [pixel for pixel in solid(name, scale) if is_white(*pixel[2:5])]
        width = {y: sum(1 for pixel in whites if pixel[1] == y)
                 for y in {pixel[1] for pixel in whites}}
        narrow = [pixel for pixel in whites if width[pixel[1]] <= max(width.values()) // 4]
        return mean_x(whites) - mean_x(narrow)
    assert lean("go") > 0 and lean("step") > 0 > lean("backstep")


@pytest.mark.parametrize("scale", TOOLBAR_SCALES)
def test_step_and_backstep_discs_mirror_each_other(scale):
    # Above the 1s, the two pictures have the same shape, mirrored.
    size = size_at("step", scale)
    step = [[pixel[3] for pixel in row] for row in decode(icons.png("step", size))]
    back = [[pixel[3] for pixel in row] for row in decode(icons.png("backstep", size))]
    assert step[:size // 2] == [row[::-1] for row in back[:size // 2]]


@pytest.mark.parametrize("scale", TOOLBAR_SCALES)
def test_pause_has_two_bars_and_stop_one_square(scale):
    size = size_at("pause", scale)

    def whites_across(name):
        rows = picture_at(name, size)
        return [colour for colour, _ in runs(
            [pixel is not None and is_white(*pixel) for pixel in rows[size // 2]])].count(True)
    assert whites_across("pause") == 2
    assert whites_across("stop") == 1


@pytest.mark.parametrize("scale", TOOLBAR_SCALES)
def test_reset_points_left_twice(scale):
    size = size_at("reset", scale)
    rows = picture_at("reset", size)
    middle = [pixel is not None and is_white(*pixel) for pixel in rows[size // 2]]
    assert [colour for colour, _ in runs(middle)].count(True) == 2
    # Above the middle the marks lean to the right: their tips are at the left.
    upper = [pixel is not None and is_white(*pixel) for pixel in rows[size * 3 // 8]]
    assert upper.index(True) > middle.index(True)


@pytest.mark.parametrize("scale", TOOLBAR_SCALES)
@pytest.mark.parametrize("name, test, least", [
    ("open", is_blue, 0.3), ("save", is_blue, 0.2), ("save_as", is_blue, 0.2),
    ("cut", is_blue, 0.2), ("paste", is_brown, 0.2), ("assemble", is_blue, 0.1),
    ("help", is_blue, 0.4), ("backstep", is_blue, 0.3)])
def test_colours_that_tell_an_icon(name, test, least, scale):
    assert share(solid(name, scale), test) >= least


@pytest.mark.parametrize("scale", TOOLBAR_SCALES)
def test_new_is_a_white_page_with_a_yellow_star_at_its_corner(scale):
    size = size_at("new", scale)
    found = solid("new", scale)
    assert share(found, is_white) >= 0.4
    yellow = [pixel for pixel in rgba("new", scale) if pixel[5] and is_yellow(*pixel[2:5])]
    assert yellow
    assert all(pixel[0] >= size / 2 and pixel[1] < size / 2 for pixel in yellow)


@pytest.mark.parametrize("scale", TOOLBAR_SCALES)
def test_undo_points_left_and_redo_right(scale):
    size = size_at("undo", scale)

    def head(name):
        """The mean x of the upper half of the arrow, the side of its head."""
        return mean_x([pixel for pixel in solid(name, scale) if pixel[1] < size / 2]) / size
    assert head("undo") < 0.5 < head("redo")


def swapped(pixels, size):
    """The pixels of rgba(), left and right swapped, sorted."""
    return sorted((size - 1 - x, y, *rest) for x, y, *rest in pixels)


def contrast(first, second):
    """The contrast ratio of two colours "#RRGGBB", from 1 to 21."""
    def lightness(colour):
        parts = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        red, green, blue = (part / 12.92 if part <= 0.03928 else ((part + 0.055) / 1.055) ** 2.4
                            for part in parts)
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue
    darker, lighter = sorted((lightness(first), lightness(second)))
    return (lighter + 0.05) / (darker + 0.05)


@pytest.mark.parametrize("scale", TOOLBAR_SCALES)
def test_undo_is_yellow_and_redo_green(scale):
    assert share(solid("undo", scale), is_yellow) >= 0.5
    assert share(solid("redo", scale), is_green) >= 0.5
    assert not share(solid("undo", scale), is_green)
    assert not share(solid("redo", scale), is_yellow)


@pytest.mark.parametrize("edge", [icons.UNDO_EDGE, icons.REDO_EDGE])
def test_the_outlines_of_undo_and_redo_read_on_the_button_face(edge):
    assert contrast(edge, style.FACE) >= 3.5


@pytest.mark.parametrize("scale", TOOLBAR_SCALES)
@pytest.mark.parametrize("name, edge", [("undo", icons.UNDO_EDGE), ("redo", icons.REDO_EDGE)])
def test_the_outlines_of_undo_and_redo_are_there_at_every_scale(name, edge, scale):
    colour = tuple(int(edge[i:i + 2], 16) for i in (1, 3, 5))
    found = sum(tuple(pixel[2:5]) == colour for pixel in solid(name, scale))
    assert found >= size_at(name, scale) // 2


@pytest.mark.parametrize("scale", SCALES)
def test_redo_has_the_shape_of_undo_mirrored(scale):
    size = size_at("undo", scale)

    def shape(name):
        return [(x, y, alpha) for x, y, _, _, _, alpha in rgba(name, scale)]
    assert sorted((size - 1 - x, y, alpha) for x, y, alpha in shape("undo")) == sorted(shape("redo"))


@pytest.mark.parametrize("scale", SCALES)
def test_disabled_undo_and_redo_are_one_even_gray(scale):
    # Yellow is far lighter than green: their own lightness would give two different ghosts,
    # the yellow one nearly as light as the button.
    size = size_at("undo", scale)
    undo, redo = rgba("undo", scale, True), rgba("redo", scale, True)
    assert swapped(undo, size) == sorted(redo)


@pytest.mark.parametrize("scale", TOOLBAR_SCALES)
def test_disabled_undo_stays_as_dark_as_the_other_disabled_icons(scale):
    found = solid("undo", scale, True)
    assert sum(pixel[2] for pixel in found) / len(found) <= 210


@pytest.mark.parametrize("scale", TOOLBAR_SCALES)
def test_the_page_of_new_has_crisp_straight_sides(scale):
    # A straight upright side falls between pixels: no soft pixels along it.
    size = size_at("new", scale)
    row = decode(icons.png("new", size))[size * 3 // 4]
    assert {pixel[3] for pixel in row} == {0, 255}


@pytest.mark.parametrize("name", icons.TOOLBAR)
def test_toolbar_pictures_do_not_change_when_made_again(name):
    first = icons.png(name, 36)
    icons.forget_pictures()
    assert icons.png(name, 36) == first


# Crisp pixels in few colours of the Windows 98 palette, for the other icons -----------

def test_the_windows_98_palette():
    assert len(icons.PALETTE) == 16 and set(icons.PALETTE) == set(LETTERS.values())
    named = {"BLACK": BLACK, "WHITE": WHITE, "SILVER": SILVER, "GRAY": GRAY, "MAROON": MAROON,
             "RED": RED, "OLIVE": OLIVE, "YELLOW": YELLOW, "GREEN": GREEN, "LIME": LIME,
             "TEAL": TEAL, "AQUA": AQUA, "NAVY": NAVY, "BLUE": BLUE, "PURPLE": PURPLE,
             "FUCHSIA": FUCHSIA}
    assert {name: getattr(icons, name) for name in named} == named


@pytest.mark.parametrize("disabled", [False, True])
@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("name", icons.OTHER)
def test_crisp_in_the_palette(name, scale, disabled):
    allowed = set(LETTERS.values()) - {PURPLE, FUCHSIA}
    if name == "close_active":
        allowed |= {FACE, LIGHT, SHADOW}
    for row in decode(icons.png(name, size_at(name, scale), disabled)):
        for red, green, blue, alpha in row:
            assert alpha in (0, 255)
            assert not alpha or (red, green, blue) in allowed


@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("name", icons.OTHER)
def test_few_colours_and_small_highlights(name, scale):
    opaque = [pixel for row in picture(name, scale) for pixel in row if pixel]
    assert BLACK in opaque and len(set(opaque)) <= 5
    highlights = sum(pixel in (LIME, AQUA) for pixel in opaque)
    assert 20 * highlights <= len(opaque)


COLOURS = {     # the colours of each icon besides black, at 100 %
    "close": set(), "close_active": {FACE, LIGHT, WHITE, SHADOW},
    "page_previous": {GREEN}, "page_next": {GREEN},
    "message_error": {RED, WHITE, GRAY}, "message_information": {WHITE, BLUE, GRAY},
    "message_warning": {YELLOW, GRAY}, "message_question": {WHITE, BLUE, GRAY},
}


@pytest.mark.parametrize("name", icons.OTHER)
def test_colours_of_each_icon(name):
    assert {pixel for row in picture(name) for pixel in row if pixel} == COLOURS[name] | {BLACK}


def colours_and_shadow(name, rows):
    """The colours of an icon besides black and besides its drop shadow, which tapers to
    nothing at both ends."""
    found = {pixel for row in rows for pixel in row if pixel} - {BLACK}
    return found - {GRAY} if name in SHADOWED else found


@pytest.mark.parametrize("name", icons.OTHER)
def test_no_colour_falls_apart(name):
    # A stroke too thin for its outline (two pixels at 150 %, where a unit is one and a
    # half) breaks apart or leaves a lone pixel: at every scale each colour is in as many
    # pieces as at 300 %.
    largest = picture(name, 3)
    expected = {colour: pieces(largest, colour) for colour in colours_and_shadow(name, largest)}
    for scale in SCALES:
        rows = picture(name, scale)
        assert {colour: pieces(rows, colour) for colour in colours_and_shadow(name, rows)} \
            == expected, scale


@pytest.mark.parametrize("name", icons.OTHER)
def test_every_colour_keeps_its_share(name):
    # The outlines must not eat a colour: at every scale each colour besides black covers
    # at least half as much of the icon's pixels as at 100 %.
    def shares(rows):
        opaque = [pixel for row in rows for pixel in row if pixel]
        return {colour: opaque.count(colour) / len(opaque) for colour in set(opaque) - {BLACK}}
    smallest = shares(picture(name))
    for scale in SCALES:
        found = shares(picture(name, scale))
        assert all(2 * found.get(colour, 0) >= share for colour, share in smallest.items()), \
            (scale, found, smallest)


# Black outlines ---------------------------------------------------------------

def outside_edge(rows):
    """The colours of the opaque pixels beside a transparent pixel or the image's edge."""
    size = len(rows)
    found = set()
    for y, row in enumerate(rows):
        for x, pixel in enumerate(row):
            if pixel is not None and any(
                    not (0 <= x + dx < size and 0 <= y + dy < size) or rows[y + dy][x + dx] is None
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                found.add(pixel)
    return found


@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("name", [name for name in icons.OTHER if name != "close_active"])
def test_black_outlines(name, scale):
    # The dialogs' icons have a gray shadow below and right of them.
    assert outside_edge(picture(name, scale)) <= ({BLACK, GRAY} if name in SHADOWED else {BLACK})


# The pairs of colours, neither of them black, that may touch: a mark on a shape, which
# has no outline of its own. Anywhere else a black outline lies between two colours.
MARKS = {
    "message_error": [(RED, WHITE)], "message_information": [(WHITE, BLUE)],
    "message_question": [(WHITE, BLUE)],
}


@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("name", [name for name in icons.OTHER if name != "close_active"])
def test_colours_meet_only_across_a_black_outline(name, scale):
    rows = picture(name, scale)
    size = len(rows)
    touching = {frozenset((rows[y][x], rows[y + dy][x + dx]))
                for y in range(size) for x in range(size) for dx, dy in ((1, 0), (0, 1))
                if x + dx < size and y + dy < size}
    touching = {pair for pair in touching if len(pair) == 2 and not pair & {None, BLACK}}
    assert touching <= {frozenset(pair) for pair in MARKS.get(name, ())}


@pytest.mark.parametrize("scale", SCALES)
def test_outlines_are_k_pixels_wide_along_straight_sides(scale):
    page = picture("page_next", scale)
    size = len(page)
    assert_edged([row[size // 4] for row in page], GREEN, outline("page_next", size))


@pytest.mark.parametrize("scale", SCALES)
def test_slanted_outlines_are_k_pixels_per_row(scale):
    rows = picture("page_next", scale)
    k = outline("page_next", len(rows))
    for row in rows:
        if GREEN in row:
            last = max(x for x, pixel in enumerate(row) if pixel == GREEN)
            assert row[last + 1:last + 1 + k] == [BLACK] * k and row[last + 1 + k] is None


def stays_clear(rows, unit):
    """Whether every opaque pixel of a picture is at least unit pixels from its edge."""
    size = len(rows)
    return all(unit <= x + 0.5 <= size - unit and unit <= y + 0.5 <= size - unit
               for y, row in enumerate(rows) for x, pixel in enumerate(row) if pixel is not None)


@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("name", [name for name in icons.OTHER if name != "close_active"])
def test_one_design_unit_clear_of_the_image_edge(name, scale):
    rows = picture(name, scale)
    assert stays_clear(rows, len(rows) / icons.BASES[name])


@pytest.mark.parametrize("disabled", [False, True])
@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("name", icons.TOOLBAR)
def test_toolbar_icons_stay_clear_of_the_image_edge(name, scale, disabled):
    # What can be seen of them: a pixel covered less than half is only a soft edge.
    rows = decode(icons.png(name, size_at(name, scale), disabled))
    visible = [[pixel if pixel[3] >= 128 else None for pixel in row] for row in rows]
    assert stays_clear(visible, len(rows) / icons.BASES[name])


@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("name", ["page_previous", "page_next"])
def test_disabled_pictures_stay_clear_of_the_edge(name, scale):
    # Their white copy lies k pixels right of and below the shape.
    rows = picture(name, scale, disabled=True)
    assert stays_clear(rows, len(rows) / icons.BASES[name])


@pytest.mark.parametrize("name", icons.TOOLBAR + ("page_previous", "page_next"))
def test_icons_are_in_the_middle(name):
    rows = picture(name)
    left, top, right, bottom = extent(rows)
    size = len(rows)
    assert abs(left - (size - 1 - right)) <= 1 and abs(top - (size - 1 - bottom)) <= 1


def mirrored(rows):
    """The picture mirrored left to right."""
    return [row[::-1] for row in rows]


def upside_down(rows):
    """The picture mirrored top to bottom."""
    return rows[::-1]


def turned(rows):
    """The picture mirrored along its diagonal from the top left."""
    return [list(row) for row in zip(*rows)]


SYMMETRIC = {   # how each symmetric icon can be mirrored and stay the same
    "close": (mirrored, turned), "page_next": (upside_down,), "page_previous": (upside_down,),
}


@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("name", SYMMETRIC)
def test_symmetric_icons_stay_symmetric(name, scale):
    # Sides that fall exactly on the centres of pixels must not make them lopsided.
    rows = picture(name, scale)
    for change in SYMMETRIC[name]:
        assert change(rows) == rows, change.__name__


@pytest.mark.parametrize("scale", SCALES)
def test_close_active_is_the_x_on_a_raised_button(scale):
    plain = picture("close", scale)
    size = len(plain)
    k = outline("close", size)
    expected = [[FACE] * size for _ in range(size)]
    for colour, (x0, y0, x1, y1) in style.bevel(0, 0, size, size, k, style.RAISED):
        for y in range(y0, y1):
            expected[y][x0:x1] = [tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))] * (x1 - x0)
    for y, row in enumerate(plain):
        for x, pixel in enumerate(row):
            if pixel is not None:
                assert 2 * k <= x < size - 2 * k and 2 * k <= y < size - 2 * k     # on the face
                expected[y][x] = pixel
    assert picture("close_active", scale) == expected


# The close button at every display scale from 100 % to 300 %, in steps of 1 %: its
# size in pixels and the width of each ring of the style's bevels, round(scale).
CLOSE_SIZES = sorted({(round(CLOSE_ICON_SIZE * percent / 100), round(percent / 100))
                      for percent in range(100, 301)})


@pytest.mark.parametrize("size, ring", CLOSE_SIZES)
def test_the_x_leaves_some_face_around_it(size, ring):
    # At least a pixel of the button's face on every side of the x.
    first, last = 2 * ring, size - 1 - 2 * ring          # the face, inside the bevel
    left, top, right, bottom = extent(pixels(icons.png("close", size)))
    assert first < min(left, top) and max(right, bottom) < last
    rows = pixels(icons.png("close_active", size, ring=ring))
    frame = [rows[y][x] for y in range(first, last + 1) for x in (first, last)] \
        + [rows[y][x] for x in range(first, last + 1) for y in (first, last)]
    assert set(frame) == {FACE}


@pytest.fixture
def root_at(tk_root, monkeypatch):
    """root_at(scale): a new hidden Tk root shown at that display scale.

    Tk keeps the scale per display, which the roots of the test run may
    share: it is put back at the end of the test. On macOS px() does not
    scale; here it follows the emulated scale too.
    """
    monkeypatch.setattr(widgets, "is_aqua", lambda widget: False)
    original = tk_root.tk.call("tk", "scaling")
    roots = []

    def make(scale):
        root = new_root()
        roots.append(root)
        root.tk.call("tk", "scaling", scale * 96 / 72)
        return root
    yield make
    for root in roots:
        root.destroy()
    tk_root.tk.call("tk", "scaling", original)


@pytest.mark.parametrize("scale, ring", [(1, 1), (1.49, 1), (1.52, 2), (2.48, 2), (2.52, 3)])
def test_close_active_has_the_rings_of_the_style(root_at, scale, ring):
    # Like the tab beside it, even where the icon's outlines are a pixel wider or
    # narrower (147 % to 149 %, 251 % to 253 %).
    root = root_at(scale)
    assert widgets.px(root, style.BEVEL) == ring
    size = round(CLOSE_ICON_SIZE * scale)
    image = icons.photo(root, "close_active", size)
    middle = runs([image.get(x, size // 2) for x in range(size)])
    assert middle[:2] == [(LIGHT, ring), (WHITE, ring)] and middle[2][0] == FACE
    assert middle[-2:] == [(SHADOW, ring), (BLACK, ring)]


# Disabled pictures, mirrored pairs and pinned pictures ------------------------

@pytest.mark.parametrize("scale", SCALES)
@pytest.mark.parametrize("name", icons.OTHER)
def test_disabled_pictures_are_embossed(name, scale):
    normal = picture(name, scale)
    size = len(normal)
    k = outline(name, size)
    shape = [(x, y) for y, row in enumerate(normal) for x, pixel in enumerate(row)
             if pixel not in (None, WHITE, SILVER)]
    expected = [[None] * size for _ in range(size)]
    for x, y in shape:
        if x + k < size and y + k < size:
            expected[y + k][x + k] = WHITE
    for x, y in shape:
        expected[y][x] = GRAY
    assert picture(name, scale, disabled=True) == expected


@pytest.mark.parametrize("scale", SCALES)
def test_the_page_arrows_are_mirrored(scale):
    assert picture("page_previous", scale) == [row[::-1] for row in picture("page_next", scale)]


# Pictures pinned letter by letter, by name and scale. page_next has square inner corners
# where its head meets its shaft, at k = 1 and at k = 2; at 150 % both bars of the small A
# of ARES's icon are two rows high, as its outline is wide.
PINNED = {
    ("close", 1): """
        ..............
        ..............
        ..............
        ...KK....KK...
        ...KKK..KKK...
        ....KKKKKK....
        .....KKKK.....
        .....KKKK.....
        ....KKKKKK....
        ...KKK..KKK...
        ...KK....KK...
        ..............
        ..............
        ..............""",
    ("message_error", 1): """
        ................................
        ................................
        ...........KKKKKKKK.............
        .........KKRRRRRRRRKK...........
        .......KKRRRRRRRRRRRRKK.........
        ......KRRRRRRRRRRRRRRRRK........
        .....KRRRRRRRRRRRRRRRRRRK.......
        ....KRRRRRRRRRRRRRRRRRRRRK......
        ....KRRRRRRRRRRRRRRRRRRRRKD.....
        ...KRRRRRRWWRRRRRRWWRRRRRRKD....
        ...KRRRRRWWWWRRRRWWWWRRRRRKD....
        ..KRRRRRRRWWWWRRWWWWRRRRRRRKD...
        ..KRRRRRRRRWWWWWWWWRRRRRRRRKD...
        ..KRRRRRRRRRWWWWWWRRRRRRRRRKDD..
        ..KRRRRRRRRRRWWWWRRRRRRRRRRKDD..
        ..KRRRRRRRRRWWWWWWRRRRRRRRRKDD..
        ..KRRRRRRRRWWWWWWWWRRRRRRRRKDD..
        ..KRRRRRRRWWWWRRWWWWRRRRRRRKDD..
        ..KRRRRRRWWWWRRRRWWWWRRRRRRKDD..
        ...KRRRRRRWWRRRRRRWWRRRRRRKDDD..
        ...KRRRRRRRRRRRRRRRRRRRRRRKDDD..
        ....KRRRRRRRRRRRRRRRRRRRRKDDD...
        ....KRRRRRRRRRRRRRRRRRRRRKDDD...
        .....KRRRRRRRRRRRRRRRRRRKDDD....
        ......KRRRRRRRRRRRRRRRRKDDDD....
        .......KKRRRRRRRRRRRRKKDDDD.....
        ........DKKRRRRRRRRKKDDDDD......
        .........DDKKKKKKKKDDDDDD.......
        ...........DDDDDDDDDDDD.........
        .............DDDDDDDD...........
        ................................
        ................................""",
    ("page_next", 1): """
        ....................
        ....................
        ....................
        ....................
        ..........K.........
        ..........KK........
        ..........KGK.......
        ..........KGGK......
        ...KKKKKKKKGGGK.....
        ...KGGGGGGGGGGGK....
        ...KGGGGGGGGGGGK....
        ...KKKKKKKKGGGK.....
        ..........KGGK......
        ..........KGK.......
        ..........KK........
        ..........K.........
        ....................
        ....................
        ....................
        ....................""",
    ("page_next", 2.25): """
        .............................................
        .............................................
        .............................................
        .............................................
        .............................................
        .............................................
        .............................................
        ......................K......................
        ......................KK.....................
        ......................KKK....................
        ......................KKKK...................
        ......................KKGKK..................
        ......................KKGGKK.................
        ......................KKGGGKK................
        ......................KKGGGGKK...............
        ......................KKGGGGGKK..............
        ......................KKGGGGGGKK.............
        ......................KKGGGGGGGKK............
        .......KKKKKKKKKKKKKKKKKGGGGGGGGKK...........
        .......KKKKKKKKKKKKKKKKKGGGGGGGGGKK..........
        .......KKGGGGGGGGGGGGGGGGGGGGGGGGGKK.........
        .......KKGGGGGGGGGGGGGGGGGGGGGGGGGGKK........
        .......KKGGGGGGGGGGGGGGGGGGGGGGGGGGGKK.......
        .......KKGGGGGGGGGGGGGGGGGGGGGGGGGGKK........
        .......KKGGGGGGGGGGGGGGGGGGGGGGGGGKK.........
        .......KKKKKKKKKKKKKKKKKGGGGGGGGGKK..........
        .......KKKKKKKKKKKKKKKKKGGGGGGGGKK...........
        ......................KKGGGGGGGKK............
        ......................KKGGGGGGKK.............
        ......................KKGGGGGKK..............
        ......................KKGGGGKK...............
        ......................KKGGGKK................
        ......................KKGGKK.................
        ......................KKGKK..................
        ......................KKKK...................
        ......................KKK....................
        ......................KK.....................
        ......................K......................
        .............................................
        .............................................
        .............................................
        .............................................
        .............................................
        .............................................
        .............................................""",
}


@pytest.mark.parametrize("name, scale", PINNED)
def test_pinned_pictures(name, scale):
    letter = {colour: letter for letter, colour in LETTERS.items()}
    letter[None] = "."
    assert ["".join(letter[pixel] for pixel in row) for row in picture(name, scale)] \
        == PINNED[name, scale].split()


# Tk images and speed ----------------------------------------------------------

@pytest.mark.parametrize("disabled", [False, True])
@pytest.mark.parametrize("name", NAMES)
def test_photo_has_the_requested_size(tk_root, name, disabled):
    image = icons.photo(tk_root, name, 54, disabled)
    assert (image.width(), image.height()) == (54, 54)
    assert str(image) in tk_root.image_names()


def test_photo_keeps_transparency(tk_root):
    image = icons.photo(tk_root, "page_next", 20)
    assert image.transparency_get(0, 0) and image.transparency_get(2, 10)
    assert not image.transparency_get(3, 10)
    assert image.get(3, 10) == BLACK                    # the outline
    assert image.get(6, 10) == GREEN
    disabled = icons.photo(tk_root, "page_next", 20, disabled=True)
    assert disabled.get(6, 10) == GRAY and disabled.get(5, 12) == WHITE
    assert disabled.transparency_get(2, 10)


def test_photo_of_a_toolbar_icon_keeps_its_soft_edge(tk_root):
    image = icons.photo(tk_root, "go", 54)
    assert image.transparency_get(0, 0) and not image.transparency_get(27, 27)
    assert image.get(27, 27) == picture_at("go", 54)[27][27]
    disabled = icons.photo(tk_root, "go", 54, disabled=True)
    red, green, blue = disabled.get(27, 27)
    assert red == green == blue


@pytest.mark.serial
def test_toolbar_renders_quickly():
    # As at start-up: nothing kept from before, every picture at 225 %. They
    # take under 60 ms on an idle machine; the limit leaves room for a busy one.
    def make_all():
        icons.forget_pictures()
        start = time.perf_counter()
        for name in icons.TOOLBAR:
            icons.png(name, 54)
            icons.png(name, 54, disabled=True)
        return time.perf_counter() - start
    assert min(make_all() for _ in range(3)) < 0.2
