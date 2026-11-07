# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Edit tab: files, unsaved changes, editing aids, gutter, status line and colours."""

import errno
import os
import re
import stat
import statistics
import subprocess
import sys
import time

import pytest
from conftest import press_key, use_test_clipboard
from test_gui_app import TITLE

from ares import capitals
from ares.gui import app as app_module
from ares.gui import editor as editor_module
from ares.gui.editor import (CURRENT_LINE_BACKGROUND, ERROR_TAG, GUTTER_BACKGROUND,
                             LINE_NUMBER_COLOUR, decode, same_file)
from ares.gui.find import replace_all
from ares.settings import DEFAULT_SIZE, Settings


@pytest.fixture
def answers(monkeypatch):
    """Scripted answers for the window's questions; records what was asked."""
    asked = []
    replies = {"save_changes": [], "save_as": [], "open": []}

    def ask_save(*args, **options):
        asked.append(("save_changes", args[1]))
        return replies["save_changes"].pop(0)

    def ask_path(**options):
        asked.append(("save_as", options.get("initialfile")))
        return replies["save_as"].pop(0)

    def ask_open(**options):
        asked.append(("open", None))
        return replies["open"].pop(0)

    monkeypatch.setattr(app_module.messagebox, "askyesnocancel", ask_save)
    monkeypatch.setattr(app_module.filedialog, "asksaveasfilename", ask_path)
    monkeypatch.setattr(app_module.filedialog, "askopenfilenames", ask_open)
    monkeypatch.setattr(app_module.messagebox, "showerror",
                        lambda *args, **options: asked.append(("error", args[1])))
    replies["asked"] = asked
    return replies


def write(path, data):
    path.write_bytes(data)
    return path


def type_text(tab, text):
    tab.text.insert("insert", text)


# Files -----------------------------------------------------------------------

def test_open_shows_the_file_coloured_and_unmodified(app, tmp_path):
    path = write(tmp_path / "prog.s", b".global _start\r\n_start:\r\n    MOV R0, #1\r\n")
    tab = app.open_path(path)
    assert tab.get_text() == ".global _start\n_start:\n    MOV R0, #1\n"
    assert tab.newline == "\r\n" and not tab.modified
    assert app.root.title() == f"prog.s - {TITLE}"
    assert tab.text.tag_ranges("label") and tab.text.tag_ranges("register")
    assert not app.is_enabled("undo")       # loading is not an edit
    assert app.settings.last_folder == str(tmp_path.resolve())


def test_opening_an_open_file_shows_its_tab(app, tmp_path):
    path = write(tmp_path / "a.s", b"NOP\n")
    first = app.open_path(path)
    app.cmd_new()
    assert app.open_path(tmp_path / "." / "a.s") is first
    assert app.editor.current is first and len(app.editor.tabs) == 2


def test_open_failure_is_reported(app, tmp_path, answers):
    assert app.open_path(tmp_path / "missing.s") is None
    assert answers["asked"][0][0] == "error" and app.editor.tabs == []


def test_open_command_opens_every_chosen_file(app, tmp_path, answers):
    paths = [write(tmp_path / f"{n}.s", b"NOP\n") for n in "ab"]
    answers["open"].append(tuple(str(p) for p in paths))
    app.cmd_open()
    assert [tab.name for tab in app.editor.tabs] == ["a.s", "b.s"]


@pytest.mark.parametrize("data, encoding, bom, newline", [
    (b"MOV R0, #1\r\nNOP\r\n", "utf-8", False, "\r\n"),
    (b"\xef\xbb\xbf@ caf\xc3\xa9\nNOP", "utf-8", True, "\n"),
    (b"@ caf\xe9 \x93quoted\x94\n", "latin-1", False, "\n"),
])
def test_saving_keeps_line_endings_encoding_and_byte_order_mark(app, tmp_path, data, encoding,
                                                                 bom, newline):
    path = write(tmp_path / "f.s", data)
    tab = app.open_path(path)
    assert (tab.encoding, tab.bom, tab.newline) == (encoding, bom, newline)
    tab.text.insert("1.0", "X")
    assert tab.modified
    assert app.save(tab)
    expected = b"\xef\xbb\xbfX" + data[3:] if bom else b"X" + data
    assert path.read_bytes() == expected
    assert not tab.modified and app.root.title() == f"f.s - {TITLE}"


def test_a_character_latin1_cannot_hold_switches_the_file_to_utf8(app, tmp_path):
    path = write(tmp_path / "f.s", b"@ \xe9\n")
    tab = app.open_path(path)
    tab.text.insert("end-1c", "€")
    app.save(tab)
    assert path.read_bytes() == "@ é\n€".encode("utf-8")
    assert tab.encoding == "utf-8"


def test_decode():
    assert decode(b"abc") == ("abc", "utf-8", False)
    assert decode(b"\xef\xbb\xbfabc") == ("abc", "utf-8", True)
    assert decode(b"\xff") == ("\xff", "latin-1", False)
    assert decode(b"\xef\xbb\xbf\xff") == ("\xff", "latin-1", True)


