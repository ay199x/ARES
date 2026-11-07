# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Closing the file of the assembled program unloads it: ARES is as right after start-up."""

import time

import pytest
from test_gui_assemble import assemble, open_source
from test_gui_run import FOREVER, READ_INT, loaded, run_io, run_until

from ares.console import FINISHED_STOPPED
from ares.gui.registers import DOUBLES, FPSCR_ROW, ROWS
from ares.machine import INITIAL_CPSR
from ares.runner import State

PROGRAM = """\
        .global _start
_start: LDR     R1, =value
        LDR     R0, [R1]
        VLDR    D1, [R1]
        MOV     R2, #5
        SVC     #1
        SVC     #10
        .data
value:  .word   7, 0x40000000
"""
RUN_COMMANDS = ("go", "step", "backstep", "pause", "stop", "reset")


def start_up_state(app):
    """What the tables show right after ARES starts (or after the program was closed)."""
    return {
        "text": app.execute.text_segment.table.count, "labels": app.execute.labels.labels,
        "data": app.execute.data_segment.machine,
        "registers": app.registers.values(),
        "coproc10": app.coproc10.values(), "coproc11": app.coproc11.values(),
        "marked": [pane.baseline for pane in app.register_panes]
                  + [app.execute.data_segment.baseline],
        "enabled": [app.is_enabled(name) for name in RUN_COMMANDS],
    }


def test_the_start_up_state(app):
    state = start_up_state(app)
    assert state["text"] == 0 and state["labels"] == [] and state["data"] is None
    assert state["registers"] == [0] * 16 + [INITIAL_CPSR, 0]
    assert state["coproc10"] == [0] * 33 and state["coproc11"] == [0] * 33
    assert state["marked"] == [None, None, None, {}]
    assert state["enabled"] == [False] * len(RUN_COMMANDS)


def stepped(app, tmp_path, steps=4):
    loaded(app, tmp_path, PROGRAM)
    app.setting_vars["show_labels"].set(True)
    app.apply_settings()
    for _ in range(steps):
        app.run("step")
    assert app.registers.values()[0] == 7 and app.coproc11.values()[1] == 0x4000000000000007
    assert app.registers.baseline is not None and app.execute.labels.labels
    return app.editor.current


@pytest.mark.parametrize("how", ["close", "close_all", "x"])
def test_closing_the_programs_file_unloads_it(app, tmp_path, how):
    start = start_up_state(app)
    tab = stepped(app, tmp_path)
    app.messages.write_output("kept output\n")
    messages = app.messages.messages.get("1.0", "end-1c")
    if how == "x":                      # the close button on the file's tab
        app.editor.notebook.closing = str(tab)
        app.editor.notebook.event_generate("<<CloseTab>>")
    else:
        app.run(how)
    assert tab not in app.editor.tabs
    assert app.machine is None and app.runner is None and app.program is None
    assert start_up_state(app) == start
    for pane in app.register_panes:
        assert all(pane._row(i).background == "" for i in range(len(pane.ROWS)))
    assert app.messages.messages.get("1.0", "end-1c") == messages      # kept as they were
    # Stepped, the program was paused: it is stopped first, as by Stop.
    assert run_io(app).endswith(f"kept output\n{FINISHED_STOPPED}\n")


@pytest.mark.parametrize("how", ["close", "close_all", "x", "errors"])
def test_an_open_memory_map_loses_the_program(app, tmp_path, how):
    """An open Memory Map shows the map alone again, as right after start-up: when the
    program's file is closed, and when an assemble with errors unloads the program."""
    app.run("memory_map")
    alone = list(app.memory_map.rows)
    loaded(app, tmp_path, PROGRAM)
    assert any(".text of the program" in text for _, text in app.memory_map.rows)
    tab = app.editor.current
    if how == "x":
        app.editor.notebook.closing = str(tab)
        app.editor.notebook.event_generate("<<CloseTab>>")
    elif how == "errors":
        tab.text.insert("end", "        BOGUS   R0\n")
        assemble(app)
        assert app.program is None and tab in app.editor.tabs
    else:
        app.run(how)
    assert app.memory_map.window is not None and app.memory_map.rows == alone
    app.memory_map.close()


