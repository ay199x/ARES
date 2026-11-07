# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The sizes of the Registers, Coproc 10 and Coproc 11 tables, which are their own.

Their rows, headings and text are larger than those of the Execute tab's tables, in the same
font families, and all three tables have the same sizes.
"""

from tkinter import font as tkfont
from types import SimpleNamespace

import pytest
from conftest import fixed_screen, lay_out, pump
from test_gui_assemble import assemble, open_source

from ares.gui import registers, table as table_module, widgets
from ares.gui.app import App
from ares.gui.table import Column, Table, column_width
from ares.gui.widgets import px

PROGRAM = """\
        .global _start
_start: MOV     R1, #5
        MOV     R2, #6
        SVC     #10
"""
WINDOW = (1707, 889)            # the inside of the maximized window, in design pixels
ROWS = {"registers": 18, "coproc10": 33, "coproc11": 33}


def panes(app):
    return app.registers, app.coproc10, app.coproc11


def row_box(table, index):
    """(top, bottom) of a row on the screen, in the body's canvas."""
    top = (index - table.top) * table.row_height
    return top, top + table.row_height


def show_all_rows(app, pane):
    """Put a tab in front; at the maximized window's size all its rows are on the screen."""
    app.side.select(pane)
    assert pump(app.root)
    assert pane.table.page >= pane.table.count


@pytest.fixture
def at_225(tk_root, monkeypatch):
    """The ARES windows the test starts are shown at 225 %."""
    monkeypatch.setattr(widgets, "is_aqua", lambda widget: False)
    original = tk_root.tk.call("tk", "scaling")
    tk_root.tk.call("tk", "scaling", 2.25 * 96 / 72)
    yield
    tk_root.tk.call("tk", "scaling", original)


@pytest.fixture
def maximized(at_225, tk_root, make_app, tmp_path, monkeypatch):
    """start(): a hidden ARES window with the size of the maximized window on a 4K screen."""
    fixed_screen(monkeypatch)

    def start(height=WINDOW[1]):
        size = f"{px(tk_root, WINDOW[0])}x{px(tk_root, height)}+0+0"
        monkeypatch.setattr(App, "_start_geometry", lambda self: size)
        app = make_app()
        assert lay_out(app.root)
        return app
    return start


# One size for the three tables --------------------------------------------------------------

def test_the_three_tables_have_the_same_row_height_and_heading_height(app):
    root = app.root
    for pane in panes(app):
        table = pane.table
        assert table.row_height == px(root, registers.ROW_HEIGHT)
        assert int(table.header.cget("height")) == px(root, registers.ROW_HEIGHT)


def test_the_three_tables_share_their_fonts(app):
    assert {id(pane.table.font) for pane in panes(app)} == {id(app.register_font)}
    assert {id(pane.table.heading_font) for pane in panes(app)} == {id(app.register_heading_font)}


def test_the_register_fonts_keep_the_families_and_change_only_their_sizes(app):
    root = app.root
    heading = tkfont.nametofont("TkHeadingFont", root=root)
    assert app.register_font.actual("family") == app.pane_font.actual("family")
    assert app.register_heading_font.actual("family") == heading.actual("family")
    for font, like in ((app.register_font, app.pane_font),
                       (app.register_heading_font, heading)):
        for option in ("weight", "slant", "underline", "overstrike"):
            assert font.actual(option) == like.actual(option)
    assert app.register_font.cget("size") == -px(root, registers.TEXT_SIZE)
    assert app.register_heading_font.cget("size") == -px(root, registers.HEADING_SIZE)


def test_at_225_percent_the_register_tables_have_their_sizes(at_225, make_app):
    """Rows and headings of 47 pixels; in Courier New, "0x00000000" is 190 pixels wide."""
    app = make_app()
    for pane in panes(app):
        assert pane.table.row_height == 47
        assert int(pane.table.header.cget("height")) == 47
    if app.register_font.actual("family") != "Courier New":
        pytest.skip("the widths are those of Courier New")
    assert app.register_font.measure("0x00000000") == 190
    assert app.register_heading_font.measure("Value") == 61


# The Execute tab's tables have the usual sizes ---------------------------------------------------

