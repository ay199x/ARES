# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Tools > Floating Point Representation: a 32-bit IEEE 754 value (single precision) in
hexadecimal, in binary as its sign, exponent and fraction, and in decimal, all editable.

Below the bits the window shows how they give the value. Not connected, the
tool is a converter: a value typed into one field shows in all of them.
Connected, it follows a register S0-S31 of the program: it shows the
register's bits after every refresh (Step, a slice of a run, Backstep, Reset,
a change of a register), and a value typed into it goes into the register
whenever values can be changed (a program is loaded and does not run or
wait). It installs no hooks: following a register costs a run nothing.
"""

import re
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from ...floats import format_single, parse_single
from ...runner import State
from ...settings import DEFAULT_FONT, installed_family
from ..style import FACE, TEXT, group
from ..widgets import Tooltip, px
from .frame import ToolModel, ToolWindow

FIELDS = ("hex", "sign", "exponent", "fraction", "decimal")
DIGITS = {"hex": 8, "sign": 1, "exponent": 8, "fraction": 23}     # characters of the fields
BINARY = ("sign", "exponent", "fraction")
_PLACES = {"sign": (31, 1), "exponent": (23, 8), "fraction": (0, 23)}  # (lowest bit, bits)
BIAS = 127
_HEX = re.compile(r"(?:0[xX])?([0-9a-fA-F]{1,8})", re.ASCII)
_BITS = re.compile(r"[01]+", re.ASCII)
SHOWN_TEXT = 16                 # characters of a wrong entry that its message repeats

WRONG = {
    "hex": "Hexadecimal: type 1 to 8 digits 0-9 or A-F (0x before them is allowed).",
    "sign": "Sign: type one bit, 0 for positive or 1 for negative.",
    "exponent": "Exponent: type 1 to 8 bits, each 0 or 1.",
    "fraction": "Fraction: type 1 to 23 bits, each 0 or 1.",
    "decimal": "Decimal: {text} is not a number. Type, for example, 1.5, -0.25, 6.02E23, "
               "Infinity or NaN.",
}
NOTES = {
    "normal": "The 1 before the point is not stored: it is the hidden bit.",
    "small": "Exponent 0: zero or a subnormal number, with 0 before the point.",
    "infinite": "Exponent all ones and fraction 0: infinity.",
    "nan": "Exponent all ones and fraction not 0: not a number (NaN).",
}
# What the window says it does, after Connect to ARM and while the program runs.
ALONE, NO_PROGRAM, WRITES, FOLLOWS = "alone", "no program", "writes", "follows"
SAY = {
    ALONE: "Type into any field and press Enter: every field then shows the new value.",
    NO_PROGRAM: "Connected: the tool follows {register} once a program is assembled.",
    WRITES: "Follows {register}: a value typed here and entered goes into {register} too.",
    FOLLOWS: "Follows {register} while the program runs or waits: the fields only show it.",
}
EXPLAINED = (                   # right of the parts they explain, from the top
    "the 32 bits in hexadecimal",
    "each hexadecimal digit stands for 4 bits",
    "the same bits: sign, exponent and fraction",
    "how the bits give the value",
)
TIPS = {
    "hex": "The 32 bits as 8 hexadecimal digits",
    "sign": "Sign (bit 31): 0 for positive, 1 for negative",
    "exponent": "Exponent (bits 30-23), stored with 127 added",
    "fraction": "Fraction (bits 22-0): the bits after the point",
    "decimal": "The value in decimal",
}
REGISTER_TIP = "The register the tool follows while it is connected"
REGISTERS = [f"S{n}" for n in range(32)]

# The window's parts, in design pixels; fonts in points.
FIELD_GAP = 10                  # between the sign, exponent and fraction fields
TRIANGLES = 34                  # from the hexadecimal digits down to the bits
ARROWS = 46                     # from the binary fields down to the formula
COLUMN_GAP = 24                 # between the fields and the explanations right of them
POINTER = 14                    # the arrow before an explanation
SIZES = {"hex": 24, "bits": 13, "formula": 11, "power": 8}
DECIMAL_CHARS = 16
HEX_COLOUR = "#FF0000"          # red: the hexadecimal digits and their triangles
DECIMAL_COLOUR = "#0000FF"      # blue: the value in decimal

HELP = """\
Floating Point Representation shows how a floating-point number is stored in 32 bits,
in the IEEE 754 single-precision format of the S registers: the bits in hexadecimal,
the same bits in binary as the sign, the exponent and the fraction, and the value in
decimal. Below the bits it shows how they give the value.

