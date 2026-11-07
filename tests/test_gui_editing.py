# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Changing values in the Registers, Coproc 10 and Coproc 11 tabs.

A double-click on a value, or Enter or F2 on a selected row, opens a field
over it with the value selected; Enter or a click elsewhere applies it;
Escape cancels; a wrong value rings the bell and the field stays open, in
view. Hidden windows never give a widget the keyboard focus, so a test tells
the pane where a click put the focus, also when the field kept it; the
mouse's own events are the real ones.
"""

import pytest
from conftest import press_key
from test_gui_app import px_limit
from test_gui_assemble import open_source
from test_gui_run import READ_INT, go_to_end, loaded, run_until

from ares.gui.app import NOT_ASSEMBLED
from ares.gui.registers import CPSR_ROW, ROWS
from ares.runner import State

PROGRAM = """\
        .global _start
_start: MOV     R2, #5
        MOV     R3, #6
        SVC     #10
"""
LOOP = """\
        .global _start
_start: ADD     R0, R0, #1
        B       _start
"""
PANES = ["registers", "coproc10", "coproc11"]
ROW = {"registers": ROWS.index("R1"), "coproc10": 4, "coproc11": 3}       # R1, S4, D3
TYPED = {"registers": "7", "coproc10": "2.5", "coproc11": "-0.5"}


def typed_value(app, pane):
    """The value the machine holds now for the row of ROW."""
    return {"registers": lambda: app.machine.reg(1), "coproc10": lambda: app.machine.single(4),
            "coproc11": lambda: app.machine.double(3)}[pane]()


TYPED_BITS = {"registers": 7, "coproc10": 0x40200000, "coproc11": 0xBFE0000000000000}


def shown(pane, index):
    """The text of a row's value as the table shows it."""
    column = [column.id for column in pane.table.columns].index("value")
    return pane._row(index).cells[column]


def made(table):
    """Make the table's (hidden) window exist: generated events need it.

    Its making delivers the <Configure> the table waited for, so the columns
    take their widths now; measure cells after this.
    """
    table.body.winfo_id()
    table.winfo_toplevel().update_idletasks()
    return table


def mouse(table, x, y, *events):
    """Send the mouse's real events to a table at (x, y) of its body."""
    made(table)
    for event in events:
        table.body.event_generate(event, x=x, y=y)


def double_click(pane, index, column="value"):
    """Press, release, press again (a double click) and release over a cell."""
    table = made(pane.table)
    table.see(index)
    x0, y0, x1, y1 = table.cell_box(index, column)
    mouse(table, (x0 + x1) // 2 - int(table.body.canvasx(0)), (y0 + y1) // 2,
          "<ButtonPress-1>", "<ButtonRelease-1>", "<ButtonPress-1>", "<ButtonRelease-1>")


def focus_moved(pane, widget, monkeypatch):
    """A click on widget took the keyboard focus from the field."""
    monkeypatch.setattr(pane, "_focus_path", lambda: str(widget) if widget is not None else "")
    pane.editor.winfo_id()
    pane.editor.event_generate("<FocusOut>")


def focus_kept(pane, monkeypatch):
    """The field keeps the keyboard focus through clicks on controls that take none.

    Without this the focus seen would depend on the tests run before: the
    first hidden window of a test run may have it itself.
    """
    monkeypatch.setattr(pane, "_focus_path",
                        lambda: str(pane.editor) if pane.editor is not None else "")


def type_into(pane, text):
    pane.editor.delete(0, "end")
    pane.editor.insert(0, text)


def bells(pane):
    rings = []
    pane.editor.bell = lambda: rings.append(1)
    return rings


def click(widget, x=3, y=3):
    """Press and release the mouse's first button over widget (the real events)."""
    widget.winfo_id()
    widget.event_generate("<ButtonPress-1>", x=x, y=y)
    widget.event_generate("<ButtonRelease-1>", x=x, y=y)


