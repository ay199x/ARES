# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""ARM X-Ray's model: the control signals of the tables, and wires that agree with what ran."""

import random
import struct
from pathlib import Path

import pytest
from conftest import PROGRAMS, ROOT

from ares.assembler import assemble
from ares.gui.tools.xray import XRayModel
from ares.machine import SNAPSHOT_PC, SNAPSHOT_REGISTERS, Machine, StopReason
from ares.program import Program
from ares.runner import Runner, State
from ares.xray import (ALU_MLA, ALU_MOVT, BLOCKS, BRANCH_EXCHANGE, BRANCH_LINK_EXCHANGE,
                       LOAD_HALF_IMMEDIATE, MOVE_16, NOTE_OTHER, NOTE_SWAP, NOTE_THUMB, EXECUTED,
                       FAILED, LOAD_MULTIPLE, MULTIPLY, NEXT, STORE_HALF_REGISTER,
                       NO_OPERATION, NOTE_MULTIPLY, NOTE_UNPREDICTABLE, HALVES as HALF_KINDS,
                       OUTSIDE, STAGES, STORE_MULTIPLE, SYSTEM_CALL, NOTHING, ENDED, WAITING,
                       BRANCH, alu, changes, condition_text, decode, executed, extend,
                       instruction_line, named, outside_note, shift, shift_by_register, trace,
                       upcoming)

END = "        B       .\n"
HEADER = "        .global _start\n_start:\n"


@pytest.fixture(scope="module")
def word_of(tmp_path_factory):
    """word_of(source): the word the assembler makes of one line, as a label's neighbour."""
    folder = tmp_path_factory.mktemp("words")
    known = {}

    def find(source):
        if source not in known:
            text = f"here:   {source}\nthere:  NOP\n"
            result = assemble(text, folder)
            assert result.ok, [m.format() for m in result.messages]
            machine = Machine(Program(result.elf_path))
            known[source] = struct.unpack("<I", machine.read_memory(0, 4))[0]
            machine.close()
        return known[source]
    return find


def signals(word):
    return decode(word).signals


def row(word, names):
    return " ".join(signals(word)[name] for name in names.split())


# The Main Decoder --------------------------------------------------------------------

MAIN_NAMES = "Branch MemtoReg MemW ALUSrc ImmSrc RegW RegSrc ALUOp"
MAIN = [
    ("ADD R0, R1, R2", "0 0 0 0 XXX 1 00 1"),
    ("ADD R0, R1, R2, LSL #3", "0 0 0 0 XXX 1 00 1"),
    ("ADD R0, R1, #1", "0 0 0 1 000 1 X0 1"),
    ("STR R0, [R1, #4]", "0 X 1 1 001 0 10 0"),
    ("STRB R0, [R1, #4]", "0 X 1 1 001 0 10 0"),
    ("LDR R0, [R1, #4]", "0 1 0 1 001 1 X0 0"),
    ("LDRB R0, [R1, #4]", "0 1 0 1 001 1 X0 0"),
    ("B there", "1 0 0 1 010 0 X1 0"),
    ("BNE there", "1 0 0 1 010 0 X1 0"),
    # The additions: a register offset takes the shifter's route, BL writes LR.
    ("LDR R0, [R1, R2]", "0 1 0 0 XXX 1 00 0"),
    ("LDR R0, [R1, R2, LSL #2]", "0 1 0 0 XXX 1 00 0"),
    ("STR R0, [R1, R2]", "0 X 1 0 XXX 0 00 0"),
    ("STRB R0, [R1, R2, LSL #1]", "0 X 1 0 XXX 0 00 0"),
    ("BL there", "1 0 0 1 010 1 X1 0"),
    # BX reads Rm on the second port, for the ALU to pass on: no register written.
    ("BX LR", "1 0 0 0 XXX 0 0X 1"),
    ("BXNE R3", "1 0 0 0 XXX 0 0X 1"),
    # MUL and MLA: registers as for data processing, and Mul 1 for the RA1 and A3 multiplexers.
    ("MUL R0, R1, R2", "0 0 0 0 XXX 1 00 1"),
    ("MLAS R0, R1, R2, R3", "0 0 0 0 XXX 1 00 1"),
    # A shift by a register is data processing; BLX is BX writing LR; NOP writes nothing.
    ("ADD R2, R1, R0, LSL R3", "0 0 0 0 XXX 1 00 1"),
    ("BLX R3", "1 0 0 0 XXX 1 0X 1"),
    ("NOP", "0 X 0 X XXX 0 XX X"),
    # MOVW and MOVT: imm16 (ImmSrc 100), no register read through RA1 or RA2; the ALU Decoder
    # tells them apart. The halfword and signed transfers: as LDR and STR, with imm8 (101).
    ("MOVW R0, #0x1234", "0 0 0 1 100 1 XX 1"),
    ("MOVT R0, #0x1234", "0 0 0 1 100 1 XX 1"),
    ("LDRH R0, [R1, #4]", "0 1 0 1 101 1 X0 0"),
    ("LDRSB R0, [R1], #-4", "0 1 0 1 101 1 X0 0"),
    ("LDRSH R0, [R1, R2]!", "0 1 0 0 XXX 1 00 0"),
    ("STRH R0, [R1, #2]!", "0 X 1 1 101 0 10 0"),
    ("STRH R0, [R1], -R2", "0 X 1 0 XXX 0 00 0"),
]


@pytest.mark.parametrize("source, expected", MAIN)
def test_the_main_decoder_gives_the_rows_of_the_tables(word_of, source, expected):
    assert row(word_of(source), MAIN_NAMES) == expected


# The ALU Decoder ---------------------------------------------------------------------

ALU_ROWS = [    # instruction with S (and the one without), ALUControl, FlagW with S=1, NoWrite
    ("ADDS R0, R1, R2", "ADD R0, R1, R2", "0000", "11", "0"),
    ("SUBS R0, R1, R2", "SUB R0, R1, R2", "0001", "11", "0"),
    ("ANDS R0, R1, R2", "AND R0, R1, R2", "0010", "10", "0"),
    ("ORRS R0, R1, R2", "ORR R0, R1, R2", "0011", "10", "0"),
    ("EORS R0, R1, R2", "EOR R0, R1, R2", "0100", "10", "0"),
    ("BICS R0, R1, R2", "BIC R0, R1, R2", "0101", "10", "0"),
    ("RSBS R0, R1, R2", "RSB R0, R1, R2", "0110", "11", "0"),
    ("MOVS R0, R2", "MOV R0, R2", "0111", "10", "0"),
    ("MVNS R0, R2", "MVN R0, R2", "1000", "10", "0"),
    ("CMP R1, R2", None, "0001", "11", "1"),
    ("CMN R1, R2", None, "0000", "11", "1"),
    ("TST R1, R2", None, "0010", "10", "1"),
    # The adder with the C flag as its carry in, and TEQ, an EOR that only sets the flags.
    ("ADCS R0, R1, R2", "ADC R0, R1, R2", "1011", "11", "0"),
    ("SBCS R0, R1, R2", "SBC R0, R1, R2", "1100", "11", "0"),
    ("RSCS R0, R1, R2", "RSC R0, R1, R2", "1101", "11", "0"),
    ("TEQ R1, R2", None, "0100", "10", "1"),
    ("TEQ R1, #1", None, "0100", "10", "1"),
    # cmd 1000 and 1010 without S: MOVW passes SrcB on, MOVT joins it to the low half of RD4.
    (None, "MOVW R0, #1", "0111", "00", "0"),
    (None, "MOVT R0, #1", "1110", "00", "0"),
]


@pytest.mark.parametrize("with_s, without_s, control, flags, no_write", ALU_ROWS)
def test_the_alu_decoder_gives_the_additions_table(word_of, with_s, without_s, control, flags,
                                                   no_write):
    if with_s:
        assert row(word_of(with_s), "ALUControl FlagW NoWrite") == f"{control} {flags} {no_write}"
    if without_s:
        assert row(word_of(without_s), "ALUControl FlagW NoWrite") == f"{control} 00 {no_write}"


@pytest.mark.parametrize("source", ["LDR R0, [R1, #4]", "STR R0, [R1, #4]", "LDR R0, [R1, R2]",
                                    "STRB R0, [R1, R2]", "B there", "BL there"])
def test_with_alu_op_0_the_alu_adds_and_writes_no_flags(word_of, source):
    assert row(word_of(source), "ALUOp ALUControl FlagW NoWrite") == "0 0000 00 0"


@pytest.mark.parametrize("source", ["LDR R0, [R1, #-4]", "STR R0, [R1, #-4]", "LDR R0, [R1, -R2]",
                                    "STRB R0, [R1, -R2, LSL #1]", "LDRB R0, [R1, #-1]"])
def test_a_negative_offset_subtracts(word_of, source):
    assert row(word_of(source), "ALUOp ALUControl FlagW") == "0 0001 00"


def test_the_alu_decoder_passes_rm_on_for_bx_and_writes_no_flags(word_of):
    assert row(word_of("BX LR"), "ALUOp ALUControl FlagW NoWrite") == "1 0111 00 0"
    assert row(word_of("BLX R3"), "ALUOp ALUControl FlagW NoWrite Link") == "1 0111 00 0 1"


def test_nop_writes_nothing_and_needs_no_alu(word_of):
    assert row(word_of("NOP"), "RegW MemW FlagW ALUControl PCS Link Syscall") == \
        "0 0 00 XXXX 0 0 0"
    assert decode(word_of("NOPEQ")).kind == NO_OPERATION


@pytest.mark.parametrize("source, expected", [
    ("ADD R2, R1, R0, LSL R3", "1"), ("MOVS R0, R1, ROR R2", "1"), ("TEQ R1, R2, LSR R3", "1"),
    ("CMP R0, R1, ASR R2", "1"), ("RSC R0, R1, R2, LSL R0", "1"), ("ADD R2, R1, R0, LSL #3", "0"),
    ("ADD R2, R1, R0", "0"), ("STR R0, [R1, R2]", "0"), ("MLA R0, R1, R2, R3", "0"),
    ("BX LR", "0"), ("MOV R0, #1", "0")])
def test_shift_reg_is_1_only_for_a_shift_by_a_register(word_of, source, expected):
    """It makes the A4 multiplexer take Rs (Instr 11:8); the shifter takes its amount from RD4."""
    assert signals(word_of(source))["ShiftReg"] == expected


@pytest.mark.parametrize("source, expected", [
    ("MUL R0, R1, R2", "1 1001 00 0"), ("MULS R0, R1, R2", "1 1001 10 0"),
    ("MLA R0, R1, R2, R3", "1 1010 00 0"), ("MLAS R0, R1, R2, R3", "1 1010 10 0"),
    ("MULNE R0, R0, R1", "1 1001 00 0")])
def test_with_mul_1_the_alu_decoder_gives_the_multipliers_codes(word_of, source, expected):
    """MUL and MLA have cmd 0000 and 0001 as AND and EOR: Mul tells them apart. With S they
    write N and Z only; the shifter passes RD2 on (Instr 11:7 is no shift)."""
    assert row(word_of(source), "Mul ALUControl FlagW NoWrite") == expected
    assert row(word_of(source), "Shift ShiftC RegSrc Link") == "0 0 00 0"


@pytest.mark.parametrize("source", ["ADD R0, R1, R2", "AND R0, R1, R2", "LDR R0, [R1]", "B there",
                                    "BX LR", "SVC #1", "PUSH {R0, LR}", "MOV R0, #1"])
def test_mul_is_0_for_every_other_instruction(word_of, source):
    assert signals(word_of(source))["Mul"] == "0"


# The additions -----------------------------------------------------------------------

@pytest.mark.parametrize("source, expected", [
    # Shift is 1 when the shifter changes its input's route.
    ("ADD R0, R1, R2", "0"),
    ("ADD R0, R1, R2, LSL #1", "1"),
    ("ADD R0, R1, R2, LSR #1", "1"),
    ("ADD R0, R1, R2, ASR #31", "1"),
    ("ADD R0, R1, R2, ROR #4", "1"),
    ("ADD R0, R1, R2, RRX", "1"),
    ("ADD R0, R1, R2, LSR #32", "1"),   # an amount of 0 in the word means 32 here
    ("ADD R0, R1, R2, ASR #32", "1"),
    ("LDR R0, [R1, R2]", "0"),
    ("LDR R0, [R1, R2, LSL #2]", "1"),
    ("STR R0, [R1, R2, ASR #1]", "1"),
    ("ADD R0, R1, #1", "0"),
    ("LDR R0, [R1, #4]", "0"),
    ("B there", "0"),
    ("BX LR", "0"),                     # Instr 11:5 of BX is no shift
    ("ADD R0, R1, R2, LSL R3", "1"),    # by a register: the trace makes it 0 for an amount of 0
    ("ADD R0, R1, R2, LSL R0", "1"),
])
def test_shift_says_the_shifter_is_in_use(word_of, source, expected):
    assert signals(word_of(source))["Shift"] == expected


@pytest.mark.parametrize("source, expected", [
    ("MOVS R0, R1, LSL #1", "1"),
    ("ANDS R0, R1, R2, LSR #1", "1"),
    ("ORRS R0, R1, R2, RRX", "1"),
    ("TST R1, R2, ROR #1", "1"),
    ("MOVS R0, #0x80000000", "1"),      # a rotated immediate
    ("MOVS R0, R1", "0"),               # no shift: C stays
    ("MOVS R0, #1", "0"),               # no rotation: C stays
    ("ANDS R0, R1, #255", "0"),
    ("MOV R0, R1, LSL #1", "0"),        # no S
    ("MOV R0, #0x80000000", "0"),
    ("ADDS R0, R1, R2, LSL #1", "0"),   # not logical: the adder's carry
    ("CMP R1, R2, LSL #1", "0"),
])
def test_shift_c_writes_c_from_the_shifter(word_of, source, expected):
    assert signals(word_of(source))["ShiftC"] == expected


@pytest.mark.parametrize("source, size, signed", [
    ("LDR R0, [R1]", "00", "0"), ("STR R0, [R1]", "00", "0"), ("LDRB R0, [R1]", "10", "0"),
    ("STRB R0, [R1]", "10", "0"), ("LDRB R0, [R1, R2]", "10", "0"),
    ("STRB R0, [R1, R2]", "10", "0"),
    ("ADD R0, R1, R2", "00", "0"), ("LDRH R0, [R1]", "01", "0"), ("STRH R0, [R1, R2]", "01", "0"),
    ("LDRSB R0, [R1, #1]", "10", "1"), ("LDRSH R0, [R1], R2", "01", "1"),
    ("POP {R0, R1}", "00", "0")])
def test_size_and_signed_mark_the_size_of_an_access(word_of, source, size, signed):
    """Size: 00 a word, 01 a halfword, 10 a byte (its high bit is the former Byte); Signed: the
    load extender copies the sign bit upwards."""
    assert row(word_of(source), "Size Signed") == f"{size} {signed}"


@pytest.mark.parametrize("source, store_src", [
    ("STR R0, [R1, R2]", "1"), ("STRB R0, [R1, R2, LSL #1]", "1"), ("STR R0, [R1, -R2]", "1"),
    ("STR R0, [R1, #4]", "0"), ("LDR R0, [R1, R2]", "0"), ("ADD R0, R1, R2", "0"),
    ("STRH R0, [R1, R2]", "1"), ("STRH R0, [R1], #2", "0"), ("LDRH R0, [R1, R2]", "0")])
def test_store_src_takes_the_third_read_port_for_a_register_offset(word_of, source, store_src):
    assert signals(word_of(source))["StoreSrc"] == store_src


@pytest.mark.parametrize("source, link", [("BL there", "1"), ("BLNE there", "1"), ("B there", "0"),
                                          ("ADD R0, R1, R2", "0"), ("BLX R3", "1"),
                                          ("BX R3", "0")])
