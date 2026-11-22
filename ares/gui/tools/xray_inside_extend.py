# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Inside Extend and inside the shifter: the windows of ARM X-Ray for these two blocks.

Extend builds the 32-bit immediate in one of five ways, or passes on the offset
that the pass counter sends for a pass of LDM, STM, PUSH or POP (ImmSrc 011),
and ImmSrc, three bits, chooses which: the window shows the bits that come in,
the six ways side by side with what each makes of them, and the multiplexer that
ImmSrc drives. Two ways join the pieces of a split field: imm4 (Instr 19:16) and
imm12 make the 16-bit immediate of MOVW and MOVT (100), imm4H (Instr 11:8) and
imm4L (Instr 3:0) the 8-bit offset of a halfword or signed transfer (101). An
instruction without an immediate (ImmSrc XXX) does not use Extend: the block
stays pale, with no way chosen, and ImmSrc comes dashed, as an X.

The shifter shifts RD2 by the amount in the word, or for a shift by a register
by RD4[7:0], the low byte of Rs: a small multiplexer that ShiftReg drives takes
one or the other. An instruction that reads no register through RD2 does not use
it: the block stays pale.
"""

from ... import xray, xray_film
from .xray_inside import (DONE, IDLE, IDLE_STATE, INK, INSIDE, LOOKS, MARK, UNUSED, WORKING,
                          InsideWindow, bit_text, look_of, signal_colour, system_note)

EXTEND_HEADING = "Six Ways and the ImmSrc Multiplexer"
EXTEND_ABOUT = ("Extend makes the immediate of the word 32 bits wide, in one of five ways,\n"
                "or passes on the pass counter's offset; ImmSrc chooses which.")
SHIFTER_HEADING = "Kind and Amount of the Shift"
SHIFTER_ABOUT = ("The shifter moves the bits of RD2 left or right, by an amount in the word\n"
                 "or in a register, before the ALU takes it.")
WAYS = (("000", "ROTATE", "imm8 rotated right by 2 x rot"),
        ("001", "ZERO-EXTEND", "imm12 with 20 zeros in front"),
        ("010", "SIGN-EXTEND x 4", "imm24 with its sign, times 4"),
        ("011", "PASS OFFSET", "the pass counter's Offset"),
        ("100", "JOIN imm16", "imm4:imm12 with 16 zeros in front"),
        ("101", "JOIN imm8", "imm4H:imm4L with 24 zeros in front"))
# A way that is not the instruction's own works on bits that are no such field of it: they are
# named by their place in the word instead.
BITS = {"rot": "bits 11:8", "imm8": "bits 7:0", "imm12": "bits 11:0", "imm24": "bits 23:0",
        "imm4": "bits 19:16", "imm4H": "bits 11:8", "imm4L": "bits 3:0"}
HOW = {"000": "7:0 rotated right by 2 x 11:8", "001": "11:0 with 20 zeros in front",
       "010": "23:0 with sign, times 4", "011": "the pass counter's Offset",
       "100": "19:16 and 11:0 joined, zeros in front", "101": "11:8 and 3:0 joined, zeros in front"}
WAY_LEFT, WAY_WIDTH, WAY_STEP = 12, 132, 138    # the boxes of the six ways
WAY_TOP, WAY_BOTTOM = 76, 234
DETAILS = (132, 148, 164)                       # the lines that say what a way takes
VALUE_Y, BINARY_Y = 186, (202, 216)             # what it makes, in hexadecimal and in binary
MUX_TOP, MUX_BOTTOM = 268, 302                  # the multiplexer ImmSrc drives, under the ways
# Where each way enters the multiplexer, and the height of its line's way across: the ways
# farther from the multiplexer go across lower, so that no two lines cross.
MUX_INPUTS = {"000": 363, "001": 387, "010": 411, "011": 435, "100": 459, "101": 483}
ACROSS = {"000": 256, "001": 250, "010": 244, "011": 244, "100": 250, "101": 256}
MUX_MIDDLE = 423
EXTEND_OUT = 0.6                # ExtImm leaves Extend at this share of its step
SHIFTER_OUT = 0.5               # the shifted value leaves the shifter at this share of its step
# The shifter's amount multiplexer: Instr 11:7 (0) or RD4[7:0] (1), ShiftReg its select.
AMOUNT_MUX = (296, 316, 287, 321)       # left, right, top, bottom
AMOUNT_INPUTS = (296, 312)


def way_lines(word, imm, name_of, arrived):
    """The lines that say what way imm takes of word, named as name_of names a field."""
    if imm == "000":
        rot, imm8 = word >> 8 & 0xF, word & 0xFF
        return ((f"{name_of('rot')} = {rot:04b} = {rot}" if arrived else name_of("rot"), "small"),
                (f"{name_of('imm8')} = {imm8:08b}" if arrived else name_of("imm8"), "small"),
                (f"rotated right by {2 * rot}" if arrived else "", "small"))
    if imm == "001":
        imm12 = word & 0xFFF
        return ((f"{name_of('imm12')} =" if arrived else name_of("imm12"), "small"),
                (f"{imm12:012b}" if arrived else "", "code"))
    if imm == "010":
        imm24 = word & 0xFFFFFF
        return ((f"{name_of('imm24')} = 0x{imm24:06X}" if arrived else name_of("imm24"), "small"),
                ("sign bit = %d" % (imm24 >> 23) if arrived else "", "small"),
                ("then 2 zeros at the right" if arrived else "", "small"))
    if imm == "100":
        imm4, imm12 = word >> 16 & 0xF, word & 0xFFF
        return ((f"{name_of('imm4')} = {imm4:04b}" if arrived else name_of("imm4"), "small"),
                (f"{name_of('imm12')} =" if arrived else name_of("imm12"), "small"),
                (f"{imm12:012b}" if arrived else "", "code"))
    high, low = word >> 8 & 0xF, word & 0xF                     # 101
    return ((f"{name_of('imm4H')} = {high:04b}" if arrived else name_of("imm4H"), "small"),
            (f"{name_of('imm4L')} = {low:04b}" if arrived else name_of("imm4L"), "small"))


class ExtendWindow(InsideWindow):
    """Inside Extend (see the module's description)."""

    BLOCK = "Extend"
    TITLE = "Inside Extend"
    HEADING = EXTEND_HEADING
    ABOUT = EXTEND_ABOUT
    SIZE = (846, 340)

    def key_of(self, film, moment, context, state, fraction):
        """The picture changes also where ExtImm leaves, within the block's step."""
        out = state == WORKING and fraction > EXTEND_OUT
        return super().key_of(film, moment, context, state, fraction) + (out,)

    def redraw(self, film, moment, context, state, fraction):
        trace = context.trace
        self.heading(16, 12)
        if trace is None or not trace.signals or system_note(trace, ""):
            why = "No instruction is shown." if trace is None else system_note(trace, "Extend") \
                or "This instruction does not use this datapath: Extend does not work for it."
            self.text(16, 44, why, fill=INK)
            return
        word = trace.word
        imm_src = trace.signals["ImmSrc"]
        used = trace.values.get("ExtImm") is not None
        arrived = used and state != IDLE_STATE
        offset = trace.values.get("Offset")
        ext_imm = self.colour("ExtImm")
        if used and offset is not None:     # a pass: the offset comes from the pass counter
            self.text(16, 44, "In: Offset, from the pass counter", fill=INK)
            self.text(220, 44, f"0x{offset:08X}" if arrived else "(not here yet)", font="code",
                      fill=self.colour("Offset") if arrived else IDLE)
        elif used:                      # the bits that come in: Instr 23:0
            self.text(16, 44, "In: Instr 23:0", fill=INK)
            bits = bit_text(word & 0xFFFFFF, 24) if arrived else "(not here yet)"
            self.text(120, 44, bits, font="code", fill=self.colour("Imm") if arrived else IDLE)
        else:
            self.text(16, 44, f"Extend is {UNUSED}.", font="bold", fill=INK)
        # The six ways: the one ImmSrc takes waits, works and is done; the others make values that
        # are rejected, so the instruction does not use them: they stay pale.
        left = WAY_LEFT
        for imm, name, how in WAYS:
            taken = used and imm == imm_src
            value = offset if imm == "011" else xray.extend(word, imm)
            lit = arrived and taken
            part = LOOKS[look_of(taken, working=lit and state == WORKING, done=lit)]
            self.box(left, WAY_TOP, left + WAY_WIDTH, WAY_BOTTOM, outline=part.outline,
                     fill=part.fill, width=1.6 if lit else 1)
            colour = INK if arrived else part.words
            own = used and imm == imm_src       # the field of the instruction: its own names
            name_of = (lambda field: field) if own else BITS.get  # noqa: E731
            self.text(left + 8, WAY_TOP + 8, f"{imm}: {name}", font="bold", fill=colour)
            self.text(left + 8, WAY_TOP + 24, how if own else HOW[imm], fill=colour,
                      width=(WAY_WIDTH - 16) * self.k)
            if imm == "011":
                lines = (("Offset =" if arrived and value is not None else
                          "no offset comes" if arrived else "Offset", "small"),)
            else:
                lines = way_lines(word, imm, name_of, arrived)
            for y, (said, font) in zip(DETAILS, lines):
                self.text(left + 8, y, said, font=font, fill=colour)
            known = arrived and value is not None
            self.text(left + 8, VALUE_Y, f"0x{value:08X}" if known else "", font="code_bold",
                      fill=colour)
            binary = bit_text(value, 32, 8) if value is not None else ""
            self.text(left + 8, BINARY_Y[0], binary[:17] if known else "", font="code",
                      fill=colour)
            self.text(left + 8, BINARY_Y[1], binary[18:] if known else "", font="code",
                      fill=colour)
            if not taken and known:
                self.text(left + WAY_WIDTH - 8, VALUE_Y, "rejected", anchor="ne", fill=MARK)
            # Into the multiplexer: down from the box's middle, across, and down to its input.
            entry, across = MUX_INPUTS[imm], ACROSS[imm]
            middle = left + WAY_WIDTH / 2
            self.line([(middle, WAY_BOTTOM), (middle, across), (entry, across), (entry, MUX_TOP)],
                      fill=ext_imm if lit else IDLE, width=2.4 if lit else 1.2, arrow="last")
            if arrived and taken:       # a dot at the input taken, a cross at the others
                x, y = self.xy(entry, MUX_TOP - 4)
                reach = self.d(2.4)
                self.canvas.create_oval(x - reach, y - reach, x + reach, y + reach, fill=INK,
                                        outline=INK, tags=("dot",))
            elif known:
                y = MUX_TOP - 6
                self.line([(entry - 3, y - 3), (entry + 3, y + 3)], fill=MARK, width=1.6,
                          tags=("cross",))
                self.line([(entry - 3, y + 3), (entry + 3, y - 3)], fill=MARK, width=1.6,
                          tags=("cross",))
            left += WAY_STEP
        # The multiplexer ImmSrc drives (its inputs at the top), and ExtImm under it, in the
        # colour of the way taken. An X comes dashed, as it leaves the control unit.
        part = LOOKS[look_of(used, working=arrived and state == WORKING, done=state == DONE)]
        first, last = min(MUX_INPUTS.values()) - 22, max(MUX_INPUTS.values()) + 22
        self.canvas.create_polygon(*self.flat([(first, MUX_TOP), (last, MUX_TOP),
                                               (last - 16, MUX_BOTTOM),
                                               (first + 16, MUX_BOTTOM)]),
                                   outline=part.outline, fill=part.fill, width=self.d(1.2))
        for imm, x in MUX_INPUTS.items():
            self.text(x, MUX_TOP + 4, imm, anchor="n", fill=part.words)
        shown = arrived or not used
        select_y = MUX_BOTTOM - 8
        edge = last - 16 * (select_y - MUX_TOP) / (MUX_BOTTOM - MUX_TOP)
        self.line([(edge + 26, select_y), (edge + 1, select_y)],
                  fill=signal_colour(imm_src) if shown else IDLE, arrow="last",
                  dash=(4, 3) if "X" in imm_src else "")
        self.text(edge + 30, select_y, f"ImmSrc = {imm_src}", anchor="w",
                  fill=signal_colour(imm_src) if shown else IDLE)
        out = used and (state == DONE or (state == WORKING and fraction > EXTEND_OUT))
        self.line([(MUX_MIDDLE, MUX_BOTTOM), (MUX_MIDDLE, MUX_BOTTOM + 24)],
                  fill=ext_imm if out else IDLE, width=2.4 if out else 1.2, arrow="last")
        if out:
            self.text(MUX_MIDDLE + 10, MUX_BOTTOM + 14, f"ExtImm = 0x{trace.values['ExtImm']:08X}",
                      font="code_bold", fill=ext_imm)


class ShifterWindow(InsideWindow):
    """Inside the shifter: the value before and after, the kind and amount of the shift, and
    the bit that becomes the carry."""

    BLOCK = "Shifter"
    TITLE = "Inside the Shifter"
    HEADING = SHIFTER_HEADING
    ABOUT = SHIFTER_ABOUT
    SIZE = (700, 346)

    def key_of(self, film, moment, context, state, fraction):
        """The picture changes also where the shifted value leaves, within the block's step."""
        out = state == WORKING and fraction > SHIFTER_OUT
        return super().key_of(film, moment, context, state, fraction) + (out,)

    def redraw(self, film, moment, context, state, fraction):
        trace = context.trace
        self.heading(16, 12)
        if trace is None or not trace.signals or system_note(trace, ""):
            why = "No instruction is shown." if trace is None else \
                system_note(trace, "the shifter") or \
                "This instruction does not use this datapath: the shifter does not work for it."
            self.text(16, 44, why, fill=INK)
            return
        values = trace.values
        rd2 = values.get("RD2")
        if rd2 is None:
            self._unused()
            return
        word = trace.word
        arrived = state != IDLE_STATE
        shift_on = trace.signals["Shift"] == "1"
        by_register = trace.signals.get("ShiftReg") == "1"
        kind, amount = word >> 5 & 3, word >> 7 & 0x1F
        if by_register:                 # the amount is the low byte of Rs, read on RD4
            amount = values["RD4"] & 0xFF
        text = xray.shift_text(word) or "LSL #0"
        result, carry = values["Shifted"], values["ShiftCarry"]
        colour = INK if arrived else IDLE
        self.text(16, 48, f"Shift = {trace.signals['Shift']}",
                  fill=signal_colour(trace.signals["Shift"]) if arrived else IDLE)
        if not arrived:
            said = "kind and amount: not here yet"
        elif by_register:
            said = f"kind: {xray.SHIFT_NAMES[kind]}   amount (RD4[7:0], R{values['A4']}): {amount}"
        elif shift_on:
            said = f"kind: {xray.SHIFT_NAMES[kind]}   amount (Instr 11:7): {amount}"
        elif "shamt5" in {name for name, *_ in xray_film.fields_of(trace)}:
            said = "no shift: shamt5 is 0"
        else:
            said = "no shift: bits 11:7 of the word are not a shift amount here"
        self.text(120, 48, said, fill=colour)
        self.text(16, 76, "In (RD2):", fill=colour)
        self.text(120, 76, bit_text(rd2, 32, 4) if arrived else "(not here yet)", font="code",
                  fill=self.colour("RD2") if arrived else IDLE)
        self.text(16, 98, f"0x{rd2:08X}" if arrived else "", font="code", fill=colour)
        done = state == DONE or (state == WORKING and fraction > SHIFTER_OUT)
        part = LOOKS[look_of(True, working=state == WORKING, done=state == DONE)]
        self.box(110, 120, 600, 170, outline=part.outline, fill=part.fill)
        if shift_on and by_register and amount == 0:
            what = f"{text}: R{values['A4']}[7:0] is 0: the value passes on unchanged, C as it is"
        elif shift_on and by_register and (amount >= 32 and kind != 3):
            what = (f"{text}: {amount} places, 32 or more: every bit has gone, "
                    + ("the sign bit fills all 32" if kind == 2 else "the result is 0"))
        elif shift_on and by_register and kind == 3:
            turn = amount & 31
            what = f"{text}: the bits turn {turn} places right ({amount} modulo 32)" if turn else \
                f"{text}: {amount} is a multiple of 32: the bits come back; C is bit 31"
        elif shift_on:
            places = "one place" if amount == 1 else f"{amount or 32} places"
            towards = "left" if kind == 0 else "right"
            what = f"{text}: every bit moves {places} {towards}" if text != "RRX" else \
                "RRX: every bit moves one place right; C comes in at the top"
        else:                           # a shift by a register always has Shift 1
            what = "Shift is 0: the value passes on unchanged"
        self.text(355, 145, what if arrived else "", anchor="center", fill=colour)
        self.text(16, 190, "Out (Shifted):", fill=colour)
        self.text(120, 190, bit_text(result, 32, 4) if done else "", font="code",
                  fill=self.colour("Shifted"))
        self.text(16, 212, f"0x{result:08X}" if done else "", font="code", fill=colour)
        if shift_on and done:
            self.text(16, 246, f"The last bit shifted out is {carry}: the carry for a logical "
                      "operation with S (ShiftC).", fill=INK)
        self._amount(trace, state, shift_on, by_register)

    def _amount(self, trace, state, shift_on, by_register):
        """The amount multiplexer: ShiftReg 0 takes Instr 11:7, 1 takes RD4[7:0]. RD4 is an
        addition: it comes only for a shift by a register. The amount leaves in the colour of
        the input taken."""
        values, word = trace.values, trace.word
        arrived = state != IDLE_STATE
        used = arrived and (shift_on or by_register)
        left, right, top, bottom = AMOUNT_MUX
        slope = (bottom - top) / 5
        part = LOOKS[look_of(shift_on or by_register, working=used and state == WORKING,
                             done=used and state == DONE)]
        self.mux(left, top, right, bottom, outline=part.outline, fill=part.fill)
        for number, y in enumerate(AMOUNT_INPUTS):
            self.text(left + 2, y, str(number), anchor="w", fill=part.words)
        own = f"Instr 11:7 = {word >> 7 & 0x1F:05b}"
        rd4 = f"RD4[7:0] = {values['RD4'] & 0xFF}" if by_register else "RD4[7:0]"
        for number, (said, comes, net) in enumerate(((own, used, "Shamt"),
                                                     (rd4, used and by_register, "RD4"))):
            y = AMOUNT_INPUTS[number]
            fill = self.colour(net) if comes else IDLE
            self.text(left - 18, y, said if comes else said.split(" =")[0], anchor="e",
                      font="code", fill=fill)
            self.line([(left - 16, y), (left, y)], fill=fill, width=1.6 if comes else 1.0,
                      arrow="last")
        taken = 1 if by_register else 0
        if used:
            x, y = self.xy(left, AMOUNT_INPUTS[taken])
            reach = self.d(2.2)
            self.canvas.create_oval(x - reach, y - reach, x + reach, y + reach, fill=INK,
                                    outline=INK)
            if by_register:             # bits 11:7 come too, and are rejected
                y = AMOUNT_INPUTS[0]
                self.line([(left - 9, y - 3), (left - 3, y + 3)], fill=MARK, width=1.6)
                self.line([(left - 9, y + 3), (left - 3, y - 3)], fill=MARK, width=1.6)
        select = right - 3
        value = ("1" if by_register else "0") if used else None
        self.line([(select, top - 14), (select, top + slope * 11 / 14)],
                  fill=signal_colour(value) if value else IDLE, arrow="last")
        self.text(select, top - 15, f"ShiftReg = {value}" if value else "ShiftReg", anchor="s",
                  fill=signal_colour(value) if value else IDLE)
        middle = (top + bottom) / 2
        if by_register:
            amount = values["RD4"] & 0xFF
        else:
            amount = word >> 7 & 0x1F
        out = self.colour("RD4" if by_register else "Shamt") if used else IDLE
        self.line([(right, middle), (right + 26, middle)], fill=out, width=1.6 if used else 1.0,
                  arrow="last")
        self.text(right + 30, middle, f"amount = {amount}" if used else "amount", anchor="w",
                  fill=out)
        if used and by_register:
            self.text(16, 332, "From 32 on every bit has gone: LSL and LSR give 0, ASR the sign in "
                      "every bit; ROR turns by the amount modulo 32.", fill=INK)

    def _unused(self):
        """An instruction that reads no register through RD2: the shifter stays pale."""
        self.text(16, 48, f"The shifter is {UNUSED}.", font="bold", fill=INK)
        self.text(16, 76, "In (RD2):", fill=IDLE)
        part = LOOKS["unused"]
        self.box(110, 120, 600, 170, outline=part.outline, fill=part.fill)
        self.text(16, 190, "Out (Shifted):", fill=IDLE)


INSIDE["Extend"] = ExtendWindow
INSIDE["Shifter"] = ShifterWindow
