# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Inside the control unit: the window of ARM X-Ray for the Control block.

The control unit has two parts. The Decoder finds the instruction's row in the
truth table of the Main Decoder from Op, Funct and Op2 (bits 7:4, which tell MUL
and MLA from data processing, BLX from BX, a shift by a register: its ShiftReg,
and the halfword and signed transfers, 1SH1, whose Funct2, bit 22, tells an
immediate offset from a register), its row in the ALU Decoder's from Mul, cmd
and S when ALUOp is 1 (cmd 1000 and 1010 without S are MOVW and MOVT), and
makes PCS in the PC Logic. Besides the tables it sends Size and Signed to the
data memory. The flags register gives its C to the ALU as CarryIn
for ADC, SBC and RSC. The
Conditional Logic checks the condition against the flags and lets PCS, RegW,
MemW, the Decoder's SVC and FlagW through AND gates only when it holds
(CondEx 1), so that an instruction whose condition fails writes nothing and
calls no service.

Bits that are no field of the instruction tell the decoders nothing: the In
rows show "-" for them, and the PC Logic's comparison of Rd with 15 stays gray
for an instruction without an Rd field. For LDM, STM, PUSH and POP the pass
counter takes the register list and gives each pass its register (PassReg),
which the PC Logic compares with 15 in place of Rd, its offset and Hold. A
number that comes in on a wire shows its bits: Rd and Ra with the register's
name after them, as the decoder reads the field, PassReg as its four bits.

