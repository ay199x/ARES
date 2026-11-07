# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The main window: layout, menus, shortcuts, toolbar, states and title."""

from tkinter import ttk

import pytest
from conftest import VIRTUAL_DISPLAY, press_key, use_test_clipboard

from ares.gui import app as app_module
from ares.gui.app import MAX_SPEED, App
from ares.gui.widgets import SHORTCUT_TAG
from ares.gui.table import MARK_OFF, STRIPE, off_colour
from ares.settings import Settings

TITLE = "ARES 1.0"      # the window's title while no file is open


def tab_titles(notebook):
    return [notebook.tab(tab, "text") for tab in notebook.tabs()]


def menu_table(app):
    """{menu title: [(label, accelerator) or "-"]} read back from the Tk menus."""
    table = {}
    bar = app.menubar
    for i in range(bar.index("end") + 1):
        menu = app.root.nametowidget(bar.entrycget(i, "menu"))
        items = []
        for j in range(menu.index("end") + 1):
            if menu.type(j) == "separator":
                items.append("-")
            else:
                items.append((menu.entrycget(j, "label"), menu.entrycget(j, "accelerator")))
        table[bar.entrycget(i, "label")] = items
    return table


# Every menu's items, with their shortcuts.
EXPECTED_MENUS = {
    "File": [("New", "Ctrl+N"), ("Open...", "Ctrl+O"), ("Open Example", ""), ("Close", ""),
             ("Close All", ""), "-",
             ("Save", "Ctrl+S"), ("Save As...", ""), ("Save All", ""), "-",
             ("Dump Memory...", ""), "-", ("Exit", "")],
    "Edit": [("Undo", "Ctrl+Z"), ("Redo", "Ctrl+Y"), "-", ("Cut", "Ctrl+X"),
             ("Copy", "Ctrl+C"), ("Paste", "Ctrl+V"), "-", ("Find/Replace...", "Ctrl+F"),
             ("Select All", "Ctrl+A"), "-", ("Capitalize Instructions", "")],
    "Run": [("Assemble", "F3"), ("Go", "F5"), ("Step", "F7"), ("Backstep", "F8"),
            ("Pause", "F9"), ("Stop", "F11"), ("Reset", "F12"), "-",
            ("Clear All Breakpoints", "Ctrl+K"), ("Toggle All Breakpoints", "Ctrl+T")],
    "Settings": [("Show Labels Window", ""), ("Assemble File Upon Opening", ""),
                 ("Addresses in Hexadecimal", ""), ("Values in Hexadecimal", ""),
                 ("Require Capital Letters", ""), ("Popup Dialog for Input", ""),
                 ("Enable Backstep While Running", ""), "-", ("Editor Font...", ""), "-",
                 ("Restore Defaults", "")],
    "Tools": [("ARM X-Ray", ""), ("BHT Simulator", ""), ("Bitmap Display", ""),
              ("Data Cache Simulator", ""),
              ("Digital Lab Sim", ""), ("Dynamic Instruction Counter", ""),
              ("Floating Point Representation", ""),
              ("Keyboard and Display MMIO Simulator", ""),
              ("Memory Reference Visualization", ""), "-", ("Memory Map", "")],
    "Help": [("Help", ""), ("About ARES", "")],
}


def test_the_title_has_the_version_and_no_full_name(make_app):
    app = make_app()
    assert app.root.title() == "ARES 1.0"
    assert "Educational" not in app.root.title()


def test_no_test_can_show_a_window(app, monkeypatch, hidden_windows):
    # Not even after monkeypatch.undo(), which once let a real message box appear.
    monkeypatch.setattr(app.root, "title", app.root.title)
    monkeypatch.undo()
    with pytest.raises(AssertionError, match="would open"):
        app_module.messagebox.askyesnocancel("ARES", "Save changes?", parent=app.root)
    app.root.deiconify()
    app.root.update()
    assert (VIRTUAL_DISPLAY or not app.root.winfo_ismapped()) and hidden_windows.shows(app.root)


