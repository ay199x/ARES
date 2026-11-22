# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The ARM X-Ray's picture: the datapath drawn on a canvas, and its film played there.

The datapath is the textbook's single-cycle ARM processor (credits.TEXTBOOK) with
the additions ARES needs, drawn with canvas shapes from the tables below, in
design pixels of the datapath's own area (its top left corner is ORIGIN on the
canvas). Each net of ares.xray_film has its polylines here, one or more for each
branch: a branch's polylines start at the net's source or on another of its
polylines, and the last one ends at the branch's input port with an arrowhead.
A value goes along a stretch that several branches share as far as a branch
that takes it, rejects it or finds its write closed leaves that stretch.

Picture.draw_film(film, moment) shows a film at any moment, the end included:
there is one way to draw, so the finished picture of an instruction is its film
at its end. The player of the window calls it again and again; only what
changed since the last call is drawn again.

The look is ares.gui.tools.xray_look's: a block the instruction does not use
stays pale, one it uses waits in a calm blue, lights while it works and keeps a
lighter tint when it is done; a value keeps its colour wherever it goes, lights
on a band of its colour as it travels and arrives, and then stays readable on a
tint of it, or on the green of a change when the instruction writes it.
"""

import math
import tkinter as tk
from tkinter import font as tkfont

from ... import xray_film
from ...xray_film import CLOSED, KINDS, MUXES, NETS, REJECTED, SIGNALS, TAKEN, WIDTHS
from ..style import WINDOW as FIELD
from ..widgets import scale
from . import xray_look as look
from .xray_look import DIM, DONE_FILL, UNUSED_FILL, WAITING_FILL, WORKING_FILL, WRITES

ORIGIN = (0, 22)                # where the datapath's area starts on the canvas, under the heading
SIZE = (1050, 432)              # the datapath's area

# The colours of the windows inside the blocks (ares.gui.tools.xray_inside) by the kinds of
# ares.xray_film.KINDS; the picture itself takes its colours from xray_look.
COLOURS = {
    "pc": "#8A5A00", "instr": "#4B0082", "cond": "#B0006A", "op": "#7B3FB5", "funct": "#A3542A",
    "rn": "#007A33", "rd": "#0047AB", "rm": "#007C80", "imm": "#C25400", "shamt": "#5F6B00",
    "rd1": "#2E7D00", "rd2": "#005F87", "alu": "#8B1A1A", "memory": "#4466FF",
    "result": "#CC4455", "flags": "#455A64", "constant": "#455A64",
}
LIT = "#FFF2B3"                 # a part at work in the windows inside the blocks
# The values' labels: a narrow fixed-width font where there is one, so that a 32-bit value fits a
# short wire; else the font of the code.
LABEL_FAMILIES = ("Consolas", "Menlo")
VALUE_SAMPLE = "0x00000000"     # the widest value a label shows, to choose its font's size
ON, OFF, IDLE, INK, MARK = look.ON, look.OFF, look.IDLE, look.INK, look.MARK
WIDTH_32, WIDTH_BUS, WIDTH_BIT = 3.2, 2.4, 1.6      # lines in use
IDLE_32, IDLE_BUS, IDLE_BIT = 1.6, 1.3, 1.0         # lines not in use
# How a block looks in each state: (fill, outline, outline width, colour of its names). With no
# instruction shown every block waits.
BLOCK_LOOKS = {
    "unused": (UNUSED_FILL, IDLE, 1.0, IDLE), "waiting": (WAITING_FILL, DIM, 1.0, INK),
    "working": (WORKING_FILL, INK, 1.8, INK), "done": (DONE_FILL, INK, 1.2, INK),
}

# Blocks -----------------------------------------------------------------------------------
# Multiplexers: name -> (left, right, top, bottom); their ports are in PORTS. RA1Mux and A3Mux
# have three inputs and two selects at their top: Mul (left) and RegSrc0 or Link (right). The A4
# multiplexer stands in front of A4, ShiftReg its select.
MUX_BOXES = {
    "PCMux": (16, 32, 190, 242), "RA1Mux": (326, 344, 165, 201), "RA2Mux": (326, 340, 218, 248),
    "A3Mux": (326, 344, 265, 301), "A4Mux": (352, 366, 298, 326), "WD3Mux": (359, 373, 325, 361),
    "ALUSrcMux": (662, 676, 216, 262), "StoreMux": (682, 696, 290, 322),
    "ResultMux": (1010, 1024, 212, 256), "AdrSrcMux": (838, 852, 204, 238),
}
BOXES = {                       # name -> (left, top, right, bottom)
    "PCReg": (84, 198, 100, 234), "IMem": (172, 176, 248, 262), "Control": (386, 12, 586, 140),
    "RegFile": (386, 160, 512, 370), "Shifter": (534, 214, 584, 252),
    "DMem": (866, 176, 936, 316), "System": (40, 16, 240, 136),
}
SHAPES = {                      # name -> the outline's points
    "Add4": ((172, 296), (196, 308), (196, 332), (172, 344), (172, 326), (178, 320), (172, 314)),
    "Add8": ((224, 344), (248, 356), (248, 372), (224, 384), (224, 370), (230, 364), (224, 358)),
    "ALU": ((748, 166), (794, 194), (794, 262), (748, 290), (748, 236), (758, 228), (748, 220)),
    "Extend": ((386, 396), (512, 390), (512, 422), (386, 422)),
}
CLOCKS = {"PCReg": (92, 234), "RegFile": (500, 370), "DMem": (926, 316)}    # a triangle, up
TITLES = {                      # block -> (x, y, text, anchor): its name, bold
    "PCReg": (92, 238, "PC", "n"), "IMem": (210, 238, "Instruction\nMemory", "center"),
    "Control": (490, 15, "Control Unit", "n"), "RegFile": (444, 207, "Register File", "center"),
    "Shifter": (559, 225, "Shifter", "center"), "DMem": (901, 285, "Data\nMemory", "center"),
    "ALU": (776, 228, "ALU", "center"), "Extend": (449, 400, "Extend", "center"),
    "Add4": (186, 320, "+", "center"), "Add8": (238, 364, "+", "center"),
    "System": (140, 20, "System (ARES)", "n"),
}
WORDS = {                       # block -> (x, y, anchor): where it says what it does
    "IMem": (210, 200, "center"), "Control": (486, 46, "center"),
    "RegFile": (449, 252, "center"), "Shifter": (559, 241, "center"), "DMem": (901, 260, "center"),
    "ALU": (774, 248, "n"), "Extend": (449, 413, "center"), "Add4": (184, 350, "n"),
    "Add8": (236, 388, "n"), "System": (140, 44, "n"),
}
WORD_WIDTHS = {"System": 186}   # a word that may need more than one line
# Input and output ports: "block.port" -> (x, y). Multiplexer inputs are "Mux.0", "Mux.1",
# the select "Mux.S", the output "Mux.Out".
PORTS = {
    "PCReg.D": (84, 216), "PCReg.Q": (100, 216), "IMem.A": (172, 216), "IMem.RD": (248, 216),
    "Add4.A": (172, 306), "Add4.B": (172, 334), "Add4.Out": (196, 320),
    "Add8.A": (224, 352), "Add8.Out": (248, 364),
    "Control.Cond": (386, 32.5), "Control.Op": (386, 42.5), "Control.Funct": (386, 55),
    "Control.Rd": (386, 65), "Control.Op2": (386, 75), "Control.Flags": (586, 126),
    "Control.ShiftC": (571, 140),
    "RegFile.A1": (386, 183), "RegFile.A2": (386, 233), "RegFile.A3": (386, 283),
    "RegFile.A4": (386, 312), "RegFile.WD3": (386, 343), "RegFile.R15": (386, 364),
    "RegFile.RD1": (512, 183), "RegFile.RD2": (512, 233), "RegFile.RD4": (512, 312),
    "RegFile.WE3": (438, 160), "RegFile.WE5": (406, 160), "RegFile.PassReg": (478, 160),
    "RegFile.WD5": (512, 352),
    "Extend.Imm": (386, 410), "Extend.ImmSrc": (512, 394), "Extend.Out": (512, 410),
    "Extend.Offset": (386, 398),
    "Shifter.In": (534, 233), "Shifter.Out": (584, 233), "Shifter.Shift": (547, 214),
    "Shifter.Shamt": (575, 252), "Shifter.Carry": (571, 214), "Shifter.RD4": (565, 252),
    "ALU.A": (748, 183), "ALU.B": (748, 242), "ALU.Result": (794, 228), "ALU.Control": (771, 180),
    "ALU.Flags": (758, 172), "ALU.RD4": (752, 287.6), "ALU.CarryIn": (752, 168.4),
    "DMem.A": (866, 221), "DMem.WD": (866, 305), "DMem.RD": (936, 222), "DMem.WE": (910, 176),
    "DMem.Size": (882, 176), "DMem.Signed": (896, 176),
    "PCMux.1": (16, 202), "PCMux.0": (16, 230), "PCMux.Out": (32, 216), "PCMux.S": (29, 198),
    "RA1Mux.0": (326, 173), "RA1Mux.1": (326, 183), "RA1Mux.2": (326, 193),
    "RA1Mux.Out": (344, 183), "RA1Mux.S": (341, 171), "RA1Mux.Mul": (329, 166.2),
    "RA2Mux.0": (326, 226), "RA2Mux.1": (326, 240), "RA2Mux.Out": (340, 233),
    "RA2Mux.S": (337, 223),
    "A3Mux.0": (326, 273), "A3Mux.1": (326, 283), "A3Mux.2": (326, 293), "A3Mux.Out": (344, 283),
    "A3Mux.S": (341, 271), "A3Mux.Mul": (329, 266.2),
    "A4Mux.0": (352, 306), "A4Mux.1": (352, 318), "A4Mux.Out": (366, 312), "A4Mux.S": (363, 303),
    "WD3Mux.1": (359, 334), "WD3Mux.0": (359, 352), "WD3Mux.Out": (373, 343),
    "WD3Mux.S": (370, 331),
    "ALUSrcMux.0": (662, 233), "ALUSrcMux.1": (662, 252), "ALUSrcMux.Out": (676, 242),
    "ALUSrcMux.S": (673, 223),
    "StoreMux.0": (682, 298), "StoreMux.1": (682, 312), "StoreMux.Out": (696, 305),
    "StoreMux.S": (693, 295),
    "ResultMux.1": (1010, 222), "ResultMux.0": (1010, 246), "ResultMux.Out": (1024, 234),
    "ResultMux.S": (1021, 219),
    "System.Call": (240, 20), "System.Number": (240, 120),
    "AdrSrcMux.1": (838, 212), "AdrSrcMux.0": (838, 228), "AdrSrcMux.Out": (852, 221),
    "AdrSrcMux.S": (849, 209),
    "PCReg.Hold": (84, 206),
    "Control.List": (440, 12), "Control.PassReg": (478, 140), "Control.Offset": (398, 140),
    "Control.Hold": (392, 140), "Control.AdrSrc": (560, 12), "Control.BaseWrite": (406, 140),
    "Control.RegSrc0": (386, 87.25), "Control.RegSrc1": (386, 99.5),
    "Control.ShiftReg": (386, 111.75), "Control.Link": (386, 124), "Control.Mul": (386, 134),
    "Control.CarryIn": (586, 113),
}
BUS = 270                       # the vertical line that carries Instr to every field
RESULT_Y = 428                  # the line that carries Result back
# Nets: name -> [(branch, polyline), ...]. Each polyline starts at the net's source port or on
# an earlier polyline of the net; the last polyline of a branch ends at its input port.
PATHS = {
    "PC": [("imem", [(100, 216), (172, 216)]), ("add4", [(150, 216), (150, 306), (172, 306)])],
    "Const4": [("add4", [(162, 334), (172, 334)])],
    "Instr": [("split", [(248, 216), (BUS, 216)]), ("split", [(BUS, 216), (BUS, 100), (BUS, 26)]),
              ("split", [(BUS, 216), (BUS, 300), (BUS, 414)])],
    "PCPlus4": [("pcmux", [(196, 320), (208, 320)]),
                ("pcmux", [(208, 320), (208, 388), (9, 388), (9, 230), (16, 230)]),
                ("add8", [(208, 320), (208, 352), (224, 352)]),
                ("wd3", [(208, 334), (359, 334)])],
    "PCPlus8": [("r15", [(248, 364), (386, 364)])],
    "Cond": [("control", [(BUS, 32.5), (386, 32.5)])],
    "Op": [("control", [(BUS, 42.5), (386, 42.5)])],
    "Funct": [("control", [(BUS, 55), (386, 55)])],
    "Op2": [("control", [(BUS, 75), (386, 75)])],
    "Rd": [("control", [(BUS, 65), (386, 65)]),
           ("ra2", [(BUS, 254), (301, 254), (301, 240), (326, 240)]),
           ("a3", [(301, 254), (301, 273), (326, 273)]),
           ("a4", [(301, 273), (301, 306), (352, 306)])],
    "Rn": [("ra1", [(BUS, 173), (326, 173)]), ("a3", [(BUS, 293), (326, 293)])],
    "Rm": [("ra2", [(BUS, 226), (326, 226)])],
    "Rs": [("ra1", [(BUS, 193), (326, 193)]), ("a4", [(BUS, 318), (352, 318)])],
    "Imm": [("extend", [(BUS, 410), (386, 410)])],
    "Shamt": [("shifter", [(BUS, 383), (575, 383), (575, 252)])],
    "Const15": [("ra1", [(318, 183), (326, 183)])],
    "Const14": [("a3", [(318, 283), (326, 283)])],
    "RA1": [("regfile", [(344, 183), (386, 183)])],
    "RA2": [("regfile", [(340, 233), (386, 233)])],
    "A3": [("regfile", [(344, 283), (386, 283)])],
    "A4": [("regfile", [(366, 312), (386, 312)])],
    "WD3": [("regfile", [(373, 343), (386, 343)])],
    "SrcA": [("alu", [(512, 183), (748, 183)]),
             ("adr", [(730, 183), (730, 140), (828, 140), (828, 212), (838, 212)])],
    "RD2": [("shifter", [(512, 233), (534, 233)]),
            ("store", [(530, 233), (530, 298), (682, 298)])],
    "RD4": [("store", [(512, 312), (682, 312)]),
            ("alu", [(670, 312), (670, 330), (752, 330), (752, 287.6)]),
            ("shifter", [(565, 312), (565, 252)])],
    "ExtImm": [("alusrc", [(512, 410), (646, 410), (646, 252), (662, 252)])],
    "Shifted": [("alusrc", [(584, 233), (662, 233)])],
    "ShiftC": [("control", [(571, 214), (571, 140)])],
    "SrcB": [("alu", [(676, 242), (748, 242)])],
    "ALUResult": [("result", [(794, 228), (820, 228)]),
                  ("result", [(820, 228), (820, 340), (994, 340), (994, 246), (1010, 246)]),
                  ("adr", [(820, 228), (838, 228)]),
                  ("wd5", [(820, 340), (820, 352), (512, 352)])],
    "Address": [("dmem", [(852, 221), (866, 221)])],
    "ALUFlags": [("control", [(758, 172), (758, 150), (640, 150), (640, 126), (586, 126)])],
    "WriteData": [("dmem", [(696, 305), (866, 305)])],
    "ReadData": [("result", [(936, 222), (1010, 222)])],
    "Result": [("pcmux", [(1024, 234), (1040, 234), (1040, RESULT_Y), (320, RESULT_Y)]),
               ("pcmux", [(320, RESULT_Y), (3, RESULT_Y), (3, 202), (16, 202)]),
               ("wd3", [(320, RESULT_Y), (320, 352), (359, 352)])],
    "PC'": [("pcreg", [(32, 216), (84, 216)])],
    # The control signals.
    "PCSrc": [("pcmux", [(396, 12), (396, 7), (29, 7), (29, 198)])],
    "MemtoReg": [("result", [(586, 22), (1021, 22), (1021, 219)])],
    # MemWrite, Signed and Size turn down to the data memory in that order, so that none crosses
    # another.
    "MemWrite": [("dmem", [(586, 35), (910, 35), (910, 176)])],
    "Signed": [("dmem", [(586, 48), (896, 48), (896, 176)])],
    "Size": [("dmem", [(586, 61), (882, 61), (882, 176)])],
    "ALUControl": [("alu", [(586, 74), (771, 74), (771, 180)])],
    "StoreSrc": [("store", [(586, 87), (658, 87), (658, 275), (693, 275), (693, 295)])],
    "ALUSrc": [("alusrc", [(586, 100), (673, 100), (673, 223)])],
    "Shift": [("shifter", [(482, 140), (482, 143), (547, 143), (547, 214)])],
    "ImmSrc": [("extend", [(520, 140), (520, 394), (512, 394)])],
    "RegWrite": [("regfile", [(438, 140), (438, 160)])],
    "RegSrc0": [("ra1", [(386, 87.25), (341, 87.25), (341, 171)])],
    "RegSrc1": [("ra2", [(386, 99.5), (349, 99.5), (349, 212), (337, 212), (337, 223)])],
    "ShiftReg": [("a4", [(386, 111.75), (363, 111.75), (363, 303)])],
    "Link": [("wd3", [(386, 124), (370, 124), (370, 331)]),
             ("a3", [(370, 258), (341, 258), (341, 271)])],
    "Mul": [("ra1", [(386, 134), (329, 134), (329, 166.2)]),
            ("a3", [(356, 134), (356, 250), (329, 250), (329, 266.2)])],
    "AdrSrc": [("adr", [(560, 12), (560, 4), (849, 4), (849, 209)])],
    "BaseWrite": [("regfile", [(406, 140), (406, 160)])],
    "Hold": [("pcreg", [(392, 140), (392, 144), (36, 144), (36, 206), (84, 206)])],
    # The system call.
    "SvcNum": [("system", [(BUS, 120), (240, 120)])],
    "Syscall": [("system", [(386, 20), (240, 20)])],
    # The pass counter of LDM, STM, PUSH and POP.
    "List": [("control", [(BUS, 26), (BUS, 3.5), (440, 3.5), (440, 12)])],
    "PassReg": [("regfile", [(478, 140), (478, 160)])],
    "Offset": [("extend", [(398, 140), (398, 148), (255, 148), (255, 398), (386, 398)])],
    # ADC, SBC and RSC: the C flag from the flags register into the adder.
    "CarryIn": [("alu", [(586, 113), (752, 113), (752, 168.4)])],
}
# Where a value stays once it has arrived: beside the input of the block that takes it, one
# place for each branch: net -> {branch: (x, y, anchor)}. A branch not here keeps no value: the
# value of RD2 stays at the register file's output, where the short wire to the shifter leaves
# no room; Result shows its value as PC' and as WD3 just after its multiplexers,
# PCPlus4's way to the second adder as that adder's PCPlus8 at R15, and the ways of Rd and Rn
# to the A3 multiplexer, wedged between Instr's line, Rd's and the constant 14, as A3 at the
# register file. The five inputs of the control unit keep their values in two columns: the
# inputs come closer than a value's box is high, so that the names down the control unit's left
# edge have room.
# The address rests inside the data memory, under A, as the register file's inputs rest inside
# it; ALUResult's way to the AdrSrc multiplexer shows its value there too. The register list
# and the pass counter's offset show in the sentence, and Offset as ExtImm after Extend.
REST = {
    "PC": {"imem": (164, 207, "se"), "add4": (164, 304, "se")},
    "Instr": {"split": (210, 170, "s")},
    "PCPlus4": {"pcmux": (12, 242, "nw"), "wd3": (347, 336, "ne")},
    "PCPlus8": {"r15": (412, 362, "w")},
    "Cond": {"control": (347, 32.5, "e")},
    "Op": {"control": (378, 42.5, "e")},
    "Funct": {"control": (347, 55, "e")},
    "Op2": {"control": (347, 75, "e")},
    "Rd": {"control": (378, 65, "e"), "ra2": (314, 242, "ne")},
    "Rn": {"ra1": (311, 171, "se")},
    "Rm": {"ra2": (314, 224, "se")},
    "Rs": {"ra1": (315, 196.5, "ne")},
    "Imm": {"extend": (382, 412, "ne")},
    "Shamt": {"shifter": (578, 260, "nw")},
    "RA1": {"regfile": (406, 183, "w")},
    "RA2": {"regfile": (406, 233, "w")},
    "SrcA": {"alu": (740, 181, "se")},
    "PassReg": {"regfile": (485, 152, "w")},
    "RD2": {"shifter": (508, 233, "e"), "store": (640, 296, "se")},
    "RD4": {"store": (640, 314, "ne"), "alu": (754, 302, "sw"), "shifter": (508, 312, "e")},
    "ExtImm": {"alusrc": (650, 250, "se")},
    "Shifted": {"alusrc": (650, 231, "se")},
    "ShiftC": {"control": (568, 144, "ne")},
    "SrcB": {"alu": (740, 233, "se")},
    "ALUResult": {"result": (1004, 252, "ne"), "wd5": (579, 350, "sw")},
    "Address": {"dmem": (870, 234, "nw")},      # inside the data memory, under its A
    "ALUFlags": {"control": (594, 129, "nw")},
    "WriteData": {"dmem": (816, 307, "ne")},
    "ReadData": {"result": (1004, 213, "se")},
    "A3": {"regfile": (406, 283, "w")},
    "A4": {"regfile": (406, 312, "w")},
    "WD3": {"regfile": (418, 343, "w")},
    "CarryIn": {"alu": (749, 165, "se")},
    "PC'": {"pcreg": (76, 192, "s")},
    "SvcNum": {"system": (236, 116, "se")},
}
# The names written before a resting value where no name stands near it.
REST_NAMES = {"Rn": "Rn ", "Rm": "Rm ", "Instr": "Instr "}
# The control signals' values, beside the input of the block or multiplexer they steer.
SIGNAL_REST = {
    "PCSrc": {"pcmux": (26, 186, "se")},
    "MemtoReg": {"result": (1018, 207, "se")},
    "MemWrite": {"dmem": (907, 168, "se")},
    "Size": {"dmem": (879, 168, "se")},
    "Signed": {"dmem": (893, 168, "se")},
    "ALUControl": {"alu": (774, 172, "sw")},
    "ALUSrc": {"alusrc": (670, 211, "se")},
    "Shift": {"shifter": (544, 206, "se")},
    "StoreSrc": {"store": (690, 283, "se")},
    "ImmSrc": {"extend": (523, 386, "nw")},
    "RegWrite": {"regfile": (435, 151, "e")},
    "RegSrc0": {"ra1": (340, 163, "se")},
    "RegSrc1": {"ra2": (335.5, 216, "se")},
    "Link": {"a3": (340, 265, "se"), "wd3": (372, 329, "sw")},
    "Syscall": {"system": (248, 22, "nw")},
    "AdrSrc": {"adr": (846, 201, "se")},
    "BaseWrite": {"regfile": (409, 151, "w")},
    "Hold": {"pcreg": (80, 204, "se")},
    "Mul": {"ra1": (328, 163, "se"), "a3": (328, 263, "se")},
    "ShiftReg": {"a4": (361, 297, "se")},
}
SIGNAL_NAMES = {                # signal -> (x, y, anchor): its name inside the control unit
    "MemtoReg": (582, 22, "e"), "MemWrite": (582, 35, "e"), "Signed": (582, 48, "e"),
    "Size": (582, 61, "e"), "ALUControl": (582, 74, "e"), "StoreSrc": (582, 87, "e"),
    "ALUSrc": (582, 100, "e"),
    "Shift": (482, 137, "s"), "ImmSrc": (520, 137, "s"),
    "RegWrite": (438, 137, "s"), "RegSrc0": (390, 87.25, "w"), "RegSrc1": (390, 99.5, "w"),
    "ShiftReg": (390, 111.75, "w"), "Link": (390, 124, "w"), "Syscall": (390, 20, "w"),
    "Mul": (390, 134, "w"), "CarryIn": (582, 113, "e"),
}
INPUT_NAMES = {                 # the control unit's inputs: (x, y, text, anchor)
    "Cond": (390, 32.5, "Cond", "w"), "Op": (390, 42.5, "Op", "w"),
    "Funct": (390, 55, "Funct", "w"), "Rd": (390, 65, "Rd", "w"), "Op2": (390, 75, "Op2", "w"),
    "Flags": (582, 126, "Flags", "e"),
    "List": (440, 15, "List", "n"),
}
CONDITION = (486, 57)           # the condition check, inside the control unit
CONDITION_WIDTH = 100
PASS_WORD = (486, 93)           # the pass counter of LDM, STM, PUSH and POP: "pass 2 of 4"
FLAG_WORD = (486, 108)          # whether the flags are written, under them
GATE_WORDS = {"RegFile": (441, 158, "sw"), "DMem": (914, 172, "sw")}  # "open" or "closed"
LONG = 120                      # a wire segment this long has an arrowhead halfway too
# The slash across each bus of more than one bit, and its width: net -> (x, y) of the slash's
# middle on the wire; the width stands below a horizontal wire, right of a vertical one.
BUS_MARKS = {
    "PC": (108, 216), "PC'": (40, 216), "Instr": (270, 128), "PCPlus4": (232, 334),
    "PCPlus8": (300, 364), "RA1": (377, 183), "RA2": (377, 233), "A3": (377, 283),
    "SrcA": (620, 183), "RD2": (538, 298), "RD4": (538, 312), "ExtImm": (588, 410),
    "SrcB": (690, 242), "ALUResult": (802, 228), "ALUFlags": (758, 160),
    "WriteData": (840, 305), "ReadData": (940, 222), "Result": (980, 428),
    "ALUControl": (771, 150), "ImmSrc": (520, 160), "Offset": (296, 398), "Size": (800, 61),
}
# The fields of the word have none: their bits are in the instruction table and in their tips;
# a stub too short for a slash (Shifted, WD3) has none. The width stands above these wires, below
# the others.
NUMBERS_ABOVE = {"RD2", "Result", "Offset"}
PORT_NAMES = {                  # the names written inside the blocks at their ports
    "IMem": ((176, 216, "A", "w"), (244, 216, "RD", "e")),
    "RegFile": ((390, 183, "A1", "w"), (390, 233, "A2", "w"), (390, 283, "A3", "w"),
                (390, 312, "A4", "w"), (390, 343, "WD3", "w"), (390, 364, "R15", "w"),
                (508, 200, "RD1", "e"), (508, 220, "RD2", "e"), (508, 299, "RD4", "e"),
                (446, 163, "WE3", "nw"), (390, 163, "BaseWrite", "nw"),
                (508, 177, "PassReg", "ne"), (508, 352, "WD5", "e")),
    # Signed stands under Size and WE at the data memory's top: the three do not fit side by side.
    "DMem": ((870, 221, "A", "w"), (870, 305, "WD", "w"), (932, 222, "RD", "e"),
             (910, 182, "WE", "n"), (882, 182, "Size", "n"), (896, 194, "Signed", "n")),
}
CONSTANTS = ((160, 334, "4", "Const4", "e"), (220, 372, "4", "static", "s"),
             (315, 183, "15", "Const15", "e"), (315, 283, "14", "Const14", "e"))
STATIC_LINES = ([(216, 376), (224, 376)],)  # Add8's second input, 4: always the same
NAMES_ON_WIRES = {              # the names of nets, written beside them: net -> (x, y, anchor)
    "PC'": (80, 220, "ne"), "PC": (166, 220, "ne"),
    "PCPlus4": (100, 391, "nw"), "PCPlus8": (324, 367, "nw"), "SrcA": (586, 187, "nw"),
    "SrcB": (708, 246, "nw"), "ExtImm": (516, 414, "nw"), "ALUResult": (830, 344, "nw"),
    "ReadData": (1008, 226, "ne"), "WriteData": (698.5, 308, "nw"), "Result": (1036, 300, "e"),
    "ShiftC": (575, 168, "w"), "PCSrc": (362, 8, "n"), "Hold": (40, 170, "w"),
    "AdrSrc": (700, 6, "n"), "Offset": (251, 290, "e"), "RD4": (749, 297, "e"),
    "RD4 shifter": (562, 268, "e"),
}
# A net named twice: the key of its second name in NAMES_ON_WIRES, and the net.
NAME_NETS = {"RD4 shifter": "RD4"}


def points(size, zoom):
    """The size in points of a font that has size points at zoom 1, at zoom: in proportion, never
    larger than that, as the pictures are laid out for their texts at zoom 1, and never under 8."""
    return max(8, int(size * zoom + 1e-6))


def fitted_zoom(room, design, k, current):
    """The zoom at which a picture design pixels large, k screen pixels each at zoom 1, fills room
    (width, height in screen pixels) in proportion: in steps of 0.01, never under 1, where its
    smallest text has 8 points; current while room holds it but not the next step. None while
    room has no size yet."""
    width, height = room
    if width <= 1 or height <= 1:
        return None

    def fits(zoom):                     # sized as the windows size their canvases
        return round(design[0] * (k * zoom)) <= width and round(design[1] * (k * zoom)) <= height
    if fits(current) and not fits(current + 0.01):
        return current
    zoom = max(1.0, math.floor(min(width / (design[0] * k), height / (design[1] * k)) * 100
                               + 1e-6) / 100)
    while zoom > 1.0 and not fits(zoom):
        zoom = round(zoom - 0.01, 2)
    return zoom


def values_font(widget, family, zoom):
    """The font of the values' labels at zoom: the largest size up to points(8, zoom) whose
    labels are no wider, in proportion, than at zoom 1, so that a value that fits its place at
    zoom 1 fits it at every zoom (a fixed-width font's letters are whole pixels wide, and the
    next size can round them up)."""
    least = tkfont.Font(root=widget, family=family, size=points(8, 1))
    room = least.measure(VALUE_SAMPLE) * zoom
    for size in range(points(8, zoom), 8, -1):
        font = tkfont.Font(root=widget, family=family, size=size)
        if font.measure(VALUE_SAMPLE) <= room:
            return font
    return least


_families = []                  # the font families installed, once asked


def families(widget):
    """The font families installed on the system, asked of Tk once."""
    if not _families:
        _families.append(frozenset(tkfont.families(widget)))
    return _families[0]


def lengths():
    """Each net's longest branch, from its source, in design pixels (for ares.xray_film)."""
    return {name: max(_branch_lengths(name).values()) for name in PATHS}


