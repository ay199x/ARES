# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The model of Tools > ARM X-Ray: one ARM instruction on the single-cycle datapath.

The datapath is the textbook's single-cycle ARM processor (credits.TEXTBOOK),
with the additions a real ARMv7 program needs: more ALU operations, a shifter, the shifter's
carry, a third read port for stores with a register offset, byte accesses, BL, BX and BLX, a
second write port for the base register with the AdrSrc multiplexer, a pass counter in the
control unit that runs LDM, STM, PUSH and POP one register at a time, a multiplier in the ALU
for MUL and MLA, whose registers the signal Mul chooses, the shift by a register, whose Rs the
A4 multiplexer reads (ShiftReg), the C flag into the ALU for ADC, SBC and RSC (CarryIn), NOP,
which writes nothing, the 16-bit immediate of MOVW and MOVT, whose ALU operation joins it to the
low half of Rd, read on A4, and halfword and signed transfers: the signal Size (a word, a
halfword or a byte) and Signed into the data memory, whose load extender widens a halfword or a
byte to 32 bits.

decode() gives the control signals of a word, from the Main Decoder and the
ALU Decoder. trace() runs a word through the datapath by hand: from the
registers and flags before it, it gives each control signal, each wire's value
and, for each of the five stages, what is in use. A wire nothing uses has the
value None; so has one whose value cannot be known yet, such as a load from a
device before it runs: reading a device would take its data.

