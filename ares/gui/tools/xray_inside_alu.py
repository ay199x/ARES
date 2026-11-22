# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Inside the ALU: the window of ARM X-Ray for this block.

SrcA and SrcB come in at the top left and reach every unit of the ALU at once.
The adder adds; to subtract it adds the inverse of the second operand and a
carry in of 1, and for RSB it swaps the operands first. ADC, SBC and RSC do the
same with the C flag as the carry in: a small multiplexer takes CarryIn, which
the flags register sends, instead of the subtract line. AND, ORR, EOR and BIC
work on each bit, and MOV and MVN pass SrcB or its inverse on. The multiplier
makes the low 32 bits of SrcA x SrcB for MUL (ALUControl 1001), and adds RD4,
the third register that MLA reads, for 1010. For MOVT (1110) a unit joins the
low half of SrcB, its immediate, as the high half to the low half of RD4, the
old value of its Rd. ALUControl drives the multiplexer that takes one of these
values as ALUResult. The flags
come from the result and from the adder: N is bit 31, Z says that the result
is 0, C is the adder's carry out and V its overflow. With ShiftC, C is the
shifter's carry instead, or bit 31 of a rotated immediate. FlagWrite says
which flags are written.

The window plays with the ALU's step of the film: SrcA, SrcB and ALUControl
arrive first, then the units work, then the result and the flags leave. An
instruction that takes SrcB alone (MOV, MVN, BX) has no SrcA: the adder and the
units that need it get nothing and stay pale, with no value and no cross. The
multiplier and the MOVT unit are additions to the textbook's ALU: they work only
for MUL and MLA, and for MOVT, and stay pale, with no value, for every other
instruction. Each unit waits in the calm blue and lights while it works; once
the result multiplexer has taken one, those it rejects turn pale and the one
taken keeps its light to the end of the step, then its lighter tint.
"""

import math

from ... import xray
from ...xray_film import ALU_WORDS, hex32
from .xray_inside import (DONE_FILL, IDLE, IDLE_STATE, INK, INSIDE, LOOKS, MARK, ON, UNUSED,
                          WORKING, InsideWindow, bit_text, gray_on, look_of, signal_colour,
                          system_note)
from .xray_picture import cut

HEADING = "Operations and Flags"
ABOUT = ("The ALU does the operation that ALUControl chooses on SrcA and SrcB (and RD4),\n"
         "and makes the flags N, Z, C and V.")
ADDER = (xray.ALU_ADD, xray.ALU_SUB, xray.ALU_RSB) + xray.CARRY_CODES
SWAPS = (xray.ALU_RSB, xray.ALU_RSC)                # the operands swapped
INVERTS = (xray.ALU_SUB, xray.ALU_RSB, xray.ALU_SBC, xray.ALU_RSC)     # NOT the second
UNITS = (("AND", xray.ALU_AND, "SrcA AND SrcB"), ("ORR", xray.ALU_ORR, "SrcA OR SrcB"),
         ("EOR", xray.ALU_EOR, "SrcA EOR SrcB"), ("BIC", xray.ALU_BIC, "SrcA AND NOT SrcB"),
         ("MOV", xray.ALU_MOV, "SrcB, passed on"), ("MVN", xray.ALU_MVN, "NOT SrcB"))
MULTIPLIER = (xray.ALU_MUL, xray.ALU_MLA)
MAKES = {xray.ALU_ADD: "SrcA plus SrcB", xray.ALU_SUB: "SrcA minus SrcB",
         xray.ALU_RSB: "SrcB minus SrcA", xray.ALU_MUL: "SrcA x SrcB",
         xray.ALU_MLA: "SrcA x SrcB + RD4", xray.ALU_ADC: "SrcA plus SrcB plus C",
         xray.ALU_SBC: "SrcA minus SrcB minus NOT C", xray.ALU_RSC: "SrcB minus SrcA minus NOT C",
         xray.ALU_MOVT: "SrcB[15:0] : RD4[15:0]"}
MAKES.update((code, what.replace(", passed on", "")) for _, code, what in UNITS)
FLAG_HOWS = {"N": "bit 31 of ALUResult", "Z": "1 when ALUResult is 0",
             "C": "carry out of the adder", "V": "overflow of the adder"}

# The parts of the ALU's step of the film, and the shares of the step where they begin.
IDLE_PART, ARRIVE, WORK, LEAVE, OUT, DONE_PART = range(6)
ARRIVED, LEAVES, LEFT = 0.3, 0.6, 0.85

# Where everything is, in design pixels.
ROW_A, ROW_B, ROW_RD4, ROW_RESULT = 30, 46, 62, 78     # the values at the top: SrcA, SrcB,
                                                        # RD4 (MLA, MOVT) and ALUResult
LABEL_X, HEX_X, BITS_X = 40, 112, 192
A_X, B_X = 16, 28                               # the lines that carry SrcA and SrcB to the units
SWAP = (70, 104, 120, 190)                      # swaps the operands for RSB
FIRST_Y, SECOND_Y, NOT_Y = 132, 160, 184        # the adder's paths: its first and second operand
SECOND_MUX = ((196, 146), (214, 156.4), (214, 187.6), (196, 198))     # the second or its inverse
SELECT_X, CARRY_X, BRANCH_Y = 205, 348, 110     # subtract: the multiplexer and the carry in
CARRY_MUX = ((318, 104), (330, 106.4), (330, 123.6), (318, 126))   # the subtract line, or CarryIn
CARRY_INPUTS, CARRY_OUT, CARRY_SELECT = (110, 120), 115, 329   # 0 and 1 clear of it all
ADDER_SHAPE = ((330, 116), (366, 136), (366, 168), (330, 188), (330, 158), (338, 152), (330, 146))
ADDED_Y, SUM_Y = 172, 152
UNIT_LEFT, UNIT_RIGHT, UNIT_TOP, UNIT_STEP, UNIT_HEIGHT = 70, 400, 210, 21, 20
TOPS = tuple(UNIT_TOP + UNIT_STEP * number for number in range(len(UNITS)))
MUL_TOP, MUL_HEIGHT = 338, 22                   # the multiplier, under the units
MUL_Y = MUL_TOP + MUL_HEIGHT / 2                # its output; SrcA, SrcB and RD4 come in at:
MUL_TAPS = (MUL_TOP + 5, MUL_TOP + 11, MUL_TOP + 17)
MOVT_TOP, MOVT_HEIGHT = 364, 22                 # the unit of MOVT, under the multiplier
MOVT_Y = MOVT_TOP + MOVT_HEIGHT / 2             # its output; SrcB and RD4 come in at:
MOVT_TAPS = (MOVT_TOP + 7, MOVT_TOP + 15)
RD4_X = 6                                       # the line that carries RD4 down to them
RESULT_MUX = ((500, 104), (560, 124), (560, 376), (500, 396))
MUX_LEFT, MUX_RIGHT, CONTROL_X, OUT_Y = 500, 560, 530, 240
FLAG_TOP, FLAG_WIDTH, FLAG_STEP, FLAG_HEIGHT = 400, 172, 182, 56
SENTENCE_Y = 462
WIDE, BIT, THIN = 2.4, 1.6, 1.2                 # lines of 32 bits and of one in use, and idle


class Operation:
    """What each part of the ALU makes of the operands of trace (xray.alu() for each unit);
    the result and the flags are the trace's, the shifter's carry in C included. Without SrcA
    (Trace.values None: MOV, MVN and BX), the adder and the units that need SrcA make nothing:
    values holds only the units that make a value."""

    def __init__(self, trace):
        signals, values = trace.signals, trace.values
        self.control = control = signals["ALUControl"]
        self.word = ALU_WORDS[control]
        self.a, self.b = a, b = values["SrcA"], values["SrcB"]
        self.uses_a = a is not None
        self.multiplies = control in MULTIPLIER     # the multiplier works for MUL and MLA only
        self.joins = control == xray.ALU_MOVT       # the MOVT unit for MOVT only
        self.rd4 = values["RD4"] if control in (xray.ALU_MLA, xray.ALU_MOVT) else None
        adding = control if control in ADDER else xray.ALU_ADD
        self.swap = adding in SWAPS
        self.invert = adding in INVERTS             # the adder adds NOT second, and a carry
        self.carry = values.get("CarryIn")          # ADC, SBC, RSC: the C flag, else None
        self.carry_in = self.carry if self.carry is not None else int(self.invert)
        self.values = {code: xray.alu(code, a or 0, b)[0] for _, code, _ in UNITS
                       if self.uses_a or code in xray.NO_FIRST_OPERAND}
        self.first = self.added = self.sum = self.carry_out = self.overflow = None
        if self.uses_a:
            self.first, second = (b, a) if self.swap else (a, b)
            self.added = ~second & xray.MASK if self.invert else second
            self.sum, adder_flags = xray.alu(adding, a, b, carry_in=self.carry or 0)
            self.carry_out, self.overflow = adder_flags >> 1 & 1, adder_flags & 1
            self.values["adder"] = self.sum
        if self.multiplies:
            self.values["multiplier"] = values["ALUResult"]
        if self.joins:
            self.values["movt"] = values["ALUResult"]
        self.taken = "adder" if control in ADDER else "multiplier" if self.multiplies else \
            "movt" if self.joins else control
        self.result, self.flags = values["ALUResult"], values["ALUFlags"]
        self.shift_c = signals["ShiftC"] == "1"
        self.rotated = self.shift_c and signals["ALUSrc"] == "1"    # C: bit 31 of ExtImm
        self.before = trace.flags
        self.flag_write = write = signals["FlagWrite"]
        self.flag_w = signals["FlagW"]
        nz = write[0] == "1"
        self.written = {"N": nz, "Z": nz, "C": write[1] == "1" or (nz and self.shift_c),
                        "V": write[1] == "1"}

    def bit(self, flag, flags=None):
        return (self.flags if flags is None else flags) >> xray.FLAG_BITS[flag] & 1

    def how(self, flag):
        """Where flag comes from, in a few words."""
        if flag == "C" and self.shift_c:
            return "bit 31 of ExtImm (ShiftC = 1)" if self.rotated else \
                "from the shifter (ShiftC = 1)"
        if flag in "CV" and self.taken != "adder":
            return f"only ADD, SUB and RSB make {flag}"
        return FLAG_HOWS[flag]

    def flag_sentence(self):
        write = self.flag_write
        if write == "11":
            return "FlagWrite = 11: all four flags are written."
        if write == "10" and self.shift_c:
            source = "ExtImm" if self.rotated else "the shifter"
            return f"FlagWrite = 10: N and Z are written, and C from {source}."
        if write == "10":
            return "FlagWrite = 10: N and Z are written; C and V are kept."
        if self.flag_w != "00":
            return "FlagWrite = 00: the condition failed, so no flag is written."
        return "FlagWrite = 00: no flag is written."


def part_of(state, fraction):
    """The part of the ALU's step at fraction of it (see ARRIVED, LEAVES and LEFT)."""
    if state == IDLE_STATE:
        return IDLE_PART
    if state != WORKING:
        return DONE_PART
    if fraction < ARRIVED:
        return ARRIVE
    if fraction < LEAVES:
        return WORK
    return LEAVE if fraction < LEFT else OUT


