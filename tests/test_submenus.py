# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The submenus of ARES's own menus: the arrow, the place beside the menu, the keyboard, the
mouse and the keyboard focus. File > Open Example is the submenu of these tests; a small
bar of their own shows what the window's menus do not have.

As in test_menubar, a hidden window never has the focus, so a test says where it is and
runs the bindings of a key; the mouse's events go to the menus' canvases.
"""

import sys
import time
import tkinter as tk

import pytest
from conftest import new_root, pump
from test_gui_clicks import click_item, click_title, closed
from test_menubar import bar  # noqa: F401  (a fixture)
from test_menubar import (EDIT, FILE, editor_text, entry_index, focus_on, item_point, key, made,
                          mouse, note_menu_keys, rings_of, tap, title_point)

from ares.gui import menubar as menubar_module
from ares.gui import style
from ares.gui.menubar import (ARROW, RIGHT_SPACE, DropDown, MenuBar, menu_arrow, new_menu,
                              place_submenu)
from ares.gui.style import HIGHLIGHT, MENU_SELECTION, SHADOW, TEXT
from ares.gui.widgets import px


def cascade(bar):
    """(the File menu, the index of Open Example in it, its submenu)."""
    menu = bar.menus[FILE]
    index = entry_index(menu, "Open Example")
    return menu, index, menu.entries[index].menu


def on_the_item(bar, app, monkeypatch):
    """File open from the keyboard with Open Example highlighted; the bar has the focus.
    Returns what cascade() does."""
    menu, index, sub = cascade(bar)
    bar.open(FILE)
    menu.highlight(index)
    focus_on(app, monkeypatch, bar)
    return menu, index, sub


def sub_open(bar):
    """The menu open, with its submenu open beside it by a press on the item."""
    menu, index, sub = cascade(bar)
    bar.open(FILE)
    bar.open_submenu(index)
    return menu, index, sub


@pytest.fixture
def quick(monkeypatch):
    """The wait of the mouse takes a millisecond; settle() lets it pass."""
    monkeypatch.setattr(menubar_module, "SUBMENU_DELAY", 1)

    def settle(widget):
        time.sleep(0.01)
        pump(widget)
    return settle


@pytest.fixture
def fruit(monkeypatch):
    """A bar of its own, one menu: Apple, a submenu Berries (with Rasp and Straw), and a
    submenu Citrus that is gray. Chosen items are noted in bar.chosen."""
    root = new_root()
    style.apply(root)
    note_menu_keys(root)
    monkeypatch.setattr(root, "focus_get", lambda: bar)
    bar = MenuBar(root)
    bar.pack(fill="x")
    bar.chosen = []
    menu = new_menu(bar)
    bar.add_cascade(label="Fruit", menu=menu, underline=0)
    menu.add_command(label="Apple", underline=0, command=lambda: bar.chosen.append("Apple"))
    berries = new_menu(menu)
    for label in ("Rasp", "Straw"):
        berries.add_command(label=label, underline=0,
                            command=lambda label=label: bar.chosen.append(label))
    menu.add_cascade(label="Berries", menu=berries, underline=0)
    citrus = new_menu(menu)
    citrus.add_command(label="Lime", command=lambda: bar.chosen.append("Lime"))
    menu.add_cascade(label="Citrus", menu=citrus, underline=0)
    menu.entryconfigure(2, state="disabled")
    yield bar
    root.destroy()


# tk.Menu's interface ----------------------------------------------------------------------

def test_a_dropdown_answers_for_its_submenu_as_tk_menu_does(bar, app):
    menu, index, sub = cascade(bar)
    assert isinstance(sub, DropDown) and sub.bar is bar
    assert menu.type(index) == "cascade"
    assert app.root.nametowidget(menu.entrycget(index, "menu")) is sub
    assert menu.enabled(index) and menu.entrycget(index, "accelerator") == ""


def test_new_menu_of_a_tk_menu_is_a_tk_menu_inside_it(make_app, monkeypatch):
    monkeypatch.setattr(menubar_module, "is_aqua", lambda widget: True)
    app = make_app()
    menu = app.root.nametowidget(app.menubar.entrycget(FILE, "menu"))
    index = next(k for k in range(menu.index("end") + 1) if menu.type(k) == "cascade")
    assert menu.entrycget(index, "label") == "Open Example"
    sub = app.root.nametowidget(menu.entrycget(index, "menu"))
    assert type(sub) is tk.Menu and sub.master is menu and sub.cget("tearoff") == 0
    assert sub.index("end") + 1 == len(app.examples)


def test_the_submenus_are_laid_out_with_their_menus_at_start_up(bar):
    pump(bar)
    assert cascade(bar)[2]._laid_out


# The arrow --------------------------------------------------------------------------------

def bounds(canvas, item):
    coords = canvas.coords(item)
    return (min(coords[::2]), min(coords[1::2]), max(coords[::2]), max(coords[1::2]))


def test_the_arrow_is_seven_pixels_high_and_points_right():
    assert ARROW == (1, 2, 3, 4, 3, 2, 1)
    points = menu_arrow(10, 20, 2)
    xs, ys = points[::2], points[1::2]
    assert (min(xs), max(xs), min(ys), max(ys)) == (10, 18, 20, 34)
    # The tip of the arrow: the row of four pixels, the longest, in the middle.
    assert [y for x, y in zip(xs, ys) if x == 18] == [26, 28]


def test_the_arrow_lies_right_of_where_the_shortcuts_end_and_adds_no_width(bar, app):
    menu, index, _ = cascade(bar)
    menu.lay_out()
    root = app.root
    entry = menu.entries[index]
    right = menu._sides[1]
    x0, y0, x1, y1 = bounds(menu.canvas, entry.arrow)
    pixel = max(1, round(root.winfo_fpixels("1i") / 96))
    assert (x1 - x0, y1 - y0) == (4 * pixel, 7 * pixel)
    assert right - px(root, RIGHT_SPACE) <= x0 and x1 <= right
    assert abs((y0 + y1) / 2 - (entry.top + entry.bottom) / 2) <= 1
    texts = max(bar.font.measure(e.label) for e in menu.entries if e.kind != "separator")
    keys = max(bar.font.measure(e.accelerator) for e in menu.entries if e.accelerator)
    assert menu.width == 2 * menu._sides[0] + px(root, 17) + texts + px(root, 12) + keys + \
        px(root, 13)


def test_a_plain_item_has_no_arrow(bar):
    menu, _, _ = cascade(bar)
    assert [e.label for e in menu.entries if e.arrow is not None] == ["Open Example"]


def test_the_arrow_is_dark_and_stays_dark_on_the_highlight(bar):
    menu, index, _ = cascade(bar)
    bar.open(FILE)
    entry = menu.entries[index]
    assert menu.canvas.itemcget(entry.arrow, "fill").upper() == TEXT
    assert menu.canvas.itemcget(entry.arrow_shadow, "state") == "hidden"
    menu.highlight(index)
    assert menu.canvas.itemcget(entry.arrow, "fill").upper() == TEXT
    assert menu.canvas.itemcget(menu._lit, "fill").upper() == MENU_SELECTION


def test_a_gray_items_arrow_is_etched_and_gray_on_the_highlight(fruit):
    menu = fruit.menus[0]
    fruit.open(0)
    entry = menu.entries[2]
    canvas = menu.canvas
    ring = px(fruit, 1)
    assert canvas.itemcget(entry.arrow, "fill").upper() == SHADOW
    assert canvas.itemcget(entry.arrow_shadow, "fill").upper() == HIGHLIGHT
    assert canvas.itemcget(entry.arrow_shadow, "state") != "hidden"
    assert canvas.find_below(entry.arrow) == (entry.arrow_shadow,)
    first, second = bounds(canvas, entry.arrow), bounds(canvas, entry.arrow_shadow)
    assert (second[0], second[1]) == (first[0] + ring, first[1] + ring)
    menu.highlight(2)
    assert canvas.itemcget(entry.arrow, "fill").upper() == SHADOW
    assert canvas.itemcget(entry.arrow_shadow, "state") == "hidden"


# The place beside the menu ------------------------------------------------------------------

def test_a_submenu_goes_to_the_right_flips_to_the_left_and_stays_on_the_screen():
    screen = (0, 0, 1000, 800)
    assert place_submenu(100, 300, 50, (200, 300), screen) == (300, 50)       # at the right
    assert place_submenu(600, 800, 50, (200, 300), screen) == (800, 50)       # just fits
    assert place_submenu(601, 801, 50, (200, 300), screen) == (401, 50)       # flipped
    assert place_submenu(100, 900, 50, (200, 300), screen) == (800, 50)       # fits neither side
    assert place_submenu(100, 300, 600, (200, 300), screen) == (300, 500)     # moved up
    assert place_submenu(100, 300, 50, (200, 900), screen) == (300, 0)        # higher than it all
    assert place_submenu(1300, 1900, 50, (200, 300), (1000, 0, 2000, 800)) == (1100, 50)


def spot_of(menu):
    x, y = menu.tk.call("wm", "geometry", menu).split("+")[1:]
    return int(x), int(y)


def test_the_submenu_opens_beside_its_item_with_its_first_item_level(bar, app, monkeypatch):
    monkeypatch.setattr(menubar_module, "screen_area", lambda widget, x, y: (0, 0, 5000, 5000))
    menu, index, sub = sub_open(bar)
    x, y = spot_of(menu)
    frame = menu._sides[0]
    assert spot_of(sub) == (x + menu.width - frame, y + menu.entries[index].top - frame)
    assert sub.entries[0].top == frame


def test_the_submenu_flips_at_the_edge_of_the_work_area(bar, app, monkeypatch):
    monkeypatch.setattr(menubar_module, "screen_area", lambda widget, x, y: (0, 0, 5000, 5000))
    menu, index, sub = cascade(bar)
    bar.open(FILE)
    x, y = spot_of(menu)
    sub.lay_out()
    frame = menu._sides[0]
    edge = x + menu.width - frame + sub.width - 1           # one pixel short of the room
    asked = []

    def area(widget, ax, ay):
        asked.append((ax, ay))
        return -5000, -5000, edge, 5000
    monkeypatch.setattr(menubar_module, "screen_area", area)
    bar.open_submenu(index)
    assert spot_of(sub)[0] == x + frame - sub.width
    assert asked[-1] == (x, y + menu.entries[index].top - frame)    # the menu's own monitor


# The keyboard -------------------------------------------------------------------------------

@pytest.mark.parametrize("keysym, char", [("Right", ""), ("Return", ""), ("KP_Enter", ""),
                                          ("e", "e"), ("E", "E")])
def test_right_enter_or_its_letter_open_it_at_once(bar, app, monkeypatch, hidden_windows, keysym,
                                                   char):
    menu, index, sub = on_the_item(bar, app, monkeypatch)
    key(bar, keysym, *(("Shift",) if keysym == "E" else ()), char=char)
    assert bar.sub_menu is sub and sub.active == 0 and hidden_windows.shows(sub)
    assert bar.open_menu is menu and menu.active == index and bar.active
    assert hidden_windows.shows(menu)


def test_the_keys_then_work_in_the_submenu(bar, app, monkeypatch):
    menu, index, sub = on_the_item(bar, app, monkeypatch)
    key(bar, "Right")
    key(bar, "Down")
    assert sub.active == 1 and menu.active == index
    key(bar, "Up")
    key(bar, "Up")
    assert sub.active == len(sub.entries) - 1 and menu.active == index


@pytest.mark.parametrize("keysym", ["Left", "Escape"])
def test_left_or_escape_close_just_the_submenu(bar, app, monkeypatch, hidden_windows, keysym):
    menu, index, sub = on_the_item(bar, app, monkeypatch)
    key(bar, "Right")
    key(bar, keysym)
    assert bar.sub_menu is None and not hidden_windows.shows(sub)
    assert bar.open_menu is menu and menu.active == index and bar.selected == FILE
    assert hidden_windows.shows(menu) and sub.active is None


def test_escape_goes_back_one_step_at_a_time(bar, app, monkeypatch):
    text = editor_text(app)
    focus_on(app, monkeypatch, text)
    key(text, "f", "Alt")
    focus_on(app, monkeypatch, bar)
    key(bar, "e")
    assert bar.sub_menu is not None
    key(bar, "Escape")
    assert bar.sub_menu is None and bar.open_menu is bar.menus[FILE]
    key(bar, "Escape")
    assert bar.open_menu is None and bar.active
    key(bar, "Escape")
    assert not bar.active


def test_right_on_an_item_of_the_submenu_opens_the_menu_beside(bar, app, monkeypatch,
                                                               hidden_windows):
    _, _, sub = on_the_item(bar, app, monkeypatch)
    key(bar, "Right")
    key(bar, "Right")
    assert bar.sub_menu is None and not hidden_windows.shows(sub)
    assert bar.open_menu is bar.menus[EDIT] and bar.menus[EDIT].active == 0


def test_left_and_right_on_a_plain_item_still_open_the_menus_beside(bar, app, monkeypatch):
    menu, index, _ = on_the_item(bar, app, monkeypatch)
    menu.highlight(0)
    key(bar, "Right")
    assert bar.open_menu is bar.menus[EDIT] and bar.sub_menu is None


def test_left_on_the_item_itself_opens_the_menu_beside(bar, app, monkeypatch):
    on_the_item(bar, app, monkeypatch)
    key(bar, "Left")
    assert bar.selected == len(bar.menus) - 1 and bar.sub_menu is None


@pytest.mark.parametrize("keysym", ["Alt_L", "Alt_R", "F10"])
def test_alt_or_f10_close_everything(bar, app, monkeypatch, hidden_windows, keysym):
    text = editor_text(app)
    focus_on(app, monkeypatch, text)
    key(text, "f", "Alt")
    focus_on(app, monkeypatch, bar)
    key(bar, "e")
    sub = bar.sub_menu
    tap(bar, keysym)
    assert closed(bar, app) and bar.sub_menu is None and not hidden_windows.shows(sub)
    assert hidden_windows.focus is text


def test_enter_on_an_item_of_the_submenu_closes_all_then_runs_it(fruit, monkeypatch):
    fruit.open(0, first=True)
    key(fruit, "Down")                                      # Berries
    key(fruit, "Right")
    key(fruit, "Down")                                      # Straw
    seen = []
    menu = fruit.menus[0].entries[1].menu
    original = menu.entries[1].command
    menu.entries[1].command = lambda: seen.append((fruit.active, fruit.sub_menu)) or original()
    key(fruit, "Return")
    assert seen == [(False, None)] and fruit.chosen == ["Straw"]


def test_a_letter_of_the_submenu_chooses_there_and_not_in_the_menu(fruit):
    fruit.open(0, first=True)
    key(fruit, "b")
    key(fruit, "s")
    assert fruit.chosen == ["Straw"] and not fruit.active


def test_a_letter_several_examples_share_moves_among_them(bar, app, monkeypatch):
    _, _, sub = on_the_item(bar, app, monkeypatch)
    key(bar, "Right")
    names = []
    for _ in range(3):
        key(bar, "b")
        names.append(sub.entries[sub.active].label)
    assert names == ["bitmap_display.s", "branches.s", "bitmap_display.s"]
    assert bar.sub_menu is sub


def test_a_letter_nothing_in_the_submenu_has_rings(bar, app, monkeypatch):
    _, _, sub = on_the_item(bar, app, monkeypatch)
    key(bar, "Right")
    key(bar, "z")
    assert bar.rings == [1] and bar.sub_menu is sub


def test_a_gray_item_with_a_submenu_does_not_open(fruit):
    menu = fruit.menus[0]
    fruit.open(0)
    menu.highlight(2)
    key(fruit, "Right")
    assert fruit.sub_menu is None and fruit.selected == 0   # the only menu, beside itself
    menu = fruit.open_menu
    menu.highlight(2)
    key(fruit, "Return")
    assert fruit.sub_menu is None and fruit.open_menu is menu
    key(fruit, "c")
    assert fruit.sub_menu is None and menu.active == 2


def test_a_gray_item_of_the_submenu_does_nothing(fruit):
    menu = fruit.menus[0]
    sub = menu.entries[1].menu
    sub.entryconfigure(0, state="disabled")
    fruit.open(0)
    fruit.open_submenu(1, first=True)
    assert sub.active == 0
    key(fruit, "Return")
    assert fruit.chosen == [] and fruit.sub_menu is sub


def test_an_open_submenu_shows_a_change_of_state_at_once(fruit):
    sub = fruit.menus[0].entries[1].menu
    fruit.open(0)
    fruit.open_submenu(1)
    sub.entryconfigure(0, state="disabled")
    assert sub.canvas.itemcget(sub.entries[0].text, "fill").upper() == SHADOW


# The mouse --------------------------------------------------------------------------------

def test_resting_on_the_item_opens_it_after_a_moment_as_windows_does(bar, quick):
    assert menubar_module.SUBMENU_DELAY == 1
    menu, index, sub = cascade(bar)
    bar.open(FILE)
    mouse(menu.canvas, "<Motion>", *item_point(menu, index))
    assert bar.sub_menu is None and menu.active == index    # not yet
    quick(bar)
    assert bar.sub_menu is sub and sub.active is None and menu.active == index


def test_the_wait_is_that_of_windows():
    assert menubar_module.SUBMENU_DELAY == 400


def test_moving_on_before_the_moment_is_over_opens_nothing(bar, quick):
    menu, index, _ = cascade(bar)
    bar.open(FILE)
    mouse(menu.canvas, "<Motion>", *item_point(menu, index))
    assert bar._wait_job is not None
    mouse(menu.canvas, "<Motion>", *item_point(menu, 0))
    assert bar._wait_job is None                            # coming back, it waits afresh
    quick(bar)
    assert bar.sub_menu is None and menu.active == 0


def test_a_press_on_the_item_opens_it_at_once_and_its_release_leaves_it_open(bar, app, quick):
    menu, index, sub = cascade(bar)
    click_title(bar, FILE)
    point = item_point(menu, index)
    mouse(menu.canvas, "<Motion>", *point)
    mouse(menu.canvas, "<ButtonPress-1>", *point)
    assert bar.sub_menu is sub and sub.active is None
    mouse(menu.canvas, "<ButtonRelease-1>", *point, held=True)
    assert bar.sub_menu is sub and bar.open_menu is menu
    mouse(menu.canvas, "<ButtonPress-1>", *point)           # pressed again: it stays
    mouse(menu.canvas, "<ButtonRelease-1>", *point, held=True)
    assert bar.sub_menu is sub


def test_a_title_pressed_and_released_on_the_item_opens_it(bar, app):
    menu, index, sub = cascade(bar)
    mouse(bar.canvas, "<ButtonPress-1>", *title_point(bar, FILE))
    mouse(menu.canvas, "<Motion>", *item_point(menu, index), held=True)
    mouse(menu.canvas, "<ButtonRelease-1>", *item_point(menu, index), held=True)
    assert bar.sub_menu is sub and bar.active


def test_the_mouse_highlights_in_the_submenu_and_the_item_stays_highlighted(bar):
    menu, index, sub = sub_open(bar)
    mouse(sub.canvas, "<Motion>", *item_point(sub, 2))
    assert sub.active == 2 and menu.active == index
    mouse(sub.canvas, "<Motion>", 1, 1)                     # on its border
    assert sub.active is None and menu.active == index and bar.sub_menu is sub


def test_moving_back_onto_the_item_keeps_it_open(bar, quick):
    menu, index, sub = sub_open(bar)
    mouse(sub.canvas, "<Motion>", *item_point(sub, 2))
    mouse(menu.canvas, "<Motion>", *item_point(menu, index))
    quick(bar)
    assert bar.sub_menu is sub and sub.active is None and menu.active == index


def test_moving_onto_another_item_closes_it_after_the_moment(bar, hidden_windows, quick):
    menu, index, sub = sub_open(bar)
    mouse(menu.canvas, "<Motion>", *item_point(menu, 0))
    assert menu.active == 0 and bar.sub_menu is sub         # the way into it may cross items
    quick(bar)
    assert bar.sub_menu is None and not hidden_windows.shows(sub) and menu.active == 0


def test_the_way_into_the_submenu_may_cross_other_items(bar, quick):
    menu, index, sub = sub_open(bar)
    mouse(menu.canvas, "<Motion>", *item_point(menu, index + 1))
    mouse(sub.canvas, "<Motion>", *item_point(sub, 0))
    assert menu.active == index                             # its item highlighted again
    quick(bar)
    assert bar.sub_menu is sub and sub.active == 0


def test_the_way_back_to_the_item_may_cross_other_items_too(bar, quick):
    menu, index, sub = sub_open(bar)
    mouse(menu.canvas, "<Motion>", *item_point(menu, 0))
    assert bar._wait_job is not None
    mouse(menu.canvas, "<Motion>", *item_point(menu, index))
    assert bar._wait_job is None
    quick(bar)
    assert bar.sub_menu is sub


def test_leaving_the_menus_keeps_the_submenu_and_its_item_highlighted(bar, quick):
    menu, index, sub = sub_open(bar)
    mouse(sub.canvas, "<Motion>", *item_point(sub, 2))
    mouse(bar, "<Motion>", -3000, -3000)                    # far away, brought by the grab
    quick(bar)
    assert bar.sub_menu is sub and sub.active is None and menu.active == index


def test_a_click_on_an_item_of_the_submenu_closes_all_and_runs_it(fruit):
    menu = fruit.menus[0]
    sub = menu.entries[1].menu
    fruit.open(0)
    fruit.open_submenu(1)
    point = item_point(sub, 1)
    mouse(sub.canvas, "<Motion>", *point)
    mouse(sub.canvas, "<ButtonPress-1>", *point)
    assert fruit.sub_menu is sub and fruit.chosen == []     # a press there closes nothing
    mouse(sub.canvas, "<ButtonRelease-1>", *point, held=True)
    assert fruit.chosen == ["Straw"] and not fruit.active and fruit.sub_menu is None


def test_a_click_on_a_gray_item_of_the_submenu_leaves_it_open(fruit):
    sub = fruit.menus[0].entries[1].menu
    sub.entryconfigure(0, state="disabled")
    fruit.open(0)
    fruit.open_submenu(1)
    point = item_point(sub, 0)
    mouse(sub.canvas, "<ButtonPress-1>", *point)
    mouse(sub.canvas, "<ButtonRelease-1>", *point, held=True)
    assert fruit.chosen == [] and fruit.sub_menu is sub


def test_a_press_dragged_from_the_title_into_the_submenu_chooses_on_release(fruit, quick):
    menu = fruit.menus[0]
    sub = menu.entries[1].menu
    mouse(fruit.canvas, "<ButtonPress-1>", *title_point(fruit, 0))
    mouse(menu.canvas, "<Motion>", *item_point(menu, 1), held=True)
    quick(fruit)
    assert fruit.sub_menu is sub
    mouse(sub.canvas, "<Motion>", *item_point(sub, 0), held=True)
    mouse(sub.canvas, "<ButtonRelease-1>", *item_point(sub, 0), held=True)
    assert fruit.chosen == ["Rasp"] and not fruit.active


def test_a_click_on_another_item_of_the_menu_runs_it_with_the_submenu_open(fruit):
    menu = fruit.menus[0]
    fruit.open(0)
    fruit.open_submenu(1)
    point = item_point(menu, 0)
    mouse(menu.canvas, "<ButtonPress-1>", *point)
    mouse(menu.canvas, "<ButtonRelease-1>", *point, held=True)
    assert fruit.chosen == ["Apple"] and not fruit.active and fruit.sub_menu is None


def test_a_gray_item_with_a_submenu_does_not_open_under_the_mouse(fruit, quick):
    menu = fruit.menus[0]
    fruit.open(0)
    point = item_point(menu, 2)
    mouse(menu.canvas, "<Motion>", *point)
    quick(fruit)
    mouse(menu.canvas, "<ButtonPress-1>", *point)
    mouse(menu.canvas, "<ButtonRelease-1>", *point, held=True)
    assert fruit.sub_menu is None and fruit.open_menu is menu


def test_a_press_outside_closes_everything(bar, app, hidden_windows):
    _, _, sub = sub_open(bar)
    mouse(bar, "<ButtonPress-1>", -3000, -3000)             # brought to the bar by its grab
    mouse(bar, "<ButtonRelease-1>", -3000, -3000, held=True)
    assert closed(bar, app) and bar.sub_menu is None and not hidden_windows.shows(sub)


def test_moving_to_another_title_closes_the_submenu(bar, app, hidden_windows):
    _, _, sub = sub_open(bar)
    mouse(bar.canvas, "<Motion>", *title_point(bar, EDIT))
    assert bar.open_menu is bar.menus[EDIT] and bar.sub_menu is None
    assert not hidden_windows.shows(sub)


def test_a_press_on_the_open_title_closes_everything(bar, app):
    menu, index, sub = cascade(bar)
    click_title(bar, FILE)
    bar.open_submenu(index)
    click_title(bar, FILE)
    assert closed(bar, app) and bar.sub_menu is None


def test_where_windows_overlap_the_one_the_event_came_to_decides(bar):
    """The submenu lies over the menu's right side, and may come over the bar: a point in
    two of them is in the one that got the event, and for the bar's grab in the submenu."""
    menu, index, sub = sub_open(bar)
    made(menu.canvas)
    made(sub.canvas)
    made(bar.canvas)
    x = sub.canvas.winfo_rootx() + sub.width // 2
    y = sub.canvas.winfo_rooty() + sub.entries[0].bottom - 1
    assert bar._locate(x, y, sub.canvas)[0] == "sub"
    assert bar._locate(x, y, bar)[0] == "sub"