def test_link_marks_bl(word_of, source, link):
    assert signals(word_of(source))["Link"] == link


@pytest.mark.parametrize("source, pcs", [
    ("ADD PC, R1, R2", "1"), ("MOV PC, LR", "1"), ("LDR PC, [R1]", "1"), ("B there", "1"),
    ("BL there", "1"), ("BX LR", "1"), ("BXNE R3", "1"), ("MOV R0, R1", "0"), ("LDR R0, [R1]", "0"),
    ("STR PC, [R1]", "0"),              # RegW is 0: Rd = 15 changes nothing here
    ("BLX R3", "1"), ("NOP", "0"), ("TEQ R1, R2", "0"),
])
def test_pcs_is_rd_15_with_regw_or_branch(word_of, source, pcs):
    assert signals(word_of(source))["PCS"] == pcs


# What lies outside -------------------------------------------------------------------

OUTSIDE_SOURCES = [
    "ADDS PC, R1, R2", "MOVS PC, LR", "SUBS PC, LR, #4",
    # The PC as any register of a shift by a register, or BLX PC: UNPREDICTABLE in ARMv7.
    ".word 0xE081F312", ".word 0xE08F0312", ".word 0xE081031F", ".word 0xE0810F12",
    ".word 0xE1B00F11", ".word 0xE12FFF3F",
    "MLS R0, R1, R2, R3", "UMULL R0, R1, R2, R3",
    "SMULL R0, R1, R2, R3", "UMLAL R0, R1, R2, R3", "SMLAL R0, R1, R2, R3",
    "LDM R0, {R1, R2}^", "STMIA R0, {R1, R2}^", ".word 0xE8B00003", ".word 0xE92D2001",
    ".word 0xE8100000", ".word 0xE89F0003", ".word 0xE9308002", ".word 0xE8910006",
    ".word 0xE4911004", ".word 0xE5BF0004", ".word 0xE6B1000F", ".word 0xE7A22003",
    ".word 0xE000029F", ".word 0xE00F0291", ".word 0xE0020F91", ".word 0xE020F291",
    ".word 0xE0005291", "UMAAL R0, R1, R2, R3",
    "LDRT R0, [R1]", "STRT R0, [R1]", "LDRBT R0, [R1]", "STRBT R0, [R1]",
    "LDRD R0, R1, [R2]", "STRD R0, R1, [R2]", "LDREX R0, [R1]", "STREX R0, R1, [R2]",
    "LDREXB R0, [R1]", "LDRHT R0, [R1]", "STRHT R0, [R1], #2", "LDRSBT R0, [R1]",
    "LDRSHT R0, [R1], R2",
    # MOVW or MOVT of the PC; a halfword transfer of the PC, with the PC as Rm, with bits 11:8 of
    # a register offset not 0000, or writing back to the PC or to the register it moves:
    # UNPREDICTABLE in ARMv7.
    ".word 0xE300F001", ".word 0xE340F001", ".word 0xE1D1F0B0", ".word 0xE19100BF",
    ".word 0xE1C1F0B2", ".word 0xE19101B2", ".word 0xE1F110B4", ".word 0xE0D110D2",
    ".word 0xE09F00B2", ".word 0xE1E110B2",
    "BXJ R0", "MRS R0, CPSR",
    "MSR CPSR_f, R0", "MSR CPSR_f, #0xF0000000", "CLZ R0, R1", "YIELD", "WFE", "WFI",
    "SEV", "BKPT #0", "UXTB R0, R1", "SXTH R0, R1",
    "REV R0, R1", "UBFX R0, R1, #2, #3", "BFI R0, R1, #2, #3", "QADD R0, R1, R2",
    ".fpu vfpv3\nVADD.F32 S0, S1, S2", ".fpu vfpv3\nVLDR S0, [R0]",
    ".fpu neon\nVADD.I32 D0, D1, D2", "MRC P15, 0, R0, C1, C0, 0", "BLX there", "PLD [R0]",
    "CPSID i", "DMB",
]


@pytest.mark.parametrize("source", OUTSIDE_SOURCES)
def test_these_instructions_lie_outside_the_datapath(word_of, source):
    word = word_of(source)
    control = decode(word)
    assert control.kind == OUTSIDE and control.note and control.note == outside_note(word)
    assert control.signals == {}


@pytest.mark.parametrize("word", [0xFA000000, 0xF1000000, 0xF57FF04F, 0xFD800000, 0xFE000000])
def test_condition_1111_is_outside(word):
    assert decode(word).kind == OUTSIDE


@pytest.mark.parametrize("source", [
    "ADD R0, R1, R2", "ADD R0, R1, R2, LSL #31", "ADD PC, R1, R2", "SUB R0, PC, #4", "ADR R0, here",
    "MOV R0, R0", "MOV PC, LR", "MOVEQ R0, #1", "MVN R0, #0", "BIC R0, R1, #255", "RSB R0, R1, #0",
    "EOR R0, R1, R2, RRX", "TST R0, #1", "CMP R0, #1", "CMN R0, R1", "LDR R0, [R1]",
    "LDR R0, [PC, #-8]", "LDR PC, [R1]", "LDR R0, [R1, R2, LSL #2]", "STR PC, [R1]",
    "LDRB R0, [R1, -R2]", "STRB R0, [R1]", "BL there", "BEQ there", "BLEQ there", "BX LR", "BX R0",
    "BX SP", "BX PC", "BXEQ LR", "LDM R0, {R1, R2}", "STM R0, {R1, R2}", "LDMIA R0!, {R1}",
    "STMDB R0!, {R1}", "PUSH {R0, LR}", "POP {R0, PC}", "LDMIB R0, {R1-R3}", "STMDA R0!, {R1, PC}",
    "LDMDB R0, {R4, PC}", "LDMIA R1, {R0, R1}", "STMIA R1, {R1, R2}", "POPNE {R4-R11, PC}",
    "LDR R0, [R1, #4]!", "STR R0, [R1, #4]!", "LDR R0, [R1], #4", "STR R0, [R1], #4",
    "LDR R0, [R1, R2]!", "STR R0, [R1], R2", "LDRB R0, [R1], #1", "STRB R0, [R1, #1]!",
    "LDR PC, [SP], #4", "PUSH {R0}", "POP {R0}", "STR R0, [R1, -R2, LSL #2]!",
    "MUL R0, R1, R2", "MULS R0, R1, R2", "MLA R0, R1, R2, R3", "MLANES R12, R11, R10, R9",
    "MUL R0, R0, R1", "MULEQ R14, R13, R1",
    "ADD R2, R1, R0, LSL R3", "MOVS R0, R1, ROR R2", "MVN R0, R1, ASR R2", "TEQ R1, R2, LSR R3",
    "CMP R0, R1, ASR R2", "ANDNES R12, R11, R10, LSL R9", "ADC R0, R1, R2", "ADCS R0, R1, #1",
    "SBC R0, R1, R2", "SBCS R0, R1, #1", "RSC R0, R1, R2, ROR R3", "RSCS R0, R1, #1",
    "TEQ R1, R2", "TEQ R1, #1", "TEQ R1, R2, ROR #3", "BLX R3", "BLXNE LR", "BLX R0", "NOP",
    "NOPEQ", "MOVW R0, #0", "MOVW R14, #0xFFFF", "MOVTNE R3, #0x8000", "MOVW SP, #1",
    "LDRH R0, [R1]", "LDRH R0, [R1, #-255]", "LDRH R0, [R1, #4]!", "LDRH R0, [R1], #4",
    "LDRH R0, [R1, R2]", "LDRH R0, [R1, -R2]!", "LDRH R0, [R1], -R2", "STRH R0, [R1]",
    "STRH R0, [R1, #2]!", "STRH R0, [R1], R2", "STRH R0, [R1, -R2]", "LDRSB R0, [R1, #1]",
    "LDRSB R0, [R1], #-1", "LDRSB R0, [R1, R2]!", "LDRSH R0, [R1]", "LDRSH R0, [R1], R2",
    "LDREQSH R0, [R1, #-2]!", "LDRH R0, [PC, #4]", "STRH R2, [R1]",
    "LDRH R0, [R1, R0]"])
def test_these_instructions_lie_inside_the_datapath(word_of, source):
    assert outside_note(word_of(source)) == ""
    assert decode(word_of(source)).kind != OUTSIDE


@pytest.mark.parametrize("cond", range(15))
@pytest.mark.parametrize("rm", range(16))
def test_bx_has_a_class_of_its_own_with_any_condition_and_register(cond, rm):
    assert decode(cond << 28 | 0x012FFF10 | rm).kind == BRANCH_EXCHANGE


def test_the_note_for_what_has_no_row_no_longer_names_bx_blx_or_nop():
    assert "BX" not in NOTE_OTHER and "other than NOP" in NOTE_OTHER


@pytest.mark.parametrize("cond", range(15))
@pytest.mark.parametrize("rm", range(15))
def test_blx_has_a_class_of_its_own_with_any_condition_and_register(cond, rm):
    assert decode(cond << 28 | 0x012FFF30 | rm).kind == BRANCH_LINK_EXCHANGE


# The parts of the datapath -----------------------------------------------------------

@pytest.mark.parametrize("control, a, b, value, flags", [
    # flags: N Z C V
    ("0000", 1, 2, 3, 0b0000),
    ("0000", 0xFFFFFFFF, 1, 0, 0b0110),
    ("0000", 0x7FFFFFFF, 1, 0x80000000, 0b1001),
    ("0000", 0x80000000, 0x80000000, 0, 0b0111),
    ("0001", 5, 3, 2, 0b0010),
    ("0001", 3, 5, 0xFFFFFFFE, 0b1000),
    ("0001", 3, 3, 0, 0b0110),
    ("0001", 0x80000000, 1, 0x7FFFFFFF, 0b0011),
    ("0010", 0xF0F0, 0xFF00, 0xF000, 0b0000),
    ("0011", 0xF0F0, 0x0F00, 0xFFF0, 0b0000),
    ("0100", 0xF0F0, 0xFF00, 0x0FF0, 0b0000),
    ("0101", 0xF0F0, 0xFF00, 0x00F0, 0b0000),
    ("0110", 3, 5, 2, 0b0010),
    ("0110", 5, 3, 0xFFFFFFFE, 0b1000),
    ("0111", 9, 7, 7, 0b0000),
    ("0111", 9, 0, 0, 0b0100),
    ("1000", 9, 0, 0xFFFFFFFF, 0b1000),
    ("1001", 7, 3, 21, 0b0000),                  # the multiplier: the low 32 bits of SrcA x SrcB
    ("1001", 0x10000, 0x10000, 0, 0b0100),
    ("1001", 0xFFFFFFFF, 2, 0xFFFFFFFE, 0b1000),
])
def test_the_alu_operations(control, a, b, value, flags):
    assert alu(control, a, b) == (value, flags)


@pytest.mark.parametrize("control, a, b, carry, value, flags", [
    # ADC: a + b + C; SBC: a - b - NOT C, as a + NOT b + C; RSC: b - a - NOT C.
    ("1011", 1, 2, 0, 3, 0b0000), ("1011", 1, 2, 1, 4, 0b0000),
    ("1011", 0xFFFFFFFF, 0, 1, 0, 0b0110), ("1011", 0x7FFFFFFF, 0, 1, 0x80000000, 0b1001),
    ("1100", 5, 3, 1, 2, 0b0010), ("1100", 5, 3, 0, 1, 0b0010),
    ("1100", 3, 3, 0, 0xFFFFFFFF, 0b1000),
    ("1100", 0x80000000, 0, 0, 0x7FFFFFFF, 0b0011),
    ("1101", 3, 5, 1, 2, 0b0010), ("1101", 3, 5, 0, 1, 0b0010),
    ("1101", 5, 3, 1, 0xFFFFFFFE, 0b1000),
])
def test_adc_sbc_and_rsc_add_the_carry(control, a, b, carry, value, flags):
    assert alu(control, a, b, carry_in=carry) == (value, flags)


def test_the_multiplier_adds_rd4_for_mla_only():
    assert alu("1010", 7, 3, 0x15) == (0x2A, 0b0000)
    assert alu("1010", 0xFFFFFFFF, 1, 1) == (0, 0b0100)
    assert alu("1001", 7, 3, 0x15) == (21, 0b0000)


@pytest.mark.parametrize("word, note", [
    (0xE000029F, NOTE_UNPREDICTABLE), (0xE00F0291, NOTE_UNPREDICTABLE),
    (0xE0020F91, NOTE_UNPREDICTABLE), (0xE020F291, NOTE_UNPREDICTABLE),
    (0xE0005291, NOTE_UNPREDICTABLE),           # bits 15:12 of MUL must be 0
    (0xE0603291, NOTE_MULTIPLY), (0xE0810392, NOTE_MULTIPLY), (0xE0410392, NOTE_MULTIPLY)])
def test_multiplies_that_stay_outside_and_why(word, note):
    assert outside_note(word) == note


@pytest.mark.parametrize("kind, amount, value, carry, expected", [
    (0, 0, 0x80000001, 1, (0x80000001, 1)),     # LSL #0: nothing changes
    (0, 0, 0x80000001, 0, (0x80000001, 0)),
    (0, 1, 0x80000001, 0, (0x00000002, 1)),
    (0, 31, 3, 0, (0x80000000, 1)),
    (1, 1, 0x80000001, 0, (0x40000000, 1)),
    (1, 0, 0x80000001, 0, (0, 1)),              # LSR #32
    (1, 0, 0x7FFFFFFF, 1, (0, 0)),
    (2, 1, 0x80000002, 1, (0xC0000001, 0)),
    (2, 0, 0x80000000, 0, (0xFFFFFFFF, 1)),     # ASR #32
    (2, 0, 0x7FFFFFFF, 1, (0, 0)),
    (3, 4, 0x0000000F, 0, (0xF0000000, 1)),
    (3, 4, 0x000000F7, 1, (0x7000000F, 0)),
    (3, 0, 0x00000003, 1, (0x80000001, 1)),     # RRX
    (3, 0, 0x00000002, 1, (0x80000001, 0)),
    (3, 0, 0x00000002, 0, (0x00000001, 0)),
])
def test_the_shifter(kind, amount, value, carry, expected):
    assert shift(value, kind, amount, carry) == expected


@pytest.mark.parametrize("kind, amount, value, carry, expected", [
    (0, 0, 0x80000001, 1, (0x80000001, 1)),     # an amount of 0 changes nothing, C stays
    (1, 0, 0x80000001, 0, (0x80000001, 0)),
    (2, 0, 0x80000001, 1, (0x80000001, 1)),
    (3, 0, 0x80000001, 0, (0x80000001, 0)),
    (0, 1, 0x80000001, 0, (2, 1)), (0, 31, 3, 0, (0x80000000, 1)),
    (0, 32, 3, 0, (0, 1)), (0, 33, 3, 1, (0, 0)), (0, 255, 3, 1, (0, 0)),
    (1, 31, 0x80000000, 0, (1, 0)), (1, 32, 0x80000000, 0, (0, 1)), (1, 33, 0x80000000, 1, (0, 0)),
    (2, 31, 0x80000000, 0, (0xFFFFFFFF, 0)), (2, 32, 0x80000000, 0, (0xFFFFFFFF, 1)),
    (2, 200, 0x7FFFFFFF, 1, (0, 0)),
    (3, 4, 0x0000000F, 0, (0xF0000000, 1)), (3, 32, 0x80000001, 0, (0x80000001, 1)),
    (3, 36, 0x0000000F, 0, (0xF0000000, 1)), (3, 64, 0x7FFFFFFF, 1, (0x7FFFFFFF, 0)),
])
def test_the_shifter_by_a_register(kind, amount, value, carry, expected):
    """The amount is RD4[7:0]: 32 or more shifts every bit out (ASR leaves the sign), and ROR
    turns by the amount modulo 32."""
    assert shift_by_register(value, kind, amount, carry) == expected


