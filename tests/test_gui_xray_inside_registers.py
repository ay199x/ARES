# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The ARM X-Ray's window inside the register file: the registers, the reads through the three
multiplexers, the write through the address decoder, the ports an instruction does not use,
how it plays with the film, and how it follows the program and closes."""

import pytest
from test_gui_run import loaded
from test_gui_xray import LARGEST, connected, steps
from test_gui_xray_inside import EXAMPLE, Event, block_point, example
from xray_layout import clashes

from ares import xray
from ares.gui.tools.xray_inside import (DONE, IDLE_STATE, UNUSED, UNUSED_LINES, WORKING, phase,
                                        steps_of)
from ares.gui.tools.xray_inside_registers import PORTS as COLUMNS
from ares.gui.tools.xray_inside import CHANGED, IDLE, INK, ON, WORKING_FILL
from ares.gui.tools.xray_inside_registers import RegisterFileWindow

SMALL = """\
        .global _start
_start: MOV     R1, #5
        MOV     R2, #3
        ADDS    R0, R1, R2
        SUB     R3, R1, R2, LSL #1
        LDR     R4, =table
        STRB    R1, [R4, #1]
        MOV     R6, #8
        STR     R0, [R4, R6]
        CMP     R0, R0
        LDRNE   R5, [R4]
        BL      function
        SVC     #10
function:
        MOV     PC, LR
        .data
table:  .word   0, 0, 0, 0
"""
NAMES = [f"R{number}" for number in range(13)] + ["R13 (SP)", "R14 (LR)", "R15 (PC + 8)"]
PORTS = (("1", "RA1", "SrcA"), ("2", "RA2", "RD2"), ("4", "A4", "RD4"))   # address, output
A3_UNUSED = f"A3: {UNUSED_LINES}"
WD3_UNUSED = f"WD3: {UNUSED}"


def inside(app, tmp_path, source=LARGEST, count=0, zoom=None):
    """The tool connected to source, its window inside the register file opened by a click on
    the block, after count Steps (the last one's film at its start)."""
    loaded(app, tmp_path, source)
    tool = connected(app)
    if zoom is not None:
        tool._make_canvas(zoom)
    tool._clicked(Event(*block_point(tool, "RegFile")))
    window = tool.insides["RegFile"]
    steps(app, count)
    return tool, window


def seek(tool, step, fraction):
    """Show the tool's film at fraction of step (forwards only, as the clock goes). The test
    moves the clock: the film's timer is not needed."""
    tool.stop_film()
    tool.test_clock.now = tool.player.start + step.start + step.duration * fraction
    tool._tick()
    tool.stop_film()


def shown(window, tag="all"):
    """The texts of the items with tag that show (not the hidden ones), in drawing order."""
    canvas = window.canvas
    return [canvas.itemcget(item, "text") for item in canvas.find_withtag(tag)
            if canvas.type(item) == "text" and canvas.itemcget(item, "state") != "hidden"
            and canvas.itemcget(item, "text")]


def words(window):
    return " | ".join(shown(window))


def row(window, number):
    """What the row of register number shows: its name, its value and, written, the new one."""
    return shown(window, f"block:R{number}")


def lit(window, fill=WORKING_FILL):
    """The blocks filled as at work: rows (R0 to R15) and the decoder; or with another fill."""
    canvas = window.canvas
    return {tag[6:] for item in canvas.find_all()
            if canvas.type(item) == "rectangle" and canvas.itemcget(item, "fill") == fill
            for tag in canvas.gettags(item) if tag.startswith("block:")}


def changed(window):
    """The rows on the green of a change: the registers written."""
    return lit(window, CHANGED)


def struck(window):
    """The registers whose old value shows struck out."""
    canvas = window.canvas
    return {tag[7:] for item in canvas.find_all() if canvas.itemcget(item, "state") != "hidden"
            for tag in canvas.gettags(item) if tag.startswith("strike:")}


def enables(window):
    """The numbers of the registers whose write enable shows 1, and how many show 0."""
    canvas = window.canvas
    ones, zeros = set(), 0
    for item in canvas.find_all():
        tags = [tag for tag in canvas.gettags(item) if tag.startswith("wire:en")]
        if not tags or canvas.type(item) != "text" or canvas.itemcget(item, "state") == "hidden":
            continue
        if canvas.itemcget(item, "text") == "1":
            ones.add(int(tags[0][7:]))
        else:
            zeros += 1
    return ones, zeros


def fits(window):
    """No text over another, over a line not its own or across a block, and none cut off."""
    canvas = window.canvas
    assert clashes(canvas) == []
    width, height = float(canvas.cget("width")), float(canvas.cget("height"))
    for item in canvas.find_all():
        if canvas.type(item) == "text" and canvas.itemcget(item, "state") != "hidden":
            left, top, right, bottom = canvas.bbox(item)
            assert left >= 0 and top >= 0 and right <= width and bottom <= height, \
                canvas.itemcget(item, "text")


def test_a_click_on_the_block_opens_the_sixteen_registers(app, tmp_path):
    tool, window = inside(app, tmp_path, count=6)           # LDR R3, [R1]
    tool.skip()
    assert isinstance(window, RegisterFileWindow)
    assert window.window.title() == "ARM X-Ray: Inside the Register File"
    assert window.SIZE[0] <= 760 and window.SIZE[1] <= 480
    context = tool._context
    before, trace = context.registers_before, context.trace
    for number in range(15):
        assert row(window, number)[:2] == [NAMES[number], f"0x{before[number]:08X}"]
    assert trace.values["PCPlus8"] == trace.pc + 8
    assert row(window, 15) == ["R15 (PC + 8)", f"0x{trace.pc + 8:08X}"]
    assert row(window, 0)[1] == "0x00000000" and row(window, 2)[1] == "0x00000005"
    assert row(window, 1)[1] == f"0x{app.machine.reg(1):08X}"     # the list's address
    fits(window)


def test_a_load_reads_its_base_register_alone_and_writes_its_register(app, tmp_path):
    tool, window = inside(app, tmp_path, count=6)           # LDR R3, [R1]
    tool.skip()
    before = tool._context.registers_before
    values = tool._context.trace.values
    assert shown(window, "wire:A1") == ["A1 = 0001"]
    assert shown(window, "wire:A2") == ["A2"]               # an immediate offset: no Rm
    assert shown(window, "wire:A4") == ["A4"]
    assert shown(window, "wire:RD1") == ["RD1", f"0x{before[1]:08X}"]
    assert shown(window, "wire:RD2") == ["RD2", UNUSED_LINES]
    assert shown(window, "wire:RD4") == ["RD4", UNUSED_LINES]
    assert (values["SrcA"], values["RD2"], values["RD4"]) == (before[1], None, None)
    assert shown(window, "word") == ["WRITE R3"]
    text = words(window)
    assert "A3 = 0011" in text and "WE3 = 1" in text and "WD3 = 0x0000000C" in text
    assert app.machine.reg(3) == 12
    assert row(window, 3) == ["R3", f"0x{before[3]:08X}", "0x0000000C"]
    assert struck(window) == {"R3"} and enables(window) == ({3}, 14)
    canvas = window.canvas
    assert {canvas.itemcget(item, "fill") for item in canvas.find_withtag("wire:en3")
            if canvas.type(item) == "line"} == {ON}
    assert "the decoder enables R3, which takes WD3 = 0x0000000C at the clock edge" in text
    assert "WRITE R3" in text
    fits(window)


def column(window, port):
    """The colours of the lines of port's column (its output's), and how many dots it has."""
    canvas, k = window.canvas, window.k
    x = next(each.column for each in COLUMNS if each.output == f"RD{port}")
    lines = {canvas.itemcget(item, "fill") for item in canvas.find_withtag(f"wire:RD{port}")
             if canvas.type(item) == "line" and canvas.itemcget(item, "state") != "hidden"}
    dots = [item for item in canvas.find_all() if canvas.type(item) == "oval"
            and canvas.itemcget(item, "fill") == INK
            and abs((canvas.coords(item)[0] + canvas.coords(item)[2]) / 2 / k - x) < 0.5]
    return lines, len(dots)


def ports(window, values, before, pc):
    """Check what each read port shows against the trace's values: a port with an address reads
    the register it names (R15 as PC + 8), one without stays gray and says it is not used."""
    for port, key, out in PORTS:
        number = values[key]
        if number is None:
            assert values[out] is None
            assert shown(window, f"wire:A{port}") == [f"A{port}"]
            assert shown(window, f"wire:RD{port}") == [f"RD{port}", UNUSED_LINES]
            assert column(window, port) == ({IDLE}, 0)
            continue
        value = pc + 8 if number == xray.PC_NUMBER else before[number]
        assert values[out] == value
        assert shown(window, f"wire:A{port}") == [f"A{port} = {number:04b}"]
        assert shown(window, f"wire:RD{port}") == [f"RD{port}", f"0x{value:08X}"]


@pytest.mark.parametrize("count, numbers", [
    (3, {"1": 1, "2": 2}),                  # ADDS R0, R1, R2
    (4, {"1": 1, "2": 2}),                  # SUB R3, R1, R2, LSL #1
    (6, {"1": 4, "2": 1}),                  # STRB R1, [R4, #1]: RD2 is stored
    (8, {"1": 4, "2": 6, "4": 0}),          # STR R0, [R4, R6]: RD4 is stored
    (12, {"2": 14}),                        # MOV PC, LR
])
def test_each_port_reads_the_register_its_address_names(app, tmp_path, count, numbers):
    tool, window = inside(app, tmp_path, SMALL, count)
    tool.skip()
    context = tool._context
    values = context.trace.values
    assert {port: values[key] for port, key, _ in PORTS if values[key] is not None} == numbers
    ports(window, values, context.registers_before, context.trace.pc)
    assert "not used: the ALU" not in words(window)
    fits(window)


@pytest.mark.parametrize("source, count, reads, why", [
    (LARGEST, 7, ("A1 = 0011", "A2 = 0000"),
     "CMP only sets the flags; no register is written."),    # CMP has no Rd
    (LARGEST, 11, ("A1 = 1111",), "A branch writes no register."),
    (LARGEST, 14, ("A2 = 0011",), "The condition failed, so R0 keeps its value."),
    (SMALL, 6, ("A1 = 0100", "A2 = 0001"), "A store writes no register."),
], ids=["cmp", "bne", "movgt-fails", "strb"])
def test_an_instruction_that_writes_no_register_says_we3_is_0(app, tmp_path, source, count,
                                                              reads, why):
    tool, window = inside(app, tmp_path, source, count)
    tool.skip()
    context = tool._context
    ports(window, context.trace.values, context.registers_before, context.trace.pc)
    text = words(window)
    assert all(read in text for read in reads), text
    assert "WE3 = 0: nothing is written. " + why in text
    assert struck(window) == set() and enables(window) == (set(), 15) and lit(window) == set()
    values = context.trace.values
    if "condition" in why:
        assert window.canvas.find_withtag("closed")         # the write is closed
        assert f"A3 = {values['A3']:04b}" in text and f"WD3 = 0x{values['WD3']:08X}" in text
    else:                                   # no register to write: A3 and WD3 are not used
        assert values["A3"] is None and values["WD3"] is None
        assert shown(window, "wire:A3") == [A3_UNUSED] and shown(window, "wire:WD3") == [WD3_UNUSED]
        assert not window.canvas.find_withtag("closed")
    fits(window)


def test_mov_reads_no_first_register_and_writes_its_register(app, tmp_path):
    tool, window = inside(app, tmp_path, count=8)           # MOVGT R0, R3, which runs
    tool.skip()
    assert shown(window, "wire:A1") == ["A1"]
    assert shown(window, "wire:RD1") == ["RD1", UNUSED_LINES]
    assert shown(window, "wire:A2") == ["A2 = 0011"] and shown(window, "wire:A4") == ["A4"]
    assert app.machine.reg(0) == 12
    assert row(window, 0) == ["R0", "0x00000000", "0x0000000C"] and struck(window) == {"R0"}
    fits(window)


READS = {"MOV R0, #5": [], "LDR R3, [R1]": ["R1"], "SUBS R2, R2, #1": ["R2"],
         "ADD R0, R1, R2": ["R1", "R2"], "CMP R3, R0": ["R3", "R0"],
         "STR R0, [R1, #4]": ["R1", "R0"], "BNE": ["R15"]}


@pytest.mark.parametrize("text", list(EXAMPLE))
def test_each_instruction_reads_only_the_registers_it_has(app, tmp_path, text):
    """LDR R3, [R1] reads R1 alone, SUBS R2, R2, #1 R2 alone, MOV R0, #5 none, a branch R15
    alone; CMP R3, R0 has no register at A3, and its WD3 does not come either."""
    tool, (window,) = example(app, tmp_path, text, "RegFile")
    context = tool._context
    trace, before = context.trace, context.registers_before
    values = trace.values
    read = [f"R{values[key]}" for _, key, _ in PORTS if values[key] is not None]
    assert read == READS[text]
    for moment in ("writing", "end"):
        if moment == "writing":             # the middle of its last step, the write
            seek(tool, steps_of(tool.film, "RegFile")[-1], 0.5)
        else:
            tool.skip()
        ports(window, values, before, trace.pc)
        if values["A3"] is None:            # CMP, STR and BNE have no register to write
            assert values["WD3"] is None and not text.startswith(("MOV", "LDR", "SUBS", "ADD"))
            assert shown(window, "wire:A3") == [A3_UNUSED]
            assert shown(window, "wire:WD3") == [WD3_UNUSED]
        fits(window)
    if values["A3"] is not None:
        assert shown(window, "wire:A3") == [f"A3 = {values['A3']:04b}"]
        assert shown(window, "wire:WD3") == [f"WD3 = 0x{values['WD3']:08X}"]
        assert shown(window, "word") == [f"WRITE R{values['A3']}"]
    else:
        assert shown(window, "word") == ["READ " + ", ".join(read)]
    if text == "CMP R3, R0":
        assert "CMP only sets the flags; no register is written." in words(window)
    if not read:                            # MOV R0, #5: only the write
        assert [step.lights for step in steps_of(tool.film, "RegFile")] == [(("RegFile",
                                                                               "WRITE R0"),)]


def test_a_register_read_and_written_keeps_its_old_value_on_rd1(app, tmp_path):
    tool, window = inside(app, tmp_path, count=9)           # ADD R1, R1, #4
    tool.skip()
    before = tool._context.registers_before
    assert app.machine.reg(1) == before[1] + 4
    assert shown(window, "wire:RD1") == ["RD1", f"0x{before[1]:08X}"]
    assert row(window, 1) == ["R1", f"0x{before[1]:08X}", f"0x{before[1] + 4:08X}"]
    fits(window)


def test_bl_reads_r15_as_pc_plus_8_and_writes_pc_plus_4_into_lr(app, tmp_path):
    tool, window = inside(app, tmp_path, SMALL, 11)         # BL function
    tool.skip()
    context = tool._context
    trace, before = context.trace, context.registers_before
    assert trace.kind == xray.BRANCH_LINK
    assert shown(window, "wire:A1") == ["A1 = 1111"]
    assert shown(window, "wire:RD1") == ["RD1", f"0x{trace.pc + 8:08X}"]
    assert shown(window, "wire:PCPlus8") == [f"PCPlus8 = 0x{trace.pc + 8:08X}"]
    assert row(window, 15) == ["R15 (PC + 8)", f"0x{trace.pc + 8:08X}"]
    assert app.machine.reg(14) == trace.pc + 4
    assert row(window, 14) == ["R14 (LR)", f"0x{before[14]:08X}", f"0x{trace.pc + 4:08X}"]
    assert "A3 = 1110" in words(window) and enables(window) == ({14}, 14)
    assert struck(window) == {"R14"}
    fits(window)


def test_a_write_to_r15_goes_to_the_pc_and_changes_no_register(app, tmp_path):
    tool, window = inside(app, tmp_path, SMALL, 12)         # MOV PC, LR
    tool.skip()
    context = tool._context
    lr = context.registers_before[14]
    text = words(window)
    assert "A3 = 1111" in text and "WE3 = 1" in text
    assert f"WE3 = 1, but R15 is the PC: the PC takes WD3 = 0x{lr:08X}" in text
    assert app.machine.pc == lr
    assert struck(window) == set() and enables(window) == (set(), 15) and lit(window) == set()
    assert row(window, 15) == ["R15 (PC + 8)", f"0x{context.trace.pc + 8:08X}"]
    fits(window)


def test_a_load_whose_condition_fails_has_nothing_to_write(app, tmp_path):
    tool, window = inside(app, tmp_path, SMALL, 10)         # LDRNE R5, [R4] with Z = 1
    tool.skip()
    values = tool._context.trace.values
    assert values["WD3"] is None and values["A3"] == 5 and values["A4"] is None
    text = words(window)
    assert "WD3 = ?" in text and "A3 = 0101" in text and "WE3 = 0" in text
    assert shown(window, "wire:A1") == ["A1 = 0100"] and shown(window, "wire:A4") == ["A4"]
    assert "WE3 = 0: nothing is written. The condition failed, so R5 keeps its value." in text
    assert window.canvas.itemcget(window.canvas.find_withtag("closed")[0], "state") != "hidden"
    assert struck(window) == set() and enables(window) == (set(), 15)
    fits(window)


def test_it_is_idle_before_its_steps_at_work_in_them_and_finished_after(app, tmp_path):
    tool, window = inside(app, tmp_path, count=6)           # LDR R3, [R1], from its start
    film = tool.film
    read, write = steps_of(film, "RegFile")
    before = tool._context.registers_before

    def state():
        return phase(film, tool.player.moment, "RegFile")
    assert state() == (IDLE_STATE, 0.0)
    assert lit(window) == set() and "A1 = 0001" not in words(window)
    assert shown(window, "wire:A1") == ["A1"]
    assert shown(window, "out") == ["RD1", "RD2", UNUSED_LINES, "RD4", UNUSED_LINES]
    assert "waits" in words(window)
    fits(window)
    seek(tool, read, 0.1)                                   # the address comes
    assert state()[0] == WORKING and "A1 = 0001" in words(window) and lit(window) == set()
    seek(tool, read, 0.45)                                  # the row read lights up
    assert lit(window) == {"R1"} and "READ R1" in words(window)
    assert shown(window, "wire:RD1") == ["RD1"]             # its value has not left yet
    fits(window)
    seek(tool, read, 0.95)                                  # the value is out
    assert shown(window, "wire:RD1") == ["RD1", f"0x{before[1]:08X}"]
    fits(window)
    between = film.steps[film.steps.index(read) + 1]
    seek(tool, between, 0.5)
    assert state() == (WORKING, 1.0) and lit(window) == set()
    assert shown(window, "wire:RD1") == ["RD1", f"0x{before[1]:08X}"]
    assert "RD1 holds the value read; the write waits for the clock edge." in words(window)
    assert shown(window, "wire:A3") == ["A3"] and struck(window) == set()
    seek(tool, write, 0.5)                                  # the decoder enables R3
    assert lit(window) == {"Decoder"} and enables(window) == ({3}, 14) and changed(window) == set()
    assert struck(window) == set() and "0x0000000C" not in row(window, 3)
    fits(window)
    seek(tool, write, 0.85)                                 # the clock edge: R3 has changed
    assert lit(window) == {"Decoder"} and changed(window) == {"R3"} and struck(window) == {"R3"}
    assert row(window, 3)[-1] == "0x0000000C"
    fits(window)
    tool.skip()
    assert state()[0] == DONE and lit(window) == set() and struck(window) == {"R3"}
    assert changed(window) == {"R3"}


@pytest.mark.parametrize("zoom", [1.0, 1.2, 1.6])
@pytest.mark.parametrize("source, counts", [(LARGEST, (1, 2, 6, 7, 8, 9, 11, 14)),
                                            (SMALL, range(3, 13))], ids=["largest", "small"])
def test_no_text_lies_over_another_or_outside_the_window(app, tmp_path, zoom, source, counts):
    tool, window = inside(app, tmp_path, source, zoom=zoom)
    assert window.zoom == zoom
    done = 0
    for count in counts:
        steps(app, count - done)
        done = count
        film = tool.film
        if film.steps and film.trace.kind != xray.SYSTEM_CALL:    # an SVC uses no port
            for step in steps_of(film, "RegFile"):  # its write, after its read if it reads
                for fraction in (0.5, 0.95):
                    seek(tool, step, fraction)
                    fits(window)
            tool.skip()
        fits(window)


def test_a_second_step_redraws_it_for_the_next_instruction(app, tmp_path):
    tool, window = inside(app, tmp_path, count=6)           # LDR R3, [R1]
    tool.skip()
    assert "A1 = 0001" in words(window) and struck(window) == {"R3"}
    assert shown(window, "wire:A2") == ["A2"]
    steps(app, 1)                                           # CMP R3, R0
    tool.skip()
    text = words(window)
    assert "A1 = 0001" not in text and "A1 = 0011" in text and "A2 = 0000" in text
    assert shown(window, "wire:A3") == [A3_UNUSED]
    assert struck(window) == set() and "WE3 = 0: nothing is written" in text


def test_before_it_runs_the_new_value_is_wd3_and_the_program_agrees(app, tmp_path):
    tool, window = inside(app, tmp_path)                    # LDR R0, =intro, not run yet
    tool.model._unrecorded = True       # as after a run that kept no history: it runs next
    tool.model._state = None
    tool.refresh()
    context = tool._context
    assert tool.model.view.kind == xray.NEXT and context.registers_after is None
    wd3 = context.trace.values["WD3"]
    assert wd3 is not None and app.machine.reg(0) == 0
    assert shown(window, "wire:A1") == ["A1 = 1111"]          # the literal, near the PC
    assert row(window, 0) == ["R0", "0x00000000", f"0x{wd3:08X}"]
    steps(app, 1)
    tool.skip()
    assert app.machine.reg(0) == wd3
    assert row(window, 0) == ["R0", "0x00000000", f"0x{wd3:08X}"]


def test_an_instruction_outside_or_none_leaves_the_block_gray(app, tmp_path):
    tool, window = inside(app, tmp_path, count=2)           # SVC #4: the system performs it
    text = words(window)
    assert "An SVC does not use the register file: the system performs the service." in text
    assert lit(window) == set() and not any(t.startswith("0x") for t in shown(window))
    fits(window)
    tool.reset_button.invoke()
    assert tool.model.view.trace is None
    assert "No instruction is shown." in words(window)
    fits(window)


def test_it_closes_with_its_close_box_and_with_the_tool(app, tmp_path):
    tool, window = inside(app, tmp_path, count=1)
    window.window.tk.call(window.window.protocol("WM_DELETE_WINDOW"))
    assert window.window is None and tool.insides == {}
    steps(app, 1)                                           # the tool goes on without it
    again = tool.open_inside("RegFile")
    assert again is not window and tool.insides == {"RegFile": again}
    tool.close()
    assert again.window is None and tool.insides == {}


MULTIPLIES = """\
        .global _start
_start: MOV     R4, #3
        MOV     R5, #7
        MOV     R6, #0x15
        MLA     R3, R4, R5, R6
        MLA     R10, R11, R12, R14
        SVC     #10
"""


def test_mla_reads_rs_rm_and_ra_and_writes_the_register_of_19_16(app, tmp_path):
    tool, window = inside(app, tmp_path, MULTIPLIES, 4)
    read, write = steps_of(tool.film, "RegFile")
    seek(tool, read, 0.95)
    assert shown(window, "wire:A1") == ["A1 = 0101 (Rs)"]
    assert shown(window, "wire:A2") == ["A2 = 0100 (Rm)"]
    assert "A4 = 0110 (Ra)" in words(window)
    assert "Mul = 1: A1 is Rs (Instr 11:8), A4 is Ra (Instr 15:12)." in words(window)
    fits(window)
    tool.skip()
    text = words(window)
    assert "A3 = 0011" in text and "(A3 = Instr 19:16, the Rd of MUL and MLA)" in text
    assert row(window, 3)[-1] == "0x0000002A" and struck(window) == {"R3"}
    fits(window)
    steps(app, 1)                           # MLA R10, R11, R12, R14: two-digit registers
    tool.skip()
    assert shown(window, "wire:A1") == ["A1 = 1100 (Rs)"]
    assert shown(window, "wire:A2") == ["A2 = 1011 (Rm)"] and "A4 = 1110 (Ra)" in words(window)
    fits(window)



def test_movt_reads_its_rd_on_a4(app, tmp_path):
    tool, window = inside(app, tmp_path, """\
        .global _start
_start: MOVW    R3, #0x8001
        MOVT    R3, #0xFFFE
        SVC     #10
""", 2)
    read, write = steps_of(tool.film, "RegFile")
    seek(tool, read, 0.95)
    assert "A4 = 0011 (Rd)" in words(window)
    assert "A4 is Rd (Instr 15:12): MOVT keeps its low half." in words(window)
    fits(window)
    tool.skip()
    assert row(window, 3)[-1] == "0xFFFE8001" and struck(window) == {"R3"}
    fits(window)


# The numbers on the wires ------------------------------------------------------------------

def test_the_numbers_on_the_wires_show_their_bits_and_the_rows_their_names(app, tmp_path):
    """MLA R10, R11, R12, R14: the register numbers come in on A1, A2, A4 and A3 as the
    picture's wires carry them, their four bits; the rows keep their names, and the block's
    word and its sentences name the registers."""
    tool, window = inside(app, tmp_path, MULTIPLIES, 5)
    read, write = steps_of(tool.film, "RegFile")
    seek(tool, read, 0.95)
    assert shown(window, "wire:A1") == ["A1 = 1100 (Rs)"]
    assert shown(window, "wire:A2") == ["A2 = 1011 (Rm)"]
    assert "A4 = 1110 (Ra)" in words(window) and shown(window, "word") == ["READ R12, R11, R14"]
    assert "The register file reads R12 = " in words(window)
    tool.skip()
    assert "A3 = 1010" in words(window) and shown(window, "word") == ["WRITE R10"]
    assert [row(window, number)[0] for number in (10, 11, 12, 14)] == [
        "R10", "R11", "R12", "R14 (LR)"]
    numbers = [text for text in shown(window) if text.startswith(("A1 ", "A2 ", "A3 ", "A4 "))]
    assert numbers and all(text.split(" = ")[1][:4].strip("01") == "" for text in numbers)
    fits(window)


def at_moment(tool, moment):
    """Show the tool's film at moment, paused there."""
    tool.stop_film()
    tool.player.play(tool.film, moment)
    tool.player.pause()


@pytest.mark.parametrize("zoom", [1.0, 1.2, 1.6])
@pytest.mark.parametrize("name, count, widest", [
    ("multiply", 5, "A1 = 1100 (Rs)"),              # MLA R10, R11, R12, R14
    ("halfwords", 4, "A4 = 0011 (Rd)"),             # MOVT R3, #0xFFFE
    ("shifts", 5, "A4 = 0011 (Rs)"),                # ADD R2, R1, R0, LSL R3
    ("multiple", 5, "PassReg = 1110"),              # PUSH {R4, R5, LR}: A4 takes PassReg
    ("multiple", 12, "PassReg = 1111"),             # POP {R4, PC}: A3 takes PassReg
], ids=["mla", "movt", "shift-by-register", "push", "pop"])
def test_the_widest_numbers_fit_at_every_zoom(app, tmp_path, zoom, name, count, widest):
    """Four bits are wider than R3: with a field's name beside them, or PassReg's, they still
    lie over nothing, while the window reads and when it is done, in every pass."""
    from test_gui_xray import HALFWORDS, MULTIPLE, SHIFTS
    source = {"multiply": MULTIPLIES, "halfwords": HALFWORDS, "shifts": SHIFTS,
              "multiple": MULTIPLE}[name]
    tool, window = inside(app, tmp_path, source, count, zoom=zoom)
    assert window.zoom == zoom
    film, seen = tool.film, set()
    for sub in film.passes or (film,):
        moments = [sub.offset + step.start + 0.95 * step.duration
                   for step in steps_of(sub, "RegFile")] + [sub.offset + sub.seconds * 0.999]
        for moment in moments:
            at_moment(tool, moment)
            fits(window)
            seen.update(shown(window))
    assert widest in seen
