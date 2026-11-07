# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The window stays quick: work that grew with the size of the window or the text.

The window's parts must not do again, on every click, key or change of size,
work that belongs to start-up (pictures) or that grows with what they hold
(the text of the message panes). Hidden windows are never drawn, so these
tests count the work instead of timing the screen.
"""

import re
import time

import pytest
from conftest import PROGRAMS, fixed_screen, lay_out, pump
from test_autohide import message_pane
from test_gui_editing import click
from test_gui_run import loaded
from test_style import make_root  # noqa: F401  (a fixture: a root at a display scale)

from ares.gui import icons, style
from ares.gui.messages import RUN_IO
from ares.gui.widgets import px

KEYSYMS = {" ": "space", "@": "at", ",": "comma", "#": "numbersign"}


def tcl_word(text):
    """text as one Tcl word, as Tk substitutes %A in a binding."""
    if not text:
        return "{}"
    return "".join("\\" + c if c in ' {}[]$\\";' else c for c in text)


def type_text(widget, text):
    """Type text as Tk runs a key press: each bind tag's binding for the key, until one breaks.

    A hidden window never has the keyboard focus, so a generated key event
    would not reach it.
    """
    for char in text:
        keysym = KEYSYMS.get(char, char)
        fields = {"%W": str(widget), "%A": tcl_word(char), "%K": keysym, "%%": "%"}
        for tag in widget.bindtags():
            script = (widget.tk.call("bind", tag, f"<KeyPress-{keysym}>")
                      or widget.tk.call("bind", tag, "<KeyPress>"))
            if not script:
                continue
            script = re.sub(r"%.", lambda m: fields.get(m.group(), "0"), script)
            stopped = widget.tk.eval("set ::typed_stopped 1\nforeach _ {1} {\n" + script
                                     + "\nset ::typed_stopped 0\n}\nset ::typed_stopped")
            if stopped == "1":
                break


def pictures(root):
    return set(root.tk.splitlist(root.tk.call("image", "names")))


def activate_tab(notebook, index):
    """Tk's own response to a click on a notebook's tab."""
    notebook.tk.call("ttk::notebook::ActivateTab", str(notebook), index)


def test_no_pictures_are_made_after_start_up(app, tmp_path):
    """Every picture of the look and the icons is drawn once, at start-up, at the display's
    size: clicks, keys, tab switches, runs and settings only show them."""
    made = pictures(app.root)
    loaded(app, tmp_path, (PROGRAMS / "circle.s").read_text(), "circle.s")
    for notebook in (app.views, app.side, app.messages):
        for index in list(range(len(notebook.tabs()))) * 2:
            activate_tab(notebook, index)
            pump(app.root)
    for name in ("step", "step", "backstep", "reset", "go", "stop", "reset"):
        click(app.buttons[name])
        pump(app.root)
    activate_tab(app.views, 0)
    type_text(app.editor.current.text, " @ typed")
    pump(app.root)
    for name in ("hex_values", "show_labels", "hex_values", "show_labels"):
        app.setting_vars[name].set(not app.setting_vars[name].get())
        app._setting_toggled(name)
        pump(app.root)
    assert pictures(app.root) == made


def test_a_setting_of_the_tables_leaves_the_editor_as_it_is(app, monkeypatch):
    """Configured again, even unchanged, a text's tab stops or font have Tk lay out every
    line of it: a setting of the tables touches neither."""
    tab = app.editor.new_file()
    tab.text.insert("1.0", "        MOV     R0, #1\n" * 2000)
    configured = []
    original = tab.text.configure
    monkeypatch.setattr(tab.text, "configure",
                        lambda *args, **kwargs: configured.append(kwargs) or original(
                            *args, **kwargs))
    for font in (app.editor_font, app.editor_bold):
        monkeypatch.setattr(font, "configure", lambda **kwargs: configured.append(kwargs))
    for name in ("hex_values", "hex_addresses", "hex_values", "hex_addresses"):
        app.setting_vars[name].set(not app.setting_vars[name].get())
        app._setting_toggled(name)
    assert configured == []
    app.settings.tab_size = 8                   # an editor setting changes the editor
    app.apply_settings()
    assert any("tabs" in options for options in configured)


def write_cost(write):
    """Seconds of the quickest of a few writes."""
    times = []
    for _ in range(7):
        start = time.perf_counter()
        write()
        times.append(time.perf_counter() - start)
    return min(times)


@pytest.mark.parametrize("pane_name", ["messages", RUN_IO])
def test_a_write_costs_the_same_whatever_the_pane_holds(area, pane_name):
    """A write measures what it adds and scrolls to the end: neither grows with the text."""
    frame, pane, font = message_pane(area, 700, 200)
    if pane_name == RUN_IO:
        pane.show_run_io()
        text = pane.run_io

        def write():
            pane.write_output("abc\n")
            pump(frame)

        def fill(count):
            pane.write_output("".join(f"output line {k}\n" for k in range(count)))
    else:
        text = pane.messages

        def write():
            pane.write_message("abc")
            pump(frame)

        def fill(count):
            text.write("".join(f"message {k}\n" for k in range(count)))
            pane._changed(text)
    pump(frame)
    fill(1000)
    pump(frame)
    small = write_cost(write)
    fill(49000)                 # Run I/O keeps the newest million characters: these fit
    pump(frame)
    large = write_cost(write)
    assert large < 3 * small + 0.002, (small, large)


def counted(monkeypatch, cls, name, counts):
    """Count the calls of a method of a class."""
    original = getattr(cls, name)

    def wrapper(*args, **kwargs):
        counts[name] += 1
        return original(*args, **kwargs)
    monkeypatch.setattr(cls, name, wrapper)


def count_handlers(monkeypatch):
    """The calls of the handlers that resize, fill and draw the tables, and decide bars."""
    from collections import Counter

    from ares.gui import widgets
    from ares.gui.execute import ExecutePane
    from ares.gui.table import Table
    counts = Counter()
    for cls, name in ((Table, "_configured"), (Table, "_layout"), (Table, "_set_bars"),
                        (Table, "refresh"), (widgets.HidingBars, "decide"),
                        (ExecutePane, "place_dividers")):
        counted(monkeypatch, cls, name, counts)
    return counts


@pytest.mark.parametrize("pane", ["text_segment", "data_segment", "labels", "registers"])
def test_a_new_size_of_a_table_settles_in_a_few_steps(make_app, tmp_path, monkeypatch, pane):
    """A table's <Configure> fits its rows and columns and decides its bars, which may change
    its size again: a few rounds, never a chain of them (each round redraws the table, and a
    divider moved by it redraws the panes around)."""
    fixed_screen(monkeypatch)
    app = make_app()
    app.setting_vars["show_labels"].set(True)
    app._setting_toggled("show_labels")
    loaded(app, tmp_path, (PROGRAMS / "circle.s").read_text(), "circle.s")
    assert lay_out(app.root)
    table = getattr(app.execute, pane, None) or getattr(app, pane)
    table = table.table
    counts = count_handlers(monkeypatch)
    width, height = table.body.winfo_width(), table.body.winfo_height()
    row = table.row_height
    for new_width, new_height in ((width - 300, height), (width, height - 3 * row),
                                  (width + 200, height + 5 * row), (40, 3 * row),
                                  (width, height)):
        counts.clear()
        table.body.event_generate("<Configure>", width=new_width, height=new_height)
        assert pump(app.root, 3000), (new_width, new_height)
        assert counts["_configured"] <= 3, (counts, new_width, new_height)
        assert counts["_layout"] <= 3 and counts["refresh"] <= 6, counts
        assert counts["place_dividers"] <= 3, counts


def tab_point(notebook, index):
    """A point on a notebook's tab, on its strip."""
    box = notebook.boxes()[index]
    return (box.x + box.right) // 2, (box.top + box.bottom) // 2


