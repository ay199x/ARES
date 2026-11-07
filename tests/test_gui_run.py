# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Running from the window: Go, Step, Backstep, Pause, Stop, Reset, speed, input and output."""

import sys
import time
from types import SimpleNamespace

import pytest
from conftest import PROGRAMS, press_key, use_test_clipboard
from test_gui_assemble import assemble, open_source, wait_for_assembly

from ares.console import FINISHED_ERROR
from ares.gui import app as app_module
from ares.gui.app import MAX_SPEED, RUN_FAILED
from ares.gui.execute import FAILED
from ares.gui.messages import RUN_IO_LIMIT, keys_as_line
from ares.machine import StopReason
from ares.runner import State

PROGRAMS_WITH_OUTPUT = sorted(p for p in PROGRAMS.glob("*.s") if p.with_suffix(".out").is_file())

COUNT = """\
        .global _start
_start: MOV     R0, #0
loop:   ADD     R0, R0, #1
        CMP     R0, #3
        BNE     loop
        MOV     R1, #7
        SVC     #10
"""
FOREVER = ".global _start\n_start: ADD R0, R0, #1\n        B _start\n"
READ_INT = """\
        .global _start
_start: SVC     #5
        ADD     R0, R0, #1
        SVC     #1
        SVC     #10
"""
ECHO = """\
        .global _start
_start: LDR     R1, =0xFF201000
poll:   LDR     R0, [R1]
        TST     R0, #0x8000
        BEQ     poll
        STRB    R0, [R1]
        AND     R0, R0, #0xFF
        CMP     R0, #'.'
        BNE     poll
        SVC     #10
"""


def loaded(app, tmp_path, source, name="prog.s"):
    open_source(app, tmp_path, source, name)
    assemble(app)
    assert app.runner is not None, app.messages.messages.get("1.0", "end-1c")
    return app.runner


def run_until(app, done, limit=20.0):
    """Let the window's event loop work until done() or the time limit."""
    deadline = time.monotonic() + limit
    while not done():
        assert time.monotonic() < deadline, "the run did not get there in time"
        app.root.update()
        time.sleep(0.001)


def go_to_end(app, limit=20.0):
    app.run("go")
    run_until(app, lambda: app.runner.state not in (State.RUNNING,), limit)


def run_io(app):
    return app.messages.run_io.get("1.0", "end-1c")


def type_line(app, text):
    """Type a line where Run I/O lets the user type, and press Enter."""
    run_io_text = app.messages.run_io
    assert run_io_text.typing
    run_io_text.insert("end-1c", text)
    app.messages._enter()


def max_speed(app):
    app.speed.set(MAX_SPEED)
    app._speed_moved(MAX_SPEED)


def slow(app, speed):
    app.speed.set(speed)
    app._speed_moved(speed)


# Go to the end ------------------------------------------------------------

@pytest.mark.parametrize("source", PROGRAMS_WITH_OUTPUT, ids=lambda p: p.name)
def test_the_programs_run_from_the_window(app, tmp_path, source):
    loaded(app, tmp_path, source.read_text(), source.name)
    typed = source.with_suffix(".in")
    lines = typed.read_text().splitlines() if typed.is_file() else []
    app.run("go")
    starts = []                         # where Run I/O shows each typed line
    for line in lines:
        run_until(app, lambda: app.messages.run_io.typing)
        starts.append(len(run_io(app)))
        type_line(app, line)
    run_until(app, lambda: app.runner.state is State.FINISHED, 60)
    shown = run_io(app)
    for start, line in reversed(list(zip(starts, lines))):     # the window shows them too
        assert shown[start:start + len(line) + 1] == line + "\n"
        shown = shown[:start] + shown[start + len(line) + 1:]
    assert shown == source.with_suffix(".out").read_text().replace("\r\n", "\n")
    assert app.machine.stop_reason is not None and app.machine.error is None


def test_go_runs_to_the_end(app, tmp_path):
    loaded(app, tmp_path, COUNT)
    assert app.is_enabled("go") and app.is_enabled("step") and not app.is_enabled("pause")
    go_to_end(app)
    assert app.runner.state is State.FINISHED
    assert run_io(app) == "-- program is finished running --\n"
    assert app.machine.reg(0) == 3
    assert app.messages.tab("current", "text") == "Run I/O"
    assert app.execute.text_segment.pc_row is None        # nothing runs next
    for name in ("go", "step", "pause", "stop"):
        assert not app.is_enabled(name), name
    assert app.is_enabled("reset") and app.is_enabled("assemble")


def test_a_run_shows_the_changes_of_the_whole_run(app, tmp_path):
    loaded(app, tmp_path, COUNT)
    go_to_end(app)
    rows = app.registers
    assert rows._row(0).background and rows._row(1).background     # R0 and R1 changed
    assert not rows._row(2).background


def test_runtime_error_in_both_panes_and_the_failing_row_shown(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: MOV R0, #0x50000000\n"
                          "        LDR R1, [R0]\n        SVC #10\n")
    go_to_end(app)
    error = ("Runtime error at line 3 (address 0x00000004): "
             "memory access out of range at 0x50000000")
    assert run_io(app) == error + "\n" + FINISHED_ERROR + "\n"
    assert app.messages.messages.get("1.0", "end-1c").splitlines()[-2:] == [error, RUN_FAILED]
    segment = app.execute.text_segment
    assert segment.pc_row == 1 and segment._row(1).background == FAILED     # light red


# Step, Backstep, breakpoints, Pause, Stop, Reset ----------------------------

def test_step_and_backstep(app, tmp_path):
    loaded(app, tmp_path, COUNT)
    segment = app.execute.text_segment
    assert not app.is_enabled("backstep")
    app.run("step")
    app.run("step")
    assert app.runner.state is State.PAUSED and segment.pc_row == 2
    assert app.machine.reg(0) == 1
    assert app.registers._row(0).background                    # R0 changed by this step
    assert app.is_enabled("backstep") and app.is_enabled("go")
    app.run("backstep")
    assert app.machine.reg(0) == 0 and segment.pc_row == 1
    app.run("backstep")
    assert segment.pc_row == 0 and not app.is_enabled("backstep")