executed() and upcoming() trace an instruction of a Machine: the one it just
ran, from the registers it recorded for Backstep, or the one at PC, from the
state now. Nothing here hooks the machine, so tracing costs nothing while a
program runs.
"""

import struct
from dataclasses import dataclass, replace

from .disasm import basic
from .errors import RuntimeFault
from .machine import SNAPSHOT_PC, SNAPSHOT_REGISTERS, condition_passed

MASK = 0xFFFFFFFF
THUMB = 0x20                    # the T bit of CPSR
PC_NUMBER, LINK_REGISTER = 15, 14
BX_MASK, BX_BITS = 0x0FFFFFF0, 0x012FFF10   # BX Rm: all but the condition and Rm
BLX_BITS = 0x012FFF30                       # BLX Rm: the same, bits 7:4 0011
NOP_MASK, NOP_BITS = 0x0FFFFFFF, 0x0320F000  # NOP, the hint: all but the condition

# The classes of the instructions inside the datapath.
DP_REGISTER = "Data processing, register operand"
DP_IMMEDIATE = "Data processing, immediate operand"
LOAD_IMMEDIATE = "Load, immediate offset"
LOAD_REGISTER = "Load, register offset"
STORE_IMMEDIATE = "Store, immediate offset"
STORE_REGISTER = "Store, register offset"
BRANCH = "Branch"
BRANCH_LINK = "Branch with link"
BRANCH_EXCHANGE = "Branch and exchange"
BRANCH_LINK_EXCHANGE = "Branch with link and exchange"
NO_OPERATION = "No operation"
SYSTEM_CALL = "System call"
LOAD_MULTIPLE = "Load multiple"
STORE_MULTIPLE = "Store multiple"
MULTIPLY = "Multiply"
MOVE_16 = "Move, 16-bit immediate"                         # MOVW and MOVT
LOAD_HALF_IMMEDIATE = "Load halfword or signed, immediate offset"   # LDRH, LDRSB, LDRSH
LOAD_HALF_REGISTER = "Load halfword or signed, register offset"
STORE_HALF_IMMEDIATE = "Store halfword, immediate offset"           # STRH
STORE_HALF_REGISTER = "Store halfword, register offset"
OUTSIDE = "Outside the datapath"
MULTIPLE = (LOAD_MULTIPLE, STORE_MULTIPLE)
HALVES = (LOAD_HALF_IMMEDIATE, LOAD_HALF_REGISTER, STORE_HALF_IMMEDIATE, STORE_HALF_REGISTER)
STORES = (STORE_IMMEDIATE, STORE_REGISTER, STORE_HALF_IMMEDIATE, STORE_HALF_REGISTER,
          STORE_MULTIPLE)

# The Main Decoder: Branch, MemtoReg, MemW, ALUSrc, ImmSrc, RegW, RegSrc, ALUOp, and Mul, which
# makes the RA1 multiplexer take Rs (Instr 11:8) and the A3 multiplexer Instr 19:16. BLX is the
# row of BX with RegW 1 (and Link 1, below); in the row of NOP nothing is written. ImmSrc has three
# bits: 000 rotate imm8, 001 imm12, 010 imm24 x 4, 011 the pass counter's offset, 100 imm16 of MOVW
# and MOVT (Instr 19:16 and 11:0), 101 imm8 of a halfword or signed transfer (Instr 11:8 and 3:0).
MAIN_SIGNALS = ("Branch", "MemtoReg", "MemW", "ALUSrc", "ImmSrc", "RegW", "RegSrc", "ALUOp",
                "Mul")
MAIN_DECODER = {
    DP_REGISTER: ("0", "0", "0", "0", "XXX", "1", "00", "1", "0"),
    DP_IMMEDIATE: ("0", "0", "0", "1", "000", "1", "X0", "1", "0"),
    STORE_IMMEDIATE: ("0", "X", "1", "1", "001", "0", "10", "0", "0"),
    LOAD_IMMEDIATE: ("0", "1", "0", "1", "001", "1", "X0", "0", "0"),
    BRANCH: ("1", "0", "0", "1", "010", "0", "X1", "0", "0"),
    STORE_REGISTER: ("0", "X", "1", "0", "XXX", "0", "00", "0", "0"),
    LOAD_REGISTER: ("0", "1", "0", "0", "XXX", "1", "00", "0", "0"),
    BRANCH_LINK: ("1", "0", "0", "1", "010", "1", "X1", "0", "0"),
    BRANCH_EXCHANGE: ("1", "0", "0", "0", "XXX", "0", "0X", "1", "0"),
    SYSTEM_CALL: ("0", "X", "0", "X", "XXX", "0", "XX", "X", "0"),
    LOAD_MULTIPLE: ("0", "1", "0", "1", "011", "1", "X0", "0", "0"),
    STORE_MULTIPLE: ("0", "X", "1", "1", "011", "0", "X0", "0", "0"),
    MULTIPLY: ("0", "0", "0", "0", "XXX", "1", "00", "1", "1"),
    BRANCH_LINK_EXCHANGE: ("1", "0", "0", "0", "XXX", "1", "0X", "1", "0"),
    NO_OPERATION: ("0", "X", "0", "X", "XXX", "0", "XX", "X", "0"),
    MOVE_16: ("0", "0", "0", "1", "100", "1", "XX", "1", "0"),
    LOAD_HALF_IMMEDIATE: ("0", "1", "0", "1", "101", "1", "X0", "0", "0"),
    LOAD_HALF_REGISTER: ("0", "1", "0", "0", "XXX", "1", "00", "0", "0"),
    STORE_HALF_IMMEDIATE: ("0", "X", "1", "1", "101", "0", "10", "0", "0"),
    STORE_HALF_REGISTER: ("0", "X", "1", "0", "XXX", "0", "00", "0", "0"),
}

# ALUControl: the textbook's four operations with 00 in front, and the additions'.
ALU_ADD, ALU_SUB, ALU_AND, ALU_ORR = "0000", "0001", "0010", "0011"
ALU_EOR, ALU_BIC, ALU_RSB, ALU_MOV, ALU_MVN = "0100", "0101", "0110", "0111", "1000"
ALU_MUL, ALU_MLA = "1001", "1010"       # the multiplier: SrcA x SrcB, and + RD4 for MLA
ALU_ADC, ALU_SBC, ALU_RSC = "1011", "1100", "1101"  # the adder with CarryIn, the C flag
ALU_MOVT = "1110"                       # MOVT: SrcB[15:0] as the high half, RD4[15:0] the low
CARRY_CODES = (ALU_ADC, ALU_SBC, ALU_RSC)
# The data memory's Size: a word, a halfword or a byte (its high bit marks a byte, its low bit
# a halfword), and how many bytes that is.
SIZE_WORD, SIZE_HALF, SIZE_BYTE = "00", "01", "10"
SIZES = {SIZE_WORD: 4, SIZE_HALF: 2, SIZE_BYTE: 1}

# The ALU Decoder, by cmd: ALUControl, FlagW with S=1, NoWrite.
ALU_DECODER = {
    0b0100: (ALU_ADD, "11", "0"),
    0b0010: (ALU_SUB, "11", "0"),
    0b0000: (ALU_AND, "10", "0"),
    0b1100: (ALU_ORR, "10", "0"),
    0b0001: (ALU_EOR, "10", "0"),
    0b1110: (ALU_BIC, "10", "0"),
    0b0011: (ALU_RSB, "11", "0"),
    0b0101: (ALU_ADC, "11", "0"),
    0b0110: (ALU_SBC, "11", "0"),
    0b0111: (ALU_RSC, "11", "0"),
    0b1101: (ALU_MOV, "10", "0"),
    0b1111: (ALU_MVN, "10", "0"),
    0b1010: (ALU_SUB, "11", "1"),       # CMP
    0b1011: (ALU_ADD, "11", "1"),       # CMN
    0b1000: (ALU_AND, "10", "1"),       # TST
    0b1001: (ALU_MOV, "00", "0"),       # BX and BLX, with S = 0: with S = 1 this cmd is TEQ
}
TEQ = 0b1001
TEQ_ROW = (ALU_EOR, "10", "1")          # TEQ: cmd 1001 with S = 1, an EOR that only sets flags
# With Mul 1 the ALU Decoder's rows of the multiplier, by cmd (000A: bit 21 is A, accumulate):
# ALUControl, FlagW with S=1 (N and Z: C and V stay), NoWrite.
MUL_DECODER = {0b0000: (ALU_MUL, "10", "0"), 0b0001: (ALU_MLA, "10", "0")}
# With S = 0, cmd 1000 and 1010 (TST and CMP have S = 1) are MOVW and MOVT: MOVW passes SrcB on,
# MOVT joins it to the low half of RD4. They have no S: FlagW is 00.
MOVE_DECODER = {0b1000: (ALU_MOV, "00", "0"), 0b1010: (ALU_MOVT, "00", "0")}
NO_FIRST_OPERAND = (ALU_MOV, ALU_MVN, ALU_MOVT)     # these use no SrcA
MULTIPLY_MASK, MULTIPLY_BITS = 0x0FC000F0, 0x00000090      # MUL, MLA: all but cond, A, S, registers

# Why an instruction lies outside.
NOTE_CONDITION = "Condition 1111 marks instructions that have no row in the decoders."
NOTE_RETURN = "An S with Rd = 15 also restores CPSR from SPSR, which this datapath cannot do."
NOTE_MULTIPLY = ("The multiplier makes the 32-bit products of MUL and MLA only: long multiplies, "
                 "MLS and UMAAL have no row in the decoders.")
NOTE_SIZES = "Doubleword and exclusive accesses have no row in the Main Decoder."
NOTE_SWAP = "SWP loads and stores at once, which has no row in the Main Decoder."
NOTE_OTHER = ("This instruction has no row in the decoders, like MRS, MSR, CLZ and the hints "
              "other than NOP.")
NOTE_PRIVILEGED = ("LDRT, STRT, LDRBT, STRBT, LDRHT, STRHT, LDRSBT and LDRSHT access the memory "
                   "as an unprivileged program, which this datapath does not model.")
NOTE_USER_BANK = ("LDM and STM with ^ reach the registers of user mode or return from an "
                  "exception, which this datapath cannot do.")
NOTE_UNPREDICTABLE = ("ARMv7 leaves this encoding UNPREDICTABLE (for example an empty register "
                      "list, the PC as the base or as a register of a multiply, of a shift by a "
                      "register, of MOVW or MOVT or of a halfword transfer, or write-back to a "
                      "register it loads or stores): the datapath does not run it.")
NOTE_BASE_LOADED = ("This LDM loads its base register before its last pass: the passes after it "
                    "would take the new base.")
NOTE_PC_FIRST = ("This LDM counts down with write-back, so its first pass would load the PC: the "
                 "PC must come last.")
NOTE_COPROCESSOR = "Floating point, NEON and coprocessor instructions have units of their own."
NOTE_THUMB = "Thumb code: this datapath decodes ARM instructions."
NOTE_TO_THUMB = "Bit 0 of the address is 1: the processor goes on in Thumb code."

# Which instruction a view shows, and how it got there.
EXECUTED = "executed"           # the one that just ran (after a Backstep: the one run before)
NEXT = "next"                   # the one at PC, not run yet
ENDED = "ended"                 # none: the program has ended
FAILED = "failed"               # the one a runtime error stopped
NOTHING = "nothing"             # none: nothing observed yet
WAITING = "waiting"             # the SVC at PC, which waits for input

STAGES = ("Fetch", "Decode", "Execute", "Memory", "Write back")
BLOCKS = ("PCMux", "PCReg", "IMem", "Add4", "Add8", "RA1Mux", "RA2Mux", "A3Mux", "A4Mux",
          "WD3Mux", "RegFile", "Extend", "Shifter", "ALUSrcMux", "StoreMux", "ALU", "AdrSrcMux",
          "DMem",
          "ResultMux", "Control", "System")
SHIFT_NAMES = ("LSL", "LSR", "ASR", "ROR")
CONDITIONS = ("EQ", "NE", "CS", "CC", "MI", "PL", "VS", "VC", "HI", "LS", "GE", "LT", "GT", "LE",
              "AL")
CONDITION_FLAGS = ("Z", "Z", "C", "C", "N", "N", "V", "V", "CZ", "CZ", "NV", "NV", "ZNV", "ZNV",
                   "")
FLAG_BITS = {"N": 3, "Z": 2, "C": 1, "V": 0}


@dataclass(frozen=True)
class Control:
    """What the control unit makes of a word: kind is its class, signals its signals as
    the tables write them, with X where they do not matter. Outside, note says why."""
    kind: str
    note: str
    signals: dict


@dataclass(frozen=True)
class Stage:
    """What is in use in one stage: the names of wires and of BLOCKS."""
    name: str
    wires: frozenset
    blocks: frozenset


@dataclass(frozen=True)
class Trace:
    """One instruction on the datapath. See the module's description."""
    pc: int
    word: int
    text: str           # as the Text Segment's Basic column shows it
    kind: str
    note: str           # why it lies outside; else ""
    condition: str      # the condition check, such as "NE: Z = 0, executes"
    signals: dict       # the decoders' signals, and CondEx, PCSrc, RegWrite, MemWrite, FlagWrite
    values: dict        # each wire's value
    flags: int          # N Z C V before it
    new_flags: int      # and after it
    stages: tuple = ()
    to_thumb: bool = False      # it writes the PC an odd address: Thumb code follows
    hardware: dict = None       # each wire's value in the circuit drawn, which makes an X a 0
    passes: tuple = ()          # LDM, STM, PUSH, POP: the Trace of each pass, in order
    number: int = 0             # a pass: its number, from 1
    count: int = 0              # a pass: how many passes the instruction makes
    registers: tuple = ()       # a pass: R0 to R15 before it (R15 as the program reads it)

    @property
    def active(self):
        """The wires in use in any stage."""
        return frozenset().union(*(stage.wires for stage in self.stages))

    @property
    def active_blocks(self):
        return frozenset().union(*(stage.blocks for stage in self.stages))


@dataclass(frozen=True)
class View:
    """What the tool shows: heading says which instruction trace is (None: no instruction),
    did what it changed, if it lies outside and ran, and ended that the program has ended;
    written is the instruction as the student wrote it (None: no line of the source made it,
    and the tool names it by trace.text, its Basic form)."""
    kind: str = NOTHING
    heading: str = ""
    trace: Trace = None
    did: tuple = ()
    ended: bool = False
    written: str = None


def named(written, basic):
    """How the tool names an instruction: as the student wrote it (written: the Source column's
    text without its number, comment and labels), else by its Basic form."""
    return written or basic