def test_a_key_stops_the_wait_of_the_mouse(bar, app, monkeypatch, quick):
    menu, index, sub = cascade(bar)
    bar.open(FILE)
    focus_on(app, monkeypatch, bar)
    mouse(menu.canvas, "<Motion>", *item_point(menu, index))
    key(bar, "Down")
    quick(bar)
    assert bar.sub_menu is None and menu.active == index + 1


def test_a_key_puts_the_highlight_back_on_the_item_of_the_open_submenu(bar, app, monkeypatch,
                                                                       quick):
    menu, index, sub = sub_open(bar)
    focus_on(app, monkeypatch, bar)
    mouse(menu.canvas, "<Motion>", *item_point(menu, 0))
    key(bar, "Down")
    quick(bar)
    assert bar.sub_menu is sub and menu.active == index and sub.active == 0


def test_closing_stops_the_wait_of_the_mouse(bar, app, quick):
    menu, index, _ = cascade(bar)
    bar.open(FILE)
    mouse(menu.canvas, "<Motion>", *item_point(menu, index))
    bar.close()
    assert bar._wait_job is None
    quick(bar)
    assert closed(bar, app) and bar.sub_menu is None


def test_a_bar_destroyed_during_the_wait_leaves_no_job(monkeypatch):
    root = new_root()
    try:
        monkeypatch.setattr(root, "focus_get", lambda: root)
        bar = MenuBar(root)
        menu = new_menu(bar)
        bar.add_cascade(label="Fruit", menu=menu, underline=0)
        sub = new_menu(menu)
        sub.add_command(label="Lime")
        menu.add_cascade(label="Citrus", menu=sub, underline=0)
        bar.open(0)
        mouse(menu.canvas, "<Motion>", *item_point(menu, 0))
        job = bar._wait_job
        assert job is not None
        bar.destroy()
        assert job not in root.tk.splitlist(root.tk.call("after", "info"))
    finally:
        root.destroy()