def _length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def _offsets(name):
    """For each polyline of a net, how far from the net's source its first point is."""
    polylines = PATHS[name]
    offsets = []
    for index, (branch, points) in enumerate(polylines):
        start = 0.0
        for (other_branch, other), offset in zip(polylines[:index], offsets):
            along = _along(other, points[0])
            if along is not None:
                start = offset + along
                break
        offsets.append(start)
    return offsets


def _junctions(name):
    """For each polyline of a net, the branches that a value takes through it to a later
    polyline that starts on it, with how far along it that later polyline starts: [(branch,
    cut)]. A stretch that several branches share shows a value that only a later branch takes
    (for example ALUResult's way to the base write port), as far as that branch leaves it."""
    polylines = PATHS[name]
    parents = []
    for index, (branch, points) in enumerate(polylines):
        parent = None
        for other in range(index):
            along = _along(polylines[other][1], points[0])
            if along is not None:
                parent = (other, along)
                break
        parents.append(parent)

    def through(index):
        """The branches whose way goes through polyline index (its own and its later ones')."""
        found = {polylines[index][0]}
        for child, parent in enumerate(parents):
            if parent is not None and parent[0] == index:
                found |= through(child)
        return found
    junctions = [[] for _ in polylines]
    for child, parent in enumerate(parents):
        if parent is not None:
            index, along = parent
            junctions[index] += [(branch, along) for branch in sorted(through(child))]
    return junctions


