# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Registers tab (R0 to R12, SP, LR, PC, CPSR and SPSR) and the floating-point tabs:
Coproc 10 (S0 to S31) and Coproc 11 (D0 to D31), each with FPSCR as its last row."""

import re
import tkinter as tk
from functools import lru_cache
from tkinter import font as tkfont
from tkinter import ttk

from ..floats import format_double, format_single, parse_double, parse_single
from ..machine import INITIAL_CPSR, INITIAL_SP
from ..syscalls import to_signed
from .menubar import MENU_BAR_CLASS
from .table import Column, Mark, Row, Table, column_width
from .widgets import px

NAMES = [f"R{n}" for n in range(13)] + ["SP", "LR", "PC"]
ROWS = NAMES + ["CPSR", "SPSR"]
CPSR_ROW, SPSR_ROW = len(NAMES), len(NAMES) + 1
# The flags the Registers show for CPSR and SPSR: (letter, bit, meaning).
PSR_FLAGS = (("N", 31, "negative"), ("Z", 30, "zero"), ("C", 29, "carry"),
             ("V", 28, "overflow"), ("I", 7, "IRQ interrupts disabled"))
MODES = {0x10: ("USR", "User"), 0x11: ("FIQ", "FIQ"), 0x12: ("IRQ", "IRQ"),
         0x13: ("SVC", "Supervisor"), 0x16: ("MON", "Monitor"), 0x17: ("ABT", "Abort"),
         0x1A: ("HYP", "Hypervisor"), 0x1B: ("UND", "Undefined"), 0x1F: ("SYS", "System")}
NO_SPSR = (0x10, 0x1F)      # User and System modes have no SPSR
SINGLES = [f"S{n}" for n in range(32)]
DOUBLES = [f"D{n}" for n in range(32)]          # Dn is S2n+1:S2n for D0 to D15
FPSCR_ROW = 32              # FPSCR is the last row of both floating-point tabs
FPSCR_FLAGS = (("N", 31, "negative"), ("Z", 30, "zero"), ("C", 29, "carry"),
               ("V", 28, "overflow"))
# The cumulative exception flags: shown after the rounding mode while they are set.
FPSCR_EXCEPTIONS = (("IOC", 0, "invalid operation"), ("DZC", 1, "divide by zero"),
                    ("OFC", 2, "overflow"), ("UFC", 3, "underflow"), ("IXC", 4, "inexact"),
                    ("IDC", 7, "input denormal"))
ROUNDING = (("RN", "round to nearest"), ("RP", "round towards plus infinity"),
            ("RM", "round towards minus infinity"), ("RZ", "round towards zero"))
CHANGED = "#B5F03C"         # rows changed by the last step or run: a retro lime green
# The three register tables' own sizes, larger than the Execute tab's, in design pixels.
ROW_HEIGHT = 21             # a row with its line, and the headings
TEXT_SIZE = 14.25           # the cells' text
HEADING_SIZE = 10.67        # the headings' text
# Characters the Value column makes room for: (hexadecimal, as numbers). The
# longest numbers are -1.17549435E-38 and -2.2250738585072014E-308.
SINGLE_CHARS = (10, 15)
DOUBLE_CHARS = (18, 24)
_NUMBER = re.compile(r"([+-]?)(0[xX][0-9a-fA-F]+|[0-9]+)", re.ASCII)
_BITS = re.compile(r"0[xX]([0-9a-fA-F]+)", re.ASCII)
_single_text = lru_cache(maxsize=1024)(format_single)    # most values stay the same
_double_text = lru_cache(maxsize=1024)(format_double)


def register_fonts(root, pane_font):
    """(cells, headings): the fonts of the register tables, in the families of the other tables.

    Made once the window has its look: the headings' family comes from it.
    """
    heading = tkfont.nametofont("TkHeadingFont", root=root)
    return (tkfont.Font(root=root, family=pane_font.actual("family"), size=-px(root, TEXT_SIZE)),
            tkfont.Font(root=root, family=heading.actual("family"), size=-px(root, HEADING_SIZE)))


def format_value(value, hexadecimal):
    """0x and 8 lowercase hex digits, or a signed decimal number."""
    return f"0x{value:08x}" if hexadecimal else str(to_signed(value))


def parse_value(text):
    """A typed 32-bit value: decimal with an optional sign, or 0x hexadecimal; None if invalid."""
    match = _NUMBER.fullmatch(text.strip())
    if match is None:
        return None
    sign, digits = match.groups()
    base = 16 if digits[:2] in ("0x", "0X") else 10
    digits = (digits[2:] if base == 16 else digits).lstrip("0") or "0"
    if len(digits) > (8 if base == 16 else 10):     # too large; Python refuses over 4,300 digits
        return None
    value = int(digits, base)
    if sign == "-":
        value = -value
    return value & 0xFFFFFFFF if -0x80000000 <= value <= 0xFFFFFFFF else None


def parse_vfp_value(text, double):
    """The bits typed for an S register, or a D register with double; None if invalid.

    0x and hexadecimal digits are the bits themselves; a number (``1.5``,
    ``-2e-3``, ``inf``, ``nan``) becomes the nearest single or double.
    """
    match = _BITS.fullmatch(text.strip())
    if match is None:
        return (parse_double if double else parse_single)(text)
    bits = int(match[1], 16)
    return bits if bits < 1 << (64 if double else 32) else None


def psr_marks(value, register):
    """N, Z, C, V, I and the mode of a CPSR or SPSR value (register names which)."""
    marks = [Mark(letter, bool(value >> bit & 1), f"{letter} (bit {bit}): {meaning}")
             for letter, bit, meaning in PSR_FLAGS]
    mode = value & 0x1F
    short, name = MODES.get(mode, ("?", None))
    tip = f"{name} mode" if name else "Not a processor mode"
    how = "MSR or CPS" if register == "CPSR" else "MSR"
    marks.append(Mark(short, True, f"{tip} (bits 4-0: 0x{mode:02x}). It cannot be changed "
                                   f"here: programs change it with {how}.", space=True))
    return tuple(marks)


def fpscr_marks(value):
    """N, Z, C, V and the rounding mode of an FPSCR value, then its exception flags that are set.

    A set exception flag shows in black after the rounding mode
    ("NZCV RN DZC"); one that is clear is not shown at all.
    """
    marks = [Mark(text, bool(value >> bit & 1), f"{text} (bit {bit}): {meaning}")
             for text, bit, meaning in FPSCR_FLAGS]
    short, meaning = ROUNDING[value >> 22 & 3]
    marks.append(Mark(short, True, f"Rounding mode (bits 23-22): {meaning}. Programs change "
                                   "it with VMSR.", space=True))
    marks += [Mark(text, True, f"{text} (bit {bit}): {meaning}", space=True)
              for text, bit, meaning in FPSCR_EXCEPTIONS if value >> bit & 1]
    return tuple(marks)


def fpscr_mark_bit(value, number):
    """The FPSCR bit that mark number of fpscr_marks(value) shows; None for the rounding mode."""
    if number < len(FPSCR_FLAGS):
        return FPSCR_FLAGS[number][1]
    shown = [bit for _, bit, _ in FPSCR_EXCEPTIONS if value >> bit & 1]
    number -= len(FPSCR_FLAGS) + 1
    return shown[number] if 0 <= number < len(shown) else None


def fpscr_tip(value):
    """The tooltip of FPSCR's row: each cumulative exception flag, its meaning and its value."""
    lines = ["Cumulative exception flags (shown after the rounding mode while set):"]
    lines += [f"{text} (bit {bit}): {meaning} = {value >> bit & 1}"
              for text, bit, meaning in FPSCR_EXCEPTIONS]
    return "\n".join(lines)