def test_the_window_layout(app):
    assert app.root.title() == TITLE
    assert str(app.main_split.cget("orient")) == "horizontal"
    assert app.main_split.panes() == (str(app.left_part), str(app.side))
    assert app.left_split.master is app.left_part
    assert str(app.left_split.cget("orient")) == "vertical"
    assert app.left_split.panes() == (str(app.views), str(app.messages))
    assert tab_titles(app.views) == ["Edit", "Execute"]
    assert tab_titles(app.messages) == ["ARES Messages", "Run I/O"]
    assert tab_titles(app.side) == ["Registers", "Coproc 10", "Coproc 11"]
    for text in (app.messages.messages, app.messages.run_io):
        tab = app.root.nametowidget(app.messages.tabs()[text is app.messages.run_io])
        buttons = [w for w in tab.winfo_children() if isinstance(w, ttk.Button)]
        assert [b.cget("text") for b in buttons] == ["Clear"]
        # At the left edge, beside the text and its scroll bars.
        assert tab.pack_slaves().index(buttons[0]) < tab.pack_slaves().index(text.master)
        assert buttons[0].pack_info()["side"] == text.master.pack_info()["side"] == "left"
    assert app.execute.panes() == (str(app.execute.segments),)    # Labels hidden by default
    segments = [app.root.nametowidget(p) for p in app.execute.segments.panes()]
    assert [w.title for w in segments] == ["Text Segment", "Data Segment"]
    assert str(app.execute.segments.cget("orient")) == "vertical"


class Divider:
    """A paned window's size and first divider; a hidden window has no real size."""

    def __init__(self, monkeypatch, paned, size, dimension):
        self.position = 0
        monkeypatch.setattr(paned, f"winfo_{dimension}", lambda: size)
        monkeypatch.setattr(paned, "sashpos", self.sashpos)

    def sashpos(self, index, position=None):
        if position is not None:
            self.position = position
        return self.position


@pytest.mark.skipif(VIRTUAL_DISPLAY, reason="a mapped window has placed its dividers already")
def test_the_splits_start_where_those_of_the_classic_window_are(app, monkeypatch):
    main = Divider(monkeypatch, app.main_split, 2000, "width")
    left = Divider(monkeypatch, app.left_split, 1000, "height")
    app._set_splits()                   # done on the first Configure event of a real window
    assert (main.position, left.position) == (1464, 771)
    main.position = 100
    app._set_splits()                   # only once
    assert main.position == 100


def test_menus_and_shortcuts(app):
    expected = {
        title: [item if item == "-" else (item[0], app._accelerator(item[1]) if item[1] else "")
                for item in items]
        for title, items in EXPECTED_MENUS.items()}
    assert menu_table(app) == expected
    for title in expected:
        index = list(expected).index(title)
        assert app.menubar.entrycget(index, "underline") == 0


def test_every_shortcut_is_bound_on_the_window_and_on_text_widgets(app):
    assert len(app._keys) == 19
    for name, key in app._keys.items():
        for sequence in app._sequences(key):
            assert app.root.bind(sequence), (name, sequence)
            assert app.root.bind_class(SHORTCUT_TAG, sequence), (name, sequence)
    assert app._sequences("Ctrl+N")[0] in ("<Control-Key-n>", "<Command-Key-n>")
    assert app._sequences("F11") == ["<Key-F11>"]


def test_settings_menu_shows_the_settings(app):
    menu = app.root.nametowidget(app.menubar.entrycget(3, "menu"))
    assert menu.type(0) == "checkbutton"
    assert app.setting_vars["require_capitals"].get() is True
    assert app.setting_vars["backstep_while_running"].get() is False


def test_toolbar_order_tooltips_and_gaps(app):
    bar = app.buttons["new"].master
    names = {button: name for name, button in app.buttons.items()}
    order = []
    for child in bar.pack_slaves():
        if child in names:
            if child.pack_info()["padx"] != 0:          # a blank gap between two groups
                order.append("|")
            order.append(names[child])
    assert " ".join(order) == ("new open save save_as | undo redo | cut copy paste | find | "
                               "assemble | go step backstep pause stop reset | help")
    assert all(str(b.cget("style")) == "Toolbutton" for b in app.buttons.values())
    assert app.tooltips["go"].text == f"Run the program ({app._accelerator('F5')})"
    assert app.tooltips["save_as"].text == "Save the current file under a new name"
    assert all(app.tooltips[name].text for name in app.buttons)