def test_the_execute_tabs_tables_have_the_usual_sizes_and_fonts(app):
    root = app.root
    heading = tkfont.nametofont("TkHeadingFont", root=root)
    execute = app.execute
    for table in (execute.text_segment.table, execute.data_segment.table, execute.labels.table):
        ring = table._ring
        assert table.row_height == max(px(root, table_module.ROW_HEIGHT),
                                       app.pane_font.metrics("linespace") + ring)
        assert int(table.header.cget("height")) == max(px(root, table_module.HEADING_HEIGHT),
                                                       heading.metrics("linespace") + 4 * ring)
        assert table.font is app.pane_font
        assert str(table.heading_font) == str(heading)


def test_at_225_percent_the_execute_tabs_tables_are_smaller_than_the_register_tables(
        at_225, make_app):
    app = make_app()
    execute = app.execute
    for table in (execute.text_segment.table, execute.data_segment.table, execute.labels.table):
        assert table.row_height == 36
        assert int(table.header.cget("height")) == 45


def test_a_table_takes_its_sizes_from_its_maker_or_else_the_usual_ones(tk_root):
    font = tkfont.Font(root=tk_root, size=9)
    usual = Table(tk_root, [Column("a", "A", 50)], font)
    taller = Table(tk_root, [Column("a", "A", 50)], font, row_height=30, heading_height=40)
    assert usual.row_height == max(px(tk_root, table_module.ROW_HEIGHT),
                                   font.metrics("linespace") + usual._ring)
    assert taller.row_height == px(tk_root, 30)
    assert int(taller.header.cget("height")) == px(tk_root, 40)
    usual.destroy()
    taller.destroy()


def test_a_font_taller_than_a_tables_rows_still_fits_them(tk_root):
    font = tkfont.Font(root=tk_root, size=40)
    table = Table(tk_root, [Column("a", "A", 50)], font, row_height=10, heading_height=10)
    assert table.row_height == font.metrics("linespace") + table._ring
    table.destroy()


def test_a_column_makes_room_for_its_heading_in_the_tables_heading_font(tk_root):
    small = tkfont.Font(root=tk_root, size=6)
    large = tkfont.Font(root=tk_root, size=30)
    chars = tkfont.Font(root=tk_root, size=6)
    wide = column_width(tk_root, chars, 1, "A long heading", large)
    narrow = column_width(tk_root, chars, 1, "A long heading", small)
    assert wide > narrow
    assert wide == large.measure("A long heading") + 2 * px(tk_root, table_module.PAD) + 2
    usual = tkfont.nametofont("TkHeadingFont", root=tk_root).measure("A long heading")
    assert column_width(tk_root, chars, 1, "A long heading") == (usual + 2 * px(
        tk_root, table_module.PAD) + 2)


# The default window and smaller ones --------------------------------------------------------------

def test_the_maximized_window_shows_every_row_with_a_small_gap_under_the_coproc_tables(maximized):
    app = maximized()
    for pane, name in zip(panes(app), ROWS):
        table = pane.table
        app.side.select(pane)
        assert pump(app.root)
        assert table.count == ROWS[name]
        gap = table.body.winfo_height() - table.count * table.row_height
        assert gap > 0
        assert table.vscroll.winfo_manager() == table.hscroll.winfo_manager() == ""
        if name != "registers":
            assert gap < 4 * table.row_height               # about 70 design pixels


@pytest.mark.parametrize("height, bars", [(889, ()), (700, ("coproc10", "coproc11")),
                                         (400, ("registers", "coproc10", "coproc11"))],
                         ids=["maximized", "too short for 33 rows", "too short for 18 rows"])
def test_a_smaller_window_shows_a_scroll_bar_when_the_rows_do_not_fit(maximized, height, bars):
    app = maximized(height)
    for pane, name in zip(panes(app), ROWS):
        table = pane.table
        app.side.select(pane)
        assert pump(app.root)
        assert (table.vscroll.winfo_manager() == "grid") == (name in bars)
        assert table.page == min(table.count, table.body.winfo_height() // table.row_height) or (
            name not in bars)
        assert table.hscroll.winfo_manager() == ""


def test_the_columns_have_room_for_their_values_in_the_larger_text(maximized):
    app = maximized()
    pad = 2 * px(app.root, table_module.PAD)
    char = app.register_font.measure("0")
    for pane, chars in ((app.registers, 11), (app.coproc10, registers.SINGLE_CHARS[0]),
                        (app.coproc11, registers.DOUBLE_CHARS[0])):
        app.side.select(pane)
        assert pump(app.root)
        value = next(column for column in pane.table.columns if column.id == "value")
        assert value.width >= chars * char + pad


