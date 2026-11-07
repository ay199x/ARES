# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Execute tab: the Text Segment above the Data Segment, and the Labels beside them, each
a small window with its own title bar."""

import bisect
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from ..disasm import text_columns
from ..machine import DDR_END, INITIAL_SP, JTAG_UART
from . import bumps
from .places import CURRENT_SP, STACK_TEXT, list_width, place_text, select_text
from .registers import format_value
from .style import (ACCENT, BEVEL, FACE, HIGHLIGHT, SHADOW, TEXT, TITLE, WINDOW, checkbox_size,
                    fit)
from .table import PAD, PLAIN, STRIPED, Column, Row, Table, column_width
from .widgets import px

CURRENT = "#FFFF99"         # the row of the next instruction to execute: light yellow
FAILED = "#FF9999"          # the row of the instruction a runtime error stopped: light red
CHANGED = "#99CCFF"         # words changed by the last step or run: light blue
SOURCE_LIMIT = 400          # characters of a line the Source column makes room for
# An inner window, in design pixels.
TITLE_BAR = 23              # its title bar
FRAME_FACE = 2              # between its raised frame and its contents
ICON = 16                   # the small window drawn at the left of the title bar
ICON_LEFT = 4               # from the title bar's left side to it
TITLE_LEFT = 25             # from the title bar's left side to the title
SEGMENT_SASH = 3            # the divider between two inner windows
SPLIT_SEGMENTS = 0.5        # at every start: the Text Segment's share of the Execute tab's height
SPLIT_LABELS = 0.75         # and the segments' share of its width while the Labels show
LEAST_SEGMENT = 60          # the Text and the Data Segment keep this much of their height
LEAST_LABELS = (200, 80)    # the segments and the Labels keep this much of their width
PAGE_BUTTON = (50, 26)      # the Previous and Next page buttons
BAR_HEIGHT = 36             # the bar under the Data Segment's table

WORDS = 8                   # words in a row of the Data Segment
ROWS = 16                   # rows on a page of it
ROW_BYTES = 4 * WORDS
PAGE = ROW_BYTES * ROWS     # 512 bytes
LAST_PAGE = 0x100000000 - PAGE
ESCAPES = {0: "\\0", 9: "\\t", 10: "\\n", 13: "\\r"}


def format_address(address, hexadecimal):
    """0x and 8 lowercase hex digits, or an unsigned decimal number."""
    return f"0x{address:08x}" if hexadecimal else str(address)


class InnerWindow(tk.Frame):
    """A small window inside the Execute tab: a raised frame around a title bar and contents.

    The title bar shows a little window and the title, on the face colour;
    while this is the active inner window it is blue with a thin bright line
    along its bottom. title is the title; contents go below the bar.
    on_chosen() is called when the title bar is pressed.
    """

    def __init__(self, master, title):
        super().__init__(master)
        ring, face = px(self, BEVEL), px(self, FRAME_FACE)
        self.configure(relief="raised", borderwidth=2 * ring, padx=face, pady=face)
        self.title = title
        self.active = False
        self.on_chosen = None
        height = px(self, TITLE_BAR)
        self.bar = bar = tk.Canvas(self, height=height, background=FACE, borderwidth=0,
                                   highlightthickness=0, takefocus=False)
        bar.pack(side="top", fill="x")
        size, left = px(self, ICON), px(self, ICON_LEFT)
        top = (height - size) // 2
        bar.create_rectangle(left, top, left + size, top + size, fill=HIGHLIGHT, outline=SHADOW,
                             width=ring)
        bar.create_rectangle(left, top, left + size, top + size // 4, fill=SHADOW, width=0)
        self.text = bar.create_text(px(self, TITLE_LEFT), height // 2, anchor="w", text=title,
                                    fill=TEXT, font="TkDefaultFont")
        self.accent = bar.create_rectangle(0, height - ring, 0, height, fill=ACCENT, width=0,
                                           state="hidden")
        bar.bind("<Configure>", self._sized)
        bar.bind("<ButtonPress-1>", self._pressed)

    def _sized(self, event):
        x0, y0, _, y1 = self.bar.coords(self.accent)
        self.bar.coords(self.accent, x0, y0, event.width, y1)

    def _pressed(self, event):
        if self.on_chosen is not None:
            self.on_chosen()

    def set_active(self, active):
        """Show the title bar as the active inner window's, or not."""
        if active != self.active:
            self.active = active
            self.bar.configure(background=TITLE if active else FACE)
            self.bar.itemconfigure(self.accent, state="normal" if active else "hidden")