@pytest.mark.parametrize("data", [
    b"\xef\xbb\xbf@ caf\xe9\nNOP\n",                # a byte-order mark, then Latin-1
    b"MOV R0, #1\rNOP\r",                           # CR line ends only
    b"@ a lone \r is no line end\r\nNOP\r\n",
    "MOV R0, #1\r\nNOP\r\n".encode("utf-16"),       # read as Latin-1
], ids=["bom latin-1", "cr", "lone cr", "utf-16"])
def test_saving_an_unchanged_file_keeps_every_byte(app, tmp_path, data):
    path = write(tmp_path / "f.s", data)
    tab = app.open_path(path)
    assert app.save(tab)
    assert path.read_bytes() == data


def test_mixed_line_ends_are_saved_as_the_more_common_one(app, tmp_path):
    for data, saved in ((b"A\r\nB\r\nC\n", b"A\r\nB\r\nC\r\n"), (b"A\nB\nC\r\n", b"A\nB\nC\n")):
        path = write(tmp_path / "f.s", data)
        tab = app.open_path(path)
        assert tab.get_text() == "A\nB\nC\n"
        assert app.save(tab) and path.read_bytes() == saved
        app.editor.remove(tab)


def test_a_save_that_fails_leaves_the_file_as_it_was(app, tmp_path, answers, monkeypatch):
    original = b"_start:\n    B _start\n" * 20
    path = write(tmp_path / "prog.s", original)
    tab = app.open_path(path)
    tab.text.insert("1.0", "@ new\n")

    def full_disk(*args):
        raise OSError(errno.ENOSPC, "No space left on device")
    for name in ("fsync", "replace"):           # while writing, or while taking the file's place
        with monkeypatch.context() as patch:
            patch.setattr(editor_module.os, name, full_disk)
            assert app.save(tab) is False
        assert answers["asked"][-1][0] == "error" and tab.modified
        assert path.read_bytes() == original
        assert list(tmp_path.glob("*.tmp")) == []          # nothing left over
    assert app.save(tab) and path.read_bytes() == b"@ new\n" + original
    assert list(tmp_path.glob("*.tmp")) == []


def test_save_keeps_the_permissions_and_refuses_a_read_only_file(app, tmp_path, answers):
    path = write(tmp_path / "f.s", b"NOP\n")
    os.chmod(path, 0o640)                       # Windows keeps only the read-only flag
    mode = stat.S_IMODE(os.stat(path).st_mode)
    tab = app.open_path(path)
    tab.text.insert("1.0", "X")
    assert app.save(tab)
    assert stat.S_IMODE(os.stat(path).st_mode) == mode
    tab.text.insert("1.0", "Y")
    os.chmod(path, stat.S_IREAD)
    try:
        if os.access(path, os.W_OK):
            pytest.skip("this user may write read-only files")
        assert app.save(tab) is False
        assert answers["asked"][-1][0] == "error"
        assert path.read_bytes() == b"XNOP\n" and list(tmp_path.glob("*.tmp")) == []
    finally:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)


def test_save_through_a_link_writes_the_file_it_leads_to(app, tmp_path):
    path = write(tmp_path / "f.s", b"NOP\n")
    link = tmp_path / "link.s"
    try:
        link.symlink_to(path)
    except OSError:
        pytest.skip("symbolic links cannot be made here")
    tab = app.open_path(link)
    tab.text.insert("1.0", "X")
    assert app.save(tab)
    assert link.is_symlink() and path.read_bytes() == b"XNOP\n"


def refuse_new_files(folder, refuse=True):
    """Make the system refuse new files in folder, or allow them again; its files stay writable."""
    if sys.platform != "win32":
        folder.chmod(0o555 if refuse else 0o755)
        return
    # A rule for Everyone on the folder alone, which its files do not inherit.
    args = ("/deny", "*S-1-1-0:(WD)") if refuse else ("/remove:d", "*S-1-1-0")
    subprocess.run(["icacls", str(folder), *args], check=True, capture_output=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)


@pytest.fixture
def no_new_files(tmp_path):
    """A folder holding f.s where the system refuses to make new files."""
    folder = tmp_path / "shared"
    folder.mkdir()
    write(folder / "f.s", b"NOP\n")
    refuse_new_files(folder)
    try:
        try:
            os.close(os.open(folder / "probe", os.O_WRONLY | os.O_CREAT | os.O_EXCL))
        except PermissionError:
            yield folder
        else:
            pytest.skip("this user may make files in any folder")
    finally:
        refuse_new_files(folder, False)


def test_save_writes_the_file_directly_where_no_new_file_can_be_made(app, no_new_files, answers,
                                                                     monkeypatch):
    path = no_new_files / "f.s"
    tab = app.open_path(path)
    tab.text.insert("1.0", "X")
    tried = []
    os_open = os.open

    def counted(name, flags, *args):    # on Windows, mkstemp would try new names for days
        tried.append(name)
        assert len(tried) < 10, "new names tried without end"
        return os_open(name, flags, *args)
    monkeypatch.setattr(os, "open", counted)
    assert app.save(tab) and path.read_bytes() == b"XNOP\n"
    app.cmd_new()
    answers["save_as"].append(str(no_new_files / "new.s"))
    assert app.save_as(app.editor.current) is False
    assert answers["asked"][-1] == ("error", f"Cannot save {no_new_files / 'new.s'}:\n"
                                             "Permission denied")
    assert sorted(os.listdir(no_new_files)) == ["f.s"]


