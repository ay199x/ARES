# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Tools menu, the window every tool has, and the Dynamic Instruction Counter's window."""

import importlib.util
from tkinter import ttk

import pytest
from conftest import native, press_key
from test_gui_assemble import assemble
from test_gui_look import RETURN_KEYS, all_buttons, framed, move_focus, tab_cycle
from test_gui_run import go_to_end, loaded, run_until
from test_responsiveness import pictures
from test_style import make_root  # noqa: F401  (a fixture: a root at a display scale)

from ares.classify import FORMATS
from ares.gui import style, tools
from ares.gui.tools import frame
from ares.gui.tools.counter import CATEGORY_PANEL, FORMAT_PANEL, CounterWindow
from ares.gui.widgets import px

COUNT = """\
        .global _start
_start: MOV     R0, #0
loop:   ADD     R0, R0, #1
        CMP     R0, #3
        BNE     loop
        SVC     #10
"""
TOTAL = 1 + 3 * 3 + 1           # MOV, 3 x (ADD, CMP, BNE), SVC
FOREVER = ".global _start\n_start: ADD R0, R0, #1\n        B _start\n"


def tools_menu(app):
    return app._menu_items["tool_counter"][0]


def counter(app):
    """Open the Dynamic Instruction Counter (or bring it to the front); returns its window."""
    app.run("tool_counter")
    return app.tool_windows["tool_counter"]


def connected(app):
    window = counter(app)
    window.connect_button.invoke()
    assert window.model.connected
    return window


def shown(window):
    """(total, {format: count}, {format: percentage}) as the panel Encoding Formats shows them."""
    counts = {name: int(box.shown) for name, box in zip(FORMATS, window.formats.counts)}
    shares = {name: bar.shown[0] for name, bar in zip(FORMATS, window.formats.bars)}
    return int(window.formats.total.shown), counts, shares


# The Tools menu ---------------------------------------------------------------------

def test_the_tools_menu_lists_the_tools_with_their_access_letters(app):
    menu = tools_menu(app)
    for tool in tools.TOOLS:
        _, index = app._menu_items[tool.command]
        assert menu.entrycget(index, "label") == tool.label.replace("&", "")
        assert menu.entrycget(index, "underline") == tool.label.index("&")
    letters = [tool.label[tool.label.index("&") + 1].lower() for tool in tools.TOOLS]
    assert len(set(letters + ["m"])) == len(tools.TOOLS) + 1       # Memory Map has M
    _, index = app._menu_items["memory_map"]
    assert menu.type(index - 1) == "separator" and index == menu.index("end")
    assert menu.entrycget(index, "underline") == 0


def test_tools_not_built_yet_are_in_the_menu_but_gray(app, monkeypatch):
    menu = tools_menu(app)
    for tool in tools.TOOLS:
        menu_state = menu.entrycget(app._menu_items[tool.command][1], "state")
        built = importlib.util.find_spec(f"ares.gui.tools.{tool.module}") is not None
        assert tools.available(tool.command) is built, tool.command
        assert menu_state == ("normal" if built else "disabled"), tool.command
        assert app.is_enabled(tool.command) is built
    # A tool whose module is missing is gray, and choosing it opens nothing.
    monkeypatch.setitem(tools._found, "tool_bht", False)
    app.editor_changed()
    assert menu.entrycget(app._menu_items["tool_bht"][1], "state") == "disabled"
    app.run("tool_bht")
    assert "tool_bht" not in app.tool_windows
    assert not tools.available("memory_map") and not tools.available("nothing")


def test_the_counter_opens_from_the_menu(app, hidden_windows):
    menu = tools_menu(app)
    menu.invoke(app._menu_items["tool_counter"][1])
    window = app.tool_windows["tool_counter"]
    assert isinstance(window, CounterWindow) and hidden_windows.shows(window.window)
    assert window.window.title() == "Dynamic Instruction Counter"
    assert str(window.window.wm_transient()) == str(app.root)
    assert list(all_buttons(window.window)) == ["Connect to ARM", "Reset", "Close"]
    assert hidden_windows.focus is window.connect_button
    assert all(window.tips[button].text for button in window.buttons)


@pytest.mark.parametrize("tool", tools.TOOLS, ids=lambda tool: tool.command)
def test_every_tool_window_is_transient_and_not_resizable(app, tool):
    """Each tool has its own window in front of the main one, of a size the user cannot
    change."""
    app.run(tool.command)
    window = app.tool_windows[tool.command].window
    assert str(window.wm_transient()) == str(app.root)
    assert window.resizable() == (False, False)