def descendants(widget):
    yield widget
    for child in widget.winfo_children():
        yield from descendants(child)


def control(widget, text):
    """The button or checkbox labelled text inside widget."""
    return next(w for w in descendants(widget)
                if w.winfo_class() in ("TButton", "TCheckbutton") and w.cget("text") == text)


def run_io_page(app):
    return app.messages.nametowidget(app.messages.tabs()[1])


def run_io_clear(app):
    return control(run_io_page(app), "Clear")


def settings_item(app, label):
    """Choose a check item of the Settings menu."""
    bar = app.menubar
    menu = next(app.root.nametowidget(bar.entrycget(i, "menu"))
                for i in range(bar.index("end") + 1) if bar.entrycget(i, "label") == "Settings")
    menu.invoke(next(i for i in range(menu.index("end") + 1)
                     if menu.type(i) == "checkbutton" and menu.entrycget(i, "label") == label))


def click_close_button(notebook, index):
    """Click the close button on the notebook's tab index."""
    notebook.update()
    x0, y0, x1, y1 = notebook.close_box(notebook.boxes()[index])
    click(notebook.strip, (x0 + x1) // 2, (y0 + y1) // 2)


@pytest.mark.parametrize("name", PANES)
def test_a_double_click_opens_a_field_with_the_value_selected(app, tmp_path, hidden_windows,
                                                              name):
    loaded(app, tmp_path, PROGRAM)
    pane = getattr(app, name)
    double_click(pane, ROW[name])           # the release after the double click keeps it
    editor = pane.editor
    assert editor is not None and editor.get() == shown(pane, ROW[name])
    assert editor.selection_present() and editor.index("insert") == len(editor.get())
    assert hidden_windows.focus is editor
    assert pane.table.selected == ROW[name]


@pytest.mark.parametrize("key", ["<Key-Return>", "<Key-KP_Enter>", "<Key-F2>"])
@pytest.mark.parametrize("name", PANES)
def test_enter_or_f2_on_a_selected_row_opens_the_field(app, tmp_path, name, key):
    loaded(app, tmp_path, PROGRAM)
    pane = getattr(app, name)
    pane.table.select(ROW[name])
    press_key(pane.table.body, key)
    assert pane.editor is not None and pane.editor.get() == shown(pane, ROW[name])


@pytest.mark.parametrize("name", PANES)
def test_enter_applies_the_value(app, tmp_path, hidden_windows, name):
    loaded(app, tmp_path, PROGRAM)
    pane = getattr(app, name)
    double_click(pane, ROW[name])
    type_into(pane, TYPED[name])
    press_key(pane.editor, "<Return>")
    assert typed_value(app, name) == TYPED_BITS[name] and pane.editor is None
    assert hidden_windows.focus is pane.table.body          # the keys move the rows again


@pytest.mark.parametrize("name", PANES)
def test_a_click_elsewhere_applies_the_value(app, tmp_path, hidden_windows, monkeypatch, name):
    loaded(app, tmp_path, PROGRAM)
    pane = getattr(app, name)
    double_click(pane, ROW[name])
    type_into(pane, TYPED[name])
    focus_moved(pane, app.messages.run_io, monkeypatch)     # a click into Run I/O
    assert typed_value(app, name) == TYPED_BITS[name] and pane.editor is None
    assert hidden_windows.focus is not pane.table.body      # the focus stays where it went


@pytest.mark.parametrize("name", PANES)
def test_a_click_on_another_row_applies_the_value(app, tmp_path, monkeypatch, name):
    loaded(app, tmp_path, PROGRAM)
    pane = getattr(app, name)
    double_click(pane, ROW[name])
    type_into(pane, TYPED[name])
    table = made(pane.table)
    x0, y0, x1, y1 = table.cell_box(0, "name")
    mouse(table, x0 + 2, y0 + 2, "<ButtonPress-1>")         # the table takes the focus
    focus_moved(pane, table.body, monkeypatch)
    assert typed_value(app, name) == TYPED_BITS[name] and pane.editor is None
    assert table.selected == 0


@pytest.mark.parametrize("name", PANES)
def test_a_wrong_value_and_a_click_elsewhere_keep_the_field(app, tmp_path, hidden_windows,
                                                            monkeypatch, name):
    loaded(app, tmp_path, PROGRAM)
    pane = getattr(app, name)
    double_click(pane, ROW[name])
    rings = bells(pane)
    type_into(pane, "abc")
    focus_moved(pane, app.editor.current.text, monkeypatch)  # a click into the editor
    assert rings == [1] and pane.editor is not None and pane.editor.get() == "abc"
    assert hidden_windows.focus is pane.editor              # it takes the focus back
    assert typed_value(app, name) == 0


def test_the_field_waits_while_another_program_has_the_focus(app, tmp_path, monkeypatch):
    loaded(app, tmp_path, PROGRAM)
    pane = app.registers
    double_click(pane, ROW["registers"])
    type_into(pane, "7")
    focus_moved(pane, None, monkeypatch)                    # ARES itself lost the focus
    assert pane.editor is not None and app.machine.reg(1) == 0
    press_key(pane.editor, "<Return>")
    assert app.machine.reg(1) == 7


@pytest.mark.parametrize("name", PANES)
def test_escape_cancels(app, tmp_path, name):
    loaded(app, tmp_path, PROGRAM)
    pane = getattr(app, name)
    double_click(pane, ROW[name])
    type_into(pane, TYPED[name])
    press_key(pane.editor, "<Key-Escape>")
    assert pane.editor is None and typed_value(app, name) == 0


def test_a_command_applies_the_field_first(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    pane = app.registers
    double_click(pane, ROW["registers"])
    type_into(pane, "7")
    app.run("step")                                         # the toolbar's or menu's Step
    assert app.machine.reg(1) == 7 and app.machine.reg(2) == 5 and pane.editor is None
    double_click(pane, ROWS.index("R4"))
    rings = bells(pane)
    type_into(pane, "seven")
    app.run("step")                                         # a wrong value: Step waits
    assert rings == [1] and pane.editor is not None and app.machine.pc == 4
    press_key(pane.editor, "<Key-Escape>")
    app.run("step")
    assert app.machine.pc == 8


def test_a_click_on_another_tab_keeps_a_wrong_value_in_front(app, tmp_path, hidden_windows,
                                                             monkeypatch):
    """Tk's click on a tab gives the focus to the table of the new tab: the field is left."""
    loaded(app, tmp_path, PROGRAM)
    pane, side = app.registers, app.side
    double_click(pane, ROW["registers"])
    rings = bells(pane)
    type_into(pane, "abc")
    side.tk.call("ttk::notebook::ActivateTab", str(side), 1)      # a click on Coproc 10's tab
    focus_moved(pane, app.coproc10.table.body, monkeypatch)
    assert side.select() == str(pane) and hidden_windows.focus is pane.editor
    assert rings == [1] and pane.editor.get() == "abc"
    app.run("step")                                         # Step waits for a right value
    assert rings == [1, 1] and app.machine.pc == 0 and pane.editor.get() == "abc"
    assert side.select() == str(pane) and hidden_windows.focus is pane.editor
    type_into(pane, "7")
    side.tk.call("ttk::notebook::ActivateTab", str(side), 1)
    focus_moved(pane, app.coproc10.table.body, monkeypatch)
    assert app.machine.reg(1) == 7 and pane.editor is None and side.select() == str(app.coproc10)


def test_a_command_brings_a_wrong_value_back_into_view(app, tmp_path, hidden_windows):
    loaded(app, tmp_path, PROGRAM)
    pane = app.coproc10
    app.side.select(pane)
    table = made(pane.table)
    table.fit(10 * table.row_height)                        # ten rows on the screen
    double_click(pane, 2)
    rings = bells(pane)
    type_into(pane, "1.2.3")
    table.scroll_to(20)                                     # the field went up with its row
    app.side.select(app.registers)                          # and another tab is in front
    hidden_windows.focus = None
    app.run("step")
    assert rings == [1] and app.machine.pc == 0 and pane.editor.get() == "1.2.3"
    assert app.side.select() == str(pane) and hidden_windows.focus is pane.editor
    x0, y0, x1, y1 = table.cell_box(2, "value")             # S2 is on the screen again,
    assert table.body.coords(pane._editing[1])[1] == y0     # under its field


def gray(button):
    """A toolbar button that is gray (not available) now."""
    assert button.instate(["disabled"])
    return button


# A click elsewhere in the window applies the value, also on a control that
# takes no keyboard focus, and a wrong value rings the bell once a click. A
# table's own bindings end a press on its headings, and a gray toolbar button
# runs no command (which would apply the value first).
CLICKS = {
    "Run I/O's Clear": lambda app: click(run_io_clear(app)),
    "a Data Segment checkbox": lambda app: click(control(app.execute.data_segment,
                                                         "Hexadecimal Values")),
    "the next page": lambda app: click(app.execute.data_segment.next_button),
    "the run speed slider": lambda app: click(app.speed),
    "a Text Segment heading": lambda app: click(app.execute.text_segment.table.header),
    "a Data Segment heading": lambda app: click(app.execute.data_segment.table.header),
    "a Labels heading": lambda app: click(app.execute.labels.table.header),
    "the gray Backstep": lambda app: click(gray(app.buttons["backstep"])),
    "a Settings check item": lambda app: settings_item(app, "Values in Hexadecimal"),
}


@pytest.mark.parametrize("how", CLICKS)
def test_a_click_on_a_control_that_takes_no_focus_applies_the_value(app, tmp_path, monkeypatch,
                                                                     how):
    loaded(app, tmp_path, PROGRAM)
    app.setting_vars["show_labels"].set(True)
    app._setting_toggled("show_labels")
    pane = app.registers
    double_click(pane, ROW["registers"])
    focus_kept(pane, monkeypatch)
    type_into(pane, "7")
    CLICKS[how](app)
    assert app.machine.reg(1) == 7 and pane.editor is None and app.machine.pc == 0


@pytest.mark.parametrize("name", PANES)
def test_a_click_on_a_heading_of_the_fields_own_table_applies_the_value(app, tmp_path,
                                                                        monkeypatch, name):
    loaded(app, tmp_path, PROGRAM)
    pane = getattr(app, name)
    double_click(pane, ROW[name])
    focus_kept(pane, monkeypatch)
    type_into(pane, TYPED[name])
    click(pane.table.header)
    assert typed_value(app, name) == TYPED_BITS[name] and pane.editor is None


def test_a_wrong_value_and_a_click_on_clear_keep_the_field(app, tmp_path, hidden_windows,
                                                          monkeypatch):
    loaded(app, tmp_path, PROGRAM)
    pane = app.registers
    double_click(pane, ROW["registers"])
    focus_kept(pane, monkeypatch)
    rings = bells(pane)
    type_into(pane, "abc")
    app.messages.write_output("output\n")
    click(run_io_clear(app))
    assert rings == [1] and pane.editor.get() == "abc" and app.machine.reg(1) == 0
    assert hidden_windows.focus is pane.editor
    assert app.messages.run_io.get("1.0", "end-1c") == ""         # the click did clear it
    type_into(pane, "7")
    click(run_io_clear(app))
    assert app.machine.reg(1) == 7 and pane.editor is None
    assert hidden_windows.focus is pane.table.body          # as after Enter


@pytest.mark.parametrize("how", ["a Settings check item", "a Data Segment checkbox"])
def test_a_wrong_value_and_a_click_on_a_setting_keep_the_setting(app, tmp_path, monkeypatch,
                                                                 how):
    """Both change Values in Hexadecimal: the setting waits for a right value, as commands do."""
    loaded(app, tmp_path, PROGRAM)
    pane = app.registers
    double_click(pane, ROW["registers"])
    focus_kept(pane, monkeypatch)
    rings = bells(pane)
    type_into(pane, "abc")
    hexadecimal = app.settings.hex_values
    CLICKS[how](app)
    assert rings == [1] and pane.editor.get() == "abc"
    ticks = app.setting_vars["hex_values"].get(), app.execute.data_segment.hex_values.get()
    assert app.settings.hex_values == hexadecimal and ticks == (hexadecimal, hexadecimal)
    type_into(pane, "7")
    CLICKS[how](app)
    assert app.machine.reg(1) == 7 and app.settings.hex_values != hexadecimal


def test_a_wrong_value_rings_once_for_a_toolbar_button(app, tmp_path, monkeypatch):
    loaded(app, tmp_path, PROGRAM)
    pane = app.registers
    double_click(pane, ROW["registers"])
    focus_kept(pane, monkeypatch)
    rings = bells(pane)
    type_into(pane, "abc")
    click(app.buttons["step"])                              # its command applies the field
    assert rings == [1] and app.machine.pc == 0 and pane.editor.get() == "abc"
    click(gray(app.buttons["backstep"]))                    # the press does
    assert rings == [1, 1] and app.machine.pc == 0 and pane.editor.get() == "abc"


def test_the_close_button_of_a_file_tab_applies_the_value_first(app, tmp_path, monkeypatch):
    loaded(app, tmp_path, PROGRAM)
    open_source(app, tmp_path, "@ notes\n", "notes.s")     # closing it keeps the program
    pane = app.registers
    double_click(pane, ROW["registers"])
    focus_kept(pane, monkeypatch)
    rings = bells(pane)
    type_into(pane, "abc")
    tab = app.editor.current
    click_close_button(app.editor.notebook, 1)
    assert rings == [1] and pane.editor.get() == "abc" and tab in app.editor.tabs
    type_into(pane, "7")
    click_close_button(app.editor.notebook, 1)
    assert app.machine.reg(1) == 7 and pane.editor is None and tab not in app.editor.tabs


def test_the_close_button_of_the_programs_tab_applies_the_value_then_unloads(
        app, tmp_path, monkeypatch):
    loaded(app, tmp_path, PROGRAM)
    pane = app.registers
    double_click(pane, ROW["registers"])
    focus_kept(pane, monkeypatch)
    rings = bells(pane)
    type_into(pane, "abc")
    tab = app.editor.current
    click_close_button(app.editor.notebook, 0)
    assert rings == [1] and pane.editor.get() == "abc" and tab in app.editor.tabs
    type_into(pane, "7")
    unloaded_with = []
    close_program = app._close_program
    monkeypatch.setattr(app, "_close_program",
                        lambda: unloaded_with.append(app.machine.reg(1)) or close_program())
    click_close_button(app.editor.notebook, 0)
    assert unloaded_with == [7] and pane.editor is None and tab not in app.editor.tabs
    assert app.machine is None and app.registers.values()[1] == 0


def test_a_wrong_value_rings_once_for_a_click_that_takes_the_focus(app, tmp_path, monkeypatch):
    loaded(app, tmp_path, PROGRAM)
    pane = app.registers
    double_click(pane, ROW["registers"])
    rings = bells(pane)
    type_into(pane, "abc")
    run_io = app.messages.run_io
    monkeypatch.setattr(pane, "_focus_path", lambda: str(run_io))  # the press focused Run I/O
    click(run_io)
    focus_moved(pane, run_io, monkeypatch)                  # the field hears of it after the press
    assert rings == [1] and pane.editor.get() == "abc"


def test_a_click_in_the_field_on_a_scroll_bar_or_on_a_divider_applies_nothing(app, tmp_path,
                                                                               monkeypatch):
    """The field moves with its row, with the scroll bars as with the mouse wheel."""
    loaded(app, tmp_path, PROGRAM)
    pane = app.registers
    double_click(pane, ROW["registers"])
    focus_kept(pane, monkeypatch)
    type_into(pane, "7")
    click(pane.editor)
    click(pane.table.vscroll)
    click(next(w for w in descendants(run_io_page(app)) if w.winfo_class() == "TScrollbar"))
    click(app.main_split)
    assert pane.editor is not None and app.machine.reg(1) == 0


def test_the_edit_commands_act_on_the_field_without_applying_it(app, tmp_path, monkeypatch):
    loaded(app, tmp_path, PROGRAM)
    pane = app.registers
    double_click(pane, ROW["registers"])
    monkeypatch.setattr(app.root, "focus_get", lambda: pane.editor)
    app.run("select_all")
    assert pane.editor is not None and app.machine.reg(1) == 0


@pytest.mark.parametrize("state", ["ready", "paused", "finished", "stopped"])
def test_values_can_be_changed_whenever_no_program_runs(app, tmp_path, state):
    loaded(app, tmp_path, PROGRAM if state in ("ready", "finished") else LOOP)
    if state == "finished":
        go_to_end(app)
    elif state in ("paused", "stopped"):
        app.run("go")
        app.run("pause" if state == "paused" else "stop")
    for name in PANES:
        pane = getattr(app, name)
        double_click(pane, ROW[name])
        assert pane.editor is not None, name
        type_into(pane, TYPED[name])
        press_key(pane.editor, "<Return>")
        assert typed_value(app, name) == TYPED_BITS[name], name


def test_no_field_and_no_message_while_a_program_runs_or_waits(app, tmp_path):
    """Run I/O stays in front, where the input is typed."""
    loaded(app, tmp_path, LOOP)
    app.run("go")
    assert app.runner.state is State.RUNNING
    messages = app.messages.messages.get("1.0", "end")
    double_click(app.registers, ROW["registers"])
    assert app.registers.editor is None
    assert app.messages.messages.get("1.0", "end") == messages
    assert app.messages.tab("current", "text") == "Run I/O"
    app.run("stop")
    loaded(app, tmp_path, READ_INT, "read.s")
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    messages = app.messages.messages.get("1.0", "end")
    for name in PANES:
        double_click(getattr(app, name), ROW[name])
        assert getattr(app, name).editor is None
    assert app.messages.messages.get("1.0", "end") == messages
    assert app.messages.tab("current", "text") == "Run I/O"


@pytest.mark.parametrize("name", PANES)
def test_before_assembling_a_double_click_says_why(app, name):
    pane = getattr(app, name)
    app.messages.show_run_io()
    double_click(pane, ROW[name])
    assert pane.editor is None
    assert app.messages.messages.get("1.0", "end-1c") == NOT_ASSEMBLED + "\n"
    assert app.messages.index("current") == 0               # ARES Messages in front
    pane.table.select(ROW[name])
    press_key(pane.table.body, "<Key-F2>")
    assert app.messages.messages.get("1.0", "end-1c") == 2 * (NOT_ASSEMBLED + "\n")


def test_before_assembling_a_flag_double_click_says_why_but_the_cpsr_value_does_not(app):
    table = made(app.registers.table)
    x0, y0, x1, y1 = table.mark_box(CPSR_ROW, "flags", 1)  # Z
    mouse(table, (x0 + x1) // 2, (y0 + y1) // 2,
          "<ButtonPress-1>", "<ButtonRelease-1>", "<ButtonPress-1>", "<ButtonRelease-1>")
    assert app.messages.messages.get("1.0", "end-1c") == NOT_ASSEMBLED + "\n"
    double_click(app.registers, CPSR_ROW)                   # changed only through its flags
    assert app.messages.messages.get("1.0", "end-1c") == NOT_ASSEMBLED + "\n"
