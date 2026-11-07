# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Tools > ARM X-Ray: the datapath of a single-cycle ARM processor, one instruction at a time.

The diagram follows the textbook's single-cycle ARM processor (credits.TEXTBOOK),
with its additions in the same style; ares.xray works out what is on its wires. The tool hooks
nothing: after Step it reads what the machine recorded for Backstep, and at
full speed it does nothing until the run stops.

ARES draws the diagram with canvas shapes from the tables below, in design
pixels: WIRES and DOTS give each wire's lines by the name ares.xray uses for it,
and the other tables the blocks, the labels and the places of the values.
"""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from ... import credits, xray
from ...machine import StopReason
from ...runner import State
from ..style import WINDOW as FIELD
from ..style import (DARK_SHADOW, FACE, NAVY, SHADOW, SUNKEN_FRAME, TEXT, default_button,
                     sunken)
from ..widgets import Tooltip, px
from .frame import ToolModel, ToolWindow, place_over

SIZE = (1000, 500)              # the diagram
STAGE_DELAY = 800               # milliseconds Play stays on a stage, at the start
DELAYS = (100, 3000)            # the least and most the Animation Speed dialog allows
DID_LINES = 8                   # changes an instruction outside shows; the rest are counted
SMALL_SIZE = 8                  # points: the values and labels on the diagram
ACTIVE = NAVY                   # what the instruction uses
IDLE = SHADOW                   # the rest
ACTIVE_WIDTH, IDLE_WIDTH = 2, 1

HELP = f"""\
ARM X-Ray shows how the processor runs an instruction: which parts of the datapath it uses
and what is on the wires. The diagram is a textbook's single-cycle ARM processor, with a few
additions that real programs need. The textbook is {credits.TEXTBOOK}

Click Connect to ARM, then Step through the program. The diagram follows each instruction:
the paths the instruction uses are dark blue and thick, the rest gray. On the wires stand PC,
the instruction, the register numbers and values, the immediate, the ALU's result and flags,
the memory address and data, and the result written back. The control unit shows every
control signal: X means that its value does not matter for this instruction. The panel at
the top left shows the instruction, its class, the condition check (for example NE: Z = 0,
executes), the decoders' other signals, and the flags before and after.

Which instruction it shows: after Step, the instruction just executed, from the registers
as they were before it ran. After Backstep and when a run stops, the instruction at PC,
which runs next (after Backstep, the one undone). The line above the instruction says which.
At a slow run speed every instruction is shown as Step shows it. At full speed the tool does
nothing until the run stops, and costs nothing: it adds no hook to the program, connected
or not. If Backstep while running keeps a history, a stop shows the last instruction
executed. When the program has ended the tool says so, and it shows the instruction that a
runtime error stopped.

A condition that fails stops the writes: PCSrc, RegWrite, MemWrite and FlagWrite are 0, and
only the path of PCPlus4 to the PC is lit after the ALU.

Play walks through the five stages of the instruction shown, one at a time: Fetch, Decode,
Execute, Memory and Write back. Each stage lights what it uses, and the values appear as the
instruction reaches them. Play stops by itself after Write back, and at once when you click
it again or Step or Backstep. Speed... sets how long each stage stays on the screen.

The additions to the textbook's diagram are these. The ALU has more operations: ALUControl
has four bits, with EOR, BIC, RSB, MOV and MVN after the textbook's ADD, SUB, AND and ORR;
NoWrite stops CMP, CMN and TST from writing a register. A shifter stands between RD2 and the
ALUSrc multiplexer, for shifts by an immediate, RRX included: the signal Shift is 1 when it
changes its input, and Extend rotates the 8-bit immediate. ShiftC writes C from the shifter or
the rotated immediate, in a logical operation with S. A store with a register offset reads
three registers: A4 and RD4 are a third read port, and StoreSrc takes WriteData from RD4. Byte
makes the data memory move the low byte of LDRB and STRB. A negative offset subtracts. BL
sets Link: two small multiplexers send 14 to A3 and PCPlus4 to WD3. BX, as in the return BX LR,
reads Rm on the port of RD2; the ALU passes it on as for MOV, and the result goes to the PC. It
writes no register, no memory and no flags. The example xray_tour.s (File > Open Example) uses
only instructions of this datapath, so that every instruction it runs animates; its last line, a
branch to itself, ends the program without running.

Whatever writes the PC, bit 0 of the address does not reach it. When that bit is 1 the processor
goes on in Thumb code, and the panel says so.