def test_go_stops_at_a_breakpoint_and_goes_on(app, tmp_path):
    loaded(app, tmp_path, COUNT)
    segment = app.execute.text_segment
    segment.toggle_breakpoint(0x10)                             # MOV R1, #7
    go_to_end(app)
    assert app.runner.state is State.PAUSED and segment.pc_row == 4
    assert app.machine.reg(0) == 3 and app.machine.reg(1) == 0
    go_to_end(app)
    assert app.runner.state is State.FINISHED and app.machine.reg(1) == 7


def test_pause_and_stop_a_long_run(app, tmp_path):
    loaded(app, tmp_path, FOREVER)
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) > 1000)
    assert app.is_enabled("pause") and app.is_enabled("stop") and not app.is_enabled("go")
    assert not app.is_enabled("assemble")
    app.run("pause")
    assert app.runner.state is State.PAUSED and app._tick_job is None
    count = app.machine.reg(0)
    app.root.update()
    assert app.machine.reg(0) == count                          # it really stopped
    assert app.execute.text_segment.pc_row in (0, 1)
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) > count + 1000)
    app.run("stop")
    assert app.runner.state is State.FINISHED and not app.is_enabled("go")


def test_reset_starts_again(app, tmp_path):
    loaded(app, tmp_path, COUNT)
    app.execute.text_segment.toggle_breakpoint(0x10)
    go_to_end(app)
    app.run("reset")
    assert app.runner.state is State.READY and app.machine.reg(0) == 0
    assert app.execute.text_segment.pc_row == 0
    assert not app.registers._row(0).background
    assert app.machine.breakpoints == {0x10}
    go_to_end(app)
    assert app.runner.state is State.PAUSED and app.machine.reg(0) == 3


def test_registers_can_be_changed_only_while_the_program_does_not_run(app, tmp_path):
    loaded(app, tmp_path, FOREVER)
    assert app.registers.editable
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) > 10)
    assert not app.registers.editable
    app.registers.edit(0)
    assert app.registers.editor is None
    app.run("pause")
    assert app.registers.editable


# Speed -----------------------------------------------------------------------

def test_slow_runs_show_every_instruction(app, tmp_path):
    loaded(app, tmp_path, COUNT)
    slow(app, 30)
    segment = app.execute.text_segment
    app.run("go")
    seen = []
    run_until(app, lambda: (seen.append((app.machine.pc, segment.pc_row)) or
                            app.runner.state is State.FINISHED), 10)
    pcs = [pc for pc, row in seen]
    assert all(row == pc // 4 for pc, row in seen if row is not None)
    assert {0, 4, 8, 12, 16, 20} <= set(pcs)


def test_moving_the_slider_to_max_during_a_slow_run(app, tmp_path):
    loaded(app, tmp_path, FOREVER)
    slow(app, 20)
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) >= 2)
    assert app.execute.text_segment.pc_row is not None
    max_speed(app)
    assert app.execute.text_segment.pc_row is None
    run_until(app, lambda: app.machine.reg(0) > 10000)
    app.run("stop")


# Input ---------------------------------------------------------------------------

def test_a_read_service_waits_for_a_line_typed_in_run_io(app, tmp_path, hidden_windows):
    loaded(app, tmp_path, READ_INT)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    assert app.messages.run_io.typing and hidden_windows.focus is app.messages.run_io
    assert app.execute.text_segment.pc_row == 0                 # the waiting SVC
    assert not app.is_enabled("go") and app.is_enabled("stop")
    type_line(app, "41")
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert run_io(app) == "41\n42-- program is finished running --\n".replace(
        "42-", "42\n-")
    assert not app.messages.run_io.typing


def test_only_the_typed_line_can_be_changed(app, tmp_path):
    loaded(app, tmp_path, READ_INT)
    app.messages.write_output("Number? ")
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    text = app.messages.run_io
    text.insert("1.0", "X")                                     # in the output: refused
    text.delete("1.0", "1.3")
    text.insert("end-1c", "12")
    text.delete("end-2c")
    assert run_io(app) == "Number? 1"
    type_line(app, "")
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert run_io(app).startswith("Number? 1\n2\n")
    text.insert("end", "Y")                                     # no line is typed now
    assert "Y" not in run_io(app)


def test_step_waits_for_input_too(app, tmp_path):
    loaded(app, tmp_path, READ_INT)
    app.run("step")
    assert app.runner.state is State.WAITING and app.messages.run_io.typing
    type_line(app, "5")
    assert app.runner.state is State.PAUSED and app.machine.reg(0) == 5
    assert app.execute.text_segment.pc_row == 1


def test_pause_and_backstep_end_the_typing(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: MOV R1, #1\n        SVC #5\n        SVC #10\n")
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    app.run("pause")
    assert not app.messages.run_io.typing and app.runner.state is State.PAUSED
    assert not app.is_enabled("backstep")                       # a full-speed Go records nothing
    app.run("reset")
    app.run("step")                                             # Step records for Backstep
    app.run("step")
    assert app.runner.state is State.WAITING and app.messages.run_io.typing
    assert app.is_enabled("backstep")
    app.run("backstep")
    assert not app.messages.run_io.typing and app.machine.pc == 0


def test_popup_dialog_for_input(app, tmp_path):
    app.setting_vars["popup_input"].set(True)
    app._setting_toggled("popup_input")
    loaded(app, tmp_path, READ_INT)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    dialog = app.line_dialog
    assert dialog is not None and not app.messages.run_io.typing
    dialog.entry.insert(0, "9")
    dialog.ok()
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert run_io(app) == "9\n10\n-- program is finished running --\n"


def test_cancelling_the_input_dialog_lets_the_user_type_in_run_io(app, tmp_path):
    app.settings.popup_input = True
    loaded(app, tmp_path, READ_INT)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    app.line_dialog.cancel()
    assert app.line_dialog is None and app.messages.run_io.typing
    type_line(app, "1")
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert app.machine.reg(0) == 2


def test_keys_go_to_the_jtag_uart_as_typed(app, tmp_path):
    loaded(app, tmp_path, ECHO)
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) == 0 and app.machine.pc > 4)
    for char in "hi.":
        assert app.messages._key(SimpleNamespace(char=char)) == "break"
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert run_io(app) == "hi.\n-- program is finished running --\n"


