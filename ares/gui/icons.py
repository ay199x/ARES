# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""ARES's icons, drawn in code at any pixel size.

Each icon is designed on a square grid as many units wide as its size in
design pixels at 100 % (BASES): 24 for the toolbar, 14 for the close button
of a file tab, 20 for the page arrows of the Data Segment and 32 for the
dialogs a program asks for. It is a few shapes, polygons and ellipses in grid
units, painted in order.

The toolbar's icons are soft and shaded. Each is painted on an _Art, which has
several samples across every pixel, and a pixel whose samples are not all the
same becomes their mixture, with as much opacity as they have opaque samples.
Shading changes colour only between pixels, so that it adds no mixing to do.
Sides that are upright or level lie on the borders between pixels, so that
sheets, boxes and bars keep crisp edges at every size. A disabled toolbar icon
is a ghost of the normal one: its lightness, half way to white, in gray. Undo
and redo are ghosts of one gray-blue arrow instead of their own colours: yellow
is far lighter than green, and its ghost would hardly show on a button.

The other icons are in the Windows 98 style, in colours of its palette, on a
_Canvas. A pixel belongs to a shape when its centre is inside it, so every
pixel is either transparent or one colour: the 100 % picture is clean pixel
art, and the same shapes drawn at size = round(base * scale) pixels are as
crisp at every other scale.

A shape that is not black has a black outline along the inside of its edge,
k = max(1, round(size / base)) pixels wide. Inside it, each side of a polygon
moves k pixels inwards, along x if the side is steeper than 45 degrees and
along y if it is flatter, so an outline is exactly k pixels wide along
upright and level sides and k pixels per row or column along slanted ones,
and its inner corners stay square. A mark on a shape, such as the letter on
a dialog's icon, has no outline of its own.

Pixel centres can fall exactly on a side; such a centre is inside on a left
or top side and outside on a right or bottom one. The sides of the close
button's x miss the centres of pixels at the usual scales, so that it stays
symmetric.

The disabled picture of these icons is Windows 98's embossed one: the pixels
that are neither transparent, white nor silver form the icon's shape, painted
white k pixels right and down, then gray in its place.