def test_tooltip_shows_its_text_and_hides(app, hidden_windows, monkeypatch):
    tooltip = app.tooltips["open"]
    if not VIRTUAL_DISPLAY:
        tooltip.show()
        assert tooltip._window is None      # not while the button is off the screen
    monkeypatch.setattr(app.buttons["open"], "winfo_ismapped", lambda: True)
    tooltip.show()
    assert hidden_windows.shows(tooltip._window)
    labels = tooltip._window.winfo_children()
    assert labels[0].cget("text") == tooltip.text
    tooltip.hide()
    assert tooltip._window is None


def test_states_without_a_file(app):
    for name in ("new", "open", "exit", "copy", "select_all", "restore_defaults",
                 "memory_map", "help", "about"):
        assert app.is_enabled(name), name
    for name in ("close", "close_all", "save", "save_as", "save_all", "undo", "redo", "cut",
                 "paste", "find", "capitalize", "go", "step", "backstep", "pause", "stop",
                 "reset", "clear_breakpoints", "toggle_breakpoints", "dump_memory"):
        assert not app.is_enabled(name), name
    assert app.buttons["save"].instate(["disabled"])
    assert app.buttons["new"].instate(["!disabled"])
    menu, index = app._menu_items["save"]
    assert menu.entrycget(index, "state") == "disabled"


def test_states_follow_the_editor(app):
    app.cmd_new()
    for name in ("close", "close_all", "save", "save_as", "save_all", "cut", "paste", "find",
                 "capitalize"):
        assert app.is_enabled(name), name
    assert not app.is_enabled("undo") and not app.is_enabled("redo")
    text = app.editor.current.text
    text.insert("1.0", "MOV R0, #1")
    assert app.is_enabled("undo") and not app.is_enabled("redo")
    app.cmd_undo()
    assert text.get("1.0", "end-1c") == ""
    assert not app.is_enabled("undo") and app.is_enabled("redo")
    assert app.buttons["redo"].instate(["!disabled"])
    app.cmd_redo()
    assert text.get("1.0", "end-1c") == "MOV R0, #1"


def test_disabled_command_does_nothing(app, monkeypatch):
    called = []
    monkeypatch.setattr(App, "cmd_save", lambda self: called.append(1), raising=True)
    app.run("save")                     # no file is open
    assert called == []


def test_title_and_tab_show_the_file_and_unsaved_changes(app):
    app.cmd_new()
    assert app.root.title() == f"untitled1.s - {TITLE}"
    app.editor.current.text.insert("1.0", "x")
    assert app.root.title() == f"untitled1.s* - {TITLE}"
    assert tab_titles(app.editor.notebook) == ["untitled1.s*"]
    app.cmd_new()
    assert app.root.title() == f"untitled2.s - {TITLE}"
    app.cmd_close()
    assert app.root.title() == f"untitled1.s* - {TITLE}"


def test_the_title_names_the_file_on_top(app, tmp_path):
    # The program's name, then the file's while one is open, * while unsaved.
    assert app.root.title() == "ARES 1.0"
    (tmp_path / "hello.s").write_text("NOP\n")
    (tmp_path / "fact.s").write_text("NOP\n")
    first = app.open_path(tmp_path / "hello.s")
    assert app.root.title() == "hello.s - ARES 1.0"
    first.text.insert("1.0", "X")
    assert app.root.title() == "hello.s* - ARES 1.0"
    second = app.open_path(tmp_path / "fact.s")
    assert app.root.title() == f"fact.s - {TITLE}"
    app.editor.select(first)
    assert app.root.title() == f"hello.s* - {TITLE}"
    assert app.save(first)
    assert app.root.title() == f"hello.s - {TITLE}"
    app.editor.select(second)
    assert app.root.title() == f"fact.s - {TITLE}"
    assert app.close_tab(second)
    assert app.root.title() == f"hello.s - {TITLE}"
    assert app.close_tab(first)
    assert app.root.title() == TITLE