def test_one_window_per_tool(app, hidden_windows):
    window = counter(app)
    hidden_windows.reset()
    assert counter(app) is window                # brought to the front, not made again
    assert hidden_windows.shows(window.window) and hidden_windows.focus is window.connect_button
    window.close()
    assert counter(app) is not window


def test_the_counter_opens_during_a_run(app, tmp_path):
    loaded(app, tmp_path, FOREVER)
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) > 100)
    assert app.is_enabled("tool_counter")
    window = connected(app)
    count = app.machine.reg(0)
    run_until(app, lambda: shown(window)[0] > 0)            # refreshed after the slices
    app.run("stop")
    assert app.machine.reg(0) > count


# The tool window -------------------------------------------------------------------

def test_connect_and_disconnect(app, tmp_path):
    loaded(app, tmp_path, COUNT)
    window = counter(app)
    button = window.connect_button
    assert button.cget("text") == "Connect to ARM" and not window.model.connected
    assert not app.machine.observers.active
    # The button keeps its width, wide enough for Disconnect from ARM.
    plain = ttk.Button(window.window, text="Disconnect from ARM")
    button.update_idletasks()
    width = button.winfo_reqwidth()
    assert width >= plain.winfo_reqwidth()
    plain.destroy()
    button.invoke()
    assert button.cget("text") == "Disconnect from ARM" and window.model.connected
    assert window.model.machine is app.machine and app.machine.observers.active
    assert window.tips[button].text == frame.TIPS[frame.DISCONNECT]
    button.update_idletasks()
    assert button.winfo_reqwidth() == width
    button.invoke()
    assert button.cget("text") == "Connect to ARM" and not window.model.connected
    assert not app.machine.observers.active
    assert window.tips[button].text == frame.TIPS[frame.CONNECT]
    button.update_idletasks()
    assert button.winfo_reqwidth() == width


def test_connected_without_a_program(app, tmp_path):
    window = connected(app)
    assert window.model.machine is None
    loaded(app, tmp_path, COUNT)
    assert window.model.machine is app.machine
    go_to_end(app)
    assert shown(window)[0] == TOTAL


def test_counts_follow_step_go_backstep_reset_and_assemble(app, tmp_path):
    loaded(app, tmp_path, COUNT)
    window = connected(app)
    for steps in (1, 2, 3):
        app.run("step")
        assert shown(window)[0] == steps
    app.run("backstep")                         # undone, but executed: the count stays
    assert shown(window)[0] == 3
    go_to_end(app)
    total, counts, shares = shown(window)
    assert total == TOTAL + 1                   # the instruction stepped back ran twice
    assert counts == {**dict.fromkeys(FORMATS, 0), "fmt_dp_imm": 8, "fmt_branch": 3,
                      "fmt_svc": 1}
    assert shares["fmt_dp_imm"] == "66.7%" and shares["fmt_svc"] == "8.3%"
    assert shares["fmt_mul"] == "0.0%"
    app.run("reset")                            # Reset, F12: the count goes on
    assert shown(window)[0] == TOTAL + 1
    app.run("step")
    assert shown(window)[0] == TOTAL + 2
    assemble(app)                               # a new program: still connected, counting
    assert window.model.connected and window.model.machine is app.machine
    assert shown(window)[0] == TOTAL + 2
    go_to_end(app)
    assert shown(window)[0] == 2 * TOTAL + 2


def test_a_register_change_refreshes_the_tools(app, tmp_path):
    loaded(app, tmp_path, COUNT)
    window = connected(app)
    refreshed = []
    window.refresh = lambda: refreshed.append(1)
    app._register_edited("R0", 5)
    assert refreshed


def test_closing_the_programs_file_keeps_the_counter_connected(app, tmp_path):
    loaded(app, tmp_path, COUNT)
    window = connected(app)
    app.run("step")
    app.run("step")
    app.run("close")
    assert app.machine is None and window.model.connected and window.model.machine is None
    assert shown(window)[0] == 2
    assert window.connect_button.cget("text") == "Disconnect from ARM"
    loaded(app, tmp_path, COUNT, "other.s")
    assert window.model.machine is app.machine
    go_to_end(app)
    assert shown(window)[0] == 2 + TOTAL