Some instructions lie outside this datapath: ADC, SBC, RSC and TEQ; shifts by a register; S
with Rd = 15; multiplies; SWP; LDM, STM, PUSH and POP; LDR and STR with write-back or
post-indexing; halfword, doubleword and exclusive accesses; SVC; BLX, MOVW, MOVT, MRS, MSR,
CLZ, NOP and other hints; floating point, coprocessors and NEON; and anything with condition
1111. For these the diagram stays gray, a note says why, and the panel lists what the
instruction changed: registers and memory, or that it has not run yet. So a function that
returns with POP {{..., PC}}, which is normal ARM, shows that return gray: POP is outside the
datapath. A return with BX LR animates.

Reset clears the diagram until the program does something more. The tool stays connected
when the program is assembled again or its file is closed.
"""

# The wires: name -> lines, each a list of points. Control signals are the blue wires of the
# textbook's figure; the names are those of ares.xray.
INSTR_X = 292                   # the wire that carries Instr to everything
RESULT_Y = 488
WIRES = {
    "PC'": [[(40, 238), (116, 238)]],
    "PC": [[(134, 238), (214, 238)], [(144, 238), (144, 347), (148, 347)]],
    "Instr": [[(286, 238), (INSTR_X, 238)], [(INSTR_X, 30), (INSTR_X, 454)]],
    "PCPlus4": [[(174, 360), (236, 360)]],
    "PCFeed": [[(190, 360), (190, 470), (14, 470), (14, 250), (22, 250)]],
    "PCPlus8": [[(236, 360), (236, 392), (244, 392)], [(270, 405), (376, 405)]],
    "LinkFeed": [[(236, 360), (340, 360)]],
    "Cond": [[(INSTR_X, 30), (340, 30)]],
    "Op": [[(INSTR_X, 58), (340, 58)]],
    "Funct": [[(INSTR_X, 86), (340, 86)]],
    "Rd": [[(INSTR_X, 114), (340, 114)]],
    "Rn": [[(INSTR_X, 224), (322, 224)]],
    "Const15": [[(312, 242), (322, 242)]],
    "Rm": [[(INSTR_X, 262), (322, 262)]],
    "RdField": [[(INSTR_X, 308), (320, 308)]],
    "RdToRA2": [[(320, 308), (320, 282), (322, 282)]],
    "RdToA3": [[(320, 308), (340, 308)]],
    "A4": [[(320, 308), (320, 340), (376, 340)]],
    "Const14": [[(332, 328), (340, 328)]],
    "Imm": [[(INSTR_X, 454), (376, 454)]],
    "Shamt": [[(INSTR_X, 428), (552, 428), (552, 290)]],
    "RA1": [[(338, 233), (376, 233)]],
    "RA2": [[(338, 272), (376, 272)]],
    "A3": [[(356, 318), (376, 318)]],
    "WD3": [[(356, 370), (376, 370)]],
    "SrcA": [[(484, 233), (686, 233)]],
    "RD2": [[(484, 272), (500, 272)]],
    "Shifted": [[(500, 272), (530, 272)], [(574, 272), (590, 272)]],
    "RD2Store": [[(500, 272), (500, 328), (508, 328)]],
    "RD4": [[(484, 345), (508, 345)]],
    "WriteData": [[(526, 336), (812, 336)]],
    "ExtImm": [[(484, 454), (582, 454), (582, 296), (590, 296)]],
    "SrcB": [[(608, 284), (686, 284)]],
    "ALUResult": [[(732, 258), (802, 258)]],
    "Address": [[(802, 258), (812, 258)]],
    "ALUBypass": [[(802, 258), (802, 400), (960, 400), (960, 308), (972, 308)]],
    "ALUFlags": [[(725, 230), (725, 186), (326, 186), (326, 134), (340, 134)]],
    "ShiftC": [[(550, 258), (550, 186)]],
    "ReadData": [[(896, 276), (972, 276)]],
    "Result": [[(990, 292), (996, 292), (996, RESULT_Y), (324, RESULT_Y)]],
    "ResultPC": [[(324, RESULT_Y), (6, RESULT_Y), (6, 226), (22, 226)]],
    "ResultReg": [[(324, RESULT_Y), (324, 380), (340, 380)]],
    # The control signals.
    "PCSrc": [[(476, 16), (484, 16), (484, 3), (31, 3), (31, 219)]],
    "MemtoReg": [[(476, 30), (981, 30), (981, 267)]],
    "MemWrite": [[(476, 44), (880, 44), (880, 208)]],
    "Byte": [[(476, 58), (848, 58), (848, 208)]],
    "ALUControl": [[(476, 72), (710, 72), (710, 221)]],
    "ALUSrc": [[(476, 86), (599, 86), (599, 265)]],
    "Shift": [[(476, 100), (542, 100), (542, 258)]],
    "StoreSrc": [[(476, 114), (517, 114), (517, 321)]],
    "ImmSrc": [[(476, 128), (492, 128), (492, 436), (462, 436), (462, 440)]],
    "RegWrite": [[(450, 170), (450, 205)]],
    "RegSrc": [[(344, 170), (344, 252), (330, 252), (330, 257)],
               [(344, 196), (330, 196), (330, 219)]],
    "Link": [[(370, 170), (370, 296), (348, 296), (348, 303)],
             [(370, 296), (370, 346), (348, 346), (348, 352)]],
}
DOTS = {
    "PC": [(144, 238)],
    "Instr": [(INSTR_X, 238)],
    "PCPlus4": [(190, 360), (236, 360)],
    "RdField": [(320, 308)],
    "RD2": [(500, 272)],
    "ALUResult": [(802, 258)],
    "Result": [(324, RESULT_Y)],
    "RegSrc": [(344, 196)],
    "Link": [(370, 296)],
}

# The multiplexers: name -> left, right, top, bottom, ((label, y), ...) for its inputs.
MUXES = {
    "PCMux": (22, 40, 214, 262, (("1", 226), ("0", 250))),
    "RA1Mux": (322, 338, 216, 250, (("0", 224), ("1", 242))),
    "RA2Mux": (322, 338, 254, 290, (("0", 262), ("1", 282))),
    "A3Mux": (340, 356, 300, 336, (("0", 308), ("1", 328))),
    "WD3Mux": (340, 356, 348, 392, (("1", 360), ("0", 380))),
    "StoreMux": (508, 526, 316, 356, (("0", 328), ("1", 345))),
    "ALUSrcMux": (590, 608, 260, 308, (("0", 272), ("1", 296))),
    "ResultMux": (972, 990, 262, 322, (("1", 276), ("0", 308))),
}
# The plain blocks: name -> left, top, right, bottom.
BOXES = {
    "PCReg": (116, 222, 134, 254),
    "IMem": (214, 222, 286, 300),
    "RegFile": (376, 205, 484, 420),
    "Shifter": (530, 258, 574, 290),
    "DMem": (812, 208, 896, 372),
    "Control": (340, 8, 476, 170),
}
SHAPES = {                      # the other blocks, as polygons
    "Add4": ((148, 335), (174, 348), (174, 372), (148, 385), (148, 366), (155, 360), (148, 354)),
    "Add8": ((244, 380), (270, 393), (270, 417), (244, 430), (244, 411), (251, 405), (244, 399)),
    "ALU": ((686, 208), (732, 234), (732, 286), (686, 312), (686, 270), (700, 260), (686, 250)),
    "Extend": ((376, 452), (484, 438), (484, 470), (376, 470)),
}
CLOCKS = {"PCReg": (125, 222), "RegFile": (396, 205), "DMem": (824, 208)}   # block -> triangle
CONSTANTS = ((142, 373, "4"), (238, 418, "4"))

# Fixed text of the blocks: block -> (x, y, text, anchor, bold).
LABELS = {
    "IMem": ((250, 268, "Instruction\nMemory", "center", True), (218, 238, "A", "w", False),
             (282, 238, "RD", "e", False)),
    "RegFile": ((452, 312, "Register\nFile", "center", True), (380, 233, "A1", "w", False),
                (380, 272, "A2", "w", False), (380, 318, "A3", "w", False),
                (380, 340, "A4", "w", False), (380, 370, "WD3", "w", False),
                (380, 405, "R15", "w", False), (480, 233, "RD1", "e", False),
                (480, 272, "RD2", "e", False), (480, 345, "RD4", "e", False),
                (450, 215, "WE3", "center", False)),
    "DMem": ((854, 300, "Data\nMemory", "center", True), (816, 258, "A", "w", False),
             (816, 336, "WD", "w", False), (892, 276, "RD", "e", False),
             (880, 218, "WE", "center", False), (848, 218, "Byte", "center", False)),
    "ALU": ((714, 260, "ALU", "center", True),),
    "Extend": ((430, 460, "Extend", "center", True),),
    "Add4": ((164, 360, "+", "center", True),),
    "Add8": ((260, 405, "+", "center", True),),
    "Control": ((344, 15, "Control Unit", "w", True), (344, 30, "Cond", "w", False),
                (344, 58, "Op", "w", False), (344, 86, "Funct", "w", False),
                (344, 114, "Rd", "w", False), (344, 134, "Flags", "w", False)),
    "Shifter": ((552, 266, "Shifter", "center", True),),
}
# Fixed text on wires: wire -> (x, y, text, anchor).
WIRE_LABELS = {
    "Cond": (294, 23, "31:28", "w"),
    "Op": (294, 51, "27:26", "w"),
    "Funct": (294, 79, "25:20", "w"),
    "Rd": (294, 107, "15:12", "w"),
    "Rn": (294, 217, "19:16", "w"),
    "Const15": (310, 242, "15", "e"),
    "Rm": (294, 255, "3:0", "w"),
    "RdField": (294, 301, "15:12", "w"),
    "Const14": (330, 328, "14", "e"),
    "Imm": (294, 447, "23:0", "w"),
    "Shamt": (294, 421, "11:5", "w"),
    "PC'": (44, 216, "PC'", "w"),
    "PC": (140, 216, "PC", "w"),
    "Instr": (288, 200, "Instr", "e"),
    "PCPlus4": (176, 341, "PCPlus4", "w"),
    "PCPlus8": (374, 414, "PCPlus8", "e"),
    "RA1": (346, 226, "RA1", "w"),
    "RA2": (346, 265, "RA2", "w"),
    "SrcA": (612, 213, "SrcA", "w"),
    "SrcB": (612, 265, "SrcB", "w"),
    "ExtImm": (488, 445, "ExtImm", "w"),
    "ALUResult": (736, 239, "ALUResult", "w"),
    "ALUFlags": (620, 178, "ALUFlags", "w"),
    "ReadData": (900, 257, "ReadData", "w"),
    "WriteData": (630, 318, "WriteData", "w"),
    "Result": (870, 478, "Result", "w"),
}
# Where each value stands: wire -> x, y, anchor. The name above is its label.
VALUES = {
    "PC'": (43, 229, "w"),
    "PC": (138, 229, "w"),
    "Instr": (288, 212, "e"),
    "PCPlus4": (176, 352, "w"),
    "PCPlus8": (480, 405, "e"),
    "RA1": (402, 233, "w"),
    "RA2": (402, 272, "w"),
    "A3": (402, 318, "w"),
    "A4": (402, 340, "w"),
    "WD3": (480, 370, "e"),
    "SrcA": (612, 226, "w"),
    "RD2": (480, 285, "e"),
    "RD4": (480, 358, "e"),
    "SrcB": (612, 277, "w"),
    "ExtImm": (488, 463, "w"),
    "ALUResult": (736, 251, "w"),
    "ALUFlags": (676, 178, "w"),
    "ReadData": (900, 268, "w"),
    "WriteData": (630, 329, "w"),
    "Result": (910, 478, "w"),
}
REGISTER_WIRES = ("RA1", "RA2", "A3", "A4")
# The control signals as the control unit shows them: signal -> x, y, anchor.
SIGNALS = {
    "PCSrc": (472, 16, "e"), "MemtoReg": (472, 30, "e"), "MemWrite": (472, 44, "e"),
    "Byte": (472, 58, "e"), "ALUControl": (472, 72, "e"), "ALUSrc": (472, 86, "e"),
    "Shift": (472, 100, "e"), "StoreSrc": (472, 114, "e"), "ImmSrc": (472, 128, "e"),
    "NoWrite": (472, 144, "e"), "RegWrite": (472, 160, "e"), "RegSrc": (344, 160, "w"),
    "Link": (344, 147, "w"), "ShiftC": (553, 197, "w"),
}
FIELDS = {"Cond": (30, 28, 4), "Op": (58, 26, 2), "Funct": (86, 20, 6), "Rd": (114, 12, 4)}
FIELD_X = 376                   # wire -> y, lowest bit, bits of the field the control unit gets
FLAGS_Y = 134
INFO = (44, 12, 240)            # the panel at the top left: x, y, width
STAGE_BOXES = (620, 432, 70, 20)    # the first stage's box: x, y, width, height
INTERNAL = ("Branch", "MemW", "RegW", "ALUOp", "FlagW", "PCS", "CondEx", "FlagWrite")


class XRayModel(ToolModel):
    """Which instruction to show (a xray.View), looked for only after the program stopped
    moving: update() reads the machine and needs no hooks.

    stopped says that the program was stopped for good (Stop), which the
    machine itself does not know.
    """

    def __init__(self):
        super().__init__()
        self.view = xray.View()
        self._forget()

    def _forget(self):
        self.stopped = False
        self._state = None              # the machine as it was at the last look
        self._number = 0                # the newest change seen
        self._backsteps = 0

    def attach(self, machine):
        stopped = self.stopped
        self._forget()
        self.stopped = stopped          # what the window said before connecting
        self._backsteps = machine.backsteps
        self.update()

    def reset(self):
        """Clear the picture until the program does something."""
        self.view = xray.View()

    def clear(self):
        """No program any more."""
        self.view = xray.View()
        self._forget()

    def update(self):
        machine = self.machine
        if machine is None:
            return False
        history = machine.history
        newest = history[-1] if history else None
        number = newest.number if newest is not None else 0
        state = (number, machine.backsteps, machine.stop_reason, self.stopped, machine.cpsr,
                 [machine.reg(n) for n in range(16)])
        if state == self._state:
            return False
        fresh = number > self._number
        undone = machine.backsteps > self._backsteps
        self._state, self._number, self._backsteps = state, number, machine.backsteps
        ended = machine.stop_reason is not None or self.stopped
        if machine.stop_reason is StopReason.ERROR:
            trace = None if machine.no_code else xray.upcoming(machine, machine.error_address)
            view = xray.View(xray.FAILED, machine.error, trace)
        elif fresh:
            view = self._executed(newest, ended)
        elif undone:
            view = xray.View(xray.UNDONE, "Undone by Backstep: it runs next",
                             xray.upcoming(machine))
        elif ended:
            view = xray.View(xray.ENDED, "The program has ended", ended=True)
        elif self.view.kind == xray.EXECUTED and newest is not None:
            return False                # a register changed by hand: that instruction still ran
        else:
            view = xray.View(xray.NEXT, "Runs next: it has not run yet", xray.upcoming(machine))
        self.view = view
        return True

    def _executed(self, change, ended):
        machine = self.machine
        shown = xray.executed(machine, change)
        did = tuple(xray.changes(machine, change)) if shown.note else ()
        heading = "Just executed; the program has ended" if ended else "Just executed"
        return xray.View(xray.EXECUTED, heading, shown, did, ended)


def show_value(name, value):
    """A wire's value as the diagram shows it: "?" until it can be known."""
    if value is None:
        return "?"
    if name in REGISTER_WIRES:
        return f"R{value}"
    if name == "ALUFlags":
        return xray.flag_text(value)
    return f"0x{value:08x}"