# The keyboard focus -------------------------------------------------------------------------

def test_the_bar_keeps_the_focus_with_the_submenu_open(bar, app, monkeypatch, hidden_windows):
    _, _, sub = sub_open(bar)
    hidden_windows.focus = None
    focus_on(app, monkeypatch, sub.canvas)                  # the submenu was given the focus
    made(bar).event_generate("<FocusOut>")
    assert bar.sub_menu is sub and hidden_windows.focus is bar


def test_a_press_that_activates_the_submenus_window_still_chooses(fruit, monkeypatch,
                                                                  hidden_windows):
    """As for a menu: the window takes the focus just before the press comes, and the menus
    must still be open for it."""
    root = fruit.winfo_toplevel()
    menu = fruit.menus[0]
    sub = menu.entries[1].menu
    fruit.open(0)
    fruit.open_submenu(1)
    monkeypatch.setattr(root, "focus_get", lambda: None)    # the main window loses the focus,
    made(fruit).event_generate("<FocusOut>")
    monkeypatch.setattr(root, "focus_get", lambda: sub.canvas)      # and the submenu gets it
    assert fruit.sub_menu is sub
    root.update_idletasks()
    assert fruit.sub_menu is sub and hidden_windows.focus is fruit
    point = item_point(sub, 0)
    mouse(sub.canvas, "<ButtonPress-1>", *point)
    mouse(sub.canvas, "<ButtonRelease-1>", *point, held=True)
    assert fruit.chosen == ["Rasp"]


