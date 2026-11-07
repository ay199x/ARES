# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Tools > Memory Reference Visualization: which memory the program uses, and how often.

The display is a grid of units, each standing for some words of memory from
a base address on, row by row from the top left. Each time the program reads
or writes a unit's memory, or executes an instruction from it, the unit's
count grows by 1, and the unit takes the colour of its count. Memory
accesses are observed only in the memory shown, and instructions are
counted per basic block (ares.observers) only while the display shows some
of the program's code: a connected tool costs Python time per access shown
and per block, never per instruction.
"""

import tkinter as tk
from bisect import bisect_right
from collections import defaultdict
from itertools import compress
from tkinter import ttk
from tkinter.colorchooser import askcolor

from ...machine import DDR_END, INITIAL_SP
from ...program import INSTRUCTION_SIZE
from ..execute import page_start
from ..places import (CURRENT_SP, STACK_TEXT, gray_unavailable, list_width, place_text,
                      select_text)
from ..style import default_button, sunken
from ..widgets import Tooltip, px
from .frame import ToolModel, ToolWindow

WORDS_PER_UNIT = tuple(2 ** n for n in range(12))       # 1 to 2048
UNIT_SIZES = (1, 2, 4, 8, 16, 32)                       # a unit's width or height, design pixels
DISPLAY_SIZES = (64, 128, 256, 512, 1024)               # the display's width or height
CHOICES = {"words_per_unit": WORDS_PER_UNIT, "unit_width": UNIT_SIZES,
           "unit_height": UNIT_SIZES, "width": DISPLAY_SIZES, "height": DISPLAY_SIZES,
           "base": range(0, 1 << 32, 4)}
# The lists of settings: (setting, label, tooltip).
SETTINGS = (
    ("words_per_unit", "Words per unit:", "How many words of memory one unit stands for"),
    ("unit_width", "Unit width (pixels):", "The width of a unit"),
    ("unit_height", "Unit height (pixels):", "The height of a unit"),
    ("width", "Display width (pixels):", "The width of the display"),
    ("height", "Display height (pixels):", "The height of the display"),
)
PLACES = (".data", "heap", CURRENT_SP, ".text")          # the base addresses, as listed

# The colour of each number of accesses, from each start up to the next one:
# none black, 1 blue, 2 green, 3 to 4 yellow, 5 to 9 orange, 10 or more red.
COLOURS = ((0, "#000000"), (1, "#0000FF"), (2, "#00FF00"), (3, "#FFFF00"), (5, "#FFC800"),
           (10, "#FF0000"))
# The numbers of accesses the slider chooses from: 0 to 10, 20 to 50 in tens, 100 to 500 in
# hundreds, 1,000 to 5,000 in thousands, then 10,000, 50,000, 100,000, 500,000 and 1,000,000.
COUNTS = (tuple(range(11)) + tuple(range(20, 51, 10)) + tuple(range(100, 501, 100))
          + tuple(range(1000, 5001, 1000)) + (10_000, 50_000, 100_000, 500_000, 1_000_000))
FIRST_COUNT = 10                # the slider's first choice
SLIDER_LENGTH = 120             # design pixels
PATCH = (24, 12)                # the colour button's picture, design pixels
TIPS = {
    "base": "The address of the first unit, at the top left",
    "slider": "Choose a number of accesses, to see or change its colour",
    "colour": "Change the colour of this number of accesses",
    "display": "Each unit's colour shows how often the program accessed its memory",
}

HELP = """\
The Memory Reference Visualization shows which memory the program uses, and how often. Its
display is a grid of units: each unit stands for one or more words of memory, from the base
address on, row by row from the top left. Each time the program reads or writes the memory of a
unit, or executes an instruction from it, the unit's count goes up by one, and the unit takes the
colour of its count.

Click Connect to ARM, then run the program (Go, Step): the display follows the program, also
while it runs at full speed; at a slow run speed you see the pattern grow. Disconnect from ARM
stops the counting; the colours stay. Reset sets every count to 0. Close closes the tool and
stops the counting.

Words per unit: how many words of memory one unit stands for, 1 to 2048. Unit width and unit
height: the size of a unit, in pixels. Display width and display height: the size of the
display, in pixels; it has as many units as fit in it.

