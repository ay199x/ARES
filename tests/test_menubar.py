# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""ARES's own Windows 98 menu bar and its menus: the table, the look, the keyboard, the
mouse, the keyboard focus with an open register field, and the speed of opening a menu.

Hidden windows never get the keyboard focus: a test tells the window where the focus is
(focus_on) and runs the bindings Tk runs for a key (key()). The mouse's events are sent
to the canvases where Tk delivers them; while the bar is active its grab brings it the
events elsewhere in ARES, so a press outside is sent to the bar itself.
"""

import re
import time
import tkinter as tk
from types import SimpleNamespace

import pytest
from conftest import lay_out, new_root, pump
from test_gui_app import EXPECTED_MENUS, menu_table
from test_gui_editing import PROGRAM, ROW, bells, click, double_click, focus_moved, type_into
from test_gui_run import loaded
from test_responsiveness import pictures, tcl_word
from test_style import make_root  # noqa: F401  (a fixture: a root at a display scale)

from ares.gui import menubar as menubar_module
from ares.gui import style
from ares.gui.app import KEEP_FIELD, MENUS, SETTINGS_COMMANDS, SETTINGS_MENU, App
from ares.gui.menubar import (ITEM_HEIGHT, ITEM_ROOM, MENU_BAR_CLASS, SEPARATOR_HEIGHT,
                              TITLE_HEIGHT, TITLE_PADDING, TITLE_ROOM, DropDown, MenuBar,
                              access_letter, place_menu)
from ares.gui.style import (BAR_LINE, DARK_SHADOW, FACE, HIGHLIGHT, LIGHT, MENU_BAR, MENU_SELECTION,
                            SHADOW, TEXT, gradient)
from ares.gui.widgets import px

TITLES = ["File", "Edit", "Run", "Settings", "Tools", "Help"]
FILE, EDIT, RUN, SETTINGS, TOOLS, HELP = range(6)
STATES = {"Shift": 0x1, "Control": 0x4}


@pytest.fixture
def bar(app, monkeypatch):
    """The window's menu bar, its bell noted in bar.rings; Tk's own handling of Windows'
    menu keys is only noted (menu_keys)."""
    bar = app.menubar
    if isinstance(bar, tk.Menu):
        pytest.skip("macOS keeps its screen menu bar")
    note_menu_keys(app.root)
    focus_on(app, monkeypatch, app.root)
    bar.rings = []
    monkeypatch.setattr(bar, "bell", lambda: bar.rings.append(1))
    return bar


def note_menu_keys(root):
    """Replace Tk's procedures for Windows' own menu keys by ones that note their window."""
    root.tk.eval("""
        set ::menu_keys {}
        foreach name {::tk::WinMenuKey ::tk::TraverseToMenu ::tk::FirstMenu} {
            if {[info commands $name] ne ""} {rename $name {}}
            proc $name {w args} {lappend ::menu_keys $w}
        }
    """)


def menu_keys(root):
    return [str(w) for w in root.tk.splitlist(root.tk.eval("set ::menu_keys"))]


def focus_on(app, monkeypatch, widget):
    """The keyboard focus is on widget (None: ARES has none) from now on."""
    monkeypatch.setattr(app.root, "focus_get", lambda: widget)


def best_sequence(widget, tag, keysym, modifiers, release):
    """The sequence of tag's bindings a key event matches as Tk chooses it: one naming the
    key before one that does not, then the one with more modifiers."""
    found, rank = None, None
    for sequence in map(str, widget.tk.splitlist(widget.tk.call("bind", tag))):
        if sequence.startswith("<<") or sequence.count("<") != 1:
            continue
        words = sequence[1:-1].split("-")
        kinds = [k for k, word in enumerate(words) if word in ("Key", "KeyPress", "KeyRelease")]
        if not kinds or (words[kinds[0]] == "KeyRelease") != release:
            continue
        mods, detail = set(words[:kinds[0]]), "-".join(words[kinds[0] + 1:])
        if (detail and detail != keysym) or not mods <= modifiers:
            continue
        this = (bool(detail), len(mods))
        if rank is None or this > rank:
            found, rank = sequence, this
    return found


def key(widget, keysym, *modifiers, release=False, char=None):
    """Run the bindings Tk runs for a key pressed (or released) while widget has the keyboard
    focus: for each bind tag the most specific sequence the key matches, until one ends the
    key with break. Returns the tags whose bindings ran."""
    alt = 0x20000 if widget._windowingsystem == "win32" else 0x8
    state = sum(alt if name == "Alt" else STATES[name] for name in modifiers)
    if char is None:
        char = keysym if len(keysym) == 1 else ""
    fields = {"%W": f"{{{widget}}}", "%K": keysym, "%s": str(state), "%A": tcl_word(char),
              "%T": "3" if release else "2"}
    ran = []
    for tag in widget.bindtags():
        sequence = best_sequence(widget, tag, keysym, set(modifiers), release)
        if sequence is None:
            continue
        ran.append(tag)
        script = re.sub(r"%.", lambda m: fields.get(m.group(), "0"),
                        str(widget.tk.call("bind", tag, sequence)))
        stopped = widget.tk.eval("set ::key_stopped 1\nforeach _ {1} {\n" + script
                                 + "\nset ::key_stopped 0\n}\nset ::key_stopped")
        if stopped == "1":
            break
    return ran


def tap(widget, keysym, *modifiers):
    """Press and release a key alone (Alt, F10)."""
    key(widget, keysym, *modifiers)
    key(widget, keysym, *modifiers, *(("Alt",) if keysym.startswith("Alt") else ()),
        release=True)


def made(widget):
    """Give a widget its native window, as on the screen: its events and place need it."""
    widget.winfo_id()
    widget.update_idletasks()
    return widget


def title_point(bar, index):
    """The middle of title index on the bar's canvas."""
    title = bar._titles[index]
    made(bar.canvas)
    return (title.x0 + title.x1) // 2, bar._title_height // 2


def item_point(menu, index):
    """The middle of item index on the menu's canvas."""
    entry = menu.entries[index]
    made(menu.canvas)
    return menu.width // 2, (entry.top + entry.bottom) // 2


def mouse(widget, event, x, y, held=False):
    """Send the mouse's event to widget at (x, y); held: with the first button down."""
    made(widget)
    widget.event_generate(event, x=x, y=y, state=0x100 if held else 0)


def entry_index(menu, label):
    return next(k for k, entry in enumerate(menu.entries) if entry.label == label)


def brightness(colour):
    """How bright a gray "#RRGGBB" is, from 0 to 1."""
    return int(colour[1:3], 16) / 255


def items_drawn(canvas, kind):
    """The canvas's items of a kind that are not hidden, in drawing order."""
    return [item for item in canvas.find_all()
            if canvas.type(item) == kind and canvas.itemcget(item, "state") != "hidden"]


def bevels_drawn(bar):
    """The rectangles shown on the bar's canvas, without its gradient and its two lines."""
    return [item for item in items_drawn(bar.canvas, "rectangle")
            if item not in bar._rows and item not in bar._lines]


