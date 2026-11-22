# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The ARM X-Ray's window inside the ALU: what it shows for each kind of instruction, what it
leaves gray without SrcA, how it plays with the film and follows the program, and that nothing
in it overlaps."""

import pytest
from test_gui_run import loaded
from test_gui_xray import LARGEST, at, connected, opened, steps, to_end
from test_gui_xray_inside import EXAMPLE, Event, drawn, example, middle_of, texts
from xray_layout import clashes

from conftest import press_key

from ares import xray
from ares.gui.tools.xray_inside import (DONE, IDLE, IDLE_STATE, INK, MARK, UNUSED, WORKING,
                                        WORKING_FILL, bit_text, phase, steps_of)
from ares.gui.tools.xray_look import net_colours
from ares.gui.tools.xray_inside_alu import MOVT_Y, MUL_Y, MUX_LEFT, SUM_Y, TOPS, UNITS, ALUWindow
from ares.xray_film import hex32

MASK = xray.MASK
ARITHMETIC = """\
        .global _start
_start: LDR     R1, =0x7FFFFFFF
        MOV     R2, #1
        ADDS    R0, R1, R2          @ too large for a signed number: N and V
        MOV     R3, #100
        SUB     R4, R3, R2, LSL #2  @ 100 - 4
        RSB     R5, R3, #10         @ 10 - 100
        SVC     #10
"""
LOGICAL = """\
        .global _start
_start: MOV     R1, #0xFF
        MOV     R2, #3
        ANDS    R0, R1, R2, LSR #1  @ the shifter's carry is 1
        MVN     R3, R2
        ORRS    R4, R1, R2          @ no shift: C and V are kept
        ANDS    R5, R1, #0xFF000000 @ C is bit 31 of the rotated immediate
        SVC     #10
"""
MEMORY = """\
        .global _start
