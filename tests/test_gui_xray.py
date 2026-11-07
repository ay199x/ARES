# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The ARM X-Ray's window: the diagram, what it shows and when, Play, and that it costs nothing."""

import time

import pytest
from test_gui_assemble import assemble
from test_gui_run import go_to_end, loaded, max_speed, run_until, slow

from conftest import ROOT

from ares import credits, xray
from ares.gui.style import NAVY, SHADOW
from ares.gui.tools import TOOLS
from ares.gui.tools import xray as tool
from ares.gui.tools.xray import (BOXES, CLOCKS, DOTS, MUXES, SHAPES, SIGNALS, SIZE, STAGE_DELAY,
                                 VALUES, WIRE_LABELS, WIRES, AnimationDialog, XRayWindow)
from ares.gui.widgets import px
from ares.runner import State

PROGRAM = """\
        .global _start
_start: LDR     R1, =table
        LDR     R0, [R1, #4]
        STR     R0, [R1, R2]
        CMP     R0, #0
        MOVEQ   R3, #1
        BL      function
        MUL     R4, R0, R0
        SVC     #10
function:
        MOV     PC, LR
table:  .word   7, 8, 9
"""
FOREVER = """\
        .global _start
_start: ADD     R0, R0, #1
        B       _start
"""


def opened(app):
    app.run("tool_xray")
    return app.tool_windows["tool_xray"]


def connected(app):
    window = opened(app)
    window.connect_button.invoke()
    assert window.model.connected
    return window


def steps(app, count):
    for _ in range(count):
        app.run("step")


def panel(window):
    diagram = window.diagram
    return tuple(diagram.canvas.itemcget(item, "text")
                 for item in (diagram.heading, diagram.instruction, diagram.info))


def value(window, name):
    return window.diagram.canvas.itemcget(window.diagram.values[name], "text")


def signal(window, name):
    return window.diagram.canvas.itemcget(window.diagram.signals[name], "text")


def colour(window, name):
    """The colour of a wire on the diagram."""
    canvas = window.diagram.canvas
    colours = {canvas.itemcget(item, "fill") for item in canvas.find_withtag(f"wire&&{name}")}
    assert len(colours) == 1
    return colours.pop()


def outline(window, name):
    canvas = window.diagram.canvas
    colours = {canvas.itemcget(item, "outline") for item in canvas.find_withtag(f"block&&{name}")}
    assert len(colours) == 1
    return colours.pop()


def lit(window):
    return {name for name in WIRES if colour(window, name) == NAVY}


def timers(window):
    """The Tk timers waiting now."""
    return window.window.tk.splitlist(window.window.tk.call("after", "info"))


# The window ----------------------------------------------------------------------------

def test_it_comes_first_in_the_tools_menu(app):
    assert TOOLS[0].command == "tool_xray" and TOOLS[0].label == "&ARM X-Ray"
    window = opened(app)
    assert isinstance(window, XRayWindow) and window.window.title() == "ARM X-Ray"
    assert window.HEADING == "Animation of the ARM Datapath"


def test_it_fits_a_small_screen(app):
    """1366 x 768 at 100 %: a title bar and the task bar leave about 690."""
    window = opened(app)
    window.window.update_idletasks()
    assert window.window.winfo_reqwidth() <= px(window.window, 1020)
    assert window.window.winfo_reqheight() <= px(window.window, 640)


def test_the_help_credits_the_textbook():
    words = " ".join(tool.HELP.split())
    assert credits.TEXTBOOK in words
    assert "Play" in words and "Speed..." in words


def test_before_connecting_it_says_what_to_do(app):
    window = opened(app)
    assert "Connect to ARM" in panel(window)[0]
    assert lit(window) == set()
    assert window.play_button.instate(["disabled"])


