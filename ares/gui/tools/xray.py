# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Tools > ARM X-Ray: the datapath of a single-cycle ARM processor, one instruction at a time.

The diagram follows the textbook's single-cycle ARM processor (credits.TEXTBOOK),
with its additions in the same style. ares.xray works out what is on its wires,
ares.xray_film turns that into a film, and xray_picture draws it. The window plays
the film by a real clock: each Step of the program starts the film of the
instruction it ran. The tool hooks nothing: after Step it reads what the machine
recorded for Backstep, and at full speed it does nothing until the run stops.
"""

import re
import textwrap
import time
import tkinter as tk
from collections import namedtuple
from tkinter import font as tkfont
from tkinter import ttk

from ... import credits, syscalls, xray, xray_film
from ...floats import format_double, format_single
from ...machine import DIALOG, INPUT, StopReason
from ...runner import State
from ...settings import XRAY_SECONDS
from ...xray_film import fields_of
from .. import icons
from ..menubar import screen_area
from ..style import SUNKEN_FRAME, TEXT, sunken
from ..style import WINDOW as FIELD
from ..widgets import Tooltip, px, scale, tip_window
from . import xray_inside, xray_look, xray_picture
from .frame import ToolModel, ToolWindow, frame_of, when_settled
from .xray_look import DIM, IDLE, INK, STAGES, VALUES, WHITE
from .xray_picture import ORIGIN, Picture, fitted_zoom, points

CANVAS = (1056, 545)            # the canvas at zoom 1, in design pixels
MAX_ZOOM = 1.6                  # the largest zoom the window opens at
FRAME = 33                      # milliseconds between two pictures of a film (about 30 a second)
WAIT = 1e-6                     # how far before its end the film of an SVC that waits stays
RIGHT = CANVAS[0]               # the right side of the datapath
# Above the datapath stands the large heading alone. Under it (xray_picture.ORIGIN and SIZE: it
# ends at 454), in two columns. At the left, from the top: the strip of the six parts, and the
# instruction as written above the table of its word. At the right: what the tool shows with
# the instruction's address and text, under it the line that says how to see inside a block,
# both one bold line, and then what the instruction did, in two columns of its own: the
# changes, then the flags and the instruction that runs next.
STRIP = (6, 456)                # the strip's left and top
STRIP_BOX = (90, 4.4, 14)       # each part's box: width, gap between two, height
LINE = (6, 488)                 # where the instruction's line starts, above the table
TABLE = (6, 505)                # the table's top left corner
VIEW = (580, 463)               # the left middle of what the tool shows ("Just executed")
VIEW_GAP = 12                   # between it and the instruction
VIEW_WIDTH = 470                # the widest that line may be: the panel's width
HINT = (580, 477)               # the left middle of "To see inside a block, click it."
TIP_WIDTH = 1040                # the widest line of a strip part's tip, in pixels at 100 %
ROW = 13                        # the height of each of its rows: Field, Binary and Hex
NAME_WIDTH = 50                 # its first column, the rows' names
BIT_WIDTH = 16                  # the column of each bit, bit 31 at the left
TABLE_ROWS = ("Field", "Binary", "Hex")
HEADER = "#EEEEEE"              # the first column's cells
EMPTY = "#E2E2E2"               # the Field cell of bits that are no field: gray, without a name
TINT = 0.14                     # how much of its colour a lit cell takes
PANEL = ((580, 488, 276), (868, 488, 182))  # what it did: each column's left, top and width
PANEL_LINES = 4                 # the lines of each column
CONTROL = 0x4                   # event.state's Control
TOOLBAR = (("assemble", "Assemble the current file"),
           ("step", "Step: runs the next instruction and plays its whole film"),
           ("backstep", "Undo the last instruction"))
# The film's picture buttons (icons.FILM): their tips, with their keys. Play and Pause are one
# button, whose picture and tip change.
FILM_TIPS = {
    "film_pause": "Pause: stops the film here (Space)",
    "film_play": "Play: plays the film from here to its end (Space)",
    "film_back": "One step back: shows the step before (B)",
    "film_step": "One step forward: runs the next instruction one step at a time (O)",
    "film_end": "Skip to end: shows the whole instruction at once (E)",
}
FILM_KEYS = (("o", "one_button"), ("b", "back_button"), ("e", "skip_button"))
WHOLE, STEPS = "whole", "steps"  # how a film plays: all of it (Step), or one step at a time
CLICK_HINT = "To see inside a block, click it."
# How a control signal looks, in its tip (the picture has no key: the table is the key of the
# colours of the values, and this line and the Help that of the control signals).
SIGNAL_LOOK = "On the picture: red when a bit is 1, gray when 0, dashed when X (does not matter)"
UNUSED = "not used by this instruction"
KIND_HEADINGS = {
    xray.DP_REGISTER: "DATA PROCESSING INSTRUCTION", xray.DP_IMMEDIATE: "DATA PROCESSING INSTRUCTION",
    xray.LOAD_IMMEDIATE: "LOAD INSTRUCTION", xray.LOAD_REGISTER: "LOAD INSTRUCTION",
    xray.STORE_IMMEDIATE: "STORE INSTRUCTION", xray.STORE_REGISTER: "STORE INSTRUCTION",
    xray.BRANCH: "BRANCH INSTRUCTION", xray.BRANCH_LINK: "BRANCH INSTRUCTION",
    xray.BRANCH_EXCHANGE: "BRANCH INSTRUCTION", xray.SYSTEM_CALL: "SYSTEM CALL",
    xray.LOAD_MULTIPLE: "LOAD MULTIPLE INSTRUCTION", xray.STORE_MULTIPLE: "STORE MULTIPLE INSTRUCTION",
    xray.MULTIPLY: "MULTIPLY INSTRUCTION", xray.BRANCH_LINK_EXCHANGE: "BRANCH INSTRUCTION",
    xray.NO_OPERATION: "NO OPERATION", xray.MOVE_16: "DATA PROCESSING INSTRUCTION",
    xray.LOAD_HALF_IMMEDIATE: "LOAD INSTRUCTION", xray.LOAD_HALF_REGISTER: "LOAD INSTRUCTION",
    xray.STORE_HALF_IMMEDIATE: "STORE INSTRUCTION", xray.STORE_HALF_REGISTER: "STORE INSTRUCTION",
}
WAITING_HEADINGS = {INPUT: "Waits for a line typed in Run I/O",
                    DIALOG: "Waits for an answer in a dialog"}
POPUP_HEADING = "Waits for a line in the input dialog"
RUNS_NEXT = "Runs next"                 # the instruction at PC, not run yet
NOTHING_LEFT = "Nothing to show"      # Backstep undid all it kept (the Help says so)
NOTHING_RUN = "Nothing has run yet"     # since the program was loaded or Reset, or all undone
PART_SHORT = dict(zip(xray_film.PARTS, xray_film.PARTS))

HELP = f"""\
ARM X-Ray shows how the processor runs an instruction, as a film: the values travel along
the wires of the datapath, from the PC to the last write. The diagram is a textbook's
single-cycle ARM processor, with a few additions that real programs need. The textbook is
{credits.TEXTBOOK}

Click Connect to ARM, then Step through the program, with the tool's own Step button or the
main window's (F7), or with One step forward (O), which goes one step of the film at a time.
Assemble (F3) and Backstep (F8) are on the tool's toolbar too. Each Step plays the film of the
instruction that just ran, in six parts: Fetch, Decode, Execute, Memory, Write back and Next PC.
In the real circuit all of this happens within one clock cycle; the film spreads it out so that
it can be read.

ARM X-Ray and the Pipeline Simulator (Tools menu) show the same program in two ways. ARM X-Ray
shows one instruction going through a datapath that does everything in one clock cycle; the
Pipeline Simulator shows when each instruction would be in each stage of a datapath cut into
five stages, with several instructions inside at once. The stages have the same names in both,
Fetch, Decode, Execute, Memory and Write back (IF, ID, EX, MEM and WB there), and the program's
results never differ.

The large heading above the picture names the kind of instruction. Under the picture, at the
left, the strip marks the part that plays, in the colours of the Pipeline Simulator's stages
(Fetch is the colour of IF, Decode of ID and so on; Next PC has its own). Rest the mouse on a
part that plays or has played: its tip says what its steps have done so far, one sentence for
each step, in order, with the real numbers; a part that has not been reached has no tip. At the
right, in bold, the tool says what it shows, Just executed or Runs next for example, with the
instruction's address and text, and under it stands "To see inside a block, click it." What the
instruction did follows them.