def test_keys_that_are_not_characters_are_left_to_the_window(app, tmp_path):
    loaded(app, tmp_path, ECHO)
    assert app.messages._key(SimpleNamespace(char="")) is None          # F5, arrows
    assert app.messages._key(SimpleNamespace(char="\x16")) is None      # Ctrl+V
    app.run("go")
    app.run("stop")
    assert app.messages._key(SimpleNamespace(char="a")) is None         # program ended


def test_paste_into_the_typed_line_and_to_the_program(app, tmp_path, monkeypatch):
    use_test_clipboard(app.root)
    loaded(app, tmp_path, READ_INT)
    monkeypatch.setattr(app.root, "focus_get", lambda: app.messages.run_io)
    app.root.clipboard_append("3")
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    app.run("paste")
    assert app.messages.run_io.get("input", "end-1c") == "3"
    app.messages._enter()
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert app.machine.reg(0) == 4


def test_paste_gives_keys_to_a_running_program(app, tmp_path, monkeypatch):
    use_test_clipboard(app.root)
    loaded(app, tmp_path, ECHO)
    monkeypatch.setattr(app.root, "focus_get", lambda: app.messages.run_io)
    app.root.clipboard_append("ok.")
    app.run("go")
    app.run("paste")
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert run_io(app) == "ok.\n-- program is finished running --\n"


# Output and responsiveness -------------------------------------------------------

def test_run_io_keeps_the_newest_output(app):
    pane = app.messages
    pane.write_output("A" * (RUN_IO_LIMIT - 10))
    pane.write_output("B" * 100)
    text = run_io(app)
    assert len(text) <= RUN_IO_LIMIT and text.endswith("B" * 100)
    pane.clear(pane.run_io)
    assert pane._output == 0 and run_io(app) == ""


@pytest.mark.serial
def test_the_window_stays_responsive_during_the_benchmark(app, tmp_path):
    source = PROGRAMS / "loop10m.s"
    loaded(app, tmp_path, source.read_text(), source.name)
    beats = []

    def beat():
        beats.append(time.perf_counter())
        if app.runner.state is State.RUNNING:
            app.root.after(5, beat)
    start = time.perf_counter()
    app.run("go")
    app.root.after(5, beat)
    run_until(app, lambda: app.runner.state is State.FINISHED, 30)
    elapsed = time.perf_counter() - start
    gaps = [b - a for a, b in zip(beats, beats[1:])]
    assert len(beats) >= 2 and max(gaps) < 0.1, (len(beats), max(gaps, default=None))
    assert elapsed < 2.0, f"the benchmark took {elapsed:.2f} s in the window"
    assert run_io(app) == source.with_suffix(".out").read_text()


@pytest.mark.serial
def test_pause_takes_effect_at_once(app, tmp_path):
    loaded(app, tmp_path, FOREVER)
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) > 1000)
    start = time.perf_counter()
    app.run("pause")
    assert time.perf_counter() - start < 0.1 and app.runner.state is State.PAUSED


@pytest.mark.serial
def test_a_sleeping_program_lets_the_window_work(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: MOV R0, #300\n        SVC #32\n"
                          "        SVC #10\n")
    app.run("go")
    beats = []
    start = time.perf_counter()
    run_until(app, lambda: beats.append(time.perf_counter()) or
              app.runner.state is State.FINISHED, 5)
    assert time.perf_counter() - start >= 0.29
    assert max(b - a for a, b in zip(beats, beats[1:])) < 0.1


def test_closing_the_window_during_a_run(make_app, tmp_path):
    app = make_app()
    loaded(app, tmp_path, FOREVER)
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) > 100)
    app.close()
    assert app._tick_job is None


def test_backstep_while_running_follows_the_setting(app, tmp_path):
    loaded(app, tmp_path, COUNT)
    go_to_end(app)
    assert not app.is_enabled("backstep")          # a full-speed run keeps no history
    app.setting_vars["backstep_while_running"].set(True)
    app._setting_toggled("backstep_while_running")
    app.run("reset")
    go_to_end(app)
    assert app.is_enabled("backstep")
    app.run("backstep")                                         # the SVC #10
    assert app.runner.state is State.PAUSED and app.execute.text_segment.pc_row == 5
    app.run("backstep")                                         # MOV R1, #7
    assert app.machine.reg(1) == 0


def test_assembling_is_possible_again_after_a_run(app, tmp_path):
    loaded(app, tmp_path, FOREVER)
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) > 100)
    app.run("assemble")
    assert app.runner.state is State.RUNNING                     # not while running
    app.run("stop")
    assemble(app)
    assert app.runner.state is State.READY


def test_dialog_services_wait_for_their_window(app, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(app_module.App, "show_dialog", lambda self, request: shown.append(
        request.service))
    loaded(app, tmp_path, ".global _start\n_start: LDR R0, =m\n        SVC #50\n"
                          "        SVC #10\n.data\nm: .asciz \"Sure?\"\n")
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    assert shown == [50]


# Regressions: breakpoints, slow runs, typing and pasting --------------------------

def test_a_breakpoint_checked_after_steps_stops_go(app, tmp_path):
    loaded(app, tmp_path, (PROGRAMS / "fact.s").read_text(), "fact.s")
    for _ in range(3):                                          # PUSH at 0x18 has run
        app.run("step")
    app.execute.text_segment.toggle_breakpoint(0x18)
    go_to_end(app)
    assert app.runner.state is State.PAUSED and app.machine.pc == 0x18


def test_toggle_all_off_and_on_again_after_running(app, tmp_path):
    loaded(app, tmp_path, FOREVER)
    segment = app.execute.text_segment
    segment.toggle_breakpoint(0x4)
    go_to_end(app)
    assert app.runner.state is State.PAUSED and app.machine.pc == 0x4
    app.run("toggle_breakpoints")
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) > 1000)
    app.run("pause")
    app.run("toggle_breakpoints")
    go_to_end(app)
    assert app.runner.state is State.PAUSED and app.machine.pc == 0x4


