# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The ARM X-Ray's film as data: its steps, their order, its decisions and its time."""

import random
import struct
from collections import Counter
from pathlib import Path

import pytest
from conftest import ROOT
from test_xray import (END, HEADER, KIND_FLOORS, WORDS, inside_word, stepped, sweep_sources,
                       word_kind)
from test_xray import no_memory, word_of  # noqa: F401  (word_of: a fixture)

from ares import xray, xray_film
from ares.assembler import assemble
from ares.machine import SNAPSHOT_REGISTERS, Machine
from ares.program import Program
from ares.xray_film import (CLOSED, DEPENDS, MUL_SELECT, MUX_OUTPUTS, MUXES, NETS, PARTS, REJECTED,
                            SIGNALS, TAKEN, film, show)

LARGEST = ROOT / "tests" / "programs" / "largest.s"


def ports_reached(step):
    for move in step.moves:
        for branch, outcome in move.outcomes:
            yield NETS[move.net][1][branch]


def needed(port, travelling, trace):
    """The input ports whose values port's value needs in this instruction."""
    block = port.split(".")[0]
    if block in MUXES:
        select, inputs = MUXES[block]
        ports = [f"{block}.S"]
        if block == xray_film.SHIFT_SELECT and "ShiftReg" not in travelling:
            ports = []                  # ShiftReg 0 stays gray: A4 takes Instr 15:12, as before
        if f"{block}.Mul" in travelling.get("Mul", ()):     # the second select of RA1 and A3
            ports.append(f"{block}.Mul")
        for number, net in enumerate(inputs):
            branch_ports = {target for target in NETS[net][1].values()}
            if net in travelling and f"{block}.{number}" in travelling[net]:
                ports.append(f"{block}.{number}")
            del branch_ports
        return ports
    ports = list(DEPENDS[port])
    if block == "Control" and "Op2" in travelling:  # MUL and MLA: the decoder needs bits 7:4
        ports.append("Control.Op2")
    if port in ("ALU.Result", "ALU.Flags") and "ALU.RD4" in travelling.get("RD4", ()):
        ports.append("ALU.RD4")         # MLA: the multiplier adds RD4
    if port in ("ALU.Result", "ALU.Flags") and "CarryIn" in travelling:
        ports.append("ALU.CarryIn")     # ADC, SBC and RSC: the adder adds the C flag
    if port in ("Shifter.Out", "Shifter.Carry") and "Shifter.RD4" in travelling.get("RD4", ()):
        ports.append("Shifter.RD4")     # a shift by a register: the amount is RD4[7:0]
    values = trace.values
    if port == "Extend.Out" and trace.signals.get("ImmSrc") == "011":
        ports = ["Extend.Offset", "Extend.ImmSrc"]      # the pass counter's offset
    if port == "RegFile.RD4" and values.get("PassReg") is not None:
        ports = ["RegFile.PassReg"]     # a pass of an STM reads the register PassReg names
    if port == "RegFile.RD1" and values["RA1"] == 15:
        ports.append("RegFile.R15")
    if port == "RegFile.RD2" and values["RA2"] == 15:
        ports.append("RegFile.R15")
    if port in ("ALU.Result", "ALU.Flags") and "SrcA" in travelling:
        ports.append("ALU.A")
    if port in ("Shifter.Out", "Shifter.Carry") and "Shamt" in travelling:
        ports.append("Shifter.Shamt")
    return ports


def check(movie):
    """Every rule a film keeps; see ares.xray_film. The film of an LDM, STM, PUSH or POP keeps
    them in each pass; its passes follow one another, the first lasting the chosen time and each
    other xray_film.PASS_SHARE of it, and add up to the whole film."""
    if movie.passes:
        start = 0.0
        for number, sub in enumerate(movie.passes):
            check(sub)
            assert sub.offset == pytest.approx(start, abs=1e-9)
            assert sub.trace is movie.trace.passes[number]
            start += sub.seconds
        first = movie.passes[0].seconds
        assert all(sub.seconds == pytest.approx(first * xray_film.PASS_SHARE)
                   for sub in movie.passes[1:])
        assert start == pytest.approx(movie.seconds, abs=1e-9)
        assert sum(step.duration for step in movie.steps) == pytest.approx(movie.seconds)
        return movie
    trace = movie.trace
    steps = movie.steps
    assert steps and [step.part for step in steps] == sorted(
        (step.part for step in steps), key=PARTS.index), "the parts in order"
    names = movie.used()
    assert len(names) == len(set(names)), "each net travels once"
    travelling = {}
    for step in steps:
        for move in step.moves:
            assert move.net in NETS
            assert move.outcomes, f"{move.net} travels to something that looks at it"
            for branch, outcome in move.outcomes:
                assert branch in NETS[move.net][1], (move.net, branch)
                assert outcome in (TAKEN, REJECTED, CLOSED)
            travelling[move.net] = {NETS[move.net][1][branch] for branch, _ in move.outcomes}
            if move.net in trace.values and move.net not in SIGNALS:
                # Only what the instruction has travels: a field it lacks, a read only such bits
                # feed, or a value behind an X stays where it is.
                assert trace.values[move.net] is not None, f"{move.net} has no value here"
    reached = set()
    for step in steps:
        for move in step.moves:
            source = NETS[move.net][0]
            missing = [port for port in needed(source, travelling, trace) if port not in reached]
            assert not missing, f"{move.net} leaves {source} before {missing} arrived"
        for decision in step.decisions:
            select, inputs = MUXES[decision.mux]
            # Mul, when it travels, is the high bit of the select of the RA1 and A3 multiplexers.
            mul = decision.mux in MUL_SELECT and f"{decision.mux}.Mul" in travelling.get("Mul", ())
            assert decision.select == (f"Mul, {select}" if mul else select)
            assert "X" not in decision.value, f"an X steers {decision.mux}"
            assert decision.taken == int(xray.filled(decision.value), 2)
            real = tuple(number for number, net in enumerate(inputs)
                         if number != decision.taken and net in travelling
                         and f"{decision.mux}.{number}" in travelling[net])
            assert decision.rejected == real, (decision.mux, decision.rejected, real)
            output = MUX_OUTPUTS[decision.mux]
            assert output in {move.net for move in step.moves}, "the decision lets its output go"
            for number, net in enumerate(inputs):
                port = f"{decision.mux}.{number}"
                if net not in travelling or port not in travelling[net]:
                    continue
                outcome = dict((NETS[net][1][b], o) for b, o in _outcomes(steps, net))[port]
                assert outcome == (TAKEN if number == decision.taken else REJECTED), \
                    (decision.mux, net, outcome)
        reached |= set(ports_reached(step))
    deciding = {d.mux for step in steps for d in step.decisions}
    working = {block for step in steps for block, _ in step.lights} |         {gate.block for step in steps for gate in step.gates}
    for step in steps:
        for move in step.moves:
            if move.net not in SIGNALS:
                continue
            for branch, _ in move.outcomes:
                block = NETS[move.net][1][branch].split(".")[0]
                # A control signal reaches only the parts that work: one that steers only gray
                # parts stays gray, with no value beside it.
                if block in MUXES:
                    assert block in deciding, (move.net, block)
                elif block in ("Shifter", "Extend", "DMem", "System"):
                    assert block in working, (move.net, block)
    total = sum(step.duration for step in steps)
    assert total == pytest.approx(movie.seconds, abs=1e-9)
    start = 0.0
    for step in steps:
        assert step.start == pytest.approx(start, abs=1e-9) and step.duration > 0
        start += step.duration
    return movie


