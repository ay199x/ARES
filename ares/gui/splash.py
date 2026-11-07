# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The splash screen shown while ARES starts.

A window without a title bar, centred on the screen: a raised frame around a navy panel with
the helmet, ARES's name and version, and a Windows 98 progress bar of separate blocks. It is
one canvas that needs nothing but Tk, so it can show before the rest of the program is
imported. It closes as soon as the main window is on the screen.
"""

import tkinter as tk
from tkinter import font as tkfont

from .. import APP_FULL_NAME, APP_NAME, __version__
from . import icons
from .style import FACE, NAVY, RAISED, SUNKEN, classic_font, draw_bevel
from .widgets import px

WHITE = "#FFFFFF"
SILVER = "#C0C0C0"
# Sizes in design pixels.
WIDTH, HEIGHT = 440, 196        # the whole window
FRAME = 2                       # the face inside the raised rings, around the panel
MARGIN = 14                     # inside the panel
HELMET_FACTOR = 4               # design pixels per pixel of the helmet's grid
HELMET = 32 * HELMET_FACTOR
GAP = 16                        # between the helmet and the text
NAME_SIZE = 44                  # the letters of ARES, in pixels
TITLE_SIZE = 16                 # the full name
VERSION_SIZE = 13
BAR_HEIGHT = 16                 # the progress bar
BLOCK, BLOCK_GAP = 8, 2         # a block of the bar and the gap after it
BAR_INSET = 2                   # between the bar's frame and its blocks


def centred(widget, width, height):
    """Where a window of that size lies in the middle of the screen: "+x+y"."""
    x = (widget.winfo_screenwidth() - width) // 2
    y = (widget.winfo_screenheight() - height) // 2
    return f"+{x}+{y}"


class Splash:
    """The splash screen: advance() fills the bar, close() takes it away."""

    def __init__(self, root):
        window = self.window = tk.Toplevel(root)
        window.withdraw()
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        width, height = px(window, WIDTH), px(window, HEIGHT)
        canvas = self.canvas = tk.Canvas(window, width=width, height=height, borderwidth=0,
                                         highlightthickness=0, background=FACE, takefocus=False)
        canvas.pack()
        ring = px(window, 1)
        draw_bevel(canvas, 0, 0, width, height, rings=RAISED)
        inset = 2 * ring + px(window, FRAME)
        canvas.create_rectangle(inset, inset, width - inset, height - inset, fill=NAVY, width=0)
        margin = inset + px(window, MARGIN)
        self._draw_helmet(margin)
        self._draw_text(margin + icons.design_factor(window, HELMET_FACTOR) * 32
                        + px(window, GAP), margin)
        self._draw_bar(margin, width - margin, height - margin)
        window.geometry(centred(window, width, height))
        window.deiconify()
        window.update()

    def _draw_helmet(self, margin):
        factor = icons.design_factor(self.window, HELMET_FACTOR)
        self.helmet = icons.helmet_photo(self.window, icons.HELMET_32, factor)
        self.canvas.create_image(margin, margin, image=self.helmet, anchor="nw")

    def _font(self, size, weight):
        window = self.window
        family = (classic_font(window) or ("TkDefaultFont",))[0]
        return tkfont.Font(root=window, family=family, size=-px(window, size), weight=weight)

    def _draw_text(self, left, top):
        canvas = self.canvas
        fonts = self.fonts = (self._font(NAME_SIZE, "bold"), self._font(TITLE_SIZE, "normal"),
                              self._font(VERSION_SIZE, "normal"))
        y = top
        for text, font, colour in ((APP_NAME, fonts[0], WHITE), (APP_FULL_NAME, fonts[1], WHITE),
                                   (f"Version {__version__}", fonts[2], SILVER)):
            canvas.create_text(left, y, text=text, font=font, fill=colour, anchor="nw")
            y += font.metrics("linespace") + px(self.window, 3)

    def _draw_bar(self, left, right, bottom):
        window, canvas = self.window, self.canvas
        top = bottom - px(window, BAR_HEIGHT)
        draw_bevel(canvas, left, top, right, bottom, rings=SUNKEN)
        inset = 2 * px(window, 1) + px(window, BAR_INSET)
        block, gap = px(window, BLOCK), px(window, BLOCK_GAP)
        count = (right - left - 2 * inset + gap) // (block + gap)
        x = left + inset
        self.blocks = []                # (left, top, right, bottom) of each block
        for _ in range(count):
            self.blocks.append((x, top + inset, x + block, bottom - inset))
            x += block + gap
        self.filled = 0

    def advance(self, share):
        """Fill the bar up to share of its length, a number from 0 to 1, and show it."""
        wanted = round(min(max(share, 0), 1) * len(self.blocks))
        if wanted <= self.filled:
            return
        for box in self.blocks[self.filled:wanted]:
            self.canvas.create_rectangle(*box, fill=NAVY, width=0)
        self.filled = wanted
        self.canvas.update_idletasks()

    def close(self):
        self.window.destroy()
