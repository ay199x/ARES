# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Tools > Bitmap Display: a part of memory shown as a picture, each word a unit of colour.

The words from the base address fill the display row by row from its top
left, each one a block of unit width x unit height pixels in the colour of
its value, 0x00RRGGBB. While the tool is connected the display shows the
words as memory holds them: at every refresh of the window (each slice of a
run, Step, Backstep, Reset, a register change) and when a program is
loaded, the model reads them and notes the rows that differ, and the window
draws those rows. No hook is added to the emulator: the instructions run as
fast as without the tool, and words written by system calls or put back by
Backstep and Reset show as well, which no hook of the emulator sees. A large
display takes a while to read and draw, so while the program runs the
window skips refreshes to keep that to a quarter of the time at most.
"""

import re
import time
import tkinter as tk
from tkinter import ttk

from ...machine import DDR_END
from ...runner import State
from ..places import gray_unavailable, list_width, place_text, put_back
from ..style import sunken
from ..widgets import Tooltip, bars_needed, px, scale, show_bar
from .frame import ToolModel, ToolWindow

UNIT_SIZES = (1, 2, 4, 8, 16, 32)               # a unit's width or height, in pixels
DISPLAY_SIZES = (64, 128, 256, 512, 1024)       # the display's width or height, in pixels
DATA, HEAP = ".data", "heap"                    # the places a display can start at
PLACES = (DATA, HEAP)
# The settings as the window shows them: the model's attribute, label, choices and tooltip.
SIZES = (
    ("unit_width", "Unit Width in Pixels:", UNIT_SIZES, "The width of a unit, which shows a word"),
    ("unit_height", "Unit Height in Pixels:", UNIT_SIZES,
     "The height of a unit, which shows a word"),
    ("width", "Display Width in Pixels:", DISPLAY_SIZES, "The width of the whole display"),
    ("height", "Display Height in Pixels:", DISPLAY_SIZES, "The height of the whole display"),
)
BASE_LABEL = "Base address for display:"
BASE_TIP = "The word at the top left: .data, heap, or an address typed here (then Enter)"
RESET_TIP = "Draw the display again from memory (black while it is not connected)"
ROOM = (0.6, 0.7)               # the most of the screen's width and height the display takes
MANY_BANDS = 16                 # more runs of changed rows than this are drawn as one
REFRESH_SHARE = 0.25            # the most of a run's time that refreshing the display takes
_ADDRESS = re.compile(r"0[xX][0-9a-fA-F]+|[0-9]+", re.ASCII)

HELP = """\
The Bitmap Display shows a part of memory as a picture: each word is one unit of the
display, drawn in the colour its value gives.

Click Connect to ARM, then run the program (Go, Step): the display shows the words as
memory holds them, also while the program runs at full speed. Disconnect from ARM stops
following the program; the picture stays. Close closes the tool.

Colours: a word's value is 0x00RRGGBB, with red in bits 23-16, green in bits 15-8 and
blue in bits 7-0; bits 31-24 do not matter. 0x00FF0000 is red, 0x0000FF00 green,
0x000000FF blue, 0x00FFFF00 yellow, 0x00FFFFFF white and 0 black.

Units: the word at the base address is the unit at the top left, the word 4 bytes on is
the unit to its right, and so on to the end of the row; the next row goes on with the
next word. With N units across, the unit in row r and column c (both counted from 0)
shows the word at the base address + 4 x (N x r + c).

Unit Width in Pixels and Unit Height in Pixels: the size of a unit. Display Width in
Pixels and Display Height in Pixels: the size of the whole display. The display is
(display width / unit width) units across and (display height / unit height) units
down: 512 x 256 pixels in units of 1 x 1 pixel are 512 x 256 units, 131,072 words
(512 KB); in units of 8 x 8 pixels they are 64 x 32 units, 2,048 words.

Base address for display: where the words start. .data is the start of the program's
data (its first section that is not code); heap is the first word after the program,
where the memory that SVC #9 hands out begins. While a program is loaded the list shows
their addresses in it, and the display follows them when another program is assembled.
While no program is assembled the list shows them gray, with "no program assembled"
instead of an address, and they cannot be chosen. Or type an address, also without a
program: 0x and hexadecimal digits or decimal digits, and press Enter: a multiple of 4,
with the whole display inside the DDR3 memory (0x00000000 to 0x3FFFFFFF). A wrong address
rings the bell and the old one stays. With a typed address, a display size that would
reach past the DDR3 memory rings the bell too and the old size stays.

