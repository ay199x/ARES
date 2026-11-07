# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The canvas table: only the rows on the screen are drawn, scrolling, selection, mouse and keys."""

import time
import tkinter
from tkinter import font as tkfont
from types import SimpleNamespace

import pytest
from conftest import fixed_screen, lay_out, press_key, pump

from ares.gui import style
from ares.gui import table as table_module
from ares.gui.table import (DEFAULT_ROWS, ELLIPSIS, MARK_OFF, STRIPE, WHITE, Column, Mark, Row,
                            Table, off_colour)
from ares.gui.widgets import Tooltip, show_bar

YELLOW = "#FFFF99"


@pytest.fixture
def font(tk_root):
    return tkfont.Font(root=tk_root, family="Courier New", size=10)


@pytest.fixture
def make_table(tk_root, font):
    tables = []

    def make(count=1000, row=None, columns=None):
        columns = columns or [Column("address", "Address", 100, "e"),
                              Column("text", "Text", 200),
                              Column("note", "Note", 150)]
        table = Table(tk_root, columns, font)
        table.pack()
        table.set_rows(count, row or (lambda i: Row((str(i), f"row {i}", ""))))
        tables.append(table)
        return table
    yield make
    for table in tables:
        table.destroy()


def shown(table, column=0):
    """The texts of one column in the rows on the screen, top to bottom."""
    texts = []
    for items in table.slots:
        item = items[2 + 2 * column]
        if table.body.itemcget(items[0], "state") != "hidden":
            texts.append(table.body.itemcget(item, "text"))
    return texts


def row_fill(table, index):
    items = table.slots[index - table.top]
    return table.body.itemcget(items[0], "fill")


def text_fill(table, index, column=1):
    items = table.slots[index - table.top]
    return table.body.itemcget(items[2 + 2 * column], "fill")


def test_only_the_rows_on_the_screen_are_drawn(make_table):
    table = make_table(count=100_000)
    assert len(table.slots) == DEFAULT_ROWS and table.page == DEFAULT_ROWS
    texts = [i for i in table.body.find_all() if table.body.type(i) == "text"]
    assert len(texts) == DEFAULT_ROWS * 3
    assert shown(table) == [str(i) for i in range(DEFAULT_ROWS)]
    assert shown(table, 1)[:2] == ["row 0", "row 1"]


def test_short_tables_hide_the_places_below_the_last_row(make_table):
    table = make_table(count=3)
    assert shown(table) == ["0", "1", "2"]
    table.set_rows(0, None)
    assert shown(table) == []
    assert table.yview() == (0.0, 1.0)


def test_rows_alternate_white_and_stripe(make_table):
    table = make_table()
    assert row_fill(table, 0) == STRIPE and row_fill(table, 1) == WHITE
    table.scroll_to(1)
    assert row_fill(table, 1) == WHITE and row_fill(table, 2) == STRIPE


def test_scroll_bar_commands(make_table):
    table = make_table(count=1000)
    table.yview("scroll", "3", "units")
    assert table.top == 3 and shown(table)[0] == "3"
    table.yview("scroll", "1", "pages")
    assert table.top == 3 + DEFAULT_ROWS
    table.yview("moveto", "0.5")
    assert table.top == 500
    table.yview("moveto", "1.0")
    assert table.top == 1000 - DEFAULT_ROWS       # the last page is full
    assert shown(table)[-1] == "999"
    table.yview("moveto", "-0.5")
    assert table.top == 0
    first, last = table.yview()
    assert first == 0.0 and last == DEFAULT_ROWS / 1000
    assert tuple(map(float, table.vscroll.get())) == (first, last)


def test_see_scrolls_as_little_as_needed(make_table):
    table = make_table(count=1000)
    table.see(5)
    assert table.top == 0
    table.see(100)
    assert table.top == 100 - DEFAULT_ROWS + 1     # the row is the last one on the screen
    table.see(50)
    assert table.top == 50
    table.see(5000)                                 # no such row
    assert table.top == 50


def test_see_with_center_puts_the_row_in_the_middle(make_table):
    table = make_table(count=1000)
    table.see(500, center=True)
    assert table.top == 500 - (DEFAULT_ROWS - 1) // 2
    top = table.top
    table.see(501, center=True)                     # already on the screen
    assert table.top == top
    table.see(2, center=True)
    assert table.top == 0


def frame(table):
    """The rectangle marking the selected row, or None when it is hidden."""
    if table.body.itemcget(table._frame, "state") == "hidden":
        return None
    return table.body.coords(table._frame)