def instruction_line(written, basic):
    """The line that names the instruction above its bits: as written, then its Basic form in
    brackets when the two differ in more than letter case and spaces; the Basic form alone
    where no line of the source made the instruction."""
    if not written:
        return basic
    if _plain(written) == _plain(basic):
        return written
    return f"{written}    ({basic})"


def _plain(text):
    return "".join(text.split()).upper()


# Inside or outside -----------------------------------------------------------------------

def outside_note(word):
    """Why the datapath cannot run word; "" when it can."""
    op = word >> 26 & 3
    if word >> 28 == 0xF:
        return NOTE_CONDITION
    if op == 0:
        return _data_note(word)
    if op == 1:
        return _memory_note(word)
    if op == 2:
        return "" if word >> 25 & 1 else _multiple_note(word)
    return "" if word >> 24 & 0xF == 0xF else NOTE_COPROCESSOR


def _is_bx(word):
    """True for BX Rm and BLX Rm."""
    return word & BX_MASK in (BX_BITS, BLX_BITS)


def _is_blx(word):
    return word & BX_MASK == BLX_BITS


def is_nop(word):
    return word & NOP_MASK == NOP_BITS


def shifted_by_register(word):
    """True for data processing with a register shifted by a register (ADD R2, R1, R0, LSL R3):
    bit 4 is 1 and bit 7 is 0."""
    return word >> 26 & 3 == 0 and not word >> 25 & 1 and word & 0x90 == 0x10


def is_move_16(word):
    """True for MOVW and MOVT: bits 27:20 0011 0000 and 0011 0100 (cmd 1000 and 1010 without S,
    the immediate form)."""
    return word & 0x0FB00000 == 0x03000000


def is_half(word):
    """True for the halfword, signed and doubleword transfers: op 00, bit 25 0, and bits 7:4 1SH1
    with SH not 00 (00 marks the multiplies and the swaps)."""
    return word & 0x0E000090 == 0x00000090 and bool(word & 0x60)


def _data_note(word):
    if _is_bx(word):
        return NOTE_UNPREDICTABLE if _is_blx(word) and word & 0xF == PC_NUMBER else ""
    if is_nop(word):
        return ""
    immediate, cmd, s = word >> 25 & 1, word >> 21 & 0xF, word >> 20 & 1
    if is_half(word):
        return _half_note(word)
    if not immediate and word & 0x90 == 0x90:       # bits 7 and 4
        if word & 0x0FB00FF0 == 0x01000090:
            return NOTE_SWAP
        if word & MULTIPLY_MASK == MULTIPLY_BITS:
            return _multiply_note(word)
        multiply = word >> 4 & 0xF == 9 and not word >> 24 & 1
        return NOTE_MULTIPLY if multiply else NOTE_SIZES
    if is_move_16(word):                # ARMv7: MOVW and MOVT may not write the PC
        return NOTE_UNPREDICTABLE if word >> 12 & 0xF == PC_NUMBER else ""
    if 0b1000 <= cmd <= 0b1011 and not s:
        return NOTE_OTHER
    if s and word >> 12 & 0xF == PC_NUMBER:
        return NOTE_RETURN
    if shifted_by_register(word):       # ARMv7: none of its registers may be the PC
        rn, rd, rs, rm = word >> 16 & 0xF, word >> 12 & 0xF, word >> 8 & 0xF, word & 0xF
        used = [rs, rm] + ([] if cmd in (0b1101, 0b1111) else [rn]) + \
            ([] if 0b1000 <= cmd <= 0b1011 else [rd])
        if PC_NUMBER in used:
            return NOTE_UNPREDICTABLE
    return ""


def _multiply_note(word):
    """Why the datapath cannot run a MUL or MLA word; "" when it can. ARMv7 leaves the PC as any
    of its registers UNPREDICTABLE, and bits 15:12 of MUL must be 0 (the processor takes a MUL
    with other bits there as an undefined instruction)."""
    rd, ra, rs, rm = word >> 16 & 0xF, word >> 12 & 0xF, word >> 8 & 0xF, word & 0xF
    accumulate = word >> 21 & 1
    if PC_NUMBER in (rd, rs, rm) or (ra == PC_NUMBER if accumulate else ra):
        return NOTE_UNPREDICTABLE
    return ""


def _half_note(word):
    """Why the datapath cannot run a halfword, signed or doubleword transfer word; "" when it can.
    LDRD and STRD (L 0 with S 1) move two words; P 0 with W 1 marks LDRHT, STRHT, LDRSBT and
    LDRSHT. ARMv7 leaves UNPREDICTABLE the PC as Rt or as Rm, bits 11:8 of a register offset other
    than 0000, and write-back to the PC or to the register moved."""
    load, signed = word >> 20 & 1, word >> 6 & 1
    if not load and signed:
        return NOTE_SIZES
    pre, write_back = word >> 24 & 1, word >> 21 & 1
    if not pre and write_back:
        return NOTE_PRIVILEGED
    base, rt, rm = word >> 16 & 0xF, word >> 12 & 0xF, word & 0xF
    register = not word >> 22 & 1
    if rt == PC_NUMBER or (register and (rm == PC_NUMBER or word >> 8 & 0xF)):
        return NOTE_UNPREDICTABLE
    if (not pre or write_back) and base in (PC_NUMBER, rt):
        return NOTE_UNPREDICTABLE
    return ""


def _memory_note(word):
    if word >> 25 & 1 and word >> 4 & 1:
        return NOTE_OTHER
    pre, write_back = word >> 24 & 1, word >> 21 & 1
    if not pre and write_back:          # P = 0 and W = 1: LDRT, STRT, LDRBT, STRBT
        return NOTE_PRIVILEGED
    if not pre or write_back:           # the base register is written too
        base, rd = word >> 16 & 0xF, word >> 12 & 0xF
        if base in (PC_NUMBER, rd) or (word >> 25 & 1 and word & 0xF == PC_NUMBER):
            return NOTE_UNPREDICTABLE
    return ""


def _multiple_note(word):
    """Why the datapath cannot run an LDM or STM word; "" when it can."""
    if word >> 22 & 1:                  # S: the user bank, or a return from an exception
        return NOTE_USER_BANK
    base, write_back, load, up = word >> 16 & 0xF, word >> 21 & 1, word >> 20 & 1, word >> 23 & 1
    registers = word & 0xFFFF
    if not registers or base == PC_NUMBER or (write_back and registers >> base & 1):
        return NOTE_UNPREDICTABLE
    if load and registers >> base & 1 and registers >> base + 1:
        return NOTE_BASE_LOADED         # the base is loaded, and a later pass needs it
    if load and write_back and not up and registers >> PC_NUMBER & 1:
        return NOTE_PC_FIRST
    return ""


# The decoders ----------------------------------------------------------------------------

def _class_of(word):
    if _is_bx(word):
        return BRANCH_LINK_EXCHANGE if _is_blx(word) else BRANCH_EXCHANGE
    if is_nop(word):
        return NO_OPERATION
    op, funct5 = word >> 26 & 3, word >> 25 & 1
    if word & MULTIPLY_MASK == MULTIPLY_BITS:   # before data processing: its Rs is no shift
        return MULTIPLY
    if is_half(word):                   # L is bit 20; bit 22 (I) marks the immediate offset
        if word >> 20 & 1:
            return LOAD_HALF_IMMEDIATE if word >> 22 & 1 else LOAD_HALF_REGISTER
        return STORE_HALF_IMMEDIATE if word >> 22 & 1 else STORE_HALF_REGISTER
    if is_move_16(word):
        return MOVE_16
    if op == 0:
        return DP_IMMEDIATE if funct5 else DP_REGISTER
    if op == 1:
        if word >> 20 & 1:
            return LOAD_REGISTER if funct5 else LOAD_IMMEDIATE
        return STORE_REGISTER if funct5 else STORE_IMMEDIATE
    if op == 3:
        return SYSTEM_CALL
    if not funct5:
        return LOAD_MULTIPLE if word >> 20 & 1 else STORE_MULTIPLE
    return BRANCH_LINK if word >> 24 & 1 else BRANCH