def single_tip(n):
    """The tooltip of Sn's row: which half of which D register it is."""
    return f"S{n}: {'high' if n % 2 else 'low'} half of D{n // 2}"


def double_tip(n):
    """The tooltip of Dn's row: the S registers that are its halves (D0 to D15 only)."""
    if n >= 16:
        return "D16-D31 have no S registers"
    return f"D{n} = S{2 * n} (low half) and S{2 * n + 1} (high half)"


def fpscr_flags_chars(value):
    """Characters of the letters fpscr_marks(value) shows ("NZCV RN DZC": 11)."""
    return len(" ".join(["NZCV"] + [mark.text for mark in fpscr_marks(value)[len(FPSCR_FLAGS):]]))


class _RegisterTable(tk.Frame):
    """A table of registers whose column "value" holds their values.

    Rows whose value differs from their value at mark() are highlighted.
    While editable is true, a double-click on a value (not of a FIXED row),
    or Enter or F2 on a selected row, opens a field over it with the value
    selected; Enter, or a click elsewhere in the window, calls on_edit(name,
    value), which puts the value into the machine and returns True; a wrong
    value rings the bell and the field stays open, brought into view with the
    keyboard focus: on_show() puts the table in front, its row is scrolled
    to. Escape closes the field with the value unchanged. The field moves
    with its row when the table scrolls. on_field() is called when the field
    opens or closes, on_blocked() when a value or flag cannot be changed now.
    Subclasses give ROWS, FIXED, values(), _cells(index, value) and
    _parse(index, text).
    """

    ROWS = ()
    FIXED = ()                  # rows whose values are changed only through their flags

    def __init__(self, master, settings, columns, font, heading_font):
        super().__init__(master)
        self.settings = settings
        self.baseline = None            # the values at mark()
        self.editable = False
        self.on_edit = self.on_field = self.on_blocked = self.on_show = None
        self.editor = None              # the field of the value being changed
        self._editing = None            # (row, canvas window item, text and value at the start)
        self.table = Table(self, columns, font, heading_font, row_height=ROW_HEIGHT,
                           heading_height=ROW_HEIGHT)
        self.table.pack(fill="both", expand=True)
        self.table.on_double_click = self._double_clicked
        self.table.on_activate = self.request_edit
        self.table.on_scroll = self._place_field
        self.table.set_rows(len(self.ROWS), self._row)

    def values(self):
        raise NotImplementedError

    def mark(self):
        """From now on highlight the rows whose values change."""
        self.baseline = self.values()
        self.refresh()

    def unmark(self):
        """Highlight no row."""
        self.baseline = None
        self.refresh()

    def refresh(self):
        self.table.refresh()

    def _row(self, index):
        value = self.values()[index]
        changed = self.baseline is not None and self.baseline[index] != value
        return Row(self._cells(index, value), CHANGED if changed else "",
                   tip=self._tip(index, value))

    def _tip(self, index, value):
        """The tooltip of a row (none)."""
        return ""

    def _fit_contents(self, column_id, chars):
        """Make a column room for chars characters (it may stretch beyond)."""
        table = self.table
        column = next(column for column in table.columns if column.id == column_id)
        width = column_width(self, table.font, chars, column.heading, table.heading_font)
        if column.base != width and not column.dragged:
            table.set_width(column_id, width)

    # Editing --------------------------------------------------------------

    def _double_clicked(self, index, column):
        if column == "value":
            self.request_edit(index)

    def request_edit(self, index):
        """The user asks to change the value of row index: a field opens if it can be changed.

        A FIXED row's value is changed only through its flags: nothing happens.
        """
        if index in self.FIXED:
            return
        if not self.editable:
            if self.on_blocked is not None:
                self.on_blocked()
        else:
            self.edit(index)

    def edit(self, index):
        """Open a field over the value of row index (not a FIXED row) while values can change.

        A field open on another row is left first, as by a click elsewhere.
        """
        if not self.leave_field() or not self.editable or index in self.FIXED:
            return
        table = self.table
        table.see(index)
        if table.cell_box(index, "value") is None:
            return
        text = self._row(index).cells[[c.id for c in table.columns].index("value")]
        editor = self.editor = tk.Entry(table.body, font=table.font, justify="right",
                                        relief="solid", borderwidth=1, highlightthickness=0)
        editor.insert(0, text)
        editor.select_range(0, "end")
        editor.icursor("end")
        # Not the window's tag: its shortcuts (Run, Paste ...) wait until the field is closed.
        editor.bindtags((str(editor), "Entry", "all"))
        editor.bind("<Return>", lambda e: self.commit(refocus=True))
        editor.bind("<KP_Enter>", lambda e: self.commit(refocus=True))
        editor.bind("<Escape>", lambda e: self.cancel_edit(refocus=True))
        editor.bind("<FocusOut>", self._focus_left)
        item = table.body.create_window(0, 0, window=editor, anchor="nw")
        self._editing = (index, item, text, self.values()[index])
        self._place_field()
        editor.focus_set()
        if self.on_field is not None:
            self.on_field()

    def _place_field(self):
        """Keep the open field over its value when the rows or the columns move."""
        if self._editing is None:
            return
        index, item = self._editing[:2]
        table = self.table
        x0 = 0
        for column in table.columns:
            if column.id == "value":
                break
            x0 += column.width
        # A row scrolled out of view takes its field along, out of sight.
        table.body.coords(item, x0, (index - table.top) * table.row_height)
        table.body.itemconfigure(item, width=column.width, height=table.row_height)

    def _focus_path(self):
        """The path of the widget with the keyboard focus; "" while ARES has none."""
        return str(self.tk.call("focus"))

    def _focus_left(self, event=None):
        """The keyboard focus left the field: a click elsewhere in ARES applies the value.

        When ARES itself loses the focus (another program comes to the front),
        or the menu bar takes it while a menu is used, the field waits, as it
        is: a command chosen from the menu applies it first.
        """
        if self.editor is None:
            return
        focus = self._focus_path()
        if (focus and focus != str(self.editor)
                and self.tk.call("winfo", "class", focus) != MENU_BAR_CLASS):
            self.commit()

    def pressed_elsewhere(self):
        """A mouse press elsewhere in the window applies the value, once.

        A press that gave the keyboard focus to another widget applies it as
        the focus leaves the field (_focus_left); here the press of a control
        that takes no focus does, and the focus goes back to the table.
        """
        if self.editor is not None and self._focus_path() in ("", str(self.editor)):
            self.commit(refocus=True)

    def leave_field(self):
        """Apply the value of the open field (something else was clicked or chosen).

        True when no field is open any more; False when the value is wrong:
        the bell rang and the field keeps the focus.
        """
        if self._editing is None:
            return True
        self.commit()
        return self._editing is None

    def commit(self, refocus=False):
        """Take the typed value; a wrong one sounds the bell and leaves the field open.

        refocus (Enter) gives the keyboard focus back to the table.
        """
        if self._editing is None:
            return "break"
        index, _, start_text, start_value = self._editing
        editor = self.editor
        text = editor.get().strip()
        # Text left as it was keeps the value as it was (a NaN keeps its bits).
        value = start_value if text == start_text else self._parse(index, text)
        if value is None or self.on_edit is None or not self.on_edit(self.ROWS[index], value):
            editor.bell()
            self._show_field()
            return "break"
        self.cancel_edit()          # on_edit may have closed it already, showing the value
        if refocus:
            self.table.body.focus_set()
        return "break"

    def _show_field(self):
        """The value was wrong and the field stays open: bring it into view, with the
        keyboard focus (a click elsewhere took it, perhaps on another tab)."""
        if self.on_show is not None:
            self.on_show()
        self.table.see(self._editing[0])
        self.editor.focus_set()

    def field_command(self, name):
        """Cut, Copy, Paste or Select All in the open field; False when no field is open."""
        editor = self.editor
        if editor is None:
            return False
        if name == "select_all":
            editor.select_range(0, "end")
            editor.icursor("end")
            return True
        if name == "paste":
            try:
                text = editor.clipboard_get()
            except tk.TclError:                 # nothing to paste
                return True
            if editor.selection_present():
                editor.delete("sel.first", "sel.last")
            editor.insert("insert", text)
            return True
        # Cut or copy as Tk's own bindings do: Tk counts a character beyond U+FFFF as two,
        # so its indices do not fit the text Python gets.
        editor.event_generate("<<Cut>>" if name == "cut" else "<<Copy>>")
        return True

    def cancel_edit(self, refocus=False):
        """Close the field without changing the value (refocus: give the table the focus)."""
        if self._editing is None:
            return
        editor, item = self.editor, self._editing[1]
        self.editor = self._editing = None
        self.table.body.delete(item)
        editor.destroy()
        if refocus:
            self.table.body.focus_set()
        if self.on_field is not None:
            self.on_field()