def test_selection_colours_and_row_colours(make_table):
    rows = {7: Row(("7", "seven", ""), YELLOW)}
    table = make_table(row=lambda i: rows.get(i, Row((str(i), f"row {i}", ""))))
    table.select(3)
    assert table.selected == 3
    assert row_fill(table, 3) == table.select_background
    assert text_fill(table, 3) == table.select_foreground
    assert row_fill(table, 7) == YELLOW and text_fill(table, 7) == "#000000"
    table.select(7)             # its own colour stays, framed in the selection colour
    assert row_fill(table, 7) == YELLOW and text_fill(table, 7) == "#000000"
    assert table.body.itemcget(table._frame, "outline") == table.select_background
    top, bottom = frame(table)[1], frame(table)[3]
    assert 7 * table.row_height <= top < bottom <= 8 * table.row_height
    assert row_fill(table, 3) == WHITE
    table.select(None)
    assert table.selected is None and frame(table) is None


def test_the_frame_follows_the_selected_row_and_leaves_with_it(make_table):
    table = make_table(count=1000)
    table.select(5)
    assert frame(table)[1] == 5 * table.row_height + 1
    table.scroll_to(3)
    assert frame(table)[1] == 2 * table.row_height + 1
    table.scroll_to(100)                            # the selected row is off the screen
    assert frame(table) is None


def test_cell_backgrounds(make_table):
    table = make_table(row=lambda i: Row((str(i), "x", "y"), "",
                                         {"text": "#99CCFF"} if i == 2 else {}))
    items = table.slots[2]
    assert table.body.itemcget(items[3], "state") == "normal"
    assert table.body.itemcget(items[3], "fill") == "#99CCFF"
    assert table.body.itemcget(items[1], "state") == "hidden"
    assert table.body.coords(items[3])[0] == 100        # the cell of column "text"
    table.select(2)
    assert text_fill(table, 2) == "#000000"             # readable on the cell's colour
    assert text_fill(table, 2, 2) == table.select_foreground


def test_select_scrolls_the_row_into_view(make_table):
    table = make_table(count=1000)
    table.select(600, center=True)
    assert table.top <= 600 < table.top + table.page
    assert table.top == 600 - (DEFAULT_ROWS - 1) // 2


def test_texts_are_cut_to_their_column(make_table, font):
    long = "ABCDEFGHIJ" * 10
    table = make_table(row=lambda i: Row(("1", long, "")))
    fits = (200 - 2 * table._pad) // font.measure("0")
    assert shown(table, 1)[0] == long[:fits - 1] + ELLIPSIS     # the cut shows
    table.set_width("text", 1000)
    assert shown(table, 1)[0] == long
    table.set_width("text", 1)                      # never narrower than the smallest width
    assert table.columns[1].width > 1


def test_fit_takes_the_rows_that_fit(make_table):
    table = make_table(count=1000)
    height = table.row_height
    table.fit(10 * height)
    assert table.page == 10 and len(table.slots) == 10
    table.fit(10 * height + 3)                      # a part of one more row shows
    assert table.page == 10 and len(table.slots) == 11
    assert shown(table) == [str(i) for i in range(11)]
    table.scroll_to(995)
    assert table.top == 990
    table.fit(4 * height)
    assert len(table.slots) == 4 and table.top == 990
    texts = [i for i in table.body.find_all() if table.body.type(i) == "text"]
    assert len(texts) == 4 * 3


def test_a_row_asked_for_stays_in_view_when_the_size_changes(make_table):
    table = make_table(count=1000)
    table.see(300)                          # shown with the 20 rows taken before any size
    assert table.top == 281
    table.fit(10 * table.row_height + 5)    # the first real size of the table
    assert table.top <= 300 < table.top + table.page
    table.select(500, center=True)
    table.fit(4 * table.row_height)
    assert table.top <= 500 < table.top + table.page


def test_scrolling_by_the_user_lets_the_row_go(make_table, monkeypatch):
    table = make_table(count=1000)
    monkeypatch.setattr(table_module, "is_aqua", lambda widget: False)
    table.see(300)
    table.scroll_to(0)
    table.fit(10 * table.row_height)
    assert table.top == 0
    table.see(300)
    table._mouse_wheel(SimpleNamespace(delta=120, state=0))
    top = table.top
    table.fit(5 * table.row_height)
    assert table.top == top
    table.see(300)
    table.set_rows(1000, table.row)         # new rows: nothing is kept
    table.fit(8 * table.row_height)
    assert table.top == 0


def test_fit_keeps_the_last_page_full(make_table):
    table = make_table(count=100)
    table.scroll_to(80)
    table.fit(40 * table.row_height)
    assert table.top == 60 and shown(table)[-1] == "99"


