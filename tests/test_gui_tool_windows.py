# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Where the tool windows and the windows their buttons open appear, and what every tool
window has: its heading, the group box Tool Control and its buttons, at 100 % and 225 %."""

import re
import sys
import tkinter as tk
from tkinter import commondialog
from tkinter import font as tkfont
from tkinter import ttk

import pytest
from test_gui_dialogs import asked
from test_gui_dialogs import program as source_asking
from test_gui_run import COUNT, READ_INT, loaded, run_until
from test_style import lookup, make_root  # noqa: F401  (a fixture: a root at a display scale)

from ares.gui import style, tools
from ares.gui.app import App
from ares.gui.tools import frame
from ares.gui.widgets import px

EVERYWHERE = (-10000, -10000, 10000, 10000)     # a work area no window reaches the edges of
POSITION = re.compile(r"\+(-?\d+)\+(-?\d+)")
# A window on the screen as frame.frame_of() gives it: its frame's top left corner at
# (100, 50), its inside 800 x 600, a frame 8 pixels wide at the sides and the bottom and 31
# at the top (title bar included), as on Windows at 100 %.
PARENT = (100, 50, 800, 600, 8, 31)
WORK_AREA = (0, 0, 1920, 1040)                  # a monitor's, without the taskbar


class Placing:
    """Records where the windows are put: the work areas asked for (the points), every
    geometry given to a window, and each window's geometry and requested size at the
    moment it is shown."""

    def __init__(self, monkeypatch, area=EVERYWHERE):
        self.area = area
        self.points = []
        self.given = []                 # (window, geometry given)
        self.shown = {}                 # window -> (geometry, (requested width, height))
        monkeypatch.setattr(frame, "screen_area", self._screen_area)
        give, show = tk.Wm.geometry, tk.Wm.deiconify

        def geometry(window, *args):
            if args:
                self.given.append((window, args[0]))
            return give(window, *args)

        def deiconify(window):
            self.shown[window] = (window.wm_geometry(),
                                  (window.winfo_reqwidth(), window.winfo_reqheight()))
            show(window)
        monkeypatch.setattr(tk.Wm, "geometry", geometry)
        monkeypatch.setattr(tk.Wm, "deiconify", deiconify)

    def _screen_area(self, widget, x, y):
        self.points.append((x, y))
        return self.area

    def position(self, window):
        """Where the window was when it was shown: the top left corner of its frame."""
        geometry, _ = self.shown[window]
        match = POSITION.search(geometry)
        return int(match[1]), int(match[2])

    def size(self, window):
        """The window's requested size (its inside) when it was shown."""
        return self.shown[window][1]


@pytest.fixture
def placing(monkeypatch):
    return Placing(monkeypatch)


def main_window(app, x=200, y=100):
    """Move the main window's frame to (x, y); returns (x, y, width, height, side, top) as
    Tk knows them: its frame's corner, its inside, its frame's sides and its top."""
    root = app.root
    root.geometry(f"+{x}+{y}")
    root.update_idletasks()
    return (x, y, root.winfo_width(), root.winfo_height(),
            root.winfo_rootx() - x, root.winfo_rooty() - y)


def opened(app, command):
    app.run(command)
    return app.tool_windows[command]


def push_buttons(widget):
    """Every push button in widget and the widgets in it, Tk's and ttk's."""
    for child in widget.winfo_children():
        if isinstance(child, (tk.Button, ttk.Button)):
            yield child
        yield from push_buttons(child)


# Centred, and kept on the work area -------------------------------------------------------

def test_a_window_is_centred_over_its_parent():
    # The parent's frame spans x 100..916 and y 50..689 (816 x 639): its middle is
    # (508, 369.5). A window of 200 x 100 inside has a frame of 216 x 139: from (400, 300)
    # it has the same middle.
    assert frame.centred((200, 100), PARENT, WORK_AREA) == (400, 300)
    # On a monitor at the left of the main one.
    assert frame.centred((200, 100), (-1800, 100, 800, 600, 8, 31), (-1920, 0, 0, 1040)) == (
        -1500, 350)


@pytest.mark.parametrize("parent, expected", [
    ((-400, 50, 800, 600, 8, 31), (0, 300)),                # across the left edge: at it
    ((100, -400, 800, 600, 8, 31), (400, 0)),               # across the top
    ((1500, 50, 800, 600, 8, 31), (1920 - 216, 300)),       # across the right edge
    ((100, 800, 800, 600, 8, 31), (400, 1040 - 139)),       # across the bottom
], ids=["left", "top", "right", "bottom"])
def test_a_window_stays_on_the_work_area(parent, expected):
    """The whole frame stays on the work area: its sides, its title bar and its bottom."""
    assert frame.centred((200, 100), parent, WORK_AREA) == expected