def _along(points, point):
    """How far along a polyline point lies, or None when it is not on it."""
    travelled = 0.0
    for a, b in zip(points, points[1:]):
        if _on_segment(a, b, point):
            return travelled + math.dist(a, point)
        travelled += math.dist(a, b)
    return None


def _on_segment(a, b, p):
    (x1, y1), (x2, y2), (x, y) = a, b, p
    if min(x1, x2) - 0.01 <= x <= max(x1, x2) + 0.01 and min(y1, y2) - 0.01 <= y <= max(y1, y2) + 0.01:
        return abs((x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)) < 0.01
    return False


def _branch_lengths(name):
    """For each branch of a net, how far its end is from the net's source."""
    ends = {}
    for (branch, points), offset in zip(PATHS[name], _offsets(name)):
        ends[branch] = max(ends.get(branch, 0.0), offset + _length(points))
    return ends


def cut(points, distance):
    """The first distance pixels of a polyline (at least its first point)."""
    out = [points[0]]
    left = distance
    for a, b in zip(points, points[1:]):
        step = math.dist(a, b)
        if left >= step:
            out.append(b)
            left -= step
            continue
        if left > 0:
            t = left / step
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        break
    return out


def bits_of(name):
    """How many bits a net carries: control signals one unless WIDTHS says more."""
    return WIDTHS.get(name, 1 if name in SIGNALS else 32)