def test_keys_move_the_selection(make_table):
    table = make_table(count=1000)
    body = table.body
    assert press_key(body, "<Key-Down>")[0] == str(body)
    assert table.selected == 0                      # the top row first
    press_key(body, "<Key-Down>")
    press_key(body, "<Key-Down>")
    assert table.selected == 2
    press_key(body, "<Key-Up>")
    assert table.selected == 1
    press_key(body, "<Key-Next>")
    assert table.selected == 1 + DEFAULT_ROWS
    assert table.top <= table.selected < table.top + table.page
    press_key(body, "<Key-Prior>")
    assert table.selected == 1
    press_key(body, "<Key-End>")
    assert table.selected == 999 and table.top == 1000 - DEFAULT_ROWS
    press_key(body, "<Key-Home>")
    assert table.selected == 0 and table.top == 0
    press_key(body, "<Key-Up>")
    assert table.selected == 0


def test_page_keys_scroll_without_a_selection(make_table):
    table = make_table(count=1000)
    press_key(table.body, "<Key-Next>")
    assert table.selected is None and table.top == DEFAULT_ROWS
    press_key(table.body, "<Key-Prior>")
    assert table.top == 0


def test_keys_do_nothing_in_an_empty_table(make_table):
    table = make_table(count=0)
    for key in ("<Key-Down>", "<Key-End>", "<Key-Next>", "<Key-Home>"):
        press_key(table.body, key)
    assert table.selected is None and table.top == 0


def test_mouse_wheel_scrolls_three_rows_a_notch(make_table, monkeypatch):
    table = make_table(count=1000)
    monkeypatch.setattr(table_module, "is_aqua", lambda widget: False)
    table._mouse_wheel(SimpleNamespace(delta=-120, state=0))
    assert table.top == 3
    for _ in range(3):                              # a smooth wheel sends small turns
        table._mouse_wheel(SimpleNamespace(delta=-40, state=0))
    assert table.top == 6
    table._mouse_wheel(SimpleNamespace(delta=240, state=0))
    assert table.top == 0


def test_mouse_wheel_on_macos_scrolls_a_row_a_unit(make_table, monkeypatch):
    table = make_table(count=1000)
    monkeypatch.setattr(table_module, "is_aqua", lambda widget: True)
    table._mouse_wheel(SimpleNamespace(delta=-2, state=0))
    assert table.top == 2


def test_shift_and_mouse_wheel_adds_up_small_turns(make_table, monkeypatch):
    table = make_table(count=1000)
    monkeypatch.setattr(table_module, "is_aqua", lambda widget: False)
    moved = []
    monkeypatch.setattr(table.body, "xview_scroll", lambda n, what: moved.append(n))
    for _ in range(12):
        table._mouse_wheel(SimpleNamespace(delta=-10, state=1))
    table._mouse_wheel(SimpleNamespace(delta=0, state=1))
    assert moved == [1]


def test_shift_and_mouse_wheel_scrolls_sideways(make_table, monkeypatch):
    table = make_table(count=1000)
    monkeypatch.setattr(table_module, "is_aqua", lambda widget: False)
    moved = []
    monkeypatch.setattr(table.body, "xview_scroll", lambda n, what: moved.append((n, what)))
    assert table._mouse_wheel(SimpleNamespace(delta=-120, state=1)) == "break"
    assert moved == [(1, "units")] and table.top == 0
    wheel = ("<Button-4>", "<Shift-Button-4>") if table.tk.call("tk", "windowingsystem") == "x11" \
        else ("<MouseWheel>", "<Shift-MouseWheel>")
    for widget in (table.body, table.header):
        assert all(widget.bind(sequence) for sequence in wheel)


def test_click_selects_and_reports_the_cell(make_table):
    table = make_table(count=1000)
    clicks = []
    table.on_click = lambda index, column: clicks.append((index, column))
    table.scroll_to(10)
    y = 2 * table.row_height + 1
    table._press(SimpleNamespace(x=150, y=y))
    assert table.selected == 12 and clicks == [(12, "text")]
    table._press(SimpleNamespace(x=5, y=1))
    assert clicks[-1] == (10, "address")
    table._press(SimpleNamespace(x=460, y=1))           # right of the last column
    assert clicks[-1] == (10, None)


def test_click_below_the_last_row_does_nothing(make_table):
    table = make_table(count=3)
    clicks = []
    table.on_click = lambda index, column: clicks.append(index)
    table._press(SimpleNamespace(x=5, y=5 * table.row_height))
    assert clicks == [] and table.selected is None


def test_double_click_reports_the_cell(make_table):
    table = make_table(count=100)
    clicks = []
    table.on_double_click = lambda index, column: clicks.append((index, column))
    table._double(SimpleNamespace(x=310, y=table.row_height + 1))
    assert clicks == [(1, "note")]