def test_the_reset_button_sets_the_counts_to_zero(app, tmp_path):
    loaded(app, tmp_path, COUNT)
    window = connected(app)
    go_to_end(app)
    window.reset_button.invoke()
    total, counts, shares = shown(window)
    assert total == 0 and set(counts.values()) == {0} and set(shares.values()) == {"0.0%"}
    assert window.model.connected
    app.run("reset")
    app.run("step")
    assert shown(window)[0] == 1


def test_close_disconnects(app, tmp_path):
    loaded(app, tmp_path, COUNT)
    window = connected(app)
    window.close_button.invoke()
    assert window.window is None
    assert not window.model.connected and not app.machine.observers.active
    go_to_end(app)                              # nothing left behind that counts
    assert app.tool_windows == {}
    again = counter(app)
    assert not again.model.connected and shown(again)[0] == 0


def test_several_tool_windows_at_once(app, tmp_path, monkeypatch):
    """Two tools (here a second counter in the place of a later tool) and the Memory Map:
    both counters count, with one block hook between them."""
    class Second(CounterWindow):
        NAME = "Second Counter"
    windows = {"tool_counter": CounterWindow, "tool_second": Second}
    monkeypatch.setattr(tools, "available", lambda command: command in windows)
    monkeypatch.setattr(tools, "window_class", windows.get)
    app.editor_changed()
    loaded(app, tmp_path, COUNT)
    hooks = len(app.machine.uc._callbacks)
    first = connected(app)
    app.run("step")
    app.run("tool_second")
    second = app.tool_windows["tool_second"]
    second.connect_button.invoke()
    app.run("memory_map")
    assert len(app.machine.uc._callbacks) == hooks + 1
    go_to_end(app)
    assert (shown(first)[0], shown(second)[0]) == (TOTAL, TOTAL - 1)
    first.close()
    assert app.machine.observers.active and app.memory_map.window is not None
    second.close()
    assert not app.machine.observers.active


@pytest.mark.parametrize("key", RETURN_KEYS)
def test_return_presses_the_framed_button(app, key):
    window = counter(app)
    buttons = all_buttons(window.window)
    assert framed(buttons) == ["Connect to ARM"]
    pressed = []
    boxes = [panel.total.canvas for panel in (window.categories, window.formats)]
    for label, button in buttons.items():
        button.configure(command=lambda label=label: pressed.append(label))
    order = [buttons["Close"], buttons["Reset"], boxes[0], window.window,
             buttons["Connect to ARM"]]
    previous = None
    for widget in order:
        move_focus(previous, widget)
        previous = widget
        press_key(widget, key)
    assert pressed == ["Close", "Reset", "Connect to ARM", "Connect to ARM", "Connect to ARM"]


def test_return_connects_and_escape_closes(app, tmp_path):
    loaded(app, tmp_path, COUNT)
    window = counter(app)
    press_key(window.connect_button, "<Key-Return>")
    assert window.model.connected
    press_key(window.connect_button, "<Key-KP_Enter>")
    assert not window.model.connected
    press_key(window.connect_button, "<Key-Return>")
    press_key(window.window, "<Key-Escape>")
    assert window.window is None and not app.machine.observers.active


def test_the_help_text_is_kept_for_the_help_window(app):
    window = counter(app)
    text = frame.paragraphs(window.HELP)
    assert "DynARMic" in text and "Total:" in text
    for label in CATEGORY_PANEL[1] + FORMAT_PANEL[1]:
        assert label in text, label
    assert "\n\n" in text and not any("\n" in part for part in text.split("\n\n"))


