# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Shared test helpers: build and run programs from source text."""

import faulthandler
import os
import re
import sys
import time
from pathlib import Path

import pytest

from ares.assembler import assemble
from ares.machine import Machine
from ares.program import Program
from ares.runner import Runner

ROOT = Path(__file__).resolve().parent.parent
PROGRAMS = ROOT / "tests" / "programs"
TEST_SCREEN = (1707, 960)       # 2560 x 1440 at 150 %: ARES starts there at 1635 x 858


@pytest.fixture
def build(tmp_path):
    """Assemble source text and return the loaded Program."""
    def _build(source):
        result = assemble(source, tmp_path)
        assert result.ok, [m.format() for m in result.messages]
        return Program(result.elf_path)
    return _build


@pytest.fixture
def run(build):
    """Assemble, load and run source text; return the stopped Machine."""
    def _run(source, time_limit=10, input_text=""):
        machine = Machine(build(source))
        machine.console.feed(input_text)
        assert machine.run(time_limit=time_limit) is not None, "program did not stop"
        return machine
    return _run


@pytest.fixture
def make_runner(build, tmp_path):
    """Assemble source text and return a Runner for it (files relative to tmp_path).

    input_text, when given, is all the typed input there will be.
    """
    def _make(source, dialogs=None, input_text=None, record_while_running=False):
        machine = Machine(build(source), base_dir=tmp_path)
        if input_text is not None:
            machine.console.feed(input_text)
            machine.console.close_input()
        return Runner(machine, dialogs=dialogs, record_while_running=record_while_running)
    return _make


