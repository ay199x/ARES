# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Inside the register file: the window of ARM X-Ray for this block.

The register file holds R0 to R14. R15 is no register here: it reads as
PC + 8, which the PCPlus8 adder gives, and what is written to R15 goes to the
PC instead. Three read ports work at once, each a multiplexer that takes one
of the sixteen registers: RD1 gives the register numbered A1, RD2 the one
numbered A2 and RD4 the one numbered A4. The window draws each multiplexer as
a column of selection marks, one for each register, with a dot at the one it
takes. The write port has an address decoder that turns A3 into one write
enable for each register, all 0 when WE3 is 0; at the clock edge the register
enabled takes WD3. The base write port writes the register that A1 reads
(A5 = A1) with WD5 when WE5 (BaseWrite) is 1: the new base of a load or store
with write-back or post-indexing, and of each pass of LDM, STM, PUSH and POP
with write-back. In a pass the register comes from the pass counter as
PassReg: two pass multiplexers, steered by the pass counter's Pass (1 while a
pass runs), give it to A3 for a load and to A4 for a store; otherwise A3 and A4
take their own inputs. For MUL and MLA the RA1 and A3 multiplexers before the
block take Rs (Instr 11:8) and Instr 19:16, and MLA reads Ra (Instr 15:12) on A4;
for a shift by a register the A4 multiplexer before the block takes Rs; MOVT
reads its own Rd on A4, for the low half it keeps: the window names these
fields beside the addresses.

The block reads in its first step of the film and writes in its last; in
between, the values read wait on RD1, RD2 and RD4. Only the ports that the
instruction reads through work: a port whose address it does not have (Rn of
MOV, A4 of all but a store with a register offset) stays gray and says so, and
so do A3 and WD3 of an instruction that has no register to write. An
instruction that reads no register, such as MOV R0, #5, has only the write.

The registers the instruction reads or writes wait in the calm blue; a row read
lights while the read multiplexer takes it and keeps a lighter tint after, and
a row written rests on the green of the changed rows of the Registers pane from
the clock edge on. The other rows are not used by the instruction: pale.

