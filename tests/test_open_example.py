# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""File > Open Example: where the examples are, the list of the submenu, and the unsaved copy
a choice opens."""

import sys

import pytest
from conftest import ROOT, pump
from test_gui_assemble import assemble, wait_for_assembly
from test_gui_clicks import click_item, click_title, closed
from test_gui_editing import PROGRAM, ROW, double_click, type_into
from test_gui_editor import answers  # noqa: F401  (a fixture)
from test_gui_run import COUNT, FOREVER, loaded, run_until
from test_menubar import bar  # noqa: F401  (a fixture)
from test_menubar import FILE, editor_text, entry_index, focus_on, key
from test_submenus import cascade

from ares import examples, helptext, toolchain
from ares.gui import about
from ares.gui import app as app_module
from ares.gui.app import MENUS
from ares.gui.editor import FileTab
from ares.runner import State

FOLDER = ROOT / "examples"
HELLO = FOLDER / "hello.s"


def shown_text(path):
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


@pytest.fixture
def example(app):
    """A tab with a copy of hello.s."""
    return app.cmd_open_example(HELLO)


# Where the examples are --------------------------------------------------------------------

def test_in_a_source_tree_the_folder_is_next_to_the_program():
    assert examples.examples_folder() == FOLDER
    assert FOLDER.is_dir()


def test_in_a_packaged_ares_the_folder_is_inside_it(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert examples.examples_folder() == tmp_path / "examples"
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples" / "one.s").write_text("x")
    assert examples.example_programs() == [tmp_path / "examples" / "one.s"]


def test_the_documents_and_the_examples_are_looked_up_in_the_same_place(tmp_path, monkeypatch):
    assert about.document_path is toolchain.document_path
    assert toolchain.document_path("LICENSE") == ROOT / "LICENSE"
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert about.document_path("LICENSE") == tmp_path / "LICENSE"


def test_the_programs_are_the_s_files_sorted_by_name(tmp_path, monkeypatch):
    folder = tmp_path / "examples"
    folder.mkdir()
    for name in ("zeta.s", "Beta.s", "alpha.s", "notes.txt", "gamma.S.bak"):
        (folder / name).write_text("x")
    (folder / "folder.s").mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert [p.name for p in examples.example_programs()] == ["alpha.s", "Beta.s", "zeta.s"]


def test_a_missing_folder_has_no_programs(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert examples.example_programs() == []


# The list -----------------------------------------------------------------------------------

def test_the_item_comes_right_under_open_and_has_a_letter_of_its_own(bar):
    menu, index, _ = cascade(bar)
    assert menu.entries[index - 1].label == "Open..."
    assert menu.entries[index].underline == 5               # Open Example
    assert dict((entry[0], entry[1]) for entry in MENUS[0][1] if entry)["open_example"] == (
        "Open &Example")


def test_the_list_equals_the_examples_folder(bar):
    _, _, sub = cascade(bar)
    names = sorted(p.name for p in FOLDER.iterdir() if p.suffix == ".s")
    assert names and [entry.label for entry in sub.entries] == names
    assert all(entry.kind == "command" and entry.state == "normal" for entry in sub.entries)
    assert all(entry.underline == 0 for entry in sub.entries)


@pytest.mark.parametrize("aqua", [False, True], ids=["own menus", "Tk's menus"])
def test_without_examples_one_gray_item_says_so(make_app, monkeypatch, aqua):
    monkeypatch.setattr(app_module, "example_programs", lambda: [])
    if aqua:
        monkeypatch.setattr("ares.gui.menubar.is_aqua", lambda widget: True)
    app = make_app()
    menu = app.root.nametowidget(app.menubar.entrycget(FILE, "menu"))
    index = next(k for k in range(menu.index("end") + 1) if menu.type(k) == "cascade")
    sub = app.root.nametowidget(menu.entrycget(index, "menu"))
    assert sub.index("end") == 0
    assert sub.entrycget(0, "label") == "(no examples found)"
    assert str(sub.entrycget(0, "state")) == "disabled"


def test_the_item_is_available_as_new_is(bar, app, tmp_path):
    menu, index, _ = cascade(bar)
    assert menu.enabled(index)                              # with no file open
    loaded(app, tmp_path, FOREVER)
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) > 100)
    assert menu.enabled(index) and app.is_enabled("new")
    app.run("open_example", HELLO)                          # a program running stops nothing
    assert app.editor.current.name == "hello.s"
    app.editor.select(app.editor.tabs[0])
    app.run("stop")


def test_a_click_on_an_example_opens_it(bar, app):
    _, index, sub = cascade(bar)
    click_title(bar, FILE)
    click_item(bar.menus[FILE], index)
    assert bar.sub_menu is sub
    click_item(sub, entry_index(sub, "arithmetic.s"))
    pump(app.root)
    assert closed(bar, app) and app.editor.current.name == "arithmetic.s"
    assert app.editor.current.path is None


def test_the_keyboard_opens_an_example(bar, app, monkeypatch):
    text = editor_text(app)
    focus_on(app, monkeypatch, text)
    key(text, "f", "Alt")
    focus_on(app, monkeypatch, bar)
    key(bar, "e")
    key(bar, "h")                                           # the only one with an h
    assert app.editor.current.name == "hello.s" and not bar.active


# The unsaved copy ---------------------------------------------------------------------------

def test_a_choice_opens_a_copy_as_a_new_unsaved_file(app, example):
    assert app.editor.current is example
    assert example.path is None and example.name == "hello.s"
    assert example.get_text() == shown_text(HELLO)
    assert example.modified and example.title() == "hello.s*"
    assert app.editor.notebook.tab(example, "text") == "hello.s*"
    assert app.root.title().startswith("hello.s* - ")
    assert app.views.select() == str(app.editor)


def test_an_empty_file_is_an_unsaved_copy_too(app, tmp_path):
    empty = tmp_path / "empty.s"
    empty.write_bytes(b"")
    tab = app.cmd_open_example(empty)
    assert tab.modified and tab.title() == "empty.s*"


def test_the_cursor_starts_at_the_top_with_the_keyboard_focus(app, hidden_windows, example):
    assert example.text.index("insert") == "1.0"
    assert hidden_windows.focus is example.text


def test_undo_cannot_empty_it(app, example):
    assert not example.can_undo() and not app.is_enabled("undo")
    app.run("undo")
    assert example.get_text() == shown_text(HELLO)


def test_undoing_a_change_goes_back_to_the_example_and_it_stays_unsaved(app, example):
    example.text.insert("1.0", "@ mine\n")
    assert app.is_enabled("undo")
    app.run("undo")
    assert example.get_text() == shown_text(HELLO)
    assert not example.can_undo()
    assert example.modified and example.title() == "hello.s*"
    app.run("redo")
    assert example.get_text().startswith("@ mine\n") and example.modified


def test_the_example_on_disk_is_never_changed(app, example, answers, tmp_path):
    before = HELLO.read_bytes()
    example.text.insert("1.0", "@ mine\n")
    answers["save_as"].append(str(tmp_path / "mine.s"))
    app.run("save")
    assert HELLO.read_bytes() == before
    assert (tmp_path / "mine.s").read_bytes().replace(b"\r\n", b"\n").startswith(b"@ mine\n")


def test_save_goes_to_save_as_with_the_examples_name_and_the_last_folder(app, example,
                                                                         monkeypatch, tmp_path):
    asked = []
    app.settings.last_folder = str(tmp_path)

    def ask(**options):
        asked.append(options)
        return str(tmp_path / "saved.s")
    monkeypatch.setattr(app_module.filedialog, "asksaveasfilename", ask)
    app.run("save")
    assert len(asked) == 1
    assert asked[0]["initialfile"] == "hello.s" and asked[0]["initialdir"] == str(tmp_path)
    assert example.path == tmp_path / "saved.s" and example.name == "saved.s"
    assert not example.modified and example.title() == "saved.s"
    assert shown_text(tmp_path / "saved.s") == shown_text(HELLO)


def test_save_cancelled_leaves_it_unsaved(app, example, answers):
    answers["save_as"].append("")
    app.run("save")
    assert example.path is None and example.modified


def test_the_copy_of_the_examples_beside_a_packaged_program_is_not_offered(
        app, monkeypatch, tmp_path):
    internal, visible = tmp_path / "_internal" / "examples", tmp_path / "examples"
    internal.mkdir(parents=True)
    visible.mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ARES.exe"))
    app.settings.last_folder = str(visible)
    assert app._folder_for_new_file() is None
    app.settings.last_folder = str(internal)
    assert app._folder_for_new_file() is None
    app.settings.last_folder = str(tmp_path)
    assert app._folder_for_new_file() == str(tmp_path)


def test_the_examples_own_folder_is_not_offered(app, example, monkeypatch, tmp_path):
    """Opened from there with File > Open, it is the last folder; a copy saved there under the
    name offered would replace the example."""
    asked = []
    app.settings.last_folder = str(FOLDER)

    def ask(**options):
        asked.append(options)
        return ""
    monkeypatch.setattr(app_module.filedialog, "asksaveasfilename", ask)
    app.run("save")
    assert asked[0]["initialdir"] is None


def test_opening_it_does_not_change_the_last_folder(app, tmp_path):
    app.settings.last_folder = str(tmp_path)
    app.cmd_open_example(HELLO)
    assert app.settings.last_folder == str(tmp_path)


def test_closing_it_asks_whether_to_save_as_any_unsaved_file(app, example, answers):
    answers["save_changes"].append(None)
    app.run("close")
    assert answers["asked"] == [("save_changes", "Save changes to hello.s?")]
    assert app.editor.current is example
    answers["save_changes"].append(False)
    app.run("close")
    assert app.editor.current is None


def test_closing_without_touching_it_asks_all_the_same(app, example, answers):
    answers["save_changes"].append(False)
    app.run("close")
    assert len(answers["asked"]) == 1


def test_exit_asks_too(app, example, answers):
    answers["save_changes"].append(None)
    app.run("exit")
    assert answers["asked"] == [("save_changes", "Save changes to hello.s?")]


def test_the_same_example_twice_gives_two_tabs(app, example):
    second = app.cmd_open_example(HELLO)
    assert second is not example and app.editor.tabs == [example, second]
    assert second.name == example.name == "hello.s"


def test_a_saved_copy_and_a_new_copy_live_side_by_side(app, example, answers, tmp_path):
    answers["save_as"].append(str(tmp_path / "hello.s"))
    app.run("save")
    second = app.cmd_open_example(HELLO)
    assert second is not example and second.path is None


def test_assemble_treats_it_as_a_new_file(app, example):
    lines = assemble(app)
    assert lines[0] == "Assemble: assembling hello.s"
    assert lines[-1] == "Assemble: operation completed successfully."
    assert app.runner is not None and app.program_tab is example
    assert example.modified and example.path is None        # assembling saves nothing


def test_assemble_file_upon_opening_assembles_it_as_open_does(app):
    app.settings.assemble_on_open = True
    tab = app.cmd_open_example(HELLO)
    wait_for_assembly(app)
    assert app.program_tab is tab and app.runner is not None


def test_an_example_takes_the_place_of_the_program_assembled_before(app, tmp_path):
    loaded(app, tmp_path, COUNT)
    tab = app.cmd_open_example(HELLO)
    assert assemble(app)[-1] == "Assemble: operation completed successfully."
    assert app.program_tab is tab


def test_without_that_setting_nothing_is_assembled(app):
    app.cmd_open_example(HELLO)
    assert not app.assembling and app.runner is None


def test_assemble_file_upon_opening_waits_while_a_program_runs(app, tmp_path):
    app.settings.assemble_on_open = True
    runner = loaded(app, tmp_path, FOREVER)
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) > 100)
    tab = app.cmd_open_example(HELLO)
    assert app.runner is runner and runner.state is State.RUNNING
    app.editor.select(app.editor.tabs[0])                   # back to the running source
    app.run("stop")                                         # now the example is assembled
    wait_for_assembly(app)
    assert app.runner is not runner and app.program_tab is tab


def test_a_read_error_shows_the_same_message_as_open(app, answers, tmp_path):
    gone = tmp_path / "gone.s"
    assert app.cmd_open_example(gone) is None
    (kind, text), = answers["asked"]
    assert kind == "error" and text.startswith(f"Cannot open {gone}:\n")
    assert app.editor.tabs == []


def test_a_failed_read_leaves_no_tab_behind(app, answers, tmp_path):
    app.cmd_new()
    app.cmd_open_example(tmp_path / "gone.s")
    assert len(app.editor.tabs) == 1 and len(app.editor.notebook.tabs()) == 1
    assert [w for w in app.editor.notebook.winfo_children()
            if isinstance(w, FileTab)] == app.editor.tabs


def test_a_register_field_is_applied_first_as_for_every_command(app, tmp_path, monkeypatch):
    loaded(app, tmp_path, PROGRAM)
    double_click(app.registers, ROW["registers"])
    field = app.registers.editor
    monkeypatch.setattr(app.root, "focus_get", lambda: field)
    type_into(app.registers, "7")
    app.run("open_example", HELLO)
    assert app.registers.editor is None and app.machine.reg(1) == 7
    assert app.editor.current.name == "hello.s"


def test_a_wrong_register_value_keeps_the_example_waiting(app, tmp_path, monkeypatch):
    loaded(app, tmp_path, PROGRAM)
    double_click(app.registers, ROW["registers"])
    field = app.registers.editor
    monkeypatch.setattr(app.root, "focus_get", lambda: field)
    monkeypatch.setattr(app.registers, "bell", lambda: None, raising=False)
    tabs = len(app.editor.tabs)
    type_into(app.registers, "abc")
    app.run("open_example", HELLO)
    assert len(app.editor.tabs) == tabs and app.registers.editor is field


def test_a_copy_of_a_file_with_windows_line_ends_keeps_them_when_saved(app, answers, tmp_path):
    source = tmp_path / "crlf.s"
    source.write_bytes(b"NOP\r\nNOP\r\n")
    tab = app.cmd_open_example(source)
    assert tab.get_text() == "NOP\nNOP\n"
    answers["save_as"].append(str(tmp_path / "copy.s"))
    app.run("save")
    assert (tmp_path / "copy.s").read_bytes() == b"NOP\r\nNOP\r\n"


def test_every_bundled_example_opens(app):
    for path in examples.example_programs():
        tab = app.cmd_open_example(path)
        assert tab.get_text() == shown_text(path) and tab.modified


# The Help -----------------------------------------------------------------------------------

def test_the_help_says_where_the_examples_are_for_every_kind_of_ares():
    assert "File > Open Example" in helptext.INTRO
    assert "folder examples" not in helptext.INTRO
    assert "File > Open Example" in helptext.IDE


def test_the_help_says_how_the_keys_work_a_submenu():
    assert "Left or\nEscape close just the submenu" in helptext.KEYBOARD
