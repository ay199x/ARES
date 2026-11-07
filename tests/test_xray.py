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
from ares.xray import (BLOCKS, BRANCH_EXCHANGE, NOTE_OTHER, NOTE_SWAP, NOTE_THUMB, EXECUTED, FAILED,
                       NEXT, OUTSIDE, STAGES, UNDONE, ENDED, alu, changes, condition_text, decode,
                       executed, extend, outside_note, shift, trace, upcoming)

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
    ("ADD R0, R1, R2", "0 0 0 0 XX 1 00 1"),
    ("ADD R0, R1, R2, LSL #3", "0 0 0 0 XX 1 00 1"),
    ("ADD R0, R1, #1", "0 0 0 1 00 1 X0 1"),
    ("STR R0, [R1, #4]", "0 X 1 1 01 0 10 0"),
    ("STRB R0, [R1, #4]", "0 X 1 1 01 0 10 0"),
    ("LDR R0, [R1, #4]", "0 1 0 1 01 1 X0 0"),
    ("LDRB R0, [R1, #4]", "0 1 0 1 01 1 X0 0"),
    ("B there", "1 0 0 1 10 0 X1 0"),
    ("BNE there", "1 0 0 1 10 0 X1 0"),
    # The additions: a register offset takes the shifter's route, BL writes LR.
    ("LDR R0, [R1, R2]", "0 1 0 0 XX 1 00 0"),
    ("LDR R0, [R1, R2, LSL #2]", "0 1 0 0 XX 1 00 0"),
    ("STR R0, [R1, R2]", "0 X 1 0 XX 0 00 0"),
    ("STRB R0, [R1, R2, LSL #1]", "0 X 1 0 XX 0 00 0"),
    ("BL there", "1 0 0 1 10 1 X1 0"),
    # BX reads Rm on the second port, for the ALU to pass on: no register written.
    ("BX LR", "1 0 0 0 XX 0 0X 1"),
    ("BXNE R3", "1 0 0 0 XX 0 0X 1"),
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
]


@pytest.mark.parametrize("with_s, without_s, control, flags, no_write", ALU_ROWS)
def test_the_alu_decoder_gives_the_additions_table(word_of, with_s, without_s, control, flags,
                                                   no_write):
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


@pytest.mark.parametrize("source, byte", [
    ("LDR R0, [R1]", "0"), ("STR R0, [R1]", "0"), ("LDRB R0, [R1]", "1"), ("STRB R0, [R1]", "1"),
    ("LDRB R0, [R1, R2]", "1"), ("STRB R0, [R1, R2]", "1"), ("ADD R0, R1, R2", "0")])
def test_byte_marks_the_byte_accesses(word_of, source, byte):
    assert signals(word_of(source))["Byte"] == byte


@pytest.mark.parametrize("source, store_src", [
    ("STR R0, [R1, R2]", "1"), ("STRB R0, [R1, R2, LSL #1]", "1"), ("STR R0, [R1, -R2]", "1"),
    ("STR R0, [R1, #4]", "0"), ("LDR R0, [R1, R2]", "0"), ("ADD R0, R1, R2", "0")])
def test_store_src_takes_the_third_read_port_for_a_register_offset(word_of, source, store_src):
    assert signals(word_of(source))["StoreSrc"] == store_src


@pytest.mark.parametrize("source, link", [("BL there", "1"), ("BLNE there", "1"), ("B there", "0"),
                                          ("ADD R0, R1, R2", "0")])
def test_link_marks_bl(word_of, source, link):
    assert signals(word_of(source))["Link"] == link


@pytest.mark.parametrize("source, pcs", [
    ("ADD PC, R1, R2", "1"), ("MOV PC, LR", "1"), ("LDR PC, [R1]", "1"), ("B there", "1"),
    ("BL there", "1"), ("BX LR", "1"), ("BXNE R3", "1"), ("MOV R0, R1", "0"), ("LDR R0, [R1]", "0"),
    ("STR PC, [R1]", "0"),              # RegW is 0: Rd = 15 changes nothing here
])
def test_pcs_is_rd_15_with_regw_or_branch(word_of, source, pcs):
    assert signals(word_of(source))["PCS"] == pcs


