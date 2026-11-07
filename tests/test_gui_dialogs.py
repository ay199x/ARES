# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The program's dialogs (SVC #50 to #59), Tools > Memory Map and File > Dump Memory."""

from types import SimpleNamespace

import pytest
from conftest import press_key
from test_gui_assemble import assemble, open_source
from test_gui_run import go_to_end, run_until

from ares.gui import dialogs
from ares.gui.dialogs import dump_bytes, segment_ranges
from ares.runner import State


def program(service, setup="", data=""):
    """A program that asks one dialog service with the message "Sure?" and then exits."""
    return (".global _start\n_start: LDR R0, =m\n" + setup + f"        SVC #{service}\n"
            "        MOV R5, R0\n        MOV R6, R1\n        SVC #10\n"
            ".data\nm: .asciz \"Sure?\"\n" + data)


def asked(app, tmp_path, source, name="prog.s"):
    """Assemble source and Go until its dialog window is open; returns the dialog."""
    open_source(app, tmp_path, source, name)
    assemble(app)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    assert app.service_dialog is not None
    return app.service_dialog


def answer(app, dialog, value, text=None):
    if text is not None:
        dialog.entry.insert(0, text)
    dialog.answer(value)
    run_until(app, lambda: app.runner.state is not State.RUNNING)


@pytest.mark.parametrize("button, value", [("Yes", 0), ("No", 1), ("Cancel", 2)])
def test_confirm_dialog(app, tmp_path, button, value):
    dialog = asked(app, tmp_path, program(50))
    assert dialog.text == "Sure?" and list(dialog.buttons) == ["Yes", "No", "Cancel"]
    assert dialog.entry is None
    dialog.buttons[button].invoke()
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert app.machine.reg(5) == value and app.service_dialog is None


def test_the_dialogs_of_a_program_have_the_short_title(app, tmp_path):
    dialog = asked(app, tmp_path, program(50))
    assert dialog.window.title() == "ARES"


def test_escape_and_closing_the_window_cancel(app, tmp_path):
    dialog = asked(app, tmp_path, program(50))
    dialog.answer(dialog.cancel_value)
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert app.machine.reg(5) == 2


@pytest.mark.parametrize("typed, value, status", [
    ("42", 42, 0), (" -7 ", 0xFFFFFFF9, 0), ("abc", 0, 0xFFFFFFFF), ("", 0, 0xFFFFFFFD)])
def test_input_integer_dialog(app, tmp_path, typed, value, status):
    dialog = asked(app, tmp_path, program(51))
    assert list(dialog.buttons) == ["OK", "Cancel"] and dialog.entry is not None
    answer(app, dialog, ..., typed)
    assert (app.machine.reg(5), app.machine.reg(6)) == (value, status)


def test_input_integer_dialog_cancelled(app, tmp_path):
    dialog = asked(app, tmp_path, program(51))
    dialog.buttons["Cancel"].invoke()
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert app.machine.reg(6) == 0xFFFFFFFE


def test_input_string_dialog(app, tmp_path):
    dialog = asked(app, tmp_path, program(54, "        LDR R1, =buffer\n        MOV R2, #8\n",
                                          "buffer: .space 8\n"))
    answer(app, dialog, ..., "Hi")
    buffer = app.program.label_address("buffer")
    assert app.machine.read_memory(buffer, 4) == b"Hi\n\0" and app.machine.reg(6) == 0


@pytest.mark.parametrize("kind, icon", [(0, "message_error"), (1, "message_information"),
                                        (2, "message_warning"), (3, "message_question"),
                                        (9, "message_information")])
def test_message_dialog_icons(app, tmp_path, kind, icon):
    dialog = asked(app, tmp_path, program(55, f"        MOV R1, #{kind}\n"))
    image = str(app.message_images[icon])
    labels = [w for w in dialog.window.winfo_children()[0].winfo_children()
              if w.winfo_class() == "TLabel"]
    assert [str(name) for name in labels[0].cget("image")] == [image]
    assert list(dialog.buttons) == ["OK"]
    answer(app, dialog, None)
    assert app.runner.state is State.FINISHED


def test_message_dialogs_with_a_value(app, tmp_path):
    dialog = asked(app, tmp_path, program(56, "        MVN R1, #4\n"))
    assert dialog.text == "Sure?-5"
    answer(app, dialog, None)
    dialog = asked(app, tmp_path, program(59, "        LDR R1, =t\n", "t: .asciz \" Yes\"\n"),
                   "string.s")
    assert dialog.text == "Sure? Yes"