def rings_of(canvas, box):
    """{side: colour} of the bevel rectangles shown along the box (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = box
    sides = {}
    for item in items_drawn(canvas, "rectangle"):
        a, b, c, d = (round(v) for v in canvas.coords(item))
        colour = canvas.itemcget(item, "fill").upper()
        if (a, b, c) == (x0, y0, x1) and d - b < (y1 - y0) // 2:
            sides.setdefault("top", colour)
        elif (a, b, d) == (x0, y0, y1) and c - a < (x1 - x0) // 2:
            sides.setdefault("left", colour)
        elif (a, c, d) == (x0, x1, y1) and d - b < (y1 - y0) // 2:
            sides.setdefault("bottom", colour)
        elif (b, c, d) == (y0, x1, y1) and c - a < (x1 - x0) // 2:
            sides.setdefault("right", colour)
    return sides


# The table ----------------------------------------------------------------------------------

def table_labels():
    """{title: [labels with their "&"]} of the menu table, the Settings menu included."""
    menus = {}
    for title, entries in MENUS:
        if entries is None:
            labels = [label for _, label in SETTINGS_MENU] + [
                label for _, label, _ in SETTINGS_COMMANDS]
        else:
            labels = [entry[1] for entry in entries if entry is not None]
        menus[title] = labels
    return menus


def test_every_item_has_an_access_letter_unique_within_its_menu():
    menus = table_labels()
    assert [access_letter(title)[0] for title in menus] == TITLES
    assert [text[underline] for text, underline in map(access_letter, menus)] == list("FERSTH")
    for title, labels in list(menus.items()) + [("bar", list(menus))]:
        letters = []
        for label in labels:
            assert label.count("&") == 1, label
            text, underline = access_letter(label)
            assert "&" not in text and text[underline].isalnum(), label
            letters.append(text[underline].lower())
        assert len(set(letters)) == len(letters), (title, letters)
    assert access_letter("Close A&ll") == ("Close All", 7)
    assert access_letter("Plain") == ("Plain", -1)


def test_the_menus_show_the_labels_without_the_mark_and_underline_their_letters(bar):
    assert [bar.entrycget(i, "label") for i in range(bar.index("end") + 1)] == TITLES
    assert all(bar.entrycget(i, "underline") == 0 for i in range(len(TITLES)))
    for labels, menu in zip(table_labels().values(), bar.menus):
        shown = [(menu.entrycget(i, "label"), menu.entrycget(i, "underline"))
                 for i in range(menu.index("end") + 1) if menu.type(i) != "separator"]
        assert shown == [access_letter(label) for label in labels]
        for entry in menu.entries:
            if entry.kind != "separator":
                assert menu.canvas.itemcget(entry.text, "text") == entry.label
                assert int(menu.canvas.itemcget(entry.text, "underline")) == entry.underline


def test_the_menus_have_their_items_shortcuts_and_states(bar, app):
    """The table of test_gui_app's own test, which reads it the same way."""
    assert menu_table(app) == EXPECTED_MENUS
    assert isinstance(app.root.nametowidget(bar.entrycget(SETTINGS, "menu")), DropDown)
    menu, index = app._menu_items["save"]
    assert menu.entrycget(index, "state") == "disabled" and not app.is_enabled("save")
    app.cmd_new()
    assert menu.entrycget(index, "state") == "normal"


def test_macos_keeps_its_screen_menu_bar(make_app, monkeypatch):
    monkeypatch.setattr(menubar_module, "is_aqua", lambda widget: True)
    app = make_app()
    assert isinstance(app.menubar, tk.Menu) and app.root.cget("menu") == str(app.menubar)
    assert not any(isinstance(w, MenuBar) for w in app.root.winfo_children())
    assert menu_table(app) == EXPECTED_MENUS
    for i, labels in enumerate(table_labels().values()):
        assert app.menubar.entrycget(i, "underline") == 0
        menu = app.root.nametowidget(app.menubar.entrycget(i, "menu"))
        assert isinstance(menu, tk.Menu)
        assert [menu.entrycget(j, "underline") for j in range(menu.index("end") + 1)
                if menu.type(j) != "separator"] == [access_letter(label)[1] for label in labels]


# The look -----------------------------------------------------------------------------------

def test_the_bar_is_at_the_top_with_a_gray_line_above_the_toolbar(bar, app):
    root = app.root
    toolbar = app.buttons["new"].master.master
    assert root.pack_slaves()[:2] == [bar, toolbar]
    assert bar.winfo_class() == MENU_BAR_CLASS
    canvas = bar.canvas
    ring = px(root, 1)
    made(canvas)
    canvas.event_generate("<Configure>", width=700, height=int(canvas.cget("height")))
    gap, line = (canvas.coords(item) for item in bar._lines)
    top = bar._title_height + ring
    assert gap == [0, top, 700, top + ring] and line == [0, top + ring, 700, top + 2 * ring]
    assert [canvas.itemcget(item, "fill").upper() for item in bar._lines] == [FACE, BAR_LINE]
    assert int(canvas.cget("height")) == bar._title_height + 3 * ring


def test_the_bar_is_a_gradient_down_to_its_gap_and_line(bar, app):
    canvas, ring = bar.canvas, px(app.root, 1)
    height = bar._title_height + ring
    assert len(bar._rows) == height
    assert [canvas.coords(row)[1::2] for row in bar._rows] == [[y, y + 1] for y in range(height)]
    assert ([canvas.itemcget(row, "fill").upper() for row in bar._rows]
            == gradient(*MENU_BAR, height))
    assert canvas.itemcget(bar._rows[0], "fill").upper() == "#FFFFFF"
    assert canvas.itemcget(bar._rows[-1], "fill").upper() == "#DEDEDE"
    assert canvas.coords(bar._lines[0])[1] == height    # the gap and the line come after it


def test_the_gradient_lies_under_everything_on_the_bar_and_is_no_picture(bar):
    canvas = bar.canvas
    assert list(canvas.find_all()[:len(bar._rows)]) == bar._rows
    assert "image" not in {canvas.type(item) for item in canvas.find_all()}


def test_resizing_the_bar_leaves_its_gradient_alone(bar):
    canvas = bar.canvas
    made(canvas)
    items = canvas.find_all()
    rows = [canvas.coords(row) for row in bar._rows]
    for width in (700, 3000):
        canvas.event_generate("<Configure>", width=width, height=int(canvas.cget("height")))
    assert canvas.find_all() == items
    assert [canvas.coords(row) for row in bar._rows] == rows


def test_the_titles_and_their_bevels_stand_out_on_every_row_of_the_gradient(bar):
    canvas = bar.canvas
    for row in bar._rows:
        light = brightness(canvas.itemcget(row, "fill"))
        assert light - brightness(TEXT) >= 0.6          # the text
        assert light - brightness(SHADOW) >= 0.3        # the dark sides of a title's bevel


def test_a_title_keeps_its_bevels_over_the_gradient(bar):
    title, canvas = bar._titles[EDIT], bar.canvas
    box = (title.x0, 0, title.x1, bar._title_height)
    bar._hot = EDIT
    bar._paint()
    assert rings_of(canvas, box)["bottom"] == SHADOW
    assert list(canvas.find_all()).index(bar._bevel[0]) > list(canvas.find_all()).index(
        bar._rows[-1])
    bar._hot = None
    bar._paint()