# What lies outside -------------------------------------------------------------------

OUTSIDE_SOURCES = [
    "ADC R0, R1, R2", "ADCS R0, R1, #1", "SBC R0, R1, R2", "SBCS R0, R1, #1", "RSC R0, R1, R2",
    "RSCS R0, R1, #1", "TEQ R1, R2", "TEQ R1, #1",
    "ADD R0, R1, R2, LSL R3", "MOV R0, R1, ROR R2", "CMP R0, R1, LSR R2",
    "ADDS PC, R1, R2", "MOVS PC, LR", "SUBS PC, LR, #4",
    "MUL R0, R1, R2", "MLA R0, R1, R2, R3", "MLS R0, R1, R2, R3", "UMULL R0, R1, R2, R3",
    "SMULL R0, R1, R2, R3", "UMLAL R0, R1, R2, R3", "SMLAL R0, R1, R2, R3",
    "LDM R0, {R1, R2}", "STM R0, {R1, R2}", "LDMIA R0!, {R1}", "STMDB R0!, {R1}",
    "PUSH {R0, LR}", "POP {R0, PC}",
    "LDR R0, [R1, #4]!", "STR R0, [R1, #4]!", "LDR R0, [R1], #4", "STR R0, [R1], #4",
    "LDR R0, [R1, R2]!", "STR R0, [R1], R2", "LDRB R0, [R1], #1", "STRB R0, [R1, #1]!",
    "LDRT R0, [R1]", "STRT R0, [R1]", "LDRBT R0, [R1]", "STRBT R0, [R1]",
    "LDRH R0, [R1]", "LDRSB R0, [R1]", "LDRSH R0, [R1]", "STRH R0, [R1]", "LDRD R0, R1, [R2]",
    "STRD R0, R1, [R2]", "LDREX R0, [R1]", "STREX R0, R1, [R2]", "LDREXB R0, [R1]",
    "SVC #10", "BLX R0", "BXJ R0", "MOVW R0, #1", "MOVT R0, #1", "MRS R0, CPSR",
    "MSR CPSR_f, R0", "MSR CPSR_f, #0xF0000000", "CLZ R0, R1", "NOP", "YIELD", "WFE", "WFI",
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
    "BX SP", "BX PC", "BXEQ LR"])
def test_these_instructions_lie_inside_the_datapath(word_of, source):
    assert outside_note(word_of(source)) == ""
    assert decode(word_of(source)).kind != OUTSIDE


@pytest.mark.parametrize("cond", range(15))
@pytest.mark.parametrize("rm", range(16))
def test_bx_has_a_class_of_its_own_with_any_condition_and_register(cond, rm):
    assert decode(cond << 28 | 0x012FFF10 | rm).kind == BRANCH_EXCHANGE


def test_the_note_for_what_has_no_row_no_longer_names_bx():
    assert "BLX" in NOTE_OTHER and "BX" not in NOTE_OTHER.replace("BLX", "")


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
])
def test_the_alu_operations(control, a, b, value, flags):
    assert alu(control, a, b) == (value, flags)


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


@pytest.mark.parametrize("imm_src, word, expected", [
    ("00", 0xE3A000FF, 0xFF),
    ("00", 0xE3A004FF, 0xFF000000),     # rotated by 8
    ("00", 0xE3A00102, 0x80000000),     # 2 rotated by 2
    ("00", 0xE3A00F01, 4),              # 1 rotated by 30
    ("01", 0xE5910FFF, 0xFFF),
    ("01", 0xE5910004, 4),
    ("10", 0xEA000001, 4),
    ("10", 0xEAFFFFFE, 0xFFFFFFF8),
    ("10", 0xEA7FFFFF, 0x01FFFFFC),
    ("10", 0xEA800000, 0xFE000000),
])
def test_extend_gives_the_immediates(imm_src, word, expected):
    assert extend(word, imm_src) == expected


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
    t = trace(0x1000, word_of("SVCNE #1"), REGISTERS, 0x40000000, no_memory)
    assert t.note and t.kind == OUTSIDE and t.condition == "NE: Z = 1, does not execute"
    assert t.signals == {} and not t.active and not t.active_blocks and t.text == "SVCNE #1"
    t = trace(0x1000, 0xF57FF04F, REGISTERS, 0x1D3, no_memory)
    assert t.note and t.condition == ""


