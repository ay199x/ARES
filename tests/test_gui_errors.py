# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""A runtime error clearly ends the program, on every way a program can fail.

The run is over as after a normal end: nothing waits for input, typed keys
no longer reach the program, Go and Step are gray, Reset and Assemble are
not, Backstep is available while it has history. The failing row is light
red, also when PC is changed afterwards, Run I/O ends with the error and the
end line, ARES Messages with the error and "Go: execution terminated with
errors.", and Reset prepares a new run.
"""

import pytest
from conftest import PROGRAMS, press_key
from test_gui_assemble import assemble
from test_gui_editing import double_click, type_into
from test_gui_run import go_to_end, loaded, run_io, run_until, slow, type_line

from ares.console import FINISHED_ERROR
from ares.gui import app as app_module
from ares.gui.app import RUN_FAILED
from ares.gui.execute import CURRENT, FAILED
from ares.gui.registers import ROWS
from ares.runner import State

# (source, where the failing instruction is, the error's message)
FAILURES = {
    "memory": (".global _start\n_start: MOV R0, #0x50000000\n        LDR R1, [R0]\n"
               "        SVC #10\n",
               "at line 3 (address 0x00000004)", "memory access out of range at 0x50000000"),
    "undefined": (".global _start\n_start: MOV R0, #1\n        UDF #0\n        SVC #10\n",
                  "at line 3 (address 0x00000004)", "undefined instruction"),
    "service": (".global _start\n_start: MOV R0, #1\n        SVC #99\n        SVC #10\n",
                "at line 3 (address 0x00000004)", "unknown service number 99 (SVC #99)"),
    "no code": (".global _start\n_start: LDR R0, =0x30000000\n        BX R0\n",
                "at address 0x30000000", "no program code at 0x30000000"),
}


def messages(app):
    return app.messages.messages.get("1.0", "end-1c").splitlines()


def finished(app):
    run_until(app, lambda: app.runner.state is not State.RUNNING)


def check_ended(app, error, row=None):
    """The run is over after a runtime error, and every part of the window says so."""
    assert app.runner.state is State.FINISHED and app.machine.error == error
    assert not app.is_enabled("go") and not app.is_enabled("step")
    assert app.is_enabled("reset") and app.is_enabled("assemble")
    assert app.is_enabled("backstep") == bool(app.machine.history)
    assert not app.messages.run_io.typing and not app.messages.keys_wanted
    assert app.line_dialog is None and app.service_dialog is None
    assert run_io(app).endswith(error + "\n" + FINISHED_ERROR + "\n")
    assert messages(app)[-2:] == [error, RUN_FAILED]
    segment = app.execute.text_segment
    assert segment.pc_row == row
    if row is not None:
        assert segment._row(row).background == FAILED       # light red, not yellow


def check_reset(app):
    app.run("reset")
    segment = app.execute.text_segment
    assert app.runner.state is State.READY and app.is_enabled("go")
    assert segment.pc_row == 0 and segment._row(0).background == CURRENT
    assert app.machine.error is None


def row_of_failure(name):
    return None if name == "no code" else 1


@pytest.mark.parametrize("name", FAILURES)
def test_a_failing_instruction_ends_the_program(app, tmp_path, name):
    source, where, message = FAILURES[name]
    loaded(app, tmp_path, source)
    go_to_end(app)
    check_ended(app, f"Runtime error {where}: {message}", row_of_failure(name))
    check_reset(app)


@pytest.mark.parametrize("name", FAILURES)
def test_a_failing_step_ends_the_program_and_keeps_backstep(app, tmp_path, name):
    source, where, message = FAILURES[name]
    loaded(app, tmp_path, source)
    for _ in range(3):                      # "no code" fails on the step after the jump
        if app.runner.state is not State.FINISHED:
            app.run("step")
    check_ended(app, f"Runtime error {where}: {message}", row_of_failure(name))
    assert app.is_enabled("backstep")                       # the steps before can be undone
    app.run("backstep")
    assert app.runner.state is not State.FINISHED
    check_next(app)
    check_reset(app)


def coloured(app):
    """{row: colour} of the Text Segment's rows that have a colour."""
    segment = app.execute.text_segment
    rows = (segment._row(row) for row in range(len(segment.rows)))
    return {index: row.background for index, row in enumerate(rows) if row.background}


def check_next(app):
    """The next instruction's row is yellow, and no row is light red."""
    segment = app.execute.text_segment
    assert segment.pc_row is not None and segment.pc_row == segment.row_of(app.machine.pc)
    assert coloured(app) == {segment.pc_row: CURRENT}


def edit_pc(app, text):
    """Type a value into PC's field and press Enter."""
    pane = app.registers
    double_click(pane, ROWS.index("PC"))
    type_into(pane, text)
    press_key(pane.editor, "<Return>")
    assert pane.editor is None and app.machine.pc == int(text, 0)