Base address: the address of the first unit, at the top left. .data is where the program's data
starts (its first section that is not code, or the end of the program when it has none). heap is
where SVC #9 hands out memory. .text is the start of the program's code. These three are places
of the program: while no program is assembled, the list shows them gray, with "no program
assembled" instead of an address, and they cannot be chosen. When a program is assembled, the
display moves to the same place in it. current SP is the page of the stack pointer, as the Data
Segment shows it. Unlike the places of the program, it can be chosen also without a program.
While SP has its start value 0 the list says "current SP: stack at 0xfffffffc", and
the display starts at the page that holds that word, the top of the on-chip memory, where the
first PUSH stores. current SP is SP's page when you choose it: to watch a stack the program sets
up itself, choose current SP again once SP has its value.

Choosing a setting or a base address starts the display again: every count goes back to 0.

Grid lines between units: a line along the top and the left edge of every unit, in the colour
opposite to that of no access.

The colours: no access black, 1 access blue, 2 green, 3 to 4 yellow, 5 to 9 orange, 10 or more
red. To change one, choose a number of accesses with the slider (0 to 10, then in steps up to
1,000,000), then click the colour button beside it and choose the colour: it applies from that
number of accesses up to the next number that has a colour of its own. The text under the slider
says which numbers of accesses the button's colour stands for.