def test_the_menus_close_when_the_focus_leaves_ares(bar, app, monkeypatch, hidden_windows):
    _, _, sub = sub_open(bar)
    focus_on(app, monkeypatch, None)
    made(bar).event_generate("<FocusOut>")
    app.root.update_idletasks()
    assert not bar.active and bar.sub_menu is None and not hidden_windows.shows(sub)


def test_moving_the_window_closes_the_submenu_too(bar, app, hidden_windows):
    _, _, sub = sub_open(bar)
    made(app.root).event_generate("<Configure>", x=40, y=50, width=900, height=700)
    assert not bar.active and not hidden_windows.shows(sub)


def test_a_shown_submenu_floats_above_without_taking_the_activation(bar, monkeypatch):
    noted = []
    monkeypatch.setattr(menubar_module, "float_inactive", noted.append)
    _, _, sub = cascade(bar)
    made(sub.canvas)
    sub.event_generate("<Map>")
    assert noted == [sub]


def test_a_shown_submenu_refuses_the_activation(bar, monkeypatch):
    if sys.platform != "win32":
        pytest.skip("Windows' activation")
    noted = []
    monkeypatch.setattr(menubar_module, "refuse_activation",
                        lambda window, frame: noted.append((window, frame)))
    _, _, sub = cascade(bar)
    made(sub)
    monkeypatch.setattr(sub, "winfo_viewable", lambda: True)
    menubar_module.float_inactive(sub)
    assert noted == [(sub, int(sub.wm_frame(), 16))]