def test_backstep_while_running_after_steps(app, tmp_path):
    app.settings.backstep_while_running = True
    loaded(app, tmp_path, FOREVER)
    for _ in range(6):
        app.run("step")
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) > 2000)
    app.run("pause")
    count, pc = app.machine.reg(0), app.machine.pc
    app.run("backstep")
    assert app.machine.pc != pc and app.machine.reg(0) in (count, count - 1)
    assert len(app.machine.history) > 100


def test_changing_a_register_while_paused_in_a_read(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: SVC #5\n        MOV R2, #9\n"
                          "        SVC #10\n")
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    app.run("pause")
    assert app.registers.editable
    app.registers.edit(15)                                      # PC
    app.registers.editor.delete(0, "end")
    app.registers.editor.insert(0, "4")
    app.registers.commit()
    go_to_end(app)
    assert app.runner.state is State.FINISHED and app.machine.reg(2) == 9
    assert app.machine.console.pending() == 0 and not app.messages.run_io.typing


def test_a_sleeping_program_is_looked_at_every_50_ms(app, tmp_path, monkeypatch):
    loaded(app, tmp_path, ".global _start\n_start: MOV R0, #300\n        SVC #32\n"
                          "        SVC #10\n")
    ticks = []
    tick = app._tick
    monkeypatch.setattr(app, "_tick", lambda: ticks.append(1) or tick())
    go_to_end(app)
    assert len(ticks) < 15, len(ticks)


def test_after_a_typed_line_the_fast_run_shows_no_next_instruction(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: SVC #5\nloop:   ADD R1, R1, #1\n"
                          "        B loop\n")
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    assert app.execute.text_segment.pc_row == 0
    type_line(app, "1")
    assert app.runner.state is State.RUNNING and app.execute.text_segment.pc_row is None
    app.run("stop")


def test_stop_ends_the_line_and_shows_no_next_instruction(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: MOV R0, #'x'\n        SVC #11\n"
                          "loop:   ADD R1, R1, #1\n        B loop\n")
    app.run("go")
    run_until(app, lambda: app.machine.reg(1) > 100)
    app.run("stop")
    assert run_io(app) == "x\n-- program is finished running (stopped) --\n"
    assert app.execute.text_segment.pc_row is None


def test_a_failing_first_step_after_reset_is_in_both_panes(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: MOV R0, #0x50000000\n"
                          "        LDR R1, [R0]\n")
    app.run("step")
    app.run("step")
    app.run("reset")
    app.run("step")
    app.run("step")
    lines = app.messages.messages.get("1.0", "end-1c").splitlines()
    assert sum(line.startswith("Runtime error at line 3") for line in lines) == 2


def test_a_slow_run_stopped_by_a_breakpoint_shows_the_last_change(app, tmp_path):
    loaded(app, tmp_path, COUNT)
    app.execute.text_segment.toggle_breakpoint(0x14)            # the SVC after MOV R1, #7
    slow(app, 30)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.PAUSED, 10)
    assert app.machine.reg(1) == 7
    assert app.registers._row(1).background                    # R1, changed by MOV R1, #7
    assert not app.registers._row(0).background                # R0 was not


def test_the_first_slow_instruction_after_a_fast_run_shows_only_its_change(app, tmp_path):
    loaded(app, tmp_path, FOREVER)
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) > 1000)
    slow(app, 1)
    app._cancel_tick()
    app._tick()                                                 # first shows where it is
    app._cancel_tick()
    while app.machine.pc != 4:                                  # until B _start is next
        app._tick()
        app._cancel_tick()
    app._tick()                                                 # B: only PC changes
    app._cancel_tick()
    assert not app.registers._row(0).background and app.registers._row(15).background
    app.run("stop")


@pytest.mark.serial
def test_moving_the_slider_to_max_takes_effect_at_once(app, tmp_path):
    loaded(app, tmp_path, FOREVER)
    slow(app, 1)
    app.run("go")
    max_speed(app)
    start = time.perf_counter()
    run_until(app, lambda: app.machine.reg(0) > 1000)
    assert time.perf_counter() - start < 0.5
    app.run("stop")


def test_assemble_upon_opening_waits_while_a_program_runs(app, tmp_path):
    app.settings.assemble_on_open = True
    runner = loaded(app, tmp_path, FOREVER)
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) > 100)
    other = tmp_path / "other.s"
    other.write_text(COUNT)
    tab = app.open_path(other)
    assert app.runner is runner and runner.state is State.RUNNING
    app.editor.select(app.editor.tabs[0])                       # back to the running source
    app.run("stop")                                             # now other.s is assembled
    wait_for_assembly(app)
    assert app.runner is not runner and app.runner.state is State.READY
    assert app.editor.current is tab and app.machine.program.end_address == 0x18


def test_keys_typed_before_a_read_start_its_line(app, tmp_path):
    loaded(app, tmp_path, READ_INT)
    assert app.messages._key(SimpleNamespace(char="4")) == "break"     # before Go
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    assert app.messages.run_io.get("input", "end-1c") == "4"
    app.messages.run_io.insert("end-1c", "1")
    app.messages._enter()
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert app.machine.reg(0) == 42 and run_io(app).startswith("41\n42")