def test_same_file_compares_files_not_spellings(tmp_path):
    path = write(tmp_path / "a.s", b"NOP\n")
    assert same_file(tmp_path / "sub" / ".." / "a.s", path)
    assert not same_file(write(tmp_path / "b.s", b"NOP\n"), path)
    assert same_file(tmp_path / "new.s", tmp_path / "." / "new.s")     # files not made yet
    assert not same_file(tmp_path / "new.s", path)


@pytest.mark.skipif(sys.platform != "win32", reason="short names and junctions are Windows'")
def test_the_same_file_under_another_spelling_shows_its_tab(app, tmp_path, answers):
    import _winapi
    import ctypes
    path = write(tmp_path / "a long file name.s", b"NOP\n")
    first = app.open_path(path)
    assert app.open_path(str(path).upper()) is first
    buffer = ctypes.create_unicode_buffer(1024)
    if ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, 1024) \
            and buffer.value != str(path):          # volumes may have no short names
        assert app.open_path(buffer.value) is first
    (tmp_path / "work").mkdir()
    lab = write(tmp_path / "work" / "lab.s", b"NOP\n")
    _winapi.CreateJunction(str(tmp_path / "work"), str(tmp_path / "link"))
    try:
        other = app.open_path(lab)
        other.text.insert("1.0", "@ unsaved\n")
        assert app.open_path(tmp_path / "link" / "lab.s") is other
        app.cmd_new()
        answers["save_as"].append(str(tmp_path / "link" / "lab.s"))
        app.cmd_save_as()                       # onto the file open in the other tab
        assert answers["asked"][-1][0] == "error" and lab.read_bytes() == b"NOP\n"
    finally:
        os.rmdir(tmp_path / "link")             # the junction, not the folder it leads to


def test_new_and_open_bring_the_edit_tab_to_the_front(app, tmp_path, hidden_windows):
    path = write(tmp_path / "a.s", b"NOP\n")
    for action in (app.cmd_new, lambda: app.open_path(path), lambda: app.open_path(path)):
        app.views.select(app.execute)
        hidden_windows.focus = None
        action()
        assert app.views.select() == str(app.editor)
        assert hidden_windows.focus is app.editor.current.text     # typing goes there


def test_undo_back_to_the_saved_text_removes_the_unsaved_mark(app, tmp_path):
    tab = app.open_path(write(tmp_path / "f.s", b"NOP\n"))
    type_text(tab, "X")
    assert tab.title() == "f.s*" and app.editor.notebook.tab(tab, "text") == "f.s*"
    app.cmd_undo()
    assert not tab.modified
    assert app.editor.notebook.tab(tab, "text") == "f.s"
    assert app.root.title() == f"f.s - {TITLE}"
    app.cmd_redo()
    assert app.editor.notebook.tab(tab, "text") == "f.s*"
    assert app.root.title() == f"f.s* - {TITLE}"


def test_save_of_a_new_file_asks_for_a_name(app, tmp_path, answers):
    app.cmd_new()
    tab = app.editor.current
    type_text(tab, "NOP")
    answers["save_as"].append(str(tmp_path / "first.s"))
    app.cmd_save()
    assert answers["asked"] == [("save_as", "untitled1.s")]
    assert (tmp_path / "first.s").read_text() == "NOP"
    assert tab.name == "first.s" and app.root.title() == f"first.s - {TITLE}"
    app.cmd_save()                          # now it has a name: no question
    assert len(answers["asked"]) == 1


def test_save_as_cancelled_changes_nothing(app, answers):
    app.cmd_new()
    answers["save_as"].append("")
    app.cmd_save_as()
    assert app.editor.current.path is None


def test_save_as_onto_a_file_open_in_another_tab_is_refused(app, tmp_path, answers):
    other = app.open_path(write(tmp_path / "other.s", b"NOP\n"))
    app.cmd_new()
    answers["save_as"].append(str(tmp_path / "other.s"))
    app.cmd_save_as()
    assert answers["asked"][-1][0] == "error"
    assert app.editor.current.path is None and other.get_text() == "NOP\n"


def test_failed_save_keeps_the_unsaved_mark(app, tmp_path, answers):
    tab = app.open_path(write(tmp_path / "f.s", b"NOP\n"))
    type_text(tab, "X")
    (tmp_path / "f.s").unlink()
    (tmp_path / "f.s").mkdir()              # writing a file there fails
    assert app.save(tab) is False
    assert answers["asked"][-1][0] == "error" and tab.modified


