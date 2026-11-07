# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The text cursor of ARES Messages and Run I/O.

ARES Messages never shows a blinking text cursor. Run I/O shows one only
while the program waits for a line typed there (a read service); not
without a program, when ready, while running without a read, finished,
stopped, after a runtime error, after Reset or once the program's file is
closed. Text is still selected with the mouse and copied in both panes,
and keys typed while a program runs still reach the JTAG UART.

Hidden windows never have the keyboard focus, so Tk never blinks a cursor
in these tests: they check the options with which Tk draws it once the
text has the focus.
"""

import tkinter as tk
from tkinter import font as tkfont
from types import SimpleNamespace

import pytest
from conftest import lay_out, press_key, pump, use_test_clipboard
from test_gui_run import ECHO, PROMPT, READ_INT, TWO_READS, loaded, run_io, run_until, type_line

from ares.gui.app import PANE_FONT_SIZE
from ares.gui.messages import MessagesPane
from ares.gui.widgets import ReadOnlyText
from ares.runner import State
from ares.settings import DEFAULT_FONT

# The options with which Tk draws a text's cursor while the text has the keyboard focus.
CURSOR = ("insertwidth", "insertontime", "insertofftime", "insertborderwidth", "blockcursor",
          "insertunfocussed")
READ_THEN_LOOP = """\
        .global _start
_start: SVC     #5
loop:   ADD     R1, R1, #1
        B       loop
"""
READ_THEN_FAIL = """\
        .global _start
_start: SVC     #5
        MOV     R0, #0x50000000
        LDR     R1, [R0]
        SVC     #10
"""
STEP_TO_READ = ".global _start\n_start: MOV R1, #1\n        SVC #5\n        SVC #10\n"


def cursor(text):
    """A text's cursor options, as Tk gives them."""
    return {option: str(text.cget(option)) for option in CURSOR}


def tk_cursor(widget):
    """The cursor of a new Tk text: a bar 2 pixels wide, on for 600 ms and off for 300 ms."""
    text = tk.Text(widget.winfo_toplevel())
    try:
        return cursor(text)
    finally:
        text.destroy()


def draws_cursor(text):
    """True when Tk draws a text cursor in text once it has the keyboard focus.

    Tk draws a bar insertwidth pixels wide (a whole character with
    blockcursor), on for insertontime milliseconds of each blink: none when
    the bar has no width or is never on.
    """
    width = text.winfo_pixels(text.cget("insertwidth"))
    block = text.tk.getboolean(text.cget("blockcursor"))
    return (width > 0 or block) and int(text.cget("insertontime")) > 0


def check_cursors(app, typing=False):
    """ARES Messages draws no cursor; Run I/O one exactly while a line is typed there, then
    the cursor of every Tk text; the editor's texts keep that cursor all the time."""
    normal = tk_cursor(app.root)
    pane = app.messages
    assert pane.run_io.typing is typing
    assert not draws_cursor(pane.messages)
    assert draws_cursor(pane.run_io) is typing
    if typing:
        assert cursor(pane.run_io) == normal
    for tab in app.editor.tabs:
        assert cursor(tab.text) == normal


def waiting(app):
    run_until(app, lambda: app.runner.state is State.WAITING)


