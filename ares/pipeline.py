# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Pipeline Simulator's timing, without a window.

The program runs as always; this module works out in which clock cycle each instruction it
executed would be in each stage of a five-stage pipeline, IF, ID, EX, MEM and WB, under the
settings (Settings). The settings never change what the program does, only the timing.

Every instruction takes one cycle in each stage. f, d, e, m and w of an instruction are the
cycles in which it leaves IF, ID, EX, MEM and WB. An instruction waits only in IF and in ID,
so e = d + 1, m = d + 2 and w = d + 3: d alone says where it is. In order:

- the first instruction leaves IF in cycle 1 and ID in cycle 2;
- an instruction cannot leave IF before the one ahead of it leaves ID, nor ID before the cycle
  after it left IF: without anything else, d = d of the one ahead + 1;
- data: a value an instruction reads must be ready. Without forwarding the reader's ID comes
  after the writer's WB (d >= w + 1), or in the same cycle when the setting allows it
  (d >= w). With forwarding a result is ready after EX and a value loaded from memory after
  MEM: the reader's EX comes after them (d >= d of the writer + 1, + 2 after a load). A PC
  write decided in ID needs its register in ID: one cycle earlier with forwarding;
- flags are written at the end of EX of the instruction that sets them. A conditional branch
  decided in ID needs them in ID: d >= e of the setter + 1; decided in EX or MEM it never waits,
  nor does any other conditional instruction, which checks its condition in EX;
- control, with S = 1, 2 or 3 for a branch decided in ID, EX or MEM: without prediction nothing
  is fetched until the branch is decided, S cycles; with prediction (made at the end of ID) a
  right guess costs 0 (not taken) or 1 (taken: the instruction fetched in line is thrown
  away), a wrong one S, and with S = 1 the outcome itself is used: 1 if taken, 0 if not. A
  jump (B or BL without a condition) costs 1 or 2 (ID or EX), always. Any other instruction
  that writes the PC is taken always and never predicted: S, or 3 when the PC comes from
  memory.

The cycles are the last instruction's w: instructions + 4 + the cycles lost, each counted once,
as a stall when nothing was fetched in it, as a flush when instructions thrown away were.

Two ways give the same cycles. The plain way (Pipeline) takes one instruction at a time and
makes the rows of the reservation table, with the instructions thrown away read from memory
(flushed rows). The fast way (Timing) takes a stretch of straight-line code at once (a Block,
which ends at most with one instruction that changes the flow): it works out the stretch once
for each state in which it can start, and keeps the answer. That state is when each register
and the flags become ready, counted from the cycle at the stretch's start, so the answer holds
whenever the stretch starts that way. The tool watches the blocks the program executes
(ares.observers) and gives them to the fast way, so it costs Python time per block, never per
instruction.

Backstep takes instructions out again (Timing.undo()): tail keeps, for each of the newest
blocks, the state of the timing before it, for as many instructions as the main window can
step back (machine.HISTORY_LIMIT) and the rows of the table after them. The numbers, the
predictor and the branch lines go back block by block, and a block cut in its middle runs
again in part, so a Backstep costs time for the instructions it undoes, never for the whole
run. Record.undo() takes them out of the run kept for other settings too.