@pytest.mark.parametrize("imm_src, word, expected", [
    ("000", 0xE3A000FF, 0xFF),
    ("000", 0xE3A004FF, 0xFF000000),    # rotated by 8
    ("000", 0xE3A00102, 0x80000000),    # 2 rotated by 2
    ("000", 0xE3A00F01, 4),             # 1 rotated by 30
    ("001", 0xE5910FFF, 0xFFF),
    ("001", 0xE5910004, 4),
    ("010", 0xEA000001, 4),
    ("010", 0xEAFFFFFE, 0xFFFFFFF8),
    ("010", 0xEA7FFFFF, 0x01FFFFFC),
    ("010", 0xEA800000, 0xFE000000),
    ("100", 0xE3010234, 0x1234),        # MOVW R0, #0x1234: imm4 and imm12
    ("100", 0xE34FAFFF, 0xFFFF),        # no sign: zeros above
    ("101", 0xE1D10FBF, 0xFF),          # LDRH R0, [R1, #255]: imm4H and imm4L
    ("101", 0xE1D102B4, 0x24),
])
def test_extend_gives_the_immediates(imm_src, word, expected):
    assert extend(word, imm_src) == expected


def test_the_pass_counters_offset_takes_no_bits_of_the_word():
    with pytest.raises(ValueError):
        extend(0xE8BD0003, "011")


@pytest.mark.parametrize("cond, flags, expected", [
    (0, 0b0100, "EQ: Z = 1, executes"),
    (0, 0b0000, "EQ: Z = 0, does not execute"),
    (1, 0b0000, "NE: Z = 0, executes"),
    (1, 0b0100, "NE: Z = 1, does not execute"),
    (2, 0b0010, "CS: C = 1, executes"),
    (3, 0b0010, "CC: C = 1, does not execute"),
    (4, 0b1000, "MI: N = 1, executes"),
    (5, 0b1000, "PL: N = 1, does not execute"),
    (6, 0b0001, "VS: V = 1, executes"),
    (7, 0b0001, "VC: V = 1, does not execute"),
    (8, 0b0010, "HI: C = 1, Z = 0, executes"),
    (8, 0b0110, "HI: C = 1, Z = 1, does not execute"),
    (9, 0b0110, "LS: C = 1, Z = 1, executes"),
    (10, 0b1001, "GE: N = 1, V = 1, executes"),
    (10, 0b1000, "GE: N = 1, V = 0, does not execute"),
    (11, 0b1000, "LT: N = 1, V = 0, executes"),
    (12, 0b0000, "GT: Z = 0, N = 0, V = 0, executes"),
    (12, 0b0100, "GT: Z = 1, N = 0, V = 0, does not execute"),
    (13, 0b0100, "LE: Z = 1, N = 0, V = 0, executes"),
    (14, 0b0000, "AL: always executes"),
])
def test_the_condition_check_says_what_it_read(cond, flags, expected):
    assert condition_text(cond, flags) == expected


# Traces by hand ----------------------------------------------------------------------

def no_memory(address, size):
    raise AssertionError("this instruction reads no memory")


REGISTERS = [0x100 * n for n in range(16)]


def test_a_register_add_on_every_wire(word_of):
    t = trace(0x1000, word_of("ADD R3, R1, R2"), REGISTERS, 0xE00001D3, no_memory)
    values = t.values
    assert t.pc == 0x1000 and t.text == "ADD R3, R1, R2"
    assert values["PC"] == 0x1000 and values["PCPlus4"] == 0x1004 and values["PCPlus8"] == 0x1008
    assert values["Instr"] == word_of("ADD R3, R1, R2")
    assert (values["RA1"], values["RA2"], values["A3"]) == (1, 2, 3)
    assert (values["RD1"], values["RD2"]) == (0x100, 0x200)
    assert (values["SrcA"], values["SrcB"], values["ALUResult"]) == (0x100, 0x200, 0x300)
    assert values["Result"] == values["WD3"] == 0x300 and values["PC'"] == 0x1004
    assert values["ExtImm"] is None and values["ReadData"] is None
    assert values["WriteData"] is None and values["RD4"] is None and values["A4"] is None
    assert t.signals["RegWrite"] == "1" and t.signals["CondEx"] == "1"


def test_r15_reads_as_pc_plus_8(word_of):
    t = trace(0x1000, word_of("ADD R0, PC, R1"), REGISTERS, 0x1D3, no_memory)
    assert t.values["RD1"] == 0x1008 and t.values["ALUResult"] == 0x1108
    t = trace(0x1000, word_of("MOV R0, PC, LSL #1"), REGISTERS, 0x1D3, no_memory)
    assert t.values["RD2"] == 0x1008 and t.values["SrcB"] == 0x2010


@pytest.mark.parametrize("source", ["ADDNE R3, R1, R2", "BNE there", "BLNE there", "BXNE LR",
                                    "MOVNE PC, LR", "LDRNE R0, [R1]", "STRNE R0, [R1]",
                                    "LDRNE PC, [R1]", "ANDNES R0, R1, R2", "ADDNES R0, R1, R2",
                                    "CMPNE R0, R1"])
def test_a_failed_condition_gates_every_write(word_of, source):
    cpsr = 0x40000000 | 0x1D3           # Z set: NE fails
    t = trace(0x1000, word_of(source), REGISTERS, cpsr, lambda address, size: bytes(size))
    gated = [t.signals[name] for name in ("CondEx", "PCSrc", "RegWrite", "MemWrite")]
    assert gated == ["0"] * 4 and t.signals["FlagWrite"] == "00"
    assert t.values["PC'"] == 0x1004 and t.new_flags == t.flags == 0b0100
    assert t.condition == "NE: Z = 1, does not execute"
    active = t.active
    assert "Result" not in active and "ResultPC" not in active and "WriteData" not in active
    assert "PC'" in active and "PCFeed" in active


def test_a_failed_condition_changes_no_signal_of_the_tables(word_of):
    word = word_of("ADDNES R3, R1, R2")
    t = trace(0x1000, word, REGISTERS, 0x40000000, no_memory)
    assert t.signals["RegW"] == "1" and t.signals["FlagW"] == "11"


def test_a_load_with_an_unknown_value_says_so(word_of):
    t = trace(0x1000, word_of("LDR R0, [R1]"), REGISTERS, 0x1D3, lambda address, size: None)
    assert t.values["ALUResult"] == 0x100
    assert t.values["ReadData"] is None and t.values["Result"] is None and t.values["WD3"] is None
    assert "ReadData" in t.active       # on the diagram: a question mark
    t = trace(0x1000, word_of("LDR PC, [R1]"), REGISTERS, 0x1D3, lambda address, size: None)
    assert t.values["PC'"] is None


def test_a_load_that_ran_takes_the_value_it_got(word_of):
    t = trace(0x1000, word_of("LDR R0, [R1]"), REGISTERS, 0x1D3, no_memory, loaded=0x1234)
    assert t.values["ReadData"] == t.values["Result"] == t.values["WD3"] == 0x1234


def test_a_load_before_it_runs_reads_with_the_function_given(word_of):
    asked = []

    def memory(address, size):
        asked.append((address, size))
        return bytes(range(1, size + 1))
    t = trace(0x1000, word_of("LDR R0, [R1, #4]"), REGISTERS, 0x1D3, memory)
    assert asked == [(0x104, 4)] and t.values["ReadData"] == 0x04030201
    asked.clear()
    t = trace(0x1000, word_of("LDRB R0, [R1, #4]"), REGISTERS, 0x1D3, memory)
    assert asked == [(0x104, 1)] and t.values["ReadData"] == 1


def test_the_stages_name_the_five_steps_in_order(word_of):
    t = trace(0, word_of("ADD R3, R1, R2"), REGISTERS, 0x1D3, no_memory)
    assert [stage.name for stage in t.stages] == list(STAGES) == [
        "Fetch", "Decode", "Execute", "Memory", "Write back"]


@pytest.mark.parametrize("source, stage, wires, blocks", [
    ("ADD R3, R1, R2", 0, {"PC", "Instr", "PCPlus4"}, {"PCReg", "IMem", "Add4"}),
    ("ADD R3, R1, R2", 1, {"RA1", "RA2", "RD1", "RD2", "Rn", "Rm"},
     {"Control", "RegFile", "RA1Mux", "RA2Mux"}),
    ("ADD R3, R1, R2", 2, {"SrcA", "SrcB", "ALUResult", "Shifted"}, {"ALU", "ALUSrcMux"}),
    ("ADD R3, R1, R2", 3, set(), set()),
    ("ADD R3, R1, R2", 4, {"Result", "ResultReg", "WD3", "A3", "PC'", "PCFeed", "ALUBypass"},
     {"RegFile", "ResultMux", "PCMux"}),
    ("ADD R3, R1, #1", 1, {"RA1", "RD1", "Imm", "ExtImm"}, {"Extend", "RegFile"}),
    ("ADD R3, R1, R2, LSL #1", 2, {"Shamt", "Shifted"}, {"Shifter"}),
    ("LDR R0, [R1]", 3, {"ALUResult", "ReadData"}, {"DMem"}),
    ("LDR R0, [R1]", 4, {"ReadData", "Result", "WD3"}, {"ResultMux"}),
    ("STR R0, [R1]", 1, {"RA2", "RD2", "RdField"}, {"RegFile"}),
    ("STR R0, [R1]", 3, {"WriteData", "RD2Store", "MemWrite"}, {"DMem", "StoreMux"}),
    ("STR R0, [R1, R2]", 1, {"A4", "RD4", "RdField"}, {"RegFile"}),
    ("STR R0, [R1, R2]", 3, {"RD4", "WriteData", "StoreSrc"}, {"DMem", "StoreMux"}),
    ("BL there", 1, {"RA1", "RD1", "PCPlus8", "Const15"}, {"Add8", "RA1Mux"}),
    ("BL there", 4, {"PC'", "ResultPC", "LinkFeed", "WD3", "Const14", "A3", "Link"},
     {"A3Mux", "WD3Mux", "PCMux"}),
    ("B there", 4, {"PC'", "ResultPC", "PCSrc"}, {"PCMux"}),
    ("ADDS R0, R1, R2", 2, {"ALUFlags"}, {"ALU"}),
    ("ANDS R0, R1, R2, LSL #1", 2, {"ALUFlags", "ShiftC"}, {"Shifter"}),
    ("BX LR", 1, {"Rm", "RA2", "RD2", "RegSrc"}, {"RA2Mux", "RegFile", "Control"}),
    ("BX LR", 2, {"Shifted", "SrcB", "ALUControl", "ALUResult"}, {"ALUSrcMux", "ALU"}),
    ("BX LR", 3, set(), set()),
    ("BX LR", 4, {"ALUBypass", "Result", "MemtoReg", "ResultPC", "PCSrc", "PC'"},
     {"ResultMux", "PCMux"}),
])
def test_each_stage_holds_its_wires_and_blocks(word_of, source, stage, wires, blocks):
    t = trace(0, word_of(source), REGISTERS, 0x1D3, lambda address, size: bytes(size))
    assert wires <= t.stages[stage].wires
    assert blocks <= t.stages[stage].blocks
    assert blocks <= set(BLOCKS)


@pytest.mark.parametrize("source, gray", [
    ("MOV R3, R2", {"RA1", "RD1", "SrcA", "Rn"}),       # MOV and MVN use no first operand
    ("MVN R3, #1", {"RA1", "RD1", "SrcA", "Rn", "RA2", "RD2"}),
    ("ADD R3, R1, R2", {"PCPlus8", "ExtImm", "Imm", "Shamt", "ReadData", "WriteData", "A4", "RD4",
                        "ALUFlags", "ShiftC", "Link", "LinkFeed", "ResultPC", "MemWrite"}),
    ("CMP R1, R2", {"Result", "WD3", "A3", "ResultReg", "ALUBypass"}),
    ("B there", {"RA2", "RD2", "A3", "WD3", "ResultReg", "Link"}),
    ("LDR R0, [R1]", {"RA2", "RD2", "Shifted", "ALUBypass", "WriteData"}),
    ("BX LR", {"RA1", "RD1", "SrcA", "Rn", "Const15", "PCPlus8", "RdField", "RdToRA2", "Imm",
               "ExtImm", "Shift", "Shamt", "ALUFlags", "ShiftC", "Address", "ReadData", "WriteData",
               "MemWrite", "A3", "WD3", "ResultReg", "RegWrite", "Link", "LinkFeed", "PCFeed"}),
])
def test_what_an_instruction_does_not_use_stays_gray(word_of, source, gray):
    t = trace(0, word_of(source), REGISTERS, 0x1D3, lambda address, size: bytes(size))
    assert not gray & t.active


def test_r15_as_a_source_lights_pc_plus_8(word_of):
    t = trace(0, word_of("ADD R0, PC, R1"), REGISTERS, 0x1D3, no_memory)
    assert "PCPlus8" in t.active and "Add8" in t.active_blocks


def test_a_write_to_r15_goes_to_the_pc_and_no_register(word_of):
    t = trace(0x1000, word_of("MOV PC, LR"), REGISTERS, 0x1D3, no_memory)
    assert t.values["PC'"] == REGISTERS[14] and t.signals["PCSrc"] == "1"
    assert "ResultPC" in t.active and "PCFeed" not in t.active
    assert "WD3" not in t.active and "A3" not in t.active


def test_bx_on_every_wire(word_of):
    t = trace(0x1000, word_of("BX R3"), REGISTERS, 0x600001D3, no_memory)
    values, sig = t.values, t.signals
    assert t.kind == BRANCH_EXCHANGE and not t.note and t.text == "BX R3"
    assert (values["RA2"], values["RD2"], values["Shifted"]) == (3, 0x300, 0x300)
    assert values["SrcB"] == values["ALUResult"] == values["Result"] == values["PC'"] == 0x300
    assert values["A3"] is None and values["WD3"] is None and values["A4"] is None
    assert values["ExtImm"] is None and values["WriteData"] is None and values["ReadData"] is None
    assert (sig["CondEx"], sig["PCSrc"], sig["RegWrite"], sig["MemWrite"]) == ("1", "1", "0", "0")
    assert sig["FlagWrite"] == "00" and t.new_flags == t.flags == 0b0110


def test_bx_takes_rm_as_it_is_whatever_instr_11_5_holds(word_of):
    """Those bits of BX would read as ROR #30 and more to a shifter."""
    state = list(REGISTERS)
    state[14] = 0x12345678
    t = trace(0, word_of("BX LR"), state, 0x1D3, no_memory)
    assert t.values["SrcB"] == 0x12345678 and t.signals["Shift"] == "0"
    assert "Shifter" not in t.active_blocks


@pytest.mark.parametrize("rm", range(15))
def test_bx_reads_the_register_named_in_instr_3_0(rm):
    t = trace(0x1000, 0xE12FFF10 | rm, REGISTERS, 0x1D3, no_memory)
    assert t.values["RA2"] == rm and t.values["PC'"] == 0x100 * rm


def test_bx_pc_reads_pc_plus_8_and_lights_its_wire(word_of):
    t = trace(0x1000, word_of("BX PC"), REGISTERS, 0x1D3, no_memory)
    assert t.values["RD2"] == t.values["PC'"] == 0x1008
    assert "PCPlus8" in t.active and "Add8" in t.active_blocks


@pytest.mark.parametrize("target, pc", [(0x2000, 0x2000), (0x2001, 0x2000), (0x2002, 0x2002),
                                        (0x2003, 0x2002), (0xFFFFFFFF, 0xFFFFFFFE)])
def test_the_pc_drops_bit_0_of_the_result_and_keeps_bit_1(word_of, target, pc):
    state = list(REGISTERS)
    state[0] = target
    t = trace(0x1000, word_of("BX R0"), state, 0x1D3, no_memory)
    assert t.values["Result"] == target and t.values["PC'"] == pc
    assert t.to_thumb == bool(target & 1)