def test_save_all_saves_only_changed_files(app, tmp_path, answers):
    a = app.open_path(write(tmp_path / "a.s", b"A\n"))
    b = app.open_path(write(tmp_path / "b.s", b"B\n"))
    type_text(a, "1")
    app.cmd_save_all()
    assert (tmp_path / "a.s").read_bytes() == b"1A\n"
    assert not a.modified and not b.modified and answers["asked"] == []


# Unsaved changes -------------------------------------------------------------

def test_close_asks_about_unsaved_changes(app, tmp_path, answers):
    path = write(tmp_path / "f.s", b"NOP\n")
    tab = app.open_path(path)
    type_text(tab, "X")
    answers["save_changes"] += [None, False]
    app.cmd_close()                         # Cancel: stays open
    assert app.editor.tabs == [tab]
    app.cmd_close()                         # No: closed, file unchanged
    assert app.editor.tabs == [] and path.read_bytes() == b"NOP\n"
    assert answers["asked"] == [("save_changes", "Save changes to f.s?")] * 2


def test_close_with_yes_saves_first(app, tmp_path, answers):
    path = write(tmp_path / "f.s", b"NOP\n")
    tab = app.open_path(path)
    type_text(tab, "X")
    answers["save_changes"].append(True)
    app.cmd_close()
    assert path.read_bytes() == b"XNOP\n" and app.editor.tabs == []


def test_unchanged_files_close_without_a_question(app, tmp_path, answers):
    app.open_path(write(tmp_path / "f.s", b"NOP\n"))
    app.cmd_new()
    assert app.cmd_close_all() is True
    assert answers["asked"] == [] and app.root.title() == TITLE


def test_close_all_stops_at_cancel(app, tmp_path, answers):
    first = app.open_path(write(tmp_path / "a.s", b"A\n"))
    second = app.open_path(write(tmp_path / "b.s", b"B\n"))
    type_text(first, "1")
    type_text(second, "2")
    answers["save_changes"] += [False, None]
    assert app.cmd_close_all() is False
    assert app.editor.tabs == [second]


def test_exit_asks_and_cancel_keeps_the_window(app, tmp_path, answers):
    tab = app.open_path(write(tmp_path / "f.s", b"NOP\n"))
    type_text(tab, "X")
    answers["save_changes"].append(None)
    app.cmd_exit()
    assert app.root.winfo_exists() and app.editor.tabs == [tab]


def test_new_files_are_numbered(app):
    for _ in range(3):
        app.cmd_new()
    assert [tab.name for tab in app.editor.tabs] == ["untitled1.s", "untitled2.s",
                                                     "untitled3.s"]


# Editing aids ------------------------------------------------------------------

def press(app, tab, keysym):
    """Press a key in the editor: only the editor's own binding runs, and stops the event."""
    assert press_key(tab.text, f"<Key-{keysym}>") == [str(tab.text)]


def test_tab_inserts_spaces_to_the_next_stop(app):
    app.cmd_new()
    tab = app.editor.current
    type_text(tab, "AB")
    press(app, tab, "Tab")
    assert tab.get_text() == "AB  "
    press(app, tab, "Tab")
    assert tab.get_text() == "AB      "
    app.settings.tab_spaces = False
    press(app, tab, "Tab")
    assert tab.get_text() == "AB      \t"


def test_tab_width_counts_tab_characters(app):
    app.cmd_new()
    tab = app.editor.current
    app.settings.tab_size = 8
    type_text(tab, "\tX")
    press(app, tab, "Tab")
    assert tab.get_text() == "\tX" + " " * 7


def test_enter_keeps_the_indentation(app):
    app.cmd_new()
    tab = app.editor.current
    type_text(tab, "    MOV R0, #1")
    press(app, tab, "Return")
    type_text(tab, "NOP")
    assert tab.get_text() == "    MOV R0, #1\n    NOP"
    tab.text.mark_set("insert", "2.2")      # inside the indentation
    press(app, tab, "Return")
    assert tab.get_text() == "    MOV R0, #1\n  \n    NOP"


def test_enter_is_one_undo_step_after_typing(app):
    app.cmd_new()
    tab = app.editor.current
    type_text(tab, "  A")
    tab.text.edit_separator()
    press(app, tab, "Return")
    app.cmd_undo()
    assert tab.get_text() == "  A"


def type_keys(tab, chars):
    """Type as the keyboard does: Tk's <KeyPress> binding runs tk::TextInsert for each key."""
    for char in chars:
        tab.text.tk.call("tk::TextInsert", tab.text._w, char)


def test_typing_after_an_undo_or_redo_is_a_step_of_its_own(app):
    app.cmd_new()
    tab = app.editor.current
    type_keys(tab, "    MOV R0, #1")
    press(app, tab, "Return")
    type_keys(tab, "MOV R1, #2")
    app.cmd_undo()
    assert tab.get_text() == "    MOV R0, #1\n    "
    type_keys(tab, "SVC #10")
    app.cmd_undo()                              # only the typing after the undo
    assert tab.get_text() == "    MOV R0, #1\n    "
    app.cmd_redo()
    type_keys(tab, "!")
    app.cmd_undo()
    assert tab.get_text() == "    MOV R0, #1\n    SVC #10"