class Screen:
    """What the code asked the window system for; no window really appears."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.shown = set()              # windows asked to be shown and not hidden since
        self.zoomed = set()             # windows asked to be maximized
        self.focus = None               # the last widget that asked for the keyboard focus
        self.roots = []                 # Tk roots made since the reset

    def shows(self, window):
        return window in self.shown


SCREEN = Screen()
VIRTUAL_DISPLAY_VARIABLE = "ARES_VIRTUAL_DISPLAY"       # set where nobody can see the windows
VIRTUAL_DISPLAY = bool(os.environ.get(VIRTUAL_DISPLAY_VARIABLE))
MAKE_WINDOWS = frozenset(("app", "make_app", "make_mapped_app", "tk_root", "make_root", "area",
                         "mapped_area", "make_table"))
NO_WINDOWS_ON_MACOS = ("Tk on macOS gives a hidden window no size, and many windows one after "
                       "the other end the process")
NEEDS_THE_KEYBOARD_FOCUS = frozenset((
    "test_edit_commands_bring_the_editor_to_the_front_with_the_focus",
    "test_a_click_on_every_item_runs_it_and_a_gray_one_nothing",
    "test_a_press_dragged_from_each_title_to_an_item_runs_it",
    "test_a_click_on_every_toolbar_button_runs_it_also_after_a_menu",
    "test_with_a_register_field_open_clicks_run_their_commands",
    "test_no_grab_is_left_after_a_menu_closes",
    "test_the_page_brought_to_the_top_gets_the_real_focus",
    "test_control_keys_altgr_alt_space_and_alt_f4_are_left_to_windows",
    "test_the_keys_of_other_windows_are_left_alone",
    "test_the_page_of_a_pressed_views_tab_gets_the_keyboard_focus",
    "test_a_wrong_register_value_keeps_its_field_when_a_tab_is_pressed",
    "test_a_click_on_an_item_of_the_submenu_closes_all_and_runs_it",
    "test_a_click_on_a_gray_item_of_the_submenu_leaves_it_open",
    "test_a_click_on_another_item_of_the_menu_runs_it_with_the_submenu_open",
    "test_a_gray_item_with_a_submenu_does_not_open_under_the_mouse",
    "test_a_bar_destroyed_during_the_wait_leaves_no_job",
    "test_a_press_that_activates_the_submenus_window_still_chooses",
    "test_the_keys_of_a_notebook_still_change_the_tab",
    "test_the_selected_tab_shows_the_keyboard_focus",
))


def _hide_every_window():
    """Make tkinter keep every window off the screen for the rest of the test run.

    Tk roots and toplevels stay withdrawn, showing and maximizing are only
    recorded in SCREEN, and a native dialog (message box, file chooser) fails
    instead of waiting on the screen. These are plain assignments, not
    monkeypatch, so that no test can take them back: monkeypatch.undo() in a
    test would undo them too.

    On X11 a window that was never mapped has no size, and its widgets no places. The tests run
    there on a virtual display, with nothing to see, so the windows are mapped on it.
    On macOS the tests make no windows at all (NO_WINDOWS_ON_MACOS); tools/check_package.py runs
    the programs and opens the tools in a real package there.
    """
    import tkinter
    from tkinter import commondialog

    tk_init, toplevel_init = tkinter.Tk.__init__, tkinter.Toplevel.__init__
    withdraw, window_state = tkinter.Wm.wm_withdraw, tkinter.Wm.wm_state
    focus_set, focus_force = tkinter.Misc.focus_set, tkinter.Misc.focus_force

    def keep_off_the_screen(window):
        if not VIRTUAL_DISPLAY:
            withdraw(window)

    def hidden_tk(self, *args, **options):
        if sys.platform == "darwin":
            pytest.skip(NO_WINDOWS_ON_MACOS)
        tk_init(self, *args, **options)
        if options.get("use") is None:  # an embedded window shows only in its container
            keep_off_the_screen(self)
        SCREEN.roots.append(self)

    def hidden_toplevel(self, *args, **options):
        toplevel_init(self, *args, **options)
        if options.get("use") is None:
            keep_off_the_screen(self)

    def show(self):
        SCREEN.shown.add(self)

    def hide(self):
        keep_off_the_screen(self)
        SCREEN.shown.discard(self)

    def state(self, newstate=None):
        if newstate is None:
            return window_state(self)
        if newstate == "withdrawn":
            hide(self)
        elif newstate in ("normal", "zoomed"):
            show(self)
            if newstate == "zoomed":
                SCREEN.zoomed.add(self)
        return None

    def take_focus(original):
        def focus(self):
            SCREEN.focus = self
            original(self)
        return focus

    def no_dialog(self, **options):
        raise AssertionError(f"the test would open a {type(self).__name__} dialog")

    tkinter.Tk.__init__ = hidden_tk
    tkinter.Toplevel.__init__ = hidden_toplevel
    tkinter.Wm.wm_deiconify = tkinter.Wm.deiconify = show
    tkinter.Wm.wm_withdraw = tkinter.Wm.withdraw = hide
    tkinter.Wm.wm_state = tkinter.Wm.state = state
    tkinter.Misc.focus_set = tkinter.Misc.focus = take_focus(focus_set)
    tkinter.Misc.focus_force = take_focus(focus_force)
    commondialog.Dialog.show = no_dialog


def pytest_collection_modifyitems(items):
    """On the virtual display no window manager gives a window the keyboard focus, and how fast
    a window draws there says nothing about a real screen."""
    if VIRTUAL_DISPLAY:
        skip = pytest.mark.skip(reason="needs a window manager: no window has the keyboard focus")
        slow = pytest.mark.skip(reason="a virtual display draws in software")
        for item in items:
            if item.originalname in NEEDS_THE_KEYBOARD_FOCUS:
                item.add_marker(skip)
            elif item.get_closest_marker("serial") and MAKE_WINDOWS & set(item.fixturenames):
                item.add_marker(slow)


@pytest.fixture(autouse=True)
def stop_a_test_that_hangs():
    """With ARES_TEST_LIMIT set, end a test that takes more seconds than that, with its process:
    a run on a rented machine then reports it instead of waiting."""
    limit = os.environ.get("ARES_TEST_LIMIT")
    if limit:
        faulthandler.dump_traceback_later(int(limit), exit=True, file=sys.__stderr__)
    yield
    if limit:
        faulthandler.cancel_dump_traceback_later()


@pytest.fixture(scope="session", autouse=True)
def no_window_on_the_screen():
    """Hide every window of the test run (see _hide_every_window)."""
    _hide_every_window()


@pytest.fixture(autouse=True)
def hidden_windows():
    """The Screen of the test: what its code asked the window system for.

    Hidden windows never get the keyboard focus, so tests use press_key()
    instead of key events, and the Screen to see which windows the code
    showed or maximized and which widget it gave the focus.
    """
    import tkinter
    SCREEN.reset()
    yield SCREEN
    for root in SCREEN.roots:
        try:
            mapped = root.winfo_ismapped()
        except tkinter.TclError:
            continue                    # already destroyed
        assert not mapped, "the test showed a window"


def press_key(widget, sequence, virtual=None):
    """Run the bindings Tk would run for a key press on widget; return the tags that ran.

    A hidden window never has the keyboard focus, so a generated key event
    would not reach it. This runs, for each of the widget's bind tags in
    order, its binding for exactly this sequence (with the % fields filled
    in), and stops after a binding that ends the event with break. virtual
    is the virtual event Tk makes of the key (<<NextWindow>> of Tab): a tag
    without a binding for the key itself runs the one for virtual, as Tk does.
    """
    # Every field becomes one Tcl word, as Tk makes it: an empty one is {}.
    fields = {"%W": f"{{{widget}}}", "%T": "2", "%K": "{??}", "%A": "{}"}
    ran = []
    for tag in widget.bindtags():
        script = widget.tk.call("bind", tag, sequence)
        if not script and virtual is not None:
            script = widget.tk.call("bind", tag, virtual)
        if not script:
            continue
        ran.append(tag)
        script = re.sub(r"%.", lambda m: fields.get(m.group(), "0"), script)
        stopped = widget.tk.eval(
            f"set ::press_stopped 1\nforeach _ {{1}} {{\n{script}\nset ::press_stopped 0\n}}\n"
            "set ::press_stopped")
        if stopped == "1":
            break
    return ran


def native(widget):
    """Give a widget and everything in it a native window, as on the screen; none is shown.

    Only widgets with one get <Configure> events, and only texts with one
    redraw and call their scroll commands. Widgets made later need this too.
    """
    widget.winfo_id()
    for child in widget.winfo_children():
        native(child)


def pump(root, limit=20000):
    """Process Tk events until none is left (True), or until limit events were processed (False).

    A layout that never settles keeps making events, so update() would not
    return; this always does.
    """
    import _tkinter
    for _ in range(limit):
        if not root.tk.dooneevent(_tkinter.ALL_EVENTS | _tkinter.DONT_WAIT):
            return True
    return False


def lay_out(root, limit=20000):
    """Lay a hidden window out as on the screen; True when its events then ran out (pump).

    Every widget gets its native window, and the parts packed in the window
    are arranged again: a withdrawn window takes its size without telling them.
    """
    native(root)
    for part in root.pack_slaves():
        part.pack_configure()
    return pump(root, limit)


def fixed_screen(monkeypatch):
    """Make the ARES windows the test starts from now on start as on a screen of TEST_SCREEN.

    ARES starts at most of the screen, so a test that counts on what fits
    in its panes would pass or fail with the screen it runs on. Tk gives a
    hidden window the size it has when it first updates, even one larger
    than the screen, but a later one only once the window is shown.
    """
    import tkinter

    from ares.gui.widgets import px
    width, height = TEST_SCREEN
    monkeypatch.setattr(tkinter.Misc, "winfo_screenwidth", lambda self: px(self, width))
    monkeypatch.setattr(tkinter.Misc, "winfo_screenheight", lambda self: px(self, height))


@pytest.fixture
def area():
    """make(width, height): a frame of that fixed size in a hidden window, laid out as on screen.

    The window has the classic look, and its size before anything is packed
    in it; give the widgets put in the frame their native windows (lay_out).
    """
    from tkinter import ttk

    from ares.gui import style
    roots = []

    def make(width, height):
        root = new_root()
        style.apply(root)
        root.geometry(f"{width + 40}x{height + 40}")
        root.winfo_id()
        root.update()
        frame = ttk.Frame(root, width=width, height=height)
        frame.pack_propagate(False)
        frame.pack()
        roots.append(root)
        return frame
    yield make
    for root in roots:
        root.destroy()


@pytest.fixture
def mapped_area():
    """make(width, height): a window whose widgets are mapped, with nothing on the screen.

    A hidden window's widgets are never mapped, so ttk gives their elements no places:
    identify finds nothing, and no press reaches a thumb. A window embedded in a hidden one
    is mapped for Tk while the system shows nothing.
    """
    import tkinter

    from ares.gui import style
    from ares.gui.widgets import is_aqua
    roots = []

    def make(width, height):
        root = new_root()
        if is_aqua(root):
            root.destroy()
            pytest.skip("no embedded windows here")
        roots.append(root)
        style.apply(root)
        root.geometry(f"{width + 40}x{height + 40}")
        holder = tkinter.Frame(root, container=True)
        holder.place(x=0, y=0, width=width, height=height)
        root.update()
        inside = tkinter.Toplevel(root, use=holder.winfo_id())
        root.update()
        assert inside.winfo_viewable() and (VIRTUAL_DISPLAY or not root.winfo_viewable())
        return inside
    yield make
    for root in roots:
        root.destroy()


@pytest.fixture
def make_mapped_app(tmp_path):
    """make(): an ARES window that is mapped, with nothing on the screen (see mapped_area).

    Unlike a hidden window it knows which widget the keyboard focus goes to. An error raised
    in a Tk callback fails the test, as in make_app.
    """
    import tkinter

    from ares.gui.app import App
    from ares.gui.widgets import is_aqua
    started = []
    errors = []

    def embedded():
        """(hidden window, root embedded in it). A root that starts inside another reads
        Tk's library files as new_root does, and can fail now and then in the same way."""
        for attempt in range(5):
            outer = new_root()
            if is_aqua(outer):
                outer.destroy()
                pytest.skip("no embedded windows here")
            outer.geometry("1740x990")
            holder = tkinter.Frame(outer, container=True)
            holder.place(x=0, y=0, width=1700, height=950)
            outer.update()
            try:
                return outer, tkinter.Tk(use=str(holder.winfo_id()))
            except tkinter.TclError as e:
                error = e
                outer.destroy()
                time.sleep(0.2)
        pytest.skip(f"Tk is not available: {error}")

    def make():
        outer, root = embedded()
        windows = {"outer": outer, "app": None}
        started.append(windows)
        app = windows["app"] = App(root, settings_path=tmp_path / "settings.json")
        report = app.report_error

        def record(kind, value, trace):
            errors.append(value)
            report(kind, value, trace)
        root.report_callback_exception = record
        root.update()
        assert pump(root)
        assert app.views.winfo_viewable() and (VIRTUAL_DISPLAY or not outer.winfo_viewable())
        return app
    yield make
    for windows in started:
        try:
            if windows["app"] is not None:
                windows["app"].close()
        except tkinter.TclError:
            pass                        # already closed by the test
        windows["outer"].destroy()
    assert not errors, f"errors in Tk callbacks: {errors!r}"