@pytest.mark.parametrize("source", ["BX R0", "MOV PC, R0", "ADD PC, R0, #0", "LDR PC, [R1]"])
def test_an_odd_address_says_that_thumb_code_follows(word_of, source):
    state = list(REGISTERS)
    state[0] = 0x2001
    t = trace(0x1000, word_of(source), state, 0x1D3, lambda address, size: bytes((1, 0x20, 0, 0)))
    assert t.to_thumb and t.values["PC'"] == 0x2000


@pytest.mark.parametrize("source", ["BX R0", "BXNE R0", "ADD R2, R0, #0", "LDR R2, [R1]"])
def test_nothing_of_thumb_code_while_the_pc_takes_no_odd_address(word_of, source):
    state = list(REGISTERS)
    state[0] = 0x2001 if "NE" in source or "R2" in source else 0x2000
    t = trace(0x1000, word_of(source), state, 0x40000000 | 0x1D3,
              lambda address, size: bytes((1, 0, 0, 0)))
    assert not t.to_thumb


def test_a_load_to_the_pc_of_unknown_value_says_nothing_of_thumb_code(word_of):
    t = trace(0x1000, word_of("LDR PC, [R1]"), REGISTERS, 0x1D3, lambda address, size: None)
    assert t.values["PC'"] is None and not t.to_thumb


def test_outside_a_trace_has_the_note_and_the_condition(word_of):
    t = trace(0x1000, word_of("UMULLNE R0, R1, R2, R3"), REGISTERS, 0x40000000, no_memory)
    assert t.note and t.kind == OUTSIDE and t.condition == "NE: Z = 1, does not execute"
    assert t.signals == {} and not t.active and not t.active_blocks
    assert t.text == "UMULLNE R0, R1, R2, R3"
    t = trace(0x1000, 0xF57FF04F, REGISTERS, 0x1D3, no_memory)
    assert t.note and t.condition == ""


def test_mla_on_every_wire(word_of):
    """MLA R3, R4, R5, R6 (Rd 19:16, Ra 15:12, Rs 11:8, Rm 3:0): Mul makes RA1 take Rs and A3
    Instr 19:16; Ra is read on A4, and the multiplier adds RD4 to RD1 x RD2."""
    state = list(REGISTERS)
    state[5], state[4], state[6] = 7, 3, 0x15
    t = trace(0x1000, word_of("MLA R3, R4, R5, R6"), state, 0x1D3, no_memory)
    values, sig = t.values, t.signals
    assert t.kind == MULTIPLY and not t.note and t.text == "MLA R3, R4, R5, R6"
    assert (values["RA1"], values["RA2"], values["A4"], values["A3"]) == (5, 4, 6, 3)
    assert (values["RD1"], values["RD2"], values["RD4"]) == (7, 3, 0x15)
    assert values["SrcA"] == 7 and values["Shifted"] == values["SrcB"] == 3
    assert values["ALUResult"] == values["Result"] == values["WD3"] == 7 * 3 + 0x15
    assert values["ExtImm"] is None and values["WriteData"] is None and values["Address"] is None
    assert (sig["Mul"], sig["ALUControl"], sig["RegWrite"], sig["PCSrc"]) == \
        ("1", ALU_MLA, "1", "0")
    assert {"Op2", "Mul", "Rs", "RD4ToALU", "RnToA3"} <= t.active
    assert not {"Const15", "Rn", "Const14", "RdToA3", "ALUFlags"} & t.active


def test_mul_reads_no_a4_and_multiplies_the_low_32_bits(word_of):
    state = list(REGISTERS)
    state[1], state[2] = 0x12345678, 0x9ABCDEF1
    t = trace(0x1000, word_of("MULS R0, R1, R2"), state, 0x300001D3, no_memory)
    values = t.values
    assert (values["RA1"], values["RA2"], values["A3"]) == (2, 1, 0)
    assert values["A4"] is None and values["RD4"] is None and "RD4ToALU" not in t.active
    assert values["ALUResult"] == 0x12345678 * 0x9ABCDEF1 & 0xFFFFFFFF
    assert t.signals["FlagWrite"] == "10"
    assert t.new_flags == (values["ALUResult"] >> 31) << 3 | 0b0011     # C and V stay
    assert t.hardware["A4"] == 0 and t.hardware["RD4"] == state[0]      # A4 reads 15:12, unused


def test_a_multiply_whose_condition_fails_writes_nothing(word_of):
    t = trace(0x1000, word_of("MULNE R0, R1, R2"), REGISTERS, 0x400001D3, no_memory)
    assert t.signals["CondEx"] == "0" and t.signals["RegWrite"] == "0"
    assert t.values["A3"] == 0 and t.values["PC'"] == 0x1004 and t.new_flags == t.flags


def test_a_shift_by_a_register_on_every_wire(word_of):
    """ADD R2, R1, R0, LSL R3: ShiftReg makes A4 read Rs; RD4 goes into the shifter, which takes
    its amount from RD4[7:0], and Shift is 1 because that amount is not 0."""
    state = list(REGISTERS)
    state[0], state[1], state[3] = 7, 0x28, 0x102          # R3[7:0] = 2
    t = trace(0x1000, word_of("ADD R2, R1, R0, LSL R3"), state, 0x1D3, no_memory)
    values, sig = t.values, t.signals
    assert (sig["ShiftReg"], sig["Shift"], sig["StoreSrc"], sig["Mul"]) == ("1", "1", "0", "0")
    assert (values["RA1"], values["RA2"], values["A4"], values["A3"]) == (1, 0, 3, 2)
    assert values["RD4"] == 0x102 and values["Shifted"] == 28 and values["SrcB"] == 28
    assert values["ALUResult"] == values["WD3"] == 0x28 + 28 and values["WriteData"] is None
    assert {"ShiftReg", "Op2", "Rs", "A4", "RD4", "RD4ToShifter"} <= t.active
    assert "A4Mux" in t.active_blocks and "Shifter" in t.active_blocks
    state[3] = 0x100                                        # R3[7:0] = 0: nothing shifts
    t = trace(0x1000, word_of("MOVS R2, R0, ROR R3"), state, 0x200001D3, no_memory)
    # The control unit cannot see R3: Shift is 1, and an amount of 0 leaves the value and C.
    assert t.signals["Shift"] == "1" and t.values["ShiftCarry"] == 1
    assert t.values["Shifted"] == 7 and t.new_flags == 0b0010     # C stays


def test_adc_takes_the_c_flag_on_the_carryin_wire(word_of):
    state = list(REGISTERS)
    t = trace(0x1000, word_of("ADCS R0, R1, R2"), state, 0x200001D3, no_memory)
    assert t.values["CarryIn"] == 1 and t.values["ALUResult"] == 0x100 + 0x200 + 1
    assert "CarryIn" in t.active and t.signals["ALUControl"] == "1011"
    t = trace(0x1000, word_of("ADD R0, R1, R2"), state, 0x200001D3, no_memory)
    assert t.values["CarryIn"] is None and "CarryIn" not in t.active


def test_teq_only_sets_the_flags(word_of):
    state = list(REGISTERS)
    state[1] = state[2] = 0x80000001
    t = trace(0x1000, word_of("TEQ R1, R2"), state, 0xF00001D3, no_memory)
    assert t.values["A3"] is None and t.signals["RegWrite"] == "0"
    assert t.values["ALUResult"] == 0 and t.new_flags == 0b0111     # N 0, Z 1, C and V stay


def test_blx_writes_lr_and_jumps_to_rm(word_of):
    state = list(REGISTERS)
    state[3] = 0x2001
    t = trace(0x1000, word_of("BLX R3"), state, 0x1D3, no_memory)
    values, sig = t.values, t.signals
    assert t.kind == BRANCH_LINK_EXCHANGE and t.text == "BLX R3"
    assert (values["RA2"], values["A3"], values["WD3"]) == (3, 14, 0x1004)
    assert values["PC'"] == 0x2000 and t.to_thumb and values["RA1"] is None
    assert (sig["RegWrite"], sig["PCSrc"], sig["Link"]) == ("1", "1", "1")
    assert {"Const14", "LinkFeed", "WD3", "ResultPC"} <= t.active


def test_nop_reads_nothing_and_writes_nothing(word_of):
    t = trace(0x1000, word_of("NOP"), REGISTERS, 0x1D3, no_memory)
    assert t.kind == NO_OPERATION and t.text == "NOP" and not t.note
    assert t.values["PC'"] == 0x1004
    assert all(t.values[name] is None for name in ("RA1", "RA2", "A3", "A4", "SrcB", "ALUResult"))
    assert t.active == {"PC", "Instr", "PCPlus4", "Cond", "Op", "Funct", "PC'", "PCFeed"}


def test_movw_writes_its_immediate_with_zeros_above(word_of):
    t = trace(0x1000, word_of("MOVW R10, #0xFEDC"), REGISTERS, 0x1D3, no_memory)
    values, sig = t.values, t.signals
    assert t.kind == MOVE_16 and not t.note and t.text == "MOVW R10, #0xFEDC"
    assert (sig["ImmSrc"], sig["ALUSrc"], sig["ALUControl"], sig["RegWrite"]) == \
        ("100", "1", "0111", "1")
    assert values["ExtImm"] == values["SrcB"] == values["ALUResult"] == values["WD3"] == 0xFEDC
    assert values["A3"] == 10 and values["PC'"] == 0x1004
    assert all(values[name] is None for name in ("RA1", "RD1", "RA2", "RD2", "A4", "RD4"))
    assert "RD4ToALU" not in t.active and {"Imm", "ExtImm", "Rd"} <= t.active


def test_movt_joins_its_immediate_to_the_low_half_of_rd(word_of):
    """MOVT R10, #0x1234: A4 reads Rd (Instr 15:12); RD4 goes into the ALU, whose ALUControl 1110
    takes the high half from SrcB and the low half from RD4."""
    state = list(REGISTERS)
    state[10] = 0xABCD5678
    t = trace(0x1000, word_of("MOVT R10, #0x1234"), state, 0x1D3, no_memory)
    values, sig = t.values, t.signals
    assert t.kind == MOVE_16 and sig["ALUControl"] == ALU_MOVT and sig["FlagW"] == "00"
    assert (values["A4"], values["RD4"], values["ExtImm"]) == (10, 0xABCD5678, 0x1234)
    assert values["ALUResult"] == values["WD3"] == 0x12345678 and values["A3"] == 10
    assert values["RA1"] is None and values["RA2"] is None
    assert {"A4", "RD4", "RD4ToALU", "RdField"} <= t.active and "A4Mux" in t.active_blocks
    assert t.hardware["RD4"] == 0xABCD5678 and t.new_flags == t.flags


def test_a_signed_load_sign_extends_what_it_reads(word_of):
    """LDRSB and LDRSH: the load extender copies the sign bit upwards; LDRH and LDRB fill zeros."""
    state = list(REGISTERS)

    def memory(address, size):
        return bytes([0x80, 0x91, 0x7F, 0x01][:size])
    for source, value, size, signed in (("LDRSB R0, [R1]", 0xFFFFFF80, "10", "1"),
                                        ("LDRB R0, [R1]", 0x80, "10", "0"),
                                        ("LDRSH R0, [R1]", 0xFFFF9180, "01", "1"),
                                        ("LDRH R0, [R1]", 0x9180, "01", "0"),
                                        ("LDR R0, [R1]", 0x017F9180, "00", "0")):
        t = trace(0x1000, word_of(source), state, 0x1D3, memory)
        assert (t.signals["Size"], t.signals["Signed"]) == (size, signed), source
        assert t.values["ReadData"] == t.values["WD3"] == value, source
        assert ("Signed" in t.active) and "Size" in t.active


def test_halfword_transfers_in_every_form(word_of):
    state = list(REGISTERS)
    state[2] = 6
    t = trace(0x1000, word_of("STRH R0, [R1], -R2"), state, 0x1D3, no_memory)
    values, sig = t.values, t.signals
    assert t.kind == STORE_HALF_REGISTER and sig["StoreSrc"] == "1" and sig["Shift"] == "0"
    assert (values["A4"], values["RD4"], values["WriteData"]) == (0, 0, 0)
    assert values["Address"] == values["SrcA"] == 0x100 and values["ALUResult"] == 0xFA
    assert (sig["AdrSrc"], sig["BaseWrite"], values["A5"], values["WD5"]) == ("1", "1", 1, 0xFA)
    assert values["Shifted"] == values["SrcB"] == 6         # the shifter passes Rm on
    t = trace(0x1000, word_of("LDRSH R3, [R1, #-0x24]!"), state, 0x1D3,
              lambda address, size: bytes([0xFE, 0xFF][:size]))
    values, sig = t.values, t.signals
    assert t.kind == LOAD_HALF_IMMEDIATE and sig["ImmSrc"] == "101"
    assert values["ExtImm"] == 0x24 and values["ALUResult"] == values["Address"] == 0xDC
    assert values["ReadData"] == 0xFFFFFFFE and values["WD5"] == 0xDC and values["A3"] == 3


def test_thumb_code_lies_outside():
    t = trace(0x1000, 0xE0810002, REGISTERS, 0x1F3, no_memory)
    assert t.kind == OUTSIDE and "Thumb" in t.note


# Wires against Unicorn ---------------------------------------------------------------

def agree(machine, change, before):
    """The trace of the instruction machine just executed agrees with the machine; the trace. An
    LDM, STM, PUSH or POP agrees pass by pass: what its passes write, one after the other, is
    what the machine did, and its last pass gives the next PC."""
    t = executed(machine, change)
    assert t.pc == before[SNAPSHOT_PC]
    if t.note:
        return t
    now = machine.uc.reg_read_batch(SNAPSHOT_REGISTERS)
    where = f"{t.text} at 0x{t.pc:08x}"
    passes = t.passes or (t,)
    # The next PC.
    assert passes[-1].values["PC'"] == machine.pc, where
    assert all(one.signals["Hold"] == "1" for one in passes[:-1]), where
    # The flags.
    assert t.new_flags == machine.cpsr >> 28, where
    thumb = 0x20 if t.to_thumb else 0
    assert machine.cpsr & 0x0FFFFFFF == before[0] & 0x0FFFFFFF | thumb, where
    if t.kind == SYSTEM_CALL:           # the system wrote what its service writes
        return t
    # The registers: each pass writes A3 with WD3 and the base A5 with WD5; all others stay.
    state = list(before[2:2 + 15])
    writes = {}
    for one in passes:
        values, sig = one.values, one.signals
        assert values["Address"] == (values["SrcA"] if sig["AdrSrc"] == "1"
                                     else values["ALUResult"]) or values["Address"] is None, where
        if sig["MemWrite"] == "1":      # Size: a word, a halfword or a byte
            size = {"00": 4, "01": 2, "10": 1}[sig["Size"]]
            writes[values["Address"]] = (size, values["WriteData"] & (1 << 8 * size) - 1)
        if sig["RegWrite"] == "1" and values["A3"] != 15:
            state[values["A3"]] = values["WD3"]
        if sig["BaseWrite"] == "1":
            state[values["A5"]] = values["WD5"]
        # A load: the value read is on the wires and what the register got.
        if sig["MemtoReg"] == "1" and sig["CondEx"] == "1":
            assert values["Result"] == values["ReadData"], where
    for n in range(15):
        assert now[2 + n] == state[n], (where, n)
    # The memory.
    if writes:
        if change.writes:
            assert sorted((start, len(old)) for start, old in change.writes) == sorted(
                (address, size) for address, (size, _) in writes.items()), where
            for address, (size, data) in writes.items():
                assert int.from_bytes(machine.read_memory(address, size), "little") == data, where
    else:
        assert change.writes == [], where
    return t