The control unit works in two steps of the film. In the first, the fields of
the word come in, the decoders' rows light and then the gates answer. In the
second, near the end, the flags register takes the ALU's flags, or keeps its
own when FlagWrite is 00. The window is drawn whole for each instruction; then
the truth tables only change their colours and light their rows in place, and
only the other parts that change are drawn again (PARTS), which keeps each
picture of the film quick. The parts wait in the calm blue, light while they
work and keep a lighter tint after; the flags register rests on the green once
it has taken flags that FlagWrite lets in.
"""

from collections import namedtuple

from ... import xray, xray_film
from .xray_inside import (DONE, DONE_FILL, FIELD, IDLE, IDLE_STATE, INK, INSIDE, LOOKS, MARK,
                          UNUSED, WORKING_FILL, InsideWindow, look_of, register_bits,
                          signal_colour)
from .xray_look import field_colour

HEADING = "Decoder and Conditional Logic"
ABOUT = ("The Decoder makes the signals from the fields of the word; the Conditional\n"
         "Logic lets them write only if the condition holds.")
OUTSIDE = "This instruction does not use this datapath: no row of the decoders lights for it."
NOTHING = "No instruction is shown."
NOT_YET = "(not here yet)"
NO_FIELD = "-"                      # an input of the In row made of bits that are no field

DECODE_AT, CHECK_AT = 0.25, 0.6     # when, in the decoding step, the rows light; the gates answer
WRITE_AT = 0.5                      # when, in the step that writes the flags, the register does

TOP = 24                            # where the tables' titles stand
ROW = 12                            # the height of a row of a table
LIFT = 0.5                          # a row's words above its middle: room for descenders
DOWN = 110                          # the parts under the tables, below the ALU Decoder's rows
PC_LOGIC_Y = 342                    # the PC Logic's title, under the Main Decoder
PASS_BOX = (520, 292 + DOWN, 752, 334 + DOWN)   # the pass counter of LDM, STM, PUSH and POP
MARGIN = 8                          # the room at the window's left and right
MIN_GAP, MAX_GAP = 3, 8             # the room between two columns of a table
WIDE_GAP = 9                        # between a table's inputs and its outputs
BETWEEN = 14                        # between the two tables

# The Main Decoder's rows: the class, its name, and the inputs Op, Funct5, Funct2, Funct0 and
# Op2 it needs. Op2 (Instr 7:4) is 1001 for MUL and MLA, whose Op and Funct are those of DP reg,
# and 1SH1 for the halfword and signed transfers (the LDRH rows hold LDRSB and LDRSH too), whose
# Funct2, bit 22, is 1 for an immediate offset.
MAIN_ROWS = (
    (xray.DP_REGISTER, "DP reg", "00", "0", "X", "X", "X"),
    (xray.DP_IMMEDIATE, "DP imm", "00", "1", "X", "X", "X"),
    (xray.STORE_IMMEDIATE, "STR", "01", "0", "X", "0", "X"),
    (xray.LOAD_IMMEDIATE, "LDR", "01", "0", "X", "1", "X"),
    (xray.BRANCH, "B", "10", "1", "X", "X", "X"),
    (xray.LOAD_REGISTER, "LDR reg", "01", "1", "X", "1", "X"),
    (xray.STORE_REGISTER, "STR reg", "01", "1", "X", "0", "X"),
    (xray.BRANCH_LINK, "BL", "10", "1", "X", "X", "X"),
    (xray.BRANCH_EXCHANGE, "BX", "00", "0", "X", "0", "0001"),
    (xray.SYSTEM_CALL, "SVC", "11", "X", "X", "X", "X"),
    (xray.LOAD_MULTIPLE, "LDM", "10", "0", "X", "1", "X"),
    (xray.STORE_MULTIPLE, "STM", "10", "0", "X", "0", "X"),
    (xray.MULTIPLY, "MUL", "00", "0", "X", "X", "1001"),
    (xray.BRANCH_LINK_EXCHANGE, "BLX", "00", "0", "X", "0", "0011"),
    (xray.NO_OPERATION, "NOP", "00", "1", "X", "0", "X"),
    (xray.MOVE_16, "MOVW/T", "00", "1", "X", "0", "X"),
    (xray.LOAD_HALF_IMMEDIATE, "LDRH imm", "00", "0", "1", "1", "1SH1"),
    (xray.LOAD_HALF_REGISTER, "LDRH reg", "00", "0", "0", "1", "1SH1"),
    (xray.STORE_HALF_IMMEDIATE, "STRH imm", "00", "0", "1", "0", "1011"),
    (xray.STORE_HALF_REGISTER, "STRH reg", "00", "0", "0", "0", "1011"),
)
MAIN_INPUTS = ("Op", "Funct5", "Funct2", "Funct0", "Op2")
MAIN_NOTE = ("Op2 tells MUL, BX, BLX and the LDRH rows (1SH1: LDRSB, LDRSH too) apart;\n"
             "NOP has funct 110010, MOVW 110000 and MOVT 110100.")
ALU_INPUTS = ("Mul", "cmd", "S")
ALU_OUTPUTS = ("ALUControl", "FlagW", "NoWrite")
ALU_NOTE = "a/b: a with S 0, b with S 1."
ALU_OP_0 = ("ALUOp 0: ALUControl 0000 (ADD), FlagW 00", "ALUOp 0, U 0 (offset down): 0001 (SUB)")
ALU_BX = 0b1001                     # with S = 0 BX and BLX; with S = 1 TEQ

# What each condition needs, in words.
RULES = {"EQ": "Z = 1", "NE": "Z = 0", "CS": "C = 1", "CC": "C = 0", "MI": "N = 1",
         "PL": "N = 0", "VS": "V = 1", "VC": "V = 0", "HI": "C = 1 and Z = 0",
         "LS": "C = 0 or Z = 1", "GE": "N = V", "LT": "N ≠ V", "GT": "Z = 0 and N = V",
         "LE": "Z = 1 or N ≠ V"}
MORE = ("Size", "Signed", "StoreSrc", "Shift", "Link", "AdrSrc", "ShiftReg")  # besides tables
MORE_XY = (532, 462 + DOWN)         # where the line that lists them begins
MORE_NAME = "Other Decoder signals:"
MORE_ABOUT = "The signals the Decoder makes from bits of the word, besides the tables' own"

# The Conditional Logic: where its parts stand.
LOGIC_Y = 306 + DOWN                # the Conditional Logic's title
CHECK_BOX = (100, 324 + DOWN, 300, 372 + DOWN)
FLAGS_BOX = (100, 416 + DOWN, 250, 464 + DOWN)
COND_Y, ALU_FLAGS_Y = 348 + DOWN, 440 + DOWN    # the wires that come in from the left
CARRY_Y = 452 + DOWN                # CarryIn leaves the flags register here, to the ALU
FLAGS_X = 170                       # the flags go up from the register to the check
BUS_X = 340                         # CondEx goes down to the gates here
GATE_X = 420                        # the gates' inputs
OUT_X = 676                         # where the signals leave, at the right
# The AND gates: the output, the gate's middle and size, where CondEx comes in, and the inputs
# from the Decoder with where they come in. SVC is the Decoder's own: 1 for an SVC. BaseW opens
# the base write port. FlagWrite comes last: CondEx goes down to it, and its output goes back to
# the flags register.
GATES = tuple((name, y + DOWN, size, condex + DOWN, tuple((i, at + DOWN) for i, at in inputs))
              for name, y, size, condex, inputs in (
                  ("PCSrc", 343, 18, 348, (("PCS", 338),)),
                  ("RegWrite", 374, 28, 374, (("RegW", 364), ("NoWrite", 384))),
                  ("MemWrite", 404, 18, 409, (("MemW", 399),)),
                  ("BaseWrite", 430, 18, 435, (("BaseW", 425),)),
                  ("Syscall", 456, 18, 461, (("SVC", 451),)),
                  ("FlagWrite", 482, 18, 487, (("FlagW", 477),))))
LOOP_X, LOOP_Y = 520, 498 + DOWN    # FlagWrite goes back to the flags register's enable
ENABLE_X = 176

Table = namedtuple("Table", "title inputs outputs values kinds lines chosen note tag")
"""A truth table: inputs and outputs name the columns after the first, which holds the rows'
names; values are the instruction's inputs for the In row (None: none), in the colours of kinds;
lines are the rows, (name, cells), or (words, None) for a line of words; line number chosen is
the instruction's (None: none); note goes under the table, and tag on the chosen line's items."""

Stage = namedtuple("Stage", "arrived decoded checked lit flags_in writing written")
"""What the window shows: the fields have come in, the decoders' rows are chosen, the gates
have answered, which part works now ("rows", "check", "flags" or ""), the ALU's flags have
come in, the step that writes the flags plays, and the flags register holds what it took."""

IDLE_STAGE = Stage(False, False, False, "", False, False, False)
DONE_STAGE = Stage(True, True, True, "", True, False, True)
# The parts of the window that are drawn again on their own when the Stage changes what they
# show: the PC Logic, the Conditional Logic, and the flags register. The truth tables are not
# drawn again: _style_tables() changes them in place.
PARTS = ("pc", "logic", "flags")


def tables_key(stage):
    """What the truth tables show of stage: they are styled again when this changes."""
    return stage.arrived, stage.decoded, stage.lit in ("rows", "check")


def part_key(part, stage):
    """What part (of PARTS) shows of stage: the part is drawn again when this changes."""
    if part == "pc":
        return tables_key(stage)
    if part == "logic":
        return stage.arrived, stage.decoded, stage.checked, stage.lit == "check"
    return (stage.arrived, stage.checked, stage.flags_in, stage.lit == "flags", stage.writing,
            stage.written)


def control_steps(film):
    """The numbers of the steps of film in which the control unit works."""
    return [number for number, step in enumerate(film.steps)
            if any(name == "Control" for name, _ in step.lights)
            or any(gate.block == "Control" for gate in step.gates)]


def stage_of(film, moment, state):
    """The Stage of the window at moment of film; state is the block's phase()."""
    if not film.steps or state == IDLE_STATE:
        return IDLE_STAGE
    if state == DONE:
        return DONE_STAGE
    marks = control_steps(film)
    if not marks:
        return IDLE_STAGE
    number, fraction = film.at(moment)
    alu = next((index for index, step in enumerate(film.steps)
                if any(move.net == "ALUFlags" for move in step.moves)), None)
    flags_in = alu is not None and number > alu
    if number == marks[0]:
        decoded, checked = fraction >= DECODE_AT, fraction >= CHECK_AT
        lit = "check" if checked else "rows" if decoded else ""
        return Stage(True, decoded, checked, lit, flags_in, False, False)
    if number == marks[-1]:
        return Stage(True, True, True, "flags", flags_in, True, fraction >= WRITE_AT)
    return Stage(True, True, True, "", flags_in, False, False)