def shift_in_use(word):
    """True when a shift by an immediate changes its input: LSL #0 is the only one that does
    not (an amount of 0 means 32 for LSR and ASR, and RRX for ROR). A shift by a register is in
    use as far as the word tells: the control unit cannot see the register's value, so Shift is
    1, and an amount of 0 in Rs then leaves the value and C as they are."""
    return bool(word >> 5 & 0x7F) or shifted_by_register(word)


def decode(word):
    """The control signals of word (a Control)."""
    note = outside_note(word)
    if note:
        return Control(OUTSIDE, note, {})
    kind = _class_of(word)
    signals = dict(zip(MAIN_SIGNALS, MAIN_DECODER[kind]))
    signals.update(ALUControl=ALU_ADD, FlagW="00", NoWrite="0", Shift="0", ShiftC="0",
                   Size=SIZE_WORD, Signed="0", StoreSrc="0", Link="0", Syscall="0", AdrSrc="0",
                   BaseW="0", Hold="0", ShiftReg="0")
    if kind in (SYSTEM_CALL, NO_OPERATION):     # the system does the work, or nothing is done:
        signals["ALUControl"] = "XXXX"          # the ALU's operation is X
    if kind == SYSTEM_CALL:
        signals["Syscall"] = "1"
    if kind in (DP_REGISTER, DP_IMMEDIATE, BRANCH_EXCHANGE, BRANCH_LINK_EXCHANGE, MULTIPLY,
                MOVE_16):
        table = {MULTIPLY: MUL_DECODER, MOVE_16: MOVE_DECODER}.get(kind, ALU_DECODER)
        cmd, s = word >> 21 & 0xF, word >> 20 & 1
        control, flag_write, no_write = TEQ_ROW if cmd == TEQ and s and kind != MULTIPLY \
            else table[cmd]
        signals.update(ALUControl=control, NoWrite=no_write, FlagW=flag_write if s else "00")
    if kind == DP_REGISTER and shifted_by_register(word):
        signals["ShiftReg"] = "1"       # the A4 multiplexer takes Rs, the shifter RD4[7:0]
    if kind in (DP_REGISTER, LOAD_REGISTER, STORE_REGISTER):
        signals["Shift"] = "1" if shift_in_use(word) else "0"
    if signals["FlagW"] == "10":        # logical: C comes from the shifter or the rotation
        rotated = kind == DP_IMMEDIATE and word >> 8 & 0xF
        if signals["Shift"] == "1" or rotated:
            signals["ShiftC"] = "1"
    if word >> 26 & 3 == 1 or kind in HALVES:
        if kind in HALVES:              # bits 6:5 are S and H: Signed, and a halfword or a byte
            signals["Size"] = SIZE_HALF if word >> 5 & 1 else SIZE_BYTE
            signals["Signed"] = str(word >> 6 & 1)
        else:                           # B, bit 22: a byte
            signals["Size"] = SIZE_BYTE if word >> 22 & 1 else SIZE_WORD
        if not word >> 23 & 1:          # U = 0: a negative offset
            signals["ALUControl"] = ALU_SUB
        pre = word >> 24 & 1
        signals["AdrSrc"] = "0" if pre else "1"         # post-indexing: the address is the base
        signals["BaseW"] = "1" if not pre or word >> 21 & 1 else "0"
    if kind in MULTIPLE:
        if not word >> 23 & 1:          # U = 0: the passes count down
            signals["ALUControl"] = ALU_SUB
        write_back = word >> 21 & 1
        signals["AdrSrc"] = "1" if write_back and not word >> 24 & 1 else "0"
        signals["BaseW"] = str(write_back)
        if kind == STORE_MULTIPLE:      # the register of each pass is read on A4
            signals["StoreSrc"] = "1"
    if kind in (STORE_REGISTER, STORE_HALF_REGISTER):  # the data is read on A4, RD4
        signals["StoreSrc"] = "1"
    if kind in (BRANCH_LINK, BRANCH_LINK_EXCHANGE):
        signals["Link"] = "1"
    # The pass counter decides PCS for each pass of an LDM: 1 for the pass that loads the PC. The
    # PC Logic compares Instr 15:12 with 15: a multiply inside the datapath never has 15 there.
    writes_pc = (word >> 12 & 0xF == PC_NUMBER and signals["RegW"] == "1"
                 and kind not in MULTIPLE)
    signals["PCS"] = "1" if writes_pc or signals["Branch"] == "1" else "0"
    return Control(kind, "", signals)


# The parts of the datapath -----------------------------------------------------------------

def alu(control, a, b, c=0, carry_in=0):
    """(result, flags N Z C V) of the ALU: C and V come from the adder, and are 0 otherwise. The
    adder adds its first operand, its second or the inverse of it, and a carry in: 0 for ADD, 1
    to subtract (SUB, and RSB with the operands swapped), and carry_in, CarryIn, the C flag, for
    ADC, SBC and RSC. The multiplier makes the low 32 bits of a x b, and for MLA of a x b + c (c
    is RD4). MOVT joins the low half of b, as the high half, to the low half of c."""
    carry = overflow = 0
    adder = {ALU_ADD: (a, b, 0), ALU_SUB: (a, ~b & MASK, 1), ALU_RSB: (b, ~a & MASK, 1),
             ALU_ADC: (a, b, carry_in), ALU_SBC: (a, ~b & MASK, carry_in),
             ALU_RSC: (b, ~a & MASK, carry_in)}
    if control in adder:
        first, second, extra = adder[control]
        total = first + second + extra
        result = total & MASK
        carry = total >> 32
        overflow = (~(first ^ second) & (first ^ result)) >> 31 & 1
    elif control == ALU_AND:
        result = a & b
    elif control == ALU_ORR:
        result = a | b
    elif control == ALU_EOR:
        result = a ^ b
    elif control == ALU_BIC:
        result = a & ~b & MASK
    elif control == ALU_MOV:
        result = b
    elif control == ALU_MUL:
        result = a * b & MASK
    elif control == ALU_MLA:
        result = (a * b + c) & MASK
    elif control == ALU_MOVT:
        result = (b & 0xFFFF) << 16 | c & 0xFFFF
    elif control == ALU_MVN:
        result = ~b & MASK
    else:
        raise ValueError(f"no ALU operation has ALUControl {control}")
    return result, (result >> 31) << 3 | (result == 0) << 2 | carry << 1 | overflow


def _rotate(value, amount):
    return (value >> amount | value << 32 - amount) & MASK if amount else value


def shift(value, kind, amount, carry):
    """(result, carry out) of the shifter for a shift by the five bits amount of the word:
    kind 0 to 3 is LSL, LSR, ASR, ROR; carry is the C flag."""
    if kind == 0:
        if not amount:
            return value, carry
        return value << amount & MASK, value >> 32 - amount & 1
    if kind == 1:
        if not amount:
            return 0, value >> 31
        return value >> amount, value >> amount - 1 & 1
    if kind == 2:
        signed = value - (value >> 31 << 32)
        amount = amount or 32
        return signed >> amount & MASK, signed >> amount - 1 & 1
    if not amount:                      # RRX
        return carry << 31 | value >> 1, value & 1
    result = _rotate(value, amount)
    return result, result >> 31


def shift_by_register(value, kind, amount, carry):
    """(result, carry out) of the shifter for a shift by a register: amount is RD4[7:0], from 0
    to 255. An amount of 0 changes nothing and keeps C. From 32 on every bit has gone: LSL and
    LSR give 0 (the carry is the last bit out at 32, 0 after), ASR gives 32 copies of the sign
    bit, and ROR turns by the amount modulo 32 (by 0: C becomes bit 31)."""
    if not amount:
        return value, carry
    if kind == 0:
        if amount < 32:
            return value << amount & MASK, value >> 32 - amount & 1
        return 0, (value & 1 if amount == 32 else 0)
    if kind == 1:
        if amount < 32:
            return value >> amount, value >> amount - 1 & 1
        return 0, (value >> 31 if amount == 32 else 0)
    if kind == 2:
        if amount < 32:
            signed = value - (value >> 31 << 32)
            return signed >> amount & MASK, signed >> amount - 1 & 1
        return (MASK if value >> 31 else 0), value >> 31
    turn = amount & 31
    if not turn:
        return value, value >> 31
    result = _rotate(value, turn)
    return result, result >> 31