def stepped(machine, limit=100_000):
    """Step the machine to its end; yields each instruction's trace once checked."""
    for _ in range(limit):
        if machine.stop_reason is not None or machine.request is not None:
            return
        before = machine.uc.reg_read_batch(SNAPSHOT_REGISTERS)
        count = len(machine.history)
        number = machine.history[-1].number if machine.history else 0
        machine.step()
        if not machine.history or machine.history[-1].number == number:
            continue                    # nothing ran: the program ended here, or it waits
        assert len(machine.history) >= min(count, 2000)
        yield agree(machine, machine.history[-1], before)


def run_steps(build, source):
    """Run source from its first instruction, step by step; the traces of its instructions."""
    machine = Machine(build(HEADER + source + END))
    return list(stepped(machine))


def only(traces, text):
    found = [t for t in traces if t.text == text]
    assert found, [t.text for t in traces]
    return found[0]


SET_UP = """\
        LDR     R1, =0x12345678
        LDR     R2, =0x0F0F00F1
        LDR     R3, =0x80000001
        MOV     R4, #5
        MOV     R5, #0
"""


@pytest.mark.parametrize("operation", ["ADD", "SUB", "AND", "ORR", "EOR", "BIC", "RSB", "ADC",
                                       "SBC", "RSC"])
@pytest.mark.parametrize("s", ["", "S"])
@pytest.mark.parametrize("operand", ["R2", "#0xFF", "#0xFF000000", "#0x3FC", "R2, LSL #3",
                                     "R2, LSR #5", "R2, ASR #7", "R2, ROR #9", "R2, RRX",
                                     "R3, LSR #32", "R3, ASR #32"])
def test_alu_operations_agree(build, operation, s, operand):
    run_steps(build, SET_UP + f"""\
        MSR     CPSR_f, #0x20000000
        {operation}{s} R0, R1, {operand}
        {operation}{s} R6, R3, {operand}
        {operation}{s} R7, R5, {operand}
        MSR     CPSR_f, #0xF0000000
        {operation}{s} R8, R1, {operand}
        {operation}{s} R1, R1, {operand}
""")


@pytest.mark.parametrize("operation", ["MOV", "MVN"])
@pytest.mark.parametrize("s", ["", "S"])
@pytest.mark.parametrize("operand", ["R2", "R3", "R5", "#0", "#0xFF", "#0xF000000F", "R3, LSL #1",
                                     "R3, LSR #1", "R3, ASR #1", "R3, ROR #1", "R3, RRX",
                                     "R3, LSR #32", "R3, ASR #32"])
def test_moves_agree(build, operation, s, operand):
    run_steps(build, SET_UP + f"""\
        MSR     CPSR_f, #0x60000000
        {operation}{s} R0, {operand}
        MSR     CPSR_f, #0x90000000
        {operation}{s} R6, {operand}
""")


@pytest.mark.parametrize("operation", ["CMP", "CMN", "TST", "TEQ"])
@pytest.mark.parametrize("operand", ["R2", "R3", "R1", "#0", "#1", "#0x80000000", "R3, LSL #1",
                                     "R3, RRX", "R3, ROR #1", "R3, LSR #32"])
def test_comparisons_agree(build, operation, operand):
    traces = run_steps(build, SET_UP + f"""\
        {operation} R1, {operand}
        {operation} R3, {operand}
        MSR     CPSR_f, #0xF0000000
        {operation} R5, {operand}
""")
    tested = [t for t in traces if t.text.startswith(operation)]
    assert len(tested) == 3 and all(t.signals["RegWrite"] == "0" for t in tested)
    assert not any("Result" in t.active for t in tested)


CONDITIONS = ["EQ", "NE", "CS", "CC", "MI", "PL", "VS", "VC", "HI", "LS", "GE", "LT", "GT", "LE",
              "AL"]


@pytest.mark.parametrize("cond", CONDITIONS)
def test_every_condition_passing_and_failing_agrees(build, cond):
    body = "".join(f"""\
        MSR     CPSR_f, #{flags << 28}
        ADD{cond} R0, R0, #1
        STR{cond} R0, [R12]
        LDR{cond} R1, [R12]
        MOV{cond}S R2, R3, LSL #1
        B{cond} over{flags}
        ADD     R4, R4, #1
over{flags}:
        BL{cond} call{flags}
call{flags}:
        ADR     R9, jump{flags}
        BX{cond} R9
        ADD     R4, R4, #1
jump{flags}:
""" for flags in range(16))
    traces = run_steps(build, "        LDR R12, =0x2000\n        LDR R3, =0xC0000001\n" + body)
    results = {t.signals["CondEx"] for t in traces if t.text.startswith("ADD")}
    assert results == ({"1"} if cond == "AL" else {"0", "1"})


def test_shifted_register_offsets_and_negative_offsets_agree(build):
    traces = run_steps(build, """\
        LDR     R1, =table
        MOV     R2, #2
        LDR     R0, [R1, #4]
        LDR     R3, [R1, R2]
        LDR     R3, [R1, R2, LSL #2]
        ADD     R6, R1, #16
        LDR     R3, [R6, #-8]
        LDR     R3, [R6, -R2, LSL #1]
        LDR     R3, [R6, -R2, LSR #1]
        LDR     R3, [R6, R2, ASR #1]
        LDR     R3, [R6, R2, ROR #1]
        LDRB    R3, [R1, #5]
        LDRB    R3, [R1, R2]
        LDRB    R3, [R6, -R2]
        LDRB    R3, [R6, #-3]
        LDR     R7, =0x87654321
        STR     R7, [R1, #4]
        STR     R7, [R1, R2, LSL #1]
        STR     R7, [R6, #-4]
        STR     R7, [R6, -R2, LSL #2]
        STRB    R7, [R1, #3]
        STRB    R7, [R1, R2]
        STRB    R7, [R6, -R2]
        STR     PC, [R1, #8]
        STR     PC, [R1, R2, LSL #2]
        B       done
        .data
table:  .word   0x11223344, 0x55667788, 0x99AABBCC, 0xDDEEFF00, 0x01020304, 0x05060708
        .text
done:
""")
    t = only(traces, "STR R7, [R1, R2, LSL #1]")
    assert t.signals["StoreSrc"] == "1" and t.values["A4"] == 7
    assert t.values["RD4"] == t.values["WriteData"] == 0x87654321
    assert t.values["RD2"] == 2 and t.values["SrcB"] == 4
    t = only(traces, "LDRB R3, [R1, #5]")
    assert t.values["ReadData"] == 0x77


def test_the_shifter_in_a_store_with_pc_as_data(build):
    traces = run_steps(build, """\
        LDR     R1, =0x3000
        STR     PC, [R1]
""")
    t = only(traces, "STR PC, [R1]")
    assert t.values["WriteData"] == t.pc + 8


def test_branches_agree(build):
    traces = run_steps(build, """\
        MOV     R0, #1
        B       forward
back:   MOV     R0, #2
        B       finish
forward:
        BL      function
        B       back
function:
        ADD     R0, R0, #3
        MOV     PC, LR
finish:
""")
    t = next(t for t in traces if t.text.startswith("BL "))
    assert t.signals["Link"] == "1" and t.values["A3"] == 14
    assert t.values["WD3"] == t.values["PCPlus4"] == t.pc + 4
    assert t.values["Result"] == t.values["PC'"] == 0x18
    assert t.values["SrcA"] == t.pc + 8
    t = only(traces, "MOV PC, LR")
    assert t.signals["PCSrc"] == "1" and t.values["PC'"] == t.values["SrcB"]


@pytest.mark.parametrize("name", [f"R{n}" for n in range(13)] + ["SP", "LR"])
def test_bx_through_each_register_agrees(build, name):
    traces = run_steps(build, f"""\
        MSR     CPSR_f, #0x90000000
        ADR     {name}, there
        BX      {name}
        ADD     R0, R0, #1
there:
""")
    t = only(traces, f"BX {name}")
    assert t.signals["PCSrc"] == "1" and t.values["PC'"] == t.values["SrcB"] == t.pc + 8
    assert t.new_flags == t.flags == 0b1001


def test_bx_pc_agrees(build):
    traces = run_steps(build, """\
        BX      PC
        ADD     R0, R0, #1
        ADD     R1, R1, #1
""")
    t = only(traces, "BX PC")
    assert t.values["PC'"] == t.pc + 8
    assert not any(t.text == "ADD R0, R0, #1" for t in traces)


def steps_of_a_jump(build, offset, branch="BX"):
    """Run to a BX R0 (or BLX R0) whose address is there + offset, and just past it; its trace
    and the machine."""
    machine = Machine(build(HEADER + f"""\
        ADR     R0, there
        ADD     R0, R0, #{offset}
        {branch:7} R0
there:  NOP
        NOP
        NOP
""" + END))
    machine.step()
    machine.step()
    assert upcoming(machine).text == f"{branch} R0"
    before = machine.uc.reg_read_batch(SNAPSHOT_REGISTERS)
    machine.step()
    return agree(machine, machine.history[-1], before), machine


@pytest.mark.parametrize("branch", ["BX", "BLX"])
@pytest.mark.parametrize("offset, thumb", [(0, False), (1, True), (2, False), (3, True)])
def test_bx_and_blx_agree_for_every_low_address_bit(build, branch, offset, thumb):
    """The address really reached, and the T bit: agree() compares both with the machine. BLX
    also writes LR, the next instruction, whatever bit 0 of the address says."""
    t, machine = steps_of_a_jump(build, offset, branch)
    there = t.pc + 4
    assert t.values["Result"] == there + offset
    assert t.values["PC'"] == machine.pc == there + (offset & 2)
    assert t.to_thumb == thumb == bool(machine.cpsr & 0x20)
    if branch == "BLX":
        assert t.values["A3"] == 14 and t.values["WD3"] == machine.reg(14) == there


def test_after_bx_to_an_odd_address_the_datapath_says_thumb_code(build):
    _, machine = steps_of_a_jump(build, 1)
    t = upcoming(machine)
    assert t.kind == OUTSIDE and t.note == NOTE_THUMB and t.text == "Thumb code"


@pytest.mark.parametrize("line", ["MOV PC, R0", "ADD PC, R0, #0"])
def test_other_writes_of_an_odd_address_to_the_pc_agree(build, line):
    machine = Machine(build(HEADER + f"""\
        ADR     R0, there
        ADD     R0, R0, #1
        {line}
there:  NOP
""" + END))
    machine.step()
    machine.step()
    before = machine.uc.reg_read_batch(SNAPSHOT_REGISTERS)
    machine.step()
    t = agree(machine, machine.history[-1], before)
    assert t.to_thumb and machine.cpsr & 0x20


def test_a_load_of_an_odd_address_to_the_pc_agrees(build):
    machine = Machine(build(HEADER + """\
        LDR     R1, =value
        LDR     PC, [R1]
there:  NOP
value:  .word   there + 1
""" + END))
    machine.step()
    before = machine.uc.reg_read_batch(SNAPSHOT_REGISTERS)
    machine.step()
    t = agree(machine, machine.history[-1], before)
    assert t.to_thumb and t.values["ReadData"] & 1 and machine.cpsr & 0x20


def test_each_return_of_a_function_animates_before_and_after_it_runs(tmp_path):
    """A leaf function returns with BX LR: the look ahead and the instruction that ran say the
    same, and each return lands after its own call."""
    result = assemble((PROGRAMS / "leaf.s").read_text(), tmp_path)
    assert result.ok
    machine = Machine(Program(result.elf_path), base_dir=tmp_path)
    returns, calls = [], []
    for _ in range(100):
        if machine.stop_reason is not None:
            break
        ahead = upcoming(machine)
        before = machine.uc.reg_read_batch(SNAPSHOT_REGISTERS)
        machine.step()
        ran = agree(machine, machine.history[-1], before)
        assert ran.text == ahead.text
        if ran.text.startswith("BL "):
            calls.append(ran.pc + 4)
        if ran.text == "BX LR":
            assert ran.kind == ahead.kind == BRANCH_EXCHANGE
            assert ran.values == ahead.values and ran.active == ahead.active
            assert {"Rm", "RD2", "SrcB", "ALUBypass", "ResultPC", "PC'"} <= ran.active
            returns.append(ran.values["PC'"])
    machine.close()
    assert returns == calls and len(returns) == 2


MULTIPLES = """\
        LDR     SP, =stack
        LDR     R8, =table
        MOV     R0, #10
        MOV     R1, #11
        MOV     R2, #12
        MOV     R3, #13
        PUSH    {R0-R3, LR}
        POP     {R4-R7}
        POP     {R9}
        STMIA   R8, {R0, R1}
        STMIB   R8, {R2, R3}
        STMDA   R8, {R0-R2}
        STMDB   R8, {R1, R3}
        LDMIA   R8, {R4, R5}
        LDMIB   R8, {R4, R5, R6}
        LDMDA   R8, {R4, R7}
        LDMDB   R8, {R5}
        STMIA   R8!, {R0, R1}
        LDMDB   R8!, {R4, R5}
        STMIB   R8!, {R2}
        LDMDA   R8!, {R6}
        STMDB   R8!, {R0-R3}
        LDMIA   R8!, {R4-R7}
        ADD     R10, R8, #4
        LDMIA   R10, {R1, R10}
        STMIA   R8, {R8, R9}
        STMIA   R8, {R0, PC}
        MOV     R0, #0
        BL      leaf
        B       finish
leaf:   PUSH    {R4, LR}
        MOV     R4, #7
        POP     {R4, PC}
finish:
        .data
        .space  64
table:  .word   1, 2, 3, 4, 5, 6, 7, 8
        .space  64
stack:  .word   0
"""


def test_every_form_of_ldm_and_stm_agrees_pass_by_pass(build):
    traces = run_steps(build, MULTIPLES)
    multiples = [t for t in traces if t.passes]
    assert len(multiples) == 21
    for t in multiples:
        registers = [n for n in range(16) if t.word >> n & 1]
        assert [one.values["PassReg"] for one in t.passes] in (registers, registers[::-1])
        assert [one.number for one in t.passes] == list(range(1, len(registers) + 1))
        assert all(one.count == len(registers) for one in t.passes)
        assert [one.signals["Hold"] for one in t.passes] == ["1"] * (len(registers) - 1) + ["0"]


def test_push_and_pop_write_the_base_in_each_pass_and_a_pop_of_the_pc_returns(build):
    traces = run_steps(build, MULTIPLES)
    push = only(traces, "PUSH {R0, R1, R2, R3, LR}")
    assert [one.values["PassReg"] for one in push.passes] == [14, 3, 2, 1, 0]   # from the top
    assert all(one.signals["BaseWrite"] == "1" and one.signals["AdrSrc"] == "0"
               for one in push.passes)                                       # STR Rk, [SP, #-4]!
    assert [one.values["Offset"] for one in push.passes] == [4] * 5
    pop = only(traces, "POP {R4, PC}")
    assert [one.values["PassReg"] for one in pop.passes] == [4, 15]          # the PC last
    assert all(one.signals["AdrSrc"] == "1" for one in pop.passes)           # LDR Rk, [SP], #4
    last = pop.passes[-1]
    assert last.signals["PCSrc"] == "1" and last.values["PC'"] == last.values["ReadData"]
    assert pop.passes[0].signals["PCSrc"] == "0"
    stay = only(traces, "LDMIB R8, {R4, R5, R6}")
    assert [one.values["Offset"] for one in stay.passes] == [4, 8, 12]       # the base stays
    assert not any(one.signals["BaseWrite"] == "1" for one in stay.passes)
    down = only(traces, "STMDB R8, {R1, R3}")
    assert [one.values["Offset"] for one in down.passes] == [8, 4]
    assert down.passes[0].signals["ALUControl"] == "0001"                    # counting down