def press_tab(notebook, index):
    x, y = tab_point(notebook, index)
    notebook.strip.winfo_id()
    notebook.strip.event_generate("<ButtonPress-1>", x=x, y=y)
    notebook.strip.event_generate("<ButtonRelease-1>", x=x, y=y)


def last_focus(app):
    return str(app.root.tk.call("focus", "-lastfor", app.views._w))


@pytest.fixture
def window(make_app, tmp_path, monkeypatch):
    """A laid out window with a program assembled, the Edit tab on top."""
    fixed_screen(monkeypatch)
    app = make_app()
    loaded(app, tmp_path, (PROGRAMS / "circle.s").read_text(), "circle.s")
    assert lay_out(app.root)
    app.views.select(0)
    assert pump(app.root)
    return app


def test_a_press_on_the_views_tab_draws_nothing_until_the_switch_is_done(mapped_window):
    """Tk's binding of notebooks draws all that is pending before it gives the page the keyboard
    focus, and the Expose events of the switch then draw the large panes again, which takes as
    long as all the rest. Drawn once, the switch takes two thirds of the time. Only the page's
    focus may ask for what is pending, when the idle jobs have begun: pack and grid map its
    tables in them."""
    app = mapped_window
    tk = app.root.tk
    tk.eval("set ::perf_updates 0")
    tk.eval("trace add execution update enter {apply {{args} {incr ::perf_updates}}}")
    try:
        press_tab(app.views, 1)
        assert app.views.index("current") == 1
        assert tk.eval("set ::perf_updates") == "0"
        assert pump(app.root)
        assert tk.eval("set ::perf_updates") == "1"
    finally:
        tk.eval("trace remove execution update enter {apply {{args} {incr ::perf_updates}}}")


@pytest.fixture
def mapped_window(make_mapped_app, tmp_path):
    """A window that knows the keyboard focus, with a program assembled, the Edit tab on top."""
    app = make_mapped_app()
    loaded(app, tmp_path, (PROGRAMS / "circle.s").read_text(), "circle.s")
    app.views.select(0)
    assert pump(app.root)
    return app