def extend(word, imm_src):
    """The Extend block's output (ExtImm) from the bits of word: 000 imm8 rotated by twice
    Instr 11:8, 001 imm12, 010 imm24 sign-extended and times 4, 100 imm16 (imm4, Instr 19:16, and
    imm12) and 101 imm8 (imm4H, Instr 11:8, and imm4L, Instr 3:0), zero-extended. 011, the pass
    counter's offset, takes no bits of the word."""
    if imm_src == "000":
        return _rotate(word & 0xFF, 2 * (word >> 8 & 0xF))
    if imm_src == "001":
        return word & 0xFFF
    if imm_src == "010":
        imm24 = word & 0xFFFFFF
        return (imm24 - (imm24 >> 23 << 24)) * 4 & MASK
    if imm_src == "100":
        return word >> 4 & 0xF000 | word & 0xFFF
    if imm_src == "101":
        return word >> 4 & 0xF0 | word & 0xF
    raise ValueError(f"ImmSrc {imm_src} takes no bits of the word")


def shift_text(word):
    """The shift of a shifted register as a program writes it ("" for none): "LSL #3", or for a
    shift by a register "LSL R3"."""
    amount, kind = word >> 7 & 0x1F, word >> 5 & 3
    if shifted_by_register(word):
        return f"{SHIFT_NAMES[kind]} R{word >> 8 & 0xF}"
    if not amount and kind == 0:
        return ""
    if not amount and kind == 3:
        return "RRX"
    return f"{SHIFT_NAMES[kind]} #{amount or 32}"


def condition_text(cond, flags):
    """The condition check of condition code cond for the flags N Z C V ("" for 1111)."""
    if cond == 0xF:
        return ""
    name = CONDITIONS[cond]
    if cond == 0xE:
        return f"{name}: always executes"
    read = ", ".join(f"{flag} = {flags >> FLAG_BITS[flag] & 1}" for flag in CONDITION_FLAGS[cond])
    return f"{name}: {read}, {'executes' if _passes(cond, flags) else 'does not execute'}"


def _passes(cond, flags):
    return bool(condition_passed(cond, flags << 28))


def flag_text(flags):
    """The flags N Z C V as four binary digits."""
    return f"{flags:04b}"


# An instruction on the datapath ------------------------------------------------------------

def trace(pc, word, registers, cpsr, read_memory, loaded=None):
    """Word at pc on the datapath (a Trace), from the state before it.

    registers holds R0 to R15 (R15 is not looked at: it reads as PC + 8) and
    cpsr the flags. read_memory(address, size) gives the bytes a load would
    read, or None when they cannot be known; for a load that ran, loaded is
    the value it got instead (for an LDM, {register: value}). An LDM or STM
    gives the Trace of its last pass, with every pass in Trace.passes.
    """
    flags = cpsr >> 28
    cond = word >> 28
    thumb = cpsr & THUMB
    control = decode(word)
    text = "Thumb code" if thumb else basic(word, pc)
    if thumb or control.note:
        condition = "" if thumb else condition_text(cond, flags)
        return Trace(pc, word, text, OUTSIDE, NOTE_THUMB if thumb else control.note, condition,
                     {}, {}, flags, flags)

    plus4, plus8 = (pc + 4) & MASK, (pc + 8) & MASK
    if control.kind == SYSTEM_CALL:
        return _system_trace(pc, word, text, control, flags)
    if control.kind == NO_OPERATION:
        return _nop_trace(pc, word, registers, text, control, flags)
    if control.kind in MULTIPLE:
        return _multiple_trace(pc, word, registers, flags, read_memory, loaded, control, text)

    def register(number):
        return plus8 if number == PC_NUMBER else registers[number]

    s = dict(control.signals)
    executes = _passes(cond, flags)
    s["CondEx"] = "1" if executes else "0"
    s["PCSrc"] = "1" if s["PCS"] == "1" and executes else "0"
    s["RegWrite"] = "1" if s["RegW"] == "1" and s["NoWrite"] == "0" and executes else "0"
    s["MemWrite"] = "1" if s["MemW"] == "1" and executes else "0"
    s["FlagWrite"] = s["FlagW"] if executes else "00"
    s["BaseWrite"] = "1" if s["BaseW"] == "1" and executes else "0"

    rn, rd, rs, rm = word >> 16 & 0xF, word >> 12 & 0xF, word >> 8 & 0xF, word & 0xF
    mul = s["Mul"] == "1"               # MUL and MLA: RA1 takes Rs, A3 takes Instr 19:16
    # MLA reads Ra (Instr 15:12) on A4 for the multiplier to add; MOVT reads Rd there, whose low
    # half it keeps: RD4 goes into the ALU.
    into_alu = s["ALUControl"] in (ALU_MLA, ALU_MOVT)
    shift_reg = s["ShiftReg"] == "1"    # a shift by a register: A4 takes Rs (Instr 11:8)
    ra1 = rs if mul else PC_NUMBER if s["RegSrc"][1] == "1" else rn
    # For a load with a register offset the table says X for RegSrc1: only Rm gives the address.
    ra2 = rd if s["RegSrc"][0] == "1" else rm if s["ALUSrc"] == "0" else None
    a4 = rs if shift_reg else rd if s["StoreSrc"] == "1" or into_alu else None
    a3 = None
    if s["RegW"] == "1" and s["NoWrite"] == "0":     # CMP, CMN and TST have no destination
        a3 = rn if mul else LINK_REGISTER if s["Link"] == "1" else rd
    rd1 = register(ra1)
    rd2 = None if ra2 is None else register(ra2)
    rd4 = None if a4 is None else register(a4)
    ext_imm = None if "X" in s["ImmSrc"] else extend(word, s["ImmSrc"])

    carry_in = flags >> 1 & 1
    shifted = shift_carry = None
    if shift_reg and s["Shift"] == "1":     # the amount is RD4[7:0]; 0 leaves value and C
        shifted, shift_carry = shift_by_register(rd2, word >> 5 & 3, rd4 & 0xFF, carry_in)
    elif s["Shift"] == "1":
        shifted, shift_carry = shift(rd2, word >> 5 & 3, word >> 7 & 0x1F, carry_in)
    elif s["ALUSrc"] == "0":
        shifted, shift_carry = rd2, carry_in
    elif s["ImmSrc"] == "000":
        shift_carry = ext_imm >> 31     # a rotated immediate's carry
    if shifted is None and rd2 is not None:
        shifted = rd2                   # a store's data passes the shifter too, unchanged
    src_b = ext_imm if s["ALUSrc"] == "1" else shifted
    alu_result, alu_flags = alu(s["ALUControl"], rd1, src_b, rd4 if into_alu else 0, carry_in)
    if s["ShiftC"] == "1":
        alu_flags = alu_flags & ~2 | shift_carry << 1
    new_flags = flags
    if s["FlagWrite"][0] == "1":
        new_flags = new_flags & 0b0011 | alu_flags & 0b1100
    if s["FlagWrite"][1] == "1":
        new_flags = new_flags & 0b1100 | alu_flags & 0b0011
    elif s["FlagWrite"][0] == "1" and s["ShiftC"] == "1":
        new_flags = new_flags & 0b1101 | alu_flags & 0b0010

    write_data = None
    if s["MemW"] == "1":
        write_data = rd4 if s["StoreSrc"] == "1" else rd2
    memory = s["MemW"] == "1" or s["MemtoReg"] == "1"
    address = None
    if memory:                          # AdrSrc 1, post-indexing: the address is the old base
        address = rd1 if s["AdrSrc"] == "1" else alu_result
    read_data = None
    if s["MemtoReg"] == "1" and executes:   # after the load extender: Size and Signed
        read_data = loaded if loaded is not None else _read(read_memory, address, s["Size"],
                                                            s["Signed"])
    result = {"0": alu_result, "1": read_data, "X": None}[s["MemtoReg"]]
    wd3 = None
    if a3 is not None:
        wd3 = plus4 if s["Link"] == "1" else result
    next_pc = plus4
    to_thumb = False
    if s["PCSrc"] == "1" and result is None:
        next_pc = None
    elif s["PCSrc"] == "1":
        next_pc = result & ~1           # bit 0 chooses Thumb code; bit 1 stays in the address
        to_thumb = bool(result & 1)

    uses_a = s["ALUControl"] not in NO_FIRST_OPERAND      # MOV, MVN and BX read no RD1
    values = {"PC": pc, "PC'": next_pc, "Instr": word, "PCPlus4": plus4, "PCPlus8": plus8,
              "RA1": ra1 if uses_a else None, "RA2": ra2, "A3": a3, "A4": a4,
              "RD1": rd1 if uses_a else None, "RD2": rd2, "RD4": rd4,
              "ExtImm": ext_imm, "Shifted": shifted, "SrcA": rd1 if uses_a else None,
              "SrcB": src_b, "ShiftCarry": shift_carry,
              "ALUResult": alu_result, "ALUFlags": alu_flags, "WriteData": write_data,
              "ReadData": read_data, "Result": result, "WD3": wd3, "Address": address,
              "A5": rn if s["BaseW"] == "1" else None,
              "WD5": alu_result if s["BaseW"] == "1" else None,
              "PassReg": None, "Offset": None, "List": None,
              "CarryIn": carry_in if s["ALUControl"] in CARRY_CODES else None}
    hardware = _hardware(word, s, register, values, carry_in)
    return Trace(pc, word, text, control.kind, "", condition_text(cond, flags), s, values, flags,
                 new_flags, _stages(s, values), to_thumb, hardware)