An instruction is named as the student wrote it where written(address) gives that text (the
window gives it: the Source column's statement), else by its Basic form: in the rows, the
tips, the branch lines and the checker's program.

check() is the dependency checker: the program in the order it is written, with the NOPs a
pipeline without any stalling or flushing hardware would need under the settings.
"""

import re
import struct
from array import array
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from itertools import islice

from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_OPT_SYNTAX_NOREGNAME, Cs
from capstone import arm_const as arm

from . import syscalls
from .disasm import basic, data_word
from .machine import HISTORY_LIMIT

MASK = 0xFFFFFFFF
STAGES = ("IF", "ID", "EX", "MEM", "WB")
STALL = "stall"
FLUSH = "Flush"
FILL = 4                        # the cycles that fill the pipeline: n instructions take n + 4
ID, EX, MEM = 1, 2, 3           # a stage that decides a branch, by the cycles it costs
STAGE_NAMES = {ID: "ID", EX: "EX", MEM: "MEM"}
NO_INSTRUCTION = "no instruction here"

# The kinds of instruction, for the timing.
PLAIN = "plain"
BRANCH = "branch"               # B or BL with a condition: may be predicted
JUMP = "jump"                   # B or BL without a condition
PC_WRITE = "PC write"           # BX, MOV PC, LDR PC, POP {..., PC} ...: taken always, not predicted
KINDS = (PLAIN, BRANCH, JUMP, PC_WRITE)

# Branch prediction.
NONE, STATIC, DYNAMIC = "none", "static", "dynamic"

# The registers, as units of the timing: R0 to R15 (the PC is never waited for), S0 to S31
# (D0 to D15 are pairs of them, as the processor keeps them), D16 to D31, and FPSCR's flags.
SP, LR, PC = 13, 14, 15
S_BASE = 16
D_HIGH = 48
FPSCR = 64
UNIT_NAMES = tuple([f"R{n}" for n in range(13)] + ["SP", "LR", "PC"]
                   + [f"S{n}" for n in range(32)] + [f"D{n}" for n in range(16, 32)] + ["FPSCR"])

BATCH = 1 << 15                 # blocks the tool takes in at once while a program runs
ROWS = 500                      # rows of the table, the newest
LINES = 1000                    # branch lines shown, the newest
# Blocks and branch lines the fast way keeps: enough for the rows and the lines shown after
# Backstep has taken out as many instructions as it can undo.
TAIL = HISTORY_LIMIT + 640
KEPT_LINES = HISTORY_LIMIT + LINES
LEAD = 8                        # instructions worked out before the first row of the table
LIMIT = 1_000_000               # instructions kept for working the numbers out again
PART = 100_000                  # instructions of a part of what is kept


@dataclass(frozen=True)
class Settings:
    """The settings, as the source tool has them, and one more: one_state, a single
    predictor state for all branches (the source tool's way) instead of one per branch."""
    forwarding: bool = False
    same_cycle: bool = False    # without forwarding: WB and ID may use the registers in one cycle
    branch_stage: int = EX      # where a branch updates the PC: ID, EX or MEM
    jump_stage: int = ID        # where a jump updates the PC: ID or EX
    prediction: str = NONE      # NONE, STATIC or DYNAMIC
    static_taken: bool = True   # static prediction: always taken, or always not taken
    bits: int = 1               # dynamic prediction: 1 or 2 bits
    first_state_1: int = 0      # the first state of 1-bit prediction: 0 or 1
    first_state_2: int = 0      # of 2-bit prediction: 0 to 3
    one_state: bool = False

    @property
    def first_state(self):
        return self.first_state_1 if self.bits == 1 else self.first_state_2

    def summary(self):
        """The settings in a line, as the window shows them."""
        if self.forwarding:
            data = "forwarding"
        elif self.same_cycle:
            data = "no forwarding, WB and ID in one cycle"
        else:
            data = "no forwarding"
        if self.prediction == NONE:
            guess = "no prediction"
        elif self.prediction == STATIC:
            guess = "static prediction, always " + ("taken" if self.static_taken else "not taken")
        else:
            guess = (f"{self.bits}-bit prediction from state {self.first_state}"
                     + (", one state for all branches" if self.one_state else ""))
        return (f"{data}; branch decided in {STAGE_NAMES[self.branch_stage]}, jump in "
                f"{STAGE_NAMES[self.jump_stage]}; {guess}")


def offsets(settings):
    """How many cycles after the writer leaves ID a reader may leave it: (for an ordinary
    reader, the same after a load, for a PC write decided in ID, the same after a load)."""
    if settings.forwarding:
        return 1, 2, 2, 3
    wait = 3 if settings.same_cycle else 4
    return wait, wait, wait, wait


def predict(settings, state):
    """(prediction, the state after a taken branch, after one not taken) for a state of the
    dynamic predictor; the static prediction for state None."""
    if state is None:
        return settings.static_taken, None, None
    if settings.bits == 1:
        return state == 1, 1, 0
    return state >= 2, min(3, state + 1), max(0, state - 1)


# Decoding --------------------------------------------------------------------------------

@dataclass(frozen=True)
class Info:
    """What the timing needs of an instruction."""
    word: int
    text: str           # as the Text Segment's Basic column shows it
    kind: str           # PLAIN, BRANCH, JUMP or PC_WRITE
    reads: tuple        # the units it reads (its registers; the PC as a value never waits)
    writes: tuple       # the units it writes (not the PC)
    loaded: frozenset   # those of writes that come from memory
    sets_flags: bool
    conditional: bool
    target: int = None  # B and BL: where they go
    from_memory: bool = False   # a PC write whose new PC comes from memory

    def decided_in_id(self, settings):
        """True when it changes the flow in ID and so needs its register and flags there."""
        if self.kind == BRANCH:
            return settings.branch_stage == ID
        return self.kind == PC_WRITE and not self.from_memory and settings.branch_stage == ID


def _d_units(n):
    return (S_BASE + 2 * n, S_BASE + 2 * n + 1) if n < 16 else (D_HIGH + n - 16,)


def _register_units():
    table = {getattr(arm, f"ARM_REG_R{n}"): (n,) for n in range(13)}
    table.update({arm.ARM_REG_SP: (SP,), arm.ARM_REG_LR: (LR,), arm.ARM_REG_PC: (PC,),
                  arm.ARM_REG_FPSCR: (FPSCR,), arm.ARM_REG_FPSCR_NZCV: (FPSCR,)})
    for n in range(32):
        table[getattr(arm, f"ARM_REG_S{n}")] = (S_BASE + n,)
        table[getattr(arm, f"ARM_REG_D{n}")] = _d_units(n)
    for n in range(16):
        table[getattr(arm, f"ARM_REG_Q{n}")] = _d_units(2 * n) + _d_units(2 * n + 1)
    return table


_REGISTER_UNITS = _register_units()
_SERVICE_REGISTER = re.compile(r"\b([RSD])(\d+) = ")
_capstone = Cs(CS_ARCH_ARM, CS_MODE_ARM)
_capstone.detail = True
_capstone.syntax = CS_OPT_SYNTAX_NOREGNAME


def _units(registers):
    found = set()
    for register in registers:
        found.update(_REGISTER_UNITS.get(register, ()))
    return found


def service_units(text):
    """The units a system call's description names: "R0 = integer, S0 = float"."""
    units = []
    for bank, number in _SERVICE_REGISTER.findall(text):
        number = int(number)
        units += ([number] if bank == "R" else [S_BASE + number] if bank == "S"
                  else list(_d_units(number)))
    return tuple(units)


def sets_flags(word):
    """True when the instruction writes the condition flags N, Z, C and V (an S, a compare,
    MSR to the flags, VMRS APSR_nzcv, a return that restores CPSR)."""
    if word >> 28 == 0xF:
        return False
    op = word >> 25 & 7
    if op in (0, 1):
        if op == 0 and word & 0x90 == 0x90:         # multiplies, swaps, extra loads and stores
            return word >> 5 & 3 == 0 and word >> 24 & 0xF == 0 and bool(word >> 20 & 1)
        opcode, s = word >> 21 & 0xF, word >> 20 & 1
        if 8 <= opcode <= 11 and not s:             # MRS, MSR, BX, CLZ and others
            if opcode != 0b1001 or (op == 0 and word >> 4 & 0xF):
                return False
            return bool(word >> 19 & 1)             # MSR CPSR_f / APSR_nzcvq
        return bool(s)
    if op == 0b100:                                 # LDM with ^ and the PC restores CPSR
        return bool(word >> 22 & 1 and word >> 20 & 1 and word >> 15 & 1)
    return word & 0x0FFFFFFF == 0x0EF1FA10          # VMRS APSR_nzcv, FPSCR


def is_load(word):
    """True for an instruction that loads registers from memory."""
    if word >> 28 == 0xF:
        return False
    op = word >> 25 & 7
    if op in (2, 3):
        return not (op == 3 and word >> 4 & 1) and bool(word >> 20 & 1)
    if op == 0 and word & 0x90 == 0x90 and word >> 5 & 3:   # LDRH, LDRSB, LDRSH, LDRD
        return bool(word >> 20 & 1) or word >> 5 & 3 == 2
    if op == 0 and word & 0x0FB000F0 == 0x01000090:         # SWP, SWPB
        return True
    if op == 0 and word & 0x0F8000F0 == 0x01800090:         # LDREX ...
        return bool(word >> 20 & 1)
    return op in (4, 6) and bool(word >> 20 & 1)            # LDM, POP; VLDR, VLDM, VPOP


def _written_back(word):
    """The base register a load or store writes back (as a set of units)."""
    op, base = word >> 25 & 7, word >> 16 & 0xF
    if op in (0, 2, 3):
        if word >> 24 & 1 == 0 or word >> 21 & 1:
            return {base}
    elif op in (4, 6) and word >> 21 & 1:
        return {base}
    return set()


def _vfp_multiple(word):
    """(reads, writes) of VLDM, VSTM, VPUSH and VPOP (Capstone leaves out some of them)."""
    base, count = word >> 16 & 0xF, word & 0xFF
    if word >> 8 & 1:                               # doubles
        first = (word >> 22 & 1) << 4 | word >> 12 & 0xF
        registers = {unit for n in range(first, min(32, first + count // 2))
                     for unit in _d_units(n)}
    else:
        first = (word >> 12 & 0xF) << 1 | word >> 22 & 1
        registers = {S_BASE + n for n in range(first, min(32, first + count))}
    reads, writes = {base}, ({base} if word >> 21 & 1 else set())
    if word >> 20 & 1:
        writes |= registers
    else:
        reads |= registers
    return reads, writes


# P, U and W of VLDM and VSTM (VPUSH, VPOP): increment after, with or without write-back, and
# decrement before with write-back. VLDR and VSTR have P = 1, W = 0.
_MULTIPLE = ((0, 1, 0), (0, 1, 1), (1, 0, 1))


def _corrected(word, reads, writes):
    """Capstone's register access, with what it leaves out put in."""
    op = word >> 25 & 7
    if word & 0x0FFFFFD0 == 0x012FFF10:             # BX, BLX register: Rm
        reads.add(word & 0xF)
        writes.add(PC)
    elif op == 0 and word & 0x0FA000F0 == 0x00A00090:   # UMLAL, SMLAL: the sum read too
        reads |= {word >> 12 & 0xF, word >> 16 & 0xF}
    elif op == 0 and word & 0x0FF000F0 == 0x00400090:   # UMAAL
        reads |= {word >> 12 & 0xF, word >> 16 & 0xF}
    elif op == 6 and word >> 9 & 7 == 0b101 and (word >> 24 & 1, word >> 23 & 1,
                                                  word >> 21 & 1) in _MULTIPLE:
        return _vfp_multiple(word)
    elif word & 0x0FFF0FFF == 0x0EE10A10:           # VMSR FPSCR, Rt
        reads.add(word >> 12 & 0xF)
        writes.add(FPSCR)
    elif op == 7 and word >> 24 & 1 == 0 and word >> 4 & 1 and word >> 9 & 7 != 0b101:
        rt = word >> 12 & 0xF                       # MRC writes Rt, MCR reads it
        if word >> 20 & 1:
            reads.discard(rt)
            if rt != PC:
                writes.add(rt)
        else:
            reads.add(rt)
    return reads, writes


@lru_cache(maxsize=1 << 16)
def decode(word, address):
    """The Info of the instruction word at address."""
    text = basic(word, address)
    cond = word >> 28
    conditional = cond < 0xE
    if word >> 25 & 7 == 0b101:                     # B, BL, BLX label
        offset = ((word & 0xFFFFFF) ^ 0x800000) - 0x800000
        target = (address + 8 + 4 * offset) & MASK
        link = (LR,) if word >> 24 & 1 or cond == 0xF else ()
        if cond == 0xF:                             # BLX label: on in Thumb code
            return Info(word, text, PC_WRITE, (), link, frozenset(), False, False)
        return Info(word, text, JUMP if cond == 0xE else BRANCH, (), link, frozenset(), False,
                    conditional, target)
    found = next(_capstone.disasm(struct.pack("<I", word), address, 1), None)
    if found is None:                               # no instruction: it would stop the program
        return Info(word, text, PLAIN, (), (), frozenset(), False, conditional)
    read_ids, write_ids = found.regs_access()
    reads, writes = _corrected(word, _units(read_ids), _units(write_ids))
    if found.id == arm.ARM_INS_SVC:                 # the registers of its service
        entry = syscalls.SERVICES.get(word & 0xFFFFFF)
        reads = set(service_units(entry.arguments)) if entry else set()
        writes = set(service_units(entry.result)) if entry else set()
    to_pc = PC in writes
    reads.discard(PC)
    writes.discard(PC)
    load = is_load(word)
    loaded = frozenset(writes - _written_back(word)) if load else frozenset()
    return Info(word, text, PC_WRITE if to_pc else PLAIN, tuple(sorted(reads)),
                tuple(sorted(writes)), loaded, sets_flags(word), conditional,
                from_memory=to_pc and load)


def instruction_text(word, address, code):
    """What a row shows for the word at address: the instruction, or the word as data when it
    is no code (a literal), or NO_INSTRUCTION where there is no memory (word None)."""
    if word is None:
        return NO_INSTRUCTION
    return basic(word, address) if code else data_word(word)


# The rows of the table: the plain way -------------------------------------------------

@dataclass(frozen=True)
class Row:
    """A row of the reservation table: an instruction executed, or one fetched and thrown away
    (flushed). text names it (as written where there is a source line), basic is its Basic
    form (or the word as data). cells holds the stage of each cycle from first on: a stage
    of STAGES, STALL or FLUSH. hold says why it waits before IF, wait why it waits in ID, and
    note why a flushed row was thrown away."""
    address: int
    text: str
    flushed: bool
    first: int
    fetched: int        # the cycle in which it leaves IF
    decoded: int        # the cycle in which it leaves ID (flushed: its last cycle in the pipeline)
    cells: tuple
    hold: str = ""
    wait: str = ""
    note: str = ""
    basic: str = ""

    @property
    def last(self):
        return self.first + len(self.cells) - 1

    def cell(self, cycle):
        """The stage in cycle, or "" outside the row."""
        index = cycle - self.first
        return self.cells[index] if 0 <= index < len(self.cells) else ""

    def tip(self, cycle):
        """What the mouse over the cell of cycle shows: why it waits, or why it was flushed."""
        stage = self.cell(cycle)
        if stage == STALL:
            return self.hold if cycle < self.fetched else self.wait
        if stage == FLUSH:
            return self.note
        return ""


@dataclass(frozen=True)
class Line:
    """A branch executed, for the branch lines: state is the predictor's state before it and
    after it (None for static prediction), predicted None without prediction."""
    address: int
    text: str
    kind: str
    before: object
    predicted: object
    taken: bool
    after: object


def line_text(line):
    """A branch line: the instruction, the state before, the prediction, what happened and
    the state now."""
    outcome = "Taken" if line.taken else "Not taken"
    head = f"[{line.text}] at 0x{line.address:08x}"
    if line.kind == PC_WRITE:
        return f"{head}  Never predicted | Actual: Taken (always)"
    if line.predicted is None:
        return f"{head}  No prediction | Actual: {outcome}"
    guess = "Taken" if line.predicted else "Not taken"
    if line.before is None:
        return f"{head}  [Static]  Prediction: {guess} | Actual: {outcome}"
    return (f"{head}  [State: {line.before}]  Prediction: {guess} | Actual: {outcome}  "
            f"State now: {line.after}")


@dataclass(frozen=True)
class Totals:
    """The numbers of a run."""
    instructions: int = 0
    cycles: int = 0
    stalls: int = 0                 # cycles lost to stalls
    flushes: int = 0                # cycles lost to instructions thrown away
    right: int = 0                  # predictions right
    wrong: int = 0

    @property
    def lost(self):
        return self.stalls + self.flushes

    @property
    def cpi(self):
        return self.cycles / self.instructions if self.instructions else 0.0

    @property
    def steady_cpi(self):
        """The CPI without the cycles that fill the pipeline."""
        return (self.cycles - FILL) / self.instructions if self.instructions else 0.0


def cycles_of(instructions, last):
    """The cycles of a run whose last instruction left ID in cycle last."""
    return last + 3 if instructions else 0


class Pipeline:
    """The plain way: one instruction at a time (feed()), with the rows of the table.

    read(address) gives (word, code) for an instruction thrown away: the word in memory (None
    where there is none) and whether it is code (not a literal). written(address) gives the
    instruction as the student wrote it, or None: its Basic form names it then.
    """

    def __init__(self, settings=Settings(), read=None, written=None):
        self.settings = settings
        self.read = read
        self.written = written
        self.count = 0
        self.stalls = self.flushes = 0
        self.right = self.wrong = 0
        self.lines = []
        self.states = {}                # address -> the predictor's state of its branch
        self.state = settings.first_state
        self.last_d = 1                 # d of the instruction ahead (1 before the first)
        self.last_f = 0                 # f of the row ahead, flushed or not
        self.need = {}                  # unit -> (d an ordinary reader needs, an early one, writer)
        self.flags = (0, None)          # the d a branch decided in ID needs, and the setter
        self.pending = (0, 0, "")       # cycles the next one loses, of them flushed, why it waits
        self._offsets = offsets(settings)

    @classmethod
    def resume(cls, settings, last_d, lost, flushed, state, read=None, written=None):
        """The plain way from the middle of a run, where the fast way had (last_d, lost,
        flushed) and the state (flags, ((unit, ordinary, early), ...)) of Timing; the writers
        before it are not known."""
        pipeline = cls(settings, read, written)
        pipeline.last_d = last_d
        pipeline.pending = (lost, flushed, "")
        start = last_d + lost
        pipeline.last_f = start - 1
        flags, entries = state
        for unit, ordinary, early in entries:
            pipeline.need[unit] = (start + ordinary if ordinary else 0,
                                   start + early if early else 0, None)
        pipeline.flags = (start + flags if flags else 0, None)
        return pipeline

    @property
    def totals(self):
        return Totals(self.count, cycles_of(self.count, self.last_d), self.stalls,
                      self.flushes, self.right, self.wrong)

    def _text(self, address, basic):
        """The instruction at address as written, else basic, its Basic form."""
        written = self.written
        return (written(address) if written is not None else None) or basic

    def feed(self, address, info, taken=False, before=None):
        """The rows of the instruction at address (decoded in info), executed: its own, then
        those of the instructions fetched after it and thrown away. taken says whether a
        branch was taken; before, when given, is the predictor's state the branch found."""
        settings = self.settings
        text = self._text(address, info.text)
        lost, flushed, why = self.pending
        first = self.last_f + 1
        fetched = self.last_d + lost
        lowest = decoded = fetched + 1
        cause = None
        early = info.decided_in_id(settings)
        slot = 1 if early and info.kind == PC_WRITE else 0
        for unit in info.reads:
            entry = self.need.get(unit)
            if entry is not None and entry[slot] > decoded:
                decoded, cause = entry[slot], (UNIT_NAMES[unit], entry[2])
        if info.conditional and early and self.flags[0] > decoded:
            decoded, cause = self.flags[0], ("the flags", self.flags[1])
        self.stalls += decoded - self.last_d - 1 - flushed
        self.flushes += flushed
        self.count += 1
        hold = ""
        if fetched > first:
            hold = why if lost > flushed and why else "waits: the instruction ahead is held in ID"
        wait = ""
        if cause is not None:
            name, writer = cause
            wait = f"waits for {name}"
            if writer is not None:
                wait += f" from {writer[1]} at 0x{writer[0]:08x}"
        cells = ((STALL,) * (fetched - first) + ("IF",) + (STALL,) * (decoded - lowest)
                 + STAGES[1:])
        rows = [Row(address, text, False, first, fetched, decoded, cells, hold, wait,
                    basic=info.text)]
        ordinary, ordinary_load, id_reader, id_load = self._offsets
        writer = (address, text)
        for unit in info.writes:
            if unit in info.loaded:
                self.need[unit] = (decoded + ordinary_load, decoded + id_load, writer)
            else:
                self.need[unit] = (decoded + ordinary, decoded + id_reader, writer)
        if info.sets_flags:
            self.flags = (decoded + 2, writer)
        self.last_d, self.last_f = decoded, fetched
        rows += self._control(address, info, text, taken, before, decoded)
        return rows

    def _control(self, address, info, text, taken, before, decoded):
        """What the instruction (named text) does to the flow: the pending loss of the next
        one, the branch line and the rows thrown away."""
        settings = self.settings
        name = f"{text} at 0x{address:08x}"
        if info.kind == PLAIN:
            self.pending = (0, 0, "")
            return []
        if info.kind == JUMP:
            stage = settings.jump_stage
            self.pending = (stage, 0, f"waits until the jump {name} is decided in "
                                      f"{STAGE_NAMES[stage]}")
            return []
        if info.kind == PC_WRITE:
            stage = MEM if info.from_memory else settings.branch_stage
            self.pending = (stage, 0, f"waits until {name} is decided in {STAGE_NAMES[stage]}")
            self.lines.append(Line(address, text, PC_WRITE, None, None, True, None))
            return []
        stage = settings.branch_stage
        taken = bool(taken)
        if settings.prediction == NONE:
            self.pending = (stage, 0, f"waits until the branch {name} is decided in "
                                      f"{STAGE_NAMES[stage]}")
            self.lines.append(Line(address, text, BRANCH, None, None, taken, None))
            return []
        state = None
        if settings.prediction == DYNAMIC:
            state = before if before is not None else (
                self.state if settings.one_state else self.states.get(address,
                                                                      settings.first_state))
        predicted, if_taken, if_not = predict(settings, state)
        after = if_taken if taken else if_not
        if settings.prediction == DYNAMIC:
            if settings.one_state:
                self.state = after
            else:
                self.states[address] = after
        if predicted == taken:
            self.right += 1
        else:
            self.wrong += 1
        self.lines.append(Line(address, text, BRANCH, state, predicted, taken, after))
        thrown = []                     # (address, the cycle it leaves IF, the cycle at whose end
        d = decoded                     # it is thrown away, why)
        after_branch = (address + 4) & MASK
        if stage == ID:
            if taken:
                thrown = [(after_branch, d, d, f"thrown away: the branch {name} is taken")]
        elif predicted:
            thrown = [(after_branch, d, d, f"thrown away: the branch {name} is predicted "
                                           f"taken")]
            if not taken:
                thrown += [((info.target + 4 * k) & MASK, d + 1 + k, d + stage - 1,
                            f"thrown away: the branch {name} was not taken, against the "
                            f"prediction") for k in range(stage - 1)]
        elif taken:
            thrown = [((address + 4 + 4 * k) & MASK, d + k, d + stage - 1,
                       f"thrown away: the branch {name} was taken, against the prediction")
                      for k in range(stage)]
        if stage == ID:
            lost = int(taken)
        elif predicted == taken:
            lost = int(taken)
        else:
            lost = stage
        self.pending = (lost, len(thrown), "")
        return [self._thrown(*entry) for entry in thrown]

    def _thrown(self, address, fetched, thrown, note):
        first = self.last_f + 1
        cells = [STALL] * (fetched - first) + ["IF"]
        cells += [stage for k, stage in ((1, "ID"), (2, "EX")) if fetched + k <= thrown]
        cells.append(FLUSH)
        word, code = self.read(address) if self.read is not None else (None, False)
        basic = instruction_text(word, address, code)
        text = self._text(address, basic) if code and word is not None else basic
        hold = "waits: the instruction ahead is held in ID" if fetched > first else ""
        self.last_f = fetched
        return Row(address, text, True, first, fetched, thrown, tuple(cells), hold, "", note,
                   basic)


# The fast way -----------------------------------------------------------------------------

# Block kinds, as small numbers for the fast loop.
_KIND = {PLAIN: 0, BRANCH: 1, JUMP: 2, PC_WRITE: 3}


class Block:
    """A stretch of straight-line code the program ran: from start, size bytes (a basic block
    of the emulator, or part of one where a run stopped inside it). Only its last
    instruction may change the flow: kind is that instruction's (as a number of _KIND)."""

    __slots__ = ("index", "start", "size", "count", "insts", "kind", "last", "target",
                 "from_memory", "infer")

    def __init__(self, index, start, size, insts, hooked):
        self.index, self.start, self.size = index, start, size
        self.count = len(insts)
        self.insts = insts
        info = insts[-1]
        self.kind = _KIND[info.kind]
        self.last = start + 4 * (self.count - 1)
        self.target = info.target
        self.from_memory = info.from_memory
        # A branch whose outcome no hook reports: the next block tells it.
        self.infer = info.kind == BRANCH and self.last not in hooked

    def addresses(self):
        return range(self.start, self.start + 4 * self.count, 4)


class Blocks:
    """The blocks the program ran, decoded once: list holds them by number, index finds the
    number of (start, size) in the program observed now. hooked holds the addresses of the
    conditional branches whose outcome a hook reports."""

    def __init__(self):
        self.list = []
        self.index = {}
        self.hooked = frozenset()
        self.read = None                # read(address, size) -> bytes, of the program observed

    def new_program(self, read, hooked):
        """Another program is observed (the blocks of the earlier ones stay in list)."""
        self.index = {}
        self.read = read
        self.hooked = frozenset(hooked)

    def add(self, start, size):
        """The number of the block (start, size), decoded the first time."""
        number = self.index.get((start, size))
        if number is None:
            count = max(1, size // 4)
            try:
                data = self.read(start, 4 * count)
            except Exception:           # it ran, so there is memory; but never fail here
                data = bytes(4 * count)
            words = struct.unpack(f"<{count}I", data)
            insts = tuple(decode(word, start + 4 * k) for k, word in enumerate(words))
            number = len(self.list)
            self.list.append(Block(number, start, 4 * count, insts, self.hooked))
            self.index[(start, size)] = number
        return number


class Timing:
    """The fast way: the totals of the run, block by block (run() takes the blocks as codes:
    the block's number times 2, plus 1 when its last instruction, a branch, was taken).

    The state of the timing before a block is (flags, ((unit, ordinary, early), ...)): how many
    cycles after the cycle at the block's start a conditional branch decided in ID, an
    ordinary reader and a PC write decided in ID of each unit may leave ID (0: no wait). A
    block's answer for a state is (its last d counted from the start, its stall cycles, the
    state after it, counted from its last d) and is kept. tail keeps for the newest blocks
    what the plain way needs to make their rows again and the state of the timing before
    each (undo() goes back with it), lines the newest branch lines.
    """

    def __init__(self, settings, blocks):
        self.settings = settings
        self.blocks = blocks
        self.count = self.stalls = self.flushes = self.right = self.wrong = 0
        self.last_d = 1
        self.lost = self.flushed = 0        # what the next block loses, of it flushed
        self.state = 0
        self.states = [(0, ())]             # the states, by number
        self._numbers = {(0, ()): 0}
        self._shifted = {}                  # state * 4 + cycles -> the state that many later
        self._answers = []                  # by block number: {state: answer}
        self.predictor = {}
        self.single = settings.first_state
        self.tail = deque(maxlen=TAIL)      # (block, last_d, lost, flushed, state, taken, before)
        self.lines = deque(maxlen=KEPT_LINES)   # (block, before, predicted, taken, after)
        self.branches = 0                   # branch lines made so far
        self.cut_lines = 0                  # branch lines undo() took out so far
        self._offsets = offsets(settings)

    @property
    def totals(self):
        return Totals(self.count, cycles_of(self.count, self.last_d), self.stalls,
                      self.flushes, self.right, self.wrong)

    def run(self, codes):
        """Take in the blocks of codes, in the order they ran."""
        settings = self.settings
        blocks = self.blocks.list
        answers = self._answers
        shifted = self._shifted
        keep, line = self.tail.append, self.lines.append
        stage, jump = settings.branch_stage, settings.jump_stage
        mode = settings.prediction
        static_taken = settings.static_taken
        two_bits = settings.bits == 2
        one_state = settings.one_state
        first_state = settings.first_state
        predictor, single = self.predictor, self.single
        last_d, lost, flushed, state = self.last_d, self.lost, self.flushed, self.state
        count = stalls = flushes = right = wrong = branches = 0
        for code in codes:
            number = code >> 1
            block = blocks[number]
            try:
                known = answers[number]
            except IndexError:
                answers.extend({} for _ in range(number + 1 - len(answers)))
                known = answers[number]
            answer = known.get(state)
            if answer is None:
                answer = known[state] = self._work_out(block, state)
            delta, inner, after = answer
            kind = block.kind
            taken = code & 1
            before = None
            if kind == 0:
                next_lost = next_flushed = 0
            elif kind == 2:
                next_lost, next_flushed = jump, 0
            elif kind == 3:
                next_lost, next_flushed = (MEM if block.from_memory else stage), 0
                line((number, None, None, 1, None))
                branches += 1
            elif mode == NONE:
                next_lost, next_flushed = stage, 0
                line((number, None, None, taken, None))
                branches += 1
            else:
                if mode == STATIC:
                    predicted, now = static_taken, None
                else:
                    before = single if one_state else predictor.get(block.last, first_state)
                    if two_bits:
                        predicted = before >= 2
                        now = (before + 1 if before < 3 else 3) if taken else (
                            before - 1 if before else 0)
                    else:
                        predicted = before == 1
                        now = 1 if taken else 0
                    if one_state:
                        single = now
                    else:
                        predictor[block.last] = now
                if predicted == taken:
                    right += 1
                    next_lost = next_flushed = taken
                else:
                    wrong += 1
                    next_lost = next_flushed = stage
                if stage == ID:
                    next_lost = next_flushed = taken
                line((number, before, predicted, taken, now))
                branches += 1
            keep((number, last_d, lost, flushed, state, taken, before))
            last_d += lost + delta
            stalls += inner + lost - flushed
            flushes += flushed
            count += block.count
            lost, flushed = next_lost, next_flushed
            if lost:
                key = after * 4 + lost
                state = shifted.get(key)
                if state is None:
                    state = shifted[key] = self._shift(after, lost)
            else:
                state = after
        self.last_d, self.lost, self.flushed, self.state = last_d, lost, flushed, state
        self.single = single
        self.count += count
        self.stalls += stalls
        self.flushes += flushes
        self.right += right
        self.wrong += wrong
        self.branches += branches

    def undo(self, count):
        """Take the last count instructions out again, as if they had not run (Backstep undid
        them): the numbers, the state, the predictor and the branch lines go back to what they
        were before them, block by block from tail, and the start of a block cut in its middle
        runs again. False, and nothing changes, when tail does not reach so far back."""
        blocks, tail = self.blocks.list, self.tail
        target = max(0, self.count - count)
        reach, index = self.count, len(tail)
        while reach > target and index:
            index -= 1
            reach -= blocks[tail[index][0]].count
        if reach > target:
            return False
        settings, lines, block = self.settings, self.lines, None
        mode, two_bits = settings.prediction, settings.bits == 2
        while self.count > target:
            number, last_d, lost, flushed, state, taken, before = tail.pop()
            block = blocks[number]
            self.count -= block.count
            self.stalls -= self._answers[number][state][1] + lost - flushed
            self.flushes -= flushed
            if block.kind in (1, 3):            # it made a branch line
                self.branches -= 1
                self.cut_lines += 1
                if lines:
                    lines.pop()
            if block.kind == 1 and mode != NONE:
                if mode == STATIC:
                    predicted = settings.static_taken
                else:                           # the predictor forgets what it learned
                    predicted = before >= 2 if two_bits else before == 1
                    if settings.one_state:
                        self.single = before
                    else:
                        self.predictor[block.last] = before
                if predicted == taken:
                    self.right -= 1
                else:
                    self.wrong -= 1
            self.last_d, self.lost, self.flushed, self.state = last_d, lost, flushed, state
        if self.count < target:
            self.run([self.blocks.add(block.start, 4 * (target - self.count)) << 1])
        return True

    def _number(self, flags, entries):
        key = (flags, entries)
        number = self._numbers.get(key)
        if number is None:
            number = self._numbers[key] = len(self.states)
            self.states.append(key)
        return number

    def _work_out(self, block, state):
        """(the block's last d counted from the start, its stall cycles, the state after it)
        for a block that starts in state."""
        settings = self.settings
        flags, entries = self.states[state]
        ordinary, early = {}, {}
        for unit, wait, early_wait in entries:
            if wait:
                ordinary[unit] = wait
            if early_wait:
                early[unit] = early_wait
        plain, plain_load, id_reader, id_load = self._offsets
        d = stalls = 0
        for info in block.insts:
            lowest = need = d + 1
            in_id = info.decided_in_id(settings)
            table = early if in_id and info.kind == PC_WRITE else ordinary
            for unit in info.reads:
                ready = table.get(unit, 0)
                if ready > need:
                    need = ready
            if info.conditional and in_id and flags > need:
                need = flags
            stalls += need - lowest
            d = need
            for unit in info.writes:
                if unit in info.loaded:
                    ordinary[unit], early[unit] = d + plain_load, d + id_load
                else:
                    ordinary[unit], early[unit] = d + plain, d + id_reader
            if info.sets_flags:
                flags = d + 2
        items = []
        for unit in set(ordinary) | set(early):
            wait, early_wait = ordinary.get(unit, 0) - d, early.get(unit, 0) - d
            wait, early_wait = (wait if wait > 1 else 0), (early_wait if early_wait > 1 else 0)
            if wait or early_wait:
                items.append((unit, wait, early_wait))
        flags -= d
        return d, stalls, self._number(flags if flags > 1 else 0, tuple(sorted(items)))

    def _shift(self, state, cycles):
        """The state cycles later."""
        flags, entries = self.states[state]
        items = []
        for unit, wait, early_wait in entries:
            wait, early_wait = wait - cycles, early_wait - cycles
            wait, early_wait = (wait if wait > 1 else 0), (early_wait if early_wait > 1 else 0)
            if wait or early_wait:
                items.append((unit, wait, early_wait))
        flags -= cycles
        return self._number(flags if flags > 1 else 0, tuple(items))

    def line(self, entry, written=None):
        """The Line of an entry of lines; written as for Pipeline."""
        number, before, predicted, taken, after = entry
        block = self.blocks.list[number]
        text = (written(block.last) if written is not None else None) or block.insts[-1].text
        kind = PC_WRITE if block.kind == 3 else BRANCH
        return Line(block.last, text, kind, before, predicted, bool(taken), after)

    def newest_lines(self, written=None, limit=LINES):
        """The Lines of the newest entries of lines (at most limit), the newest last."""
        lines = self.lines
        return [self.line(entry, written)
                for entry in islice(lines, max(0, len(lines) - limit), None)]

    def rows(self, read=None, limit=ROWS, written=None):
        """The newest rows of the table (at most limit), made by the plain way from tail; read
        and written as for Pipeline."""
        tail = list(self.tail)
        if not tail:
            return []
        blocks = self.blocks.list
        start, count = len(tail), 0
        while start > 0 and count < limit + LEAD:
            start -= 1
            count += blocks[tail[start][0]].count
        number, last_d, lost, flushed, state, taken, before = tail[start]
        pipeline = Pipeline.resume(self.settings, last_d, lost, flushed, self.states[state],
                                   read, written)
        rows = []
        for number, _, _, _, _, taken, before in tail[start:]:
            block = blocks[number]
            for address, info in zip(block.addresses(), block.insts):
                last = address == block.last
                rows += pipeline.feed(address, info, taken if last else False,
                                      before if last else None)
        return rows[-limit:]


class Record:
    """The blocks the program ran, as codes (see Timing.run()), to work the numbers out again
    for other settings: the whole run up to LIMIT instructions; past that the oldest parts are
    dropped while at least LIMIT instructions stay. A part gathers what is added until it holds
    PART instructions or more. dropped counts the instructions dropped."""

    def __init__(self):
        self.parts = deque()            # [codes, instructions]
        self.instructions = 0
        self.dropped = 0

    def add(self, codes, instructions):
        if not self.parts or self.parts[-1][1] >= PART:
            self.parts.append([array("L"), 0])
        part = self.parts[-1]
        part[0].extend(codes)
        part[1] += instructions
        self.instructions += instructions
        while len(self.parts) > 1 and self.instructions - self.parts[0][1] >= LIMIT:
            gone = self.parts.popleft()
            self.instructions -= gone[1]
            self.dropped += gone[1]

    def undo(self, count, blocks):
        """Take the last count instructions out (Backstep undid them); blocks is the Blocks
        whose numbers the codes hold. A block cut in its middle keeps its start."""
        parts, listed = self.parts, blocks.list
        while count > 0 and parts:
            part = parts[-1]
            codes = part[0]
            if codes:
                block = listed[codes.pop() >> 1]
                out = min(count, block.count)
                if out < block.count:
                    codes.append(blocks.add(block.start, 4 * (block.count - out)) << 1)
                part[1] -= out
                self.instructions -= out
                count -= out
            if not codes:
                parts.pop()

    def codes(self):
        for part, _ in self.parts:
            yield part


# The dependency checker ----------------------------------------------------------------------

@dataclass(frozen=True)
class Checked:
    """A line of the checker's program: an instruction (its address), or a NOP it added
    (address None)."""
    address: int
    text: str

    @property
    def added(self):
        return self.address is None


def control_nops(info, settings):
    """The NOPs after a branch or jump: without prediction 1, 2 or 3 for the stage that decides
    it (MEM for a PC that comes from memory); with prediction none, as the source tool's table
    has it."""
    if info.kind == PLAIN or settings.prediction != NONE:
        return 0
    if info.kind == BRANCH:
        return settings.branch_stage
    if info.kind == JUMP:
        return settings.jump_stage
    return MEM if info.from_memory else settings.branch_stage


def check(instructions, settings, written=None):
    """The checker's program for instructions, [(address, Info)] in the order they are
    written, which it reads as they stand (it does not follow branches): each instruction,
    after the NOPs it needs for the values and flags it reads, and after a branch or jump the
    NOPs of control_nops(). Returns ([Checked], the NOPs added). written names the
    instructions as for Pipeline."""
    plain, plain_load, id_reader, id_load = offsets(settings)
    need, flags = {}, 0
    slot = added = 0                    # the cycle in which the next one would leave ID
    lines = []
    for address, info in instructions:
        early = info.decided_in_id(settings)
        column = 1 if early and info.kind == PC_WRITE else 0
        ready = max((need[unit][column] for unit in info.reads if unit in need), default=0)
        if info.conditional and early:
            ready = max(ready, flags)
        nops = max(0, ready - slot)
        lines += [Checked(None, "NOP")] * nops
        slot += nops
        text = (written(address) if written is not None else None) or info.text
        lines.append(Checked(address, text))
        for unit in info.writes:
            if unit in info.loaded:
                need[unit] = (slot + plain_load, slot + id_load)
            else:
                need[unit] = (slot + plain, slot + id_reader)
        if info.sets_flags:
            flags = slot + 2
        slot += 1
        after = control_nops(info, settings)
        lines += [Checked(None, "NOP")] * after
        slot += after
        added += nops + after
    return lines, added