def test_tab_and_enter_replace_a_selection_before_they_measure(app):
    app.cmd_new()
    tab = app.editor.current
    type_text(tab, "    MOV R0, R1")
    tab.text.tag_add("sel", "1.4", "1.7")       # MOV, selected from left to right
    tab.text.mark_set("insert", "1.7")
    press(app, tab, "Tab")
    assert tab.get_text() == "         R0, R1"
    assert app.editor.position.cget("text") == "Line: 1  Column: 9"
    app.cmd_undo()                              # one step
    assert tab.get_text() == "    MOV R0, R1"
    tab.text.tag_add("sel", "1.0", "1.end")
    tab.text.mark_set("insert", "1.end")
    press(app, tab, "Return")
    assert tab.get_text() == "\n"               # nothing left of the cursor to indent like
    app.cmd_undo()
    assert tab.get_text() == "    MOV R0, R1"


def press_tab_with(tab, modifiers):
    """Tab with Shift or Control held, as Tk runs it; returns the tags whose bindings ran.

    The editor's own <Tab> binding is the only Tab binding of its text, so
    for Tk it is the best match there and runs first, with the modifiers in
    the event's state; unless it ends the event, the later tags' bindings for
    the key with these modifiers run.
    """
    text = tab.text
    state = {"Shift": 1, "Control": 4, "Control-Shift": 5}[modifiers]
    fields = {"%W": str(text), "%s": str(state), "%T": "2", "%K": "Tab", "%A": "{}"}
    script = re.sub(r"%.", lambda m: fields.get(m.group(), "0"),
                    text.tk.call("bind", str(text), "<Key-Tab>"))
    stopped = text.tk.eval(f"set ::stopped 1\nforeach _ {{1}} {{\n{script}\nset ::stopped 0\n}}\n"
                           "set ::stopped")
    return [str(text)] + ([] if stopped == "1" else press_key(text, f"<{modifiers}-Key-Tab>"))


def test_tab_with_shift_or_control_is_left_to_tk(app):
    app.cmd_new()
    tab = app.editor.current
    for modifiers in ("Shift", "Control", "Control-Shift"):
        tab.text.delete("1.0", "end")
        tab.text.insert("1.0", "MOV R0, #1")
        tab.text.mark_set("insert", "1.0")
        assert press_tab_with(tab, modifiers) == [str(tab.text), "Text"]
        assert tab.get_text() == "MOV R0, #1"
    press(app, tab, "Tab")
    assert tab.get_text() == "    MOV R0, #1"


def test_status_line_shows_line_and_column(app, answers):
    app.cmd_new()
    tab = app.editor.current
    type_text(tab, "MOV R0, #1\nNOP")
    assert app.editor.position.cget("text") == "Line: 2  Column: 4"
    tab.text.mark_set("insert", "1.0")
    assert app.editor.position.cget("text") == "Line: 1  Column: 1"
    answers["save_changes"].append(False)
    app.cmd_close_all()
    assert app.editor.position.cget("text") == ""


def test_the_position_is_a_plain_label_beside_show_line_numbers(app):
    """No panel: the line and column stand at the left of the status line, and the check box
    follows them."""
    app.cmd_new()
    position = app.editor.position
    assert position.master is app.editor.status
    slaves = app.editor.status.pack_slaves()
    assert slaves[0] is position and slaves[1].cget("text") == "Show Line Numbers"
    assert str(position.cget("width")) == ""


def test_current_line_has_its_background(app):
    app.cmd_new()
    tab = app.editor.current
    type_text(tab, "A\nB\nC")
    tab.text.mark_set("insert", "2.0")
    assert tab.text.tag_cget("current_line", "background") == CURRENT_LINE_BACKGROUND
    assert [str(i) for i in tab.text.tag_ranges("current_line")] == ["2.0", "3.0"]


def test_capitalize_instructions_is_one_undo_step(app):
    app.cmd_new()
    tab = app.editor.current
    original = "_start:\n    mov r0, #1   @ keep me\n    NOP\n    .GLOBAL _start\n"
    type_text(tab, original)
    tab.text.mark_set("insert", "3.2")
    app.cmd_capitalize()
    assert tab.get_text() == "_start:\n    MOV R0, #1   @ keep me\n    NOP\n    .global _start\n"
    assert tab.text.index("insert") == "3.2"
    assert tab.capitalize() == 0            # nothing left to change
    app.cmd_undo()
    assert tab.get_text() == original