def test_decimal_values_still_fit_the_maximized_window_without_a_sideways_bar(maximized):
    app = maximized()
    app.settings.hex_values = False
    for pane in (app.coproc10, app.coproc11):
        app.side.select(pane)
        pane.refresh()
        assert pump(app.root)
        assert pane.table.hscroll.winfo_manager() == ""


# What is drawn in the rows ----------------------------------------------------------------------

def test_the_flags_letters_fit_their_rows(maximized):
    app = maximized()
    for pane, row in ((app.registers, registers.CPSR_ROW), (app.registers, registers.SPSR_ROW),
                      (app.coproc10, registers.FPSCR_ROW), (app.coproc11, registers.FPSCR_ROW)):
        show_all_rows(app, pane)
        table = pane.table
        top, bottom = row_box(table, row)
        marks = table.row(row).cells[-1]
        assert marks
        for number in range(len(marks)):
            x0, y0, x1, y1 = table.mark_box(row, "flags", number)
            assert (y0, y1) == (top, bottom)
        items = table.slots[row - table.top][1 + 2 * len(table.columns):]
        shown = [item for item in items if table.body.itemcget(item, "state") != "hidden"]
        assert len(shown) == len(marks)
        for item in shown:
            _, y0, _, y1 = table.body.bbox(item)
            assert top <= y0 and y1 <= bottom


def test_a_double_click_opens_the_field_of_the_row_under_the_mouse(maximized, tmp_path):
    app = maximized()
    open_source(app, tmp_path, PROGRAM)
    assemble(app)
    for pane in panes(app):
        show_all_rows(app, pane)
        table = pane.table
        last = len(pane.ROWS) - 1 - len(pane.FIXED)
        for index in (0, 1, last // 2, last):
            top, bottom = row_box(table, index)
            for y in (top, top + 1, (top + bottom) // 2, bottom - 1):
                table._clicked = None
                table._double(SimpleNamespace(x=table.cell_box(index, "value")[0] + 5, y=y))
                assert pane.editor is not None, (pane, index, y)
                assert pane._editing[0] == index
                pane.cancel_edit()


def test_the_edit_field_covers_its_cell_exactly(maximized, tmp_path):
    app = maximized()
    open_source(app, tmp_path, PROGRAM)
    assemble(app)
    for pane in panes(app):
        show_all_rows(app, pane)
        table = pane.table
        pane.edit(3)
        item = pane._editing[1]
        column = next(column for column in table.columns if column.id == "value")
        x0, y0, x1, y1 = table.cell_box(3, "value")
        assert table.body.coords(item) == [x0, y0]
        assert int(table.body.itemcget(item, "height")) == y1 - y0 == table.row_height
        assert int(table.body.itemcget(item, "width")) == column.width
        assert pane.editor.cget("font") == str(table.font)
        pane.cancel_edit()


def test_the_selection_fits_its_row(maximized, tmp_path):
    app = maximized()
    open_source(app, tmp_path, PROGRAM)
    assemble(app)
    for pane in panes(app):
        show_all_rows(app, pane)
        table = pane.table
        table.select(2)
        pump(app.root)
        top, bottom = row_box(table, 2)
        place = 2 - table.top
        background = table.slots[place][0]
        assert table.body.itemcget(background, "fill").lower() == (
            table.select_background.lower())
        _, y0, _, y1 = table.body.coords(background)
        assert (y0, y1) == (top, bottom)


def test_the_change_highlight_fits_its_row(maximized, tmp_path):
    app = maximized()
    open_source(app, tmp_path, PROGRAM)
    assemble(app)
    for pane, change in ((app.registers, lambda p: p.set_values(
            [1] * 16, p.cpsr, p.spsr)),
            (app.coproc10, lambda p: p.set_values([1] * 32, p.fpscr)),
            (app.coproc11, lambda p: p.set_values([1] * 32, p.fpscr))):
        show_all_rows(app, pane)
        table = pane.table
        pane.mark()
        change(pane)
        pump(app.root)
        place = 0
        top, bottom = row_box(table, place)
        assert table._raised.get(place)
        for item in table._raised[place]:
            _, y0, _, y1 = table.body.coords(item)
            assert top <= y0 and y1 <= bottom
        pane.unmark()