WRITE_BACK = """\
        LDR     R1, =table
        LDR     SP, =stack
        MOV     R2, #4
        LDR     R0, [R1, #4]!
        LDR     R3, [R1], #4
        LDR     R3, [R1], #-8
        LDRB    R4, [R1, #2]!
        LDRB    R4, [R1], #-1
        LDR     R5, [R1, R2]!
        LDR     R5, [R1], -R2
        LDR     R6, [R1, R2, LSL #1]!
        LDR     R6, [R1], R2, LSR #1
        STR     R0, [R1, #4]!
        STR     R0, [R1], #4
        STRB    R0, [R1, #-1]!
        STRB    R0, [R1], R2
        STR     R3, [R1, -R2, LSL #1]!
        STR     PC, [R1], #4
        PUSH    {R0}
        POP     {R7}
        BL      leaf
        B       finish
leaf:   PUSH    {LR}
        POP     {PC}
finish:
        .data
        .space  64
table:  .word   0x11223344, 0x55667788, 0x99AABBCC, 0xDDEEFF00, 0x01020304, 0x05060708
        .space  64
stack:  .word   0
"""


def test_write_back_and_post_indexing_agree_and_write_the_base(build):
    traces = run_steps(build, WRITE_BACK)
    moved = [t for t in traces if t.signals.get("BaseWrite") == "1"]
    assert len(moved) == 19
    for t in moved:
        values = t.values
        assert values["A5"] == t.word >> 16 & 0xF and values["WD5"] == values["ALUResult"]
        post = not t.word >> 24 & 1
        assert t.signals["AdrSrc"] == ("1" if post else "0")
        assert values["Address"] == (values["SrcA"] if post else values["ALUResult"])
    post = only(traces, "LDR R3, [R1], #4")
    assert post.values["Address"] == post.values["SrcA"] != post.values["ALUResult"]
    ret = only(traces, "POP {PC}")
    assert ret.signals["PCSrc"] == "1" and ret.values["PC'"] == ret.values["ReadData"]
    assert ret.signals["BaseWrite"] == "1" and ret.values["A5"] == 13


MULTIPLIES = """        LDR     R1, =0x12345678
        LDR     R2, =0x9ABCDEF1
        MOV     R3, #7
        MOV     R4, #3
        MUL     R0, R3, R4
        MULS    R5, R1, R2
        MLA     R6, R3, R4, R0
        MLAS    R7, R1, R2, R3
        MOV     R9, #0
        MSR     CPSR_f, #0x30000000
        MULS    R10, R9, R1
        MLAS    R11, R1, R2, R1
        MULS    R12, R2, R2
        CMP     R3, R4
        MULGT   R8, R3, R3
        MULLE   R8, R4, R4
        MLANE   R6, R4, R4, R6
        MLAEQS  R6, R4, R4, R6
        MUL     R3, R3, R3
        MLA     R4, R4, R4, R4
        MUL     LR, SP, R1
"""


def test_mul_and_mla_agree_and_keep_c_and_v(build):
    traces = run_steps(build, MULTIPLIES)
    multiplies = [t for t in traces if t.kind == MULTIPLY]
    assert len(multiplies) == 14
    assert only(traces, "MUL R0, R3, R4").values["ALUResult"] == 21
    mla = only(traces, "MLA R6, R3, R4, R0")
    assert mla.values["RD4"] == 21 and mla.values["ALUResult"] == 42 and mla.values["A4"] == 0
    zero = only(traces, "MULS R10, R9, R1")
    assert zero.new_flags == 0b0111                 # Z written, C and V kept
    assert only(traces, "MULLE R8, R4, R4").signals["CondEx"] == "0"
    assert only(traces, "MUL R3, R3, R3").values["WD3"] == 49   # Rd may be a source


SHIFTS_BY_REGISTER = """        LDR     R1, =0x80000001
        LDR     R2, =0x12345678
        MOV     R5, #0x100
"""


@pytest.mark.parametrize("amount", [0, 1, 31, 32, 33, 255, 0x100, 0x120])
@pytest.mark.parametrize("operation", ["MOVS R0, R1", "ADDS R0, R2, R1", "ANDS R0, R2, R1",
                                       "TEQ R2, R1", "RSCS R0, R2, R1", "MVN R0, R1"])
def test_shifts_by_a_register_agree(build, amount, operation):
    """Every kind of shift by every interesting amount (RD4[7:0]: 0x100 and 0x120 are 0 and 32
    there), with C set and clear before it, for a logical and an arithmetic operation."""
    body = "".join(f"""        MSR     CPSR_f, #{flags}
        {operation}, {kind} R3
""" for kind in ("LSL", "LSR", "ASR", "ROR") for flags in (0, 0x20000000))
    traces = run_steps(build, SHIFTS_BY_REGISTER + f"        LDR     R3, ={amount}\n" + body)
    shifted = [t for t in traces if t.signals.get("ShiftReg") == "1"]
    assert len(shifted) == 8
    assert all(t.signals["Shift"] == "1" for t in shifted)   # the decoder cannot see Rs


def test_adc_sbc_rsc_and_teq_agree(build):
    traces = run_steps(build, SET_UP + """\
        MSR     CPSR_f, #0x20000000
        ADCS    R0, R1, R2
        ADC     R6, R3, #1
        SBCS    R7, R4, R5
        SBC     R8, R2, R1, LSL #4
        RSCS    R9, R4, #3
        RSC     R10, R1, R2, ROR R4
        MSR     CPSR_f, #0
        ADCS    R0, R3, R3
        SBCS    R7, R5, R4
        RSCS    R9, R5, R4
        TEQ     R1, R1
        TEQ     R3, #0x80000000
        TEQ     R2, R1, LSL R4
        ADCNES  R11, R1, R1
""")
    carried = [t for t in traces if t.values.get("CarryIn") is not None]
    assert len(carried) == 10 and {t.values["CarryIn"] for t in carried} == {0, 1}
    teq = [t for t in traces if t.text.startswith("TEQ")]
    assert len(teq) == 3 and all(t.values["A3"] is None for t in teq)


def test_blx_and_nop_agree_and_blx_returns_with_bx_lr(build):
    traces = run_steps(build, """\
        MOV     R0, #1
        ADR     R3, leaf
        BLX     R3
        NOP
        CMP     R0, #2
        NOPEQ
        ADR     R4, after
        BLXNE   R4
        BLXEQ   R4
        MOV     R0, #9
after:  B       finish
leaf:   ADD     R0, R0, #1
        BX      LR
finish:
""")
    blx = only(traces, "BLX R3")
    assert blx.values["A3"] == 14 and blx.values["WD3"] == blx.pc + 4
    assert any(t.text == "BX LR" and t.values["PC'"] == blx.pc + 4 for t in traces)
    assert len([t for t in traces if t.kind == NO_OPERATION]) == 2
    assert only(traces, "BLXNE R4").signals["RegWrite"] == "0"     # its condition fails
    assert not any(t.text == "MOV R0, #9" for t in traces)


HALVES = """\
        LDR     R1, =table
        MOV     R2, #6
        MOVW    R3, #0x8001
        MOVT    R3, #0xFFFE
        MOVW    R4, #0xFFFF
        CMP     R2, #6
        MOVTEQ  R4, #0x1234
        MOVTNE  R4, #0x5555
        STRH    R3, [R1]
        STRH    R3, [R1, #2]!
        STRH    R4, [R1], #4
        STRH    R3, [R1, R2]
        STRH    R4, [R1, -R2]!
        STRH    R3, [R1], R2
        LDRH    R5, [R1]
        LDRH    R5, [R1, #-2]
        LDRH    R6, [R1, #4]!
        LDRH    R6, [R1], #-4
        LDRH    R7, [R1, R2]
        LDRH    R7, [R1, -R2]!
        LDRH    R8, [R1], R2
        LDRSB   R9, [R1, #1]
        LDRSB   R9, [R1], #-1
        LDRSB   R10, [R1, R2]!
        LDRSB   R10, [R1, -R2]
        LDRSH   R11, [R1]
        LDRSH   R11, [R1, #-6]!
        LDRSH   R12, [R1], R2
        LDRSH   R12, [R1, -R2]
        LDRNEH  R0, [R1]
        STREQH  R3, [R1, #-2]
        LDREQSB R0, [R1, #-1]!
        LDRH    R0, [PC, #4]
        B       finish
        .word   0x11112222
        .word   0x87654321
finish:
        .data
        .space  64
table:  .hword  0x7FFF, 0x8000, 0x00FF, 0xFF80, 0x0102, 0x0304, 0x0506, 0x0708
        .space  64
"""


def test_movw_movt_and_every_halfword_transfer_agree(build):
    traces = run_steps(build, HALVES)
    moves = [t for t in traces if t.kind == MOVE_16]
    assert len(moves) == 5 and only(traces, "MOVT R3, #0xFFFE").values["WD3"] == 0xFFFE8001
    assert only(traces, "MOVTEQ R4, #0x1234").values["WD3"] == 0x1234FFFF
    assert only(traces, "MOVTNE R4, #0x5555").signals["RegWrite"] == "0"
    halves = [t for t in traces if t.kind in HALF_KINDS]
    assert len(halves) == 25
    assert {t.text.split()[0] for t in halves} >= {"LDRH", "STRH", "LDRSB", "LDRSH"}
    assert {(t.signals["AdrSrc"], t.signals["BaseWrite"]) for t in halves} == {
        ("0", "0"), ("0", "1"), ("1", "1")}         # offset, write-back and post-indexing
    assert only(traces, "LDRSB R9, [R1], #-1").values["ReadData"] == 0xFFFFFF80   # 0x80, signed
    assert only(traces, "LDRSB R9, [R1, #1]").values["WD3"] == 0xFFFFFFFF
    odd = only(traces, "LDRSH R11, [R1, #-6]!")     # at an odd address: 0x00, then 0x80
    assert odd.values["Address"] & 1 and odd.values["ReadData"] == 0xFFFF8000
    assert only(traces, "LDRH R5, [R1]").values["ReadData"] == 0xFF80       # zeros above
    literal = only(traces, "LDRH R0, [PC, #4]")
    assert literal.values["ReadData"] == 0x4321 and literal.values["RD1"] == literal.pc + 8


def test_ldr_pc_literal_pool_and_adr_agree(build):
    traces = run_steps(build, """\
        LDR     R0, =0xDEADBEEF
        LDR     R1, =there
        LDR     PC, [PC, #-4]
        .word   there
        MOV     R2, #1
there:  ADR     R3, there
        ADR     R4, later
        ADD     R5, PC, #8
        ADD     R6, R5, PC
        MOV     R7, PC
        LDR     R8, [PC]
        ADD     PC, PC, #0
        NOP
        LDR     R9, value
        B       finish
later:  .word   7
value:  .word   0x13572468
finish:
""")
    t = next(t for t in traces if t.text.startswith("LDR PC"))
    assert t.signals["PCSrc"] == "1" and t.signals["RegWrite"] == "1"
    assert t.values["PC'"] == t.values["ReadData"] == t.values["Result"]
    t = next(t for t in traces if t.text.startswith("LDR R0, [PC"))
    assert t.values["ReadData"] == 0xDEADBEEF and t.values["RD1"] == t.pc + 8
    assert not any(t.text == "MOV R2, #1" for t in traces)


def test_a_load_from_the_jtag_uart_takes_the_value_that_ran(build):
    """Reading the device again would lose a character: the trace uses the register after."""
    machine = Machine(build(HEADER + """\
        LDR     R1, =0xFF201000
        LDR     R0, [R1]
        LDR     R2, [R1]
""" + END))
    machine.console.feed("AB")
    traces = list(stepped(machine))
    first = [t for t in traces if t.text == "LDR R0, [R1]"][0]
    second = [t for t in traces if t.text == "LDR R2, [R1]"][0]
    assert first.values["ReadData"] & 0xFF == ord("A")
    assert second.values["ReadData"] & 0xFF == ord("B")


def test_a_look_ahead_never_reads_a_device(build):
    machine = Machine(build(HEADER + """\
        LDR     R1, =0xFF201000
        LDR     R0, [R1]
""" + END))
    machine.console.feed("AB")
    machine.step()
    t = upcoming(machine)
    assert t.text == "LDR R0, [R1]" and t.values["ReadData"] is None
    assert t.values["ALUResult"] == 0xFF201000
    machine.step()
    assert machine.reg(0) & 0xFF == ord("A")


def test_a_look_ahead_reads_memory_as_it_is(build):
    machine = Machine(build(HEADER + """\
        LDR     R1, =value
        LDR     R0, [R1]
        B       .
value:  .word   0x1234
"""))
    machine.step()
    assert upcoming(machine).values["ReadData"] == 0x1234


def test_a_store_over_itself_shows_the_instruction_that_ran(build):
    machine = Machine(build(HEADER + """\
        MOV     R0, #0
        LDR     R1, =here
here:   STR     R0, [R1]
""" + END))
    machine.step()
    machine.step()
    before = machine.uc.reg_read_batch(SNAPSHOT_REGISTERS)
    machine.step()
    t = agree(machine, machine.history[-1], before)
    assert t.text == "STR R0, [R1]" and t.values["WriteData"] == 0


def data_fields(cmd, rn, rd, rng):
    """S, Rn and Rd of a data-processing word: the fields a comparison or move has not are 0."""
    compares, moves = cmd in (8, 9, 10, 11), cmd in (13, 15)
    return 1 if compares else rng.randrange(2), 0 if moves else rn, 0 if compares else rd


def multiple_word(rng, cond=14 << 28, base=12, pc=False):
    """An LDM or STM word of the datapath with random fields: any of P, U, W and L, and a list
    that the datapath can run (see xray.outside_note()); an LDM loads the PC only with pc."""
    pre, up, write_back, load = (rng.randrange(2) for _ in range(4))
    registers = rng.getrandbits(16) & rng.choice([0xFFFF, 0x7FFF, 0x00FF, 0x4FF0, 0x800F])
    if write_back or (load and registers >> base + 1):
        registers &= ~(1 << base)       # write-back to the base, or the base loaded too soon
    if load and (not pc or (write_back and not up)):
        registers &= 0x7FFF             # counting down with write-back, the PC would come first
    registers = registers or 1 << rng.choice([0, 3, 7, 14])
    return (cond | 4 << 25 | pre << 24 | up << 23 | write_back << 21 | load << 20 | base << 16
            | registers)


def multiply_word(rng, cond=14 << 28):
    """A MUL or MLA word with random registers (never the PC), with S or not."""
    accumulate, s = rng.randrange(2), rng.randrange(2)
    rd, ra, rs, rm = (rng.randrange(15) for _ in range(4))
    return (cond | accumulate << 21 | s << 20 | rd << 16 | (ra if accumulate else 0) << 12
            | rs << 8 | 0x90 | rm)


def move_16_word(rng, cond=14 << 28):
    """A MOVW or MOVT word with any immediate and any register but the PC."""
    return (cond | 0x03000000 | rng.randrange(2) << 22 | rng.randrange(16) << 16
            | rng.randrange(15) << 12 | rng.randrange(4096))


HALF_BITS = {"LDRH": (1, 0, 1), "STRH": (0, 0, 1), "LDRSB": (1, 1, 0), "LDRSH": (1, 1, 1)}  # L S H


def half_word(rng, cond=14 << 28):
    """An LDRH, STRH, LDRSB or LDRSH word in any form: an immediate offset (imm4H and imm4L) or a
    register one (R11), up or down, pre-indexed with or without ! or post-indexed; the base, R12,
    and every address stay in DDR3."""
    load, signed, half = HALF_BITS[rng.choice(list(HALF_BITS))]
    pre, write_back = rng.choice([(1, 0), (1, 1), (0, 0)])
    rt = rng.randrange(13)
    if (write_back or not pre) and rt == 12:
        rt = 0                          # write-back to the register moved is UNPREDICTABLE
    immediate = rng.randrange(2)
    offset = rng.randrange(256)
    low = (offset >> 4 << 8 | offset & 0xF) if immediate else 11
    return (cond | pre << 24 | rng.randrange(2) << 23 | immediate << 22 | write_back << 21
            | load << 20 | 12 << 16 | rt << 12 | 0x90 | signed << 6 | half << 5 | low)