def test_pause_keeps_an_unsent_line_and_stop_forgets_it(app, tmp_path):
    loaded(app, tmp_path, READ_INT)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    app.messages.run_io.insert("end-1c", "12")
    app.run("pause")
    assert run_io(app) == "" and not app.messages.run_io.typing
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    assert app.messages.run_io.get("input", "end-1c") == "12"
    app.messages.run_io.insert("end-1c", "3")
    app.run("stop")
    assert run_io(app) == "-- program is finished running (stopped) --\n"
    app.run("reset")
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    assert app.messages.run_io.get("input", "end-1c") == ""
    app.run("stop")


def test_undo_while_typing_for_the_program_leaves_the_editor(app, tmp_path, monkeypatch):
    loaded(app, tmp_path, READ_INT)
    tab = app.editor.current
    tab.text.insert("1.0", "@ note\n")
    text = tab.get_text()
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    monkeypatch.setattr(app.root, "focus_get", lambda: app.messages.run_io)
    app.run("undo")
    app.run("redo")
    assert tab.get_text() == text and app.views.select() == str(app.execute)
    app.run("stop")


@pytest.mark.parametrize("state, sent", [(0, True), (0x4, False), (0x20004, True)])
def test_keys_with_a_shortcut_modifier_are_left_to_the_window(app, tmp_path, monkeypatch,
                                                             state, sent):
    monkeypatch.setattr(app.messages, "windowing_system", "win32")
    loaded(app, tmp_path, ECHO)
    result = app.messages._key(SimpleNamespace(char="f", state=state))
    assert (result == "break") is sent
    assert app.messages._key(SimpleNamespace(char="f", state=0x20000)) is None   # Alt+F


def test_no_empty_line_before_the_end_line_after_a_typed_line(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: LDR R0, =p\n        SVC #4\n"
                          "        SVC #5\n        SVC #10\n.data\np: .asciz \"N? \"\n")
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    type_line(app, "5")
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert run_io(app) == "N? 5\n-- program is finished running --\n"


def test_typing_with_the_cursor_in_the_output_goes_to_the_line(app, tmp_path):
    app.messages.write_output("Number? ")
    loaded(app, tmp_path, READ_INT)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    text = app.messages.run_io
    text.mark_set("insert", "1.0")                              # a click in the output
    assert app.messages._key(SimpleNamespace(char="7")) is None
    assert text.compare("insert", "==", "end-1c")
    app.run("stop")


def test_paste_reaches_the_program_by_every_route(app, tmp_path):
    use_test_clipboard(app.root)
    app.root.clipboard_append("ok.")
    loaded(app, tmp_path, ECHO)
    app.run("go")
    assert app.messages._paste_from("CLIPBOARD") == "break"
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert run_io(app) == "ok.\n-- program is finished running --\n"


def test_closing_the_programs_file_ends_the_typing_in_run_io(app, tmp_path):
    # The waiting program is stopped and unloaded: Paste cannot reach Run I/O without a file.
    loaded(app, tmp_path, READ_INT)
    app.run("go")
    run_until(app, lambda: app.messages.run_io.typing)
    assert app.is_enabled("paste")
    app.cmd_close()
    assert app.editor.current is None and app.runner is None
    assert not app.messages.run_io.typing and not app.is_enabled("paste")


# Regressions: output, typed lines and slow runs -----------------------------------

TWO_READS = """\
        .global _start
_start: SVC     #5
        MOV     R4, R0
        SVC     #5
        MOV     R5, R0
        SVC     #10
"""
PROMPT = """\
        .global _start
_start: LDR     R0, =prompt
        SVC     #4
        SVC     #5
        SVC     #10
        .data
prompt: .asciz  "N? "
"""


def test_a_zero_byte_in_the_output_loses_nothing_after_it(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: MOV R0, #'A'\n        SVC #11\n"
                          "        MOV R0, #0\n        SVC #11\n        MOV R0, #'B'\n"
                          "        SVC #11\n        SVC #10\n")
    go_to_end(app)
    assert run_io(app) == "AB\n-- program is finished running --\n"
    assert app.messages._output == len(run_io(app))


def test_reset_and_assembling_start_the_next_run_on_a_new_line(app, tmp_path):
    loaded(app, tmp_path, PROMPT)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    app.run("reset")
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    assert run_io(app) == "N? \nN? "
    app.run("pause")
    assemble(app)
    app.run("step")
    app.run("stop")
    assert run_io(app) == "N? \nN? \n-- program is finished running (stopped) --\n"


def test_backspace_typed_before_a_read_corrects_its_line(app, tmp_path):
    loaded(app, tmp_path, READ_INT)
    for char in "12\b3":
        assert app.messages._key(SimpleNamespace(char=char)) == "break"
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    assert app.messages.run_io.get("input", "end-1c") == "13"
    app.messages._enter()
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert app.machine.reg(0) == 14 and app.machine.error is None


def test_the_input_dialog_keeps_its_text_through_pause_and_cancel(app, tmp_path):
    app.settings.popup_input = True
    loaded(app, tmp_path, READ_INT)
    app.messages._key(SimpleNamespace(char="7"))               # before the read
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    assert app.line_dialog.entry.get() == "7"
    app.line_dialog.entry.insert("end", "2")
    app.run("pause")
    assert app.line_dialog is None
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    assert app.line_dialog.entry.get() == "72"
    app.line_dialog.cancel()                                    # typed in Run I/O after all
    assert app.messages.run_io.get("input", "end-1c") == "72"
    app.messages._enter()
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert app.machine.reg(0) == 73


def test_backstep_keeps_the_text_of_the_input_dialog(app, tmp_path):
    app.settings.popup_input = True
    loaded(app, tmp_path, ".global _start\n_start: MOV R1, #1\n        SVC #5\n"
                          "        SVC #10\n")
    app.run("step")
    app.run("step")
    app.line_dialog.entry.insert(0, "33")
    app.run("backstep")
    assert app.line_dialog is None and app.machine.pc == 0
    app.run("step")
    app.run("step")
    assert app.line_dialog.entry.get() == "33"
    app.run("stop")