class ALUWindow(InsideWindow):
    """Inside the ALU (see the module's description)."""

    BLOCK = "ALU"
    TITLE = "Inside the ALU"
    HEADING = HEADING
    ABOUT = ABOUT
    SIZE = (760, 480)

    def __init__(self, tool):
        self._part = None               # the part of the step drawn now
        self._moving = []               # (line, points, offset, longest, start, end): _travel()
        super().__init__(tool)

    def redraw(self, film, moment, context, state, fraction):
        self._moving = []
        self._part = part = part_of(state, fraction)
        trace = context.trace
        self.resting = trace is None    # no instruction: every part rests in the calm blue
        used = trace is not None and trace.signals and not system_note(trace, "")
        op = Operation(trace) if used else None
        self.heading(16, 8)
        if op is None:
            why = "No instruction is shown." if trace is None else \
                system_note(trace, "the ALU") or "This instruction does not use this datapath."
            self.text(744, 28, why, anchor="ne", fill=INK)
            part = IDLE_PART
        self._table(op, part)
        self._word(op, part)
        self._buses(op, part)
        self._adder(op, part, state)
        self._units(op, part, state)
        self._multiplier(op, part, state)
        self._movt(op, part, state)
        self._result_mux(op, part, state)
        self._flags(op, part)
        self._move(fraction)

    def key_of(self, film, moment, context, state, fraction):
        """The window is drawn whole for a new film or instruction; within the film, animate()
        draws it again when the part of the ALU's step changes (part_of())."""
        return film, context

    def animate(self, film, moment, context, state, fraction):
        part = part_of(state, fraction)
        if part == self._part:
            self._move(fraction)
        elif self._part == OUT and part == DONE_PART:      # all is out: the lit parts are done
            self._part = part
            self.canvas.itemconfigure("lit", fill=DONE_FILL)
            self.canvas.dtag("lit", "lit")
        else:
            self.canvas.delete("all")
            self.redraw(film, moment, context, state, fraction)

    # The parts -------------------------------------------------------------------------------

    def _table(self, op, part):
        """SrcA and SrcB as they come in, and ALUResult once it has left. A SrcA that the
        instruction does not have says so from the start: it never comes."""
        here, out = part >= ARRIVE, part >= OUT
        for name, y in (("SrcA", ROW_A), ("SrcB", ROW_B)):
            used = op is not None and (name == "SrcB" or op.uses_a)
            colour = self.colour(name) if here and used else IDLE
            self.text(LABEL_X, y, name, font="bold", fill=colour, tags=(f"wire:{name}",))
            if op is None:
                continue
            if not used:
                alone = "SrcB and RD4" if op.joins else "SrcB alone"
                self.text(HEX_X, y, f"{UNUSED}: {op.word} takes {alone}", fill=IDLE)
                continue
            if not here:
                self.text(HEX_X, y, "(not here yet)", fill=IDLE)
                continue
            value = op.a if name == "SrcA" else op.b
            self.text(HEX_X, y, hex32(value), font="code_bold", fill=colour)
            self.text(BITS_X, y, bit_text(value), font="code", fill=colour)
        # RD4 comes in for MLA, whose multiplier adds it, and MOVT, which keeps its low half.
        used = op is not None and op.rd4 is not None
        colour = self.colour("RD4") if here and used else IDLE
        self.text(LABEL_X, ROW_RD4, "RD4", font="bold", fill=colour, tags=("wire:RD4",))
        if op is not None and op.multiplies and not used:
            self.text(HEX_X, ROW_RD4, f"{UNUSED}: MUL adds nothing to the product", fill=IDLE)
        elif used and not here:
            self.text(HEX_X, ROW_RD4, "(not here yet)", fill=IDLE)
        elif used:
            self.text(HEX_X, ROW_RD4, hex32(op.rd4), font="code_bold", fill=colour)
            self.text(BITS_X, ROW_RD4, bit_text(op.rd4), font="code", fill=colour)
        colour = self.colour("ALUResult") if out else IDLE
        self.text(LABEL_X, ROW_RESULT, "ALUResult", font="bold", fill=colour)
        if out:
            self.text(HEX_X, ROW_RESULT, hex32(op.result), font="code_bold", fill=colour)
            self.text(BITS_X, ROW_RESULT, bit_text(op.result), font="code", fill=colour)

    def _word(self, op, part):
        """What the ALU does, in a word, while it works and after."""
        if op is not None and part >= WORK:
            self.text(744, 28, op.word, anchor="ne", font="title", fill=INK)
            self.text(744, 50, f"ALUResult = {MAKES[op.control]}", anchor="ne", fill=INK)

    def _buses(self, op, part):
        """The lines that carry SrcA and SrcB from where they come in to every unit, and RD4 to
        the multiplier and the MOVT unit. The multiplier's taps carry a value only for MUL and
        MLA, the MOVT unit's only for MOVT."""
        no_first = xray.NO_FIRST_OPERAND
        a_taps = [FIRST_Y] + [top + 6 for top, (_, code, _) in zip(TOPS, UNITS)
                              if code not in no_first]
        b_taps = [SECOND_Y] + [top + (UNIT_HEIGHT / 2 if code in no_first else 14)
                               for top, (_, code, _) in zip(TOPS, UNITS)]
        multiplies = op is not None and op.multiplies
        joins = op is not None and op.joins
        for name, x, y, taps, used, extra in (
                ("SrcA", A_X, ROW_A + 7, a_taps, op is not None and op.uses_a,
                 [(MUL_TAPS[0], multiplies)]),
                ("SrcB", B_X, ROW_B + 7, b_taps, op is not None,
                 [(MUL_TAPS[1], multiplies), (MOVT_TAPS[0], joins)]),
                ("RD4", RD4_X, ROW_RD4 + 7, [], op is not None and op.rd4 is not None,
                 [(MUL_TAPS[2], multiplies), (MOVT_TAPS[1], joins)])):
            tags = (f"wire:{name}",)
            every = taps + [tap for tap, _ in extra]
            polylines = [[(LABEL_X - 4, y), (x, y), (x, every[-1])]]
            polylines += [[(x, tap), (UNIT_LEFT, tap)] for tap in every]
            arrows = [False] + [True] * len(every)
            for points, arrow in zip(polylines, arrows):
                self.line(points, fill=IDLE, width=THIN, arrow="last" if arrow else "none",
                          tags=tags)
            reach = taps + [tap for tap, comes in extra if comes]
            if not reach:
                continue
            lit = [[(LABEL_X - 4, y), (x, y), (x, reach[-1])]]
            lit += [[(x, tap), (UNIT_LEFT, tap)] for tap in reach]
            there = used and part > ARRIVE
            for tap in reach[:-1]:
                self._dot(x, tap, self.colour(name) if there else IDLE, tags=tags)
            if used and part >= ARRIVE:
                self._travel(lit, [False] + [True] * len(reach), self.colour(name), WIDE, tags,
                             part == ARRIVE, 0.0, ARRIVED)

    def _adder(self, op, part, state):
        """The adder, with the swap for RSB and the inverse of its second operand, and the two
        multiplexers on its way, which share its look. Without SrcA it adds nothing: it stays
        pale, with no value and no choice."""
        working = op is not None and part >= WORK
        in_use = working and op.uses_a
        rejected = in_use and part >= LEAVE and op.taken != "adder"
        active = in_use and not rejected
        lit = active and state == WORKING
        look = LOOKS[look_of(op is not None and op.uses_a and not rejected, working=lit,
                             done=active, resting=self.resting)]
        outline, fill, width = look.outline, look.fill, 1.6 if active else 1
        shining = ("lit",) if lit else ()       # what animate() makes done when the step ends
        values = INK if active else MARK if rejected else IDLE
        swapped = working and op.swap
        first = self.colour("SrcB" if swapped else "SrcA") if active else IDLE
        second = self.colour("SrcA" if swapped else "SrcB") if active else IDLE
        line = WIDE if active else THIN
        # The swap: straight through, or crossed for RSB.
        left, top, right, bottom = SWAP
        tags = ("block:Swap",)
        self.box(left, top, right, bottom, outline=outline, fill=fill, width=width,
                 tags=tags + shining)
        self.text((left + right) / 2, top + 3, "SWAP", anchor="n", font="bold",
                  fill=INK if in_use else look.words, tags=tags)
        rsb = ("1" if op.swap else "0") if working else None
        swapper = "RSC" if working and op.control == xray.ALU_RSC else "RSB"
        self.text((left + right) / 2, bottom - 3, f"{swapper} = {rsb}" if rsb else "RSB",
                  anchor="s", fill=signal_colour(rsb) if rsb else look.words, tags=tags)
        for start, end, net in ((FIRST_Y, SECOND_Y if swapped else FIRST_Y, "SrcA"),
                                (SECOND_Y, FIRST_Y if swapped else SECOND_Y, "SrcB")):
            self.line([(left, start), (right, end)], width=line,
                      fill=self.colour(net) if active else gray_on(fill), tags=("wire:Swap",))
        # The first operand goes to the adder; the second, or its inverse, to the multiplexer.
        self.line([(right, FIRST_Y), (ADDER_SHAPE[0][0], FIRST_Y)], fill=first, width=line,
                  arrow="last", tags=("wire:First",))
        if in_use:                      # under its line: the carry in's names stand over it
            self.text(230, FIRST_Y + 3, hex32(op.first), anchor="nw", font="code",
                      fill=first if active else values, tags=("wire:First",))
        mux_left = SECOND_MUX[0][0]
        taken = (1 if op.invert else 0) if working else None
        for number, y in ((0, SECOND_Y), (1, NOT_Y)):
            chosen = active and taken == number
            points = [(right, y), (mux_left, y)] if number == 0 else [(170, y), (mux_left, y)]
            self.line(points, fill=second, width=WIDE if chosen else THIN, arrow="last",
                      tags=("wire:Second",))
        self.line([(140, SECOND_Y), (140, NOT_Y), (152, NOT_Y)], fill=second, width=line,
                  arrow="last", tags=("wire:Second",))
        self._dot(140, SECOND_Y, second, tags=("wire:Second",))
        gate = self.gate("NOT", 152, NOT_Y, outline=outline, fill=fill)
        for tag in ("block:Not",) + shining:
            self.canvas.addtag_withtag(tag, gate)
        self.text(161, 196, "NOT", anchor="n", fill=INK if in_use else IDLE)
        self.canvas.create_polygon(*self.flat(SECOND_MUX), outline=outline, fill=fill,
                                   width=self.d(1.6 if active else 1.2),
                                   tags=("block:SecondMux",) + shining)
        for number, y in ((0, SECOND_Y), (1, NOT_Y)):
            self.text(mux_left + 3, y, str(number), anchor="w",
                      fill=INK if in_use else look.words, tags=("block:SecondMux",))
        if in_use:
            for number, y in ((0, SECOND_Y), (1, NOT_Y)):
                if number == taken:
                    self._dot(mux_left, y, INK if active else MARK)
                else:
                    self._cross(mux_left - 6, y, ("wire:Second",))
        # SUB, RSB, SBC or RSC: the multiplexer takes the inverse; SUB and RSB add a carry of 1.
        invert = ("1" if op.invert else "0") if working else None
        colour = signal_colour(invert) if invert else IDLE
        tags = ("wire:Invert",)
        name = "SBC or RSC" if working and op.carry is not None else "SUB or RSB"
        self.text(SELECT_X, 102, f"{name} = {invert}" if invert else name, anchor="s",
                  fill=colour, tags=tags)
        mux_top = SECOND_MUX[0][1] + (SECOND_MUX[1][1] - SECOND_MUX[0][1]) / 2
        signal = BIT if invert else THIN
        self.line([(SELECT_X, 104), (SELECT_X, mux_top)], fill=colour, width=signal,
                  arrow="last", tags=tags)
        left_x = CARRY_MUX[0][0]
        self.line([(SELECT_X, BRANCH_Y), (left_x, BRANCH_Y)], fill=colour, width=signal,
                  arrow="last", tags=tags)
        self._dot(SELECT_X, BRANCH_Y, colour, radius=1.8, tags=tags)
        self._carry(op, working, in_use, active, look, shining)
        # What the multiplexer takes goes to the adder.
        self.line([(SECOND_MUX[1][0], ADDED_Y), (ADDER_SHAPE[0][0], ADDED_Y)], fill=second,
                  width=line, arrow="last", tags=("wire:Added",))
        if in_use:
            self.text(230, ADDED_Y - 3, hex32(op.added), anchor="sw", font="code",
                      fill=second if active else values, tags=("wire:Added",))
        self.canvas.create_polygon(*self.flat(ADDER_SHAPE), outline=outline, fill=fill,
                                   width=self.d(width if active else 1.2),
                                   tags=("block:Adder",) + shining)
        self.text(350, SUM_Y, "+", anchor="center", font="bold",
                  fill=INK if in_use else look.words, tags=("block:Adder",))
        self.text(CARRY_X, 192, "ADDER", anchor="n", font="bold", fill=INK if in_use else IDLE)
        # The sum goes to the result multiplexer; the carry out and the overflow to the flags.
        alu = self.colour("ALUResult") if active else IDLE
        self.line([(ADDER_SHAPE[1][0], SUM_Y), (MUX_LEFT, SUM_Y)], fill=alu, width=line,
                  arrow="last", tags=("wire:Sum",))
        if in_use:
            chosen = part >= LEAVE and op.taken == "adder"
            self.text(374, SUM_Y - 3, hex32(op.sum), anchor="sw",
                      font="code_bold" if chosen else "code", fill=alu if active else values,
                      tags=("wire:Sum",))
            flags = self.colour("ALUFlags") if active else values
            self.text(374, SUM_Y + 6, f"carry out = {op.carry_out}", fill=flags,
                      tags=("wire:CarryOut",))
            self.text(374, SUM_Y + 22, f"overflow = {op.overflow}", fill=flags,
                      tags=("wire:Overflow",))

    def _carry(self, op, working, in_use, active, look, shining):
        """The adder's carry in: a multiplexer takes the subtract line (0 for ADD, 1 for SUB and
        RSB) or, for ADC, SBC and RSC, CarryIn, the C flag from the flags register. CarryIn is an
        addition: it comes only for these three. The carry in has the colour of the input taken:
        CarryIn's, or the subtract line's red or gray."""
        carried = working and op.carry is not None
        choice = ("1" if carried else "0") if working else None
        tags = ("block:CarryMux",)
        self.canvas.create_polygon(*self.flat(CARRY_MUX), outline=look.outline, fill=look.fill,
                                   width=self.d(1.6 if active else 1.2), tags=tags + shining)
        left_x = CARRY_MUX[0][0]
        for number, y in enumerate(CARRY_INPUTS):
            self.text(left_x + 2, y, str(number), anchor="w", fill=INK if in_use else look.words,
                      tags=tags)
        flags = self.colour("CarryIn") if carried else IDLE
        self.text(left_x - 16, CARRY_INPUTS[1], f"CarryIn = {op.carry}" if carried else "CarryIn",
                  anchor="e", fill=flags, tags=("wire:CarryIn",))
        self.line([(left_x - 14, CARRY_INPUTS[1]), (left_x, CARRY_INPUTS[1])], fill=flags,
                  width=BIT if carried else THIN, arrow="last", tags=("wire:CarryIn",))
        if in_use:
            taken = 1 if carried else 0
            self._dot(left_x, CARRY_INPUTS[taken], INK if active else MARK)
            if carried:                 # the subtract line brings a value too, rejected
                self._cross(left_x - 6, CARRY_INPUTS[0], ("wire:Invert",))
        top = CARRY_MUX[0][1] + (CARRY_MUX[1][1] - CARRY_MUX[0][1]) * \
            (CARRY_SELECT - CARRY_MUX[0][0]) / (CARRY_MUX[1][0] - CARRY_MUX[0][0])  # its edge
        select = signal_colour(choice) if choice else IDLE
        self.line([(CARRY_SELECT, 92), (CARRY_SELECT, top)], fill=select,
                  width=BIT if choice else THIN, arrow="last", tags=("wire:WithCarry",))
        self.text(CARRY_SELECT - 4, 96, f"with carry = {choice}" if choice else "with carry",
                  anchor="e", fill=select, tags=("wire:WithCarry",))
        # The carry in goes down into the adder.
        carry = str(op.carry_in) if in_use else None
        out = (flags if carried else signal_colour(carry)) if carry else IDLE
        self.line([(CARRY_MUX[1][0], CARRY_OUT), (CARRY_X, CARRY_OUT), (CARRY_X, 126)], fill=out,
                  width=BIT if carry else THIN, arrow="last", tags=("wire:CarryInAdder",))
        self.text(CARRY_X + 6, 118, f"carry in = {carry}" if carry else "carry in", anchor="w",
                  fill=out, tags=("wire:CarryInAdder",))

    def _units(self, op, part, state):
        """AND, ORR, EOR, BIC, MOV and MVN, each with what it makes of the operands; without
        SrcA, the units that need it stay pale, with no value."""
        working = op is not None and part >= WORK
        for (name, code, what), top in zip(UNITS, TOPS):
            middle = top + UNIT_HEIGHT / 2
            makes = op is not None and code in op.values
            used = working and makes
            taken = working and code == op.taken
            rejected = used and part >= LEAVE and not taken
            active = used and not rejected
            lit = active and state == WORKING
            look = LOOKS[look_of(makes and not rejected, working=lit, done=active,
                                 resting=self.resting)]
            tags = (f"block:{name}",)
            self.box(UNIT_LEFT, top, UNIT_RIGHT, top + UNIT_HEIGHT, outline=look.outline,
                     fill=look.fill, width=1.6 if active else 1,
                     tags=tags + (("lit",) if lit else ()))
            colour = INK if used else look.words
            self.text(UNIT_LEFT + 6, middle, name, anchor="w", font="bold", fill=colour,
                      tags=tags)
            self.text(UNIT_LEFT + 42, middle, what, anchor="w", fill=colour, tags=tags)
            if used:
                chosen = taken and part >= LEAVE
                fill = self.colour("ALUResult") if chosen else INK if active else \
                    MARK if rejected else IDLE
                self.text(UNIT_RIGHT - 6, middle, hex32(op.values[code]), anchor="e",
                          font="code_bold" if chosen else "code", fill=fill, tags=tags)
            self.line([(UNIT_RIGHT, middle), (MUX_LEFT, middle)], arrow="last",
                      fill=self.colour("ALUResult") if active else IDLE,
                      width=WIDE if active else THIN, tags=(f"wire:{name}",))

    def _multiplier(self, op, part, state):
        """The multiplier: SrcA x SrcB, and + RD4 for MLA (ALUControl 1010). An addition: it
        works only when ALUControl chooses it, and else stays pale, with no value."""
        working = op is not None and part >= WORK and op.multiplies
        lit = working and state == WORKING
        look = LOOKS[look_of(op is not None and op.multiplies, working=lit, done=working,
                             resting=self.resting)]
        tags = ("block:Multiplier",)
        self.box(UNIT_LEFT, MUL_TOP, UNIT_RIGHT, MUL_TOP + MUL_HEIGHT, outline=look.outline,
                 fill=look.fill, width=1.6 if working else 1,
                 tags=tags + (("lit",) if lit else ()))
        colour = INK if working else look.words
        self.text(UNIT_LEFT + 6, MUL_Y, "MUL", anchor="w", font="bold", fill=colour, tags=tags)
        what = MAKES[op.control] if working else "SrcA x SrcB; with 1010, + RD4"
        self.text(UNIT_LEFT + 42, MUL_Y, what, anchor="w", fill=colour, tags=tags)
        if working:
            chosen = part >= LEAVE
            self.text(UNIT_RIGHT - 6, MUL_Y, hex32(op.values["multiplier"]), anchor="e",
                      font="code_bold" if chosen else "code",
                      fill=self.colour("ALUResult") if chosen else INK, tags=tags)
        self.line([(UNIT_RIGHT, MUL_Y), (MUX_LEFT, MUL_Y)], arrow="last",
                  fill=self.colour("ALUResult") if working else IDLE,
                  width=WIDE if working else THIN, tags=("wire:Multiplier",))

    def _movt(self, op, part, state):
        """The unit of MOVT (ALUControl 1110): the low half of SrcB, the immediate, becomes the
        high half, and the low half of RD4, the old value of Rd, stays. An addition: it works only
        for MOVT, and else stays pale, with no value."""
        working = op is not None and part >= WORK and op.joins
        lit = working and state == WORKING
        look = LOOKS[look_of(op is not None and op.joins, working=lit, done=working,
                             resting=self.resting)]
        tags = ("block:MOVT",)
        self.box(UNIT_LEFT, MOVT_TOP, UNIT_RIGHT, MOVT_TOP + MOVT_HEIGHT, outline=look.outline,
                 fill=look.fill, width=1.6 if working else 1,
                 tags=tags + (("lit",) if lit else ()))
        colour = INK if working else look.words
        self.text(UNIT_LEFT + 6, MOVT_Y, "MOVT", anchor="w", font="bold", fill=colour, tags=tags)
        what = MAKES[xray.ALU_MOVT]
        if working:                     # the two halves
            what = f"SrcB[15:0] 0x{op.b & 0xFFFF:04X} : RD4[15:0] 0x{op.rd4 & 0xFFFF:04X}"
        self.text(UNIT_LEFT + 42, MOVT_Y, what, anchor="w", fill=colour, tags=tags)
        if working:
            chosen = part >= LEAVE
            self.text(UNIT_RIGHT - 6, MOVT_Y, hex32(op.values["movt"]), anchor="e",
                      font="code_bold" if chosen else "code",
                      fill=self.colour("ALUResult") if chosen else INK, tags=tags)
        self.line([(UNIT_RIGHT, MOVT_Y), (MUX_LEFT, MOVT_Y)], arrow="last",
                  fill=self.colour("ALUResult") if working else IDLE,
                  width=WIDE if working else THIN, tags=("wire:MOVT",))

    def _result_mux(self, op, part, state):
        """The multiplexer that ALUControl drives, and ALUResult leaving it: it waits while the
        units work and lights when it takes one of their values."""
        here = op is not None and part >= ARRIVE
        working = op is not None and part >= WORK
        decided = op is not None and part >= LEAVE
        out = op is not None and part >= OUT
        lit = decided and state == WORKING
        look = LOOKS[look_of(op is not None, working=lit, done=decided, resting=self.resting)]
        tags = ("block:ResultMux",)
        self.canvas.create_polygon(*self.flat(RESULT_MUX),
                                   outline=INK if working else look.outline, fill=look.fill,
                                   width=self.d(1.6 if decided else 1.2),
                                   tags=tags + (("lit",) if lit else ()))
        inputs = [("adder", SUM_Y)] + [(code, top + UNIT_HEIGHT / 2)
                                       for top, (_, code, _) in zip(TOPS, UNITS)]
        inputs += [("multiplier", MUL_Y), ("movt", MOVT_Y)]
        codes = [(SUM_Y - 30 + 12 * number, code) for number, code in enumerate(ADDER)]
        codes += [(y, code) for code, y in inputs[1:-2]]
        codes += [(MUL_Y - 6, xray.ALU_MUL), (MUL_Y + 6, xray.ALU_MLA), (MOVT_Y, xray.ALU_MOVT)]
        for y, code in codes:
            chosen = decided and code == op.control
            colour = INK if chosen or (working and not decided) else gray_on(look.fill)
            self.text(MUX_LEFT + 4, y, code, anchor="w", font="code_bold" if chosen else "code",
                      fill=colour, tags=tags)
        if decided:                     # only an input that brings a value is rejected
            for unit, y in inputs:
                if unit == op.taken:
                    self._dot(MUX_LEFT, y)
                elif unit in op.values:
                    self._cross(MUX_LEFT - 6, y, (f"wire:{unit}",))
        # ALUControl comes in from above.
        value = op.control if here else None
        tags = ("wire:ALUControl",)
        top = RESULT_MUX[0][1] + (RESULT_MUX[1][1] - RESULT_MUX[0][1]) / 2
        points = [(CONTROL_X, 100), (CONTROL_X, top)]
        self.line(points, fill=IDLE, width=THIN, arrow="last", tags=tags)
        if here:
            self._travel([points], [True], signal_colour(value), 2.0, tags, part == ARRIVE, 0.0,
                         ARRIVED)
        self.text(CONTROL_X, 98, f"ALUControl = {value}" if value else "ALUControl", anchor="s",
                  fill=signal_colour(value) if value else IDLE, tags=tags)
        # ALUResult leaves to the right.
        tags = ("wire:ALUResult",)
        points = [(MUX_RIGHT, OUT_Y), (744, OUT_Y)]
        self.line(points, fill=IDLE, width=THIN, arrow="last", tags=tags)
        if decided:
            self._travel([points], [True], self.colour("ALUResult"), WIDE, tags, part == LEAVE,
                         LEAVES, LEFT)
        self.text(MUX_RIGHT + 8, OUT_Y - 3,
                  f"ALUResult = {hex32(op.result)}" if out else "ALUResult", anchor="sw",
                  font="code_bold" if out else "small",
                  fill=self.colour("ALUResult") if out else IDLE, tags=tags)

    def _flags(self, op, part):
        """The four flags: where each comes from, its value, and whether it is written. They wait
        until they leave, and are done then: the flags register in the control unit writes
        them."""
        out = op is not None and part >= OUT
        look = LOOKS[look_of(op is not None, done=out, resting=self.resting)]
        flags = self.colour("ALUFlags")
        for number, flag in enumerate("NZCV"):
            left = 16 + FLAG_STEP * number
            tags = (f"block:Flag{flag}",)
            self.box(left, FLAG_TOP, left + FLAG_WIDTH, FLAG_TOP + FLAG_HEIGHT,
                     outline=look.outline, fill=look.fill, tags=tags)
            self.text(left + 8, FLAG_TOP + 2, f"{flag} = {op.bit(flag)}" if out else flag,
                      font="title", fill=flags if out else look.words, tags=tags)
            how = op.how(flag) if op is not None else FLAG_HOWS[flag]
            self.text(left + 8, FLAG_TOP + 21, how, fill=INK if out else look.words, tags=tags)
            if out:
                written = op.written[flag]
                said = "written" if written else f"kept: {flag} stays {op.bit(flag, op.before)}"
                self.text(left + 8, FLAG_TOP + 37, said, fill=ON if written else MARK, tags=tags)
        if out:
            self.text(16, SENTENCE_Y, op.flag_sentence(), fill=INK)
            self.text(744, SENTENCE_Y, f"ALUFlags NZCV = {op.flags:04b}", anchor="ne",
                      fill=flags)

    # Helpers ---------------------------------------------------------------------------------

    def _dot(self, x, y, colour=INK, radius=2.2, tags=()):
        cx, cy = self.xy(x, y)
        r = self.d(radius)
        return self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=colour,
                                       outline=colour, tags=tags)

    def _cross(self, x, y, tags=()):
        """The gray cross of a rejected input."""
        for dy in (-3, 3):
            self.line([(x - 3, y - dy), (x + 3, y + dy)], fill=MARK, width=1.6, tags=tags)

    def _travel(self, polylines, arrows, colour, width, tags, moving, start, end):
        """Draw a value on polylines in colour: each polyline starts at the value's source (the
        first point of the first) or on an earlier one. While moving, the value travels from
        its source in the share start to end of the step (_move() grows the lines)."""
        offsets = []
        for index, points in enumerate(polylines):
            offset = 0.0
            for other, other_offset in zip(polylines[:index], offsets):
                along = _along(other, points[0])
                if along is not None:
                    offset = other_offset + along
                    break
            offsets.append(offset)
        longest = max(offset + _length(points) for points, offset in zip(polylines, offsets))
        for points, arrow, offset in zip(polylines, arrows, offsets):
            item = self.line(points, fill=colour, width=width, arrow="last" if arrow else "none",
                             tags=tags)
            if moving:
                self._moving.append((item, points, offset, longest, start, end))

    def _move(self, fraction):
        """Grow the lines of the values that travel to where they are at fraction of the step."""
        canvas = self.canvas
        for item, points, offset, longest, start, end in self._moving:
            share = min(1.0, max(0.0, (fraction - start) / (end - start)))
            reach = share * longest - offset
            if reach <= 0:
                canvas.itemconfigure(item, state="hidden")
                continue
            part = cut(points, reach)
            canvas.coords(item, *self.flat(part if len(part) > 1 else part * 2))
            canvas.itemconfigure(item, state="normal")


def _length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def _along(points, point):
    """How far along a polyline point lies, or None when it is not on it."""
    travelled = 0.0
    for a, b in zip(points, points[1:]):
        (x1, y1), (x2, y2), (x, y) = a, b, point
        if min(x1, x2) - 0.01 <= x <= max(x1, x2) + 0.01 and \
                min(y1, y2) - 0.01 <= y <= max(y1, y2) + 0.01 and \
                abs((x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)) < 0.01:
            return travelled + math.dist(a, point)
        travelled += math.dist(a, b)
    return None


INSIDE["ALU"] = ALUWindow