def test_a_tool_not_connected_shows_nothing_of_the_program(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = opened(app)
    app.run("step")
    assert lit(window) == set() and value(window, "PC") == ""


def test_connected_it_shows_the_first_instruction_as_the_next(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    assert panel(window)[0].startswith("Runs next") and panel(window)[1].startswith("LDR R1")
    assert value(window, "PC") == "0x00000000"


# What a Step shows -------------------------------------------------------------------------

def test_a_step_of_a_load_lights_its_paths_and_writes_its_values(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 2)
    assert panel(window)[0] == "Just executed" and panel(window)[1] == "LDR R0, [R1, #4]"
    assert "Load, immediate offset" in panel(window)[2]
    assert "AL: always executes" in panel(window)[2]
    table = app.machine.reg(1)
    assert value(window, "PC") == "0x00000004"
    assert value(window, "PC'") == "0x00000008"
    assert value(window, "Instr") == "0xe5910004"
    assert value(window, "RA1") == "R1" and value(window, "A3") == "R0"
    assert value(window, "SrcA") == f"0x{table:08x}" and value(window, "SrcB") == "0x00000004"
    assert value(window, "ExtImm") == "0x00000004"
    assert value(window, "ALUResult") == f"0x{table + 4:08x}"
    assert value(window, "ReadData") == value(window, "WD3") == "0x00000008"
    assert value(window, "Result") == "0x00000008"
    assert value(window, "WriteData") == "" and value(window, "RD2") == ""
    assert signal(window, "MemtoReg") == "MemtoReg 1"
    assert signal(window, "RegSrc") == "RegSrc X0"
    assert signal(window, "ImmSrc") == "ImmSrc 01"
    assert signal(window, "ALUControl") == "ALUControl 0000"
    assert {"PC", "Instr", "SrcA", "SrcB", "ExtImm", "ALUResult", "Address", "ReadData", "Result",
            "ResultReg", "WD3", "A3", "RegWrite"} <= lit(window)
    assert not {"RD2", "WriteData", "ALUBypass", "ResultPC", "ALUFlags"} & lit(window)
    assert outline(window, "DMem") == NAVY and outline(window, "Shifter") == SHADOW


def test_a_store_with_a_register_offset_takes_the_third_read_port(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 3)
    assert panel(window)[1] == "STR R0, [R1, R2]"
    assert value(window, "A4") == "R0" and value(window, "RD4") == "0x00000008"
    assert value(window, "WriteData") == "0x00000008"
    assert signal(window, "StoreSrc") == "StoreSrc 1"
    assert signal(window, "MemtoReg") == "MemtoReg X"
    assert {"A4", "RD4", "WriteData", "StoreSrc", "MemWrite"} <= lit(window)
    assert "RD2Store" not in lit(window)


def test_a_failed_condition_says_so_and_lights_only_the_way_on(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 5)
    assert panel(window)[1] == "MOVEQ R3, #1"
    assert "EQ: Z = 0, does not execute" in panel(window)[2]
    assert signal(window, "RegWrite") == "RegWrite 0"
    assert {"PCFeed", "PC'"} <= lit(window)
    assert not {"Result", "WD3", "A3", "RegWrite"} & lit(window)
    assert "CondEx 0" in panel(window)[2]


def test_bl_shows_the_link_paths(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 6)
    assert panel(window)[1].startswith("BL ")
    assert value(window, "A3") == "R14" and value(window, "WD3") == "0x00000018"
    assert {"Link", "Const14", "LinkFeed", "ResultPC", "PCSrc", "PCPlus8"} <= lit(window)
    assert "ResultReg" not in lit(window) and "PCFeed" not in lit(window)
    assert signal(window, "Link") == "Link 1"


RETURN = """\
        .global _start
_start: MOV     R0, #1
        BL      function
        SVC     #10
function:
        CMP     R0, #2
        BXEQ    LR
        BX      LR
"""


def test_bx_lights_the_way_from_rm_to_the_pc(app, tmp_path):
    loaded(app, tmp_path, RETURN)
    window = connected(app)
    steps(app, 5)
    assert panel(window)[1] == "BX LR" and "Branch and exchange" in panel(window)[2]
    assert value(window, "RA2") == "R14" and value(window, "RD2") == "0x00000008"
    assert value(window, "SrcB") == value(window, "ALUResult") == "0x00000008"
    assert value(window, "Result") == value(window, "PC'") == "0x00000008"
    assert {"Rm", "RA2", "RD2", "Shifted", "SrcB", "ALUResult", "ALUBypass", "Result", "ResultPC",
            "PCSrc", "PC'"} <= lit(window)
    assert not {"RA1", "SrcA", "A3", "WD3", "ResultReg", "PCFeed", "Link"} & lit(window)
    assert signal(window, "PCSrc") == "PCSrc 1" and signal(window, "RegWrite") == "RegWrite 0"
    assert signal(window, "RegSrc") == "RegSrc 0X"
    assert signal(window, "ALUControl") == "ALUControl 0111"
    assert colour(window, "ResultPC") == NAVY and colour(window, "ResultReg") == SHADOW


def test_a_failed_bx_goes_on_along_pc_plus_4(app, tmp_path):
    loaded(app, tmp_path, RETURN)
    window = connected(app)
    steps(app, 4)
    assert panel(window)[1] == "BXEQ LR"
    assert "EQ: Z = 0, does not execute" in panel(window)[2]
    assert signal(window, "PCSrc") == "PCSrc 0" and value(window, "PC'") == "0x00000014"
    assert "PCFeed" in lit(window) and "ResultPC" not in lit(window)


def test_play_walks_bx_through_its_stages(app, tmp_path):
    loaded(app, tmp_path, RETURN)
    window = connected(app)
    steps(app, 5)
    diagram = window.diagram
    trace = window.model.view.trace
    diagram.show(trace, 1)
    assert {"Rm", "RD2"} <= lit(window) and value(window, "SrcB") == ""
    diagram.show(trace, 2)
    assert {"SrcB", "ALUResult"} <= lit(window) and value(window, "PC'") == ""
    diagram.show(trace, 3)
    assert not lit(window)
    diagram.show(trace, 4)
    assert {"ResultPC", "PC'"} <= lit(window) and value(window, "PC'") == "0x00000008"


def test_bx_to_an_odd_address_says_that_thumb_code_follows(app, tmp_path):
    loaded(app, tmp_path, """\
        .global _start
_start: ADR     R0, there
        ADD     R0, R0, #1
        BX      R0
there:  MOV     R0, R0
""")
    window = connected(app)
    steps(app, 3)
    assert panel(window)[1] == "BX R0" and xray.NOTE_TO_THUMB in panel(window)[2]
    assert value(window, "Result") == "0x0000000d" and value(window, "PC'") == "0x0000000c"
    steps(app, 1)
    assert xray.NOTE_THUMB in panel(window)[2]


def test_the_panel_with_all_its_lines_ends_above_the_wires_under_it(app, tmp_path):
    """The longest condition, the longest heading and the line on Thumb code at once."""
    loaded(app, tmp_path, RETURN)
    window = connected(app)
    diagram = window.diagram
    condition = "GT: Z = 1, N = 0, V = 0, does not execute"
    body = "\n".join((xray.BRANCH_EXCHANGE, condition, "Branch 1  MemW 0  RegW 0  ALUOp 1",
                      "FlagW 00  PCS 1  CondEx 1  FlagWrite 00", "Flags NZCV 0000 -> 0000",
                      xray.NOTE_TO_THUMB))
    diagram.write_info("Just executed; the program has ended", "BXNE R12", body)
    canvas = diagram.canvas
    assert canvas.bbox(diagram.info)[3] < canvas.bbox(diagram.wire_text["Instr"])[1]


def test_a_plain_return_says_nothing_of_thumb_code(app, tmp_path):
    loaded(app, tmp_path, RETURN)
    window = connected(app)
    steps(app, 5)
    assert xray.NOTE_TO_THUMB not in panel(window)[2]


def test_the_help_tells_that_bx_is_animated():
    outside = tool.HELP[tool.HELP.index("Some instructions lie outside"):
                        tool.HELP.index("For these the diagram stays gray")]
    assert "BLX" in outside and "BX" not in outside.replace("BLX", "")
    assert "BX" in tool.HELP[:tool.HELP.index("Some instructions lie outside")]


def test_the_help_says_that_a_return_with_pop_lies_outside():
    text = " ".join(tool.HELP.split())
    assert "returns with POP {..., PC}, which is normal ARM" in text
    assert "POP is outside the datapath. A return with BX LR animates." in text


def test_the_help_names_the_example_made_for_the_tool():
    assert "xray_tour.s" in tool.HELP and (ROOT / "examples" / "xray_tour.s").is_file()


def test_an_instruction_outside_leaves_the_diagram_gray_and_lists_what_it_did(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 8)
    heading, text, body = panel(window)
    assert text == "MUL R4, R0, R0" and "Outside the datapath" in body
    assert "no multiplier" in body and "R4 0x00000000 -> 0x00000040" in body
    assert lit(window) == set() and value(window, "PC") == ""
    assert signal(window, "PCSrc") == "PCSrc"
    assert window.play_button.instate(["disabled"])


def test_an_instruction_outside_that_has_not_run_says_so(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 8)
    app.run("backstep")
    assert "It has not run yet." in panel(window)[2]


def test_many_changes_are_counted_not_listed(app, tmp_path):
    loaded(app, tmp_path, """\
        .global _start
_start: LDR     SP, =0x4000
        PUSH    {R0-R12}
        SVC     #10
""")
    window = connected(app)
    for number in range(13):
        app.machine.set_reg(number, number + 1)
    steps(app, 2)
    body = panel(window)[2]
    assert "and 6 more" in body and len(body.splitlines()) == 3 + tool.DID_LINES + 1


# What it shows when ------------------------------------------------------------------------

def test_after_backstep_the_heading_says_it_was_undone(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 2)
    app.run("backstep")
    assert panel(window)[0].startswith("Undone by Backstep")
    assert panel(window)[1] == "LDR R0, [R1, #4]"


def test_at_a_slow_speed_it_follows_each_instruction(app, tmp_path):
    loaded(app, tmp_path, FOREVER)
    window = connected(app)
    slow(app, 30)
    seen = set()
    app.run("go")

    def both():
        seen.add(panel(window)[1])
        return len(seen) == 2
    run_until(app, both)
    app.run("pause")
    assert panel(window)[0] == "Just executed"
    assert {text.split()[0] for text in seen} >= {"ADD", "B"}


def test_at_full_speed_refresh_does_no_work(app, tmp_path, monkeypatch):
    loaded(app, tmp_path, FOREVER)
    window = connected(app)
    max_speed(app)
    looks = []
    update = window.model.update
    monkeypatch.setattr(window.model, "update", lambda: looks.append(1) or update())
    shows = []
    show = window.show
    monkeypatch.setattr(window, "show", lambda: shows.append(1) or show())
    monkeypatch.setattr(xray, "upcoming", lambda *args: pytest.fail("traced while running"))
    app.run("go")
    deadline = time.monotonic() + 0.3
    while time.monotonic() < deadline:
        app.root.update()
    assert app.runner.state is State.RUNNING
    assert looks == [] and shows == []
    monkeypatch.undo()
    app.run("pause")
    assert panel(window)[0].startswith("Runs next")


def test_connected_it_adds_no_hook(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    machine = app.machine
    hooks = len(machine.uc._callbacks)
    window = opened(app)
    assert len(machine.uc._callbacks) == hooks
    window.connect_button.invoke()
    app.run("step")
    assert len(machine.uc._callbacks) == hooks
    window.connect_button.invoke()
    assert len(machine.uc._callbacks) == hooks


def test_at_full_speed_a_finished_program_says_so(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    max_speed(app)
    go_to_end(app)
    assert panel(window) == ("The program has ended", "", "")
    assert lit(window) == set()


def test_the_stop_button_ends_the_program_here_too(app, tmp_path):
    loaded(app, tmp_path, FOREVER)
    window = connected(app)
    max_speed(app)
    app.run("go")
    app.root.update()
    app.run("stop")
    assert panel(window)[0] == "The program has ended"
    app.run("reset")
    assert panel(window)[0].startswith("Runs next")


def test_a_runtime_error_shows_the_instruction_that_failed(app, tmp_path):
    loaded(app, tmp_path, """\
        .global _start
_start: LDR     R1, =0x50000000
        LDR     R0, [R1]
""")
    window = connected(app)
    steps(app, 2)
    assert "out of range" in panel(window)[0] and panel(window)[1] == "LDR R0, [R1]"
    assert value(window, "ALUResult") == "0x50000000" and value(window, "ReadData") == "?"


def test_a_new_assembly_starts_again_and_stays_connected(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 2)
    assemble(app)
    assert window.model.connected and panel(window)[0].startswith("Runs next")
    assert panel(window)[1].startswith("LDR R1")


def test_closing_the_file_leaves_it_connected_without_a_program(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    window.machine_changed(None)
    assert window.model.connected and panel(window)[0] == "No program is loaded."


def test_disconnected_what_it_shows_stays(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 2)
    window.connect_button.invoke()
    app.run("step")
    assert panel(window)[1] == "LDR R0, [R1, #4]" and "ReadData" in lit(window)


def test_reset_clears_the_picture(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 2)
    window.reset_button.invoke()
    assert lit(window) == set() and value(window, "PC") == ""
    assert panel(window)[0] == "Waiting for the program."
    assert window.play_button.instate(["disabled"])
    app.run("step")
    assert panel(window)[1] == "STR R0, [R1, R2]"


# Play --------------------------------------------------------------------------------------

def playing(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 2)
    window.play_button.invoke()
    return window


def stage_boxes(window):
    canvas = window.diagram.canvas
    return [canvas.itemcget(box, "fill") == NAVY for box, _ in window.diagram.stage_boxes]


def test_play_walks_through_the_stages_one_at_a_time(app, tmp_path):
    window = playing(app, tmp_path)
    trace = window.model.view.trace
    assert window.play_button.cget("text") == "Stop"
    for number, stage in enumerate(trace.stages):
        assert window._stage == number
        assert stage_boxes(window) == [index == number for index in range(5)]
        assert lit(window) == set(stage.wires) & set(WIRES)
        window.window.after_cancel(window._job)
        window._next_stage()
    assert window._job is None and window._stage is None
    assert window.play_button.cget("text") == "Play"
    assert stage_boxes(window) == [False] * 5
    assert lit(window) == set(trace.active) & set(WIRES)


def test_the_values_appear_as_the_instruction_reaches_them(app, tmp_path):
    window = playing(app, tmp_path)
    assert value(window, "PC") == "0x00000004" and value(window, "ALUResult") == ""
    for stage in range(2):
        window.window.after_cancel(window._job)
        window._next_stage()
    assert value(window, "PC") == "0x00000004" and value(window, "ALUResult") != ""
    assert value(window, "ReadData") == ""


def test_play_uses_the_speed_chosen(app, tmp_path, monkeypatch):
    window = playing(app, tmp_path)
    window.play_button.invoke()
    assert window.delay == STAGE_DELAY
    window._set_delay(250)
    delays = []
    after = window.window.after
    monkeypatch.setattr(window.window, "after",
                        lambda delay, call: delays.append(delay) or after(delay, call))
    window.play_button.invoke()
    assert delays == [250]


def test_play_really_runs_on_timers(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 2)
    window._set_delay(1)
    window.play_button.invoke()
    run_until(app, lambda: window._job is None, limit=5)
    assert window.play_button.cget("text") == "Play"


def test_the_button_stops_play_and_shows_all_again(app, tmp_path):
    window = playing(app, tmp_path)
    window.play_button.invoke()
    assert window._job is None and window.play_button.cget("text") == "Play"
    assert "ReadData" in lit(window)


@pytest.mark.parametrize("command", ["step", "backstep"])
def test_step_and_backstep_cancel_play(app, tmp_path, command):
    window = playing(app, tmp_path)
    job = window._job
    app.run(command)
    assert window._job is None and job not in timers(window)
    assert window.play_button.cget("text") == "Play"
    assert stage_boxes(window) == [False] * 5


def test_closing_the_window_cancels_every_timer(app, tmp_path):
    window = playing(app, tmp_path)
    job = window._job
    assert job in timers(window)
    window.close()
    assert job not in app.root.tk.splitlist(app.root.tk.call("after", "info"))
    assert window.window is None


def test_reset_and_disconnect_cancel_play(app, tmp_path):
    window = playing(app, tmp_path)
    window.reset_button.invoke()
    assert window._job is None
    app.run("step")
    window.play_button.invoke()
    window.connect_button.invoke()
    assert window._job is None


def test_the_speed_dialog_sets_the_time_of_a_stage(app):
    window = opened(app)
    chosen = []
    dialog = AnimationDialog(window.window, 800, chosen.append)
    assert dialog.window.title() == "Animation Speed"
    assert "0.80 s" in dialog.text.cget("text")
    dialog.scale.set(1500)
    assert "1.50 s" in dialog.text.cget("text")
    dialog.ok()
    assert chosen == [1500] and not dialog.window.winfo_exists()


def test_cancel_in_the_speed_dialog_changes_nothing(app):
    window = opened(app)
    chosen = []
    dialog = AnimationDialog(window.window, 800, chosen.append)
    dialog.scale.set(1500)
    dialog.cancel()
    assert chosen == []


def test_the_speed_button_opens_the_dialog_over_the_tool(app, monkeypatch):
    window = opened(app)
    made = []
    monkeypatch.setattr(tool, "AnimationDialog", lambda *args: made.append(args))
    window.speed_button.invoke()
    assert made[0][:2] == (window.window, STAGE_DELAY)
    made[0][2](400)
    assert window.delay == 400


# The drawing -------------------------------------------------------------------------------

def outlines():
    """Every block as a polygon, in design pixels."""
    shapes = {}
    for name, (left, right, top, bottom, _) in MUXES.items():
        slope = (bottom - top) // 5
        shapes[name] = [(left, top), (right, top + slope), (right, bottom - slope), (left, bottom)]
    for name, (left, top, right, bottom) in BOXES.items():
        shapes[name] = [(left, top), (right, top), (right, bottom), (left, bottom)]
    shapes.update({name: list(points) for name, points in SHAPES.items()})
    return shapes


def inside(point, polygon, margin=1.0):
    """True when point lies inside polygon, more than margin from its edges."""
    x, y = point
    crossings = 0
    for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            crossings += 1
        length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        along = ((x - x0) * (x1 - x0) + (y - y0) * (y1 - y0)) / length ** 2
        along = min(1, max(0, along))
        near = ((x - x0 - along * (x1 - x0)) ** 2 + (y - y0 - along * (y1 - y0)) ** 2) ** 0.5
        if near <= margin:
            return False
    return crossings % 2 == 1


def points_of(line):
    for (x0, y0), (x1, y1) in zip(line, line[1:]):
        length = max(abs(x1 - x0), abs(y1 - y0), 1)
        for step in range(length + 1):
            yield x0 + (x1 - x0) * step / length, y0 + (y1 - y0) * step / length


def test_no_wire_crosses_a_block():
    shapes = outlines()
    for name, lines in WIRES.items():
        for line in lines:
            for point in points_of(line):
                for block, polygon in shapes.items():
                    assert not inside(point, polygon), (name, block, point)


def on_edge(point, polygon):
    x, y = point
    for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1]):
        length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        along = min(1, max(0, ((x - x0) * (x1 - x0) + (y - y0) * (y1 - y0)) / length ** 2))
        if ((x - x0 - along * (x1 - x0)) ** 2 + (y - y0 - along * (y1 - y0)) ** 2) ** 0.5 <= 1.5:
            return True
    return False


def test_every_wire_end_meets_a_block_or_another_wire():
    shapes = outlines()
    for name, lines in WIRES.items():
        for line in lines:
            for end in (line[0], line[-1]):
                on_block = any(on_edge(end, polygon) for polygon in shapes.values())
                on_wire = any(end in points_of(other) for other_name, others in WIRES.items()
                              for other in others if other is not line)
                constant = name in ("Const14", "Const15")
                assert on_block or on_wire or constant, (name, end)


def test_the_diagram_stays_inside_the_canvas():
    width, height = SIZE
    for lines in WIRES.values():
        for line in lines:
            assert all(0 <= x <= width and 0 <= y <= height for x, y in line)
    assert all(0 < x < width and 0 < y < height for x, y in CLOCKS.values())
    assert all(point in points for name, dots in DOTS.items() for point in dots
               for points in [[p for line in WIRES[name] for p in points_of(line)]])


def test_every_name_of_the_model_is_drawn(app, word_of_all):
    """The wires and blocks a trace can light are all on the canvas."""
    window = opened(app)
    canvas = window.diagram.canvas
    for block in xray.BLOCKS:
        assert canvas.find_withtag(f"block&&{block}"), block
    for trace in word_of_all:
        assert set(trace.active) <= set(WIRES) | {"RD1"}        # RD1 is SrcA's wire
        assert set(trace.active_blocks) <= set(xray.BLOCKS)
    assert set(VALUES) <= set(trace.values) and set(SIGNALS) <= set(trace.signals)


@pytest.fixture
def word_of_all():
    """Traces of a word of each class."""
    state = [1] * 16
    words = (0xE0810002, 0xE2810001, 0xE5910004, 0xE5810004, 0xE7910002, 0xE7810002, 0xEA000001,
             0xEB000001, 0xE1B00081, 0xE0100081, 0xE12FFF1E)
    return [xray.trace(0, word, state, 0x1D3, lambda address, size: bytes(size)) for word in words]


def text_boxes(window):
    canvas = window.diagram.canvas
    found = {}
    for item in canvas.find_all():
        if canvas.type(item) == "text" and canvas.itemcget(item, "text"):
            found[item] = canvas.bbox(item)
    return found


def test_the_texts_do_not_overlap_with_the_longest_values(app, tmp_path):
    """Every value at its longest, every signal with four digits' room where it has them."""
    window = opened(app)
    diagram = window.diagram
    canvas = diagram.canvas
    for name, item in diagram.values.items():
        short = name in tool.REGISTER_WIRES or name == "ALUFlags"
        canvas.itemconfigure(item, text="R15" if short else "0x0000000f")
    for name, item in diagram.signals.items():
        digits = {"ALUControl": "0000", "RegSrc": "X0", "ImmSrc": "XX"}.get(name, "X")
        canvas.itemconfigure(item, text=f"{name} {digits}")
    for name, item in diagram.fields.items():
        canvas.itemconfigure(item, text="0" * tool.FIELDS[name][2])
    canvas.itemconfigure(diagram.flags, text="0000")
    canvas.itemconfigure(diagram.shift_text, text="ROR #31")
    boxes = list(text_boxes(window).items())
    room = px(canvas, 1)
    for index, (one, (left, top, right, bottom)) in enumerate(boxes):
        for other, (left2, top2, right2, bottom2) in boxes[index + 1:]:
            apart = (right - room <= left2 or right2 - room <= left or bottom - 3 * room <= top2
                     or bottom2 - 3 * room <= top)
            assert apart, (canvas.itemcget(one, "text"), canvas.itemcget(other, "text"))


def test_each_wire_has_a_label_of_the_textbook():
    names = {text for _, _, text, _ in WIRE_LABELS.values()}
    assert {"PC'", "PC", "PCPlus4", "PCPlus8", "RA1", "RA2", "SrcA", "SrcB", "ALUResult",
            "ALUFlags", "ReadData", "WriteData", "Result", "ExtImm", "Instr"} <= names


@pytest.mark.parametrize("name", ["PCSrc", "MemtoReg", "MemWrite", "ALUControl", "ALUSrc", "ImmSrc",
                                  "RegWrite", "RegSrc", "NoWrite", "ShiftC", "Link", "Byte",
                                  "StoreSrc", "Shift"])
def test_the_control_unit_shows_every_signal(name):
    assert name in SIGNALS


# Regressions ----------------------------------------------------------------------------------

READ = """\
        .data
buffer: .space  200
        .global _start
        .text
_start: LDR     R0, =buffer
        MOV     R1, #190
        SVC     #8
        SVC     #10
"""


def test_connecting_after_stop_says_the_program_has_ended(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    steps(app, 2)
    app.run("stop")
    window = connected(app)
    assert panel(window)[0] == "Just executed; the program has ended"


def test_connecting_again_after_stop_keeps_saying_so(app, tmp_path):
    loaded(app, tmp_path, FOREVER)
    window = connected(app)
    max_speed(app)
    app.run("go")
    app.root.update()
    app.run("stop")
    window.connect_button.invoke()
    window.connect_button.invoke()
    assert panel(window)[0] == "The program has ended"


def test_a_new_program_after_stop_runs_next_again(app, tmp_path):
    loaded(app, tmp_path, FOREVER)
    window = connected(app)
    app.run("stop")
    assemble(app)
    assert panel(window)[0] == "Runs next: it has not run yet"


def test_a_long_memory_change_stays_one_short_line(app, tmp_path):
    loaded(app, tmp_path, READ)
    window = connected(app)
    app.machine.console.feed("x" * 150 + "\n")
    steps(app, 3)
    lines = window.model.view.did
    assert any(line.endswith(" bytes") for line in lines)
    assert all(len(line) < 44 for line in lines)


def test_a_jump_to_no_code_shows_no_made_up_instruction(app, tmp_path):
    loaded(app, tmp_path, """\
        .global _start
_start: LDR     R1, =0x200000
        MOV     PC, R1
""")
    window = connected(app)
    steps(app, 3)
    heading, instruction, _ = panel(window)
    assert "no program code" in heading and instruction == ""
    assert str(window.play_button.cget("state")) == "disabled" or window.play_button.instate(
        ["disabled"])


def test_step_onto_a_read_cancels_play(app, tmp_path):
    loaded(app, tmp_path, READ)
    window = connected(app)
    steps(app, 2)
    window.play()
    assert window._job is not None
    app.run("step")                     # the read waits for a line
    assert app.runner.state is State.WAITING
    assert window._job is None and window.play_button.cget("text") == "Play"


def test_reset_after_backsteps_back_to_the_start_says_runs_next(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 2)
    app.run("backstep")
    app.run("backstep")
    assert panel(window)[0] == "Undone by Backstep: it runs next"
    app.run("reset")
    assert panel(window)[0] == "Runs next: it has not run yet"