_start: LDR     R1, =table
        MOV     R4, #0x41
        STRB    R4, [R1, #1]        @ at R1 + 1
        LDR     R5, [R1, #-4]       @ at R1 - 4
        BL      function            @ to PC + 8 + the offset
        SVC     #10
function:
        BX      LR
        .data
table:  .word   0
"""
FAILED = """\
        .global _start
_start: MOV     R0, #1
        CMP     R0, #1
        SUBNES  R2, R0, #5          @ Z is 1: it does not run
        SVC     #10
"""
MIXED = """\
        .global _start
_start: LDR     R1, =table
        MOV     R2, #3
        CMP     R2, #3
        SUBNES  R8, R2, #1
        MOV     R3, R2
        RSB     R4, R2, #10
        ANDS    R5, R1, R2, LSR #1
        ANDS    R10, R2, #0xFF000000
        SUB     R6, R1, R2, LSL #2
        STRB    R2, [R1, #1]
        LDR     R0, [R1, #-4]
        ADDS    R7, R1, R1
        MVN     R9, R2
        BL      function
        SVC     #10
function:
        BX      LR
        .data
table:  .word   0x80000000
"""


def shown(app, tmp_path, source, count, zoom=None):
    """The tool and its window inside the ALU after count Steps of source, the film ended."""
    loaded(app, tmp_path, source)
    tool = connected(app)
    if zoom is not None:
        tool._make_canvas(zoom)
    window = tool.open_inside("ALU")
    steps(app, count)
    to_end(tool)
    return tool, window


def instruction(tool):
    return tool.canvas.itemcget(tool.view_text, "text")


def at_share(tool, share):
    """Show the film at share of the ALU's step (a negative share: before it)."""
    step = steps_of(tool.film, "ALU")[0]
    at(tool, tool.player.start + step.start + share * step.duration - tool.test_clock.now)


def tagged(window, tag, kind="text"):
    """The texts of the text items with tag, or the items of another kind with it."""
    canvas = window.canvas
    if kind == "text":
        return [canvas.itemcget(item, "text") for item in canvas.find_withtag(tag)
                if canvas.type(item) == "text"]
    return [item for item in canvas.find_withtag(tag) if canvas.type(item) == kind]


def lit(window):
    """The parts filled as at work."""
    canvas = window.canvas
    return {tag[6:] for item in canvas.find_all() if canvas.type(item) in ("rectangle", "polygon")
            and canvas.itemcget(item, "fill") == WORKING_FILL
            for tag in canvas.gettags(item) if tag.startswith("block:")}


def flags_shown(window):
    """N Z C V as the four flags show them."""
    words = texts(window)
    bits = 0
    for flag in "NZCV":
        bits = bits << 1 | next(int(word[-1]) for word in words if word.startswith(f"{flag} = "))
    return bits


def statuses(window):
    return [word for word in texts(window) if word == "written" or word.startswith("kept: ")]


def kept(flags):
    return [f"kept: {flag} stays {flags >> xray.FLAG_BITS[flag] & 1}" for flag in "NZCV"]


def cpsr(app, flags):
    """The bits of flags (such as "NZ") in the CPSR now, in that order."""
    value = app.machine.cpsr >> 28
    return [value >> xray.FLAG_BITS[flag] & 1 for flag in flags]


def shown_bits(window, flags):
    return [flags_shown(window) >> xray.FLAG_BITS[flag] & 1 for flag in flags]


def dots(window):
    """The heights of the dots on the inputs of the result multiplexer, in design pixels."""
    canvas, k = window.canvas, window.k
    found = []
    for item in canvas.find_all():
        if canvas.type(item) == "oval" and canvas.itemcget(item, "fill") == INK:
            left, top, right, bottom = canvas.coords(item)
            if abs((left + right) / 2 / k - MUX_LEFT) < 0.5:
                found.append(round((top + bottom) / 2 / k))
    return found


def crosses(window):
    """The heights of the crosses on the inputs of the result multiplexer, in design pixels."""
    canvas, k = window.canvas, window.k
    found = set()
    for item in canvas.find_all():
        coords = canvas.coords(item)
        if canvas.type(item) != "line" or canvas.itemcget(item, "fill") != MARK:
            continue
        if len(coords) == 4:            # a stroke of a cross, not a wire
            x1, y1, x2, y2 = coords
            if abs((x1 + x2) / 2 / k - (MUX_LEFT - 6)) < 0.5:
                found.add(round((y1 + y2) / 2 / k))
    return sorted(found)


def assert_laid_out(window):
    """No text over another, over a line or across an outline, and none cut off."""
    canvas = window.canvas
    assert clashes(canvas) == []
    width, height = int(canvas.cget("width")), int(canvas.cget("height"))
    for item in canvas.find_all():
        if canvas.type(item) == "text" and canvas.itemcget(item, "text"):
            left, top, right, bottom = canvas.bbox(item)
            assert left >= 0 and top >= 0 and right <= width and bottom <= height, \
                canvas.itemcget(item, "text")


# Opening and closing -------------------------------------------------------------------------

def test_a_click_on_the_alu_opens_its_window_and_escape_closes_it(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    tool = connected(app)
    left, top, right, bottom = tool.canvas.bbox(tool.picture.titles["ALU"][0])
    tool._clicked(Event((left + right) // 2, (top + bottom) // 2))
    window = tool.insides["ALU"]
    assert isinstance(window, ALUWindow)
    assert window.window.title() == "ARM X-Ray: Inside the ALU"
    press_key(window.window, "<Escape>")
    assert window.window is None and tool.insides == {}
    steps(app, 7)                       # the closed window is left alone
    to_end(tool)
    window = tool.open_inside("ALU")
    tool.close()
    assert window.window is None


def test_the_window_is_small_enough_and_no_text_is_under_8_points(app, tmp_path):
    from tkinter import font as tkfont
    window = shown(app, tmp_path, LARGEST, 7, zoom=1.0)[1]
    width, height = ALUWindow.SIZE
    assert width <= 760 and height <= 480
    canvas = window.canvas
    assert int(canvas.cget("width")) == round(width * window.k)
    for item in canvas.find_all():
        if canvas.type(item) == "text":
            size = tkfont.Font(root=canvas, font=canvas.itemcget(item, "font")).actual("size")
            assert size >= 8, canvas.itemcget(item, "text")


# What it shows -------------------------------------------------------------------------------

def test_cmp_subtracts_by_adding_the_inverse_and_a_carry_in(app, tmp_path):
    tool, window = shown(app, tmp_path, LARGEST, 7)
    assert instruction(tool).endswith("CMP R3, R0")
    trace = tool.film.trace
    a, b, result = (trace.values[name] for name in ("SrcA", "SrcB", "ALUResult"))
    assert (a, b) == (app.machine.reg(3), app.machine.reg(0)) and result == a - b
    words = texts(window)
    for value in (a, b, result):
        assert hex32(value) in words and bit_text(value) in words
    assert {"SUB", "ALUControl = 0001", "RSB = 0", "SUB or RSB = 1", "carry in = 1",
            f"ALUResult = {hex32(result)}", "FlagWrite = 11: all four flags are written.",
            "ALUFlags NZCV = 0010"} <= set(words)
    assert tagged(window, "wire:First") == [hex32(a)]
    assert tagged(window, "wire:Added") == [hex32(~b & MASK)]       # NOT SrcB, and a carry in
    assert flags_shown(window) == trace.values["ALUFlags"] == app.machine.cpsr >> 28
    assert statuses(window) == ["written"] * 4
    assert dots(window) == [SUM_Y]                                  # it takes the adder's sum
    assert_laid_out(window)


def test_a_second_step_shows_the_next_instruction(app, tmp_path):
    tool, window = shown(app, tmp_path, LARGEST, 7)
    assert "SUB" in texts(window)
    steps(app, 1)                       # MOVGT R0, R3: SrcA is not used
    to_end(tool)
    assert instruction(tool).endswith("MOVGT R0, R3")
    trace = tool.film.trace
    a, b = trace.values["SrcA"], trace.values["SrcB"]
    assert a is None and b == app.machine.reg(3)
    words = texts(window)
    assert "SUB" not in words and "MOV" in words and "ALUControl = 0111" in words
    assert f"{UNUSED}: MOV takes SrcB alone" in words
    canvas = window.canvas
    assert {canvas.itemcget(item, "fill") for item in tagged(window, "wire:SrcA", "line")} == {IDLE}
    assert gray_without_srca(window, b)
    taken = [item for item in canvas.find_withtag("block:MOV")
             if canvas.type(item) == "text" and canvas.itemcget(item, "text") == hex32(b)]
    assert [canvas.itemcget(item, "fill") for item in taken] == [net_colours(trace)["ALUResult"]]
    assert dots(window) == [TOPS[4] + 10]
    assert f"ALUResult = {hex32(b)}" in words and app.machine.reg(0) == b
    assert "FlagWrite = 00: no flag is written." in words
    assert statuses(window) == kept(trace.flags)
    assert_laid_out(window)
    steps(app, 1)                       # ADD R1, R1, #4
    to_end(tool)
    assert "ADD" in texts(window) and f"ALUResult = {hex32(app.machine.reg(1))}" in texts(window)


def test_adds_makes_n_and_v_when_the_sum_overflows(app, tmp_path):
    tool, window = shown(app, tmp_path, ARITHMETIC, 3)
    assert instruction(tool).endswith("ADDS R0, R1, R2")
    words = texts(window)
    assert {"ADD", "SUB or RSB = 0", "carry in = 0", "carry out = 0", "overflow = 1",
            "ALUResult = 0x80000000"} <= set(words)
    assert tagged(window, "wire:Added") == [hex32(1)]
    assert flags_shown(window) == 0b1001 == tool.film.trace.new_flags == app.machine.cpsr >> 28
    assert statuses(window) == ["written"] * 4
    assert_laid_out(window)


def test_sub_takes_the_shifted_register_and_rsb_swaps_the_operands(app, tmp_path):
    tool, window = shown(app, tmp_path, ARITHMETIC, 5)
    assert instruction(tool).endswith("SUB R4, R3, R2, LSL #2")
    assert tool.film.trace.values["SrcB"] == 4
    words = texts(window)
    assert bit_text(4) in words and "ALUResult = 0x00000060" in words
    assert app.machine.reg(4) == 96
    assert statuses(window) == kept(tool.film.trace.flags)
    steps(app, 1)                       # RSB R5, R3, #10
    to_end(tool)
    assert "RSB R5, R3" in instruction(tool)
    words = texts(window)
    assert {"RSB", "RSB = 1", "SUB or RSB = 1", "ALUResult = SrcB minus SrcA"} <= set(words)
    assert tagged(window, "wire:First") == [hex32(10)]              # SrcB goes first
    assert tagged(window, "wire:Added") == [hex32(~100 & MASK)]     # and NOT SrcA second
    assert f"ALUResult = {hex32(-90 & MASK)}" in words and app.machine.reg(5) == -90 & MASK
    canvas, k = window.canvas, window.k
    ends = sorted((round(canvas.coords(item)[1] / k), round(canvas.coords(item)[3] / k))
                  for item in tagged(window, "wire:Swap", "line"))
    assert ends == [(132, 160), (160, 132)]                         # the swap's lines cross
    assert_laid_out(window)


def test_a_logical_operation_with_s_takes_c_from_the_shifter(app, tmp_path):
    tool, window = shown(app, tmp_path, LOGICAL, 3)
    assert instruction(tool).endswith("ANDS R0, R1, R2, LSR #1")
    trace = tool.film.trace
    assert trace.signals["ShiftC"] == "1" and trace.values["ShiftCarry"] == 1
    words = texts(window)
    assert {"AND", "from the shifter (ShiftC = 1)", "only ADD, SUB and RSB make V",
            "FlagWrite = 10: N and Z are written, and C from the shifter.",
            "ALUResult = 0x00000001"} <= set(words)
    assert shown_bits(window, "NZC") == cpsr(app, "NZC") == [0, 0, 1]
    assert statuses(window) == ["written", "written", "written", kept(trace.flags)[3]]
    assert dots(window) == [TOPS[0] + 10]
    assert_laid_out(window)
    steps(app, 1)                       # MVN R3, R2
    to_end(tool)
    words = texts(window)
    assert f"{UNUSED}: MVN takes SrcB alone" in words
    assert "ALUResult = 0xFFFFFFFC" in words and app.machine.reg(3) == 0xFFFFFFFC


def test_a_logical_operation_takes_c_only_with_shiftc(app, tmp_path):
    tool, window = shown(app, tmp_path, LOGICAL, 5)
    assert instruction(tool).endswith("ORRS R4, R1, R2")
    words = texts(window)
    assert {"ORR", "only ADD, SUB and RSB make C", "ALUResult = 0x000000FF",
            "FlagWrite = 10: N and Z are written; C and V are kept."} <= set(words)
    assert statuses(window) == ["written", "written", "kept: C stays 1", "kept: V stays 0"]
    assert shown_bits(window, "NZ") == cpsr(app, "NZ") and cpsr(app, "CV") == [1, 0]
    assert dots(window) == [TOPS[1] + 10]
    assert_laid_out(window)
    steps(app, 1)                       # ANDS R5, R1, #0xFF000000: a rotated immediate
    to_end(tool)
    words = texts(window)
    assert {"bit 31 of ExtImm (ShiftC = 1)", "ALUResult = 0x00000000",
            "FlagWrite = 10: N and Z are written, and C from ExtImm."} <= set(words)
    assert statuses(window) == ["written", "written", "written", "kept: V stays 0"]
    assert shown_bits(window, "NZC") == cpsr(app, "NZC") == [0, 1, 1]
    assert_laid_out(window)


def test_strb_ldr_and_bl_add_or_subtract_an_address_or_a_target(app, tmp_path):
    tool, window = shown(app, tmp_path, MEMORY, 3)
    assert instruction(tool).endswith("STRB R4, [R1, #1]")
    address = app.machine.reg(1) + 1
    assert f"ALUResult = {hex32(address)}" in texts(window)
    assert app.machine.read_memory(address, 1) == b"A"
    steps(app, 1)                       # LDR R5, [R1, #-4]: a negative offset subtracts
    to_end(tool)
    words = texts(window)
    assert "SUB" in words and f"ALUResult = {hex32(app.machine.reg(1) - 4)}" in words
    steps(app, 1)                       # BL function
    to_end(tool)
    assert " BL " in instruction(tool)
    assert f"ALUResult = {hex32(app.machine.pc)}" in texts(window)
    assert_laid_out(window)


def test_a_failed_condition_makes_the_flags_but_writes_none(app, tmp_path):
    tool, window = shown(app, tmp_path, FAILED, 3)
    trace = tool.film.trace
    assert trace.signals["CondEx"] == "0" and trace.signals["FlagW"] == "11"
    words = texts(window)
    assert "FlagWrite = 00: the condition failed, so no flag is written." in words
    assert f"ALUResult = {hex32(-4 & MASK)}" in words and app.machine.reg(2) == 0
    assert flags_shown(window) == trace.values["ALUFlags"] == 0b1000
    assert statuses(window) == kept(trace.flags)
    assert app.machine.cpsr >> 28 == trace.flags
    assert_laid_out(window)


def gray_without_srca(window, b):
    """Without SrcA, the adder and the units that need SrcA make no value: they are gray, and
    only MVN's input, which brings NOT SrcB, is rejected; MOV and MVN show their values."""
    canvas = window.canvas
    for _, code, _ in UNITS:
        name = next(name for name, unit, _ in UNITS if unit == code)
        shown = [canvas.itemcget(item, "text") for item in canvas.find_withtag(f"block:{name}")
                 if canvas.type(item) == "text"]
        colours = {canvas.itemcget(item, "fill") for item in canvas.find_withtag(f"block:{name}")
                   if canvas.type(item) == "text"}
        if code in xray.NO_FIRST_OPERAND:
            assert hex32(xray.alu(code, 0, b)[0]) in shown, name
        else:
            assert not any(word.startswith("0x") for word in shown) and colours == {IDLE}, name
    for tag in ("wire:First", "wire:Added", "wire:Sum", "wire:CarryOut", "wire:Overflow"):
        assert tagged(window, tag) == [], tag
    assert crosses(window) == [TOPS[5] + 10]        # MVN's NOT SrcB alone
    return True


@pytest.mark.parametrize("text", list(EXAMPLE))
def test_each_instruction_brings_the_operands_it_has(app, tmp_path, text):
    """SrcA and SrcB as the trace has them: MOV R0, #5 has no SrcA, STR R0, [R1, #4] adds its
    offset to R1 (its R0 does not come to the ALU)."""
    tool, (window,) = example(app, tmp_path, text, "ALU")
    values = tool.film.trace.values
    a, b = values["SrcA"], values["SrcB"]
    middle_of(tool)
    if a is None:                           # before the ALU's step, too
        assert f"{UNUSED}: MOV takes SrcB alone" in texts(window)
    to_end(tool)
    words = texts(window)
    if a is None:
        assert text == "MOV R0, #5" and f"{UNUSED}: MOV takes SrcB alone" in words
        assert gray_without_srca(window, b)
    else:
        assert hex32(a) in words and bit_text(a) in words
    assert hex32(b) in words and bit_text(b) in words
    if text.startswith("STR"):
        assert b == 4 and a == tool._context.registers_before[1]
    assert f"ALUResult = {hex32(values['ALUResult'])}" in words
    assert f"ALUFlags NZCV = {values['ALUFlags']:04b}" in words
    assert_laid_out(window)


# Playing with the film -----------------------------------------------------------------------

def test_the_alu_is_idle_then_at_work_then_finished(app, tmp_path):
    tool, window = shown(app, tmp_path, LARGEST, 7)
    film = tool.film
    canvas = window.canvas
    at_share(tool, -0.02)
    assert phase(film, tool.player.moment, "ALU")[0] == IDLE_STATE
    assert texts(window).count("(not here yet)") == 2 and lit(window) == set()
    assert "SUB" not in texts(window)
    assert_laid_out(window)
    at_share(tool, 0.15)                # SrcA, SrcB and ALUControl arrive
    assert phase(film, tool.player.moment, "ALU")[0] == WORKING
    assert hex32(12) in texts(window) and lit(window) == set() and "SUB" not in texts(window)
    travelling = [item for item in tagged(window, "wire:SrcA", "line")
                  if canvas.itemcget(item, "fill") == net_colours(film.trace)["SrcA"]]
    assert any(canvas.itemcget(item, "state") == "hidden" for item in travelling)
    at_share(tool, 0.29)
    assert all(canvas.itemcget(item, "state") != "hidden" for item in travelling)
    assert_laid_out(window)
    at_share(tool, 0.45)                # every unit works, with the adder's multiplexers
    assert "SUB" in texts(window)
    assert lit(window) == {"Swap", "Not", "SecondMux", "CarryMux", "Adder", "AND", "ORR", "EOR",
                           "BIC", "MOV", "MVN"}
    assert "ALUResult = SrcA minus SrcB" in texts(window)
    assert not any(word.startswith("ALUResult = 0x") for word in texts(window))
    assert_laid_out(window)
    at_share(tool, 0.7)                 # the multiplexer takes the adder's sum
    assert lit(window) == {"Swap", "Not", "SecondMux", "CarryMux", "Adder", "ResultMux"}
    assert not any(word.startswith("N = ") for word in texts(window))
    assert_laid_out(window)
    at_share(tool, 0.95)                # the result and the flags have left
    assert "ALUResult = 0x0000000C" in texts(window) and flags_shown(window) == 0b0010
    assert_laid_out(window)
    to_end(tool)
    assert phase(film, tool.player.moment, "ALU")[0] == DONE
    assert lit(window) == set() and "ALUResult = 0x0000000C" in texts(window)


def test_drawing_again_only_when_the_part_changes_draws_what_drawing_all_draws(app, tmp_path):
    """Within a film the window is drawn again only when the part of the ALU's step changes,
    and when its step ends it only puts out its light: at every moment, forwards and after
    playing again from the end, that is the picture a whole redraw makes."""
    tool, window = shown(app, tmp_path, LARGEST, 7)         # CMP R3, R0
    film = tool.film
    step = steps_of(film, "ALU")[0]
    moments = [film.seconds * number / 40 for number in range(41)]
    moments += [step.start + step.duration * share for share in (0.1, 0.4, 0.7, 0.9, 1.0)]
    for play in range(2):
        for moment in sorted(moments):
            at(tool, tool.player.start + moment - tool.test_clock.now)
            parts = drawn(window)
            window.key = None                               # draw it all again
            window.draw(film, tool.player.moment, tool._context)
            assert drawn(window) == parts, (play, moment)
        tool.player.play(tool.film)                         # back to the start, from the end
    tool.stop_film()


def test_without_an_instruction_inside_the_datapath_the_alu_stays_gray(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    tool = opened(app)                  # not connected: no instruction
    window = tool.open_inside("ALU")
    assert "No instruction is shown." in texts(window)
    tool.connect_button.invoke()
    steps(app, 2)                       # SVC #4: the system performs it
    to_end(tool)
    words = texts(window)
    assert "An SVC does not use the ALU: the system performs the service." in words
    assert not any(word.startswith("0x") for word in words) and lit(window) == set()
    assert {window.canvas.itemcget(item, "fill") for item in window.canvas.find_all()
            if window.canvas.type(item) == "line"} == {IDLE}
    assert_laid_out(window)


@pytest.mark.parametrize("zoom", [1.0, 1.1, 1.3, 1.45, 1.6])
def test_nothing_overlaps_at_any_zoom(app, tmp_path, zoom):
    loaded(app, tmp_path, MIXED)
    tool = connected(app)
    tool._make_canvas(zoom)
    window = tool.open_inside("ALU")
    for _ in range(16):
        steps(app, 1)
        if steps_of(tool.film, "ALU"):     # not an SVC, which does not use the ALU
            for share in (0.15, 0.45, 0.7, 0.95):
                at_share(tool, share)
                assert_laid_out(window)
        to_end(tool)
        assert_laid_out(window)


MULTIPLIES = """\
        .global _start
_start: MOV     R4, #3
        MOV     R5, #7
        MOV     R6, #0x15
        MLA     R3, R4, R5, R6
        MULS    R7, R5, R4
        ADD     R8, R4, R5
        SVC     #10
"""


def test_the_multiplier_works_for_mla_and_mul_only(app, tmp_path):
    """MLA: SrcA x SrcB + RD4 through ALUControl 1010, every other unit rejected; MULS: no RD4,
    N and Z written; ADD: the multiplier, an addition, stays gray, with no value and no cross."""
    tool, window = shown(app, tmp_path, MULTIPLIES, 4)      # MLA R3, R4, R5, R6
    words = texts(window)
    assert {"MLA", "ALUResult = SrcA x SrcB + RD4", "ALUControl = 1010", "SrcA x SrcB + RD4",
            hex32(0x15), bit_text(0x15), "ALUResult = 0x0000002A"} <= set(words)
    assert hex32(0x2A) in tagged(window, "block:Multiplier")
    assert dots(window) == [round(MUL_Y)]
    assert crosses(window) == sorted([SUM_Y] + [top + 10 for top in TOPS])
    assert_laid_out(window)
    steps(app, 1)                           # MULS R7, R5, R4
    to_end(tool)
    words = texts(window)
    assert "SrcA x SrcB" in words and f"{UNUSED}: MUL adds nothing to the product" in words
    assert "FlagWrite = 10: N and Z are written; C and V are kept." in words
    assert hex32(21) in tagged(window, "block:Multiplier") and app.machine.reg(7) == 21
    assert_laid_out(window)
    steps(app, 1)                           # ADD R8, R4, R5
    to_end(tool)
    assert round(MUL_Y) not in crosses(window) and dots(window) == [SUM_Y]
    assert not any(word.startswith("0x") for word in tagged(window, "block:Multiplier"))
    assert_laid_out(window)


def test_the_multipliers_step_drawn_in_parts_is_drawn_as_a_whole(app, tmp_path):
    """MLA: at every moment, forwards and after playing again from the end, the window drawn again only
    when the part of the ALU's step changes is the picture a whole redraw makes."""
    tool, window = shown(app, tmp_path, MULTIPLIES, 4)
    film = tool.film
    step = steps_of(film, "ALU")[0]
    moments = [film.seconds * number / 40 for number in range(41)]
    moments += [step.start + step.duration * share for share in (0.1, 0.4, 0.7, 0.9, 1.0)]
    for play in range(2):
        for moment in sorted(moments):
            at(tool, tool.player.start + moment - tool.test_clock.now)
            parts = drawn(window)
            window.key = None
            window.draw(film, tool.player.moment, tool._context)
            assert drawn(window) == parts, (play, moment)
        tool.player.play(tool.film)
    tool.stop_film()



MOVES = """\
        .global _start
_start: MOVW    R3, #0x8001
        MOVT    R3, #0xFFFE
        SVC     #10
"""


def test_movt_joins_the_low_half_of_srcb_to_the_low_half_of_rd4(app, tmp_path):
    """MOVT R3, #0xFFFE: ALUControl 1110 takes the unit of MOVT, which shows the two halves; RD4
    comes in, SrcA does not; MOVW before it passes SrcB on (MOV), and the MOVT unit, an
    addition, stays gray."""
    tool, window = shown(app, tmp_path, MOVES, 1)           # MOVW R3, #0x8001
    assert dots(window) == [TOPS[4] + 10]                   # MOV
    assert not any(word.startswith("0x") for word in tagged(window, "block:MOVT"))
    assert_laid_out(window)
    steps(app, 1)
    to_end(tool)
    words = texts(window)
    assert {"MOVT", "ALUResult = SrcB[15:0] : RD4[15:0]", "ALUControl = 1110", hex32(0x8001),
            "ALUResult = 0xFFFE8001", f"{UNUSED}: MOVT takes SrcB and RD4"} <= set(words)
    assert "SrcB[15:0] 0xFFFE : RD4[15:0] 0x8001" in tagged(window, "block:MOVT")
    assert hex32(0xFFFE8001) in tagged(window, "block:MOVT")
    assert dots(window) == [round(MOVT_Y)]
    assert crosses(window) == sorted([TOPS[4] + 10, TOPS[5] + 10])  # MOV and MVN: SrcB alone
    assert_laid_out(window)