def _outcomes(steps, net):
    for step in steps:
        for move in step.moves:
            if move.net == net:
                return move.outcomes
    return ()


def check_values(movie):
    """What travels is what the model works out: the same values where the model has one."""
    for sub in movie.passes:
        check_values(sub)
    if movie.passes:
        return
    trace = movie.trace
    for step in movie.steps:
        for move in step.moves:
            if move.net in trace.values and trace.values[move.net] is not None:
                assert move.text == show(move.net, trace.values[move.net]), move.net


@pytest.fixture(scope="module")
def largest(tmp_path_factory):
    """The traces of the first 12 instructions of the study program, as they ran."""
    folder = tmp_path_factory.mktemp("largest")
    result = assemble(LARGEST.read_text(), folder)
    assert result.ok
    machine = Machine(Program(result.elf_path), base_dir=folder)
    traces = []
    for _ in range(40):
        machine.step()
        if machine.request is not None:
            machine.drop_request()
            continue
        traces.append(xray.executed(machine, machine.history[-1]))
        if len(traces) == 36:
            break
    machine.close()
    return traces


def find(traces, text, nth=0):
    found = [t for t in traces if t.text == text]
    return found[nth]


# The two films of the design note ----------------------------------------------------------

def test_the_film_of_ldr_r3_from_r1(largest):
    trace = find(largest, "LDR R3, [R1]")
    movie = check(film(trace, 15))
    check_values(movie)
    sentences = [step.sentence for step in movie.steps]
    assert sentences[0].startswith("The PC holds 0x00000014")
    assert "0xE5913000" in sentences[1] and "PCPlus4 = 0x00000018" in sentences[1]
    assert sentences[2].startswith("The word splits into its fields: cond 1110, op 01, funct 011001")
    assert "LDR, a load with an immediate offset" in sentences[3]
    assert any("the ALU adds 0x0000003C and 0x00000000: 0x0000003C, the address" in s
               for s in sentences)
    assert any("reads the word at 0x0000003C: 0x0000000C" in s for s in sentences)
    assert any(s == "RegWrite is 1: R3 takes 0x0000000C." for s in sentences)
    assert sentences[-1].startswith("At the clock edge the PC takes 0x00000018")
    parts = [step.part for step in movie.steps]
    assert set(parts) == set(PARTS)
    decisions = {d.mux: d for step in movie.steps for d in step.decisions}
    assert decisions["ALUSrcMux"].taken == 1 and decisions["ResultMux"].taken == 1
    assert decisions["PCMux"].taken == 0 and "RA2Mux" not in decisions    # RegSrc1 is X
    assert decisions["ResultMux"].rejected == (0,)          # a load rejects ALUResult
    assert decisions["ALUSrcMux"].rejected == ()            # nothing comes from the shifter
    assert any("The register file reads R1 = 0x0000003C on RD1." == s for s in sentences)
    assert not {"RA2", "RD2", "Rm", "Shifted"} & set(movie.used())
    gates = {g.enable: g for step in movie.steps for g in step.gates}
    assert gates["RegWrite"].open and not gates["MemWrite"].open
    assert not gates["FlagWrite"].open


@pytest.mark.parametrize("text, named, absent", [
    ("LDR R3, [R1]", ["cond 1110", "op 01", "funct 011001", "Rn R1", "Rd R3", "imm12 0x000"],
     ["Rm"]),
    ("CMP R3, R0", ["funct 010101", "Rn R3", "shamt5 00000", "sh 00", "Rm R0"],
     ["imm", "Rd"]),
    ("BNE #0x14", ["cond 0001", "op 10", "funct 10,", "imm24 0xFFFFF9"], ["Rn", "Rd", "Rm"]),
    ("ADD R1, R1, #4", ["funct 101000", "Rn R1", "Rd R1", "rot 0000", "imm8 00000100"], ["Rm"]),
])
def test_the_split_names_the_fields_the_bit_display_shows(largest, text, named, absent):
    split = next(step for step in film(find(largest, text), 15).steps if step.fields)
    for part in named:
        assert part in split.sentence, (part, split.sentence)
    for part in absent:
        assert part not in split.sentence, (part, split.sentence)


def test_every_step_has_time_to_read_its_sentence(largest):
    movie = film(find(largest, "LDR R3, [R1]"), 15)
    for step in movie.steps:
        assert step.duration >= 15 * (0.55 + len(step.sentence) / 75) / sum(
            max(0.8 + 200 / 400 if s.moves else 0.8, 0.55 + len(s.sentence) / 75)
            for s in movie.steps) - 1e-9


def test_a_subtraction_says_which_value_it_takes_from_which(largest):
    alu = next(step for step in film(find(largest, "SUBS R2, R2, #1"), 15).steps
               if step.lights and step.lights[0][0] == "ALU")
    assert "subtracts 0x00000001 from 0x00000005" in alu.sentence


def test_the_film_of_bne_taken_and_not_taken(largest):
    taken, not_taken = find(largest, "BNE #0x14"), find(largest, "BNE #0x14", 4)
    for trace, pc_src, next_pc in ((taken, 1, "0x00000014"), (not_taken, 0, "0x0000002C")):
        movie = check(film(trace, 15))
        check_values(movie)
        decision = next(d for step in movie.steps for d in step.decisions if d.mux == "PCMux")
        assert decision.taken == pc_src
        assert movie.steps[-1].sentence.startswith(f"At the clock edge the PC takes {next_pc}")
    sentences = [step.sentence for step in film(not_taken, 15).steps]
    assert any("NE: Z = 1: the condition fails (CondEx 0): nothing will be written." in s
               for s in sentences)
    assert any(s.startswith("PCSrc is 0 because the condition failed") for s in sentences)