def test_a_slow_run_shows_the_instruction_after_a_sleep(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: MOV R0, #100\n        SVC #32\n"
                          "        MOV R1, #1\n        SVC #10\n")
    slow(app, 30)
    segment, rows = app.execute.text_segment, []
    app.run("go")
    run_until(app, lambda: rows.append(segment.pc_row) or app.runner.state is State.FINISHED,
              10)
    shown = [row for k, row in enumerate(rows) if k == 0 or row != rows[k - 1]]
    assert shown == [0, 1, 2, 3, None]


def test_dragging_with_the_middle_button_pastes_nothing(app, tmp_path):
    use_test_clipboard(app.root)
    app.root.clipboard_append("9")                              # the selection, for the test
    loaded(app, tmp_path, READ_INT)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    text = app.messages.run_io
    app.root.tk.call("::tk::TextScanMark", text._w, 5, 5)      # the middle button drags...
    app.root.tk.call("::tk::TextScanDrag", text._w, 5, 40)
    assert app.messages._paste_from("PRIMARY") == "break"       # ...and is released
    assert text.get("input", "end-1c") == ""
    app.root.tk.call("::tk::TextScanMark", text._w, 5, 5)      # a click without a drag
    assert app.messages._paste_from("PRIMARY") == "break"
    assert text.get("input", "end-1c") == "9"
    app.run("stop")


def test_a_line_kept_by_pause_takes_the_keys_typed_while_paused(app, tmp_path):
    loaded(app, tmp_path, TWO_READS)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    app.messages.run_io.insert("end-1c", "12")
    app.run("pause")
    for char in "\b5":
        app.messages._key(SimpleNamespace(char=char))
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    assert app.messages.run_io.get("input", "end-1c") == "15"
    app.run("pause")
    for char in "0\n":                                        # Enter: the read needs no wait
        app.messages._key(SimpleNamespace(char=char))
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    assert app.machine.reg(4) == 150
    assert app.messages.run_io.get("input", "end-1c") == ""    # nothing left for the next
    app.run("stop")


def test_a_character_read_in_part_reaches_the_read_as_typed(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: LDR R1, =0xFF201000\n"
                          "poll:   LDR R0, [R1]\n        TST R0, #0x8000\n"
                          "        BEQ poll\n        LDR R0, =buf\n        MOV R1, #8\n"
                          "        SVC #8\n        SVC #10\n        .data\n"
                          "buf:    .space 8\n")
    app.messages._key(SimpleNamespace(char="\u00e9"))         # two bytes: one is read
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    assert app.messages.run_io.get("input", "end-1c") == ""
    app.messages._enter()
    run_until(app, lambda: app.runner.state is State.FINISHED)
    buf = next(label.address for label in app.program.labels if label.name == "buf")
    assert app.machine.read_memory(buf, 3) == b"\xa9\n\x00"


def test_a_slow_run_ending_with_a_branch_to_itself_shows_the_last_change(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: MOV R0, #1\n        MOV R1, #2\n"
                          "end:    B end\n")
    slow(app, 30)
    go_to_end(app, 10)
    assert app.machine.stop_reason is StopReason.SELF_BRANCH
    assert app.registers._row(1).background and not app.registers._row(0).background


def test_changing_a_register_while_paused_in_a_sleep_keeps_the_sleep(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: MOV R0, #300\n        SVC #32\n"
                          "        MOV R2, #9\n        SVC #10\n")
    app.run("go")
    run_until(app, lambda: app.machine.request is not None)
    app.run("pause")
    app.registers.edit(5)
    app.registers.editor.delete(0, "end")
    app.registers.editor.insert(0, "1")
    app.registers.commit()
    assert app.machine.reg(5) == 1 and app.machine.request is not None    # still asleep
    app.run("stop")


def test_typed_lines_count_toward_the_run_io_limit(app, tmp_path):
    loaded(app, tmp_path, READ_INT)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    type_line(app, "5")
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert run_io(app) == "5\n6\n-- program is finished running --\n"
    assert app.messages._output == len(run_io(app))


# Regressions: Pause, Stop and files opened during a run ----------------------------

@pytest.mark.parametrize("start", ["go", "step"])
def test_a_slow_go_after_pause_in_a_read_waits_again(app, tmp_path, start):
    loaded(app, tmp_path, READ_INT)
    app.run(start)
    run_until(app, lambda: app.runner.state is State.WAITING)
    app.messages.run_io.insert("end-1c", "12")
    app.run("pause")
    slow(app, 30)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING, 5)
    assert app.messages.run_io.get("input", "end-1c") == "12"
    app.run("stop")


def test_a_slow_go_after_pause_in_a_dialog_shows_it_again(app, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(app_module.App, "show_dialog", lambda self, request: shown.append(
        request.service))
    loaded(app, tmp_path, ".global _start\n_start: LDR R0, =m\n        SVC #50\n"
                          "        SVC #10\n.data\nm: .asciz \"Sure?\"\n")
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    app.run("pause")
    slow(app, 30)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING, 5)
    assert shown == [50, 50]
    app.run("stop")


def test_stop_forgets_a_line_kept_by_pause(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: MOV R1, #1\n        SVC #5\n"
                          "        SVC #10\n")
    app.run("step")
    app.run("step")
    app.messages.run_io.insert("end-1c", "12")
    app.run("pause")
    app.run("stop")
    app.run("backstep")                                         # the program is back...
    app.run("step")
    app.run("step")
    assert app.messages.run_io.get("input", "end-1c") == ""    # ...but not the line
    app.run("stop")


def test_only_control_characters_are_left_out_of_typed_keys(app, tmp_path):
    assert keys_as_line("a\u00a0b\u3000c\u200dd\te\rf") == "a\u00a0b\u3000c\u200dd\tef"
    assert keys_as_line("\b12\b3\x7f4") == "14"
    loaded(app, tmp_path, READ_INT)
    assert app.messages._key(SimpleNamespace(char="\u00a0")) == "break"
    assert app.machine.console.pending() == 2                  # a no-break space: two bytes
    assert app.messages._key(SimpleNamespace(char="\ud83d")) is None    # half a pair