WIRES = ("PC", "PC'", "Instr", "PCPlus4", "PCPlus8", "RA1", "RA2", "A3", "A4", "RD1", "RD2", "RD4",
         "ExtImm", "Shifted", "SrcA", "SrcB", "ALUResult", "ALUFlags", "WriteData", "ReadData",
         "Result", "WD3", "Address", "A5", "WD5", "PassReg", "Offset", "List", "CarryIn")


def _nop_trace(pc, word, registers, text, control, flags):
    """A NOP on the datapath: fetched and decoded; its row of the Main Decoder writes nothing,
    and the PC goes on. Nothing after the decoder works for it: its wires have no value (in
    Trace.hardware the circuit's values behind its X, as for any instruction)."""
    cond = word >> 28
    executes = _passes(cond, flags)
    s = dict(control.signals)
    s.update(CondEx="1" if executes else "0", PCSrc="0", RegWrite="0", MemWrite="0",
             FlagWrite="00", BaseWrite="0")
    plus4, plus8 = (pc + 4) & MASK, (pc + 8) & MASK
    values = dict.fromkeys(WIRES)
    values.update({"PC": pc, "PC'": plus4, "Instr": word, "PCPlus4": plus4, "PCPlus8": plus8})
    stages = (Stage(STAGES[0], frozenset({"PC", "Instr", "PCPlus4"}),
                    frozenset({"PCReg", "IMem", "Add4"})),
              Stage(STAGES[1], frozenset({"Cond", "Op", "Funct"}), frozenset({"Control"})),
              Stage(STAGES[2], frozenset(), frozenset()),
              Stage(STAGES[3], frozenset(), frozenset()),
              Stage(STAGES[4], frozenset({"PC'", "PCFeed"}), frozenset({"PCMux"})))

    def register(number):
        return plus8 if number == PC_NUMBER else registers[number]
    hardware = _hardware(word, s, register, values, flags >> 1 & 1)
    return Trace(pc, word, text, NO_OPERATION, "", condition_text(cond, flags), s, values, flags,
                 flags, stages, False, hardware)


def _system_trace(pc, word, text, control, flags):
    """An SVC on the datapath: fetched and decoded; then the control unit hands the call to the
    system (ARES performs the service) and the PC goes on. Nothing of the datapath after the
    decoder takes part: its wires have no value."""
    cond = word >> 28
    executes = _passes(cond, flags)
    s = dict(control.signals)
    s.update(CondEx="1" if executes else "0", PCSrc="0", RegWrite="0", MemWrite="0",
             FlagWrite="00", BaseWrite="0", Syscall="1" if executes else "0")
    plus4 = (pc + 4) & MASK
    values = dict.fromkeys(WIRES)
    values.update({"PC": pc, "PC'": plus4, "Instr": word, "PCPlus4": plus4,
                   "PCPlus8": (pc + 8) & MASK, "SvcNum": word & 0xFFFFFF})
    stages = (Stage(STAGES[0], frozenset({"PC", "Instr", "PCPlus4"}),
                    frozenset({"PCReg", "IMem", "Add4"})),
              Stage(STAGES[1], frozenset({"Cond", "Op", "Funct", "Rd", "SvcNum", "Syscall"}),
                    frozenset({"Control", "System"})),
              Stage(STAGES[2], frozenset(), frozenset()), Stage(STAGES[3], frozenset(), frozenset()),
              Stage(STAGES[4], frozenset({"PC'", "PCFeed"}), frozenset({"PCMux"})))
    return Trace(pc, word, text, SYSTEM_CALL, "", condition_text(cond, flags), s, values, flags,
                 flags, stages, False, dict(values))


def pass_order(word):
    """The passes of an LDM or STM word, in the order they run: [(register, offset)], where offset
    is what the pass counter gives the ALU through Extend (the ALU adds it to the base as it stands
    then, or subtracts it when U is 0). With write-back the base moves 4 at each pass, through the
    base write port: counting up, the registers go from the lowest; counting down, from the
    highest, so that each pass is next to the base. Without it the base stays, and each offset is
    the register's distance from it."""
    pre, up, write_back = word >> 24 & 1, word >> 23 & 1, word >> 21 & 1
    registers = [number for number in range(16) if word >> number & 1]
    if write_back:
        return [(number, 4) for number in (registers if up else registers[::-1])]
    count = len(registers)
    if up:                              # IA: 4(k - 1), IB: 4k
        return [(number, 4 * (k - 1 + pre)) for k, number in enumerate(registers, 1)]
    return [(number, 4 * (count - k + pre)) for k, number in enumerate(registers, 1)]  # DA, DB


def _multiple_trace(pc, word, registers, flags, read_memory, loaded, control, text):
    """An LDM or STM: one pass through the datapath for each register (pass_order()), each from the
    registers as the pass before left them. A failed condition makes one pass that writes
    nothing. The Trace of the last pass, with all of them in its passes."""
    executes = _passes(word >> 28, flags)
    order = pass_order(word) if executes else pass_order(word)[:1]
    state = list(registers[:16])
    base = word >> 16 & 0xF
    traces = []
    for number, (register, offset) in enumerate(order, 1):
        made = _pass(pc, word, state, flags, read_memory, loaded, control, text, register, offset,
                     number, len(order), executes)
        traces.append(made)
        values = made.values
        if made.signals["BaseWrite"] == "1":
            state[base] = values["WD5"]
        if made.signals["RegWrite"] == "1" and register != PC_NUMBER and values["WD3"] is not None:
            state[register] = values["WD3"]     # (a value not known yet leaves the old one)
    return replace(traces[-1], passes=tuple(traces))


