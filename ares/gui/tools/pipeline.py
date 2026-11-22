# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Tools > Pipeline Simulator: when each instruction the program executes would be in each stage
of a five-stage pipeline, under settings for data forwarding, the stages that decide branches
and jumps, and branch prediction.

ares.pipeline works the timing out. The model follows the basic blocks the program executes
(ares.observers' follow_blocks) and the outcome of each conditional branch, hooked by address
with the flags as the BHT Simulator does, and gives the blocks to the fast way: Python time per
block and per conditional branch, never per instruction. A Backstep takes the instructions it
undoes out of the pipeline again; a Reset of the program or another program empties it. The
window shows the numbers, the branch lines and the reservation table, which the plain way
makes again from the newest blocks when the window draws it: while the program runs at full
speed only the numbers follow it.
"""

import tkinter as tk
from decimal import ROUND_HALF_UP, Decimal
from itertools import islice
from tkinter import font as tkfont
from tkinter import ttk

from ... import credits, pipeline
from ...pipeline import (BATCH, DYNAMIC, EX, FLUSH, ID, MEM, NONE, STALL, STATIC, Blocks, Record,
                         Settings, Timing, decode, line_text)
from ...runner import State
from ..menubar import screen_area
from ..style import FACE, GRID, SHADOW, TEXT, default_button, group, sunken
from ..style import WINDOW as FIELD
from ..widgets import HidingBars, ReadOnlyText, Tooltip, px, tab_moves_on, tip_window
from .bht import HOLDS
from .frame import (ToolModel, ToolWindow, frame_of, give_maximize_box, place_over,
                    when_settled)

# The walk through pipeline_tour.s in the help: its three settings, and what the window shows
# for each (tests/test_examples.py checks them against a run).
TOUR_SETTINGS = (Settings(), Settings(forwarding=True),
                 Settings(forwarding=True, prediction=DYNAMIC, bits=2, first_state_2=1))
TOUR = ("62 cycles, CPI 2.21, steady-state CPI 2.07", "44 cycles, CPI 1.57, steady-state CPI 1.43",
        "41 cycles, CPI 1.46, steady-state CPI 1.32")

HELP = f"""\
The Pipeline Simulator shows how the program's instructions would pass through a pipeline of
five stages: IF (fetch the instruction), ID (decode it and read its registers), EX (execute),
MEM (memory) and WB (write the result back). Each instruction spends one clock cycle in each
stage, and up to five instructions are in the pipeline at once, so a program takes about one
cycle for each instruction, plus the cycles its data and its branches cost. The settings are
those of the tool it follows: data forwarding, the stages in which branches and jumps change
the PC, and branch prediction.

ARM X-Ray and the Pipeline Simulator show the same stages in two ways. ARM X-Ray shows one
instruction going through a datapath that does everything in one clock cycle; the Pipeline
Simulator shows when each instruction would be in each stage of a datapath cut into five
stages, with several instructions inside at once. The stages have the same names in both
(Fetch is IF, Decode ID, Execute EX, Memory MEM and Write back WB), and the program's results
never differ: only the timing does.

Click Connect to ARM, then run the program (Go, Step). The tool's own Assemble, Step and
Backstep buttons do what the main window's do (F3, F7, F8). The numbers follow the program,
also while it runs at full speed; the branch lines and the table get their newest lines when
the run stops. Backstep takes the instruction it undoes out of the pipeline again, and Reset
(F12) and Assemble empty the pipeline. Disconnect from ARM stops the observing; what the tool
shows stays. The tool's own Reset starts its numbers again from zero. Close closes the tool.

What the window shows

The line of numbers: Instructions, how many the program executed; Cycles, the cycle in which
the last of them leaves WB, which is the instructions + 4 + the cycles lost; Lost to stalls,
the cycles lost while instructions waited (the stall cells); Lost to flushes, the cycles lost
to instructions fetched and thrown away; CPI, the cycles divided by the instructions;
Steady-state CPI, the same without the 4 cycles that fill the pipeline at the start; and
Predictions right, of the predictions made. Rest the mouse on a number to see what it is,
with its sum worked out with the numbers shown, for example CPI = cycles / instructions =
62 / 28 = 2.21. Under the numbers stand the settings in force.

CPI is cycles / instructions. Steady-state CPI is (cycles - 4) / instructions: the CPI without
the four cycles that only fill the pipeline at the start, so the number a long program comes
near. After the first Step of the walk below, 1 instruction has taken 5 cycles: CPI 5 / 1 =
5.00, and steady-state CPI (5 - 4) / 1 = 1.00, as each instruction after the first adds one
cycle when nothing waits.

Each instruction is named as you wrote it, as the Source column of the Text Segment shows it
without its line number and comment: MOV R0, #20, not MOV R0, #0x14; BNE next, not BNE #0x24.
The table, the branch lines, the tips and Check Dependency all name it so. Rest the mouse on
an instruction in the table to see its Basic form, as the Basic column shows it. A
word without a line of its own, such as a word of data thrown away after a branch or the
second word of a line that makes two, shows its Basic form.

The branch lines: a line for every branch that runs, the newest last, as the tool it follows
writes them: the instruction and its address, the state of the predictor before it, the
prediction, what the branch did, and the state now. The tool keeps the last 1,000 lines.

The reservation table: a row for every instruction that enters the pipeline, with its address
and its text, and a column for every clock cycle. Each cell holds the stage the instruction
is in, one colour for each stage, as the key under the table shows. An instruction that must
wait keeps its stage, and those cells say stall, in gray. Rest the mouse on one to see what it
waits for, for example: waits for R3 from LDR R3, [R1] at 0x00000014. Instructions fetched
and thrown away have rows of their own, in gray letters, whose last cell says Flush; the mouse
on it says why. The table shows the last 500 rows, with the newest row and the newest cycle in
view; scroll it with its bars or the mouse wheel (with Shift the wheel scrolls sideways).

Make the window larger, or maximize it, and the table shows more rows and more cycles, and
the branch lines more of each line; the numbers and the buttons keep their size. The window
can be made smaller down to five rows of the table. Check Dependency's list grows with its
window in the same way.

The settings

Settings... opens the settings in three groups, as the tool it follows has them. Confirm
Settings works the numbers, the branch lines and the table out again for the instructions
already run, so that you see at once what a setting changes. Reset Default Settings puts the
first settings back in the window; Confirm Settings then uses them. Escape closes the window
and keeps the settings as they were. Choices that do not apply are gray. Rest the mouse on WB
and ID in the same cycle, Branch stage, Jump stage or the line of the states to see what it
means.

Data dependency. Data forwarding: No (at first) or Yes. Without forwarding an instruction
reads its registers in ID, after the instruction that writes them has left WB: two neighbours
that depend on each other lose 3 cycles, at a distance of two 2, and at a distance of three 1.
WB and ID in the same cycle (No at first), without forwarding: Yes lets the reader's ID share
the writer's WB cycle, a cycle less: 2, 1 and 0. With forwarding a result is passed on as soon
as EX has made it, and a value loaded from memory as soon as MEM has read it: the instruction
right after a load that uses the loaded value waits one cycle, and no other waits.

Control dependency. Branch stage, the stage in which a branch updates the PC: ID, EX (at
first) or MEM; and Jump stage, the stage in which a jump does: ID (at first) or EX. Without
prediction nothing is fetched until a branch is decided, so it costs 1, 2 or 3 cycles, taken
or not, and the row after it starts with stall cells. A jump costs 1 or 2 cycles, always.

Branch prediction. No prediction (at first). Static: every branch is predicted always taken,
or always not taken. Dynamic: a state for each branch predicts it, and moves one up when the
branch is taken and one down when it is not. With 1 bit, state 0 predicts not taken and state
1 taken. With 2 bits, states 0 and 1 predict not taken and states 2 and 3 taken (State 0 <-->
State 1 <--> State 2 <--> State 3), so a branch in state 0 or 3 must go the other way twice
before its prediction changes. First state sets the state each branch starts in. One state
for all branches makes all branches share one state.

The prediction is made at the end of ID. Predicted not taken, fetching goes on in line;
predicted taken, the one instruction already fetched in line is thrown away and fetching goes
on at the branch's target. When the branch is decided, a wrong prediction throws away
everything fetched since. So a right prediction costs 0 cycles (not taken) or 1 (taken), and a
wrong one 2 or 3 for a branch decided in EX or MEM. A branch decided in ID is known as early as
the prediction, and its outcome is used: 1 cycle if taken, 0 if not.

Check Dependency

Check Dependency opens Corrected Program Code: the program as it is written, with the NOPs
that a pipeline without any stalling or flushing hardware would need under the settings in
force, each marked "@ added by the checker". The one line above the program counts them, for
example NOPs added: 26, and says No program assembled when there is none. The window follows
Confirm Settings and Assemble; Escape or its close box closes it. As the tool it follows does,
it reads the program in the order it is written and does not follow branches. Between two
neighbours that depend on each other it puts 3 NOPs without help, 2 when WB and ID share a
cycle, and none with forwarding, but 1 after a load. Without prediction it puts 1, 2 or 3 NOPs
after a branch decided in ID, EX or MEM, 1 or 2 after a jump, and after any other instruction
that writes the PC as many as it costs; with prediction it puts none after any of them, as the
tool it follows does. For code without branches, the checker's NOPs are the table's stall
cycles.

How ARES differs from the tool it follows, and why

ARES runs the program as always. The tool watches the instructions that execute and works out
in which cycle each would be in each stage, so the settings never change what the program
does, only the timing. Where the tool it follows leaves the repair to NOPs, ARES shows what
the hardware would do: an instruction that must wait keeps its stage, in stall cells, and the
instructions fetched and thrown away are rows of their own.

The instructions thrown away are read from memory at the addresses the pipeline would have
fetched, and are never executed. A row thrown away on a literal word, such as the words of
LDR R0, =value after the code, shows the word as data; past the end of memory it says no
instruction here.

ARM branches test the flags N, Z, C and V, not two registers. The flags are written at the end
of EX of the instruction that sets them and do not pass through WB, so a branch decided in ID
waits one cycle when the instruction just before it sets the flags, and a branch decided in EX
or MEM never waits for them. Other conditional instructions check their condition in EX and
never wait.

ARM's branch and jump: B with a condition is the tool's branch, and B and BL without a
condition are its jump. BL with a condition is a branch that also writes LR. Every other
instruction that writes the PC (BX, MOV PC, LDR into the PC, POP with the PC) is a branch that
is taken always and never predicted, decided in the branch's stage, or in MEM when the PC
comes from memory. Decided in ID it needs its register in ID: with forwarding, one cycle
earlier than other instructions need theirs.

The registers: every register an instruction reads counts, also the base of an address, the
register that gives a shift amount and the register a store writes to memory (the PC read as a
value never waits), against every register an earlier instruction writes, also a base with
write-back, LR of BL and every register of POP. Floating-point registers count the same way
(D0 is S0 and S1). A conditional instruction counts as reading and writing what it names
whether or not its condition holds.

Every instruction takes one cycle in each stage, also PUSH, POP, MUL and the floating-point
instructions, which a real processor needs more cycles for. An SVC counts as one instruction
that reads and writes the registers of its service.

With forwarding, the instruction right after a load that uses the loaded value waits one
cycle. The tool it follows does not show this case in its table.

The predictor keeps a state for each branch address, as processors do. The tool it follows
keeps a single state for all branches: One state for all branches gives its way.

ARES says ID where the tool it follows says DEC, for the stage that decodes the instruction.

Confirm Settings works the numbers out again from the instructions already run, so that the
settings can be compared on the same run.

The tool it follows has a Set Reg Value button. ARES needs none: set a register in the
Registers pane while no program is running: double-click its value, type the number and press
Enter.

A walk through pipeline_tour.s

Open File > Open Example > pipeline_tour.s, assemble it (F3), open the Pipeline Simulator and
click Connect to ARM. The program starts as the test program of the tool it follows: two
equal values, a BNE that is not taken, and a BEQ that is taken over three lines. Then come a
load followed by its use, a short loop that runs three times, and the result, 16, printed
with SVC #1. It executes 28 instructions.

With the first settings (no forwarding, branches decided in EX, no prediction), press F7
once: MOV R0, #20 passes the five stages in 5 cycles, CPI 5.00 and steady-state CPI 1.00.
Press F5 for the rest.
CMP R0, R1 waits 3 cycles for R1 from the MOV just before it: rest the mouse on its stall
cells. Each of the five branches executed costs 2 cycles, and the row after it starts with
stall cells. LDR R10, [R9] waits for R9 and ADD R10, R10, R8 for R10. All 30 cycles lost are
lost to stalls: {TOUR[0]}.

In Settings..., choose Data forwarding Yes, then Confirm Settings. The waits for the MOVs and
the CMPs are gone; only the two loads still cost a cycle each, as the next instruction uses
the value they load, and the branches still cost 2 cycles each: {TOUR[1]}. Deciding the
branches in ID instead gives as many cycles: each branch then costs 1 cycle, but waits 1 cycle
for the flags of the CMP or SUBS just before it.

Now keep forwarding and choose Dynamic prediction with 2 bits, first state 1, as in the tool
it follows. BNE is predicted not taken and is not taken: no cycle lost. BEQ is predicted not
taken but is taken: MOV R5 and MOV R6, fetched in line, are thrown away (Flush), 2 cycles. In
the loop, BNE is predicted wrong the first time (2 cycles), right the second (1 cycle, for the
instruction fetched in line) and wrong when the loop ends (2 cycles). 2 of the 5 predictions
are right: {TOUR[2]}. Check Dependency says NOPs added: 26 for the first settings, 8 with
forwarding and 2 with prediction.

How much of the run the tool keeps

To work the numbers out again for other settings, the tool keeps the run: every instruction,
up to 1,000,000. For a longer run it keeps the last 1,000,000 or a little more, dropping the
oldest a hundred thousand or more at a time, and the numbers worked out for new settings count
from the oldest instruction kept, as the line of the settings then says. The numbers for the
settings in force always cover the whole run. Working them out again for a million
instructions takes a fraction of a second. Backstep takes its instructions out of what is
kept too, so Confirm Settings afterwards works on the instructions that remain.

Backstep, Reset and Assemble

The pipeline holds the instructions of the run going on. Backstep takes the instruction it
undoes out again: its row, its cycles, its stalls and flushes, its branch line and what the
predictor learned from it. One Step and one Backstep leave the tool as it was before the
Step. After a run at full speed this holds as far back as the main window can step back:
Backstep can then undo up to the last 2,000 instructions when Settings > Enable Backstep While
Running is on. A Backstep only takes out instructions the tool took in: not those that ran
while it was not connected.

Reset (F12) and Assemble empty the pipeline, as a pipeline cannot keep the instructions of a
run that is gone; the tool's own Reset empties it too. The tool stays connected when the
program is assembled again or its file is closed. Disconnect from ARM keeps what the tool
shows, and Connect to ARM goes on from there, unless the program was reset or assembled in
between. A breakpoint, Pause or Stop comes before an instruction, which enters the table when
it runs.

While the tool is connected a run takes longer: ARES works out each group of instructions
that runs without a branch, and looks at each conditional branch as it runs. A loop of
10,000,000 instructions takes a few seconds instead of a tenth of a second.

{credits.PIPELINE_ORIGIN}
"""


def conditional_branches(program):
    """{address: whether it is taken, for each value of the flags N, Z, C and V} of the
    program's B and BL with a condition."""
    found = {}
    for address in program.code_addresses():
        word = program.read_word(address)
        if word is not None and word >> 25 & 7 == 0b101 and word >> 28 < 0xE:
            found[address] = HOLDS[word >> 28]
    return found


class PipelineModel(ToolModel):
    """The timing of the instructions executed while connected, under settings.

    The block follower adds a code for each block entered to pending (see
    pipeline.Timing.run()): the branch hook marks the block's branch taken,
    a stop inside the block cuts it, and the next block tells the outcome of
    a branch no hook reports. pending goes to the fast way (timing) and to
    record, which keeps the run for configure(), at each update() and
    whenever BATCH blocks have gathered.

    The pipeline holds the instructions of the run going on. A Backstep
    takes the instructions it undid out again (undo()); a Reset of the
    program, another program (Assemble) and reset() empty it. The model sees
    a Reset or a Backstep in the machine's counts, machine.resets and
    machine.backsteps, whenever it looks: at the end of each run of the
    emulator, before it takes in a batch of blocks, and at update(). Blocks
    gathered before the latest end of a run (pending[:mark]) ran before what
    it sees then, the others after it. held counts the newest instructions
    the tool took in that the machine can still undo: a Backstep takes out at
    most those (none that ran while the tool was not connected).

    written(program, address), which the window gives, names an instruction
    of program as the student wrote it (None where there is no such text).
    """

    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.blocks = Blocks()
        self.written = None
        self._pending = []
        self._mark = [0]                # blocks of pending that ran before the latest stop
        self._unknown = [None]          # a block whose branch outcome the next block tells
        self._program = None            # the program observed last
        self._source = None             # the machine observed last (the rows thrown away)
        self._seen = (0, 0)             # the machine's resets and backsteps at the last look
        self._left = None               # the machine when the tool stopped observing it
        self.error = None               # what went wrong in a hook, raised by update()
        self.reset()

    def reset(self):
        """Start the timing and the numbers again from zero."""
        del self._pending[:]
        self._mark[0] = 0
        self._unknown[0] = None
        self._empty()

    def _empty(self):
        """No instruction in the pipeline any more."""
        self.timing = Timing(self.settings, self.blocks)
        self.record = Record()
        self.counted_from = 0           # instructions the numbers leave out at the start
        self.held = 0
        self.changed = True

    @property
    def totals(self):
        return self.timing.totals

    # Observing ------------------------------------------------------------------------

    def attach(self, machine):
        left = self._left
        if machine is not self._source:         # another program: the run shown is gone
            self.blocks = Blocks()
            self.reset()
        elif left is None or machine.resets != left[0]:     # reset while not observed
            self.reset()
        elif left != self._where(machine):
            self.held = 0                       # it ran or stepped back unobserved
        self._seen = (machine.resets, machine.backsteps)
        program = machine.program
        self._program, self._source = program, machine
        branches = conditional_branches(program)
        self.blocks.new_program(machine.read_memory, branches)
        observers = machine.observers
        observers.follow_blocks(self, *self._followers())
        if branches:
            pending = self._pending

            def ran(address, flags):
                if branches[address][flags] and pending:
                    pending[-1] |= 1
            observers.watch_code(self, branches, ran, flags=True)

    def detach(self, machine):
        self.update()
        machine.observers.forget(self)
        self._left = self._where(machine)

    @staticmethod
    def _where(machine):
        """Where machine stands: its resets, its backsteps and its newest change recorded."""
        history = machine.history
        return machine.resets, machine.backsteps, history[-1].number if history else 0

    def _followers(self):
        """(entered, stopped, stepped_over) for ares.observers' follow_blocks."""
        pending = self._pending
        append = pending.append
        blocks = self.blocks
        index, add, listed = blocks.index, blocks.add, blocks.list
        unknown, mark = self._unknown, self._mark
        process, look = self._process, self._look

        def entered(handle, address, size, key):
            try:
                block = unknown[0]
                if block is not None:
                    unknown[0] = None
                    if address == block.target and pending:
                        pending[-1] |= 1
                if len(pending) >= BATCH:
                    look(mark[0])
                    process()
                number = index.get((address, size))
                if number is None:
                    number = add(address, size)
                append(number << 1)
                if listed[number].infer:
                    unknown[0] = listed[number]
            except BaseException as error:      # never into the emulator: update() raises it
                self.error = error

        def stopped(address):
            try:
                if pending:
                    block = listed[pending[-1] >> 1]
                    if block.start <= address < block.start + block.size:
                        unknown[0] = None       # the rest did not run, its branch neither
                        if address == block.start:
                            pending.pop()
                        else:
                            pending[-1] = add(block.start, address - block.start) << 1
                look(mark[0])
                mark[0] = len(pending)
            except BaseException as error:
                self.error = error

        def stepped_over(address):
            unknown[0] = None
            append(add(address, 4) << 1)
            mark[0] = len(pending)

        return entered, stopped, stepped_over

    def _look(self, before):
        """Take in a Reset or Backsteps of the machine since the last look: pending[:before]
        ran before them, the rest after them."""
        machine = self.machine
        resets, backsteps = machine.resets, machine.backsteps
        if (resets, backsteps) == self._seen:
            return
        pending = self._pending
        after = pending[before:]
        del pending[before:]
        if not after:
            self._unknown[0] = None             # its block is undone, or its run gone
        if resets != self._seen[0]:             # the run the pipeline holds is gone
            del pending[:]
            self._empty()
        else:
            self._process()
            self.undo(backsteps - self._seen[1])
        self._seen = (resets, backsteps)
        pending.extend(after)

    def _process(self):
        """Give the blocks gathered to the fast way and to the record."""
        pending = self._pending
        if pending:
            before = self.timing.count
            self.timing.run(pending)
            added = self.timing.count - before
            self.record.add(pending, added)
            self.held += added
            del pending[:]
            self.changed = True
        self._mark[0] = 0

    def update(self):
        if self.error is not None:
            error, self.error = self.error, None
            raise error
        machine = self.machine
        if machine is not None:
            if (machine.resets, machine.backsteps) != self._seen:
                self._look(len(self._pending))  # no run since: all of pending ran before
            elif self._unknown[0] is not None:
                # The block's branch ran and the program stopped before the next block: PC tells.
                block, self._unknown[0] = self._unknown[0], None
                if machine.pc == block.target and self._pending:
                    self._pending[-1] |= 1
        self._process()
        changed, self.changed = self.changed, False
        return changed

    def undo(self, count):
        """Take the last count instructions out of the pipeline again, at most those held
        (Backstep undid them): their rows, cycles, stalls and flushes, their branch lines and
        what the predictor learned from them. The run kept loses them too."""
        count = min(count, self.held, self.timing.count)
        if count <= 0:
            return
        self.held -= count
        self.record.undo(count, self.blocks)
        if not self.timing.undo(count):
            self._work_out()            # the tail did not reach: from the run kept
        self.changed = True

    # Other settings ----------------------------------------------------------------------

    def configure(self, settings):
        """Work the numbers out again for settings, from the run kept; False when they are the
        settings in force."""
        self.update()
        if settings == self.settings:
            return False
        self.settings = settings
        self._work_out()
        return True

    def _work_out(self):
        """The timing again for the settings in force, from the run kept."""
        timing = Timing(self.settings, self.blocks)
        for codes in self.record.codes():
            timing.run(codes)
        self.timing = timing
        self.counted_from = self.record.dropped
        self.changed = True

    # What the window shows ---------------------------------------------------------------

    def read_word(self, address):
        """(word, code) at address, for a row thrown away: the word in memory (None where there
        is none) and whether it is an instruction of the program."""
        machine, program = self.machine or self._source, self._program
        word = None
        if machine is not None:
            try:
                word = machine.peek_words(address, 1)[0]
            except Exception:           # never fail a drawing for one word
                word = None
        elif program is not None:
            word = program.read_word(address)
        return word, program is not None and program.is_code(address)

    def namer(self, program=None):
        """written(address) for the instructions of program (by default the program whose run
        the pipeline holds), or None when nothing names them as written."""
        written, program = self.written, program or self._program
        if written is None or program is None:
            return None
        return lambda address: written(program, address)

    def rows(self):
        """The newest rows of the reservation table."""
        return self.timing.rows(self.read_word, written=self.namer())

    def lines(self):
        """The newest branch lines (at most pipeline.LINES), the newest last."""
        return self.timing.newest_lines(self.namer())

    @property
    def program(self):
        """The program observed now, else the one observed last (None before any)."""
        return self.machine.program if self.machine is not None else self._program

    def check(self, program=None):
        """(program, the checker's lines, the NOPs added) for program (by default the program
        observed), or None without a program."""
        program = program or self.program
        if program is None:
            return None
        instructions = [(address, decode(program.read_word(address), address))
                        for address in program.code_addresses()]
        lines, added = pipeline.check(instructions, self.settings, self.namer(program))
        return program, lines, added


# The window ---------------------------------------------------------------------------------

TOOLBAR = (("assemble", "Assemble the current file"), ("step", "Run one instruction"),
           ("backstep", "Undo the last instruction"))
# The colour of each kind of cell, and of its letters where they are not TEXT.
COLOURS = {"IF": "#CFE2F3", "ID": "#D9EAD3", "EX": "#FFF2CC", "MEM": "#FCE5CD", "WB": "#E4D7F5",
           STALL: "#DDDDDD", FLUSH: "#A0522D"}
INKS = {STALL: "#6E6E6E", FLUSH: "#FFFFFF"}
KEY = (("IF", "fetch"), ("ID", "decode"), ("EX", "execute"), ("MEM", "memory"),
       ("WB", "write back"), (STALL, "waits"), (FLUSH, "thrown away"))
# The numbers above the table: (label, characters of its field).
FIELDS = (("Instructions:", 13), ("Cycles:", 13), ("Lost to stalls:", 9),
          ("Lost to flushes:", 9), ("CPI:", 5), ("Steady-state CPI:", 5),
          ("Predictions right:", 15))
VISIBLE_ROWS = 14               # rows of the table in view at the window's usual size
VISIBLE_CYCLES = 18             # cycles of the table in view at the window's usual size
LEAST_ROWS, LEAST_CYCLES = 5, 6     # in view at the least size, or on a small screen
TEXT_CHARS = 24                 # the instruction's column, in characters
LOG_LINES = 5                   # branch lines in view
WHEEL = 3                       # rows a notch of the mouse wheel scrolls
TIP_DELAY = 600                 # milliseconds the mouse rests on a cell before its tip shows
CHECK_SIZE = (64, 26)           # Check Dependency's text, in characters and lines
CHECK_LEAST = 8                 # its lines at its least size
ADDED = "#000080"               # the NOPs the checker added
EMPTY = {False: "Click Connect to ARM, then run or step the program.",
         None: "No program is loaded.",
         True: "Run or step the program."}


def two_places(part, whole):
    """part / whole with two decimals, rounded half up as by hand (4 / 3 is 1.33); "" when
    whole is 0."""
    if not whole:
        return ""
    return str((Decimal(part) / Decimal(whole)).quantize(Decimal("0.01"), ROUND_HALF_UP))


def numbers(totals, settings):
    """The texts of the fields of FIELDS."""
    count = totals.instructions
    if settings.prediction == NONE:
        right = "no prediction"
    else:
        right = f"{totals.right:,} of {totals.right + totals.wrong:,}"
    return (f"{count:,}", f"{totals.cycles:,}", f"{totals.stalls:,}", f"{totals.flushes:,}",
            two_places(totals.cycles, count), two_places(totals.cycles - pipeline.FILL, count),
            right)


def tips(totals, settings):
    """What the mouse over each field of FIELDS shows: what the number is, with its sum worked
    out with the numbers shown."""
    count, cycles = totals.instructions, totals.cycles
    lost, fill = totals.stalls + totals.flushes, pipeline.FILL
    cpi = "CPI = cycles / instructions"
    steady = f"Steady-state CPI = (cycles - {fill}) / instructions"
    total = f"Cycles = instructions + {fill} + cycles lost"
    if count:
        cpi += f" = {cycles:,} / {count:,} = {two_places(cycles, count)}"
        steady += f" = ({cycles:,} - {fill}) / {count:,} = {two_places(cycles - fill, count)}"
        total += f" = {count:,} + {fill} + {lost:,} = {cycles:,}"
    if settings.prediction == NONE:
        right = "Predictions right: no branch is predicted (Settings... chooses a prediction)"
    else:
        made = totals.right + totals.wrong
        right = (f"Predictions right = {totals.right:,} of {made:,} predictions "
                 f"({totals.right:,} right + {totals.wrong:,} wrong = {made:,})\n"
                 "each conditional branch is predicted at the end of ID")
    return (f"Instructions: how many instructions the program executed = {count:,}",
            total + f"\nthe cycle in which the last instruction leaves WB; the first {fill} "
                    "cycles fill the pipeline",
            f"Lost to stalls = the cycles lost while instructions waited = {totals.stalls:,}\n"
            "the stall cells: waits for a value, for the flags, or until a branch or jump is "
            "decided",
            f"Lost to flushes = the cycles lost to instructions thrown away = "
            f"{totals.flushes:,}\nthe rows that end in Flush, fetched after a branch",
            cpi + "\nthe clock cycles an instruction takes, on average",
            steady + f"\nthe CPI without the {fill} cycles that only fill the pipeline at the "
                     "start:\nthe number a long program comes near",
            right)


class ReservationTable:
    """The reservation table on a canvas: a heading row, then a row for each instruction, its
    address and text first, then a cell for each cycle it is in the pipeline, in its stage's
    colour. Only what is in view is drawn: from row top and from the cycle first + left.

    The canvas takes the room the window gives it: more rows and cycles in a larger window.
    It is drawn again once its size has settled (frame.when_settled), the newest row and
    cycle still in view if they were. usual holds the rows and cycles in view at the
    window's usual size."""

    def __init__(self, master, font):
        self.font = font
        self.pad = px(master, 4)
        self.row_height = font.metrics("linespace") + px(master, 6)
        self.cell = max(font.measure(text) for text in (*pipeline.STAGES, STALL, FLUSH,
                                                         "00000")) + px(master, 10)
        self.address_width = font.measure("0x00000000") + 2 * self.pad
        self.text_width = font.measure("0" * TEXT_CHARS) + 2 * self.pad
        self.side = self.address_width + self.text_width
        self.frame = sunken(tk.Frame(master))
        self.canvas = canvas = tk.Canvas(self.frame, background=FIELD, borderwidth=0,
                                         highlightthickness=0, takefocus=False)
        self.usual = (VISIBLE_ROWS, VISIBLE_CYCLES)
        self.ask(*self.usual)
        self.yscroll = ttk.Scrollbar(self.frame, orient="vertical", command=self.yview)
        self.xscroll = ttk.Scrollbar(self.frame, orient="horizontal", command=self.xview)
        canvas.grid(row=0, column=0, sticky="nsew")
        self.yscroll.grid(row=0, column=1, sticky="ns")
        self.xscroll.grid(row=1, column=0, sticky="ew")
        self.frame.rowconfigure(0, weight=1)
        self.frame.columnconfigure(0, weight=1)
        self.rows, self.first, self.count = [], 1, 0    # count: the cycles the rows cover
        self.top = self.left = 0
        self.message = ""
        self._clips = {}
        self._tip = None                # (spot, pending job, tip window)
        self._view = self.usual         # the rows and cycles in view when last drawn
        self._sized = False             # the canvas has had a size on the screen
        canvas.bind("<Configure>", self._configured, add="+")
        when_settled(canvas, self.fit)
        canvas.bind("<MouseWheel>", self._wheel)
        canvas.bind("<Shift-MouseWheel>", lambda event: self._wheel(event, sideways=True))
        canvas.bind("<Button-4>", lambda event: self.yview("scroll", -WHEEL, "units"))
        canvas.bind("<Button-5>", lambda event: self.yview("scroll", WHEEL, "units"))
        canvas.bind("<Motion>", self._moved)
        canvas.bind("<Leave>", lambda event: self.hide_tip())

    def ask(self, rows, cycles):
        """Let the canvas ask for room for rows rows and cycles cycles."""
        self.canvas.configure(width=self.side + cycles * self.cell,
                              height=(rows + 1) * self.row_height)

    def shrink(self, width, height):
        """Show fewer cycles and rows at the usual size, so that the table is width and height
        pixels smaller (not fewer than LEAST_CYCLES and LEAST_ROWS)."""
        cycles = max(LEAST_CYCLES, VISIBLE_CYCLES - -(-width // self.cell))
        rows = max(LEAST_ROWS, VISIBLE_ROWS - -(-height // self.row_height))
        self.usual = (rows, cycles)
        self.ask(rows, cycles)

    def _size(self):
        """The canvas's size; the size it has at the window's usual size while it has none."""
        canvas = self.canvas
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width <= 1 or height <= 1:
            rows, cycles = self.usual
            width, height = self.side + cycles * self.cell, (rows + 1) * self.row_height
        return width, height

    def _configured(self, event):
        """The canvas's first size on the screen: drawn at once (later ones once settled)."""
        if not self._sized and event.width > 1 and event.height > 1:
            self._sized = True
            self.fit()

    def fit(self):
        """Draw the table for the canvas's size now, the newest row and cycle still in view
        if they were."""
        rows, cycles = self._view
        newest_row = self.top + rows >= len(self.rows)
        newest_cycle = self.left + cycles >= self.count
        rows, cycles = self.in_view()
        if newest_row:
            self.top = max(0, len(self.rows) - rows)
        if newest_cycle:
            self.left = max(0, self.count - cycles)
        self.draw()

    def in_view(self):
        """(rows, cycles) the table has room for."""
        width, height = self._size()
        return (max(1, (height - self.row_height) // self.row_height),
                max(1, (width - self.side) // self.cell))

    def show(self, rows, message=""):
        """Show rows, the newest row and the newest cycle in view; message when there are none."""
        self.rows, self.message = rows, message
        self.first = min((row.first for row in rows), default=1)
        self.count = max((row.last for row in rows), default=0) - self.first + 1 if rows else 0
        rows_in_view, cycles_in_view = self.in_view()
        self.top = max(0, len(rows) - rows_in_view)
        self.left = max(0, self.count - cycles_in_view)
        self.draw()

    def yview(self, *args):
        rows_in_view = self.in_view()[0]
        self.top = self._moved_to(args, self.top, len(self.rows), rows_in_view)
        self.draw()

    def xview(self, *args):
        cycles_in_view = self.in_view()[1]
        self.left = self._moved_to(args, self.left, self.count, cycles_in_view)
        self.draw()

    @staticmethod
    def _moved_to(args, now, total, page):
        if args and args[0] == "moveto":
            place = round(float(args[1]) * total)
        elif args and args[0] == "scroll":
            place = now + int(args[1]) * (page if args[2] == "pages" else 1)
        else:
            place = now
        return max(0, min(max(0, total - page), place))

    def _wheel(self, event, sideways=False):
        notches = -int(event.delta / 120) if event.delta else 0
        if sideways:
            self.xview("scroll", notches * WHEEL, "units")
        else:
            self.yview("scroll", notches * WHEEL, "units")
        return "break"

    def _clipped(self, text):
        """text, cut with "..." to fit the instruction's column."""
        shown = self._clips.get(text)
        if shown is None:
            room, font = self.text_width - 2 * self.pad, self.font
            shown = text
            if font.measure(text) > room:
                while shown and font.measure(shown + "...") > room:
                    shown = shown[:-1]
                shown += "..."
            self._clips[text] = shown
        return shown

    def _heading(self, left, right, text, name, centre=False):
        canvas, height = self.canvas, self.row_height
        canvas.create_rectangle(left, 0, right - 1, height - 1, fill=FACE, outline=GRID,
                                tags=(f"head:{name}",))
        x, anchor = ((left + right) // 2, "center") if centre else (left + self.pad, "w")
        canvas.create_text(x, height // 2, text=text, anchor=anchor, font=self.font, fill=TEXT,
                           tags=(f"head:{name}",))

    def draw(self):
        """Draw the part in view."""
        canvas = self.canvas
        canvas.delete("all")
        self.hide_tip()
        width, height = self._size()
        rows_in_view, cycles_in_view = self._view = self.in_view()
        self.top = max(0, min(self.top, len(self.rows) - rows_in_view))
        self.left = max(0, min(self.left, self.count - cycles_in_view))
        size, cell, side, pad = self.row_height, self.cell, self.side, self.pad
        self._heading(0, self.address_width, "Address", "address")
        self._heading(self.address_width, side, "Instruction", "instruction")
        cycles = range(self.first + self.left,
                       self.first + min(self.count, self.left + cycles_in_view))
        for column, cycle in enumerate(cycles):
            x = side + column * cell
            self._heading(x, x + cell, str(cycle), f"cycle{cycle}", centre=True)
        if not self.rows and self.message:
            canvas.create_text(width // 2, size + (height - size) // 2, text=self.message,
                               font=self.font, fill=TEXT, tags=("message",))
        for line, index in enumerate(range(self.top, min(len(self.rows),
                                                          self.top + rows_in_view))):
            row = self.rows[index]
            y = size + line * size
            ink = SHADOW if row.flushed else TEXT
            canvas.create_text(pad, y + size // 2, anchor="w", text=f"0x{row.address:08x}",
                               font=self.font, fill=ink, tags=(f"row:{index}",))
            canvas.create_text(self.address_width + pad, y + size // 2, anchor="w",
                               text=self._clipped(row.text), font=self.font, fill=ink,
                               tags=(f"row:{index}",))
            for column, cycle in enumerate(cycles):
                stage = row.cell(cycle)
                if stage:
                    x = side + column * cell
                    tag = f"cell:{index}.{cycle}"
                    canvas.create_rectangle(x + 1, y + 1, x + cell - 2, y + size - 2,
                                            fill=COLOURS[stage], outline=GRID, tags=(tag,))
                    canvas.create_text(x + cell // 2, y + size // 2, text=stage, font=self.font,
                                       fill=INKS.get(stage, TEXT), tags=(tag,))
        total = len(self.rows)
        self.yscroll.set(*((self.top / total, min(1, (self.top + rows_in_view) / total))
                           if total else (0, 1)))
        self.xscroll.set(*((self.left / self.count,
                            min(1, (self.left + cycles_in_view) / self.count))
                           if self.count else (0, 1)))

    def _row_at(self, y):
        """The number of the row drawn at the canvas height y, or None."""
        size = self.row_height
        index = self.top + (y - size) // size
        if y < size or index >= min(len(self.rows), self.top + self._view[0]):
            return None
        return index

    def cell_at(self, x, y):
        """(row number, cycle) of the cell at the canvas point (x, y), or None."""
        index = self._row_at(y)
        if index is None or x < self.side:
            return None
        cycle = self.first + self.left + (x - self.side) // self.cell
        if not self.rows[index].cell(cycle):
            return None
        return index, cycle

    def spot_at(self, x, y):
        """What the canvas point (x, y) is on: a cell, (row number, cycle); a row's
        instruction, (row number, None); or nothing, None."""
        if x >= self.side:
            return self.cell_at(x, y)
        index = self._row_at(y)
        return (index, None) if index is not None and x >= self.address_width else None

    def tip(self, spot):
        """What the mouse over spot (of spot_at()) shows ("" for nothing): why a cell waits
        or was thrown away; for an instruction its Basic form where it is shown as written,
        and all of it where its column cuts it."""
        index, cycle = spot
        row = self.rows[index]
        if cycle is not None:
            return row.tip(cycle)
        lines = [row.text] if self._clipped(row.text) != row.text else []
        if row.basic and row.basic != row.text:
            lines.append(f"Basic: {row.basic}")
        return "\n".join(lines)

    def _moved(self, event):
        spot = self.spot_at(event.x, event.y)
        if self._tip is not None and self._tip[0] == spot:
            return
        self.hide_tip()
        text = self.tip(spot) if spot is not None else ""
        if text:
            job = self.canvas.after(TIP_DELAY, lambda: self._show_tip(spot, text, event.x_root,
                                                                      event.y_root))
            self._tip = (spot, job, None)

    def _show_tip(self, spot, text, x, y):
        if self._tip is None or self._tip[0] != spot:
            return
        canvas = self.canvas
        self._tip = (spot, None, tip_window(canvas, text, x + px(canvas, 12),
                                            y + px(canvas, 8)))

    def hide_tip(self):
        if self._tip is not None:
            _, job, window = self._tip
            if job is not None:
                self.canvas.after_cancel(job)
            if window is not None:
                window.destroy()
            self._tip = None


class Key:
    """The key of the table: each kind of cell, as the table draws it, and what it means."""

    def __init__(self, master, font, cell, height):
        interface = tkfont.nametofont("TkDefaultFont", root=master)
        gap = px(master, 6)
        self.canvas = canvas = tk.Canvas(master, height=height, background=FACE, borderwidth=0,
                                         highlightthickness=0, takefocus=False)
        x = 0
        canvas.create_text(x, height // 2, anchor="w", text="Key:", font=interface, fill=TEXT,
                           tags=("key:title",))
        x += interface.measure("Key:") + gap
        for stage, meaning in KEY:
            canvas.create_rectangle(x + 1, 1, x + cell - 2, height - 2, fill=COLOURS[stage],
                                    outline=GRID, tags=(f"key:{stage}",))
            canvas.create_text(x + cell // 2, height // 2, text=stage, font=font,
                               fill=INKS.get(stage, TEXT), tags=(f"key:{stage}",))
            x += cell + gap // 2
            canvas.create_text(x, height // 2, anchor="w", text=meaning, font=interface,
                               fill=TEXT, tags=(f"meaning:{stage}",))
            x += interface.measure(meaning) + 2 * gap
        canvas.configure(width=x)


class _Log(ReadOnlyText):
    """The branch lines' text, which keeps only its newest lines."""

    def keep_last(self, lines):
        extra = int(self.index("end-1c").split(".")[0]) - 1 - lines
        if extra > 0:
            self.tk.call(self._original, "delete", "1.0", f"{extra + 1}.0")


class PipelineWindow(ToolWindow):
    """Tools > Pipeline Simulator."""

    NAME = "Pipeline Simulator"
    HEADING = "Five-Stage Pipeline and Branch Prediction"
    HELP = HELP
    MODEL = PipelineModel

    def __init__(self, app):
        self.settings_window = self.check_window = None
        # The timing whose lines are shown, and its lines made and taken out then.
        self._shown_lines = (None, 0, 0)
        self._stale = False             # the table and the lines wait for the run to stop
        self._fitted = False
        self.usual = self._least = None     # the window's inside: usual and least sizes
        super().__init__(app)
        self.buttons += (self.settings_button, self.check_button)
        default_button(self.connect_button, self.buttons, self.typed)
        for name, _ in TOOLBAR:
            key = app._keys.get(name)
            if key:
                for sequence in app._sequences(key):
                    self.window.bind(sequence, lambda event, n=name: app.run(n) or "break")
        self.commands_changed()

    def build(self, body):
        app = self.app
        self.model.written = self._written
        gap = px(body, 5)
        font = app.pane_font
        bar = ttk.Frame(body)
        bar.pack(side="top", fill="x", pady=(0, gap))
        self.tool_buttons = {}
        for name, tip in TOOLBAR:
            normal, disabled = app.images[name]
            button = ttk.Button(bar, image=(normal, "disabled", disabled), style="Toolbutton",
                                takefocus=False, command=lambda n=name: app.run(n))
            button.pack(side="left")
            key = app._keys.get(name)
            Tooltip(button, f"{tip} ({app._accelerator(key)})" if key else tip)
            self.tool_buttons[name] = button
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=gap)
        self.settings_button = ttk.Button(bar, text="Settings...", command=self.open_settings)
        self.check_button = ttk.Button(bar, text="Check Dependency", command=self.open_check)
        self.settings_button.pack(side="left", padx=(0, px(body, 3)))
        self.check_button.pack(side="left")
        Tooltip(self.settings_button, "Forwarding, the stages that decide branches and jumps, "
                                      "and branch prediction")
        Tooltip(self.check_button, "Corrected Program Code: the program with the NOPs a "
                                   "pipeline without stalls would need")

        numbers_row = ttk.Frame(body)
        numbers_row.pack(side="top", fill="x")
        self.fields, self.number_tips = [], []
        for column, (label, width) in enumerate(FIELDS):
            title = ttk.Label(numbers_row, text=label)
            title.grid(row=0, column=2 * column, sticky="w",
                       padx=(2 * gap if column else 0, px(body, 2)))
            variable = tk.StringVar(master=body)
            field = ttk.Entry(numbers_row, textvariable=variable, state="readonly", width=width,
                              justify="right", takefocus=False)
            field.grid(row=0, column=2 * column + 1, sticky="w")
            self.fields.append(variable)
            self.number_tips.append((Tooltip(title, ""), Tooltip(field, "")))
        self.summary = ttk.Label(body, text="")
        self.summary.pack(side="top", anchor="w", pady=(px(body, 3), gap))

        ttk.Label(body, text="Branches").pack(side="top", anchor="w")
        page = sunken(tk.Frame(body))
        page.pack(side="top", fill="x")
        self.log = text = _Log(page, font=font, wrap="none", height=LOG_LINES, background=FIELD,
                               foreground=TEXT, borderwidth=0, highlightthickness=0,
                               padx=px(body, 4), pady=px(body, 2))
        tab_moves_on(text)
        yscroll = ttk.Scrollbar(page, orient="vertical", command=text.yview)
        xscroll = ttk.Scrollbar(page, orient="horizontal", command=text.xview)
        text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)
        ring = page.winfo_pixels(page.cget("borderwidth"))
        page.configure(width=1, height=LOG_LINES * font.metrics("linespace")
                       + 2 * (ring + text.winfo_pixels(text.cget("pady"))))
        page.grid_propagate(False)
        self.bars = HidingBars(text, yscroll, xscroll)

        ttk.Label(body, text="Reservation table").pack(side="top", anchor="w", pady=(gap, 0))
        self.table = ReservationTable(body, font)
        self.table.frame.pack(side="top", fill="both", expand=True)
        self.key = Key(body, font, self.table.cell, self.table.row_height)
        # Packed before the table, at the bottom: the table takes the room left.
        self.key.canvas.pack(side="bottom", anchor="w", pady=(gap, 0), before=self.table.frame)

    def _written(self, program, address):
        """The instruction at address of program as the student wrote it, while program is
        the one loaded (the Source column shows its lines); None elsewhere."""
        app = self.app
        return app.written(address) if program is app.program else None

    # What the window shows --------------------------------------------------------

    def show(self):
        if not self._fitted:
            self._fit()
        model = self.model
        for variable, text in zip(self.fields, numbers(model.totals, model.settings)):
            if variable.get() != text:
                variable.set(text)
        for pair, text in zip(self.number_tips, tips(model.totals, model.settings)):
            for tip in pair:
                tip.set_text(text)
        summary = "Settings: " + model.settings.summary()
        if model.counted_from:
            summary += f" (the numbers count from instruction {model.counted_from + 1:,})"
        if str(self.summary.cget("text")) != summary:
            self.summary.configure(text=summary)
        if self._racing():
            self._stale = True          # the newest lines and rows would pass too fast to read
            return
        self._stale = False
        self._show_lines()
        if not model.connected:
            message = EMPTY[False]
        elif model.machine is None:
            message = EMPTY[None]
        else:
            message = EMPTY[True]
        self.table.show(model.rows(), message)

    def _racing(self):
        """True while the program runs at full speed."""
        runner = self.app.runner
        return (runner is not None and runner.state is State.RUNNING
                and self.app.run_speed is None)

    def _show_lines(self):
        """Show the newest branch lines (at most pipeline.LINES): those made since the last
        time are added; all are written again for other numbers, or once a Backstep has
        taken lines out."""
        model, text = self.model, self.log
        timing = model.timing
        lines = timing.lines
        shown, before, cut = self._shown_lines
        again = shown is not timing or cut != timing.cut_lines
        self._shown_lines = (timing, timing.branches, timing.cut_lines)
        if again:
            text.clear()
            before = timing.branches - min(len(lines), pipeline.LINES)
        new = min(timing.branches - before, len(lines), pipeline.LINES)
        if new > 0:
            if new == pipeline.LINES:
                text.clear()
            named = model.namer()
            text.write("".join(line_text(timing.line(entry, named)) + "\n"
                               for entry in islice(lines, len(lines) - new, None)))
            text.keep_last(pipeline.LINES)
            text.see_end()
        if new > 0 or again:
            self.bars.schedule()

    def _fit(self):
        """The window's usual size, the table showing VISIBLE_ROWS rows and VISIBLE_CYCLES
        cycles, fewer where the window would not fit the screen it opens on; and its least
        size, the table showing LEAST_ROWS and LEAST_CYCLES (the line of numbers keeps the
        width). The window keeps asking for its usual size while its contents ask for the
        least: so it opens at the usual size and can be made as small as the least without
        cutting anything off."""
        self._fitted = True
        window, root, table = self.window, self.app.root, self.table
        window.update_idletasks()
        frame = frame_of(root)
        middle = (root.winfo_rootx() + frame[2] // 2, root.winfo_rooty() + frame[3] // 2)
        left, top, right, bottom = screen_area(root, *middle)
        side, title = frame[4], frame[5]
        wide = window.winfo_reqwidth() - (right - left - 2 * side)
        high = window.winfo_reqheight() - (bottom - top - title - side)
        if wide > 0 or high > 0:
            table.shrink(max(0, wide), max(0, high))
            window.update_idletasks()
        self.usual = (window.winfo_reqwidth(), window.winfo_reqheight())
        table.ask(LEAST_ROWS, LEAST_CYCLES)
        window.update_idletasks()
        self._least = (min(self.usual[0], window.winfo_reqwidth()),
                       min(self.usual[1], window.winfo_reqheight()))
        window.pack_propagate(False)
        window.configure(width=self.usual[0], height=self.usual[1])

    def min_size(self):
        """The least size: the table showing LEAST_ROWS rows (see _fit())."""
        return self._least if self._least is not None else super().min_size()

    # The buttons ---------------------------------------------------------------------

    def open_settings(self):
        if self.settings_window is not None:
            self.settings_window.lift()
        else:
            self.settings_window = SettingsWindow(self)

    def open_check(self):
        if self.check_window is not None:
            self.check_window.refresh()
            self.check_window.lift()
        else:
            self.check_window = CheckWindow(self)

    def confirm(self, settings):
        """Confirm Settings: work everything out again for settings."""
        if self.model.configure(settings):
            self.show()
            if self.check_window is not None:
                self.check_window.refresh()

    # Called by the main window ----------------------------------------------------------

    def commands_changed(self):
        """The main window's commands changed: Assemble, Step and Backstep follow them."""
        if self.window is None:
            return
        for name, button in self.tool_buttons.items():
            button.state(["!disabled"] if self.app.is_enabled(name) else ["disabled"])

    def refresh(self):
        """Show what the program did since the last refresh; the lines and the table only once
        a run at full speed has stopped."""
        if self.model.update() or (self._stale and not self._racing()):
            self.show()

    def machine_changed(self, machine):
        super().machine_changed(machine)
        if self.check_window is not None:
            self.check_window.refresh()      # another program, or none

    def close(self):
        if self.window is not None:
            self.table.hide_tip()
            for window in (self.settings_window, self.check_window):
                if window is not None:
                    window.close()
        super().close()


class SettingsWindow:
    """Settings...: the settings in three groups, as the source tool has them. Confirm Settings
    works the numbers out again for them; Reset Default Settings puts back the first ones, to be
    confirmed; Escape and the title bar's close button leave the settings as they were. The
    choices that do not apply are gray. Each choice has a name; what a name does not say goes
    into its tip (TIPS)."""

    TITLE = "Pipeline Simulator Settings"
    LADDER = ("State 0 <--> State 1 <--> State 2 <--> State 3\n"
              "States 0, 1: not taken; 2, 3: taken")
    TIPS = {
        "same_cycle": "Without forwarding, may WB and ID use the registers in the same cycle?\n"
                      "Yes: an instruction's ID may share the WB cycle of the one it waits for",
        "branch_stage": "The stage in which a branch (B with a condition) updates the PC",
        "jump_stage": "The stage in which a jump (B or BL without a condition) updates the PC",
        "ladder": "States 0 and 1 predict not taken, states 2 and 3 taken. A taken branch\n"
                  "moves its state one to the right, a branch not taken one to the left",
    }

    def __init__(self, tool):
        self.tool = tool
        parent = tool.window
        self.window = window = tk.Toplevel(parent)
        window.withdraw()
        window.title(self.TITLE)
        window.transient(parent)
        window.resizable(False, False)
        gap = px(window, 6)
        content = ttk.Frame(window, padding=px(window, 8))
        content.pack(fill="both", expand=True)
        self.variables = {
            "forwarding": tk.IntVar(master=window), "same_cycle": tk.IntVar(master=window),
            "branch_stage": tk.IntVar(master=window), "jump_stage": tk.IntVar(master=window),
            "prediction": tk.StringVar(master=window), "static_taken": tk.IntVar(master=window),
            "bits": tk.IntVar(master=window), "first_state_1": tk.IntVar(master=window),
            "first_state_2": tk.IntVar(master=window), "one_state": tk.IntVar(master=window)}
        self.parts = {}                 # name -> the widgets of its choice
        self.tips = {}                  # name -> the tip of its choice's name (TIPS)
        left, right = ttk.Frame(content), ttk.Frame(content)
        left.grid(row=0, column=0, sticky="nsew")
        right.grid(row=0, column=1, sticky="nsew", padx=(gap, 0))
        data = group(left, "Data dependency")
        data.pack(side="top", fill="x")
        self._choice(data, "forwarding", "Data forwarding:", ((0, "No"), (1, "Yes")))
        self._choice(data, "same_cycle", "WB and ID in the same cycle:", ((0, "No"), (1, "Yes")))
        control = group(left, "Control dependency")
        control.pack(side="top", fill="x", pady=(gap, 0))
        self._choice(control, "branch_stage", "Branch stage:",
                     ((ID, "ID"), (EX, "EX"), (MEM, "MEM")))
        self._choice(control, "jump_stage", "Jump stage:", ((ID, "ID"), (EX, "EX")))
        guess = group(right, "Branch prediction")
        guess.pack(side="top", fill="both", expand=True)
        self._choice(guess, "prediction", "Prediction:",
                     ((NONE, "No prediction"), (STATIC, "Static"), (DYNAMIC, "Dynamic")))
        self._choice(guess, "static_taken", "Static prediction:",
                     ((1, "Always taken"), (0, "Always not taken")))
        self._choice(guess, "bits", "Dynamic prediction:", ((1, "1 bit"), (2, "2 bits")))
        self._choice(guess, "first_state_1", "First state with 1 bit:",
                     ((0, "State 0 (not taken)"), (1, "State 1 (taken)")))
        self._choice(guess, "first_state_2", "First state with 2 bits:",
                     ((0, "State 0"), (1, "State 1"), (2, "State 2"), (3, "State 3")))
        self.ladder = ttk.Label(guess, text=self.LADDER)
        self.ladder.pack(side="top", anchor="w", pady=(px(window, 2), 0))
        self.tips["ladder"] = Tooltip(self.ladder, self.TIPS["ladder"])
        self.one_state = ttk.Checkbutton(guess, text="One state for all branches",
                                         variable=self.variables["one_state"],
                                         command=self._grey)
        self.one_state.pack(side="top", anchor="w", pady=(gap, 0))
        row = ttk.Frame(content)
        row.grid(row=1, column=0, columnspan=2, sticky="e", pady=(2 * gap, 0))
        self.reset_button = ttk.Button(row, text="Reset Default Settings",
                                       command=self.reset_defaults)
        self.confirm_button = ttk.Button(row, text="Confirm Settings", command=self.confirm)
        self.reset_button.pack(side="left", padx=(0, gap))
        self.confirm_button.pack(side="left")
        self.buttons = (self.reset_button, self.confirm_button)
        default_button(self.confirm_button, self.buttons)
        window.bind("<Return>", self._return)
        window.bind("<KP_Enter>", self._return)
        window.bind("<Escape>", lambda event: self.close())
        window.protocol("WM_DELETE_WINDOW", self.close)
        self.put(tool.model.settings)
        place_over(window, parent)
        window.deiconify()
        self.confirm_button.focus_set()

    def _choice(self, master, name, label, options):
        frame = ttk.Frame(master)
        frame.pack(side="top", fill="x", pady=(px(master, 3), 0))
        title = ttk.Label(frame, text=label)
        title.pack(side="top", anchor="w")
        if name in self.TIPS:
            self.tips[name] = Tooltip(title, self.TIPS[name])
        buttons = ttk.Frame(frame)
        buttons.pack(side="top", anchor="w", padx=(px(master, 12), 0))
        widgets = [title]
        for value, text in options:
            button = ttk.Radiobutton(buttons, text=text, value=value,
                                     variable=self.variables[name], command=self._grey)
            button.pack(side="left", padx=(0, px(master, 8)))
            widgets.append(button)
        self.parts[name] = widgets

    def put(self, settings):
        """Show settings in the choices."""
        for name, variable in self.variables.items():
            value = getattr(settings, name)
            variable.set(value if isinstance(value, str) else int(value))
        self._grey()

    def settings(self):
        """The settings the choices show."""
        values = {name: variable.get() for name, variable in self.variables.items()}
        for name in ("forwarding", "same_cycle", "static_taken", "one_state"):
            values[name] = bool(values[name])
        return Settings(**values)

    def _grey(self):
        values = {name: variable.get() for name, variable in self.variables.items()}
        dynamic = values["prediction"] == DYNAMIC
        on = {"same_cycle": not values["forwarding"],
              "static_taken": values["prediction"] == STATIC, "bits": dynamic,
              "first_state_1": dynamic and values["bits"] == 1,
              "first_state_2": dynamic and values["bits"] == 2}
        for name, enabled in on.items():
            for widget in self.parts[name]:
                widget.state(["!disabled"] if enabled else ["disabled"])
        state = ["!disabled"] if on["first_state_2"] else ["disabled"]
        self.ladder.state(state)
        self.one_state.state(["!disabled"] if dynamic else ["disabled"])

    def _return(self, event):
        button = event.widget if event.widget in self.buttons else self.confirm_button
        button.invoke()
        return "break"

    def reset_defaults(self):
        self.put(Settings())

    def confirm(self):
        settings = self.settings()
        self.close()
        self.tool.confirm(settings)

    def lift(self):
        self.window.deiconify()
        self.window.lift()
        self.confirm_button.focus_set()

    def close(self):
        if self.window is not None:
            self.window.destroy()
            self.window = None
            self.tool.settings_window = None


class CheckWindow:
    """Check Dependency: Corrected Program Code, the program as it is written with the NOPs a
    pipeline without any stalling or flushing hardware would need under the settings, each
    marked as added by the checker, under one line that counts them.

    It opens with room for CHECK_SIZE lines and can be made larger or maximized, the list
    taking the room, or smaller down to CHECK_LEAST lines (usual and least sizes, as the
    Pipeline Simulator's window has them). It has no button: Escape and its close box close
    it."""

    TITLE = "Corrected Program Code"
    MARK = "@ added by the checker"
    NOTHING = "No program assembled"

    def __init__(self, tool):
        self.tool = tool
        parent = tool.window
        self.window = window = tk.Toplevel(parent)
        window.withdraw()
        window.title(self.TITLE)
        window.transient(parent)
        window.resizable(True, True)
        content = ttk.Frame(window, padding=px(window, 6))
        content.pack(fill="both", expand=True)
        font = tool.app.pane_font
        self.count_label = ttk.Label(content, text="")
        self.count_label.pack(side="top", anchor="w", pady=(0, px(window, 5)))
        page = sunken(tk.Frame(content))
        page.pack(side="top", fill="both", expand=True)
        columns, lines = CHECK_SIZE
        self.text = text = ReadOnlyText(page, font=font, wrap="none", width=columns,
                                        height=lines, background=FIELD, foreground=TEXT,
                                        borderwidth=0, highlightthickness=0, padx=px(window, 4),
                                        pady=px(window, 2))
        text.tag_configure("added", foreground=ADDED)
        tab_moves_on(text)
        yscroll = ttk.Scrollbar(page, orient="vertical", command=text.yview)
        xscroll = ttk.Scrollbar(page, orient="horizontal", command=text.xview)
        text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)
        self.bars = HidingBars(text, yscroll, xscroll)
        window.bind("<Escape>", lambda event: self.close())
        window.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()
        self._sizes()
        place_over(window, parent)
        window.minsize(*self.least)
        window.bind("<Map>", self._mapped, add="+")
        window.deiconify()
        text.focus_set()                # the window's keys, Escape among them, reach it

    def _sizes(self):
        """usual and least, the window's inside with CHECK_SIZE and CHECK_LEAST lines of the
        list; it keeps asking for the usual size while its contents ask for the least."""
        window, text = self.window, self.text
        window.update_idletasks()
        self.usual = (window.winfo_reqwidth(), window.winfo_reqheight())
        text.configure(height=CHECK_LEAST)
        window.update_idletasks()
        self.least = (window.winfo_reqwidth(), window.winfo_reqheight())
        window.pack_propagate(False)
        window.configure(width=self.usual[0], height=self.usual[1])

    def _mapped(self, event):
        if event.widget is self.window:
            give_maximize_box(self.window)

    def refresh(self):
        """Check the program observed now under the settings in force."""
        if self.window is None:
            return
        model, text = self.tool.model, self.text
        text.clear()
        result = model.check(self.tool.app.program)
        if result is None:
            self.count_label.configure(text=self.NOTHING)
            self.bars.schedule()
            return
        program, lines, added = result
        labels = {}
        for label in program.labels:
            if program.is_code(label.address):
                labels.setdefault(label.address, []).append(label.name)
        for line in lines:
            if line.added:
                text.write(f"{'':12}{'NOP':<28}{self.MARK}\n", "added")
                continue
            for name in labels.get(line.address, ()):
                text.write(f"{name}:\n")
            text.write(f"0x{line.address:08x}  {line.text}\n")
        self.count_label.configure(text=f"NOPs added: {added:,}")
        self.bars.schedule()

    def lift(self):
        self.window.deiconify()
        self.window.lift()
        self.text.focus_set()

    def close(self):
        if self.window is not None:
            self.window.destroy()
            self.window = None
            self.tool.check_window = None


WINDOW = PipelineWindow