def test_the_page_of_a_pressed_views_tab_gets_the_keyboard_focus(mapped_window):
    app = mapped_window
    press_tab(app.views, 1)
    assert pump(app.root)
    assert last_focus(app) == str(app.execute.text_segment.table.body)
    assert app.execute.text_segment.active
    press_tab(app.views, 0)
    assert pump(app.root)
    assert last_focus(app) == str(app.root.tk.call("ttk::focusFirst", app.views.select()))


def test_the_page_shown_for_the_first_time_gets_the_keyboard_focus(make_mapped_app):
    """Its panes are placed as it comes to the front, in the idle jobs after the press."""
    app = make_mapped_app()
    assert app.views.index("current") == 0
    press_tab(app.views, 1)
    assert pump(app.root)
    assert last_focus(app) == str(app.execute.text_segment.table.body)


def test_a_press_beside_the_tabs_changes_nothing(window):
    app = window
    views = app.views
    x, y = views.winfo_width() - 5, tab_point(views, 0)[1]
    assert views.tab_at(x, y) is None
    views.strip.event_generate("<ButtonPress-1>", x=x, y=y)
    views.strip.event_generate("<ButtonRelease-1>", x=x, y=y)
    assert pump(app.root)
    assert views.index("current") == 0


def test_a_press_on_the_tab_on_top_changes_nothing(window):
    app = window
    calls = []
    app._focus_view = lambda: calls.append(1)
    press_tab(app.views, 0)
    assert pump(app.root)
    assert calls == [] and app.views.index("current") == 0


def test_the_notebook_keeps_the_keyboard_focus_it_has(mapped_window, monkeypatch):
    """As in Tk's binding: with the focus on the notebook the arrow keys go on changing tabs."""
    app = mapped_window
    views = app.views
    views.focus_force()
    assert pump(app.root)
    if str(views.tk.call("focus")) != str(views):
        pytest.skip("this window cannot have the keyboard focus here")
    press_tab(views, 1)
    assert pump(app.root)
    assert views.index("current") == 1
    assert last_focus(app) == str(views)


def test_the_page_leaves_the_keyboard_focus_to_a_register_field_that_stays_open(mapped_window):
    """A field left open has a wrong value. Scrolled out of view it gets the focus only when it
    is mapped again, so until then the notebook still has it, and the page would take it."""
    app = mapped_window
    views = app.views
    views.select(1)
    assert pump(app.root)
    app.registers.edit(1)
    views.focus_set()                   # where Tk's binding leaves the focus
    assert pump(app.root)
    app._focus_view()
    assert pump(app.root)
    assert last_focus(app) == str(views)


def test_a_wrong_register_value_keeps_its_field_when_a_tab_is_pressed(mapped_window):
    """The bell rings once, and the field keeps the keyboard focus."""
    app = mapped_window
    views = app.views
    views.select(1)
    assert pump(app.root)
    pane = app.registers
    pane.edit(1)
    rings = []
    pane.editor.bell = lambda: rings.append(1)
    pane.editor.delete(0, "end")
    pane.editor.insert(0, "not a number")
    assert pump(app.root)
    press_tab(views, 0)
    pane.commit()                       # the focus left it, as on the screen
    assert pump(app.root)
    assert rings == [1]
    assert pane.editor is not None
    assert last_focus(app) == str(pane.editor)


def test_a_scroll_bar_that_comes_and_goes_settles_in_a_few_steps(make_app, tmp_path,
                                                                  monkeypatch):
    """Rows that no longer fit bring the vertical bar, which narrows the rows' room: decided
    once, with the horizontal bar, not again and again."""
    fixed_screen(monkeypatch)
    app = make_app()
    loaded(app, tmp_path, (PROGRAMS / "circle.s").read_text(), "circle.s")
    assert lay_out(app.root)
    table = app.execute.text_segment.table
    counts = count_handlers(monkeypatch)
    page, row, count = table.page, table.row, table.count
    for rows in (page + 5, max(1, page - 2), page + 1, page, 500, 3):
        counts.clear()
        table.set_rows(rows, lambda index: row(index % count))
        assert pump(app.root, 3000), rows
        # A round: the rows refresh (and decide the bars), the bar's coming resizes the rows'
        # room once (and they decide again).
        assert counts["_set_bars"] <= 8 and counts["_configured"] <= 3, (rows, counts)


@pytest.mark.serial
def test_the_theme_is_drawn_quickly(make_root):
    """Drawing every picture of the look at 300 % takes a moment, once per Tk root."""
    root = make_root(3.0)
    start = time.perf_counter()
    style.apply(root)
    assert time.perf_counter() - start < 0.5


@pytest.mark.serial
def test_the_icons_are_drawn_quickly(make_root):
    """All the icons at 300 %, in colour and gray, are drawn in well under a second."""
    root = make_root(3.0)
    start = time.perf_counter()
    for name in icons.TOOLBAR:
        for disabled in (False, True):
            icons.photo(root, name, px(root, 24), disabled=disabled)
    for name in ("close", "close_active", "page_previous", "page_next", "message_error",
                 "message_information", "message_warning", "message_question"):
        icons.photo(root, name, px(root, 32))
    icons.window_photos(root)
    assert time.perf_counter() - start < 1.0
