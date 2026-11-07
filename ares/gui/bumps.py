# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The dotted texture of the toolbar's grip and the window's dividers.

The dots are a pattern of 4 x 4 design pixels: two dark dots, each with a light one up and to the
left of it, the second pair two design pixels right of and below the first. A canvas draws them
with two polygons, one for each colour, whatever the number of dots: a polygon can visit every
dot and come back along the same line, which encloses nothing. Tk's stipple bitmaps cannot do
this, because their dots do not grow with the display.

A Divider lays such a canvas over the sash of a ttk paned window, which has no way to show a
texture itself: it follows the sash, and it moves the sash when it is dragged.
"""

import tkinter as tk

from .style import GRID, HIGHLIGHT
from .widgets import px, scale

PERIOD = 4                  # the pattern's size, in design pixels
BAND = 4                    # the width of the dotted band along a divider
BAND_START = {True: 5, False: 4}    # from a divider's edge to it: lying down, and standing


def dots(x0, y0, x1, y1, ratio, shift=0):
    """The top left corners of the dots inside a box, as (x, y) pixels.

    ratio is pixels per design pixel; shift moves the pattern right and down by that many
    design pixels (the light dots lie one to the left of and above the dark ones).
    """
    found = []
    size = max(1, round(ratio))
    rows = int((y1 - y0) / ratio) + PERIOD
    columns = int((x1 - x0) / ratio) + PERIOD
    for row in range(0, rows, PERIOD // 2):
        offset = PERIOD // 2 if row % PERIOD else 0
        for column in range(offset, columns, PERIOD):
            x = x0 + round((column + shift) * ratio)
            y = y0 + round((row + shift) * ratio)
            if x + size <= x1 and y + size <= y1:
                found.append((x, y))
    return found


def outline(points, size):
    """One polygon's coordinates through squares of size pixels at points: each is walked
    round, and the way back runs along the same line, so that only the squares are filled."""
    if not points:
        return []
    path = []
    for x, y in points:
        path += [x, y, x + size, y, x + size, y + size, x, y + size, x, y]
    for x, y in reversed(points):
        path += [x, y]
    return path


def draw(canvas, x0, y0, x1, y1, tags=()):
    """Draw the texture in a box of a canvas: its light dots, then its dark ones."""
    ratio = scale(canvas)
    size = px(canvas, 1)
    for colour, shift in ((HIGHLIGHT, 0), (GRID, 1)):
        path = outline(dots(x0, y0, x1, y1, ratio, shift), size)
        if path:
            canvas.create_polygon(*path, fill=colour, width=0, tags=tags)


def clamped(position, length, thickness, least):
    """position, moved as little as it takes to keep both panes at their least sizes. A window
    too small for both shares what it has in their proportion."""
    first, second = least
    if not first and not second:
        return position
    room = length - thickness
    if room < first + second:
        return room * first // (first + second)
    return min(max(position, first), room - second)


def limit_tag(paned):
    """The bind tag of keep_panes()."""
    return f"AresPanes{id(paned)}"


def keep_panes(paned, least, thickness):
    """Keep the panes of a ttk paned window at their least sizes (in pixels) while Tk's own
    binding drags its first sash: a tag after Tk's puts the sash back within them."""
    paned.least, paned.sash_thickness = least, thickness
    tags = list(paned.bindtags())
    tags.insert(tags.index("TPanedwindow") + 1, limit_tag(paned))
    paned.bindtags(tuple(tags))
    paned.bind_class(limit_tag(paned), "<B1-Motion>", lambda event: keep_panes_now(paned))


def keep_panes_now(paned):
    """Put the first sash of a window given to keep_panes() back within its limits."""
    if len(paned.panes()) < 2:
        return
    length = (paned.winfo_height() if str(paned.cget("orient")) == "vertical"
              else paned.winfo_width())
    at = paned.sashpos(0)
    limited = clamped(at, length, paned.sash_thickness, paned.least)
    if limited != at:
        paned.sashpos(0, limited)


class Divider:
    """The dotted cover of the first sash of a ttk paned window (see the module's description).

    least are the pixels that a drag leaves to the panes before and after it.
    """

    def __init__(self, paned, first, thickness, least=(0, 0)):
        self.paned, self.first = paned, first
        self.thickness = thickness
        self.least = least
        self.vertical = str(paned.cget("orient")) == "vertical"    # the panes lie one over another
        background = paned.winfo_toplevel().cget("background")
        self.canvas = tk.Canvas(paned, borderwidth=0, highlightthickness=0,
                                takefocus=False, background=background,
                                cursor="sb_v_double_arrow" if self.vertical
                                else "sb_h_double_arrow")
        self._grabbed = None        # where in the divider the mouse pressed
        self._length = None
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        paned.bind("<Configure>", self.place, add="+")
        first.bind("<Configure>", self.place, add="+")

    def position(self):
        return self.paned.sashpos(0)

    def place(self, event=None):
        """Put the cover on the sash, and draw it again if its length changed."""
        at = self.position()
        if self.vertical:
            self.canvas.place(x=0, y=at, relwidth=1, height=self.thickness)
            length = self.paned.winfo_width()
        else:
            self.canvas.place(x=at, y=0, relheight=1, width=self.thickness)
            length = self.paned.winfo_height()
        tk.Misc.tkraise(self.canvas)
        if length != self._length:
            self._length = length
            self.draw(length)

    def draw(self, length):
        canvas = self.canvas
        canvas.delete("all")
        band = px(canvas, BAND)
        start = px(canvas, BAND_START[self.vertical])
        line = px(canvas, 1)
        far = self.thickness - line         # a gray line along its far edge
        if self.vertical:
            draw(canvas, 0, start, length, start + band)
            canvas.create_rectangle(0, far, length, self.thickness, fill=GRID, width=0)
        else:
            draw(canvas, start, 0, start + band, length)
            canvas.create_rectangle(far, 0, self.thickness, length, fill=GRID, width=0)

    def _at(self, event):
        return event.y if self.vertical else event.x

    def _press(self, event):
        self._grabbed = self._at(event)

    def _drag(self, event):
        if self._grabbed is None:
            return
        length = (self.paned.winfo_height() if self.vertical else self.paned.winfo_width())
        wanted = self.position() + self._at(event) - self._grabbed
        self.paned.sashpos(0, clamped(wanted, length, self.thickness, self.least))
        self.place()

    def _release(self, event):
        self._grabbed = None