class RegistersPane(_RegisterTable):
    """Name | Number | Value | Flags for R0 to R12, SP, LR, PC, CPSR and SPSR.

    CPSR and SPSR (the SPSR of the current mode; User and System modes have
    none: "-") are shown in hexadecimal, followed by their flags N, Z, C, V
    and I, black when set, and the mode. A double-click on a flag calls
    on_toggle(name, bit) while values can be changed; the mode cannot be
    changed here.
    """

    ROWS = ROWS
    FIXED = (CPSR_ROW, SPSR_ROW)

    def __init__(self, master, settings, font, heading_font):
        self.registers = [0] * 13 + [INITIAL_SP, 0, 0]
        self.cpsr = INITIAL_CPSR
        self.spsr = 0
        self.on_toggle = None
        # Name, Number, Value and Flags share the width equally.
        def width(chars, heading):
            return column_width(master, font, chars, heading, heading_font)
        super().__init__(master, settings, [
            Column("name", "Name", width(4, "Name"), stretch=True),
            Column("number", "Number", width(2, "Number"), "e", stretch=True),
            Column("value", "Value", width(11, "Value"), "e", stretch=True),
            Column("flags", "Flags", width(9, "Flags"), marks=len(PSR_FLAGS) + 1, stretch=True),
        ], font, heading_font)
        self.table.on_mark = self._mark_double_clicked

    def values(self):
        """The value of every row: R0 to PC, CPSR, then SPSR (None when the mode has none)."""
        spsr = None if self.cpsr & 0x1F in NO_SPSR else self.spsr
        return self.registers + [self.cpsr, spsr]

    def set_values(self, registers, cpsr, spsr):
        """Show new values: registers holds R0 to R15; spsr is the current mode's SPSR."""
        self.cancel_edit()
        self.registers = list(registers)
        self.cpsr = cpsr
        self.spsr = spsr
        self.refresh()

    def _cells(self, index, value):
        name = ROWS[index]
        if index < CPSR_ROW:
            return name, str(index), format_value(value, self.settings.hex_values), ()
        if value is None:
            return name, "", "-", (Mark("-", True, "User and System modes have no SPSR"),)
        return name, "", f"0x{value:08x}", psr_marks(value, name)

    def _parse(self, index, text):
        return parse_value(text)

    def _mark_double_clicked(self, index, column, number):
        """A double-click on a flag of CPSR or SPSR changes it (not on the mode)."""
        if index not in self.FIXED or number >= len(PSR_FLAGS) or self.values()[index] is None:
            return
        if not self.editable:
            if self.on_blocked is not None:
                self.on_blocked()
        elif self.leave_field() and self.on_toggle is not None:
            self.on_toggle(ROWS[index], PSR_FLAGS[number][1])