def test_movgt_executed_and_not_executed(largest):
    runs = [t for t in largest if t.text == "MOVGT R0, R3"]
    executes = {t.signals["CondEx"] for t in runs}
    assert executes == {"0", "1"}
    for trace in runs:
        movie = check(film(trace, 15))
        gate = next(g for step in movie.steps for g in step.gates if g.enable == "RegWrite")
        assert gate.open == (trace.signals["CondEx"] == "1")


def test_every_instruction_of_the_study_program_has_its_film(largest):
    for trace in largest:
        movie = film(trace, 15)
        if trace.note:
            assert movie.steps == ()
        else:
            check_values(check(movie))


# Over many generated words ---------------------------------------------------------------

def test_random_words_make_films_that_keep_every_rule(build):
    rng = random.Random(0xF11)
    machine = Machine(build(HEADER + END))
    machine.read_memory(0, 4)
    address = 0x200000
    machine.write_memory(address, bytes(4))
    interesting = [0, 1, 2, 31, 32, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0x80000001, 0xFF]
    kinds = Counter()
    for _ in range(1500):
        word = inside_word(rng)
        kinds[word_kind(word)] += 1
        machine.write_memory(address, struct.pack("<I", word))
        for n in range(11):
            machine.set_reg(n, rng.choice(interesting + [rng.getrandbits(32)]))
        machine.set_reg(11, rng.randrange(0x40, 0x100) * 4)     # where BX and BLX R11 may go
        machine.set_reg(12, 0x300000 + rng.randrange(0x1000) * 4)
        machine.uc.reg_write(SNAPSHOT_REGISTERS[0], rng.randrange(16) << 28 | 0x1D3)
        machine.set_reg(15, address)
        machine.step()
        trace = xray.executed(machine, machine.history[-1])
        seconds = rng.choice([5, 15, 40])
        movie = check(film(trace, seconds))
        check_values(movie)
        upcoming = xray.upcoming(machine, address)       # the same word, from the state now
        check(film(upcoming, seconds))
        machine.history.clear()
        address += 8
    for kind, least in KIND_FLOORS.items():     # no kind drops out of the generated words
        assert kinds[kind] >= least * 1500 // WORDS, (kind, kinds)


@pytest.mark.parametrize("path", sweep_sources(), ids=lambda path: path.name)
def test_every_step_of_the_programs_has_a_film(tmp_path, path):
    result = assemble(Path(path).read_text(), tmp_path)
    if not result.ok:
        pytest.skip("written in lower case on purpose")
    machine = Machine(Program(result.elf_path), base_dir=tmp_path)
    for trace in stepped(machine, limit=2000):
        movie = film(trace, 15)
        if not trace.note:
            check_values(check(movie))
    machine.close()


def test_the_hardware_values_only_fill_what_an_x_left_open(build):
    rng = random.Random(0xAB)
    machine = Machine(build(HEADER + END))
    for trace in stepped(machine):
        assert trace
    for _ in range(300):
        word = inside_word(rng)
        registers = [rng.getrandbits(32) for _ in range(16)]
        trace = xray.trace(0x1000, word, registers, rng.randrange(16) << 28, lambda a, s: None)
        for name, value in trace.values.items():
            if value is not None:
                assert trace.hardware[name] == value, name
        for name in ("RA1", "RA2", "A3", "RD1", "RD2", "RD4", "ExtImm", "Shifted", "WriteData"):
            assert trace.hardware[name] is not None, name


# The time ----------------------------------------------------------------------------------

@pytest.mark.parametrize("seconds", [5, 15, 40])
def test_the_steps_add_up_to_the_chosen_time(largest, seconds):
    movie = film(find(largest, "LDR R3, [R1]"), seconds)
    assert sum(step.duration for step in movie.steps) == pytest.approx(seconds)
    assert movie.steps[-1].start + movie.steps[-1].duration == pytest.approx(seconds)


def test_a_longer_wire_gets_more_time(largest):
    trace = find(largest, "LDR R3, [R1]")
    plain = film(trace, 15)
    longer = film(trace, 15, {"PC'": 1600})
    step = next(n for n, s in enumerate(plain.steps) if any(m.net == "PC'" for m in s.moves))
    assert longer.steps[step].duration > plain.steps[step].duration


def test_at_tells_the_step_and_how_far(largest):
    movie = film(find(largest, "LDR R3, [R1]"), 15)
    assert movie.at(0) == (0, 0.0)
    second = movie.steps[1]
    number, fraction = movie.at(second.start + second.duration / 2)
    assert number == 1 and fraction == pytest.approx(0.5)
    assert movie.at(15) == (len(movie.steps), 1.0)
    assert movie.at(100) == (len(movie.steps), 1.0)


def test_an_instruction_outside_has_no_film(word_of):
    multiply = xray.trace(0x1000, word_of("UMULL R0, R1, R2, R3"), [0] * 16, 0x1D3, no_memory)
    assert multiply.note and film(multiply, 15).steps == ()
    assert film(None, 15).steps == ()


# LDM, STM, PUSH and POP: one pass for each register ------------------------------------------

def test_a_push_plays_one_pass_for_each_register_the_first_at_the_chosen_speed(word_of):
    registers = [0x1000 + 0x100 * n for n in range(16)]
    trace = xray.trace(0x1000, word_of("PUSH {R4, R5, LR}"), registers, 0x1D3, no_memory)
    movie = check(film(trace, 15))
    check_values(movie)
    assert len(movie.passes) == 3
    assert movie.passes[0].seconds == 15 and movie.seconds == pytest.approx(15 + 2 * 15 / 3)
    for number, sub in enumerate(movie.passes, 1):
        assert all(step.sentence.startswith(f"Pass {number} of 3: ") for step in sub.steps)
        assert set(sub.used()) >= {"List", "PassReg", "Offset", "SrcA", "ExtImm", "Address"}
    held = [sub.steps[-1] for sub in movie.passes[:-1]]
    assert all("keeps the PC at 0x00001000" in step.sentence for step in held)
    assert all(g.enable == "Hold" and not g.open for step in held for g in step.gates)
    assert movie.steps[-1].sentence.startswith("Pass 3 of 3: At the clock edge the PC takes "
                                               "0x00001004")
    writes = [step.sentence for sub in movie.passes for step in sub.steps
              if "BaseWrite is 1" in step.sentence]
    assert len(writes) == 3 and "R13 takes WD5 = 0x00001CF4" in writes[-1]