@pytest.mark.parametrize("pc", ["0x0", "0x8"])
def test_the_failing_row_stays_light_red_when_pc_is_changed(app, tmp_path, pc):
    """The run is over: the new PC's row gets no colour, as after a normal end."""
    source, where, message = FAILURES["memory"]
    loaded(app, tmp_path, source)
    go_to_end(app)
    edit_pc(app, pc)
    check_ended(app, f"Runtime error {where}: {message}", 1)
    assert coloured(app) == {1: FAILED}
    check_reset(app)


def test_no_row_turns_light_red_when_pc_is_changed_after_no_program_code(app, tmp_path):
    source, where, message = FAILURES["no code"]
    loaded(app, tmp_path, source)
    go_to_end(app)
    assert coloured(app) == {}
    edit_pc(app, "4")
    check_ended(app, f"Runtime error {where}: {message}", None)
    assert coloured(app) == {}


def test_backstep_after_a_failing_step_and_a_pc_change_shows_the_next_instruction(app, tmp_path):
    source, where, message = FAILURES["memory"]
    loaded(app, tmp_path, source)
    app.run("step")
    app.run("step")
    edit_pc(app, "8")
    check_ended(app, f"Runtime error {where}: {message}", 1)
    app.run("backstep")
    assert app.runner.state is State.PAUSED and app.machine.pc == 0
    check_next(app)


def test_a_new_assemble_forgets_the_failing_row(app, tmp_path):
    source, where, message = FAILURES["memory"]
    loaded(app, tmp_path, source)
    go_to_end(app)
    edit_pc(app, "0x8")
    assemble(app)
    assert app.runner.state is State.READY
    check_next(app)


def test_a_slow_run_ends_the_same_way(app, tmp_path):
    source, where, message = FAILURES["memory"]
    loaded(app, tmp_path, source)
    slow(app, 30)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.FINISHED)
    check_ended(app, f"Runtime error {where}: {message}", 1)


def circle(app):
    app.open_path(PROGRAMS / "circle.s")
    assemble(app)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)


CIRCLE_ERROR = "Runtime error at line 23 (address 0x00000008): invalid float input (SVC #6)"


def test_a_wrong_number_typed_in_run_io_ends_the_program(app):
    """A radius of "rk" for circle.s: Run I/O and ARES Messages say the program has ended."""
    circle(app)
    type_line(app, "rk")
    finished(app)
    check_ended(app, CIRCLE_ERROR, 2)
    assert run_io(app) == "Radius: rk\n" + CIRCLE_ERROR + "\n" + FINISHED_ERROR + "\n"
    check_reset(app)


def test_a_wrong_number_typed_in_the_input_window_ends_the_program(app):
    app.settings.popup_input = True
    circle(app)
    assert app.line_dialog is not None
    app.line_dialog.entry.insert(0, "rk")
    app.line_dialog.ok()
    finished(app)
    check_ended(app, CIRCLE_ERROR, 2)
    check_reset(app)


def test_an_error_inside_a_dialog_service_ends_the_program(app, tmp_path):
    loaded(app, tmp_path, """\
        .global _start
_start: LDR     R0, =ask
        LDR     R1, =0x50000000
        MOV     R2, #8
        SVC     #54
        SVC     #10
        .data
ask:    .asciz  "Name?"
""")
    app.run("go")
    run_until(app, lambda: app.service_dialog is not None)
    app.service_dialog.entry.insert(0, "hi")
    app.service_dialog.answer(...)                          # OK: the text goes nowhere
    finished(app)
    error = ("Runtime error at line 5 (address 0x0000000c): "
             "memory access out of range at 0x50000000")
    check_ended(app, error, 3)
    check_reset(app)


def test_a_dialog_service_with_a_bad_message_ends_the_program(app, tmp_path, hidden_windows,
                                                              monkeypatch):
    made = []
    dialog = app_module.ServiceDialog
    monkeypatch.setattr(app_module, "ServiceDialog",
                        lambda *args: made.append(args) or dialog(*args))
    loaded(app, tmp_path, ".global _start\n_start: LDR R0, =0x50000000\n        SVC #50\n"
                          "        SVC #10\n")
    go_to_end(app)
    assert made == [] and hidden_windows.shown == {app.root}    # no dialog was made or shown
    assert app.runner.state is State.FINISHED and messages(app)[-1] == RUN_FAILED
    assert run_io(app).endswith(FINISHED_ERROR + "\n")


def test_a_normal_end_says_nothing_about_errors(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: MOV R0, #1\n        SVC #10\n")
    go_to_end(app)
    assert RUN_FAILED not in messages(app) and FINISHED_ERROR not in run_io(app)