The numbers that come in on A1, A2, A3, A4 and PassReg show their four bits,
as on the picture's wires (A1 = 0001); the rows keep their names, and so does
the block's word (READ R1).
"""

import math
from dataclasses import dataclass

from ... import xray
from ...xray_film import CMD_NAMES, hex32
from .xray_inside import (DIM, DONE, FIELD, IDLE, IDLE_STATE, INK, INSIDE, LOOKS, MARK, OFF, ON,
                          UNUSED, UNUSED_LINES, InsideWindow, look_of, register_bits,
                          signal_colour, system_note)
from .xray_picture import IDLE_BIT, WIDTH_32, WIDTH_BIT, cut, width_of

BLOCK = "RegFile"
HEADING = "Three Read Ports and Two Write Ports"
ABOUT = ("The register file reads up to three registers at once, on RD1, RD2 and RD4,\n"
         "and writes at the clock edge: register A3 takes WD3 when WE3 is 1, and the\n"
         "base register, A5 = A1, takes WD5 when WE5 is 1. R15 reads as PC + 8.")
NAMES = tuple(f"R{number}" for number in range(13)) + ("R13 (SP)", "R14 (LR)", "R15 (PC + 8)")

# Where things are, in design pixels.
TOP, ROW = 66, 21                   # the top of R0's row, and the height of each row
LEFT, RIGHT = 196, 462              # the column of the registers
NAME_X, VALUE_X, NEW_X = LEFT + 6, LEFT + 84, LEFT + 182
DECODER = (122, TOP + 2, 176, TOP + 15 * ROW - 2)      # left, top, right, bottom: beside R0 to R14
OUT = TOP + 16 * ROW + 12           # where the arrows of RD1, RD2 and RD4 end
STUB = 8                            # how far the registers' wires go past the last column
SENTENCE = 448                      # the sentence: up to two lines, left of the read ports
SENTENCE_WIDTH = 476                # where it wraps, before what the ports say under them
CAPTION_X = 496                     # the middle of "16-to-1 read multiplexers", over the columns,
                                    # clear of the numbers at the A4 pass multiplexer's inputs


def middle(number):
    """The y of the middle of the row of register number."""
    return TOP + number * ROW + ROW / 2


# The pass multiplexers: (left, right, top, bottom) of the one before the decoder (inputs A3 and
# PassReg) and of the one before the A4 read port (inputs A4 and PassReg); Pass steers both.
PASS_W = (100, 114, 108, 160)
PASS_R = (676, 690, 16, 52)
INPUTS = (                          # (name, its net in ares.xray_film, its wire from the left edge)
    ("WD3", "WD3", ((16, 38), (236, 38), (236, TOP))),
    ("WD5", "WD5", ((16, 56), (250, 56), (250, TOP))),
    ("PassReg", "PassReg", ((16, 84), (90, 84), (90, 120), (PASS_W[0], 120))),
    ("A3", "A3", ((16, 148), (PASS_W[0], 148))),
    ("WE3", "RegWrite", ((16, 300), (DECODER[0], 300))),
    ("WE5", "BaseWrite", ((16, 334), (DECODER[0], 334))),
    ("PCPlus8", "PCPlus8", ((16, middle(15)), (LEFT, middle(15)))),
)
BELOW = ("PCPlus8",)                # inputs whose names stand under their wires


@dataclass(frozen=True)
class Port:
    """A read port: its address (A1) with its key in Trace.values and the net whose colour it
    has (the address multiplexer's output before the block), its output (RD1) with its key,
    which is also its net, and the x of its column."""
    address: str
    key: str
    net: str
    output: str
    value: str
    column: float


PORTS = (Port("A1", "RA1", "RA1", "RD1", "SrcA", 540), Port("A2", "RA2", "RA2", "RD2", "RD2", 624),
         Port("A4", "A4", "A4", "RD4", "RD4", 708))

# Where the block is in the film (with IDLE_STATE before its first step and DONE after its last).
READING, BETWEEN, WRITING = "reading", "between", "writing"
# When things happen within the block's two steps, as fractions of the step.
READ_WORK, READ_OUT, READ_DONE = 0.3, 0.6, 0.9      # the rows light; the values leave; they are out
WRITE_DECODE, WRITE_EDGE = 0.35, 0.7                # the decoder enables a row; the clock edge
HIDDEN, SHOWN = {"state": "hidden"}, {"state": "normal"}
# What the write port does.
OPEN, TO_PC, CLOSED, NO_WRITE = "open", "to the PC", "closed", "no write"


def stage(film, moment, state):
    """Where the block is at moment: IDLE_STATE before its first step, READING in the step in
    which it reads, BETWEEN that step and the one in which it writes (its gate), WRITING in that
    one, DONE after it (state is what phase() gives). An instruction that reads no register has
    no step that reads."""
    if state in (IDLE_STATE, DONE):
        return state
    number = film.at(moment)[0]
    if number < len(film.steps):
        step = film.steps[number]
        if any(gate.block == BLOCK for gate in step.gates):
            return WRITING
        if any(name == BLOCK and word.startswith("READ") for name, word in step.lights):
            return READING
    return BETWEEN


def ports_read(trace):
    """The read ports trace uses, in order, as the film reads them: those whose address it has
    in Trace.values (port 1 of MOV, MVN and BX, port 2 of a load with an immediate offset and
    port 4 of all but a store with a register offset have none)."""
    values = trace.values
    return [port for port in PORTS if values.get(port.key) is not None]


def write_kind(trace):
    """OPEN: register A3 takes WD3; TO_PC: A3 is R15, so the PC takes it instead; CLOSED: A3 and
    WD3 come, but WE3 is 0 (the condition failed); NO_WRITE: the instruction has no register to
    write (A3 has no value), so A3 and WD3 are not used by it."""
    a3 = trace.values.get("A3")
    if a3 is None:
        return NO_WRITE
    if trace.signals["RegWrite"] != "1":
        return CLOSED
    return TO_PC if a3 == xray.PC_NUMBER else OPEN


# MUL and MLA: the field each address comes from, named beside it. A1's and A2's numbers with
# their fields are wider than the room between their columns: they end at these x instead of
# standing in the middle of their columns, A1's clear of the block's word, A2's of the A4 pass
# multiplexer.
MULTIPLY_FIELDS = {"A1": "Rs", "A2": "Rm", "A4": "Ra"}
MULTIPLY_ENDS = {"A1": 560, "A2": 662}


def _listed(parts):
    """parts as a sentence lists them: "a", "a and b", "a, b and c"."""
    if len(parts) < 2:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


class Facts:
    """What the window shows of one instruction, worked out once for each picture."""

    def __init__(self, trace, context):
        values = self.values = trace.values
        self.trace = trace
        self.used = ports_read(trace)
        self.kind = write_kind(trace)
        self.a3 = values["A3"]
        self.read = [values[port.key] for port in self.used]     # the register of each port
        before = context.registers_before
        self.before = [before[number] if before is not None else None for number in range(15)]
        self.before.append(values["PCPlus8"])                   # R15 reads as PC + 8
        self.written = self.a3 if self.kind == OPEN else None
        self.old = self.new = None
        after = context.registers_after
        self.writes = {}                # register -> (old, new): the writes at the clock edge
        if self.written is not None:
            self.old = self.before[self.written]
            self.new = after[self.written] if after is not None else values["WD3"]
            self.writes[self.written] = (self.old, self.new)
        self.base = values.get("A5") if trace.signals.get("BaseWrite") == "1" else None
        if self.base is not None:       # the base write port
            new = after[self.base] if after is not None else values["WD5"]
            self.writes[self.base] = (self.before[self.base], new)

    def read_word(self):
        """What the block says while it reads, as the picture's word: READ R1, R2 ("" when it
        reads no register)."""
        names = []
        for number in self.read:
            if f"R{number}" not in names:
                names.append(f"R{number}")
        return "READ " + ", ".join(names) if names else ""

    def write_word(self):
        names = [f"R{self.a3}"] if self.kind in (OPEN, TO_PC) else []
        if self.base is not None:
            names.append(f"R{self.base}")
        return "WRITE " + ", ".join(names) if names else ""

    def read_sentence(self):
        values = self.values
        reads = [f"R{values[port.key]} = {hex32(values[port.value])} on {port.output}"
                 for port in self.used]
        said = f"The register file reads {_listed(reads)}."
        if self.trace.kind == xray.MULTIPLY:    # what the multiplexers before it chose
            said += " Mul = 1: A1 is Rs (Instr 11:8)"
            said += ", A4 is Ra (Instr 15:12)." if values.get("A4") is not None else "."
        if self.trace.signals.get("ShiftReg") == "1":
            said += " ShiftReg = 1: A4 is Rs (Instr 11:8), the shift amount's register."
        if self.trace.signals.get("ALUControl") == xray.ALU_MOVT:
            said += " A4 is Rd (Instr 15:12): MOVT keeps its low half."
        if self.values.get("PassReg") is not None and self.values.get("A4") is not None:
            said += " Pass = 1: A4 takes PassReg."
        return said

    def idle_sentence(self):
        if self.used:
            return ("The register file waits: the numbers of the registers to read have not come "
                    "yet.")
        if self.kind == NO_WRITE:
            return "This instruction reads no register and writes none."
        return "This instruction reads no register: the register file waits for the write."

    def between_sentence(self):
        outputs = [port.output for port in self.used]
        if len(outputs) == 1:
            return f"{outputs[0]} holds the value read; the write waits for the clock edge."
        return f"{_listed(outputs)} hold the values read; the write waits for the clock edge."

    def write_sentence(self):
        said = self._write_sentence()
        values, signals = self.values, self.trace.signals
        if self.base is not None:
            old, new = self.writes[self.base]
            said += f" WE5 = 1: the base port writes R{self.base} with WD5 = {hex32(new)}."
        elif values.get("A5") is not None:
            said += f" WE5 = {signals.get('BaseWrite')}: the base R{values['A5']} keeps its value."
        return said

    def _write_sentence(self):
        kind, a3, trace = self.kind, self.a3, self.trace
        if kind == OPEN:
            source = " (A3 = PassReg)" if self.values.get("PassReg") is not None else ""
            if trace.kind == xray.MULTIPLY:
                source = " (A3 = Instr 19:16, the Rd of MUL and MLA)"
            return (f"WE3 = 1: the decoder enables R{a3}{source}, which takes WD3 = "
                    f"{hex32(self.new)} at the clock edge in place of {hex32(self.old)}.")
        if kind == TO_PC:
            return (f"WE3 = 1, but R15 is the PC: the PC takes WD3 = "
                    f"{hex32(self.values['WD3'])} at the clock edge, and no register here changes.")
        if kind == NO_WRITE:
            if trace.kind == xray.NO_OPERATION:
                what = "NOP writes nothing."
            elif trace.signals["NoWrite"] == "1":
                name = CMD_NAMES[trace.word >> 21 & 0xF]
                what = f"{name} only sets the flags; no register is written."
            elif trace.kind in xray.STORES:
                what = "A store writes no register."
            else:
                what = "A branch writes no register."
            return f"WE3 = 0: nothing is written. {what}"
        return f"WE3 = 0: nothing is written. The condition failed, so R{a3} keeps its value."


class RegisterFileWindow(InsideWindow):
    """Inside the register file (see the module's description)."""

    BLOCK = BLOCK
    TITLE = "Inside the Register File"
    HEADING = HEADING
    ABOUT = ABOUT
    SIZE = (760, 480)
    timed = growing = ()                # what animate() changes within a step: set by redraw()

    def redraw(self, film, moment, context, state, fraction):
        self.timed = []                 # [item, fraction, look before, look after, after shown]
        self.growing = []               # (line, its points, fraction it starts, fraction it ends)
        self.heading(16, 8)
        trace = context.trace
        self.resting = trace is None    # no instruction: every part rests in the calm blue
        facts = where = None            # None: the block stays pale
        if trace is not None and trace.signals and not system_note(trace, ""):
            facts = Facts(trace, context)
            where = stage(film, moment, state)
        self._draw_rows(facts, where)
        self._draw_decoder(facts, where)
        self._draw_reads(facts, where)
        self._draw_inputs(facts, where)
        self._draw_sentences(facts, where, trace)

    def animate(self, film, moment, context, state, fraction):
        canvas = self.canvas
        for entry in self.timed:
            item, at, before, after, shown = entry
            now = fraction >= at
            if now != shown:
                canvas.itemconfigure(item, **(after if now else before))
                entry[4] = now
        for item, points, start, end in self.growing:
            share = min(1.0, max(0.0, (fraction - start) / (end - start)))
            if share <= 0:
                canvas.itemconfigure(item, state="hidden")
                continue
            part = cut(points, _length(points) * share)
            if len(part) < 2:
                part = part * 2
            canvas.coords(item, *self.flat(part))
            canvas.itemconfigure(item, state="normal")

    # Helpers ----------------------------------------------------------------------------

    def _later(self, item, at, before, after):
        """item looks as before until the fraction at of the block's step, then as after."""
        self.canvas.itemconfigure(item, **after)
        self.timed.append([item, at, before, after, True])

    def _look(self, name, width):
        """The options of a part with the look called name (LOOKS), its outline width wide."""
        look = LOOKS[name]
        return {"outline": look.outline, "fill": look.fill, "width": self.d(width)}

    def _ring(self, x, y, radius, outline, fill):
        """A selection mark: a small ring, or a dot when filled."""
        return self.canvas.create_oval(*self.xy(x - radius, y - radius),
                                       *self.xy(x + radius, y + radius), outline=outline,
                                       fill=fill, width=self.d(1))

    # The parts --------------------------------------------------------------------------

    def _draw_rows(self, facts, where):
        """The sixteen rows with each register's name and value: the rows read light while the
        block reads, and the row written shows its old value struck out and its new one. The
        rows the instruction reads or writes wait in the calm blue, the others stay pale."""
        active = where not in (None, IDLE_STATE)
        read = set(facts.read) if active else set()
        writes = facts.writes if where in (WRITING, DONE) else {}
        involved = set(facts.read) | set(facts.writes) if facts is not None else set()
        for number in range(16):
            top, y = TOP + number * ROW, middle(number)
            tags = (f"block:R{number}",)
            done = number in read and where != READING
            part = LOOKS[look_of(number in involved, done=done, resting=self.resting)]
            box = self.box(LEFT, top + 1, RIGHT, top + ROW - 1, outline=part.outline,
                           fill=part.fill, width=1.6 if done else 1, tags=tags)
            if number in read and where == READING:
                self._later(box, READ_WORK, self._look("waiting", 1), self._look("working", 1.6))
            self.text(NAME_X, y, NAMES[number], anchor="w",
                      fill=part.words if facts is None else INK, tags=tags)
            if facts is None:
                continue
            colour = self.colour("PCPlus8") if number == xray.PC_NUMBER else INK
            value = self.text(VALUE_X, y, hex32(facts.before[number]), anchor="w", font="code",
                              fill=colour, tags=tags)
            if number in writes:
                new = self.colour("ALUResult" if number == facts.base else "WD3")
                self._draw_write(writes[number][1], new, box, value, number, where,
                                 number in read)

    def _draw_write(self, new, colour, box, value, number, where, read):
        """The row written: its old value struck out, an arrow and the new value new, in colour,
        the colour of WD3 or, for the base, of WD5 (ALUResult); from the clock edge on the row
        rests on the green of a change."""
        canvas = self.canvas
        y = middle(number)
        tags = (f"block:R{number}",)
        left, top, right, bottom = canvas.bbox(value)
        across = top + (bottom - top) / 2
        strike = canvas.create_line(left, across, right, across, fill=MARK, width=self.d(1.2),
                                    tags=(f"strike:R{number}",))
        items = [strike]
        start = max(VALUE_X + 70, right / self.k + 4)
        if start < NEW_X - 8:
            items.append(self.line([(start, y), (NEW_X - 4, y)], fill=INK, arrow="last"))
        items.append(self.text(NEW_X, y, hex32(new), anchor="w", font="code_bold",
                               fill=colour, tags=tags))
        canvas.itemconfigure(value, fill=MARK)
        canvas.itemconfigure(box, **self._look("changed", 1.6))
        if where != WRITING:
            return
        self._later(box, WRITE_EDGE, self._look("done" if read else "waiting", 1.6 if read else 1),
                    self._look("changed", 1.6))
        self._later(value, WRITE_EDGE, {"fill": INK}, {"fill": MARK})
        for item in items:
            self._later(item, WRITE_EDGE, HIDDEN, SHOWN)

    def _draw_decoder(self, facts, where):
        """The address decoder: A3 and WE3 come in, and one write enable leaves for each of R0
        to R14. In the write step all are 0 but the one of register A3 when WE3 is 1. It waits
        until then, lights when it enables a register and is done after (at once when it
        enables none)."""
        left, top, right, bottom = DECODER
        done, writing = where == DONE, where in (WRITING, DONE)
        part = LOOKS[look_of(facts is not None, done=done, resting=self.resting)]
        box = self.box(left, top, right, bottom, outline=part.outline, fill=part.fill,
                       width=1.6 if done else 1, tags=("block:Decoder",))
        title = self.text((left + right) / 2, (top + bottom) / 2, "Address\ndecoder",
                          anchor="center", font="bold", fill=INK if writing else part.words,
                          justify="center", tags=("block:Decoder",))
        enabled = facts.written if writing else None
        if where == WRITING:
            self._later(box, WRITE_DECODE, self._look("waiting", 1),
                        self._look("working" if enabled is not None else "done", 1.6))
            self._later(title, WRITE_DECODE, {"fill": DIM}, {"fill": INK})
        for number in range(15):
            y = middle(number)
            on = number == enabled
            colour, width = (ON, WIDTH_BIT) if on else (OFF, IDLE_BIT)
            tags = (f"wire:en{number}",)
            line = self.line([(right, y), (LEFT, y)], fill=colour if done else IDLE,
                             width=width if done else IDLE_BIT, arrow="last", tags=tags)
            if not writing:
                continue
            bit = self.text((right + LEFT) / 2, y - 2, "1" if on else "0", anchor="s",
                            fill=colour, tags=tags)
            if where == WRITING:
                self._later(line, WRITE_DECODE, {"fill": IDLE, "width": self.d(IDLE_BIT)},
                            {"fill": colour, "width": self.d(width)})
                self._later(bit, WRITE_DECODE, HIDDEN, SHOWN)

    def _draw_reads(self, facts, where):
        """The three read multiplexers, each a column of selection marks: the dot in a column
        marks the register its address names, and that register's value goes down the column
        to the port's output."""
        end = PORTS[-1].column + STUB
        for number in range(16):
            y = middle(number)
            self.line([(RIGHT, y), (end, y)], fill=IDLE, width=IDLE_BIT, tags=(f"wire:Q{number}",))
        for port in PORTS:
            self.line([(port.column, TOP), (port.column, OUT)], fill=IDLE, width=IDLE_BIT,
                      arrow="last", tags=(f"wire:{port.output}",))
            for number in range(16):
                self._ring(port.column, middle(number), 2.2, IDLE, FIELD)
        active = where not in (None, IDLE_STATE)
        self.text(CAPTION_X, 26, "16-to-1 read multiplexers", anchor="n",
                  fill=INK if active else IDLE)
        used = facts.used if active else []
        for port in reversed(PORTS):    # the nearer columns' wires over the farther ones'
            if port not in used:
                continue
            y = middle(facts.values[port.key])
            colour = self.colour(port.value)
            tags = (f"wire:{port.output}",)
            tap = self.line([(RIGHT, y), (port.column, y)], fill=colour, width=WIDTH_32,
                            tags=tags)
            dot = self._ring(port.column, y, 3.2, INK, INK)
            points = ((port.column, y), (port.column, OUT))
            out = self.line(points, fill=colour, width=WIDTH_32, arrow="last", tags=tags)
            if where == READING:
                self._later(tap, READ_WORK, HIDDEN, SHOWN)
                self._later(dot, READ_WORK, HIDDEN, SHOWN)
                self.growing.append((out, points, READ_OUT, READ_DONE))
        for port in PORTS:
            self._draw_port_words(port, facts, where)

    def _draw_port_words(self, port, facts, where):
        """A port's address over its column, the register number's four bits, and its output's
        name and value under it. A port the instruction does not read through stays gray and
        says so under its name."""
        active = where not in (None, IDLE_STATE)
        unused = facts is not None and port not in facts.used
        used = active and not unused
        tags = (f"wire:{port.address}",)
        if port.address == "A4":        # its address comes through the pass multiplexer
            self._draw_pass_mux(PASS_R, "A4", facts, where, facts is not None and not unused,
                                port)
            return self._draw_port_out(port, facts, where, used, unused, active)
        if used:
            field, x, anchor = "", port.column, "s"
            if facts.trace.kind == xray.MULTIPLY:
                field = f" ({MULTIPLY_FIELDS[port.address]})"
                x, anchor = MULTIPLY_ENDS[port.address], "se"
            number = register_bits(facts.values[port.key])
            self.text(x, TOP - 4, f"{port.address} = {number}{field}", anchor=anchor,
                      font="code", fill=self.colour(port.net), tags=tags)
        else:
            self.text(port.column, TOP - 4, port.address, anchor="s", font="code", fill=IDLE,
                      tags=tags)
        return self._draw_port_out(port, facts, where, used, unused, active)

    def _draw_port_out(self, port, facts, where, used, unused, active):
        """A read port's output under its column: its name and its value."""
        tags = (f"wire:{port.output}", "out")
        name = self.text(port.column, OUT + 3, port.output, anchor="n", font="bold",
                         fill=INK if used else IDLE, tags=tags)
        if unused:
            self.text(port.column, OUT + 16, UNUSED_LINES, anchor="n", justify="center",
                      fill=IDLE, tags=tags)
            return
        if not active:
            return
        value = self.text(port.column, OUT + 16, hex32(facts.values[port.value]), anchor="n",
                          font="code", fill=self.colour(port.value), tags=tags)
        if where == READING:
            self._later(name, READ_DONE, {"fill": IDLE}, {"fill": INK})
            self._later(value, READ_DONE, HIDDEN, SHOWN)

    def _draw_pass_mux(self, box, name, facts, where, reads=False, port=None):
        """A pass multiplexer (box): input 0 the port's own address name, input 1 PassReg, and
        Pass from the pass counter as its select; its output goes to the decoder (A3) or down
        the A4 read multiplexer's column (reads: the instruction reads through it), in the
        colour of the input taken. Pale unless the instruction uses the port; it works in the
        step that reads (A4) or writes (A3)."""
        left, right, top, bottom = box
        values = facts.values if facts is not None else {}
        register = values.get("PassReg")
        active = facts is not None and where not in (None, IDLE_STATE)
        passes = facts is not None and register is not None and (
            (name == "A3" and values.get("A3") is not None) or
            (name == "A4" and values.get("A4") is not None))
        owns = facts is not None and not passes and (
            (name == "A3" and facts.kind != NO_WRITE) or (name == "A4" and reads))
        passing, own = active and passes, active and owns
        lit = passing or own
        works, after = (READING, (BETWEEN, WRITING, DONE)) if name == "A4" else (WRITING, (DONE,))
        part = LOOKS[look_of(passes or owns, working=lit and where == works,
                             done=lit and where in after, resting=self.resting)]
        tags = (f"wire:Pass{name}",)
        self.mux(left, top, right, bottom, outline=INK if lit else part.outline, fill=part.fill)
        slope = (bottom - top) / 5
        inputs = (top + slope + 4, bottom - slope - 4)      # input 0 above, 1 below for A4
        middle = (top + bottom) / 2
        if name == "A4":
            first, second = inputs
            label0 = "A4"
            if own and values.get("A4") is not None:
                label0 = f"A4 = {register_bits(values['A4'])}"
            if own and facts.trace.kind == xray.MULTIPLY:
                label0 += " (Ra)"
            elif own and facts.trace.signals.get("ShiftReg") == "1":
                label0 += " (Rs)"
            elif own and facts.trace.signals.get("ALUControl") == xray.ALU_MOVT:
                label0 += " (Rd)"
            label1 = f"PassReg = {register_bits(register)}" if passing else "PassReg"
            self.line([(left - 6, first), (left, first)], fill=INK if own else IDLE,
                      tags=tags)
            self.line([(left - 6, second), (left, second)], fill=INK if passing else IDLE,
                      tags=tags)
            self.text(left - 8, first, label0, anchor="e", font="code",
                      fill=self.colour("A4") if own else IDLE, tags=("wire:A4",))
            self.text(left - 8, second, label1, anchor="e", font="code",
                      fill=self.colour("PassReg") if passing else IDLE, tags=("wire:PassReg",))
            out = [(right, middle), (port.column, middle), (port.column, TOP)]
        else:
            out = [(right, middle), (DECODER[0], middle)]
        taken = self.colour("PassReg" if passing else name) if lit else IDLE
        self.line(out, fill=taken, width=WIDTH_BIT if lit else IDLE_BIT, arrow="last", tags=tags)
        for number, y in ((0, inputs[0] if name == "A4" else 148), (1, inputs[1] if name == "A4"
                                                                     else 120)):
            self.text(left + 2, y, str(number), anchor="w", fill=INK if lit else part.words)
            if lit and number == (1 if passing else 0):
                self._ring(left, y, 2.2, INK, INK)
        # The select, Pass, from the pass counter: from above for A4, from below for A3.
        value = "1" if passing else "0" if lit else ""
        colour = ON if passing else OFF if lit else IDLE
        x = right - 3
        if name == "A4":
            self.line([(x, 2), (x, top + slope * 3 / 14)], fill=colour, width=1.2,
                      arrow="last", tags=tags)
            self.text(x + 4, 4, f"Pass = {value}" if value else "Pass", anchor="nw",
                      fill=colour, tags=tags)
        else:
            self.line([(x, 178), (x, bottom - slope * 11 / 14)], fill=colour, width=1.2,
                      arrow="last", tags=tags)
            self.text(x + 1, 180, f"Pass = {value}" if value else "Pass", anchor="ne",
                      fill=colour, tags=tags)

    def _draw_inputs(self, facts, where):
        """What comes in at the left: WD3, A3 and WE3 for the write, in its step, and PCPlus8,
        which R15 reads as, when R15 is read."""
        self._draw_pass_mux(PASS_W, "A3", facts, where)
        for name, net, points in INPUTS:
            tags = (f"wire:{name}",)
            self.line(points, fill=IDLE, width=width_of(net, False), arrow="last", tags=tags)
            label, colour, comes = name, IDLE, None
            if facts is not None:
                label, colour, comes = self._input(name, facts, where)
            x, y = points[0]
            font = "code" if "=" in label else "small"
            if name in BELOW:           # under its wire: something stands over it
                self.text(x + 2, y + 3, label, anchor="nw", font=font, fill=colour, tags=tags)
            else:
                self.text(x + 2, y - 3, label, anchor="sw", font=font, fill=colour, tags=tags)
            if comes is None:
                continue
            line = self.line(points, fill=colour, width=width_of(net, True), arrow="last",
                             tags=tags)
            if comes:
                self.growing.append((line, points) + comes)
        if facts is not None and facts.kind == CLOSED and where in (WRITING, DONE):
            x, y = INPUTS[0][2][-1]     # a bar across WD3's end: the write is closed
            bar = self.line([(x - 7, y - 7), (x + 7, y - 7)], fill=MARK, width=2.4,
                            tags=("wire:WD3", "closed"))
            if where == WRITING:
                self._later(bar, WRITE_EDGE, HIDDEN, SHOWN)

    def _input(self, name, facts, where):
        """(label, colour, how it comes) of an input: how it comes is None while it is not
        there, () once it has come, or the fractions of the step between which it comes. A3
        and WD3 of an instruction with no register to write say that they are not used by it;
        a WD3 that has no value (a load that did not read) comes as a question mark, gray."""
        values = facts.values
        if name in ("WD5", "WE5"):      # the base write port
            if values.get("A5") is None:
                return name, IDLE, None
            if where not in (WRITING, DONE):
                return name, IDLE, None
            comes = (0.0, WRITE_DECODE) if where == WRITING else ()
            if name == "WE5":
                value = facts.trace.signals.get("BaseWrite")
                return f"WE5 = {value}", signal_colour(value), comes
            return f"WD5 = {hex32(values['WD5'])}", self.colour("ALUResult"), comes
        if name == "PassReg":           # the pass counter: A3 of a load, A4 of a store
            register = values.get("PassReg")
            if register is None or where in (None, IDLE_STATE):
                return name, IDLE, None
            return f"PassReg = {register_bits(register)}", self.colour("PassReg"), ()
        if name == "PCPlus8":
            if where in (None, IDLE_STATE) or xray.PC_NUMBER not in facts.read:
                return name, IDLE, None
            return (f"PCPlus8 = {hex32(values['PCPlus8'])}", self.colour("PCPlus8"),
                    (0.0, READ_WORK) if where == READING else ())
        if name != "WE3" and facts.kind == NO_WRITE:
            if name == "A3" and values.get("PassReg") is not None:
                return "A3: not used", IDLE, None   # one line, clear of PassReg's wire
            return f"{name}: {UNUSED_LINES if name == 'A3' else UNUSED}", IDLE, None
        if where not in (WRITING, DONE):
            return name, IDLE, None
        if name == "A3" and values.get("PassReg") is not None:
            return name, IDLE, None     # a pass: the pass multiplexer takes PassReg instead
        comes = (0.0, WRITE_DECODE) if where == WRITING else ()
        if name == "WE3":
            value = facts.trace.signals["RegWrite"]
            return f"WE3 = {value}", signal_colour(value), comes
        if name == "A3":
            return f"A3 = {register_bits(facts.a3)}", self.colour("A3"), comes
        if values["WD3"] is None:
            return "WD3 = ?", IDLE, None
        return f"WD3 = {hex32(values['WD3'])}", self.colour("WD3"), comes

    def _draw_sentences(self, facts, where, trace):
        """The sentence that says what the block does now, and the word over the registers."""
        if facts is None:
            why = ("No instruction is shown." if trace is None else
                   system_note(trace, "the register file") or
                   "This instruction does not use this datapath: the register file does not work "
                   "for it.")
            self.text(16, SENTENCE, why, font="bold", fill=INK, tags=("sentence",))
            return
        if where == IDLE_STATE:
            sentence = facts.idle_sentence()
        elif where == READING:
            sentence = facts.read_sentence()
        elif where == BETWEEN:
            sentence = facts.between_sentence()
        else:
            sentence = facts.write_sentence()
        self.text(16, SENTENCE, sentence, fill=INK, tags=("sentence",),
                  width=SENTENCE_WIDTH * self.k)
        if where == IDLE_STATE:
            return
        read_word, write_word = facts.read_word(), facts.write_word()
        word = write_word if where in (WRITING, DONE) and write_word else read_word
        item = self.text(RIGHT - 4, TOP - 4, word, anchor="se", font="bold", fill=INK,
                         tags=("word",))
        if where == READING:
            self._later(item, READ_WORK, HIDDEN, SHOWN)
        elif where == WRITING and write_word:
            self._later(item, WRITE_EDGE, {"text": read_word}, {"text": write_word})


INSIDE[BLOCK] = RegisterFileWindow