def test_a_pop_that_loads_the_pc_ends_as_a_branch(word_of):
    registers = [0x2000 + 0x100 * n for n in range(16)]
    trace = xray.trace(0x1000, word_of("POP {R4, PC}"), registers, 0x1D3,
                       lambda address, size: (0x3000 + address).to_bytes(4, "little"))
    movie = check(film(trace, 15))
    last = movie.passes[-1]
    decision = next(d for step in last.steps for d in step.decisions if d.mux == "PCMux")
    assert decision.taken == 1 and last.trace.values["PCPlus4"] == 0x1004
    assert "PC' takes Result = 0x00005D04" in " ".join(step.sentence for step in last.steps)
    assert movie.steps[-1].sentence.startswith("Pass 2 of 2: At the clock edge the PC takes "
                                               "0x00005D04")
    first = movie.passes[0]
    assert any("AdrSrc is 1: the address is RD1 = 0x00002D00" in step.sentence
               for step in first.steps)


def test_a_multiple_whose_condition_fails_makes_one_pass_that_writes_nothing(word_of):
    trace = xray.trace(0x1000, word_of("POPNE {R4, R5}"), [0x100] * 16, 0x400001D3, no_memory)
    movie = check(film(trace, 15))
    assert len(movie.passes) == 1 and trace.count == 1
    gates = {g.enable: g for step in movie.steps for g in step.gates}
    assert not gates["RegWrite"].open and not gates["BaseWrite"].open


def test_a_post_indexed_load_uses_the_old_base_and_writes_the_new_one(word_of):
    registers = [0x1000 * n for n in range(16)]
    trace = xray.trace(0x100, word_of("LDR R0, [R1], #8"), registers, 0x1D3,
                       lambda address, size: (0xBEEF).to_bytes(size, "little"))
    movie = check(film(trace, 15))
    check_values(movie)
    decisions = {d.mux: d for step in movie.steps for d in step.decisions}
    assert decisions["AdrSrcMux"].taken == 1 and decisions["AdrSrcMux"].rejected == (0,)
    sentences = " ".join(step.sentence for step in movie.steps)
    assert "post-indexed" in sentences and "0x00001008, the new base" in sentences
    assert "AdrSrc is 1: the address is RD1 = 0x00001000" in sentences
    assert "the base R1 takes WD5 = 0x00001008" in sentences
    gates = {g.enable: g for step in movie.steps for g in step.gates}
    assert gates["BaseWrite"].open and gates["RegWrite"].open
    outcomes = dict(next(m.outcomes for step in movie.steps for m in step.moves
                         if m.net == "ALUResult"))
    assert outcomes == {"adr": REJECTED, "result": REJECTED, "wd5": TAKEN}


def test_write_back_takes_the_sum_as_the_address_and_the_new_base(word_of):
    registers = [0x1000 * n for n in range(16)]
    trace = xray.trace(0x100, word_of("STR R0, [R1, #-4]!"), registers, 0x1D3, no_memory)
    movie = check(film(trace, 15))
    decisions = {d.mux: d for step in movie.steps for d in step.decisions}
    assert decisions["AdrSrcMux"].taken == 0 and decisions["AdrSrcMux"].rejected == (1,)
    sentences = " ".join(step.sentence for step in movie.steps)
    assert "with write-back" in sentences and "the address and the new base" in sentences
    assert "writes the word 0x00000000 at 0x00000FFC" in sentences
    assert "the base R1 takes WD5 = 0x00000FFC" in sentences


def system_words(movie):
    return [word for step in movie.steps for block, word in step.lights if block == "System"]


def test_an_svc_hands_the_call_to_the_system(largest):
    svc = find(largest, "SVC #4")
    movie = check(film(svc, 15, service="SVC #4, print string: R0 = 0x00001000"))
    check_values(movie)
    assert system_words(movie) == ["SVC #4, print string: R0 = 0x00001000"]
    used = movie.used()
    assert {"Instr", "SvcNum", "Syscall", "PC'"} <= set(used)
    assert not {"ALUResult", "SrcA", "RD1", "Result", "ReadData"} & set(used)
    split = next(step for step in movie.steps if step.fields)
    assert "imm24 0x000004, the number of the service" in split.sentence
    assert movie.steps[-1].lights == (("PCReg", f"0x{svc.pc + 4:08X}"),)
    assert any("ARES performs it. SVC #4, print string" in step.sentence for step in movie.steps)


def test_an_svc_that_waits_ends_its_film_at_the_system(largest):
    svc = find(largest, "SVC #4")
    movie = check(film(svc, 15, service="SVC #4, print string", waiting=True))
    assert movie.steps[-1].lights == (("System", "SVC #4, print string\nwaits for input"),)
    assert "PC'" not in movie.used()
    assert "Run I/O" in movie.steps[-1].sentence


def test_an_svc_whose_condition_fails_calls_nothing(word_of):
    t = xray.trace(0x1000, word_of("SVCNE #1"), [0] * 16, 0x400001D3, no_memory)
    movie = check(film(t, 15, service="SVC #1, print integer: R0 = 0"))
    assert system_words(movie) == ["SVC #1\nnot called"]
    assert any("Syscall, RegWrite and MemWrite are 0" in step.sentence for step in movie.steps)


# What the labels show -----------------------------------------------------------------------

@pytest.mark.parametrize("net, value, text", [
    ("PC", 0x14, "0x00000014"), ("ALUResult", 0xFFFFFFE4, "0xFFFFFFE4"), ("RA1", 15, "1111"),
    ("A3", 3, "0011"), ("Cond", 0b1110, "1110"), ("Funct", 0b11001, "011001"),
    ("ALUFlags", 0b10, "0010"), ("Imm", 0xFFFFF9, "0xFFFFF9"), ("ShiftC", 1, "1"),
    ("ALUControl", "0111", "0111"), ("ReadData", None, "?"), ("PassReg", 13, "1101"),
    ("Rs", 0, "0000"), ("A4", 14, "1110"),
])
def test_values_show_as_the_datapath_writes_them(net, value, text):
    assert show(net, value) == text


def test_a_tip_gives_a_register_number_as_its_bits_and_the_register_they_name():
    assert xray_film.register_bits(13) == "1101 (R13)"
    assert xray_film.register_bits(0) == "0000 (R0)"


FIELD_LOW_BITS = {"Rn": 16, "Rd": 12, "Rs": 8, "Rm": 0}   # where each field starts in the word


