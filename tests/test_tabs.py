# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Slanted tabs: where they are, what they draw, and that the mouse and keys still work."""

import tkinter as tk
from tkinter import ttk

import pytest
from conftest import new_root, pump

from ares.gui import style, tabs
from ares.gui.widgets import px


def press(book, x, y):
    """Press the mouse's first button on the strip."""
    book.strip.winfo_id()
    book.strip.event_generate("<ButtonPress-1>", x=x, y=y)


@pytest.fixture
def root():
    root = new_root()
    style.apply(root)
    yield root
    root.destroy()


@pytest.fixture
def book(root):
    notebook = tabs.Notebook(root)
    notebook.place(x=0, y=0, width=600, height=300)
    for title in ("Edit", "Execute", "Registers"):
        notebook.add(tk.Frame(notebook), text=title)
    root.update()
    return notebook


def test_a_tab_has_its_top_left_corner_cut():
    box = tabs.TabBox(0, 10, 60, 2, 21, "Edit", False, True, False)
    assert tabs.outline(box, 5) == (10, 21, 10, 7, 15, 2, 60, 2, 60, 21)


def test_tabs_are_as_wide_as_their_text_with_room_at_the_sides(book):
    boxes = book.boxes(600)
    side = px(book, style.TAB_SIDE)
    assert boxes[0].x == px(book, style.TAB_LEFT)
    assert [box.right - box.x for box in boxes] == [book.font.measure(box.text) + 2 * side
                                                    for box in boxes]
    assert [box.right for box in boxes[:-1]] == [box.x for box in boxes[1:]]    # they touch
    assert [box.text for box in boxes] == ["Edit", "Execute", "Registers"]
    assert [box.top for box in boxes] == [px(book, style.TAB_TOP)] * 3
    assert boxes[0].bottom - boxes[0].top == px(book, style.TAB_HEIGHT)


def test_only_the_tab_on_top_is_selected(book):
    assert [box.selected for box in book.boxes(600)] == [True, False, False]
    book.select(2)
    assert [box.selected for box in book.boxes(600)] == [False, False, True]


def test_too_many_tabs_share_the_room_and_shorten_their_text(book):
    room = 120
    boxes = book.boxes(room + px(book, style.TAB_LEFT))
    assert boxes[-1].right <= room + px(book, style.TAB_LEFT)
    assert any(box.text.endswith(tabs.ELLIPSIS) for box in boxes)


def test_fit_text_keeps_what_fits():
    assert tabs.fit_text("abcdef", 6, len) == "abcdef"
    assert tabs.fit_text("abcdef", 5, len) == "ab..."
    assert tabs.fit_text("abcdef", 2, len) == ""


def test_squeeze_takes_from_the_largest_first():
    assert tabs.squeeze([10, 50, 40], 100) == [10, 50, 40]
    assert tabs.squeeze([10, 50, 40], 90) == [10, 40, 40]
    assert sum(tabs.squeeze([10, 50, 40], 60)) <= 60
    assert tabs.squeeze([], 10) == []


def test_the_corner_cut_off_a_tab_belongs_to_the_tab_before_it(book):
    first, second, _ = book.boxes()
    assert book.tab_at(first.x + 1, first.top + 1) is None
    assert book.tab_at(second.x + 1, second.top + 1) == 0
    assert book.tab_at(second.x + 10, second.top + 10) == 1
    assert book.tab_at(first.x + 1, first.bottom + 1) is None       # below the tabs


def test_a_press_brings_a_tab_to_the_front_and_gives_the_notebook_the_focus(book):
    seen = []
    book.bind("<<NotebookTabChanged>>", lambda event: seen.append(book.index("current")), add="+")
    box = book.boxes()[1]
    press(book, box.x + 15, box.top + 10)
    assert book.index("current") == 1
    pump(book)
    assert seen[-1] == 1


def test_a_press_outside_the_tabs_does_nothing(book):
    press(book, 590, 5)
    assert book.index("current") == 0


def test_a_disabled_tab_stays_behind(book):
    book.tab(1, state="disabled")
    box = book.boxes()[1]
    press(book, box.x + 15, box.top + 10)
    assert book.index("current") == 0


def test_on_press_can_take_a_press_over(book):
    pressed = []
    book.on_press = lambda index: pressed.append(index) or True
    box = book.boxes()[2]
    press(book, box.x + 15, box.top + 10)
    assert pressed == [2] and book.index("current") == 0


def colours(canvas):
    return {str(canvas.itemcget(item, "fill")).upper() for item in canvas.find_all()
            if canvas.type(item) in ("rectangle", "polygon", "line")}


def test_the_strip_draws_the_tabs_and_the_lines_of_the_page(book):
    book.draw()
    assert {style.TAB, style.TAB_BORDER, style.GRID, style.HIGHLIGHT, style.FACE} <= \
        colours(book.strip)
    texts = [book.strip.itemcget(item, "text") for item in book.strip.find_all()
             if book.strip.type(item) == "text"]
    assert sorted(texts) == ["Edit", "Execute", "Registers"]
    assert all(book.strip.type(item) != "image" for item in book.strip.find_all())


def test_the_drawing_follows_a_new_title_and_a_new_tab(book):
    book.tab(0, text="Changed")
    book.add(tk.Frame(book), text="Later")
    pump(book)
    texts = {book.strip.itemcget(item, "text") for item in book.strip.find_all()
             if book.strip.type(item) == "text"}
    assert {"Changed", "Later"} <= texts