@pytest.mark.serial
def test_capitalize_is_one_edit_that_keeps_markers_and_undoes_quickly(app):
    original = "\n".join(f"    mov r{n % 13}, #{n}   @ line {n}" if n % 2 else
                         f"loop{n}: add r1, r1, r2" for n in range(1, 2001))
    app.cmd_new()
    tab = app.editor.current
    tab.text.insert("1.0", original)
    tab.set_error_lines({1, 2, 1000, 2000})
    tab.text.mark_set("insert", "1000.6")
    changes = []
    tab.text.add_change_listener(lambda *change: changes.append(change))
    assert tab.capitalize() == 2000
    assert changes == [(1, 2000, 2000)]
    assert tab.get_text() == capitals.capitalize(original)
    assert tab.error_lines() == {1, 2, 1000, 2000} and tab.text.index("insert") == "1000.6"
    assert [str(index) for index in tab.text.tag_ranges("current_line")] == ["1000.0", "1001.0"]
    for command in (app.cmd_undo, app.cmd_redo):
        changes.clear()
        start = time.perf_counter()
        command()
        app.root.update_idletasks()
        assert time.perf_counter() - start < 1 and len(changes) == 2    # one delete, one insert
    assert tab.get_text() == capitals.capitalize(original)


def test_capitalize_keeps_the_markers_of_a_line_split_in_two(app):
    app.cmd_new()
    tab = app.editor.current
    tab.text.insert("1.0", "    mov r0, #1\n    nop")
    tab.text.edit_reset()
    tab.set_error_lines({1})
    tab.text.mark_set("insert", "1.11")
    press(app, tab, "Return")
    assert tab.error_lines() == {1, 2}
    assert tab.capitalize() == 2
    assert tab.get_text() == "    MOV R0,\n     #1\n    NOP"
    assert tab.error_lines() == {1, 2}


def test_replace_all_keeps_a_marker_that_joining_lines_left_on_part_of_a_line(app):
    app.cmd_new()
    tab = app.editor.current
    tab.text.insert("1.0", "    mov r0, #1\n    mov r1, #2\n    nop\n    mov r2, #3")
    tab.set_error_lines({2})
    tab.text.mark_set("insert", "2.end")
    assert press_key(tab.text, "<Key-Delete>") == ["Text"]        # joins lines 2 and 3
    assert tab.get_text().split("\n")[1] == "    mov r1, #2    nop"
    assert tab.error_lines() == {2}
    assert replace_all(tab.text, "mov", "MOV", match_case=True) == 3
    assert tab.error_lines() == {2}


def test_undo_of_a_paste_over_lines_marks_none_of_the_lines_it_brings_back(app):
    use_test_clipboard(app.root)
    app.cmd_new()
    tab = app.editor.current
    original = "    MOV R0, #1\n    MOV R1, #2\n    MOV R2, #3\n    SVC #0"
    tab.text.insert("1.0", original)
    tab.text.edit_reset()
    tab.text.tag_add("sel", "2.0", "4.0")
    tab.text.mark_set("insert", "2.0")
    app.root.clipboard_append("    bad r1\n    ADD R1, R1, #1\n")
    app.cmd_paste()
    tab.set_error_lines({2})                    # the pasted "bad r1"
    app.cmd_undo()
    assert tab.get_text() == original and tab.error_lines() == set()


@pytest.mark.parametrize("edit", [
    lambda tab: tab.capitalize(),
    lambda tab: replace_all(tab.text, "    mov", "    MOV", match_case=True),
], ids=["capitalize", "replace all"])
def test_undo_and_redo_of_an_edit_that_keeps_the_line_count_keep_the_markers(app, edit):
    original = (".global _start\n_start:\n    mov r0, #1\n    MOV R1, #2\n    mov r2, #3\n"
                "    svc #0\n")
    app.cmd_new()
    tab = app.editor.current
    tab.text.insert("1.0", original)
    tab.text.edit_reset()
    tab.set_error_lines({1, 3, 5, 6})       # in and around the changed lines (3-5 or 3-6)
    edit(tab)
    for command in (app.cmd_undo, app.cmd_redo, app.cmd_undo):
        command()
        assert tab.error_lines() == {1, 3, 5, 6}
    assert tab.get_text() == original


def test_select_line_and_go_to_line(app):
    app.cmd_new()
    tab = app.editor.current
    type_text(tab, "A\nBBB\nC")
    app.views.select(app.execute)
    app.go_to_line((tab, 2))
    assert app.views.select() == str(app.editor)
    assert tab.text.get("sel.first", "sel.last") == "BBB"
    assert tab.text.index("insert") == "2.0"


def test_selection_stays_visible_when_the_find_window_has_the_focus(app):
    app.cmd_new()
    text = app.editor.current.text
    assert text.cget("inactiveselectbackground") == text.cget("selectbackground") != ""
    pane = app.messages.messages
    assert pane.cget("inactiveselectbackground") == pane.cget("selectbackground")


def test_find_opens_with_the_selected_text(app, monkeypatch):
    shown = []
    monkeypatch.setattr(app.find_dialog, "show", lambda initial="": shown.append(initial))
    app.cmd_new()
    tab = app.editor.current
    type_text(tab, "MOV R0, #1\nNOP")
    tab.text.tag_add("sel", "1.0", "1.3")
    app.cmd_find()
    tab.text.tag_add("sel", "1.0", "2.1")
    app.cmd_find()                          # several lines: not used
    assert shown == ["MOV", ""]


# Gutter ----------------------------------------------------------------------------