def test_the_titles_are_black_in_the_menu_font_with_their_letters_underlined(bar, app):
    root = app.root
    font = bar.font
    assert bar._title_height == max(px(root, TITLE_HEIGHT),
                                    font.metrics("linespace") + px(root, TITLE_ROOM))
    x = 0
    for title in bar._titles:
        canvas = bar.canvas
        assert canvas.itemcget(title.text, "font") == "TkMenuFont"
        assert canvas.itemcget(title.text, "fill").upper() == TEXT
        assert int(canvas.itemcget(title.text, "underline")) == 0
        assert (title.x0, title.x1) == (x, x + font.measure(title.label)
                                        + 2 * px(root, TITLE_PADDING))
        assert canvas.coords(title.text) == [title.x0 + px(root, TITLE_PADDING), bar._text_y]
        x = title.x1
    assert not bevels_drawn(bar)                # only the gradient and the etched line


def test_a_title_under_the_mouse_is_raised_and_an_open_title_pressed_in(bar, app):
    ring = px(app.root, 1)
    canvas = bar.canvas
    title = bar._titles[EDIT]
    box = (title.x0, 0, title.x1, bar._title_height)
    mouse(canvas, "<Motion>", *title_point(bar, EDIT))
    assert rings_of(canvas, box) == {"top": HIGHLIGHT, "left": HIGHLIGHT, "bottom": SHADOW,
                                     "right": SHADOW}
    assert canvas.coords(title.text) == [title.x0 + px(app.root, TITLE_PADDING), bar._text_y]
    canvas.event_generate("<Leave>")
    assert not bevels_drawn(bar)
    mouse(canvas, "<ButtonPress-1>", *title_point(bar, EDIT))
    assert rings_of(canvas, box) == {"top": SHADOW, "left": SHADOW, "bottom": HIGHLIGHT,
                                     "right": HIGHLIGHT}
    assert canvas.coords(title.text) == [title.x0 + px(app.root, TITLE_PADDING) + ring,
                                         bar._text_y + ring]
    bar.close()
    bar.activate(RUN)                                       # selected from the keyboard
    title = bar._titles[RUN]
    assert rings_of(canvas, (title.x0, 0, title.x1, bar._title_height))["top"] == HIGHLIGHT


def test_a_menu_has_the_square_raised_border_of_windows_98(bar, app):
    bar.open(FILE)
    menu = bar.menus[FILE]
    ring = px(app.root, 1)
    canvas = menu.canvas
    width, height = menu.width, menu.height
    assert (int(canvas.cget("width")), int(canvas.cget("height"))) == (width, height)
    assert str(menu.cget("background")).upper() == str(canvas.cget("background")).upper() == FACE
    assert rings_of(canvas, (0, 0, width, height)) == {"top": LIGHT, "left": LIGHT,
                                                       "bottom": DARK_SHADOW,
                                                       "right": DARK_SHADOW}
    assert rings_of(canvas, (ring, ring, width - ring, height - ring)) == {
        "top": HIGHLIGHT, "left": HIGHLIGHT, "bottom": SHADOW, "right": SHADOW}
    frame = 2 * ring + px(app.root, 1)
    assert menu._sides == (frame, width - frame)
    assert menu.entries[0].top == frame and menu.entries[-1].bottom == height - frame
    assert menu.overrideredirect()
    assert menu.winfo_class() == "AresMenu"