Change any of the five fields: type into it and press Enter, or move to another field
(Tab, or a click). Every field then shows the new value. What a field cannot take
rings the bell and stays in the field, which keeps the keyboard focus, with a note in
Instructions, until it is corrected; Escape puts back what the field showed. A field
left as it was keeps the value as it was: a NaN keeps its bits.

Hexadecimal: 1 to 8 digits 0-9 and A-F; 0x before them is allowed. Sign: one bit, 0
for a positive and 1 for a negative number. Exponent: up to 8 bits. Fraction: up to
23 bits. Fewer digits or bits than the field holds are filled up with zeros on the
left. Decimal: a number such as 1.5, -0.25 or 6.02E23, or Infinity or NaN, rounded to
the nearest single-precision value. Decimal values are written and read as in the
Coproc 10 tab.

How the bits give the value. Each hexadecimal digit stands for 4 bits, as the red
triangles show. For an exponent e from 1 to 254 the value is (-1)^sign × 2^(e - 127) ×
1.fraction: the 1 before the point, underlined, is not stored (the hidden bit). The
exponent 0 gives zero and the subnormal numbers: (-1)^sign × 2^(0 + 1 - 127) ×
0.fraction. The exponent 255 (all ones) gives infinity when the fraction is 0, and NaN
(not a number) otherwise.

Connect to ARM: the tool follows the register chosen at the bottom, S0 to S31, in the
assembled program. It shows the register's value after each Step, while the program
runs, and after Backstep, Reset and a change in the register tabs. While the program
does not run (before it starts, paused or finished), a value typed into the tool goes
into the register, and the Coproc 10 and Coproc 11 tabs show it at once (S2n and
S2n+1 are the halves of Dn). While the program runs or waits for input, the fields
only show the register. Connected before a program is assembled, or after its file was
closed, the tool waits for one and changes no register. Choosing another register shows
its value at once. Disconnect from ARM: the tool is a converter again, and the value
stays.

Reset sets the value to 0.0; while the tool follows a program that does not run, it
sets the register to 0.0 too, and while the program runs it changes nothing. The tool
stays connected when the program is assembled again or its file is closed. Close
closes the tool.