What counts: each read and each write of the program's instructions (LDR, STR, LDRB, STRH, PUSH,
POP, LDM, STM, VLDR, VSTR ...), once for each word it reads or writes, in the unit of that word:
PUSH {R0, R1} and VSTR D0 each write two words and count two accesses, and an unaligned
LDR R0, [R1, #2] reads from two words and counts once in the unit of each. STREX counts two
when it stores, as the processor ARES simulates reads the word before it writes it. Each
instruction executed counts as a read of its own word once it has completed, as in the Dynamic
Instruction Counter: a conditional instruction counts whether its condition holds or not. Memory
that a system call reads or writes for the program (the string SVC #4 prints, the line SVC #8
reads) does not count.

The counts go on when the program is assembled again (unless the display moves), reset (Reset,
F12) or stepped back (Backstep undoes an instruction, but its accesses happened): only the tool's
Reset button, its settings and its base address set them to 0. The tool stays connected when the
program is assembled again or its file is closed.

While the tool is connected a run takes longer: ARES counts each access to the memory shown and,
while the display shows some of the program's code, each group of instructions that runs without
a branch. A loop of 10,000,000 instructions whose code is shown takes about a second instead of a
tenth of a second, and every 1,000,000 accesses to the memory shown add about half a second.
"""


def places(machine):
    """The base addresses the display can start at, [(name, address)] in the order of
    PLACES, for the program of machine. Each is the address of a word: a place off a word
    starts at the word that holds it. While no program is loaded (machine None) the places
    of the program have none (None), and current SP is that of SP's start value."""
    if machine is None:
        return [(name, stack_page(INITIAL_SP) if name == CURRENT_SP else None)
                for name in PLACES]
    sections = machine.program.sections
    data = next((s.address for s in sections if not s.executable), None)
    if data is None:
        data = (max((s.end for s in sections), default=0) + 3) & ~3
    text = next((s.address for s in sections if s.executable), 0)
    return [(".data", data & ~3), ("heap", machine.heap_start),
            (CURRENT_SP, stack_page(machine.reg(13))), (".text", text & ~3)]


def entries(machine):
    """The places of places(machine) as the list shows them, [(name, address, text)]:
    "0x00000030 (.data)", ".data: no program assembled" for a place without an address,
    and for current SP with SP's start value 0 where the stack starts."""
    sp = INITIAL_SP if machine is None else machine.reg(13)
    return [(name, address,
             STACK_TEXT if name == CURRENT_SP and sp == INITIAL_SP else place_text(name, address))
            for name, address in places(machine)]


def stack_page(sp):
    """The page the Data Segment shows for the current SP: from SP's row on, or for an empty
    stack at the end of a memory region (SP's start value 0, or the top of DDR3) the page
    its first push stores to."""
    if sp in (0, DDR_END):
        sp = (sp - 4) & 0xFFFFFFFF
    return page_start(sp)


def accesses(first, last):
    """Words for the numbers of accesses first to last (None: no end): "3 to 4 accesses"."""
    if last is None:
        return f"{first:,} or more accesses"
    if last == first:
        return f"{first:,} access" if first == 1 else f"{first:,} accesses"
    return f"{first:,} to {last:,} accesses"


def opposite(colour):
    """The colour "#RRGGBB" with every bit of red, green and blue inverted."""
    return f"#{int(colour[1:], 16) ^ 0xFFFFFF:06X}"


def bands(rows):
    """[first, last] of each band of consecutive rows among rows, from the top."""
    found = []
    for row in sorted(rows):
        if found and row == found[-1][1] + 1:
            found[-1][1] = row
        else:
            found.append([row, row])
    return found


class ColourScale:
    """The colour of each number of accesses.

    colours is [(start, "#RRGGBB")] sorted by start, the first start 0: a
    colour is that of the numbers from its start up to the next start.
    """

    def __init__(self, colours=COLOURS):
        self.colours = list(colours)
        self.starts = [start for start, _ in self.colours]

    def level(self, count):
        """The index in colours of the colour of count."""
        return bisect_right(self.starts, count) - 1

    def colour(self, count):
        return self.colours[self.level(count)][1]

    def last(self, count):
        """The last number of accesses with the colour of count (None: no last)."""
        level = self.level(count) + 1
        return self.starts[level] - 1 if level < len(self.starts) else None

    def set(self, count, colour):
        """Show count, and the numbers after it up to the next start, in colour."""
        level = self.level(count)
        if self.starts[level] == count:
            self.colours[level] = (count, colour)
        else:
            self.colours.insert(level + 1, (count, colour))
            self.starts.insert(level + 1, count)


class VisualizationModel(ToolModel):
    """The counts of the units of the display, and the memory they stand for (no window).

    The display is width x height design pixels of units of unit_width x
    unit_height: columns x rows units. Unit k stands for words_per_unit
    words from base + k * 4 * words_per_unit on; the address space ends the
    display early. counts[k] is how often the program accessed the memory
    of unit k while connected: each read and write of a word there (each
    word of one of 8 bytes, or of an unaligned one that reaches into the
    next word), and each instruction completed from there (the display
    shows some of the program's code then). The counts go on across
    Assemble, Reset and Backstep; reset() and configure() set them to 0.
    """

    def __init__(self):
        super().__init__()
        self.words_per_unit = 1
        self.unit_width = self.unit_height = 16
        self.width = self.height = 256
        self.base = 0
        self._hits = defaultdict(int)   # unit -> accesses since the last update, while observing
        self._blocks = None             # the machine's BlockCounts, while it shows code
        self._seen = {}                 # their runs as already counted here
        self._lay_out()

    def _lay_out(self):
        self.counts = [0] * (self.columns * self.rows)
        self._shift = 1 + self.words_per_unit.bit_length()     # bits of a unit's bytes
        self._units = {}                # (address, size) -> the units of its instructions
        self._changed = set()           # units whose counts changed since take_changes()
        self._everything = True         # every unit to be drawn again

    @property
    def columns(self):
        return self.width // self.unit_width

    @property
    def rows(self):
        return self.height // self.unit_height

    @property
    def end(self):
        """The last address the display shows."""
        return min(self.base + (len(self.counts) << self._shift), 1 << 32) - 1

    def unit_of(self, address):
        """The unit that shows address, or None."""
        if self.base <= address <= self.end:
            return (address - self.base) >> self._shift
        return None

    def configure(self, **settings):
        """Change settings (words_per_unit, unit_width, unit_height, width, height, base):
        the display starts again, every count 0, and observes the memory it shows now."""
        for name, value in settings.items():
            if value not in CHOICES[name]:
                raise ValueError(f"{name} cannot be {value!r}")
        machine = self.machine
        if machine is not None:
            self.detach(machine)
        for name, value in settings.items():
            setattr(self, name, value)
        self._lay_out()
        if machine is not None:
            self.attach(machine)

    def attach(self, machine):
        observers = machine.observers
        observers.count_accesses(self, self._hits, self.base, self.end, self._shift)
        # Instructions are executed from the program's code: blocks are counted only
        # while the display shows some of it.
        if any(s.address <= self.end and self.base < s.end
               for s in machine.program.sections if s.executable):
            self._blocks = observers.count_blocks(self)
            self._seen = dict(self._blocks.runs)

    def detach(self, machine):
        self.update()
        machine.observers.forget(self)
        self._blocks = None
        self._seen = {}

    def reset(self):
        self.update()
        self.counts = [0] * len(self.counts)
        self._changed.clear()
        self._everything = True

    def update(self):
        """Take in the accesses and instructions since the last update; True when counts
        changed since the last take_changes()."""
        counts, changed, hits = self.counts, self._changed, self._hits
        if hits:
            for unit, count in hits.items():
                counts[unit] += count
            changed.update(hits)
            hits.clear()                # the same dictionary: the hook counts into it
        blocks = self._blocks
        if blocks is not None:
            seen = self._seen
            for stretch, count in blocks.runs.items():
                new = count - seen.get(stretch, 0)
                if new:
                    seen[stretch] = count
                    for unit in self._units_of(stretch):
                        counts[unit] += new
                        changed.add(unit)
        return self._everything or bool(self._changed)

    def take_changes(self):
        """The units whose counts changed since the last call, or None when every unit is
        to be drawn again (the display started again)."""
        changes, self._changed = self._changed, set()
        everything, self._everything = self._everything, False
        return None if everything else changes

    def _units_of(self, stretch):
        """The units of the instructions of a stretch (address, size) that the display shows."""
        units = self._units.get(stretch)
        if units is None:
            address, size = stretch
            base, shift = self.base, self._shift
            first, last = max(address, base), min(address + size - INSTRUCTION_SIZE, self.end)
            units = [(at - base) >> shift for at in range(first, last + 1, INSTRUCTION_SIZE)]
            self._units[stretch] = units
        return units


class VisualizationWindow(ToolWindow):
    """Tools > Memory Reference Visualization.

    The settings, the base address and the colours are on the left, the
    display on the right: a picture with one pixel per unit (units) copied,
    enlarged to the units' size, into the picture on the canvas (picture).
    Only the units whose colour changed are drawn again: in each band of
    rows that has some, the columns from the first to the last of them.
    """

    NAME = "Memory Reference Visualization"
    HEADING = "Where a program reads and writes memory"
    HELP = HELP
    MODEL = VisualizationModel

    def __init__(self, app):
        super().__init__(app)
        # The colour button is a push button too: Return presses it while it has the
        # focus, and it then has the black frame.
        default_button(self.connect_button, self.buttons + (self.colour_button,))

    def build(self, body):
        gap = px(body, 6)
        self.colours = ColourScale()
        self.places = entries(self.app.machine)     # [(name, address, text)], as listed
        # The place chosen, and the text the list showed for it then: the base is its address.
        self.place, address, self.chosen_text = self.places[0]
        if address is not None:         # without a program the base waits for one
            self.model.configure(base=address)
        settings = ttk.Frame(body)
        settings.grid(row=0, column=0, sticky="n")
        self.grid_shown = tk.BooleanVar(master=body, value=True)
        self.grid_box = ttk.Checkbutton(settings, text="Grid lines between units",
                                        variable=self.grid_shown, command=self._draw_grid)
        self.grid_box.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, gap))
        self.lists = {}
        for row, (name, label, tip) in enumerate(SETTINGS, start=1):
            ttk.Label(settings, text=label).grid(row=row, column=0, sticky="w")
            box = ttk.Combobox(settings, state="readonly", width=6,
                               values=[str(value) for value in CHOICES[name]])
            box.set(str(getattr(self.model, name)))
            box.bind("<<ComboboxSelected>>", lambda event, name=name: self._setting_chosen(name))
            box.grid(row=row, column=1, sticky="e", padx=(gap, 0), pady=px(body, 2))
            Tooltip(box, tip)
            self.lists[name] = box
        row = len(SETTINGS) + 1
        ttk.Label(settings, text="Base address:").grid(row=row, column=0, sticky="w")
        # Wide enough to show each place whole: the widest is current SP's while SP is 0.
        texts = (STACK_TEXT, place_text(".data", None), place_text(CURRENT_SP, 0))
        self.base_list = ttk.Combobox(settings, state="readonly", width=list_width(body, texts),
                                      postcommand=self._look_up_places)
        self.base_list.bind("<<ComboboxSelected>>", self._place_chosen)
        self.base_list.grid(row=row, column=1, sticky="e", padx=(gap, 0), pady=px(body, 2))
        Tooltip(self.base_list, TIPS["base"])
        self._show_places()

        colour = ttk.Frame(settings)
        colour.grid(row=row + 1, column=0, columnspan=2, pady=(2 * gap, 0))
        self.slider = ttk.Scale(colour, from_=0, to=len(COUNTS) - 1, orient="horizontal",
                                length=px(body, SLIDER_LENGTH))
        self.slider.pack(side="left")
        # Tk's slider takes no keyboard focus from a click, and the keys then stay elsewhere.
        self.slider.bind("<ButtonPress-1>", lambda event: self.slider.focus_set(), add="+")
        Tooltip(self.slider, TIPS["slider"])
        width, height = px(body, PATCH[0]), px(body, PATCH[1])
        self.patch = tk.PhotoImage(master=body, width=width, height=height)
        self.patch.put("#000000", to=(0, 0, width, height))     # its edge
        self.colour_button = ttk.Button(colour, image=self.patch, command=self.choose_colour)
        self.colour_button.pack(side="left", padx=(gap, 0))
        Tooltip(self.colour_button, TIPS["colour"])
        for key in ("<Return>", "<KP_Enter>"):
            self.colour_button.bind(key, self._press_colour)
        self.count_label = ttk.Label(settings, anchor="center")
        self.count_label.grid(row=row + 2, column=0, columnspan=2, sticky="ew")

        frame = sunken(tk.Frame(body))
        frame.grid(row=0, column=1, sticky="n", padx=(2 * gap, 0))
        self.canvas = tk.Canvas(frame, borderwidth=0, highlightthickness=0, takefocus=False)
        self.canvas.pack()
        self.units = tk.PhotoImage(master=body)          # one pixel per unit
        self.picture = tk.PhotoImage(master=body)        # the display
        self.canvas.create_image(0, 0, image=self.picture, anchor="nw")
        Tooltip(self.canvas, TIPS["display"])
        self._set_channels()
        self.choice = COUNTS.index(FIRST_COUNT)
        self.slider.set(self.choice)
        self.slider.configure(command=self._slid)
        self._show_count()
        self._lay_out()

    # The settings and the base address ------------------------------------------------

    def _setting_chosen(self, name):
        self._configure(**{name: int(self.lists[name].get())})

    def _configure(self, **settings):
        self.model.configure(**settings)
        self._lay_out()
        self.show()

    def _show_places(self):
        """List the places, and show the place chosen as the list showed it then."""
        self.base_list.configure(values=[text for _, _, text in self.places])
        self.base_list.set(self.chosen_text)

    def _look_up_places(self):
        """The list opens: the places of the program as it is now (SP moves as it runs);
        those without an address are gray."""
        self.places = entries(self.app.machine)
        self._show_places()
        gray_unavailable(self.base_list, [address is not None for _, address, _ in self.places])

    def _place_chosen(self, event=None):
        index = self.base_list.current()
        # The places as they are now: the mouse wheel chooses without opening the list, from
        # the entries of its last look-up, and SP may have moved since.
        self.places = entries(self.app.machine)
        if index >= 0 and self.places[index][1] is not None:
            self.place, address, self.chosen_text = self.places[index]
            self._configure(base=address)
        self._show_places()             # a place without an address changes nothing
        select_text(self.base_list)     # as after a choice in the list

    def machine_changed(self, machine):
        """A program was loaded: the display moves to the place chosen in it, and starts
        again if that is another address. A program unloaded leaves the display as it is;
        the places of the program have no address then."""
        if machine is not None:
            self.model.observe(None)    # not the old program's machine any more
        self.places = entries(machine)
        _, address, text = self.places[PLACES.index(self.place)]
        if machine is not None:
            self.chosen_text = text
            if address != self.model.base:
                self._configure(base=address)
        elif address is None:
            self.chosen_text = text     # ".data: no program assembled"
        self._show_places()
        super().machine_changed(machine)

    # The colours ---------------------------------------------------------------

    def _slid(self, value):
        index = round(float(value))
        if float(value) != index:
            self.slider.set(index)      # the slider stops at whole positions; it calls again
            return
        self.choice = index
        self._show_count()

    def _show_count(self):
        """The colour button and the text under the slider, for the count the slider shows."""
        count = COUNTS[self.choice]
        ring = px(self.colour_button, 1)
        width, height = self.patch.width(), self.patch.height()
        self.patch.put(self.colours.colour(count), to=(ring, ring, width - ring, height - ring))
        self.count_label.configure(text=accesses(count, self.colours.last(count)))

    def _press_colour(self, event):
        self.colour_button.invoke()
        return "break"

    def choose_colour(self):
        """The colour button: choose the colour of the count the slider shows."""
        count = COUNTS[self.choice]
        old = self.colours.colour(count)
        title = f"Colour of {accesses(count, self.colours.last(count))}"
        _, colour = askcolor(old, title=title, parent=self.window)
        if colour is None or colour.upper() == old:
            return
        self.colours.set(count, colour.upper())
        self._set_channels()
        self._show_count()
        self.canvas.itemconfigure("grid", fill=opposite(self.colours.colour(0)))
        self._draw_all()

    def _set_channels(self):
        """The red, green and blue of each colour level, as tables for bytes.translate()."""
        rgb = [bytes.fromhex(colour[1:]) for _, colour in self.colours.colours]
        rgb += [bytes(3)] * (256 - len(rgb))
        self.channels = [bytes(colour[k] for colour in rgb) for k in range(3)]

    # The display ---------------------------------------------------------------

    def _lay_out(self):
        """Size the pictures and the canvas for the settings, and draw the grid lines; every
        unit is drawn again by the next show()."""
        model = self.model
        canvas = self.canvas
        self.unit_size = width, height = (max(1, px(canvas, model.unit_width)),
                                          max(1, px(canvas, model.unit_height)))
        self.units.configure(width=model.columns, height=model.rows)
        self.picture.configure(width=model.columns * width, height=model.rows * height)
        canvas.configure(width=model.columns * width, height=model.rows * height)
        self.levels = bytearray(len(model.counts))      # the colour level drawn for each unit
        self._draw_grid()

    def _draw_grid(self):
        """While Grid lines is checked, a line along the top and the left edge of each unit,
        in the colour opposite to that of no access."""
        canvas, model = self.canvas, self.model
        canvas.delete("grid")
        if not self.grid_shown.get():
            return
        width, height = self.unit_size
        right, bottom = model.columns * width, model.rows * height
        line = px(canvas, 1)
        colour = opposite(self.colours.colour(0))
        for column in range(model.columns):
            x = column * width
            canvas.create_rectangle(x, 0, x + line, bottom, fill=colour, width=0, tags="grid")
        for row in range(model.rows):
            y = row * height
            canvas.create_rectangle(0, y, right, y + line, fill=colour, width=0, tags="grid")

    def show(self):
        changes = self.model.take_changes()
        if changes is None:
            self._draw_all()
        elif changes:
            self._draw(changes)

    def _draw_all(self):
        counts, level = self.model.counts, self.colours.level
        self.levels = levels = bytearray(len(counts))
        for unit in compress(range(len(counts)), counts):      # the units with a count
            levels[unit] = level(counts[unit])
        self._paint(0, self.model.rows - 1)

    def _draw(self, units):
        """Draw again the units whose colour changed: in each band of rows that has some,
        the columns from the first to the last of them."""
        counts, levels, level = self.model.counts, self.levels, self.colours.level
        columns = self.model.columns
        spans = {}                      # row -> [first, last] column whose colour changed
        for unit in units:
            new = level(counts[unit])
            if levels[unit] != new:
                levels[unit] = new
                row, column = divmod(unit, columns)
                span = spans.get(row)
                if span is None:
                    spans[row] = [column, column]
                elif column < span[0]:
                    span[0] = column
                elif column > span[1]:
                    span[1] = column
        for first, last in bands(spans):
            band = [spans[row] for row in range(first, last + 1)]
            self._paint(first, last, min(left for left, _ in band),
                        max(right for _, right in band))

    def _paint(self, first, last, left=0, right=None):
        """Draw the units of rows first to last, columns left to right (None: the last
        column), from their colour levels."""
        columns = self.model.columns
        if right is None:
            right = columns - 1
        levels = self.levels
        if right - left + 1 == columns:
            part = levels[first * columns:(last + 1) * columns]
        else:
            part = b"".join(levels[row * columns + left:row * columns + right + 1]
                            for row in range(first, last + 1))
        pixels = bytearray(3 * len(part))
        for k, channel in enumerate(self.channels):
            pixels[k::3] = part.translate(channel)
        header = b"P6 %d %d 255\n" % (right - left + 1, last - first + 1)
        self.units.put(header + bytes(pixels), to=(left, first))
        width, height = self.unit_size
        self.picture.tk.call(self.picture, "copy", self.units, "-from", left, first, right + 1,
                             last + 1, "-to", left * width, first * height, "-zoom", width,
                             height)

    def close(self):
        super().close()
        self.units = self.picture = self.patch = None       # their pictures go too


WINDOW = VisualizationWindow
