# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The model of Tools > ARM X-Ray: one ARM instruction on the single-cycle datapath.

The datapath is the textbook's single-cycle ARM processor (credits.TEXTBOOK),
with the additions a real ARMv7 program needs: more ALU operations, a shifter, the shifter's carry, a
third read port for stores with a register offset, byte accesses, BL and BX.

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
from dataclasses import dataclass

from .disasm import basic
from .errors import RuntimeFault
from .machine import SNAPSHOT_PC, SNAPSHOT_REGISTERS, condition_passed

MASK = 0xFFFFFFFF
THUMB = 0x20                    # the T bit of CPSR
PC_NUMBER, LINK_REGISTER = 15, 14
BX_MASK, BX_BITS = 0x0FFFFFF0, 0x012FFF10   # BX Rm: all but the condition and Rm

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
OUTSIDE = "Outside the datapath"

# The Main Decoder: Branch, MemtoReg, MemW, ALUSrc, ImmSrc, RegW, RegSrc, ALUOp.
MAIN_SIGNALS = ("Branch", "MemtoReg", "MemW", "ALUSrc", "ImmSrc", "RegW", "RegSrc", "ALUOp")
MAIN_DECODER = {
    DP_REGISTER: ("0", "0", "0", "0", "XX", "1", "00", "1"),
    DP_IMMEDIATE: ("0", "0", "0", "1", "00", "1", "X0", "1"),
    STORE_IMMEDIATE: ("0", "X", "1", "1", "01", "0", "10", "0"),
    LOAD_IMMEDIATE: ("0", "1", "0", "1", "01", "1", "X0", "0"),
    BRANCH: ("1", "0", "0", "1", "10", "0", "X1", "0"),
    STORE_REGISTER: ("0", "X", "1", "0", "XX", "0", "00", "0"),
    LOAD_REGISTER: ("0", "1", "0", "0", "XX", "1", "00", "0"),
    BRANCH_LINK: ("1", "0", "0", "1", "10", "1", "X1", "0"),
    BRANCH_EXCHANGE: ("1", "0", "0", "0", "XX", "0", "0X", "1"),
}

# ALUControl: the textbook's four operations with 00 in front, and the additions'.
ALU_ADD, ALU_SUB, ALU_AND, ALU_ORR = "0000", "0001", "0010", "0011"
ALU_EOR, ALU_BIC, ALU_RSB, ALU_MOV, ALU_MVN = "0100", "0101", "0110", "0111", "1000"

# The ALU Decoder, by cmd: ALUControl, FlagW with S=1, NoWrite.
ALU_DECODER = {
    0b0100: (ALU_ADD, "11", "0"),
    0b0010: (ALU_SUB, "11", "0"),
    0b0000: (ALU_AND, "10", "0"),
    0b1100: (ALU_ORR, "10", "0"),
    0b0001: (ALU_EOR, "10", "0"),
    0b1110: (ALU_BIC, "10", "0"),
    0b0011: (ALU_RSB, "11", "0"),
    0b1101: (ALU_MOV, "10", "0"),
    0b1111: (ALU_MVN, "10", "0"),
    0b1010: (ALU_SUB, "11", "1"),       # CMP
    0b1011: (ALU_ADD, "11", "1"),       # CMN
    0b1000: (ALU_AND, "10", "1"),       # TST
    0b1001: (ALU_MOV, "00", "0"),       # BX, with S = 0: with S = 1 this cmd is TEQ, outside
}
NO_FIRST_OPERAND = (ALU_MOV, ALU_MVN)   # these use SrcB alone

# Why an instruction lies outside.
NOTE_CONDITION = "Condition 1111 marks instructions that have no row in the decoders."
NOTE_CARRY = "ADC, SBC and RSC need the C flag as an input of the ALU, which it does not have."
NOTE_TEQ = "TEQ has no row in the ALU Decoder."
NOTE_SHIFT = "The shifter takes its amount from the instruction, not from a register."
NOTE_RETURN = "An S with Rd = 15 also restores CPSR from SPSR, which this datapath cannot do."
NOTE_MULTIPLY = "The ALU has no multiplier."
NOTE_SIZES = "Halfword, doubleword and exclusive accesses have no row in the Main Decoder."
NOTE_SWAP = "SWP loads and stores at once, which has no row in the Main Decoder."
NOTE_OTHER = ("This instruction has no row in the decoders, like BLX, MOVW, MOVT, MRS, MSR, CLZ "
              "and NOP.")