def word_kind(word):
    """The kind of a generated word, for counting: the new kinds by name, else "other". MOVW,
    MOVT and the halfword transfers come first: their bits 24:20 would read as a cmd."""
    if word & 0x0FB00000 == 0x03000000:
        return "movt" if word >> 22 & 1 else "movw"
    if word & 0x0E000090 == 0x00000090 and word & 0x60:
        bits = (word >> 20 & 1, word >> 6 & 1, word >> 5 & 1)
        name = next(name for name, value in HALF_BITS.items() if value == bits).lower()
        index = "post-indexed" if not word >> 24 & 1 else "write-back" if word >> 21 & 1 \
            else "offset"
        return f"{name} {'immediate' if word >> 22 & 1 else 'register'} {index}"
    if word & 0x0FC000F0 == 0x00000090:
        return "multiply-accumulate" if word >> 21 & 1 else "multiply"
    if word >> 25 & 7 == 0b100:
        return "store multiple" if not word >> 20 & 1 else "load multiple"
    if word >> 26 & 3 == 1:
        if not word >> 24 & 1:
            return "post-indexed"
        if word >> 21 & 1:
            return "write-back"
    if word & 0x0FFFFFF0 == 0x012FFF30:
        return "blx"
    if word & 0x0FFFFFFF == 0x0320F000:
        return "nop"
    if word >> 26 & 3 == 0 and not word >> 25 & 1 and word & 0x90 == 0x10:
        return "shift by register"
    if word >> 26 & 3 == 0 and word >> 21 & 0xF in (5, 6, 7):
        return "carry"
    if word >> 26 & 3 == 0 and word >> 21 & 0xF == 9 and word >> 20 & 1:
        return "teq"
    return "other"


# How many of WORDS generated words each new kind must have at least (a share of the expected):
# every halfword transfer in each form, an immediate or a register offset, without write-back,
# with ! or post-indexed.
WORDS = 4000
KIND_FLOORS = {"load multiple": 200, "store multiple": 200, "post-indexed": 120,
               "write-back": 120, "multiply": 150, "multiply-accumulate": 150,
               "shift by register": 90, "carry": 100, "teq": 25, "blx": 12, "nop": 30,
               "movw": 150, "movt": 150}
KIND_FLOORS.update((f"{name} {form} {index}", 10) for name in ("ldrh", "strh", "ldrsb", "ldrsh")
                   for form in ("immediate", "register")
                   for index in ("offset", "write-back", "post-indexed"))


def inside_word(rng):
    """A word of a class of the datapath, with random fields."""
    cond = rng.choice([14, 14, 14, rng.randrange(15)]) << 28
    kind = rng.randrange(8)
    if kind == 4:                       # LDM, STM, PUSH, POP: a base that stays in DDR3
        return multiple_word(rng, cond)
    if kind == 5:                       # MUL, MLA
        return multiply_word(rng, cond)
    if kind == 6:                       # MOVW, MOVT
        return move_16_word(rng, cond)
    if kind == 7:                       # LDRH, STRH, LDRSB, LDRSH
        return half_word(rng, cond)
    rn, rd, rm = rng.randrange(13), rng.randrange(13), rng.randrange(13)
    if kind == 0:                       # data processing, register
        if rng.randrange(8) == 0:       # BX or BLX R11: R11 holds an address of the code
            return cond | rng.choice([0x012FFF10, 0x012FFF30]) | 11
        cmd = rng.randrange(16)
        s, rn, rd = data_fields(cmd, rn, rd, rng)
        if rng.randrange(3) == 0:       # shifted by a register: Rs in 11:8
            return (cond | cmd << 21 | s << 20 | rn << 16 | rd << 12 | rng.randrange(13) << 8
                    | rng.randrange(4) << 5 | 1 << 4 | rm)
        return (cond | cmd << 21 | s << 20 | rn << 16 | rd << 12 | rng.randrange(32) << 7
                | rng.randrange(4) << 5 | rm)
    if kind == 1:                       # data processing, immediate
        if rng.randrange(8) == 0:       # NOP, a hint in the space of TEQ without S
            return cond | 0x0320F000
        cmd = rng.randrange(16)
        s, rn, rd = data_fields(cmd, rn, rd, rng)
        return cond | 1 << 25 | cmd << 21 | s << 20 | rn << 16 | rd << 12 | rng.randrange(4096)
    rn = 12                             # memory: a base and an offset that stay in DDR3
    pre, write_back = rng.choice([(1, 0), (1, 0), (1, 1), (0, 0)])  # offset, !, post-indexed
    if (write_back or not pre) and rd == rn:
        rd = 0                          # write-back to the register moved is UNPREDICTABLE
    index = pre << 24 | write_back << 21
    if kind == 2:                       # immediate offset
        return (cond | 1 << 26 | index | rng.randrange(2) << 23 | rng.randrange(2) << 22
                | rng.randrange(2) << 20 | rn << 16 | rd << 12 | rng.randrange(4096))
    return (cond | 3 << 25 | index | rng.randrange(2) << 23 | rng.randrange(2) << 22
            | rng.randrange(2) << 20 | rn << 16 | rd << 12 | rng.randrange(4) << 7
            | rng.randrange(3) << 5 | 11)


def test_random_jumps_of_bx_agree_with_the_machine(build):
    """Any register, condition and flags: a word and a target each time at new places."""
    rng = random.Random(0xB0B)
    machine = Machine(build(HEADER + END))
    address = 0x200000
    for _ in range(500):
        rm = rng.randrange(16)
        word = rng.randrange(15) << 28 | 0x012FFF10 | rm
        target = address + 0x10 + 4 * rng.randrange(4)
        machine.write_memory(address, struct.pack("<I", word))
        machine.write_memory(target, struct.pack("<I", 0xE1A00000))
        for n in range(13):
            machine.set_reg(n, rng.getrandbits(32))
        machine.set_reg(14, rng.getrandbits(32))
        if rm != 15:
            machine.set_reg(rm, target)
        machine.uc.reg_write(SNAPSHOT_REGISTERS[0], rng.randrange(16) << 28 | 0x1D3)
        machine.set_reg(15, address)
        before = machine.uc.reg_read_batch(SNAPSHOT_REGISTERS)
        machine.step()
        assert machine.stop_reason is None, machine.error
        t = agree(machine, machine.history[-1], before)
        assert t.kind == BRANCH_EXCHANGE and t.values["RA2"] == rm
        machine.history.clear()
        address += 0x40


def test_random_ldm_and_stm_words_agree_with_the_machine_pass_by_pass(build):
    """Any of the forms, with the PC in the list or not, any condition and flags."""
    rng = random.Random(0x1D5)
    machine = Machine(build(HEADER + END))
    machine.read_memory(0, 4)
    address = 0x200000
    checked = 0
    for _ in range(1500):
        word = multiple_word(rng, rng.choice([14, rng.randrange(15)]) << 28, rng.choice([11, 12]),
                             pc=True)
        assert outside_note(word) == ""
        machine.write_memory(address, struct.pack("<I", word))
        machine.write_memory(address + 4, struct.pack("<I", 0xE1A00000))
        for n in range(11):
            machine.set_reg(n, rng.getrandbits(32))
        machine.set_reg(11, 0x300000 + rng.randrange(0x100) * 4)
        machine.set_reg(12, 0x301000 + rng.randrange(0x100) * 4)
        machine.set_reg(14, 0x200000 + rng.randrange(0x100) * 4)
        for base in (11, 12):           # what an LDM of the PC loads: the address of a NOP
            start = machine.reg(base) - 64
            machine.write_memory(start, struct.pack("<33I", *[address + 4] * 33))
        machine.uc.reg_write(SNAPSHOT_REGISTERS[0], rng.randrange(16) << 28 | 0x1D3)
        machine.set_reg(15, address)
        before = machine.uc.reg_read_batch(SNAPSHOT_REGISTERS)
        machine.step()
        assert machine.stop_reason is None, machine.error
        t = agree(machine, machine.history[-1], before)
        assert t.passes and t.kind in (LOAD_MULTIPLE, STORE_MULTIPLE)
        checked += 1
        machine.history.clear()
        address += 8
    assert checked == 1500


def test_random_words_of_the_datapath_agree_with_the_machine(build):
    """Random operands and flags: each word, written over the next free place, runs once."""
    rng = random.Random(0x5EED)
    machine = Machine(build(HEADER + END))
    machine.read_memory(0, 4)
    address = 0x200000
    machine.write_memory(address, bytes(4))
    interesting = [0, 1, 2, 31, 32, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0x80000001, 0xFF]
    checked = 0
    kinds = {}
    for _ in range(WORDS):
        word = inside_word(rng)
        kinds[word_kind(word)] = kinds.get(word_kind(word), 0) + 1
        assert outside_note(word) == ""
        machine.write_memory(address, struct.pack("<I", word))
        for n in range(11):
            machine.set_reg(n, rng.choice(interesting + [rng.getrandbits(32)]))
        # R11: an address of the code where BX and BLX R11 may go (but not the end of the code)
        machine.set_reg(11, rng.randrange(0x40, 0x100) * 4)
        machine.set_reg(12, 0x300000 + rng.randrange(0x1000) * 4)
        machine.uc.reg_write(SNAPSHOT_REGISTERS[0], rng.randrange(16) << 28 | 0x1D3)
        machine.set_reg(15, address)
        before = machine.uc.reg_read_batch(SNAPSHOT_REGISTERS)
        machine.step()
        assert machine.stop_reason is None, machine.error
        agree(machine, machine.history[-1], before)
        checked += 1
        machine.history.clear()
        address += 8
    assert checked == WORDS
    for kind, least in KIND_FLOORS.items():     # no kind drops out of the generated words
        assert kinds.get(kind, 0) >= least, (kind, kinds)


def sweep_sources():
    """The programs that do not need input, of the tests and the examples."""
    found = [path for path in sorted(PROGRAMS.glob("*.s"))
             if not path.with_suffix(".in").exists()]
    found += [path for path in sorted((ROOT / "examples").glob("*.s"))
              if path.name not in ("keyboard_echo.s",)]
    return found


@pytest.mark.parametrize("path", sweep_sources(), ids=lambda path: path.name)
def test_every_step_of_the_programs_agrees(tmp_path, path):
    result = assemble(Path(path).read_text(), tmp_path)
    if not result.ok:
        pytest.skip("written in lower case on purpose")
    machine = Machine(Program(result.elf_path), base_dir=tmp_path)
    inside = outside = 0
    for t in stepped(machine, limit=4000):
        if t.note:
            outside += 1
        else:
            inside += 1
    machine.close()
    assert inside + outside > 0
    assert inside > 0 or path.name == "float_bits.s"


# What an instruction outside did ---------------------------------------------------------

def test_changes_lists_registers_and_memory(build):
    machine = Machine(build(HEADER + """\
        MOV     R0, #5
        MOV     R1, #6
        LDR     SP, =0x4000
        PUSH    {R0, R1}
        POP     {R2, R3}
        MUL     R4, R0, R1
""" + END))
    for _ in range(3):
        machine.step()
    machine.step()
    lines = changes(machine, machine.history[-1])
    assert "SP 0x00004000 -> 0x00003ff8" in lines
    assert "Memory 0x00003ff8: 0x00000000 -> 0x00000005" in lines
    assert "Memory 0x00003ffc: 0x00000000 -> 0x00000006" in lines
    assert not any(line.startswith("PC") for line in lines)
    machine.step()
    lines = changes(machine, machine.history[-1])
    assert lines == ["R2 0x00000000 -> 0x00000005", "R3 0x00000000 -> 0x00000006",
                     "SP 0x00003ff8 -> 0x00004000"]


def test_changes_shows_a_jump_and_new_flags(build):
    machine = Machine(build(HEADER + """\
        ADR     R0, there
        BX      R0
        NOP
there:  MSR     CPSR_f, #0xF0000000
""" + END))
    machine.step()
    machine.step()
    assert changes(machine, machine.history[-1]) == ["PC 0x00000004 -> 0x0000000c"]
    machine.step()
    assert changes(machine, machine.history[-1]) == ["CPSR 0x000001d3 -> 0xf00001d3"]


def test_changes_of_an_instruction_that_changed_nothing(build):
    machine = Machine(build(HEADER + "        NOP\n" + END))
    machine.step()
    assert changes(machine, machine.history[-1]) == []


def test_changes_lists_every_word_written_also_over_the_same_value(build):
    machine = Machine(build(HEADER + """\
        LDR     SP, =0x4000
        MOV     R5, #7
        PUSH    {R0, R1}
        STR     R5, [SP]
        STR     R5, [SP]
        STRB    R0, [SP, #4]
""" + END))
    for _ in range(3):
        machine.step()
    lines = changes(machine, machine.history[-1])       # zeros over zeros: both words
    assert sorted(lines) == ["Memory 0x00003ff8: 0x00000000 -> 0x00000000",
                             "Memory 0x00003ffc: 0x00000000 -> 0x00000000",
                             "SP 0x00004000 -> 0x00003ff8"]
    machine.step()
    assert changes(machine, machine.history[-1]) == ["Memory 0x00003ff8: 0x00000000 -> 0x00000007"]
    machine.step()                                      # the same value again
    assert changes(machine, machine.history[-1]) == ["Memory 0x00003ff8: 0x00000007 -> 0x00000007"]
    machine.step()
    assert changes(machine, machine.history[-1]) == ["Memory 0x00003ffc: 0x00 -> 0x00"]


def test_changes_lists_a_word_written_twice_once(build):
    machine = Machine(build(HEADER + "        NOP\n" + END))
    machine.write_memory(0x4000, bytes([1, 2, 3, 4]))
    machine.step()
    change = machine.history[-1]
    change.writes += [(0x4000, bytes([9, 9, 9, 9])), (0x4000, bytes([8, 8, 8, 8]))]
    assert changes(machine, change) == ["Memory 0x00004000: 0x09090909 -> 0x04030201"]


# The model: which instruction it shows ---------------------------------------------------

STEPS = HEADER + """\
        MOV     R0, #1
        MOV     R1, #2
        ADD     R2, R0, R1
""" + END


def connected(machine):
    model = XRayModel()
    model.connect(machine)
    return model


def test_at_the_start_nothing_has_run_and_the_next_instruction_is_named(build):
    model = connected(Machine(build(STEPS)))
    assert model.view.kind == NOTHING and model.view.trace is None
    assert model.view.heading == "Nothing has run yet" and model.next == (0, "MOV R0, #1")
    assert not model.update()           # nothing happened


def test_after_a_run_that_kept_no_history_it_shows_the_instruction_at_pc_as_next(build):
    machine = Machine(build(STEPS))
    model = connected(machine)
    machine.step()
    model.update()
    machine.history.clear()             # as a run that records nothing leaves it
    machine.step()
    machine.history.clear()
    assert model.update()
    assert model.view.kind == NEXT and model.view.trace.pc == machine.pc


def test_after_step_it_shows_the_instruction_executed_from_before(build):
    machine = Machine(build(STEPS))
    model = connected(machine)
    machine.step()
    assert model.update()
    assert model.view.kind == EXECUTED and model.view.trace.text == "MOV R0, #1"
    machine.step()
    machine.step()
    assert model.update()
    trace_shown = model.view.trace
    assert trace_shown.text == "ADD R2, R0, R1" and trace_shown.values["RD1"] == 1
    assert not model.update()