Following a register costs the program nothing while it runs: the tool reads the
register only when the window shows the program's state.
"""


# The fields' texts ------------------------------------------------------------------

def texts(bits):
    """The text of each field (FIELDS) for the 32 bits of a value."""
    binary = f"{bits:032b}"
    return {"hex": f"{bits:08X}", "sign": binary[0], "exponent": binary[1:9],
            "fraction": binary[9:], "decimal": format_single(bits)}


def parse(field, text, bits):
    """The value typed into field as 32 bits; None when the field cannot take text.

    A binary field replaces its own bits of bits; fewer bits or digits than a
    field holds are filled up with zeros on the left. The decimal field reads
    numbers as the register tabs do (ares.floats.parse_single).
    """
    text = text.strip()
    if field == "decimal":
        return parse_single(text)
    if field == "hex":
        match = _HEX.fullmatch(text)
        return int(match[1], 16) if match else None
    low, count = _PLACES[field]
    if not _BITS.fullmatch(text) or len(text) > count:
        return None
    return bits & ~(((1 << count) - 1) << low) & 0xFFFFFFFF | int(text, 2) << low


def wrong(field, text):
    """What the window says about text, which field cannot take."""
    text = text.strip()
    if len(text) > SHOWN_TEXT:
        text = text[:SHOWN_TEXT] + "..."
    return WRONG[field].format(text=text)


def formula(bits):
    """How the bits give the value, as the window writes it below them.

    Returns (parts, label, note). parts are (text, kind, roles): kind is ""
    for plain text, "power" for a raised power and "hidden" for the bit
    before the point that is not stored; roles name the fields whose arrows
    point at the part. label goes on the exponent's arrow, note (one of
    NOTES) below the formula.
    """
    sign, exponent, fraction = bits >> 31 & 1, bits >> 23 & 0xFF, bits & 0x7FFFFF
    if exponent == 0xFF:
        if fraction:
            return [("NaN", "", BINARY), (" =", "", ())], "255", NOTES["nan"]
        return ([("(-1)", "", ()), (str(sign), "power", ("sign",)), (" × ", "", ()),
                 ("Infinity", "", ("exponent", "fraction")), (" =", "", ())],
                "255", NOTES["infinite"])
    if exponent:
        power, hidden, label = exponent - BIAS, "1", f"{exponent} - {BIAS}"
    else:
        power, hidden, label = 1 - BIAS, "0", f"0 + 1 - {BIAS}"
    parts = [("(-1)", "", ()), (str(sign), "power", ("sign",)), (" × 2", "", ()),
             (str(power), "power", ("exponent",)), (" × ", "", ()),
             (hidden, "hidden", ("fraction",)), (f".{fraction:023b}", "", ("fraction",)),
             (" =", "", ())]
    return parts, label, NOTES["normal" if exponent else "small"]


# The model -------------------------------------------------------------------------

class FloatModel(ToolModel):
    """The value shown, as 32 bits, and the register (0-31: S0-S31) it follows.

    Connected to a program it takes the register's bits when it starts
    observing the program's machine and at each update(); it installs no
    hook. take() is a value typed in or set by Reset: the window writes it
    into the register when values can be changed.
    """

    def __init__(self):
        super().__init__()
        self.bits = 0
        self.register = 0

    def attach(self, machine):
        self.bits = machine.single(self.register)

    def detach(self, machine):
        self.update()

    def update(self):
        machine = self.machine
        if machine is None:
            return False
        bits = machine.single(self.register)
        changed = bits != self.bits
        self.bits = bits
        return changed

    def choose(self, register):
        """Follow Sregister from now on; True when the value shown changes."""
        self.register = register
        return self.update()

    def take(self, bits):
        """A value typed in (or set by Reset): bits."""
        self.bits = bits & 0xFFFFFFFF

    def reset(self):
        self.take(0)


# The window -------------------------------------------------------------------------

class FloatWindow(ToolWindow):
    """Tools > Floating Point Representation.

    The fields, the triangles from each hexadecimal digit to its 4 bits, the
    arrows from the binary fields to the formula and the explanations right
    of them are all on one canvas, placed from the fonts' sizes. Enter in a
    field, or the keyboard focus leaving it for another part of ARES, applies
    what was typed; a wrong entry rings the bell and stays, with the focus.
    """

    NAME = "Floating Point Representation"
    HEADING = "A 32-bit IEEE 754 number, bit by bit"
    HELP = HELP
    MODEL = FloatModel

    def build(self, body):
        window = self.window
        family = installed_family(DEFAULT_FONT, set(tkfont.families(window)))
        self.fonts = {name: tkfont.Font(root=window, family=family, size=size)
                      for name, size in SIZES.items()}
        self.fonts["hidden"] = tkfont.Font(root=window, family=family, size=SIZES["formula"],
                                           underline=True)
        self._closing = False
        self._error = None              # (field, message) while a field holds a wrong entry
        self._shown = {}                # the text each field showed last
        self._drawn = None              # the bits the formula shows
        self._mode_shown = None         # (mode, register, error) Instructions shows
        self._idle = None               # the display of the register, due while the run idles
        self._widths = {}               # (kind, text with 0 for 1) -> pixels
        self._pointed = None            # ({field: x where its arrow ends}, exponent's label)
        self._note = None               # the note below the formula
        canvas = self.canvas = tk.Canvas(body, background=FACE, borderwidth=0,
                                         highlightthickness=0, takefocus=False)
        canvas.grid(row=0, column=0, sticky="w")
        self.variables, self.entries, self.items, self.field_tips = {}, {}, {}, {}
        for name in FIELDS:
            font = self.fonts["hex" if name == "hex" else "bits"]
            colour = {"hex": HEX_COLOUR, "decimal": DECIMAL_COLOUR}.get(name, TEXT)
            variable = tk.StringVar(master=window)
            entry = ttk.Entry(canvas, textvariable=variable, font=font, foreground=colour,
                              width=DIGITS.get(name, DECIMAL_CHARS), justify="right")
            entry.bind("<Return>", lambda event, name=name: self._entered(name))
            entry.bind("<KP_Enter>", lambda event, name=name: self._entered(name))
            entry.bind("<Escape>", lambda event, name=name: self._escaped(name))
            entry.bind("<FocusOut>", lambda event, name=name: self._leaving(name), add="+")
            self.variables[name], self.entries[name] = variable, entry
            self.field_tips[name] = Tooltip(entry, TIPS[name])
        self.typed = tuple(self.entries.values())      # Return applies the field (_entered)
        self._lay_out()
        gap = px(body, 6)
        box = group(body, "Instructions", labelanchor="nw")
        box.grid(row=1, column=0, sticky="ew", pady=(gap, 0))
        self.instructions = ttk.Label(box, wraplength=int(canvas.cget("width")) - 2 * gap)
        self.instructions.pack(fill="x")
        row = ttk.Frame(body)
        row.grid(row=2, column=0, sticky="w", pady=(gap, 0))
        ttk.Label(row, text="Register followed while connected:").pack(side="left")
        self.register_box = ttk.Combobox(row, state="readonly", width=4, values=REGISTERS)
        self.register_box.current(0)
        self.register_box.pack(side="left", padx=(gap, 0))
        self.register_box.bind("<<ComboboxSelected>>", self._chosen)
        self.register_tip = Tooltip(self.register_box, REGISTER_TIP)
        window.bind("<Destroy>", self._destroyed, add="+")

    def _lay_out(self):
        """Place the fields and draw what does not change: the triangles, the labels of the
        binary fields, the explanations, and the arrows (moved with the formula)."""
        canvas, entries, fonts = self.canvas, self.entries, self.fonts
        label_font = tkfont.nametofont("TkDefaultFont", root=canvas)
        one = px(canvas, 1)
        # The binary fields side by side, the hexadecimal one centred above them; the
        # label "sign" is wider than its field.
        overhang = -(-(label_font.measure("sign") - entries["sign"].winfo_reqwidth()) // 2)
        self.left = x = max(0, overhang) + one
        self.columns = {}
        for name in BINARY:
            self.columns[name] = x
            x += entries[name].winfo_reqwidth() + px(canvas, FIELD_GAP)
        bits_width = x - px(canvas, FIELD_GAP) - self.left
        self.columns["hex"] = self.left + (bits_width - entries["hex"].winfo_reqwidth()) // 2
        hex_bottom = entries["hex"].winfo_reqheight()
        bits_top = hex_bottom + px(canvas, TRIANGLES)
        bits_bottom = bits_top + entries["sign"].winfo_reqheight()
        tops = {"hex": 0, "sign": bits_top, "exponent": bits_top, "fraction": bits_top}
        for name, top in tops.items():
            self.items[name] = canvas.create_window(self.columns[name], top,
                                                    window=entries[name], anchor="nw")
        # A triangle from each hexadecimal digit to its 4 bits.
        for digit in range(8):
            left = self._bit_span(4 * digit)[0] + one
            right = self._bit_span(4 * digit + 3)[1] - one
            canvas.create_polygon(self._digit_centre(digit), hex_bottom, left, bits_top,
                                  right, bits_top, fill=HEX_COLOUR, outline="",
                                  tags="triangle")
        labels_bottom = bits_bottom + px(canvas, 2) + label_font.metrics("linespace")
        self.starts = {}
        for name in BINARY:
            middle = self.columns[name] + entries[name].winfo_reqwidth() / 2
            canvas.create_text(middle, bits_bottom + px(canvas, 2), text=name, anchor="n",
                               font=label_font, fill=TEXT, tags="label")
            self.starts[name] = (middle, labels_bottom + px(canvas, 2))
        # The formula: its raised powers on top, the rest on the baseline below them. The
        # exponent's power has the room of the widest, so the parts after it stay in place.
        formula_font, power_font = fonts["formula"], fonts["power"]
        formula_top = labels_bottom + px(canvas, ARROWS)
        power_line = formula_top + power_font.metrics("ascent")
        self.baseline = power_line + round(formula_font.metrics("ascent") / 2)
        self.tops = {"": self.baseline - formula_font.metrics("ascent"),
                     "hidden": self.baseline - fonts["hidden"].metrics("ascent"),
                     "power": power_line - power_font.metrics("ascent")}
        self.power_room = self._measure("power", f"{1 - BIAS}")
        formula_bottom = self.baseline + formula_font.metrics("descent")
        self.arrow_end = formula_top - px(canvas, 2)
        shape = (px(canvas, 7), px(canvas, 8), px(canvas, 3))
        self.arrows = {name: canvas.create_line(0, 0, 0, 0, arrow="last", arrowshape=shape,
                                                width=one, fill=TEXT)
                       for name in BINARY}
        self.label_box = canvas.create_rectangle(0, 0, 0, 0, fill=FACE, width=0)
        self.label = canvas.create_text(0, 0, text="", font=label_font, fill=TEXT)
        self.note = canvas.create_text(self.left, formula_bottom + px(canvas, 4), text="",
                                       anchor="nw", font=label_font, fill=TEXT)
        # As many items as the longest formula has parts; a shorter one hides the rest.
        self.parts = [canvas.create_text(self.left, self.tops[""], text="", anchor="nw",
                                         font=formula_font, fill=TEXT, state="hidden",
                                         tags="formula")
                      for _ in formula(0)[0]]
        self._parts_shown = [None] * len(self.parts)    # (text, kind, x) of each item
        widest = self._place(formula(0)[0])[1] - self.left     # infinity and NaN are shorter
        notes = max(label_font.measure(note) for note in NOTES.values())
        # The explanations, right of the parts they explain, and the decimal field.
        right = self.left + max(bits_width, widest, notes) + px(canvas, COLUMN_GAP)
        middles = (hex_bottom / 2, (hex_bottom + bits_top) / 2, (bits_top + bits_bottom) / 2,
                   (labels_bottom + formula_top) / 2)
        pointer, room = px(canvas, POINTER), px(canvas, 6)
        for middle, text in zip(middles, EXPLAINED):
            canvas.create_line(right + pointer, middle, right, middle, arrow="last",
                               arrowshape=(px(canvas, 5), px(canvas, 5), px(canvas, 3)),
                               width=one, fill=TEXT, tags="explanation")
            canvas.create_text(right + pointer + room, middle, text=text, anchor="w",
                               font=label_font, fill=TEXT, tags="explanation")
        decimal = entries["decimal"]
        line_middle = self.baseline - formula_font.metrics("ascent") / 2
        decimal_top = round(line_middle - decimal.winfo_reqheight() / 2)
        self.columns["decimal"] = right
        self.items["decimal"] = canvas.create_window(right, decimal_top, window=decimal,
                                                     anchor="nw")
        width = right + max([pointer + room + label_font.measure(text) for text in EXPLAINED]
                            + [decimal.winfo_reqwidth()]) + px(canvas, 2)
        height = max(formula_bottom + px(canvas, 4) + label_font.metrics("linespace"),
                     decimal_top + decimal.winfo_reqheight())
        canvas.configure(width=width, height=height)

    def _character(self, name, index):
        """(left, right) of character index of field name, as it is drawn."""
        entry = self.entries[name]
        width = self.fonts["hex" if name == "hex" else "bits"].measure("0")
        inset = (entry.winfo_reqwidth() - DIGITS[name] * width) / 2
        left = self.columns[name] + inset + index * width
        return left, left + width

    def _bit_span(self, index):
        """(left, right) of bit index of the 32, the sign bit first, in the binary fields."""
        if index == 0:
            return self._character("sign", 0)
        if index <= 8:
            return self._character("exponent", index - 1)
        return self._character("fraction", index - 9)

    def _digit_centre(self, digit):
        left, right = self._character("hex", digit)
        return (left + right) / 2

    def _measure(self, kind, text):
        """Pixels of text in the font of a formula part of kind. The fonts are monospace:
        every digit is as wide as 0, so few widths are kept."""
        key = kind, text.replace("1", "0")
        width = self._widths.get(key)
        if width is None:
            width = self._widths[key] = self.fonts[kind or "formula"].measure(text)
        return width

    def _place(self, parts):
        """Where the parts of a formula go: ([x of each], x after the last, {role: (left,
        right) of the parts an arrow points at})."""
        places, spans, x = [], {}, self.left
        for text, kind, roles in parts:
            width = self._measure(kind, text)
            places.append(x)
            for role in roles:
                left, right = spans.get(role, (x, x))
                spans[role] = (min(left, x), max(right, x + width))
            if kind == "power" and "exponent" in roles:
                width = max(width, self.power_room)
            x += width
        return places, x, spans

    def _draw_formula(self, bits):
        """Write how bits give the value, point the arrows at its parts, label the exponent's.

        Only what changed is drawn again: while the tool follows a register,
        mostly the bits of the fraction.
        """
        canvas = self.canvas
        parts, label, note = formula(bits)
        places, _, spans = self._place(parts)
        for index, item in enumerate(self.parts):
            new = (*parts[index][:2], places[index]) if index < len(parts) else None
            old, self._parts_shown[index] = self._parts_shown[index], new
            if new == old:
                continue
            if new is None:
                canvas.itemconfigure(item, text="", state="hidden")
                continue
            text, kind, x = new
            if old is None or old[1:] != new[1:]:
                canvas.coords(item, x, self.tops[kind])
                canvas.itemconfigure(item, font=self.fonts[kind or "formula"])
            canvas.itemconfigure(item, text=text, state="normal")
        ends = {name: (left + right) / 2 for name, (left, right) in spans.items()}
        if (ends, label) != self._pointed:
            self._pointed = ends, label
            for name, item in self.arrows.items():
                canvas.coords(item, *self.starts[name], ends[name], self.arrow_end)
            (x0, y0), x1 = self.starts["exponent"], ends["exponent"]
            canvas.itemconfigure(self.label, text=label)
            canvas.coords(self.label, (x0 + x1) / 2, (y0 + self.arrow_end) / 2)
            left, top, right, bottom = canvas.bbox(self.label)
            canvas.coords(self.label_box, left - px(canvas, 2), top, right + px(canvas, 2),
                          bottom)
        if note != self._note:
            self._note = note
            canvas.itemconfigure(self.note, text=note)
        self._drawn = bits

    # Showing ---------------------------------------------------------------------------

    def show(self):
        """Show the model's value in every field (what was typed and not applied goes),
        how its bits give it, and what the tool does now."""
        model = self.model
        self._error = None
        shown = self._shown = texts(model.bits)
        for name, variable in self.variables.items():
            if variable.get() != shown[name]:
                variable.set(shown[name])
        if model.bits != self._drawn:
            self._draw_formula(model.bits)
        if self.register_box.current() != model.register:
            self.register_box.current(model.register)
        self._show_mode()

    def refresh(self):
        """Show the register followed, after a step, a slice of a run, Reset or a change.

        Once the program runs the fields only follow: what was typed and not
        applied goes. While it runs, the register is shown when the window is
        idle, not right after each slice of the run: drawing there would leave
        Tk no idle time to redraw the window before the next slice.
        """
        following = self._mode() == FOLLOWS
        if following and self._mode_shown[0] == FOLLOWS:
            if self._idle is None:
                self._idle = self.window.after_idle(self._follow)
        elif self.model.update() or following:
            self.show()
        else:
            self._show_mode()

    def _follow(self):
        """The window is idle during a run: show the register followed if it changed."""
        self._idle = None
        if self.window is not None and self.model.update():
            self.show()

    def _mode(self):
        """What the tool does now: ALONE, NO_PROGRAM, WRITES or FOLLOWS (see SAY)."""
        model = self.model
        if not model.connected:
            return ALONE
        if model.machine is None:
            return NO_PROGRAM
        runner = self.app.runner
        if runner is not None and runner.state in (State.RUNNING, State.WAITING):
            return FOLLOWS
        return WRITES

    def _show_mode(self):
        """The fields can be typed into unless the program runs; Instructions says what the
        tool does, or what is wrong with an entry."""
        mode = self._mode()
        shown = (mode, self.model.register, self._error)
        if shown == self._mode_shown:
            return
        self._mode_shown = shown
        state = ["readonly"] if mode == FOLLOWS else ["!readonly"]
        for entry in self.entries.values():
            entry.state(state)
        text = (self._error[1] if self._error is not None
                else SAY[mode].format(register=REGISTERS[self.model.register]))
        self.instructions.configure(text=text)

    # Typing ----------------------------------------------------------------------------

    def _entered(self, name):
        self._apply(name)
        return "break"              # not the window's Return, which presses a button

    def _focus_path(self):
        """The path of the widget with the keyboard focus; "" while ARES has none."""
        return str(self.window.tk.call("focus"))

    def _leaving(self, name):
        """The keyboard focus is leaving a field. Where it goes is known once the changes of
        the moment are done: on the way to another ARES window no widget has it for a while."""
        self.app.root.after_idle(self._left, name)

    def _left(self, name):
        """The keyboard focus left a field: Tab or a click elsewhere in ARES applies it.

        When ARES itself loses the focus (another program comes to the front)
        the field waits, as it is.
        """
        if self._closing or self.window is None or not self.entries[name].winfo_exists():
            return                  # the window is going
        focus = self._focus_path()
        if focus and focus != str(self.entries[name]):
            self._apply(name)

    def _apply(self, name):
        """Take what was typed into field name; False when it is wrong: the bell rings, and
        the field keeps the text and the keyboard focus.

        While another field holds a wrong entry, the focus only passed through
        this one (the wrong field took it back): nothing changes.
        """
        if self._error is not None and self._error[0] != name:
            return False
        text = self.variables[name].get().strip()
        if text == self._shown[name]:
            # Left as it was: the value stays as it was (a NaN keeps its bits).
            if self._error is not None or self.variables[name].get() != text:
                self.show()
            return True
        bits = parse(name, text, self.model.bits)
        entry = self.entries[name]
        if bits is None:
            entry.bell()
            self._error = (name, wrong(name, text))
            self._show_mode()
            entry.focus_set()
            return False
        self._take(bits)
        return True

    def _take(self, bits):
        """A value typed in or set by Reset: every field shows it, and while the tool follows
        a program that does not run, it goes into the register as an edit in Coproc 10
        does."""
        model = self.model
        model.take(bits)
        if model.machine is not None:
            self.app.change_single(model.register, model.bits)
        self.show()

    def _escaped(self, name):
        """Escape puts back what a changed field showed; in a field left as it was it closes
        the tool, as elsewhere in the window."""
        if self._error is None and self.variables[name].get().strip() == self._shown[name]:
            return None
        self.show()
        return "break"

    def _chosen(self, event=None):
        """Another register was chosen: connected, the tool shows its value at once."""
        register = self.register_box.current()
        if register >= 0 and register != self.model.register:
            self.model.choose(register)
            self.show()

    # The buttons -----------------------------------------------------------------------

    def reset(self):
        """The value 0.0, also in the register while the tool follows a program that does
        not run; while the program runs the fields only follow it."""
        if self._mode() != FOLLOWS:
            self._take(0)

    def close(self):
        self._closing = True        # the fields' focus leaves without applying them
        super().close()

    def _destroyed(self, event):
        """The window goes, by Close or with the main window: nothing is left to run for it."""
        if event.widget is self.window and self._idle is not None:
            self.window.after_cancel(self._idle)
            self._idle = None


WINDOW = FloatWindow
