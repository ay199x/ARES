# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Notebooks whose tabs have a slanted left edge, drawn by Tk on a canvas.

A theme element of ttk can only be a rectangle, so a Notebook keeps ttk's notebook for
everything that matters (its pages, selection, keyboard bindings and focus) and lays a strip, a
canvas, over the row of its tabs. The strip draws the tabs, the two lines above the page and the
tab under the mouse, and it answers the mouse; the keys go to the notebook as ever, which keeps
the keyboard focus and tells the strip what changed. Thin frames around the page draw the
remaining lines of its frame.

The drawing has no pictures except a tab's close button, which is an icon.
"""

import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont
from tkinter import ttk

from .style import (BEVEL, FACE, GRID, HIGHLIGHT, MENU_SELECTION, SHADOW, TAB, TAB_BORDER,
                    TAB_HEIGHT, TAB_LEFT, TAB_SIDE, TAB_TOP, TEXT)
from .widgets import px

SLANT = 5                   # how far the top left corner of a tab is cut, in design pixels
CLOSE_GAP = 4               # between a tab's text and its close button
NARROW_SIDE = 3             # from a squeezed tab's edge to its text
WATCHED = ("<<NotebookTabChanged>>", "<FocusIn>", "<FocusOut>", "<Configure>")
ELLIPSIS = "..."


@dataclass(frozen=True)
class TabBox:
    """Where a tab is on the strip, in pixels: x <= x < right, top <= y < bottom."""
    index: int
    x: int
    right: int
    top: int
    bottom: int
    text: str               # as it fits
    selected: bool
    first: bool
    last: bool


def outline(box, slant):
    """The corners of a tab, from the bottom of its left side, clockwise: a corner cut."""
    return (box.x, box.bottom, box.x, box.top + slant, box.x + slant, box.top,
            box.right, box.top, box.right, box.bottom)


def fit_text(text, room, measure):
    """text, shortened with dots at its end until measure() says it fits in room pixels."""
    if measure(text) <= room:
        return text
    while text and measure(text + ELLIPSIS) > room:
        text = text[:-1]
    return text + ELLIPSIS if text else ""


def squeeze(widths, room):
    """The widths, the largest made smaller until their sum fits room; none under 1."""
    widths = list(widths)
    while sum(widths) > room and max(widths, default=0) > 1:
        largest = max(widths)
        lower = max((width for width in widths if width < largest), default=1)
        tall = [i for i, width in enumerate(widths) if width == largest]
        step = min(largest - lower, -(-(sum(widths) - room) // len(tall))) or 1
        for i in tall:
            widths[i] = max(1, widths[i] - step)
    return widths


def frame_lines(master, widget):
    """Draw hair lines around widget, in master, a child of whose parent it is: gray at its top
    and left, white at its bottom and right. They lie just outside it. Returns them."""
    hair = max(1, px(master, BEVEL) // 2)
    places = ((GRID, {"x": -hair, "y": -hair, "relwidth": 1, "width": 2 * hair, "height": hair}),
              (GRID, {"x": -hair, "y": -hair, "relheight": 1, "height": 2 * hair, "width": hair}),
              (HIGHLIGHT, {"x": -hair, "rely": 1, "relwidth": 1, "width": 2 * hair,
                           "height": hair}),
              (HIGHLIGHT, {"relx": 1, "y": -hair, "relheight": 1, "height": 2 * hair,
                           "width": hair}))
    lines = []
    for colour, place in places:
        line = tk.Frame(master, background=colour, borderwidth=0, highlightthickness=0,
                        takefocus=False)
        line.place(in_=widget, bordermode="outside", **place)
        lines.append(line)
    return lines


class Notebook(ttk.Notebook):
    """A ttk notebook with slanted tabs (see the module's description).

    strip is the colour behind the tabs. on_press, when set, gets the index of a tab the
    mouse pressed; it returns True when it dealt with that, else the tab is activated as
    ttk's own press would. <<TabClicked>> comes at the release of the mouse on a tab.
    """

    def __init__(self, master=None, strip=FACE, **options):
        super().__init__(master, **options)
        self.on_press = None
        self.close_images = None        # (normal, under the mouse) on closable tabs
        self.font = tkfont.nametofont("TkDefaultFont", root=self)
        self.ring = px(self, BEVEL)
        self.slant = px(self, SLANT)
        self.row = px(self, TAB_TOP) + px(self, TAB_HEIGHT)     # the height of the tabs' row
        self.strip = tk.Canvas(self, height=self.row + 2 * self.ring, background=strip,
                               borderwidth=0, highlightthickness=0, takefocus=False)
        self.strip.place(x=0, y=0, relwidth=1)
        self._frame_lines()
        self._job = None
        self._hover = None              # the index of the tab whose close button is under the mouse
        self.strip.bind("<ButtonPress-1>", self._press)
        self.strip.bind("<ButtonRelease-1>", self._release)
        self.strip.bind("<Motion>", self._motion)
        self.strip.bind("<Enter>", self._motion)    # the mouse can arrive on a button at once
        self.strip.bind("<Leave>", self._left)
        # Through a bind tag of its own: a plain bind() of whoever uses the notebook would replace
        # a binding on the widget.
        self._tag = f"AresTabs{id(self)}"
        self.bindtags((self._tag, *self.bindtags()))
        for sequence in WATCHED:
            self.bind_class(self._tag, sequence, self._redraw_soon)
        self.bind_class(self._tag, "<Destroy>", self._destroyed)
        self.strip.bind("<Configure>", self._redraw_soon)
        self._pressed_close = None
        self.closing = None             # the tab whose close button was clicked

    def _frame_lines(self):
        """The lines of the page's frame that the strip does not draw: blue at the left, and
        gray with a thin white one outside it at the right and the bottom."""
        hair = max(1, self.ring // 2)
        ring = self.ring
        top = self.row
        edge = hair * 2 + ring
        lines = ((TAB_BORDER, {"x": 0, "y": top, "width": hair, "relheight": 1, "height": -top}),
                 (GRID, {"relx": 1, "x": -edge, "y": top + 2 * ring, "width": ring, "relheight": 1,
                         "height": -top - 2 * ring - hair * 2}),
                 (GRID, {"x": hair, "rely": 1, "y": -edge, "relwidth": 1, "width": -hair * 3,
                         "height": ring}),
                 (HIGHLIGHT, {"relx": 1, "x": -hair, "y": top, "width": hair, "relheight": 1,
                              "height": -top}),
                 (HIGHLIGHT, {"x": 0, "rely": 1, "y": -hair, "relwidth": 1, "height": hair}))
        self.frame_lines = []
        for colour, place in lines:
            line = tk.Frame(self, background=colour, borderwidth=0, highlightthickness=0,
                            takefocus=False)
            line.place(**place)
            self.frame_lines.append(line)

    # What changes the tabs: every call that adds, removes or renames one -------------------

    def add(self, child, **options):
        super().add(child, **options)
        self._redraw_soon()

    def insert(self, pos, child, **options):
        super().insert(pos, child, **options)
        self._redraw_soon()

    def forget(self, tab_id):
        super().forget(tab_id)
        self._redraw_soon()

    def hide(self, tab_id):
        super().hide(tab_id)
        self._redraw_soon()

    def tab(self, tab_id, option=None, **options):
        result = super().tab(tab_id, option, **options)
        if options:
            self._redraw_soon()
        return result

    def _redraw_soon(self, event=None):
        """Draw the strip once the changes of the moment are done."""
        if self._job is None:
            self._job = self.after_idle(self._idle)

    def _idle(self):
        self._job = None
        self.draw()

    def _destroyed(self, event):
        if event.widget is not self:
            return
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        for sequence in (*WATCHED, "<Destroy>"):
            self.tk.call("bind", self._tag, sequence, "")

    # Where the tabs are ------------------------------------------------------------------

    def _natural_width(self, text):
        return self.font.measure(text) + self._around_text()

    def _around_text(self):
        """What a tab with a close button needs beside its text."""
        room = 2 * px(self, TAB_SIDE)
        if self.close_images is not None:
            room += px(self, CLOSE_GAP) + self.close_images[0].width()
        return room

    def _fitted(self, widths, chosen, room):
        """The widths made to fit room. The selected tab, at index chosen (or None), keeps room
        for a little of its text, and for its close button."""
        fitted = squeeze(widths, room)
        least = self._around_text() + self.font.measure("ab" + ELLIPSIS)
        if chosen is None or fitted[chosen] >= min(least, widths[chosen]):
            return fitted
        others = widths[:chosen] + widths[chosen + 1:]
        keep = min(least, widths[chosen])
        fitted = squeeze(others, max(len(others), room - keep))
        return fitted[:chosen] + [keep] + fitted[chosen:]

    def boxes(self, width=None):
        """A TabBox for each shown tab, in a strip of width pixels (the strip's own by default)."""
        width = self.strip.winfo_width() if width is None else width
        left = px(self, TAB_LEFT)
        shown = [(i, self.tab(tab, "text")) for i, tab in enumerate(self.tabs())
                 if str(self.tab(tab, "state")) != "hidden"]
        widths = [self._natural_width(text) for _, text in shown]
        current = self.index("current") if self.select() else None
        chosen = next((i for i, (index, _) in enumerate(shown) if index == current), None)
        if width > 1:                   # a window never shown has no width: nothing to fit in
            widths = self._fitted(widths, chosen, max(len(shown), width - left))
        boxes, x = [], left
        for number, ((index, text), wide) in enumerate(zip(shown, widths)):
            room = wide - (self._around_text() if self._closable(wide, index == current)
                           else 2 * px(self, NARROW_SIDE))
            boxes.append(TabBox(index, x, x + wide, px(self, TAB_TOP), self.row,
                                fit_text(text, room, self.font.measure),
                                index == current, number == 0, number == len(shown) - 1))
            x += wide
        return boxes

    def _closable(self, wide, selected):
        """True when a tab wide pixels wide shows its close button: every tab does until there
        is no room for dots beside it; the selected one always."""
        return self.close_images is not None and (
            selected or wide >= self._around_text() + self.font.measure(ELLIPSIS))

    def tab_at(self, x, y):
        """The index of the tab at (x, y) of the strip, or None. The corner cut off a tab
        belongs to the tab before it."""
        for box in self.boxes():
            if box.x <= x < box.right and box.top <= y < box.bottom:
                if x - box.x + y - box.top < self.slant:
                    return None if box.first else box.index - 1
                return box.index
        return None

    def close_box(self, box):
        """(x0, y0, x1, y1) of the close button of the tab of box, or None."""
        if not self._closable(box.right - box.x, box.selected):
            return None
        image = self.close_images[0]
        x1 = box.right - px(self, TAB_SIDE)
        y0 = box.top + (box.bottom - box.top - image.height()) // 2
        return x1 - image.width(), y0, x1, y0 + image.height()

    def close_at(self, x, y):
        """The index of the tab whose close button is at (x, y), or None."""
        for box in self.boxes():
            area = self.close_box(box)
            if area is not None and area[0] <= x < area[2] and area[1] <= y < area[3]:
                return box.index
        return None

    # Drawing ---------------------------------------------------------------------------------

    def draw(self):
        """Draw the tabs, and the frame's lines above the page."""
        canvas = self.strip
        canvas.delete("all")
        boxes = self.boxes()
        width = max(canvas.winfo_width(), 1)
        ring, row = self.ring, self.row
        canvas.create_rectangle(0, row, width, row + ring, fill=TAB_BORDER, width=0)
        canvas.create_rectangle(0, row + ring, width, row + 2 * ring, fill=HIGHLIGHT, width=0)
        for box in sorted(boxes, key=lambda box: box.selected):     # the selected one on top
            self._draw_tab(box, boxes)

    def _draw_tab(self, box, boxes):
        canvas, ring, slant = self.strip, self.ring, self.slant
        selected = box.selected
        fill = TAB if selected else FACE
        line = TAB_BORDER if selected else GRID
        before = next((other for other in boxes if other.right == box.x), None)
        if before is not None:          # the corner cut off shows the tab before it
            canvas.create_polygon(box.x, box.top, box.x + slant, box.top, box.x, box.top + slant,
                                  fill=TAB if before.selected else FACE, width=0)
        bottom = box.bottom + (2 * ring if selected else 0)
        shape = outline(TabBox(box.index, box.x, box.right, box.top, bottom, box.text, selected,
                               box.first, box.last), slant)
        canvas.create_polygon(*shape, fill=fill, width=0)
        # The outline: the slant, the top, the left side and, on the last tab or the selected
        # one, the right side; a neighbour's left side is the right side of the others.
        canvas.create_line(box.x, box.top + slant, box.x + slant, box.top, fill=line, width=ring)
        canvas.create_rectangle(box.x + slant, box.top, box.right, box.top + ring, fill=line,
                                width=0)
        side_top = box.top if before is not None and not selected else box.top + slant
        canvas.create_rectangle(box.x, side_top, box.x + ring, bottom, fill=line, width=0)
        if box.last or selected:
            canvas.create_rectangle(box.right - ring, box.top, box.right, bottom, fill=line,
                                    width=0)
        if selected:
            focused = str(self.tk.call("focus")) == str(self)
            light = MENU_SELECTION if focused else HIGHLIGHT
            canvas.create_line(box.x + ring, box.top + slant + ring, box.x + slant + ring,
                               box.top + ring, fill=light, width=ring)
            canvas.create_rectangle(box.x + slant + ring, box.top + ring, box.right - ring,
                                    box.top + 2 * ring, fill=light, width=0)
            canvas.create_rectangle(box.x + ring, box.top + slant + ring, box.x + 2 * ring, bottom,
                                    fill=light, width=0)
        self._draw_label(box)

    def _draw_label(self, box):
        canvas = self.strip
        state = str(self.tab(self.tabs()[box.index], "state"))
        colour = SHADOW if state == "disabled" else TEXT
        middle = (box.top + box.bottom) // 2 + self.ring
        area = self.close_box(box)
        if area is None:
            canvas.create_text((box.x + box.right) // 2, middle, text=box.text, fill=colour,
                               font=self.font)
            return
        canvas.create_text(box.x + px(self, TAB_SIDE), middle, text=box.text, anchor="w",
                           fill=colour, font=self.font)
        image = self.close_images[1 if box.index == self._hover else 0]
        canvas.create_image(area[0], area[1] + self.ring, image=image, anchor="nw")

    # The mouse --------------------------------------------------------------------------

    def _press(self, event):
        self._pressed_close = self.close_at(event.x, event.y)
        if self._pressed_close is not None:
            return "break"              # a tab being closed is not selected
        index = self.tab_at(event.x, event.y)
        if index is None or str(self.tab(self.tabs()[index], "state")) == "disabled":
            return None
        if self.on_press is None or not self.on_press(index):
            self.activate(index)
        return None

    def activate(self, index):
        """What a press on a tab does: bring it to the front and move the keyboard focus."""
        self.tk.call("ttk::notebook::ActivateTab", self._w, index)

    def _release(self, event):
        pressed, self._pressed_close = self._pressed_close, None
        if pressed is not None and self.close_at(event.x, event.y) == pressed:
            self.closing = self.tabs()[pressed]
            self.event_generate("<<CloseTab>>")
        elif self.tab_at(event.x, event.y) is not None:
            self.event_generate("<<TabClicked>>")

    def _motion(self, event):
        if self.close_images is not None:
            self._set_hover(self.close_at(event.x, event.y))

    def _left(self, event):
        self._set_hover(None)

    def _set_hover(self, index):
        if index != self._hover:
            self._hover = index
            self._redraw_soon()


class ClosableNotebook(Notebook):
    """A notebook whose tabs have close buttons: a press and release on one generates
    <<CloseTab>> on the notebook, with the tab in closing.

    close_images are (normal, under the mouse): the caller keeps them alive.
    """

    def __init__(self, master, close_images, **options):
        super().__init__(master, strip=TAB, **options)
        self.close_images = close_images