def _pass(pc, word, state, flags, read_memory, loaded, control, text, register, offset, number,
          count, executes):
    """Pass number of count of an LDM or STM: a load or store of register at the base and the
    offset; state holds R0 to R14 as the passes before left them."""
    plus4, plus8 = (pc + 4) & MASK, (pc + 8) & MASK
    cond = word >> 28
    load = control.kind == LOAD_MULTIPLE
    last = number == count

    def read(n):
        return plus8 if n == PC_NUMBER else state[n]

    s = dict(control.signals)
    s["CondEx"] = "1" if executes else "0"
    s["PCS"] = "1" if load and register == PC_NUMBER else "0"
    s["PCSrc"] = "1" if s["PCS"] == "1" and executes else "0"
    s["RegWrite"] = "1" if load and executes else "0"
    s["MemWrite"] = "1" if not load and executes else "0"
    s["FlagWrite"] = "00"
    s["BaseWrite"] = "1" if s["BaseW"] == "1" and executes else "0"
    s["Hold"] = "0" if last else "1"    # the pass counter keeps the PC until the last pass
    base = word >> 16 & 0xF
    rd1 = read(base)
    alu_result, alu_flags = alu(s["ALUControl"], rd1, offset)
    address = rd1 if s["AdrSrc"] == "1" else alu_result
    a4 = rd4 = write_data = read_data = None
    if not load:
        a4, rd4 = register, read(register)
        write_data = rd4
    elif executes:
        if isinstance(loaded, dict) and register in loaded:
            read_data = loaded[register]
        else:
            read_data = _read(read_memory, address, SIZE_WORD)
    result = read_data if load else None
    next_pc, to_thumb = plus4, False
    if s["PCSrc"] == "1":
        next_pc = None if result is None else result & ~1
        to_thumb = result is not None and bool(result & 1)
    values = dict.fromkeys(WIRES)
    values.update({"PC": pc, "PC'": next_pc, "Instr": word, "PCPlus4": plus4, "PCPlus8": plus8,
                   "RA1": base, "A3": register if load else None, "A4": a4, "RD1": rd1,
                   "RD4": rd4, "ExtImm": offset, "SrcA": rd1, "SrcB": offset,
                   "ALUResult": alu_result, "ALUFlags": alu_flags, "WriteData": write_data,
                   "ReadData": read_data, "Result": result, "WD3": result if load else None,
                   "Address": address, "A5": base if s["BaseW"] == "1" else None,
                   "WD5": alu_result if s["BaseW"] == "1" else None, "PassReg": register,
                   "Offset": offset, "List": word & 0xFFFF})
    rm = word & 0xF                     # behind the X of RegSrc1: RA2 reads Rm
    hardware = dict(values)
    field = word >> 12 & 0xF            # behind the pass counter: what A3 and A4 would take
    hardware.update(RA2=rm, RD2=read(rm), Shifted=read(rm), ShiftCarry=flags >> 1 & 1,
                    A3=register if load else field, A4=field if load else register,
                    RD4=read(field) if load else rd4, WriteData=rd4 if not load else read(rm))
    if not load:
        hardware["Result"] = values["ALUResult"]
    stages = _pass_stages(s, load)
    return Trace(pc, word, text, control.kind, "", condition_text(cond, flags), s, values, flags,
                 flags, stages, to_thumb, hardware, (), number, count,
                 tuple(state[:15]) + (plus8,))


def _pass_stages(s, load):
    """The Stages of a pass of an LDM or STM (see _stages())."""
    executes = s["CondEx"] == "1"
    fetch = Stage(STAGES[0], frozenset({"PC", "Instr", "PCPlus4"}),
                  frozenset({"PCReg", "IMem", "Add4"}))
    wires = {"Cond", "Op", "Funct", "List", "Rn", "RA1", "RD1", "PassReg", "Offset", "ImmSrc",
             "ExtImm", "RegSrc"}
    blocks = {"Control", "RA1Mux", "RegFile", "Extend"}
    if not load:
        wires |= {"RD4"}
    decode_stage = Stage(STAGES[1], frozenset(wires), frozenset(blocks))
    execute = Stage(STAGES[2], frozenset({"SrcA", "SrcB", "ALUResult", "ALUControl", "ALUSrc"}),
                    frozenset({"ALU", "ALUSrcMux"}))
    wires, blocks = set(), set()
    if executes:
        wires |= {"Address", "AdrSrc"}
        blocks |= {"AdrSrcMux", "DMem"}
        if load:
            wires.add("ReadData")
        else:
            wires |= {"WriteData", "MemWrite", "StoreSrc"}
            blocks.add("StoreMux")
    memory = Stage(STAGES[3], frozenset(wires), frozenset(blocks))
    wires, blocks = {"PC'"}, {"PCMux"}
    wires.add("ResultPC" if s["PCSrc"] == "1" else "PCFeed")
    if s["Hold"] == "1":
        wires.add("Hold")
    if load and executes:
        wires |= {"WD3", "RegWrite", "Result", "MemtoReg"}
        blocks |= {"RegFile", "WD3Mux", "ResultMux"}
    if s["BaseWrite"] == "1":
        wires |= {"WD5", "BaseWrite"}
    write_back = Stage(STAGES[4], frozenset(wires), frozenset(blocks))
    return fetch, decode_stage, execute, memory, write_back


def filled(value):
    """A control signal's value in the circuit drawn: each X is a 0, as the textbook's own
    hardware description fills the X entries of its tables."""
    return value.replace("X", "0")


def _hardware(word, s, register, values, carry_in):
    """Each wire's value in the circuit drawn (Trace.hardware), where values leaves None for what
    only an X decides: the register file reads, Extend builds, the shifter shifts and the
    multiplexers choose also there, with every X a 0. The data memory alone reads only for a
    load that runs (a read can take a device's data), so ReadData is the same in both."""
    f = {name: filled(value) for name, value in s.items()}
    rn, rd, rs, rm = word >> 16 & 0xF, word >> 12 & 0xF, word >> 8 & 0xF, word & 0xF
    mul = f["Mul"] == "1"               # the third inputs of the RA1 and A3 multiplexers
    shift_reg = f["ShiftReg"] == "1"    # the A4 multiplexer's second input, and the shifter's
    ra1 = rs if mul else PC_NUMBER if f["RegSrc"][1] == "1" else rn
    ra2 = rd if f["RegSrc"][0] == "1" else rm
    a3 = rn if mul else LINK_REGISTER if f["Link"] == "1" else rd
    a4 = rs if shift_reg else rd
    rd1, rd2, rd4 = register(ra1), register(ra2), register(a4)
    ext_imm = extend(word, f["ImmSrc"])
    shifted, carry = rd2, carry_in
    if f["Shift"] == "1" and shift_reg:
        shifted, carry = shift_by_register(rd2, word >> 5 & 3, rd4 & 0xFF, carry_in)
    elif f["Shift"] == "1":
        shifted, carry = shift(rd2, word >> 5 & 3, word >> 7 & 0x1F, carry_in)
    elif f["ALUSrc"] == "1" and f["ImmSrc"] == "000":
        carry = ext_imm >> 31
    result = values["ReadData"] if f["MemtoReg"] == "1" else values["ALUResult"]
    hardware = dict(values)
    hardware.update(RA1=ra1, RA2=ra2, A3=a3, A4=a4,
                    RD1=rd1, SrcA=rd1, RD2=rd2, RD4=rd4, ExtImm=ext_imm, Shifted=shifted,
                    ShiftCarry=carry, WriteData=rd4 if f["StoreSrc"] == "1" else rd2,
                    Result=result, WD3=values["PCPlus4"] if f["Link"] == "1" else result,
                    CarryIn=carry_in)
    return hardware


def _read(read_memory, address, size, signed="0"):
    """What the data memory puts on RD for a load of Size size at address: the bytes read, and
    for a halfword or a byte what its load extender makes of them, the bits above filled with
    zeros or, when signed is "1", with copies of the sign bit. None when the bytes cannot be
    known."""
    count = SIZES[size]
    data = read_memory(address, count)
    if data is None:
        return None
    value = int.from_bytes(data, "little")
    if signed == "1" and value >> 8 * count - 1:
        value -= 1 << 8 * count
    return value & MASK