@pytest.mark.parametrize("how", ["running", "paused", "waiting"])
def test_a_program_that_runs_is_stopped_first(app, tmp_path, how):
    loaded(app, tmp_path, READ_INT if how == "waiting" else FOREVER)
    app.run("go")
    if how == "waiting":
        run_until(app, lambda: app.runner.state is State.WAITING)
    else:
        run_until(app, lambda: app.machine.reg(0) > 1000)
    if how == "paused":
        app.run("pause")
    app.run("close")
    assert app.machine is None and app._tick_job is None
    assert not app.messages.run_io.typing
    assert run_io(app).rstrip("\n").endswith(FINISHED_STOPPED)
    assert [app.is_enabled(name) for name in RUN_COMMANDS] == [False] * len(RUN_COMMANDS)
    for _ in range(5):                  # nothing of the old run comes back
        app.root.update()
        time.sleep(0.01)
    assert app.machine is None and app.registers.values()[0] == 0


def test_a_finished_or_ready_program_gets_no_stop_line(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    app.run("close")
    assert FINISHED_STOPPED not in run_io(app)
    loaded(app, tmp_path, PROGRAM, "second.s")
    app.run("go")
    run_until(app, lambda: app.runner.state is State.FINISHED)
    app.run("close")
    assert FINISHED_STOPPED not in run_io(app) and app.machine is None


def test_closing_another_file_keeps_the_program(app, tmp_path):
    program_tab = stepped(app, tmp_path)
    open_source(app, tmp_path, "@ notes\n", "notes.s")
    other = app.editor.current
    before = start_up_state(app)
    app.close_tab(other)
    assert app.machine is not None and start_up_state(app) == before
    assert app.editor.current is program_tab


def test_opening_or_switching_files_never_changes_the_tables(app, tmp_path):
    program_tab = stepped(app, tmp_path)
    before = start_up_state(app)
    open_source(app, tmp_path, ".global _start\n_start: SVC #10\n", "other.s")
    assert start_up_state(app) == before
    app.editor.select(program_tab)
    app.root.update()
    assert start_up_state(app) == before
    app.editor.select(app.editor.tabs[-1])
    app.root.update()
    assert start_up_state(app) == before and app.machine is not None


def test_only_assemble_loads_a_program_again(app, tmp_path):
    tab = stepped(app, tmp_path)
    path = tab.path
    app.run("close")
    app.open_path(path)                 # the same file again: still nothing loaded
    assert app.machine is None and app.execute.text_segment.table.count == 0
    assert not app.is_enabled("go")
    assemble(app)
    assert app.machine is not None and app.is_enabled("go")


def test_a_file_closed_while_it_assembles_is_not_loaded(app, tmp_path):
    open_source(app, tmp_path, PROGRAM)
    tab = app.editor.current
    app.run("assemble")
    assert app.assembling
    app.close_tab(tab)
    run_until(app, lambda: not app.assembling)
    app.root.update()
    assert app.machine is None and app.execute.text_segment.table.count == 0
    assert "Assemble: operation completed successfully." in app.messages.messages.get(
        "1.0", "end-1c")
    assert not app.is_enabled("go") and not app.is_enabled("reset")


def test_an_untitled_programs_tab_unloads_it_too(app):
    app.cmd_new()
    tab = app.editor.current
    tab.text.insert("1.0", ".global _start\n_start: MOV R0, #3\n        SVC #10\n")
    assemble(app)
    assert app.machine is not None
    tab.text.edit_modified(False)       # no question about saving
    app.close_tab(tab)
    assert app.machine is None and app.registers.values()[:16] == [0] * 16


def test_the_cpsr_row_shows_its_start_value_again(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: MOVS R0, #0\n        MSR CPSR_c, #0x10\n"
                          "        SVC #10\n")
    app.run("step")
    app.run("step")
    assert app.registers.values()[ROWS.index("CPSR")] != INITIAL_CPSR
    app.run("close")
    values = app.registers.values()
    assert values[ROWS.index("CPSR")] == INITIAL_CPSR and values[ROWS.index("SPSR")] == 0
    assert app.coproc11.values()[FPSCR_ROW] == 0 and len(DOUBLES) == 32