def test_register_numbers_travel_as_their_four_bits_and_the_register_file_names_them(word_of):
    """The fields Rn, Rd, Rm and Rs, the multiplexers' outputs RA1, RA2, A3 and A4, the
    constants 15 and 14 and the pass counter's PassReg travel as four bits, as the table of the
    word shows them (1101, not R13); the register file's word and the sentences name the
    register."""
    registers = [0x1000 + 0x100 * n for n in range(16)]
    seen = set()

    def memory(address, size):
        return (0x3000 + address).to_bytes(4, "little")
    for source in ("MLA R3, R4, R5, R6", "ADD R2, R1, R0, LSL R3", "LDR PC, [SP, #4]",
                   "STR R12, [R10, R3]", "BL .", "MOV R13, R15", "PUSH {R4, R5, LR}",
                   "POP {R4, PC}", "MOVT R3, #0xFFFE"):
        trace = xray.trace(0x1000, word_of(source), registers, 0x1D3, memory)
        movie = check(film(trace, 15))
        for sub in movie.passes or (movie,):
            values = sub.trace.values
            for step in sub.steps:
                for move in step.moves:
                    if move.net not in xray_film.REGISTER_NETS:
                        continue
                    if move.net in FIELD_LOW_BITS:
                        number = sub.trace.word >> FIELD_LOW_BITS[move.net] & 0xF
                    else:
                        number = {"Const15": 15, "Const14": 14}.get(move.net,
                                                                     values.get(move.net))
                    assert move.text == f"{number:04b}", (source, move.net, move.text)
                    seen.add(move.net)
                for block, word in step.lights:
                    if block == "RegFile":
                        assert word.split()[1].startswith("R"), (source, word)
    assert seen == set(xray_film.REGISTER_NETS)
    trace = xray.trace(0x1000, word_of("MLA R3, R4, R5, R6"), registers, 0x1D3, no_memory)
    sentences = " ".join(step.sentence for step in film(trace, 15).steps)
    for said in ("Rd R3, Ra R6, Rs R5", "RA1 takes R5 (Rs); RA2 takes R4 (Rm); A4 takes R6 (Ra)",
                 "The register file reads R5 = ", "RegWrite is 1: R3"):
        assert said in sentences, said


def test_every_signal_and_net_has_a_kind_and_a_source_port():
    for name, (source, branches) in NETS.items():
        assert name in xray_film.KINDS
        assert source in DEPENDS or source.split(".")[0] in MUXES, source
        assert branches
    assert set(SIGNALS) <= set(NETS)


def test_an_svc_that_waits_for_a_dialog_says_so(largest):
    svc = find(largest, "SVC #4")
    movie = check(film(svc, 15, service="SVC #4, print string", waiting="dialog"))
    assert movie.steps[-1].lights == (("System", "SVC #4, print string\nwaits for an answer"),)
    assert "the dialog window" in movie.steps[-1].sentence
    movie = check(film(svc, 15, service="SVC #4, print string", waiting="popup"))
    assert "the input dialog" in movie.steps[-1].sentence


def test_an_svc_whose_service_fails_stops_at_the_system(largest):
    svc = find(largest, "SVC #4")
    movie = check(film(svc, 15, service="SVC #4, print string: R0 = 0x80000000",
                       error="no memory at 0x80000000"))
    word = movie.steps[-1].lights[0][1]
    assert word.endswith("\nfails") and "PC'" not in movie.used()
    assert "fails: no memory at 0x80000000. The program stops here." in movie.steps[-1].sentence


def reads(movie):
    """The registers the register file reads in movie, as its word says."""
    words = [word for step in movie.steps for block, word in step.lights if block == "RegFile"]
    return next((word for word in words if word.startswith("READ")), "")


@pytest.mark.parametrize("source, read, absent", [
    ("LDR R3, [R1]", "READ R1", {"RA2", "RD2", "Rm", "Shifted"}),
    ("SUBS R2, R2, #1", "READ R2", {"RA2", "RD2", "Rm", "Shifted"}),
    ("MOV R0, #5", "", {"RA1", "RA2", "SrcA", "RD2", "Rn", "Rm", "Const15"}),
    ("ADD R0, R1, R2", "READ R1, R2", {"Imm", "ExtImm"}),
    ("CMP R3, R0", "READ R3, R0", {"A3", "WD3", "Rd", "Const14"}),
    ("BNE .", "READ R15", {"RA2", "RD2", "Rn", "Rm", "Rd", "Shifted"}),
])
def test_only_what_the_instruction_has_travels(word_of, source, read, absent):
    trace = xray.trace(0x1000, word_of(source), [0x100 * n for n in range(16)], 0x1D3,
                       lambda address, size: bytes(size))
    movie = check(film(trace, 15))
    check_values(movie)
    assert reads(movie) == read
    assert not absent & set(movie.used()), absent & set(movie.used())


def test_an_x_steers_nothing_and_only_real_inputs_are_rejected(word_of):
    regs = [0x100 * n for n in range(16)]
    store = film(xray.trace(0x1000, word_of("STR R0, [R1, #4]"), regs, 0x1D3, no_memory), 15)
    decisions = {d.mux: d for step in store.steps for d in step.decisions}
    assert decisions["ALUSrcMux"].rejected == (0,)          # the data from the shifter
    assert "ResultMux" not in decisions                     # MemtoReg is X
    branch = film(xray.trace(0x1000, word_of("BNE ."), regs, 0x1D3, no_memory), 15)
    decisions = {d.mux: d for step in branch.steps for d in step.decisions}
    assert decisions["PCMux"].taken == 1 and decisions["PCMux"].rejected == (0,)
    assert decisions["RA1Mux"].taken == 1 and decisions["RA1Mux"].rejected == ()
    assert "RA2Mux" not in decisions
    for step in branch.steps:
        assert "(0 here)" not in step.sentence


@pytest.mark.parametrize("source, names", [
    ("MOV R0, #5", "cond op I cmd S  Rd rot imm8"),
    ("CMP R3, R0", "cond op I cmd S Rn  shamt5 sh 0 Rm"),
])
def test_the_bit_display_names_no_field_the_instruction_lacks(word_of, source, names):
    trace = xray.trace(0x1000, word_of(source), [0] * 16, 0x1D3, no_memory)
    assert " ".join(name for name, *_ in xray_film.fields_of(trace)) == names


@pytest.mark.parametrize("source, funct", [("BNE .", "10"), ("BL .", "11"), ("SVC #1", "11"),
                                           ("ADD R0, R1, R2", "001000"), ("BX LR", "010010")])