class TextSegment(InnerWindow):
    """Bkpt | Address | Code | Basic | Source for every word of the program's code sections.

    A checked Bkpt box is a breakpoint; only instructions have one; the
    boxes are gray while Toggle All Breakpoints has switched them all off.
    on_breakpoints(addresses) is called with the addresses where a run has
    to stop whenever they change: none while they are switched off.
    """

    def __init__(self, master, settings, font):
        super().__init__(master, "Text Segment")
        self.settings = settings
        self.font = font
        self.on_breakpoints = None
        bkpt = max(column_width(self, font, 0, "Bkpt"), checkbox_size(self) + 2 * px(self, PAD))
        # The widths of Basic and Source until a program is shown, and again without one.
        self._empty_widths = {"basic": column_width(self, font, 24, "Basic"),
                              "source": column_width(self, font, 40, "Source")}
        self.table = Table(self, [
            Column("bkpt", "Bkpt", bkpt, "center", checkbox=True, shade=PLAIN),
            Column("address", "Address", column_width(self, font, 10, "Address"), "e",
                   shade=PLAIN),
            Column("code", "Code", column_width(self, font, 10, "Code"), "e", shade=STRIPED),
            Column("basic", "Basic", self._empty_widths["basic"]),
            Column("source", "Source", self._empty_widths["source"], stretch=True),
        ], font)
        self.table.pack(fill="both", expand=True)
        self.table.on_click = self._clicked
        self.table.on_double_click = self._clicked      # the second click of a double click
        self.table.on_heading = self._heading_clicked
        self.clear()

    def load(self, program, listing):
        """Show a program's rows (an ares.disasm.Listing); no breakpoints are set."""
        self.program = program
        self.listing = listing
        self.rows = listing.rows
        self._code = listing.instructions
        self.breakpoints = set()
        self.enabled = True
        self.pc_row = None
        self.pc_failed = False
        self._tab_size = listing.tab_size       # the Source column is wide enough for it
        widest = min(SOURCE_LIMIT, listing.widest_source)
        self.table.set_rows(len(self.rows), self._row, {
            "basic": column_width(self, self.font, listing.widest_basic, "Basic"),
            "source": column_width(self, self.font, widest, "Source")})
        self.refresh()                          # the tab width may have changed meanwhile

    def clear(self):
        self.program = self.listing = None
        self.rows = []
        self._code = []
        self.breakpoints = set()
        self.enabled = True
        self.pc_row = None
        self.pc_failed = False
        self._tab_size = None
        self.table.set_rows(0, None, self._empty_widths)    # no bar for the last program's widths

    def _row(self, index):
        row = self.rows[index]
        box = (row.address in self.breakpoints, self.enabled) if self._code[index] else None
        tab_size = self.settings.tab_size
        source = (row.source if tab_size == self.listing.tab_size
                  else self.listing.sources.text(row.line, tab_size))
        colour = (FAILED if self.pc_failed else CURRENT) if index == self.pc_row else ""
        return Row((box, format_address(row.address, self.settings.hex_addresses),
                    f"0x{row.code:08x}", row.basic, source), colour)

    def refresh(self):
        """Show the rows again (after a setting changed, such as the tab width)."""
        tab_size = self.settings.tab_size
        if self.listing is not None and tab_size != self._tab_size:
            self._tab_size = tab_size
            sources = self.listing.sources
            widest = max((text_columns(sources.text(row.line, tab_size))
                          for row in self.rows if row.line is not None), default=0)
            self.table.set_width("source", column_width(self, self.font,
                                                        min(SOURCE_LIMIT, widest), "Source"))
        self.table.refresh()

    def row_of(self, address):
        """Index of the row at address, or None."""
        i = bisect.bisect_left(self.rows, address, key=lambda row: row.address)
        return i if i < len(self.rows) and self.rows[i].address == address else None

    def set_pc(self, address, failed=False):
        """Highlight the row of the next instruction to execute and scroll it into view.

        failed: the instruction at address stopped the program with a runtime
        error; its row is light red instead of yellow. None, or an address
        without a row, highlights nothing.
        """
        self.pc_failed = failed
        self.pc_row = None if address is None else self.row_of(address)
        if self.pc_row is not None:
            self.table.see(self.pc_row)
        self.table.refresh()

    def show_address(self, address):
        """Select the row at address in the middle of the table; False when it has none."""
        index = self.row_of(address)
        if index is None:
            return False
        self.table.select(index, center=True)
        return True

    # Breakpoints ---------------------------------------------------------

    @property
    def active_breakpoints(self):
        """Addresses where a run stops: the checked ones, unless all are switched off."""
        return set(self.breakpoints) if self.enabled else set()

    def toggle_breakpoint(self, address):
        """Check or uncheck the breakpoint of the instruction at address."""
        index = self.row_of(address)
        if index is not None and self._code[index]:
            self.breakpoints ^= {address}
            self._breakpoints_changed()

    def clear_breakpoints(self):
        """Uncheck every breakpoint (and switch breakpoints on again)."""
        self.breakpoints = set()
        self.enabled = True
        self._breakpoints_changed()

    def toggle_all(self):
        """Switch all breakpoints off, or on again, keeping their check marks."""
        if self.rows:
            self.enabled = not self.enabled
            self._breakpoints_changed()

    def _breakpoints_changed(self):
        self.table.refresh()
        if self.on_breakpoints is not None:
            self.on_breakpoints(self.active_breakpoints)

    def _clicked(self, index, column):
        if column == "bkpt" and self._code[index]:
            self.toggle_breakpoint(self.rows[index].address)

    def _heading_clicked(self, column):
        if column == "bkpt":
            self.toggle_all()