def test_after_backstep_it_shows_the_instruction_before_finished_or_nothing(build):
    machine = Machine(build(HEADER + """\
        MOV     R0, #20
        MOV     R1, #20
""" + END))
    model = connected(machine)
    machine.step()
    machine.step()
    model.update()
    machine.backstep()                  # as before the second Step: MOV R0, #20 has run
    assert model.update()
    view = model.view
    assert view.kind == EXECUTED and view.trace.text == "MOV R0, #0x14"
    assert view.heading == "Just executed" and not view.ended and model.undone
    assert view.did == ("R0 0x00000000 -> 0x00000014",)
    assert model.next == (4, "MOV R1, #0x14") and model.change is machine.history[-1]
    assert model.flags == (0, 0)
    machine.backstep()                  # as before the first Step: nothing has run
    assert model.update()
    assert model.view.kind == NOTHING and model.view.trace is None
    assert model.view.heading == "Nothing has run yet"
    assert model.next == (0, "MOV R0, #0x14")
    assert model.next == (0, "MOV R0, #0x14") and model.change is None and model.flags is None
    machine.step()                      # a Step after Backsteps: as any Step
    assert model.update() and not model.undone
    assert model.view.kind == EXECUTED and model.view.trace.text == "MOV R0, #0x14"


def test_after_backstep_a_push_shows_finished_with_its_last_pass(build):
    machine = Machine(build(HEADER + """\
        LDR     SP, =0x4000
        MOV     R4, #4
        PUSH    {R4, LR}
        MOV     R0, #1
""" + END))
    model = connected(machine)
    for _ in range(4):
        machine.step()
    model.update()
    machine.backstep()
    assert model.update()
    shown = model.view.trace
    assert model.view.kind == EXECUTED and shown.kind == STORE_MULTIPLE
    assert len(shown.passes) == 2 and shown.number == 2 and shown.count == 2
    assert "SP 0x00004000 -> 0x00003ff8" in model.view.did
    assert "Memory 0x00003ff8: 0x00000000 -> 0x00000004" in model.view.did


def test_after_backstep_an_svc_and_a_branch_show_finished(build):
    machine = Machine(build(HEADER + """\
        MOV     R0, #25
        SVC     #1
        B       there
        NOP
there:  MOV     R2, #3
""" + END))
    model = connected(machine)
    for _ in range(4):
        machine.step()
    model.update()
    machine.backstep()                  # MOV R2 undone: the branch ran last
    assert model.update()
    assert model.view.kind == EXECUTED and model.view.trace.kind == BRANCH
    assert model.view.trace.values["PC'"] == 0x10 and model.next[0] == 0x10
    machine.backstep()                  # the branch undone: the SVC ran last
    assert model.update()
    assert model.view.kind == EXECUTED and model.view.trace.kind == SYSTEM_CALL
    assert model.view.heading == "Just executed" and model.next == (8, "B #0x10")


def test_after_backstep_from_the_end_the_program_has_not_ended(build):
    machine = Machine(build(HEADER + "        MOV R0, #1\n        SVC #10\n"))
    model = connected(machine)
    machine.step()
    machine.step()
    model.update()
    assert model.view.ended
    machine.backstep()
    assert model.update()
    assert model.view.kind == EXECUTED and model.view.trace.text == "MOV R0, #1"
    assert model.view.heading == "Just executed" and not model.view.ended
    assert model.next == (4, "SVC #0xA")


def test_after_a_run_that_kept_its_history_backstep_shows_each_instruction_before(make_runner):
    runner = make_runner(STEPS, record_while_running=True)
    machine = runner.machine
    model = connected(machine)
    machine.set_breakpoint(8)
    runner.run()
    model.update()
    assert model.view.trace.text == "MOV R1, #2"
    runner.backstep()
    assert model.update()
    assert model.view.kind == EXECUTED and model.view.trace.text == "MOV R0, #1"
    runner.backstep()
    assert model.update() and model.view.kind == NOTHING


def test_after_a_run_without_history_a_backstep_to_its_end_shows_nothing(make_runner):
    runner = make_runner(STEPS)
    machine = runner.machine
    model = connected(machine)
    machine.set_breakpoint(4)
    runner.run()                        # MOV R0 ran unrecorded
    model.update()
    assert model.view.kind == NEXT and model.view.trace.text == "MOV R1, #2"
    runner.step()
    model.update()
    runner.backstep()
    assert model.update()
    assert model.view.kind == NOTHING and model.view.trace is None


def test_after_a_run_stops_it_shows_the_instruction_at_pc(build):
    machine = Machine(build(HEADER + """\
        MOV     R0, #1
stop:   MOV     R1, #2
""" + END))
    model = connected(machine)
    machine.set_breakpoint(4)
    while not machine.at_breakpoint and machine.stop_reason is None:
        machine.run_slice()
    assert model.update()
    assert model.view.kind == NEXT and model.view.trace.text == "MOV R1, #2"


def test_with_history_kept_a_stop_shows_the_last_instruction_executed(make_runner):
    runner = make_runner(HEADER + """\
        MOV     R0, #1
        MOV     R1, #2
stop:   MOV     R2, #3
""" + END, record_while_running=True)
    machine = runner.machine
    model = connected(machine)
    machine.set_breakpoint(8)
    runner.run()
    assert runner.state is State.PAUSED
    assert model.update()
    assert model.view.kind == EXECUTED and model.view.trace.text == "MOV R1, #2"


def test_a_slow_run_shows_each_instruction_as_step_does(make_runner):
    runner = make_runner(STEPS)
    model = connected(runner.machine)
    runner.go(slow=True)
    runner.run_slice()
    assert model.update() and model.view.kind == EXECUTED
    assert model.view.trace.text == "MOV R0, #1"
    runner.run_slice()
    assert model.update() and model.view.trace.text == "MOV R1, #2"


def test_a_register_changed_by_hand_shows_when_the_instruction_runs(build):
    machine = Machine(build(STEPS.replace("MOV     R0, #1", "ADD     R0, R3, #1")))
    model = connected(machine)
    machine.set_reg(3, 9)
    model.update()
    assert model.view.kind == NOTHING   # still nothing has run
    machine.step()
    assert model.update()
    assert model.view.trace.values["RD1"] == 9


def test_a_register_changed_by_hand_leaves_what_was_executed(build):
    machine = Machine(build(STEPS))
    model = connected(machine)
    machine.step()
    model.update()
    machine.set_reg(3, 9)
    assert not model.update()
    assert model.view.kind == EXECUTED


def test_the_last_instruction_says_the_program_ended(build):
    machine = Machine(build(HEADER + "        MOV R0, #1\n        SVC #10\n"))
    model = connected(machine)
    machine.step()
    machine.step()
    assert machine.stop_reason is StopReason.EXIT
    assert model.update()
    assert model.view.kind == EXECUTED and model.view.ended
    assert "ended" in model.view.heading and model.view.trace.text == "SVC #0xA"
    assert model.view.did == ()         # the service changed nothing


def test_a_program_that_ended_at_full_speed_says_so(build):
    machine = Machine(build(STEPS))
    model = connected(machine)
    machine.run(time_limit=10)
    assert model.update()
    assert model.view.kind == ENDED and model.view.trace is None
    assert "ended" in model.view.heading


def test_a_stop_ends_the_program_too(make_runner):
    runner = make_runner(STEPS)
    machine = runner.machine
    model = connected(machine)
    runner.step()
    model.update()
    runner.stop()
    model.stopped = runner.state is State.FINISHED
    assert model.update()
    assert model.view.kind == ENDED


def test_a_failing_instruction_is_shown_with_its_error(build):
    machine = Machine(build(HEADER + """\
        LDR     R1, =0x50000000
        LDR     R0, [R1]
""" + END))
    model = connected(machine)
    machine.step()
    model.update()
    machine.step()
    assert machine.stop_reason is StopReason.ERROR
    assert model.update()
    view = model.view
    assert view.kind == FAILED and view.trace.text == "LDR R0, [R1]"
    assert "out of range" in view.heading
    assert view.trace.values["ALUResult"] == 0x50000000 and view.trace.values["ReadData"] is None


def test_a_jump_to_no_code_says_so_without_a_trace(build):
    machine = Machine(build(HEADER + """\
        LDR     R1, =0xFF200000
        MOV     PC, R1
""" + END))
    model = connected(machine)
    machine.step()
    machine.step()
    machine.step()
    assert machine.stop_reason is StopReason.ERROR
    assert model.update()
    assert model.view.kind == FAILED and model.view.trace is None
    assert "no program code" in model.view.heading


def test_outside_it_says_what_the_instruction_did(build):
    machine = Machine(build(HEADER + """\
        LDR     R0, =0x1000
        MOV     R1, #6
        MOV     R2, #7
        UMULL   R3, R4, R1, R2
""" + END))
    model = connected(machine)
    for _ in range(3):
        machine.step()
    model.update()
    machine.backstep()
    machine.step()
    model.update()
    assert model.view.trace.text == "MOV R2, #7"
    machine.step()
    model.update()
    view = model.view
    assert view.trace.note and view.did == ("R3 0x00000000 -> 0x0000002a",)
    machine.backstep()                  # back to MOV R2, #7, finished, with what it did
    model.update()
    assert model.view.kind == EXECUTED and model.view.trace.text == "MOV R2, #7"
    assert model.view.did == ("R2 0x00000000 -> 0x00000007",)
    assert model.next[1] == "UMULL R3, R4, R1, R2"


def test_a_new_program_starts_again(build):
    model = connected(Machine(build(STEPS)))
    other = Machine(build(HEADER + "        MOV R5, #5\n" + END))
    model.observe(other)
    assert model.view.kind == NOTHING and model.next == (0, "MOV R5, #5")


def test_reset_of_the_program_shows_the_first_instruction_as_next(make_runner):
    runner = make_runner(STEPS)
    model = connected(runner.machine)
    runner.step()
    model.update()
    runner.reset()
    assert model.update()
    assert model.view.kind == NOTHING and model.view.heading == "Nothing has run yet"
    assert model.next == (0, "MOV R0, #1")


def test_the_tools_reset_clears_the_picture(build):
    machine = Machine(build(STEPS))
    model = connected(machine)
    machine.step()
    model.update()
    model.reset()
    assert model.view.trace is None
    assert not model.update()           # until the program does something
    machine.step()
    assert model.update() and model.view.trace.text == "MOV R1, #2"


def test_disconnected_it_keeps_what_it_shows_and_looks_at_nothing(build):
    machine = Machine(build(STEPS))
    model = connected(machine)
    machine.step()
    model.update()
    shown = model.view
    model.disconnect()
    machine.step()
    assert not model.update() and model.view is shown


# The instruction as the student wrote it -------------------------------------------------

@pytest.mark.parametrize("written, basic, line", [
    ("MOV R0, #20", "MOV R0, #0x14", "MOV R0, #20    (MOV R0, #0x14)"),
    ("BNE next", "BNE #0x24", "BNE next    (BNE #0x24)"),
    ("ADD R1, R2, R3", "ADD R1, R2, R3", "ADD R1, R2, R3"),
    ("MOV R0,#1", "MOV R0, #1", "MOV R0,#1"),               # spaces aside, the same
    ("PUSH {r4, lr}", "PUSH {R4, LR}", "PUSH {r4, lr}"),     # letter case aside, the same
    (None, "MOV R0, #0x14", "MOV R0, #0x14"),               # no source line: Basic
    ("", "NOP", "NOP"),
])
def test_the_line_is_as_written_with_the_basic_form_when_they_differ(written, basic, line):
    assert instruction_line(written, basic) == line
    assert named(written, basic) == (written or basic)


WRITTEN = HEADER + """\
        MOV     R0, #20         @ twenty
        MOV     R1, #20
        ADD     R2, R0, R1
""" + END


def written_by(source):
    """What App.written gives for the program of source: its lines without comments."""
    lines = {4 * number: " ".join(line.split("@")[0].split())
             for number, line in enumerate(source.splitlines()[2:])}
    return lambda address: lines.get(address) or None


def test_the_model_names_instructions_as_written(build):
    machine = Machine(build(WRITTEN))
    model = XRayModel()
    model.written = written_by(WRITTEN)
    model.connect(machine)
    assert model.view.kind == NOTHING and model.next == (0, "MOV R0, #20")
    machine.step()
    model.update()
    assert model.view.written == "MOV R0, #20" and model.next == (4, "MOV R1, #20")
    assert model.view.trace.text == "MOV R0, #0x14"         # the trace keeps its Basic form
    machine.backstep()
    model.update()
    assert model.view.written is None and model.view.kind == NOTHING
    assert model.next == (0, "MOV R0, #20")


def test_a_word_changed_while_running_keeps_its_basic_form(build):
    machine = Machine(build(WRITTEN))
    machine.step()
    machine.write_memory(4, struct.pack("<I", 0xE3A01005))     # MOV R1, #5 over MOV R1, #20
    model = XRayModel()
    model.written = written_by(WRITTEN)
    model.connect(machine)
    assert model.view.written == "MOV R0, #20" and model.next == (4, "MOV R1, #5")


def test_without_a_source_the_model_names_the_basic_form(build):
    machine = Machine(build(WRITTEN))
    model = connected(machine)
    assert model.next == (0, "MOV R0, #0x14")
    machine.step()
    model.update()
    assert model.view.written is None and model.view.trace.text == "MOV R0, #0x14"


# It costs nothing ------------------------------------------------------------------------

def test_no_hook_while_not_connected(build):
    machine = Machine(build(STEPS))
    hooks = len(machine.uc._callbacks)
    model = XRayModel()
    model.observe(machine)
    assert not model.update() and model.machine is None
    assert len(machine.uc._callbacks) == hooks


def test_no_hook_while_connected(build):
    machine = Machine(build(STEPS))
    hooks = len(machine.uc._callbacks)
    model = connected(machine)
    assert len(machine.uc._callbacks) == hooks
    machine.run(time_limit=10)
    model.update()
    assert len(machine.uc._callbacks) == hooks
    model.disconnect()
    assert len(machine.uc._callbacks) == hooks
    assert machine.observers.blocks is None and not machine.observers.watches_memory


@pytest.mark.parametrize("word", [0xE1010092, 0xE1410092])
def test_a_swap_has_its_own_note(word):
    assert decode(word).note == NOTE_SWAP


# A system call ---------------------------------------------------------------------------

def test_an_svc_hands_its_number_to_the_system(word_of):
    t = trace(0x1000, word_of("SVC #1"), REGISTERS, 0x1D3, no_memory)
    assert t.kind == SYSTEM_CALL and t.note == "" and t.text == "SVC #1"
    s = t.signals
    assert (s["Syscall"], s["CondEx"], s["RegWrite"], s["MemWrite"], s["PCSrc"]) == \
        ("1", "1", "0", "0", "0")
    assert s["ALUControl"] == "XXXX"
    assert t.values["SvcNum"] == 1 and t.values["PC'"] == 0x1004
    assert t.values["ALUResult"] is None and t.values["Result"] is None
    assert "System" in t.stages[1].blocks and set(t.active_blocks) <= set(BLOCKS)


def test_an_svc_whose_condition_fails_calls_nothing(word_of):
    t = trace(0x1000, word_of("SVCNE #1"), REGISTERS, 0x40000000, no_memory)
    assert t.kind == SYSTEM_CALL and t.condition == "NE: Z = 1, does not execute"
    assert t.signals["Syscall"] == "0" and t.signals["CondEx"] == "0"
    assert t.values["PC'"] == 0x1004


def test_an_svc_that_waits_for_input_shows_as_waiting(build):
    machine = Machine(build(HEADER + "        MOV R0, #1\n        SVC #5\n" + END))
    model = connected(machine)
    machine.step()
    model.update()
    machine.step()                      # the read waits for a line
    assert machine.request is not None
    assert model.update()
    view = model.view
    assert view.kind == WAITING and "Run I/O" in view.heading
    assert view.trace.kind == SYSTEM_CALL and view.trace.pc == machine.pc
    assert not model.update()           # nothing new while it waits
    machine.console.feed("42\n")
    machine.step()
    assert model.update() and model.view.kind == EXECUTED
    assert model.view.trace.kind == SYSTEM_CALL and machine.reg(0) == 42