def test_the_funct_wire_carries_only_funct_fields(word_of, source, funct):
    trace = xray.trace(0x1000, word_of(source), [0] * 16, 0x1D3, no_memory)
    movie = film(trace, 15, service="SVC #1, print integer: R0 = 0")
    (text,) = [move.text for step in movie.steps for move in step.moves if move.net == "Funct"]
    assert text == funct
    split = next(step for step in movie.steps if step.fields)
    assert f"funct {funct}" in split.sentence


@pytest.mark.parametrize("source, travel, still", [
    ("LDR R3, [R1]", {"RegSrc0", "Link", "MemWrite", "Size", "Signed", "MemtoReg", "ImmSrc",
                      "ALUSrc"}, {"RegSrc1", "Shift", "StoreSrc", "Syscall"}),
    ("CMP R3, R0", {"RegSrc0", "RegSrc1", "Shift", "ALUSrc", "MemtoReg"},
     {"Link", "ImmSrc", "MemWrite", "Size", "Signed", "StoreSrc", "Syscall"}),
    ("MOV R0, #5", {"ImmSrc", "ALUSrc", "Link", "MemtoReg"},
     {"RegSrc0", "RegSrc1", "Shift", "StoreSrc", "MemWrite", "Size", "Signed", "Syscall"}),
    # Signed steers the load extender: it travels for a load only.
    ("STRH R0, [R1, #2]", {"Size", "MemWrite", "ImmSrc", "RegSrc1"}, {"Signed", "MemtoReg"}),
    ("LDRSB R0, [R1, R2]", {"Size", "Signed", "MemtoReg", "Op2"}, {"ImmSrc", "Imm", "StoreSrc"}),
    ("MOVW R0, #5", {"ImmSrc", "ALUSrc", "Imm", "Rd"},
     {"RegSrc0", "RegSrc1", "Rn", "RA1", "A4", "RD4", "Size", "Signed", "ShiftReg"}),
    ("MOVT R0, #5", {"ImmSrc", "ALUSrc", "Imm", "Rd", "A4", "RD4"},
     {"RegSrc0", "RegSrc1", "Rn", "RA1", "RA2", "Size", "Signed", "ShiftReg"}),
    ("SVC #1", {"Syscall", "PCSrc"},
     {"RegWrite", "MemWrite", "ALUControl", "Link", "RegSrc0", "ImmSrc"}),
    # The additions of LDM, STM, write-back and post-indexing steer parts only they use.
    ("CMP R3, R0", {"MemtoReg"}, {"Hold", "BaseWrite", "PassReg", "Offset", "List", "AdrSrc"}),
    ("MOV R0, #5", {"ImmSrc"}, {"Hold", "BaseWrite", "PassReg", "Offset", "List", "AdrSrc"}),
    ("LDR R3, [R1]", {"AdrSrc", "Address"}, {"Hold", "BaseWrite", "PassReg", "Offset", "List"}),
    ("LDR R3, [R1], #4", {"AdrSrc", "BaseWrite"}, {"Hold", "PassReg", "Offset", "List"}),
    # Mul, Op2 and Rs are additions too: they travel only for MUL and MLA, with Mul 1.
    ("ADD R0, R1, R2", {"RegSrc0", "Link", "Rn"}, {"Mul", "Op2", "Rs"}),
    ("LDR R3, [R1]", {"RegSrc0", "Link"}, {"Mul", "Op2", "Rs"}),
    ("MUL R0, R1, R2", {"Mul", "Op2", "Rs", "Rn", "Rm", "RegSrc0", "RegSrc1", "Link", "Shift"},
     {"Rd", "RD4", "ImmSrc", "MemWrite", "Size", "StoreSrc", "AdrSrc", "Hold", "BaseWrite"}),
    ("MLA R0, R1, R2, R3", {"Mul", "Op2", "Rs", "Rd", "RD4"}, {"ImmSrc", "MemWrite", "StoreSrc"}),
])
def test_a_signal_that_steers_only_gray_parts_stays_gray(word_of, source, travel, still):
    regs = [0x100 * n for n in range(16)]
    trace = xray.trace(0x1000, word_of(source), regs, 0x1D3, lambda address, size: bytes(size))
    movie = film(trace, 15, service="SVC #1, print integer: R0 = 0")
    moved = set(movie.used())
    assert travel <= moved, travel - moved
    assert not still & moved, still & moved
    if trace.kind == xray.SYSTEM_CALL:
        assert not [g for step in movie.steps for g in step.gates]   # no "closed" marks



# MUL and MLA: the multiplier in the ALU, and Mul for the registers -----------------------------

def multiply_film(word_of, source, flags=0x1D3):
    registers = [0x10 * n for n in range(16)]
    registers[5], registers[4], registers[6] = 7, 3, 0x15
    trace = xray.trace(0x1000, word_of(source), registers, flags, no_memory)
    movie = check(film(trace, 15))
    check_values(movie)
    return trace, movie


def test_mla_takes_rs_and_19_16_with_mul_and_adds_rd4(word_of):
    trace, movie = multiply_film(word_of, "MLA R3, R4, R5, R6")
    decisions = {d.mux: d for step in movie.steps for d in step.decisions}
    ra1, a3 = decisions["RA1Mux"], decisions["A3Mux"]
    assert (ra1.taken, ra1.select, ra1.value, ra1.rejected) == (2, "Mul, RegSrc0", "10", (0, 1))
    assert (a3.taken, a3.select, a3.value, a3.rejected) == (2, "Mul, Link", "10", (0, 1))
    assert decisions["WD3Mux"].select == "Link" and decisions["RA2Mux"].taken == 0
    outcomes = {move.net: dict(move.outcomes) for step in movie.steps for move in step.moves}
    assert outcomes["Rn"] == {"ra1": REJECTED, "a3": TAKEN}      # Instr 19:16, MLA's Rd
    assert outcomes["Rs"] == {"ra1": TAKEN}
    assert outcomes["Rd"] == {"control": TAKEN, "ra2": REJECTED, "a3": REJECTED, "a4": TAKEN}
    assert outcomes["RD4"] == {"alu": TAKEN}                     # Ra's value, to the multiplier
    assert outcomes["Mul"] == {"ra1": TAKEN, "a3": TAKEN} and outcomes["Op2"] == {"control": TAKEN}
    sentences = [step.sentence for step in movie.steps]
    assert "funct 000010, Rd R3, Ra R6, Rs R5, op2 1001, Rm R4." in sentences[2]
    assert "op 00, funct 000010 and op2 1001: MLA, a multiply-accumulate." in sentences[3]
    assert "RegSrc0 0, Mul 1, ALUSrc 0, ALUControl 1010" in sentences[4]
    assert ("Mul and RegSrc choose the registers to read: RA1 takes R5 (Rs); RA2 takes R4 "
            "(Rm); A4 takes R6 (Ra).") in sentences
    a4 = decisions["A4Mux"]
    assert (a4.taken, a4.select, a4.value, a4.rejected) == (0, "ShiftReg", "0", ())
    assert "ShiftReg" not in movie.used()       # 0: gray, as Mul is for every other instruction
    assert ("ALUControl 1010: the multiplier: 0x00000007 x 0x00000003 + 0x00000015 = "
            "0x0000002A.") in sentences
    assert "RegWrite is 1: R3 (Instr 19:16: Mul is 1) takes 0x0000002A." in sentences
    lights = [word for step in movie.steps for block, word in step.lights if block == "ALU"]
    assert lights == ["MLA"]