def test_the_message_boxes_keep_the_short_title(app, monkeypatch):
    titles = []
    monkeypatch.setattr(app_module.messagebox, "askyesnocancel",
                        lambda title, message, **options: titles.append(title))   # Cancel
    app.cmd_new()
    app.editor.current.text.insert("1.0", "x")
    app.cmd_close()
    assert titles == ["ARES"] and len(app.editor.tabs) == 1


def test_speed_slider_label(app):
    assert app.speed_label.cget("text") == "Run speed at max (no interaction)"
    assert app.run_speed is None
    app.speed.set(10.4)
    app._speed_moved(10.4)
    assert app.speed.get() == 10
    assert app.speed_label.cget("text") == "Run speed 10 inst/sec"
    assert app.run_speed == 10
    app.speed.set(MAX_SPEED)
    app._speed_moved(MAX_SPEED)
    assert app.run_speed is None


def register_rows(app):
    """{name: (number, value, flags)} as the Registers table draws them.

    flags holds (text, colour) of each mark: N, Z, C, V, I and the mode.
    """
    table = app.registers.table
    body = table.body
    rows = {}
    for items in table.slots:
        if body.itemcget(items[0], "state") != "hidden":
            name, number, value = (body.itemcget(items[2 + 2 * k], "text") for k in range(3))
            marks = tuple((body.itemcget(item, "text"), body.itemcget(item, "fill"))
                          for item in items[9:] if body.itemcget(item, "state") != "hidden")
            rows[name] = (number, value, marks)
    return rows


def test_registers_show_the_initial_state(app):
    table = app.registers.table
    table.fit(30 * table.row_height)
    rows = register_rows(app)
    assert list(rows) == [f"R{n}" for n in range(13)] + ["SP", "LR", "PC", "CPSR", "SPSR"]
    assert [number for number, _, _ in rows.values()] == [str(n) for n in range(16)] + ["", ""]
    assert rows["R0"][1:] == ("0x00000000", ())
    assert rows["SP"][1] == "0x00000000"
    gray, black = MARK_OFF, "#000000"
    stripe = off_colour(STRIPE)         # CPSR is on a gray row, SPSR on a white one
    assert rows["CPSR"][1:] == ("0x000001d3", (("N", stripe), ("Z", stripe), ("C", stripe),
                                               ("V", stripe), ("I", black), ("SVC", black)))
    assert rows["SPSR"][1:] == ("0x00000000", (("N", gray), ("Z", gray), ("C", gray),
                                               ("V", gray), ("I", gray), ("?", black)))
    app.setting_vars["hex_values"].set(False)
    app._setting_toggled("hex_values")
    rows = register_rows(app)
    assert rows["SP"][1] == "0"
    assert rows["CPSR"][1] == "0x000001d3"         # status registers stay hexadecimal
    app.registers.set_values([0xFFFFFFFF] * 16, 0xF000001F, 0x1234)
    rows = register_rows(app)
    assert rows["R5"][1] == "-1"
    assert rows["CPSR"][2] == (("N", black), ("Z", black), ("C", black), ("V", black),
                               ("I", stripe), ("SYS", black))
    assert rows["SPSR"][1:] == ("-", (("-", black),))           # System mode has no SPSR


def test_settings_menu_changes_are_saved(app, tmp_path):
    app.setting_vars["require_capitals"].set(False)
    app._setting_toggled("require_capitals")
    assert Settings.load(tmp_path / "settings.json").require_capitals is False
    app.cmd_restore_defaults()
    assert app.setting_vars["require_capitals"].get() is True
    assert Settings.load(tmp_path / "settings.json").require_capitals is True


