# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The dotted texture of the toolbar's grip and the dividers."""

import tkinter as tk
from tkinter import ttk

import pytest
from conftest import native, new_root, pump

from ares.gui import bumps, style
from ares.gui.widgets import px


@pytest.fixture
def root():
    root = new_root()
    style.apply(root)
    yield root
    root.destroy()


def test_the_pattern_repeats_every_four_design_pixels_with_a_second_dot_at_its_half():
    points = set(bumps.dots(0, 0, 8, 8, 1))
    assert points == {(0, 0), (4, 0), (2, 2), (6, 2), (0, 4), (4, 4), (2, 6), (6, 6)}


def test_the_pattern_grows_with_the_display():
    points = bumps.dots(0, 0, 18, 18, 2.25)
    assert (0, 0) in points and (9, 0) in points and (4, 4) in points or (5, 5) in points


def test_the_dark_dots_lie_down_and_right_of_the_light_ones():
    light = bumps.dots(0, 0, 9, 9, 1)
    dark = bumps.dots(0, 0, 9, 9, 1, 1)
    assert {(x + 1, y + 1) for x, y in light if x < 8 and y < 8} <= set(dark)


def test_no_dot_leaves_its_box():
    for x, y in bumps.dots(3, 5, 40, 17, 2.25, 1):
        assert 3 <= x and x + 2 <= 40 and 5 <= y and y + 2 <= 17


def test_a_polygon_walks_every_dot_and_comes_back_on_its_own_line():
    path = bumps.outline([(0, 0), (4, 0)], 1)
    assert path[:10] == [0, 0, 1, 0, 1, 1, 0, 1, 0, 0]
    assert path[-4:] == [4, 0, 0, 0]
    assert bumps.outline([], 1) == []


def test_a_texture_is_two_polygons_however_many_dots_it_has(root):
    canvas = tk.Canvas(root, width=1000, height=20)
    bumps.draw(canvas, 0, 0, 1000, 20)
    items = canvas.find_all()
    assert len(items) == 2 and {canvas.type(item) for item in items} == {"polygon"}
    assert [str(canvas.itemcget(item, "fill")).upper() for item in items] == \
        [style.HIGHLIGHT, style.GRID]


@pytest.fixture
def split(root):
    root.geometry("400x300")
    paned = ttk.PanedWindow(root, orient="horizontal")
    paned.pack(fill="both", expand=True)
    first, second = tk.Frame(paned, width=200, height=300), tk.Frame(paned, width=190, height=300)
    paned.add(first)
    paned.add(second)
    native(root)
    assert pump(root)
    paned.sashpos(0, 200)
    assert pump(root)
    return paned, first


def test_a_divider_lies_on_its_sash_and_follows_it(split):
    paned, first = split
    divider = bumps.Divider(paned, first, 10)
    pump(paned)
    divider.place()
    assert divider.canvas.place_info()["x"] == str(paned.sashpos(0))
    paned.sashpos(0, 120)
    divider.place()
    assert divider.canvas.place_info()["x"] == str(paned.sashpos(0))


def test_dragging_a_divider_moves_its_sash(split, monkeypatch):
    paned, first = split
    position = [200]        # a hidden paned window keeps no sash: this one stands in for it
    monkeypatch.setattr(paned, "sashpos", lambda index, new=None: (
        position.__setitem__(0, new) if new is not None else None) or position[0])
    divider = bumps.Divider(paned, first, 10)
    divider.place()
    divider.canvas.winfo_id()
    divider.canvas.event_generate("<ButtonPress-1>", x=4, y=50)
    divider.canvas.event_generate("<B1-Motion>", x=-46, y=50)
    divider.canvas.event_generate("<ButtonRelease-1>", x=-46, y=50)
    assert position == [150]
    assert divider.canvas.place_info()["x"] == "150"


def test_the_window_has_two_dotted_dividers_and_a_dotted_grip(app):
    assert [divider.paned for divider in app.dividers] == [app.main_split, app.left_split]
    assert app.dividers[0].canvas.cget("cursor") == "sb_h_double_arrow"
    assert app.dividers[1].canvas.cget("cursor") == "sb_v_double_arrow"
    kinds = [app.grip.type(item) for item in app.grip.find_all()]
    assert kinds == ["rectangle"] * px(app.root, style.TOOL_BUTTON) + ["polygon"] * 2


def test_the_lines_of_the_window(app):
    assert str(app.toolbar_line.cget("background")).upper() == style.BAR_LINE
    colours = [str(line.cget("background")).upper() for line in app.body_lines]
    assert colours == [style.GRID, style.GRID, style.HIGHLIGHT, style.HIGHLIGHT]
    assert len(app.left_lines) == 4


def test_a_press_on_a_divider_keeps_an_open_register_field(app):
    canvas = app.dividers[0].canvas
    calls = []
    app.registers.pressed_elsewhere = lambda: calls.append(1)
    canvas.winfo_id()
    canvas.event_generate("<ButtonPress-1>", x=2, y=2)
    canvas.event_generate("<ButtonRelease-1>", x=2, y=2)
    assert calls == []


def test_a_divider_has_its_dots_and_a_gray_line_along_its_far_edge(split):
    paned, first = split
    divider = bumps.Divider(paned, first, 10)
    divider.draw(300)
    canvas = divider.canvas
    kinds = [canvas.type(item) for item in canvas.find_all()]
    assert kinds == ["polygon", "polygon", "rectangle"]
    line = canvas.find_all()[-1]
    assert str(canvas.itemcget(line, "fill")).upper() == style.GRID
    assert canvas.coords(line) == [10 - px(canvas, 1), 0, 10, 300]