def test_muls_writes_n_and_z_and_reads_no_rd4(word_of):
    trace, movie = multiply_film(word_of, "MULS R0, R4, R5", 0x300001D3)
    used = set(movie.used())
    assert not {"Rd", "RD4", "ExtImm", "Imm"} & used          # bits 15:12 of MUL are no field
    sentences = " ".join(step.sentence for step in movie.steps)
    assert ("the multiplier: 0x00000007 x 0x00000003 = 0x00000015; its flags NZCV are "
            "0000") in sentences
    assert "FlagWrite is 10: N and Z are written: NZCV 0011 -> 0011." in sentences
    gates = {g.enable: g for step in movie.steps for g in step.gates}
    assert gates["FlagWrite"].open and gates["RegWrite"].open


def test_a_multiply_whose_condition_fails_closes_the_write(word_of):
    trace, movie = multiply_film(word_of, "MULNE R0, R4, R5", 0x400001D3)
    gates = {g.enable: g for step in movie.steps for g in step.gates}
    assert not gates["RegWrite"].open
    assert any("the condition fails (CondEx 0)" in step.sentence for step in movie.steps)


# The shift by a register, ADC, SBC, RSC, TEQ, BLX and NOP ----------------------------------------

def made(word_of, source, registers=None, flags=0x1D3):
    registers = registers or [0x10 * n for n in range(16)]
    trace = xray.trace(0x1000, word_of(source), registers, flags, no_memory)
    movie = check(film(trace, 15))
    check_values(movie)
    return trace, movie, [step.sentence for step in movie.steps]


def test_a_shift_by_a_register_reads_rs_on_a4_and_shifts_by_rd4(word_of):
    registers = [0x10 * n for n in range(16)]
    registers[0], registers[1], registers[3] = 7, 0x28, 0x302      # R3[7:0] = 2
    trace, movie, sentences = made(word_of, "ADD R2, R1, R0, LSL R3", registers)
    decisions = {d.mux: d for step in movie.steps for d in step.decisions}
    a4 = decisions["A4Mux"]
    assert (a4.taken, a4.select, a4.value, a4.rejected) == (1, "ShiftReg", "1", (0,))
    outcomes = {move.net: dict(move.outcomes) for step in movie.steps for move in step.moves}
    assert outcomes["Rs"] == {"a4": TAKEN}                      # not to RA1: Mul is 0
    assert outcomes["Rd"]["a4"] == REJECTED and outcomes["ShiftReg"] == {"a4": TAKEN}
    assert outcomes["RD4"] == {"shifter": TAKEN} and outcomes["Op2"] == {"control": TAKEN}
    assert outcomes["A4"] == {"regfile": TAKEN} and "Shamt" in outcomes
    assert ("RegSrc and ShiftReg choose the registers to read: RA1 takes R1 (Rn); RA2 takes R0 "
            "(Rm); A4 takes R3 (Rs).") in sentences
    assert ("ShiftReg 1: the shifter shifts 0x00000007 by R3[7:0] = 2 (LSL R3): 0x0000001C."
            in sentences)
    assert "op 00, funct 001000 and op2 0001: ADD" in sentences[3]
    lights = [word for step in movie.steps for block, word in step.lights if block == "Shifter"]
    assert lights == ["LSL R3"]


def test_a_shift_by_a_register_of_amount_0_passes_rd2_on(word_of):
    registers = [0x10 * n for n in range(16)]
    registers[3] = 0x100                                            # R3[7:0] = 0
    trace, movie, sentences = made(word_of, "MOVS R2, R0, ROR R3", registers, 0x200001D3)
    assert trace.signals["Shift"] == "1"            # the control unit cannot see R3
    assert any(s.startswith("ShiftReg 1: the shifter shifts") and "by R3[7:0] = 0" in s
               and s.endswith("unchanged: an amount of 0 leaves it and C as they are.")
               for s in sentences)
    assert "RA1" not in movie.used()                # MOV reads no Rn


def test_adc_sbc_and_rsc_take_the_c_flag_on_carryin(word_of):
    registers = [0x10 * n for n in range(16)]
    registers[1], registers[2] = 7, 3
    for source, line in (("ADCS R0, R1, R2", "the ALU adds 0x00000007, 0x00000003 and the carry 1"
                                             ": 0x0000000B"),
                         ("SBC R0, R1, R2", "the ALU subtracts 0x00000003 and NOT C from "
                                            "0x00000007 (C = 1): 0x00000004"),
                         ("RSC R0, R1, R2", "the ALU subtracts 0x00000007 and NOT C from "
                                            "0x00000003 (C = 1): 0xFFFFFFFC")):
        trace, movie, sentences = made(word_of, source, registers, 0x200001D3)
        assert any(line in s for s in sentences), (source, sentences)
        assert "CarryIn" in movie.used()
        carried = next(n for n, step in enumerate(movie.steps)
                       if any(m.net == "CarryIn" for m in step.moves))
        alu = next(n for n, step in enumerate(movie.steps)
                   if any(m.net == "ALUResult" for m in step.moves))
        assert carried < alu                # the carry is there before the ALU works
    trace, movie, sentences = made(word_of, "ADD R0, R1, R2", registers, 0x200001D3)
    assert "CarryIn" not in movie.used()


def test_teq_exclusive_ors_and_writes_no_register(word_of):
    trace, movie, sentences = made(word_of, "TEQ R1, R2")
    assert any("TEQ only sets the flags; no register is written" in s for s in sentences)
    assert [word for step in movie.steps for block, word in step.lights if block == "ALU"] == \
        ["EOR"]
    assert "TEQ, data processing" in sentences[3] and "TEQS" not in sentences[3]