class Diagram:
    """The datapath on a canvas (see the module's description)."""

    def __init__(self, master, app):
        canvas = self.canvas = tk.Canvas(master, width=px(master, SIZE[0]),
                                         height=px(master, SIZE[1]), background=FIELD,
                                         borderwidth=0, highlightthickness=0, takefocus=False)
        pane = app.pane_font
        interface = tkfont.nametofont("TkTextFont", root=master).actual("family")
        self.small = tkfont.Font(root=master, family=interface, size=SMALL_SIZE)
        self.bold = tkfont.Font(root=master, family=interface, size=SMALL_SIZE, weight="bold")
        self.code = tkfont.Font(root=master, family=pane.cget("family"), size=SMALL_SIZE)
        self.big_code = tkfont.Font(root=master, family=pane.cget("family"), size=SMALL_SIZE + 1,
                                    weight="bold")
        self.values = {}                # wire -> its value's text item
        self.signals = {}               # signal -> its text item
        self.fields = {}                # Instr field -> its text item
        self.blocks_text = {}           # block -> its labels' text items
        self.wire_text = {}             # wire -> its label's text item
        self.stage_boxes = []           # (rectangle, text) of each stage
        self._draw()

    def _point(self, x, y):
        return px(self.canvas, x), px(self.canvas, y)

    def _flat(self, points):
        return [number for point in points for number in self._point(*point)]

    def _text(self, x, y, text, anchor, font=None, fill=IDLE, **options):
        return self.canvas.create_text(*self._point(x, y), text=text, anchor=anchor,
                                       font=font or self.small, fill=fill, **options)

    def _draw(self):
        canvas = self.canvas
        self._draw_blocks()
        for name, lines in WIRES.items():
            for line in lines:
                canvas.create_line(*self._flat(line), fill=IDLE, width=px(canvas, IDLE_WIDTH),
                                   capstyle="projecting", joinstyle="miter", tags=("wire", name))
        reach = px(canvas, 2)
        for name, points in DOTS.items():
            for x, y in points:
                x, y = self._point(x, y)
                canvas.create_oval(x - reach, y - reach, x + reach, y + reach, fill=IDLE,
                                   outline=IDLE, tags=("dot", name))
        for name, (x, y, text, anchor) in WIRE_LABELS.items():
            self.wire_text[name] = self._text(x, y, text, anchor)
        for name, (x, y, anchor) in VALUES.items():
            self.values[name] = self._text(x, y, "", anchor, self.code, TEXT)
        for name, (x, y, anchor) in SIGNALS.items():
            self.signals[name] = self._text(x, y, name, anchor)
        for name, (y, _, _) in FIELDS.items():
            self.fields[name] = self._text(FIELD_X, y, "", "w", self.code, TEXT)
        self.flags = self._text(FIELD_X, FLAGS_Y, "", "w", self.code, TEXT)
        self.shift_text = self._text(552, 280, "", "center", self.code, TEXT)
        self._draw_stages()
        x, y, width = INFO
        self.heading = self._text(x, y, "", "nw", self.bold, TEXT, width=px(canvas, width))
        self.instruction = self._text(x, y, "", "nw", self.big_code, TEXT,
                                      width=px(canvas, width))
        self.info = self._text(x, y, "", "nw", self.small, TEXT, width=px(canvas, width))

    def _draw_blocks(self):
        canvas = self.canvas
        for name, (left, right, top, bottom, inputs) in MUXES.items():
            slope = (bottom - top) // 5
            points = [(left, top), (right, top + slope), (right, bottom - slope), (left, bottom)]
            canvas.create_polygon(*self._flat(points), fill=FIELD, outline=IDLE,
                                  width=px(canvas, IDLE_WIDTH), tags=("block", name))
            self.blocks_text[name] = [
                self._text(left + 4, y, label, "w") for label, y in inputs]
        for name, (left, top, right, bottom) in BOXES.items():
            canvas.create_rectangle(*self._flat(((left, top), (right, bottom))), fill=FIELD,
                                    outline=IDLE, width=px(canvas, IDLE_WIDTH),
                                    tags=("block", name))
        for name, points in SHAPES.items():
            canvas.create_polygon(*self._flat(points), fill=FIELD, outline=IDLE,
                                  width=px(canvas, IDLE_WIDTH), tags=("block", name))
        for name, (x, y) in CLOCKS.items():
            points = ((x - 5, y), (x + 5, y), (x, y + 7))
            canvas.create_polygon(*self._flat(points), fill=FIELD, outline=IDLE,
                                  width=px(canvas, IDLE_WIDTH), tags=("block", name))
            self._text(x, y - 7, "CLK", "center")
        for name, labels in LABELS.items():
            self.blocks_text.setdefault(name, []).extend(
                self._text(x, y, text, anchor, self.bold if bold else self.small,
                           justify="center" if anchor == "center" else "left")
                for x, y, text, anchor, bold in labels)
        for x, y, text in CONSTANTS:
            self._text(x, y, text, "e")

    def _draw_stages(self):
        x, y, width, height = STAGE_BOXES
        for number, name in enumerate(xray.STAGES):
            left = x + number * (width + 2)
            box = self.canvas.create_rectangle(*self._flat(((left, y), (left + width, y + height))),
                                               fill=FACE, outline=IDLE)
            text = self._text(left + width // 2, y + height // 2, name, "center", self.small)
            self.stage_boxes.append((box, text))

    def show(self, trace, stage=None):
        """Show trace (None: no instruction): all of it, or as far as stage (Play), lighting
        that stage alone."""
        canvas = self.canvas
        stages = trace.stages if trace is not None else ()
        lit = stages if stage is None else stages[stage:stage + 1]
        wires = frozenset().union(*(each.wires for each in lit))
        blocks = frozenset().union(*(each.blocks for each in lit))
        reached = stages if stage is None else stages[:stage + 1]
        known = frozenset().union(*(each.wires for each in reached))
        for name in WIRES:
            active = name in wires
            colour, width = (ACTIVE, ACTIVE_WIDTH) if active else (IDLE, IDLE_WIDTH)
            canvas.itemconfigure(f"wire&&{name}", fill=colour, width=px(canvas, width))
            canvas.itemconfigure(f"dot&&{name}", fill=colour, outline=colour)
            if name in self.wire_text:
                canvas.itemconfigure(self.wire_text[name], fill=TEXT if active else IDLE)
        for name in xray.BLOCKS:
            active = name in blocks
            colour, width = (ACTIVE, ACTIVE_WIDTH) if active else (IDLE, IDLE_WIDTH)
            canvas.itemconfigure(f"block&&{name}", outline=colour, width=px(canvas, width))
            for item in self.blocks_text.get(name, ()):
                canvas.itemconfigure(item, fill=DARK_SHADOW if active else IDLE)
        values = trace.values if trace is not None else {}
        for name, item in self.values.items():
            text = show_value(name, values.get(name)) if name in known else ""
            canvas.itemconfigure(item, text=text)
        self._show_signals(trace, wires)
        self._show_stage(stage)

    def _show_signals(self, trace, wires):
        canvas = self.canvas
        signals = trace.signals if trace is not None else {}
        for name, item in self.signals.items():
            value = signals.get(name)
            text = name if value is None else f"{name} {value}"
            canvas.itemconfigure(item, text=text, fill=TEXT if name in wires else IDLE)
        for name, (_, low, bits) in FIELDS.items():
            shown = signals and f"{trace.word >> low & (1 << bits) - 1:0{bits}b}"
            canvas.itemconfigure(self.fields[name], text=shown or "")
        canvas.itemconfigure(self.flags, text=signals and xray.flag_text(trace.flags) or "")
        shifted = trace is not None and signals.get("Shift") == "1"
        canvas.itemconfigure(self.shift_text, text=xray.shift_text(trace.word) if shifted else "")

    def _show_stage(self, stage):
        canvas = self.canvas
        for number, (box, text) in enumerate(self.stage_boxes):
            current = number == stage
            canvas.itemconfigure(box, fill=ACTIVE if current else FACE)
            canvas.itemconfigure(text, fill=FIELD if current else IDLE)

    def write_info(self, heading, instruction, body):
        """Fill the panel at the top left: each part starts where the one above it ended."""
        canvas = self.canvas
        room = px(canvas, 4)
        y = px(canvas, INFO[1])
        for item, text in ((self.heading, heading), (self.instruction, instruction),
                           (self.info, body)):
            canvas.itemconfigure(item, text=text)
            canvas.coords(item, px(canvas, INFO[0]), y)
            box = canvas.bbox(item)
            if text and box:
                y = box[3] + room


class AnimationDialog:
    """Speed...: how long each stage of Play stays on the screen.

    It is modal, and opens centred over the tool's window. OK gives
    apply(milliseconds) the time chosen; Cancel, Escape and the close box
    change nothing.
    """

    def __init__(self, master, delay, apply):
        self.apply = apply
        window = self.window = tk.Toplevel(master)
        window.withdraw()
        window.title("Animation Speed")
        window.transient(master)
        window.resizable(False, False)
        gap = px(window, 6)
        body = ttk.Frame(window, padding=2 * gap)
        body.pack(fill="both", expand=True)
        self.delay = tk.DoubleVar(master=window, value=delay)
        self.text = ttk.Label(body, text="")
        self.text.pack(anchor="w")
        self.scale = ttk.Scale(body, from_=DELAYS[0], to=DELAYS[1], variable=self.delay,
                               length=px(window, 240), command=self._moved)
        self.scale.pack(fill="x", pady=gap)
        buttons = ttk.Frame(body)
        buttons.pack(anchor="e", pady=(gap, 0))
        ok = ttk.Button(buttons, text="OK", command=self.ok)
        ok.pack(side="left", padx=(0, gap))
        cancel = ttk.Button(buttons, text="Cancel", command=self.cancel)
        cancel.pack(side="left")
        default_button(ok, (ok, cancel))
        self._moved()
        window.bind("<Return>", self._return)
        window.bind("<KP_Enter>", self._return)
        window.bind("<Escape>", lambda event: self.cancel())
        window.protocol("WM_DELETE_WINDOW", self.cancel)
        place_over(window, master)
        window.deiconify()
        window.grab_set()
        ok.focus_set()

    def milliseconds(self):
        return round(self.delay.get() / 50) * 50

    def _moved(self, *args):
        self.text.configure(text=f"Each stage stays for {self.milliseconds() / 1000:.2f} s")

    def _return(self, event):
        if isinstance(event.widget, ttk.Button):
            event.widget.invoke()
        else:
            self.ok()
        return "break"

    def ok(self):
        self.apply(self.milliseconds())
        self.cancel()

    def cancel(self):
        self.window.grab_release()
        self.window.destroy()


class XRayWindow(ToolWindow):
    """Tools > ARM X-Ray."""

    NAME = "ARM X-Ray"
    HEADING = "Animation of the ARM Datapath"
    HELP = HELP
    MODEL = XRayModel

    def __init__(self, app):
        self.delay = STAGE_DELAY        # milliseconds on each stage of Play
        self._job = None                # Play's timer
        self._waiting = False           # the program waited for input at the last look
        self._stage = None              # the stage Play is on
        super().__init__(app)
        self.buttons += (self.play_button, self.speed_button)
        default_button(self.connect_button, self.buttons, self.typed)

    def build(self, body):
        field = sunken(ttk.Frame(body, style=SUNKEN_FRAME))
        field.pack(side="top")
        self.diagram = Diagram(field, self.app)
        self.diagram.canvas.pack()
        line = ttk.Frame(body)
        line.pack(side="top", fill="x", pady=(px(body, 5), 0))
        self.play_button = ttk.Button(line, text="Play", command=self.play)
        self.play_button.pack(side="left")
        self.speed_button = ttk.Button(line, text="Speed...", command=self.choose_speed)
        self.speed_button.pack(side="left", padx=(px(body, 5), 0))
        self.tips_of_play = (
            Tooltip(self.play_button, "Walk through the stages of the instruction shown"),
            Tooltip(self.speed_button, "Choose how long each stage stays on the screen"))

    # What it shows -----------------------------------------------------------------------

    def show(self):
        """Show the model's view, whole: this ends a Play."""
        self.stop_playing()
        view = self.model.view
        self.diagram.show(view.trace)
        self.diagram.write_info(*self._panel(view))
        playable = view.trace is not None and not view.trace.note
        self.play_button.state(["!disabled"] if playable else ["disabled"])

    def _panel(self, view):
        """The panel's heading, instruction line and body for a view."""
        model = self.model
        if view.kind == xray.NOTHING:
            if not model.connected:
                return "Click Connect to ARM to follow the program.", "", ""
            return ("Waiting for the program." if model.machine is not None
                    else "No program is loaded."), "", ""
        trace = view.trace
        if trace is None:
            return view.heading, "", ""
        instruction = trace.text
        if trace.note:
            lines = [trace.kind, trace.note]
            if trace.condition:
                lines.append(trace.condition)
            lines += self._did(view)
            return view.heading, instruction, "\n".join(lines)
        signals = trace.signals
        lines = [trace.kind, trace.condition,
                 "  ".join(f"{name} {signals[name]}" for name in INTERNAL[:4]),
                 "  ".join(f"{name} {signals[name]}" for name in INTERNAL[4:]),
                 f"Flags NZCV {xray.flag_text(trace.flags)} -> {xray.flag_text(trace.new_flags)}"]
        if trace.to_thumb:
            lines.append(xray.NOTE_TO_THUMB)
        return view.heading, instruction, "\n".join(lines)

    def _did(self, view):
        if view.kind == xray.FAILED:
            return []
        if view.kind != xray.EXECUTED:
            return ["It has not run yet."]
        if not view.did:
            return ["It changed no register and no memory."]
        lines = list(view.did[:DID_LINES])
        if len(view.did) > DID_LINES:
            lines.append(f"and {len(view.did) - DID_LINES} more")
        return lines

    # Called by the main window ----------------------------------------------------------

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
        if runner is None or (runner.state is State.RUNNING and app.run_speed is None):
            return
        waiting = runner.state is State.WAITING
        if waiting and not self._waiting and self._job is not None:
            self.show()                 # Step reached a read: the machine shows no change
        self._waiting = waiting
        self.model.stopped = runner.state is State.FINISHED
        super().refresh()

    # Play --------------------------------------------------------------------------------

    def play(self):
        """Start walking through the stages, or stop doing so."""
        if self._job is not None:
            self.show()
            return
        self._stage = -1
        self.play_button.configure(text="Stop")
        self._next_stage()

    def _next_stage(self):
        self._job = None
        self._stage += 1
        if self._stage >= len(xray.STAGES):
            self.show()
            return
        self.diagram.show(self.model.view.trace, self._stage)
        self._job = self.window.after(self.delay, self._next_stage)

    def stop_playing(self):
        if self._job is not None:
            self.window.after_cancel(self._job)
            self._job = None
        self._stage = None
        self.play_button.configure(text="Play")

    def choose_speed(self):
        AnimationDialog(self.window, self.delay, self._set_delay)

    def _set_delay(self, milliseconds):
        self.delay = milliseconds

    def close(self):
        if self.window is not None:
            self.stop_playing()
        super().close()


WINDOW = XRayWindow