@pytest.mark.parametrize("service, typed, value, status", [
    (52, "2.5", 0x40200000, 0), (52, "abc", 0, 0xFFFFFFFF), (52, "", 0, 0xFFFFFFFD),
    (53, "-0.5", 0xBFE0000000000000, 0), (53, "1e400", 0x7FF0000000000000, 0)])
def test_input_float_and_double_dialogs(app, tmp_path, service, typed, value, status):
    dialog = asked(app, tmp_path, program(service))
    assert list(dialog.buttons) == ["OK", "Cancel"] and dialog.entry is not None
    answer(app, dialog, ..., typed)
    number = app.machine.single(0) if service == 52 else app.machine.double(0)
    assert (number, app.machine.reg(6)) == (value, status)


def test_message_dialogs_with_a_float_or_a_double(app, tmp_path):
    dialog = asked(app, tmp_path, program(57, "        LDR R1, =0x3FC00000\n"
                                              "        VMOV S0, R1\n"))
    assert dialog.text == "Sure?1.5" and dialog.entry is None and list(dialog.buttons) == ["OK"]
    labels = [w for w in dialog.window.winfo_children()[0].winfo_children()
              if w.winfo_class() == "TLabel"]
    assert [str(name) for name in labels[0].cget("image")] == [
        str(app.message_images["message_information"])]
    answer(app, dialog, None)
    dialog = asked(app, tmp_path, program(58, "        LDR R1, =0x9999999A\n"
                                              "        LDR R2, =0x3FB99999\n"
                                              "        VMOV D0, R1, R2\n"), "double.s")
    assert dialog.text == "Sure?0.1"


def test_stop_and_reset_close_the_dialog(app, tmp_path):
    dialog = asked(app, tmp_path, program(50))
    app.run("stop")
    assert app.service_dialog is None and dialog.window is None
    app.run("reset")
    dialog = asked(app, tmp_path, program(50))
    app.run("reset")
    assert app.service_dialog is None and dialog.window is None
    assert app.runner.state is State.READY


def test_step_answers_its_dialog_too(app, tmp_path):
    open_source(app, tmp_path, program(50))
    assemble(app)
    app.run("step")
    app.run("step")
    assert app.runner.state is State.WAITING and app.service_dialog is not None
    app.service_dialog.buttons["No"].invoke()
    assert app.runner.state is State.PAUSED and app.machine.reg(0) == 1


# Tools > Memory Map ------------------------------------------------------------

def test_memory_map_without_a_program(app):
    app.run("memory_map")
    rows = app.memory_map.rows
    assert rows[0] == ("0x00000000 - 0x3fffffff",
                       "DDR3 memory, 1 GB (the program, its data and the heap)")
    assert ("0xff201000 - 0xff201007", "JTAG UART: data register, then control register") in rows
    assert rows[3][0] == "0xffff0000 - 0xffffffff"     # its rows: test_gui_memory_map.py
    assert rows[-1][0] == "other addresses"
    window = app.memory_map.window
    app.run("memory_map")                               # the same window again
    assert app.memory_map.window is window
    app.memory_map.close()


def test_memory_map_shows_the_program(app, tmp_path):
    open_source(app, tmp_path, program(10))
    assemble(app)
    app.run("memory_map")
    rows = app.memory_map.rows
    assert [address for address, _ in rows] == [
        "0x00000000 - 0x3fffffff", "0x00000000 - 0x00000017", "0x00000018 - 0x0000001d",
        "0xff200000 - 0xff20ffff", "0xff201000 - 0xff201007", "0xffff0000 - 0xffffffff",
        "", "", "", "other addresses"]                  # the on-chip memory's further lines
    assert rows[1][1] == "    .text of the program, 24 bytes"       # under DDR3
    assert rows[2][1] == "    .data of the program, 6 bytes"


# File > Dump Memory -------------------------------------------------------------

DUMPED = """\
        .global _start
_start: LDR     R1, =value
        MOV     R0, #0x41
        STR     R0, [R1]
        SVC     #10
        .data
value:  .word   7
more:   .byte   1, 2
"""


def open_dump(app):
    """The open Dump Memory dialog object, made by the command."""
    created = []
    original = dialogs.DumpMemoryDialog.__init__

    def init(self, *args, **options):
        original(self, *args, **options)
        created.append(self)
    return created, init


def test_dump_memory_needs_a_program(app):
    assert not app.is_enabled("dump_memory")