def test_a_zero_byte_after_a_newline_adds_no_empty_line(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: MOV R0, #1\n        LDR R1, =msg\n"
                          "        MOV R2, #7\n        SVC #15\n        SVC #10\n"
                          ".data\nmsg: .asciz \"Hello\\n\"\n")
    go_to_end(app)
    assert run_io(app) == "Hello\n-- program is finished running --\n"


def test_assemble_upon_opening_turned_off_during_the_run_assembles_nothing(app, tmp_path):
    app.settings.assemble_on_open = True
    runner = loaded(app, tmp_path, FOREVER)
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) > 100)
    other = tmp_path / "other.s"
    other.write_text(COUNT)
    app.open_path(other)
    app.settings.assemble_on_open = False
    app.run("stop")
    assert not app.assembling and app.runner is runner


def test_assemble_upon_opening_takes_the_tab_on_top_if_the_last_file_fails(app, tmp_path,
                                                                           monkeypatch):
    monkeypatch.setattr(app_module.messagebox, "showerror", lambda *args, **options: None)
    app.settings.assemble_on_open = True
    runner = loaded(app, tmp_path, FOREVER)
    good = tmp_path / "good.s"
    good.write_text(COUNT)
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) > 100)
    app.open_paths([good, tmp_path / "missing.s"])
    app.run("stop")
    wait_for_assembly(app)
    assert app.runner is not runner and app.machine.program.end_address == 0x18


def test_cancel_keeps_the_dialog_text_after_a_zero_byte(app, tmp_path):
    use_test_clipboard(app.root)
    app.settings.popup_input = True
    loaded(app, tmp_path, READ_INT)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    app.root.tk.eval('set ::test_clipboard "12\\u000034"')
    app.root.tk.call("ttk::entry::Paste", app.line_dialog.entry._w)    # the field's paste
    assert app.line_dialog.entry.get() == "12\x0034"
    app.line_dialog.cancel()
    assert app.messages.run_io.get("input", "end-1c") == "1234"
    app.run("stop")