def gutter_numbers(tab):
    tab.gutter.redraw()
    canvas = tab.gutter
    return [canvas.itemcget(item, "text") for item in canvas.find_all()
            if canvas.type(item) == "text"]


def test_gutter_shows_the_visible_line_numbers(app):
    app.cmd_new()
    tab = app.editor.current
    type_text(tab, "\n".join(f"NOP @ {n}" for n in range(1, 301)))
    tab.text.see("1.0")
    app.root.update()
    numbers = gutter_numbers(tab)
    assert numbers[:3] == ["1", "2", "3"] and 5 < len(numbers) < 300
    tab.text.yview("100.0")
    app.root.update()
    assert gutter_numbers(tab)[0] == "100"
    canvas = tab.gutter
    assert canvas.cget("background") == GUTTER_BACKGROUND
    text_items = [i for i in canvas.find_all() if canvas.type(i) == "text"]
    assert canvas.itemcget(text_items[0], "fill") == LINE_NUMBER_COLOUR


def test_gutter_lines_up_with_the_text(app):
    app.cmd_new()
    tab = app.editor.current
    type_text(tab, "A\nB\nC")
    app.root.update()
    tab.gutter.redraw()
    canvas = tab.gutter
    items = [i for i in canvas.find_all() if canvas.type(i) == "text"]
    for line, item in enumerate(items, 1):
        _, y, _, height, _ = tab.text.dlineinfo(f"{line}.0")
        top, bottom = canvas.bbox(item)[1], canvas.bbox(item)[3]
        assert abs((top + bottom) / 2 - (y + height / 2)) <= 2


def test_show_line_numbers_hides_the_gutter_and_is_saved(app, tmp_path):
    app.cmd_new()
    tab = app.editor.current
    app.editor.line_numbers.set(False)
    app.editor._toggle_line_numbers()
    assert tab.gutter.grid_info() == {}         # taken out of the layout
    assert Settings.load(tmp_path / "settings.json").show_line_numbers is False
    app.cmd_new()
    assert app.editor.current.gutter.grid_info() == {}
    app.editor.line_numbers.set(True)
    app.editor._toggle_line_numbers()
    assert int(tab.gutter.grid_info()["column"]) == 0


def test_error_markers_move_with_their_lines(app):
    app.cmd_new()
    tab = app.editor.current
    type_text(tab, "A\nB\nC\nD")
    tab.set_error_lines({2, 4})
    tab.text.insert("1.0", "new\n")
    assert tab.error_lines() == {3, 5}
    tab.text.delete("3.0", "4.0")           # the first marked line goes
    assert tab.error_lines() == {4}
    tab.text.insert("4.1", " typed")        # editing a marked line keeps its marker
    tab.text.insert("4.0", "@ ")
    assert tab.error_lines() == {4}
    assert tab.text.get("4.0", "4.end") == "@ D typed"
    app.root.update()
    tab.gutter.redraw()
    canvas = tab.gutter
    ovals = [i for i in canvas.find_all() if canvas.type(i) == "oval"]
    assert len(ovals) == 1


MARKED = ".global _start\n_start:\n    mov r0, #1\nmov r1, #2\n    add r2, r0, r1\n    svc #0"


@pytest.mark.parametrize("edit, marked", [
    (lambda tab: tab.text.mark_set("insert", "3.end"), {3, 4, 5, 6}),
    # Enter at the end of a marked line, indented or not, and of the last line
    (lambda tab: (tab.text.mark_set("insert", "3.end"), press_key(tab.text, "<Key-Return>")),
     {3, 5, 6, 7}),
    (lambda tab: (tab.text.mark_set("insert", "4.end"), press_key(tab.text, "<Key-Return>")),
     {3, 4, 6, 7}),
    (lambda tab: (tab.text.mark_set("insert", "6.end"), press_key(tab.text, "<Key-Return>"),
                  type_keys(tab, "NOP")), {3, 4, 5, 6}),
    # Lines pasted at the end of a marked line, and at the start of one after another
    (lambda tab: (tab.text.mark_set("insert", "3.end"), tab.text.event_generate("<<Paste>>")),
     {3, 6, 7, 8}),
    (lambda tab: (tab.text.mark_set("insert", "4.0"), tab.text.event_generate("<<Paste>>")),
     {3, 6, 7, 8}),
    # Typing in marked lines, and undoing an Enter at the end of one
    (lambda tab: (tab.text.mark_set("insert", "3.6"), type_keys(tab, "X"),
                  tab.text.mark_set("insert", "4.0"), type_keys(tab, "Y")), {3, 4, 5, 6}),
    (lambda tab: (tab.text.mark_set("insert", "3.end"), press_key(tab.text, "<Key-Return>"),
                  tab.undo()), {3, 4, 5, 6}),
], ids=["no edit", "enter after indented", "enter after unindented", "enter after last",
        "paste at end", "paste at start", "typing", "enter undone"])