NOTE_WRITE_BACK = ("Write-back and post-indexing write the base register too, and the register "
                   "file has one write port.")
NOTE_MULTIPLE = "LDM, STM, PUSH and POP move several registers: more than a single cycle."
NOTE_SVC = "SVC calls the system, which is no part of this datapath."
NOTE_COPROCESSOR = "Floating point, NEON and coprocessor instructions have units of their own."
NOTE_THUMB = "Thumb code: this datapath decodes ARM instructions."
NOTE_TO_THUMB = "Bit 0 of the address is 1: the processor goes on in Thumb code."

# Which instruction a view shows, and how it got there.
EXECUTED = "executed"           # the one that just ran
NEXT = "next"                   # the one at PC, not run yet
UNDONE = "undone"               # the one at PC, which Backstep undid
ENDED = "ended"                 # none: the program has ended
FAILED = "failed"               # the one a runtime error stopped
NOTHING = "nothing"             # none: nothing observed yet

STAGES = ("Fetch", "Decode", "Execute", "Memory", "Write back")
BLOCKS = ("PCMux", "PCReg", "IMem", "Add4", "Add8", "RA1Mux", "RA2Mux", "A3Mux", "WD3Mux",
          "RegFile", "Extend", "Shifter", "ALUSrcMux", "StoreMux", "ALU", "DMem", "ResultMux",
          "Control")
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
    did what it changed, if it lies outside and ran, and ended that the program has ended."""
    kind: str = NOTHING
    heading: str = ""
    trace: Trace = None
    did: tuple = ()
    ended: bool = False


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
        return "" if word >> 25 & 1 else NOTE_MULTIPLE
    return NOTE_SVC if word >> 24 & 0xF == 0xF else NOTE_COPROCESSOR


def _is_bx(word):
    return word & BX_MASK == BX_BITS


def _data_note(word):
    if _is_bx(word):
        return ""
    immediate, cmd, s = word >> 25 & 1, word >> 21 & 0xF, word >> 20 & 1
    if not immediate and word & 0x90 == 0x90:       # bits 7 and 4
        if word & 0x0FB00FF0 == 0x01000090:
            return NOTE_SWAP
        multiply = word >> 4 & 0xF == 9 and not word >> 24 & 1
        return NOTE_MULTIPLY if multiply else NOTE_SIZES
    if 0b1000 <= cmd <= 0b1011 and not s:
        return NOTE_OTHER
    if not immediate and word >> 4 & 1:
        return NOTE_SHIFT
    if cmd in (0b0101, 0b0110, 0b0111):
        return NOTE_CARRY
    if cmd == 0b1001:
        return NOTE_TEQ
    if s and word >> 12 & 0xF == PC_NUMBER:
        return NOTE_RETURN
    return ""


def _memory_note(word):
    if word >> 25 & 1 and word >> 4 & 1:
        return NOTE_OTHER
    if not word >> 24 & 1 or word >> 21 & 1:        # P = 0 or W = 1
        return NOTE_WRITE_BACK
    return ""


# The decoders ----------------------------------------------------------------------------

def _class_of(word):
    if _is_bx(word):
        return BRANCH_EXCHANGE
    op, funct5 = word >> 26 & 3, word >> 25 & 1
    if op == 0:
        return DP_IMMEDIATE if funct5 else DP_REGISTER
    if op == 1:
        if word >> 20 & 1:
            return LOAD_REGISTER if funct5 else LOAD_IMMEDIATE
        return STORE_REGISTER if funct5 else STORE_IMMEDIATE
    return BRANCH_LINK if word >> 24 & 1 else BRANCH


def shift_in_use(word):
    """True when a shift by an immediate changes its input: LSL #0 is the only one that does
    not (an amount of 0 means 32 for LSR and ASR, and RRX for ROR)."""
    return bool(word >> 5 & 0x7F)


def decode(word):
    """The control signals of word (a Control)."""
    note = outside_note(word)
    if note:
        return Control(OUTSIDE, note, {})
    kind = _class_of(word)
    signals = dict(zip(MAIN_SIGNALS, MAIN_DECODER[kind]))
    signals.update(ALUControl=ALU_ADD, FlagW="00", NoWrite="0", Shift="0", ShiftC="0", Byte="0",
                   StoreSrc="0", Link="0")
    if kind in (DP_REGISTER, DP_IMMEDIATE, BRANCH_EXCHANGE):
        control, flag_write, no_write = ALU_DECODER[word >> 21 & 0xF]
        s = word >> 20 & 1
        signals.update(ALUControl=control, NoWrite=no_write, FlagW=flag_write if s else "00")
    if kind in (DP_REGISTER, LOAD_REGISTER, STORE_REGISTER):
        signals["Shift"] = "1" if shift_in_use(word) else "0"
    if signals["FlagW"] == "10":        # logical: C comes from the shifter or the rotation
        rotated = kind == DP_IMMEDIATE and word >> 8 & 0xF
        if signals["Shift"] == "1" or rotated:
            signals["ShiftC"] = "1"
    if word >> 26 & 3 == 1:
        signals["Byte"] = str(word >> 22 & 1)
        if not word >> 23 & 1:          # U = 0: a negative offset
            signals["ALUControl"] = ALU_SUB
    if kind == STORE_REGISTER:
        signals["StoreSrc"] = "1"
    if kind == BRANCH_LINK:
        signals["Link"] = "1"
    writes_pc = word >> 12 & 0xF == PC_NUMBER and signals["RegW"] == "1"
    signals["PCS"] = "1" if writes_pc or signals["Branch"] == "1" else "0"
    return Control(kind, "", signals)


# The parts of the datapath -----------------------------------------------------------------

def alu(control, a, b):
    """(result, flags N Z C V) of the ALU: C and V come from the adder, and are 0 otherwise."""
    carry = overflow = 0
    if control in (ALU_ADD, ALU_SUB, ALU_RSB):
        if control == ALU_RSB:
            a, b = b, a
        second = b if control == ALU_ADD else ~b & MASK
        total = a + second + (control != ALU_ADD)
        result = total & MASK
        carry = total >> 32
        overflow = (~(a ^ second) & (a ^ result)) >> 31 & 1
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
    else:
        result = ~b & MASK
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


def extend(word, imm_src):
    """The Extend block's output (ExtImm): 00 imm8 rotated by twice Instr 11:8, 01 imm12,
    10 imm24 sign-extended and times 4."""
    if imm_src == "00":
        return _rotate(word & 0xFF, 2 * (word >> 8 & 0xF))
    if imm_src == "01":
        return word & 0xFFF
    imm24 = word & 0xFFFFFF
    return (imm24 - (imm24 >> 23 << 24)) * 4 & MASK


def shift_text(word):
    """The shift of a shifted register as a program writes it ("" for none)."""
    amount, kind = word >> 7 & 0x1F, word >> 5 & 3
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
    the value it got instead.
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

    def register(number):
        return plus8 if number == PC_NUMBER else registers[number]

    s = dict(control.signals)
    executes = _passes(cond, flags)
    s["CondEx"] = "1" if executes else "0"
    s["PCSrc"] = "1" if s["PCS"] == "1" and executes else "0"
    s["RegWrite"] = "1" if s["RegW"] == "1" and s["NoWrite"] == "0" and executes else "0"
    s["MemWrite"] = "1" if s["MemW"] == "1" and executes else "0"
    s["FlagWrite"] = s["FlagW"] if executes else "00"

    rn, rd, rm = word >> 16 & 0xF, word >> 12 & 0xF, word & 0xF
    ra1 = PC_NUMBER if s["RegSrc"][1] == "1" else rn
    # For a load with a register offset the table says X for RegSrc1: only Rm gives the address.
    ra2 = rd if s["RegSrc"][0] == "1" else rm if s["ALUSrc"] == "0" else None
    a4 = rd if s["StoreSrc"] == "1" else None
    a3 = None
    if s["RegW"] == "1":
        a3 = LINK_REGISTER if s["Link"] == "1" else rd
    rd1 = register(ra1)
    rd2 = None if ra2 is None else register(ra2)
    rd4 = None if a4 is None else register(a4)
    ext_imm = None if s["ImmSrc"] == "XX" else extend(word, s["ImmSrc"])

    carry_in = flags >> 1 & 1
    shifted = shift_carry = None
    if s["Shift"] == "1":
        shifted, shift_carry = shift(rd2, word >> 5 & 3, word >> 7 & 0x1F, carry_in)
    elif s["ALUSrc"] == "0":
        shifted, shift_carry = rd2, carry_in
    elif s["ImmSrc"] == "00":
        shift_carry = ext_imm >> 31     # a rotated immediate's carry
    src_b = ext_imm if s["ALUSrc"] == "1" else shifted
    alu_result, alu_flags = alu(s["ALUControl"], rd1, src_b)
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
    read_data = None
    if s["MemtoReg"] == "1" and executes:
        read_data = loaded if loaded is not None else _read(read_memory, alu_result, s["Byte"])
    result = {"0": alu_result, "1": read_data, "X": None}[s["MemtoReg"]]
    wd3 = None
    if s["RegW"] == "1":
        wd3 = plus4 if s["Link"] == "1" else result
    next_pc = plus4
    to_thumb = False
    if s["PCSrc"] == "1" and result is None:
        next_pc = None
    elif s["PCSrc"] == "1":
        next_pc = result & ~1           # bit 0 chooses Thumb code; bit 1 stays in the address
        to_thumb = bool(result & 1)

    values = {"PC": pc, "PC'": next_pc, "Instr": word, "PCPlus4": plus4, "PCPlus8": plus8,
              "RA1": ra1, "RA2": ra2, "A3": a3, "A4": a4, "RD1": rd1, "RD2": rd2, "RD4": rd4,
              "ExtImm": ext_imm, "Shifted": shifted, "SrcA": rd1, "SrcB": src_b,
              "ALUResult": alu_result, "ALUFlags": alu_flags, "WriteData": write_data,
              "ReadData": read_data, "Result": result, "WD3": wd3}
    return Trace(pc, word, text, control.kind, "", condition_text(cond, flags), s, values, flags,
                 new_flags, _stages(s, values), to_thumb)


def _read(read_memory, address, byte):
    data = read_memory(address, 1 if byte == "1" else 4)
    return None if data is None else int.from_bytes(data, "little")


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

    wires = {"Cond", "Op", "Funct", "Rd", "RegSrc"}
    blocks = {"Control"}
    if uses_a:
        wires |= {"RA1", "RD1"}
        wires.add("Const15" if s["RegSrc"][1] == "1" else "Rn")
        blocks |= {"RA1Mux", "RegFile"}
    if uses_b:
        wires |= {"RA2", "RD2"}
        wires |= {"RdField", "RdToRA2"} if s["RegSrc"][0] == "1" else {"Rm"}
        blocks |= {"RA2Mux", "RegFile"}
    if a4 is not None:
        wires |= {"A4", "RD4", "RdField"}
        blocks.add("RegFile")
    if s["ImmSrc"] != "XX":
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
    execute = Stage(STAGES[2], frozenset(wires), frozenset(blocks))

    wires, blocks = set(), set()
    if executes and (s["MemW"] == "1" or s["MemtoReg"] == "1"):
        wires |= {"ALUResult", "Address"}
        blocks.add("DMem")
        if s["Byte"] == "1":
            wires.add("Byte")
        if s["MemW"] == "1":
            wires |= {"WriteData", "MemWrite"}
            blocks.add("StoreMux")
            if s["StoreSrc"] == "1":
                wires |= {"RD4", "StoreSrc"}
            else:
                wires.add("RD2Store")
        else:
            wires.add("ReadData")
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
        else:
            wires |= {"RdField", "RdToA3", "ResultReg"}
    if from_result:
        wires |= {"Result", "MemtoReg"}
        blocks.add("ResultMux")
        wires.add("ReadData" if s["MemtoReg"] == "1" else "ALUBypass")
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
    if control.signals.get("MemtoReg") == "1":
        rd = word >> 12 & 0xF
        loaded = machine.pc | machine.cpsr >> 5 & 1 if rd == PC_NUMBER else machine.reg(rd)
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
    """What the instruction of change did, one line for each register and memory place
    changed, machine having just run it."""
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
    for address, bytes_before in change.writes:
        bytes_after = peek(address, len(bytes_before))
        if bytes_after is None or bytes_after == bytes_before:
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