def test_thumb_code_lies_outside():
    t = trace(0x1000, 0xE0810002, REGISTERS, 0x1F3, no_memory)
    assert t.kind == OUTSIDE and "Thumb" in t.note


# Wires against Unicorn ---------------------------------------------------------------

def agree(machine, change, before):
    """The trace of the instruction machine just executed agrees with the machine; the trace."""
    t = executed(machine, change)
    assert t.pc == before[SNAPSHOT_PC]
    if t.note:
        return t
    now = machine.uc.reg_read_batch(SNAPSHOT_REGISTERS)
    where = f"{t.text} at 0x{t.pc:08x}"
    values, sig = t.values, t.signals
    # The next PC.
    assert values["PC'"] == machine.pc, where
    # The flags.
    assert t.new_flags == machine.cpsr >> 28, where
    thumb = 0x20 if t.to_thumb else 0
    assert machine.cpsr & 0x0FFFFFFF == before[0] & 0x0FFFFFFF | thumb, where
    # The registers: the one written has WD3, all others stay.
    written = values["A3"] if sig["RegWrite"] == "1" and values["A3"] != 15 else None
    for n in range(15):
        expected = values["WD3"] if n == written else before[2 + n]
        assert now[2 + n] == expected, (where, n)
    # The memory.
    size = 1 if sig["Byte"] == "1" else 4
    if sig["MemWrite"] == "1":
        address = values["ALUResult"]
        expected = values["WriteData"] & (0xFF if size == 1 else 0xFFFFFFFF)
        if change.writes:
            assert [(start, len(old)) for start, old in change.writes] == [(address, size)], where
            data = machine.read_memory(address, size)
            assert int.from_bytes(data, "little") == expected, where
    else:
        assert change.writes == [], where
    # A load: the value read is on the wires and what the register got.
    if sig["MemtoReg"] == "1" and sig["CondEx"] == "1":
        assert values["Result"] == values["ReadData"], where
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


@pytest.mark.parametrize("operation", ["ADD", "SUB", "AND", "ORR", "EOR", "BIC", "RSB"])
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


@pytest.mark.parametrize("operation", ["CMP", "CMN", "TST"])
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


def steps_of_a_jump(build, offset):
    """Run to a BX R0 whose address is there + offset, and just past it; its trace and the
    machine."""
    machine = Machine(build(HEADER + f"""\
        ADR     R0, there
        ADD     R0, R0, #{offset}
        BX      R0
there:  NOP
        NOP
        NOP
""" + END))
    machine.step()
    machine.step()
    assert upcoming(machine).text == "BX R0"
    before = machine.uc.reg_read_batch(SNAPSHOT_REGISTERS)
    machine.step()
    return agree(machine, machine.history[-1], before), machine


@pytest.mark.parametrize("offset, thumb", [(0, False), (1, True), (2, False), (3, True)])
def test_bx_agrees_for_every_low_address_bit(build, offset, thumb):
    """The address really reached, and the T bit: agree() compares both with the machine."""
    t, machine = steps_of_a_jump(build, offset)
    there = t.pc + 4
    assert t.values["Result"] == there + offset
    assert t.values["PC'"] == machine.pc == there + (offset & 2)
    assert t.to_thumb == thumb == bool(machine.cpsr & 0x20)


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
    compares, moves = cmd in (8, 10, 11), cmd in (13, 15)
    return 1 if compares else rng.randrange(2), 0 if moves else rn, 0 if compares else rd