def test_segment_ranges(app, tmp_path):
    open_source(app, tmp_path, DUMPED)
    assemble(app)
    assert segment_ranges(app.program) == {".text": (0, 0x14), ".data": (0x14, 0x1A)}
    open_source(app, tmp_path, ".global _start\n_start: B .\n", "nodata.s")
    assemble(app)
    assert segment_ranges(app.program) == {".text": (0, 4)}


def test_dump_bytes():
    assert dump_bytes(b"\x01\x02\x03\x04\x05", True) == b"\x01\x02\x03\x04\x05"
    assert dump_bytes(b"\x01\x02\x03\x04\x05", False) == b"04030201\n00000005\n"


@pytest.mark.parametrize("segment, form, expected", [
    (".text", "Hexadecimal text", b"e59f1008\ne3a00041\ne5810000\nef00000a\n00000014\n"),
    (".data", "Binary", b"\x41\x00\x00\x00\x01\x02"),
])
def test_dump_memory_writes_the_memory_as_it_is_now(app, tmp_path, monkeypatch, segment, form,
                                                    expected):
    open_source(app, tmp_path, DUMPED)
    assemble(app)
    go_to_end(app)                                      # value becomes 0x41
    created, init = open_dump(app)
    monkeypatch.setattr(dialogs.DumpMemoryDialog, "__init__", init)
    path = tmp_path / "out.dump"
    monkeypatch.setattr(dialogs.filedialog, "asksaveasfilename", lambda **options: str(path))
    app.run("dump_memory")
    dialog = created[-1]
    dialog.segment.set(segment)
    dialog.format.set(form)
    assert dialog.dump() == str(path)
    assert path.read_bytes() == expected and dialog.window is None
    assert app.messages.messages.get("1.0", "end-1c").splitlines()[-1].startswith(
        f"Dump Memory: {segment} (0x")


def test_dump_memory_cancelled_or_failing(app, tmp_path, monkeypatch):
    open_source(app, tmp_path, DUMPED)
    assemble(app)
    created, init = open_dump(app)
    monkeypatch.setattr(dialogs.DumpMemoryDialog, "__init__", init)
    monkeypatch.setattr(dialogs.filedialog, "asksaveasfilename", lambda **options: "")
    app.run("dump_memory")
    dialog = created[-1]
    assert dialog.dump() is None and dialog.window is not None
    folder = tmp_path / "a folder"
    folder.mkdir()
    monkeypatch.setattr(dialogs.filedialog, "asksaveasfilename", lambda **options: str(folder))
    assert dialog.dump() is None and dialog.window is not None
    assert dialog.status.cget("text").startswith("Cannot write")
    dialog.close()


# Regressions ----------------------------------------------------------------------

def test_dialogs_of_the_program_leave_the_run_keys_working(app, tmp_path):
    dialog = asked(app, tmp_path, program(50))
    assert dialog.window.grab_status() is None              # the window is not locked
    for key in ("F8", "F9", "F11", "F12"):
        assert dialog.window.bind(f"<Key-{key}>")
    press_key(dialog.buttons["Yes"], "<Key-F11>")           # Stop, from inside the dialog
    assert app.runner.state is State.FINISHED and app.service_dialog is None


def test_the_input_dialog_has_the_run_keys_and_the_keys_typed_before(app, tmp_path):
    app.settings.popup_input = True
    open_source(app, tmp_path, ".global _start\n_start: SVC #5\n        SVC #10\n")
    assemble(app)
    app.messages._key(SimpleNamespace(char="7"))
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    dialog = app.line_dialog
    assert dialog.entry.get() == "7" and dialog.window.grab_status() is None
    press_key(dialog.entry, "<Key-F9>")                     # Pause
    assert app.runner.state is State.PAUSED and app.line_dialog is None


def test_dump_memory_closes_when_assembling_again(app, tmp_path):
    open_source(app, tmp_path, DUMPED)
    assemble(app)
    app.run("dump_memory")
    dialog = app.dump_dialog
    assert dialog is not None and dialog.window.grab_status() is None
    app.run("dump_memory")                                  # the same window again
    assert app.dump_dialog is dialog
    assemble(app)
    assert dialog.window is None and app.dump_dialog is None


def test_memory_map_follows_the_assembled_program(app, tmp_path):
    app.run("memory_map")
    assert not any(".text" in text for _, text in app.memory_map.rows)
    open_source(app, tmp_path, DUMPED)
    assemble(app)
    assert any(".text of the program" in text for _, text in app.memory_map.rows)
    app.memory_map.close()


def test_dump_memory_needs_something_to_dump(app, tmp_path):
    open_source(app, tmp_path, ".global _start\n_start:\n")
    assemble(app)
    assert app.runner is not None and not app.is_enabled("dump_memory")
