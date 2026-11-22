# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Pipeline Simulator's timing (ares.pipeline), without a window: tables worked by hand,
the source tool's figures, the checker against the stalls, and the fast way against the plain
way."""

import random
import struct
import time

import pytest
from conftest import ROOT

from ares import disasm, pipeline, xray
from ares.assembler import assemble
from ares.gui.tools import pipeline as pipeline_tool
from ares.gui.tools.pipeline import PipelineModel
from ares.machine import HISTORY_LIMIT, Machine, StopReason, condition_passed
from ares.pipeline import (BRANCH, DYNAMIC, EX, FLUSH, ID, JUMP, MEM, NONE, PC_WRITE, PLAIN,
                           STALL, STATIC, Blocks, Pipeline, Settings, Timing, Totals, check,
                           decode)
from ares.program import Program
from ares.runner import Runner, State

# Words of the instructions the tables use (the assembler's own encodings).
MOV_R0_1 = 0xE3A00001           # MOV R0, #1
MOV_R1_2 = 0xE3A01002           # MOV R1, #2
MOV_R2_3 = 0xE3A02003           # MOV R2, #3
MOV_R5_0 = 0xE3A05000           # MOV R5, #0
ADD_R1 = 0xE2811001             # ADD R1, R1, #1
ADD_R2_R1 = 0xE2812001          # ADD R2, R1, #1
LDR_R1 = 0xE5901000             # LDR R1, [R0]
CMP_R0_3 = 0xE3500003           # CMP R0, #3
POP_R4_PC = 0xE8BD8010          # POP {R4, PC}
BX_LR = 0xE12FFF1E              # BX LR
MOV_LR_R0 = 0xE1A0E000          # MOV LR, R0
LDR_LR = 0xE590E000             # LDR LR, [R0]


def branch_word(cond, address, target, link=False):
    """B (BL) with condition cond at address to target."""
    offset = ((target - address - 8) >> 2) & 0xFFFFFF
    return cond << 28 | (0xB if link else 0xA) << 24 | offset


def feed(settings, items, memory=None):
    """The plain way over items, [(address, word, taken)]: (pipeline, rows)."""
    memory = memory or {}
    for address, word, _ in items:
        memory.setdefault(address, word)
    read = lambda address: (memory.get(address), address in memory)  # noqa: E731
    plain = Pipeline(settings, read)
    rows = []
    for address, word, taken in items:
        rows += plain.feed(address, decode(word, address), taken)
    return plain, rows


def straight(settings, words):
    return feed(settings, [(4 * k, word, False) for k, word in enumerate(words)])


def table(rows):
    """(first cycle, cells) of each row, the cells as text."""
    return [(row.first, " ".join(row.cells)) for row in rows]


def assert_sums(totals):
    """cycles = instructions + 4 + lost, always."""
    assert totals.cycles == totals.instructions + 4 + totals.stalls + totals.flushes


FULL = "IF ID EX MEM WB"
NO_HELP, SAME_CYCLE, FORWARDING = Settings(), Settings(same_cycle=True), Settings(forwarding=True)


# Decoding --------------------------------------------------------------------------------

def names(units):
    return {pipeline.UNIT_NAMES[unit] for unit in units}


@pytest.mark.parametrize("word, reads, writes, loaded", [
    (0xE5913000, {"R1"}, {"R3"}, {"R3"}),                       # LDR R3, [R1]
    (0xE4910004, {"R1"}, {"R0", "R1"}, {"R0"}),                 # LDR R0, [R1], #4
    (0xE5A10004, {"R0", "R1"}, {"R1"}, set()),                  # STR R0, [R1, #4]!
    (0xE8BD8010, {"SP"}, {"R4", "SP"}, {"R4"}),                 # POP {R4, PC}
    (0xE92D4010, {"SP", "R4", "LR"}, {"SP"}, set()),            # PUSH {R4, LR}
    (0xE1A00211, {"R1", "R2"}, {"R0"}, set()),                  # LSL R0, R1, R2
    (0xE12FFF1E, {"LR"}, set(), set()),                         # BX LR
    (0xE0A10392, {"R0", "R1", "R2", "R3"}, {"R0", "R1"}, set()),    # UMLAL R0, R1, R2, R3
    (0xED2D8B02, {"SP", "S16", "S17"}, {"SP"}, set()),          # VPUSH {D8}
    (0xECBD0A02, {"SP"}, {"SP", "S0", "S1"}, {"S0", "S1"}),     # VPOP {S0, S1}
    (0xECB00B04, {"R0"}, {"R0", "S0", "S1", "S2", "S3"}, {"S0", "S1", "S2", "S3"}),
    (0xEC410B10, {"R0", "R1"}, {"S0", "S1"}, set()),            # VMOV D0, R0, R1
    (0xEEE10A10, {"R0"}, {"FPSCR"}, set()),                     # VMSR FPSCR, R0
    (0xEE110F10, set(), {"R0"}, set()),                         # MRC P15, #0, R0, C1, C0, #0
    (0xEF000009, {"R0"}, {"R0"}, set()),                        # SVC #9: allocate heap memory
    (0xEF000001, {"R0"}, set(), set()),                         # SVC #1: print integer
    (0xEF000007, set(), {"S0", "S1"}, set()),                   # SVC #7: read double, D0
    (0xEB000000, set(), {"LR"}, set()),                         # BL
])
def test_an_instruction_reads_and_writes_what_it_names(word, reads, writes, loaded):
    info = decode(word, 0x100)
    assert (names(info.reads), names(info.writes), names(info.loaded)) == (reads, writes, loaded)


@pytest.mark.parametrize("word, kind, flags, conditional, from_memory", [
    (0xE0900001, PLAIN, True, False, False),        # ADDS R0, R0, R1
    (0xE0A00001, PLAIN, False, False, False),       # ADC R0, R0, R1: reads C, sets nothing
    (0xE3500003, PLAIN, True, False, False),        # CMP R0, #3
    (0x12800001, PLAIN, False, True, False),        # ADDNE R0, R0, #1
    (0xE128F000, PLAIN, True, False, False),        # MSR APSR_nzcvq, R0
    (0xEEF1FA10, PLAIN, True, False, False),        # VMRS APSR_nzcv, FPSCR
    (0x0A000000, BRANCH, False, True, False),       # BEQ
    (0x1B000000, BRANCH, False, True, False),       # BLNE: a branch that also writes LR
    (0xEA000000, JUMP, False, False, False),        # B
    (0xEB000000, JUMP, False, False, False),        # BL
    (0xE12FFF1E, PC_WRITE, False, False, False),    # BX LR
    (0x112FFF1E, PC_WRITE, False, True, False),     # BXNE LR
    (0xE1A0F00E, PC_WRITE, False, False, False),    # MOV PC, LR
    (0xE8BD8010, PC_WRITE, False, False, True),     # POP {R4, PC}
    (0xE590F000, PC_WRITE, False, False, True),     # LDR PC, [R0]
    (0xE1B0F00E, PC_WRITE, True, False, False),     # MOVS PC, LR restores CPSR
])
def test_an_instruction_has_its_kind(word, kind, flags, conditional, from_memory):
    info = decode(word, 0x100)
    assert (info.kind, info.sets_flags, info.conditional, info.from_memory) == (
        kind, flags, conditional, from_memory)


def test_a_branch_knows_where_it_goes():
    assert decode(branch_word(0x0, 0x100, 0x80), 0x100).target == 0x80
    assert decode(branch_word(0xE, 0x100, 0x200, link=True), 0x100).target == 0x200


DATAPATH_WORDS = [
    0xE0810002, 0xE2433001, 0xE3A00005, 0xE3E00000, 0xE5913004, 0xE7910102, 0xE5810004,
    0xE7810002, 0xE5C10001, 0xE1500003, 0x12855001, 0xE2106CFF, 0xE0844080, 0xE1A00000,
    0xE12FFF1E, 0xEB000004, 0xEA000002, 0x0A000001, 0xE0200301, 0xE1C00001,
]


@pytest.mark.parametrize("word", DATAPATH_WORDS, ids=hex)
def test_reads_and_writes_agree_with_the_x_ray(word):
    """For an instruction of the X-Ray's datapath, the registers it reads (RA1 when used, RA2,
    A4) and writes (A3), the PC left out."""
    trace = xray.trace(0x100, word, [0] * 16, 0, lambda address, size: bytes(size))
    assert trace.note == "", trace.text
    values = trace.values
    reads = {values[port] for port in ("RA1", "RA2", "A4") if values.get(port) is not None}
    writes = {values["A3"]} if values.get("A3") is not None else set()
    info = decode(word, 0x100)
    assert set(info.reads) == reads - {15}, trace.text
    assert set(info.writes) == writes - {15}, trace.text


def example_instructions(tmp_path):
    for path in sorted((ROOT / "examples").glob("*.s")):
        result = assemble(path.read_text(encoding="utf-8"), tmp_path / path.stem)
        assert result.ok, path.name
        program = Program(result.elf_path)
        for address in program.code_addresses():
            yield path.name, address, program.read_word(address)


def test_every_instruction_of_every_example_decodes(tmp_path):
    seen = set()
    for name, address, word in example_instructions(tmp_path):
        info = decode(word, address)
        assert not info.text.startswith(".word"), (name, hex(address))
        assert info.kind in pipeline.KINDS
        seen.add(info.text)
    assert {"VMUL.F32 S0, S2, S2", "VDIV.F64 D0, D1, D2", "VLDR S1, [R1]"} <= seen


def test_floating_point_registers_count_like_the_others(tmp_path):
    texts = {decode(word, address).text: decode(word, address)
             for _, address, word in example_instructions(tmp_path)}
    vmul = texts["VMUL.F32 S0, S2, S2"]
    assert names(vmul.reads) == {"S2"} and names(vmul.writes) == {"S0"}
    vdiv = texts["VDIV.F64 D0, D1, D2"]
    assert names(vdiv.reads) == {"S2", "S3", "S4", "S5"} and names(vdiv.writes) == {"S0", "S1"}
    vldr = texts["VLDR S1, [R1]"]
    assert names(vldr.loaded) == {"S1"}


# Tables worked by hand -------------------------------------------------------------------------

def test_independent_instructions_take_n_plus_4_cycles():
    plain, rows = straight(NO_HELP, [MOV_R0_1, MOV_R1_2, MOV_R2_3])
    assert table(rows) == [(1, FULL), (2, FULL), (3, FULL)]
    assert plain.totals == Totals(3, 7, 0, 0)


@pytest.mark.parametrize("settings, second, lost", [
    (NO_HELP, "IF stall stall stall ID EX MEM WB", 3),
    (SAME_CYCLE, "IF stall stall ID EX MEM WB", 2),
    (FORWARDING, FULL, 0)])
def test_two_neighbours_that_depend_lose_3_2_or_0(settings, second, lost):
    plain, rows = straight(settings, [ADD_R1, ADD_R2_R1, MOV_R5_0])
    assert table(rows)[:2] == [(1, FULL), (2, second)]
    third = " ".join([STALL] * lost + [FULL])
    assert table(rows)[2] == (3, third)             # held in IF while the reader waits in ID
    assert plain.totals == Totals(3, 7 + lost, lost, 0)
    if lost:
        assert rows[1].wait == "waits for R1 from ADD R1, R1, #1 at 0x00000000"
        assert rows[2].hold == "waits: the instruction ahead is held in ID"


@pytest.mark.parametrize("distance, settings, lost", [
    (2, NO_HELP, 2), (2, SAME_CYCLE, 1), (2, FORWARDING, 0),
    (3, NO_HELP, 1), (3, SAME_CYCLE, 0), (3, FORWARDING, 0)])
def test_the_same_at_distance_2_and_3(distance, settings, lost):
    plain, _ = straight(settings, [ADD_R1] + [MOV_R5_0] * (distance - 1) + [ADD_R2_R1])
    assert plain.totals.stalls == lost
    assert_sums(plain.totals)


def test_a_load_then_its_use_waits_one_cycle_with_forwarding():
    plain, rows = straight(FORWARDING, [LDR_R1, ADD_R2_R1])
    assert table(rows) == [(1, FULL), (2, "IF stall ID EX MEM WB")]
    assert rows[1].tip(3) == "waits for R1 from LDR R1, [R0] at 0x00000000"
    assert plain.totals == Totals(2, 7, 1, 0)
    plain, _ = straight(FORWARDING, [LDR_R1, MOV_R5_0, ADD_R2_R1])    # one between: no wait
    assert plain.totals.stalls == 0


def test_a_branch_decided_in_id_waits_for_the_flags_of_the_one_before():
    items = [(0, CMP_R0_3, False), (4, branch_word(0x0, 4, 0x40), False), (8, MOV_R5_0, False)]
    plain, rows = feed(Settings(branch_stage=ID), items)
    # The next one waits in IF while the branch waits in ID, then while it is decided.
    assert table(rows) == [(1, FULL), (2, "IF stall ID EX MEM WB"),
                           (3, "stall stall IF ID EX MEM WB")]
    assert rows[1].wait == "waits for the flags from CMP R0, #3 at 0x00000000"
    assert plain.totals == Totals(3, 9, 2, 0)       # 1 for the flags, 1 for the branch
    plain, rows = feed(Settings(branch_stage=EX), items)
    assert table(rows)[1] == (2, FULL)              # decided in EX: no wait for the flags
    assert plain.totals == Totals(3, 9, 2, 0)       # 2 for the branch


def test_other_conditional_instructions_never_wait_for_the_flags():
    plain, _ = straight(Settings(branch_stage=ID), [CMP_R0_3, 0x12855001, MOV_R5_0])  # ADDNE
    assert plain.totals.stalls == 0


@pytest.mark.parametrize("stage", [ID, EX, MEM])
@pytest.mark.parametrize("taken", [False, True])
def test_without_prediction_a_branch_costs_its_stage_taken_or_not(stage, taken):
    target = 0x40
    after = target if taken else 8
    items = [(0, MOV_R5_0, False), (4, branch_word(0x1, 4, target), taken),
             (after, MOV_R0_1, False)]
    plain, rows = feed(Settings(branch_stage=stage), items)
    assert len(rows) == 3 and not any(row.flushed for row in rows)
    assert table(rows)[2] == (3, " ".join([STALL] * stage + [FULL]))
    assert rows[2].hold.startswith("waits until the branch BNE")
    assert plain.totals == Totals(3, 7 + stage, stage, 0)


# (stage, predicted, taken) -> cycles lost, all of them flushed
PREDICTED_COSTS = {
    (ID, True, True): 1, (ID, True, False): 0, (ID, False, True): 1, (ID, False, False): 0,
    (EX, True, True): 1, (EX, True, False): 2, (EX, False, True): 2, (EX, False, False): 0,
    (MEM, True, True): 1, (MEM, True, False): 3, (MEM, False, True): 3, (MEM, False, False): 0,
}


@pytest.mark.parametrize("stage, predicted, taken", sorted(PREDICTED_COSTS))
def test_with_prediction_a_branch_costs_0_1_or_its_stage(stage, predicted, taken):
    target = 0x40
    after = target if taken else 8
    items = [(0, MOV_R5_0, False), (4, branch_word(0x1, 4, target), taken),
             (after, MOV_R0_1, False)]
    memory = {8: MOV_R1_2, 12: MOV_R2_3, 16: MOV_R0_1, 0x40: MOV_R0_1, 0x44: MOV_R1_2,
              0x48: MOV_R2_3}
    settings = Settings(branch_stage=stage, prediction=STATIC, static_taken=predicted)
    plain, rows = feed(settings, items, memory)
    lost = PREDICTED_COSTS[stage, predicted, taken]
    flushed = [row for row in rows if row.flushed]
    assert len(flushed) == lost
    assert plain.totals == Totals(3, 7 + lost, 0, lost, int(predicted == taken),
                                  int(predicted != taken))
    if stage > ID and predicted and not taken:      # the one in line, then the target's
        assert [row.address for row in flushed] == [8] + [0x40 + 4 * k for k in range(stage - 1)]
    elif stage > ID and not predicted and taken:    # those in line
        assert [row.address for row in flushed] == [8 + 4 * k for k in range(stage)]
    elif lost:
        assert [row.address for row in flushed] == [8]
    for row in flushed:
        assert row.cells[-1] == FLUSH and row.note.startswith("thrown away: the branch BNE")
    assert table(rows)[-1][1] == FULL               # the next one never stalls here


def test_a_flushed_row_reaches_ex_when_the_branch_is_decided_in_mem():
    items = [(0, MOV_R5_0, False), (4, branch_word(0x1, 4, 0x40), True), (0x40, MOV_R0_1, False)]
    settings = Settings(branch_stage=MEM, prediction=STATIC, static_taken=False)
    _, rows = feed(settings, items, {8: MOV_R1_2, 12: MOV_R2_3, 16: MOV_R0_1})
    assert table(rows) == [(1, FULL), (2, FULL), (3, "IF ID EX Flush"), (4, "IF ID Flush"),
                           (5, "IF Flush"), (6, FULL)]
    assert [row.text for row in rows[2:5]] == ["MOV R1, #2", "MOV R2, #3", "MOV R0, #1"]


@pytest.mark.parametrize("stage", [ID, EX])
def test_a_jump_costs_1_or_2_always(stage):
    items = [(0, MOV_R5_0, False), (4, branch_word(0xE, 4, 0x40), True), (0x40, MOV_R0_1, False)]
    for prediction in (NONE, STATIC, DYNAMIC):
        plain, rows = feed(Settings(jump_stage=stage, prediction=prediction), items)
        assert table(rows)[2] == (3, " ".join([STALL] * stage + [FULL]))
        assert rows[2].hold.startswith("waits until the jump B #0x40")
        assert plain.totals == Totals(3, 7 + stage, stage, 0)
        assert plain.lines == []                # a jump has no branch line


@pytest.mark.parametrize("stage", [ID, EX, MEM])
def test_a_pop_into_the_pc_is_decided_in_mem(stage):
    items = [(0, MOV_R5_0, False), (4, POP_R4_PC, True), (0x40, MOV_R0_1, False)]
    plain, rows = feed(Settings(branch_stage=stage), items)
    assert table(rows)[2] == (3, "stall stall stall " + FULL)
    assert plain.totals == Totals(3, 10, 3, 0)
    assert plain.lines[0].kind == PC_WRITE and plain.lines[0].taken


def test_a_pc_write_decided_in_id_needs_its_register_in_id():
    items = [(0, MOV_LR_R0, False), (4, BX_LR, True), (0x40, MOV_R0_1, False)]
    plain, rows = feed(Settings(branch_stage=ID, forwarding=True), items)
    assert table(rows)[1] == (2, "IF stall ID EX MEM WB")
    assert rows[1].wait == "waits for LR from MOV LR, R0 at 0x00000000"
    assert plain.totals.stalls == 2                 # 1 for LR, 1 for the PC write
    items[0] = (0, LDR_LR, False)
    plain, _ = feed(Settings(branch_stage=ID, forwarding=True), items)
    assert plain.totals.stalls == 3                 # 2 after a load
    plain, _ = feed(Settings(branch_stage=EX, forwarding=True), items)
    assert plain.totals.stalls == 1 + 2             # a load's use in EX, and EX


def test_the_predictor_states_move_one_up_when_taken_and_one_down_when_not():
    branch = branch_word(0x1, 0, 0)
    outcomes = [True, True, True, False, False, True, False, False, False]
    settings = Settings(prediction=DYNAMIC, bits=2, first_state_2=1)
    plain, _ = feed(settings, [(0, branch, taken) for taken in outcomes])
    assert [(line.before, line.predicted, line.after) for line in plain.lines] == [
        (1, False, 2), (2, True, 3), (3, True, 3), (3, True, 2), (2, True, 1),
        (1, False, 2), (2, True, 1), (1, False, 0), (0, False, 0)]
    settings = Settings(prediction=DYNAMIC, bits=1, first_state_1=1)
    plain, _ = feed(settings, [(0, branch, taken) for taken in outcomes])
    assert [line.predicted for line in plain.lines] == [True] + outcomes[:-1]


def test_each_branch_has_its_own_state_unless_one_is_chosen():
    first, second = branch_word(0x1, 0, 0), branch_word(0x1, 8, 0)
    items = [(0, first, True), (8, second, False), (0, first, True), (8, second, False)]
    plain, _ = feed(Settings(prediction=DYNAMIC, bits=1), items)
    assert [line.before for line in plain.lines] == [0, 0, 1, 0]
    plain, _ = feed(Settings(prediction=DYNAMIC, bits=1, one_state=True), items)
    assert [line.before for line in plain.lines] == [0, 1, 0, 1]


def test_a_branch_line_says_the_state_the_guess_what_happened_and_the_state_now():
    branch = branch_word(0x1, 8, 0x40)
    plain, _ = feed(Settings(prediction=DYNAMIC, bits=2, first_state_2=1), [(8, branch, True)])
    assert pipeline.line_text(plain.lines[0]) == (
        "[BNE #0x40] at 0x00000008  [State: 1]  Prediction: Not taken | Actual: Taken  "
        "State now: 2")
    plain, _ = feed(Settings(), [(8, branch, False)])
    assert pipeline.line_text(plain.lines[0]) == (
        "[BNE #0x40] at 0x00000008  No prediction | Actual: Not taken")


# The source tool's figures ------------------------------------------------------------------

def test_the_cpi_of_its_two_figures():
    eight = Totals(8, 8 + 4 + 2, 0, 2)
    assert (eight.cpi, eight.steady_cpi) == (1.75, 1.25)
    six = Totals(6, 6 + 4 + 2, 2, 0)
    assert six.cpi == 2.0 and six.steady_cpi == pytest.approx(4 / 3)


def test_its_test_bench_with_forwarding_and_2_bit_prediction_from_state_1():
    """Eight instructions: two equal values, a branch not taken, three more, a branch taken
    over three lines (two flushed), the last: CPI 1.75, steady-state 1.25, state 1 at the end."""
    bne, beq = branch_word(0x1, 8, 0x1C), branch_word(0x0, 0x18, 0x28)
    items = [(0, MOV_R0_1, False), (4, MOV_R1_2, False), (8, bne, False), (0xC, MOV_R2_3, False),
             (0x10, MOV_R5_0, False), (0x14, MOV_R0_1, False), (0x18, beq, True),
             (0x28, MOV_R1_2, False)]
    memory = {0x1C: MOV_R2_3, 0x20: MOV_R5_0, 0x24: MOV_R0_1}
    settings = Settings(forwarding=True, prediction=DYNAMIC, bits=2, first_state_2=1,
                        one_state=True)
    plain, rows = feed(settings, items, memory)
    totals = plain.totals
    assert (totals.instructions, totals.lost, totals.cpi, totals.steady_cpi) == (8, 2, 1.75, 1.25)
    assert [(line.predicted, line.taken) for line in plain.lines] == [(False, False),
                                                                      (False, True)]
    assert plain.lines[-1].after == 1
    assert [row.address for row in rows if row.flushed] == [0x1C, 0x20]


# The checker ------------------------------------------------------------------------------

def checked(settings, words):
    lines, added = check([(4 * k, decode(word, 4 * k)) for k, word in enumerate(words)],
                         settings)
    return ["NOP" if line.added else line.text for line in lines], added


@pytest.mark.parametrize("settings, nops", [(NO_HELP, 3), (SAME_CYCLE, 2), (FORWARDING, 0)])
def test_the_checker_puts_3_2_or_0_nops_between_neighbours(settings, nops):
    lines, added = checked(settings, [ADD_R1, ADD_R2_R1])
    assert lines == ["ADD R1, R1, #1"] + ["NOP"] * nops + ["ADD R2, R1, #1"]
    assert added == nops


def test_the_checker_puts_one_nop_after_a_load_with_forwarding():
    assert checked(FORWARDING, [LDR_R1, ADD_R2_R1])[1] == 1


@pytest.mark.parametrize("stage", [ID, EX, MEM])
def test_the_checker_puts_1_2_or_3_nops_after_a_branch_without_prediction(stage):
    words = [MOV_R5_0, branch_word(0x1, 4, 0x40), MOV_R0_1]
    assert checked(Settings(branch_stage=stage), words)[1] == stage
    assert checked(Settings(branch_stage=stage, prediction=STATIC), words)[1] == 0
    assert checked(Settings(branch_stage=stage, prediction=DYNAMIC), words)[1] == 0
    jump = [MOV_R5_0, branch_word(0xE, 4, 0x40), MOV_R0_1]
    assert checked(Settings(branch_stage=stage, jump_stage=EX), jump)[1] == 2
    assert checked(Settings(branch_stage=stage, jump_stage=EX, prediction=DYNAMIC),
                   jump)[1] == 0                # with prediction none after any of them
    pop = [MOV_R5_0, POP_R4_PC, MOV_R0_1]
    assert checked(Settings(branch_stage=stage), pop)[1] == MEM
    assert checked(Settings(branch_stage=stage, prediction=STATIC), pop)[1] == 0


def test_the_checker_on_its_test_bench_with_the_first_settings():
    bne, beq = branch_word(0x1, 0xC, 0x24), branch_word(0x0, 0x20, 0x30)
    words = [MOV_R0_1, MOV_R1_2, 0xE1500001, bne, MOV_R2_3, 0xE3A03003, 0xE3A04003, 0xE1530004,
             beq, MOV_R5_0]                     # ... CMP R0, R1; ... CMP R3, R4
    lines, added = checked(NO_HELP, words)
    assert added == 3 + 2 + 3 + 2
    assert lines[:8] == ["MOV R0, #1", "MOV R1, #2", "NOP", "NOP", "NOP", "CMP R0, R1",
                         "BNE #0x24", "NOP"]


# Generated programs -------------------------------------------------------------------------

REGISTERS = [f"R{n}" for n in range(8)]


def random_instruction(rng):
    a, b, c = (rng.choice(REGISTERS) for _ in range(3))
    k = rng.randrange(16)
    return rng.choice([
        f"ADD     {a}, {b}, {c}", f"SUB     {a}, {b}, #{k}", f"MOV     {a}, #{k}",
        f"ADDS    {a}, {b}, #{k}", f"CMP     {a}, {b}", f"LDR     {a}, [R9, #{4 * k}]",
        f"STR     {a}, [R9, #{4 * k}]", f"MUL     {a}, {b}, {c}", f"ADDNE   {a}, {a}, #1",
        f"LSL     {a}, {b}, #{k}", f"EOR     {a}, {b}, {c}", f"LDRB    {a}, [R9, #{k}]",
        f"MOVEQ   {a}, {b}", f"LDR     {a}, [R9], #0"])


def generated(seed, branches=True, length=6):
    """A program of random instructions; with branches, a counted loop, a branch forward that
    may or may not be taken, and a call of a function that returns with POP {R4, PC}."""
    rng = random.Random(seed)
    lines = ["        .data", "area:   .space  80", "        .global _start", "        .text",
             "_start: LDR     R9, =area", "        MOV     R10, #3"]

    def some():
        lines.extend("        " + random_instruction(rng) for _ in range(rng.randrange(1, length)))

    some()
    if branches:
        lines.append("loop:")
        some()
        lines += ["        SUBS    R10, R10, #1", "        BNE     loop"]
        some()
        lines.append(f"        CMP     R{rng.randrange(8)}, #{rng.randrange(4)}")
        lines.append(f"        B{rng.choice(['EQ', 'NE', 'GT', 'LT', 'CS'])}     skip")
        some()
        lines.append("skip:")
        some()
        lines += ["        BL      function"]
        some()
    lines += ["        SVC     #10"]
    if branches:
        lines += ["function:", "        PUSH    {R4, LR}"]
        some()
        lines += ["        POP     {R4, PC}"]
    return "\n".join(lines) + "\n"


def trace(program, limit=4000):
    """[(address, word, taken)] of the instructions the program executes, one Step at a time."""
    machine = Machine(program)
    steps = []
    while machine.stop_reason is None and len(steps) < limit and not machine.ends_here():
        address, cpsr = machine.pc, machine.cpsr
        word = machine.peek_words(address, 1)[0]
        machine.step()
        if machine.stop_reason is StopReason.ERROR:
            break
        steps.append((address, word, condition_passed(word >> 28, cpsr)))
    return machine, steps


def reader(program):
    def read(address):
        return program.read_word(address), program.is_code(address)
    return read


def blocks_of(steps, program, rng, cuts=0.3, blocks=None):
    """The trace cut into blocks at random places (with chance cuts after an instruction), a
    block ending at least after every instruction that changes the flow: (Blocks, codes).
    The blocks are added to blocks when it is given."""
    if blocks is None:
        blocks = Blocks()

        def read(address, size):
            return b"".join(struct.pack("<I", program.read_word(address + k) or 0)
                            for k in range(0, size, 4))
        hooked = [address for address, word, _ in steps if decode(word, address).kind == BRANCH]
        blocks.new_program(read, hooked)
    codes, start = [], None
    for index, (address, word, taken) in enumerate(steps):
        if start is None:
            start = address
        last = index == len(steps) - 1 or decode(word, address).kind != PLAIN
        if last or rng.random() < cuts:
            number = blocks.add(start, address + 4 - start)
            codes.append(number * 2 + int(taken and decode(word, address).kind == BRANCH))
            start = None
    return blocks, codes


SETTINGS = [
    Settings(), Settings(same_cycle=True), Settings(forwarding=True),
    Settings(branch_stage=ID), Settings(branch_stage=MEM, jump_stage=EX),
    Settings(forwarding=True, branch_stage=ID, prediction=STATIC),
    Settings(prediction=STATIC, static_taken=False, branch_stage=MEM),
    Settings(forwarding=True, prediction=DYNAMIC, bits=1, first_state_1=1),
    Settings(prediction=DYNAMIC, bits=2, first_state_2=2, branch_stage=ID),
    Settings(forwarding=True, prediction=DYNAMIC, bits=2, first_state_2=1, one_state=True),
    Settings(same_cycle=True, prediction=DYNAMIC, bits=1, one_state=True, branch_stage=MEM),
]


@pytest.fixture(scope="module")
def programs(tmp_path_factory):
    """(program, trace) of a few generated programs."""
    made = []
    for seed in range(6):
        work = tmp_path_factory.mktemp(f"generated{seed}")
        result = assemble(generated(seed), work)
        assert result.ok, [message.format() for message in result.messages]
        program = Program(result.elf_path)
        _, steps = trace(program)
        made.append((program, steps))
    return made


@pytest.mark.parametrize("settings", SETTINGS, ids=lambda settings: settings.summary())
def test_the_fast_way_gives_what_the_plain_way_gives(programs, settings):
    rng = random.Random(7)
    for program, steps in programs:
        plain = Pipeline(settings, reader(program))
        rows = []
        for address, word, taken in steps:
            rows += plain.feed(address, decode(word, address), taken)
        blocks, codes = blocks_of(steps, program, rng)
        timing = Timing(settings, blocks)
        cut = rng.randrange(len(codes) + 1)
        timing.run(codes[:cut])
        timing.run(codes[cut:])
        assert timing.totals == plain.totals
        assert_sums(timing.totals)
        assert [timing.line(entry) for entry in timing.lines] == plain.lines[-pipeline.LINES:]
        assert timing.rows(reader(program)) == rows[-pipeline.ROWS:]


LOOP = ("        .global _start\n        .text\n_start: MOV     R0, #200\n"
        "loop:   LDR     R1, [SP, #-4]\n        ADD     R2, R1, #1\n"
        "        SUBS    R0, R0, #1\n        BNE     loop\n        SVC     #10\n")


def test_the_fast_way_works_a_block_out_once_for_each_state(tmp_path):
    result = assemble(LOOP, tmp_path)
    program = Program(result.elf_path)
    _, steps = trace(program)
    blocks, codes = blocks_of(steps, program, random.Random(3), cuts=0)
    timing = Timing(Settings(forwarding=True, prediction=DYNAMIC, bits=2), blocks)
    timing.run(codes)
    assert len(codes) > 200 and timing.count == 802
    assert sum(len(known) for known in timing._answers) <= 4


def test_a_long_run_shows_its_last_500_rows_with_their_tips(tmp_path):
    result = assemble(LOOP, tmp_path)
    program = Program(result.elf_path)
    _, steps = trace(program)
    settings = Settings(forwarding=True, prediction=DYNAMIC, bits=2)
    plain = Pipeline(settings, reader(program))
    rows = []
    for address, word, taken in steps:
        rows += plain.feed(address, decode(word, address), taken)
    blocks, codes = blocks_of(steps, program, random.Random(1))
    timing = Timing(settings, blocks)
    timing.run(codes)
    shown = timing.rows(reader(program))
    assert len(shown) == pipeline.ROWS and shown == rows[-pipeline.ROWS:]
    assert any(row.wait.startswith("waits for R1 from LDR R1, [SP, #-4]") for row in shown)


@pytest.mark.parametrize("seed", range(8))
def test_for_straight_line_code_the_checkers_nops_are_the_stall_cycles(tmp_path, seed):
    result = assemble(generated(seed, branches=False, length=14), tmp_path)
    program = Program(result.elf_path)
    _, steps = trace(program)
    instructions = [(address, decode(word, address)) for address, word, _ in steps]
    for settings in SETTINGS[:5]:
        plain = Pipeline(settings)
        for address, info in instructions:
            plain.feed(address, info)
        assert check(instructions, settings)[1] == plain.totals.stalls
        assert_sums(plain.totals)


def test_branches_not_taken_cost_the_checkers_nops_without_prediction():
    words = [ADD_R1, branch_word(0x1, 4, 0x40), ADD_R2_R1, CMP_R0_3, branch_word(0x0, 16, 0x40),
             MOV_R5_0, MOV_LR_R0, 0x112FFF1E, MOV_R0_1]     # ... BXNE LR, not taken
    for settings in SETTINGS[:5]:
        plain, _ = straight(settings, words)
        lines, added = checked(settings, words)
        assert added == plain.totals.stalls, settings


def same_as_plain(timing, program, steps, settings):
    """The fast way after steps agrees with the plain way over them: numbers, lines, rows."""
    plain, rows = plain_of(program, steps, settings)
    assert timing.totals == plain.totals
    assert timing.newest_lines() == plain.lines[-pipeline.LINES:]
    assert timing.rows(reader(program)) == rows[-pipeline.ROWS:]


@pytest.mark.parametrize("settings", SETTINGS, ids=lambda settings: settings.summary())
def test_undo_gives_what_the_shorter_run_gives_and_the_run_goes_on(programs, settings):
    """Instructions taken out at random places, block boundaries or not: the numbers, the
    branch lines, the rows and the predictor are those of the run without them, also once
    the run goes on from there."""
    rng = random.Random(11)
    for program, steps in programs:
        blocks, codes = blocks_of(steps, program, rng)
        timing = Timing(settings, blocks)
        timing.run(codes)
        n = len(steps)
        for _ in range(3):
            k = rng.randrange(1, n + 1)
            assert timing.undo(k)
            n -= k
            same_as_plain(timing, program, steps[:n], settings)
            more = rng.randrange(0, len(steps) - n + 1)
            timing.run(blocks_of(steps[n:n + more], program, rng, blocks=blocks)[1])
            n += more
            same_as_plain(timing, program, steps[:n], settings)


def test_undo_says_when_the_tail_does_not_reach(programs, monkeypatch):
    monkeypatch.setattr(pipeline, "TAIL", 3)
    program, steps = programs[0]
    blocks, codes = blocks_of(steps, program, random.Random(2), cuts=1.0)   # a block each
    timing = Timing(Settings(), blocks)
    timing.run(codes)
    before = timing.totals
    assert not timing.undo(4) and timing.totals == before
    assert timing.undo(3)
    plain, _ = plain_of(program, steps[:-3], Settings())
    assert timing.totals == plain.totals and timing.newest_lines() == plain.lines


def test_the_record_takes_instructions_out_too(programs):
    program, steps = programs[3]
    blocks, codes = blocks_of(steps, program, random.Random(5))
    record = pipeline.Record()
    record.add(codes[:5], sum(blocks.list[code >> 1].count for code in codes[:5]))
    record.add(codes[5:], len(steps) - record.instructions)
    record.undo(len(steps) - 9, blocks)
    assert record.instructions == 9
    timing = Timing(FORWARDING, blocks)
    for part in record.codes():
        timing.run(part)
    same_as_plain(timing, program, steps[:9], FORWARDING)
    record.undo(100, blocks)
    assert record.instructions == 0 and list(record.codes()) == []


def test_the_record_keeps_the_last_million_instructions_or_so():
    record = pipeline.Record()
    for _ in range(25):
        record.add([2, 4, 6], 60_000)
    assert pipeline.LIMIT <= record.instructions < pipeline.LIMIT + pipeline.PART
    assert record.dropped + record.instructions == 25 * 60_000
    assert sum(len(part) for part in record.codes()) == 3 * (record.instructions // 60_000)


# The model: what the tool observes of a real run -----------------------------------------------

def model_run(program, settings, step=False, breakpoints=()):
    """(machine, model) after running program with the Pipeline Simulator's model connected:
    at full speed (stopping at breakpoints and going on), or one Step at a time."""
    machine = Machine(program)
    model = PipelineModel()
    model.configure(settings)
    model.connect(machine)
    runner = Runner(machine)
    for address in breakpoints:
        runner.set_breakpoint(address)
    while runner.state is not State.FINISHED:
        if step:
            runner.step()
        else:
            runner.run()
        model.update()
    return machine, model


def plain_of(program, steps, settings):
    plain = Pipeline(settings, reader(program))
    rows = []
    for address, word, taken in steps:
        rows += plain.feed(address, decode(word, address), taken)
    return plain, rows


@pytest.mark.parametrize("settings", SETTINGS[::2], ids=lambda settings: settings.summary())
def test_the_model_gives_the_plain_ways_numbers_at_full_speed_and_by_step(programs, settings):
    for program, steps in programs:
        plain, rows = plain_of(program, steps, settings)
        for step in (False, True):
            _, model = model_run(program, settings, step)
            assert model.totals == plain.totals, step
            assert model.lines() == plain.lines[-pipeline.LINES:]
            assert model.rows() == rows[-pipeline.ROWS:]


def test_a_run_stopped_inside_blocks_counts_each_instruction_once(programs):
    settings = Settings(forwarding=True, prediction=DYNAMIC, bits=2)
    for program, steps in programs:
        addresses = sorted({address for address, _, _ in steps})
        _, model = model_run(program, settings, breakpoints=addresses[1::3])
        assert model.totals == plain_of(program, steps, settings)[0].totals


def test_without_hooks_the_next_block_tells_a_branchs_outcome(programs, monkeypatch):
    monkeypatch.setattr(pipeline_tool, "conditional_branches", lambda program: {})
    settings = Settings(prediction=DYNAMIC, bits=1)
    for program, steps in programs:
        for step in (False, True):
            _, model = model_run(program, settings, step)
            assert model.totals == plain_of(program, steps, settings)[0].totals


def test_no_setting_changes_what_the_program_does(programs):
    def outcome(machine):
        area = machine.program.label_address("area")
        return ([machine.reg(n) for n in range(16)], machine.cpsr,
                machine.peek_words(area, 20), machine.console.text)
    for program, _ in programs:
        machine = Machine(program)
        machine.run()
        alone = outcome(machine)
        for settings in SETTINGS:
            machine, _ = model_run(program, settings)
            assert outcome(machine) == alone


def test_a_branch_to_the_next_instruction_gets_its_real_outcome(build):
    program = build("        .global _start\n        .text\n_start: MOV     R0, #0\n"
                    "        CMP     R0, #0\n        BEQ     next\nnext:   MOV     R1, #1\n"
                    "        CMP     R0, #1\n        BEQ     last\nlast:   SVC     #10\n")
    settings = Settings(prediction=STATIC, static_taken=False)
    for step in (False, True):
        _, model = model_run(program, settings, step)
        assert [line.taken for line in model.lines()] == [True, False]
        assert model.totals.flushes == 2 and model.totals.wrong == 1


def test_a_branch_that_ends_a_step_is_known_at_once(build):
    program = build("        .global _start\n        .text\n_start: MOV     R0, #1\n"
                    "        CMP     R0, #1\n        BEQ     away\n        MOV     R1, #2\n"
                    "away:   SVC     #10\n")
    machine = Machine(program)
    model = PipelineModel()
    model.connect(machine)
    runner = Runner(machine)
    for _ in range(3):
        runner.step()
    model.update()
    assert [line.taken for line in model.lines()] == [True]
    assert model.totals.instructions == 3


def test_a_wait_hint_the_machine_steps_over_counts(build):
    program = build("        .global _start\n        .text\n_start: MOV     R0, #1\n"
                    "        WFE\n        ADD     R0, R0, #1\n        YIELD\n        SVC     #10\n")
    _, steps = trace(program)
    for step in (False, True):
        _, model = model_run(program, NO_HELP, step)
        assert model.totals == plain_of(program, steps, NO_HELP)[0].totals
        assert model.totals.instructions == 5


def test_other_settings_are_worked_out_again_from_the_run(programs):
    program, steps = programs[2]
    _, model = model_run(program, Settings())
    other = Settings(forwarding=True, branch_stage=MEM, prediction=DYNAMIC, bits=2)
    assert model.configure(other) and not model.configure(other)
    plain, rows = plain_of(program, steps, other)
    assert model.totals == plain.totals and model.counted_from == 0
    assert model.rows() == rows[-pipeline.ROWS:]


def test_past_the_limit_new_settings_count_from_the_oldest_instruction_kept(programs,
                                                                         monkeypatch):
    monkeypatch.setattr(pipeline, "LIMIT", 12)
    monkeypatch.setattr(pipeline, "PART", 4)
    monkeypatch.setattr(pipeline_tool, "BATCH", 4)
    program, steps = programs[0]
    _, model = model_run(program, Settings())
    assert model.totals == plain_of(program, steps, Settings())[0].totals  # the settings in force
    model.configure(FORWARDING)
    kept = model.record.instructions
    assert model.counted_from == len(steps) - kept > 0
    assert model.totals.instructions == kept
    assert_sums(model.totals)


# Backstep, Reset and another program -----------------------------------------------------------

def connected_to(program, settings=Settings(), record_while_running=False):
    """(machine, runner, model): the model connected under settings, nothing run yet."""
    machine = Machine(program)
    model = PipelineModel()
    model.configure(settings)
    model.connect(machine)
    return machine, Runner(machine, record_while_running=record_while_running), model


def agrees(model, program, steps, settings):
    """The model shows what the plain way gives for steps: numbers, branch lines, rows."""
    plain, rows = plain_of(program, steps, settings)
    assert model.totals == plain.totals
    assert model.lines() == plain.lines[-pipeline.LINES:]
    assert model.rows() == rows[-pipeline.ROWS:]


def step(runner, model, times=1):
    for _ in range(times):
        runner.step()
        model.update()


def test_a_step_and_a_backstep_leave_the_pipeline_empty(programs):
    program, _ = programs[0]
    _, runner, model = connected_to(program)
    step(runner, model)
    assert model.totals.instructions == 1
    assert runner.backstep()
    model.update()
    assert model.totals == Totals() and model.rows() == [] and model.lines() == []
    assert model.record.instructions == 0


@pytest.mark.parametrize("settings", SETTINGS, ids=lambda settings: settings.summary())
def test_each_backstep_takes_one_instruction_out_and_steps_go_on(build, settings):
    """The tour: a branch not taken, one taken (its flushes with prediction), stalls for
    values and for the flags, a load and its use, a loop. Stepped to the end, then back one
    Backstep at a time to the start, then on one Step at a time: each time the tool shows
    what that many Steps show."""
    program = build((ROOT / "examples" / "pipeline_tour.s").read_text(encoding="utf-8"))
    _, steps = trace(program)
    _, runner, model = connected_to(program, settings)
    step(runner, model, len(steps))
    agrees(model, program, steps, settings)
    for n in range(len(steps) - 1, -1, -1):
        assert runner.backstep()
        model.update()
        agrees(model, program, steps[:n], settings)
    for n in range(1, len(steps) + 1):
        step(runner, model)
        agrees(model, program, steps[:n], settings)


@pytest.mark.parametrize("settings", SETTINGS[::2], ids=lambda settings: settings.summary())
def test_steps_and_backsteps_then_other_settings_agree(programs, settings):
    """Steps, then several Backsteps seen at one look, over and over; Confirm Settings then
    works on what remains of the run."""
    other = SETTINGS[-1] if settings != SETTINGS[-1] else SETTINGS[0]
    rng = random.Random(4)
    for program, steps in programs:
        machine, runner, model = connected_to(program, settings)
        n = 0
        for _ in range(4):
            more = rng.randrange(len(steps) - n + 1)
            step(runner, model, more)
            n += more
            back = rng.randrange(n + 1)
            for _ in range(back):
                assert runner.backstep()
            model.update()
            n -= back
            agrees(model, program, steps[:n], settings)
        model.configure(other)
        agrees(model, program, steps[:n], other)


COUNTDOWN = ("        .global _start\n        .text\n_start: LDR     R0, =3000\n"
             "loop:   SUBS    R0, R0, #1\n        BNE     loop\n        MOV     R1, #1\n"
             "        MOV     R2, #2\n        SVC     #10\n")


def test_after_a_run_kept_for_backstep_each_backstep_takes_one_out(build, monkeypatch):
    """Backstep while running: after the run each Backstep, down to the 2,000th, takes one
    instruction out, without working the run out again; the rows and the branch lines are
    still the newest 500 and 1,000 of what remains (3,000 branch lines ran)."""
    program = build(COUNTDOWN)
    _, steps = trace(program, limit=10_000)
    settings = Settings(prediction=DYNAMIC, bits=2)
    machine, runner, model = connected_to(program, settings, record_while_running=True)
    assert runner.run() is State.FINISHED
    model.update()
    agrees(model, program, steps, settings)
    monkeypatch.setattr(model, "_work_out", lambda: pytest.fail("worked out again"))
    assert len(machine.history) == HISTORY_LIMIT
    n = len(steps)
    for back in (1, 2, 997, 1000):
        for _ in range(back):
            assert runner.backstep()
        model.update()
        n -= back
        agrees(model, program, steps[:n], settings)
    assert not runner.backstep()                        # as far back as Backstep goes


def test_a_backstep_past_the_tail_works_the_numbers_out_from_the_run_kept(programs,
                                                                         monkeypatch):
    monkeypatch.setattr(pipeline, "TAIL", 3)
    program, steps = programs[0]
    _, runner, model = connected_to(program)
    step(runner, model, 10)
    for _ in range(6):
        runner.backstep()
    model.update()
    plain, _ = plain_of(program, steps[:4], Settings())
    assert model.totals == plain.totals and model.lines() == plain.lines


def test_reset_and_another_program_empty_the_pipeline(programs):
    program, steps = programs[1]
    _, runner, model = connected_to(program)
    runner.run()
    model.update()
    assert model.totals.instructions == len(steps)
    runner.reset()
    model.update()
    assert model.totals == Totals() and model.rows() == [] and model.record.instructions == 0
    runner.run()
    runner.reset()
    runner.run()
    model.update()                                      # seen only now: one run counts
    agrees(model, program, steps, Settings())
    runner.reset()
    runner.step()
    runner.step()
    runner.backstep()
    model.update()
    agrees(model, program, steps[:1], Settings())
    model.observe(Machine(program))                     # Assemble: the program's new machine
    assert model.totals == Totals() and model.record.instructions == 0


def test_disconnect_and_connect_keep_what_the_tool_holds(programs):
    program, steps = programs[2]
    machine, runner, model = connected_to(program)
    step(runner, model, 5)
    model.disconnect()
    model.connect(machine)
    agrees(model, program, steps[:5], Settings())
    runner.backstep()
    model.update()
    agrees(model, program, steps[:4], Settings())
    model.disconnect()
    runner.step()                                       # not observed
    model.connect(machine)
    runner.backstep()                                   # undoes what the tool never took in
    model.update()
    agrees(model, program, steps[:4], Settings())
    model.disconnect()
    runner.reset()
    model.connect(machine)                              # the run it held is gone
    assert model.totals == Totals()


def test_backsteps_take_out_only_what_the_tool_took_in(programs):
    program, steps = programs[0]
    machine = Machine(program)
    runner = Runner(machine)
    for _ in range(3):
        runner.step()
    model = PipelineModel()
    model.connect(machine)
    runner.backstep()
    model.update()
    assert model.totals == Totals()
    step(runner, model)                                 # the third instruction again
    assert [row.address for row in model.rows()] == [steps[2][0]]
    model.reset()                                       # the tool's Reset
    runner.backstep()
    model.update()
    assert model.totals == Totals()


def test_a_backstep_before_a_step_seen_at_one_look(programs):
    """The model sees a Backstep at the end of the next run of the emulator, so a Step after
    it, or a Reset and a run, are taken in the right order."""
    program, steps = programs[3]
    _, runner, model = connected_to(program)
    step(runner, model, 6)
    runner.backstep()
    runner.backstep()
    runner.step()
    model.update()
    agrees(model, program, steps[:5], Settings())
    runner.run()
    runner.reset()
    step(runner, model, 2)
    agrees(model, program, steps[:2], Settings())


@pytest.mark.serial
def test_ten_million_instructions_with_the_pipeline_simulator(build):
    """Connected, the tool follows blocks and conditional branches: in time, with the timing
    worked out by hand (13 cycles a turn without help, 7 with forwarding and prediction)."""
    program = build((ROOT / "tests" / "programs" / "loop10m.s").read_text())
    for settings, cycles in ((Settings(), 26_000_022),
                             (Settings(forwarding=True, prediction=DYNAMIC, bits=2), 14_000_018)):
        machine = Machine(program)
        model = PipelineModel()
        model.configure(settings)
        model.connect(machine)
        start = time.perf_counter()
        assert machine.run() is StopReason.EXIT
        model.update()
        elapsed = time.perf_counter() - start
        assert model.totals.instructions == 10_000_009 and model.totals.cycles == cycles
        assert elapsed < 10.0, f"{elapsed:.3f} s"


def test_a_row_thrown_away_on_a_literal_shows_it_as_data(build):
    """The words of LDR R0, =value after the code are no instructions: fetched in line after a
    branch, they show as data; the checker skips them."""
    program = build("        .global _start\n        .text\n_start: LDR     R0, =0x12345678\n"
                    "        CMP     R0, #0\n        BNE     over\n        .ltorg\n"
                    "over:   SVC     #10\n")
    settings = Settings(prediction=STATIC, static_taken=False)
    _, model = model_run(program, settings)
    thrown = [row for row in model.rows() if row.flushed]
    assert [row.text for row in thrown] == [".word 0x12345678", "SVC #0xA"]
    lines = model.check()[1]
    assert [line.text for line in lines if not line.added] == [
        "LDR R0, [PC, #4]", "CMP R0, #0", "BNE #0x10", "SVC #0xA"]
    assert pipeline.instruction_text(None, 0x40000000, False) == "no instruction here"


WRITTEN = """\
        .global _start
        .text