def alu_rows():
    """The rows of the ALU Decoder: (Mul, cmd, name, S, ALUControl, FlagW, NoWrite), with S and
    FlagW as a/b where they differ with S; cmd 1001 has two rows: BX and BLX with S 0, TEQ with S
    1; so have cmd 1000 and 1010: MOVW and MOVT with S 0, TST and CMP with S 1. With Mul 1, the
    rows of MUL and MLA."""
    rows = []
    for cmd, (control, flag_write, no_write) in xray.ALU_DECODER.items():
        if cmd == ALU_BX:
            rows.append(("0", cmd, "BX", "0", control, flag_write, no_write))
            rows.append(("0", cmd, "TEQ", "1") + xray.TEQ_ROW)
        elif no_write == "1":           # CMP, CMN and TST only set the flags: S is 1
            rows.append(("0", cmd, xray_film.CMD_NAMES[cmd], "1", control, flag_write, no_write))
            if cmd in xray.MOVE_DECODER:    # with S 0: MOVW and MOVT
                name = "MOVW" if cmd == 0b1000 else "MOVT"
                rows.append(("0", cmd, name, "0") + xray.MOVE_DECODER[cmd])
        else:
            rows.append(("0", cmd, xray_film.CMD_NAMES[cmd], "0/1", control, f"00/{flag_write}",
                         no_write))
    for cmd, (control, flag_write, no_write) in xray.MUL_DECODER.items():
        rows.append(("1", cmd, xray_film.ALU_WORDS[control], "0/1", control, f"00/{flag_write}",
                     no_write))
    return rows


def condition_check(trace):
    """The condition check as the window says it: the rule, and what the flags make of it."""
    cond = trace.word >> 28
    name = xray.CONDITIONS[cond]
    condex = trace.signals["CondEx"]
    if name == "AL":
        return "AL always holds", f"AL: always -> CondEx {condex}"
    read = ", ".join(f"{flag} = {trace.flags >> xray.FLAG_BITS[flag] & 1}"
                     for flag in xray.CONDITION_FLAGS[cond])
    return f"{name} holds when {RULES[name]}", f"{name}: {read} -> CondEx {condex}"


def flags_effect(signals):
    """What FlagWrite does to the flags register, in a few words."""
    flag_write = signals["FlagWrite"]
    if flag_write == "11":
        return "all four written"
    if flag_write == "10":
        return "N, Z and C written" if signals["ShiftC"] == "1" else "N and Z written"
    return "kept: FlagWrite is 00"


def funct_field(trace, high, low=None):
    """True when the bits high to low of trace's word all lie in its funct fields
    (xray_film.fields_of()): the bits of the funct that the instruction has."""
    low = high if low is None else low
    fields = [(top, bottom) for _, top, bottom, kind in xray_film.fields_of(trace)
              if kind == "funct"]
    return all(any(bottom <= bit <= top for top, bottom in fields) for bit in range(low, high + 1))


def field_bits(trace, high, low=None):
    """The bits high to low of trace's word in binary, or NO_FIELD when they are not all funct
    bits of the instruction."""
    low = high if low is None else low
    if not funct_field(trace, high, low):
        return NO_FIELD
    return f"{trace.word >> low & (1 << high - low + 1) - 1:0{high - low + 1}b}"