class CoprocPane(_RegisterTable):
    """Name | Value | Flags for S0 to S31 (Coproc 10) or D0 to D31 (Coproc 11), then FPSCR.

    S2n and S2n+1 are the low and high halves of Dn (D0 to D15). Values are
    numbers (``1.5``), or their bits in hexadecimal when Values in
    Hexadecimal is on. A typed value is a number or, with 0x, the bits.
    FPSCR's row shows its value in hexadecimal and, as Flags, N Z C V, the
    rounding mode and the exception flags that are set; a double-click on one
    of them, but not on the rounding mode, calls on_toggle("FPSCR", bit).
    """

    FIXED = (FPSCR_ROW,)

    def __init__(self, master, settings, font, heading_font, double):
        self.double = double
        self.ROWS = (DOUBLES if double else SINGLES) + ["FPSCR"]
        self.doubles = [0] * len(DOUBLES)
        self.fpscr = 0
        self.on_toggle = None
        # Name, Value and Flags share the width equally.
        def width(chars, heading):
            return column_width(master, font, chars, heading, heading_font)
        super().__init__(master, settings, [
            Column("name", "Name", width(5, "Name"), stretch=True),
            Column("value", "Value", width(self._value_chars(settings), "Value"), "e",
                   stretch=True),
            Column("flags", "Flags", width(fpscr_flags_chars(0), "Flags"),
                   marks=len(FPSCR_FLAGS) + 1 + len(FPSCR_EXCEPTIONS), stretch=True),
        ], font, heading_font)
        self.table.on_mark = self._mark_double_clicked

    def _value_chars(self, settings):
        return (DOUBLE_CHARS if self.double else SINGLE_CHARS)[not settings.hex_values]

    def _mark_double_clicked(self, index, column, number):
        """A double-click on a flag of FPSCR changes it (not on the rounding mode)."""
        bit = fpscr_mark_bit(self.fpscr, number) if index == FPSCR_ROW else None
        if bit is None:
            return
        if not self.editable:
            if self.on_blocked is not None:
                self.on_blocked()
        elif self.leave_field() and self.on_toggle is not None:
            self.on_toggle("FPSCR", bit)

    def values(self):
        """The bits of every row: D0 to D31 or S0 to S31 (the halves of D0 to D15), then FPSCR."""
        if self.double:
            registers = list(self.doubles)
        else:
            registers = [double >> half & 0xFFFFFFFF for double in self.doubles[:16]
                         for half in (0, 32)]
        return registers + [self.fpscr]

    def set_values(self, doubles, fpscr):
        """Show new values: doubles holds the bits of D0 to D31."""
        self.cancel_edit()
        self.doubles = list(doubles)
        self.fpscr = fpscr
        self.refresh()

    def refresh(self):
        # The columns make room for the values as they are written now, and for
        # the exception flags that are set.
        self._fit_contents("value", self._value_chars(self.settings))
        self._fit_contents("flags", fpscr_flags_chars(self.fpscr))
        super().refresh()

    def _cells(self, index, value):
        if index == FPSCR_ROW:
            return "FPSCR", f"0x{value:08x}", fpscr_marks(value)
        if self.double:
            text = f"0x{value:016x}" if self.settings.hex_values else _double_text(value)
        else:
            text = f"0x{value:08x}" if self.settings.hex_values else _single_text(value)
        return self.ROWS[index], text, ()

    def _tip(self, index, value):
        if index == FPSCR_ROW:
            return fpscr_tip(value)
        return double_tip(index) if self.double else single_tip(index)

    def _parse(self, index, text):
        return parse_vfp_value(text, self.double)
