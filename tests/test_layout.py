# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Scroll bars that come and go: the window settles and its dividers stay where they are.

The windows stay hidden but are laid out as on the screen (conftest.lay_out):
every widget has its native window, so Tk sends <Configure> events and
redraws the texts. The event loop then runs a bounded number of events,
which must be enough for it to go idle: a layout that switched a scroll bar
on and off for ever would keep it busy, and ARES would hang in the next
update_idletasks() (every tooltip calls it).
"""

import time
from tkinter import font as tkfont
from tkinter import ttk

import pytest
from conftest import PROGRAMS, fixed_screen, lay_out, native, new_root, pump

from ares.gui import app as app_module
from ares.gui import execute as execute_module
from ares.gui.app import PANE_FONT_SIZE
from ares.gui.execute import LabelsPane
from ares.gui.table import PAD, Column, Row, Table, column_width
from ares.gui.widgets import keep_size, px, tip_window
from ares.program import Label
from ares.runner import State
from ares.settings import DEFAULT_FONT, Settings

LONG_OUTPUT = """\
        .global _start
_start: LDR     R0, =line
        SVC     #4              @ a line much wider than Run I/O
        SVC     #10
        .data
line:   .asciz  "{}\\n"
""".format("x" * 300)


def rows_program(rows):
    """A program whose Text Segment has the given number of rows."""
    return ".global _start\n_start:\n" + "        MOV R0, #1\n" * (rows - 1) + "        SVC #10\n"


def wait_until(root, done, limit=30.0):
    """Let the window work until done(), a few events at a time, within the time limit."""
    deadline = time.monotonic() + limit
    while not done():
        assert time.monotonic() < deadline, "the window did not get there in time"
        if pump(root, 100):
            time.sleep(0.002)


def assemble(app):
    app.run("assemble")
    wait_until(app.root, lambda: not app.assembling)


def replace_and_assemble(app, source):
    """Put source in place of the text of the file on top, and assemble it."""
    text = app.editor.current.text
    text.delete("1.0", "end")
    text.insert("1.0", source)
    assemble(app)


def go(app):
    app.run("go")
    wait_until(app.root, lambda: app.runner.state is not State.RUNNING)


def settles(app):
    """True when the window goes idle (widgets made since get their native windows first)."""
    native(app.root)
    return pump(app.root)


def dividers(app):
    """Where the dividers are: main, Edit and Execute over the messages, Text over Data, Labels."""
    execute = app.execute
    positions = [app.main_split.sashpos(0), app.left_split.sashpos(0), execute.segments.sashpos(0)]
    if execute.labels_shown:
        positions.append(execute.sashpos(0))
    return positions


def drag(divider, position):
    """Move a divider as the mouse does (Tk's own drag binding sets its position so)."""
    divider.sashpos(0, position)
    assert pump(divider)


def bars(table):
    """(vertical, horizontal): which of a table's scroll bars are in the grid."""
    return bool(table.vscroll.winfo_manager()), bool(table.hscroll.winfo_manager())


# The whole window ---------------------------------------------------------------------

@pytest.mark.parametrize("split_execute", [None, 0.3, 0.65])
def test_programs_of_every_length_settle_after_assemble_and_go(make_app, tmp_path, monkeypatch,
                                                              split_execute):
    """A scroll bar coming or going must not change the size its table asks for: the divided
    window would place its dividers anew, and where that just lets the rows fit, the bar would
    leave, the divider go back, and so on without end (9 rows at the default size)."""
    if split_execute is not None:
        monkeypatch.setattr(execute_module, "SPLIT_SEGMENTS", split_execute)
    path = tmp_path / "rows.s"
    path.write_text(rows_program(3), encoding="utf-8")
    fixed_screen(monkeypatch)
    app = make_app(files=[path])
    assert lay_out(app.root)
    sources = [("leaf.s", (PROGRAMS / "leaf.s").read_text())]
    sources += [(f"{rows} rows", rows_program(rows)) for rows in range(3, 45)]
    for name, source in sources:
        replace_and_assemble(app, source)
        assert app.runner is not None, name
        assert settles(app), f"{name}: the window does not settle after Assemble"
        go(app)
        assert settles(app), f"{name}: the window does not settle after Go"
        tip_window(app.buttons["go"], "Go", 0, 0).destroy()     # update_idletasks() returns


@pytest.mark.parametrize("dragged", [False, True], ids=["as placed", "dragged"])
def test_the_dividers_stay_where_they_are(make_app, tmp_path, monkeypatch, dragged):
    """Assemble, Go, a Run I/O line wider than the pane and Clear move no divider."""
    for module, name, share in ((app_module, "SPLIT_MAIN", 0.7), (app_module, "SPLIT_LEFT", 0.6),
                                (execute_module, "SPLIT_SEGMENTS", 0.4),
                                (execute_module, "SPLIT_LABELS", 0.7)):
        monkeypatch.setattr(module, name, share)
    path = tmp_path / "long.s"
    path.write_text(LONG_OUTPUT, encoding="utf-8")
    fixed_screen(monkeypatch)
    app = make_app(files=[path])
    # The Labels shown before the window has its size, as at a start with them on (a hidden
    # window started with them keeps the size it had before its geometry was given).
    app.setting_vars["show_labels"].set(True)
    app._setting_toggled("show_labels")
    assert lay_out(app.root)
    execute = app.execute
    width, height = app.main_split.winfo_width(), app.left_split.winfo_height()
    assert dividers(app)[:2] == [round(0.7 * width), round(0.6 * height)]
    assemble(app)                       # the Execute tab shows: its dividers are placed
    assert settles(app)
    assert execute.segments.winfo_width() == execute.sashpos(0)
    assert dividers(app) == [round(0.7 * width), round(0.6 * height),
                             round(0.4 * execute.segments.winfo_height()),
                             round(0.7 * execute.winfo_width())]
    if dragged:
        drag(app.main_split, round(0.6 * width))
        drag(app.left_split, round(0.55 * height))
        drag(execute.segments, round(0.3 * execute.segments.winfo_height()))
        drag(execute, round(0.65 * execute.winfo_width()))
        assert dividers(app) == [round(0.6 * width), round(0.55 * height),
                                 round(0.3 * execute.segments.winfo_height()),
                                 round(0.65 * execute.winfo_width())]
    expected = dividers(app)
    messages = app.messages
    steps = (("Assemble", lambda: assemble(app)),
             ("Go", lambda: go(app)),
             ("Clear Run I/O", lambda: messages.clear(messages.run_io)),
             ("Clear ARES Messages", lambda: messages.clear(messages.messages)),
             ("Assemble 60 rows", lambda: replace_and_assemble(app, rows_program(60))),
             ("Assemble 1 row", lambda: replace_and_assemble(app, rows_program(1))),
             ("Assemble again", lambda: replace_and_assemble(app, LONG_OUTPUT)),
             ("Go again", lambda: go(app)))
    vertical_bars = set()               # of the Text Segment: it came and went
    for name, step in steps:
        step()
        assert settles(app), name
        assert dividers(app) == expected, name
        vertical_bars.add(bars(execute.text_segment.table)[0])
        if name.startswith("Go"):           # the 300 characters did not fit: a bar below them
            xscroll = messages.run_io.master.grid_slaves(row=1, column=1)
            assert len(messages.run_io.get("1.0", "1.end")) == 300 and xscroll, name
    assert vertical_bars == {False, True}


# Tables in divided windows -----------------------------------------------------------

def test_a_table_in_a_divided_window_asks_for_one_size_whatever_its_bars(tk_root):
    """The dividers alone decide its size; elsewhere a table asks for what it holds."""
    font = tkfont.Font(root=tk_root, family=DEFAULT_FONT, size=PANE_FONT_SIZE)
    divided = ttk.PanedWindow(tk_root, orient="vertical")
    inside = Table(divided, [Column("a", "A", 50), Column("b", "B", 80, stretch=True)], font)
    divided.add(inside)
    alone = Table(tk_root, [Column("a", "A", 50), Column("b", "B", 80, stretch=True)], font)
    try:
        assert keep_size(ttk.Frame(inside)) and not keep_size(ttk.Frame(tk_root))
        sizes = []
        for count, width in ((100, 10), (0, 1000), (100, 10)):
            for table in (inside, alone):
                table.set_rows(count, lambda i: Row(("a", "b")))
                table.fill(width)
                table.fit(5 * table.row_height)
            tk_root.update_idletasks()
            assert bars(inside) == bars(alone) == (bool(count), bool(count))
            assert (inside.winfo_reqwidth(), inside.winfo_reqheight()) == (1, 1)
            sizes.append((alone.winfo_reqwidth(), alone.winfo_reqheight()))
        with_bars, without, again = sizes
        assert with_bars == again and without[0] < with_bars[0] and without[1] < with_bars[1]
    finally:
        divided.destroy()
        alone.destroy()


def test_a_divider_stays_when_a_scroll_bar_comes_or_goes():
    root = new_root()
    try:
        root.geometry("600x500")
        root.winfo_id()
        root.update()
        font = tkfont.Font(root=root, family=DEFAULT_FONT, size=PANE_FONT_SIZE)
        divided = ttk.PanedWindow(root, orient="vertical")
        divided.pack(fill="both", expand=True)
        tables = [Table(divided, [Column("a", "A", 60), Column("b", "B", 60, stretch=True)], font)
                  for _ in range(2)]
        for table in tables:
            divided.add(table, weight=1)
        assert lay_out(root)
        drag(divided, 150)
        for count in (2, 100, 2, 100):
            for table in tables:
                table.set_rows(count, lambda i: Row(("a", "b")))
            assert pump(root)
            assert bars(tables[0]) == (count == 100, False)
            assert divided.sashpos(0) == 150
    finally:
        root.destroy()


# A table in an area of fixed size -----------------------------------------------------

def resize_area(frame, width, height):
    frame.configure(width=width, height=height)
    assert lay_out(frame.winfo_toplevel())


def four_columns(area):
    """A table of four columns (the last stretches) and no rows, filling an area of 500 x about
    300 pixels: its rows fit with 2 pixels to spare, fewer than the horizontal bar takes."""
    frame = area(500, 300)
    font = tkfont.Font(root=frame, family=DEFAULT_FONT, size=PANE_FONT_SIZE)
    table = Table(frame, [Column("a", "A", 60), Column("b", "B", 60), Column("c", "C", 60),
                          Column("d", "D", 60, stretch=True)], font)
    table.pack(fill="both", expand=True)
    table.set_rows(0, None)
    assert lay_out(frame.winfo_toplevel())
    assert bars(table) == (False, False)
    resize_area(frame, 500, 300 - table.body.winfo_height() % table.row_height + 2)
    assert table.body.winfo_height() % table.row_height == 2 < table.hscroll.winfo_reqheight()
    return frame, table


def test_a_table_whose_bars_would_need_each_other_settles(area):
    """Each bar decided alone from the body's size would not settle: when the rows fit only
    without the horizontal bar and the columns only without the vertical one, the two would
    switch each other on and off for ever. Decided at once from the room of both, neither is
    needed."""
    frame, table = four_columns(area)
    across = table.vscroll.winfo_reqwidth()
    width, height = table.body.winfo_width(), table.body.winfo_height()
    rows = height // table.row_height
    for start in ((60, None), (rows, {"d": width})):       # vertical bar only, then both
        table.set_rows(start[0], lambda i: Row((str(i), "b", "c", "d")), start[1])
        assert pump(frame)
        assert bars(table) == (True, start[1] is not None)
        # New contents: rows that fit only without the horizontal bar, columns that fit
        # only without the vertical one.
        table.set_rows(rows, lambda i: Row((str(i), "b", "c", "d")),
                       {"d": width - 180 - across // 2})
        assert pump(frame, 3000), "the scroll bars switch each other on and off"
        assert bars(table) == (False, False)
        assert (table.body.winfo_width(), table.body.winfo_height()) == (width, height)


def test_a_table_shows_both_bars_when_one_makes_the_other_needed(area):
    frame, table = four_columns(area)
    width, height = table.body.winfo_width(), table.body.winfo_height()
    rows = height // table.row_height
    table.set_rows(rows, lambda i: Row((str(i), "b", "c", "d")), {"d": width})
    assert pump(frame)                  # the columns do not fit, the rows not above their bar
    assert bars(table) == (True, True)
    table.set_rows(rows, lambda i: Row((str(i), "b", "c", "d")), {"d": width - 180})
    assert pump(frame)
    assert bars(table) == (False, False) and table.body.winfo_height() == height


# Columns of the Execute tab's tables ---------------------------------------------------

def test_an_empty_text_segment_takes_its_first_widths_again(make_app, tmp_path, monkeypatch):
    """After a program with a long source line, an assemble that fails does not leave the empty
    Text Segment with that line's width, and a scroll bar under no row."""
    fixed_screen(monkeypatch)
    app = make_app()
    segment = app.execute.text_segment
    first = [column.base for column in segment.table.columns]
    path = tmp_path / "long.s"
    source = rows_program(2).replace("#1", "#1    @ " + "x" * 300)
    path.write_text(source, encoding="utf-8")
    text = app.open_path(path).text
    assert lay_out(app.root)
    assemble(app)
    assert settles(app)
    assert segment.table.columns[4].base > first[4] and bars(segment.table) == (False, True)
    text.insert("end", "        MOVX R0, #1\n")
    assemble(app)
    assert app.runner is None and segment.table.count == 0
    assert [column.base for column in segment.table.columns] == first
    app.views.select(app.execute)
    assert settles(app)
    assert bars(segment.table) == (False, False)


def test_the_label_column_needs_the_widest_label_or_its_heading(tk_root):
    """It needs no more than that, so a narrow Labels pane shows no scroll bar its labels do
    not need."""
    font = tkfont.Font(root=tk_root, family=DEFAULT_FONT, size=PANE_FONT_SIZE)
    pane = LabelsPane(tk_root, Settings(), font)
    try:
        table = pane.table
        heading = column_width(pane, font, 0, "Label")
        assert table.columns[0].base == heading             # no labels: only the heading
        pane.load([Label(name, 0x1000 + 4 * k, ".text", False) for k, name in
                   enumerate(("_start", "ask", "area", "pi_single", "pi_double"))])
        widest = pane.name_font.measure("pi_double")    # names in the plain interface font
        assert table.columns[0].base == widest + 2 * px(pane, PAD) + 2
        need = table.columns[0].base + table.columns[1].base
        table.fill(need)
        assert bars(table) == (False, False)
        table.fill(need - 1)
        assert bars(table) == (False, True)
        pane.clear()
        assert table.columns[0].base == heading
        pane.load([Label("a_label_of_21_letters", 0x1000, ".text", False)])
        assert table.columns[0].base == (pane.name_font.measure("a_label_of_21_letters")
                                         + 2 * px(pane, PAD) + 2)
    finally:
        pane.destroy()