def test_items_and_separators_have_windows_98_sizes(bar, app):
    """The texts start 17 px into an item; the shortcuts end 13 px before its right side,
    at least 12 px after the widest text."""
    root = app.root
    menu = bar.menus[FILE]
    menu.lay_out()
    line = bar.font.metrics("linespace")
    row = max(px(root, ITEM_HEIGHT), line + px(root, ITEM_ROOM))
    left, right = menu._sides
    for entry in menu.entries:
        if entry.kind == "separator":
            assert entry.bottom - entry.top == px(root, SEPARATOR_HEIGHT)
        else:
            assert entry.bottom - entry.top == row
            x, y = menu.canvas.coords(entry.text)
            assert (x, y) == (left + px(root, 17), entry.top + (row - line) // 2)
    keys = [menu.canvas.coords(entry.key) for entry in menu.entries if entry.key is not None]
    assert keys and {x for x, _ in keys} == {right - px(root, 13)}         # right-aligned
    assert {menu.canvas.itemcget(entry.key, "anchor") for entry in menu.entries
            if entry.key is not None} == {"ne"}
    texts = max(bar.font.measure(e.label) for e in menu.entries if e.kind != "separator")
    keys = max(bar.font.measure(e.accelerator) for e in menu.entries if e.accelerator)
    assert menu.width == 2 * left + px(root, 17) + texts + px(root, 12) + keys + px(root, 13)


@pytest.mark.parametrize("scale", [2.25])
def test_the_menus_are_scaled_with_the_display(make_root, tmp_path, scale):
    root = make_root(scale)
    app = App(root, settings_path=tmp_path / "settings.json")
    try:
        root.update()
        bar = app.menubar
        ring = px(root, 1)
        assert ring == 2
        menu = bar.menus[FILE]
        assert menu._sides[0] == 3 * ring
        separator = next(e for e in menu.entries if e.kind == "separator")
        assert separator.bottom - separator.top == px(root, SEPARATOR_HEIGHT) == 20
        item = menu.entries[0]
        assert item.bottom - item.top >= px(root, ITEM_HEIGHT) == 38
        assert bar._title_height >= px(root, TITLE_HEIGHT) == 45
        gray, white = separator.lines
        assert [round(v) for v in menu.canvas.coords(gray)][1::2] == [
            separator.top + 10, separator.top + 12]
        menu.lay_out()
        left, right = menu._sides
        assert {round(menu.canvas.coords(entry.text)[0]) for entry in menu.entries
                if entry.kind != "separator"} == {left + 38}          # 17 px in
        assert {round(menu.canvas.coords(entry.key)[0]) for entry in menu.entries
                if entry.key is not None} == {right - 29}             # 13 px before the side
        settings = bar.menus[SETTINGS]
        settings.lay_out()
        check = settings.entries[0].check
        xs = [round(v) for v in settings.canvas.coords(check)[::2]]
        assert max(xs) - min(xs) == 14                      # the 7 pixels of the mark, doubled
        assert min(xs) == settings._sides[0] + (29 - 14) // 2       # in the first 13 px
    finally:
        app.close()


def text_colour(menu, entry):
    return menu.canvas.itemcget(entry.text, "fill").upper()


def etched(menu, entry):
    """The white copy under a disabled text, one ring lower right, is shown."""
    return menu.canvas.itemcget(entry.shadow, "state") != "hidden"


def test_the_highlighted_item_is_blue_with_dark_text(bar, app):
    bar.open(EDIT, first=True)
    menu = bar.menus[EDIT]
    app.cmd_new()                                           # Undo stays gray: nothing to undo
    menu.highlight(entry_index(menu, "Copy"))
    entry = menu.entries[menu.active]
    left, right = menu._sides
    assert menu.canvas.coords(menu._lit) == [left, entry.top, right, entry.bottom]
    assert menu.canvas.itemcget(menu._lit, "fill").upper() == MENU_SELECTION
    assert items_drawn(menu.canvas, "rectangle").count(menu._lit) == 1
    assert text_colour(menu, entry) == TEXT
    assert menu.canvas.itemcget(entry.key, "fill").upper() == TEXT
    other = menu.entries[entry_index(menu, "Select All")]
    assert text_colour(menu, other) == TEXT and not etched(menu, other)


def test_disabled_items_are_etched_gray_and_gray_on_blue_when_highlighted(bar, app):
    ring = px(app.root, 1)
    bar.open(FILE)
    menu = bar.menus[FILE]
    entry = menu.entries[entry_index(menu, "Save")]         # no file is open
    assert text_colour(menu, entry) == SHADOW and etched(menu, entry)
    x, y = menu.canvas.coords(entry.text)
    assert menu.canvas.coords(entry.shadow) == [x + ring, y + ring]
    assert menu.canvas.itemcget(entry.shadow, "fill").upper() == HIGHLIGHT
    assert menu.canvas.find_below(entry.text) == (entry.shadow,)       # the copy is under it
    assert menu.canvas.itemcget(entry.key, "fill").upper() == SHADOW
    assert menu.canvas.itemcget(entry.key_shadow, "state") != "hidden"
    menu.highlight(entry_index(menu, "Save"))
    assert text_colour(menu, entry) == SHADOW and not etched(menu, entry)
    assert menu.canvas.itemcget(entry.key_shadow, "state") == "hidden"
    assert menu.canvas.itemcget(menu._lit, "state") == "normal"


def test_separators_are_etched_lines_inset_from_the_border(bar, app):
    ring = px(app.root, 1)
    menu = bar.menus[FILE]
    menu.lay_out()
    left, right = menu._sides
    for entry in (e for e in menu.entries if e.kind == "separator"):
        gray, white = (menu.canvas.coords(item) for item in entry.lines)
        middle = entry.top + px(app.root, SEPARATOR_HEIGHT) // 2
        assert gray == [left + ring, middle, right - ring, middle + ring]
        assert white == [left + ring, middle + ring, right - ring, middle + 2 * ring]
        assert [menu.canvas.itemcget(item, "fill").upper() for item in entry.lines] == [
            SHADOW, HIGHLIGHT]


def check_shown(menu, label):
    entry = menu.entries[entry_index(menu, label)]
    return menu.canvas.itemcget(entry.check, "state") != "hidden"


def test_check_marks_follow_the_settings(bar, app):
    menu = bar.menus[SETTINGS]
    bar.open(SETTINGS)
    shown = {name: check_shown(menu, access_letter(label)[0]) for name, label in SETTINGS_MENU}
    assert shown == {name: getattr(app.settings, name) for name, _ in SETTINGS_MENU}
    assert shown["require_capitals"] and not shown["show_labels"]
    entry = menu.entries[entry_index(menu, "Require Capital Letters")]
    assert menu.canvas.type(entry.check) == "polygon"
    assert menu.canvas.itemcget(entry.check, "fill").upper() == TEXT
    menu.highlight(entry_index(menu, "Require Capital Letters"))
    assert menu.canvas.itemcget(entry.check, "fill").upper() == TEXT
    pixel = max(1, round(app.root.winfo_fpixels("1i") / 96))
    xs = [round(v) for v in menu.canvas.coords(entry.check)[::2]]
    assert max(xs) - min(xs) == 7 * pixel
    bar.close()
    app.setting_vars["require_capitals"].set(False)         # from the menu, or Restore Defaults
    app._setting_toggled("require_capitals")
    bar.open(SETTINGS)
    assert not check_shown(menu, "Require Capital Letters")
    bar.close()
    app.cmd_restore_defaults()
    bar.open(SETTINGS)
    assert check_shown(menu, "Require Capital Letters")


def test_choosing_a_settings_item_turns_it_over(bar, app, monkeypatch):
    menu = bar.menus[SETTINGS]
    assert app.settings.require_capitals
    bar.open(SETTINGS, first=True)
    focus_on(app, monkeypatch, bar)
    key(bar, "c")                                           # Require Capital Letters
    assert not app.settings.require_capitals and not bar.active
    assert not app.setting_vars["require_capitals"].get()
    bar.open(SETTINGS)
    assert not check_shown(menu, "Require Capital Letters")
    point = item_point(menu, entry_index(menu, "Require Capital Letters"))
    mouse(menu.canvas, "<ButtonPress-1>", *point)
    mouse(menu.canvas, "<ButtonRelease-1>", *point, held=True)
    assert app.settings.require_capitals and app.setting_vars["require_capitals"].get()


def test_enabled_states_follow_the_window_also_in_an_open_menu(bar, app):
    menu = bar.menus[FILE]
    save = entry_index(menu, "Save")
    bar.open(FILE)
    assert text_colour(menu, menu.entries[save]) == SHADOW
    app.cmd_new()                                           # a menu shows the change at once
    assert menu.entrycget(save, "state") == "normal"
    assert text_colour(menu, menu.entries[save]) == TEXT
    painted = []
    original = menu._paint
    menu._paint = lambda index: painted.append(index) or original(index)
    app.editor_changed()                                    # nothing changed: nothing drawn
    assert painted == []


def test_a_closed_menu_notes_its_states_and_draws_nothing(bar, app, monkeypatch):
    painted = []
    for menu in bar.menus:
        monkeypatch.setattr(menu, "_paint", painted.append)
    app.cmd_new()                                           # Save, Close ... become available
    menu, index = app._menu_items["save"]
    assert menu.entrycget(index, "state") == "normal" and painted == []


# The keyboard ---------------------------------------------------------------------------------

def editor_text(app):
    app.cmd_new()
    return app.editor.current.text


def field_open(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    double_click(app.registers, ROW["registers"])
    return app.registers.editor


FOCUS = {
    "the editor": lambda app, tmp_path: editor_text(app),
    "Run I/O": lambda app, tmp_path: app.messages.run_io,
    "ARES Messages": lambda app, tmp_path: app.messages.messages,
    "a table": lambda app, tmp_path: app.registers.table.body,
    "a register's field": field_open,
}


@pytest.mark.parametrize("where", FOCUS)
@pytest.mark.parametrize("keysym", ["Alt_L", "Alt_R", "F10"])
def test_alt_or_f10_alone_activates_the_bar_and_again_deactivates_it(bar, app, tmp_path,
                                                                      monkeypatch,
                                                                      hidden_windows, where,
                                                                      keysym):
    widget = FOCUS[where](app, tmp_path)
    focus_on(app, monkeypatch, widget)
    key(widget, keysym)
    assert not bar.active                                   # released alone, it activates
    key(widget, keysym, *(("Alt",) if keysym != "F10" else ()), release=True)
    assert bar.active and bar.selected == FILE and bar.open_menu is None
    assert hidden_windows.focus is bar
    title = bar._titles[FILE]
    assert rings_of(bar.canvas, (title.x0, 0, title.x1, bar._title_height))["top"] == HIGHLIGHT
    focus_on(app, monkeypatch, bar)
    tap(bar, keysym)
    assert not bar.active and hidden_windows.focus is widget
    if where == "a register's field":
        assert app.registers.editor is widget and app.machine.reg(1) == 0
    assert menu_keys(app.root) == []                        # Windows' own menu bar is not used


def test_a_key_between_alt_and_its_release_leaves_the_bar(bar, app):
    text = editor_text(app)
    key(text, "Alt_L")
    key(text, "Shift_L", "Alt")                             # Alt+Shift changes the keyboard
    key(text, "Alt_L", "Alt", release=True)
    assert not bar.active


def test_a_held_alt_that_repeats_activates_once_on_its_release(bar, app, monkeypatch):
    text = editor_text(app)
    for _ in range(3):
        key(text, "Alt_L")
    key(text, "Alt_L", "Alt", release=True)
    assert bar.active
    focus_on(app, monkeypatch, bar)
    for _ in range(3):                                      # closes it; the repeats do nothing
        key(bar, "Alt_L")
    focus_on(app, monkeypatch, text)
    key(text, "Alt_L", "Alt", release=True)
    assert not bar.active


def test_alt_released_in_another_window_is_held_no_more(bar, app, monkeypatch):
    """Alt pressed in the window and released in a dialog that came up meanwhile: the next
    Alt is pressed afresh, and deactivates the bar."""
    text = editor_text(app)
    entry = tk.Entry(tk.Toplevel(app.root))
    key(text, "Alt_L")
    key(entry, "Alt_L", "Alt", release=True)
    key(text, "F10")
    key(text, "F10", release=True)
    assert bar.active
    focus_on(app, monkeypatch, bar)
    key(bar, "Alt_L")
    assert not bar.active


@pytest.mark.parametrize("keysym", ["space", "F4"])
def test_after_alt_and_a_key_left_to_windows_the_next_alt_activates(bar, app, keysym):
    """Alt+Space opens Windows' window menu, which takes Alt's release (as does the dialog
    Alt+F4 may bring): the next Alt pressed alone activates the bar all the same."""
    text = editor_text(app)
    key(text, "Alt_L")
    key(text, keysym, "Alt", char=" " if keysym == "space" else "")
    tap(text, "Alt_L")
    assert bar.active


@pytest.mark.parametrize("keys", [
    [("Alt_R", ("Control",), False), ("Alt_R", ("Control", "Alt"), True)],   # AltGr
    [("F10", ("Control",), False)],
    [("F10", ("Shift",), False)],
    [("space", ("Alt",), False)],                           # the window menu
    [("F4", ("Alt",), False)],                              # close the window
    [("q", ("Control", "Alt"), False)],
])
def test_control_keys_altgr_alt_space_and_alt_f4_are_left_to_windows(bar, app, keys):
    text = editor_text(app)
    for keysym, modifiers, release in keys:
        key(text, keysym, *modifiers, release=release, char=" " if keysym == "space" else None)
    assert not bar.active and bar.open_menu is None
    assert menu_keys(app.root) == [str(text)] * len(keys)
    if keys[0][0] == "F10":                                 # its release ends at the bar
        key(text, "F10", *keys[0][1], release=True)
        assert not bar.active and menu_keys(app.root) == [str(text)]


def test_the_keys_of_other_windows_are_left_alone(bar, app):
    dialog = tk.Toplevel(app.root)
    entry = tk.Entry(dialog)
    tap(entry, "Alt_L")
    tap(entry, "F10")
    key(entry, "f", "Alt")
    assert not bar.active and bar.open_menu is None
    assert menu_keys(app.root) == [str(entry)] * 5


def test_left_and_right_move_round_the_bar(bar, app, monkeypatch):
    bar.activate()
    focus_on(app, monkeypatch, bar)
    selected = []
    for keysym in ("Left", "Left", "Right", "Right", "Right"):
        key(bar, keysym)
        selected.append(bar.selected)
    assert selected == [HELP, TOOLS, HELP, FILE, EDIT] and bar.open_menu is None


@pytest.mark.parametrize("keysym", ["Down", "Up", "Return", "KP_Enter"])
def test_down_up_or_enter_open_the_selected_menu_with_its_first_item_highlighted(
        bar, app, monkeypatch, hidden_windows, keysym):
    bar.activate(RUN)
    focus_on(app, monkeypatch, bar)
    key(bar, keysym)
    menu = bar.menus[RUN]
    assert bar.open_menu is menu and menu.active == 0 and hidden_windows.shows(menu)


def test_a_titles_letter_on_the_active_bar_opens_its_menu(bar, app, monkeypatch):
    bar.activate()
    focus_on(app, monkeypatch, bar)
    key(bar, "q")
    assert bar.rings == [1] and bar.open_menu is None
    key(bar, "S", "Shift")
    assert bar.open_menu is bar.menus[SETTINGS] and bar.menus[SETTINGS].active == 0


@pytest.mark.parametrize("where", ["the editor", "a table", "a register's field"])
@pytest.mark.parametrize("letter", list("fersth"))
def test_alt_and_a_titles_letter_open_its_menu_with_the_first_item_highlighted(
        bar, app, tmp_path, monkeypatch, hidden_windows, where, letter):
    widget = FOCUS[where](app, tmp_path)
    focus_on(app, monkeypatch, widget)
    key(widget, "Alt_L")
    assert key(widget, letter, "Alt")[-1] == "all"
    key(widget, "Alt_L", "Alt", release=True)
    index = "fersth".index(letter)
    menu = bar.menus[index]
    assert bar.active and bar.selected == index and bar.open_menu is menu and menu.active == 0
    assert hidden_windows.shows(menu) and hidden_windows.focus is bar
    assert menu_keys(app.root) == []                        # Windows' own menu bar is not used
    if where == "a register's field":
        assert app.registers.editor is widget and app.machine.reg(1) == 0


def test_up_and_down_move_round_the_menu_past_the_separators(bar, app, monkeypatch):
    bar.open(FILE, first=True)
    focus_on(app, monkeypatch, bar)
    menu = bar.menus[FILE]
    down, up = [], []
    for _ in range(10):
        key(bar, "Down")
        down.append(menu.entries[menu.active].label)
    assert down == ["Open...", "Open Example", "Close", "Close All", "Save", "Save As...",
                    "Save All", "Dump Memory...", "Exit", "New"]       # gray items too
    for _ in range(2):
        key(bar, "Up")
        up.append(menu.entries[menu.active].label)
    assert up == ["Exit", "Dump Memory..."]


def test_enter_on_a_gray_item_does_nothing(bar, app, monkeypatch):
    calls = []
    monkeypatch.setattr(app, "cmd_save", lambda: calls.append(1))
    bar.open(FILE, first=True)
    focus_on(app, monkeypatch, bar)
    menu = bar.menus[FILE]
    menu.highlight(entry_index(menu, "Save"))
    key(bar, "Return")
    assert calls == [] and bar.open_menu is menu


def test_left_and_right_open_the_menus_beside(bar, app, monkeypatch, hidden_windows):
    bar.open(FILE)
    focus_on(app, monkeypatch, bar)
    key(bar, "Left")
    assert bar.open_menu is bar.menus[HELP] and bar.menus[HELP].active == 0
    assert not hidden_windows.shows(bar.menus[FILE]) and hidden_windows.shows(bar.menus[HELP])
    key(bar, "Right")
    key(bar, "Right")
    assert bar.open_menu is bar.menus[EDIT] and bar.selected == EDIT


def test_a_chosen_command_runs_after_the_menus_closed_with_the_focus_back(bar, app,
                                                                         monkeypatch,
                                                                         hidden_windows):
    text = editor_text(app)
    focus_on(app, monkeypatch, text)
    seen = []
    monkeypatch.setattr(app, "cmd_select_all", lambda: seen.append(
        (bar.active, bar.open_menu, hidden_windows.focus,
         hidden_windows.shows(bar.menus[EDIT]))))
    key(text, "e", "Alt")
    focus_on(app, monkeypatch, bar)
    for _ in range(6):                                      # from Undo to Select All
        key(bar, "Down")
    assert bar.menus[EDIT].entries[bar.menus[EDIT].active].label == "Select All"
    key(bar, "Return")
    assert seen == [(False, None, text, False)]


@pytest.mark.parametrize("keysym", ["a", "A"])
def test_an_items_letter_chooses_it_at_once(bar, app, monkeypatch, keysym):
    seen = []
    monkeypatch.setattr(app, "cmd_assemble", lambda: seen.append(bar.active))
    app.cmd_new()
    bar.open(RUN)
    focus_on(app, monkeypatch, bar)
    key(bar, keysym, *(("Shift",) if keysym.isupper() else ()))
    assert seen == [False] and bar.open_menu is None


def test_a_gray_items_letter_only_highlights_it(bar, app, monkeypatch):
    bar.open(FILE)
    focus_on(app, monkeypatch, bar)
    key(bar, "s")                                           # Save: no file is open
    menu = bar.menus[FILE]
    assert bar.open_menu is menu and menu.entries[menu.active].label == "Save"


def test_a_letter_several_items_share_moves_among_them(monkeypatch):
    root = new_root()
    try:
        style.apply(root)
        note_menu_keys(root)
        monkeypatch.setattr(root, "focus_get", lambda: root)
        bar = MenuBar(root)
        bar.pack(fill="x")
        menu = DropDown(bar)
        bar.add_cascade(label="Fruit", menu=menu, underline=0)
        chosen = []
        for label in ("&Apple", "&Apricot", "&Banana", "A&vocado", "&Avocado pear"):
            text, underline = access_letter(label)
            menu.add_command(label=text, underline=underline,
                             command=lambda text=text: chosen.append(text))
        bar.open(0, first=True)
        highlighted = []
        for _ in range(4):
            key(bar, "a")
            highlighted.append(menu.active)
        assert highlighted == [1, 4, 0, 1] and chosen == []
        rings = []
        monkeypatch.setattr(bar, "bell", lambda: rings.append(1))
        key(bar, "z")
        assert rings == [1] and bar.open_menu is menu
        key(bar, "v")
        assert chosen == ["Avocado"] and not bar.active
    finally:
        root.destroy()


@pytest.mark.parametrize("title, letter, command", [("f", "x", "exit"), ("e", "t", "cut")])
def test_with_alt_still_held_a_letter_chooses_in_the_open_menu(bar, app, monkeypatch, title,
                                                               letter, command):
    """As in Windows, Alt held down through F and X chooses File > Exit: the second letter is
    the open menu's (T is Edit's Cut, not the Tools menu), not Windows' own."""
    calls = []
    monkeypatch.setattr(app, f"cmd_{command}", lambda: calls.append(bar.active))
    text = editor_text(app)
    focus_on(app, monkeypatch, text)
    key(text, "Alt_L")
    key(text, title, "Alt")
    focus_on(app, monkeypatch, bar)
    key(bar, letter, "Alt")
    assert calls == [False] and bar.open_menu is None and bar.rings == []
    key(text, "Alt_L", "Alt", release=True)
    assert not bar.active and menu_keys(app.root) == []


def test_with_alt_still_held_the_arrows_move_in_the_menus(bar, app, monkeypatch):
    text = editor_text(app)
    focus_on(app, monkeypatch, text)
    key(text, "Alt_L")
    key(text, "e", "Alt")
    focus_on(app, monkeypatch, bar)
    key(bar, "Down", "Alt")
    assert bar.menus[EDIT].active == 1
    key(bar, "Right", "Alt")
    assert bar.open_menu is bar.menus[RUN] and bar.menus[RUN].active == 0
    key(bar, "Escape", "Alt")
    assert bar.active and bar.open_menu is None and menu_keys(app.root) == []


def test_escape_closes_the_menu_then_the_bar(bar, app, monkeypatch, hidden_windows):
    text = editor_text(app)
    focus_on(app, monkeypatch, text)
    key(text, "r", "Alt")
    focus_on(app, monkeypatch, bar)
    key(bar, "Escape")
    assert bar.active and bar.selected == RUN and bar.open_menu is None
    assert not hidden_windows.shows(bar.menus[RUN])
    title = bar._titles[RUN]
    assert rings_of(bar.canvas, (title.x0, 0, title.x1, bar._title_height))["top"] == HIGHLIGHT
    key(bar, "Escape")
    assert not bar.active and hidden_windows.focus is text


@pytest.mark.parametrize("keysym", ["Alt_L", "Alt_R", "F10"])
def test_alt_or_f10_close_every_menu(bar, app, monkeypatch, hidden_windows, keysym):
    text = editor_text(app)
    focus_on(app, monkeypatch, text)
    key(text, "h", "Alt")
    focus_on(app, monkeypatch, bar)
    key(bar, keysym)
    assert not bar.active and bar.open_menu is None and hidden_windows.focus is text
    focus_on(app, monkeypatch, text)
    key(text, keysym, *(("Alt",) if keysym != "F10" else ()), release=True)
    assert not bar.active                                   # its release does not open it again


def test_the_window_shortcuts_wait_while_the_bar_is_active(bar, app, monkeypatch):
    calls = []
    monkeypatch.setattr(app, "cmd_new", lambda: calls.append(1))
    bar.open(RUN)
    focus_on(app, monkeypatch, bar)
    assert key(bar, "n", "Control", char="\x0e") == [str(bar)]
    assert key(bar, "F5") == [str(bar)] and key(bar, "Tab") == [str(bar)]
    assert calls == [] and bar.open_menu is bar.menus[RUN] and bar.rings == []


def test_the_bar_binds_the_keys_before_tk_and_gives_them_back(monkeypatch):
    root = new_root()
    try:
        before = {sequence: str(root.tk.call("bind", "all", sequence))
                  for sequence in ("<Key-Alt_L>", "<Key-F10>", "<Alt-Key>", "<FocusOut>")}
        bar = MenuBar(root)
        for sequence, original in before.items():
            script = str(root.tk.call("bind", "all", sequence))
            assert script.startswith("if {") and script.endswith(original)
        bar.destroy()
        assert {sequence: str(root.tk.call("bind", "all", sequence))
                for sequence in before} == before
    finally:
        root.destroy()


# The mouse --------------------------------------------------------------------------------------

def test_a_press_on_a_title_opens_its_menu_and_a_press_on_it_again_closes_it(
        bar, app, monkeypatch, hidden_windows):
    text = editor_text(app)
    focus_on(app, monkeypatch, text)
    point = title_point(bar, EDIT)
    mouse(bar.canvas, "<ButtonPress-1>", *point)
    menu = bar.menus[EDIT]
    assert bar.open_menu is menu and menu.active is None and hidden_windows.shows(menu)
    assert hidden_windows.focus is bar
    mouse(bar.canvas, "<ButtonRelease-1>", *point, held=True)
    assert bar.open_menu is menu                            # a click leaves it open
    focus_on(app, monkeypatch, bar)
    mouse(bar.canvas, "<ButtonPress-1>", *point)
    assert not bar.active and not hidden_windows.shows(menu) and hidden_windows.focus is text


def test_the_open_menu_follows_the_mouse_onto_another_title(bar, app, hidden_windows):
    mouse(bar.canvas, "<ButtonPress-1>", *title_point(bar, FILE))
    mouse(bar.canvas, "<ButtonRelease-1>", *title_point(bar, FILE), held=True)
    mouse(bar.canvas, "<Motion>", *title_point(bar, TOOLS))
    assert bar.open_menu is bar.menus[TOOLS] and bar.menus[TOOLS].active is None
    assert hidden_windows.shows(bar.menus[TOOLS]) and not hidden_windows.shows(bar.menus[FILE])


def test_the_item_under_the_mouse_is_highlighted(bar, app):
    bar.open(FILE)
    menu = bar.menus[FILE]
    mouse(menu.canvas, "<Motion>", *item_point(menu, entry_index(menu, "Open...")))
    assert menu.active == 1
    mouse(menu.canvas, "<Motion>", *item_point(menu, entry_index(menu, "Save")))
    assert menu.entries[menu.active].label == "Save"        # gray, highlighted all the same
    separator = next(k for k, e in enumerate(menu.entries) if e.kind == "separator")
    mouse(menu.canvas, "<Motion>", *item_point(menu, separator))
    assert menu.active is None
    mouse(menu.canvas, "<Motion>", *item_point(menu, 0))
    mouse(menu.canvas, "<Motion>", 1, 1)                    # on the border
    assert menu.active is None
    mouse(menu.canvas, "<Motion>", *item_point(menu, 0))
    mouse(bar, "<Motion>", -3000, -3000)                    # far away, brought by the grab
    assert menu.active is None


def test_a_release_on_an_item_chooses_it_and_on_a_gray_one_nothing(bar, app, monkeypatch):
    calls = []
    monkeypatch.setattr(app, "cmd_new", lambda: calls.append("new"))
    monkeypatch.setattr(app, "cmd_save", lambda: calls.append("save"))
    bar.open(FILE)
    menu = bar.menus[FILE]
    point = item_point(menu, entry_index(menu, "Save"))
    mouse(menu.canvas, "<ButtonPress-1>", *point)
    mouse(menu.canvas, "<ButtonRelease-1>", *point, held=True)
    assert calls == [] and bar.open_menu is menu
    point = item_point(menu, entry_index(menu, "New"))
    mouse(menu.canvas, "<ButtonPress-1>", *point)
    mouse(menu.canvas, "<ButtonRelease-1>", *point, held=True)
    assert calls == ["new"] and not bar.active


def test_a_press_on_a_title_dragged_into_the_menu_chooses_on_release(bar, app, monkeypatch):
    calls = []
    monkeypatch.setattr(app, "cmd_memory_map", lambda: calls.append(bar.active))
    mouse(bar.canvas, "<ButtonPress-1>", *title_point(bar, TOOLS))
    menu = bar.menus[TOOLS]
    index = entry_index(menu, "Memory Map")
    point = item_point(menu, index)
    mouse(menu.canvas, "<Motion>", *point, held=True)
    assert menu.active == index
    mouse(menu.canvas, "<ButtonRelease-1>", *point, held=True)
    assert calls == [False]


def test_a_press_outside_closes_the_menus_and_does_nothing_else(bar, app, tmp_path,
                                                                 monkeypatch, hidden_windows):
    field = field_open(app, tmp_path)
    focus_on(app, monkeypatch, field)
    type_into(app.registers, "7")
    mouse(bar.canvas, "<ButtonPress-1>", *title_point(bar, RUN))
    focus_on(app, monkeypatch, bar)
    focus_moved(app.registers, bar, monkeypatch)             # the field hears the bar took it
    mouse(bar, "<ButtonPress-1>", -3000, -3000)             # brought to the bar by its grab
    assert not bar.active and hidden_windows.focus is field
    assert app.registers.editor is field and app.machine.reg(1) == 0     # nothing else


def test_a_press_on_a_button_while_a_menu_is_open_goes_to_the_bar(bar, app):
    """The bar's grab brings it a press elsewhere in ARES: the toolbar's New does not run."""
    assert lay_out(app.root)
    tabs = len(app.editor.tabs)
    bar.open(HELP)                                          # away from the New button
    pump(app.root)                                          # the grab is in place
    assert app.root.grab_current() is bar
    button = made(app.buttons["new"])
    button.event_generate("<ButtonPress-1>", x=3, y=3)     # Tk sends it on to the bar first,
    pump(app.root)                                          # as it does on the screen
    button.event_generate("<ButtonRelease-1>", x=3, y=3)
    pump(app.root)
    assert not bar.active and len(app.editor.tabs) == tabs
    assert app.root.grab_current() is None


def test_the_release_of_a_press_outside_does_nothing_either(bar, app):
    """A click on an error message's link closes the menu and is not taken as the link's
    click: its release ends at the bar too, which keeps the grab until then."""
    clicked = []
    app.messages.on_click = clicked.append
    app.messages.write_message("Error: line 3", target=3)
    assert lay_out(app.root)
    text = app.messages.messages
    assert "link" in text.tag_names("@5,5")
    bar.open(HELP)
    pump(app.root)
    text.event_generate("<ButtonPress-1>", x=5, y=5)
    pump(app.root)
    assert not bar.active and app.root.grab_current() is bar
    text.event_generate("<ButtonRelease-1>", x=5, y=5)
    pump(app.root)
    assert clicked == [] and app.root.grab_current() is None
    text.event_generate("<ButtonPress-1>", x=5, y=5)          # the next click is the link's
    text.event_generate("<ButtonRelease-1>", x=5, y=5)
    pump(app.root)
    assert clicked == [3]


@pytest.mark.parametrize("end", ["release", "right release", "focus lost", "next press"])
def test_the_grab_kept_for_that_release_is_let_go(bar, app, monkeypatch, end):
    assert lay_out(app.root)
    bar.open(EDIT)
    pump(app.root)
    button = 3 if end == "right release" else 1
    mouse(bar, f"<ButtonPress-{button}>", -3000, -3000)
    assert not bar.active and app.root.grab_current() is bar
    if end == "focus lost":                                 # another program came to the front
        focus_on(app, monkeypatch, None)
        bar.event_generate("<FocusOut>")
    elif end == "next press":                               # its release never came
        mouse(bar, "<ButtonPress-1>", -3000, -3000)
    else:
        mouse(bar, f"<ButtonRelease-{button}>", -3000, -3000)
    assert app.root.grab_current() is None and not bar.active


def test_a_press_on_the_bar_keeps_an_open_register_field(bar, app, tmp_path, monkeypatch):
    assert MENU_BAR_CLASS in KEEP_FIELD
    field = field_open(app, tmp_path)
    focus_on(app, monkeypatch, field)
    type_into(app.registers, "7")
    click(bar.canvas, *title_point(bar, RUN))               # the press ends on the bar
    app._pressed(SimpleNamespace(widget=bar))               # as a press on a scroll bar
    assert app.registers.editor is field and app.machine.reg(1) == 0


# The keyboard focus, the window and an open register field ---------------------------------------

def test_losing_the_keyboard_focus_closes_the_menus(bar, app, monkeypatch, hidden_windows):
    text = editor_text(app)
    focus_on(app, monkeypatch, text)
    key(text, "Alt_L")
    key(text, "f", "Alt")
    focus_on(app, monkeypatch, None)                        # another program came to the front
    made(bar).event_generate("<FocusOut>")
    assert bar._held == set()                               # at once: Alt was let go
    app.root.update_idletasks()                             # the focus changes of the moment
    assert not bar.active and not hidden_windows.shows(bar.menus[FILE])
    assert hidden_windows.focus is bar                      # the focus left with ARES
    focus_on(app, monkeypatch, bar)                         # ARES is active again: Tk gives the
    bar.event_generate("<FocusIn>")                         # bar the focus, which goes back
    assert hidden_windows.focus is text


def test_another_ares_window_taking_the_focus_closes_the_menus(bar, app, monkeypatch,
                                                                hidden_windows):
    bar.open(FILE)
    dialog = tk.Toplevel(app.root)
    focus_on(app, monkeypatch, dialog)
    made(bar).event_generate("<FocusOut>")
    assert not bar.active and hidden_windows.focus is bar   # the dialog keeps the focus


def test_a_menu_given_the_focus_leaves_it_with_the_bar(bar, app, monkeypatch,
                                                         hidden_windows):
    bar.open(TOOLS)
    menu = bar.menus[TOOLS]
    hidden_windows.focus = None
    focus_on(app, monkeypatch, menu.canvas)
    made(bar).event_generate("<FocusOut>")
    assert bar.open_menu is menu and hidden_windows.focus is bar


def test_moving_the_window_closes_the_menus(bar, app, monkeypatch, hidden_windows):
    bar.open(EDIT)
    made(app.root).event_generate("<Configure>", x=40, y=50, width=900, height=700)
    assert not bar.active and not hidden_windows.shows(bar.menus[EDIT])


def test_the_bar_takes_and_releases_a_grab(bar, app, monkeypatch):
    grabs = []
    monkeypatch.setattr(bar, "grab_set", lambda: grabs.append("set"))
    monkeypatch.setattr(bar, "grab_release", lambda: grabs.append("release"))
    bar.activate()
    bar.open(EDIT)
    bar.open(RUN)
    bar.close()
    assert grabs == ["set", "release"]


def test_opening_a_menu_keeps_an_open_register_field_and_a_command_applies_it(
        bar, app, tmp_path, monkeypatch, hidden_windows):
    field = field_open(app, tmp_path)
    focus_on(app, monkeypatch, field)
    type_into(app.registers, "7")
    key(field, "r", "Alt")                                  # Run
    assert bar.open_menu is bar.menus[RUN] and hidden_windows.focus is bar
    focus_on(app, monkeypatch, bar)
    focus_moved(app.registers, bar, monkeypatch)
    assert app.registers.editor is field and app.machine.reg(1) == 0
    key(bar, "s")                                           # Step
    assert app.machine.reg(1) == 7 and app.machine.pc == 4 and app.registers.editor is None


def test_a_wrong_value_and_a_chosen_command_ring_once_and_keep_the_field(
        bar, app, tmp_path, monkeypatch, hidden_windows):
    field = field_open(app, tmp_path)
    focus_on(app, monkeypatch, field)
    rings = bells(app.registers)
    type_into(app.registers, "abc")
    mouse(bar.canvas, "<ButtonPress-1>", *title_point(bar, RUN))
    focus_on(app, monkeypatch, bar)
    focus_moved(app.registers, bar, monkeypatch)
    menu = bar.menus[RUN]
    point = item_point(menu, entry_index(menu, "Step"))
    mouse(menu.canvas, "<Motion>", *point)
    mouse(menu.canvas, "<ButtonPress-1>", *point)
    mouse(menu.canvas, "<ButtonRelease-1>", *point, held=True)
    assert rings == [1] and app.registers.editor is field and field.get() == "abc"
    assert app.machine.pc == 0 and not bar.active and hidden_windows.focus is field


# Placing and speed ----------------------------------------------------------------------------------

def test_a_menu_opens_below_its_title_and_stays_on_the_screen():
    screen = (0, 0, 1000, 800)
    assert place_menu(100, 20, 38, (200, 300), screen) == (100, 38)
    assert place_menu(900, 20, 38, (200, 300), screen) == (800, 38)        # moved left
    assert place_menu(-50, 20, 38, (200, 300), screen) == (0, 38)
    assert place_menu(100, 600, 618, (200, 300), screen) == (100, 300)     # above the title
    assert place_menu(100, 200, 218, (200, 700), screen) == (100, 100)     # neither: on screen
    assert place_menu(1200, 20, 38, (200, 300), (1000, 0, 2000, 800)) == (1200, 38)


def test_the_menu_is_placed_below_its_title(bar, app, monkeypatch):
    monkeypatch.setattr(menubar_module, "screen_area", lambda widget, x, y: (0, 0, 5000, 5000))
    canvas = made(bar.canvas)                               # where the bar is on the screen
    bar.open(RUN)
    menu = bar.menus[RUN]
    x = canvas.winfo_rootx() + bar._titles[RUN].x0
    y = canvas.winfo_rooty() + bar._title_height
    assert app.root.tk.call("wm", "geometry", menu).endswith(f"+{x}+{y}")


def test_a_shown_menu_floats_above_without_taking_the_activation(bar, app, monkeypatch):
    float_inactive = menubar_module.float_inactive
    noted = []
    monkeypatch.setattr(menubar_module, "float_inactive", noted.append)
    menu = bar.menus[FILE]
    made(menu.canvas)
    menu.canvas.event_generate("<Map>")
    menu.event_generate("<Map>")                            # shown on the screen
    assert noted == [menu]
    float_inactive(menu)                                    # not on the screen: left alone
    float_inactive(SimpleNamespace(winfo_viewable=lambda: True,
                                   wm_frame=lambda: "not a window"))    # an error is ignored


@pytest.mark.serial
def test_a_menu_opens_quickly_and_makes_no_picture(bar, app):
    """A menu is made at start-up: opening it only shows the states and places it."""
    made = pictures(app.root)
    slowest = 0
    for _ in range(3):
        for index in range(len(TITLES)):
            start = time.perf_counter()
            bar.open(index, first=True)
            slowest = max(slowest, time.perf_counter() - start)
            bar.close()
    assert slowest < 0.05, slowest
    assert pictures(app.root) == made


@pytest.mark.serial
def test_the_menus_add_little_to_the_start_up(make_app, monkeypatch):
    spent = []

    def timed(function):
        def run(*args):
            start = time.perf_counter()
            function(*args)
            spent.append(time.perf_counter() - start)
        return run
    monkeypatch.setattr(App, "_make_menus", timed(App._make_menus))
    monkeypatch.setattr(MenuBar, "_prepare", timed(MenuBar._prepare))
    app = make_app()
    if isinstance(app.menubar, tk.Menu):
        pytest.skip("macOS keeps its screen menu bar")
    assert len(spent) == 2 and sum(spent) < 0.2, spent
    assert all(menu._laid_out for menu in app.menubar.menus)
