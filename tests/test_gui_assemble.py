# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Assembling from the window: messages, clickable errors, gutter markers and settings."""

import shutil
import threading
import time
from tkinter import ttk

import pytest
from conftest import PROGRAMS, press_key

from ares import assembler
from ares.gui import app as app_module
from ares.gui.widgets import SHORTCUT_TAG
from ares.gui import dialogs
from ares.settings import DEFAULT_SIZE, Settings
from ares.toolchain import ToolchainMissingError

CAPITALS = ".global _start\n_start:\n    mov r0, #1\n    SVC #10\n    add r1, r1, #2\n"
HELLO = (PROGRAMS / "hello.s").read_text()
SLOW = ".global _start\n_start:\n    NOP\nx = 0\n.rept 6000000\nx = x + 1\n.endr\n"


def wait_for_assembly(app):
    deadline = time.monotonic() + 30
    while app.assembling:
        app.root.update()
        time.sleep(0.01)
        assert time.monotonic() < deadline, "assembling did not finish"
    app.root.update()


def assemble(app):
    app.run("assemble")
    wait_for_assembly(app)
    return app.messages.messages.get("1.0", "end-1c").splitlines()


def open_source(app, tmp_path, source, name="prog.s"):
    path = tmp_path / name
    path.write_text(source, encoding="utf-8", newline="\n")
    return path, app.open_path(path)


def assembled_files(app):
    start = "Assemble: assembling "
    lines = app.messages.messages.get("1.0", "end-1c").splitlines()
    return [line[len(start):] for line in lines if line.startswith(start)]


