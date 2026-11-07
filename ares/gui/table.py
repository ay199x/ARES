# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""A table for any number of rows, drawn on a canvas: only the rows on the screen are drawn.

The Text Segment, Data Segment, Labels and Registers use it. A Treeview
cannot colour a single cell (the Data Segment highlights single words) or a
single letter (the flags of CPSR), and holding only the rows on the screen it
would scroll them away by itself. Its columns fill its width: the stretching
columns share what the others leave.
"""

import re
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import font as tkfont
from tkinter import ttk

from .style import (BEVEL, FACE, GRID, checkbox_size, draw_bevel, draw_checkbox, place_checkbox,
                    show_checkbox, sunken)
from .style import TEXT as HEADING_TEXT
from .widgets import TOOLTIP_DELAY, bars_needed, is_aqua, keep_size, px, show_bar, tip_window

DEFAULT_ROWS = 20       # rows taken to fit until the table knows its height (hidden windows)
ROW_HEIGHT = 16         # a row with its line, in design pixels
HEADING_HEIGHT = 20     # the headings, likewise
WHEEL_ROWS = 3          # rows scrolled per notch of the mouse wheel
WHEEL_NOTCH = 120       # mouse wheel delta of one notch on Windows
PAD = 4                 # space between a cell's border and its text, in design pixels
GRAB = 4                # how near a heading's right border the mouse can drag it, likewise
MIN_WIDTH = 16          # narrowest column, likewise
ELLIPSIS = "…"     # ends a text cut to fit its cell

WHITE = "#FFFFFF"
STRIPE = "#E0E0E0"      # every second row, from the first
TEXT = "#000000"
MARK_OFF = "#ADADAD"    # a mark that is off (a flag whose bit is 0): light gray
_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}")
HIDDEN = "hidden"       # a row place showing nothing
# How a column shows the rows' colours: stripes and a row's own colour, stripes only, or
# neither (white).
SHADED, STRIPED, PLAIN = "shaded", "striped", "plain"
LIT = 0.65              # a highlight's lit edge: this much of the way to white
SHADED_EDGE = 0.55      # a highlight's shaded edge: its colour times this


@dataclass
class Column:
    id: str
    heading: str
    width: int                  # pixels its contents need; the width drawn may be more
    anchor: str = "w"           # where the text sits in its cell: "w", "e" or "center"
    checkbox: bool = False      # the cells hold checkboxes, (checked, enabled) or None for none
    marks: int = 0              # the cells hold up to this many Marks (a tuple) instead
    stretch: bool = False       # shares the width the other columns leave with the other such
    shade: str = SHADED         # how it shows the rows' colours
    font: object = None         # its cells' font, when not the table's
    base: int = field(default=0, init=False)            # pixels its contents need
    dragged: bool = field(default=False, init=False)    # resized by hand: keeps its width

    def __post_init__(self):
        self.base = self.width


@dataclass(frozen=True)
class Mark:
    """A letter or word of a cell, drawn on its own from the left: black when on, else gray."""
    text: str
    on: bool = True
    tip: str = ""               # shown while the mouse rests on it
    space: bool = False         # a space before it


@dataclass
class Row:
    cells: tuple                # one text (or checkbox) per column
    background: str = ""        # the whole row's colour; "" for white or the stripe
    cell_backgrounds: dict = field(default_factory=dict)   # column id -> colour
    tip: str = ""               # shown while the mouse rests on the row (a mark shows its own)


def off_colour(background):
    """The colour of a mark that is off: light gray, as much darker on a coloured row as on white.

    #ADADAD on a green changed row (#99CC55) could hardly be seen.
    """
    if background == WHITE or not _COLOUR.fullmatch(background):
        return MARK_OFF
    return "#" + "".join(f"{round(int(background[k:k + 2], 16) * 0.68):02X}" for k in (1, 3, 5))


def edges(colour):
    """(lit, shaded): the colours of a highlight's raised edges: its top and left sides, and
    its bottom and right sides."""
    values = [int(colour[k:k + 2], 16) for k in (1, 3, 5)]
    lit = [round(value + (255 - value) * LIT) for value in values]
    shaded = [round(value * SHADED_EDGE) for value in values]
    return tuple("#" + "".join(f"{value:02X}" for value in side) for side in (lit, shaded))


def column_width(widget, font, chars, heading, heading_font=None):
    """Pixels for a column of chars characters of font under the given heading.

    The heading is in heading_font, or else in Tk's heading font.
    """
    heading_font = heading_font or tkfont.nametofont("TkHeadingFont", root=widget)
    return max(chars * font.measure("0"), heading_font.measure(heading)) + 2 * px(widget, PAD) + 2


class Table(tk.Frame):
    """Rows 0 to count - 1, each made by row(index) when it comes on the screen.

    The rows scroll with the scroll bar, the mouse wheel and the keys Up,
    Down, Page Up, Page Down, Home and End (which also move the selected
    row). The columns fill the table's width: the stretching ones share what
    the others leave, equally, but each at least as wide as its contents
    need; when even that does not fit, a horizontal scroll bar appears and
    the columns scroll sideways, headings and rows together. The vertical
    scroll bar shows only while not every row fits wholly; both bars are
    decided at once (widgets.bars_needed), so neither switches on and off.
    In a divided window the table's size is the dividers' alone. A heading's
    right border can be dragged to resize its column, which then keeps that
    width (not the last column's: it ends where the table does). The
    headings are raised buttons, and the table sits in a sunken border.
    Rows are white and light gray in turn, from a gray first row, with a
    line around each cell; a column's shade says which of the rows' colours
    it shows. A row or cell with a colour of its own is raised by a thin
    crisp edge. row_height and heading_height, in design pixels, are the
    heights of a row with its line and of the headings: a taller font gets
    more.
    Callbacks: on_click(index, column id) and on_double_click(...) for a
    row, on_mark(index, column id, number of the mark) for a double click on
    a mark, on_heading(column id) for a heading, on_scroll() when the rows or
    columns move on the screen, on_activate(index) for Enter or F2 on the
    selected row.
    """

    def __init__(self, master, columns, font, heading_font=None, stripes=True,
                 row_height=ROW_HEIGHT, heading_height=HEADING_HEIGHT):
        super().__init__(master)
        sunken(self)                    # around the headings, the rows and the scroll bars
        keep_size(self)                 # its bars coming and going move no divider
        self.columns = list(columns)
        self.font = font
        self.stripes = stripes          # rows white and gray in turn, else all white
        self.heading_font = heading_font or tkfont.nametofont("TkHeadingFont", root=self)
        self.on_click = self.on_double_click = self.on_heading = self.on_scroll = None
        self.on_mark = self.on_activate = None
        self.count = 0
        self.row = None
        self.top = 0                    # index of the first row on the screen
        self.selected = None            # index of the selected row, or None
        self.page = DEFAULT_ROWS        # rows that fit wholly
        self.slots = []                 # canvas items of each row place on the screen
        self._boxes = {}                # the inside of a checkbox -> all of its items
        self._rules = []                # the line under each row place
        self._raised = {}               # row place -> the items of the edges of its highlights
        self._shown = []                # what each place shows (HIDDEN, or None: not known)
        self._available = 0             # the body's width on the screen (0: not known yet)
        # The body's size with the scroll bars shown when it was measured: the room of
        # the body and the bars, which does not change when a bar comes or goes.
        self._room_width = self._room_height = 0
        self._hscroll_shown = self._vscroll_shown = True
        self._lines = []                # the line at the right of each column
        self._keep = None               # (row, center) kept in view when the size changes
        self._wheel = {"x": 0, "y": 0}  # mouse wheel turns not yet scrolled
        self._clicked = None            # the row of the last click (a double click's first)
        self._drag = None               # (column, start x, start width) while resizing
        self._pressed = None            # heading pressed and not yet released
        self._tips = {}                 # mark item -> its tooltip text
        self._tip_job = self._tip = None    # a tooltip waiting to show, the one shown
        self._tip_item = None           # the mark item the tooltip is for, or ("row", index)
        self._row_tip = ""              # the text of a row's tooltip
        self._motion_row = None         # the row the mouse was last seen over
        self._fixed = font.metrics("fixed")
        self._char = font.measure("0")
        self._pad = px(self, PAD)
        self._ring = px(self, BEVEL)
        self.row_height = max(px(self, row_height), font.metrics("linespace") + self._ring)
        style = ttk.Style(self)
        self.select_background = style.lookup("Treeview", "background", ("selected",)) or "#0078D7"
        self.select_foreground = style.lookup("Treeview", "foreground", ("selected",)) or WHITE
        heading_background = style.lookup("TFrame", "background") or "#F0F0F0"

        self.header = tk.Canvas(self, height=max(px(self, heading_height),
                                                 self.heading_font.metrics("linespace")
                                                 + 4 * self._ring),
                                background=heading_background, highlightthickness=0,
                                borderwidth=0, takefocus=False)
        # A small requested size: the dividers of the window decide the table's size.
        self.body = tk.Canvas(self, background=FACE, highlightthickness=0, borderwidth=0,
                              width=1, height=1, xscrollcommand=self._xscrolled,
                              takefocus=True)
        self.vscroll = ttk.Scrollbar(self, orient="vertical", command=self.yview)
        self.hscroll = ttk.Scrollbar(self, orient="horizontal", command=self.xview)
        self.header.grid(row=0, column=0, sticky="ew")
        self.body.grid(row=1, column=0, sticky="nsew")
        self.vscroll.grid(row=1, column=1, sticky="ns")
        self.hscroll.grid(row=2, column=0, sticky="ew")
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        # Marks the selected row when the row has a colour of its own (the next instruction).
        self._frame = self.body.create_rectangle(0, 0, 0, 0, outline=self.select_background,
                                                 width=2, state="hidden", tags=("frame",))
        self._framed = None             # (place, width) the frame is drawn at
        self._bind_events()
        self._layout()
        self.fit(self.row_height * DEFAULT_ROWS)

    # Contents ------------------------------------------------------------

    def set_rows(self, count, row, widths=None):
        """Show new rows: row(index) returns the Row for index; nothing is selected.

        widths, {column id: pixels}, changes the widths of columns at the same time.
        """
        self.count, self.row = count, row
        self.top, self.selected, self._keep = 0, None, None
        self.body.xview_moveto(0)
        if widths:
            for column in self.columns:
                if column.id in widths:
                    column.base = max(px(self, MIN_WIDTH), int(widths[column.id]))
                    column.dragged = False
            self._fit_columns()
            self._layout()
        else:
            self.refresh()

    def clear(self):
        self.set_rows(0, None)

    def refresh(self):
        """Draw the rows on the screen again (after their contents changed)."""
        self.top = max(0, min(self.top, self.count - self.page))
        shown = 0
        for place, items in enumerate(self.slots):
            index = self.top + place
            if index < self.count:
                self._draw(place, items, index, self.row(index))
                shown += 1
            elif self._shown[place] is not HIDDEN:
                for item in items + [self._rules[place]]:
                    self.body.itemconfigure(item, state="hidden")
                self._drop_edges(place)
                self._shown[place] = HIDDEN
        bottom = shown * self.row_height
        for x, line in zip(self._borders(), self._lines):
            self.body.coords(line, x, 0, x + self._ring, bottom)
        place = None if self.selected is None else self.selected - self.top
        frame = (place, self._full_width()) if place is not None and 0 <= place < shown else None
        if frame != self._framed:
            self._framed = frame
            if frame is None:
                self.body.itemconfigure(self._frame, state="hidden")
            else:
                y = place * self.row_height
                self.body.coords(self._frame, 1, y + 1, frame[1] - 2, y + self.row_height - 1)
                self.body.itemconfigure(self._frame, state="normal")
        self._set_bars()

    def _draw(self, place, items, index, row):
        # A selected row is filled with the selection colour, except one with marks: a mark
        # that is on stays black, and the frame shows the selection.
        filled = index == self.selected and not row.background and not self._has_marks(row)
        stripe = STRIPE if self.stripes and index % 2 == 0 else WHITE
        background = row.background or (self.select_background if filled else stripe)
        foreground = self.select_foreground if filled else TEXT
        key = (index, row.cells, background, foreground, tuple(row.cell_backgrounds.items()),
               row.tip)
        if self._tip_item == ("row", index) and row.tip != self._row_tip:
            self._hide_tip()                    # it would tell about the row as it was
        if self._shown[place] == key:
            return
        self._shown[place] = key
        body = self.body
        body.itemconfigure(items[0], fill=background, state="normal")
        body.itemconfigure(self._rules[place], state="normal")
        marks_at, x0 = 1 + 2 * len(self.columns), 0
        self._drop_edges(place)
        span = None                     # the columns (from, to) the row's own colour shows in
        for k, (column, text) in enumerate(zip(self.columns, row.cells)):
            cell, item = items[1 + 2 * k], items[2 + 2 * k]
            colour = row.cell_backgrounds.get(column.id)
            if colour:
                self._raise_edges(place, x0, x0 + column.width, colour)
            elif not filled:            # a column that does not show the row's own colour
                if column.shade == PLAIN:
                    colour = WHITE
                elif column.shade == STRIPED and row.background:
                    colour = stripe
            if row.background and not colour:
                span = (span[0] if span else x0, x0 + column.width)
            body.itemconfigure(cell, fill=colour or "", state="normal" if colour else "hidden")
            if column.checkbox:
                show_checkbox(body, self._boxes[item], text)
            elif column.marks:
                body.itemconfigure(item, state="hidden")
                self._draw_marks(items[marks_at:marks_at + column.marks], x0, column.width,
                                 place, text, TEXT if colour else foreground,
                                 off_colour(colour or background))
            else:
                body.itemconfigure(item, text=self._fit_text(text, column),
                                   fill=TEXT if colour else foreground, state="normal")
            marks_at += column.marks
            x0 += column.width
        if span is not None and row.background not in (WHITE, STRIPE):
            self._raise_edges(place, *span, row.background)

    def _raise_edges(self, place, x0, x1, colour):
        """Raise a highlight of a row place from x0 to x1 by a thin crisp edge, lit at its top
        and left sides and shaded at its bottom and right sides, inside the grid lines."""
        ring, body = self._ring, self.body
        y0 = place * self.row_height
        x1, y1 = x1 - ring, y0 + self.row_height - ring
        lit, shaded = edges(colour)
        items = self._raised.setdefault(place, [])
        for fill, box in ((lit, (x0, y0, x1, y0 + ring)), (lit, (x0, y0, x0 + ring, y1)),
                          (shaded, (x0, y1 - ring, x1, y1)), (shaded, (x1 - ring, y0, x1, y1))):
            items.append(body.create_rectangle(*box, fill=fill, width=0, tags=("edge",)))
        body.tag_lower("edge", "line")

    def _drop_edges(self, place):
        """Take away the edges of the highlights of a row place."""
        items = self._raised.pop(place, None)
        if items:
            self.body.delete(*items)

    def _draw_marks(self, items, x0, width, place, marks, foreground, off):
        """Draw the marks of a cell of a column from x0, width wide, each with its own item.

        Marks that do not fit in the column are not drawn.
        """
        body = self.body
        y = place * self.row_height + self.row_height // 2
        spans = self._mark_spans(x0, width, marks)
        for k, item in enumerate(items):
            if k >= len(marks) or spans[k] is None:
                if item == self._tip_item:
                    self._hide_tip()
                body.itemconfigure(item, state="hidden")
                self._tips.pop(item, None)
                continue
            mark = marks[k]
            body.coords(item, spans[k][0], y)
            body.itemconfigure(item, text=mark.text, fill=foreground if mark.on else off,
                               state="normal")
            if self._tips.get(item) != mark.tip and item == self._tip_item:
                self._hide_tip()                # it would tell about another mark
            self._tips[item] = mark.tip

    def _mark_spans(self, x0, width, marks):
        """(left, right) of each mark of a cell of a column from x0, width wide.

        None for a mark that does not fit in the column, and for those after it.
        """
        spans, x, end = [], x0 + self._pad, x0 + width - self._pad
        for mark in marks:
            if mark.space:
                x += self.font.measure(" ")
            right = x + self.font.measure(mark.text)
            spans.append((x, right) if right <= end and (not spans or spans[-1]) else None)
            x = right
        return spans

    def _has_marks(self, row):
        return any(column.marks and cell for column, cell in zip(self.columns, row.cells))

    def mark_box(self, index, column_id, number):
        """(x0, y0, x1, y1) of mark number of a cell of a row on the screen in the body's canvas."""
        box = self.cell_box(index, column_id)
        if box is None:
            return None
        k = [column.id for column in self.columns].index(column_id)
        marks = self.row(index).cells[k]
        if not 0 <= number < len(marks):
            return None
        span = self._mark_spans(box[0], self.columns[k].width, marks)[number]
        return None if span is None else (span[0], box[1], span[1], box[3])

    def _mark_at(self, index, column_id, x):
        """The number of the mark of a row's cell at x of the body's canvas, or None."""
        for k, column in enumerate(self.columns):
            if column.id == column_id and column.marks:
                box = self.cell_box(index, column_id)
                if box is None:
                    return None
                spans = self._mark_spans(box[0], column.width, self.row(index).cells[k])
                return next((n for n, span in enumerate(spans)
                             if span is not None and span[0] <= x < span[1]), None)
        return None

    # Tooltips of marks ---------------------------------------------------

    def _mark_entered(self, event):
        self._hide_tip()
        current = self.body.find_withtag("current")
        tip = self._tips.get(current[0]) if current else None
        if tip:
            self._tip_item = current[0]
            self._tip_job = self.after(TOOLTIP_DELAY, self._show_tip)

    def _row_motion(self, event):
        """The mouse moves over the rows: a row with a tooltip shows it after a rest.

        Over a mark, the mark's own tooltip shows instead.
        """
        current = self.body.find_withtag("current")
        if current and self._tips.get(current[0]):
            return
        index = self.index_at(event.y)
        if index == self._motion_row:
            return
        if isinstance(self._tip_item, tuple):
            self._hide_tip()                    # another row now, or none
        self._motion_row = index
        tip = self.row(index).tip if index is not None else ""
        if tip and self._tip_item is None:
            self._tip_item, self._row_tip = ("row", index), tip
            self._tip_job = self.after(TOOLTIP_DELAY, self._show_tip)

    def _show_tip(self):
        self._tip_job = None
        item = self._tip_item
        if isinstance(item, tuple):             # a row's: below the row, at its left
            box, text = self.cell_box(item[1], self.columns[0].id), self._row_tip
        else:
            box = self.body.bbox(item) if item is not None else None
            text = self._tips.get(item, "")
        if box is None or self._tip is not None or not self.body.winfo_ismapped():
            return
        x = self.body.winfo_rootx() + box[0] - int(self.body.canvasx(0))
        y = self.body.winfo_rooty() + box[3] - int(self.body.canvasy(0))
        self._tip = tip_window(self.body, text, x, y)

    def _hide_tip(self, event=None):
        if self._tip_job is not None:
            self.after_cancel(self._tip_job)
            self._tip_job = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None
        self._tip_item = None
        self._motion_row = None                 # the row under the mouse may show its own again

    def _fit_text(self, text, column):
        """text, or as much of it as fits in a cell of column followed by an ellipsis."""
        room = column.width - 2 * self._pad
        if column.font is not None:
            return _cut(text, room, column.font)
        if self._fixed and text.isascii():      # every character as wide as "0"
            fits = max(0, room // self._char)
            return text if len(text) <= fits else text[:fits - 1] + ELLIPSIS if fits else ""
        return _cut(text, room, self.font)

    # Selection and scrolling ---------------------------------------------

    def select(self, index, center=False):
        """Select a row (None for none) and scroll it into view; center puts it mid-screen."""
        self.selected = index
        top = self.top
        if index is not None:
            self._keep = (index, center)
            self.top = self._top_showing(index, center)
        self.refresh()
        if self.top != top:
            self._scrolled()

    def see(self, index, center=False):
        """Scroll as little as needed to show a row wholly, or to the middle with center.

        The row stays in view when the table's size changes, until the user scrolls.
        """
        if 0 <= index < self.count:
            self._keep = (index, center)
        self._scroll(self._top_showing(index, center))

    def _top_showing(self, index, center):
        """The top row that shows row index wholly (the current one if it does)."""
        if not 0 <= index < self.count or self.top <= index < self.top + self.page:
            return self.top
        if center:
            return index - (self.page - 1) // 2
        return index if index < self.top else index - self.page + 1

    def scroll_to(self, top):
        """Show the rows from top (the user scrolled: no row is kept in view any more)."""
        self._keep = None
        self._scroll(top)

    def _scroll(self, top):
        top = max(0, min(top, self.count - self.page))
        if top != self.top:
            self.top = top
            self.refresh()
            self._scrolled()

    def _scrolled(self):
        self._hide_tip()
        if self.on_scroll is not None:
            self.on_scroll()

    def cell_box(self, index, column_id):
        """(x0, y0, x1, y1) of a cell of a row on the screen in the body's canvas, or None."""
        place = index - self.top
        if not 0 <= place < len(self.slots) or index >= self.count:
            return None
        x0 = 0
        for column in self.columns:
            if column.id == column_id:
                y0 = place * self.row_height
                return x0, y0, x0 + column.width, y0 + self.row_height
            x0 += column.width
        return None

    def yview(self, *args):
        """The scroll bar's commands: moveto fraction, or scroll n units or pages."""
        if not args:
            return self._fractions()
        if args[0] == "moveto":
            self.scroll_to(round(float(args[1]) * self.count))
        elif args[0] == "scroll":
            step = self.page if args[2] == "pages" else 1
            self.scroll_to(self.top + int(args[1]) * step)
        return None

    def xview(self, *args):
        self.body.xview(*args)
        self._scrolled()

    def _fractions(self):
        if self.count <= self.page:
            return 0.0, 1.0
        return self.top / self.count, min(1.0, (self.top + self.page) / self.count)

    def _set_bars(self):
        """Set the scroll bars: each shows only while the rows or the columns do not fit.

        Both are decided at once from the room of the body and the bars,
        the rows by whole rows and the columns by what each needs (a dragged
        one its width). Until the table knows its width, the vertical bar
        shows while the rows do not all fit its height, and the horizontal
        one shows.
        """
        self.vscroll.set(*self._fractions())
        if self._available:
            least = sum(column.base for column in self.columns)
            vertical, horizontal = bars_needed(
                lambda height: self.count <= max(1, height // self.row_height),
                lambda width: least <= width,
                self._room_width, self._room_height,
                (self.vscroll.winfo_reqwidth(), self.hscroll.winfo_reqheight()))
        else:
            vertical, horizontal = self.count > self.page, self._total_width() > self._available
        if vertical != self._vscroll_shown:
            self._vscroll_shown = vertical
            show_bar(self.vscroll, vertical)
        if horizontal != self._hscroll_shown:
            self._hscroll_shown = horizontal
            show_bar(self.hscroll, horizontal)
            if not horizontal:
                self.body.xview_moveto(0)
                self.header.xview_moveto(0)

    def _xscrolled(self, first, last):
        self.hscroll.set(first, last)
        self.header.xview_moveto(first)

    def move_selection(self, rows):
        """Move the selected row by rows (the top row is selected first if none is)."""
        if not self.count:
            return
        start = self.top if self.selected is None else self.selected + rows
        self.select(max(0, min(start, self.count - 1)))

    # Size and columns ----------------------------------------------------

    def fit(self, height):
        """Take the rows place for a body of the given height in pixels.

        A row asked for with see() or select() stays in view.
        """
        self._set_room(height=height)
        self._fit(height)

    def _fit(self, height):
        page = max(1, height // self.row_height)
        slots = page + (1 if height % self.row_height else 0)
        before = (self.top, len(self.slots))
        self.page = page
        while len(self.slots) < slots:
            self._add_slot()
        while len(self.slots) > slots:
            for item in self.slots.pop() + [self._rules.pop()]:
                self.body.delete(item)
                self._boxes.pop(item, None)
            self._shown.pop()
            self._drop_edges(len(self.slots))
        if self._keep is not None:
            self.top = self._top_showing(*self._keep)
        self._set_region()
        self.refresh()
        if (self.top, len(self.slots)) != before:
            self._scrolled()

    def fill(self, width):
        """Fit the columns to a body of the given width in pixels (its width on the screen)."""
        self._set_room(width=width)
        self._fill(width)

    def _fill(self, width):
        self._available = max(0, int(width))
        if self._fit_columns():
            self._layout()
        else:
            self._set_region()

    def _set_room(self, width=None, height=None):
        """Keep the room of the body and its scroll bars: the body's size and the bars shown."""
        if width is not None:
            self._room_width = max(0, int(width)) + (
                self.vscroll.winfo_reqwidth() if self._vscroll_shown else 0)
        if height is not None:
            self._room_height = max(0, int(height)) + (
                self.hscroll.winfo_reqheight() if self._hscroll_shown else 0)

    def set_width(self, column_id, width):
        """Make a column's contents need the given number of pixels.

        That is its width, or the least it gets when it stretches.
        """
        for column in self.columns:
            if column.id == column_id:
                column.base = max(px(self, MIN_WIDTH), int(width))
                column.dragged = False
        self._fit_columns()
        self._layout()

    def _resize(self, k, width):
        """Column k dragged to the given width: it keeps that width from now on."""
        column = self.columns[k]
        column.base = max(px(self, MIN_WIDTH), int(width))
        column.dragged = column.stretch
        self._fit_columns()
        self._layout()

    def _fit_columns(self):
        """Give each column its width for the body's width; True when a width changed.

        The stretching columns not resized by hand share the width the others
        leave in equal parts, except that a column whose contents need more
        than its part keeps what it needs; the last columns take the pixels
        left over by the division.
        """
        before = [column.width for column in self.columns]
        pool = [column for column in self.columns if column.stretch and not column.dragged]
        sharing = {column.id for column in pool}
        room = self._available
        for column in self.columns:
            if column.id not in sharing:
                column.width = column.base
                room -= column.width
        pool.sort(key=lambda column: column.base, reverse=True)
        while pool and pool[0].base * len(pool) > room:
            column = pool.pop(0)
            column.width = column.base
            room -= column.width
            sharing.discard(column.id)
        if sharing:
            share, extra = divmod(room, len(sharing))
            ordered = [column for column in self.columns if column.id in sharing]
            for k, column in enumerate(ordered):
                column.width = share + (k >= len(ordered) - extra)
        return [column.width for column in self.columns] != before

    def set_heading(self, column_id, heading):
        for column in self.columns:
            if column.id == column_id:
                column.heading = heading
        self._layout()

    def _add_slot(self):
        place = len(self.slots)
        y = place * self.row_height
        body = self.body
        items = [body.create_rectangle(0, y, 0, y + self.row_height, width=0, fill=WHITE,
                                       state="hidden", tags=("row",))]
        boxes = []
        for column in self.columns:
            items.append(body.create_rectangle(0, y, 0, y, width=0, state="hidden",
                                               tags=("cell",)))
            if column.checkbox:                 # its inside in the text's place
                boxes.append(draw_checkbox(body, tags=("text",)))
                items.append(boxes[-1][0])
            else:
                items.append(body.create_text(0, 0, anchor=column.anchor,
                                              font=column.font or self.font, fill=TEXT,
                                              state="hidden", tags=("text",)))
        for column in self.columns:             # after the others: their places stay the same
            items += [body.create_text(0, 0, anchor="w", font=self.font, fill=TEXT,
                                       state="hidden", tags=("text", "mark"))
                      for _ in range(column.marks)]
        for box in boxes:                       # the rest of each checkbox, last
            self._boxes[box[0]] = box
            items += box[1:]
        self.slots.append(items)
        self._rules.append(body.create_rectangle(0, 0, 0, 0, fill=GRID, width=0, state="hidden",
                                                 tags=("line",)))
        self._shown.append(HIDDEN)
        self._place_slot(place, items)
        self._stack()

    def _stack(self):
        """Put the canvas items in their drawing order: rows, cells, edges, lines, frame, texts."""
        body = self.body
        if self.slots:                          # "row" must name an item
            body.tag_raise("cell", "row")
        body.tag_raise("edge")
        body.tag_raise("line")
        body.tag_raise("frame")
        body.tag_raise("text")

    def _place_slot(self, place, items):
        y0 = place * self.row_height
        y1 = y0 + self.row_height
        middle = y0 + self.row_height // 2
        body = self.body
        body.coords(items[0], 0, y0, self._full_width(), y1)
        body.coords(self._rules[place], 0, y1 - self._ring, self._full_width(), y1)
        x0 = 0
        for k, column in enumerate(self.columns):
            x1 = x0 + column.width
            body.coords(items[1 + 2 * k], x0, y0, x1 - self._ring, y1)
            if column.checkbox:
                size = checkbox_size(body)
                place_checkbox(body, self._boxes[items[2 + 2 * k]], (x0 + x1 - size) // 2,
                               middle - size // 2)
                x0 = x1
                continue
            if column.anchor == "center":
                x = (x0 + x1) // 2
            elif column.anchor == "e":
                x = x1 - self._pad
            else:
                x = x0 + self._pad
            body.coords(items[2 + 2 * k], x, middle)
            x0 = x1

    def _borders(self):
        """x of the line at the right of each column."""
        x, borders = 0, []
        for column in self.columns:
            x += column.width
            borders.append(x - self._ring)
        return borders

    def _total_width(self):
        return sum(column.width for column in self.columns)

    def _full_width(self):
        """The width of the rows: the columns', or the body's when that is wider."""
        return max(self._total_width(), self._available)

    def _layout(self):
        """Draw the headings and grid lines and place every row's items for the column widths."""
        header, body = self.header, self.body
        header.delete("all")
        height = int(header.cget("height"))
        x0 = 0
        for column in self.columns:
            x1 = x0 + column.width
            draw_bevel(header, x0, 0, x1, height)       # a raised heading button
            header.create_text((x0 + x1) // 2, height // 2, anchor="center",
                               text=_cut(column.heading, column.width - 2 * self._pad,
                                         self.heading_font),
                               font=self.heading_font, fill=HEADING_TEXT)
            x0 = x1
        for line in self._lines:
            body.delete(line)
        self._lines = [body.create_rectangle(x, 0, x + self._ring, 0, fill=GRID, width=0,
                                             tags=("line",)) for x in self._borders()]
        self._stack()
        for place, items in enumerate(self.slots):
            self._place_slot(place, items)
        self._shown = [None] * len(self.slots)       # texts are cut to the new widths
        self._set_region()
        self.refresh()
        self._scrolled()

    def _set_region(self):
        """Scroll the rows and headings over the full width, never less than the body's.

        A region narrower than the canvas would let the rows slide sideways
        away from their headings. The horizontal scroll bar shows only while
        the columns do not fit.
        """
        full = self._full_width()
        height = max(1, len(self.slots)) * self.row_height
        self.body.configure(scrollregion=(0, 0, full, height))
        self.header.configure(scrollregion=(0, 0, full, int(self.header.cget("height"))))
        for items, rule in zip(self.slots, self._rules):
            x0, y0, _, y1 = self.body.coords(items[0])
            self.body.coords(items[0], x0, y0, full, y1)
            self.body.coords(rule, 0, y1 - self._ring, full, y1)
        self._set_bars()

    # Mouse and keys --------------------------------------------------------

    def _bind_events(self):
        body, header = self.body, self.header
        body.bind("<Configure>", self._configured)
        body.bind("<ButtonPress-1>", self._press)
        body.bind("<Double-ButtonPress-1>", self._double)
        body.tag_bind("mark", "<Enter>", self._mark_entered)
        body.tag_bind("mark", "<Leave>", self._hide_tip)
        body.bind("<Motion>", self._row_motion)
        body.bind("<Leave>", self._hide_tip)
        for button in (2, 3):                           # the first button: _press
            body.bind(f"<ButtonPress-{button}>", self._hide_tip)
        body.bind("<Destroy>", self._hide_tip, add="+")
        for widget in (body, header):
            if widget._windowingsystem == "x11":
                widget.bind("<Button-4>", lambda e: self._wheel_rows(-WHEEL_ROWS))
                widget.bind("<Button-5>", lambda e: self._wheel_rows(WHEEL_ROWS))
                widget.bind("<Shift-Button-4>", lambda e: self._wheel_columns(-1))
                widget.bind("<Shift-Button-5>", lambda e: self._wheel_columns(1))
            else:
                widget.bind("<MouseWheel>", self._mouse_wheel)
                widget.bind("<Shift-MouseWheel>", self._mouse_wheel)
        for key, rows in (("Up", -1), ("Down", 1)):
            body.bind(f"<Key-{key}>", lambda e, n=rows: self._key(self.move_selection, n))
        body.bind("<Key-Prior>", lambda e: self._page(-1))
        body.bind("<Key-Next>", lambda e: self._page(1))
        for key in ("Home", "Control-Home"):
            body.bind(f"<{key}>", lambda e: self._key(self.select, 0))
        for key in ("End", "Control-End"):
            body.bind(f"<{key}>", lambda e: self._key(self.select, self.count - 1))
        body.bind("<Key-Left>", lambda e: self._key(self._wheel_columns, -1))
        body.bind("<Key-Right>", lambda e: self._key(self._wheel_columns, 1))
        for key in ("Return", "KP_Enter", "F2"):
            body.bind(f"<Key-{key}>", self._activate)
        header.bind("<Motion>", self._heading_motion)
        header.bind("<Leave>", lambda e: header.configure(cursor=""))
        header.bind("<ButtonPress-1>", self._heading_press)
        header.bind("<B1-Motion>", self._heading_drag)
        header.bind("<ButtonRelease-1>", self._heading_release)

    def _configured(self, event):
        # The room in both directions, measured with the bars as they are before either is
        # decided again.
        self._set_room(event.width, event.height)
        self._fill(event.width)
        self._fit(event.height)

    def _key(self, action, *args):
        if self.count:
            action(*args)
        return "break"

    def _activate(self, event=None):
        """Enter or F2: the selected row is to be acted on (a register's value changed)."""
        if self.selected is not None and self.on_activate is not None:
            self.on_activate(self.selected)
        return "break"

    def _page(self, direction):
        if self.count:
            if self.selected is None:
                self.scroll_to(self.top + direction * self.page)
            else:
                self.move_selection(direction * self.page)
        return "break"

    def index_at(self, y):
        """The row at height y of the body (window pixels), or None."""
        if y < 0:
            return None
        index = self.top + int(y) // self.row_height
        return index if index < min(self.count, self.top + len(self.slots)) else None

    def column_at(self, x):
        """The id of the column at x of the body (window pixels), or None."""
        x = self.body.canvasx(x)
        left = 0
        for column in self.columns:
            if left <= x < left + column.width:
                return column.id
            left += column.width
        return None

    def _press(self, event):
        self._hide_tip()
        self.body.focus_set()
        index = self._clicked = self.index_at(event.y)
        if index is not None:
            self.select(index)
            if self.on_click is not None:
                self.on_click(index, self.column_at(event.x))
        return "break"

    def _double(self, event):
        # The first click may have scrolled a partly shown row into view, so the
        # row under the mouse now is not the one clicked.
        index = self._clicked if self._clicked is not None else self.index_at(event.y)
        if index is None:
            return "break"
        column = self.column_at(event.x)
        mark = self._mark_at(index, column, self.body.canvasx(event.x))
        if mark is not None and self.on_mark is not None:
            self.on_mark(index, column, mark)
        elif self.on_double_click is not None:
            self.on_double_click(index, column)
        return "break"

    def _mouse_wheel(self, event):
        sideways = event.state & 1              # Shift
        if is_aqua(self):
            steps = -event.delta                # one row (or unit) per unit, as Tk's own lists
        else:
            way = "x" if sideways else "y"
            self._wheel[way] -= event.delta * (1 if sideways else WHEEL_ROWS)
            steps = int(self._wheel[way] / WHEEL_NOTCH)     # whole steps: a smooth wheel adds up
            self._wheel[way] -= steps * WHEEL_NOTCH
        return self._wheel_columns(steps) if sideways else self._wheel_rows(steps)

    def _wheel_rows(self, rows):
        if rows:
            self.scroll_to(self.top + rows)
        return "break"

    def _wheel_columns(self, units):
        if units:
            self.body.xview_scroll(units, "units")
            self._scrolled()
        return "break"

    def _border_at(self, x):
        """The column whose right border is at x of the header (window pixels), or None."""
        x = self.header.canvasx(x)
        grab = px(self, GRAB)
        borders = self._borders()
        if self.columns and self.columns[-1].stretch:
            borders.pop()                       # the last column ends where the table does
        for k, border in enumerate(borders):
            if abs(x - border) <= grab:
                return k
        return None

    def _heading_motion(self, event):
        resize = self._drag is not None or self._border_at(event.x) is not None
        self.header.configure(cursor="sb_h_double_arrow" if resize else "")

    def _heading_press(self, event):
        k = self._border_at(event.x)
        if k is not None:
            self._drag = (k, event.x, self.columns[k].width)
            self._pressed = None
        else:
            self._drag = None
            self._pressed = self._heading_at(event.x)
        return "break"

    def _heading_drag(self, event):
        if self._drag is not None:
            k, start, width = self._drag
            self._resize(k, width + event.x - start)
        return "break"

    def _heading_release(self, event):
        drag, pressed = self._drag, self._pressed
        self._drag = self._pressed = None
        on_heading = 0 <= event.y < int(self.header.cget("height"))
        if (drag is None and pressed is not None and on_heading
                and pressed == self._heading_at(event.x) and self.on_heading is not None):
            self.on_heading(pressed)
        self._heading_motion(event)
        return "break"

    def _heading_at(self, x):
        x = self.header.canvasx(x)
        left = 0
        for column in self.columns:
            if left <= x < left + column.width:
                return column.id
            left += column.width
        return None


def _cut(text, room, font):
    """text, or as much of it as fits in room pixels of font followed by an ellipsis."""
    if font.measure(text) <= room:
        return text
    room -= font.measure(ELLIPSIS)
    low, high = 0, len(text)            # text[:low] fits, text[:high + 1] does not
    while low < high:
        middle = (low + high + 1) // 2
        if font.measure(text[:middle]) <= room:
            low = middle
        else:
            high = middle - 1
    return text[:low] + ELLIPSIS if room >= 0 else ""