def test_the_percentage_bar(app):
    bar = frame.PercentBar(app.root)
    assert bar.shown == ("0.0%", 0) and not bar.cover.winfo_manager()
    bar.set(1, 4)
    assert bar.shown == ("25.0%", round(bar.room / 4))
    assert bar.cover.place_info()["width"] == str(round(bar.room / 4))
    assert bar.canvas.itemcget(bar.text, "text") == bar.cover.itemcget(bar.cover_text,
                                                                       "text") == "25.0%"
    assert bar.canvas.itemcget(bar.text, "fill") == style.TEXT           # on the field
    assert bar.cover.itemcget(bar.cover_text, "fill") == "#FFFFFF"       # on the blocks
    assert all(bar.cover.itemcget(item, "fill") == "#000080"
               for item in bar.cover.find_all() if item != bar.cover_text)
    # Navy blocks two thirds as wide as the bar is high, with 2-pixel gaps.
    block, gap = round(bar.inner * 2 / 3), px(bar.canvas, 2)
    blocks = [bar.cover.coords(item) for item in bar.cover.find_all() if item != bar.cover_text]
    assert {(x1 - x0, y0, y1) for x0, y0, x1, y1 in blocks} == {(block, 0, bar.inner)}
    assert [x0 for x0, _, _, _ in blocks] == [k * (block + gap) for k in range(len(blocks))]
    bar.set(2, 3)
    assert bar.shown[0] == "66.7%"
    bar.set(3, 48)                      # 6.25 %: a half rounds up, as by hand
    assert bar.shown[0] == "6.3%"
    bar.set(1, 400)
    assert bar.shown[0] == "0.3%"
    bar.set(3, 3)
    assert bar.shown == ("100.0%", bar.room)
    bar.set(0, 0)
    assert not bar.cover.winfo_manager()


def drawn_under_the_text(bar):
    """[(colour of the bar, colour of the text)] at each column of the filled part that the
    percentage crosses, as the bar draws them: a canvas laid in a gap covers the second
    canvas (navy blocks on the field's face, the white text), which covers the field."""
    cover, filled = bar.cover, bar.shown[1]
    x0, _, x1, _ = cover.bbox(bar.cover_text)           # one column wider on each side
    blocks = [cover.coords(item) for item in cover.find_all() if item != bar.cover_text]
    pieces = {}                                         # column -> the canvas laid there
    for piece in cover.winfo_children():
        left = int(piece.place_info()["x"])
        pieces.update(dict.fromkeys(range(left, left + int(piece.cget("width"))), piece))
    columns = []
    for x in range(x0 + 1, min(x1 - 1, filled)):
        piece = pieces.get(x)
        if piece is not None:
            (item,) = piece.find_all()
            columns.append((piece.cget("background"), piece.itemcget(item, "fill")))
        else:
            navy = any(left <= x < right for left, _, right, _ in blocks)
            columns.append((style.NAVY if navy else cover.cget("background"),
                            cover.itemcget(bar.cover_text, "fill")))
    return columns


@pytest.mark.parametrize("scale", [1.0, 1.5, 2.25])
def test_the_percentage_is_white_on_the_blocks_only(make_root, scale):
    """Dark on the field, in the gaps between the blocks too, and white on navy:
    each gap the text can cross holds a dark copy of it, in line with the white one."""
    root = make_root(scale)
    style.apply(root)
    for width in (frame.BAR_WIDTH, 74):         # the default bar, the cache's hit rate
        bar = frame.PercentBar(root, width=width)
        cover, text = bar.cover, bar.cover_text
        blocks = [cover.coords(item) for item in cover.find_all() if item != text]
        for part, whole in ((4, 7), (2, 3), (3, 4), (7, 8), (19, 20), (999, 1000), (1, 1)):
            bar.set(part, whole)
            columns = drawn_under_the_text(bar)
            assert columns and set(columns) <= {(style.NAVY, style.WINDOW),
                                                (style.FACE, style.TEXT)}, (width, bar.shown)
            x, y = cover.coords(text)
            for piece in cover.winfo_children():
                (item,) = piece.find_all()
                left = int(piece.place_info()["x"])
                right = left + int(piece.cget("width"))
                assert not any(x0 < right and left < x1 for x0, _, x1, _ in blocks)
                assert piece.coords(item) == [x - left, y]
                assert [piece.itemcget(item, option) for option in ("text", "font", "anchor")] \
                    == [cover.itemcget(text, option) for option in ("text", "font", "anchor")]


def test_no_pictures_are_made_for_the_counter(app, tmp_path):
    made = pictures(app.root)
    loaded(app, tmp_path, COUNT)
    window = connected(app)
    app.run("step")
    go_to_end(app)
    window.reset_button.invoke()
    window.close()
    assert pictures(app.root) == made


def test_refreshing_shows_only_what_changed(app, tmp_path):
    loaded(app, tmp_path, COUNT)
    window = connected(app)
    shows = []
    show = window.show
    window.show = lambda: shows.append(1) or show()
    app.run("step")
    app.run("reset")                            # nothing ran: nothing to show again
    assert len(shows) == 1