def drag(text, first, last):
    """Select from index first to index last with the mouse, through Tk's own bindings."""
    pump(text.winfo_toplevel())
    (x0, y0, _, h0), (x1, y1, _, h1) = text.bbox(first), text.bbox(last)
    text.event_generate("<ButtonPress-1>", x=x0 + 1, y=y0 + h0 // 2)
    text.event_generate("<B1-Motion>", x=x1 + 1, y=y1 + h1 // 2)
    text.event_generate("<ButtonRelease-1>", x=x1 + 1, y=y1 + h1 // 2)


def copied(app, text, monkeypatch):
    """Press Ctrl+C with the keyboard focus in text; returns what the clipboard then holds."""
    monkeypatch.setattr(app.root, "focus_get", lambda: text)
    press_key(text, app._sequences("Ctrl+C")[0])
    return app.root.clipboard_get()


# The panes alone ------------------------------------------------------------------------

@pytest.fixture
def pane(area):
    frame = area(600, 200)
    font = tkfont.Font(root=frame, family=DEFAULT_FONT, size=PANE_FONT_SIZE)
    pane = MessagesPane(frame, font, lambda target: None)
    pane.pack(fill="both", expand=True)
    assert lay_out(frame.winfo_toplevel())
    return pane


def test_run_io_draws_a_cursor_exactly_while_a_line_is_typed(pane):
    normal = tk_cursor(pane)
    run_io = pane.run_io
    assert not draws_cursor(pane.messages) and not draws_cursor(run_io)
    pane.write_output("N? ")
    pane.begin_line("4")
    assert run_io.typing and cursor(run_io) == normal
    lines = []
    pane.on_line = lambda line, rest: lines.append(line)
    pane._enter()                                           # Enter sends the line
    assert lines == ["4"] and not draws_cursor(run_io)
    pane.begin_line()
    assert cursor(run_io) == normal
    pane.paste("7\n")                                       # a pasted line break sends it too
    assert lines == ["4", "7"] and not draws_cursor(run_io)
    pane.begin_line("12")
    assert pane.end_line() == "12" and not draws_cursor(run_io)       # the wait ended
    assert pane.end_line() is None and not draws_cursor(run_io)
    assert not draws_cursor(pane.messages)


def test_clear_keeps_the_cursor_of_the_line_being_typed(pane):
    normal = tk_cursor(pane)
    pane.write_message("Assemble: assembling prog.s")
    pane.write_output("N? ")
    pane.begin_line("12")
    pane.clear(pane.run_io)
    assert pane.run_io.get("input", "end-1c") == "12" and cursor(pane.run_io) == normal
    pane.clear(pane.messages)
    assert cursor(pane.run_io) == normal and not draws_cursor(pane.messages)


def test_keys_for_a_running_program_show_no_cursor(pane):
    keys = []
    pane.on_keys = keys.append
    pane.keys_wanted = True                                 # a program is ready or runs
    for char in "ok.":
        assert pane._key(SimpleNamespace(char=char)) == "break"
    assert keys == list("ok.") and not draws_cursor(pane.run_io)
    assert pane.run_io.get("1.0", "end-1c") == ""           # the keys are not shown


def test_other_read_only_texts_keep_the_cursor_of_tk(tk_root):
    # The tools' logs and help texts show the cursor while they have the focus.
    text = ReadOnlyText(tk_root)
    try:
        assert cursor(text) == tk_cursor(tk_root) and draws_cursor(text)
    finally:
        text.destroy()


# In the window, in every state of a program -----------------------------------------------

def test_no_cursor_without_a_program(app):
    check_cursors(app)
    app.cmd_new()                                           # an empty file, nothing assembled
    check_cursors(app)


def test_no_cursor_when_assembled_and_ready(app, tmp_path):
    loaded(app, tmp_path, READ_INT)
    assert app.runner.state is State.READY
    check_cursors(app)
    assert app.messages._key(SimpleNamespace(char="4")) == "break"     # typed ahead of the read
    check_cursors(app)


def test_no_cursor_while_running_and_keys_still_reach_the_jtag_uart(app, tmp_path):
    loaded(app, tmp_path, ECHO)
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) == 0 and app.machine.pc > 4)
    assert app.runner.state is State.RUNNING
    check_cursors(app)
    for char in "hi.":
        assert app.messages._key(SimpleNamespace(char=char)) == "break"
        check_cursors(app)
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert run_io(app) == "hi.\n-- program is finished running --\n"
    check_cursors(app)


def test_the_cursor_shows_while_a_read_waits_and_goes_when_it_ends(app, tmp_path):
    loaded(app, tmp_path, TWO_READS)
    app.run("go")
    for line in ("1", "2"):
        waiting(app)
        check_cursors(app, typing=True)
        type_line(app, line)
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert (app.machine.reg(4), app.machine.reg(5)) == (1, 2)
    check_cursors(app)


def test_no_cursor_once_the_line_is_sent_and_the_program_runs_on(app, tmp_path):
    loaded(app, tmp_path, READ_THEN_LOOP)
    app.run("go")
    waiting(app)
    type_line(app, "5")
    run_until(app, lambda: app.machine.reg(1) > 100)
    assert app.runner.state is State.RUNNING
    check_cursors(app)
    app.run("stop")
    check_cursors(app)


def test_stop_in_a_read_takes_the_cursor_away(app, tmp_path):
    loaded(app, tmp_path, READ_INT)
    app.run("go")
    waiting(app)
    app.messages.run_io.insert("end-1c", "12")
    app.run("stop")                                         # F11
    assert run_io(app) == "-- program is finished running (stopped) --\n"
    check_cursors(app)


def test_pause_and_backstep_in_a_read_take_the_cursor_away_until_it_waits_again(app, tmp_path):
    loaded(app, tmp_path, STEP_TO_READ)
    app.run("step")                                         # Step records for Backstep
    app.run("step")
    assert app.runner.state is State.WAITING
    check_cursors(app, typing=True)
    app.run("backstep")
    check_cursors(app)
    app.run("go")
    waiting(app)
    check_cursors(app, typing=True)
    app.run("pause")
    check_cursors(app)
    app.run("go")
    waiting(app)
    check_cursors(app, typing=True)
    app.run("stop")
    check_cursors(app)


@pytest.mark.parametrize("source, line", [(READ_THEN_FAIL, "1"), (READ_INT, "x")],
                         ids=["after the read", "in the read"])
def test_no_cursor_after_a_runtime_error(app, tmp_path, source, line):
    loaded(app, tmp_path, source)
    app.run("go")
    waiting(app)
    type_line(app, line)
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert app.machine.error is not None
    check_cursors(app)


def test_reset_in_a_read_takes_the_cursor_away_until_the_next_read(app, tmp_path):
    loaded(app, tmp_path, READ_INT)
    app.run("go")
    waiting(app)
    app.run("reset")
    assert app.runner.state is State.READY
    check_cursors(app)
    app.run("go")
    waiting(app)
    check_cursors(app, typing=True)
    app.run("stop")
    check_cursors(app)


def test_closing_the_programs_file_in_a_read_takes_the_cursor_away(app, tmp_path):
    loaded(app, tmp_path, READ_INT)
    app.run("go")
    waiting(app)
    app.cmd_close()
    assert app.runner is None and app.editor.tabs == []
    check_cursors(app)


def test_the_input_dialog_leaves_run_io_without_a_cursor_until_cancel(app, tmp_path):
    app.settings.popup_input = True
    loaded(app, tmp_path, READ_INT)
    app.run("go")
    waiting(app)
    assert app.line_dialog is not None
    check_cursors(app)
    app.line_dialog.cancel()                                # the line is typed in Run I/O now
    check_cursors(app, typing=True)
    app.run("stop")
    check_cursors(app)


def test_clear_in_the_window_keeps_the_cursor_of_the_line(app, tmp_path):
    loaded(app, tmp_path, READ_INT)
    app.run("go")
    waiting(app)
    app.messages.run_io.insert("end-1c", "12")
    app.messages.clear(app.messages.run_io)
    assert app.messages.run_io.get("input", "end-1c") == "12"
    check_cursors(app, typing=True)
    app.messages.clear(app.messages.messages)
    check_cursors(app, typing=True)
    app.run("stop")


def test_text_is_still_selected_with_the_mouse_and_copied_in_both_panes(app, tmp_path,
                                                                        monkeypatch):
    use_test_clipboard(app.root)
    loaded(app, tmp_path, PROMPT)                           # "N? ", then a read
    assert lay_out(app.root)
    pane = app.messages
    pane.show_messages()
    drag(pane.messages, "1.0", "1.8")
    assert copied(app, pane.messages, monkeypatch) == "Assemble"
    check_cursors(app)
    app.run("go")
    waiting(app)
    drag(pane.run_io, "1.0", "1.2")                         # the prompt, while a line is typed
    assert copied(app, pane.run_io, monkeypatch) == "N?"
    check_cursors(app, typing=True)
    type_line(app, "5")
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert run_io(app) == "N? 5\n-- program is finished running --\n"
    drag(pane.run_io, "2.0", "2.2")                         # the end line: no line is typed
    assert copied(app, pane.run_io, monkeypatch) == "--"
    check_cursors(app)