_start: MOV     R0, #20
        MOV     R1, #20         @ the same
        CMP     R0, R1
        BNE     next
        LDR     R2, =0x12345678
        ADD     R3, R2, #1
next:   SVC     #10
"""


def test_the_tool_names_instructions_as_the_student_wrote_them(build):
    """The rows, their tips, the branch lines and the checker's program say MOV R0, #20 and
    BNE next; each row keeps its Basic form; a word of data thrown away stays data."""
    program = build(WRITTEN)
    sources = disasm.SourceColumn(program, WRITTEN)
    machine = Machine(program)
    model = PipelineModel()
    model.configure(Settings(prediction=STATIC, static_taken=True))
    model.written = lambda shown, address: disasm.written(shown, sources, address)
    model.connect(machine)
    Runner(machine).run()
    model.update()
    rows = model.rows()
    executed = [row for row in rows if not row.flushed]
    assert [row.text for row in executed] == [
        "MOV R0, #20", "MOV R1, #20", "CMP R0, R1", "BNE next", "LDR R2, =0x12345678",
        "ADD R3, R2, #1", "SVC #10"]
    assert [row.basic for row in executed[:4]] == [
        "MOV R0, #0x14", "MOV R1, #0x14", "CMP R0, R1", "BNE #0x18"]
    assert executed[2].wait == "waits for R1 from MOV R1, #20 at 0x00000004"
    thrown = [row for row in rows if row.flushed]       # predicted taken, not taken
    assert [row.text for row in thrown] == ["LDR R2, =0x12345678", "SVC #10"]
    assert thrown[0].basic == "LDR R2, [PC, #4]"
    assert thrown[0].note == "thrown away: the branch BNE next at 0x0000000c is predicted taken"
    assert pipeline.line_text(model.lines()[0]) == (
        "[BNE next] at 0x0000000c  [Static]  Prediction: Taken | Actual: Not taken")
    assert [line.text for line in model.check()[1] if not line.added] == [
        row.text for row in executed]
    model.written = lambda shown, address: None         # no source: the Basic forms
    assert [row.text for row in model.rows() if not row.flushed][3] == "BNE #0x18"


def test_a_word_of_data_thrown_away_stays_data_and_a_hold_names_the_branch(build):
    source = ("        .global _start\n        .text\n_start: LDR     R0, =0x12345678\n"
              "        CMP     R0, #0\n        BNE     over\n        .ltorg\n"
              "over:   SVC     #10\n")
    program = build(source)
    sources = disasm.SourceColumn(program, source)
    written = lambda shown, address: disasm.written(shown, sources, address)  # noqa: E731
    for settings, texts in ((Settings(prediction=STATIC, static_taken=False),
                             [".word 0x12345678", "SVC #10"]), (Settings(), [])):
        machine = Machine(program)
        model = PipelineModel()
        model.configure(settings)
        model.written = written
        model.connect(machine)
        Runner(machine).run()
        model.update()
        assert [row.text for row in model.rows() if row.flushed] == texts
    assert model.rows()[-1].hold == "waits until the branch BNE over at 0x00000008 is decided in EX"


# Every way a run can stop: the Dynamic Instruction Counter counts the same instructions --------

# What is typed into the programs that read, a line at a time, only once they wait for it.
TYPED = {"strings.s": ["ARM\n", "3\n"], "keyboard_echo.s": ["Abc1\n"]}
FAILS = ("        .global _start\n        .text\n_start: MOV     R0, #1\n"
         "        ADD     R0, R0, #1\n        MOV     R1, #0x50000000\n"
         "        LDR     R2, [R1]        @ out of range: the run ends here\n"
         "        ADD     R0, R0, #1\n        SVC     #10\n")


def sources():
    found = [path for path in sorted((ROOT / "examples").glob("*.s"))]
    found += [path for path in sorted((ROOT / "tests" / "programs").glob("*.s"))
              if path.name not in ("loop10m.s", "lowercase.s")]
    return found


def typed_for(path):
    if path.name in TYPED:
        return list(TYPED[path.name])
    given = path.with_suffix(".in")
    return given.read_text(encoding="utf-8").splitlines(keepends=True) if given.is_file() else []


def counted(program, lines, tmp_path):
    """(machine, counter, model) of a run with both tools connected, paused every 20 ms (and
    so between slices), the lines typed one by one whenever the run waits or pauses."""
    from ares.gui.tools.counter import CounterModel
    machine = Machine(program, base_dir=tmp_path)
    counter, model = CounterModel(), PipelineModel()
    counter.connect(machine)
    model.connect(machine)
    runner = Runner(machine)
    for _ in range(10_000):
        state = runner.run(time_limit=0.02)
        counter.update()
        model.update()
        if state is State.FINISHED:
            break
        if lines:
            machine.console.feed(lines.pop(0))
    assert runner.state is State.FINISHED
    return machine, counter, model


@pytest.mark.parametrize("path", sources(), ids=lambda path: path.name)
def test_the_tool_counts_the_instructions_the_counter_counts(path, tmp_path):
    result = assemble(path.read_text(encoding="utf-8"), tmp_path)
    assert result.ok
    machine, counter, model = counted(Program(result.elf_path), typed_for(path), tmp_path)
    assert model.totals.instructions == counter.total > 0
    assert_sums(model.totals)


def test_a_runtime_error_inside_a_block_leaves_out_the_instruction_that_failed(build, tmp_path):
    machine, counter, model = counted(build(FAILS), [], tmp_path)
    assert machine.stop_reason is StopReason.ERROR
    assert model.totals.instructions == counter.total == 3
    assert [row.text for row in model.rows()][-1] == "MOV R1, #0x50000000"