class LabelsPane(InnerWindow):
    """Label | Address for every label of the program, by address.

    The Label column needs the widest name, or its heading when that is
    wider. on_show(address) is called when a label is double-clicked.
    """

    def __init__(self, master, settings, font):
        super().__init__(master, "Labels")
        self.settings = settings
        self.font = font
        self.labels = []
        self.on_show = None
        self.name_font = tkfont.nametofont("TkTextFont", root=self)
        self.table = Table(self, [
            Column("label", "Label", self._label_width(), stretch=True, shade=PLAIN,
                   font=self.name_font),
            Column("address", "Address", column_width(self, font, 10, "Address"), "e",
                   stretch=True, shade=PLAIN),
        ], font)
        self.table.pack(fill="both", expand=True)
        self.table.on_double_click = self._double_clicked

    def load(self, labels):
        """Show labels (ares.program.Label), sorted by address and then name."""
        self.labels = sorted(labels, key=lambda label: (label.address, label.name))
        self.table.set_rows(len(self.labels), self._row, {"label": self._label_width()})

    def clear(self):
        self.labels = []
        self.table.set_rows(0, None, {"label": self._label_width()})

    def _label_width(self):
        widest = max((self.name_font.measure(label.name[:SOURCE_LIMIT])
                      for label in self.labels), default=0)
        return max(widest + 2 * px(self, PAD) + 2, column_width(self, self.font, 0, "Label"))

    def refresh(self):
        self.table.refresh()

    def _row(self, index):
        label = self.labels[index]
        return Row((label.name, format_address(label.address, self.settings.hex_addresses)))

    def _double_clicked(self, index, column):
        if self.on_show is not None:
            self.on_show(self.labels[index].address)


def ascii_text(word):
    """The 4 bytes of a word in memory order, two characters each (' H', '\\n', ' .')."""
    return "".join(ESCAPES.get(byte) or (" " + chr(byte) if 32 <= byte < 127 else " .")
                   for byte in word.to_bytes(4, "little"))


def value_heading(offset, hexadecimal):
    """Heading of the Data Segment column of the word at offset in its row."""
    return f"Value (+{offset:x})" if hexadecimal else f"Value (+{offset})"


def page_start(address):
    """The first address of the page shown for address: its row, kept in DDR3 memory if it is."""
    base = address & ~(ROW_BYTES - 1)
    if base < DDR_END < base + PAGE:
        base = DDR_END - PAGE
    return min(base, LAST_PAGE)