def test_the_work_area_at_225_percent():
    # Frames of 14 pixels at the sides and the bottom, 65 at the top; a work area of 3840 x
    # 2064 (a 4K monitor without its taskbar).
    parent, area = (3000, 1500, 1600, 1200, 14, 65), (0, 0, 3840, 2064)
    assert frame.centred((900, 700), parent, area) == (3840 - 900 - 28, 2064 - 700 - 65 - 14)
    assert frame.centred((900, 700), (-1000, -600, 1600, 1200, 14, 65), area) == (0, 0)


def test_a_window_larger_than_the_work_area_is_at_its_top_left_corner():
    """Its title bar stays on the screen."""
    assert frame.centred((2000, 1200), PARENT, WORK_AREA) == (0, 0)
    assert frame.centred((2000, 1200), PARENT, (-1920, 100, 0, 1140)) == (-1920, 100)


def test_the_frame_of_a_window(make_root):
    root = make_root()
    root.geometry("800x600+100+50")
    root.update_idletasks()
    x, y, width, height, side, top = frame.frame_of(root)
    assert (x, y, width, height) == (100, 50, 800, 600)
    # From the frame's corner to the inside's: the side of the frame, and its top.
    assert (side, top) == (root.winfo_rootx() - 100, root.winfo_rooty() - 50)
    if sys.platform == "win32":
        assert 0 < side < top               # the title bar is in the top
    # A maximized window's frame lies partly outside the screen.
    root.geometry("+-8+-8")
    root.update_idletasks()
    assert frame.frame_of(root)[:2] == (-8, -8)
    assert frame.frame_of(root)[4:] == (side, top)


class Maximized:
    """A window restored at (500, 300), then maximized, as Tk tells about it at 225 %."""

    def state(self):
        return "zoomed"

    def wm_geometry(self):
        return "3840x2001+500+300"

    def winfo_x(self):
        return -14

    def winfo_y(self):
        return -14

    def winfo_rootx(self):
        return 0

    def winfo_rooty(self):
        return 51

    def winfo_width(self):
        return 3840

    def winfo_height(self):
        return 2001


def test_a_maximized_window_is_where_it_is_and_not_where_it_was():
    assert frame.frame_of(Maximized()) == (-14, -14, 3840, 2001, 14, 65)


