# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Tools > Dynamic Instruction Counter: the instructions executed so far, by category and by
encoding format.

The tool, its classification (ares.classify) and its window come from
DynARMic (GLSVLSI 2026), a dynamic ARM instruction counting tool. The window
shows two panels side by side, as DynARMic's page does: Instruction
Categories at the left, with DynARMic's five categories, and Encoding
Formats at the right, with the eight ARMv7 encoding formats. Each panel is a
group box that shows the total, then for each category or format its count
and its share of the total on a percentage bar. One connection counts both
panels, per basic block
(ares.observers), so a connected counter costs Python time per block, never
per instruction.
"""

import tkinter as tk
from decimal import ROUND_HALF_UP, Decimal
from tkinter import ttk

from ... import classify
from ..style import SUNKEN, TEXT, draw_bevel, group
from ..style import WINDOW as FIELD
from ..widgets import px
from .frame import PercentBar, ToolModel, ToolWindow

# The panels, with DynARMic's labels in its order: (title, the labels of the counts).
CATEGORY_PANEL = ("Instruction Categories",
                  ("ALU:", "Branch:", "Memory (Byte Access):", "Memory (Reg-to-Reg):",
                   "Conditional Load & Others:"))                     # classify.CLASSES
FORMAT_PANEL = ("Encoding Formats",
                ("Data Processing (Register):", "Data Processing (Immediate):",
                 "Load/Store (Immediate):", "Load/Store (Register):", "Branch:", "Multiply:",
                 "Load/Store Multiple:", "Supervisor Call & Others:"))   # classify.FORMATS
TOTAL = "Total:"

# Sizes in design pixels.
FIELD_SIZE = (104, 20)          # a count's field
NUMBER_INDENT = 5               # a count, from its field's left side
ROW_GAP = 6                     # between two rows
TOTAL_GAP = 20                  # between the row Total: and the next
LABEL_GAP = 10                  # at least, between the labels and the counts
BOX_GAP = 6                     # between a count and its bar
PANEL_GAP = 5                   # between the two panels

TENTH = Decimal("0.1")

HELP = """\
The Dynamic Instruction Counter counts the instructions the program executes, and sorts them
into five categories and into the eight ARMv7 encoding formats.

Click Connect to ARM, then run the program (Go, Step): the counts follow the program, also
while it runs at full speed. Disconnect from ARM stops the counting; the counts stay. Reset
sets them to 0. Close closes the tool and stops the counting.

The window has two panels side by side: Instruction Categories at the left and Encoding
Formats at the right. Each starts with Total: the instructions executed while the tool was
connected, since it was opened or since its Reset button was pressed. Below it each category
or format has its count, its share of Total in per cent with one decimal, and a bar filled as
far as that share. Each instruction counts once in each panel, so the counts of a panel add
up to Total.

The counts go on when the program is assembled again, reset (Reset, F12) or stepped back
(Backstep undoes an instruction, but it was executed): only the tool's own Reset sets them to
0. The tool stays connected when the program is assembled again or its file is closed.

An instruction counts once it has completed. A breakpoint, Pause or Stop comes before an
instruction, which counts when it runs. A system call that waits for typed input counts once,
when it has its input. The instruction that ends the program with a runtime error does not
count, nor does B . at the end of a program, where ARES stops. A conditional instruction
counts whether its condition holds or not: the processor executes it either way.

Instruction Categories, the left panel:

ALU: the instructions that compute in the registers, with or without a condition, such as
ADD R0, R1, R2, SUB R0, R0, #1, MOV R0, #5, CMP R0, #10, AND R0, R0, #15, LSL R0, R0, #2
and ADDNE R0, R0, #1, and the multiplies MUL, MLA and UMULL. MOV PC, LR counts here too, not
as a branch. As DynARMic decides, every instruction of no other category is ALU as well: NOP,
the floating-point instructions (VADD.F32 S0, S1, S2, VLDR, VPUSH), the forms of LDM and STM
other than LDMIA and STMIA (STMDB R1!, {R2, R3}), and PUSH, POP, LDM and STM with a
condition (POPNE {R4, R5}, LDMNE R1, {R2}). Two of them are not: STMDB SP!, {R4, R5} is
PUSH {R4, R5}, of Memory (Reg-to-Reg), and PUSHNE {R4} is STRNE R4, [SP, #-4]!, a
conditional store.

Branch: B, BL, BX and BLX, with or without a condition: BNE loop counts whether it branches
or not.

Memory (Byte Access): the loads and stores of one byte, without a condition: LDRB R0, [R1],
STRB R0, [R1, #1] and LDRSB R0, [R1].

Memory (Reg-to-Reg): the other loads and stores without a condition, which move registers to
and from memory: of a word, a halfword, two words or several registers, such as
LDR R0, [R1], STR R0, [R1, #4], LDR R0, =value, LDRH, STRH, LDRSH, LDRD, PUSH {R4, LR},
POP {R4, PC}, LDM and STM (LDMIA, STMIA). A value that MOV or MVN can give is not loaded: the
assembler makes LDR R0, =5 into MOV R0, #5, an ALU instruction.

Conditional Load & Others: the loads and stores with a condition, such as LDRNE R0, [R1],
STREQ R0, [R1, #4] and LDRNEB R0, [R1], and the system calls (SVC #1). BKPT is of this
category too, but it ends the program with a runtime error, so it is never counted.

Encoding Formats, the right panel:

Data Processing (Register): an operation on registers only, such as ADD R0, R1, R2,
MOV R4, R0, CMP R0, R1 or LSL R0, R0, R1.

Data Processing (Immediate): an operation with an immediate (#) operand, such as
ADD R0, R0, #1, MOV R0, #5, CMP R0, #10, LSL R0, R0, #2 or ADD R4, R0, R0, LSL #1 (a shift
by a constant). Instructions of no other format count as data processing too: as immediate
when they have an immediate operand, else as register. NOP and VMUL.F32 S0, S0, S1 count as
register, VLDR D1, [R1, #8] as immediate.

Load/Store (Immediate): LDR, STR, LDRB, STRB, LDRH, STRH ... with an immediate offset or none:
LDR R0, [R1], STR R0, [R1, #4], LDR R0, =value. As DynARMic decides, an offset in R9 to R12,
SP or LR (LDR R0, [R1, R9]) and an offset after the brackets (LDR R0, [R1], R2) count here
too. A value that MOV or MVN can give is not loaded: the assembler makes LDR R0, =5 into
MOV R0, #5, which counts as Data Processing (Immediate).

Load/Store (Register): an offset in a register: LDR R0, [R1, R2], STR R0, [R1, R2, LSL #2],
LDR R0, [R1, -R2].

Branch: B, BL, BX and BLX, with or without a condition, as in Instruction Categories.

Multiply: MUL, MLA, MLS and the long multiplies SMULL, UMULL, SMLAL, UMLAL.

Load/Store Multiple: PUSH, POP, LDM and STM, such as PUSH {R4, LR}, POP {R4, PC} and
POP {PC}. A PUSH of one register other than SP counts as Load/Store (Immediate): the
assembler makes PUSH {LR} into STR LR, [SP, #-4]!, as the Text Segment's Basic column shows.
LDR R4, [SP], #4 is POP {R4} and counts here.

Supervisor Call & Others: the system calls, such as SVC #1. BKPT is of this format too, but
it ends the program with a runtime error, so it is never counted.

The Dynamic Instruction Counter and its classification come from DynARMic (GLSVLSI 2026), a
dynamic ARM instruction counting tool, with its author's permission.

While the tool is connected a run takes a little longer: ARES counts each group of
instructions that runs without a branch. A loop of 10,000,000 instructions takes about a
second instead of a tenth of a second.
"""


def share(part, whole):
    """part's share of whole in tenths of a per cent, as DynARMic's page rounds it: JavaScript's
    ((part / whole) * 100).toFixed(1) rounds the double that the division and the
    multiplication give, half up on its exact binary value. 1 of 16 is 6.25 and gives 6.3, but
    23 of 80 is the double 28.749999999999996 and gives 28.7. 0 while whole is 0."""
    if not whole:
        return 0
    return int(Decimal(part / whole * 100).quantize(TENTH, rounding=ROUND_HALF_UP) * 10)


def percentage(tenths):
    """A share in tenths of a per cent as DynARMic's page writes it: 6.3%, 0.0%, 100.0%."""
    return f"{tenths // 10}.{tenths % 10}%"


class CounterModel(ToolModel):
    """The counts: total, the instructions executed; formats, how many had each encoding
    format (in the order of classify.FORMATS); and classes, how many were of each category
    (in the order of classify.CLASSES). One connection counts all of them.

    It counts on the machine it observes while connected and keeps counting
    across Assemble, Reset and Backstep: only reset() starts again from 0.
    The format and category of an instruction are those of the word in memory
    when update() first sees its stretch of code: a program that changes its
    own instructions is counted with the words found then.
    """

    def __init__(self):
        super().__init__()
        self.total = 0
        self.formats = [0] * len(classify.FORMATS)
        self.classes = [0] * len(classify.CLASSES)
        self._blocks = None             # the machine's BlockCounts, while observing
        self._seen = {}                 # their runs as already counted here
        self._stretches = {}            # (address, size) -> (formats, classes) of its code

    def attach(self, machine):
        self._blocks = machine.observers.count_blocks(self)
        self._seen = dict(self._blocks.runs)
        self._stretches = {}

    def detach(self, machine):
        self.update()
        machine.observers.forget(self)
        self._blocks = None
        self._seen = {}

    def reset(self):
        self.update()
        self.total = 0
        self.formats = [0] * len(classify.FORMATS)
        self.classes = [0] * len(classify.CLASSES)

    def update(self):
        blocks = self._blocks
        if blocks is None:
            return False
        seen, changed = self._seen, False
        for stretch, count in blocks.runs.items():
            new = count - seen.get(stretch, 0)
            if new:
                seen[stretch] = count
                changed = True
                formats, classes = self._kinds_of(stretch)
                self.total += new * sum(formats)
                for index, number in enumerate(formats):
                    self.formats[index] += new * number
                for index, number in enumerate(classes):
                    self.classes[index] += new * number
        return changed

    def _kinds_of(self, stretch):
        kinds = self._stretches.get(stretch)
        if kinds is None:
            address, size = stretch
            kinds = self._stretches[stretch] = classify.tally(
                self.machine.read_memory(address, size))
        return kinds


class CountBox:
    """A count in a sunken white field, at its left in the fields' font. shown is the text it
    shows."""

    def __init__(self, master):
        width, height = px(master, FIELD_SIZE[0]), px(master, FIELD_SIZE[1])
        self.canvas = canvas = tk.Canvas(master, width=width, height=height, background=FIELD,
                                         borderwidth=0, highlightthickness=0, takefocus=False)
        draw_bevel(canvas, 0, 0, width, height, rings=SUNKEN, face=FIELD)
        self.shown = "0"
        self.text = canvas.create_text(px(master, NUMBER_INDENT), height // 2, anchor="w",
                                       text=self.shown, fill=TEXT, font="TkTextFont")

    def set(self, number):
        text = str(number)
        if text != self.shown:
            self.canvas.itemconfigure(self.text, text=text)
            self.shown = text


class ShareBar(PercentBar):
    """A share of the total on a percentage bar, in tenths of a per cent as share() rounds it:
    the blocks reach that much of the bar, rounded half up to whole pixels."""

    def set(self, part, whole):
        tenths = share(part, whole)
        self.show(percentage(tenths), (2 * tenths * self.room + 1000) // 2000)


class Panel:
    """One of the window's two panels: a group box with the row Total: and its count in a
    field, a gap, then a row for each category or format, with its label, its count in a field
    (CountBox) and its share of the total on a percentage bar (ShareBar).

    labels holds the labels of the rows, Total: first; total the total's field; counts and bars
    those of the rows below it.
    """

    def __init__(self, body, panel):
        title, labels = panel
        self.box = group(body, title)
        self.labels, self.counts, self.bars = [], [], []
        for row, text in enumerate((TOTAL,) + labels):
            above = 0 if row == 0 else TOTAL_GAP if row == 1 else ROW_GAP
            space = (px(body, above), 0)
            label = ttk.Label(self.box, text=text)
            label.grid(row=row, column=0, sticky="w", pady=space,
                       padx=(0, px(body, LABEL_GAP)))
            box = CountBox(self.box)
            box.canvas.grid(row=row, column=1, sticky="w", pady=space)
            self.labels.append(label)
            if row == 0:
                self.total = box
                continue
            bar = ShareBar(self.box)
            bar.canvas.grid(row=row, column=2, sticky="w", pady=space,
                            padx=(px(body, BOX_GAP), 0))
            self.counts.append(box)
            self.bars.append(bar)

    def show(self, total, counts):
        self.total.set(total)
        for box, bar, count in zip(self.counts, self.bars, counts):
            box.set(count)
            bar.set(count, total)


class CounterWindow(ToolWindow):
    """Tools > Dynamic Instruction Counter.

    Its panels (Panel) are categories, Instruction Categories at the left, and
    formats, Encoding Formats at the right.
    """

    NAME = "Dynamic Instruction Counter"
    HELP = HELP
    MODEL = CounterModel

    def build(self, body):
        self.categories = Panel(body, CATEGORY_PANEL)
        self.formats = Panel(body, FORMAT_PANEL)
        self.categories.box.pack(side="left", fill="both", expand=True)
        self.formats.box.pack(side="left", fill="both", expand=True, padx=(px(body, PANEL_GAP), 0))

    def show(self):
        model = self.model
        self.categories.show(model.total, model.classes)
        self.formats.show(model.total, model.formats)


WINDOW = CounterWindow