What the display shows: while the tool is connected, the words as memory holds them
after each step, during a run (up to about 30 times a second, see Speed), when the run
stops, and after Backstep, Reset (F12) and Assemble: also words that system calls write
(SVC #8 reading a string, for example), words Backstep puts back and the program's first
values after Reset or Assemble. The tool stays connected when the program is assembled
again or its file is closed; while no program is loaded the picture stays as it is.
While the tool is not connected the picture stays too, and a change of a setting makes
the display black.

The tool's Reset button draws the display again: from memory while the tool is connected
to a program, else black.

On a scaled screen each pixel of the display is a square of whole screen pixels, as near
to the screen's scale as whole pixels allow (2 x 2 at 200 % and 225 %), so the display
keeps about its size and its units stay sharp. A display that would then not fit on the
screen is drawn with fewer screen pixels per pixel, and with scroll bars when even one
screen pixel per pixel does not fit.

Speed: the tool adds nothing to the instructions themselves. It reads the display's
words when the window shows the program's state and draws only the rows that changed.
A small display costs next to nothing. A large one takes longer (a display of 1024 x 1024
units has 4 MB to read, and a million pixels to draw when all of it changes), so while
the program runs the tool skips refreshes until reading and drawing take a quarter of the
time at most: the program runs at least three quarters as fast as without the tool, and
the display still follows it a few times a second.
"""


def parse_address(text):
    """A typed address: 0x and hexadecimal digits, or decimal digits; None if it is neither."""
    text = text.strip()
    if _ADDRESS.fullmatch(text) is None:
        return None
    hexadecimal = text[:2] in ("0x", "0X")
    digits = (text[2:] if hexadecimal else text).lstrip("0")
    if len(digits) > 10:                # far beyond any address; Python refuses huge numbers
        return None
    return int(digits or "0", 16 if hexadecimal else 10)


def fits(address, size):
    """True when size bytes from address start at a word and lie in DDR3 memory."""
    return address % 4 == 0 and 0 <= address and address + size <= DDR_END


def data_start(program):
    """Where the program's data starts: its first section that is not code, else its end."""
    start = next((s.address for s in program.sections if not s.executable), None)
    if start is None:
        start = (max((s.end for s in program.sections), default=0) + 3) & ~3
    return start


def place_address(place, machine):
    """The address of a place (DATA or HEAP) in the program of machine."""
    return data_start(machine.program) if place == DATA else machine.heap_start


def zoom(scale, width, height, room_width, room_height):
    """Screen pixels per pixel of a display of width x height pixels.

    The interface's scale rounded to whole pixels, so the units stay sharp,
    and less while the display would not fit in room_width x room_height;
    at least 1.
    """
    factor = max(1, round(scale))
    while factor > 1 and (width * factor > room_width or height * factor > room_height):
        factor -= 1
    return factor


def bands(rows, most=MANY_BANDS):
    """The runs of consecutive numbers in sorted rows, as (first, end) with end excluded.

    More than most runs become one, from the first row to the last.
    """
    runs = []
    for row in rows:
        if runs and runs[-1][1] == row:
            runs[-1][1] = row + 1
        else:
            runs.append([row, row + 1])
    if len(runs) > most:
        return [(runs[0][0], runs[-1][1])]
    return [tuple(run) for run in runs]


def ppm(words, columns, across, down):
    """A binary PPM picture of words, columns of them in a row, each a block of across x
    down pixels in its colour.

    words are 4 bytes each, as memory holds a value 0x00RRGGBB: blue, green,
    red, then a byte that does not matter.
    """
    count = len(words) // 4
    rows = count // columns
    rgb = bytearray(3 * count)
    for channel, offset in enumerate((2, 1, 0)):
        rgb[channel::3] = words[offset::4]
    if across > 1:
        channels = [rgb[channel::3] for channel in range(3)]
        rgb = bytearray(len(rgb) * across)
        for k in range(across):
            for channel, values in enumerate(channels):
                rgb[3 * k + channel::3 * across] = values
    if down > 1:
        line = 3 * columns * across
        rgb = b"".join(rgb[start:start + line] * down for start in range(0, len(rgb), line))
    return b"P6\n%d %d\n255\n" % (columns * across, rows * down) + rgb


class BitmapModel(ToolModel):
    """The words of a bitmap display, and the rows of it that changed.

    The display is width x height pixels, in units of unit_width x
    unit_height pixels: columns x rows units, one word each. base is where
    its words start: DATA, HEAP (places in the program observed) or an
    address. words holds them, 4 bytes each as in memory, row by row: as
    memory holds them while a program is observed; else what they were
    when it was observed last, or zeros (black) after a change of the
    settings or reset(). Nothing of it survives closing the window: a new
    window starts with the defaults.
    """

    def __init__(self):
        super().__init__()
        self.unit_width = self.unit_height = 1
        self.width, self.height = 512, 256
        self.base = DATA
        self.words = b""
        self._changed = set()           # rows the window has not drawn since they changed
        self._start_again()

    @property
    def columns(self):
        return self.width // self.unit_width

    @property
    def rows(self):
        return self.height // self.unit_height

    @property
    def size(self):
        """The bytes the display shows."""
        return 4 * self.columns * self.rows

    def address(self):
        """The address of the display's first word; None for a place while no program is
        observed."""
        if not isinstance(self.base, str):
            return self.base
        return None if self.machine is None else place_address(self.base, self.machine)

    def color(self, column, row):
        """The colour 0xRRGGBB of the unit at column and row (both from 0)."""
        start = 4 * (row * self.columns + column)
        return int.from_bytes(self.words[start:start + 3], "little")

    # Settings ------------------------------------------------------------------

    def set_layout(self, unit_width, unit_height, width, height):
        """Show the display in these sizes, in pixels; False (nothing changes) when a typed
        base address would then reach past DDR3 memory."""
        if not isinstance(self.base, str):
            if not fits(self.base, 4 * (width // unit_width) * (height // unit_height)):
                return False
        layout = unit_width, unit_height, width, height
        if layout != (self.unit_width, self.unit_height, self.width, self.height):
            self.unit_width, self.unit_height, self.width, self.height = layout
            self._start_again()
        return True

    def set_base(self, base):
        """Start the display at base, DATA, HEAP or an address; False (nothing changes) for
        an address that is not a word or with which the display would reach past DDR3."""
        if not isinstance(base, str) and not fits(base, self.size):
            return False
        if base != self.base:
            self.base = base
            self._start_again()
        return True

    # Observing ----------------------------------------------------------------

    def attach(self, machine):
        self.update()

    def detach(self, machine):
        self.update()

    def reset(self):
        """Draw the display again: from memory while a program is observed, else black."""
        self._start_again()

    def update(self):
        if self.machine is None:
            return False
        words, old = self._read(), self.words
        if words == old:
            return False
        line = 4 * self.columns
        self._changed.update(row for row, start in enumerate(range(0, len(words), line))
                             if words[start:start + line] != old[start:start + line])
        self.words = words
        return True

    def take_changes(self):
        """The rows changed since the last call, in order."""
        rows, self._changed = sorted(self._changed), set()
        return rows

    def _start_again(self):
        """Every row anew: black, then what memory holds while a program is observed."""
        self.words = bytes(self.size)
        self._changed = set(range(self.rows))
        self.update()

    def _read(self):
        """The display's words as memory holds them now; zeros past the end of DDR3."""
        size, address = self.size, self.address()
        inside = max(0, min(size, DDR_END - address))
        words = self.machine.read_memory(address, inside) if inside else b""
        return words if inside == size else words + bytes(size - inside)


class BitmapWindow(ToolWindow):
    """Tools > Bitmap Display: the settings at the left, the display at their right.

    The display is one picture, made when the window opens and sized again
    when the display's size changes; the rows that changed are put into it
    as a few PPM pictures, never pixel by pixel.
    """

    NAME = "Bitmap Display"
    HELP = HELP
    MODEL = BitmapModel
    clock = staticmethod(time.perf_counter)

    def __init__(self, app):
        self.shown_size = None          # the display's size in pixels when the picture was sized
        self.factor = 1                 # screen pixels per pixel of the display
        self.next_refresh = 0.0         # while the program runs: the clock of the next refresh
        super().__init__(app)
        self.tips[self.reset_button].set_text(RESET_TIP)

    def refresh(self):
        """Show the words memory holds now. While the program runs, a refresh that took t
        keeps the next one away until t / REFRESH_SHARE after it began: a large display
        then slows the program down little, and still follows it."""
        start = self.clock()
        runner = self.app.runner
        if runner is not None and runner.state is State.RUNNING and start < self.next_refresh:
            return
        super().refresh()
        self.next_refresh = start + (self.clock() - start) / REFRESH_SHARE

    def build(self, body):
        gap, line = px(body, 6), px(body, 2)
        model = self.model
        self.places_machine = self.app.machine      # the machine whose places the list shows
        settings = ttk.Frame(body)
        settings.grid(row=0, column=0, sticky="nw")
        self.size_boxes = {}
        for row, (name, label, values, tip) in enumerate(SIZES):
            ttk.Label(settings, text=label).grid(row=row, column=0, sticky="w", pady=line)
            box = ttk.Combobox(settings, state="readonly", width=6, values=values)
            box.set(getattr(model, name))
            box.bind("<<ComboboxSelected>>", lambda event, name=name: self._size_chosen(name))
            box.grid(row=row, column=1, sticky="e", padx=(gap, 0), pady=line)
            self.size_boxes[name] = box
            Tooltip(box, tip)
        ttk.Label(settings, text=BASE_LABEL).grid(row=len(SIZES), column=0, sticky="w",
                                                  pady=line)
        # The field's text before its last change, and now: choosing a place that has no
        # address puts the first back.
        self.field_text = tk.StringVar(master=body)
        self._texts = ("", "")
        self._tracing = self.field_text.trace_add("write", self._text_changed)
        # Wide enough to show each place whole, also without a program.
        texts = [place_text(place, None) for place in PLACES] + [place_text(DATA, 0)]
        self.base_box = box = ttk.Combobox(settings, width=list_width(body, texts),
                                           textvariable=self.field_text,
                                           postcommand=self._list_opens)
        box.grid(row=len(SIZES), column=1, sticky="w", padx=(gap, 0), pady=line)
        box.bind("<<ComboboxSelected>>", self._place_chosen)
        for sequence in ("<Return>", "<KP_Enter>"):
            box.bind(sequence, self._address_entered)
        self.typed = (box,)
        box.bind("<FocusOut>", self._address_leaving, add="+")
        Tooltip(box, BASE_TIP)
        self._show_base()
        screen = sunken(tk.Frame(body))
        screen.grid(row=0, column=1, sticky="nw", padx=(2 * gap, 0))
        self.canvas = tk.Canvas(screen, background="#000000", borderwidth=0,
                                highlightthickness=0, takefocus=False)
        self.vbar = ttk.Scrollbar(screen, orient="vertical", command=self.canvas.yview)
        self.hbar = ttk.Scrollbar(screen, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=self.hbar.set, yscrollcommand=self.vbar.set)
        self.canvas.grid(row=0, column=0)
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar.grid(row=1, column=0, sticky="ew")
        self.image = tk.PhotoImage(master=self.canvas, width=1, height=1)
        self.canvas.create_image(0, 0, anchor="nw", image=self.image)

    def show(self):
        model = self.model
        if (model.width, model.height) != self.shown_size:
            self._size_picture()
        for first, end in bands(model.take_changes()):
            self._draw(first, end)

    def close(self):
        super().close()
        self.image = None               # the picture goes with its window
        if self._tracing is not None:   # Tcl would keep the window's object for the trace
            self.field_text.trace_remove("write", self._tracing)
            self._tracing = None

    def machine_changed(self, machine):
        self.places_machine = machine
        self._show_base()
        super().machine_changed(machine)

    # The display -------------------------------------------------------------------

    def _size_picture(self):
        """Size the picture and its canvas for the display: as large as the interface's
        scale makes it, if that fits the screen, with scroll bars if it does not."""
        model, window = self.model, self.window
        room_width = int(window.winfo_screenwidth() * ROOM[0])
        room_height = int(window.winfo_screenheight() * ROOM[1])
        self.factor = zoom(scale(window), model.width, model.height, room_width, room_height)
        width, height = model.width * self.factor, model.height * self.factor
        self.image.configure(width=width, height=height)
        thickness = (self.vbar.winfo_reqwidth(), self.hbar.winfo_reqheight())
        vertical, horizontal = bars_needed(lambda room: height <= room, lambda room: width <= room,
                                           room_width, room_height, thickness)
        self.canvas.configure(
            width=min(width, room_width - (thickness[0] if vertical else 0)),
            height=min(height, room_height - (thickness[1] if horizontal else 0)),
            scrollregion=(0, 0, width, height))
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        show_bar(self.vbar, vertical)
        show_bar(self.hbar, horizontal)
        self.shown_size = model.width, model.height

    def _draw(self, first, end):
        """Put the rows from first to end (excluded) into the picture."""
        model = self.model
        across, down = model.unit_width * self.factor, model.unit_height * self.factor
        line = 4 * model.columns
        data = ppm(model.words[first * line:end * line], model.columns, across, down)
        self.image.tk.call(self.image.name, "put", data, "-format", "ppm", "-to", 0, first * down)

    # The settings ------------------------------------------------------------------

    def _size_chosen(self, name):
        sizes = {key: int(box.get()) for key, box in self.size_boxes.items()}
        if not self.model.set_layout(**sizes):
            self.window.bell()
            self.size_boxes[name].set(getattr(self.model, name))
            return
        self.show()

    def _place_labels(self):
        """The list's texts for the places: with their addresses while a program is loaded,
        else saying that no program is assembled."""
        machine = self.places_machine
        return [place_text(place, None if machine is None else place_address(place, machine))
                for place in PLACES]

    def _list_opens(self):
        """The list opens: without a program its places are gray (they have no address)."""
        gray_unavailable(self.base_box, [self.places_machine is not None] * len(PLACES))

    def _text_changed(self, *args):
        self._texts = (self._texts[1], self.field_text.get())

    def _base_text(self):
        base = self.model.base
        if isinstance(base, str):
            return self._place_labels()[PLACES.index(base)]
        return f"0x{base:08x}"

    def _show_base(self):
        self.base_box.configure(values=self._place_labels())
        self.base_box.set(self._base_text())

    def _place_chosen(self, event=None):
        index = self.base_box.current()
        if index < 0:
            return
        if self.places_machine is None:     # no program: its places have no address
            put_back(self.base_box, self._texts[0])     # the field keeps what it showed
        else:
            self._set_base(PLACES[index])

    def _address_entered(self, event=None):
        self._apply_typed()
        return "break"                  # not Connect

    def _focus_path(self):
        """The path of the widget with the keyboard focus; "" while ARES has none."""
        return str(self.window.tk.call("focus"))

    def _address_leaving(self, event=None):
        """The keyboard focus is leaving the base field. Where it goes is known once the
        changes of the moment are done: on the way to another ARES window no widget has it
        for a while."""
        self.app.root.after_idle(self._address_left)

    def _address_left(self, event=None):
        """The keyboard focus left the base field: for another part of ARES the typed text
        is applied; for the field's own list, or while another program is in front, it
        waits."""
        if self.window is None:
            return
        focus, field = self._focus_path(), str(self.base_box)
        if focus and focus != field and not focus.startswith(field + "."):
            self._apply_typed()

    def _apply_typed(self):
        """Take the text of the base field: a place's name or text, or an address; a wrong
        address, or a place while no program is loaded, rings the bell and the old base
        stays."""
        text = self.base_box.get().strip()
        if text == self._base_text():
            return
        labels = self._place_labels()
        base = next((place for place, label in zip(PLACES, labels) if text in (place, label)),
                    None)
        if base is None:
            base = parse_address(text)
        elif self.places_machine is None:
            base = None                 # a place of no program: it has no address
        if base is None or not self._set_base(base):
            self.window.bell()
            self._show_base()

    def _set_base(self, base):
        if not self.model.set_base(base):
            return False
        self._show_base()
        self.show()
        return True


WINDOW = BitmapWindow