def test_a_slow_run_ending_after_a_sleep_shows_the_last_change(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: MOV R0, #50\n        SVC #32\n")
    slow(app, 30)
    go_to_end(app, 10)
    assert app.machine.stop_reason is StopReason.DROPPED_OFF
    assert app.registers._row(15).background                   # PC, changed by the SVC


def test_a_slow_speed_after_max_shows_the_next_instruction_before_it_runs(app, tmp_path):
    loaded(app, tmp_path, FOREVER)
    slow(app, 5)
    app.run("go")
    max_speed(app)                                              # the yellow row goes...
    slow(app, 5)                                                # ...before the next tick
    app._cancel_tick()
    count, pc = app.machine.reg(0), app.machine.pc
    app._tick()
    assert (app.machine.reg(0), app.machine.pc) == (count, pc)  # shown, not run yet
    assert app.execute.text_segment.pc_row == pc // 4
    max_speed(app)
    run_until(app, lambda: app.machine.reg(0) > 1000)           # a fast run, then slow
    slow(app, 5)
    app._cancel_tick()
    count, pc = app.machine.reg(0), app.machine.pc
    app._tick()
    assert (app.machine.reg(0), app.machine.pc) == (count, pc)
    assert app.execute.text_segment.pc_row == pc // 4
    app.run("stop")


def test_clear_between_the_bytes_of_a_character_keeps_it_whole(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: LDR R1, =0xFF201000\n"
                          "poll:   LDR R0, [R1]\n        TST R0, #0x8000\n"
                          "        BEQ poll\n        STRB R0, [R1]\n        B poll\n")
    app.messages._key(SimpleNamespace(char="\u00e9"))
    for _ in range(5):
        app.run("step")                                         # its first byte is printed
    app.messages.clear(app.messages.run_io)
    for _ in range(5):
        app.run("step")                                         # and its second
    assert run_io(app) == "\u00e9"
    app.run("stop")
    assert run_io(app) == "\u00e9\n-- program is finished running (stopped) --\n"


# Regressions: Go at full speed, and pasted surrogates ------------------------------

def test_go_at_max_after_pause_in_a_sleep_shows_no_next_instruction(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: ADD R1, R1, #1\n        MOV R0, #200\n"
                          "        SVC #32\n        ADD R2, R2, #1\n        B _start\n")
    app.run("go")
    run_until(app, lambda: app.machine.request is not None)     # asleep
    app.run("pause")
    app.run("go")                                               # at max speed, still asleep
    assert app.execute.text_segment.pc_row is None and app._stale
    run_until(app, lambda: app.machine.reg(2) >= 1 and app.machine.request is not None, 5)
    slow(app, 2)
    app._cancel_tick()
    pc, registers = app.machine.pc, [app.machine.reg(n) for n in range(16)]
    app._tick()                                                 # shows first, runs nothing
    assert app.execute.text_segment.pc_row == pc // 4
    assert app.registers.registers == registers
    app.run("stop")


def test_pasting_half_a_surrogate_pair_raises_nothing(app, tmp_path):
    use_test_clipboard(app.root)
    loaded(app, tmp_path, READ_INT)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    app.root.tk.eval('set ::test_clipboard "7\\uD83D"')
    assert app.messages._paste_from("CLIPBOARD") == "break"
    app.messages._enter()                                       # the read gets "7?"
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert "invalid integer input" in app.machine.error


# Regressions: emoji and pasted line breaks -----------------------------------------

SVC54 = """\
        .global _start
_start: LDR     R0, =ask
        LDR     R1, =name
        MOV     R2, #16
        SVC     #54
        MOV     R3, R1
        SVC     #10
        .data
ask:    .asciz  "Name?"
name:   .space  16
"""


wide_characters_are_halves = pytest.mark.skipif(
    sys.platform != "win32", reason="only Windows's Tk keeps such a character as two halves")


def type_emoji_and_backspace(entry, text):
    entry.insert("end", text + "\U0001F600")
    entry.icursor("end")
    press_key(entry, "<Key-BackSpace>")         # Tk 8.6 takes only half of the emoji


@wide_characters_are_halves
def test_backspace_after_an_emoji_in_a_dialog_of_the_program_takes_all_of_it(app, tmp_path):
    loaded(app, tmp_path, SVC54)
    app.run("go")
    run_until(app, lambda: app.service_dialog is not None)
    type_emoji_and_backspace(app.service_dialog.entry, "Ann")
    app.service_dialog.answer(...)
    run_until(app, lambda: app.runner.state is State.FINISHED, 5)
    name = app.machine.program.label_address("name")
    assert app.machine.read_memory(name, 5) == b"Ann\n\0" and app.machine.reg(3) == 0


@wide_characters_are_halves
def test_backspace_after_an_emoji_in_the_input_dialog_takes_all_of_it(app, tmp_path):
    app.settings.popup_input = True
    loaded(app, tmp_path, TWO_READS)
    app.run("go")
    run_until(app, lambda: app.line_dialog is not None)
    type_emoji_and_backspace(app.line_dialog.entry, "5")
    app.line_dialog.ok()
    run_until(app, lambda: app.line_dialog is not None, 5)
    type_emoji_and_backspace(app.line_dialog.entry, "7")
    app.line_dialog.cancel()                                    # the line goes on in Run I/O
    assert app.messages.run_io.get("input", "end-1c") == "7"
    app.messages._enter()
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert (app.machine.reg(4), app.machine.reg(5)) == (5, 7) and not app.machine.error


def test_a_line_break_pasted_into_the_typed_line_sends_it(app, tmp_path):
    use_test_clipboard(app.root)
    loaded(app, tmp_path, TWO_READS)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    app.root.tk.eval('set ::test_clipboard "12\\n"')         # a line copied with its end
    app.messages._paste_from("CLIPBOARD")
    assert not app.messages.run_io.typing                       # sent, as with Enter
    run_until(app, lambda: app.messages.run_io.typing)          # the second read
    assert app.machine.reg(4) == 12 and run_io(app) == "12\n"
    app.messages.paste("34")
    app.messages._enter()
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert app.machine.reg(5) == 34 and not app.machine.error


def test_text_after_a_pasted_line_break_is_typed_ahead(app, tmp_path):
    use_test_clipboard(app.root)
    loaded(app, tmp_path, TWO_READS)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    app.messages.paste("13")
    app.messages.run_io.mark_set("insert", "insert - 1c")      # between 1 and 3
    app.root.tk.eval('set ::test_clipboard "2\\n4"')
    app.messages._paste_from("CLIPBOARD")                       # sends 12; 43 is typed ahead
    run_until(app, lambda: app.machine.reg(4) == 12 and app.messages.run_io.typing, 5)
    assert app.messages.run_io.get("input", "end-1c") == "43"
    assert run_io(app) == "12\n43"
    app.messages._enter()
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert app.machine.reg(5) == 43


@pytest.mark.parametrize("event", ["<<Paste>>", "<<PasteSelection>>"])
def test_a_line_break_pasted_into_the_input_dialog_presses_ok(app, tmp_path, event):
    use_test_clipboard(app.root)
    app.settings.popup_input = True
    loaded(app, tmp_path, TWO_READS)
    app.run("go")
    run_until(app, lambda: app.line_dialog is not None)
    app.root.tk.eval('set ::test_clipboard "5\\n7"')
    press_key(app.line_dialog.entry, event)                     # Tk's paste, then OK
    run_until(app, lambda: app.machine.reg(4) == 5 and app.line_dialog is not None, 5)
    assert app.line_dialog.entry.get() == "7"                   # typed ahead of this read
    assert run_io(app) == "5\n"
    app.line_dialog.ok()
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert app.machine.reg(5) == 7 and not app.machine.error


def test_ok_in_the_input_dialog_gives_the_program_the_line_shown(app, tmp_path):
    use_test_clipboard(app.root)
    app.settings.popup_input = True
    loaded(app, tmp_path, READ_INT)
    app.run("go")
    run_until(app, lambda: app.line_dialog is not None)
    app.root.tk.eval('set ::test_clipboard "12\\u000034"')
    app.root.tk.call("ttk::entry::Paste", app.line_dialog.entry._w)
    app.line_dialog.ok()
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert run_io(app) == "1234\n1235\n-- program is finished running --\n"


# Regressions: selections in Run I/O ------------------------------------------------

NL_PROMPT = """\
        .global _start
_start: LDR     R0, =prompt
        SVC     #4
        SVC     #5
        SVC     #1
        SVC     #10
        .data
prompt: .asciz  "Number?\\n"
"""


def test_a_selection_to_the_end_of_run_io_changes_only_the_typed_line(app, tmp_path):
    loaded(app, tmp_path, NL_PROMPT)
    app.run("go")
    run_until(app, lambda: app.messages.run_io.typing)
    text = app.messages.run_io
    text.insert("end-1c", "12")
    press_key(text, "<<SelectAll>>")                            # Ctrl+/ selects up to "end"
    app.messages._key(SimpleNamespace(char="3", state=0))       # keeps the line's part of it
    text.tk.call("tk::TextInsert", text._w, "3")                # Text's binding for the key
    assert run_io(app) == "Number?\n3"
    text.tag_add("sel", "input", "end")                         # as a triple-click selects
    press_key(text, "<Key-BackSpace>")
    assert run_io(app) == "Number?\n"
    text.delete("end-1c")                       # one index, as Ctrl+K at the line end (macOS)
    assert run_io(app) == "Number?\n"
    text.tag_add("sel", "input", "end")
    app.messages.paste("7")
    assert run_io(app) == "Number?\n7"
    app.run("stop")
    assert run_io(app) == "Number?\n-- program is finished running (stopped) --\n"