def test_shortcuts_win_over_text_widget_bindings(app, monkeypatch):
    monkeypatch.setattr(app_module.filedialog, "askopenfilenames", lambda **options: ())
    app.cmd_new()
    text = app.editor.current.text
    text.insert("1.0", "MOV R0, #1\nMOV R1, #2")
    text.edit_separator()
    text.mark_set("insert", "1.4")
    assert text.bindtags()[:3] == (str(text), SHORTCUT_TAG, "Text")
    # The Text class would delete to the line end (Ctrl+K), swap letters
    # (Ctrl+T) and open a line (Ctrl+O); the window's binding stops that.
    for key in ("Ctrl+K", "Ctrl+T", "Ctrl+O"):
        sequence = app._sequences(key)[0]
        assert text.tk.call("bind", "Text", sequence.replace("Command", "Control"))
        assert press_key(text, sequence) == [SHORTCUT_TAG]
    assert text.get("1.0", "end-1c") == "MOV R0, #1\nMOV R1, #2"
    text.insert("end", "\nA")
    text.edit_separator()
    text.insert("end", "B")
    text.edit_separator()
    assert press_key(text, app._sequences("Ctrl+Z")[0]) == [SHORTCUT_TAG]    # one undo
    assert text.get("1.0", "end-1c") == "MOV R0, #1\nMOV R1, #2\nA"
    for pane in (app.messages.messages, app.messages.run_io):
        assert pane.bindtags()[:3] == (str(pane), SHORTCUT_TAG, "Text")


def test_shortcuts_work_wherever_the_focus_is(app):
    app.cmd_new()
    tree = app.registers.table.body
    assert press_key(tree, app._sequences("Ctrl+N")[0]) == [str(app.root)]
    assert [tab.name for tab in app.editor.tabs] == ["untitled1.s", "untitled2.s"]
    assert press_key(tree, "<Key-F5>") == [str(app.root)]      # Go: not available yet


def test_read_only_panes_ignore_typing_but_can_be_copied(app, monkeypatch):
    use_test_clipboard(app.root)
    pane = app.messages.messages
    app.messages.write_message("Assemble: assembling x.s")
    pane.insert("end", "typed")
    pane.delete("1.0", "end")
    app.root.clipboard_append("pasted")
    pane.event_generate("<<Paste>>")
    assert pane.get("1.0", "end-1c") == "Assemble: assembling x.s\n"
    pane.tag_add("sel", "1.0", "1.8")
    monkeypatch.setattr(app.root, "focus_get", lambda: pane)
    app.cmd_copy()
    assert app.root.clipboard_get() == "Assemble"
    app.cmd_select_all()
    assert pane.get("sel.first", "sel.last") == "Assemble: assembling x.s\n"


@pytest.mark.parametrize("where", ["messages", "run_io", "registers"])
def test_cut_and_paste_keys_in_a_pane_leave_the_editor_alone(app, monkeypatch, where):
    use_test_clipboard(app.root)
    app.cmd_new()
    tab = app.editor.current
    tab.text.insert("1.0", "    MOV R0, #1\n")
    tab.select_line(1)                  # as clicking an error message does
    pane = {"messages": app.messages.messages, "run_io": app.messages.run_io,
            "registers": app.registers.table.body}[where]
    monkeypatch.setattr(app.root, "focus_get", lambda: pane)      # the student clicks the pane
    app.root.clipboard_append("PASTED")
    for key, command in (("Ctrl+X", "cut"), ("Ctrl+V", "paste")):
        press_key(pane, app._sequences(key)[0])
        app.run(command)                                            # from the menu or toolbar
    assert tab.get_text() == "    MOV R0, #1\n" and app.root.clipboard_get() == "PASTED"
    monkeypatch.setattr(app.root, "focus_get", lambda: tab.text)
    press_key(tab.text, app._sequences("Ctrl+X")[0])
    assert tab.get_text() == "\n" and app.root.clipboard_get() == "    MOV R0, #1"


def click_tab(notebook, page):
    """Click a notebook's tab as Tk does.

    A page with nothing that takes the keyboard focus, such as Execute, leaves
    the focus on the notebook (Tk's own focus command: the Screen does not see it).
    """
    notebook.tk.call("ttk::notebook::ActivateTab", notebook, page)


@pytest.mark.parametrize("command", ["undo", "redo", "cut", "paste", "capitalize", "find"])
def test_edit_commands_bring_the_editor_to_the_front_with_the_focus(app, hidden_windows,
                                                                    monkeypatch, command):
    use_test_clipboard(app.root)
    app.cmd_new()
    tab = app.editor.current
    tab.text.insert("1.0", "_start:\n    mov r0, #1\n")
    tab.text.edit_separator()
    tab.text.insert("end", "    SVC #10\n")
    if command == "redo":
        app.cmd_undo()
    tab.text.tag_add("sel", "2.4", "2.7")
    app.root.clipboard_append("MOV")
    # The Find window takes the focus itself; the editor has it back when that closes.
    monkeypatch.setattr(app.find_dialog, "show", lambda initial="": None)
    click_tab(app.views, app.execute)
    hidden_windows.focus = None         # no longer the editor, where New put it
    app.run(command)
    assert app.views.select() == str(app.editor)
    assert hidden_windows.focus is tab.text