def test_blx_writes_lr_and_takes_rm_as_the_next_pc(word_of):
    registers = [0x10 * n for n in range(16)]
    registers[3] = 0x2000
    trace, movie, sentences = made(word_of, "BLX R3", registers)
    decisions = {d.mux: d for step in movie.steps for d in step.decisions}
    assert decisions["A3Mux"].taken == 1 and decisions["WD3Mux"].taken == 1    # 14, PCPlus4
    assert decisions["PCMux"].taken == 1
    assert "RegWrite is 1: R14 takes 0x00001004." in sentences
    assert "op 00, funct 010010 and op2 0011: BLX, a branch with link" in sentences[3]
    assert movie.steps[-1].sentence.startswith("At the clock edge the PC takes 0x00002000")


def test_bx_sends_op2_which_tells_it_from_blx(word_of):
    trace, movie, sentences = made(word_of, "BX LR")
    assert "Op2" in movie.used() and "op2 0001: BX" in sentences[3]


def test_nop_writes_nothing_and_the_pc_goes_on(word_of):
    trace, movie, sentences = made(word_of, "NOP")
    assert set(movie.used()) == {"PC", "Const4", "Instr", "PCPlus4", "Cond", "Op", "Funct",
                                 "PCSrc", "PC'"}
    assert any(s.startswith("NOP: nothing is written") for s in sentences)
    assert "NOP, a hint that does nothing" in sentences[3]
    assert movie.steps[-1].sentence.startswith("At the clock edge the PC takes 0x00001004")
    assert not [g for step in movie.steps for g in step.gates]      # no "closed" marks
    trace, movie, sentences = made(word_of, "NOPEQ", flags=0x1D3)
    assert any("the condition fails" in s for s in sentences)


# MOVW and MOVT; LDRH, STRH, LDRSB and LDRSH ------------------------------------------------------

def test_movt_reads_rd_on_a4_and_joins_the_halves_in_the_alu(word_of):
    registers = [0x10 * n for n in range(16)]
    registers[10] = 0xABCD5678
    trace, movie, sentences = made(word_of, "MOVT R10, #0x1234", registers)
    outcomes = {move.net: dict(move.outcomes) for step in movie.steps for move in step.moves}
    assert outcomes["Rd"] == {"control": TAKEN, "a3": TAKEN, "a4": TAKEN}
    assert outcomes["RD4"] == {"alu": TAKEN} and outcomes["Imm"] == {"extend": TAKEN}
    assert "Rn" not in outcomes and "RA1" not in outcomes and "RegSrc0" not in outcomes
    decisions = {d.mux: d for step in movie.steps for d in step.decisions}
    assert (decisions["A4Mux"].taken, decisions["A4Mux"].rejected) == (0, ())
    assert "MOVT keeps the low half of its Rd: A4 takes R10 (Rd), Instr 15:12." in sentences
    assert ("ImmSrc is 100: Extend joins imm4 and imm12 into imm16 and zero-extends it: ExtImm = "
            "0x00001234.") in sentences
    assert ("ALUControl 1110: MOVT: R10 = 0x1234 : 0x5678, the new high half from SrcB and the "
            "old low half from RD4: 0x12345678.") in sentences
    assert "funct 110100, imm4 0001, Rd R10, imm12 0x234." in sentences[2]
    assert "MOVT, a move of a 16-bit immediate into the high half" in sentences[3]
    assert [word for step in movie.steps for block, word in step.lights if block == "ALU"] == \
        ["MOVT"]
    move = next(m for step in movie.steps for m in step.moves if m.net == "Imm")
    assert move.text == "0x1234"


def test_movw_passes_its_immediate_on(word_of):
    trace, movie, sentences = made(word_of, "MOVW R2, #0x8001")
    assert "RD4" not in movie.used() and "A4" not in movie.used()
    assert "ALUControl 0111: the ALU passes SrcB 0x00008001: 0x00008001." in sentences
    assert "RegWrite is 1: R2 takes 0x00008001." in sentences


@pytest.mark.parametrize("source, size, word, said", [
    ("LDRSB R0, [R1, #3]", "byte", "READ BYTE\nSIGNED",
     ": 0x80; its load extender copies the sign bit, 1, into bits 31:8: ReadData = 0xFFFFFF80."),
    ("LDRH R0, [R1], #2", "halfword", "READ HALF",
     ": 0x8000; its load extender fills bits 31:16 with zeros: ReadData = 0x00008000."),
    ("LDRSH R0, [R1, -R2]!", "halfword", "READ HALF\nSIGNED",
     ": 0x8000; its load extender copies the sign bit, 1, into bits 31:16: ReadData = "
     "0xFFFF8000."),
    ("LDRB R0, [R1]", "byte", "READ BYTE",
     ": 0x80; its load extender fills bits 31:8 with zeros: ReadData = 0x00000080."),
])
def test_a_load_of_a_halfword_or_byte_says_how_it_is_extended(word_of, source, size, word, said):
    registers = [0x10 * n for n in range(16)]
    def memory(address, count):         # a byte 0x80, a halfword 0x8000
        return bytes([0x80] if count == 1 else [0, 0x80, 0, 0x80][:count])
    trace = xray.trace(0x1000, word_of(source), registers, 0x1D3, memory)
    movie = check(film(trace, 15))
    check_values(movie)
    memory = next(step for step in movie.steps if any(b == "DMem" for b, _ in step.lights))
    assert memory.lights == (("DMem", word),)
    assert f"reads the {size} at " in memory.sentence and memory.sentence.endswith(said)
    outcomes = {move.net: dict(move.outcomes) for step in movie.steps for move in step.moves}
    assert outcomes["Size"] == {"dmem": TAKEN} and outcomes["Signed"] == {"dmem": TAKEN}


def test_strh_writes_the_low_half_of_its_data(word_of):
    registers = [0x10 * n for n in range(16)]
    registers[0] = 0x12345678
    trace, movie, sentences = made(word_of, "STRH R0, [R1, R2]!", registers)
    assert "MemWrite is 1: the data memory writes the halfword 0x5678 at 0x00000030." in sentences
    memory = next(step for step in movie.steps if any(b == "DMem" for b, _ in step.lights))
    assert memory.lights == (("DMem", "WRITE HALF"),)
    assert "STRH, a store of a halfword with a register offset, with write-back" in sentences[3]
    assert "RegWrite is 0: a store writes no register; BaseWrite is 1: the base R1 takes WD5 = " \
           "0x00000030." in sentences
    assert "Signed" not in movie.used() and "Size 01" in sentences[4]