def click_message(app, index):
    messages = app.messages.messages
    messages.see(index)                 # ARES Messages may be too short for every line
    app.root.update()
    x, y, width, height = messages.bbox(index)
    messages.event_generate("<ButtonRelease-1>", x=x + 1, y=y + height // 2)


def test_assembling_a_correct_program(app, tmp_path):
    path, tab = open_source(app, tmp_path, (PROGRAMS / "hello.s").read_text())
    app.messages.show_run_io()
    assert assemble(app) == [f"Assemble: assembling {path}",
                             "Assemble: operation completed successfully."]
    assert app.messages.tab("current", "text") == "ARES Messages"
    assert app.program is not None and app.program.entry == app.program.label_address("_start")
    assert tab.error_lines() == set()


def test_capital_letter_errors_are_listed_marked_and_clickable(app, tmp_path):
    path, tab = open_source(app, tmp_path, CAPITALS)
    lines = assemble(app)
    assert lines == [
        f"Assemble: assembling {path}",
        f"Error in {path} line 3: write instructions and registers in capitals: MOV R0, #1",
        f"Error in {path} line 5: write instructions and registers in capitals: ADD R1, R1, #2",
        "Assemble: operation completed with errors."]
    assert app.program is None
    assert tab.error_lines() == {3, 5}
    tab.gutter.redraw()
    assert len([i for i in tab.gutter.find_all() if tab.gutter.type(i) == "oval"]) == 2

    app.views.select(app.execute)
    click_message(app, "3.10")
    assert app.views.select() == str(app.editor)
    assert tab.text.get("sel.first", "sel.last") == "    add r1, r1, #2"


def test_clicking_a_line_without_a_target_does_nothing(app, tmp_path):
    path, tab = open_source(app, tmp_path, CAPITALS)
    assemble(app)
    tab.text.mark_set("insert", "1.0")
    click_message(app, "1.3")                           # "Assemble: assembling ..."
    assert tab.text.index("insert") == "1.0" and not tab.text.tag_ranges("sel")


def test_an_error_finds_its_file_after_the_file_was_closed_and_opened_again(app, tmp_path):
    path, tab = open_source(app, tmp_path, CAPITALS)
    assemble(app)
    app.cmd_close()
    again = app.open_path(path)
    click_message(app, "3.10")                          # "Error in <path> line 5: ..."
    assert again.text.get("sel.first", "sel.last") == "    add r1, r1, #2"


def test_an_error_of_an_untitled_file_finds_its_tab(app):
    app.cmd_new()
    tab = app.editor.current
    tab.text.insert("1.0", CAPITALS)
    assemble(app)
    app.cmd_new()
    click_message(app, "3.10")                          # "Error in untitled1.s line 5: ..."
    assert app.editor.current is tab
    assert tab.text.get("sel.first", "sel.last") == "    add r1, r1, #2"
    app.editor.remove(tab)                              # closed without saving
    other = app.editor.current
    click_message(app, "3.10")                          # nothing to show
    assert app.editor.tabs == [other] and not other.text.tag_ranges("sel")


@pytest.mark.parametrize("command", ["save", "save_as"])
def test_an_error_finds_its_tab_after_the_file_is_saved_under_a_new_name(app, tmp_path,
                                                                         monkeypatch, command):
    """Save names an untitled file; Save As renames a saved one."""
    if command == "save":
        app.cmd_new()
        tab = app.editor.current
        tab.text.insert("1.0", CAPITALS)
    else:
        _, tab = open_source(app, tmp_path, CAPITALS)
    assemble(app)
    monkeypatch.setattr(app_module.filedialog, "asksaveasfilename",
                        lambda **options: str(tmp_path / "renamed.s"))
    app.run(command)
    assert tab.name == "renamed.s"
    click_message(app, "3.10")                          # "Error in <old name> line 5: ..."
    assert tab.text.get("sel.first", "sel.last") == "    add r1, r1, #2"


def test_assembler_errors_are_listed_with_their_line(app, tmp_path):
    path, tab = open_source(app, tmp_path, ".global _start\n_start:\n    NOP\n    MOVX R0, #1\n")
    lines = assemble(app)
    assert lines[1].startswith(f"Error in {path} line 4: bad instruction")
    assert lines[-1] == "Assemble: operation completed with errors."
    assert tab.error_lines() == {4}


def test_next_assemble_clears_the_markers(app, tmp_path):
    path, tab = open_source(app, tmp_path, CAPITALS)
    assemble(app)
    assert tab.error_lines() == {3, 5}
    app.cmd_capitalize()
    lines = assemble(app)
    assert lines[-1] == "Assemble: operation completed successfully."
    assert tab.error_lines() == set()


def test_missing_start_is_a_warning(app, tmp_path):
    path, tab = open_source(app, tmp_path, "    MOV R0, #1\n    SVC #10\n")
    assert assemble(app) == [
        f"Assemble: assembling {path}",
        f"Warning in {path}: No global _start label: execution starts at address 0x00000000. "
        "Add .global _start and _start: before your first instruction.",
        "Assemble: operation completed successfully."]
    assert tab.error_lines() == set()


def test_capital_letters_can_be_switched_off(app, tmp_path):
    open_source(app, tmp_path, CAPITALS)
    app.setting_vars["require_capitals"].set(False)
    app._setting_toggled("require_capitals")
    assert assemble(app)[-1] == "Assemble: operation completed successfully."


def test_a_new_file_is_assembled_under_its_tab_name(app):
    app.cmd_new()
    tab = app.editor.current
    tab.text.insert("1.0", CAPITALS)
    lines = assemble(app)
    assert lines[0] == "Assemble: assembling untitled1.s"
    assert lines[1].startswith("Error in untitled1.s line 3: ")
    assert tab.error_lines() == {3, 5}


def test_the_unsaved_text_is_assembled_and_the_file_is_not_written(app, tmp_path):
    path, tab = open_source(app, tmp_path, CAPITALS)
    app.cmd_capitalize()
    assert assemble(app)[-1] == "Assemble: operation completed successfully."
    assert path.read_text() == CAPITALS and tab.modified


def test_messages_accumulate_until_cleared(app, tmp_path):
    open_source(app, tmp_path, (PROGRAMS / "hello.s").read_text())
    assemble(app)
    assert len(assemble(app)) == 4


def test_assemble_is_unavailable_without_a_file_and_while_assembling(app, tmp_path):
    assert not app.is_enabled("assemble")
    open_source(app, tmp_path, (PROGRAMS / "hello.s").read_text())
    assert app.is_enabled("assemble")
    app.run("assemble")
    assert app.assembling and not app.is_enabled("assemble")
    wait_for_assembly(app)
    assert app.is_enabled("assemble")


def test_f3_assembles(app, tmp_path):
    path, tab = open_source(app, tmp_path, (PROGRAMS / "hello.s").read_text())
    assert press_key(tab.text, "<Key-F3>") == [SHORTCUT_TAG]
    wait_for_assembly(app)
    assert app.messages.messages.get("1.0", "end-1c").splitlines()[-1] == (
        "Assemble: operation completed successfully.")


def test_assemble_upon_opening(app, tmp_path):
    app.settings.assemble_on_open = True
    open_source(app, tmp_path, (PROGRAMS / "hello.s").read_text())
    wait_for_assembly(app)
    assert app.messages.messages.get("1.0", "end-1c").splitlines()[-1] == (
        "Assemble: operation completed successfully.")


def test_assemble_upon_opening_several_files_assembles_the_one_on_top(app, tmp_path,
                                                                      monkeypatch):
    app.settings.assemble_on_open = True
    first, second = tmp_path / "first.s", tmp_path / "second.s"
    first.write_text(HELLO)
    second.write_text(CAPITALS)
    monkeypatch.setattr(app_module.filedialog, "askopenfilenames",
                        lambda **options: (str(first), str(second)))
    app.run("open")
    wait_for_assembly(app)
    assert assembled_files(app) == [str(second)]
    assert app.editor.current.name == "second.s" and app.editor.current.error_lines() == {3, 5}


def test_files_given_at_start_assemble_the_one_on_top(make_app, tmp_path):
    Settings(assemble_on_open=True).save(tmp_path / "settings.json")
    first, second = tmp_path / "first.s", tmp_path / "second.s"
    first.write_text(HELLO)
    second.write_text(HELLO)
    app = make_app(files=[str(first), str(second)])
    wait_for_assembly(app)
    assert assembled_files(app) == [str(second)] and app.editor.current.name == "second.s"


def test_a_file_opened_while_assembling_is_assembled_next(app, tmp_path):
    app.settings.assemble_on_open = True
    first, _ = open_source(app, tmp_path, HELLO, "first.s")
    assert app.assembling
    second, tab = open_source(app, tmp_path, CAPITALS, "second.s")
    wait_for_assembly(app)
    assert assembled_files(app) == [str(first), str(second)]
    assert tab.error_lines() == {3, 5}


def test_missing_assembler_is_reported(app, tmp_path, monkeypatch):
    def missing(name):
        raise ToolchainMissingError(f"{name} not found")
    monkeypatch.setattr(assembler, "tool_path", missing)
    path, tab = open_source(app, tmp_path, (PROGRAMS / "hello.s").read_text())
    assert assemble(app)[1:] == ["Error: arm-none-eabi-as not found",
                                 "Assemble: operation completed with errors."]


def test_closing_the_tab_while_assembling(app, tmp_path):
    path, tab = open_source(app, tmp_path, CAPITALS)
    app.run("assemble")
    app.cmd_close()
    wait_for_assembly(app)
    assert app.messages.messages.get("1.0", "end-1c").splitlines()[-1] == (
        "Assemble: operation completed with errors.")


@pytest.mark.parametrize("source", [SLOW, HELLO], ids=["slow", "hello"])
def test_closing_the_window_while_assembling_removes_its_folder(app, tmp_path, monkeypatch,
                                                                source):
    started = threading.Event()
    popen = assembler.subprocess.Popen

    def start(*args, **options):
        process = popen(*args, **options)
        started.set()
        return process
    monkeypatch.setattr(assembler.subprocess, "Popen", start)
    open_source(app, tmp_path, source)
    app.run("assemble")
    if source is SLOW:
        assert started.wait(10)             # the assembler is at work, its files open
    thread = app._assembly[0]
    try:
        app.close()                         # HELLO: at once; the worker still writes its files
        assert not thread.is_alive() and not app.workdir.exists()
    finally:
        shutil.rmtree(app.workdir, ignore_errors=True)


# Settings > Editor Font... -------------------------------------------------------

def test_the_font_dialog_shows_the_family_the_editor_draws_with(app, monkeypatch):
    """On a system without the default family, the closest one stands in for it there too."""
    monkeypatch.setattr(dialogs, "installed_family", lambda family, installed: "Stand-in")
    app.run("editor_font")
    assert app.font_dialog.family.get() == "Stand-in"
    assert app.font_dialog.preview_font.cget("family") == "Stand-in"
    app.font_dialog.cancel()


def test_editor_font_dialog_changes_and_saves_the_font(app, tmp_path):
    app.cmd_new()
    app.run("editor_font")
    dialog = app.font_dialog
    family = next(f for f in dialog.families if f != app.settings.font_family)
    dialog.family.set(family)
    dialog.size.set("16")
    dialog.tab_size.set("8")
    dialog.tab_spaces.set(False)
    dialog.ok()
    assert not dialog.window.winfo_exists()
    s = Settings.load(tmp_path / "settings.json")
    assert (s.font_family, s.font_size, s.tab_size, s.tab_spaces) == (family, 16, 8, False)
    assert app.editor_font.cget("family") == family and app.editor_font.cget("size") == 16
    assert app.editor_bold.cget("size") == 16


def test_editor_font_dialog_refuses_bad_sizes_and_cancel_changes_nothing(app, tmp_path):
    app.run("editor_font")
    dialog = app.font_dialog
    dialog.size.set("200")
    dialog.ok()
    assert dialog.window.winfo_exists() and dialog.status.cget("text")
    dialog.size.set("abc")
    dialog.ok()
    assert dialog.window.winfo_exists()
    dialog.cancel()
    assert app.settings.font_size == DEFAULT_SIZE
    assert not (tmp_path / "settings.json").exists() or \
        Settings.load(tmp_path / "settings.json").font_size == DEFAULT_SIZE


def find_button(widget, label):
    for child in widget.winfo_children():
        if isinstance(child, ttk.Button) and child.cget("text") == label:
            return child
        found = find_button(child, label)
        if found is not None:
            return found
    return None


@pytest.mark.parametrize("focus, applied", [("Cancel", False), ("OK", True), (None, True)])
def test_return_presses_the_focused_button_else_ok(app, tmp_path, focus, applied):
    app.run("editor_font")
    dialog = app.font_dialog
    dialog.size.set("20")
    press_key(find_button(dialog.window, focus) if focus else dialog.family_box,
              "<Key-Return>")
    assert not dialog.window.winfo_exists()
    assert (app.settings.font_size, Settings.load(tmp_path / "settings.json").font_size) == (
        (20, 20) if applied else (DEFAULT_SIZE, DEFAULT_SIZE))


def test_restore_defaults_brings_the_font_back(app):
    app.settings.font_size = 20
    app.apply_settings()
    assert app.editor_font.cget("size") == 20
    app.run("restore_defaults")
    assert app.editor_font.cget("size") == DEFAULT_SIZE