def test_error_markers_stay_on_their_lines(app, edit, marked):
    use_test_clipboard(app.root)
    app.root.clipboard_append("    NOP\n    NOP\n")
    app.cmd_new()
    tab = app.editor.current
    tab.text.insert("1.0", MARKED)
    tab.text.edit_reset()                       # as after opening the file
    tab.set_error_lines({3, 4, 5, 6})
    edit(tab)
    assert tab.error_lines() == marked
    # Each marked line keeps the marker on all of it, its newline too.
    assert all(ERROR_TAG in tab.text.tag_names(f"{line}.end") for line in marked)
    app.root.update()
    tab.gutter.redraw()
    canvas = tab.gutter
    assert len([i for i in canvas.find_all() if canvas.type(i) == "oval"]) == len(marked)


def test_error_markers_show_without_line_numbers(app):
    app.cmd_new()
    tab = app.editor.current
    type_text(tab, "A\nB\nC")
    app.root.update()
    width = int(tab.gutter.cget("width"))
    app.editor.line_numbers.set(False)
    app.editor._toggle_line_numbers()
    assert tab.gutter.grid_info() == {}         # nothing to show
    tab.set_error_lines({2})
    app.root.update()
    canvas = tab.gutter
    assert int(canvas.grid_info()["column"]) == 0 and int(canvas.cget("width")) < width
    canvas.redraw()
    assert [canvas.type(item) for item in canvas.find_all()] == ["oval"]
    tab.text.delete("2.0", "3.0")               # the marked line goes, and the column with it
    app.root.update()
    assert tab.gutter.grid_info() == {}


@pytest.mark.serial
def test_the_gutter_looks_up_the_markers_of_the_lines_in_view_only(app, monkeypatch):
    app.cmd_new()
    tab = app.editor.current
    tab.text.insert("1.0", "\n".join(f"    mov r1, #{n}" for n in range(1, 2001)))
    tab.set_error_lines(range(1, 2001, 2))
    tab.text.yview("1000.0")
    app.root.update()
    looked_up = []
    marked_lines = editor_module.marked_lines
    monkeypatch.setattr(editor_module, "marked_lines",
                        lambda text, first, last: looked_up.append((first, last))
                        or marked_lines(text, first, last))
    tab.text.mark_set("insert", "1000.10")
    times = []
    for _ in range(20):
        start = time.perf_counter()
        tab.text.insert("insert", "X")
        app.root.update_idletasks()             # the gutter is drawn again
        times.append(time.perf_counter() - start)
    first, last = looked_up[-1]
    assert first == 1000 and last < 1100
    assert statistics.median(times) < 0.005


def run_wheel_binding(widget, tag, delta):
    """Run a tag's <MouseWheel> binding for widget as Tk would, with the wheel turned by delta."""
    fields = {"%W": str(widget), "%D": str(delta)}
    widget.tk.eval(re.sub(r"%.", lambda m: fields.get(m.group(), "0"),
                          widget.tk.call("bind", tag, "<MouseWheel>")))


def test_the_wheel_over_the_line_numbers_scrolls_as_over_the_text(app):
    app.cmd_new()
    tab = app.editor.current
    tab.text.insert("1.0", "\n".join(f"NOP @ {n}" for n in range(1, 301)))
    app.root.update()
    for delta in (120, -120, 40, -40, 1, -1):
        views = []
        for widget, tag in ((tab.gutter, str(tab.gutter)), (tab.text, "Text")):
            tab.text.yview("100.0")
            start = tab.text.yview()[0]
            run_wheel_binding(widget, tag, delta)
            views.append(tab.text.yview()[0])
        assert views[0] == views[1], delta
        if abs(delta) >= 40:                    # up as well as down
            assert (views[0] < start) == (delta > 0), delta


# Colours and speed ---------------------------------------------------------------

def test_editor_colours_and_font(app):
    app.cmd_new()
    text = app.editor.current.text
    assert text.cget("background") == "#FFFFFF" and text.cget("foreground") == "#000000"
    expected = {"register": "#354BF5", "number": "#63A645", "label": "#2F5D16",
                "directive": "#3F7576", "comment": "#A1896A", "string": "#942F29"}
    for tag, colour in expected.items():
        assert text.tag_cget(tag, "foreground").upper() == colour
    assert app.editor_bold.actual("weight") == "bold"
    assert app.editor_font.actual("size") == DEFAULT_SIZE
    tags = text.tag_names()
    assert tags.index("sel") > max(tags.index(t) for t in expected)


@pytest.mark.serial
def test_typing_in_a_long_file_stays_fast(app):
    lines = []
    for n in range(500):
        lines += [f"loop{n}:", f"    LDR R{n % 13}, =0x{n:08X}   @ load {n}",
                  f"    ADDNE R1, R1, R2, LSL #2", f"    .word {n}, {n + 1}, 0x{n:x}"]
    app.cmd_new()
    tab = app.editor.current
    tab.text.insert("1.0", "\n".join(lines))
    app.root.update()
    times = []
    for i in range(20):
        start = time.perf_counter()
        tab.text.insert("1000.10", "X")
        times.append(time.perf_counter() - start)
    assert statistics.median(times) < 0.005