def test_arrow_keys_after_undo_on_the_execute_tab_move_the_cursor(app, hidden_windows):
    app.cmd_new()
    tab = app.editor.current
    tab.text.insert("1.0", "    NOP\n")
    tab.text.edit_separator()
    tab.text.insert("end", "    SVC #10\n")
    click_tab(app.views, app.execute)
    hidden_windows.focus = None         # no longer the editor, where New put it
    press_key(app.views, app._sequences("Ctrl+Z")[0])
    # The next key goes where the focus is; left on the notebook, Left would show Execute.
    press_key(hidden_windows.focus or app.views, "<Key-Left>")
    assert app.views.select() == str(app.editor)
    assert tab.get_text() == "    NOP\n"


def test_the_find_window_shows_its_match_in_the_edit_tab(app):
    app.cmd_new()
    tab = app.editor.current
    tab.text.insert("1.0", "_start:\n    SVC #10\n")
    tab.text.mark_set("insert", "1.0")
    app.run("find")
    app.views.select(app.execute)       # the Find window stays open meanwhile
    dialog = app.find_dialog
    dialog.find_entry.insert(0, "SVC")
    press_key(dialog.find_entry, "<Key-Return>")
    assert app.views.select() == str(app.editor)
    assert tab.text.get("sel.first", "sel.last") == "SVC"


def test_opening_a_folder_says_it_is_a_folder(app, tmp_path, monkeypatch):
    errors = []
    monkeypatch.setattr(app_module.messagebox, "showerror",
                        lambda title, message, **options: errors.append(message))
    folder = tmp_path / "lab1"
    folder.mkdir()
    assert app.open_path(folder) is None        # Windows itself says "Permission denied"
    assert errors == [f"{folder} is a folder, not a file."] and app.editor.tabs == []


def test_failing_commands_in_read_only_panes_do_not_stop_the_window(app):
    # Tk's bindings run commands that may fail and catch the error, such as
    # copying with nothing selected. Had the error passed through Python,
    # mainloop() would raise it and ARES would end.
    pane = app.messages.messages
    caught = []

    def poke():
        caught.append(pane.tk.eval(f"catch {{{pane._w} get sel.first sel.last}}"))
        app.root.after(10, app.root.quit)
    app.root.after(10, poke)
    app.root.mainloop()
    assert caught == ["1"]


def test_clear_buttons_empty_their_pane(app):
    app.messages.write_message("one")
    app.messages.write_output("two")
    for text in (app.messages.messages, app.messages.run_io):
        tab = app.root.nametowidget(app.messages.tabs()[text is app.messages.run_io])
        clear = [w for w in tab.winfo_children() if isinstance(w, ttk.Button)][0]
        clear.invoke()
        assert text.get("1.0", "end-1c") == ""


def test_unexpected_errors_go_to_the_messages_pane(app):
    try:
        raise ValueError("boom")
    except ValueError as e:
        app.report_error(type(e), e, e.__traceback__)
    text = app.messages.messages.get("1.0", "end")
    assert "Internal error: ValueError('boom')" in text
    assert "Traceback" in text


def test_close_button_on_a_tab_closes_it(app):
    first = app.editor.new_file()
    second = app.editor.new_file()
    notebook = app.editor.notebook
    app.root.update()
    x0, y0, x1, y1 = notebook.close_box(notebook.boxes()[0])
    x, y = (x0 + x1) // 2, (y0 + y1) // 2
    notebook.strip.winfo_id()
    notebook.strip.event_generate("<ButtonPress-1>", x=x, y=y)
    notebook.strip.event_generate("<ButtonRelease-1>", x=x, y=y)
    assert app.editor.tabs == [second]
    assert not first.winfo_exists()


def px_limit(widget, size):
    return min(widget.winfo_height(), round(size * widget.winfo_fpixels("1i") / 96))