A value leaves the block that makes it and travels along its wire as a small label, lit on a
band of its own colour, to every block that takes it, and rests beside that block's input once it
has arrived: lit for that step and the next, then on a light tint of its colour, so that it stays
easy to read. What the instruction changes, the register written, the memory word, the flags and
the PC, rests on the green that marks changed rows in the Registers pane. A value keeps its colour
wherever it goes: what comes from a field of the word keeps the field's colour through the blocks
it passes (Rn's number, the value read for it and SrcA; the second register's number, its value,
the shifter's output and the data stored; the immediate and ExtImm; Rd and A3), and after a
multiplexer a wire has the colour of the input it took. New values have colours of their own: the
PC and its sums brown, the ALU's result dark red, with the address and the result written back
that come from it, and the data read from memory blue. R15 reads as PCPlus8, so its value has the
PC's colour. A register's number travels on its wire as its four bits, as the table shows them:
1101 is R13; the register file's word, READ R13, names the register, and so do the tips and the
panel. A block that the instruction uses waits in a calm blue until its inputs have arrived,
lights up yellow while it works and says what it does: READ R1, ADD, WRITE R3; it keeps a lighter
tint once it is done. A block that the instruction does not use stays pale. At a multiplexer its
inputs arrive: a dot marks the input it takes, a gray cross one that it rejects, and its select
signal arrives with its value. A control signal is red when it is 1, gray when it is 0, and dashed
when the tables say X, does not matter; its tip says so too. Only what the instruction has
travels: bits that are no field of it, and a register, a block or a multiplexer that only they or
an X would steer, stay gray, with no dot, no cross and no value. So does a control signal that
steers only such gray parts; its tip still gives its value. A write whose enable is 0 shows a gray
bar where the data arrives: nothing is written. The control unit shows the condition check, for
example NE: Z = 0, executes. When the condition fails, nothing is written and the PC takes PC + 4.
The wires carry no bit numbers, only their arrows and, across a bus of more than one bit, a slash
with its width: which bits of the word a field's wire carries, the table under the picture shows,
and so does the wire's tip.

Under the strip stands the instruction as you wrote it, as the Source column shows it, with its
Basic form after it in brackets when the two differ: MOV R0, #20 (MOV R0, #0x14). An instruction
that no line of yours made by itself, such as the second word of a line that makes two, shows its
Basic form alone. Under it, a table breaks its word down, bit 31 at the left. Row Field names the
fields of its kind under the textbook's names, each cell as wide as its bits; row Binary has their
bits, and row Hex the word's eight hexadecimal digits, each under its four bits: the number on the
wire Instr. The table is the key of the colours: when the word splits, each field's cells take the
colour of its value on the picture, and the Hex row the colour of Instr; bits that are no field of
the instruction stay gray, without a name. Rest the mouse on a cell to see its field's name, its
bits, its value and where it goes. Beside the table, when the film ends, the panel lists what the
instruction did, as the program really ran it, in two columns: each register changed with its old
and new value and each word of memory written, also one stored over the same value, as many as the
columns hold (the rest are counted; the Registers pane and the memory show them all) and the flags
before and after. The instruction that runs next stands in the panel always, during the film too.
The panel and the film name an
instruction as you wrote it, else by its Basic form; the control unit names the operation it
decodes. Rest the mouse on a wire or a block to see its name, its width, what it is for and its
value now in hexadecimal, decimal and binary.

Click a block to see inside it; over a block that opens, the pointer becomes a hand. The control
unit shows the Main Decoder's and the ALU Decoder's tables with the rows of this instruction lit,
the PC Logic, and the Conditional Logic that checks the condition against the flags, with the gates
that make PCSrc, RegWrite, MemWrite, FlagWrite and Syscall. The register file shows its registers,
the three ports that read and the two that write: WD3, and the base write port. The ALU shows its
adder with its carry in, its logical units, its multiplier and the unit that joins MOVT's two
halves, the multiplexer that ALUControl drives, and how it makes the flags. Extend shows its five
ways of making the immediate and the pass counter's offset, and the shifter its shift and where its
amount comes from. The instruction memory and the data memory show the words around the address,
with the name of the DE1-SoC's device where a device lies; the data memory also shows its load
extender, which widens a halfword or a byte read to 32 bits. Each window plays at the same speed as
the film and follows it: Play, Pause, One step forward, One step back and Skip to end move it too,
and a Step or a Backstep shows the new instruction in it. The multiplexers, the adders and the PC
have their tips only. Each window names what it shows at its top, Decoder and Conditional Logic
for the control unit for example; rest the mouse on the name to see what the block does. A register
number that comes in on a wire shows its four bits there too (A1 = 0001), while the register file's
rows and its word, READ R1, name the register.

The film's picture buttons stand beside Assemble, Step and Backstep; a tip gives each one's name
and key. There are two ways to run the next instruction. Step (F7) runs it and plays its whole
film; until that film has ended, of the film's buttons only Pause (Space) and Skip to end (E) work.
One step forward (O) runs it and plays only the first step of its film, then waits: each press
plays the next step. While such a film has not ended, One step back (B) shows the step before, Play
plays from there to the end, the same button showing Pause while it plays (Space), Skip to end
shows the whole instruction at once (E), and Step waits until the film has ended. Once a film has
ended, Step and One step forward run the next instruction; after One step forward, One step back
still goes back into the film, which has then not ended any more. Backstep (F8) takes the whole
instruction back, at any time. The main window's Step, Go, Backstep and Reset work at all times
too, and end a film that has not ended. While the program runs, the film's buttons are off. The
slider sets how long the film of one instruction lasts, from 5 to 40 seconds; ARES keeps your
choice. Without Animate each step, a Step shows the whole instruction at once, and One step forward
still goes one step at a time.

The window can be made larger, or maximized: once its size has settled, the picture is drawn
again as large as the window holds it, in proportion, its text with it, and a film that plays
goes on. It shrinks again down to the size at which the smallest text has 8 points. The windows
inside the blocks grow and shrink in the same way, each with a size of its own. Each window opens
at its usual size.

Only Step and One step forward play a film. While the program runs there is no film: at a slow
run speed each instruction shows finished, and at full speed the tool does nothing until the
run stops, so it costs nothing. Backstep plays no film: the tool shows what it showed before
the Step that Backstep undoes, the instruction that is now the last one run, finished. While
nothing has run, after Assemble or Reset and after undoing the first instruction, the picture is
empty, the tool says Nothing has run yet and the panel names the instruction that runs next.
After a run that kept no history for Backstep, the tool shows the instruction at PC, which has
not run yet, under the line Runs next. Nothing to show means that Backstep has undone all it kept
and can go back no further.

The additions to the textbook's datapath are these. The ALU has more operations: ALUControl has
four bits, with EOR, BIC, RSB, MOV and MVN after the textbook's ADD, SUB, AND and ORR; NoWrite
stops CMP, CMN, TST and TEQ from writing a register. A shifter stands between RD2 and the ALUSrc
multiplexer, for shifts by an immediate, RRX included: the signal Shift is 1 when it changes its
input, and Extend rotates the 8-bit immediate. ShiftC writes C from the shifter or the rotated
immediate, in a logical operation with S. A store with a register offset reads three registers: A4
and RD4 are a third read port, and StoreSrc takes WriteData from RD4. The signal Size tells the
data memory to move a word (00), a halfword (01) or a byte (10), for LDRB, STRB and the halfword
and signed transfers. A negative offset subtracts. BL sets Link: two small multiplexers send 14 to
A3 and PCPlus4 to WD3. BX reads Rm on the port of RD2; the ALU passes it on as for MOV, and the
result goes to the PC. The AdrSrc multiplexer gives the data memory its address: ALUResult, or RD1,
the base as it was, for post-indexing. The register file has a second write port for the base
register, the base write port: BaseWrite opens it, WD5 brings ALUResult, and it writes the register
that A1 reads (A5 = A1 = Rn). The control unit has a pass counter for LDM, STM, PUSH and POP: List
brings it the register list (Instr 15:0); for each pass it sends the number of one register as
PassReg, which the register file takes as A3 for a load or as A4 for a store, and an offset as
Offset, which Extend passes on when ImmSrc is 011; its signal Hold keeps the PC until the last
pass. MUL and MLA have a multiplier inside the ALU: ALUControl 1001 multiplies SrcA by SrcB, 1010
adds RD4 to the product, and the tip of the strip's Execute shows the whole multiplication. The
control unit tells them from data processing by Op2, bits 7:4 of the word, which are 1001. Its
signal Mul, 1 for MUL and MLA, makes the RA1 multiplexer take its third input, Rs (bits 11:8), and
the A3 multiplexer its third input, bits 19:16, the register that MUL and MLA write. MLA reads Ra
(bits 15:12) on A4, and RD4 goes into the ALU on a wire of its own. A shift by a register, such as
ADD R2, R1, R0, LSL R3, reads Rs (bits 11:8) on A4: the signal ShiftReg, 1 only for it, makes the
A4 multiplexer take bits 11:8 instead of 15:12. RD4 goes into the shifter, whose own multiplexer
then takes the amount from RD4[7:0] instead of bits 11:7; Shift is 1 for every shift by a register,
as the control unit cannot see Rs: an amount of 0 leaves the value and C as they are, and from 32
on every bit has gone. ADC, SBC and RSC add the C flag: the wire CarryIn brings it from the flags
register in the control unit to the adder, with ALUControl 1011, 1100 and 1101. TEQ has its row in
the ALU Decoder: an exclusive OR that only sets the flags, like TST. BLX Rm is the row of BX with
Link 1: LR takes PCPlus4, and the PC takes Rm. NOP has a row of its own in the Main Decoder, in
which nothing is written. Op2 also tells BX (0001) from BLX (0011), and a shift by a register (bit
4 is 1) from a shift by an immediate. ImmSrc has three bits: 000 rotates imm8, 001 zero-extends
imm12, 010 sign-extends imm24 and multiplies it by 4, 011 passes on the pass counter's offset, 100
joins imm4 (bits 19:16) and imm12 into the 16-bit immediate of MOVW and MOVT, and 101 joins imm4H
(bits 11:8) and imm4L (bits 3:0) into the 8-bit offset of a halfword or signed transfer. MOVW and
MOVT share a row of their own in the Main Decoder, and the ALU Decoder tells them apart by cmd.
MOVW writes its immediate with zeros above it: the ALU passes SrcB on, as for MOV. MOVT reads its
Rd on A4 and keeps its low half: RD4 goes into the ALU, whose ALUControl 1110 joins the immediate,
as the high half, to the low half of RD4. LDRH, STRH, LDRSB and LDRSH have rows of their own in the
Main Decoder, which tells them by Op2 (1SH1) and by Funct2, bit 22, which says whether the offset
is an immediate or a register. The signal Signed makes the load extender inside the data memory
copy the sign bit of the halfword or byte read into the bits above it, for LDRSH and LDRSB; with
Signed 0 they get zeros. The halfword and signed transfers write their base through the base write
port and use the AdrSrc multiplexer as LDR and STR do. The example xray_tour.s (File > Open
Example) uses only instructions of this datapath, so that every instruction it runs plays a film.

LDM, STM, PUSH and POP move one register in each pass through the datapath, a clock cycle each.
The film plays one pass after another, the first at the chosen speed and each other in a third of
that time; the heading and the strip's tips say which pass plays, for example pass 2 of 4.
The registers go in the order of their numbers, and the PC last, so a POP that loads the PC ends
as a branch. With write-back (the ! of LDM and STM, and every PUSH and POP) the base write port
writes the base in every pass, 4 further on, so that each pass is a load or store of one register
next to the base, and the last pass leaves the base where the instruction leaves it; counting
down (PUSH, STMDB), the passes go from the highest register. Without write-back the base stays
and each pass takes the register's distance from it as its offset.

LDR, STR, LDRB and STRB with write-back or post-indexing write their base register too, through
the base write port. With write-back (the ! of LDR R0, [R1, #4]!) the address is the base plus
the offset, ALUResult, and the base takes the same value. Post-indexed (LDR R0, [R1], #4) the
address is the base as it was: AdrSrc is 1 and the multiplexer takes RD1, while the ALU works out
the new base, which the base write port writes at the clock edge. A single-register PUSH or POP is
such a store or load of SP.

An SVC asks the system for a service: its 24-bit immediate is the number of the service. The
control unit sets the signal Syscall and hands the call to the box System (ARES) at the top
left, which shows the number, the name of the service and what it did, for example SVC #1,
print integer: R0 = 25. {credits.XRAY_SYSTEM} When the service waits for input, the film stops
at the system, and the SVC ends once you have typed a line in Run I/O. The SVC itself writes no
register: what the service changed shows in the panel.

Whatever writes the PC, bit 0 of the address does not reach it. When that bit is 1 the processor
goes on in Thumb code, and the strip's tip of Next PC and the panel say so.

Some instructions lie outside this datapath: S with Rd = 15; long multiplies, MLS and UMAAL;
SWP; LDRT, STRT, LDRBT, STRBT, LDRHT, STRHT, LDRSBT and LDRSHT; LDM and STM with ^; an LDM that
loads its base before its last pass, or that counts down with write-back and loads the PC;
encodings that ARMv7 leaves UNPREDICTABLE, such as write-back to the register a load or store
moves, or the PC as a register of a multiply, of a shift by a register, of MOVW or MOVT or of a
halfword transfer; doubleword and exclusive accesses (LDRD, STRD, LDREX, STREX); MRS, MSR, CLZ
and the hints other than NOP; floating point, coprocessors and NEON; and anything with condition
1111. For these the diagram stays pale and gray, and the panel says why on its first line (its
tip has all of it) and lists what the instruction changed.

Reset clears the picture until the program does something more. The tool stays connected when
the program is assembled again or its file is closed.

{credits.XRAY_ORIGIN}
"""

NET_TIPS = {
    "PC": "the address of the instruction that runs now",
    "PC'": "the address of the next instruction, written into the PC at the clock edge",
    "Instr": "the instruction word read from the instruction memory",
    "Const4": "the constant 4 that the adder adds",
    "PCPlus4": "PC + 4: the address of the next instruction in order",
    "PCPlus8": "PC + 8: what the program reads as R15",
    "Cond": "the condition field (31:28): when the instruction runs",
    "Op": "the op field (27:26): the kind of instruction",
    "Funct": "the funct field (25:20): which instruction of its kind, and its options",
    "Rd": "the destination register's number (15:12); in MLA, Ra, which A4 reads; in MOVT, read "
          "on A4 too, for its low half",
    "Rn": "the first source register's number (19:16); in MUL and MLA, the register written",
    "Rm": "the second source register's number (3:0)",
    "Rs": "the number of the register in bits 11:8: Rs of MUL and MLA, for RA1, or of a shift "
          "by a register, for A4",
    "Op2": "bits 7:4 of the word: they tell MUL and MLA (1001) from data processing, a shift by "
           "a register (bit 4) from one by an immediate, BLX (0011) from BX (0001), and the "
           "halfword and signed transfers (1SH1: S signed, H a halfword)",
    "A4": "the number of the register read on the third port: from the A4 multiplexer",
    "ShiftReg": "1: a shift by a register: the A4 multiplexer takes Rs (11:8), the shifter its "
                "amount from RD4[7:0]",
    "CarryIn": "the C flag, from the flags register, the carry in of the adder for ADC, SBC "
               "and RSC",
    "Imm": "the immediate bits of the word (23:0), for Extend, which takes the bits of its "
           "ImmSrc",
    "Shamt": "the shift amount and kind (11:5), for the shifter",
    "Const15": "the number 15: R15, for an instruction that reads the PC",
    "Const14": "the number 14: LR, for BL",
    "RA1": "the number of the register read on the first port",
    "RA2": "the number of the register read on the second port",
    "A3": "the number of the register written",
    "WD3": "the value written into register A3",
    "SrcA": "the first operand of the ALU (RD1)",
    "RD2": "the value of the register read on the second port",
    "RD4": "the value of the register read on the third port (A4): the data of a store with a "
           "register offset, Ra of MLA, which the multiplier adds, Rs of a shift by a register, "
           "whose low byte is the shift amount, or Rd of MOVT, whose low half stays",
    "ExtImm": "the immediate made 32 bits wide by Extend",
    "Shifted": "RD2 after the shifter",
    "ShiftC": "the bit that the shifter shifted out last: the carry for logical operations",
    "SrcB": "the second operand of the ALU",
    "ALUResult": "the ALU's result: a value, a product, an address, a new base or a branch target",
    "ALUFlags": "the flags N, Z, C and V of the ALU's result",
    "WriteData": "the value a store writes into the data memory",
    "ReadData": "the value a load reads from the data memory, a halfword or a byte widened to 32 "
                "bits by its load extender",
    "Result": "the value written back: the ALU's result or the data read",
    "PCSrc": "1: the PC takes Result (a branch or a write to R15)",
    "MemtoReg": "1: Result takes the data read from memory",
    "MemWrite": "1: the data memory writes WriteData",
    "Size": "how much the data memory reads or writes: 00 a word, 01 a halfword, 10 a byte",
    "Signed": "1: the load extender in the data memory copies the sign bit of the halfword or "
              "byte read into the bits above it (LDRSH, LDRSB); 0: zeros",
    "ALUControl": "which operation the ALU does (1001 and 1010: the multiplier; 1011, 1100 "
                  "and 1101: ADC, SBC and RSC; 1110: MOVT)",
    "ALUSrc": "1: SrcB is the immediate ExtImm; 0: the register value",
    "Shift": "1: the shifter shifts RD2 (by a register: when the amount, RD4[7:0], is not 0)",
    "StoreSrc": "1: WriteData is the third read port's value RD4",
    "ImmSrc": "how Extend builds the immediate: 000 rotated imm8, 001 imm12, 010 imm24 x 4, 011 "
              "the pass counter's offset, 100 imm16 of MOVW and MOVT, 101 imm8 of a halfword "
              "transfer",
    "RegWrite": "1: the register file writes WD3 into register A3",
    "RegSrc0": "1: the first read port reads R15 (when Mul is 0)",
    "RegSrc1": "1: the second read port reads Rd (for a store)",
    "Link": "1: BL and BLX write PCPlus4 into LR (R14)",
    "Mul": "1: MUL or MLA: the RA1 multiplexer takes Rs (11:8) and the A3 multiplexer Instr 19:16",
    "Syscall": "1: the control unit hands an SVC to the system",
    "SvcNum": "the immediate of an SVC (23:0): the number of the service",
    "AdrSrc": "1: the data memory's address is RD1, the base before the access (post-indexing); "
              "0: ALUResult",
    "Address": "the data memory's address, from the AdrSrc multiplexer",
    "BaseWrite": "1: the base write port writes WD5 into the base register (A5 = A1)",
    "WD5": "the new base for the base write port: ALUResult",
    "Hold": "1: the pass counter keeps the PC, so the next pass runs the same instruction",
    "List": "the register list of LDM, STM, PUSH or POP (15:0), for the pass counter",
    "PassReg": "the register of this pass: A3 for a load, A4 for a store",
    "Offset": "the offset of this pass from the base, for Extend (ImmSrc 011)",
}
BLOCK_TIPS = {
    "PCReg": "the PC register: holds the address of the instruction; takes PC' at the clock edge",
    "IMem": "the instruction memory: gives the word at address A",
    "Add4": "an adder: PC + 4", "Add8": "an adder: PC + 8, which the program reads as R15",
    "Control": "the control unit: decodes the instruction and makes the control signals; its "
               "pass counter runs LDM, STM, PUSH and POP one register at a time",
    "RegFile": "the register file: reads up to three registers, writes one at the clock edge "
               "and the base through its base write port",
    "Extend": "Extend: makes the immediate of the word 32 bits wide, in one of five ways, or "
              "passes on the pass counter's offset",
    "Shifter": "the shifter: shifts RD2 by an amount in the word, or by RD4[7:0] for a shift "
               "by a register",
    "ALU": "the ALU: adds, subtracts, multiplies, does a logical operation or joins the halves "
           "of MOVT, and makes the flags",
    "DMem": "the data memory: reads at address A, or writes WD there at the clock edge, a word, a "
            "halfword or a byte (Size); its load extender widens a halfword or a byte read to 32 "
            "bits (Signed)",
    "System": "the system: ARES performs the service that an SVC asks for, where a real "
              "processor would enter the operating system",
    "PCMux": "a multiplexer: PCSrc chooses the next PC",
    "RA1Mux": "a multiplexer: RegSrc0 and Mul choose the first register to read",
    "RA2Mux": "a multiplexer: RegSrc1 chooses the second register to read",
    "A3Mux": "a multiplexer: Link and Mul choose the register to write",
    "A4Mux": "a multiplexer: ShiftReg chooses the third register to read: Rs (11:8) for a shift "
             "by a register, else Instr 15:12",
    "WD3Mux": "a multiplexer: Link chooses the value to write",
    "StoreMux": "a multiplexer: StoreSrc chooses the value to store",
    "ALUSrcMux": "a multiplexer: ALUSrc chooses SrcB",
    "ResultMux": "a multiplexer: MemtoReg chooses Result",
    "AdrSrcMux": "a multiplexer: AdrSrc chooses the data memory's address",
}


class XRayModel(ToolModel):
    """Which instruction to show (a xray.View), looked for only after the program stopped
    moving: update() reads the machine and needs no hooks.

    stopped says that the program was stopped for good (Stop), which the
    machine itself does not know. After a Backstep the machine is just after
    the instruction of its newest history entry, so the view shows that
    instruction finished, as it did before the Step that was undone; with no
    entry left, nothing. Nothing is shown either while nothing has run since the
    program was loaded or Reset (the next instruction is named in the panel): so a
    Backstep to the start shows what the tool showed before the first Step. After
    a run that kept no history, the instruction at PC is shown as the one that runs
    next. written(address), set by the window, gives the instruction at address as
    the student wrote it (App.written), or None.
    """

    def __init__(self):
        super().__init__()
        self.view = xray.View()
        self.next = None                # (pc, name) of the instruction that runs after it
        self.change = None              # the history entry of the instruction executed
        self.waits = None               # what the SVC at PC waits for (machine.INPUT, DIALOG)
        self.popup_input = False        # Settings: a read asks for its line in a dialog window
        self.flags = None               # NZCV (before, after) of the instruction executed
        self.undone = False             # the view changed because of a Backstep: no film plays
        self.written = None             # written(address) -> the student's text, or None
        self._forget()

    def _forget(self):
        self.stopped = False
        self._state = None              # the machine as it was at the last look
        self._number = 0                # the newest change seen
        self._backsteps = 0
        self._resets = None             # the machine's Resets at the last look
        self._pc = None                 # PC at the last look
        self._unrecorded = False        # it ran without a history since it was loaded or Reset

    def attach(self, machine):
        stopped = self.stopped
        self._forget()
        self.stopped = stopped          # what the window said before connecting
        self._backsteps = machine.backsteps
        self._resets = machine.resets
        self._unrecorded = not machine.history and machine.pc != machine.program.entry
        self.update()

    def reset(self):
        """Clear the picture until the program does something."""
        self.view = xray.View()
        self.next = self.flags = None

    def clear(self):
        """No program any more."""
        self.view = xray.View()
        self.next = self.flags = None
        self._forget()

    def update(self):
        machine = self.machine
        if machine is None:
            return False
        history = machine.history
        newest = history[-1] if history else None
        number = newest.number if newest is not None else 0
        request = machine.request
        waits = request.kind if request is not None and request.kind in WAITING_HEADINGS else None
        state = (number, machine.backsteps, machine.stop_reason, self.stopped, machine.cpsr,
                 [machine.reg(n) for n in range(16)], waits)
        if state == self._state:
            return False
        fresh = number > self._number
        undone = machine.backsteps > self._backsteps and not fresh
        ended = machine.stop_reason is not None or self.stopped
        if machine.resets != self._resets:          # Reset: the run is gone
            self._unrecorded = False
        elif not (fresh or undone) and self._pc is not None and (
                machine.pc != self._pc or number < self._number):
            self._unrecorded = True     # a run that kept no history (it dropped what was kept)
        self._resets, self._pc = machine.resets, machine.pc
        self._state, self._number, self._backsteps = state, number, machine.backsteps
        self.waits = waits
        if not (fresh or undone or ended or waits) and self.view.kind == xray.EXECUTED \
                and newest is not None:
            return False                # a register changed by hand: that instruction still ran
        self.undone = undone
        self.next = self.flags = self.change = None
        if machine.stop_reason is StopReason.ERROR:
            trace = None if machine.no_code else xray.upcoming(machine, machine.error_address)
            view = self._view(xray.FAILED, machine.error, trace)
        elif waits and not ended:       # an SVC at PC waits: it has not ended
            heading = WAITING_HEADINGS[waits]
            if waits == INPUT and self.popup_input:
                heading = POPUP_HEADING
            view = self._view(xray.WAITING, heading, xray.upcoming(machine))
        elif fresh or (undone and newest is not None):
            view = self._executed(newest, ended)
        elif newest is None and not self._unrecorded and not ended:
            view = xray.View(heading=NOTHING_RUN)   # as before the first Step
            self.next = (machine.pc, self._name(xray.upcoming(machine)))
        elif undone:                    # no instruction run is left to show: nothing
            view = xray.View(heading=NOTHING_LEFT)
        elif ended:
            view = xray.View(xray.ENDED, "The program has ended", ended=True)
        else:
            view = self._view(xray.NEXT, RUNS_NEXT, xray.upcoming(machine))
        self.view = view
        return True

    def _executed(self, change, ended):
        machine = self.machine
        shown = xray.executed(machine, change)
        did = tuple(xray.changes(machine, change))
        heading = "Just executed; the program has ended" if ended else "Just executed"
        self.flags = (change.registers[0] >> 28, machine.cpsr >> 28)
        self.change = change
        if not ended:
            after = xray.upcoming(machine)
            self.next = (machine.pc, self._name(after))
        return xray.View(xray.EXECUTED, heading, shown, did, ended, self._written(shown))

    def _view(self, kind, heading, trace):
        return xray.View(kind, heading, trace, written=self._written(trace))

    def _written(self, trace):
        """trace's instruction as the student wrote it, or None: no line of the source made it,
        or the word there is no longer the program's own (written while the program ran)."""
        machine, written = self.machine, self.written
        if trace is None or machine is None or written is None:
            return None
        if machine.program.read_word(trace.pc) != trace.word:
            return None
        return written(trace.pc) or None

    def _name(self, trace):
        """How the tool names trace's instruction: as written, else by its Basic form."""
        return "" if trace is None else xray.named(self._written(trace), trace.text)


# The scale of the picture --------------------------------------------------------------------

def zoom_for(area, frame, chrome, canvas):
    """How much larger than its design size the picture can be drawn so that the whole window
    fits area: area is the work area (left, top, right, bottom), frame the window frame's
    (side, top) widths, chrome the size of everything else in the window (width, height) and
    canvas the picture's size at zoom 1, all in screen pixels. Never under 1, where the
    smallest text has 8 points; at most MAX_ZOOM."""
    left, top, right, bottom = area
    side, title = frame
    room_w = right - left - 2 * side - chrome[0]
    room_h = bottom - top - title - side - chrome[1]
    zoom = min(room_w / canvas[0], room_h / canvas[1])
    return max(1.0, min(MAX_ZOOM, int(zoom * 20) / 20))


def kind_heading(trace):
    """The large heading that names the kind of instruction shown, and for an LDM, STM, PUSH or
    POP which pass it shows (trace is that pass)."""
    if trace is None:
        return ""
    if trace.kind in KIND_HEADINGS:
        if trace.count > 1:
            return f"{KIND_HEADINGS[trace.kind]}, PASS {trace.number} OF {trace.count}"
        return KIND_HEADINGS[trace.kind]
    word = trace.word
    if trace.note == xray.NOTE_THUMB:
        return "THUMB INSTRUCTION"
    if word >> 24 & 0xF == 0xF and word >> 28 != 0xF:
        return "SYSTEM CALL"
    if word >> 25 & 7 == 0b100 and word >> 28 != 0xF:
        return "LOAD MULTIPLE INSTRUCTION" if word >> 20 & 1 else "STORE MULTIPLE INSTRUCTION"
    if trace.note == xray.NOTE_MULTIPLY:
        return "MULTIPLY INSTRUCTION"
    return "INSTRUCTION OUTSIDE THE DATAPATH"


def condition_lines(trace):
    """The condition check as the control unit shows it: the condition, the flags it reads,
    and its answer, in three short lines."""
    cond = trace.word >> 28
    name = xray.CONDITIONS[cond]
    if cond == 0xE:
        return f"{name}\nalways runs"
    read = " ".join(f"{flag}={trace.flags >> xray.FLAG_BITS[flag] & 1}"
                    for flag in xray.CONDITION_FLAGS[cond])
    answer = "holds: it runs" if trace.signals.get("CondEx") == "1" else "fails: no writes"
    return f"{name}\n{read}\n{answer}"


_REGISTER = re.compile(r"\b([RSD])(\d+) = ([^,]*)")
_ADDRESSES = ("address", "name", "buffer", "message", "string", "bits")


def register_text(bank, number, meaning, value, service=""):
    """One register a service reads or writes, as the System box shows it: R0 = 25."""
    if bank == "S":
        return f"S{number} = {format_single(value)}"
    if bank == "D":
        return f"D{number} = {format_double(value)}"
    if "character" in meaning:
        shown = f"'{chr(value)}' ({value})" if 32 <= value < 127 else str(value)
        return f"R{number} = {shown}"
    if "hexadecimal" in service or any(word in meaning for word in _ADDRESSES):
        return f"R{number} = 0x{value:08X}"
    if "unsigned" in service:
        return f"R{number} = {value}"
    return f"R{number} = {syscalls.to_signed(value)}"


def service_text(number, machine, before=None, done=True):
    """What the system does for SVC #number, as its box says: the number, the name of the
    service and the registers it reads (before: R0 to R15 before the call, None: as they are
    now) and, when done, the registers it wrote: "SVC #1, print integer: R0 = 25"."""
    entry = syscalls.SERVICES.get(number)
    if entry is None:
        return f"SVC #{number}: no such service"

    def value(bank, n, written):
        if bank == "S":
            return machine.single(n)
        if bank == "D":
            return machine.double(n)
        return machine.reg(n) if written or before is None else before[n]

    def listed(text, written):
        return [register_text(bank, int(n), meaning, value(bank, int(n), written), entry.name)
                for bank, n, meaning in _REGISTER.findall(text)]

    reads = listed(entry.arguments, False)
    writes = listed(entry.result, True) if done else []
    text = f"SVC #{number}, {entry.name}"
    if reads:
        text += ": " + ", ".join(reads)
    if writes:
        text += ("; result " if reads else ": result ") + ", ".join(writes)
    return text


# The table of the word --------------------------------------------------------------------

Cells = namedtuple("Cells", "name high low kind boxes label digits")
# The fields' wires: net -> the bits of the word it carries.
WORD_NETS = {"Cond": (31, 28), "Op": (27, 26), "Funct": (25, 20), "Rn": (19, 16),
             "Rd": (15, 12), "Rs": (11, 8), "Op2": (7, 4), "Rm": (3, 0), "Shamt": (11, 5),
             "Imm": (23, 0), "SvcNum": (23, 0), "List": (15, 0)}
PLACES = {"Control": "the control unit", "Extend": "Extend", "Shifter": "the shifter",
          "System": "the system", "RA1Mux": "the RA1 multiplexer",
          "RA2Mux": "the RA2 multiplexer", "A3Mux": "the A3 multiplexer",
          "A4Mux": "the A4 multiplexer"}
MEANINGS = {
    "cond": "the condition: when the instruction runs", "op": "the kind of instruction",
    "funct": "the operation and its options", "cmd": "the operation",
    "P": "1: the offset is added before the access (pre-indexing); 0: after it",
    "U": "1: the offset is added; 0: it is subtracted", "B": "1: a byte; 0: a word",
    "W": "1: the base register is written back", "Ra": "the register added to the product",
    "rot": "the rotation: imm8 turns right by twice rot", "imm8": "the 8-bit immediate",
    "imm4": "the top 4 bits of the 16-bit immediate",
    "imm4H": "the high 4 bits of the 8-bit offset", "imm4L": "the low 4 bits of the 8-bit offset",
    "shamt5": "the shift amount", "sh": "the kind of shift: 00 LSL, 01 LSR, 10 ASR, 11 ROR",
    "op2": "bits 7:4: they tell MUL and MLA (1001), BX (0001) from BLX (0011), and the "
           "halfword and signed transfers (1SH1)",
    "register list": "one bit for each register, R0 at bit 0 to R15 at bit 15: 1 moves it",
}


def bit_x(bit):
    """The left side of bit's column in the table, in design pixels."""
    return TABLE[0] + NAME_WIDTH + (31 - bit) * BIT_WIDTH


def tinted(colour, share=TINT):
    """colour mixed with white, share of it: the background of a lit cell."""
    return xray_look.tint(colour, share)


def cell_colour(kind, name):
    """The colour of a lit field's cells: the colour of its value on the picture (the table is
    the key of the colours), ink for bits that the kind of instruction fixes, gray for bits that
    are no field of it."""
    if kind == "constant":
        return INK if name else IDLE
    return xray_look.field_colour(kind)


def field_meaning(trace, name, kind):
    """What a field of trace's word is, for its tip."""
    word, shape = trace.word, trace.kind
    memory = word >> 26 & 3 == 1
    multiple = word >> 25 & 7 == 0b100
    branch = word >> 25 & 7 == 0b101
    half = word >> 28 != 0xF and xray.is_half(word)
    if kind == "constant":
        if not name:
            return "no field of this instruction: nothing uses these bits"
        if name == "27:0":
            return "the rest of the word: the instruction lies outside this datapath"
        return "bits that this kind of instruction fixes"
    if name == "I":
        if half:
            return "1: the offset is an immediate (imm4H and imm4L); 0: a register (Rm)"
        if memory:
            return "1: the offset is a register (Rm); 0: the immediate imm12"
        return "1: Src2 is an immediate (rot and imm8); 0: a register (Rm)"
    if name == "S":
        return "1: with ^" if multiple else "1: the flags are set"
    if name == "L":
        if branch:
            return "1: link: the return address goes into LR"
        return "1: a load; 0: a store"
    if name in ("P", "U") and multiple:
        return ("1: the address moves on before each register; 0: after it" if name == "P"
                else "1: the addresses count up; 0: down")
    if name == "Rn":
        return "the base register" if memory or multiple or half else \
            "the first source register"
    if name == "Rd":
        if (memory or half) and word >> 20 & 1:
            return "the register loaded"
        if memory or half:
            return "the register stored"
        return "the destination register"
    if name == "Rm":
        if shape in (xray.BRANCH_EXCHANGE, xray.BRANCH_LINK_EXCHANGE):
            return "the register that holds the target's address"
        return "the offset register" if memory or half else "the second source register"
    if name == "Rs":
        return "the second factor" if word & xray.MULTIPLY_MASK == xray.MULTIPLY_BITS else \
            "the register whose low byte is the shift amount"
    if name == "imm12":
        return "the 12-bit offset" if memory else "the low 12 bits of the 16-bit immediate"
    if name == "imm24":
        return "the number of the service" if word >> 24 & 0xF == 0xF else \
            "the distance to the target, in words"
    if name in ("0", "1", "1 1"):
        return "bits that this kind of instruction fixes"
    return MEANINGS.get(name, "")


def value_line(word, name, high, low, kind):
    """The second line of a cell's tip: the field's bits and its value."""
    width = high - low + 1
    value = word >> low & (1 << width) - 1
    text = (f"Bit {high}" if width == 1 else f"Bits {high}:{low}") + f", value {value:0{width}b}"
    if width > 1:
        text += f" = {value}"
    if kind in ("rn", "rd", "rm") and width == 4:
        text += f": R{value}"
    elif name == "cond" and value < len(xray.CONDITIONS):
        text += f": {xray.CONDITIONS[value]}"
    elif width > 8:
        text += f" = 0x{value:X}"
    return text


def joined(names):
    """Names in a sentence: "a", "a and b", "a, b and c"."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def value_text(value, width=32):
    """A value in hexadecimal, decimal and binary, for a tip."""
    if value is None:
        return "not known yet"
    if isinstance(value, str):
        return value
    digits = (width + 3) // 4
    text = f"0x{value:0{digits}X} = {value}"
    if width == 32 and value >> 31:
        text += f" = {value - (1 << 32)}"
    binary = f"{value:0{width}b}"
    groups = " ".join(binary[i:i + 4] for i in range(0, width, 4)) if width > 8 else binary
    return f"{text}\n0b {groups}"


def button_states(mode, ended, playing, first, running, can_step, can_back):
    """Which of the film's buttons, and of the toolbar's Step and Backstep, are on, and the
    picture of the Play and Pause button. mode is how the film shown plays: WHOLE (Step started
    it), STEPS (One step forward did), or None (none was started: after Backstep, Assemble or
    Reset, without Animate each step); ended says that it has ended, playing that it plays now,
    first that it is at its first step or within it, running that the program runs (Go);
    can_step and can_back say whether the main window can Step and Backstep now.

    While a film plays whole, only Pause or Play and Skip to end work; while it goes step by
    step, One step forward, One step back (not at the first step), Play or Pause and Skip to
    end. Once it has ended, or with none, Step and One step forward run the next instruction,
    and One step back goes back into a film that went step by step. While the program runs the
    film's buttons are off. Backstep follows the main window."""
    face = "film_pause" if playing else "film_play"
    if running:
        return dict(pause=False, back=False, forward=False, skip=False, step=can_step,
                    backstep=can_back, face=face)
    unfinished = mode is not None and not ended
    return dict(pause=unfinished, back=mode == STEPS and not first,
                forward=(mode == STEPS and not ended) or (not unfinished and can_step),
                skip=unfinished, step=can_step and not unfinished, backstep=can_back, face=face)


def step_end(film, number):
    """The moment at which step number of film ends: the last one exactly at the film's end
    (the sum of the steps' times may miss it by a hair), so that waiting there it has ended."""
    if number >= len(film.steps) - 1:
        return film.seconds
    step = film.steps[number]
    return step.start + step.duration


class Player:
    """Plays a film on the picture by a clock: tick(now) draws the film at that moment.

    clock gives the time in seconds (time.monotonic, or the tests' own); the
    window calls tick() about 30 times a second while the film plays.
    """

    def __init__(self, show, clock=time.monotonic):
        self.show = show                # show(film, moment): draw the film at moment
        self.clock = clock
        self.film = None
        self.start = 0.0                # clock time of the film's moment 0
        self.paused_at = None           # the moment shown while paused
        self.stop_at = None             # pause again when the film reaches this moment
        self.held = False               # waiting where a step ended: show that step ended

    @property
    def playing(self):
        return self.film is not None and self.paused_at is None and not self.ended

    @property
    def moment(self):
        if self.film is None:
            return 0.0
        if self.paused_at is not None:
            return self.paused_at
        return min(self.film.seconds, self.clock() - self.start)

    @property
    def ended(self):
        return self.film is not None and self.paused_at is None and \
            self.clock() - self.start >= self.film.seconds

    def play(self, film, moment=0.0, stop_at=None):
        """Play film from moment; with stop_at, it waits once it gets there (a step's end)."""
        self.film = film
        self.start = self.clock() - moment
        self.paused_at = None
        self.stop_at = stop_at
        self.held = False
        self.tick()

    def finish(self, film):
        """Show film at its end, at once."""
        self.film = film
        self.start = self.clock() - film.seconds
        self.paused_at = None
        self.stop_at = None
        self.held = False
        self.show(film, film.seconds)

    def hold(self, film, moment):
        """Show film waiting at moment, where a step ends, as One step forward leaves it."""
        self.film = film
        self.start = self.clock() - moment
        self.paused_at = moment
        self.stop_at = None
        self.held = True
        self.show(film, moment)

    def tick(self, now=None):
        if self.film is None or self.paused_at is not None:
            return
        now = self.clock() if now is None else now
        moment = now - self.start
        if self.stop_at is not None and moment >= self.stop_at:
            moment = self.stop_at
            self.paused_at = moment
            self.stop_at = None
            self.held = True
        self.show(self.film, min(moment, self.film.seconds))

    def pause(self):
        if self.film is not None and self.paused_at is None and not self.ended:
            self.paused_at = self.moment
            self.held = False
            self.show(self.film, self.paused_at)

    def resume(self):
        """Go on from where the film was paused, to where it was going (its end, or the end of
        the step it plays)."""
        if self.paused_at is not None:
            self.start = self.clock() - self.paused_at
            self.paused_at = None
            self.held = False
            self.tick()

    def play_on(self):
        """Play: from the moment shown to the film's end."""
        self.stop_at = None
        self.resume()

    def one_step(self):
        """Play to the end of the step at the moment shown, then wait there: waiting where a
        step ends, the next step."""
        film = self.film
        if film is None:
            return
        moment = self.moment
        if moment >= film.seconds:
            return
        number, _ = film.at(moment)
        self.stop_at = step_end(film, number)
        if self.paused_at is not None:
            self.start = self.clock() - self.paused_at
            self.paused_at = None
        self.held = False
        self.tick()

    def rescale(self, film):
        """The same film at another speed (or drawn again): it goes on from the same share of
        its time; waiting at the end of a step, or playing to the end of one, it keeps that
        step's end exactly (by the step's number), so that One step forward plays the next."""
        if self.film is None:
            return
        old = self.film
        paused = self.paused_at is not None
        if paused and self.held:
            moment = step_end(film, old.at(self.paused_at, True)[0])
        else:
            share = self.moment / old.seconds if old.seconds else 1.0
            moment = share * film.seconds
        stop = None if self.stop_at is None else step_end(film, old.at(self.stop_at, True)[0])
        self.film = film
        self.start = self.clock() - moment
        self.paused_at = moment if paused else None
        self.stop_at = stop
        self.show(film, moment)


class XRayWindow(ToolWindow):
    """Tools > ARM X-Ray.

    The window opens at its usual size, the picture at the zoom at which the whole window fits
    the screen; made larger or maximized, it draws the picture again as large as the window
    holds it, in proportion, once the size has settled; it cannot be made smaller than the
    picture at zoom 1 (_fit(), rezoom()).
    """

    NAME = "ARM X-Ray"
    HEADING = "Animation of the ARM Datapath"
    HELP = HELP
    MODEL = XRayModel

    def __init__(self, app, clock=time.monotonic):
        self.clock = clock
        self._job = None                # the film's timer
        self._waiting = False           # the program waited for input at the last look
        self._steps_seen = getattr(app, "steps_taken", 0)
        self.film = None                # the film of the instruction shown
        self.mode = None                # how it plays (WHOLE, STEPS), None: no film was begun
        self._step_by_step = False      # One step forward runs an instruction: its film STEPS
        self._states = {}               # the buttons' states as last set (_update_buttons())
        self.zoom = self.usual_zoom = 1.0   # the picture's now, and as the window opened
        self.least = self.usual = None  # the window's inside at its least and usual sizes
        self._fitted = False
        self._tip = None                # (pending job, tip window)
        self.insides = {}               # block -> its open window inside it
        self._context = None            # what the windows inside the blocks need
        settings = app.settings
        self.seconds = settings.xray_seconds
        self.animate = tk.BooleanVar(master=app.root, value=settings.xray_animate)
        super().__init__(app)
        self.model.written = app.written
        for widget in self.buttons + (self.speed_scale, self.animate_box):
            widget.bind("<space>", self._space)
        self.window.bind("<space>", self._space)
        windowing = self.window.tk.call("tk", "windowingsystem")
        self._alt = 0x20000 if windowing == "win32" else 0x8   # event.state's Alt (menubar)
        for key, name in FILM_KEYS:
            button = getattr(self, name)
            for sequence in (f"<Key-{key}>", f"<Key-{key.upper()}>"):    # also with Caps Lock
                self.window.bind(sequence, lambda event, b=button: self._film_key(event, b))
        # The main window's keys of Assemble, Step and Backstep press the toolbar's buttons
        # here: a key whose button is off does nothing.
        for name, button in self.tool_buttons.items():
            key = app._keys.get(name)
            if key:
                for sequence in app._sequences(key):
                    self.window.bind(sequence, lambda event, b=button: b.invoke() or "break")
        self.commands_changed()

    # Building ----------------------------------------------------------------------------

    def build(self, body):
        app = self.app
        gap = px(body, 5)
        bar = ttk.Frame(body)
        bar.pack(side="top", fill="x", pady=(0, gap))
        self.bar = bar
        self.tool_buttons = {}
        self.tool_tips = []
        for name, tip in TOOLBAR:
            normal, disabled = app.images[name]
            button = ttk.Button(bar, image=(normal, "disabled", disabled), style="Toolbutton",
                                takefocus=False, command=lambda n=name: app.run(n))
            button.pack(side="left")
            key = app._keys.get(name)
            self.tool_tips.append(Tooltip(button, f"{tip} ({app._accelerator(key)})" if key
                                          else tip))
            self.tool_buttons[name] = button
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=gap)
        size = round(icons.BASES["film_play"] * scale(body))
        self.film_images = {name: (icons.photo(body, name, size),
                                   icons.photo(body, name, size, disabled=True))
                            for name in icons.FILM}
        # Play or Pause, One step back, One step forward and Skip to end, side by side.
        pictures = (("film_play", self.toggle_pause), ("film_back", self.step_back),
                    ("film_step", self.one_step), ("film_end", self.skip))
        self.pause_button, self.back_button, self.one_button, self.skip_button = (
            self._film_button(bar, name, command) for name, command in pictures)
        self.film_tips = tuple(Tooltip(button, FILM_TIPS[name]) for button, (name, _) in zip(
            (self.pause_button, self.back_button, self.one_button, self.skip_button), pictures))
        self.pause_picture = "film_play"    # Pause while the film plays, else Play
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=gap)
        self.speed_label = ttk.Label(bar, width=len("40 s per instruction"))
        self.speed_label.pack(side="left")
        self.speed_scale = ttk.Scale(bar, from_=XRAY_SECONDS.start, to=XRAY_SECONDS.stop - 1,
                                     length=px(body, 130), command=self._speed_moved)
        self.speed_scale.set(self.seconds)
        self.speed_scale.pack(side="left", padx=(gap, gap))
        Tooltip(self.speed_scale, "How long the film of one instruction lasts")
        self.animate_box = ttk.Checkbutton(bar, text="Animate each step", variable=self.animate,
                                           command=self._animate_changed)
        self.animate_box.pack(side="left", padx=(gap, 0))
        Tooltip(self.animate_box, "Play a film at each Step; else show the whole instruction")
        self._speed_moved(self.seconds)
        # The picture's room takes what the window leaves it. It asks for the picture at zoom 1,
        # the least, and the picture is drawn again as large as it holds once its size settles.
        # In a window taller than the picture needs, the picture stays at the top, under the
        # toolbar, and the room left over is below it; across, it stays in the middle.
        self.room = ttk.Frame(body)
        self.room.pack(side="top", fill="both", expand=True)
        self.field = sunken(ttk.Frame(self.room, style=SUNKEN_FRAME))
        self.field.place(relx=0.5, rely=0.0, anchor="n")
        self._make_canvas(1.0)
        self.field.update_idletasks()
        width, height = self.field.winfo_reqwidth(), self.field.winfo_reqheight()
        self.border = (width - self.canvas.winfo_reqwidth(),
                       height - self.canvas.winfo_reqheight())
        self.room.configure(width=width, height=height)
        when_settled(self.room, lambda: self._room_settled())

    def _film_button(self, bar, name, command):
        """A picture button of the film, in the style of the toolbar's (icons.FILM)."""
        normal, disabled = self.film_images[name]
        button = ttk.Button(bar, image=(normal, "disabled", disabled), style="Toolbutton",
                            takefocus=False, command=command)
        button.pack(side="left")
        return button

    def _make_canvas(self, zoom):
        """The canvas and everything drawn on it, at zoom."""
        if getattr(self, "canvas", None) is not None:
            self.canvas.destroy()
        self.zoom = zoom
        k = scale(self.field) * zoom
        self.k = k
        canvas = self.canvas = tk.Canvas(self.field, width=round(CANVAS[0] * k),
                                         height=round(CANVAS[1] * k), background=FIELD,
                                         borderwidth=0, highlightthickness=0, takefocus=False)
        canvas.pack()
        pane = self.app.pane_font
        interface = tkfont.nametofont("TkTextFont", root=canvas).actual("family")
        code = pane.cget("family")
        self.picture = Picture(canvas, zoom, code, interface)
        self.fonts = {
            "small": self.picture.small, "bold": self.picture.bold, "code": self.picture.code,
            "code_bold": self.picture.code_bold,
            "heading": tkfont.Font(root=canvas, family=interface, size=points(15, zoom),
                                   weight="bold"),
            "bits_bold": tkfont.Font(root=canvas, family=code, size=points(9, zoom),
                                     weight="bold"),
        }
        self.cells, self.hex_cells = [], []
        self._draw_frame()
        self._bind_tips()
        canvas.bind("<ButtonRelease-1>", self._clicked, add="+")

    def xy(self, x, y):
        return x * self.k, y * self.k

    def text(self, x, y, text="", anchor="nw", font="small", fill=TEXT, **options):
        return self.canvas.create_text(*self.xy(x, y), text=text, anchor=anchor,
                                       font=self.fonts[font], fill=fill, **options)

    def _draw_frame(self):
        """The parts around the datapath: above it the large heading; under it at the left the
        strip, the instruction and the table of its word, and at the right what the tool shows
        with the instruction's address, the line on the blocks and what the instruction did.
        The table is the key of the colours."""
        canvas = self.canvas
        over = ("over",)                # above the values in flight (XRayPicture._step)
        self.heading_item = self.text(RIGHT / 2, 0, "", "n", "heading", INK, tags=over)
        self.strip = []
        left, top = STRIP
        width, gap, height = STRIP_BOX
        for number, name in enumerate(xray_film.PARTS):
            x = left + number * (width + gap)
            tag = (f"strip:{number}",)  # its tip: what its steps did so far (strip_tip())
            box = canvas.create_rectangle(*self.xy(x, top), *self.xy(x + width, top + height),
                                          fill=WHITE, outline=IDLE, width=max(1, self.k),
                                          tags=tag)
            label = self.text(x + width / 2, top + height / 2, name, "center", "small", IDLE,
                              tags=tag)
            self.strip.append((box, label))
        self.instruction_item = self.text(*LINE, "", "nw", "bits_bold", INK)
        self._draw_table_frame()
        self.view_heading = self.text(*VIEW, "", "w", "bold", INK)
        self.view_text = self.text(*VIEW, "", "w", "code_bold", INK)
        self.hint = self.text(*HINT, CLICK_HINT, "w", "bold", INK)
        # The note of an instruction outside the datapath, a line above the two columns, whole
        # in its tip (note_tip()).
        self.note_item = self.text(*PANEL[0][:2], "", "nw", "code", INK, tags=("note:panel",))
        self.panels = [self.text(x, y, "", "nw", "code", INK) for x, y, _ in PANEL]
        self.panel = self.panels[0]
        self.panel_lines = []           # what the instruction did, as its columns show it

    def _draw_table_frame(self):
        """The table's first column: the names of its rows, and the 0x of the Hex row before
        its first digit."""
        x, top = TABLE
        for number, name in enumerate(TABLE_ROWS):
            y = top + number * ROW
            self.canvas.create_rectangle(*self.xy(x, y), *self.xy(x + NAME_WIDTH, y + ROW),
                                         fill=HEADER, outline=IDLE, width=max(1, self.k),
                                         tags=("table",))
            self.text(x + 4, y + ROW / 2, name, "w", "bold", INK, tags=("table",))
        self.hex_prefix = self.text(x + NAME_WIDTH - 3, top + 2.5 * ROW, "0x", "e", "code_bold",
                                    DIM, tags=("table",))

    # Tips --------------------------------------------------------------------------------

    def _bind_tips(self):
        canvas = self.canvas
        canvas.bind("<Motion>", self._pointer_moved, add="+")
        canvas.bind("<Leave>", lambda event: self._hide_tip(), add="+")

    def _pointer_moved(self, event):
        canvas = self.canvas
        found = canvas.find_overlapping(event.x - 3, event.y - 3, event.x + 3, event.y + 3)
        target = None
        for item in reversed(found):
            for tag in canvas.gettags(item):
                if tag.startswith(("wire:", "block:", "field:", "hex:", "strip:", "note:")):
                    target = tag
                    break
            if target:
                break
        cursor = "hand2" if target is not None and target.startswith("block:") and \
            xray_inside.window_class(target[6:]) is not None else ""
        if str(canvas.cget("cursor")) != cursor:
            canvas.configure(cursor=cursor)
        if self._tip is not None and self._tip[0] == target:
            return
        self._hide_tip()
        if target is not None:
            job = canvas.after(600, lambda: self._show_tip(target, event.x_root, event.y_root))
            self._tip = (target, job, None)

    def _show_tip(self, target, x, y):
        if self._tip is None or self._tip[0] != target or self.window is None:
            return
        text = self.tip_text(target)
        if not text:                    # a part of the strip not reached yet, no note: no tip
            self._tip = (target, None, None)
            return
        window = tip_window(self.canvas, text, x + px(self.canvas, 12), y + px(self.canvas, 8))
        self._tip = (target, None, window)

    def _hide_tip(self):
        if self._tip is not None:
            target, job, window = self._tip
            if job is not None:
                self.canvas.after_cancel(job)
            if window is not None:
                window.destroy()
            self._tip = None

    def tip_text(self, target):
        """What the mouse over a wire or a block shows: its name, width, purpose and value; over
        a cell of the table, its field (cell_tip()); over a part of the strip, what its steps
        did (strip_tip()); over the note of an instruction outside the datapath, all of it."""
        kind, name = target.split(":", 1)
        if kind in ("field", "hex"):
            return self.cell_tip(kind, int(name[1:]))
        if kind == "strip":
            return self.strip_tip(int(name))
        if kind == "note":
            return self.note_tip()
        trace, film = self._pass_shown()
        shown = film is not None and bool(film.steps)
        if kind == "block":
            text = f"{xray_film.BLOCK_NAMES.get(name, name)}\n{BLOCK_TIPS.get(name, '')}"
            word = self._block_word(name)
            if shown and name not in self._used_blocks():
                text += f"\nNow: {UNUSED}"
            elif word:
                text += f"\nNow: {word}"
            return text
        width = xray_picture.bits_of(name)
        lines = [f"{name}, {width} bit{'s' if width > 1 else ''}", NET_TIPS.get(name, "")]
        if name in xray_film.SIGNALS:
            lines.append(SIGNAL_LOOK)
        value = self._net_value(name, trace)
        if shown and value is None and name == "ShiftReg" and "A4Mux" in self._used_blocks():
            lines.append("Now: 0: the A4 multiplexer takes Instr 15:12")    # gray: an addition
        elif shown and value is None and name in xray_film.SIGNALS and trace is not None \
                and trace.signals:      # a signal that steers only gray parts keeps its value
            lines.append(f"Now: {xray_film.signal_value(trace, name)}, {UNUSED}")
        elif shown and value is None:
            lines.append(f"Now: {UNUSED}")
        elif value is not None and name in xray_film.REGISTER_NETS and str(value).isdigit():
            number = int(value, 2) if isinstance(value, str) else value     # "0011" or 3
            lines.append("Now: " + xray_film.register_bits(number))     # 1101 (R13)
        elif value is not None:
            lines.append("Now: " + (value_text(value, width) if not isinstance(value, str)
                                    else value))
        return "\n".join(line for line in lines if line)

    def cell_tip(self, kind, number):
        """The tip of a cell of the table: for field number of fields_of() (kind "field") its
        name and what it is, its bits and value, and where its wire takes it; for the Hex row's
        digit number (kind "hex") its bits and value, the word being the value on Instr."""
        trace = self.model.view.trace
        if trace is None:
            return ""
        word = trace.word
        if kind == "hex":
            high = 31 - 4 * number
            value = word >> high - 3 & 0xF
            return (f"Hexadecimal digit {number + 1} of 8: bits {high}:{high - 3}\n"
                    f"Value: {value:04b} = 0x{value:X} = {value}\n"
                    f"The word, 0x{word:08X}, is the value on the wire Instr")
        name, high, low, field = fields_of(trace)[number]
        meaning = field_meaning(trace, name, field)
        title = f"{name}: {meaning}" if name else meaning[:1].upper() + meaning[1:]
        return "\n".join((title, value_line(word, name, high, low, field),
                          self._where_it_goes(high, low, field)))

    def strip_tip(self, index):
        """The tip of part index of the strip: the sentences of its steps that have played or
        play now, in the pass shown, in order, one a line; nothing for a part not reached yet
        (and for a part that has no step)."""
        film = self.film
        if film is None or not film.steps:
            return ""
        player = self.player
        moment, held = (player.moment, player.held) if player.film is film else \
            (film.seconds, False)
        if moment >= film.seconds and self.model.view.kind == xray.WAITING:
            moment, held = film.seconds - WAIT, False   # the system still works (_draw_moment)
        sub, local = film.part(moment, held)
        number, _ = sub.at(local, held)
        part = xray_film.PARTS[index]
        return "\n".join(step.sentence for step in sub.steps[:number + 1] if step.part == part)

    def note_tip(self):
        """The note of an instruction outside the datapath, whole, as the panel shows its first
        words."""
        trace = self.model.view.trace
        if trace is None or not trace.note or not self.canvas.itemcget(self.note_item, "text"):
            return ""
        return textwrap.fill(trace.note, 80)

    def _where_it_goes(self, high, low, kind):
        """Where the bits high to low of a field of kind go in the film shown: on which wire,
        to which blocks, and which reject them."""
        if kind == "constant":
            return f"Goes nowhere: no wire takes {'it' if high == low else 'them'}"
        film = self.film
        used = set(film.used()) if film is not None else set()
        covering = [net for net, (top, bottom) in WORD_NETS.items()
                    if top >= high and low >= bottom and net in used]
        nets = [net for net in covering if xray_film.KINDS[net] == kind] or covering
        if not nets:
            return f"Goes nowhere: {UNUSED}"
        said = []
        for net in nets:
            outcomes = {}
            for step in film.steps:
                for move in step.moves:
                    if move.net == net:
                        for branch, outcome in move.outcomes:
                            outcomes.setdefault(branch, outcome)
            ports = xray_film.NETS[net][1]
            places = {outcome: [PLACES.get(ports[branch].split(".")[0], ports[branch])
                                for branch in ports if outcomes.get(branch) == outcome]
                      for outcome in (xray_film.TAKEN, xray_film.REJECTED, xray_film.CLOSED)}
            text = f"on the wire {net}"
            reached = places[xray_film.TAKEN] or places[xray_film.CLOSED]
            if reached:
                text += f" to {joined(reached)}"
            rejected = places[xray_film.REJECTED]
            if rejected:
                text += f"; {joined(rejected)} reject{'s' if len(rejected) == 1 else ''} it"
            said.append(text)
        return "Goes " + "; ".join(said)

    def _pass_shown(self):
        """(trace, film) of what the picture shows: for an LDM, STM, PUSH or POP the pass it
        shows now; else the instruction and its film."""
        film = self.film
        if film is None or not film.passes:
            return self.model.view.trace, film
        moment = self.player.moment if self.player.film is film else film.seconds
        sub, _ = film.part(moment, self.player.held)
        return sub.trace, sub

    def _net_value(self, name, trace):
        _, film = self._pass_shown()
        if film is not None:
            for step in film.steps:
                for move in step.moves:
                    if move.net == name:
                        if name in xray_film.SIGNALS:
                            return move.text
                        value = trace.values.get(name) if trace and trace.values else None
                        if name in ("Cond", "Op", "Funct", "Imm", "Shamt", "Rn", "Rd", "Rm"):
                            return move.text
                        return value if value is not None else move.text
        return None

    def _used_blocks(self):
        """The blocks that work in the film shown (the pass shown): they light or decide."""
        used = set()
        for step in self._pass_shown()[1].steps:
            used |= {block for block, _ in step.lights}
            used |= {decision.mux for decision in step.decisions}
        return used

    def _block_word(self, block):
        canvas = self.canvas
        item = self.picture.words.get(block)
        return canvas.itemcget(item, "text") if item is not None else ""

    # Inside the blocks --------------------------------------------------------------------

    def _clicked(self, event):
        """A click on a block opens the window with what is inside it."""
        canvas = self.canvas
        found = canvas.find_overlapping(event.x - 2, event.y - 2, event.x + 2, event.y + 2)
        for item in reversed(found):
            for tag in canvas.gettags(item):
                if tag.startswith("block:") and xray_inside.window_class(tag[6:]) is not None:
                    self.open_inside(tag[6:])
                    return

    def open_inside(self, block):
        """Open the window inside block (bring it to the front when it is open); None when the
        block has none."""
        kind = xray_inside.window_class(block)
        if kind is None:
            return None
        window = self.insides.get(block)
        if window is not None and window.window is not None:
            window.lift()
        else:
            window = self.insides[block] = kind(self)
        film = self.film
        if film is not None:
            moment = self.player.moment if self.player.film is film else film.seconds
            self._draw_insides(film, moment)
        return window

    def inside_closed(self, window):
        self.insides = {block: open_window for block, open_window in self.insides.items()
                        if open_window is not window}

    def _draw_insides(self, film, moment, held=False):
        if not self.insides:
            return
        film, moment = film.part(moment, held)
        if self._context is None or getattr(self, "_context_film", None) is not film:
            self._context = self._make_context(film)
            self._context_film = film
        for window in list(self.insides.values()):
            if window.window is not None:
                window.draw(film, moment, self._context)

    def _make_context(self, film=None):
        """What the windows inside the blocks need besides the film (xray_inside.Context); for a
        pass of an LDM, STM, PUSH or POP, the registers before and after that pass, and its own
        memory write."""
        model = self.model
        view = model.view
        machine = model.machine
        trace = view.trace
        if film is not None and film.trace is not None and film.trace.count:
            return self._pass_context(film.trace)
        peek = xray._peek(machine) if machine is not None else (lambda address, size: None)
        before = after = None
        writes = []
        if view.kind == xray.EXECUTED and model.change is not None and machine is not None:
            before = list(model.change.registers[2:18])
            after = [machine.reg(n) for n in range(16)]
            writes = [(address, bytes(old), peek(address, len(old)))
                      for address, old in model.change.writes]
        elif machine is not None and trace is not None:
            before = [machine.reg(n) for n in range(16)]
        return xray_inside.Context(view, trace, before, after, peek, writes)

    def _pass_context(self, trace):
        """The Context of one pass (trace) of an LDM, STM, PUSH or POP."""
        model = self.model
        view, machine = model.view, model.machine
        peek = xray._peek(machine) if machine is not None else (lambda address, size: None)
        passes = view.trace.passes if view.trace is not None else (trace,)
        number = trace.number
        before = list(trace.registers[:16])
        after = writes = None
        if view.kind == xray.EXECUTED and model.change is not None and machine is not None:
            if number < len(passes):
                after = list(passes[number].registers[:16])
            else:
                after = [machine.reg(n) for n in range(16)]
            writes = []
            address = trace.values.get("Address")
            if trace.signals.get("MemWrite") == "1" and address is not None:
                for start, old in model.change.writes:
                    offset = (address - start) & 0xFFFFFFFF
                    if offset < len(old):
                        writes.append((address, bytes(old[offset:offset + 4]),
                                       peek(address, 4)))
        return xray_inside.Context(view, trace, before, after, peek, writes or [])

    # What it shows -----------------------------------------------------------------------

    def show(self, mode=None, resume=None):
        """Show the model's view: its film played whole from the start with mode WHOLE, its
        first step with mode STEPS (then it waits), else finished (this ends a film that
        plays). resume is where the film had got to when the SVC that waited for input has
        ended (_reached()): the film goes on at the system (_starting())."""
        if not self._fitted:
            self._fit()
        self.stop_film()
        view = self.model.view
        self.film = film = self._film_of(view)
        self._context = None
        self._draw_view(view)
        self.mode = mode if film.steps else None
        if film.steps and mode is not None:
            moment, stop_at, wait = self._starting(film, mode, resume)
            if wait:
                self.player.hold(film, moment)
            else:
                self.player.play(film, moment, stop_at)
                self._schedule()
        elif film.steps:
            self.player.finish(film)
        else:
            self.player.film = None
            self.picture.clear(resting=view.trace is None)  # outside the datapath: all pale
            self._show_moment(film, 0.0, finished=True)
            self._draw_insides(film, film.seconds)
        self._update_buttons()

    @staticmethod
    def _starting(film, mode, resume=None):
        """(moment, stop_at, wait): where a film of mode begins. Whole, at its start; step by
        step, its first step plays and waits. When an SVC that waited for input has ended,
        resume is (number, held): the step its film had reached, and whether it waited at that
        step's end. The film goes on at the system's step, whole to the end; step by step, the
        system's step plays again and waits, but a film that had not reached it stays where it
        was: waiting there, or playing that step to its end."""
        steps = film.steps
        number, held = resume if resume is not None else (0, False)
        if resume is not None:
            system = next((index for index, step in enumerate(steps)
                           if any(block == "System" for block, _ in step.lights)), 0)
            if mode != STEPS or number >= system:
                number, held = system, False
        number = min(number, len(steps) - 1)
        if held and mode == STEPS:
            return step_end(film, number), None, True
        return steps[number].start, step_end(film, number) if mode == STEPS else None, False

    @property
    def player(self):
        if getattr(self, "_player", None) is None:
            self._player = Player(self._draw_moment, self.clock)
        return self._player

    def _film_of(self, view):
        trace = view.trace
        next_text = ""
        if view.kind == xray.EXECUTED and self.model.next is not None:
            next_text = self.model.next[1]
        service = ""
        machine = self.model.machine
        if trace is not None and trace.kind == xray.SYSTEM_CALL and machine is not None:
            change = self.model.change if view.kind == xray.EXECUTED else None
            before = list(change.registers[2:18]) if change is not None else None
            service = service_text(trace.word & 0xFFFFFF, machine, before,
                                   done=view.kind == xray.EXECUTED)
        waiting = error = ""
        if view.kind == xray.WAITING:
            waiting = {INPUT: "popup" if self.model.popup_input else "input",
                       DIALOG: "dialog"}.get(self.model.waits, "input")
        elif view.kind == xray.FAILED:
            error = view.heading

        def made(next_text):
            return xray_film.film(trace, self.seconds, xray_picture.lengths(), next_text,
                                  service, waiting, error)
        film = made(next_text)
        if next_text and film.steps:    # the last sentence names the next instruction: its
            tip = tkfont.nametofont("TkTooltipFont", root=self.canvas)  # line in the tip of
            width = TIP_WIDTH * scale(self.canvas)                      # Next PC is not wider
            over = tip.measure(film.steps[-1].sentence) - width
            if over > 0:
                room = tip.measure(next_text) - over
                film = made(self._shorten(next_text, room, tip))
        return film

    def _measure(self, text, font):
        """The width of text in one of the canvas's fonts, named, in design pixels; in a Font
        given, in screen pixels."""
        if isinstance(font, str):
            return self.fonts[font].measure(text) / self.k
        return font.measure(text)

    def _shorten(self, text, width, font):
        """text, cut short with "..." when it is wider than width in font (as _measure())."""
        if self._measure(text, font) <= width:
            return text
        while text and self._measure(text + "...", font) > width:
            text = text[:-1]
        return text + "..."

    def _fit(self):
        """Choose the picture's usual zoom, at which the whole window fits the screen it opens
        on (zoom_for()), and the window's two sizes: it opens at its usual size, and can be made
        as small as its least, the picture at zoom 1, where its smallest text has 8 points. The
        window keeps asking for its usual size while its contents ask for the least: between
        the two the room of the picture shrinks, and nothing else is cut off."""
        self._fitted = True
        window, root = self.window, self.app.root
        window.update_idletasks()
        k = scale(window)
        one = (round(CANVAS[0] * k), round(CANVAS[1] * k))
        least = (window.winfo_reqwidth(), window.winfo_reqheight())
        chrome = (least[0] - one[0], least[1] - one[1])
        frame = frame_of(root)
        middle = (root.winfo_rootx() + frame[2] // 2, root.winfo_rooty() + frame[3] // 2)
        area = screen_area(root, *middle)
        zoom = zoom_for(area, (frame[4], frame[5]), chrome, (CANVAS[0] * k, CANVAS[1] * k))
        self.usual_zoom = zoom
        if zoom != self.zoom:
            self._make_canvas(zoom)
        self.least = least
        self.usual = (least[0] + round(CANVAS[0] * (k * zoom)) - one[0],
                      least[1] + round(CANVAS[1] * (k * zoom)) - one[1])
        window.pack_propagate(False)
        window.configure(width=self.usual[0], height=self.usual[1])

    def min_size(self):
        """The least size: the picture at zoom 1 (see _fit())."""
        return self.least if self.least is not None else super().min_size()

    def _room_settled(self):
        """The window's size has settled: draw the picture again as large as its room holds it,
        in proportion (fitted_zoom())."""
        if self.window is None:
            return
        room = self.room
        zoom = fitted_zoom((room.winfo_width() - self.border[0],
                            room.winfo_height() - self.border[1]), CANVAS, scale(self.window),
                           self.zoom)
        if zoom is not None and zoom != self.zoom:
            self.rezoom(zoom)

    def rezoom(self, zoom):
        """Draw everything again at zoom. The picture goes on showing what it showed: a film
        goes on from its moment, playing or paused, and the windows inside the blocks keep
        theirs (each has a size of its own)."""
        player = self.player
        held = player.playing           # the film waits while the picture is drawn again: the
        if held:                        # first picture of a large window takes long to paint,
            player.pause()              # and a film that went on meanwhile would skip it
        try:
            self._hide_tip()
            old = self.film
            self._make_canvas(zoom)
            view = self.model.view
            self._draw_view(view)
            if old is None:                 # nothing shown yet
                return
            film = self._film_of(view)      # the same, unless the screen's scale changed
            if film.steps == old.steps and film.seconds == old.seconds:
                film = old
            else:
                self._context = None
            self.film = film
            if film.steps and player.film is old:
                player.rescale(film)        # the same moment: it draws it
            else:
                self.picture.clear(resting=film.trace is None)
                self._show_moment(film, 0.0, finished=True)
            self._update_buttons()
        finally:
            if held and self.window is not None:
                self.canvas.update_idletasks()      # drawn at the new size now
                player.resume()
                self._schedule_if_playing()
                self._update_buttons()

    def _draw_view(self, view):
        """The parts that do not move: headings, the word and its fields, the panel."""
        canvas = self.canvas
        trace = view.trace
        canvas.itemconfigure(self.heading_item, text=kind_heading(trace))
        self._show_view_heading(view)
        self._draw_fields(trace, view.written)
        self._show_panel([])
        self._shown = None              # the strip and the fields are drawn again

    def _show_view_heading(self, view):
        """What the tool shows, at the bottom right above the line on the blocks, and after it
        the instruction's address and text (as written, else its Basic form), in the panel's
        width. When the two do not fit, the instruction keeps at least half the room and what
        the tool shows is cut short: a runtime error, the longest, stands whole in the panel."""
        canvas = self.canvas
        room = VIEW_WIDTH
        heading, text = self._view_heading(view), ""
        if view.trace is not None:
            address = f"0x{view.trace.pc:08X}  "
            text = address + xray.named(view.written, view.trace.text)
            wanted = room - self._measure(heading, "bold") - VIEW_GAP
            if self._measure(text, "code_bold") > wanted:
                width = max(wanted, room / 2) - self._measure(address, "code_bold")
                text = address + self._shorten(text[len(address):], width, "code_bold")
            room -= self._measure(text, "code_bold") + VIEW_GAP
        heading = self._shorten(heading, room, "bold")
        canvas.itemconfigure(self.view_heading, text=heading)
        left = VIEW[0] + (self._measure(heading, "bold") + VIEW_GAP if heading else 0)
        canvas.coords(self.view_text, *self.xy(left, VIEW[1]))
        canvas.itemconfigure(self.view_text, text=text)

    def _view_heading(self, view):
        model = self.model
        if view.kind == xray.NOTHING:
            if not model.connected:
                return "Click Connect to ARM to follow the program."
            if model.machine is None:
                return "No program is loaded."
            return view.heading or "Waiting for the program."
        return view.heading

    def _draw_fields(self, trace, written=None):
        """The instruction's line (as written, with its Basic form when the two differ) and,
        under it, the table of its word: in row Field the names of its fields, in row Binary
        their bits, each field's cells as wide as its bits, and in row Hex the word's eight
        hexadecimal digits, each under its four bits."""
        canvas = self.canvas
        canvas.delete("cells")
        self.cells, self.hex_cells = [], []
        top = TABLE[1]
        if trace is None:
            canvas.itemconfigure(self.instruction_item, text="")
            for number in range(len(TABLE_ROWS)):
                self._cell(bit_x(31), top + number * ROW, bit_x(0) + BIT_WIDTH, FIELD)
            self._light_fields(False)
            return
        line = self._shorten(xray.instruction_line(written, trace.text),
                             bit_x(0) + BIT_WIDTH - LINE[0], "bits_bold")
        canvas.itemconfigure(self.instruction_item, text=line)
        word = trace.word
        for index, (name, high, low, kind) in enumerate(fields_of(trace)):
            tag = f"field:f{index}"
            left, right = bit_x(high), bit_x(low) + BIT_WIDTH
            boxes = (self._cell(left, top, right, EMPTY if kind == "constant" and not name
                                else FIELD, tag),
                     self._cell(left, top + ROW, right, FIELD, tag))
            label = self.text((left + right) / 2, top + ROW / 2, name, "center", "bold", IDLE,
                              tags=("cells", tag)) if name else None
            digits = [self.text(bit_x(bit) + BIT_WIDTH / 2, top + 1.5 * ROW,
                                str(word >> bit & 1), "center", "code", IDLE, tags=("cells", tag))
                      for bit in range(high, low - 1, -1)]
            self.cells.append(Cells(name, high, low, kind, boxes, label, digits))
        for number in range(8):
            left = bit_x(31 - 4 * number)
            tag = f"hex:h{number}"
            box = self._cell(left, top + 2 * ROW, left + 4 * BIT_WIDTH, FIELD, tag)
            digit = self.text(left + 2 * BIT_WIDTH, top + 2.5 * ROW,
                              f"{word >> 28 - 4 * number & 0xF:X}", "center", "code_bold", IDLE,
                              tags=("cells", tag))
            self.hex_cells.append((box, digit))
        self._light_fields(False)

    def _cell(self, left, top, right, fill, tag=None):
        """A cell of the table, one row high, from left to right."""
        return self.canvas.create_rectangle(*self.xy(left, top), *self.xy(right, top + ROW),
                                            fill=fill, outline=IDLE, width=max(1, self.k),
                                            tags=("cells", tag) if tag else ("cells",))

    def _light_fields(self, on):
        """Light the table (on): each field's cells in the colour of its value on the picture,
        the Hex row in the colour of Instr, whose value it is; else everything gray. The table
        is the key of the colours."""
        canvas = self.canvas
        for cell in self.cells:
            colour = cell_colour(cell.kind, cell.name) if on else IDLE
            fill = tinted(colour) if on and cell.kind != "constant" else FIELD
            name_box, bits_box = cell.boxes
            if cell.name or cell.kind != "constant":    # bits that are no field stay gray
                canvas.itemconfigure(name_box, fill=fill)
            canvas.itemconfigure(bits_box, fill=fill)
            if cell.label is not None:
                canvas.itemconfigure(cell.label, fill=colour)
            for digit in cell.digits:
                canvas.itemconfigure(digit, fill=colour)
        colour = VALUES["instr"] if on and self.hex_cells else IDLE
        for box, digit in self.hex_cells:
            canvas.itemconfigure(box, fill=tinted(colour) if on else FIELD)
            canvas.itemconfigure(digit, fill=colour)
        canvas.itemconfigure(self.hex_prefix, fill=colour if on and self.hex_cells else DIM)
        self.fields_lit = on

    def _draw_moment(self, film, moment):
        """Draw film at moment: the picture, the strip and, at the end, the panel."""
        held = self.player.held
        finished = moment >= film.seconds
        if finished and self.model.view.kind == xray.WAITING:
            moment = film.seconds - WAIT    # the system still works: its step stays lit
            held = finished = False
        sub, local = film.part(moment, held)
        self.picture.draw_film(sub, local, held)
        self._show_moment(film, moment, finished=finished, held=held)
        self._draw_insides(film, moment, held)

    def _show_moment(self, film, moment, finished, held=False):
        canvas = self.canvas
        trace = film.trace
        if not film.steps:
            self._shown = None
            for box, label in self.strip:
                canvas.itemconfigure(box, fill=WHITE, outline=IDLE, width=max(1, self.k))
                canvas.itemconfigure(label, fill=IDLE, font=self.fonts["small"])
            self._light_fields(trace is not None)
            self._fill_panel()
            return
        number, fraction = film.at(moment, held)
        waiting_end = self.model.view.kind == xray.WAITING and moment >= film.seconds - WAIT
        shown = (id(film), min(number, len(film.steps) - 1), finished, waiting_end)
        if shown == getattr(self, "_shown", None):
            return                      # the same film at the same step: only the picture moved
        self._shown = shown
        current = film.steps[min(number, len(film.steps) - 1)]
        part = xray_film.PARTS.index(current.part)
        for index, (box, label) in enumerate(self.strip):
            # The parts played and the part that plays take the colours of the Pipeline
            # Simulator's stages; the part that plays has a dark outline and bold letters.
            playing = index == part and not finished
            reached = finished or index <= part
            canvas.itemconfigure(box, fill=STAGES[xray_film.PARTS[index]] if reached else WHITE,
                                 outline=INK if playing else IDLE,
                                 width=max(1, self.k * (2 if playing else 1)))
            canvas.itemconfigure(label, fill=INK if reached else IDLE,
                                 font=self.fonts["bold"] if playing else self.fonts["small"])
        if film.passes:                 # the heading says which pass plays
            canvas.itemconfigure(self.heading_item,
                                 text=kind_heading(film.part(moment, held)[0].trace))
        split = next((i for i, step in enumerate(film.steps) if step.fields), None)
        self._light_fields(split is not None and number >= split)
        if trace is not None and trace.signals:
            decoded = any(step.lights and step.lights[0][0] == "Control"
                          for step in film.steps[:number + 1])
            self.picture.show_condition(condition_lines(trace) if decoded else "")
            if trace.count > 1 and decoded:     # the pass counter, under the condition
                shown = film.part(moment, held)[0].trace
                self.picture.show_pass(f"pass {shown.number} of {shown.count}")
            else:
                self.picture.show_pass("")
        if finished or waiting_end:
            self._fill_panel()
        else:                           # what it did comes at the end; the next instruction
            following = self._next_lines()      # stays, where it stands then
            self._show_panel([], [""] * max(0, PANEL_LINES - len(following)) + following)

    def _fill_panel(self):
        """What the instruction did, as the emulator recorded it, beside the table in two
        columns of PANEL_LINES lines: "What it did:" with the changes (see _placed()), the flags,
        and always the instruction that runs next: the changes that do not fit are counted. An
        instruction outside the datapath has its kind in the heading and its note on a line
        across the two columns above them, cut short when it is long (its tip has it whole); a
        runtime error stands whole across the two columns."""
        view, model = self.model.view, self.model
        changed, after = [], []
        trace = view.trace
        note = trace.note if trace is not None and view.kind != xray.FAILED else ""
        rows = PANEL_LINES - (1 if note else 0)
        following = self._next_lines()
        if view.kind == xray.EXECUTED:
            changed.append("What it did:")
            if trace is not None and (trace.signals.get("CondEx") == "0" if trace.signals
                                      else trace.condition.endswith("does not execute")):
                changed.append("  skipped: its condition failed")
            changes = ["  " + re.sub(r"0x([0-9a-f]+)", lambda m: "0x" + m.group(1).upper(), line)
                       for line in view.did if not line.startswith(("CPSR", "PC "))]
            if not changes:
                changed.append("  no register or memory changed")
            ending = []
            if model.flags is not None:
                before, now = model.flags
                ending.append(f"  Flags NZCV {before:04b} -> {now:04b}")
            if trace is not None and trace.to_thumb:
                ending.append("  goes on in Thumb code")
            low = []                    # the next instruction keeps its lines in the right column
            if len(ending) + len(following) > rows:
                low, ending = ending, []
            left, right = self._placed(changes, rows - len(changed) - len(low),
                                       rows - len(ending) - len(following))
            changed += left + low
            after += right + ending + following
        elif trace is None and model.next is not None:     # nothing has run yet
            after += following
        elif view.kind == xray.NEXT and trace is not None:
            changed.append("It has not run yet.")
        elif view.kind == xray.WAITING:
            changed += ["It has not ended yet: the system", "waits for the answer."]
        elif view.kind == xray.FAILED:  # the heading may be cut short above the panel
            width = PANEL[1][0] + PANEL[1][2] - PANEL[0][0]
            changed += self._wrapped(view.heading, width, "code")[:PANEL_LINES]
        self._show_panel(changed, after, note)

    def _placed(self, changes, left_room, right_room):
        """(left lines, right lines) that show changes in the two columns: all in the left one
        when they fit there; otherwise the short ones (a register) in the right column, the
        others in the left, and one that no longer fits the left in the right, broken over two
        lines; what fits nowhere is counted ("and 2 more"), and to make room for that line the
        change shown last is taken back, whole."""
        wide = [self._change_lines(line) for line in changes]
        if sum(map(len, wide)) <= left_room:
            return [line for lines in wide for line in lines], []
        narrow_width = PANEL[1][2]
        left, right = [], []
        placed = []                     # (column, number of its lines) of each change shown
        for line, lines in zip(changes, wide):
            if self._measure(line, "code") <= narrow_width and len(right) < right_room:
                right.append(line)
                placed.append((right, 1))
            elif len(left) + len(lines) <= left_room:
                left += lines
                placed.append((left, len(lines)))
            else:
                split = self._narrow_lines(line)
                if split is None or len(right) + len(split) > right_room:
                    continue                    # it fits nowhere: counted below
                right += split
                placed.append((right, len(split)))
        while len(placed) < len(changes):   # a line to count the others, in the room left
            more = f"  and {len(changes) - len(placed)} more"
            if len(left) < left_room:
                return left + [more], right
            if len(right) < right_room:
                return left, right + [more]
            if not placed:
                return left, right              # no room at all, not even to count them
            column, count = placed.pop()        # take back the change shown last
            del column[-count:]
        return left, right

    def _narrow_lines(self, line):
        """A change broken over two lines that fit the right column, before its old value
        ("  Memory 0x000000EC:" and "    0x00000000 -> 0x00000000"); None when they do not."""
        if ": " not in line:
            return None
        head, tail = line.split(": ", 1)
        lines = [head + ":", "    " + tail]
        width = PANEL[1][2]
        return lines if all(self._measure(part, "code") <= width for part in lines) else None

    def _change_lines(self, line):
        """A line of what changed, as one line or, wider than the left column, two: broken
        before the new value (an 8-byte memory word, a D register)."""
        width = PANEL[0][2]
        if self._measure(line, "code") <= width or " -> " not in line:
            return [line]
        head, tail = line.rsplit(" -> ", 1)
        return [head + " ->", "      " + tail]

    def _wrapped(self, text, width, font):
        """text broken into lines no wider than width design pixels in font, between words; the
        last line of a text that needs more than PANEL_LINES lines ends with "..."."""
        lines = []
        for word in text.split():
            if lines and self._measure(lines[-1] + " " + word, font) <= width:
                lines[-1] += " " + word
            else:
                lines.append(word)
        if len(lines) > PANEL_LINES:
            lines[PANEL_LINES - 1] = self._shorten(" ".join(lines[PANEL_LINES - 1:]), width, font)
        return [self._shorten(line, width, font) for line in lines]

    def _show_panel(self, first, second=(), note=""):
        """Show what the instruction did: first in the left column, second in the right one;
        with a note (of an instruction outside the datapath), the note on a line across both
        and the two columns a line lower."""
        canvas = self.canvas
        shown = self._shorten(note, PANEL[1][0] + PANEL[1][2] - PANEL[0][0], "code") \
            if note else ""
        canvas.itemconfigure(self.note_item, text=shown)
        lower = self.fonts["code"].metrics("linespace") / self.k if note else 0
        self.panel_lines = ([shown] if note else []) + [line for line in first if line] + \
            [line for line in second if line]
        for item, lines, (x, y, _) in zip(self.panels, (first, second), PANEL):
            canvas.coords(item, *self.xy(x, y + lower))
            canvas.itemconfigure(item, text="\n".join(lines))

    def panel_text(self):
        """What the panel says, its two columns one after the other."""
        return "\n".join(self.panel_lines)

    def _next_lines(self):
        """The panel's lines naming the instruction that runs next (as written, else by its
        Basic form), for its right column; none when none is known."""
        if self.model.next is None:
            return []
        pc, text = self.model.next
        indent = "      "
        room = PANEL[1][2] - self._measure(indent, "code")
        return [f"Next: PC = 0x{pc:08X},", indent + self._shorten(text, room, "code")]

    # The film ----------------------------------------------------------------------------

    def _schedule(self):
        if self.window is None:
            return
        self._job = self.window.after(FRAME, self._tick)

    def _tick(self):
        self._job = None
        player = self.player
        player.tick()
        if player.playing:
            self._schedule()
        self._update_buttons()

    def _end_film(self):
        """A film that has not ended stops here, its instruction drawn whole (not left half
        drawn, nor waiting at a step)."""
        if self._unfinished():
            self.stop_film()
            self.player.finish(self.film)
            self._update_buttons()

    def stop_film(self):
        if self._job is not None and self.window is not None:
            self.window.after_cancel(self._job)
        self._job = None

    def _schedule_if_playing(self):
        self.stop_film()
        if self.player.playing:
            self._schedule()

    def _film_state(self):
        """(mode, ended, playing, first) of the film shown, for button_states(): mode None when
        no film was begun or the player shows another one."""
        player, film = self.player, self.film
        if film is None or not film.steps or player.film is not film:
            return None, True, False, True
        moment = player.moment
        first = film.steps[0]
        return (self.mode, moment >= film.seconds - 1e-9, player.playing,
                moment <= first.start + first.duration + 1e-9)

    def _unfinished(self):
        """A film begun by Step or One step forward has not ended."""
        mode, ended, _, _ = self._film_state()
        return mode is not None and not ended

    def toggle_pause(self):
        """Play and Pause (Space): a film that plays stops where it is; one that waits (or
        was paused) plays from there to its end."""
        if not self._unfinished() or self._running():
            return
        player = self.player
        if player.playing:
            player.pause()
            self.stop_film()
        else:
            player.play_on()
            self._schedule_if_playing()
        self._update_buttons()

    def one_step(self):
        """One step forward (O): in a film that goes step by step, its next step plays, then
        it waits; with no film that has not ended, the next instruction runs, and its film's
        first step plays (see refresh())."""
        if self._running():
            return
        mode, ended, _, _ = self._film_state()
        if mode == STEPS and not ended:
            self.player.one_step()
            self._schedule_if_playing()
            self._update_buttons()
        elif mode is None or ended:
            self._step_by_step = True
            try:
                self.app.run("step")
            finally:
                self._step_by_step = False

    def step_back(self):
        """One step back (B): in a film that went step by step, the picture of the step before
        the one shown (paused within a step, of the step before that one), waiting there; a
        film that had ended has not ended any more."""
        mode, ended, _, first = self._film_state()
        if mode != STEPS or first or self._running():
            return
        player, film = self.player, self.film
        if ended:
            number = len(film.steps) - 1
        else:
            number, _ = film.at(player.moment, player.held)
        self.stop_film()
        player.hold(film, step_end(film, number - 1))
        self._update_buttons()

    def skip(self):
        """Skip to end (E): the whole instruction at once (its button is on only while a film
        has not ended)."""
        if self.film is not None and self.film.steps:
            self.stop_film()
            self.player.finish(self.film)
            self._update_buttons()

    def _running(self):
        runner = self.app.runner
        return runner is not None and runner.state is State.RUNNING

    def _space(self, event):
        self.toggle_pause()
        return "break"

    def _film_key(self, event, button):
        """O, B and E press their film button (a disabled one does nothing); held with Control
        or Alt they are no key of the film, and are left alone."""
        if event.state & (CONTROL | self._alt):
            return None
        button.invoke()
        return "break"

    def _speed_moved(self, value):
        seconds = round(float(value))
        if self.speed_scale.get() != seconds:
            self.speed_scale.set(seconds)
        self.speed_label.configure(text=f"{seconds} s per instruction")
        if seconds == self.seconds:
            return
        self.seconds = seconds
        settings = self.app.settings
        settings.xray_seconds = seconds
        self.app.save_settings()
        if self.film is not None and self.film.steps:
            view = self.model.view
            film = self._film_of(view)
            self.film = film
            self.player.rescale(film)

    def _animate_changed(self):
        settings = self.app.settings
        settings.xray_animate = bool(self.animate.get())
        self.app.save_settings()

    def _update_buttons(self):
        """The film's buttons and the toolbar's Step and Backstep, as button_states() says for
        the film shown and the main window's commands now."""
        if self.window is None:
            return
        app = self.app
        states = button_states(*self._film_state(), self._running(), app.is_enabled("step"),
                               app.is_enabled("backstep"))
        picture = states.pop("face")
        if picture != self.pause_picture:   # Pause while the film plays, else Play
            self.pause_picture = picture
            normal, disabled = self.film_images[picture]
            self.pause_button.configure(image=(normal, "disabled", disabled))
            self.film_tips[0].set_text(FILM_TIPS[picture])
        buttons = {"pause": self.pause_button, "back": self.back_button,
                   "forward": self.one_button, "skip": self.skip_button,
                   "step": self.tool_buttons["step"], "backstep": self.tool_buttons["backstep"]}
        for name, on in states.items():
            if self._states.get(name) != on:
                self._states[name] = on
                buttons[name].state(["!disabled"] if on else ["disabled"])

    # Called by the main window ----------------------------------------------------------

    def commands_changed(self):
        """The main window's commands changed: Assemble follows them, and Step, Backstep and
        the film's buttons with what the film allows (_update_buttons())."""
        if self.window is None:
            return
        on = self.app.is_enabled("assemble")
        self.tool_buttons["assemble"].state(["!disabled"] if on else ["disabled"])
        self._update_buttons()

    def toggle_connection(self):
        runner = self.app.runner
        self.model.stopped = runner is not None and runner.state is State.FINISHED
        super().toggle_connection()

    def machine_changed(self, machine):
        self.model.stopped = False      # a new program, or none
        self.model.observe(machine)
        if machine is None and self.model.connected:
            self.model.clear()
        self.show()

    def refresh(self):
        """Nothing at all at full speed: the program's state is looked at when it stops."""
        app = self.app
        runner = app.runner
        if runner is None:
            return
        if runner.state is State.RUNNING and app.run_speed is None:
            self._end_film()            # a run at full speed: no film, and no work after this
            return
        waiting = runner.state is State.WAITING
        if waiting and not self._waiting:
            self._end_film()            # Step reached a read: the instruction has not ended
        self._waiting = waiting
        self.model.stopped = runner.state is State.FINISHED
        steps = getattr(app, "steps_taken", 0)
        stepped = steps != self._steps_seen
        self.model.popup_input = bool(getattr(app.settings, "popup_input", False))
        self._steps_seen = steps
        before = self.model.view
        if self.model.update():
            view = self.model.view
            animate = runner.state is not State.RUNNING and self.animate.get()
            undone = self.model.undone  # a Backstep shows its instruction finished: no film
            resumed = (not undone and before.kind == xray.WAITING and view.kind == xray.EXECUTED
                       and before.trace is not None and view.trace is not None
                       and before.trace.pc == view.trace.pc)
            if resumed:                 # the input came: the SVC's film goes on at the system
                mode = STEPS if self.mode == STEPS else WHOLE if animate else None
                self.show(mode, resume=self._reached())
            else:                       # a Step plays the film whole (or shows it finished),
                fresh = stepped and not undone and view.kind in (xray.EXECUTED, xray.WAITING)
                mode = STEPS if self._step_by_step else WHOLE if animate else None
                self.show(mode if fresh else None)      # One step forward its first step
        self.commands_changed()

    def _reached(self):
        """(number, held): the step that the film shown has reached, and whether it waits at
        that step's end."""
        player, film = self.player, self.film
        if film is None or not film.steps or player.film is not film:
            return 0, False
        number, _ = film.at(player.moment, player.held)
        return number, player.held

    def close(self):
        if self.window is not None:
            self.stop_film()
            self._hide_tip()
            for window in list(self.insides.values()):
                window.close()
        super().close()


WINDOW = XRayWindow
