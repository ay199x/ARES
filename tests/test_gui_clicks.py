# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Mouse clicks reach every command: each menu item and each toolbar button.

The clicks are the mouse's real events (a press and a release) sent to the
menus' pop-up windows, the bar and the buttons, so that they go through the
bindings and the grab as on the screen; the commands themselves are only
noted. The menus also work when Windows activates a menu's window at a
press, and they refuse that activation (Windows only).
"""

import sys
import tkinter as tk

import pytest
from conftest import pump
from test_gui_editing import PROGRAM, focus_moved, type_into
from test_gui_run import loaded
from test_menubar import bar  # noqa: F401  (a fixture)
from test_menubar import (EDIT, FILE, TITLES, TOOLS, editor_text, entry_index, field_open,
                          focus_on, item_point, key, made, mouse, tap, title_point)

from ares.gui import menubar as menubar_module


class Noted(list):
    """The commands the clicks ran, in order, from start() on: the window's commands are
    then only noted."""

    def __init__(self, app, monkeypatch):
        super().__init__()
        self.app, self.monkeypatch = app, monkeypatch

    def start(self):
        self.monkeypatch.setattr(self.app, "run", self.append)
        self.monkeypatch.setattr(self.app, "_setting_toggled",
                                 lambda name: self.append("setting " + name))


@pytest.fixture
def ran(app, monkeypatch):
    return Noted(app, monkeypatch)


def command_of(app, menu, index):
    """What choosing item index of menu runs: its command, or its setting."""
    for name, (where, k) in app._menu_items.items():
        if where is menu and k == index:
            return name
    variable = menu.entries[index].variable
    return next("setting " + name for name, var in app.setting_vars.items() if var is variable)


def click_title(bar, index):
    """Press and release the mouse on a title of the bar."""
    point = title_point(bar, index)
    mouse(bar.canvas, "<ButtonPress-1>", *point)
    mouse(bar.canvas, "<ButtonRelease-1>", *point, held=True)
    pump(bar)                                               # the grab is in place


def click_item(menu, index):
    """Move the mouse onto an item of the open menu, press and release it there."""
    point = item_point(menu, index)
    mouse(menu.canvas, "<Motion>", *point)
    mouse(menu.canvas, "<ButtonPress-1>", *point)
    mouse(menu.canvas, "<ButtonRelease-1>", *point, held=True)
    pump(menu)


def click_button(button):
    made(button)
    button.event_generate("<ButtonPress-1>", x=3, y=3)
    button.event_generate("<ButtonRelease-1>", x=3, y=3, state=0x100)
    pump(button)


def closed(bar, app):
    """The menus are closed and no grab is left behind."""
    return not bar.active and bar.open_menu is None and app.root.grab_current() is None


@pytest.mark.parametrize("title", range(len(TITLES)), ids=TITLES)
def test_a_click_on_every_item_runs_it_and_a_gray_one_nothing(bar, app, tmp_path, ran, title):
    loaded(app, tmp_path, PROGRAM)
    ran.start()
    menu = bar.menus[title]
    settings = {name: var.get() for name, var in app.setting_vars.items()}
    for index, entry in enumerate(menu.entries):
        if entry.kind == "separator":
            continue
        click_title(bar, title)
        assert bar.open_menu is menu
        click_item(menu, index)
        if entry.kind == "cascade":
            assert ran == [] and bar.sub_menu is entry.menu, entry.label
            click_title(bar, title)
            assert closed(bar, app)
        elif menu.enabled(index):
            assert ran == [command_of(app, menu, index)], entry.label
            assert closed(bar, app), entry.label
        else:
            assert ran == [] and bar.open_menu is menu, entry.label     # as in Windows
            click_title(bar, title)
            assert closed(bar, app)
        ran.clear()
        for name, value in settings.items():
            app.setting_vars[name].set(value)


def test_a_press_dragged_from_each_title_to_an_item_runs_it(bar, app, tmp_path, ran):
    loaded(app, tmp_path, PROGRAM)
    ran.start()
    for title, menu in enumerate(bar.menus):
        index = next((k for k in range(len(menu.entries)) if menu.enabled(k)), None)
        if index is None:                                   # Help's items come with its pages
            continue
        mouse(bar.canvas, "<ButtonPress-1>", *title_point(bar, title))
        pump(bar)
        mouse(menu.canvas, "<Motion>", *item_point(menu, index), held=True)
        mouse(menu.canvas, "<ButtonRelease-1>", *item_point(menu, index), held=True)
        pump(bar)
        assert ran[-1:] == [command_of(app, menu, index)] and closed(bar, app), TITLES[title]


# Windows activates a menu's window at a press --------------------------------------------

@pytest.mark.parametrize("settled", ["before the press", "after the release"])
def test_an_item_still_runs_when_the_press_activates_its_menus_window(
        bar, app, monkeypatch, hidden_windows, ran, settled):
    """The menu's window takes the keyboard focus from the main window just before the press
    comes: the menus stay open for it; the bar takes the focus back once that is done."""
    ran.start()
    text = editor_text(app)
    focus_on(app, monkeypatch, text)
    click_title(bar, FILE)
    menu = bar.menus[FILE]
    focus_on(app, monkeypatch, None)                        # the main window loses the focus,
    made(bar).event_generate("<FocusOut>")
    focus_on(app, monkeypatch, menu.canvas)                 # and the menu's window gets it
    assert bar.open_menu is menu
    if settled == "before the press":
        app.root.update_idletasks()
        assert bar.open_menu is menu and hidden_windows.focus is bar
    click_item(menu, entry_index(menu, "Open..."))
    app.root.update_idletasks()
    assert ran == ["open"] and closed(bar, app)
    assert hidden_windows.focus is text                     # given back before the command


def test_the_menus_close_when_the_focus_really_left(bar, app, monkeypatch, hidden_windows, ran):
    ran.start()
    click_title(bar, TOOLS)
    focus_on(app, monkeypatch, None)                        # another program came to the front
    made(bar).event_generate("<FocusOut>")
    app.root.update_idletasks()
    assert closed(bar, app) and ran == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' activation")
def test_the_menus_windows_refuse_the_activation_a_press_asks_for(bar, app):
    import ctypes
    user32 = ctypes.WinDLL("user32")
    user32.SendMessageW.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t,
                                    ctypes.c_ssize_t)
    user32.SendMessageW.restype = ctypes.c_ssize_t
    menu = bar.menus[FILE]
    frame = int(menu.wm_frame(), 16)
    canvas = made(menu.canvas).winfo_id()
    question = (0x0201 << 16) | 1                           # WM_LBUTTONDOWN, HTCLIENT

    def answer():
        return user32.SendMessageW(canvas, menubar_module.WM_MOUSEACTIVATE, frame, question)
    length = user32.SendMessageW(frame, 0x000E, 0, 0)      # WM_GETTEXTLENGTH, Tk's answer
    menubar_module.refuse_activation(menu, frame)
    menubar_module.refuse_activation(menu, frame)           # once per frame window
    assert answer() == menubar_module.MA_NOACTIVATE
    assert user32.SendMessageW(frame, 0x000E, 0, 0) == length   # the rest still goes to Tk


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' window procedures")
def test_a_refusing_window_gives_tk_its_procedure_back_when_destroyed(app, monkeypatch):
    window = tk.Toplevel(app.root)
    made(window)
    frame = int(window.wm_frame(), 16)
    user32 = menubar_module._user32()
    tk_procedure = user32.get_procedure(frame, menubar_module.GWLP_WNDPROC)
    menubar_module.refuse_activation(window, frame)
    assert user32.get_procedure(frame, menubar_module.GWLP_WNDPROC) != tk_procedure
    seen = []
    give_back = menubar_module._give_procedure_back

    def noted(widget, event):
        give_back(widget, event)
        if event.widget is widget:
            seen.append(user32.get_procedure(frame, menubar_module.GWLP_WNDPROC))
    monkeypatch.setattr(menubar_module, "_give_procedure_back", noted)
    window.destroy()
    assert seen == [tk_procedure]


def test_a_shown_menu_refuses_the_activation(bar, monkeypatch):
    """float_inactive() gives the frame of a menu on the screen the refusing procedure."""
    if sys.platform != "win32":
        pytest.skip("Windows' activation")
    noted = []
    monkeypatch.setattr(menubar_module, "refuse_activation",
                        lambda window, frame: noted.append((window, frame)))
    menu = bar.menus[EDIT]
    made(menu)
    monkeypatch.setattr(menu, "winfo_viewable", lambda: True)
    menubar_module.float_inactive(menu)
    assert noted == [(menu, int(menu.wm_frame(), 16))]


# The toolbar, also after the menus were used ----------------------------------------------

def close_by_item(bar, app, monkeypatch):
    click_title(bar, FILE)
    click_item(bar.menus[FILE], entry_index(bar.menus[FILE], "New"))


def close_by_escape(bar, app, monkeypatch):
    click_title(bar, EDIT)
    focus_on(app, monkeypatch, bar)
    key(bar, "Escape")
    key(bar, "Escape")


def close_by_title(bar, app, monkeypatch):
    click_title(bar, EDIT)
    mouse(bar.canvas, "<ButtonPress-1>", *title_point(bar, EDIT))
    mouse(bar.canvas, "<ButtonRelease-1>", *title_point(bar, EDIT), held=True)


def close_by_press_outside(bar, app, monkeypatch):
    click_title(bar, EDIT)
    mouse(bar, "<ButtonPress-1>", -3000, -3000)             # brought to the bar by its grab
    mouse(bar, "<ButtonRelease-1>", -3000, -3000, held=True)


def close_by_alt(bar, app, monkeypatch):
    click_title(bar, EDIT)
    focus_on(app, monkeypatch, bar)
    tap(bar, "Alt_L")


def close_by_focus(bar, app, monkeypatch):
    click_title(bar, EDIT)
    focus_on(app, monkeypatch, None)
    made(bar).event_generate("<FocusOut>")
    app.root.update_idletasks()
    focus_on(app, monkeypatch, editor_text(app))


def close_by_moving(bar, app, monkeypatch):
    click_title(bar, EDIT)
    made(app.root).event_generate("<Configure>", x=40, y=50, width=900, height=700)


CLOSINGS = {"an item chosen": close_by_item, "Escape twice": close_by_escape,
            "its title pressed again": close_by_title, "a press outside": close_by_press_outside,
            "Alt": close_by_alt, "the focus leaving ARES": close_by_focus,
            "the window moved": close_by_moving}


@pytest.mark.parametrize("closing", [None, *CLOSINGS])
def test_a_click_on_every_toolbar_button_runs_it_also_after_a_menu(bar, app, tmp_path,
                                                                  monkeypatch, ran, closing):
    loaded(app, tmp_path, PROGRAM)
    ran.start()
    if closing is not None:
        CLOSINGS[closing](bar, app, monkeypatch)
        pump(app.root)
        assert closed(bar, app), closing
        ran.clear()
    for name, button in app.buttons.items():
        available = button.instate(["!disabled"])
        click_button(button)
        assert ran == ([name] if available else []), name
        ran.clear()
    assert closed(bar, app)


def test_with_a_register_field_open_clicks_run_their_commands(bar, app, tmp_path, monkeypatch,
                                                              ran):
    """A click on the toolbar or a menu item leaves the field to the command (which applies
    it): it is not closed by the press, and the command runs."""
    field = field_open(app, tmp_path)
    ran.start()
    focus_on(app, monkeypatch, field)
    type_into(app.registers, "7")
    click_button(app.buttons["step"])
    assert ran == ["step"] and app.registers.editor is field
    click_title(bar, FILE)
    focus_on(app, monkeypatch, bar)
    focus_moved(app.registers, bar, monkeypatch)             # the field hears the bar took it
    click_item(bar.menus[FILE], entry_index(bar.menus[FILE], "New"))
    assert ran == ["step", "new"] and app.registers.editor is field and closed(bar, app)


def test_with_a_register_field_open_a_click_on_step_applies_it_and_steps(app, tmp_path,
                                                                        monkeypatch):
    field = field_open(app, tmp_path)
    focus_on(app, monkeypatch, field)
    type_into(app.registers, "7")
    pc = app.machine.reg(15)
    click_button(app.buttons["step"])
    assert app.registers.editor is None and app.machine.reg(1) == 7
    assert app.machine.reg(15) == pc + 4


@pytest.mark.parametrize("closing", CLOSINGS)
def test_no_grab_is_left_after_a_menu_closes(bar, app, tmp_path, monkeypatch, ran, closing):
    loaded(app, tmp_path, PROGRAM)
    ran.start()
    CLOSINGS[closing](bar, app, monkeypatch)
    pump(app.root)
    assert closed(bar, app)
    ran.clear()
    text = made(editor_text(app))                           # a press elsewhere reaches its widget
    presses = []
    text.bind("<ButtonPress-1>", lambda event: presses.append(event.widget), add="+")
    mouse(text, "<ButtonPress-1>", 5, 5)
    mouse(text, "<ButtonRelease-1>", 5, 5, held=True)
    assert presses == [text] and ran == []
    click_title(bar, FILE)                                  # and the menus open and work again
    click_item(bar.menus[FILE], entry_index(bar.menus[FILE], "Open..."))
    assert ran == ["open"] and closed(bar, app)