@pytest.mark.parametrize("sequence", ["<Enter>", "<Motion>"])
def test_the_close_button_under_the_mouse_is_the_raised_one(root, sequence):
    normal, raised = tk.PhotoImage(master=root, width=8, height=8), tk.PhotoImage(
        master=root, width=8, height=8)
    book = tabs.ClosableNotebook(root, (normal, raised))
    book.place(x=0, y=0, width=600, height=300)
    book.add(tk.Frame(book), text="a.s")
    book.add(tk.Frame(book), text="b.s")
    root.update()
    book.strip.winfo_id()
    box = book.boxes()[1]
    x0, y0, x1, y1 = book.close_box(box)
    book.strip.event_generate(sequence, x=x0 + 2, y=y0 + 2)
    assert book._hover == 1
    book.draw()
    assert [book.strip.itemcget(item, "image") for item in book.strip.find_all()
            if book.strip.type(item) == "image"] == [str(raised), str(normal)]      # the selected tab comes last
    book.strip.event_generate("<Leave>")
    assert book._hover is None


def test_closing_the_notebook_leaves_nothing_waiting(root):
    notebook = tabs.Notebook(root)
    notebook.add(tk.Frame(notebook), text="One")
    notebook.destroy()
    root.update()


def test_the_strip_lies_over_the_row_of_the_tabs(make_mapped_app):
    """In a mapped window the real tabs' row ends where the strip's own lines begin."""
    app = make_mapped_app()
    book = app.side
    app.root.update()
    page = app.registers
    top = style.page_padding(book)[1]
    assert page.winfo_y() - top == book.row
    assert book.strip.winfo_height() == book.row + 2 * book.ring
    assert book.strip.winfo_width() == book.winfo_width()


def test_the_keys_of_a_notebook_still_change_the_tab(make_mapped_app):
    app = make_mapped_app()
    book = app.side
    box = book.boxes()[0]
    app.root.update()
    press(book, box.x + 15, box.top + 10)
    app.root.update()
    assert app.root.focus_get() is book
    for key, expected in (("<Key-Right>", 1), ("<Key-Right>", 2), ("<Key-Left>", 1)):
        book.event_generate(key)
        app.root.update()
        assert book.index("current") == expected
    book.event_generate("<Control-Key-Tab>")
    app.root.update()
    assert book.index("current") == 2


def test_the_selected_tab_shows_the_keyboard_focus(make_mapped_app):
    app = make_mapped_app()
    book = app.side
    box = book.boxes()[0]
    app.root.update()
    book.draw()
    assert style.MENU_SELECTION not in colours(book.strip)
    press(book, box.x + 15, box.top + 10)
    app.root.update()
    book.draw()
    assert style.MENU_SELECTION in colours(book.strip)


def test_the_real_tab_row_stays_a_ttk_notebook(book):
    assert isinstance(book, ttk.Notebook)
    assert book.winfo_class() == "TNotebook"


def selected_fill(book):
    """The texts on the tab the strip paints as selected: the widest item of its colour."""
    canvas = book.strip
    book.update()
    fills = [canvas.bbox(item) for item in canvas.find_all() if canvas.type(item) == "polygon"
             and str(canvas.itemcget(item, "fill")).upper() == style.TAB]
    x0, _, x1, _ = max(fills, key=lambda box: box[2] - box[0])      # not a cut-off corner
    return next(canvas.itemcget(item, "text") for item in canvas.find_all()
                if canvas.type(item) == "text" and x0 <= canvas.bbox(item)[0] <= x1)


def test_a_plain_bind_of_the_user_keeps_the_strip_up_to_date(make_mapped_app):
    app = make_mapped_app()
    book = app.side
    book.bind("<<NotebookTabChanged>>", lambda event: None)
    app.root.update()
    book.select(2)
    assert selected_fill(book) == "Coproc 11"
    book.select(1)
    assert selected_fill(book) == "Coproc 10"


def test_the_file_tabs_paint_the_tab_on_top(make_mapped_app):
    app = make_mapped_app()
    first = app.editor.new_file()
    second = app.editor.new_file()
    app.root.update()
    book = app.editor.notebook
    assert selected_fill(book) == second.title()
    app.editor.select(first)
    assert selected_fill(book) == first.title()
    box = book.boxes()[1]
    book.strip.event_generate("<ButtonPress-1>", x=box.x + 15, y=box.top + 10)
    book.strip.event_generate("<ButtonRelease-1>", x=box.x + 15, y=box.top + 10)
    assert selected_fill(book) == second.title()


@pytest.fixture
def many(root):
    normal, raised = tk.PhotoImage(master=root, width=14, height=14), tk.PhotoImage(
        master=root, width=14, height=14)
    book = tabs.ClosableNotebook(root, (normal, raised))
    book.images = normal, raised
    book.place(x=0, y=0, width=1200, height=300)
    for number in range(45):
        book.add(tk.Frame(book), text=f"untitled{number}.s")
    book.select(5)
    root.update()
    return book


def test_a_narrow_tab_is_selected_by_a_click_not_closed(many):
    boxes = many.boxes(1200)
    narrow = boxes[10]
    assert narrow.right - narrow.x < many._natural_width("ab")
    assert many.close_box(narrow) is None
    assert boxes[-1].right <= 1200


def test_the_selected_tab_keeps_its_close_button_and_some_text(many):
    box = many.boxes(1200)[5]
    assert box.selected and many.close_box(box) is not None
    assert box.text.endswith(tabs.ELLIPSIS) and len(box.text) > len(tabs.ELLIPSIS)