def use_test_clipboard(root):
    """Give the Tk interpreter of root a clipboard of its own; the system one is left alone."""
    root.tk.eval("""
        rename ::clipboard {}
        rename ::tk::GetSelection {}
        set ::test_clipboard ""
        proc ::clipboard {option args} {
            switch -- $option {
                clear {set ::test_clipboard ""}
                append {append ::test_clipboard [lindex $args end]}
                get {return $::test_clipboard}
            }
        }
        proc ::tk::GetSelection {w {selection PRIMARY}} {return $::test_clipboard}
    """)


def new_root():
    """A new Tk root, or skip the test where Tk cannot open a window.

    Starting Tk reads its library files; on a busy Windows machine that can
    fail now and then, so it is tried a few times.
    """
    import tkinter
    for attempt in range(5):
        try:
            return tkinter.Tk()
        except tkinter.TclError as e:
            error = e
            time.sleep(0.2)
    pytest.skip(f"Tk is not available: {error}")


@pytest.fixture(scope="session")
def tk_root():
    """One hidden Tk root for widget tests; skipped where Tk cannot open a window."""
    root = new_root()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def make_app(tmp_path):
    """Start hidden ARES windows with their settings in tmp_path; all are closed afterwards.

    An error raised in a Tk callback (a binding, a menu command, an after
    job) fails the test; the window itself would only show it in ARES Messages.
    """
    import tkinter

    from ares.gui.app import App
    apps = []
    errors = []

    def make(**options):
        root = new_root()
        app = App(root, settings_path=tmp_path / "settings.json", **options)
        report = app.report_error

        def record(kind, value, trace):
            errors.append(value)
            report(kind, value, trace)
        root.report_callback_exception = record
        root.update()
        apps.append(app)
        return app
    yield make
    for app in apps:
        try:
            app.close()
        except tkinter.TclError:
            pass                        # already closed by the test
    assert not errors, f"errors in Tk callbacks: {errors!r}"


@pytest.fixture
def app(make_app):
    return make_app()
