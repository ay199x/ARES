# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The ARM X-Ray's window inside the control unit: the truth tables of the Main Decoder and the
ALU Decoder with the instruction's rows, the PC Logic, and the Conditional Logic with the flags
register, the condition check and the gates, Syscall's among them; what it shows of bits that
are no field; how it plays with the film and follows the program."""

import pytest
from test_gui_run import loaded
from test_gui_xray import LARGEST, at, connected, steps, to_end
from test_gui_xray_inside import (EXAMPLE, Event, block_point, drawn, example, joined, texts,
                                  within)
from xray_layout import clashes

from ares import xray, xray_film
from ares.gui.tools import xray_inside
from ares.gui.tools.xray_inside import (DONE, IDLE, IDLE_STATE, OFF, ON, UNUSED, WORKING,
                                        WORKING_FILL, phase)
from ares.gui.tools.xray_inside_control import (GATE_X, MORE_ABOUT, MORE_NAME, NOT_YET, OUT_X,
                                                OUTSIDE, PC_LOGIC_Y, ControlWindow,
                                                control_steps)

PROGRAM = """\
        .global _start
_start: MOV     R1, #5              @ 1
        MVN     R2, #2              @ 2: R2 = -3
        ADDS    R3, R1, R2          @ 3: the ADD row with S 1
        SUB     R4, R1, R2, LSL #1  @ 4: a shift
        LDR     R5, =buffer         @ 5
        STRB    R1, [R5]            @ 6: a byte store
        ADD     R6, R5, #4          @ 7
        LDR     R0, [R6, #-4]       @ 8: a negative offset subtracts
        CMP     R1, R2              @ 9
        MOVLE   R7, #1              @ 10: the condition fails
        BL      function            @ 11
        MOVS    R8, R1, LSL #30     @ 13: C comes from the shifter
        SVC     #10                 @ 14
function:
        MOV     PC, LR              @ 12: Rd 15 with RegW 1
        .data
buffer: .word   0
"""
LINKED = """\
        .global _start
_start: BL      function
        SVC     #10
function:
        BX      LR
"""
CALLS = """\
        .global _start
_start: MOV     R0, #7
        ADD     R1, R0, R0          @ 2
        SVC     #1                  @ 3: prints 7
        CMP     R0, R0              @ 4: Z = 1
        SVCNE   #1                  @ 5: does not run
        SVC     #10
"""
RD_UNUSED = f"Rd: {UNUSED}"


def opened_on(app, tmp_path, source):
    loaded(app, tmp_path, source)
    tool = connected(app)
    return tool, tool.open_inside("Control")


def shown(app, tool, count, text):
    """Run count more instructions, show the last one finished and check that it is text."""
    steps(app, count)
    to_end(tool)
    trace = tool.model.view.trace
    assert trace.text.startswith(text), trace.text
    return trace


def show_at(tool, seconds):
    """Show the tool's film, and the window with it, at seconds from the film's start."""
    at(tool, tool.player.start + seconds - tool.test_clock.now)


def chosen(window, table):
    """The texts of the row that lights in table ("main" or "alu"), in their order."""
    canvas = window.canvas
    return [canvas.itemcget(item, "text") for item in canvas.find_withtag("chosen")
            if table in canvas.gettags(item) and canvas.type(item) == "text"]


def item(window, text):
    canvas = window.canvas
    found = [item for item in canvas.find_all()
             if canvas.type(item) == "text" and canvas.itemcget(item, "text") == text]
    assert found, f"{text!r} is not in {texts(window)}"
    return found[0]


def colour(window, text):
    return window.canvas.itemcget(item(window, text), "fill")


def lit(window):
    """The texts inside the rectangles filled as a part at work."""
    canvas = window.canvas
    boxes = [canvas.bbox(box) for box in canvas.find_all()
             if canvas.type(box) == "rectangle" and canvas.itemcget(box, "fill") == WORKING_FILL]
    inside = []
    for left, top, right, bottom in boxes:
        inside += [canvas.itemcget(item, "text") for item in canvas.find_all()
                   if canvas.type(item) == "text" and canvas.itemcget(item, "text")
                   and left <= canvas.bbox(item)[0] and canvas.bbox(item)[2] <= right
                   and top <= canvas.bbox(item)[1] and canvas.bbox(item)[3] <= bottom]
    return inside


def flat(text):
    """text on one line: a text drawn on two lines is the same words."""
    return " ".join(text.split())


def item_at(window, text):
    """Where the text item that says text lies, in design pixels: (left, top, right, bottom)."""
    left, top, right, bottom = window.canvas.bbox(item(window, text))
    return left / window.k, top / window.k, right / window.k, bottom / window.k


def compared(window):
    """The values written over the wires that leave the PC Logic's comparison and its AND gate."""
    canvas, k = window.canvas, window.k
    found = []
    for shape in canvas.find_all():
        if canvas.type(shape) != "text" or not canvas.itemcget(shape, "text"):
            continue
        left, top, right, bottom = canvas.bbox(shape)
        x, y = (left + right) / 2 / k, (top + bottom) / 2 / k
        if 130 < x < 280 and PC_LOGIC_Y + 10 < y < PC_LOGIC_Y + 32:
            found.append(canvas.itemcget(shape, "text"))
    return found


def main_row(trace):
    """What the Main Decoder's row of trace says: its name, inputs and signals."""
    name = {xray.DP_REGISTER: "DP reg", xray.DP_IMMEDIATE: "DP imm", xray.STORE_IMMEDIATE: "STR",
            xray.LOAD_IMMEDIATE: "LDR", xray.BRANCH: "B", xray.LOAD_REGISTER: "LDR reg",
            xray.STORE_REGISTER: "STR reg", xray.BRANCH_LINK: "BL",
            xray.BRANCH_EXCHANGE: "BX", xray.MULTIPLY: "MUL", xray.MOVE_16: "MOVW/T",
            xray.LOAD_HALF_IMMEDIATE: "LDRH imm", xray.LOAD_HALF_REGISTER: "LDRH reg",
            xray.STORE_HALF_IMMEDIATE: "STRH imm", xray.STORE_HALF_REGISTER: "STRH reg"}[trace.kind]
    return [name] + [trace.signals[signal] for signal in xray.MAIN_SIGNALS]


# Opening and closing -------------------------------------------------------------------------

def test_a_click_on_the_control_unit_opens_its_window_and_closing_works(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    tool = connected(app)
    tool._clicked(Event(*block_point(tool, "Control")))
    window = tool.insides["Control"]
    assert isinstance(window, ControlWindow)
    assert xray_inside.window_class("Control") is ControlWindow
    assert window.window.title() == "ARM X-Ray: Inside the Control Unit"
    # It fits 1366 x 768 at 100 %, with its title bar and frame, above the taskbar.
    assert window.SIZE[0] <= 840 and window.SIZE[1] + 31 + 8 <= 768 - 48
    window.close()
    assert tool.insides == {} and window.window is None
    window = tool.open_inside("Control")
    tool.close()
    assert window.window is None


# The decoders ------------------------------------------------------------------------------

def test_the_main_decoder_lights_the_row_of_each_class_and_follows_the_program(app, tmp_path):
    tool, window = opened_on(app, tmp_path, LARGEST)
    for count, text in ((1, "LDR"), (5, "LDR"), (1, "CMP"), (2, "ADD"), (2, "BNE")):
        trace = shown(app, tool, count, text)
        word = trace.word
        row = chosen(window, "main")
        name, inputs, signals = row[0], row[1:6], row[6:]
        expected = main_row(trace)
        assert [name] + signals == expected                    # the row of the table ...
        assert signals == [trace.signals[s] for s in xray.MAIN_SIGNALS]     # ... is the trace's
        words = joined(window)
        branch = trace.kind == xray.BRANCH                      # bits 22 and 20 lie in imm24
        funct2, funct0 = ("-", "-") if branch else (str(word >> 22 & 1), str(word >> 20 & 1))
        assert f"In {word >> 26 & 3:02b} {word >> 25 & 1} {funct2} {funct0}" in words
        assert inputs[0] == f"{word >> 26 & 3:02b}"
        assert clashes(window.canvas) == []


def test_bl_and_bx_light_their_own_rows(app, tmp_path):
    tool, window = opened_on(app, tmp_path, LINKED)
    trace = shown(app, tool, 1, "BL")
    assert chosen(window, "main")[0] == "BL" and trace.signals["PCS"] == "1"
    trace = shown(app, tool, 1, "BX")
    assert chosen(window, "main")[0] == "BX"
    assert chosen(window, "alu") == ["BX", "0", "1001", "0", "0111", "00", "0"]
    assert clashes(window.canvas) == []


def test_the_alu_decoder_lights_the_row_of_cmd_or_the_line_of_alu_op_0(app, tmp_path):
    tool, window = opened_on(app, tmp_path, PROGRAM)
    shown(app, tool, 2, "MVN")
    assert chosen(window, "alu") == ["MVN", "0", "1111", "0", "1000", "00", "0"]
    trace = shown(app, tool, 1, "ADDS")
    assert chosen(window, "alu") == ["ADD", "0", "0100", "1", trace.signals["ALUControl"],
                                     trace.signals["FlagW"], trace.signals["NoWrite"]]
    assert chosen(window, "alu")[4:] == ["0000", "11", "0"]
    assert "ADD 0 0100 0/1 0000 00/11 0" not in joined(window)  # the lit row is S 1's
    shown(app, tool, 2, "LDR")
    assert chosen(window, "alu") == ["ALUOp 0: ALUControl 0000 (ADD), FlagW 00"]
    assert "In 0 - -" in joined(window)     # a load's bits 24:20 are no cmd and no S
    trace = shown(app, tool, 3, "LDR")                       # LDR R0, [R6, #-4]
    assert trace.signals["ALUControl"] == xray.ALU_SUB
    assert chosen(window, "alu") == ["ALUOp 0, U 0 (offset down): 0001 (SUB)"]
    shown(app, tool, 1, "CMP")
    assert chosen(window, "alu") == ["CMP", "0", "1010", "1", "0001", "11", "1"]
    assert clashes(window.canvas) == []


# The PC Logic and the Conditional Logic -----------------------------------------------------

def test_the_pc_logic_makes_pcs_from_rd_regw_and_branch(app, tmp_path):
    tool, window = opened_on(app, tmp_path, PROGRAM)
    shown(app, tool, 3, "ADDS")
    assert "PCS 0" in texts(window) and "Branch 0" in texts(window)
    trace = shown(app, tool, 9, "MOV")                      # MOV PC, LR
    assert trace.signals["PCS"] == "1" and trace.signals["Branch"] == "0"
    words = texts(window)
    assert "Rd 1111 (R15)" in words and "RegW 1" in words and "PCS 1" in words
    assert colour(window, "PCS 1") == ON and colour(window, "Branch 0") == OFF
    assert clashes(window.canvas) == []


def test_the_condition_check_and_the_gates_show_the_trace(app, tmp_path):
    tool, window = opened_on(app, tmp_path, LARGEST)
    shown(app, tool, 7, "CMP")
    words = texts(window)
    assert "AL: always -> CondEx 1" in words
    assert "NoWrite 1" in words and "RegW 1" in words and "RegWrite 0" in words
    assert "FlagW 11" in words and "FlagWrite 11" in words
    trace = shown(app, tool, 4, "BNE")
    assert trace.condition == "NE: Z = 0, executes"
    words = texts(window)
    assert "NE holds when Z = 0" in words and "NE: Z = 0 -> CondEx 1" in words
    for name in ("PCSrc", "RegWrite", "MemWrite"):
        value = trace.signals[name]
        assert f"{name} {value}" in words
        assert colour(window, f"{name} {value}") == (ON if value == "1" else OFF)
    assert colour(window, "PCSrc 1") == ON
    machine = tool.model.machine
    assert machine.pc == trace.values["PC'"] != trace.pc + 4     # the branch was taken
    assert clashes(window.canvas) == []


def test_a_failed_condition_closes_every_gate(app, tmp_path):
    tool, window = opened_on(app, tmp_path, PROGRAM)
    trace = shown(app, tool, 10, "MOVLE")
    assert trace.condition == "LE: Z = 0, N = 0, V = 0, does not execute"
    words = texts(window)
    assert "LE holds when Z = 1 or N ≠ V" in words
    assert "LE: Z = 0, N = 0, V = 0 -> CondEx 0" in words
    assert "RegW 1" in words and "RegWrite 0" in words and "PCSrc 0" in words
    assert colour(window, "RegW 1") == ON and colour(window, "RegWrite 0") == OFF
    assert "kept: FlagWrite is 00" in words
    context = tool._make_context()
    assert context.registers_after[7] == context.registers_before[7]   # R7 was not written
    assert clashes(window.canvas) == []


def test_the_flags_register_takes_the_alu_flags_at_their_step(app, tmp_path):
    tool, window = opened_on(app, tmp_path, PROGRAM)
    steps(app, 3)                                           # ADDS R3, R1, R2
    film = tool.film
    old = xray.flag_text(film.trace.flags)
    new = f"{tool.model.machine.cpsr >> 28:04b}"
    assert new == xray.flag_text(film.trace.new_flags) and new != old
    decoding, writing = control_steps(film)
    step = film.steps[writing]
    show_at(tool, step.start + step.duration * 0.25)
    assert old in texts(window) and "ALUFlags 0010" in texts(window)
    assert "Flags (NZCV)" in lit(window)                    # at work: it opens
    assert "all four written" not in texts(window)
    show_at(tool, step.start + step.duration * 0.75)        # the same step: it has taken them
    assert f"{new} (was {old})" in texts(window) and "all four written" in texts(window)
    to_end(tool)
    assert f"{new} (was {old})" in texts(window) and lit(window) == []
    assert clashes(window.canvas) == []
    shown(app, tool, 1, "SUB")                              # no S: the flags stay
    assert "kept: FlagWrite is 00" in texts(window) and "FlagW 00" in texts(window)
    trace = shown(app, tool, 9, "LSLS")                     # MOVS R8, R1, LSL #30
    assert trace.signals["FlagWrite"] == "10" and trace.signals["ShiftC"] == "1"
    old, new = xray.flag_text(trace.flags), f"{tool.model.machine.cpsr >> 28:04b}"
    assert new != old and f"{new} (was {old})" in texts(window)
    assert "N, Z and C written" in texts(window) and "FlagWrite 10" in texts(window)
    assert clashes(window.canvas) == []


def test_the_decoders_other_signals_are_shown(app, tmp_path):
    tool, window = opened_on(app, tmp_path, PROGRAM)
    shown(app, tool, 4, "SUB")
    assert "Shift 1" in texts(window) and colour(window, "Shift 1") == ON
    trace = shown(app, tool, 2, "STRB")
    words = texts(window)
    assert "Size 10" in words and "MemW 1" in words and "MemWrite 1" in words
    assert "Signed 0" in words and colour(window, "Size 10") == ON
    assert "ShiftC 0" not in words                          # the shifter's carry comes in
    assert tool.model.machine.read_memory(trace.values["ALUResult"], 1) == bytes([5])
    assert chosen(window, "main") == main_row(trace)[:1] + ["01", "0", "X", "0", "X"] + \
        main_row(trace)[1:]
    assert clashes(window.canvas) == []


# Playing with the film ---------------------------------------------------------------------

def test_it_is_idle_before_its_step_at_work_during_it_and_finished_after(app, tmp_path):
    tool, window = opened_on(app, tmp_path, LARGEST)
    steps(app, 7)                                           # CMP R3, R0: the film plays
    film = tool.film
    decoding, writing = control_steps(film)
    step = film.steps[decoding]
    show_at(tool, 0.0)
    assert phase(film, tool.player.moment, "Control")[0] == IDLE_STATE
    assert NOT_YET in texts(window) and chosen(window, "main") == [] and lit(window) == []
    assert "Cond" in texts(window) and "PCSrc" in texts(window)
    assert clashes(window.canvas) == []
    show_at(tool, step.start + step.duration * 0.1)        # the fields come in
    assert phase(film, tool.player.moment, "Control")[0] == WORKING
    assert NOT_YET not in texts(window) and "Cond 1110" in texts(window)
    assert chosen(window, "main") == []
    show_at(tool, step.start + step.duration * 0.4)        # the same step: the rows light
    assert chosen(window, "main")[0] == "DP reg" and chosen(window, "alu")[0] == "CMP"
    assert "DP reg" in lit(window) and "CMP" in lit(window)
    assert "= 15" not in lit(window)                        # CMP has no Rd to compare
    assert "Condition Check" not in lit(window)
    assert "PCSrc" in texts(window) and "PCSrc 0" not in texts(window)
    assert clashes(window.canvas) == []
    show_at(tool, step.start + step.duration * 0.8)        # then the gates answer
    assert "Condition Check" in lit(window) and "AL: always -> CondEx 1" in texts(window)
    assert "DP reg" in lit(window) and "CMP" in lit(window)  # lit to the end of the step
    assert "PCSrc 0" in texts(window) and "RegWrite 0" in texts(window)
    assert clashes(window.canvas) == []
    show_at(tool, film.steps[decoding + 1].start + 0.01)   # its step is over: nothing at work
    assert lit(window) == [] and chosen(window, "main")[0] == "DP reg"
    assert "ALUFlags" in texts(window)                      # the ALU has not worked yet
    to_end(tool)
    assert phase(film, tool.player.moment, "Control")[0] == DONE
    assert lit(window) == [] and chosen(window, "alu")[0] == "CMP"
    assert "all four written" in texts(window)
    assert clashes(window.canvas) == []


def test_changing_only_what_the_stage_changes_draws_what_drawing_all_draws(app, tmp_path):
    """Within a film the window styles its tables in place and draws again only the parts
    whose Stage changed: at every moment, forwards and after playing again from the end, that is the
    picture a whole redraw makes."""
    tool, window = opened_on(app, tmp_path, PROGRAM)
    steps(app, 3)                                           # ADDS R3, R1, R2: the flags change
    film = tool.film
    for play in range(2):
        for number in range(41):
            show_at(tool, film.seconds * number / 40)
            parts = drawn(window)
            window.key = None                               # draw it all again
            window.draw(film, tool.player.moment, tool._context)
            assert drawn(window) == parts, (play, number)
        tool.player.play(tool.film)                         # back to the start, from the end
    tool.stop_film()


@pytest.mark.parametrize("zoom", [1.0, 1.6])
def test_it_has_no_overlaps_at_the_smallest_and_largest_zoom(app, tmp_path, zoom):
    loaded(app, tmp_path, PROGRAM)
    tool = connected(app)
    tool._make_canvas(zoom)
    tool.show()
    window = tool.open_inside("Control")
    assert window.zoom == pytest.approx(zoom)
    for count, text in ((3, "ADDS"), (5, "LDR"), (2, "MOVLE"), (2, "MOV")):
        shown(app, tool, count, text)
        assert clashes(window.canvas) == []
        width, height = window.SIZE
        for shape in window.canvas.find_all():
            left, top, right, bottom = window.canvas.bbox(shape)
            assert right <= width * window.k + 1 and bottom <= height * window.k + 1


def test_an_svc_lights_its_row_and_sends_syscall(app, tmp_path):
    tool, window = opened_on(app, tmp_path, LARGEST)
    trace = shown(app, tool, 2, "SVC")
    assert trace.kind == xray.SYSTEM_CALL
    assert chosen(window, "main")[0] == "SVC" and OUTSIDE not in texts(window)
    assert chosen(window, "alu") == []                      # the ALU does not work for it
    assert "Syscall 1" in texts(window) and "PCS 0" in texts(window)
    assert NOT_YET not in texts(window)
    assert "In 11 1 - -" in joined(window) and "In 0 - -" in joined(window)    # imm24
    assert clashes(window.canvas) == []
    shown(app, tool, 1, "LDR")                              # and the next one is a load again
    assert chosen(window, "main")[0] == "LDR" and "Syscall 0" in texts(window)


@pytest.mark.parametrize("zoom", [1.0, 1.6])
@pytest.mark.parametrize("count, text, svc, condex, syscall", [
    (2, "ADD", "0", "1", "0"), (3, "SVC", "1", "1", "1"), (5, "SVCNE", "1", "0", "0"),
], ids=["add", "svc", "svcne-fails"])
def test_syscall_leaves_an_and_gate_of_svc_and_condex(app, tmp_path, zoom, count, text, svc,
                                                      condex, syscall):
    """The Conditional Logic lets the Decoder's SVC through only when the condition holds:
    Syscall = SVC AND CondEx, drawn as the other gates are, with its inputs at the left and
    its output leaving at the right."""
    loaded(app, tmp_path, CALLS)
    tool = connected(app)
    tool._make_canvas(zoom)
    window = tool.open_inside("Control")
    trace = shown(app, tool, count, text)
    assert trace.signals["CondEx"] == condex and trace.signals["Syscall"] == syscall
    assert (trace.kind == xray.SYSTEM_CALL) == (svc == "1")
    words = texts(window)
    assert f"SVC {svc}" in words and f"Syscall {syscall}" in words
    assert colour(window, f"SVC {svc}") == (ON if svc == "1" else OFF)
    assert colour(window, f"Syscall {syscall}") == (ON if syscall == "1" else OFF)
    assert colour(window, f"CondEx {condex}") == (ON if condex == "1" else OFF)
    left, top, right, bottom = item_at(window, f"SVC {svc}")
    assert right <= GATE_X                                  # an input of a gate
    left, top, right, bottom = item_at(window, f"Syscall {syscall}")
    assert left >= OUT_X                                    # and an output at the right
    later = texts(window)[texts(window).index(MORE_NAME):]
    assert not any(word.startswith("Syscall") for word in later)
    assert [word for word in words if word.startswith("Syscall")] == [f"Syscall {syscall}"]
    assert clashes(window.canvas) == []
    within(window)


@pytest.mark.parametrize("text", list(EXAMPLE))
def test_bits_that_are_no_field_tell_the_decoders_nothing(app, tmp_path, text):
    """Without an Rd field (CMP, a branch) the PC Logic's comparison with 15 gets nothing; the
    Funct0 of a branch lies in imm24; ALUFlags come from the trace."""
    tool, (window,) = example(app, tmp_path, text, "Control")
    to_end(tool)
    trace = tool.film.trace
    word, values = trace.word, trace.values
    flats = [flat(word_shown) for word_shown in texts(window)]
    rd = word >> 12 & 0xF
    if "Rd" in xray_film.present(trace):
        assert f"Rd {rd:04b} (R{rd})" in flats and RD_UNUSED not in flats
        assert compared(window) == ["1" if rd == 15 else "0", "0"]     # RegW AND Rd = 15
    else:
        assert text in ("CMP R3, R0", "BNE")
        assert RD_UNUSED in flats and not any(word_shown.startswith("Rd ") for word_shown in flats)
        assert colour(window, "= 15") == IDLE and compared(window) == []
    funct2, funct0 = ("-", "-") if text == "BNE" else (str(word >> 22 & 1), str(word >> 20 & 1))
    assert f"In {word >> 26 & 3:02b} {word >> 25 & 1} {funct2} {funct0}" in joined(window)
    assert f"ALUFlags {values['ALUFlags']:04b}" in texts(window)
    assert clashes(window.canvas) == []
    within(window)


MULTIPLIES = """\
        .global _start
_start: MOV     R4, #3
        MOV     R5, #7
        MOV     R6, #0x15
        MLA     R3, R4, R5, R6      @ 4
        MULS    R0, R4, R5          @ 5
        MLA     R10, R11, R12, R14  @ 6
        SVC     #10
"""


@pytest.mark.parametrize("zoom", [1.0, 1.6])
def test_mul_and_mla_light_their_rows_with_op2_and_mul(app, tmp_path, zoom):
    """Op2 1001 lights the Main Decoder's MUL row, whose Mul is 1; with Mul 1 the ALU Decoder
    lights MLA's or MUL's row by cmd; the PC Logic compares bits 15:12, Ra of MLA, no field of
    MUL."""
    loaded(app, tmp_path, MULTIPLIES)
    tool = connected(app)
    tool._make_canvas(zoom)
    window = tool.open_inside("Control")
    shown(app, tool, 4, "MLA")
    row = chosen(window, "main")
    assert row[:6] == ["MUL", "00", "0", "X", "X", "1001"] and row[-1] == "1"
    assert chosen(window, "alu") == ["MLA", "1", "0001", "0", "1010", "00", "0"]
    words = joined(window)
    assert "In 00 0 0 0 1001" in words and "In 1 0001 0" in words
    assert "Ra 0110 (R6)" in [flat(word) for word in texts(window)]
    assert clashes(window.canvas) == []
    within(window)
    shown(app, tool, 1, "MULS")
    assert chosen(window, "alu") == ["MUL", "1", "0000", "1", "1001", "10", "0"]
    assert "15:12: no field of MUL, which writes 19:16" in [flat(word) for word in texts(window)]
    assert compared(window) == []
    assert clashes(window.canvas) == []
    within(window)
    shown(app, tool, 1, "MLA")              # two-digit registers
    assert "Ra 1110 (R14)" in [flat(word) for word in texts(window)]
    assert clashes(window.canvas) == []
    within(window)



MOVES_AND_HALVES = """\
        .global _start
_start: LDR     R1, =cell
        MOVW    R2, #0x80FE         @ 2
        MOVT    R2, #0x1234         @ 3
        STRH    R2, [R1], #2        @ 4
        LDRSB   R3, [R1, -R0]       @ 5
        SVC     #10
        .data
cell:   .word   0
"""


def test_movw_movt_and_the_halfword_transfers_light_their_rows(app, tmp_path):
    """MOVW and MOVT share a row of the Main Decoder (ImmSrc 100); the ALU Decoder tells them
    apart by cmd with S 0. STRH and LDRSB light the rows that Op2 1SH1 and Funct2 choose, and
    the Decoder sends Size and Signed."""
    tool, window = opened_on(app, tmp_path, MOVES_AND_HALVES)
    trace = shown(app, tool, 2, "MOVW")
    row = chosen(window, "main")
    assert row == main_row(trace)[:1] + ["00", "1", "X", "0", "X"] + main_row(trace)[1:]
    assert "In 00 1 0 0 -" in joined(window)                # bits 7:4 are no op2 of MOVW
    assert row[1 + 5 + 4] == "100"                          # ImmSrc
    assert chosen(window, "alu") == ["MOVW", "0", "1000", "0", "0111", "00", "0"]
    assert clashes(window.canvas) == []
    shown(app, tool, 1, "MOVT")
    assert chosen(window, "main")[0] == "MOVW/T"
    assert chosen(window, "alu") == ["MOVT", "0", "1010", "0", "1110", "00", "0"]
    assert "In 0 1010 0" in joined(window)
    trace = shown(app, tool, 1, "STRH")
    assert chosen(window, "main") == main_row(trace)[:1] + ["00", "0", "1", "0", "1011"] + \
        main_row(trace)[1:]
    assert "Size 01" in texts(window) and "Signed 0" in texts(window)
    trace = shown(app, tool, 1, "LDRSB")
    assert chosen(window, "main") == main_row(trace)[:1] + ["00", "0", "0", "1", "1SH1"] + \
        main_row(trace)[1:]
    assert "In 00 0 0 1 1101" in joined(window)
    assert colour(window, "Signed 1") == ON and "Size 10" in texts(window)
    assert chosen(window, "alu") == ["ALUOp 0, U 0 (offset down): 0001 (SUB)"]
    assert clashes(window.canvas) == []
    within(window)


def test_a_pass_brings_passreg_to_the_pc_logic_as_its_bits(app, tmp_path):
    """POP {R4, PC}: in each pass the PC Logic compares PassReg, which comes in as its four bits,
    with 15; the pass counter's line names the register."""
    from test_gui_xray import MULTIPLE
    tool, window = opened_on(app, tmp_path, MULTIPLE)
    steps(app, 12)
    assert tool.model.view.trace.text == "POP {R4, PC}"
    for sub in tool.film.passes:
        tool.stop_film()
        tool.player.play(tool.film, sub.offset + sub.seconds * 0.999)
        tool.player.pause()
        register = sub.trace.values["PassReg"]
        words = [flat(word) for word in texts(window)]
        assert f"PassReg {register:04b}" in words
        assert any(word.startswith(f"pass {sub.trace.number} of 2: PassReg R{register}, ")
                   for word in words)
        assert compared(window)[0] == ("1" if register == 15 else "0")     # PassReg = 15
        assert clashes(window.canvas) == []
        within(window)


def test_the_decoder_s_other_signals_have_a_name_with_a_tip(app, tmp_path):
    tool, window = opened_on(app, tmp_path, PROGRAM)
    shown(app, tool, 6, "STRB")
    assert MORE_NAME in texts(window) and "The Decoder also sends:" not in texts(window)
    assert window.tips["tip:more"] == MORE_ABOUT
    left, top, right, bottom = window.canvas.bbox(item(window, MORE_NAME))
    assert window.tip_at((left + right) // 2, (top + bottom) // 2) == "tip:more"