def main_table(trace):
    """The Main Decoder as a Table, with the row of trace's class chosen (None: no trace). An
    input made of bits that are no field of the instruction shows NO_FIELD (Funct0 of B, BL and
    SVC, bit 20, lies in imm24)."""
    lines = [(name, (op, funct5, funct2, funct0, op2) + xray.MAIN_DECODER[kind])
             for kind, name, op, funct5, funct2, funct0, op2 in MAIN_ROWS]
    values = chosen = None
    if trace is not None:
        word = trace.word
        op2 = f"{word >> 4 & 0xF:04b}" if "Op2" in xray_film.present(trace) else NO_FIELD
        values = (f"{word >> 26 & 3:02b}", field_bits(trace, 25), field_bits(trace, 22),
                  field_bits(trace, 20), op2)
        chosen = next(number for number, row in enumerate(MAIN_ROWS) if row[0] == trace.kind)
    return Table("Main Decoder", MAIN_INPUTS, xray.MAIN_SIGNALS, values,
                 ("op", "funct", "funct", "funct", "op"), lines, chosen, MAIN_NOTE, "main")


def alu_table(trace):
    """The ALU Decoder as a Table. When ALUOp is 1 the row of cmd is chosen, showing S and FlagW
    as they are; when it is 0, one of the two lines above the rows: ADD, or SUB for a load or
    store with a negative offset. An input made of bits that are no field of the instruction
    (cmd and S of B, BL and SVC) shows NO_FIELD."""
    rows = alu_rows()
    lines = [(ALU_OP_0[0], None), (ALU_OP_0[1], None)]
    values = chosen = None
    if trace is not None:
        word, signals = trace.word, trace.signals
        cmd, mul = word >> 21 & 0xF, signals["Mul"]
        values = (mul, field_bits(trace, 24, 21), field_bits(trace, 20))
        if trace.kind not in (xray.DP_REGISTER, xray.DP_IMMEDIATE, xray.BRANCH_EXCHANGE,
                              xray.BRANCH_LINK_EXCHANGE, xray.MULTIPLY, xray.MOVE_16):
            values = (mul, NO_FIELD, NO_FIELD)  # its bits 24:20 are no cmd and no S
        if trace.kind in (xray.SYSTEM_CALL, xray.NO_OPERATION):
            chosen = None               # ALUOp is X: the system does the work, or nothing is done
        elif signals["ALUOp"] == "1":       # cmd 1000, 1001, 1010: the row of its S
            s_bit = str(word >> 20 & 1)
            chosen = 2 + next(number for number, row in enumerate(rows)
                              if row[:2] == (mul, cmd) and (mul == "1" or row[3] in (s_bit, "0/1")))
        else:
            chosen = 1 if signals["ALUControl"] == xray.ALU_SUB else 0
    for number, (mul, cmd, name, s_bit, control, flag_write, no_write) in enumerate(rows):
        cells = (mul, f"{cmd:04b}", s_bit, control, flag_write, no_write)
        if chosen == number + 2:
            signals = trace.signals
            cells = (mul, f"{cmd:04b}", values[2], signals["ALUControl"], signals["FlagW"],
                     signals["NoWrite"])
        lines.append((name, cells))
    return Table("ALU Decoder", ALU_INPUTS, ALU_OUTPUTS, values, ("control", "funct", "funct"),
                 lines, chosen, ALU_NOTE, "alu")