def width_of(name, active):
    bits = bits_of(name)
    if bits == 32:
        return WIDTH_32 if active else IDLE_32
    return (WIDTH_BUS if active else IDLE_BUS) if bits > 1 else (WIDTH_BIT if active else IDLE_BIT)


def colour_of(name, value=None):
    """A net's colour in the windows inside the blocks: its kind's (COLOURS), or for a control
    signal red for 1, gray for 0 or X."""
    kind = KINDS.get(name, "constant")
    if kind == "control":
        if value is None or "X" in value or "1" not in value:
            return OFF
        return ON
    return COLOURS[kind]


def used_blocks(film):
    """The blocks that work in film (a pass of an LDM, STM, PUSH or POP): those that light, and
    the multiplexers that decide."""
    used = set()
    for step in film.steps:
        used |= {block for block, _ in step.lights}
        used |= {decision.mux for decision in step.decisions}
    return used


class Picture:
    """The datapath on a canvas, at zoom times the design size, and a film drawn on it."""

    def __init__(self, canvas, zoom, code_family, text_family):
        self.canvas = canvas
        self.k = scale(canvas) * zoom           # screen pixels per design pixel
        self.zoom = zoom
        size = points(8, zoom)
        installed = families(canvas)
        labels = next((family for family in LABEL_FAMILIES if family in installed), code_family)
        self.small = tkfont.Font(root=canvas, family=text_family, size=size)
        self.bold = tkfont.Font(root=canvas, family=text_family, size=size, weight="bold")
        self.code = tkfont.Font(root=canvas, family=labels, size=size)
        self.code_bold = tkfont.Font(root=canvas, family=labels, size=size, weight="bold")
        self.values = values_font(canvas, labels, zoom)
        self.items = {}                 # (net, polyline index) -> overlay line
        self.labels = {}                # (net, branch) -> (box, text) travelling labels
        self.rests = {}                 # (net, branch or None) -> (box, text) resting labels
        self.blocks = {}                # block -> outline item
        self.clocks = {}                # block -> the triangle of its clock input
        self.states = {}                # block -> how it looks now (BLOCK_LOOKS)
        self.words = {}                 # block -> word item
        self.titles = {}                # block -> title items
        self.marks = {}                 # mux input port -> (dot, cross)
        self.gates = {}                 # block -> closed mark items
        self.signal_names = {}
        self.base = {}                  # net -> base line items
        self.trunks = {}                # (net, polyline index) -> thick line of a shared stretch
        self.parts = {}                 # (net, polyline index) -> [(slash or arrow item, along)]
        self.junctions = {name: _junctions(name) for name in PATHS}
        self.offsets = {name: _offsets(name) for name in PATHS}
        self.longest = {name: max(_branch_lengths(name).values()) for name in PATHS}
        self.sizes = {(name, index): _length(points) for name in PATHS
                      for index, (_, points) in enumerate(PATHS[name])}
        self.ends = {name: self._ends(name) for name in PATHS}
        self.drawn = None               # (film, steps finished, step playing, fraction)
        self.colours = look.net_colours(None)   # net -> its colour for the film drawn
        # (net, branch or None) -> [number of the step it arrived in, value, colour, changed,
        # its look now]: the values that rest, lit for that step and the next, then readable.
        self.resting = {}
        self.now = (0, True)            # (number of the step playing, the film has finished)
        self._draw()

    # Coordinates -----------------------------------------------------------------------------

    def xy(self, x, y):
        return (ORIGIN[0] + x) * self.k, (ORIGIN[1] + y) * self.k

    def flat(self, points):
        return [c for point in points for c in self.xy(*point)]

    def d(self, size):
        return max(1, size * self.k)

    def text(self, x, y, text, anchor="center", font=None, fill=IDLE, **options):
        return self.canvas.create_text(*self.xy(x, y), text=text, anchor=anchor,
                                       font=font or self.small, fill=fill, **options)

    # The picture without a film --------------------------------------------------------------

    def _draw(self):
        """The datapath with no instruction: every block waits, every wire is gray."""
        canvas = self.canvas
        fill, outline, width, names = BLOCK_LOOKS["waiting"]
        for name, (left, right, top, bottom) in MUX_BOXES.items():
            slope = (bottom - top) / 5
            points = [(left, top), (right, top + slope), (right, bottom - slope), (left, bottom)]
            self.blocks[name] = canvas.create_polygon(
                *self.flat(points), fill=fill, outline=outline, width=self.d(width),
                tags=("block", f"block:{name}"))
            select, inputs = MUXES[name]
            for number in range(len(inputs)):
                x, y = PORTS[f"{name}.{number}"]
                self.titles.setdefault(name, []).append(
                    self.text(x + 3, y, str(number), "w", fill=names, tags=(f"block:{name}",)))
        for name, (left, top, right, bottom) in BOXES.items():
            self.blocks[name] = canvas.create_rectangle(
                *self.flat(((left, top), (right, bottom))), fill=fill, outline=outline,
                width=self.d(width), tags=("block", f"block:{name}"))
        for name, points in SHAPES.items():
            self.blocks[name] = canvas.create_polygon(
                *self.flat(points), fill=fill, outline=outline, width=self.d(width),
                tags=("block", f"block:{name}"))
        for name, (x, y) in CLOCKS.items():
            self.clocks[name] = canvas.create_polygon(
                *self.flat(((x - 5, y), (x + 5, y), (x, y - 6))), fill=fill, outline=outline,
                width=self.d(1), tags=(f"block:{name}",))
        self.states = dict.fromkeys(self.blocks, "waiting")
        for name, (x, y, text, anchor) in TITLES.items():
            self.titles.setdefault(name, []).append(
                self.text(x, y, text, anchor, self.bold, names, justify="center",
                          tags=(f"block:{name}",)))
        for block, port_names in PORT_NAMES.items():
            for x, y, text, anchor in port_names:
                self.titles.setdefault(block, []).append(
                    self.text(x, y, text, anchor, fill=names, tags=(f"block:{block}",)))
        for name, (x, y, text, anchor) in INPUT_NAMES.items():
            self.titles.setdefault("Control", []).append(
                self.text(x, y, text, anchor, fill=names, tags=("block:Control",)))
        for name, (x, y, anchor) in SIGNAL_NAMES.items():
            self.signal_names[name] = self.text(x, y, name, anchor, fill=DIM,
                                                tags=("block:Control",))
        for x, y, text, net, anchor in CONSTANTS:
            self.text(x, y, text, anchor, fill=IDLE, tags=(f"wire:{net}",))
        for points in STATIC_LINES:
            canvas.create_line(*self.flat(points), fill=IDLE, width=self.d(IDLE_32),
                               arrow="last", arrowshape=self._arrow(False),
                               tags=("wire:static",))
        for name, (x, y, anchor) in NAMES_ON_WIRES.items():
            net = NAME_NETS.get(name, name)
            self.text(x, y, net, anchor, fill=IDLE, tags=(f"wire:{net}",))
        self._draw_wires()
        self._draw_dots()
        for name, (x, y, anchor) in WORDS.items():
            options = {"width": WORD_WIDTHS[name] * self.k} if name in WORD_WIDTHS else {}
            self.words[name] = self.text(x, y, "", anchor, self.bold, INK, justify="center",
                                         tags=(f"block:{name}",), **options)
        self.condition = self.text(*CONDITION, "", "n", fill=INK, justify="center",
                                   width=CONDITION_WIDTH * self.k, tags=("block:Control",))
        self.flag_word = self.text(*FLAG_WORD, "", "n", fill=INK, tags=("block:Control",))
        self.pass_word = self.text(*PASS_WORD, "", "n", fill=INK, tags=("block:Control",))
        self.gate_words = {block: self.text(x, y, "", anchor, fill=MARK, tags=(f"gate:{block}",))
                           for block, (x, y, anchor) in GATE_WORDS.items()}
        self._draw_marks()

    def _arrow(self, active):
        size = 7 if active else 6
        return (self.d(size), self.d(size), self.d(size * 0.42))

    def _draw_wires(self):
        canvas = self.canvas
        for name, polylines in PATHS.items():
            ends = self._ends(name)
            items = []
            for index, (branch, points) in enumerate(polylines):
                last = index in ends
                items.append(canvas.create_line(
                    *self.flat(points), fill=IDLE, width=self.d(width_of(name, False)),
                    capstyle="butt", joinstyle="miter", arrow="last" if last else "none",
                    arrowshape=self._arrow(False), tags=("wire", f"wire:{name}")))
            self.base[name] = items
            for index, (branch, points) in enumerate(polylines):
                self.items[(name, index)] = canvas.create_line(
                    *self.flat(points[:1] * 2), fill=IDLE, width=self.d(width_of(name, True)),
                    capstyle="butt", joinstyle="miter", state="hidden",
                    tags=("wire", f"wire:{name}"))
                if self.junctions[name][index]:     # a stretch that later branches share
                    self.trunks[(name, index)] = canvas.create_line(
                        *self.flat(points[:1] * 2), fill=IDLE,
                        width=self.d(width_of(name, True)), capstyle="butt",
                        joinstyle="miter", state="hidden", tags=("wire", f"wire:{name}"))
            for index in range(len(polylines)):
                self.labels[(name, index)] = self._label_items(name, moving=True)
            rest = REST.get(name)
            if isinstance(rest, dict):
                for branch in rest:
                    self.rests[(name, branch)] = self._label_items(name)
            elif rest is not None:
                self.rests[(name, None)] = self._label_items(name)
        for name in SIGNALS:
            rest = SIGNAL_REST.get(name)
            if isinstance(rest, dict):
                for branch in rest:
                    self.rests[(name, branch)] = self._label_items(name)
            else:
                self.rests[(name, None)] = self._label_items(name)
        self._draw_bus_marks()
        self._draw_mid_arrows()

    def _ends(self, name):
        """The indexes of the polylines of a net that end at an input port."""
        ends = set()
        polylines = PATHS[name]
        last = {}
        for index, (branch, points) in enumerate(polylines):
            last[branch] = index
        for index, (branch, points) in enumerate(polylines):
            if index == last[branch]:
                ends.add(index)
        return ends

    def _label_items(self, name, moving=False):
        """A label for a value of net name: a white box and its text, hidden until used; a
        moving label travels along the wire, the others stay where a value has arrived."""
        canvas = self.canvas
        tags = ("label", f"wire:{name}") + (("moving",) if moving else ())
        box = canvas.create_rectangle(0, 0, 0, 0, fill=FIELD, outline=IDLE, width=self.d(1),
                                      state="hidden", tags=tags)
        text = canvas.create_text(0, 0, text="", font=self.values, fill=INK, state="hidden",
                                  tags=tags)
        return box, text

    def _draw_dots(self):
        """A dot where a net's polyline leaves another one of it."""
        canvas = self.canvas
        reach = self.d(2)
        for name, polylines in PATHS.items():
            offsets = self.offsets[name]
            for index, ((branch, points), offset) in enumerate(zip(polylines, offsets)):
                if index == 0 or offset == 0 or name == "Instr":
                    continue
                x, y = self.xy(*points[0])
                canvas.create_oval(x - reach, y - reach, x + reach, y + reach, fill=IDLE,
                                   outline=IDLE, tags=(f"dot:{name}",))

    def _draw_bus_marks(self):
        """A slash with the width across each bus of more than one bit, on its first line."""
        canvas = self.canvas
        for name, (mx, my) in BUS_MARKS.items():
            horizontal = any(_on_segment(a, b, (mx, my)) and a[1] == b[1]
                             for _, points in PATHS[name] for a, b in zip(points, points[1:]))
            index = next(number for number, (_, points) in enumerate(PATHS[name])
                         if any(_on_segment(a, b, (mx, my)) for a, b in zip(points, points[1:])))
            part = f"part:{name}/{index}"
            along = _along(PATHS[name][index][1], (mx, my))
            items = [canvas.create_line(*self.flat(((mx - 3, my + 4), (mx + 3, my - 4))),
                                        fill=IDLE, width=self.d(1),
                                        tags=("slash", f"slash:{name}", part))]
            if horizontal and name in NUMBERS_ABOVE:
                items.append(self.text(mx + 2, my - 3, str(bits_of(name)), "sw", fill=IDLE,
                                       tags=("slash", f"slash:{name}", part)))
            elif horizontal:
                items.append(self.text(mx + 2, my + 3, str(bits_of(name)), "nw", fill=IDLE,
                                       tags=("slash", f"slash:{name}", part)))
            else:
                items.append(self.text(mx + 5, my, str(bits_of(name)), "w", fill=IDLE,
                                       tags=("slash", f"slash:{name}", part)))
            self.parts.setdefault((name, index), []).extend((item, along) for item in items)

    def _draw_mid_arrows(self):
        """An arrowhead halfway along each long segment, pointing the way the value goes."""
        canvas = self.canvas
        for name, polylines in PATHS.items():
            for index, (_, points) in enumerate(polylines):
                travelled = 0.0
                for (x1, y1), (x2, y2) in zip(points, points[1:]):
                    length = math.dist((x1, y1), (x2, y2))
                    travelled += length
                    if length < LONG:
                        continue
                    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                    dx, dy = (x2 - x1) / length * 4, (y2 - y1) / length * 4
                    item = canvas.create_line(*self.flat(((mx - dx, my - dy), (mx + dx, my + dy))),
                                              fill=IDLE, width=self.d(width_of(name, False)),
                                              arrow="last", arrowshape=self._arrow(False),
                                              tags=("mid", f"mid:{name}", f"wire:{name}",
                                                    f"part:{name}/{index}"))
                    self.parts.setdefault((name, index), []).append(
                        (item, travelled - length / 2))

    def _draw_marks(self):
        canvas = self.canvas
        reach = self.d(2.2)
        for mux, (select, inputs) in MUXES.items():
            for number in range(len(inputs)):
                x, y = self.xy(*PORTS[f"{mux}.{number}"])
                dot = canvas.create_oval(x - reach, y - reach, x + reach, y + reach, fill=INK,
                                         outline=INK, state="hidden")
                arm = self.d(3)
                cx = x - self.d(6)
                cross = (canvas.create_line(cx - arm, y - arm, cx + arm, y + arm, fill=MARK,
                                            width=self.d(1.6), state="hidden"),
                         canvas.create_line(cx - arm, y + arm, cx + arm, y - arm, fill=MARK,
                                            width=self.d(1.6), state="hidden"))
                self.marks[f"{mux}.{number}"] = (dot, cross)
        for block, port in (("RegFile", "RegFile.WD3"), ("DMem", "DMem.WD"),
                            ("Control", "Control.Flags"), ("Base", "RegFile.WD5"),
                            ("PCReg", "PCReg.D")):
            x, y = self.xy(*PORTS[port])
            arm = self.d(5)
            if block in ("Control", "Base"):    # the port is on the block's right side
                bar = canvas.create_line(x + self.d(3), y - arm, x + self.d(3), y + arm,
                                         fill=MARK, width=self.d(2.4), state="hidden")
            else:
                bar = canvas.create_line(x - self.d(3), y - arm, x - self.d(3), y + arm,
                                         fill=MARK, width=self.d(2.4), state="hidden")
            self.gates[block] = bar

    # Drawing a film ------------------------------------------------------------------------

    def clear(self, resting=True):
        """Nothing travels: with no instruction (resting) every block waits; for an instruction
        outside the datapath everything stays pale and gray."""
        self.drawn = None
        self.colours = look.net_colours(None)
        self.resting = {}
        canvas = self.canvas
        for item in list(self.items.values()) + list(self.trunks.values()):
            canvas.itemconfigure(item, state="hidden")
        for box, text in list(self.labels.values()) + list(self.rests.values()):
            canvas.itemconfigure(box, state="hidden")
            canvas.itemconfigure(text, state="hidden")
        state = "waiting" if resting else "unused"
        for name in self.blocks:
            self._paint(name, state)
        for item in self.words.values():
            canvas.itemconfigure(item, text="")
        for item in self.signal_names.values():
            canvas.itemconfigure(item, fill=DIM if resting else IDLE)
        for dot, cross in self.marks.values():
            canvas.itemconfigure(dot, state="hidden")
            for line in cross:
                canvas.itemconfigure(line, state="hidden")
        for bar in self.gates.values():
            canvas.itemconfigure(bar, state="hidden")
        for item in self.gate_words.values():
            canvas.itemconfigure(item, text="")
        canvas.itemconfigure(self.flag_word, text="")
        canvas.itemconfigure("mid", fill=IDLE)
        for name, items in self.base.items():
            for item in items:
                canvas.itemconfigure(item, fill=IDLE, dash="")
        canvas.itemconfigure("slash", fill=IDLE)
        canvas.itemconfigure(self.condition, text="")
        canvas.itemconfigure(self.pass_word, text="")

    def draw_film(self, film, moment, inclusive=False):
        """Show film as it is at moment (seconds from its start); after its end, finished.
        With inclusive, a moment where a step ends shows that step ended (Film.at).

        Steps already drawn by the last call stay as they are, so playing a film
        draws each step's moves again only while they travel.
        """
        number, fraction = film.at(moment, inclusive)
        drawn = self.drawn
        if drawn is None or drawn[0] is not film or drawn[1] > number:
            self._start(film)
            done = 0
        else:
            done = drawn[1]
        self.now = (number, number >= len(film.steps))
        for index in range(done, min(number, len(film.steps))):
            self._step(film.steps[index], index, 1.0, playing=False)
        if number < len(film.steps):
            self._step(film.steps[number], number, fraction, playing=True)
        self._settle(number, number >= len(film.steps))
        self.drawn = (film, number, number if number < len(film.steps) else None, fraction)

    def _start(self, film):
        """Before film's first step: the blocks it uses wait, the others stay pale; its colours
        are worked out (xray_look.net_colours())."""
        self.clear(resting=False)
        self.colours = look.net_colours(film.trace)
        used = used_blocks(film)
        for name in self.blocks:
            if name in used:
                self._paint(name, "waiting")
        if "Control" in used:
            for item in self.signal_names.values():
                self.canvas.itemconfigure(item, fill=DIM)
        self._dash_unused_x(film)

    def _paint(self, block, state):
        """Give block the look of state (BLOCK_LOOKS), its clock and its names with it."""
        if self.states.get(block) == state:
            return                      # a picture of the same step: nothing changes
        canvas = self.canvas
        fill, outline, width, names = BLOCK_LOOKS[state]
        self.states[block] = state
        canvas.itemconfigure(self.blocks[block], fill=fill, outline=outline, width=self.d(width))
        if block in self.clocks:
            canvas.itemconfigure(self.clocks[block], fill=fill, outline=outline)
        for item in self.titles.get(block, ()):
            canvas.itemconfigure(item, fill=names)

    def _dash_unused_x(self, film):
        """A control signal that is X steers only gray parts and does not travel: its gray wire
        stays dashed, as X is drawn."""
        trace = getattr(film, "trace", None)
        if trace is None or not trace.signals:
            return
        used = set(film.used())
        for net in xray_film.SIGNALS:
            if net in used or "X" not in xray_film.signal_value(trace, net):
                continue
            for item in self.base.get(net, ()):
                self.canvas.itemconfigure(item, dash=(4, 3))

    def _step(self, step, number, fraction, playing):
        """Draw step number of the film, fraction of the way: its blocks light while it plays
        (playing, fraction under 1) and keep a lighter tint once it is done."""
        canvas = self.canvas
        state = "working" if playing and fraction < 1 else "done"
        for block, word in step.lights:
            if block in self.blocks:
                self._paint(block, state)
            if block in self.words:
                canvas.itemconfigure(self.words[block], text=word)
        longest = max((self.longest[move.net] for move in step.moves), default=0.0)
        head = longest * fraction
        for move in step.moves:
            self._move(move, head, fraction >= 1, number)
        if step.moves and playing:      # a travelling value passes over the arrowheads, but
            canvas.tag_raise("moving")  # not over the heading and the line beside it (a register
            canvas.tag_raise("over")    # list and AdrSrc travel just under them)
        for decision in step.decisions:
            self._decide(decision, state)
        for gate in step.gates:
            self._gate(gate)

    def _move(self, move, head, arrived, number):
        """Draw a net's value head pixels from its source: each polyline grows as far as
        the head has come, with the value's label at its tip (at a junction the label goes
        down every branch); a branch whose value has arrived shows it where it stays."""
        canvas = self.canvas
        name = move.net
        outcomes = dict(move.outcomes)
        value = move.text
        colour = look.signal_colour(value) if name in SIGNALS else \
            self.colours.get(name, look.VALUES["constant"])
        dashed = name in SIGNALS and "X" in value
        ends = self.ends[name]
        finished = {}                   # branch -> its value has arrived at its end
        passed = []                     # (polyline, how far) the value has gone all along
        for index, ((branch, points), offset) in enumerate(zip(PATHS[name],
                                                                 self.offsets[name])):
            outcome = outcomes.get(branch)
            item = self.items[(name, index)]
            trunk = self.trunks.get((name, index))
            box, text = self.labels[(name, index)]
            size = self.sizes[(name, index)]
            later = [(along, outcomes[other]) for other, along in self.junctions[name][index]
                     if outcomes.get(other) is not None]
            # How far the value goes along this polyline: all of it for its own branch, else as
            # far as the farthest later branch that it reaches leaves it.
            limit = size if outcome is not None else max((a for a, _ in later), default=0.0)
            reach = min(head - offset, limit) if limit > 0 else 0.0
            if index in ends and outcome is not None:
                finished[branch] = head - offset >= size
            if reach <= 0:
                for hidden in (item, trunk, box, text):
                    if hidden is not None:
                        canvas.itemconfigure(hidden, state="hidden")
                continue
            part = cut(points, reach)
            if len(part) < 2:
                part = part * 2
            width = width_of(name, True)
            thin = outcome is None or (outcome != TAKEN and index in ends)
            canvas.coords(item, *self.flat(part))
            canvas.itemconfigure(item, state="normal", fill=colour,
                                 width=self.d(max(width * 0.6, WIDTH_BIT) if thin else width),
                                 dash=(4, 3) if dashed else "",
                                 arrow="last" if (index in ends and outcome is not None)
                                 or reach < limit else "none",
                                 arrowshape=self._arrow(True))
            # The stretch to a later branch that takes the value is thick, also where this
            # polyline's own end is thin (rejected, closed) or not reached.
            taken = max((a for a, o in later if o == TAKEN), default=0.0)
            if trunk is not None and thin and taken > 0:
                piece = cut(points, min(head - offset, taken))
                canvas.coords(trunk, *self.flat(piece if len(piece) > 1 else piece * 2))
                canvas.itemconfigure(trunk, state="normal", fill=colour, width=self.d(width),
                                     dash=(4, 3) if dashed else "")
            elif trunk is not None:
                canvas.itemconfigure(trunk, state="hidden")
            if arrived or reach >= limit:
                passed.append((index, limit))
                canvas.itemconfigure(box, state="hidden")
                canvas.itemconfigure(text, state="hidden")
            else:
                self._place(box, text, part[-1], "center", value, colour)
        self._rest(move, colour, finished, number)
        for index, limit in passed:     # its slashes and arrowheads, as far as the value went
            for mark, along in self.parts.get((name, index), ()):
                if along <= limit + 0.01:
                    canvas.itemconfigure(mark, fill=colour)
            canvas.tag_raise(f"mid:{name}")
            if name in self.signal_names:
                canvas.itemconfigure(self.signal_names[name], fill=INK)

    def _rest(self, move, colour, finished, number):
        """A value stays where its wire ends once it has arrived there (REST), in step number;
        what the instruction writes (xray_look.WRITES, an open write) is a change."""
        name = move.net
        rest = REST.get(name) if name not in SIGNALS else SIGNAL_REST.get(name)
        if rest is None or not finished:
            return
        outcomes = dict(move.outcomes)
        if isinstance(rest, dict):
            places = [(branch, point, move.text) for branch, point in rest.items()
                      if finished.get(branch)]
        elif all(finished.values()):
            places = [(None, rest, REST_NAMES.get(name, "") + move.text)]
        else:
            places = []
        for branch, (x, y, anchor), value in places:
            key = (name, branch)
            changed = key in WRITES and outcomes.get(branch) == TAKEN
            kind = self._look_of(number, changed)
            box, text = self.rests[key]
            self._place(box, text, (x, y), anchor, value, colour, kind)
            self.resting[key] = [number, value, colour, changed, kind]

    def _look_of(self, number, changed):
        """How a value that arrived in step number looks now (_settle())."""
        playing, finished = self.now
        if not finished and number >= playing - 1:
            return "band"
        return "changed" if changed else "rest"

    def _settle(self, number, finished):
        """A value that rests is lit on a band of its colour while the step it arrived in plays
        and the next one; then, and once the film has finished, it stays readable on a tint of
        its colour, or on the green of a change."""
        self.now = (number, finished)
        for key, entry in self.resting.items():
            arrived, value, colour, changed, shown = entry
            wanted = self._look_of(arrived, changed)
            if wanted != shown:
                box, text = self.rests[key]
                self._restyle(box, text, colour, wanted)
                entry[4] = wanted

    def _place(self, box, text, point, anchor, value, colour, kind="band"):
        """Show a value at point: a travelling one, or one that has just arrived, on a band of
        its colour (kind "band"), one that stays on a tint of it ("rest") or on the green of a
        change ("changed")."""
        canvas = self.canvas
        x, y = self.xy(*point)
        fill, ink = self._looks(colour, kind)
        canvas.itemconfigure(text, text=value, anchor=anchor, state="normal", fill=ink)
        canvas.coords(text, x, y)
        left, top, right, bottom = canvas.bbox(text)
        pad = self.d(1.5)
        shift = max(0.0, pad - left) - max(0.0, right + pad - float(canvas.cget("width")))
        if shift:                       # a label travelling along the picture's edge
            canvas.move(text, shift, 0)
            left, right = left + shift, right + shift
        canvas.coords(box, left - pad, top, right + pad, bottom)
        canvas.itemconfigure(box, state="normal", fill=fill, outline=colour)
        canvas.tag_raise(box)
        canvas.tag_raise(text)

    @staticmethod
    def _looks(colour, kind):
        """(fill, text colour) of a value of colour that looks as kind says (_place())."""
        return look.band(colour) if kind == "band" else look.rest(colour, kind == "changed")

    def _restyle(self, box, text, colour, kind):
        fill, ink = self._looks(colour, kind)
        self.canvas.itemconfigure(text, fill=ink)
        self.canvas.itemconfigure(box, fill=fill, outline=colour)

    def _decide(self, decision, state="done"):
        canvas = self.canvas
        select, inputs = MUXES[decision.mux]
        for number in range(len(inputs)):
            dot, cross = self.marks[f"{decision.mux}.{number}"]
            taken = number == decision.taken
            canvas.itemconfigure(dot, state="normal" if taken else "hidden")
            for line in cross:          # only an input that brings a value is rejected
                canvas.itemconfigure(line, state="normal" if number in decision.rejected
                                     else "hidden")
                canvas.tag_raise(line)
        self._paint(decision.mux, state)

    def _gate(self, gate):
        canvas = self.canvas
        bar = self.gates.get(gate.block)
        if bar is not None:
            canvas.itemconfigure(bar, state="hidden" if gate.open else "normal")
            canvas.tag_raise(bar)
        if gate.block == "Control":
            canvas.itemconfigure(self.flag_word, text="flags written" if gate.open else
                                 "flags kept", fill=ON if gate.open else MARK)
        elif gate.block in self.gate_words:
            canvas.itemconfigure(self.gate_words[gate.block], text="open" if gate.open else
                                 "closed", fill=ON if gate.open else MARK)

    def show_condition(self, text):
        self.canvas.itemconfigure(self.condition, text=text)

    def show_pass(self, text):
        """What the pass counter says in the control unit ("pass 2 of 4"), or nothing."""
        self.canvas.itemconfigure(self.pass_word, text=text)