def test_an_item_of_the_submenu_gives_the_focus_back_on_a_mapped_window(make_mapped_app):
    """The real focus of a window that is mapped: the bar takes it for the menus and the
    new tab has it after the choice."""
    app = make_mapped_app()
    bar = app.menubar
    if isinstance(bar, tk.Menu):
        pytest.skip("macOS keeps its screen menu bar")
    app.cmd_new()
    pump(app.root)
    first = app.editor.current
    first.text.focus_force()
    pump(app.root)
    assert app.root.focus_get() is first.text
    menu, index, sub = cascade(bar)
    bar.open(FILE)
    pump(app.root)
    assert app.root.focus_get() is bar
    bar.open_submenu(index, first=True)
    pump(app.root)
    assert app.root.focus_get() is bar and bar.sub_menu is sub
    bar.choose(entry_index(sub, "hello.s"), sub)
    pump(app.root)
    assert closed(bar, app) and bar.sub_menu is None
    assert app.editor.current is not first
    assert app.root.focus_get() is app.editor.current.text


def test_the_click_on_open_example_opens_its_submenu_and_a_title_click_closes_it(bar, app):
    menu, index, sub = cascade(bar)
    click_title(bar, FILE)
    click_item(menu, index)
    assert bar.sub_menu is sub
    click_title(bar, FILE)
    assert closed(bar, app)


def test_the_bevel_of_the_title_stays_pressed_in_with_a_submenu_open(bar, app):
    sub_open(bar)
    title = bar._titles[FILE]
    assert rings_of(bar.canvas, (title.x0, 0, title.x1, bar._title_height))["top"] == SHADOW