class DataSegment(InnerWindow):
    """Address | Value (+0) ... Value (+1c): a page of memory, 16 rows of 8 words.

    Below the table are the Previous and Next page buttons, a list of places
    to show, and the checkboxes Hexadecimal Addresses and Hexadecimal Values,
    which are the settings of the same names (on_setting(name, value) is
    called when one is clicked), and ASCII. Words changed since mark() are
    highlighted: those the instructions recorded since then wrote (Step and
    slow runs), on any page, and the words of the page shown at mark() whose
    value differs. Without a program there is no memory to show: the list
    is disabled and says so (ares.gui.places).
    """

    def __init__(self, master, settings, font, images):
        super().__init__(master, "Data Segment")
        self.settings = settings
        self.on_setting = None
        self.machine = None
        self.base = 0                   # address of the first word of the page
        self.words = []                 # the words of the page (None: no memory there)
        self.baseline = {}              # address -> word at mark()
        self._marked = None             # number of the machine's last recorded change at mark()
        self._written = set()           # words written by the instructions recorded since
        self._places = []               # (name, address or None for the current SP)
        self._chosen = 0                # the place chosen last
        value = max(column_width(self, font, 11, value_heading(0x1C, True)),
                    column_width(self, font, 11, value_heading(28, False)))
        # Address and the eight values share the width equally.
        columns = [Column("address", "Address", column_width(self, font, 10, "Address"), "e",
                          stretch=True, shade=PLAIN)]
        columns += [Column(str(k), value_heading(4 * k, settings.hex_addresses), value, "e",
                           stretch=True) for k in range(WORDS)]
        self.table = Table(self, columns, font)
        bar = ttk.Frame(self)
        bar.pack(side="bottom", pady=px(self, 5))
        self.table.pack(side="top", fill="both", expand=True)
        self.previous_button = ttk.Button(bar, image=images["page_previous"], takefocus=False,
                                          style="Page.TButton", command=lambda: self.turn(-1))
        self.next_button = ttk.Button(bar, image=images["page_next"], takefocus=False,
                                      style="Page.TButton", command=lambda: self.turn(1))
        self.previous_button.pack(side="left")
        self.next_button.pack(side="left")
        # Wide enough to show each place whole: the widest is current SP's while SP is 0.
        texts = (STACK_TEXT, place_text(".data", None), place_text("JTAG UART", JTAG_UART))
        self.places = ttk.Combobox(bar, state="readonly", width=list_width(self, texts),
                                   takefocus=False, postcommand=self._look_up_places)
        self.places.pack(side="left", padx=px(self, 5))
        self.places.bind("<<ComboboxSelected>>", self._place_chosen)
        self.hex_addresses = tk.BooleanVar(self, settings.hex_addresses)
        self.hex_values = tk.BooleanVar(self, settings.hex_values)
        self.ascii = tk.BooleanVar(self, False)
        for text, var, name in (("Hexadecimal Addresses", self.hex_addresses, "hex_addresses"),
                                ("Hexadecimal Values", self.hex_values, "hex_values"),
                                ("ASCII", self.ascii, None)):
            ttk.Checkbutton(bar, text=text, variable=var, takefocus=False,
                            command=lambda v=var, n=name: self._checked(n, v)).pack(
                                side="left", padx=(0, px(self, 5)))
        self.clear()

    def load(self, machine):
        """Show the memory of a machine, from the start of its data."""
        self.machine = machine
        text = next((s.address for s in machine.program.sections if s.executable), 0)
        self._places = [(".data", self.data_start()), (CURRENT_SP, None), (".text", text),
                        ("JTAG UART", JTAG_UART)]
        self._chosen = 0
        self._look_up_places()
        self._set_buttons()
        self.baseline = {}
        self.show(self.data_start())

    def _look_up_places(self):
        """List the places, current SP as SP is now (the list opens, a place was chosen, or
        a program was loaded), and show the place chosen last."""
        if self.machine is None:
            return
        stack = STACK_TEXT if self.machine.reg(13) == INITIAL_SP else CURRENT_SP
        self.places.configure(values=[stack if address is None else place_text(name, address)
                                      for name, address in self._places])
        self.places.current(self._chosen)

    def data_start(self):
        """Where the program's data starts: its first section that is not code, else its end."""
        sections = self.machine.program.sections
        start = next((s.address for s in sections if not s.executable), None)
        if start is None:
            start = (max((s.end for s in sections), default=0) + 3) & ~3
        return start

    def clear(self):
        self.machine = None
        self.words = []
        self.baseline = {}
        self._marked = None
        self._written = set()
        self._places = []
        self._chosen = 0
        self.places.configure(values=())
        self.places.set(place_text(".data", None))     # no address: no program assembled
        self._set_buttons()
        self.table.clear()

    def _set_buttons(self):
        state = ["!disabled"] if self.machine is not None else ["disabled"]
        for widget in (self.previous_button, self.next_button, self.places):
            widget.state(state)

    def show(self, address, select=False):
        """Show the page from the row holding address; select selects that row."""
        if self.machine is None:
            return False
        self.base = page_start(address)
        self.words = self.machine.peek_words(self.base, WORDS * ROWS)
        sideways = self.table.body.xview()[0]
        self.table.set_rows(ROWS, self._row)
        self.table.body.xview_moveto(sideways)      # the columns stay where they were
        if select:
            self.table.select((address - self.base) // ROW_BYTES)
        return True

    def turn(self, pages):
        """Show the previous (-1) or next (1) page."""
        if self.machine is not None:
            self.show(max(0, min(self.base + pages * PAGE, LAST_PAGE)))

    def refresh(self):
        """Read the page from memory again and show it."""
        if self.machine is not None:
            self.words = self.machine.peek_words(self.base, WORDS * ROWS)
            self._written = self._written_since_mark()
        self.table.refresh()

    def mark(self):
        """From now on highlight the words that change (see the class)."""
        self.baseline = {}
        self._written = set()
        if self.machine is not None:
            # Typed input may have changed the JTAG UART since the page was read.
            self.words = self.machine.peek_words(self.base, WORDS * ROWS)
            self.baseline = {self.base + 4 * k: word for k, word in enumerate(self.words)}
            history = self.machine.history
            self._marked = history[-1].number if history else 0
        self.table.refresh()

    def unmark(self):
        """Highlight no word."""
        self.baseline = {}
        self._marked = None
        self._written = set()
        self.table.refresh()

    def _written_since_mark(self):
        """Words written by the instructions recorded for Backstep since mark()."""
        if self._marked is None:
            return set()
        words = set()
        # Changes are numbered in order. Those after the mark may have been
        # undone by Backstep, and the oldest of a long run are dropped.
        for change in reversed(self.machine.history):
            if change.number <= self._marked:
                break
            for address, old in change.writes:
                words.update(word & 0xFFFFFFFF
                             for word in range(address & ~3, address + len(old), 4))
        return words

    def apply_settings(self):
        hexadecimal = self.settings.hex_addresses
        self.hex_addresses.set(hexadecimal)
        self.hex_values.set(self.settings.hex_values)
        for k, column in enumerate(self.table.columns[1:]):
            column.heading = value_heading(4 * k, hexadecimal)
        self.table.set_heading("address", "Address")        # draws the headings again
        self.table.refresh()

    def _row(self, index):
        address = self.base + index * ROW_BYTES
        cells = [format_address(address, self.settings.hex_addresses)]
        changed = {}
        for k in range(WORDS):
            word = self.words[index * WORDS + k]
            if word is None:                # not memory
                cells.append("")
                continue
            if self.ascii.get():
                cells.append(ascii_text(word))
            else:
                cells.append(format_value(word, self.settings.hex_values))
            if (address + 4 * k in self._written
                    or self.baseline.get(address + 4 * k, word) != word):
                changed[str(k)] = CHANGED
        return Row(tuple(cells), "", changed)

    def _checked(self, name, var):
        if name is None:
            self.table.refresh()            # ASCII
        elif self.on_setting is not None:
            self.on_setting(name, var.get())

    def _place_chosen(self, event=None):
        if self.machine is None or self.places.current() < 0:
            return
        self._chosen = self.places.current()
        # The mouse wheel chooses without opening the list: the field took current SP's text
        # from the last look-up. It says what SP is now, as the page shown does.
        self._look_up_places()
        select_text(self.places)
        name, address = self._places[self._chosen]
        if address is None:                 # the current SP: the words at the top of the stack
            address = self.machine.reg(13)
            # An empty stack at the end of a memory region (SP's start value 0,
            # or the top of DDR3): show the word its first push stores to.
            if address in (0, DDR_END):
                address = (address - 4) & 0xFFFFFFFF
        self.show(address)


class ExecutePane(ttk.PanedWindow):
    """Text Segment above Data Segment, with the Labels at their right when shown.

    The dividers take their default places once the panes have their size
    on the screen; the Labels' divider stays where it was while the Labels
    are hidden and shown again while ARES runs. The
    inner window last used is the active one: its title bar shows it, from
    the moment its table gets the keyboard focus or its title bar is pressed.
    """

    def __init__(self, master, settings, font, images):
        super().__init__(master, orient="horizontal", style="Inner.TPanedwindow")
        self.settings = settings
        self.segments = ttk.PanedWindow(self, orient="vertical", style="Inner.TPanedwindow")
        self.text_segment = TextSegment(self.segments, settings, font)
        self.data_segment = DataSegment(self.segments, settings, font, images)
        self.segments.add(self.text_segment, weight=1)
        self.segments.add(self.data_segment, weight=1)
        self.add(self.segments, weight=1)
        sash, least = px(self, SEGMENT_SASH), px(self, LEAST_SEGMENT)
        bumps.keep_panes(self.segments, (least, least), sash)
        bumps.keep_panes(self, tuple(px(self, size) for size in LEAST_LABELS), sash)
        self.labels = LabelsPane(self, settings, font)
        self.labels.on_show = self.show_address
        self.labels_shown = False
        for window in (self.text_segment, self.data_segment, self.labels):
            window.on_chosen = lambda window=window: window.table.body.focus_set()
            window.table.body.bind("<FocusIn>", lambda event, window=window:
                                   self._activate(window), add="+")
        self.split_labels = SPLIT_LABELS    # the Labels' divider, while ARES runs
        self._segments_pending = True       # the divider waits for a size to be placed
        self._labels_pending = True
        self.segments.bind("<Configure>", self.place_dividers, add="+")
        self.bind("<Configure>", self.place_dividers, add="+")
        self.show_labels(settings.show_labels)

    def _activate(self, chosen):
        """Make chosen the active inner window."""
        for window in (self.text_segment, self.data_segment, self.labels):
            window.set_active(window is chosen)

    def load(self, machine, listing):
        """Show a machine's program: its Text Segment rows (an ares.disasm.Listing), its
        memory and its labels."""
        self.text_segment.load(machine.program, listing)
        self.data_segment.load(machine)
        self.labels.load(machine.program.labels)

    def clear(self):
        self.text_segment.clear()
        self.data_segment.clear()
        self.labels.clear()

    def apply_settings(self):
        self.show_labels(self.settings.show_labels)
        self.text_segment.refresh()
        self.data_segment.apply_settings()
        self.labels.refresh()

    def show_labels(self, on):
        """Show or hide the Labels at the right."""
        if on == self.labels_shown:
            return
        if on:
            self.add(self.labels, weight=0)
            self.labels_shown = True
            self._labels_pending = True
            # Tk must lay the new pane out first: a divider placed before that leaves it
            # no width at all.
            self.update_idletasks()
            self.place_dividers()
        else:
            self._keep_labels_divider()
            self.forget(self.labels)
            self.labels_shown = False

    def show_address(self, address):
        """Show an address (a label's): its row in the Text Segment, else in the Data Segment."""
        return (self.text_segment.show_address(address)
                or self.data_segment.show(address, select=True))

    def place_dividers(self, event=None):
        """Put the dividers in their places, once the panes have a size.

        The segments' <Configure> comes while this window places its panes, and a divider
        moved then takes effect only for the pane after it: the segments would keep their
        width. So the Labels' divider waits for this window's own <Configure>.
        """
        height = self.segments.winfo_height()
        if self._segments_pending and height > 1 and height >= self.winfo_height():
            self._segments_pending = False
            self.segments.sashpos(0, round(height * SPLIT_SEGMENTS))
        width = self.winfo_width()
        if (self._labels_pending and self.labels_shown and width > 1
                and (event is None or event.widget is not self.segments)):
            self._labels_pending = False
            self.sashpos(0, round(width * self.split_labels))

    def _keep_labels_divider(self):
        """Keep where the Labels' divider is while the Labels are hidden, until ARES ends."""
        width = self.winfo_width()
        if not self._labels_pending and self.labels_shown and width > 1:
            self.split_labels = self.sashpos(0) / width