def _stages(s, values):
    """The Stages of an instruction that lies inside (see trace()).

    Control signals count in the stage that uses them. A failed condition
    leaves the memory and the writes gray: the PC just goes on.
    """
    executes = s["CondEx"] == "1"
    ra1, ra2, a4 = values["RA1"], values["RA2"], values["A4"]
    uses_a = s["ALUControl"] not in NO_FIRST_OPERAND
    uses_b = ra2 is not None
    fetch = Stage(STAGES[0], frozenset({"PC", "Instr", "PCPlus4"}),
                  frozenset({"PCReg", "IMem", "Add4"}))

    mul = s["Mul"] == "1"               # MUL and MLA: Op2 tells them; Mul chooses Rs and 19:16
    shift_reg = s["ShiftReg"] == "1"    # a shift by a register: Op2 tells it; ShiftReg takes Rs
    wires = {"Cond", "Op", "Funct", "Rd", "RegSrc"} | ({"Op2", "Mul"} if mul else set())
    if shift_reg:
        wires |= {"Op2", "ShiftReg"}
    blocks = {"Control"}
    if uses_a:
        wires |= {"RA1", "RD1"}
        wires.add("Rs" if mul else "Const15" if s["RegSrc"][1] == "1" else "Rn")
        blocks |= {"RA1Mux", "RegFile"}
    if uses_b:
        wires |= {"RA2", "RD2"}
        wires |= {"RdField", "RdToRA2"} if s["RegSrc"][0] == "1" else {"Rm"}
        blocks |= {"RA2Mux", "RegFile"}
    if a4 is not None:
        wires |= {"A4", "RD4"} | ({"Rs"} if shift_reg else {"RdField"})
        blocks |= {"RegFile", "A4Mux"}
    if "X" not in s["ImmSrc"]:
        wires |= {"ImmSrc", "Imm", "ExtImm"}
        blocks.add("Extend")
    if (uses_a and ra1 == PC_NUMBER) or (uses_b and ra2 == PC_NUMBER) or a4 == PC_NUMBER:
        wires.add("PCPlus8")
        blocks.add("Add8")
    decode_stage = Stage(STAGES[1], frozenset(wires), frozenset(blocks))

    wires = {"SrcB", "ALUResult", "ALUControl", "ALUSrc"}
    blocks = {"ALU", "ALUSrcMux"}
    if uses_a:
        wires.add("SrcA")
    if s["ALUSrc"] == "0":
        wires.add("Shifted")
    if s["Shift"] == "1":
        wires |= {"Shift", "Shamt"}
        blocks.add("Shifter")
    if s["FlagWrite"] != "00":
        wires.add("ALUFlags")
        if s["ShiftC"] == "1":
            wires.add("ShiftC")
    if s["ALUControl"] in (ALU_MLA, ALU_MOVT):  # RD4 into the ALU: MLA adds it, MOVT keeps
        wires.add("RD4ToALU")                   # its low half
    if shift_reg:                       # RD4 comes into the shifter: its amount is RD4[7:0]
        wires.add("RD4ToShifter")
        blocks.add("Shifter")
    if s["ALUControl"] in CARRY_CODES:  # ADC, SBC and RSC: the C flag into the adder
        wires.add("CarryIn")
    execute = Stage(STAGES[2], frozenset(wires), frozenset(blocks))

    wires, blocks = set(), set()
    if executes and (s["MemW"] == "1" or s["MemtoReg"] == "1"):
        wires |= {"ALUResult", "Address", "AdrSrc"}
        blocks |= {"DMem", "AdrSrcMux"}
        wires.add("Size")              # a word, a halfword or a byte
        if s["MemW"] == "1":
            wires |= {"WriteData", "MemWrite"}
            blocks.add("StoreMux")
            if s["StoreSrc"] == "1":
                wires |= {"RD4", "StoreSrc"}
            else:
                wires.add("RD2Store")
        else:                           # the load extender: Signed
            wires |= {"ReadData", "Signed"}
    memory = Stage(STAGES[3], frozenset(wires), frozenset(blocks))

    wires, blocks = {"PC'"}, {"PCMux"}
    to_pc = s["PCSrc"] == "1"
    to_register = s["RegWrite"] == "1" and values["A3"] != PC_NUMBER
    from_result = to_pc or (to_register and s["Link"] == "0")
    if to_pc:
        wires |= {"PCSrc", "ResultPC"}
    else:
        wires.add("PCFeed")
    if to_register:
        wires |= {"A3", "WD3", "RegWrite"}
        blocks |= {"RegFile", "WD3Mux", "A3Mux"}
        if s["Link"] == "1":
            wires |= {"Link", "Const14", "LinkFeed"}
        elif s["Mul"] == "1":           # MUL and MLA write the register of Instr 19:16
            wires |= {"Mul", "RnToA3", "ResultReg"}
        else:
            wires |= {"RdField", "RdToA3", "ResultReg"}
    if from_result:
        wires |= {"Result", "MemtoReg"}
        blocks.add("ResultMux")
        wires.add("ReadData" if s["MemtoReg"] == "1" else "ALUBypass")
    if s["BaseWrite"] == "1":
        wires |= {"WD5", "BaseWrite"}
        blocks.add("RegFile")
    write_back = Stage(STAGES[4], frozenset(wires), frozenset(blocks))
    return fetch, decode_stage, execute, memory, write_back


# Instructions of a machine -----------------------------------------------------------------

def _word(read, address):
    data = read(address, 4)
    return None if data is None else struct.unpack("<I", data)[0]


def _peek(machine):
    """What reads memory without touching a device: None for what is no memory."""
    def read(address, size):
        try:
            return machine.read_memory(address, size)
        except RuntimeFault:
            return None
    return read


def _before(machine, change):
    """The same for the memory as it was before the instruction of change ran."""
    peek = _peek(machine)

    def read(address, size):
        data = peek(address, size)
        if data is None:
            return None
        data = bytearray(data)
        for start, old in reversed(change.writes):
            for index, byte in enumerate(old):
                offset = (start + index - address) & MASK
                if offset < size:
                    data[offset] = byte
        return bytes(data)
    return read


def executed(machine, change):
    """The Trace of the instruction that change (of machine.history) recorded, machine having
    just run it: from the registers before it. A load's value is what it left in its register:
    reading the memory again could take a character from the JTAG UART."""
    registers = change.registers
    read = _before(machine, change)
    pc, cpsr = registers[SNAPSHOT_PC], registers[0]
    word = _word(read, pc)
    control = decode(word)
    loaded = None

    def got(number):
        return machine.pc | machine.cpsr >> 5 & 1 if number == PC_NUMBER else machine.reg(number)
    if control.kind == LOAD_MULTIPLE:
        loaded = {number: got(number) for number in range(16) if word >> number & 1}
    elif control.signals.get("MemtoReg") == "1":
        loaded = got(word >> 12 & 0xF)
    return trace(pc, word, registers[2:2 + 16], cpsr, read, loaded)


def upcoming(machine, pc=None):
    """The Trace of the instruction at pc (at PC when None) from the state now; None when there
    is no memory there. A load from a device has a value that cannot be known yet."""
    read = _peek(machine)
    pc = machine.pc if pc is None else pc
    word = _word(read, pc)
    if word is None:
        return None
    return trace(pc, word, [machine.reg(n) for n in range(16)], machine.cpsr, read)


REGISTER_NAMES = (["CPSR", "SPSR"] + [f"R{n}" for n in range(13)] + ["SP", "LR", "PC", "FPSCR",
                                                                    "FPEXC"]
                  + [f"D{n}" for n in range(32)])


LONGEST_WRITE = 8               # bytes that a memory change shows as a value


def changes(machine, change):
    """What the instruction of change did, machine having just run it: one line for each
    register changed, and one for each place of memory it wrote, also when the place kept its
    value (a word stored over the same word reads 0x00000000 -> 0x00000000), each place once."""
    old = change.registers
    new = machine.uc.reg_read_batch(SNAPSHOT_REGISTERS)
    lines = []
    for index in (*range(2, len(old)), 0, 1):
        name, before, after = REGISTER_NAMES[index], old[index], new[index]
        if before == after or (index == SNAPSHOT_PC and after == before + 4):
            continue
        digits = 16 if name[0] == "D" else 8
        lines.append(f"{name} 0x{before:0{digits}x} -> 0x{after:0{digits}x}")
    peek = _peek(machine)
    seen = set()
    for address, bytes_before in change.writes:    # the first write of a place has its old value
        if (address, len(bytes_before)) in seen:
            continue
        seen.add((address, len(bytes_before)))
        bytes_after = peek(address, len(bytes_before))
        if bytes_after is None:                     # no memory: a device's register
            continue
        if len(bytes_before) > LONGEST_WRITE:
            lines.append(f"Memory 0x{address:08x}: {len(bytes_before)} bytes")
            continue
        digits = 2 * len(bytes_before)
        old_value = int.from_bytes(bytes_before, "little")
        new_value = int.from_bytes(bytes_after, "little")
        lines.append(f"Memory 0x{address:08x}: 0x{old_value:0{digits}x} -> "
                     f"0x{new_value:0{digits}x}")
    return lines