def inside_word(rng):
    """A word of a class of the datapath, with random fields."""
    cond = rng.choice([14, 14, 14, rng.randrange(15)]) << 28
    kind = rng.randrange(4)
    rn, rd, rm = rng.randrange(13), rng.randrange(13), rng.randrange(13)
    if kind == 0:                       # data processing, register
        cmd = rng.choice([0, 1, 2, 3, 4, 8, 10, 11, 12, 13, 14, 15])
        s, rn, rd = data_fields(cmd, rn, rd, rng)
        return (cond | cmd << 21 | s << 20 | rn << 16 | rd << 12 | rng.randrange(32) << 7
                | rng.randrange(4) << 5 | rm)
    if kind == 1:                       # data processing, immediate
        cmd = rng.choice([0, 1, 2, 3, 4, 8, 10, 11, 12, 13, 14, 15])
        s, rn, rd = data_fields(cmd, rn, rd, rng)
        return cond | 1 << 25 | cmd << 21 | s << 20 | rn << 16 | rd << 12 | rng.randrange(4096)
    rn = 12                             # memory: a base and an offset that stay in DDR3
    if kind == 2:                       # immediate offset
        return (cond | 1 << 26 | 1 << 24 | rng.randrange(2) << 23 | rng.randrange(2) << 22
                | rng.randrange(2) << 20 | rn << 16 | rd << 12 | rng.randrange(4096))
    return (cond | 3 << 25 | 1 << 24 | rng.randrange(2) << 23 | rng.randrange(2) << 22
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


def test_random_words_of_the_datapath_agree_with_the_machine(build):
    """Random operands and flags: each word, written over the next free place, runs once."""
    rng = random.Random(0x5EED)
    machine = Machine(build(HEADER + END))
    machine.read_memory(0, 4)
    address = 0x200000
    machine.write_memory(address, bytes(4))
    interesting = [0, 1, 2, 31, 32, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0x80000001, 0xFF]
    checked = 0
    for _ in range(3000):
        word = inside_word(rng)
        assert outside_note(word) == ""
        machine.write_memory(address, struct.pack("<I", word))
        for n in range(11):
            machine.set_reg(n, rng.choice(interesting + [rng.getrandbits(32)]))
        machine.set_reg(11, rng.randrange(0x100) * 4)
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
    assert checked == 3000


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


def test_at_the_start_it_shows_the_instruction_that_runs_next(build):
    model = connected(Machine(build(STEPS)))
    assert model.view.kind == NEXT and model.view.trace.text == "MOV R0, #1"
    assert not model.update()           # nothing happened


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


def test_after_backstep_it_shows_the_instruction_undone(build):
    machine = Machine(build(STEPS))
    model = connected(machine)
    machine.step()
    machine.step()
    model.update()
    machine.backstep()
    assert model.update()
    assert model.view.kind == UNDONE and model.view.trace.text == "MOV R1, #2"
    assert machine.pc == model.view.trace.pc
    machine.backstep()
    assert model.update()
    assert model.view.kind == UNDONE and model.view.trace.text == "MOV R0, #1"
    machine.step()
    assert model.update()
    assert model.view.kind == EXECUTED and model.view.trace.text == "MOV R0, #1"


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


def test_a_register_changed_by_hand_shows_in_what_runs_next(build):
    machine = Machine(build(STEPS.replace("MOV     R0, #1", "ADD     R0, R3, #1")))
    model = connected(machine)
    assert model.view.trace.values["RD1"] == 0
    machine.set_reg(3, 9)
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


def test_outside_it_says_what_the_instruction_did_or_that_it_has_not_run(build):
    machine = Machine(build(HEADER + """\
        LDR     R0, =0x1000
        MOV     R1, #6
        MOV     R2, #7
        MUL     R3, R1, R2
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
    machine.backstep()
    model.update()
    assert model.view.kind == UNDONE and model.view.did == ()
    assert "not run" in model.view.heading or "runs next" in model.view.heading


def test_a_new_program_starts_again(build):
    model = connected(Machine(build(STEPS)))
    other = Machine(build(HEADER + "        MOV R5, #5\n" + END))
    model.observe(other)
    assert model.view.kind == NEXT and model.view.trace.text == "MOV R5, #5"


def test_reset_of_the_program_shows_the_first_instruction_as_next(make_runner):
    runner = make_runner(STEPS)
    model = connected(runner.machine)
    runner.step()
    model.update()
    runner.reset()
    assert model.update()
    assert model.view.kind == NEXT and model.view.trace.text == "MOV R0, #1"


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