def test_double_click_on_a_partly_shown_row_acts_on_that_row(make_table):
    table = make_table(count=100)
    table.fit(10 * table.row_height + table.row_height // 2)
    clicks, doubles = [], []
    table.on_click = lambda index, column: clicks.append(index)
    table.on_double_click = lambda index, column: doubles.append(index)
    y = 10 * table.row_height + 3                       # row 10, only half on the screen
    table._press(SimpleNamespace(x=5, y=y))
    assert clicks == [10] and table.top == 1            # scrolled to show it wholly
    table._double(SimpleNamespace(x=5, y=y))            # the second click, same place
    assert doubles == [10]


def test_heading_click_and_border_drag(make_table):
    table = make_table()
    clicked = []
    table.on_heading = clicked.append
    table._heading_press(SimpleNamespace(x=150, y=5))
    table._heading_release(SimpleNamespace(x=160, y=5))
    assert clicked == ["text"]
    table._heading_press(SimpleNamespace(x=150, y=5))
    table._heading_release(SimpleNamespace(x=330, y=5))     # released over another heading
    assert clicked == ["text"]
    border = 100 + 200 - 1                                  # right border of "text"
    table._heading_press(SimpleNamespace(x=border, y=5))
    table._heading_drag(SimpleNamespace(x=border + 50, y=5))
    table._heading_release(SimpleNamespace(x=border + 50, y=5))
    assert table.columns[1].width == 250 and clicked == ["text"]
    assert table.body.coords(table.slots[0][6])[0] == 100 + 250 + table._pad


@pytest.mark.parametrize("y", [-300, 400])
def test_a_heading_released_away_from_the_headings_is_no_click(make_table, y):
    table = make_table()
    clicked = []
    table.on_heading = clicked.append
    table._heading_press(SimpleNamespace(x=150, y=5))
    table._heading_release(SimpleNamespace(x=150, y=y))
    assert clicked == []


def test_heading_shows_the_resize_cursor_near_a_border(make_table):
    table = make_table()
    table._heading_motion(SimpleNamespace(x=99))
    assert str(table.header.cget("cursor")) == "sb_h_double_arrow"
    table._heading_motion(SimpleNamespace(x=50))
    assert str(table.header.cget("cursor")) == ""


def test_set_rows_can_change_widths(make_table):
    table = make_table(count=1000)
    table.set_rows(3, lambda i: Row(("a", "b", "c")), {"text": 300, "nothing": 5})
    assert [c.width for c in table.columns] == [100, 300, 150]
    assert shown(table, 1) == ["b", "b", "b"]
    assert table.body.coords(table.slots[0][6])[0] == 400 + table._pad


def test_widgets_can_bind_on_a_table(make_table):
    table = make_table()
    table.bind("<Enter>", lambda e: None)
    assert table.bind() == ("<Enter>",)
    Tooltip(table, "a table")


def test_wide_characters_are_measured(make_table, font):
    wide = "\u8ba1\u6570\u5668\u52a0\u4e00" * 10
    table = make_table(row=lambda i: Row(("1", "@ " + wide, "")))
    text = shown(table, 1)[0]
    assert text.endswith(ELLIPSIS) and font.measure(text) <= 200 - 2 * table._pad


def test_checkbox_column(make_table):
    """Classic checkboxes drawn on the canvas, in the middle of their cells: (checked,
    enabled), or None for a row without one."""
    from ares.gui.style import checkbox_size
    columns = [Column("box", "Box", 30, "center", checkbox=True), Column("text", "Text", 100)]
    table = make_table(count=100, columns=columns,
                       row=lambda i: Row(((i % 4 == 1, True) if i % 2 else None, str(i))))
    body = table.body
    boxes = [table._boxes[slot[2]] for slot in table.slots[:4]]
    assert all(body.itemcget(item, "state") == "hidden" for item in boxes[0])    # row 0: none
    assert [body.itemcget(boxes[k][9], "state") for k in (1, 3)] == ["normal", "hidden"]
    assert all(body.itemcget(item, "state") == "normal" for item in boxes[3][:9])
    x0, y0, x1, y1 = body.coords(boxes[1][0])
    size = checkbox_size(body)
    assert (x0, x1 - x0) == ((30 - size) // 2, size)                     # in its cell's middle
    table.scroll_to(1)                          # the first place now shows row 1
    assert body.itemcget(boxes[0][9], "state") == "normal"


MARKS = (Mark("N", True, "negative"), Mark("Z", False, "zero"), Mark("SVC", True, "mode",
                                                                    space=True))


def marks_table(make_table):
    """Rows whose odd ones have the three MARKS in their "flags" column."""
    columns = [Column("name", "Name", 60), Column("flags", "Flags", 120, marks=4)]
    return make_table(count=100, columns=columns,
                      row=lambda i: Row((f"row {i}", MARKS if i % 2 else ())))


def drawn_marks(table, place):
    """(text, colour, x) of the marks drawn in a row place."""
    body = table.body
    return [(body.itemcget(item, "text"), body.itemcget(item, "fill"), body.coords(item)[0])
            for item in table.slots[place][5:] if body.itemcget(item, "state") != "hidden"]


def test_marks_are_drawn_one_after_another(make_table, font):
    table = marks_table(make_table)
    assert drawn_marks(table, 0) == []
    pad, char = table._pad, font.measure("0")
    assert drawn_marks(table, 1) == [("N", "#000000", 60 + pad), ("Z", MARK_OFF, 60 + pad + char),
                                     ("SVC", "#000000", 60 + pad + 3 * char)]
    assert table.body.itemcget(table.slots[1][4], "state") == "hidden"  # the column's own text
    assert table.mark_box(1, "flags", 2) == (60 + pad + 3 * char, table.row_height,
                                             60 + pad + 6 * char, 2 * table.row_height)
    assert table.mark_box(0, "flags", 0) is None and table.mark_box(1, "flags", 3) is None
    table.select(1)                     # selected: the row keeps its colours, with a frame
    assert [colour for _, colour, _ in drawn_marks(table, 1)] == ["#000000", MARK_OFF, "#000000"]
    assert row_fill(table, 1) == WHITE
    assert table.body.itemcget(table._frame, "state") == "normal"
    assert table.body.coords(table._frame)[1] == table.row_height + 1
    table.select(0)                                     # a row without marks: filled
    assert row_fill(table, 0) == table.select_background
    table.scroll_to(1)                                  # the places show other rows now
    assert drawn_marks(table, 1) == [] and len(drawn_marks(table, 0)) == 3


def test_an_off_mark_stays_visible_on_a_coloured_row(make_table):
    columns = [Column("name", "Name", 60), Column("flags", "Flags", 120, marks=4)]
    table = make_table(count=100, columns=columns,
                       row=lambda i: Row((f"row {i}", MARKS), "#99CC55" if i == 1 else ""))
    assert drawn_marks(table, 1)[1][1] == off_colour("#99CC55") == "#688B3A"
    assert drawn_marks(table, 0)[1][1] == drawn_marks(table, 2)[1][1] == off_colour(STRIPE)
    assert off_colour(WHITE) == MARK_OFF
    assert off_colour(STRIPE) == "#989898"     # as much darker on the gray rows


def test_marks_that_do_not_fit_their_column_are_not_drawn(make_table, font):
    table = marks_table(make_table)
    marks, doubles = [], []
    table.on_mark = lambda index, column, number: marks.append(number)
    table.on_double_click = lambda index, column: doubles.append(column)
    table.set_width("flags", table._pad + 3 * font.measure("0") + table._pad)    # N, Z and a space
    assert [text for text, _, _ in drawn_marks(table, 1)] == ["N", "Z"]
    assert table.mark_box(1, "flags", 2) is None
    x0, y0, x1, y1 = table.mark_box(1, "flags", 1)
    table._double(SimpleNamespace(x=(x0 + x1) // 2, y=(y0 + y1) // 2))
    assert marks == [1]
    table.set_width("flags", 120)
    assert [text for text, _, _ in drawn_marks(table, 1)] == ["N", "Z", "SVC"]


def test_double_click_on_a_mark_reports_it(make_table, font):
    table = marks_table(make_table)
    marks, doubles = [], []
    table.on_mark = lambda index, column, number: marks.append((index, column, number))
    table.on_double_click = lambda index, column: doubles.append((index, column))
    for number in range(3):
        x0, y0, x1, y1 = table.mark_box(3, "flags", number)
        table._double(SimpleNamespace(x=(x0 + x1) // 2, y=(y0 + y1) // 2))
    assert marks == [(3, "flags", 0), (3, "flags", 1), (3, "flags", 2)] and doubles == []
    x0, y0, x1, y1 = table.mark_box(3, "flags", 2)
    table._double(SimpleNamespace(x=x1 + 20, y=y0 + 2))     # beside the marks
    table._double(SimpleNamespace(x=x0 - font.measure(" ") // 2, y=y0 + 2))  # the space
    table._double(SimpleNamespace(x=5, y=y0 + 2))
    assert doubles == [(3, "flags"), (3, "flags"), (3, "name")] and len(marks) == 3


def test_a_mark_has_a_tooltip(make_table, monkeypatch):
    table = marks_table(make_table)
    shown = []
    monkeypatch.setattr(table_module, "tip_window",
                        lambda widget, text, x, y: shown.append(text) or SimpleNamespace(
                            destroy=lambda: shown.append("gone")))
    monkeypatch.setattr(table.body, "winfo_ismapped", lambda: True)
    item = table.slots[1][6]                            # the Z of row 1
    monkeypatch.setattr(table.body, "find_withtag", lambda tag: (item,))
    table._mark_entered(None)
    assert table._tip_job is not None
    table._show_tip()
    assert shown == ["zero"]
    table._hide_tip()
    assert shown == ["zero", "gone"]
    table._mark_entered(None)
    table.scroll_to(1)                                  # scrolling forgets a waiting tooltip
    assert table._tip_job is None and table._tip_item is None
    table.scroll_to(0)                                  # the Z of row 1 on the screen again
    for button in ("<ButtonPress-3>", "<ButtonPress-2>", "<ButtonPress-1>"):
        table._mark_entered(None)
        table._show_tip()
        assert table._tip is not None
        press_key(table.body, button)                   # any button hides it
        assert table._tip is None, button


def test_unchanged_rows_are_not_drawn_again(make_table, monkeypatch):
    table = make_table(count=1000)
    calls = []
    original = table.body.itemconfigure
    monkeypatch.setattr(table.body, "itemconfigure",
                        lambda *args, **options: calls.append(args) or original(*args, **options))
    table.refresh()
    assert calls == []
    table.scroll_to(1)
    assert calls


@pytest.mark.serial
def test_scrolling_a_long_table_is_fast(make_table):
    table = make_table(count=1_000_000)
    table.fit(40 * table.row_height)
    start = time.perf_counter()
    for top in range(0, 200_000, 1000):
        table.scroll_to(top)
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"200 scrolls took {elapsed:.3f} s"


# Columns that fill the table's width ----------------------------------------------

@pytest.fixture
def placed_table(tk_root, font):
    """A table with a real size, although its window stays hidden.

    A withdrawn window with a geometry lays out the widgets placed in it, so
    the body gets its width and height. Its <Configure> events come only once
    it is on the screen, so resize() gives the table the size as they would.
    """
    windows = []

    def make(width, columns, count=30):
        window = tkinter.Toplevel(tk_root)
        window.geometry("1200x700")
        table = Table(window, columns, font)
        table.set_rows(count, lambda i: Row(tuple(f"{c.id}{i}" for c in columns)))
        windows.append(window)
        resize(table, width)
        return table
    yield make
    for window in windows:
        window.destroy()


def resize(table, width):
    """Place a table width pixels wide and tell it its size, as <Configure> would."""
    table.place(x=0, y=0, width=width, height=400)
    table.winfo_toplevel().update()
    table._configured(SimpleNamespace(width=table.body.winfo_width(),
                                      height=table.body.winfo_height()))
    table.winfo_toplevel().update()


def widths(table):
    return [column.width for column in table.columns]


def test_the_last_column_takes_the_rest_of_the_width(placed_table):
    table = placed_table(600, [Column("a", "A", 50), Column("b", "B", 80),
                               Column("source", "Source", 100, stretch=True)])
    body = table.body.winfo_width()
    assert body > 300 and table._available == body
    assert widths(table) == [50, 80, body - 130]
    assert table.hscroll.winfo_manager() == ""          # everything fits: no scroll bar
    resize(table, 900)                                  # the pane gets wider
    assert widths(table) == [50, 80, table.body.winfo_width() - 130] and widths(table)[2] > 400


def test_stretching_columns_share_the_width_equally(placed_table):
    table = placed_table(500, [Column(k, k.upper(), 60, stretch=True) for k in "abcd"])
    body = table.body.winfo_width()
    assert sum(widths(table)) == body and max(widths(table)) - min(widths(table)) <= 1
    assert widths(table) == sorted(widths(table))       # the pixels left over go to the last


def test_a_column_that_needs_more_than_its_share_keeps_its_width(make_table):
    table = make_table(columns=[Column("a", "A", 40, stretch=True),
                                Column("b", "B", 150, stretch=True),
                                Column("c", "C", 40, stretch=True)])
    table.fill(330)                                     # equal parts would be 110: b needs 150
    assert widths(table) == [90, 150, 90]
    table.fill(600)
    assert widths(table) == [200, 200, 200]
    table.fill(231)                                     # they need 230 together
    assert widths(table) == [40, 150, 41] and table.hscroll.winfo_manager() == ""
    table.fill(200)                                     # too narrow: a scroll bar instead
    assert widths(table) == [40, 150, 40] and table.hscroll.winfo_manager() == "grid"
    table.fill(400)
    assert table.hscroll.winfo_manager() == ""


def test_headings_and_rows_scroll_sideways_together(placed_table):
    """In a table narrower than its pane, Left, Shift+wheel and the left arrow of the scroll
    bar do not move the rows away from their headings."""
    table = placed_table(500, [Column("a", "A", 60), Column("b", "B", 60)])     # narrow
    window = table.winfo_toplevel()
    for scroll in (lambda: press_key(table.body, "<Key-Left>"),
                   lambda: table._wheel_columns(-3),                    # Shift + mouse wheel
                   lambda: table.xview("scroll", "-1", "units"),        # the left arrow
                   lambda: press_key(table.body, "<Key-Right>")):
        scroll()
        window.update()
        assert table.body.canvasx(0) == table.header.canvasx(0) == 0
    resize(table, 100)                                  # now the columns do not fit
    assert table.hscroll.winfo_manager() == "grid"
    for _ in range(3):
        press_key(table.body, "<Key-Right>")
    window.update()
    assert table.body.canvasx(0) > 0 and table.header.canvasx(0) == table.body.canvasx(0)
    resize(table, 500)                                  # they fit again: back at the start
    assert table.body.canvasx(0) == table.header.canvasx(0) == 0
    assert table.hscroll.winfo_manager() == ""


def test_the_scroll_region_is_never_narrower_than_the_body(make_table):
    table = make_table(count=5)
    table.fill(800)                                     # the columns need 450
    for canvas in (table.body, table.header):
        assert float(str(canvas.cget("scrollregion")).split()[2]) == 800
    assert table.body.coords(table.slots[0][0])[2] == 800       # rows as wide as the body


def test_a_dragged_column_keeps_its_width_and_the_others_share_the_rest(make_table):
    table = make_table(columns=[Column(k, k.upper(), 50, stretch=True) for k in "abc"])
    table.fill(600)
    assert widths(table) == [200, 200, 200]
    border = 200 - 1
    table._heading_press(SimpleNamespace(x=border, y=5))
    table._heading_drag(SimpleNamespace(x=border - 100, y=5))
    table._heading_release(SimpleNamespace(x=border - 100, y=5))
    assert widths(table) == [100, 250, 250]
    table.fill(800)                                     # the pane gets wider
    assert widths(table) == [100, 350, 350]
    table._heading_motion(SimpleNamespace(x=799))       # the last border is the table's edge
    assert str(table.header.cget("cursor")) == ""
    table._heading_press(SimpleNamespace(x=799, y=5))
    table._heading_drag(SimpleNamespace(x=600, y=5))
    assert widths(table) == [100, 350, 350]
    table.set_rows(5, table.row, {"a": 50})             # new contents: it stretches again
    assert widths(table) == [266, 267, 267]


def test_thin_lines_between_the_cells(make_table):
    table = make_table(count=3)
    table.fill(600)
    body = table.body
    for place in range(3):
        rule = table._rules[place]
        assert body.itemcget(rule, "state") == "normal"
        assert body.itemcget(rule, "fill") == style.GRID
        ring = table._ring
        assert body.coords(rule) == [0, (place + 1) * table.row_height - ring,
                                     600, (place + 1) * table.row_height]
    assert body.itemcget(table._rules[3], "state") == "hidden"      # no row there
    assert [body.coords(line)[0] for line in table._lines] == [100 - ring, 300 - ring, 450 - ring]
    assert {body.itemcget(line, "fill") for line in table._lines} == {style.GRID}
    order = body.find_all()
    assert order.index(table._rules[0]) > order.index(table.slots[0][0])   # over the row
    assert order.index(table._rules[0]) < order.index(table.slots[0][2])   # under the text


def test_enter_or_f2_acts_on_the_selected_row(make_table):
    table = make_table(count=10)
    rows = []
    table.on_activate = rows.append
    press_key(table.body, "<Key-Return>")
    assert rows == []                                   # nothing selected
    table.select(4)
    for key in ("<Key-Return>", "<Key-KP_Enter>", "<Key-F2>"):
        assert press_key(table.body, key) == [str(table.body)]
    assert rows == [4, 4, 4]


def test_a_cut_off_mark_cannot_be_double_clicked(make_table, font):
    """A double-click where a mark that does not fit would be is no mark's."""
    table = marks_table(make_table)
    marks, doubles = [], []
    table.on_mark = lambda index, column, number: marks.append(number)
    table.on_double_click = lambda index, column: doubles.append(column)
    x0, y0, x1, y1 = table.mark_box(1, "flags", 2)      # SVC, while it fits
    table.set_width("flags", table._pad + 3 * font.measure("0") + table._pad)    # N, Z and a space
    assert table.mark_box(1, "flags", 2) is None
    table._double(SimpleNamespace(x=x0 + 1, y=(y0 + y1) // 2))        # where SVC began
    table._double(SimpleNamespace(x=(x0 + x1) // 2, y=(y0 + y1) // 2))   # past the column
    assert marks == [] and doubles == ["flags", None]


# Scroll bars only where needed ---------------------------------------------------

def test_the_vertical_scroll_bar_shows_only_while_the_rows_do_not_fit(make_table):
    table = make_table(count=5)
    table.fit(10 * table.row_height)
    assert table.vscroll.winfo_manager() == ""          # 5 rows fit: no scroll bar
    table.set_rows(30, table.row)
    assert table.vscroll.winfo_manager() == "grid"
    table.fit(40 * table.row_height)                    # the pane got taller: all fit
    assert table.vscroll.winfo_manager() == ""
    table.fit(29 * table.row_height + table.row_height // 2)    # the last row only in part
    assert table.vscroll.winfo_manager() == "grid"
    table.scroll_to(1)
    table.fit(30 * table.row_height)                    # all fit again: back at the top
    assert table.vscroll.winfo_manager() == "" and table.top == 0


def test_the_edges_of_a_coloured_cell_stay_above_it_when_the_table_gains_row_places(make_table):
    colour = "#99CCFF"
    table = make_table(count=30, row=lambda index: Row(
        (str(index), f"row {index}", ""), cell_backgrounds={"text": colour} if index == 1 else {}))
    table.fit(table.row_height * 4)
    table.fill(450)
    edges = table._raised[1]
    assert edges
    table.fit(table.row_height * 9)
    body = table.body
    order = list(body.find_all())
    cell = table.slots[1][1 + 2 * 1]
    assert body.itemcget(cell, "fill") == colour
    assert all(order.index(cell) < order.index(item) for item in table._raised[1])
    assert all(order.index(item) < order.index(table._rules[1]) for item in table._raised[1])


def test_the_registers_need_no_scroll_bar_at_a_normal_height(make_app, monkeypatch):
    """The Registers table shows no vertical scroll bar it does not need.

    The window is laid out at the size it starts with on a screen of TEST_SCREEN.
    """
    fixed_screen(monkeypatch)
    app = make_app()
    assert lay_out(app.root)
    table = app.registers.table
    assert table.count == 18 and table.body.winfo_height() >= 18 * table.row_height
    assert table.vscroll.winfo_manager() == table.hscroll.winfo_manager() == ""
    for pane, rows in ((app.registers, 18), (app.coproc10, 33), (app.coproc11, 33)):
        table = pane.table
        app.side.select(pane)
        assert pump(app.root)
        assert table.count == rows and table._available > 1
        assert bool(table.vscroll.winfo_manager()) == (table.body.winfo_height()
                                                       < rows * table.row_height)


def test_both_scroll_bars_are_decided_at_once_from_the_room(make_table):
    """The room is the body's size with the bars shown when it was measured, which a bar
    coming or going does not change: from any bars the table takes the same ones at once,
    and keeps them when the body gets the size they leave it."""
    table = make_table(count=10, columns=[Column("a", "A", 100), Column("b", "B", 100)])
    across, down = table.vscroll.winfo_reqwidth(), table.hscroll.winfo_reqheight()
    rows = 10 * table.row_height
    seen = set()
    # At the edges: the columns need 200 pixels, beside a vertical bar 200 + across; the rows
    # need rows pixels, above a horizontal bar rows + down.
    for width in (199, 200, 199 + across, 200 + across):
        for height in (rows - 1, rows, rows - 1 + down, rows + down):
            decided = set()
            for start in ((False, False), (True, False), (False, True), (True, True)):
                for bar, shown in zip((table.vscroll, table.hscroll), start):
                    show_bar(bar, shown)
                table._vscroll_shown, table._hscroll_shown = start
                for _ in range(2):              # the body gets the size the bars leave
                    vertical, horizontal = table._vscroll_shown, table._hscroll_shown
                    table._configured(SimpleNamespace(width=width - across * vertical,
                                                      height=height - down * horizontal))
                decided.add((table._vscroll_shown, table._hscroll_shown))
                assert (table._vscroll_shown, table._hscroll_shown) == (vertical, horizontal)
            assert len(decided) == 1, (width, height, decided)
            seen |= decided
    assert seen == {(False, False), (True, False), (False, True), (True, True)}