def test_a_window_opens_over_the_middle_of_a_maximized_one():
    x, y = frame.centred((800, 600), frame.frame_of(Maximized()), (0, 0, 3840, 2100))
    # The inside of the window lies over the middle of the inside of the parent.
    assert (x + 14 + 400, y + 65 + 300) == (0 + 3840 // 2, 51 + 2001 // 2)


# The tool windows ---------------------------------------------------------------------

def descendants(widget):
    yield widget
    for child in widget.winfo_children():
        yield from descendants(child)


@pytest.mark.parametrize("scale", [1, 1.25, 1.5, 1.75, 2, 2.25, 2.5, 3])
def test_every_list_of_the_tools_shows_its_longest_entry_whole(make_root, tmp_path, scale):
    """A list's field holds its width in the font's digits, and its text is bold."""
    root = make_root(scale)
    app = App(root, settings_path=tmp_path / "settings.json")
    try:
        lists = 0
        for tool in tools.TOOLS:
            app.run(tool.command)
            window = app.tool_windows[tool.command].window
            for box in descendants(window):
                if box.winfo_class() == "TCombobox" and box.cget("values"):
                    font = tkfont.nametofont(str(box.cget("font")), root=root)
                    room = int(box.cget("width")) * font.measure("0")
                    for text in box.cget("values"):
                        assert font.measure(text) <= room, (tool.command, text)
                    lists += 1
        assert lists > 10
    finally:
        app.close()


@pytest.mark.parametrize("tool", tools.TOOLS, ids=lambda tool: tool.command)
def test_a_tool_window_opens_centred_over_the_main_window(app, placing, tool):
    """Placed before it is shown: Windows would put it at the top left corner of the screen."""
    x, y, width, height, side, top = main_window(app)
    window = opened(app, tool.command).window
    inside_width, inside_height = placing.size(window)
    assert placing.position(window) == (x + (width - inside_width) // 2,
                                        y + (height - inside_height) // 2)
    # The work area of the main window's monitor: the one at the middle of the main window.
    assert placing.points == [(x + side + width // 2, y + top + height // 2)]
    # Only its place is given: it keeps the size its contents ask for.
    given = [geometry for widget, geometry in placing.given if widget is window]
    assert given and all(POSITION.fullmatch(geometry) for geometry in given)


def editor_font(app, tmp_path):
    app.run("editor_font")
    return app.font_dialog


def memory_map(app, tmp_path):
    app.run("memory_map")
    return app.memory_map


def dump_memory(app, tmp_path):
    loaded(app, tmp_path, COUNT)
    app.run("dump_memory")
    return app.dump_dialog


def popup_input(app, tmp_path):
    app.settings.popup_input = True
    loaded(app, tmp_path, READ_INT)
    app.run("go")
    run_until(app, lambda: app.line_dialog is not None)
    return app.line_dialog


def service_dialog(app, tmp_path):
    return asked(app, tmp_path, source_asking(50))


@pytest.mark.parametrize("show", [editor_font, memory_map, dump_memory, popup_input,
                                  service_dialog], ids=lambda show: show.__name__)
def test_a_dialog_of_the_main_window_opens_centred_over_it(app, placing, tmp_path, show):
    """As the tools' windows: Windows would put it at the top left corner of the screen."""
    x, y, width, height, _, _ = main_window(app)
    window = show(app, tmp_path).window
    inside_width, inside_height = placing.size(window)
    assert placing.position(window) == (x + (width - inside_width) // 2,
                                        y + (height - inside_height) // 2)


@pytest.mark.parametrize("corner", ["top left", "bottom right"])
def test_a_tool_window_stays_on_the_work_area(app, monkeypatch, corner):
    """A main window near the work area's corner: the tool's frame is moved in from the edges
    it would cross."""
    x, y, width, height, side, top = main_window(app)
    middle_x, middle_y = x + side + width // 2, y + top + height // 2
    if corner == "top left":
        area = (middle_x - 50, middle_y - 50, middle_x + 5000, middle_y + 5000)
    else:
        area = (middle_x - 5000, middle_y - 5000, middle_x + 50, middle_y + 50)
    placing = Placing(monkeypatch, area)
    window = opened(app, "tool_counter").window
    left, upper = placing.position(window)
    inside_width, inside_height = placing.size(window)
    if corner == "top left":
        assert (left, upper) == area[:2]
    else:
        assert (left + inside_width + 2 * side, upper + inside_height + top + side) == area[2:]


def test_a_tool_chosen_again_comes_to_the_front_where_it_is(app, placing, hidden_windows):
    main_window(app)
    window = opened(app, "tool_counter")
    where = window.window.wm_geometry()
    main_window(app, 600, 300)
    hidden_windows.reset()
    placing.given.clear()
    assert opened(app, "tool_counter") is window
    assert hidden_windows.shows(window.window)
    assert window.window.wm_geometry() == where and placing.given == []


def test_the_mmio_font_dialog_is_centred_over_the_tool_s_window(app, placing, monkeypatch):
    """Font... of the Keyboard and Display MMIO Simulator: placed before it is shown, over the
    tool whose window its grab holds, not at the top left corner of the screen."""
    # Tk lays out no window that belongs to a hidden one (the main window): here the windows
    # belong to none, so that the tool's window has its size.
    monkeypatch.setattr(tk.Wm, "transient", lambda window, master=None: "")
    main_window(app)
    tool = opened(app, "tool_mmio")
    parent = tool.window
    parent.geometry("+300+200")
    parent.update_idletasks()
    width, height = parent.winfo_width(), parent.winfo_height()
    assert (width, height) == (parent.winfo_reqwidth(), parent.winfo_reqheight())
    side, top = parent.winfo_rootx() - 300, parent.winfo_rooty() - 200
    placing.points.clear()
    tool.font_button.invoke()
    dialog = tool.font_dialog.window
    inside_width, inside_height = placing.size(dialog)
    assert placing.position(dialog) == (300 + (width - inside_width) // 2,
                                        200 + (height - inside_height) // 2)
    # The work area of the tool's monitor: the one at the middle of the tool's window.
    assert placing.points == [(300 + side + width // 2, 200 + top + height // 2)]
    # Only its place is given: it keeps the size its contents ask for.
    given = [geometry for widget, geometry in placing.given if widget is dialog]
    assert given and all(POSITION.fullmatch(geometry) for geometry in given)
    tool.font_dialog.cancel()


def test_every_window_a_tool_opens_is_placed_before_it_is_shown(app, placing, monkeypatch):
    """The tool's own window and every window its buttons open (Font... of the Keyboard and
    Display MMIO Simulator): each is given its place before it is shown,
    else Windows puts it at the top left corner of the screen. The system's own dialogs (the
    colour chooser) are placed by the system: here each is cancelled at once."""
    made = []
    make = tk.Toplevel.__init__

    def toplevel(window, *args, **options):
        make(window, *args, **options)
        made.append(window)
    monkeypatch.setattr(tk.Toplevel, "__init__", toplevel)
    monkeypatch.setattr(commondialog.Dialog, "show",
                        lambda dialog, **options: dialog._fixresult(app.root, ""))
    main_window(app)
    titles = {}                         # tool -> the titles of the windows it opened
    for tool in tools.TOOLS:
        made.clear()
        window = opened(app, tool.command)
        left_alone = (window.connect_button, window.reset_button, window.close_button)
        for button in list(push_buttons(window.window)):
            if button not in left_alone:
                button.invoke()
        titles[tool.command] = [each.title() for each in made]
        for each in made:
            given = [geometry for widget, geometry in placing.given if widget is each]
            assert given, (tool.command, each.title())
            # Shown where it was put last.
            assert placing.position(each) == tuple(
                int(number) for number in POSITION.search(given[-1]).groups()), (
                tool.command, each.title())
        window.close()
    for tool in tools.TOOLS:
        name = tools.window_class(tool.command).NAME
        assert titles[tool.command][0] == name
    assert "Font" in titles["tool_mmio"]


# What every tool window has -----------------------------------------------------------------

HEADINGS = {"tool_cache": "Data cache performance, access by access",
            "tool_memref": "Where a program reads and writes memory",
            "tool_fpr": "A 32-bit IEEE 754 number, bit by bit",
            "tool_bht": "Predicting branches with a branch history table",
            "tool_xray": "Animation of the ARM Datapath"}


def all_widgets(widget):
    found = []
    for child in widget.winfo_children():
        found += [child] + all_widgets(child)
    return found


@pytest.mark.parametrize("scale", [1.0, 2.25])
def test_every_tool_window_ends_in_the_group_box_tool_control(make_root, tmp_path, scale):
    """No title strip: the title bar names the tool. A heading only where it says more. At the
    bottom an etched group box with its title centred, holding Connect to ARM at the left,
    Close at the right and Reset between them, and no Help."""
    root = make_root(scale)
    app = App(root, settings_path=tmp_path / "settings.json")
    try:
        for tool in tools.TOOLS:
            window = opened(app, tool.command)
            assert window.window.title() == window.NAME
            labels = [child for child in all_widgets(window.window)
                      if child.winfo_class() == "TLabel" and child.cget("text") == window.NAME]
            assert labels == [], tool.command           # the title appears once
            assert window.HEADING == HEADINGS.get(tool.command, "")
            content = window.window.winfo_children()[0]
            parts = content.pack_slaves()
            control = parts[-1]
            assert control.winfo_class() == "TLabelframe", tool.command
            assert control.cget("text") == "Tool Control"
            assert str(control.cget("labelanchor")) == "n"
            assert control.pack_info()["fill"] == "x"
            if window.HEADING:
                assert parts[0].cget("text") == window.HEADING
                assert str(parts[0].cget("style")) == style.HEADING
            assert len(parts) == (3 if window.HEADING else 2), tool.command
            buttons = (window.connect_button, window.reset_button, window.close_button)
            assert [button.cget("text") for button in buttons] == [
                "Connect to ARM", "Reset", "Close"]
            assert [button.master for button in buttons] == [control] * 3
            assert [int(button.grid_info()["column"]) for button in buttons] == [0, 2, 4]
            for column in (1, 3):                       # the room left over, between them
                assert int(control.grid_columnconfigure(column, "weight")) == 1
            assert not hasattr(window, "help_button") and not hasattr(window, "show_help")
            window.close()
    finally:
        app.close()


def test_the_heading_is_large_and_bold(make_root):
    root = make_root(2.25)
    style.apply(root)
    font = tkfont.Font(root=root, name=style.HEADING_FONT, exists=True)
    assert lookup(root, style.HEADING, "font") == style.HEADING_FONT
    assert font.actual("weight") == "bold"
    default = tkfont.nametofont("TkDefaultFont", root=root)
    assert font.cget("size") == round(default.cget("size") * 1.5)