class ControlWindow(InsideWindow):
    """Inside the control unit (see the module's description)."""

    BLOCK = "Control"
    TITLE = "Inside the Control Unit"
    HEADING = HEADING
    ABOUT = ABOUT
    SIZE = (840, 508 + DOWN)            # larger than the others: its tables have more rows
    shown = None                        # the Stage the canvas shows
    trace = None                        # the instruction it shows, inside the datapath, or None

    def __init__(self, tool):
        self.measured = {}              # (text, font) -> its width: see _width()
        super().__init__(tool)

    def rezoomed(self):
        self.measured = {}              # the fonts have new sizes: measure again

    def key_of(self, film, moment, context, state, fraction):
        """The window is drawn whole only for a new film or instruction; within a film,
        animate() styles the tables again and draws again the parts whose Stage changed."""
        return film, context

    def redraw(self, film, moment, context, state, fraction):
        trace = context.trace
        inside = trace is not None and bool(trace.signals)
        self.trace = trace if inside else None
        self.resting = trace is None    # no instruction: every part rests in the calm blue
        self.shown = stage_of(film, moment, state) if inside else IDLE_STAGE
        self.heading(MARGIN, 6, None if inside else NOTHING if trace is None else OUTSIDE)
        self.in_rows = []               # each table's In row: ([its items], values, kinds)
        self.chosen_rows = []           # each table's chosen line: (frame, [(item, lit, not)])
        self._decoders(self.trace)
        self._style_tables(self.shown)
        for part in PARTS:
            self._draw_part(part)

    def animate(self, film, moment, context, state, fraction):
        if self.trace is None:
            return
        now = stage_of(film, moment, state)
        if now == self.shown:           # the rows light or the gates answer within the step
            return
        before, self.shown = self.shown, now
        if tables_key(now) != tables_key(before):
            self._style_tables(now)
        for part in PARTS:
            if part_key(part, now) != part_key(part, before):
                self._draw_part(part)

    def _draw_part(self, part):
        """Draw part (of PARTS) again; each of its items has the part's name as a tag."""
        canvas = self.canvas
        canvas.delete(part)
        canvas.addtag_all("before")     # what is drawn already does not belong to the part
        trace, stage = self.trace, self.shown
        if part == "pc":
            self._pc_logic(trace, stage)
        elif part == "logic":
            self._conditional_logic(trace, stage)
        else:
            self._flags(trace, stage)
        canvas.addtag_all(part)
        canvas.dtag("before", part)
        canvas.dtag("all", "before")

    # The picture ------------------------------------------------------------------------

    def _width(self, text, font):
        """The width of text in font, in design pixels; the window's fonts change only with its
        zoom (rezoomed()), so each text is measured once at each zoom."""
        width = self.measured.get((text, font))
        if width is None:
            width = self.measured[text, font] = self.fonts[font].measure(text) / self.k
        return width

    def ink(self, kind, value):
        """The colour of an input of a table: its field's, as the instruction table under the
        picture has it, or a signal's (Mul) for "control"."""
        return signal_colour(value) if kind == "control" else field_colour(kind)

    def _wire(self, points, value, shown, arrow="last", **options):
        """A one-bit or control wire: red for 1, gray for 0, dashed for X; gray when not used."""
        if not shown:
            return self.line(points, fill=IDLE, arrow=arrow, **options)
        dash = (4, 3) if value is not None and "X" in value else ""
        return self.line(points, fill=signal_colour(value), width=1.8, arrow=arrow, dash=dash,
                         **options)

    # The decoders ---------------------------------------------------------------------------

    def _decoders(self, trace):
        """The truth tables of the Main Decoder and the ALU Decoder, side by side, as they are
        before the fields come in; _style_tables() gives them the Stage's look."""
        main, alu = main_table(trace), alu_table(trace)
        main_widths, alu_widths = self._widths(main), self._widths(alu)
        # The room the two tables leave goes to the gaps between their columns (6: the frames
        # of the chosen rows stand out 3 on each side).
        room = (self.SIZE[0] - 2 * MARGIN - 6 - BETWEEN - 2 * WIDE_GAP
                - sum(main_widths) - sum(alu_widths))
        gap = max(MIN_GAP, min(MAX_GAP, room / (len(main_widths) + len(alu_widths) - 4)))
        right = self._table(MARGIN, main, main_widths, gap)
        self._table(right + BETWEEN, alu, alu_widths, gap)

    def _style_tables(self, stage):
        """Give the truth tables the look of stage: their words in ink once the fields have
        come, the In rows' values (NOT_YET before), and the chosen lines lit once the rows are
        decoded, lit while the rows work and done after; a lit line's items have the tag
        "chosen"."""
        canvas = self.canvas
        canvas.itemconfigure("tableink", fill=INK if stage.arrived else IDLE)
        for items, values, kinds in self.in_rows:
            for number, (item, value, kind) in enumerate(zip(items, values, kinds)):
                if stage.arrived:
                    canvas.itemconfigure(item, text=value, font=self.fonts["code"],
                                         fill=IDLE if value == NO_FIELD else self.ink(kind, value))
                else:                   # one line in the first column says that none has come
                    canvas.itemconfigure(item, text="" if number else NOT_YET,
                                         font=self.fonts["small"], fill=IDLE)
        lit = stage.decoded
        for frame, items in self.chosen_rows:
            working = lit and stage.lit in ("rows", "check")
            canvas.itemconfigure(frame, state="normal" if lit else "hidden",
                                 fill=WORKING_FILL if working else DONE_FILL)
            for item, on, off in items:
                canvas.itemconfigure(item, **(on if lit else off))
            for item in [frame] + [item for item, _, _ in items]:
                if lit:
                    canvas.addtag_withtag("chosen", item)
                else:
                    canvas.dtag(item, "chosen")

    def _widths(self, table):
        """The widths of a Table's columns: the rows' names, then one for each signal."""
        rows = [cells for _, cells in table.lines if cells is not None]
        widths = [max(self._width(name, "bold") for name in
                      [name for name, cells in table.lines if cells is not None] + ["In"])]
        for index, header in enumerate(table.inputs + table.outputs):
            cells = [row[index] for row in rows]
            if table.values is not None and index < len(table.values):
                cells.append(table.values[index])
            widths.append(max([self._width(header, "small")]
                              + [self._width(cell, "code") for cell in cells]))
        return widths

    def _table(self, left, table, widths, gap):
        """Draw a Table with its top left corner at (left, TOP), its columns widths wide and
        gap apart, as it is before the fields come in; give its right edge. What the Stage
        changes is kept for _style_tables(): the words in ink once the fields have come (tag
        "tableink"), the items of the In row's values, and the chosen line: its frame, hidden
        until it lights, and its words, whose items have the table's tag."""
        inputs, values, kinds, chosen = table.inputs, table.values, table.kinds, table.chosen
        xs, x = [], left
        for index, width in enumerate(widths):
            xs.append(x)
            x += width + (WIDE_GAP if index == len(inputs) else gap)
        right = max([x - gap] + [left + self._width(words, "small")
                                 for words, cells in table.lines if cells is None])
        ink = ("tableink",)
        self.text(left, TOP, table.title, font="bold", fill=IDLE, tags=ink)
        for header, x in zip(inputs + table.outputs, xs[1:]):
            self.text(x, TOP + 16, header, fill=IDLE, tags=ink)
        self.line([(left, TOP + 30), (right, TOP + 30)], fill=IDLE, width=1, tags=ink)
        y = TOP + 31
        self.text(left, y + ROW / 2, "In", anchor="w", font="bold", fill=IDLE, tags=ink)
        if values is not None:          # their texts come from _style_tables()
            items = [self.text(x, y + ROW / 2, "", anchor="w") for x in xs[1:1 + len(values)]]
            self.in_rows.append((items, values, kinds))
        y += ROW
        for number, (name, cells) in enumerate(table.lines):
            height = ROW + (2 if cells is None else 0)   # a sentence's brackets hang lower
            if number == chosen:
                self._chosen_line(left, right, y, name, cells, xs[1:], table, height)
            else:
                self.text(left, y + height / 2 - LIFT, name, anchor="w", fill=IDLE)
                for cell, x in zip(cells or (), xs[1:]):
                    self.text(x, y + ROW / 2 - LIFT, cell, anchor="w", font="code", fill=IDLE)
            y += height
        self.text(left, y + 2, table.note, fill=IDLE, tags=ink)
        return right

    def _chosen_line(self, left, right, y, name, cells, xs, table, height=ROW):
        """The chosen line of table at y, height high: its frame, and its words with how each
        looks lit and not, for _style_tables()."""
        tags = (table.tag,)
        frame = self.box(left - 3, y, right + 3, y + height, outline=INK, width=1.4,
                         fill=DONE_FILL, state="hidden", tags=tags)
        item = self.text(left, y + height / 2 - LIFT, name, anchor="w", fill=IDLE, tags=tags)
        if cells is None:
            items = [(item, {"fill": INK}, {"fill": IDLE})]
        else:
            items = [(item, {"fill": INK, "font": self.fonts["bold"]},
                      {"fill": IDLE, "font": self.fonts["small"]})]
            for index, (cell, x) in enumerate(zip(cells, xs)):
                if index < len(table.inputs):
                    colour = self.ink(table.kinds[index], cell)
                else:
                    colour = INK if "/" in cell else signal_colour(cell)
                item = self.text(x, y + ROW / 2 - LIFT, cell, anchor="w", font="code", fill=IDLE,
                                 tags=tags)
                items.append((item, {"fill": colour}, {"fill": IDLE}))
        self.chosen_rows.append((frame, items))

    def _pc_logic(self, trace, stage):
        """PCS = (Rd = 15 AND RegW) OR Branch, as a comparison and two gates. Bits 15:12 of an
        instruction without an Rd field (B, BL, BX, SVC, CMP, CMN, TST) are no Rd: they are not
        used by it, so the comparison gets nothing and stays gray, and the AND gate makes no
        value from it."""
        ink = INK if stage.arrived else IDLE
        y = PC_LOGIC_Y
        self.text(MARGIN, y, "PC Logic", font="bold", fill=ink)
        self.text(MARGIN + self._width("PC Logic", "bold") + 10, y,
                  "PCS = (Rd = 15 AND RegW) OR Branch", fill=ink)
        passes = trace is not None and trace.kind in xray.MULTIPLE
        has_rd = trace is not None and ("Rd" in xray_film.present(trace) or passes)
        known = has_rd and stage.arrived
        decoded = trace is not None and stage.decoded
        compared = has_rd and decoded
        rd = trace.word >> 12 & 0xF if has_rd else 0
        name = "Rd"
        multiply = trace is not None and trace.kind == xray.MULTIPLY
        if passes:                      # the pass counter's register stands for Rd
            rd, name = trace.values["PassReg"], "PassReg"
        elif multiply:                  # bits 15:12 of MLA are Ra; MUL writes Instr 19:16
            name = "Ra"
        if multiply and not has_rd:     # under the comparison, clear of its box
            self.text(6, y + 39, "15:12: no field of MUL,\nwhich writes 19:16", anchor="nw",
                      fill=IDLE)
        elif trace is not None and not has_rd:
            self.text(6, y + 39, "Rd: " + UNUSED.replace(" by ", "\nby ", 1), anchor="nw",
                      fill=IDLE)
        else:                           # PassReg: its bits; a field: its bits and its register
            said = f"{name} {register_bits(rd)}" if passes else f"{name} {rd:04b} (R{rd})"
            self.text(6, y + 26.5, said if known else name, anchor="sw",
                      fill=self.colour("Rd") if known else IDLE)
        self.line([(4, y + 28), (84, y + 28)], fill=self.colour("Rd") if known else IDLE,
                  width=2.4 if known else 1.2, arrow="last")
        lighting = stage.lit in ("rows", "check")
        compare = LOOKS[look_of(has_rd, working=compared and lighting, done=compared,
                                resting=self.resting)]
        gates = LOOKS[look_of(trace is not None, working=decoded and lighting, done=decoded,
                              resting=self.resting)]
        self.box(84, y + 19, 128, y + 37, outline=compare.outline, fill=compare.fill)
        self.text(106, y + 28, "= 15", anchor="center", fill=compare.words)
        s = trace.signals if trace is not None else {}
        is_15 = both = None
        if has_rd:
            is_15 = "1" if rd == 15 else "0"
            both = "1" if is_15 == "1" and s.get("RegW") == "1" else "0"
        self._wire([(128, y + 28), (190, y + 28)], is_15, compared, arrow="none")
        self._input(190, y + 40, "RegW", s.get("RegW"), decoded)
        self.gate("AND", 190, y + 34, outline=gates.outline, fill=gates.fill, size=22)
        self._wire([(212, y + 34), (283, y + 34)], both, compared, arrow="none")
        self._input(283, y + 46, "Branch", s.get("Branch"), decoded)
        self.gate("OR", 280, y + 40, outline=gates.outline, fill=gates.fill, size=22)
        self._wire([(302, y + 40), (350, y + 40)], s.get("PCS"), decoded)
        if compared:
            self.text(160, y + 26, is_15, anchor="s", font="code", fill=signal_colour(is_15))
            self.text(248, y + 32, both, anchor="s", font="code", fill=signal_colour(both))
        self._value(354, y + 40, "PCS", s.get("PCS"), decoded)
        self._pass_counter(trace, stage)

    def _pass_counter(self, trace, stage):
        """The pass counter: for LDM, STM, PUSH and POP it takes the register list and gives each
        pass its register (PassReg), its offset and Hold, which keeps the PC until the last pass;
        any other instruction does not use it."""
        left, top, right, bottom = PASS_BOX
        passes = trace is not None and trace.kind in xray.MULTIPLE
        known = passes and stage.arrived
        decoded = passes and stage.decoded
        part = LOOKS[look_of(passes, working=decoded and stage.lit in ("rows", "check"),
                             done=decoded, resting=self.resting)]
        self.box(left, top, right, bottom, outline=part.outline, fill=part.fill,
                 width=1.4 if decoded else 1)
        self.text(left + 6, top + 2, "Pass Counter", font="bold",
                  fill=INK if known else part.words)
        if not passes:
            if trace is not None:
                self.text(left + 6, top + 15, "Not used by this instruction.", fill=IDLE)
            return
        v, s = trace.values, trace.signals
        listed = f"{v['List']:016b}"
        self.text(left + 92, top + 2, f"List {listed}" if known else "List", font="code",
                  fill=self.colour("List") if known else part.words)
        if not decoded:
            return
        self.text(left + 6, top + 15, f"pass {trace.number} of {trace.count}: "
                  f"PassReg R{v['PassReg']}, Offset 0x{v['Offset']:X}", fill=INK)
        hold = s.get("Hold", "0")
        said = "keeps the PC" if hold == "1" else "the PC goes on"
        self.text(left + 6, top + 28, f"Hold {hold}: {said}", fill=signal_colour(hold))

    def _input(self, x, y, name, value, shown, bubble=False):
        """A gate's input at (x, y) with its name and value written at its left."""
        end = x - 5 if bubble else x
        self._wire([(x - 8, y), (end, y)], value, shown, arrow="none")
        if bubble:
            r = self.d(2.5)
            cx, cy = self.xy(x - 2.5, y)
            self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=FIELD,
                                    outline=INK if shown else IDLE, width=self.d(1.2))
        self._value(x - 10, y, name, value, shown, anchor="e")

    def _value(self, x, y, name, value, shown, anchor="w"):
        """A signal's name and value, in the signal's colour (only its name when not known)."""
        if shown and value is not None:
            self.text(x, y, f"{name} {value}", anchor=anchor, fill=signal_colour(value))
        else:
            self.text(x, y, name, anchor=anchor, fill=IDLE)

    # The Conditional Logic --------------------------------------------------------------

    def _conditional_logic(self, trace, stage):
        """The condition check, CondEx down to the AND gates, the gates with what comes in from
        the Decoder and what leaves them, and the Decoder's other signals."""
        ink = INK if stage.arrived else IDLE
        self.text(MARGIN, LOGIC_Y, "Conditional Logic", font="bold", fill=ink)
        s = trace.signals if trace is not None else {}
        decoder = dict(s)
        if trace is not None:           # the Decoder's SVC: 1 for an SVC, whatever its condition
            decoder["SVC"] = "1" if trace.kind == xray.SYSTEM_CALL else "0"
        known = trace is not None and stage.arrived
        decoded = trace is not None and stage.decoded
        checked = trace is not None and stage.checked
        # Cond comes in and goes to the condition check.
        cond = trace.word >> 28 if trace is not None else 0
        self.text(6, COND_Y - 3, f"Cond {cond:04b}" if known else "Cond", anchor="sw",
                  fill=self.colour("Cond") if known else IDLE)
        self.line([(4, COND_Y), (CHECK_BOX[0], COND_Y)],
                  fill=self.colour("Cond") if known else IDLE, width=2.4 if known else 1.2,
                  arrow="last")
        left, top, right, bottom = CHECK_BOX
        working = stage.lit == "check"
        logic = LOOKS[look_of(trace is not None, working=checked and working, done=checked,
                              resting=self.resting)]
        self.box(left, top, right, bottom, outline=logic.outline, fill=logic.fill,
                 width=1.4 if checked else 1)
        self.text(left + 6, top + 3, "Condition Check", font="bold",
                  fill=INK if known else logic.words)
        if trace is not None:
            rule, check = condition_check(trace)
            self.text(left + 6, top + 17, rule if known else "", fill=INK)
            self.text(left + 6, top + 31, check if checked else "", fill=INK)
        # CondEx, down to every gate.
        condex = s.get("CondEx")
        self._wire([(right, COND_Y), (GATE_X, COND_Y)], condex, checked, arrow="last")
        self._value(right + 4, COND_Y - 3, "CondEx", condex, checked, anchor="sw")
        last = GATES[-1][3]
        self._wire([(BUS_X, COND_Y), (BUS_X, last), (GATE_X, last)], condex, checked,
                   arrow="last")
        self._dot(BUS_X, COND_Y, condex, checked)
        for name, y, size, condex_y, inputs in GATES[1:-1]:
            self._wire([(BUS_X, condex_y), (GATE_X, condex_y)], condex, checked, arrow="last")
            self._dot(BUS_X, condex_y, condex, checked)
        # The gates.
        for name, y, size, condex_y, inputs in GATES:
            self.gate("AND", GATE_X, y, outline=logic.outline, fill=logic.fill, size=size)
            for signal, input_y in inputs:
                value = decoder.get(signal)
                self._input(GATE_X, input_y, signal, value, decoded, bubble=signal == "NoWrite")
            out = s.get(name)
            if name == "FlagWrite":
                points = [(GATE_X + size, y), (LOOP_X, y), (LOOP_X, LOOP_Y), (ENABLE_X, LOOP_Y),
                          (ENABLE_X, FLAGS_BOX[3])]
                self._wire(points, out, checked)
                self._value(GATE_X + size + 6, y - 3, name, out, checked, anchor="sw")
            else:
                self._wire([(GATE_X + size, y), (OUT_X, y)], out, checked)
                self._value(OUT_X + 4, y, name, out, checked)
        self._more(trace, stage)

    def _dot(self, x, y, value, shown):
        r = self.d(2.2)
        cx, cy = self.xy(x, y)
        colour = signal_colour(value) if shown else IDLE
        self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=colour, outline=colour)

    def _flags(self, trace, stage):
        """The flags register: the ALU's flags come in from the left, FlagWrite opens it, and
        what it holds goes up to the condition check. It waits until its step, works in it when
        it opens, and rests on the green from the clock edge that writes it; one that stays
        closed is done then."""
        known = trace is not None and stage.arrived
        checked = trace is not None and stage.checked
        flags_in = trace is not None and stage.flags_in
        left, top, right, bottom = FLAGS_BOX
        writes = trace is not None and trace.signals["FlagWrite"] != "00"
        lit = stage.lit == "flags" and writes
        name = look_of(trace is not None, working=lit, done=stage.written, resting=self.resting)
        if stage.written and writes:
            name = "changed"
        part = LOOKS[name]
        self.box(left, top, right, bottom, outline=INK if known else part.outline,
                 fill=part.fill, width=1.4 if stage.writing and writes else 1)
        self.text(left + 6, top + 3, "Flags (NZCV)", font="bold",
                  fill=INK if known else part.words)
        if trace is not None:
            old = xray.flag_text(trace.flags)
            new = xray.flag_text(trace.new_flags)
            if stage.written and writes:
                held = f"{new} (was {old})"
            else:
                held = old
            self.text(left + 6, top + 18, held, anchor="nw", font="code_bold",
                      fill=self.colour("ALUFlags") if known else part.words)
            if stage.written:
                self.text(left + 6, top + 32, flags_effect(trace.signals),
                          fill=INK if writes else MARK)
        # What it holds goes up to the condition check.
        colour = self.colour("ALUFlags") if checked else IDLE
        self.line([(FLAGS_X, top), (FLAGS_X, CHECK_BOX[3])], fill=colour,
                  width=2.4 if checked else 1.2, arrow="last")
        if trace is not None and checked:
            self.text(FLAGS_X + 6, (top + CHECK_BOX[3]) / 2, xray.flag_text(trace.flags),
                      anchor="w", font="code", fill=colour)
        # The ALU's flags come in from the left.
        colour = self.colour("ALUFlags") if flags_in else IDLE
        value = trace.values.get("ALUFlags") if trace is not None else None
        said = f"ALUFlags {value:04b}" if flags_in and value is not None else "ALUFlags"
        self.text(6, ALU_FLAGS_Y - 3, said, anchor="sw", fill=colour)
        self.line([(4, ALU_FLAGS_Y), (left, ALU_FLAGS_Y)], fill=colour,
                  width=2.4 if flags_in else 1.2, arrow="last")
        if trace is not None and (stage.writing or stage.written) and not writes:
            self.line([(left - 12, ALU_FLAGS_Y - 6), (left - 12, ALU_FLAGS_Y + 6)], fill=MARK,
                      width=2.4)          # closed: the register keeps its flags
        # ADC, SBC and RSC: its C leaves for the ALU's adder as CarryIn, an addition.
        carry = trace.values.get("CarryIn") if trace is not None else None
        sent = carry is not None and stage.checked
        colour = self.colour("CarryIn") if sent else IDLE
        self.line([(right, CARRY_Y), (right + 20, CARRY_Y)], fill=colour,
                  width=1.8 if sent else 1.2, arrow="last")
        self.text(right + 23, CARRY_Y, f"CarryIn = {carry}" if sent else "CarryIn",
                  anchor="w", fill=colour)

    def _more(self, trace, stage):
        """The signals the Decoder makes from bits of the word besides the tables' own."""
        decoded = trace is not None and stage.decoded
        x, y = MORE_XY
        self.tipped(self.text(x, y, MORE_NAME, fill=INK if stage.arrived else IDLE), "tip:more",
                    MORE_ABOUT)
        s = trace.signals if trace is not None else {}
        for name in MORE:
            value = s.get(name)
            said = f"{name} {value}" if decoded else name
            width = self._width(f"{name} 0", "small")
            if x + width > self.SIZE[0] - MARGIN:       # on the next line
                x, y = MORE_XY[0], y + 15
            self.text(x, y + 15, said, anchor="nw", fill=signal_colour(value) if decoded else IDLE)
            x += width + 12


INSIDE["Control"] = ControlWindow