ARES's own icon, the helmet of Ares, is not made of shapes: it is two fixed
pixel grids, HELMET_16 and HELMET_32, only ever enlarged by whole numbers with
every pixel a square of one colour, so it has no smoothing at any size.
"""

import array
import base64
import binascii
import functools
import math
import struct
import tkinter
import zlib
from fractions import Fraction

from .style import BEVEL, FACE, RAISED, bevel
from .widgets import px, scale

TOOLBAR = ("new", "open", "save", "save_as", "undo", "redo", "cut", "copy", "paste",
           "find", "assemble", "go", "step", "backstep", "pause", "stop", "reset", "help")
TURNING = ("undo", "redo")      # the turning arrows
OTHER = ("close", "close_active",       # file tab close button; close_active is under the mouse
         "page_previous", "page_next",  # pages of the Data Segment
         "message_error", "message_information", "message_warning",  # dialogs of a program
         "message_question")

# The width of each icon's grid: its size in design pixels.
BASES = {**{name: 24 for name in TOOLBAR}, "close": 14, "close_active": 14,
         "page_previous": 20, "page_next": 20, "message_error": 32,
         "message_information": 32, "message_warning": 32, "message_question": 32}

# The 16 colours of the Windows 98 palette (red, green, blue). The icons outside
# the toolbar use no purple or fuchsia, and lime and aqua only for small highlights.
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
SILVER = (192, 192, 192)
GRAY = (128, 128, 128)
MAROON = (128, 0, 0)
RED = (255, 0, 0)
OLIVE = (128, 128, 0)
YELLOW = (255, 255, 0)
GREEN = (0, 128, 0)
LIME = (0, 255, 0)
TEAL = (0, 128, 128)
AQUA = (0, 255, 255)
NAVY = (0, 0, 128)
BLUE = (0, 0, 255)
PURPLE = (128, 0, 128)
FUCHSIA = (255, 0, 255)
PALETTE = (BLACK, WHITE, SILVER, GRAY, MAROON, RED, OLIVE, YELLOW, GREEN, LIME, TEAL, AQUA,
           NAVY, BLUE, PURPLE, FUCHSIA)

FINE = 64                   # coordinates are whole multiples of 1 / FINE grid unit


def _rgb(color):
    """A colour "#RRGGBB" of the style as (red, green, blue)."""
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


# Shapes, as lists of (x, y) points in grid units, y pointing down -----------

def _arc(cx, cy, r, start, end):
    """Points on a circle from angle start to end (degrees, clockwise from 3 o'clock).

    They are rounded to whole 1 / FINE units, as every coordinate must be.
    """
    steps = max(2, math.ceil(abs(end - start) / 7.5))
    angles = (math.radians(start + (end - start) * i / steps) for i in range(steps + 1))
    return [(round((cx + r * math.cos(a)) * FINE) / FINE,
             round((cy + r * math.sin(a)) * FINE) / FINE) for a in angles]


def _turned(points):
    """Points given as (x + y, x - y), in x and y: for shapes along the diagonals."""
    return [((d + t) / 2, (d - t) / 2) for d, t in points]


def _diagonal(d0, d1, t0, t1):
    """The corners of the band d0 <= x + y <= d1, t0 <= x - y <= t1: a square turned 45 degrees."""
    return _turned([(d0, t0), (d0, t1), (d1, t1), (d1, t0)])


def _corners(points):
    """points without repeats and without points on a straight line between their neighbours."""
    result = [point for i, point in enumerate(points) if point != points[i - 1]]
    i = 0
    while len(result) > 2 and i < len(result):
        (x0, y0), (x1, y1), (x2, y2) = result[i - 1], result[i], result[(i + 1) % len(result)]
        if (x1 - x0) * (y2 - y1) == (y1 - y0) * (x2 - x1):
            del result[i]
            i = max(i - 1, 0)
        else:
            i += 1
    return result


class _Mask(list):
    """The pixels of a shape: item y holds row y, bit x set for the pixel (x, y).

    A polygon's mask keeps its points, so that its outline can have square
    inner corners.
    """

    points = None

    def __or__(self, other):
        return _Mask(a | b for a, b in zip(self, other))

    def __and__(self, other):
        return _Mask(a & b for a, b in zip(self, other))

    def __sub__(self, other):
        return _Mask(a & ~b for a, b in zip(self, other))


def _eroded(mask, k):
    """The pixels of mask more than k steps (left, right, up or down) from any pixel outside it."""
    rows = list(mask)
    for _ in range(k):
        rows = [row & row << 1 & row >> 1 & above & below
                for row, above, below in zip(rows, [0] + rows[:-1], rows[1:] + [0])]
    return _Mask(rows)


def _ceil_div(num, den):
    return -(-num // den)


class _Canvas:
    """A square picture of size x size pixels, painted shape by shape in grid units.

    Inside, coordinates are whole numbers: a grid unit is 2 * FINE * size of
    them and a pixel 2 * FINE * base, so every test of a pixel's centre
    against a shape is exact.
    """

    def __init__(self, size, base, ring=None):
        self.size = size
        self.base = base
        self.k = max(1, round(size / base))     # outline width in pixels
        self.ring = self.k if ring is None else ring    # close_active's bevel rings, in pixels
        self.half = FINE * base                 # half a pixel
        self.colors = [None]                    # number -> colour; 0 is transparent
        self.pixels = bytearray(size * size)    # colour numbers, row by row

    def _whole(self, value):
        """A coordinate in grid units, in the canvas's whole numbers."""
        fine = value * FINE
        if fine != int(fine):
            raise ValueError(f"{value} is not a whole multiple of 1/{FINE}")
        return 2 * self.size * int(fine)

    def polygon(self, points, inset=0):
        """The pixels whose centre is inside a polygon of points in grid units.

        A centre on a left or top side is inside, on a right or bottom side
        outside. inset moves every side that many pixels inwards: along x if
        the side is steeper than 45 degrees, along y if it is flatter.
        """
        size, half = self.size, self.half
        whole = _corners([(self._whole(x), self._whole(y)) for x, y in points])
        pairs = list(zip(whole, whole[1:] + whole[:1]))
        turn = 1 if sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in pairs) > 0 else -1
        lines = []                              # each side: inside is a * x + b * y <= c
        for (x0, y0), (x1, y1) in pairs:
            a, b = turn * (y1 - y0), turn * (x0 - x1)
            lines.append((a, b, a * x0 + b * y0 - max(abs(a), abs(b)) * 2 * half * inset))
        if inset:                               # the corners, where the moved sides meet
            ys = [Fraction(a0 * c1 - a1 * c0, a0 * b1 - a1 * b0)
                  for (a0, b0, c0), (a1, b1, c1) in zip(lines[-1:] + lines[:-1], lines)]
        else:
            ys = [Fraction(y) for x, y in whole]
        crossings = [[] for _ in range(size)]   # each row: the first pixel right of each side
        for i, (a, b, c) in enumerate(lines):
            if a:
                y0, y1 = ys[i], ys[(i + 1) % len(ys)]
                # The rows whose centre, (2 j + 1) * half, is from the upper end to the lower.
                first = max(math.ceil((min(y0, y1) - half) / (2 * half)), 0)
                end = min(math.ceil((max(y0, y1) - half) / (2 * half)), size)
                for j in range(first, end):
                    centre = (2 * j + 1) * half
                    num, den = c - b * centre - a * half, 2 * a * half
                    if den < 0:
                        num, den = -num, -den
                    crossings[j].append(_ceil_div(num, den))
        mask = _Mask()
        for xs in crossings:
            xs.sort()
            row = 0
            for first, end in zip(xs[::2], xs[1::2]):
                first, end = max(first, 0), min(end, size)
                if end > first:
                    row |= (1 << end) - (1 << first)
            mask.append(row)
        if not inset:
            mask.points = points
        return mask

    def rect(self, x0, y0, x1, y1):
        return self.polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])

    def ellipse(self, cx, cy, rx, ry=None):
        """The pixels whose centre is inside an ellipse (a circle without ry), not on it."""
        size, half = self.size, self.half
        cx, cy, rx = self._whole(cx), self._whole(cy), self._whole(rx)
        ry = rx if ry is None else self._whole(ry)
        mask = _Mask([0] * size)
        for j in range(size):
            dy = (2 * j + 1) * half - cy
            room = rx * rx * (ry * ry - dy * dy)    # inside: (x - cx)^2 * ry^2 < room
            if room > 0:
                m = math.isqrt(_ceil_div(room, ry * ry) - 1)     # the farthest whole x - cx
                first = max(_ceil_div(cx - m - half, 2 * half), 0)
                end = min((cx + m - half) // (2 * half) + 1, size)
                if end > first:
                    mask[j] = (1 << end) - (1 << first)
        return mask

    def box(self, x0, y0, x1, y1):
        """The pixels x0 <= x < x1, y0 <= y < y1 (in pixels, not grid units)."""
        row = (1 << x1) - (1 << x0)
        return _Mask(row if y0 <= j < y1 else 0 for j in range(self.size))

    def fill(self, color, mask):
        """Paint the pixels of mask in color."""
        if color not in self.colors:
            self.colors.append(color)
        paint = bytes((self.colors.index(color),))
        pixels, size = self.pixels, self.size
        for y, row in enumerate(mask):
            start = y * size
            while row:
                low = row & -row
                above = row + low               # the lowest run carries into the bit after it
                first, end = low.bit_length() - 1, (above & -above).bit_length() - 1
                pixels[start + first:start + end] = paint * (end - first)
                row &= above

    def inner(self, mask):
        """The pixels of mask inside its outline, which is k pixels wide along its edge."""
        inner = _eroded(mask, self.k)
        if mask.points is not None:             # square inner corners
            inner &= self.polygon(mask.points, self.k)
        return inner

    def outlined(self, color, mask, inner=None):
        """Paint mask in color inside a black outline k pixels wide along its edge.

        inner, when given, is the inside to paint (self.inner(mask), mirrored or
        moved together with mask).
        """
        self.fill(BLACK, mask)
        self.fill(color, self.inner(mask) if inner is None else inner)

    def flip(self):
        """Mirror the picture left to right."""
        size = self.size
        for start in range(0, size * size, size):
            self.pixels[start:start + size] = self.pixels[start:start + size][::-1]


# The toolbar's pictures ------------------------------------------------------

LEVELS = 16                 # colours of a shaded fill
# Each channel's part of a colour's lightness; together they never exceed 255.
_RED_PART = bytes(299 * value // 1000 for value in range(256))
_GREEN_PART = bytes(587 * value // 1000 for value in range(256))
_BLUE_PART = bytes(114 * value // 1000 for value in range(256))
_GHOST = bytes(255 - (255 - value) // 2 for value in range(256))    # half way to white


def _samples(size):
    """The samples across each pixel of a picture size pixels wide."""
    return 4 if size <= 32 else 3 if size <= 64 else 2


def _runs(row):
    """The runs of set bits in a row: (first, end) pairs."""
    runs = []
    while row:
        low = row & -row
        above = row + low                       # the lowest run carries into the bit after it
        runs.append((low.bit_length() - 1, (above & -above).bit_length() - 1))
        row &= above
    return runs


def _bezier(p0, p1, p2, p3, steps=8):
    """Points along a cubic curve from p0 to p3, pulled towards p1 and p2."""
    points = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        a, b, d, e = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
        points.append((a * p0[0] + b * p1[0] + d * p2[0] + e * p3[0],
                       a * p0[1] + b * p1[1] + d * p2[1] + e * p3[1]))
    return points


def _inset(points, distance):
    """The polygon whose sides lie distance units inside the sides of points."""
    points = [point for i, point in enumerate(points) if point != points[i - 1]]
    turn = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1)
               in zip(points, points[1:] + points[:1]))
    turn = 1 if turn > 0 else -1
    result = []
    for (x0, y0), (x1, y1), (x2, y2) in zip(points[-1:] + points[:-1], points,
                                            points[1:] + points[:1]):
        first, second = math.hypot(x1 - x0, y1 - y0), math.hypot(x2 - x1, y2 - y1)
        nx0, ny0 = turn * (y0 - y1) / first, turn * (x1 - x0) / first
        nx1, ny1 = turn * (y1 - y2) / second, turn * (x2 - x1) / second
        room = distance / max(1 + nx0 * nx1 + ny0 * ny1, 0.25)
        result.append((x1 + (nx0 + nx1) * room, y1 + (ny0 + ny1) * room))
    return result


def _bar(x0, y0, x1, y1, width, round_ends=False):
    """A straight bar from (x0, y0) to (x1, y1), width units wide."""
    length = math.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    nx, ny = -uy * width / 2, ux * width / 2
    if not round_ends:
        return [(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)]
    start = math.degrees(math.atan2(ny, nx))
    return (_arc(x1, y1, width / 2, start, start - 180)
            + _arc(x0, y0, width / 2, start - 180, start - 360))


def _star(cx, cy, outer, inner, points=5):
    """A star of points tips, the first one pointing up."""
    result = []
    for i in range(2 * points):
        angle = math.radians(i * 180 / points - 90)
        radius = inner if i % 2 else outer
        result.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return result


def _down(top, bottom, y0=2, y1=22):
    """A paint from the colour top at y0 down to the colour bottom at y1."""
    return (top, bottom), (0, y0), (0, y1)


def _slant(first, last, start=(2, 2), end=(22, 22)):
    """A paint from the colour first at the point start to the colour last at end."""
    return (first, last), start, end


@functools.lru_cache(maxsize=64)
def _shades(stops, levels):
    """levels colours going evenly through the colours of stops, "#RRGGBB"."""
    stops = [_rgb(stop) for stop in stops]
    shades = []
    for level in range(levels):
        where = level * (len(stops) - 1) / (levels - 1)
        i = min(int(where), len(stops) - 2)
        part = where - i
        shades.append(tuple(round(a + (b - a) * part) for a, b in zip(stops[i], stops[i + 1])))
    return shades


class _Art:
    """A toolbar picture, painted in samples and finished as RGBA pixels.

    Coordinates are in grid units, as on a _Canvas, but each pixel is
    samples x samples numbers of colours, so that shapes are the same _Masks
    with finer rows. Shading is computed along whole rows, and only the pixels
    whose samples differ are mixed one by one when the picture is finished.
    """

    def __init__(self, size, base):
        self.pixel_size = size
        self.samples = _samples(size)
        self.size = size * self.samples
        self.scale = size / base                # pixels per unit
        self.unit = self.size / base            # samples per unit
        self.thin = max(1, round(self.scale)) / self.scale     # a thin line, in units
        self.colors = [None]                    # number -> colour; 0 is transparent
        self.numbers = {}
        self.pixels = bytearray(self.size * self.size)

    def snap(self, value):
        """value, in units, on the nearest border between two pixels."""
        return round(value * self.scale) / self.scale

    def snapped(self, points):
        """points on borders between pixels, so that upright and level sides stay crisp."""
        return [(self.snap(x), self.snap(y)) for x, y in points]

    def polygon(self, points):
        """The samples whose centre is inside a polygon, by the even-odd rule.

        Its points must lie on the grid: from 0 to the grid's width in x and y.
        """
        size, unit = self.size, self.unit
        crossings = [[] for _ in range(size)]
        x1, y1 = points[-1]
        x1, y1 = x1 * unit, y1 * unit
        for x, y in points:
            x0, y0, x1, y1 = x1, y1, x * unit, y * unit
            if y0 != y1:
                ax, ay, bx, by = (x0, y0, x1, y1) if y0 < y1 else (x1, y1, x0, y0)
                first, end = math.ceil(ay - 0.5), math.ceil(by - 0.5)
                slope = (bx - ax) / (by - ay)
                across = ax + (first + 0.5 - ay) * slope + 0.5
                for row in crossings[first:end]:
                    row.append(across)
                    across += slope
        mask = _Mask()
        for xs in crossings:
            if len(xs) == 2:                    # nearly always
                first, end = xs
                mask.append(abs((1 << int(end)) - (1 << int(first))))
            elif xs:
                xs.sort()
                mask.append(sum((1 << int(end)) - (1 << int(first))
                                for first, end in zip(xs[::2], xs[1::2])))
            else:
                mask.append(0)
        return mask

    def rect(self, x0, y0, x1, y1):
        """The samples of a rectangle whose sides lie on the nearest borders between pixels."""
        size, step = self.size, self.samples
        left, top, right, bottom = (min(round(value * self.scale) * step, size)
                                    for value in (x0, y0, x1, y1))
        return _Mask([0] * top + [(1 << right) - (1 << left)] * (bottom - top)
                     + [0] * (size - bottom))

    def ellipse(self, cx, cy, rx, ry=None):
        """The samples whose centre is inside an ellipse (a circle without ry)."""
        size, unit = self.size, self.unit
        cx, cy, rx = cx * unit, cy * unit, rx * unit
        ry = rx if ry is None else ry * unit
        mask = _Mask([0] * size)
        for j in range(max(math.ceil(cy - ry - 0.5), 0), min(math.ceil(cy + ry - 0.5), size)):
            height = (j + 0.5 - cy) / ry
            width = rx * math.sqrt(max(1 - height * height, 0))
            first, end = max(int(cx - width + 0.5), 0), min(int(cx + width + 0.5), size)
            if end > first:
                mask[j] = (1 << end) - (1 << first)
        return mask

    def _number(self, color):
        """The number of a colour, as (red, green, blue)."""
        number = self.numbers.get(color)
        if number is None:
            number = self.numbers[color] = len(self.colors)
            self.colors.append(color)
        return number

    def _ramp(self, stops, levels=LEVELS):
        """The numbers of levels colours going evenly through the colours of stops."""
        return [self._number(color) for color in _shades(stops, levels)]

    def _wide(self, numbers):
        """A line of samples from the numbers of the colours of its pixels."""
        wide = bytearray(len(numbers) * self.samples)
        for i in range(self.samples):
            wide[i::self.samples] = numbers
        return bytes(wide)

    def _shaded(self, stops, start, end):
        """The lines of a fill from the first of stops at start to the last at end.

        Colours change only between pixels, so that shading alone never
        leaves a pixel to be mixed. Along a slanted fill, each row of pixels
        is the same line of colours moved along.
        """
        ramp = self._ramp(stops)
        out, scale = self.pixel_size, self.scale
        x0, y0 = start[0] * scale, start[1] * scale
        dx, dy = end[0] * scale - x0, end[1] * scale - y0
        each = LEVELS / (dx * dx + dy * dy)
        top = LEVELS - 1
        if not dx:
            return [bytes((ramp[min(max(int((y + 0.5 - y0) * dy * each), 0), top)],)) * self.size
                    for y in range(out)]
        slide = dy / dx
        least, most = sorted((0, round(slide * (out - 1))))
        offset = ((0.5 - x0) * dx + (0.5 - y0) * dy) * each
        step = dx * each
        line = self._wide(bytes(ramp[min(max(int(x * step + offset), 0), top)]
                                for x in range(least, out + most)))
        return [line[(round(slide * y) - least) * self.samples:][:self.size] for y in range(out)]

    def ball(self, cx, cy, radius, stops):
        """The lines of a fill like a lit ball: its middle in the first of stops, its rim in the
        last, and lighter towards the lower right."""
        levels = 32
        ramp = self._ramp(stops, levels)
        out, scale = self.pixel_size, self.scale * radius

        def light(place, centre):
            """How much one coordinate of a pixel lights it, in hundredths of a level."""
            where = (place + 0.5) / scale - centre / radius
            return round((1.2 * where * where + 0.3 * where) * levels * 100)
        across = [light(x, cx) for x in range(out)]
        down = [light(y, cy) - 10 * levels for y in range(out)]
        lowest = min(across) + min(down)
        table = [ramp[min(max((value + lowest) // 100, 0), levels - 1)]
                 for value in range(max(across) + max(down) - lowest + 1)]
        across = [value - min(across) for value in across]
        down = [value - min(down) for value in down]
        return [self._wide(bytes([table[value + extra] for value in across])) for extra in down]

    def paint(self, paint, mask):
        """Paint the samples of mask.

        paint is a colour "#RRGGBB", (stops, start, end) for a shaded fill, or
        the lines of one, a line of the numbers of its samples for each row of pixels.
        """
        pixels, size, samples = self.pixels, self.size, self.samples
        if isinstance(paint, str):
            lines = [bytes((self._number(_rgb(paint)),)) * size] * self.pixel_size
        else:
            lines = paint if isinstance(paint, list) else self._shaded(*paint)
        start = 0
        for y, row in enumerate(mask):
            if row:
                line = lines[y // samples]
                low = row & -row
                end = row.bit_length()
                if row + low == 1 << end:       # one run, as in most rows
                    first = low.bit_length() - 1
                    pixels[start + first:start + end] = line[first:end]
                else:
                    for first, end in _runs(row):
                        pixels[start + first:start + end] = line[first:end]
            start += size

    def outlined(self, points, edge, inside, width=None):
        """Paint a polygon in edge, and inside it, width units in from its sides, in inside."""
        self.paint(edge, self.polygon(points))
        self.paint(inside, self.polygon(_inset(points, self.thin if width is None else width)))

    def flip(self):
        """Mirror the picture left to right."""
        size = self.size
        for start in range(0, size * size, size):
            self.pixels[start:start + size] = self.pixels[start:start + size][::-1]

    def text(self, color, x0, x1, y, count, pitch=2):
        """Paint count lines of text from x0 to x1, thin and evenly spaced, the first at y."""
        step = max(round(pitch * self.scale), 2 * max(1, round(self.scale))) / self.scale
        for i in range(count):
            top = self.snap(y) + i * step
            self.paint(color, self.rect(x0, top, x1, top + self.thin))

    def finished(self):
        """The picture as RGBA bytes, row by row."""
        samples, out, size = self.samples, self.pixel_size, self.size
        colors = self.colors
        pixels = bytes(self.pixels)
        plain = bytearray(out * out)            # a pixel's first sample
        soft = []                               # (place in plain, RGBA) of mixed pixels
        mixed = {}
        for y in range(out):
            start = y * samples * size
            lines = [pixels[start + i * size:start + (i + 1) * size] for i in range(samples)]
            plain[y * out:(y + 1) * out] = lines[0][::samples]
            first = int.from_bytes(lines[0], "little")
            differ = 0
            for line in lines[1:]:
                differ |= first ^ int.from_bytes(line, "little")
            along = first ^ first >> 8
            found = differ
            for i in range(1, samples):         # gather each pixel's differences in its first byte
                found |= differ >> 8 * i | along >> 8 * (i - 1)
            if found:
                marks = found.to_bytes(size, "little")[::samples]
                for x, mark in enumerate(marks):
                    if mark:
                        key = b"".join([line[x * samples:(x + 1) * samples] for line in lines])
                        value = mixed.get(key)
                        if value is None:
                            value = mixed[key] = _mixed(key, colors)
                        soft.append((y * out + x, value))
        result = bytearray(4 * out * out)
        for channel in range(3):
            table = bytes(color[channel] if color else 0 for color in colors)
            result[channel::4] = plain.translate(table.ljust(256, b"\0"))
        result[3::4] = plain.translate((b"\0" + b"\xff" * (len(colors) - 1)).ljust(256, b"\0"))
        for place, value in soft:
            result[4 * place:4 * place + 4] = value
        return bytes(result)


def _mixed(samples, colors):
    """The RGBA pixel of samples, numbers of colours: as many opaque as they are, mixed."""
    red = green = blue = count = 0
    for number in set(samples):
        color = colors[number]
        if color:
            times = samples.count(number)
            red += color[0] * times
            green += color[1] * times
            blue += color[2] * times
            count += times
    if not count:
        return bytes(4)
    half = count // 2
    return bytes(((red + half) // count, (green + half) // count, (blue + half) // count,
                  (510 * count + len(samples)) // (2 * len(samples))))


def _ghosted(frame):
    """The disabled form of a toolbar picture, RGBA bytes: gray, half way to white."""
    light = (int.from_bytes(frame[0::4].translate(_RED_PART), "little")
             + int.from_bytes(frame[1::4].translate(_GREEN_PART), "little")
             + int.from_bytes(frame[2::4].translate(_BLUE_PART), "little"))
    gray = light.to_bytes(len(frame) // 4, "little").translate(_GHOST)
    result = bytearray(frame)
    result[0::4] = result[1::4] = result[2::4] = gray
    return bytes(result)


# The pictures. Colours go from the light above to the shade below.

EDGE = "#8A8A8A"            # the side of a sheet of paper
TEXT = "#A6A6A6"            # lines of text on it
PAPER = _slant("#FFFFFF", "#E2E2E2")
ARROW = _down("#7FB0E0", "#2F6AAE", 1, 15)     # the arrow that saves
ARROW_EDGE = "#1F4F8A"
UNDO = _down("#FFF27A", "#F2BC00", 1, 22)
UNDO_EDGE = "#8F6B00"
REDO = _down("#B4EA78", "#4FA81E", 1, 22)
REDO_EDGE = "#2F6B12"
TURN = _down("#B9C8DE", "#6C86B0", 1, 22)      # the arrow of disabled undo and redo
TURN_EDGE = "#4C648E"
GREEN_DISC = ("#0C5018", "#17782A", "#2E9A42", "#A6DCA6")    # its rim, then middle to edge
BLUE_DISC = ("#1A3CA8", "#2460D8", "#4C8CF0", "#BCD6FA")


def _new(c):
    """A white sheet with a small yellow star at its upper right corner."""
    c.outlined(c.snapped([(3, 2), (19, 2), (19, 22), (3, 22)]), EDGE, PAPER)
    c.paint("#C8C8C8", c.rect(5, 10, 6, 11) | c.rect(5, 15, 6, 16))
    c.outlined(_star(17.25, 5.75, 4.5, 2), "#D89A00", _down("#FFF27A", "#FFC800", 1, 10), 0.8)


def _open(c):
    """A blue folder with a sheet standing in it."""
    c.outlined(c.snapped([(2, 4), (9, 4), (11, 6), (17, 6), (17, 21), (2, 21)]), "#6A6A6A",
               _down("#D6D6D6", "#9A9A9A", 4, 21))
    c.outlined(c.snapped([(10, 2), (16, 2), (19, 5), (19, 14), (10, 14)]), EDGE, "#FFFFFF")
    c.text(TEXT, 12, 15, 5, 2)
    c.outlined([(6.5, 10), (22.5, 10), (22.5, 21.5), (4, 21.5)], "#2A5A9E",
               _down("#B4CDEA", "#4F80C4", 10, 21.5))


def _drive(c):
    """A gray drive, open at the top."""
    c.outlined([(5, 9), (19, 9), (22.5, 15), (22.5, 22), (1.5, 22), (1.5, 15)], "#808080",
               _down("#FFFFFF", "#D8D8D8", 9, 22))
    c.paint("#808080", c.rect(1.5, 15, 22.5, 15.5))


def _saving_arrow(c):
    """The blue arrow that comes over the top and down into the drive."""
    points = (_bezier((1, 8), (1.5, 3.5), (5, 1), (9.5, 1), 6)
              + _bezier((9.5, 1), (13, 1), (15.5, 3.5), (15.5, 7.5), 6)
              + [(19, 7.5), (12, 15), (5, 7.5), (8.5, 7.5)]
              + _bezier((8.5, 7.5), (8.5, 6), (7.5, 5), (6, 5), 4)
              + _bezier((6, 5), (4, 5), (2.5, 6), (1, 8), 4))
    c.outlined(points, ARROW_EDGE, ARROW)


def _save(c):
    """The blue arrow going into a gray drive with a vented front."""
    _drive(c)
    c.paint(_slant("#8E8E8E", "#E6E6E6", (3, 0), (20, 0)), c.rect(3.5, 17, 20.5, 20))
    for x in (11, 13, 15, 17, 19):
        c.paint("#F4F4F4", c.rect(x, 17, x + c.thin, 20))
    _saving_arrow(c)


def _save_as(c):
    """The arrow and the drive, with a white field for a name on its front."""
    _drive(c)
    c.outlined(c.snapped([(3.5, 16.5), (20.5, 16.5), (20.5, 20.5), (3.5, 20.5)]), "#4A4A4A",
               _slant("#C0C0C0", "#F8F8F8", (4, 0), (20, 0)))
    c.paint("#000000", c.rect(16.5, 16.5, 18, 20.5))
    _saving_arrow(c)


def _turning_arrow(c, edge, inside):
    """An arrow with its head at the upper left, its tail curling down."""
    points = ([(3, 8.5), (11, 1.5), (11, 5)]
              + _bezier((11, 5), (18.5, 5), (23.5, 11), (16.5, 22))
              + _bezier((16.5, 22), (18.5, 16), (16.5, 12), (11, 12))
              + [(11, 15.5)])
    c.outlined(points, edge, inside)


def _undo(c):
    """The yellow turning arrow."""
    _turning_arrow(c, UNDO_EDGE, UNDO)


def _redo(c):
    """The green turning arrow, mirrored when it is finished (_toolbar_picture)."""
    _turning_arrow(c, REDO_EDGE, REDO)


def _turn(c):
    """The gray-blue turning arrow that disabled undo and redo are made from."""
    _turning_arrow(c, TURN_EDGE, TURN)


def _cut(c):
    """Open scissors: two gray blades going up, blue finger rings below."""
    steel = _slant("#FFFFFF", "#8E8EA8", (2, 2), (12, 12))
    c.outlined([(2, 3.5), (4.5, 2), (14, 13), (11.5, 15)], "#5C5C70", steel)
    c.outlined([(10, 2), (12.5, 1), (14.5, 14), (11.5, 14.5)], "#5C5C70", steel)
    blue = "#1042B8"
    c.paint("#0A2C8A", c.polygon(_bar(12.5, 13, 9.5, 16.5, 2.6)))
    c.paint("#0A2C8A", c.polygon(_bar(12.5, 13, 15, 15, 2.6)))
    for x, y, r in ((8, 19.25, 3.75), (17.75, 16.25, 3.75)):
        c.paint("#0A2C8A", c.ellipse(x, y, r) - c.ellipse(x, y, r - 2.4))
        c.paint(blue, c.ellipse(x, y, r - 0.6) - c.ellipse(x, y, r - 1.9))


def _copy(c):
    """Two sheets with lines of text, the upper one with a folded corner."""
    c.outlined(c.snapped([(3, 2), (15, 2), (15, 17), (3, 17)]), "#ABABAB", PAPER)
    c.text("#C0C0C0", 5, 13, 5, 4)
    corner = c.snapped([(8, 7), (21, 7), (21, 18), (17, 22), (8, 22)])
    c.outlined(corner, EDGE, PAPER)
    c.text(TEXT, 10, 19, 10, 4)
    c.outlined([(21, 18), (17, 18), (17, 22)], EDGE, "#C8C8C8")


def _paste(c):
    """A brown clipboard holding a sheet, a gray clip at its top."""
    c.outlined(c.snapped([(4, 3), (20, 3), (21, 4), (21, 22), (3, 22), (3, 4)]), "#6E4708",
               _down("#D29A40", "#A86E18", 3, 22))
    c.outlined(c.snapped([(6, 6), (18, 6), (18, 16), (14, 20), (6, 20)]), "#7C7C7C", PAPER)
    c.text(TEXT, 8, 16, 9, 3)
    c.outlined([(18, 16), (14, 16), (14, 20)], "#7C7C7C", "#C8C8C8")
    c.outlined([(7.5, 6), (8, 3.5), (9.5, 3), (10, 1.5), (14, 1.5), (14.5, 3), (16, 3.5),
                (16.5, 6)], "#5C5C5C", _down("#E0E0E0", "#8E8E8E", 1.5, 6))


def _find(c):
    """A magnifier over a sheet, and a pencil writing on it."""
    c.outlined(c.snapped([(5, 4), (18, 4), (18, 21), (5, 21)]), EDGE, PAPER)
    c.text(TEXT, 7, 12, 14, 3)
    c.paint("#5F6B80", c.polygon(_bar(2.25, 13, 6, 10, 2.4, True)))
    c.paint("#6C7890", c.ellipse(9, 7.5, 6))
    c.paint(_slant("#F0F4FC", "#8FA8D8", (5, 3), (13, 12)), c.ellipse(9, 7.5, 6 - 1.2))
    # The pencil, from its point at the lower left to its end at the upper right.
    c.paint("#7A4A10", c.polygon(_bar(15, 19, 21.6, 10.4, 3.6) + [(13, 21.5)]))
    c.paint(_slant("#F4C878", "#C87C20", (16, 12), (20, 16)),
            c.polygon(_bar(15.5, 18.4, 21.2, 10.9, 2)))
    c.paint("#F2DCB4", c.polygon([(14.3, 17.8), (16.5, 19.5), (13.5, 20.9)]))
    c.paint("#000000", c.polygon([(13.7, 19.5), (14.8, 20.3), (13, 21.5)]))


def _assemble(c):
    """A gray wrench crossed by a blue screwdriver."""
    notch = c.polygon([(1, 1), (6, 0), (7.2, 5.6), (5.6, 7.2), (0, 6)])
    c.paint("#6A6A72", (c.ellipse(6.5, 6.5, 5) | c.polygon(_bar(7, 7, 20.5, 20.5, 3.8, True)))
            - notch)
    wide = c.polygon([(1, 0), (6.5, 0), (7.9, 5.3), (5.3, 7.9), (0, 6.5)])
    c.paint(_slant("#FFFFFF", "#A8A8B0", (2, 2), (20, 20)),
            (c.ellipse(6.5, 6.5, 4.2) | c.polygon(_bar(7, 7, 20.5, 20.5, 2.2, True))) - wide)
    c.paint("#6A6A72", c.ellipse(20.25, 20.25, 0.8))
    c.outlined(_bar(9, 15, 21.5, 2.5, 2.4), "#14389C", "#E8EEFF", 0.7)
    c.outlined(_bar(3.6, 20.4, 9, 15, 5, True), "#14389C",
               _slant("#A8C4F0", "#2C5CC0", (3, 15), (9, 21)))


@functools.lru_cache(maxsize=16)
def _disc_picture(size, cx, cy, radius, colors):
    """The samples and colours of a shaded disc with a dark rim, on an empty picture."""
    art = _Art(size, BASES["go"])
    art.paint(colors[0], art.ellipse(cx, cy, radius))
    art.paint(art.ball(cx, cy, radius, colors[1:]), art.ellipse(cx, cy, radius - 1.25))
    return bytes(art.pixels), art.colors, art.numbers


def _disc(c, cx, cy, radius, colors):
    """Start a picture with a shaded disc."""
    pixels, numbers_to_colors, numbers = _disc_picture(c.pixel_size, cx, cy, radius, colors)
    c.pixels[:] = pixels
    c.colors, c.numbers = list(numbers_to_colors), dict(numbers)


def _mark(c, points, tint):
    """A white mark on a disc, its inside softly tinted."""
    c.outlined(points, "#FFFFFF", _down("#FFFFFF", tint, 6, 18), 0.9)


def _go(c):
    """A green disc with a white triangle pointing right."""
    _disc(c, 12, 12, 11, GREEN_DISC)
    _mark(c, [(9, 5.5), (19.5, 12), (9, 18.5)], "#E0F2E0")


def _small_disc(c, colors, tint):
    """Go's disc, smaller, at the upper left."""
    _disc(c, 10.5, 10.5, 9.5, colors)
    _mark(c, [(7.75, 4.75), (17, 10.5), (7.75, 16.25)], tint)


def _one(c, x, color):
    """A bold figure 1 standing on the bottom of the picture, its left side at x."""
    c.paint(color, c.polygon(c.snapped([
        (x + 1.5, 13.5), (x + 4, 13.5), (x + 4, 21.5), (x + 5.5, 21.5), (x + 5.5, 23),
        (x, 23), (x, 21.5), (x + 1.5, 21.5), (x + 1.5, 16), (x, 16.5), (x, 15)])))


def _step(c):
    """Go's disc and triangle, smaller, with a black 1 at the lower right."""
    _small_disc(c, GREEN_DISC, "#E0F2E0")
    _one(c, 17.5, "#000000")


def _backstep(c):
    """Step in blue, its disc mirrored, with a dark 1 at the lower left."""
    _small_disc(c, BLUE_DISC, "#E0E8FA")
    c.flip()
    _one(c, 1, "#0A1A48")


def _pause(c):
    """Go's disc with two white bars."""
    _disc(c, 12, 12, 11, GREEN_DISC)
    for x in (6.75, 13):
        c.paint(_down("#FFFFFF", "#E0F2E0", 6, 18), c.rect(x, 6, x + 4.25, 18))


def _stop(c):
    """Go's disc with a white square."""
    _disc(c, 12, 12, 11, GREEN_DISC)
    c.paint(_down("#FFFFFF", "#E0F2E0", 6, 18), c.rect(6.5, 6.5, 17.5, 17.5))


def _reset(c):
    """Go's disc with two white triangles pointing left, back to the start."""
    _disc(c, 12, 12, 11, GREEN_DISC)
    for tip in (4.5, 12):
        _mark(c, [(tip, 12), (tip + 6.5, 6.5), (tip + 6.5, 17.5)], "#E0F2E0")


def _help(c):
    """A blue disc inside a blue ring, with a white question mark."""
    c.paint("#2B59A8", c.ellipse(12, 12, 11))
    c.paint("#FFFFFF", c.ellipse(12, 12, 9.75))
    c.paint("#2B59A8", c.ellipse(12, 12, 8.75))
    c.paint(_down("#6E9AD8", "#2C5CB0", 3, 21), c.ellipse(12, 12, 8))
    mark = (_arc(12, 9.5, 4.75, -190, 40)
            + [(13.75, 13.25), (13.75, 15), (10.25, 15), (10.25, 12.5)]
            + _arc(12, 9.5, 1.75, 30, -190))
    c.paint("#FFFFFF", c.polygon(mark))
    c.paint("#FFFFFF", c.ellipse(12, 17.25, 1.9))


# The other icons. Coordinates are in grid units. Most slanted sides run at 1:1 or
# 1:2 and pass between pixel centres at 100 %, so their steps are even; corners are
# on whole units, or on half units where a side or a centre line needs it.

def _crossed(c, cx, cy, width, span):
    """An x: two diagonal strokes crossing at (cx, cy), each width wide along a row.

    Their ends are square to them, where x + y or x - y is span away from
    its value at the crossing.
    """
    d, t = cx + cy, cx - cy
    return (c.polygon(_diagonal(d - span, d + span, t - width / 2, t + width / 2))
            | c.polygon(_diagonal(d - width / 2, d + width / 2, t - span, t + span)))


def _close(c):
    """A black x, like a window's close button.

    No side of it falls on the centre of a pixel at the usual scales, so
    there it is symmetric left to right, top to bottom and along its
    diagonals; at every scale it leaves a pixel of close_active's face
    around it.
    """
    c.fill(BLACK, _crossed(c, 7, 7, 2.5, 7.25))


def _close_active(c):
    """The x on a small raised button, the style's own, that fills the image."""
    size = c.size
    c.fill(_rgb(FACE), c.box(0, 0, size, size))
    for color, box in bevel(0, 0, size, size, c.ring, RAISED):
        c.fill(_rgb(color), c.box(*box))
    _close(c)


def _page_next(c):
    """A green arrow pointing right."""
    c.outlined(GREEN, c.polygon([(3, 8), (10, 8), (10, 3), (17, 10), (10, 17), (10, 12),
                                 (3, 12)]))


def _page_previous(c):
    """A green arrow pointing left."""
    _page_next(c)
    c.flip()


# The icons of a program's dialogs, each with a gray shadow 2 units below and right.

def _message_error(c):
    """A red disc with a white x."""
    c.fill(GRAY, c.ellipse(17, 17, 13))
    c.outlined(RED, c.ellipse(15, 15, 13))
    c.fill(WHITE, _crossed(c, 15, 14.5, 4, 10))


def _bubble(c):
    """A white speech bubble, its tail at the lower left."""
    tail = [(8, 18), (14, 20), (6, 28)]
    c.fill(GRAY, c.ellipse(17.5, 14, 13, 10) | c.polygon([(x + 2, y + 2) for x, y in tail]))
    c.outlined(WHITE, c.ellipse(15.5, 12, 13, 10) | c.polygon(tail))


def _message_information(c):
    """A white speech bubble with a blue i."""
    _bubble(c)
    for box in ((14, 4, 17, 7), (14, 9, 17, 18), (12, 9, 14, 10), (12, 17, 19, 18)):
        c.fill(BLUE, c.rect(*box))


def _message_warning(c):
    """A yellow triangle with a black exclamation mark."""
    c.fill(GRAY, c.polygon([(17.5, 5), (29.5, 29), (5.5, 29)]))
    c.outlined(YELLOW, c.polygon([(15.5, 3), (27.5, 27), (3.5, 27)]))
    c.fill(BLACK, c.polygon([(14, 10), (17, 10), (16.5, 20), (14.5, 20)]))
    c.fill(BLACK, c.rect(14, 22, 17, 25))


def _message_question(c):
    """A white speech bubble with a blue question mark."""
    _bubble(c)
    c.fill(BLUE, c.polygon([(11, 6), (13, 4), (18, 4), (20, 6), (20, 10), (17, 13), (17, 15),
                            (14, 15), (14, 12), (17, 9), (17, 7), (14, 7), (14, 9), (11, 9)]))
    c.fill(BLUE, c.rect(14, 16, 17, 19))


_DRAW = {
    "new": _new, "open": _open, "save": _save, "save_as": _save_as,
    "undo": _undo, "redo": _redo, "cut": _cut, "copy": _copy, "paste": _paste,
    "find": _find, "assemble": _assemble, "go": _go, "step": _step,
    "backstep": _backstep, "pause": _pause, "stop": _stop, "reset": _reset,
    "help": _help, "close": _close, "close_active": _close_active,
    "page_previous": _page_previous, "page_next": _page_next,
    "message_error": _message_error, "message_information": _message_information,
    "message_warning": _message_warning, "message_question": _message_question,
}


# Output --------------------------------------------------------------------

def _picture(name, size, ring=None):
    """The canvas of the icon called name, drawn at size x size pixels."""
    draw = _DRAW[name]
    if not 8 <= size <= 256:
        raise ValueError(f"icon size must be from 8 to 256 pixels, not {size}")
    canvas = _Canvas(size, BASES[name], ring)
    draw(canvas)
    return canvas


def _embossed(canvas):
    """The colour numbers and colours of the disabled picture of canvas.

    The pixels that are neither transparent, white nor silver form the
    icon's shape: it is painted white k pixels right and down, then gray in
    its place.
    """
    size, k = canvas.size, canvas.k
    table = bytes(color not in (None, WHITE, SILVER) for color in canvas.colors)
    shape = canvas.pixels.translate(table.ljust(256, b"\0"))    # 1 where the shape is
    pixels = bytearray(size * size)
    for y in range(size - k):                   # white (colour 1), k pixels right and down
        start = (y + k) * size + k
        pixels[start:start + size - k] = shape[y * size:y * size + size - k]
    for i, inside in enumerate(shape):
        if inside:
            pixels[i] = 2                       # gray
    return pixels, [None, WHITE, GRAY]


def _chunk(kind, data):
    """One PNG chunk: length, kind, data and checksum."""
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", binascii.crc32(kind + data)))


def _encode(size, pixels, colors):
    """A PNG file of size x size RGBA pixels, from colour numbers (0 is transparent)."""
    rgba = [bytes(4)] + [bytes((*color, 255)) for color in colors[1:]]
    rows = b"".join(b"\0" + b"".join(rgba[n] for n in pixels[i:i + size])
                    for i in range(0, len(pixels), size))
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(rows))
            + _chunk(b"IEND", b""))


@functools.lru_cache(maxsize=64)
def _toolbar_picture(name, size, plain=False):
    """The RGBA bytes of a toolbar icon, kept for its disabled form. plain gives undo and
    redo as the gray-blue arrow."""
    art = _Art(size, BASES[name])
    (_turn if plain else _DRAW[name])(art)
    if name != "redo":
        return art.finished()
    frame = array.array("I", art.finished())    # its head at the upper right
    for start in range(0, size * size, size):
        frame[start:start + size] = frame[start:start + size][::-1]
    return frame.tobytes()


def forget_pictures():
    """Forget the pictures kept, so that the next ones are made from nothing."""
    _toolbar_picture.cache_clear()
    _disc_picture.cache_clear()


def _encode_rgba(size, frame):
    """A PNG file of size x size pixels, from their RGBA bytes."""
    stride = 4 * size
    rows = b"".join(b"\0" + frame[i:i + stride] for i in range(0, len(frame), stride))
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(rows, 1))
            + _chunk(b"IEND", b""))


def png(name, size, disabled=False, ring=None):
    """The icon called name as a square RGBA PNG image, size x size pixels (8 to 256).

    An unknown name raises KeyError. ring is the width in pixels of each
    ring of close_active's raised bevel; by default it is the width of the
    icon's outlines.
    """
    if name in TOOLBAR:
        if not 8 <= size <= 256:
            raise ValueError(f"icon size must be from 8 to 256 pixels, not {size}")
        if disabled and name in TURNING:
            return _encode_rgba(size, _ghosted(_toolbar_picture(name, size, True)))
        frame = _toolbar_picture(name, size)
        return _encode_rgba(size, _ghosted(frame) if disabled else frame)
    canvas = _picture(name, size, ring)
    if disabled:
        return _encode(size, *_embossed(canvas))
    return _encode(size, canvas.pixels, canvas.colors)


def photo(master, name, size, disabled=False):
    """The icon called name as a PhotoImage of master, size x size pixels.

    close_active's button has the rings of the style's own bevels on
    master's display, like the tab beside it, even at a scale where they are
    a pixel wider or narrower than the icon's outlines (147 % to 149 %, for
    example).
    """
    # Tk documents base64 as a form of PNG data that it always reads.
    data = base64.b64encode(png(name, size, disabled, px(master, BEVEL))).decode("ascii")
    return tkinter.PhotoImage(master=master, data=data, format="png")


# ARES's own icon: the helmet of Ares, a Corinthian helmet with a red horsehair crest. Each
# letter is a pixel in a colour of HELMET_COLOURS, "." is transparent.

HELMET_32 = (
    "................................",
    "...........KKKKKKKKKKK..........",
    "..........KRRRRRRRRRRRKK........",
    "........KKRRRRRRMMRRRRRRKK......",
    ".......KRRRRMMMRRRRMMMRRRRK.....",
    ".......KRRMMRRRRRRRRRRMMRRRK....",
    "......KRRMRRMMMMMMMMRRRRMRRRK...",
    "......KRMRMMKKKKKKKKMMMRRMRRK...",
    "......KMMMKKYYYYYYYYKKKMRRMRRK..",
    ".......KKKYYYYOOOOOOYYYKMRMRRK..",
    ".......KYYWWOOOOOOOOOOOYKKRMRRK.",
    "......KYYWOOOOOOOOOOOOOOYKRMRRK.",
    "......KYYOOOOOOOOOOOOOOOOOKKMRK.",
    ".....KYYOOOOOOOOOOOOOOOOOOK.KRK.",
    ".....KYYOKKOOOOOOOOOOOOOOOOKKRK.",
    ".....KYKKKKKKOOOOOOOOOOOOOOK.KK.",
    ".....KYOKKKKOOOOOOOOOOOOOOOK.KK.",
    ".....KYOOOOOOOOOOOOOOOOOOOOK..K.",
    ".....KYOOOOOOOOOOOOOOOOOOOOK....",
    ".....KYOOOOOOOOOOOOOOOOOOOK.....",
    ".....KYOOOOOOOOOOOOOOOOOOOK.....",
    ".....KKKKKOOOOOOOOOOOOOOOOK.....",
    ".....KYOOOOOOOOOOOOOOOOOOOK.....",
    ".....KYOOOOOOOOOKKKOOOOOOOOK....",
    ".....KYOOOOOOOOK...KYOOOOOOK....",
    ".....KYOOOOOOOK.....KYOOOOOK....",
    ".....KYOOOOOOK.......KKKKKKK....",
    "......KKKKKKK...................",
    "................................",
    "................................",
    "................................",
    "................................",
)

HELMET_16 = (
    "................",
    ".....KKKKKK.....",
    "....KRRRRRRKK...",
    "...KRRMMMMRRRK..",
    "...KRMKKKKKMRRK.",
    "...KKKYYYYYKKRK.",
    "...KYYWOOOOYKMK.",
    "..KYOOOOOOOOKRK.",
    "..KYKKKOOOOOOKK.",
    "..KYOOOOOOOOOK..",
    "..KYOOOOOOOOOK..",
    "..KKKOOOOOOOOK..",
    "..KYOOOOKKOOOOK.",
    "..KYOOOK..KOOOK.",
    "..KKKKK....KKKK.",
    "................",
)

HELMET_COLOURS = {"K": BLACK, "R": RED, "M": MAROON, "O": OLIVE, "Y": YELLOW, "W": WHITE}
# The pictures of the icon of a window, by size in pixels: (grid, whole-number enlargement).
WINDOW_PICTURES = {16: (HELMET_16, 1), 32: (HELMET_32, 1), 48: (HELMET_16, 3),
                   64: (HELMET_32, 2), 128: (HELMET_32, 4)}


def helmet_png(grid, factor, square=None):
    """The helmet of grid, each of its pixels factor x factor pixels, as a PNG image.

    It lies in the middle of a transparent square of square pixels, by default
    just big enough for it. factor is a whole number.
    """
    size = len(grid) * factor
    square = size if square is None else square
    if square < size:
        raise ValueError(f"a helmet of {size} pixels does not fit in {square}")
    numbers = {letter: i for i, letter in enumerate(HELMET_COLOURS, 1)}
    numbers["."] = 0
    pixels = bytearray(square * square)
    inset = (square - size) // 2
    for y, row in enumerate(grid):
        line = b"".join(bytes((numbers[letter],)) * factor for letter in row)
        for copy in range(y * factor, (y + 1) * factor):
            start = (inset + copy) * square + inset
            pixels[start:start + size] = line
    return _encode(square, pixels, [None, *HELMET_COLOURS.values()])


def helmet_photo(master, grid, factor):
    """The helmet of grid, enlarged factor times, as a PhotoImage of master."""
    data = base64.b64encode(helmet_png(grid, factor)).decode("ascii")
    return tkinter.PhotoImage(master=master, data=data, format="png")


def design_factor(widget, factor):
    """A whole-number enlargement close to factor design pixels per pixel of a grid."""
    return max(1, round(factor * scale(widget)))


def window_photos(master):
    """The pictures of the icon of a window as PhotoImages of master, the smallest first."""
    return [helmet_photo(master, *WINDOW_PICTURES[size]) for size in sorted(WINDOW_PICTURES)]


def window_png(wanted):
    """The icon of a window for a place of wanted x wanted pixels, as a PNG image.

    It is the largest of WINDOW_PICTURES that fits, or the smallest, on a
    transparent square of that size, so that the system has nothing to
    enlarge or shrink, and so nothing to smooth.
    """
    fits = [size for size in WINDOW_PICTURES if size <= wanted]
    grid, factor = WINDOW_PICTURES[max(fits) if fits else min(WINDOW_PICTURES)]
    return helmet_png(grid, factor, max(wanted, len(grid) * factor))
