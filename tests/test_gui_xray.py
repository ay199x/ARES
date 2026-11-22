# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The ARM X-Ray's window: its toolbar, the film and its controls, when it plays, what it shows,
the picture, and that it costs nothing while the program runs."""

import math
import time

import pytest
from test_gui_assemble import assemble
from test_gui_run import go_to_end, loaded, max_speed, run_until, slow, type_line
from test_xray import word_of  # noqa: F401  (a fixture)

from conftest import ROOT, lay_out, press_key, pump
from window_layout import at_size
from window_layout import clashes as widget_clashes
from xray_layout import clashes

from ares import credits, xray, xray_film
from ares.gui.tools import TOOLS
from ares.gui.tools import xray as tool
from ares.gui.tools import xray_look as look
from ares.gui.tools import xray_picture as picture
from ares.gui.tools.xray import (CANVAS, MAX_ZOOM, Player, XRayWindow, fields_of, value_text,
                                 zoom_for)
from ares.gui.widgets import px, scale
from ares.runner import State

PROGRAM = """\
        .global _start
_start: LDR     R1, =table
        LDR     R0, [R1, #4]
        STR     R0, [R1, R2]
        CMP     R0, #0
        MOVEQ   R3, #1
        BL      function
        UMULL   R4, R5, R0, R0
        SVC     #10
function:
        MOV     PC, LR
table:  .word   7, 8, 9
"""
FOREVER = """\
        .global _start
_start: ADD     R0, R0, #1
        B       _start
"""
LARGEST = (ROOT / "tests" / "programs" / "largest.s").read_text()


class Clock:
    """A clock the test moves by hand."""

    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def opened(app):
    app.run("tool_xray")
    window = app.tool_windows["tool_xray"]
    clock = Clock()
    window.clock = clock
    window.player.clock = clock
    window.test_clock = clock
    return window


def connected(app):
    window = opened(app)
    window.connect_button.invoke()
    assert window.model.connected
    return window


def steps(app, count):
    for _ in range(count):
        app.run("step")


def text_of(window, item):
    return window.canvas.itemcget(item, "text")


def heading(window):
    return text_of(window, window.view_heading)


def panel(window):
    """What the panel beside the table says, its two columns one after the other."""
    return window.panel_text()


def sentence(window):
    """The sentence of the step shown now: the last line of the tip of the strip's part that
    plays (with the film at its end, of the last part that has a tip)."""
    canvas = window.canvas
    tips = [window.tip_text(f"strip:{index}") for index in range(len(window.strip))]
    playing = [index for index, (box, _) in enumerate(window.strip)
               if canvas.itemcget(box, "outline") == look.INK]
    index = playing[0] if playing else max((i for i, tip in enumerate(tips) if tip),
                                           default=None)
    return tips[index].split("\n")[-1] if index is not None else ""


def at(window, seconds):
    """Move the film's clock and draw what it shows then, as a tick of the timer does."""
    window.test_clock.now += seconds
    window._tick()


def to_end(window):
    at(window, window.film.seconds + 1)


def canvas_state(window):
    """Everything drawn on the canvas, to compare two pictures (in any stacking order: a label
    comes to the top where it is placed)."""
    canvas = window.canvas
    state = []
    for item in canvas.find_all():
        options = {}
        for name in ("fill", "outline", "width", "state", "text", "dash", "arrow"):
            try:
                options[name] = canvas.itemcget(item, name)
            except Exception:
                pass
        coords = tuple(round(c, 1) for c in canvas.coords(item))
        state.append((canvas.type(item), coords, tuple(sorted(options.items()))))
    return sorted(state)


def timers(window):
    return window.window.tk.splitlist(window.window.tk.call("after", "info"))


def wire_colour(window, name):
    """The colours of a net's overlay lines that show (empty: it did not travel)."""
    canvas = window.canvas
    return {canvas.itemcget(window.picture.items[(name, index)], "fill")
            for index in range(len(picture.PATHS[name]))
            if canvas.itemcget(window.picture.items[(name, index)], "state") == "normal"}


# The window ----------------------------------------------------------------------------

def test_it_comes_first_in_the_tools_menu(app):
    assert TOOLS[0].command == "tool_xray" and TOOLS[0].label == "&ARM X-Ray"
    window = opened(app)
    assert isinstance(window, XRayWindow) and window.window.title() == "ARM X-Ray"
    assert window.HEADING == "Animation of the ARM Datapath"


def test_the_toolbar_has_the_main_windows_assemble_step_and_backstep(app, tmp_path):
    window = opened(app)
    assert list(window.tool_buttons) == ["assemble", "step", "backstep"]
    for name, button in window.tool_buttons.items():
        assert str(button.cget("image")[0]) == str(app.images[name][0])
    assert window.tool_buttons["step"].instate(["disabled"])
    loaded(app, tmp_path, PROGRAM)
    assert window.tool_buttons["step"].instate(["!disabled"])
    assert window.tool_buttons["backstep"].instate(["disabled"])
    window.tool_buttons["step"].invoke()
    assert len(app.machine.history) == 1
    assert window.tool_buttons["backstep"].instate(["!disabled"])
    window.tool_buttons["backstep"].invoke()
    assert len(app.machine.history) == 0


def test_the_keys_of_the_main_window_work_in_the_tools_window(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    press_key(window.canvas, "<Key-F7>")
    assert len(app.machine.history) == 1
    press_key(window.canvas, "<Key-F8>")
    assert len(app.machine.history) == 0
    assert "F7" in window.tool_tips[1].text


def test_the_scale_is_chosen_to_fit_the_screen():
    canvas = CANVAS
    # 1366 x 768 at 100 %: 720 of work area under a title bar of 31 and a frame of 8.
    assert zoom_for((0, 0, 1366, 720), (8, 31), (16, 128), canvas) == 1.0
    # 3840 x 2160 at 225 %: the picture is drawn larger.
    k = 2.25
    large = zoom_for((0, 0, 3840, 2052), (round(8 * k), round(31 * k)), (16 * k, 128 * k),
                     (canvas[0] * k, canvas[1] * k))
    assert 1.2 <= large <= MAX_ZOOM
    # Never under 1: the smallest text stays 8 points.
    assert zoom_for((0, 0, 800, 600), (8, 31), (16, 128), canvas) == 1.0


def test_the_whole_window_fits_1366_by_768_at_100_percent(app):
    """At its least size, the picture at zoom 1, the window fits the work area of 1366 x 768 at
    100 %: 720 high under a title bar of 31 and a frame of 8."""
    window = opened(app)
    lay_out(window.window)
    k = scale(window.window)
    width, height = (size / k for size in window.min_size())
    assert width + 2 * 8 <= 1366, width
    assert height + 31 + 8 <= 768 - 48, height
    settled_at(window, *window.min_size())
    assert window.zoom == 1.0


def test_no_text_is_smaller_than_8_points(app):
    window = opened(app)
    canvas = window.canvas
    from tkinter import font as tkfont
    for item in canvas.find_all():
        if canvas.type(item) == "text":
            size = tkfont.Font(root=canvas, font=canvas.itemcget(item, "font")).actual("size")
            assert size >= 8 or size <= -11, canvas.itemcget(item, "text")


# Resizing ----------------------------------------------------------------------------------

def settled_at(window, width, height):
    """The window's contents laid out as if its inside were width x height pixels, and its
    picture drawn again as it is once the size has settled; returns the part laid out."""
    part = at_size(window.window, width, height)
    window._room_settled()
    lay_out(window.window)
    return part


def font_sizes(canvas):
    """The sizes in points of the fonts of the texts drawn on canvas."""
    from tkinter import font as tkfont
    return {tkfont.Font(root=canvas, font=canvas.itemcget(item, "font")).actual("size")
            for item in canvas.find_all() if canvas.type(item) == "text"}


# A maximized window's inside on a screen: its work area under the title bar. Tk's scaling at
# 225 % is HIGH (3.0); at 100 % it stays as the tests start.
MAXIMIZED = {"1366 x 768": ((1366, 697), None), "1920 x 1080": ((1920, 1017), None),
             "3840 x 2160 at 225 %": ((3840, 2000), 3.0)}


@pytest.mark.parametrize("size", ["least", "usual", *MAXIMIZED])
def test_the_window_lays_out_whole_at_its_least_usual_and_maximized_sizes(app, tmp_path, size):
    """Nothing is cut off, Tool Control's buttons included; the picture fills its room in
    proportion, never under zoom 1, and no text of it lies over anything."""
    inside, scaling = MAXIMIZED.get(size, (None, None))
    before = float(app.root.tk.call("tk", "scaling"))
    if scaling is not None:
        app.root.tk.call("tk", "scaling", scaling)
    try:
        loaded(app, tmp_path, MIXED)
        window = connected(app)
        steps(app, 5)                           # ADD R4, R0, R3, LSL #1
        window.skip()
        k = scale(window.window)
        width, height = inside or {"least": window.min_size(), "usual": window.usual}[size]
        part = settled_at(window, width, height)
        assert widget_clashes(part) == []
        assert window.zoom == {"least": 1.0, "usual": window.usual_zoom}.get(size, window.zoom)
        assert window.zoom >= 1.0 and min(font_sizes(window.canvas)) >= 8
        room = (window.room.winfo_width() - window.border[0],
                window.room.winfo_height() - window.border[1])
        canvas = (int(window.canvas.cget("width")), int(window.canvas.cget("height")))
        assert canvas[0] / canvas[1] == pytest.approx(CANVAS[0] / CANVAS[1], rel=0.005)
        assert canvas[0] <= room[0] and canvas[1] <= room[1]
        if size != "least":                     # as large as fits: one more step would not
            larger = (CANVAS[0] * k * (window.zoom + 0.01), CANVAS[1] * k * (window.zoom + 0.01))
            assert round(larger[0]) > room[0] or round(larger[1]) > room[1]
        assert clashes(window.canvas) == []
        if size == "3840 x 2160 at 225 %":
            assert window.zoom == pytest.approx(MAXIMIZED_HIGH)
    finally:
        app.root.tk.call("tk", "scaling", before)


def test_the_window_opens_at_its_usual_size_each_time(app):
    window = opened(app)
    usual, least, zoom = window.usual, window.min_size(), window.usual_zoom
    assert (window.window.winfo_reqwidth(), window.window.winfo_reqheight()) == usual
    assert window.zoom == zoom and least[0] < usual[0] and least[1] < usual[1]
    assert window.window.minsize() == least
    settled_at(window, usual[0] + 300, usual[1] + 200)
    assert window.zoom > zoom
    window.close()
    window = opened(app)                        # the size is not kept
    assert window.usual == usual and window.zoom == zoom


@pytest.mark.parametrize("wider, taller", [(0, 0), (0, 300), (200, 0)])
def test_the_picture_stays_at_the_top_under_the_toolbar(app, wider, taller):
    """In a window taller than the picture needs, the picture stays right under the toolbar
    and the room left over is below it; in a wider one, it stays in the middle across."""
    window = opened(app)
    width, height = window.usual
    zoom = window.zoom
    settled_at(window, width + wider, height + taller)
    room, field = window.room, window.field
    assert window.zoom == zoom                  # the other side holds the picture as it was
    assert field.winfo_y() == 0
    assert room.winfo_height() - field.winfo_height() >= taller - 1
    assert abs(field.winfo_x() - (room.winfo_width() - field.winfo_width()) / 2) <= 1
    assert room.winfo_y() - (window.bar.winfo_y() + window.bar.winfo_height()) <= px(window.bar, 5)


def test_the_picture_is_drawn_again_only_once_the_size_has_settled(app, monkeypatch):
    window = opened(app)
    lay_out(window.window)                      # native windows, to have <Configure> events
    time.sleep(0.3)
    pump(app.root)                              # a settling the layout started is done
    settled = []
    monkeypatch.setattr(window, "_room_settled", lambda: settled.append(1))
    room = window.room
    width, height = window.usual
    for step in range(1, 30):                   # a drag: the size changes at every pixel
        room.event_generate("<Configure>", width=width + step, height=height + step)
    pump(app.root)
    assert settled == []                        # not for every pixel of the drag
    time.sleep(0.3)
    pump(app.root)
    assert settled == [1]                       # once, when the size stopped changing


def test_a_film_goes_on_after_the_window_is_resized(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    window = connected(app)
    steps(app, 6)                               # LDR R3, [R1]
    at(window, window.film.seconds / 3)
    film, moment = window.film, window.player.moment
    window.rezoom(1.6)
    assert window.zoom == 1.6 and window.film is film     # the same film, at its moment
    assert window.player.playing and window._job is not None
    assert window.player.moment == pytest.approx(moment)
    assert sentence(window) == film.steps[film.at(moment)[0]].sentence
    shown = canvas_state(window)                # as a window at 1.6 from the start draws it
    window.picture.drawn, window._shown = None, None
    window._draw_moment(film, window.player.moment)
    assert canvas_state(window) == shown
    at(window, 1)
    assert window.player.moment == pytest.approx(moment + 1)
    to_end(window)
    ended = texts_shown(window)
    assert not window.player.playing and "What it did:" in panel(window)
    window.rezoom(1.0)                          # finished: it stays finished, the same
    assert texts_shown(window) == ended and not window.player.playing


def test_a_film_waits_while_the_picture_is_drawn_again_at_a_new_size(app, tmp_path,
                                                                     monkeypatch):
    """Drawing a large window's first picture takes long (a second at 3840 x 2160): the film
    does not move on meanwhile, and goes on from where it was once the picture is drawn."""
    loaded(app, tmp_path, LARGEST)
    window = connected(app)
    steps(app, 6)
    at(window, window.film.seconds / 3)
    moment = window.player.moment
    canvas_class = type(window.canvas)

    def slow(canvas):
        window.test_clock.now += 2.0            # the paint of the new picture takes two seconds
    monkeypatch.setattr(canvas_class, "update_idletasks", slow, raising=False)
    window.rezoom(1.6)
    monkeypatch.undo()
    assert window.player.playing and window._job is not None
    assert window.player.moment == pytest.approx(moment)
    at(window, 1)
    assert window.player.moment == pytest.approx(moment + 1)


def test_a_paused_film_stays_where_it_was_after_a_resize(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    window = connected(app)
    steps(app, 5)
    window.skip()                               # Step's film has ended: One step forward is on
    window.one_button.invoke()                  # LDR R3, [R1]: its first step, and it waits
    to_end(window)
    held, moment = texts_shown(window), window.player.moment
    window.rezoom(1.3)
    assert window.player.paused_at == pytest.approx(moment) and window.player.held
    assert texts_shown(window) == held and pause_shows(window) == "Play"
    window.one_button.invoke()                  # One step forward goes on with the second step
    to_end(window)
    second = window.film.steps[1]
    assert window.player.paused_at == pytest.approx(second.start + second.duration)


def texts_shown(window):
    """The texts the canvas shows, with their colours, in any order."""
    canvas = window.canvas
    return sorted((canvas.itemcget(item, "text"), canvas.itemcget(item, "fill"))
                  for item in canvas.find_all() if canvas.type(item) == "text"
                  and canvas.itemcget(item, "state") != "hidden" and canvas.itemcget(item, "text"))


def test_the_help_says_the_window_can_be_resized():
    words = " ".join(tool.HELP.split())
    for said in ("The window can be made larger, or maximized", "in proportion, its text with it",
                 "a film that plays goes on", "down to the size at which the smallest text has "
                 "8 points", "The windows inside the blocks grow and shrink in the same way",
                 "opens at its usual size"):
        assert said in words, said


def test_the_help_credits_the_textbook_and_says_one_clock_cycle():
    words = " ".join(tool.HELP.split())
    assert credits.TEXTBOOK in words
    assert "within one clock cycle" in words


def test_before_connecting_it_says_what_to_do(app):
    window = opened(app)
    assert "Connect to ARM" in heading(window)
    assert window.pause_button.instate(["disabled"]) and window.back_button.instate(["disabled"])


def test_connected_before_anything_ran_it_shows_nothing_and_names_the_next(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    assert heading(window) == "Nothing has run yet"
    assert not window.player.playing and window.film.steps == ()
    assert wire_colour(window, "PC") == set()
    assert "Next: PC = 0x00000000," in panel(window) and "LDR R1" in panel(window)


def test_after_a_run_that_kept_no_history_it_shows_the_instruction_that_runs_next(app,
                                                                                   tmp_path):
    loaded(app, tmp_path, FOREVER)
    window = connected(app)
    app.run("step")
    to_end(window)
    max_speed(app)
    app.run("go")
    deadline = time.monotonic() + 0.3
    while time.monotonic() < deadline:
        app.root.update()
    app.run("pause")                    # the run dropped the history: the instruction at PC
    assert heading(window) == "Runs next"
    assert "It has not run yet." in panel(window)
    assert wire_colour(window, "PC") == {look.VALUES["pc"]}


# The film ----------------------------------------------------------------------------------

def test_a_step_plays_the_film_of_the_instruction_it_ran(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    app.run("step")
    assert heading(window) == "Just executed"
    assert window.player.playing and window._job is not None
    assert sentence(window).startswith("The PC holds 0x00000000")
    assert text_of(window, window.heading_item) == "LOAD INSTRUCTION"
    canvas = window.canvas
    box, label = window.strip[0]
    assert canvas.itemcget(box, "fill") == look.STAGES["Fetch"]
    assert canvas.itemcget(box, "outline") == look.INK
    assert panel(window).startswith("Next: PC = ")     # the rest of the panel comes at the end
    assert "What it did" not in panel(window)
    to_end(window)
    assert not window.player.playing and window._job is None
    assert "What it did:" in panel(window)
    assert f"R1 0x00000000 -> 0x{app.machine.reg(1):08X}" in panel(window)
    assert sentence(window).startswith("At the clock edge the PC takes 0x00000004")


def test_the_parts_of_the_film_come_in_order_with_the_strip(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    app.run("step")
    canvas = window.canvas
    seen = []
    for step in window.film.steps:
        window.test_clock.now = window.player.start + step.start + step.duration / 2
        window._tick()
        current = [name for (box, label), name in zip(window.strip, xray_film.PARTS)
                   if canvas.itemcget(box, "outline") == look.INK]
        assert current == [step.part]
        assert sentence(window) == step.sentence
        seen.append(step.part)
    assert seen == sorted(seen, key=xray_film.PARTS.index)


def test_the_film_lasts_the_time_of_the_slider_and_keeps_it(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    window.speed_scale.set(5)
    window._speed_moved(5)
    assert window.seconds == 5 and app.settings.xray_seconds == 5
    assert "5 s per instruction" in window.speed_label.cget("text")
    app.run("step")
    assert window.film.seconds == 5
    at(window, 4.9)
    assert window.player.playing
    at(window, 0.2)
    assert not window.player.playing
    from ares.settings import Settings
    assert Settings.load(app.settings_path).xray_seconds == 5


def test_changing_the_speed_during_a_film_keeps_its_place(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    app.run("step")
    at(window, window.film.seconds / 2)
    window.speed_scale.set(40)
    window._speed_moved(40)
    assert window.film.seconds == 40
    assert window.player.moment == pytest.approx(20, abs=0.5)


def pause_shows(window):
    """Which picture the Play and Pause button shows, checked against its image and its tip."""
    name = window.pause_picture
    assert str(window.pause_button.cget("image")[0]) == str(window.film_images[name][0])
    assert window.film_tips[0].text == tool.FILM_TIPS[name]
    return {"film_pause": "Pause", "film_play": "Play"}[name]


def test_pause_and_play_with_the_button_and_the_space_bar(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    app.run("step")
    at(window, 2)
    assert pause_shows(window) == "Pause"
    window.pause_button.invoke()
    assert window.player.paused_at == pytest.approx(2) and pause_shows(window) == "Play"
    assert window.film_tips[0].text.startswith("Play") and "(Space)" in window.film_tips[0].text
    moment = window.player.moment
    window.test_clock.now += 5
    assert window.player.moment == moment
    press_key(window.canvas, "<space>")
    assert window.player.playing and pause_shows(window) == "Pause"
    # Space on the focused Connect button pauses too, and leaves the tool connected.
    press_key(window.connect_button, "<space>")
    assert window.player.paused_at is not None and window.model.connected
    press_key(window.animate_box, "<space>")
    assert window.player.playing and window.animate.get()


FILM_BUTTONS = (("pause_button", "film_play", "Play", "Space"),
                ("back_button", "film_back", "One step back", "B"),
                ("one_button", "film_step", "One step forward", "O"),
                ("skip_button", "film_end", "Skip to end", "E"))


def test_the_film_buttons_are_pictures_beside_the_toolbars_with_name_and_key(app):
    window = opened(app)
    slaves = window.bar.pack_slaves()
    places = [slaves.index(getattr(window, attribute)) for attribute, *_ in FILM_BUTTONS]
    assert places == sorted(places) and places[0] > slaves.index(window.tool_buttons["backstep"])
    assert places[-1] - places[0] == 3                  # side by side, as on the toolbar
    for (attribute, picture_name, name, key), tip in zip(FILM_BUTTONS, window.film_tips):
        button = getattr(window, attribute)
        assert str(button.cget("style")) == "Toolbutton" and not str(button.cget("text"))
        normal, _, disabled = button.cget("image")
        assert (str(normal), str(disabled)) == tuple(str(image) for image in
                                                     window.film_images[picture_name])
        assert not window.window.tk.getboolean(button.cget("takefocus"))
        assert tip.text.startswith(f"{name}: ") and tip.text.endswith(f" ({key})")
        size = round(24 * scale(window.window))     # the toolbar's icons' size
        assert window.film_images[picture_name][0].width() == size
    assert "Assemble the current file (F3)" == window.tool_tips[0].text
    assert window.tool_tips[1].text == ("Step: runs the next instruction and plays its whole "
                                        "film (F7)")
    # No key of the main window: its shortcuts are F keys and Ctrl with a letter.
    assert not {"O", "B", "E", "Space"} & set(app._keys.values())


def test_the_film_keys_held_with_control_or_alt_are_left_alone(app, tmp_path):
    """Ctrl+O, Ctrl+B, Alt+E...: a key of another command, not of the film."""
    class Key:
        def __init__(self, state):
            self.state = state
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    app.run("step")
    at(window, 1)
    for state in (tool.CONTROL, window._alt, tool.CONTROL | window._alt):
        assert window._film_key(Key(state), window.skip_button) is None
        assert window.player.playing
    assert window._film_key(Key(0x1), window.skip_button) == "break"   # Shift: E
    assert not window.player.playing


def test_playing_to_the_end_skipping_and_the_finished_view_draw_the_same(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    window = connected(app)
    steps(app, 6)                               # to LDR R3, [R1]
    assert text_of(window, window.view_text).endswith("LDR R3, [R1]")
    at(window, 0.1)
    for _ in range(80):
        at(window, window.film.seconds / 60)
    played = canvas_state(window)
    app.run("backstep")                         # the same instruction again, its whole film
    app.run("step")
    at(window, 3)
    window.skip_button.invoke()
    skipped = canvas_state(window)
    window.show()
    finished = canvas_state(window)
    assert played == skipped == finished


def test_animate_off_shows_each_step_finished_at_once(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    window.animate_box.invoke()
    assert not window.animate.get() and not app.settings.xray_animate
    app.run("step")
    assert not window.player.playing and "What it did:" in panel(window)
    assert window.mode is None                  # no film that has not ended
    window.one_button.invoke()                  # One step forward still goes a step at a time
    assert window.mode == tool.STEPS and window.player.playing
    to_end(window)
    first = window.film.steps[0]
    assert window.player.held
    assert window.player.paused_at == pytest.approx(first.start + first.duration)


def test_a_step_during_a_film_starts_the_next_film(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    app.run("step")
    at(window, 3)
    app.run("step")
    assert window.player.playing and window.player.moment == pytest.approx(0)
    assert text_of(window, window.view_text).endswith("LDR R0, [R1, #4]")


TWO_MOVES = """\
        .global _start
_start: MOV     R0, #20
        MOV     R1, #20
        SVC     #10
"""


def test_backstep_shows_what_it_showed_before_that_step(app, tmp_path):
    loaded(app, tmp_path, TWO_MOVES)
    window = connected(app)
    before_any = (heading(window), panel(window))
    steps(app, 2)
    to_end(window)
    app.run("backstep")                 # MOV R0, #20 finished, as after the first Step
    assert heading(window) == "Just executed" and not window.player.playing
    assert window._job is None and window.player.moment == window.film.seconds
    assert text_of(window, window.instruction_item) == "MOV R0, #20    (MOV R0, #0x14)"
    assert text_of(window, window.view_text) == "0x00000000  MOV R0, #20"
    assert "R0 0x00000000 -> 0x00000014" in panel(window)
    assert "Next: PC = 0x00000004," in panel(window) and "MOV R1, #20" in panel(window)
    assert wire_colour(window, "PC") == {look.VALUES["pc"]}
    app.run("backstep")                 # nothing has run: the empty picture, as at the start
    assert (heading(window), panel(window)) == before_any
    assert heading(window) == "Nothing has run yet"
    assert not window.player.playing and window.film.steps == ()
    assert wire_colour(window, "PC") == set()
    assert "Next: PC = 0x00000000," in panel(window) and "MOV R0, #20" in panel(window)
    assert text_of(window, window.view_text) == "" == text_of(window, window.instruction_item)
    assert window.back_button.instate(["disabled"]) and window.pause_button.instate(["disabled"])
    assert window.one_button.instate(["!disabled"])
    assert window.tool_buttons["step"].instate(["!disabled"])
    app.run("step")                     # a Step after Backsteps plays its film as before
    assert window.player.playing and heading(window) == "Just executed"
    assert text_of(window, window.view_text) == "0x00000000  MOV R0, #20"


def test_backstep_after_a_push_an_svc_and_a_branch_shows_them_finished(app, tmp_path):
    loaded(app, tmp_path, """        .global _start
_start: LDR     SP, =0x4000
        MOV     R0, #25
        PUSH    {R0, LR}
        SVC     #1
        B       there
        NOP
there:  MOV     R2, #3
        SVC     #10
""")
    window = connected(app)
    steps(app, 6)
    for kind in (xray.BRANCH, xray.SYSTEM_CALL, xray.STORE_MULTIPLE):
        app.run("backstep")
        trace = window.model.view.trace
        assert trace.kind == kind and heading(window) == "Just executed"
        assert not window.player.playing and window.player.moment == window.film.seconds
        if kind == xray.SYSTEM_CALL:
            system = next(step for step in window.film.steps
                          if step.lights and step.lights[0][0] == "System")
            assert system.lights[0][1] == "SVC #1, print integer: R0 = 25"
        if kind == xray.STORE_MULTIPLE:                 # its last pass, finished
            assert len(window.film.passes) == 2
            assert text_of(window, window.heading_item).endswith("PASS 2 OF 2")
            assert "Memory 0x00003FF8: 0x00000000 -> 0x00000019" in panel(window)


def test_backstep_to_a_finished_svc_that_waits_again_plays_no_film(app, tmp_path):
    loaded(app, tmp_path, """        .data
buffer: .space  200
        .global _start
        .text
_start: LDR     R0, =buffer
        MOV     R1, #190
loop:   SVC     #8
        B       loop
""")
    window = connected(app)
    steps(app, 3)                       # the read waits for a line
    type_line(app, "abc")
    run_until(app, lambda: app.runner.state is not State.WAITING)
    steps(app, 2)                       # B loop, then the read waits again
    assert window.model.view.kind == xray.WAITING
    app.run("backstep")                 # B loop undone: the read that ended is shown
    view = window.model.view
    assert view.kind == xray.EXECUTED and view.trace.kind == xray.SYSTEM_CALL
    assert not window.player.playing and window._job is None


def test_backstep_from_the_end_of_the_program_says_just_executed(app, tmp_path):
    loaded(app, tmp_path, TWO_MOVES)
    window = connected(app)
    steps(app, 3)
    assert heading(window) == "Just executed; the program has ended"
    app.run("backstep")
    assert heading(window) == "Just executed" and not window.player.playing
    assert text_of(window, window.view_text) == "0x00000004  MOV R1, #20"


def test_at_a_slow_speed_each_instruction_shows_finished_with_no_film(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    slow(app, 25)
    app.run("go")
    run_until(app, lambda: len(app.machine.history) >= 2, limit=10)
    assert not window.player.playing and window._job is None
    app.run("pause")


def test_at_full_speed_refresh_does_no_work_and_a_film_stops(app, tmp_path, monkeypatch):
    loaded(app, tmp_path, FOREVER)
    window = connected(app)
    app.run("step")
    assert window._job is not None
    max_speed(app)
    looks = []
    update = window.model.update
    monkeypatch.setattr(window.model, "update", lambda: looks.append(1) or update())
    monkeypatch.setattr(xray, "upcoming", lambda *args: pytest.fail("traced while running"))
    app.run("go")
    deadline = time.monotonic() + 0.3
    while time.monotonic() < deadline:
        app.root.update()
    assert app.runner.state is State.RUNNING
    assert looks == [] and window._job is None
    monkeypatch.undo()
    app.run("pause")
    assert heading(window).startswith("Runs next")


def test_a_full_speed_run_during_a_film_draws_the_instruction_whole(app, tmp_path):
    loaded(app, tmp_path, FOREVER)
    window = connected(app)
    app.run("step")
    at(window, 1)
    max_speed(app)
    app.run("go")
    app.root.update()
    assert window._job is None and not window.player.playing
    assert window.player.moment == pytest.approx(window.film.seconds)
    assert "What it did:" in panel(window)
    app.run("pause")


READ = """        .data
buffer: .space  200
        .global _start
        .text
_start: LDR     R0, =buffer
        MOV     R1, #190
        SVC     #8
        SVC     #10
"""


def test_a_step_onto_a_read_plays_the_svc_up_to_the_system(app, tmp_path):
    loaded(app, tmp_path, READ)
    window = connected(app)
    steps(app, 2)
    app.run("step")                     # the read waits for a line
    assert app.runner.state is State.WAITING
    assert window.model.view.kind == xray.WAITING
    assert heading(window) == tool.WAITING_HEADINGS["input"]
    assert window.player.playing
    window.skip()
    (block, word), = window.film.steps[-1].lights
    assert block == "System" and word.startswith("SVC #8, read string: R0 = 0x")
    assert word.endswith("R1 = 190\nwaits for input")
    assert "It has not ended yet" in panel(window)
    canvas = window.canvas                  # the system still works: Execute plays, Next PC waits
    strip = [canvas.itemcget(box, "fill") for box, _ in window.strip]
    assert strip[2] == look.STAGES["Execute"] and strip[5] == strip[4] == look.WHITE
    assert canvas.itemcget(window.strip[2][0], "outline") == look.INK
    assert canvas.itemcget(window.picture.blocks["System"], "fill") == look.WORKING_FILL
    type_line(app, "abc")               # the line comes: the SVC ends, its film goes on
    run_until(app, lambda: app.runner.state is not State.WAITING)
    view = window.model.view
    assert view.kind == xray.EXECUTED and view.trace.kind == xray.SYSTEM_CALL
    assert window.player.playing
    system = next(step for step in window.film.steps
                  if step.lights and step.lights[0][0] == "System")
    assert window.player.moment >= system.start - 1e-6
    window.skip()
    assert system.lights[0][1].endswith("R1 = 190") and "waits" not in system.lights[0][1]


def test_connecting_after_stop_says_the_program_has_ended(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    steps(app, 2)
    app.run("stop")
    window = connected(app)
    assert heading(window) == "Just executed; the program has ended"


def test_connecting_again_after_stop_keeps_saying_so(app, tmp_path):
    loaded(app, tmp_path, FOREVER)
    window = connected(app)
    max_speed(app)
    app.run("go")
    app.root.update()
    app.run("stop")
    window.connect_button.invoke()
    window.connect_button.invoke()
    assert heading(window) == "The program has ended"


def test_a_new_program_after_stop_shows_that_nothing_has_run(app, tmp_path):
    loaded(app, tmp_path, FOREVER)
    window = connected(app)
    app.run("stop")
    assemble(app)
    assert heading(window) == "Nothing has run yet"


def test_a_long_memory_change_stays_one_short_line(app, tmp_path):
    loaded(app, tmp_path, READ)
    window = connected(app)
    app.machine.console.feed("x" * 150 + "\n")
    steps(app, 3)
    window.skip()
    lines = window.model.view.did
    assert any(line.endswith(" bytes") for line in lines)
    assert all(len(line) < 44 for line in lines)
    assert any(line.strip().endswith(" bytes") for line in panel(window).splitlines())


def test_many_changes_are_counted_not_listed(app, tmp_path):
    loaded(app, tmp_path, """        .global _start
_start: LDR     SP, =0x4000
        PUSH    {R0-R12}
        SVC     #10
""")
    window = connected(app)
    for number in range(13):
        app.machine.set_reg(number, number + 1)
    steps(app, 2)
    window.skip()                       # the film of its thirteen passes, at its end
    text = panel(window)
    changes = [line for line in text.splitlines() if line.startswith("  Memory")]
    assert len(changes) < 13 and "and " in text and " more" in text
    assert text.endswith("Next: PC = 0x00000008,\n      SVC #10")     # it never gives way
    assert "SP 0x00004000 -> 0x00003FCC" in text    # counting took back a word, not SP


def test_the_panel_lists_every_word_written_also_over_the_same_value(app, tmp_path):
    loaded(app, tmp_path, """        .global _start
_start: LDR     SP, =0x4000
        PUSH    {R4, R6}
        MOV     R1, #0
        STR     R1, [SP]
        SVC     #10
""")
    window = connected(app)
    steps(app, 2)                       # zeros over zeros
    window.skip()
    lines = panel(window).splitlines()
    assert "  Memory 0x00003FF8: 0x00000000 -> 0x00000000" in lines
    assert "  Memory 0x00003FFC: 0x00000000 -> 0x00000000" in lines
    assert "  no register or memory changed" not in lines
    steps(app, 2)                       # STR of the value already there
    window.skip()
    lines = panel(window).splitlines()
    assert lines[:3] == ["What it did:", "  Memory 0x00003FF8: 0x00000000 -> 0x00000000",
                         "  Flags NZCV 0000 -> 0000"]


def test_a_jump_to_no_code_shows_no_made_up_instruction(app, tmp_path):
    loaded(app, tmp_path, """        .global _start
_start: LDR     R1, =0x200000
        MOV     PC, R1
""")
    window = connected(app)
    steps(app, 3)
    assert "no program code" in heading(window)
    assert text_of(window, window.view_text) == ""
    assert window.pause_button.instate(["disabled"])


def test_disconnected_what_it_shows_stays(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 2)
    window.connect_button.invoke()
    app.run("step")
    assert text_of(window, window.view_text).endswith("LDR R0, [R1, #4]")


def test_reset_after_backsteps_back_to_the_start_shows_that_nothing_has_run(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 2)
    app.run("backstep")
    app.run("backstep")
    assert heading(window) == "Nothing has run yet"
    app.run("reset")
    assert heading(window) == "Nothing has run yet"


def test_after_backstep_the_instruction_undone_is_the_next_one(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 2)
    app.run("backstep")
    assert heading(window) == "Just executed"
    assert text_of(window, window.view_text) == "0x00000000  LDR R1, =table"
    assert panel(window).endswith("Next: PC = 0x00000004,\n      LDR R0, [R1, #4]")
    assert window.film.steps[-1].sentence.endswith("the next instruction is LDR R0, [R1, #4].")


def test_connected_it_adds_no_hook(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    machine = app.machine
    hooks = len(machine.uc._callbacks)
    window = opened(app)
    window.connect_button.invoke()
    app.run("step")
    to_end(window)
    assert len(machine.uc._callbacks) == hooks


def test_closing_the_window_cancels_its_timer(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    app.run("step")
    job = window._job
    assert job in timers(window)
    tk_root = app.root
    window.close()
    assert job not in tk_root.tk.splitlist(tk_root.tk.call("after", "info"))


def test_a_film_ticks_about_thirty_times_a_second(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    app.run("step")
    script = window.window.tk.call("after", "info", window._job)
    assert script
    assert tool.FRAME == 33


def count_canvas_work(window, monkeypatch):
    """A list that grows by one with each change the canvas is asked to make."""
    done = []
    canvas = window.canvas
    for name in ("coords", "itemconfigure", "tag_raise", "create_line", "create_text",
                 "delete"):
        original = getattr(canvas, name)
        monkeypatch.setattr(canvas, name,
                            lambda *args, _o=original, **options: done.append(1) or _o(*args,
                                                                                      **options))
    return done


def test_a_picture_of_the_film_changes_only_what_moves(app, tmp_path, monkeypatch):
    """While a film plays the main window must stay quick: each picture asks the canvas for a
    bounded number of changes, and fewer while the same step goes on."""
    loaded(app, tmp_path, LARGEST)
    window = connected(app)
    for _ in range(6):
        app.run("step")
    done = count_canvas_work(window, monkeypatch)
    worst = within = 0
    for _ in range(120):
        before = len(done)
        number = window.film.at(window.player.moment)[0]
        at(window, window.film.seconds / 120)
        changes = len(done) - before
        worst = max(worst, changes)
        if window.film.at(window.player.moment)[0] == number:
            within = max(within, changes)
    assert worst < 600, worst
    assert within < 250, within


@pytest.mark.serial
def test_a_picture_of_the_film_takes_little_time(app, tmp_path):
    """One picture takes a small part of the 33 milliseconds between two (the median, with
    the garbage collector held: a test run's large heap is not the film's doing)."""
    import gc
    loaded(app, tmp_path, LARGEST)
    window = connected(app)
    for _ in range(6):
        app.run("step")
    times = []
    gc.disable()
    try:
        for _ in range(60):
            start = time.perf_counter()
            at(window, window.film.seconds / 60)
            times.append(time.perf_counter() - start)
    finally:
        gc.enable()
    times.sort()
    assert times[len(times) // 2] < 0.008, times[len(times) // 2]
    assert times[-3] < 0.025, times[-3]


# What it shows -----------------------------------------------------------------------------

@pytest.mark.parametrize("line, kind", [
    ("ADD R0, R1, R2", "DATA PROCESSING INSTRUCTION"), ("LDR R0, [R1]", "LOAD INSTRUCTION"),
    ("STR R0, [R1]", "STORE INSTRUCTION"), ("B .", "BRANCH INSTRUCTION"),
    ("BX LR", "BRANCH INSTRUCTION"), ("SVC #1", "SYSTEM CALL"),
    ("MUL R0, R1, R2", "MULTIPLY INSTRUCTION"), ("UMULL R0, R1, R2, R3", "MULTIPLY INSTRUCTION"),
    # The trace of an LDM or STM is its last pass: the heading says which pass it shows.
    ("PUSH {R0, R1}", "STORE MULTIPLE INSTRUCTION, PASS 2 OF 2"),
    ("POP {R0, R1}", "LOAD MULTIPLE INSTRUCTION, PASS 2 OF 2"),
    ("LDM R0, {R1}", "LOAD MULTIPLE INSTRUCTION"),
    ("MOVW R0, #1", "DATA PROCESSING INSTRUCTION"), ("MOVT R0, #1", "DATA PROCESSING INSTRUCTION"),
    ("LDRSB R0, [R1, R2]", "LOAD INSTRUCTION"), ("STRH R0, [R1], #2", "STORE INSTRUCTION"),
    ("LDRD R0, R1, [R2]", "INSTRUCTION OUTSIDE THE DATAPATH"),
])
def test_the_heading_names_the_kind_of_instruction(word_of, line, kind):
    trace = xray.trace(0, word_of(line), [0x100] * 16, 0x1D3, lambda a, s: bytes(s))
    assert tool.kind_heading(trace) == kind


@pytest.mark.parametrize("line, names", [
    ("ADD R0, R1, #4", "cond op I cmd S Rn Rd rot imm8"),
    ("ADD R0, R1, R2, LSL #3", "cond op I cmd S Rn Rd shamt5 sh 0 Rm"),
    ("ADD R0, R1, R2, LSL R3", "cond op I cmd S Rn Rd Rs 0 sh 1 Rm"),
    ("LDR R0, [R1, #4]", "cond op I P U B W L Rn Rd imm12"),
    ("STR R0, [R1, R2, LSL #2]", "cond op I P U B W L Rn Rd shamt5 sh 0 Rm"),
    ("BNE .", "cond op 1 L imm24"),
    ("SVC #1", "cond op 1 1 imm24"),
    ("PUSH {R4, LR}", "cond op 0 P U S W L Rn register list"),
    ("MUL R0, R1, R2", "cond op I cmd S Rd  Rs op2 Rm"),       # bits 15:12 of MUL: no field
    ("MLAS R10, R11, R12, R14", "cond op I cmd S Rd Ra Rs op2 Rm"),
    ("MOVT R0, #0x1234", "cond op funct imm4 Rd imm12"),
    ("LDRSH R0, [R1, #-6]!", "cond op 0 P U I W L Rn Rd imm4H op2 imm4L"),
    ("STRH R0, [R1], -R2", "cond op 0 P U I W L Rn Rd 0000 op2 Rm"),
])
def test_the_bit_display_has_the_fields_of_the_textbook(word_of, line, names):
    trace = xray.trace(0, word_of(line), [0x100] * 16, 0x1D3, lambda a, s: bytes(s))
    fields = fields_of(trace)
    assert " ".join(name for name, *_ in fields) == names
    covered = sorted(bit for _, high, low, _ in fields for bit in range(low, high + 1))
    assert covered == list(range(32))


# The table of the word: one instruction of each kind, as the next one to run.
TABLE_LINES = ["ADD R0, R1, #4", "ADD R0, R1, R2, LSL #3", "ADD R0, R1, R2, LSL R3", "MOV R0, R1",
               "CMP R1, #0", "MUL R0, R1, R2", "MLAS R10, R11, R12, R14", "LDR R0, [R1, #4]",
               "STR R0, [R1, R2, LSL #2]", "LDRSH R0, [R1, #-6]!", "STRH R0, [R1], -R2",
               "PUSH {R4, LR}", "LDM R0, {R1}", "BNE .", "BL .", "BX LR", "BLX R12", "SVC #1",
               "MOVW R0, #0x1234", "MOVT R0, #0x1234", "NOP", "LDRD R0, R1, [R2]"]


def showing(app, word_of, line):
    """The tool showing line's instruction, as the next one to run, finished; and its trace."""
    window = opened(app)
    trace = xray.trace(0, word_of(line), [0x100] * 16, 0x1D3, lambda a, s: bytes(s))
    window.model.view = xray.View(xray.NEXT, "Runs next", trace)
    window.show()
    return window, trace


def design_box(window, item):
    """The coordinates of a rectangle on the canvas, in design pixels."""
    return tuple(round(c / window.k, 1) for c in window.canvas.coords(item))


def centre_x(window, item):
    left, _, right, _ = window.canvas.bbox(item)
    return (left + right) / 2 / window.k


@pytest.mark.parametrize("line", TABLE_LINES)
def test_the_table_has_a_cell_for_each_field_as_wide_as_its_bits(app, word_of, line):
    window, trace = showing(app, word_of, line)
    canvas, top, row = window.canvas, tool.TABLE[1], tool.ROW
    fields = fields_of(trace)
    assert [(cell.name, cell.high, cell.low, cell.kind) for cell in window.cells] == fields
    covered = []
    for cell in window.cells:
        left, right = tool.bit_x(cell.high), tool.bit_x(cell.low) + tool.BIT_WIDTH
        assert right - left == (cell.high - cell.low + 1) * tool.BIT_WIDTH
        assert design_box(window, cell.boxes[0]) == pytest.approx((left, top, right, top + row))
        assert design_box(window, cell.boxes[1]) == pytest.approx(
            (left, top + row, right, top + 2 * row))
        if cell.name:                           # the name, in the middle of its cell
            assert canvas.itemcget(cell.label, "text") == cell.name
            assert centre_x(window, cell.label) == pytest.approx((left + right) / 2, abs=1)
            label = canvas.bbox(cell.label)     # it reads whole: no smaller font, no cut
            assert label[0] >= left * window.k and label[2] <= right * window.k
        else:
            assert cell.label is None
        bits = [canvas.itemcget(digit, "text") for digit in cell.digits]
        assert "".join(bits) == f"{trace.word >> cell.low & (1 << len(bits)) - 1:0{len(bits)}b}"
        for bit, digit in zip(range(cell.high, cell.low - 1, -1), cell.digits):
            assert centre_x(window, digit) == pytest.approx(
                tool.bit_x(bit) + tool.BIT_WIDTH / 2, abs=1)
        covered += range(cell.low, cell.high + 1)
    assert sorted(covered) == list(range(32))
    assert clashes(canvas) == []


@pytest.mark.parametrize("line", ["ADD R0, R1, #4", "SVC #1", "LDRD R0, R1, [R2]"])
def test_the_hex_row_has_the_words_digits_each_under_its_four_bits(app, word_of, line):
    window, trace = showing(app, word_of, line)
    canvas = window.canvas
    top, row = tool.TABLE[1] + 2 * tool.ROW, tool.ROW
    assert "".join(canvas.itemcget(digit, "text") for _, digit in window.hex_cells) == \
        f"{trace.word:08X}"
    for number, (box, digit) in enumerate(window.hex_cells):
        left = tool.bit_x(31 - 4 * number)
        assert design_box(window, box) == pytest.approx(
            (left, top, left + 4 * tool.BIT_WIDTH, top + row))
        assert centre_x(window, digit) == pytest.approx(left + 2 * tool.BIT_WIDTH, abs=1)
    assert canvas.itemcget(window.hex_prefix, "text") == "0x"   # before the first digit
    prefix = canvas.bbox(window.hex_prefix)
    assert prefix[2] <= canvas.bbox(window.hex_cells[0][0])[0] + 1
    assert prefix[0] >= (tool.TABLE[0] + 4) * window.k


@pytest.mark.parametrize("line", TABLE_LINES)
def test_a_lit_field_has_the_colour_of_the_wire_that_carries_it(app, word_of, line):
    """The table is the key of the colours: each field's cells have the colour of its value on
    the picture, the wire that carries it where it travels; the Hex row that of Instr."""
    window, trace = showing(app, word_of, line)
    window._light_fields(True)
    canvas = window.canvas
    used = set(window.film.used())
    for cell in window.cells:
        texts, boxes = cell_colours(window, cell)
        if cell.kind == "constant":             # fixed bits in ink; no field: gray and empty
            assert texts == ({picture.INK} if cell.name else {picture.IDLE})
            assert boxes == [tool.FIELD if cell.name else tool.EMPTY, tool.FIELD]
            continue
        wires = [net for net, (high, low) in tool.WORD_NETS.items()
                 if high >= cell.high and cell.low >= low and xray_film.KINDS[net] == cell.kind]
        assert wires, cell
        colour = look.field_colour(cell.kind)
        assert texts == {colour}, cell
        assert boxes == [tool.tinted(colour)] * 2
        for net in wires:
            if net in used:
                assert wire_colour(window, net) == {colour}, (cell, net)
    assert {canvas.itemcget(digit, "fill") for _, digit in window.hex_cells} == \
        {look.VALUES["instr"]}
    if window.film.steps:
        assert wire_colour(window, "Instr") == {look.VALUES["instr"]}
    window._light_fields(False)
    for cell in window.cells:
        assert cell_colours(window, cell)[0] == {picture.IDLE}


@pytest.mark.parametrize("line", TABLE_LINES)
def test_every_cell_has_a_tip_with_its_field_bits_value_and_way(app, word_of, line):
    window, trace = showing(app, word_of, line)
    for number, (name, high, low, kind) in enumerate(fields_of(trace)):
        lines = window.tip_text(f"field:f{number}").split("\n")
        assert len(lines) == 3 and all(lines), (name, lines)
        assert lines[0].startswith(f"{name}: ") if name else lines[0].startswith("No field")
        bits = f"Bit {high}, " if high == low else f"Bits {high}:{low}, "
        assert lines[1].startswith(bits + "value "), lines
        assert lines[2].startswith(("Goes on the wire ", "Goes nowhere: ")), lines
    for number in range(8):
        lines = window.tip_text(f"hex:h{number}").split("\n")
        high = 31 - 4 * number
        assert lines[0] == f"Hexadecimal digit {number + 1} of 8: bits {high}:{high - 3}"
        assert lines[1].startswith(f"Value: {trace.word >> high - 3 & 0xF:04b} = 0x")


def test_bits_that_are_no_field_stay_gray_and_empty(app, word_of):
    window, trace = showing(app, word_of, "MUL R0, R1, R2")    # bits 15:12 of MUL: no field
    window._light_fields(True)
    (empty,) = [cell for cell in window.cells if not cell.name]
    assert (empty.high, empty.low, empty.label) == (15, 12, None)
    assert cell_colours(window, empty) == ({picture.IDLE}, [tool.EMPTY, tool.FIELD])
    tip = window.tip_text(f"field:f{window.cells.index(empty)}")
    assert tip.startswith("No field of this instruction") and "Bits 15:12" in tip


def test_the_tip_of_a_cell_says_its_field_bits_value_and_where_it_goes(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    window = connected(app)
    steps(app, 6)                               # LDR R3, [R1]
    window.skip()
    assert window.model.view.trace.text == "LDR R3, [R1]"
    names = [cell.name for cell in window.cells]

    def tip(name):
        return window.tip_text(f"field:f{names.index(name)}").split("\n")
    assert tip("cond") == ["cond: the condition: when the instruction runs",
                           "Bits 31:28, value 1110 = 14: AL",
                           "Goes on the wire Cond to the control unit"]
    title, value, goes = tip("Rd")
    assert title == "Rd: the register loaded" and value == "Bits 15:12, value 0011 = 3: R3"
    assert goes.startswith("Goes on the wire Rd to the control unit") and "A3 multiplexer" in goes
    assert tip("Rn")[2].startswith("Goes on the wire Rn to the RA1 multiplexer")
    assert tip("imm12") == ["imm12: the 12-bit offset", "Bits 11:0, value 000000000000 = 0 = 0x0",
                            "Goes on the wire Imm to Extend"]
    assert tip("L") == ["L: 1: a load; 0: a store", "Bit 20, value 1",
                        "Goes on the wire Funct to the control unit"]
    word = window.model.view.trace.word
    assert window.tip_text("hex:h0") == (f"Hexadecimal digit 1 of 8: bits 31:28\n"
                                         f"Value: 1110 = 0xE = 14\n"
                                         f"The word, 0x{word:08X}, is the value on the wire Instr")
    window._pointer_moved(Event(*middle(window, window.hex_cells[0][1])))
    assert window._tip is not None and window._tip[0] == "hex:h0"


def test_the_strip_and_the_table_stand_under_the_picture_at_the_left(app, tmp_path):
    """From the top: the heading, the datapath, and under it at the left the strip of the six
    parts, as wide as the table (no line of sentences under it), the instruction as written and
    its table; at their right what the tool shows, the line on the blocks and what it did."""
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    app.run("step")
    to_end(window)
    canvas, k = window.canvas, window.k
    bottom = (picture.ORIGIN[1] + picture.SIZE[1]) * k
    heading = canvas.bbox(window.heading_item)
    assert heading[3] - 0.18 * (heading[3] - heading[1]) <= picture.ORIGIN[1] * k
    assert not hasattr(window, "sentence")
    strip = [canvas.bbox(box) for box, _ in window.strip]
    line = canvas.bbox(window.instruction_item)
    table = [canvas.bbox(item) for tag in ("table", "cells") for item in canvas.find_withtag(tag)]
    assert bottom <= min(box[1] for box in strip)
    assert max(box[3] for box in strip) <= line[1] + 1
    assert line[3] <= min(box[1] for box in table) + 1
    assert max(box[3] for box in table) <= float(canvas.cget("height"))
    right = max(box[2] for box in table)
    assert min(box[0] for box in strip) == pytest.approx(min(box[0] for box in table), abs=2)
    assert max(box[2] for box in strip) == pytest.approx(right, abs=2)
    for item in (window.view_heading, window.view_text, window.hint, *window.panels):
        assert canvas.bbox(item)[0] >= right, text_of(window, item)
    assert clashes(canvas) == []


def test_each_part_of_the_strip_has_its_sentences_so_far_as_its_tip(app, tmp_path):
    """A part that plays or has played has, as its tip, the sentences of its steps that have
    played so far, in order, one a line; a part not reached has none."""
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    app.run("step")                             # LDR R1, =table
    film = window.film
    for number, step in enumerate(film.steps):
        window.test_clock.now = window.player.start + step.start + step.duration / 2
        window._tick()
        part = xray_film.PARTS.index(step.part)
        for index, name in enumerate(xray_film.PARTS):
            said = [s.sentence for s in film.steps[:number + 1] if s.part == name]
            assert window.tip_text(f"strip:{index}") == "\n".join(said), (number, name)
            assert bool(said) == (index <= part)
    to_end(window)
    for index, name in enumerate(xray_film.PARTS):
        assert window.tip_text(f"strip:{index}") == "\n".join(
            s.sentence for s in film.steps if s.part == name)
    assert sentence(window).startswith("At the clock edge the PC takes 0x00000004")


def test_a_part_of_the_strip_shows_its_tip_as_the_wires_do(app, tmp_path):
    """The tips of the wires' machinery: the mouse over a part that has played brings its tip
    up; over a part not reached, nothing comes up."""
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    app.run("step")                             # the film's first step: only Fetch plays
    window._pointer_moved(Event(*middle(window, window.strip[1][1])))
    assert window._tip[0] == "strip:1"
    window._show_tip("strip:1", 0, 0)
    assert window._tip == ("strip:1", None, None)       # Decode not reached: no tip
    window._pointer_moved(Event(*middle(window, window.strip[0][0])))
    assert window._tip[0] == "strip:0"
    window._show_tip("strip:0", 0, 0)
    shown = window._tip[2]
    assert shown is not None and shown.winfo_children()[0].cget("text").startswith(
        "The PC holds 0x00000000")
    window._hide_tip()
    assert window._tip is None


def test_the_strip_tips_say_the_pass_shown(app, tmp_path):
    loaded(app, tmp_path, MULTIPLE)
    window = connected(app)
    steps(app, 5)                               # PUSH {R4, R5, LR}: three passes
    film = window.film
    second = film.passes[1]
    at(window, second.offset + second.seconds / 2 - (window.test_clock.now - window.player.start))
    tip = window.tip_text("strip:0").split("\n")      # Fetch, of the second pass only
    assert tip == [s.sentence for s in second.steps if s.part == "Fetch"]
    assert all(line.startswith("Pass 2 of 3: ") for line in tip)


def test_the_panel_has_the_outside_note_and_always_the_next_instruction(app, tmp_path):
    """What the line under the strip said only: with nothing run, "Nothing has run yet" stands
    right above the panel, which names the next instruction; an instruction outside the
    datapath has its note on the panel's first line, whole in its tip; the next instruction
    never gives way: more changes are counted instead."""
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    assert heading(window) == "Nothing has run yet"
    assert panel(window).startswith("Next: PC = 0x00000000,")
    steps(app, 8)                               # UMULL, outside the datapath
    note = text_of(window, window.note_item)
    assert note.endswith("...") and xray.NOTE_MULTIPLY.startswith(note[:-3])
    assert panel(window).splitlines()[:2] == [note, "What it did:"]
    assert " ".join(window.tip_text("note:panel").split()) == xray.NOTE_MULTIPLY
    canvas = window.canvas
    assert canvas.bbox(window.note_item)[3] <= min(canvas.bbox(item)[1] + 2
                                                   for item in window.panels)
    assert "Next: PC = 0x0000001C," in panel(window)
    assert clashes(canvas) == []
    steps(app, 1)                               # SVC #10, inside: no note
    assert text_of(window, window.note_item) == "" and window.tip_text("note:panel") == ""


def middle(window, item):
    left, top, right, bottom = window.canvas.bbox(item)
    return (left + right) // 2, (top + bottom) // 2


class Event:
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.x_root, self.y_root = x, y


def cell_colours(window, cell):
    """The colours of a field's name and bits in the table, and of its two cells."""
    canvas = window.canvas
    texts = [cell.label] * (cell.label is not None) + list(cell.digits)
    return ({canvas.itemcget(item, "fill") for item in texts},
            [canvas.itemcget(box, "fill") for box in cell.boxes])


def test_the_fields_light_when_the_word_splits(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    app.run("step")                             # LDR R1, [PC, #...]
    canvas = window.canvas
    rd = next(cell for cell in window.cells if cell.name == "Rd")
    assert cell_colours(window, rd) == ({picture.IDLE}, [tool.FIELD, tool.FIELD])
    assert {canvas.itemcget(digit, "fill") for _, digit in window.hex_cells} == {picture.IDLE}
    split = next(step for step in window.film.steps if step.fields)
    window.test_clock.now = window.player.start + split.start - 0.01
    window._tick()
    assert cell_colours(window, rd)[0] == {picture.IDLE}
    window.test_clock.now = window.player.start + split.start + 0.01
    window._tick()
    lit = tool.tinted(look.VALUES["rd"])
    assert cell_colours(window, rd) == ({look.VALUES["rd"]}, [lit, lit])
    assert {canvas.itemcget(digit, "fill") for _, digit in window.hex_cells} == \
        {look.VALUES["instr"]} == {canvas.itemcget(window.hex_prefix, "fill")}


def test_the_panel_agrees_with_the_registers_after_every_step(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    window = connected(app)
    for _ in range(14):
        app.run("step")
        if app.runner.state is State.WAITING:
            break
        window.skip()
        text = panel(window)
        if window.model.view.kind != xray.EXECUTED:
            continue
        for line in text.splitlines():
            parts = line.split()
            if parts and parts[0].startswith("R") and parts[0][1:].isdigit():
                number = int(parts[0][1:])
                assert int(parts[-1], 16) == app.machine.reg(number), line
        assert f"PC = 0x{app.machine.pc:08X}" in text


def test_an_instruction_outside_stays_gray_with_its_note(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 8)                               # UMULL, after BL and the return
    assert text_of(window, window.view_text).endswith("UMULL R4, R5, R0, R0")
    assert window.film.steps == () and not window.player.playing
    assert xray.NOTE_MULTIPLY.startswith(text_of(window, window.note_item)[:-3])
    assert all(window.tip_text(f"strip:{index}") == "" for index in range(6))
    assert "R4 0x00000000 -> 0x00000040" in panel(window)
    assert wire_colour(window, "PC") == set()


def test_a_failed_condition_writes_nothing_and_the_pc_goes_on(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 5)                               # MOVEQ R3, #1 with Z = 0
    window.skip()
    canvas = window.canvas
    assert canvas.itemcget(window.picture.gates["RegFile"], "state") == "normal"
    assert "R3" not in panel(window).split("Next")[0]
    assert "the condition failed" in " ".join(s.sentence for s in window.film.steps)


def test_tips_say_name_width_purpose_and_value(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    app.run("step")
    to_end(window)
    tip = window.tip_text("wire:PC")
    assert tip.startswith("PC, 32 bits") and "0x00000000 = 0" in tip and "0b" in tip
    assert window.tip_text("wire:RegWrite").startswith("RegWrite, 1 bit")
    assert "Now: 1" in window.tip_text("wire:RegWrite")
    assert window.tip_text("block:ALU").startswith("ALU\n")
    assert "Now: ADD" in window.tip_text("block:ALU")


def test_a_runtime_error_shows_the_instruction_that_failed(app, tmp_path):
    loaded(app, tmp_path, """\
        .global _start
_start: LDR     R1, =0x50000000
        LDR     R0, [R1]
""")
    window = connected(app)
    steps(app, 2)
    assert heading(window).startswith("Runtime error")      # cut short beside the heading
    assert "out of range" in panel(window)                  # whole beside the table
    assert text_of(window, window.view_text).endswith("LDR R0, [R1]")


def test_a_new_assembly_starts_again_and_stays_connected(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 2)
    assemble(app)
    assert window.model.connected and heading(window) == "Nothing has run yet"


def test_closing_the_file_leaves_it_connected_without_a_program(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    window.machine_changed(None)
    assert window.model.connected and heading(window) == "No program is loaded."


def test_at_full_speed_a_finished_program_says_so(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    max_speed(app)
    go_to_end(app)
    assert heading(window) == "The program has ended"


def test_reset_clears_the_picture(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    app.run("step")
    window.reset_button.invoke()
    assert window.model.view.kind == xray.NOTHING and wire_colour(window, "PC") == set()
    assert not window.player.playing


# The picture -------------------------------------------------------------------------------

def test_every_net_of_the_film_is_drawn_and_ends_at_its_ports():
    assert set(picture.PATHS) == set(xray_film.NETS)
    for name, (source, branches) in xray_film.NETS.items():
        polylines = picture.PATHS[name]
        assert {branch for branch, _ in polylines} == set(branches), name
        if source in picture.PORTS:
            assert polylines[0][1][0] == picture.PORTS[source], name
        last = {}
        for branch, points in polylines:
            last[branch] = points
        for branch, port in branches.items():
            if port in picture.PORTS:
                assert last[branch][-1] == picture.PORTS[port], (name, branch)


def test_every_polyline_starts_at_its_source_or_on_its_net():
    for name, polylines in picture.PATHS.items():
        for index, (branch, points) in enumerate(polylines):
            if index == 0:
                continue
            on = any(picture._along(other, points[0]) is not None
                     for _, other in polylines[:index])
            fields = name in ("Rd", "Rn", "Rs") and points[0][0] == picture.BUS   # a second tap
            assert on or fields, (name, index)


def test_the_wires_are_straight_lines_across_or_down():
    for name, polylines in picture.PATHS.items():
        for _, points in polylines:
            for (x1, y1), (x2, y2) in zip(points, points[1:]):
                assert x1 == x2 or y1 == y2, (name, points)


def outlines():
    shapes = {}
    for name, (left, right, top, bottom) in picture.MUX_BOXES.items():
        slope = (bottom - top) / 5
        shapes[name] = [(left, top), (right, top + slope), (right, bottom - slope), (left, bottom)]
    for name, (left, top, right, bottom) in picture.BOXES.items():
        shapes[name] = [(left, top), (right, top), (right, bottom), (left, bottom)]
    for name, points in picture.SHAPES.items():
        shapes[name] = list(points)
    return shapes


def strictly_inside(point, polygon, margin=1.5):
    """point lies inside polygon, further than margin from its outline."""
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
        length = math.dist((x1, y1), (x2, y2)) or 1
        along = max(0.0, min(1.0, ((x - x1) * (x2 - x1) + (y - y1) * (y2 - y1)) / length ** 2))
        if math.dist((x, y), (x1 + along * (x2 - x1), y1 + along * (y2 - y1))) <= margin:
            return False
    return inside


def test_no_wire_runs_through_a_block():
    shapes = outlines()
    for name, polylines in picture.PATHS.items():
        for _, points in polylines:
            for (x1, y1), (x2, y2) in zip(points, points[1:]):
                length = max(abs(x2 - x1), abs(y2 - y1), 1)
                for step in range(1, int(length)):
                    point = (x1 + (x2 - x1) * step / length, y1 + (y2 - y1) * step / length)
                    for block, polygon in shapes.items():
                        assert not strictly_inside(point, polygon), (name, block, point)


def test_the_datapath_stays_inside_its_area():
    width, height = picture.SIZE
    for polylines in picture.PATHS.values():
        for _, points in polylines:
            assert all(0 <= x <= width and 0 <= y <= height for x, y in points)


def test_every_net_has_a_colour_with_enough_contrast():
    """At least 3 to 1 on white and on the fills of the blocks; gray only on white and pale."""
    def luminance(colour):
        r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
        f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)

    def ratio(one, other):
        light, dark = sorted((luminance(one), luminance(other)), reverse=True)
        return (light + 0.05) / (dark + 0.05)
    for colour in list(look.VALUES.values()) + [picture.ON, picture.OFF, picture.INK]:
        for fill in list(look.FILLS.values()) + [look.WHITE]:
            assert ratio(colour, fill) >= 3.0, (colour, fill)
    assert ratio(picture.IDLE, look.WHITE) >= 3.0 and ratio(picture.IDLE, look.UNUSED_FILL) >= 3.0


MIXED = """        .global _start
_start: LDR     R1, =table
        MOV     R2, #2
        LDR     R0, [R1, #4]
        LDR     R3, [R1, R2, LSL #2]
        ADD     R4, R0, R3, LSL #1
        STR     R4, [R1, R2]
        STRB    R4, [R1, #1]
        CMP     R0, R3
        ADDNE   R5, R5, #1
        ANDS    R6, R0, #0xFF000000
        BL      function
        SVC     #10
function:
        BX      LR
        .data
table:  .word   0x11223344, 0x55667788, 0x99AABBCC, 0xDDEEFF00
"""


MULTIPLY = """        .global _start
_start: MOV     R4, #3
        MOV     R5, #7
        MOV     R6, #0x15
        MUL     R0, R4, R5
        MLA     R3, R4, R5, R6
        MLAS    R10, R11, R12, R14
        MULS    R7, R5, R5
        CMP     R4, R5
        MLAGTS  R8, R4, R5, R6
        MLALES  R9, R4, R5, R6
        MOV     R1, #0
        MULS    R2, R1, R5
        SVC     #10
"""


SHIFTS = """        .global _start
_start: LDR     SP, =stack
        MOV     R0, #7
        MOV     R1, #40
        MOV     R3, #2
        ADD     R2, R1, R0, LSL R3
        MOV     R5, #0x100
        MOVS    R4, R0, ROR R5
        TEQ     R1, R0, LSR R3
        CMP     R1, R0, ASR R3
        ADDS    R6, R1, R1
        ADC     R7, R0, R1
        SBCS    R8, R1, R0
        RSC     R9, R0, R1, LSL #1
        TEQ     R0, #7
        LDR     R10, =table
        STR     R2, [R10, R3]
        MLA     R11, R0, R3, R1
        ADR     R12, leaf
        BLX     R12
        NOP
        SVC     #10
leaf:   NOP
        BX      LR
        .data
table:  .word   0, 0, 0, 0
        .space  64
stack:  .word   0
"""
# Steps of SHIFTS: 5 ADD LSL R3, 7 MOVS ROR R5 (amount 0), 8 TEQ LSR R3, 9 CMP ASR R3, 11 ADC, 12
# SBCS, 13 RSC, 14 TEQ #7, 16 STR with a register offset, 17 MLA, 19 BLX, 20 and 22 NOP, 21 BX LR.
HALFWORDS = """        .global _start
_start: LDR     R1, =table
        MOV     R2, #2
        MOVW    R3, #0x8001
        MOVT    R3, #0xFFFE
        STRH    R3, [R1, #2]!
        STRH    R3, [R1], R2
        LDRH    R4, [R1, #-2]
        LDRSB   R5, [R1, #-1]!
        LDRSH   R6, [R1], #2
        LDRSB   R7, [R1, -R2]
        LDRH    R8, [R1, R2]!
        LDRSH   R9, [R1, R2]
        CMP     R2, #3
        LDREQH  R10, [R1]
        STRH    R4, [R1, -R2]!
        LDRB    R11, [R1]
        MOVW    R12, #0xFFFF
        SVC     #10
        .data
table:  .hword  0x1111, 0x2222, 0x3333, 0x4444
        .space  64
"""
# Steps of HALFWORDS: 3 MOVW, 4 MOVT, 5 STRH #2!, 6 STRH post-indexed by R2, 7 LDRH #-2, 8 LDRSB
# #-1!, 9 LDRSH post-indexed by #2, 10 LDRSB -R2, 11 LDRH R2!, 12 LDRSH R2, 14 LDRH whose condition
# fails, 15 STRH -R2!, 16 LDRB, 17 MOVW.
HALFWORDS_INSIDE = (3, 4, 5, 8, 9, 11, 14, 16)


# The zooms of a maximized window: on 1366 x 768, on 1920 x 1080, on 3840 x 2160 at 100 % (and
# at 225 %, MAXIMIZED_HIGH, with Tk's scaling HIGH).
MAXIMIZED_ZOOMS = [1.03, 1.61, 3.58]
MAXIMIZED_HIGH = 1.44


@pytest.mark.parametrize("zoom", [1.0, 1.3, 1.6] + MAXIMIZED_ZOOMS)
@pytest.mark.parametrize("source, counts", [(LARGEST, (6, 7, 8, 10, 11, 14, 35)),
                                            (MIXED, range(1, 14)), (MULTIPLY, range(1, 13)),
                                            (SHIFTS, range(1, 24)), (HALFWORDS, range(1, 19))],
                         ids=["largest", "mixed", "multiply", "shifts", "halfwords"])
def test_no_text_lies_over_a_text_a_wire_or_a_block(app, tmp_path, zoom, source, counts):
    loaded(app, tmp_path, source)
    window = connected(app)
    window._make_canvas(zoom)
    done = 0
    for count in counts:
        while done < count:
            app.run("step")
            done += 1
        window.skip()
        assert clashes(window.canvas) == [], (count, text_of(window, window.view_text))


@pytest.mark.parametrize("zoom", [1.0, 1.3, MAXIMIZED_ZOOMS[1]])
def test_no_text_lies_over_another_during_a_film(app, tmp_path, zoom):
    loaded(app, tmp_path, LARGEST)
    window = connected(app)
    window._make_canvas(zoom)
    for _ in range(6):
        app.run("step")
    for step in window.film.steps:
        window.test_clock.now = window.player.start + step.start + step.duration * 0.98
        window._tick()
        moving = lambda item: "moving" in window.canvas.gettags(item)  # noqa: E731
        assert clashes(window.canvas, ignore=moving) == [], step.sentence


def test_the_lengths_of_the_nets_come_from_the_picture():
    lengths = picture.lengths()
    assert set(lengths) == set(picture.PATHS)
    assert lengths["Result"] > lengths["RA1"] * 5
    assert all(math.isfinite(value) and value > 0 for value in lengths.values())


# The player alone --------------------------------------------------------------------------

def test_the_player_draws_by_its_clock():
    shown = []
    clock = Clock()
    player = Player(lambda film, moment: shown.append(moment), clock)

    class Film:
        seconds = 10.0
        steps = ()

        def at(self, moment):
            return 0, 0.0
    film = Film()
    player.play(film)
    assert shown[-1] == 0.0 and player.playing
    clock.now += 4
    player.tick()
    assert shown[-1] == pytest.approx(4)
    player.pause()
    clock.now += 3
    player.tick()
    assert shown[-1] == pytest.approx(4)
    player.resume()
    clock.now += 7
    player.tick()
    assert shown[-1] == pytest.approx(10) and player.ended
    player.finish(film)
    assert shown[-1] == 10.0


# A system call ---------------------------------------------------------------------------

PRINT = """        .global _start
_start: MOV     R0, #25
        SVC     #1
        SVC     #10
"""


def test_an_svc_plays_the_call_to_the_system(app, tmp_path):
    loaded(app, tmp_path, PRINT)
    window = connected(app)
    steps(app, 2)
    assert text_of(window, window.heading_item) == "SYSTEM CALL"
    assert window.player.playing
    window.skip()
    words = [word for step in window.film.steps for block, word in step.lights
             if block == "System"]
    assert words == ["SVC #1, print integer: R0 = 25"]
    assert "Next: PC = " in panel(window)
    assert window.tip_text("block:System").startswith("System (ARES)\n")
    assert window.tip_text("wire:Syscall").startswith("Syscall, 1 bit")


class Registers:
    """The registers a service reads, for service_text."""

    def __init__(self, *values):
        self.values = list(values) + [0] * (16 - len(values))

    def reg(self, n):
        return self.values[n]

    def single(self, n):
        return 0x3FC00000

    def double(self, n):
        return 0x3FF8000000000000


@pytest.mark.parametrize("number, values, text", [
    (1, (25,), "SVC #1, print integer: R0 = 25"),
    (1, (0xFFFFFFFF,), "SVC #1, print integer: R0 = -1"),
    (4, (0x1000,), "SVC #4, print string: R0 = 0x00001000"),
    (11, (65,), "SVC #11, print character: R0 = 'A' (65)"),
    (34, (255,), "SVC #34, print hexadecimal: R0 = 0x000000FF"),
    (36, (0xFFFFFFFF,), "SVC #36, print unsigned: R0 = 4294967295"),
    (2, (), "SVC #2, print float: S0 = 1.5"),
    (5, (42,), "SVC #5, read integer: result R0 = 42"),
    (8, (0x2000, 20), "SVC #8, read string: R0 = 0x00002000, R1 = 20"),
    (10, (), "SVC #10, exit"),
    (99, (), "SVC #99: no such service"),
])
def test_the_system_box_says_the_service_and_its_registers(number, values, text):
    assert tool.service_text(number, Registers(*values)) == text


def test_a_service_reads_its_registers_before_and_its_result_after():
    after = Registers(0x10040000)
    text = tool.service_text(9, after, before=[16] + [0] * 15)
    assert text == "SVC #9, allocate heap memory: R0 = 16; result R0 = 0x10040000"
    assert tool.service_text(5, Registers(7), done=False) == "SVC #5, read integer"


def test_the_panel_says_when_the_condition_failed(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    window = connected(app)
    steps(app, 14)                          # MOVGT, whose condition fails
    window.skip()
    assert window.model.view.trace.text.startswith("MOVGT")
    assert "skipped: its condition failed" in panel(window)
    steps(app, 1)                           # ADD runs
    window.skip()
    assert "skipped" not in panel(window)


def test_a_waiting_film_played_to_its_end_says_it_has_not_ended(app, tmp_path):
    loaded(app, tmp_path, READ)
    window = connected(app)
    steps(app, 3)                           # the read waits for a line
    system = next(step for step in window.film.steps
                  if step.lights and step.lights[0][0] == "System")
    at(window, system.start + system.duration / 2)
    assert panel(window) == ""
    to_end(window)                          # the clock plays the film to its end
    assert "It has not ended yet" in panel(window)
    assert window.canvas.itemcget(window.picture.blocks["System"], "fill") == look.WORKING_FILL


DIALOG = """        .data
ask:    .asciz  "Go on?"
        .global _start
        .text
_start: LDR     R0, =ask
        SVC     #50
        SVC     #10
"""


def test_a_service_that_asks_in_a_dialog_says_so(app, tmp_path, monkeypatch):
    import ares.gui.app as app_module
    monkeypatch.setattr(app_module.App, "show_dialog", lambda self, request: None)
    loaded(app, tmp_path, DIALOG)
    window = connected(app)
    steps(app, 2)                           # the confirm dialog waits for its answer
    assert window.model.view.kind == xray.WAITING
    assert heading(window) == tool.WAITING_HEADINGS["dialog"]
    window.skip()
    (block, word), = window.film.steps[-1].lights
    assert word.startswith("SVC #50, confirm dialog") and word.endswith("waits for an answer")
    assert "the dialog window" in window.film.steps[-1].sentence


def test_a_read_that_asks_in_the_input_dialog_says_so(app, tmp_path, monkeypatch):
    import ares.gui.app as app_module
    monkeypatch.setattr(app_module.App, "_open_line_dialog", lambda self, text="": None)
    app.settings.popup_input = True
    loaded(app, tmp_path, READ)
    window = connected(app)
    steps(app, 3)
    assert heading(window) == tool.POPUP_HEADING
    window.skip()
    assert "the input dialog" in window.film.steps[-1].sentence


FAILS = """        .global _start
_start: MOV     R0, #1
        SVC     #99
"""


def test_a_service_that_fails_stops_the_film_at_the_system(app, tmp_path):
    loaded(app, tmp_path, FAILS)
    window = connected(app)
    steps(app, 2)
    view = window.model.view
    assert view.kind == xray.FAILED and view.trace.kind == xray.SYSTEM_CALL
    window.skip()
    (block, word), = window.film.steps[-1].lights
    assert block == "System" and word == "SVC #99: no such service\nfails"
    assert "The program stops here." in window.film.steps[-1].sentence


def test_a_shared_stretch_is_thick_and_an_unused_branch_keeps_its_marks_gray(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    window = connected(app)
    canvas, drawn = window.canvas, window.picture
    steps(app, 9)                           # ADD R1, R1, #4: Result goes to WD3, the PC rejects it
    window.skip()
    thick = drawn.d(picture.width_of("Result", True))
    assert float(canvas.itemcget(drawn.items[("Result", 0)], "width")) == pytest.approx(thick)
    assert float(canvas.itemcget(drawn.items[("Result", 1)], "width")) < thick
    steps(app, 2)                           # BNE: nothing goes from PCPlus4 to WD3
    window.skip()
    slash = [item for item in canvas.find_withtag("slash:PCPlus4") if canvas.type(item) == "line"]
    assert [canvas.itemcget(item, "fill") for item in slash] == [picture.IDLE]
    lit = [item for item in canvas.find_withtag("mid:PCPlus4")
           if canvas.itemcget(item, "fill") != picture.IDLE]
    assert lit                              # the stretch to the PC multiplexer is lit
    assert all("part:PCPlus4/3" not in canvas.gettags(item) for item in lit)


SHIFTED = """        .global _start
_start: MOV     R0, #7
        MOV     R1, #40
        ADD     R2, R1, R0, LSL #2
        SVC     #10
"""


def resting(window, net, branch):
    box, text = window.picture.rests[(net, branch)]
    canvas = window.canvas
    if canvas.itemcget(text, "state") == "hidden":
        return None
    return canvas.itemcget(text, "text")


def test_the_shifters_output_and_srcb_keep_their_values(app, tmp_path):
    loaded(app, tmp_path, SHIFTED)
    window = connected(app)
    steps(app, 3)                           # ADD R2, R1, R0, LSL #2: 0x28 + 0x1C
    window.skip()
    assert resting(window, "Shifted", "alusrc") == "0x0000001C"
    assert resting(window, "SrcB", "alu") == "0x0000001C"
    assert resting(window, "SrcA", "alu") == "0x00000028"
    assert clashes(window.canvas) == []


def test_every_value_rests_beside_the_input_it_reaches():
    """Nearer to the port that takes it than to the port it leaves, and than to the input of any
    other block: the value of RD2, whose short wire to the shifter leaves no room, and the word,
    which goes to every field of the word at once, stay where they leave."""
    elsewhere = {("RD2", "shifter"), ("Instr", "split"), ("RD4", "shifter")}
    outputs = {source for source, _ in xray_film.NETS.values()}
    inputs = {port: xy for port, xy in picture.PORTS.items() if port not in outputs}
    for table in (picture.REST, picture.SIGNAL_REST):
        for net, branches in table.items():
            source, ports = xray_film.NETS[net]
            for branch, (x, y, _) in branches.items():
                if (net, branch) in elsewhere:
                    continue
                into = picture.PORTS[ports[branch]]
                out = picture.PORTS.get(source)
                if out is None:
                    continue
                assert math.dist((x, y), into) < math.dist((x, y), out), (net, branch)
                block = ports[branch].split(".")[0]
                nearest = min(math.dist((x, y), xy) for port, xy in inputs.items()
                              if port.split(".")[0] != block)
                assert math.dist((x, y), into) < nearest, (net, branch)


def test_the_colours_of_the_values_are_clearly_different():
    """Each two colours of the values are clearly apart; cond and the ALU's result, the PC and
    the data read, far apart (CIE76 distance)."""
    def lab(colour):
        r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
        f = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
        r, g, b = f(r), f(g), f(b)
        x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
        y = 0.2126 * r + 0.7152 * g + 0.0722 * b
        z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
        h = lambda v: v ** (1 / 3) if v > 0.008856 else 7.787 * v + 16 / 116  # noqa: E731
        return 116 * h(y) - 16, 500 * (h(x) - h(y)), 200 * (h(y) - h(z))
    colours = look.VALUES
    for one, two in (("cond", "alu"), ("pc", "memory")):
        assert math.dist(lab(colours[one]), lab(colours[two])) > 25, (one, two)
    distinct = sorted(set(colours.values()))
    for index, one in enumerate(distinct):
        for two in distinct[index + 1:]:
            assert math.dist(lab(one), lab(two)) > 18, (one, two)


MULTIPLE = """        .global _start
_start: LDR     SP, =stack
        LDR     R8, =table
        MOV     R4, #4
        MOV     R5, #5
        PUSH    {R4, R5, LR}
        STMIA   R8, {R4, R5}
        LDMIA   R8, {R0, R1}
        STMDB   R8!, {R0-R2}
        LDMIB   R8, {R6, R7}
        BL      leaf
        SVC     #10
leaf:   PUSH    {R4, LR}
        POP     {R4, PC}
        .data
        .space  64
table:  .word   1, 2, 3, 4, 5, 6, 7, 8
        .space  64
stack:  .word   0
"""


WRITE_BACK = """        .global _start
_start: LDR     R1, =table
        LDR     SP, =stack
        MOV     R2, #4
        LDR     R0, [R1, #4]!
        LDR     R3, [R1], #4
        LDRB    R4, [R1], #-1
        LDR     R5, [R1, R2, LSL #1]!
        STR     R0, [R1], R2
        STRB    R0, [R1, #-1]!
        PUSH    {R0}
        POP     {R7}
        SVC     #10
        .data
        .space  64
table:  .word   0x11223344, 0x55667788, 0x99AABBCC, 0xDDEEFF00, 0x01020304, 0x05060708
        .space  64
stack:  .word   0
"""


@pytest.mark.parametrize("zoom", [1.0, 1.3, 1.6])
def test_no_text_lies_over_anything_with_write_back_or_post_indexing(app, tmp_path, zoom):
    loaded(app, tmp_path, WRITE_BACK)
    window = connected(app)
    window._make_canvas(zoom)
    for count in range(1, 13):
        app.run("step")
        window.skip()
        assert clashes(window.canvas) == [], (count, text_of(window, window.view_text))


def test_a_post_indexed_load_writes_its_base_through_the_base_write_port(app, tmp_path):
    loaded(app, tmp_path, WRITE_BACK)
    window = connected(app)
    steps(app, 5)                           # LDR R3, [R1], #4
    window.skip()
    assert window.model.view.trace.text == "LDR R3, [R1], #4"
    assert wire_colour(window, "BaseWrite") == {picture.ON}
    assert wire_colour(window, "ALUResult") and "Now: 1" in window.tip_text("wire:AdrSrc")
    inside = window.open_inside("RegFile")
    words = [inside.canvas.itemcget(item, "text") for item in inside.canvas.find_all()
             if inside.canvas.type(item) == "text"]
    assert "WE5 = 1" in words and "WRITE R3, R1" in words
    assert any(word.startswith("WD5 = 0x") for word in words)


@pytest.mark.parametrize("zoom", [1.0, 1.3, 1.6])
def test_no_text_lies_over_anything_at_the_end_of_each_pass(app, tmp_path, zoom):
    """PUSH, POP, LDM and STM: the picture at the end of each pass, at the three scales."""
    loaded(app, tmp_path, MULTIPLE)
    window = connected(app)
    window._make_canvas(zoom)
    passes = 0
    for count in range(1, 15):
        app.run("step")
        film = window.film
        for sub in film.passes or (film,):
            at(window, sub.offset + sub.seconds - (window.test_clock.now - window.player.start))
            assert clashes(window.canvas) == [], (count, sub.trace.text, sub.trace.number)
            passes += 1
    assert passes > 20


def test_a_push_plays_one_pass_for_each_register_and_says_which(app, tmp_path):
    loaded(app, tmp_path, MULTIPLE)
    window = connected(app)
    steps(app, 5)                           # PUSH {R4, R5, LR}
    film = window.film
    assert len(film.passes) == 3 and window.player.playing
    assert heading(window) == "Just executed"
    seen = []
    for sub in film.passes:
        at(window, sub.offset + sub.seconds / 2 - (window.test_clock.now - window.player.start))
        seen.append(text_of(window, window.heading_item))
        assert sentence(window).startswith(f"Pass {sub.trace.number} of 3: ")
        assert window.canvas.itemcget(window.picture.pass_word, "text") == \
            f"pass {sub.trace.number} of 3"
        register = sub.trace.values["PassReg"]     # its bits, and the register they name
        assert window.tip_text("wire:PassReg").endswith(f"Now: {register:04b} (R{register})")
    assert seen == [f"STORE MULTIPLE INSTRUCTION, PASS {n} OF 3" for n in (1, 2, 3)]
    to_end(window)
    assert "Memory 0x" in panel(window) and "SP 0x" in panel(window)
    assert window.tip_text("wire:Hold").endswith("Now: 0")
    assert "Now: 1" in window.tip_text("wire:BaseWrite")


def test_the_additions_stay_gray_for_an_instruction_that_does_not_use_them(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    window = connected(app)
    steps(app, 6)                           # LDR R3, [R1]: the AdrSrc multiplexer takes ALUResult
    window.skip()
    for net in ("Hold", "PassReg", "Offset", "List", "BaseWrite"):
        assert wire_colour(window, net) == set(), net
    assert window.tip_text("wire:Hold").endswith(f"Now: 0, {tool.UNUSED}")
    assert window.tip_text("wire:BaseWrite").endswith(f"Now: 0, {tool.UNUSED}")
    decision = next(d for step in window.film.steps for d in step.decisions
                    if d.mux == "AdrSrcMux")
    assert decision.taken == 0 and decision.rejected == (1,)
    assert window.tip_text("wire:Address").endswith(tool.value_text(0x3C))


def test_the_windows_inside_follow_the_pass_shown(app, tmp_path):
    loaded(app, tmp_path, MULTIPLE)
    window = connected(app)
    steps(app, 5)                           # PUSH {R4, R5, LR}: LR, then R5, then R4
    inside = {block: window.open_inside(block) for block in ("RegFile", "Extend", "Control")}
    film = window.film
    for sub in film.passes:
        at(window, sub.offset + sub.seconds * 0.999 - (window.test_clock.now - window.player.start))
        words = [inside["RegFile"].canvas.itemcget(item, "text")
                 for item in inside["RegFile"].canvas.find_all()
                 if inside["RegFile"].canvas.type(item) == "text"]
        register = sub.trace.values["PassReg"]
        # The pass multiplexer before A4 takes PassReg, steered by the pass counter's Pass.
        assert f"PassReg = {register:04b}" in words and "Pass = 1" in words
        assert "WE5 = 1" in words
        extend = [inside["Extend"].canvas.itemcget(item, "text")
                  for item in inside["Extend"].canvas.find_all()
                  if inside["Extend"].canvas.type(item) == "text"]
        assert "011: PASS OFFSET" in extend and "ExtImm = 0x00000004" in extend
        control = " | ".join(inside["Control"].canvas.itemcget(item, "text")
                             for item in inside["Control"].canvas.find_all()
                             if inside["Control"].canvas.type(item) == "text")
        assert f"pass {sub.trace.number} of 3: PassReg R{register}" in control


CONDITIONAL = """        .global _start
_start: LDR     SP, =stack
        LDR     R1, =table
        MOV     R2, #4
        MOVS    R0, #1
        LDRGT   R3, [R1], R2, LSL #1
        STRGTB  R3, [R1, #-1]!
        LDRLEB  R3, [R1, -R2, ASR #1]!
        PUSHGT  {R0-R12, LR}
        POPGT   {R0-R12}
        LDMGTIB R1, {R4, R5}
        STMLEDA R1!, {R4, R5}
        CMPGT   R0, #0x80000000
        ADDGTS  R4, R4, R5, LSL #31
        SVC     #10
        .data
        .space  64
table:  .word   1, 2, 3, 4, 5, 6, 7, 8
        .space  64
stack:  .word   0
"""


@pytest.mark.parametrize("name", ["largest", "multiple", "shifts", "halfwords"])
def test_the_last_sentence_fits_a_tip_no_wider_than_the_datapath(app, tmp_path, name):
    """The strip's tips have one sentence a line; the film's last one names the next
    instruction, cut short so that it is no wider than the datapath at 100 % (TIP_WIDTH) in the
    tips' font."""
    source = {"largest": LARGEST, "multiple": MULTIPLE, "shifts": SHIFTS,
              "halfwords": HALFWORDS}[name]
    loaded(app, tmp_path, source)
    window = connected(app)
    font, width = tip_font(window)
    seen = 0
    for _ in range({"shifts": 23, "halfwords": 18}.get(name, 15)):
        app.run("step")
        if window.film.steps and "the next instruction is" in window.film.steps[-1].sentence:
            assert font.measure(window.film.steps[-1].sentence) <= width
            seen += 1
    assert seen > 10


def tip_font(window):
    """The font of the tips, and the widest a line of a strip's tip may be in it."""
    from tkinter import font as tkfont
    return (tkfont.nametofont("TkTooltipFont", root=window.canvas),
            tool.TIP_WIDTH * scale(window.canvas))


@pytest.mark.parametrize("count, text", [(7, "CMP R3, R0"), (6, "LDR R3, [R1]"), (5, "MOV R0, #0")])
def test_the_new_parts_keep_no_value_where_the_instruction_does_not_use_them(app, tmp_path,
                                                                              count, text):
    loaded(app, tmp_path, LARGEST)
    window = connected(app)
    steps(app, count)
    window.skip()
    assert window.model.view.trace.text == text
    nets = ["Hold", "BaseWrite", "PassReg", "Offset", "List", "Mul", "Op2", "Rs"]
    if not text.startswith("LDR"):
        nets.append("AdrSrc")
    for net in nets:
        assert wire_colour(window, net) == set(), net
        for (name, branch), (box, label) in window.picture.rests.items():
            if name == net:
                assert window.canvas.itemcget(label, "state") == "hidden", net
    if text.startswith("LDR"):
        assert resting(window, "Address", "dmem") == "0x0000003C"


HIGH = 3.0                              # Tk's scaling at 225 % on Windows (216 dots per inch)


@pytest.mark.parametrize("zoom", [1.25, MAXIMIZED_HIGH, 1.3])
@pytest.mark.parametrize("name", ["largest", "mixed", "multiple", "write_back", "multiply",
                                  "shifts", "halfwords"])
def test_no_text_lies_over_anything_at_225_percent(app, tmp_path, zoom, name):
    """At 225 %, as Windows sets Tk's scaling there, with the zoom the window chooses: the
    picture at the end of every instruction (and of every pass), and the windows inside the
    blocks for a pass, for a load with write-back, for MUL, MLA and MULS, for the shifts by a
    register, ADC, RSC, the store with a register offset, MLA, BLX and NOP, and for MOVW, MOVT
    and the halfword and signed transfers."""
    source = {"largest": LARGEST, "mixed": MIXED, "multiple": MULTIPLE,
              "write_back": WRITE_BACK, "multiply": MULTIPLY, "shifts": SHIFTS,
              "halfwords": HALFWORDS}[name]
    inside_at = {"shifts": (5, 7, 8, 11, 13, 16, 17, 19, 20),
                 "halfwords": HALFWORDS_INSIDE}.get(name, (4, 5, 6))
    before = float(app.root.tk.call("tk", "scaling"))
    app.root.tk.call("tk", "scaling", HIGH)
    try:
        loaded(app, tmp_path, source)
        window = connected(app)
        window._make_canvas(zoom)
        assert scale(window.canvas) == pytest.approx(2.25, abs=0.01)
        for count in range(1, {"shifts": 24, "halfwords": 19}.get(name, 14)):
            app.run("step")
            film = window.film
            for sub in film.passes or (film,):
                moment = sub.offset + sub.seconds * 0.999 if film.passes else film.seconds
                window.player.paused_at = moment
                window._draw_moment(film, moment)
                assert clashes(window.canvas) == [], (count, sub.trace.text)
                if count in inside_at:
                    for block in ("RegFile", "Control", "Extend", "DMem", "ALU", "Shifter"):
                        inside = window.open_inside(block)
                        window._draw_moment(film, moment)
                        assert clashes(inside.canvas) == [], (block, count, sub.trace.text)
    finally:
        app.root.tk.call("tk", "scaling", before)


def test_the_register_files_window_takes_passreg_for_a3_in_a_load_pass(app, tmp_path):
    loaded(app, tmp_path, MULTIPLE)
    window = connected(app)
    steps(app, 12)                          # POP {R4, PC} in the leaf function
    assert window.model.view.trace.text == "POP {R4, PC}"
    inside = window.open_inside("RegFile")
    film = window.film
    for sub in film.passes:
        at(window, sub.offset + sub.seconds * 0.999 - (window.test_clock.now - window.player.start))
        canvas = inside.canvas
        words = [canvas.itemcget(item, "text") for item in canvas.find_all()
                 if canvas.type(item) == "text" and canvas.itemcget(item, "state") != "hidden"]
        register = sub.trace.values["PassReg"]
        assert f"PassReg = {register:04b}" in words and "Pass = 1" in words
        assert f"A3 = {register:04b}" not in words  # A3's own input does not come in a pass
        assert any("(A3 = PassReg)" in word for word in words) or register == 15


def test_a_gray_signal_keeps_its_value_in_its_tip(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    window = connected(app)
    steps(app, 6)                           # LDR R3, [R1]: RA2 and the shifter not used
    window.skip()
    assert window.tip_text("wire:RegSrc1").endswith("Now: X, not used by this instruction")
    assert window.tip_text("wire:Shift").endswith("Now: 0, not used by this instruction")
    assert window.tip_text("wire:Mul").endswith("Now: 0, not used by this instruction")
    assert "Now: 1" in window.tip_text("wire:RegWrite")
    for net in ("RegSrc1", "Shift", "StoreSrc", "Syscall"):
        box, text = window.picture.rests[(net, next(iter(xray_film.NETS[net][1])))]
        assert window.canvas.itemcget(text, "state") == "hidden", net



# MUL and MLA ---------------------------------------------------------------------------------

def test_mla_takes_rs_and_19_16_with_mul_and_multiplies_in_the_alu(app, tmp_path):
    """Mul, red, makes the RA1 multiplexer take Rs and the A3 multiplexer Instr 19:16; Op2
    brings 1001 to the control unit; Ra is read on A4 and RD4 goes into the ALU, whose line
    shows the whole multiplication."""
    loaded(app, tmp_path, MULTIPLY)
    window = connected(app)
    steps(app, 5)                           # MLA R3, R4, R5, R6
    window.skip()
    assert text_of(window, window.heading_item) == "MULTIPLY INSTRUCTION"
    assert wire_colour(window, "Mul") == {picture.ON}
    assert wire_colour(window, "Op2") == {look.VALUES["op"]}
    assert wire_colour(window, "Rs") == {look.VALUES["rn"]}
    assert resting(window, "Mul", "ra1") == resting(window, "Mul", "a3") == "1"
    assert resting(window, "Rs", "ra1") == "0101" and resting(window, "A3", "regfile") == "0011"
    assert resting(window, "RD4", "alu") == "0x00000015"
    decisions = {d.mux: d for step in window.film.steps for d in step.decisions}
    assert decisions["RA1Mux"].taken == decisions["A3Mux"].taken == 2
    assert window.canvas.itemcget(window.picture.words["ALU"], "text") == "MLA"
    assert any("the multiplier: 0x00000007 x 0x00000003 + 0x00000015 = 0x0000002A" in step.sentence
               for step in window.film.steps)
    assert "Now: 1" in window.tip_text("wire:Mul") and "Now: 1001" in window.tip_text("wire:Op2")
    canvas, k = window.canvas, window.picture.k
    store = window.picture.items[("RD4", 0)]            # lit only as far as the ALU's way leaves
    assert canvas.itemcget(store, "state") == "normal"
    assert round(canvas.coords(store)[-2] / k) == 670
    assert canvas.itemcget(window.picture.items[("RD4", 1)], "state") == "normal"
    assert "R3 0x00000000 -> 0x0000002A" in panel(window)
    assert clashes(canvas) == []


def test_a_shared_stretch_carries_a_value_that_only_a_later_branch_takes(app, tmp_path):
    """LDR R3, [R1]: Rd goes to A3's multiplexer only, along the stretch it shares with RA2's
    way, lit (and thick) as far as A3's way leaves it; a store with post-indexing: ALUResult goes
    to the base write port along the Result multiplexer's way, lit as far as it leaves it."""
    loaded(app, tmp_path, LARGEST)
    window = connected(app)
    steps(app, 6)
    window.skip()
    canvas, drawn = window.canvas, window.picture
    k = drawn.k
    item, trunk = drawn.items[("Rd", 1)], drawn.trunks[("Rd", 1)]
    assert canvas.itemcget(item, "state") == canvas.itemcget(trunk, "state") == "normal"
    x, y = picture.PATHS["Rd"][2][1][0]   # where A3's way leaves RA2's (and the bus's) stretch
    assert [round(c / k) for c in canvas.coords(trunk)[-2:]] == [x, y + picture.ORIGIN[1]]
    assert float(canvas.itemcget(trunk, "width")) == pytest.approx(
        drawn.d(picture.width_of("Rd", True)))


def test_alu_result_goes_to_the_base_port_along_the_result_multiplexers_way(app, tmp_path):
    loaded(app, tmp_path, WRITE_BACK)
    window = connected(app)
    steps(app, 8)                           # STR R0, [R1], R2
    window.skip()
    canvas, drawn = window.canvas, window.picture
    k = drawn.k
    assert window.model.view.trace.text == "STR R0, [R1], R2"
    for index, end in ((0, (820, 228)), (1, (820, 340))):
        item = drawn.items[("ALUResult", index)]
        assert canvas.itemcget(item, "state") == "normal"
        assert [round(c / k) for c in canvas.coords(item)[-2:]] == \
            [end[0], end[1] + picture.ORIGIN[1]]


def test_the_help_lists_the_multiplier_and_mul():
    words = " ".join(tool.HELP.split())
    for said in ("MUL and MLA have a multiplier inside the ALU", "Op2, bits 7:4", "Its signal Mul",
                 "MLA reads Ra (bits 15:12) on A4", "long multiplies, MLS and UMAAL"):
        assert said in words, said



# Shifts by a register; ADC, SBC, RSC and TEQ; BLX and NOP --------------------------------------

def test_a_shift_by_a_register_reads_rs_on_a4_and_shifts_by_rd4(app, tmp_path):
    """ShiftReg, red, makes the A4 multiplexer take Rs (Instr 11:8); RD4 goes into the shifter,
    whose word names the shift, and the line under the strip says the amount."""
    loaded(app, tmp_path, SHIFTS)
    window = connected(app)
    steps(app, 5)                           # ADD R2, R1, R0, LSL R3
    window.skip()
    assert wire_colour(window, "ShiftReg") == {picture.ON}
    assert wire_colour(window, "Rs") == {look.VALUES["rn"]}
    assert wire_colour(window, "Op2") == {look.VALUES["op"]}
    assert resting(window, "ShiftReg", "a4") == "1" and resting(window, "A4", "regfile") == "0011"
    assert resting(window, "RD4", "shifter") == "0x00000002"
    assert window.canvas.itemcget(window.picture.items[("RD4", 2)], "state") == "normal"
    decisions = {d.mux: d for step in window.film.steps for d in step.decisions}
    assert decisions["A4Mux"].taken == 1 and decisions["A4Mux"].rejected == (0,)
    assert window.canvas.itemcget(window.picture.words["Shifter"], "text") == "LSL R3"
    assert any("by R3[7:0] = 2 (LSL R3)" in step.sentence for step in window.film.steps)
    assert "Now: 1" in window.tip_text("wire:ShiftReg")
    assert window.tip_text("block:A4Mux").startswith("A4 multiplexer\n")
    assert clashes(window.canvas) == []


def test_a_store_with_a_register_offset_takes_15_12_with_shiftreg_gray(app, tmp_path):
    loaded(app, tmp_path, SHIFTS)
    window = connected(app)
    steps(app, 16)                          # STR R2, [R10, R3]
    window.skip()
    assert window.model.view.trace.text == "STR R2, [R10, R3]"
    assert wire_colour(window, "ShiftReg") == set()
    assert window.tip_text("wire:ShiftReg").endswith("Now: 0: the A4 multiplexer takes Instr 15:12")
    decisions = {d.mux: d for step in window.film.steps for d in step.decisions}
    assert decisions["A4Mux"].taken == 0 and decisions["A4Mux"].rejected == ()
    assert resting(window, "A4", "regfile") == "0010"


def test_adc_takes_the_c_flag_on_carryin(app, tmp_path):
    loaded(app, tmp_path, SHIFTS)
    window = connected(app)
    steps(app, 11)                          # ADC R7, R0, R1: C is 0 after ADDS 40 + 40
    window.skip()
    assert window.model.view.trace.text == "ADC R7, R0, R1"
    assert wire_colour(window, "CarryIn") == {look.VALUES["flags"]}
    assert resting(window, "CarryIn", "alu") == "0"
    assert window.canvas.itemcget(window.picture.words["ALU"], "text") == "ADC"
    assert window.canvas.itemcget(window.picture.signal_names["CarryIn"], "fill") == picture.INK
    steps(app, 1)                           # SBCS R8, R1, R0
    window.skip()
    assert wire_colour(window, "CarryIn") == {look.VALUES["flags"]}
    steps(app, 2)                           # RSC, then TEQ R0, #7: no carry
    window.skip()
    assert wire_colour(window, "CarryIn") == set()
    assert text_of(window, window.heading_item) == "DATA PROCESSING INSTRUCTION"


def test_blx_and_nop_play_their_films(app, tmp_path):
    loaded(app, tmp_path, SHIFTS)
    window = connected(app)
    steps(app, 19)                          # BLX R12
    window.skip()
    assert text_of(window, window.heading_item) == "BRANCH INSTRUCTION"
    assert resting(window, "Link", "a3") == "1" and resting(window, "A3", "regfile") == "1110"
    assert "LR 0x00000000 -> 0x" in panel(window)
    steps(app, 1)                           # NOP
    window.skip()
    assert text_of(window, window.heading_item) == "NO OPERATION"
    assert wire_colour(window, "PCSrc") == {picture.OFF}
    for net in ("RA1", "RA2", "A4", "SrcB", "ALUResult", "RegWrite", "ALUControl"):
        assert wire_colour(window, net) == set(), net
    assert any(step.sentence.startswith("NOP: nothing is written") for step in window.film.steps)
    assert "no register or memory changed" in panel(window)


def test_the_help_lists_the_shift_by_a_register_carryin_teq_blx_and_nop():
    words = " ".join(tool.HELP.split())
    for said in ("the signal ShiftReg, 1 only for it", "RD4 goes into the shifter",
                 "the wire CarryIn brings it from the flags register", "TEQ has its row",
                 "BLX Rm is the row of BX with Link 1", "NOP has a row of its own",
                 "of a shift by a register, of MOVW or MOVT"):
        assert said in words, said
    assert "ADC, SBC, RSC and TEQ; shifts by a register" not in words



# MOVW and MOVT; LDRH, STRH, LDRSB and LDRSH -------------------------------------------------------

def test_movt_reads_rd_on_a4_and_joins_the_halves_in_the_alu(app, tmp_path):
    """MOVT R3: Rd goes to A3 and, through the A4 multiplexer, to A4; RD4 goes into the ALU, whose
    word is MOVT; Extend joins imm4 and imm12 (ImmSrc 100); RA1 and RA2 read nothing."""
    loaded(app, tmp_path, HALFWORDS)
    window = connected(app)
    steps(app, 4)                           # MOVT R3, #0xFFFE
    window.skip()
    assert window.model.view.trace.text == "MOVT R3, #0xFFFE"
    assert text_of(window, window.heading_item) == "DATA PROCESSING INSTRUCTION"
    assert resting(window, "A4", "regfile") == "0011"
    assert resting(window, "RD4", "alu") == "0x00008001"
    assert resting(window, "ImmSrc", "extend") == "100" and resting(window, "Imm", "extend") == \
        "0xFFFE"
    assert window.canvas.itemcget(window.picture.words["ALU"], "text") == "MOVT"
    assert window.canvas.itemcget(window.picture.words["Extend"], "text") == "JOIN imm4:imm12"
    for net in ("RA1", "RA2", "Rn", "Size", "Signed", "ShiftReg"):
        assert wire_colour(window, net) == set(), net
    assert any("MOVT: R3 = 0xFFFE : 0x8001" in step.sentence for step in window.film.steps)
    assert "R3 0x00008001 -> 0xFFFE8001" in panel(window)
    assert "Now: 1110" in window.tip_text("wire:ALUControl")
    assert clashes(window.canvas) == []


def test_a_signed_byte_load_says_its_size_and_sign_in_the_data_memory(app, tmp_path):
    """LDRSB R5, [R1, #-1]!: Size 10 and Signed 1 come into the data memory, whose word says READ
    BYTE and SIGNED; the base is written back through the base write port."""
    loaded(app, tmp_path, HALFWORDS)
    window = connected(app)
    steps(app, 8)
    window.skip()
    trace = window.model.view.trace
    assert trace.text == "LDRSB R5, [R1, #-1]!" and text_of(window, window.heading_item) == \
        "LOAD INSTRUCTION"
    assert resting(window, "Size", "dmem") == "10" and resting(window, "Signed", "dmem") == "1"
    assert wire_colour(window, "Signed") == {picture.ON}
    assert window.canvas.itemcget(window.picture.words["DMem"], "text") == "READ BYTE\nSIGNED"
    assert resting(window, "ImmSrc", "extend") == "101"
    assert trace.values["ReadData"] == 0xFFFFFF80 and wire_colour(window, "BaseWrite") == \
        {picture.ON}
    assert "R5 0x00000000 -> 0xFFFFFF80" in panel(window)
    assert window.tip_text("wire:Size").startswith("Size, 2 bits\n") and \
        window.tip_text("wire:Size").endswith("Now: 10")
    assert "Now: 1" in window.tip_text("wire:Signed")
    assert clashes(window.canvas) == []
    steps(app, 7)                           # STRH R4, [R1, -R2]!: a store, Signed gray
    window.skip()
    assert window.model.view.trace.text == "STRH R4, [R1, -R2]!"
    assert wire_colour(window, "Signed") == set() and resting(window, "Size", "dmem") == "01"
    assert window.canvas.itemcget(window.picture.words["DMem"], "text") == "WRITE HALF"
    assert window.tip_text("wire:Signed").endswith(f"Now: 0, {tool.UNUSED}")


def test_the_help_lists_movw_movt_and_the_halfword_transfers():
    words = " ".join(tool.HELP.split())
    for said in ("ImmSrc has three bits", "100 joins imm4 (bits 19:16) and imm12",
                 "101 joins imm4H (bits 11:8) and imm4L", "MOVW writes its immediate with zeros",
                 "MOVT reads its Rd on A4 and keeps its low half", "ALUControl 1110",
                 "LDRH, STRH, LDRSB and LDRSH have rows of their own in the Main Decoder",
                 "The signal Size tells the data memory to move a word (00), a halfword (01) "
                 "or a byte (10)", "The signal Signed makes the load extender",
                 "doubleword and exclusive accesses", "LDRHT, STRHT, LDRSBT and LDRSHT"):
        assert said in words, said
    assert "halfword, doubleword" not in words and "MOVW, MOVT, MRS" not in words


# The instruction as the student wrote it ---------------------------------------------------

WRITTEN = """        .global _start
_start: MOV     R0, #20         @ twenty
        ADD     R3,R0,R0
        MOV     R1, #20
loop:   SUBS    R0, R0, #10
        BNE     loop            @ twice
        ADRL    R2, far
        SVC     #10
far:    .word   5
"""


def line_of(window):
    return text_of(window, window.instruction_item)


def test_the_instruction_shows_as_written_with_its_basic_form_when_they_differ(app, tmp_path):
    loaded(app, tmp_path, WRITTEN)
    window = connected(app)
    assert panel(window).endswith("Next: PC = 0x00000000,\n      MOV R0, #20")    # nothing ran
    app.run("step")
    assert line_of(window) == "MOV R0, #20    (MOV R0, #0x14)"
    assert text_of(window, window.view_text) == "0x00000000  MOV R0, #20"
    to_end(window)
    assert panel(window).endswith("Next: PC = 0x00000004,\n      ADD R3,R0,R0")
    assert sentence(window).endswith("the next instruction is ADD R3,R0,R0.")
    app.run("step")                                 # the same but for spaces: as written
    assert line_of(window) == "ADD R3,R0,R0"
    assert text_of(window, window.view_text) == "0x00000004  ADD R3,R0,R0"
    steps(app, 2)
    assert line_of(window) == "SUBS R0, R0, #10    (SUBS R0, R0, #0xA)"
    app.run("step")
    assert line_of(window) == "BNE loop    (BNE #0xC)"
    steps(app, 3)                                   # ADRL's first word: the line's text
    basic = window.model.view.trace.text
    assert line_of(window) == f"ADRL R2, far    ({basic})"
    app.run("step")                                 # its second word: no line of its own
    basic = window.model.view.trace.text
    assert line_of(window) == basic and text_of(window, window.view_text).endswith(basic)
    assert window.film.steps[-1].sentence.endswith("the next instruction is SVC #10.")


def test_assembled_while_connected_the_first_instruction_is_named_as_written(app, tmp_path):
    window = connected(app)
    loaded(app, tmp_path, WRITTEN)
    assert heading(window) == "Nothing has run yet"
    assert panel(window).endswith("Next: PC = 0x00000000,\n      MOV R0, #20")


def test_the_word_stands_in_the_table_under_the_instruction_line(app, tmp_path):
    loaded(app, tmp_path, WRITTEN)
    window = connected(app)
    app.run("step")
    to_end(window)
    canvas = window.canvas
    hex_digits = "".join(canvas.itemcget(digit, "text") for _, digit in window.hex_cells)
    assert hex_digits == f"{window.model.view.trace.word:08X}" == "E3A00014"
    line = canvas.bbox(window.instruction_item)
    assert line[0] == pytest.approx(tool.LINE[0] * window.k, abs=2)
    assert line[3] <= min(canvas.bbox(box)[1] for box, _ in window.hex_cells + [
        (cell.boxes[0], None) for cell in window.cells]) + 1


LONG = "a_label_" + "with_a_name_long_enough_to_fill_the_whole_line_" * 3


@pytest.mark.parametrize("zoom", [1.0, 1.3, 1.6])
def test_a_long_line_as_written_fits_its_place(app, tmp_path, zoom):
    loaded(app, tmp_path, f"""        .data
{LONG}: .word   5
        .global _start
        .text
_start: LDR     R0, ={LONG}
        LDR     R1, ={LONG}
        SVC     #10
""")
    window = connected(app)
    window._make_canvas(zoom)
    app.run("step")
    window.skip()
    canvas = window.canvas
    width = float(canvas.cget("width"))
    assert clashes(canvas) == []
    line = canvas.bbox(window.instruction_item)
    assert line_of(window).endswith("...") and line[2] <= (tool.RIGHT - 6) * window.k
    for item in (window.view_text, window.panel, window.view_heading):
        assert canvas.bbox(item)[2] <= width, text_of(window, item)
    assert text_of(window, window.view_text).startswith("0x00000000  LDR R0, =a_label_")
    assert "      LDR R1, =a_label_" in panel(window)
    font, most = tip_font(window)
    assert font.measure(window.film.steps[-1].sentence) <= most
    assert "the next instruction is LDR R1, =a_label_" in window.film.steps[-1].sentence
    assert window.film.steps[-1].sentence.endswith("...")


def test_the_help_says_where_the_strip_and_the_table_stand_and_the_buttons_keys():
    words = " ".join(tool.HELP.split())
    for said in ("Under the picture, at the left, the strip marks the part that plays",
                 "its tip says what its steps have done so far, one sentence for each step",
                 "a part that has not been reached has no tip",
                 "under it stands \"To see inside a block, click it.\"",
                 "a table breaks its word down, bit 31 at the left", "Row Field names the fields",
                 "each cell as wide as its bits", "row Binary has their bits",
                 "row Hex the word's eight hexadecimal digits, each under its four bits: the "
                 "number on the wire Instr", "bits that are no field of the instruction stay "
                 "gray, without a name", "its field's name, its bits, its value and where it goes",
                 "picture buttons stand beside Assemble, Step and Backstep",
                 "a tip gives each one's name and key", "Pause (Space)", "One step forward (O)",
                 "One step back (B)", "at once (E)", "Step (F7) runs it and plays its whole film",
                 "plays only the first step of its film, then waits"):
        assert said in words, said
    assert "After it comes its word in hexadecimal" not in words
    assert "line under the strip" not in words and "(R)" not in words


def test_the_help_says_how_backstep_and_the_panel_work_and_names_the_pipeline():
    words = " ".join(tool.HELP.split())
    for said in ("Backstep plays no film", "the instruction that is now the last one run",
                 "the picture is empty", "also one stored over the same value",
                 "The instruction that runs next stands in the panel always", "as you wrote it",
                 "its Basic form", "Pipeline Simulator", "one clock cycle",
                 "cut into five stages", "several instructions inside at once",
                 "the program's results never differ"):
        assert said in words, said
    assert "Replay" not in words
    assert "Undone by Backstep" not in words and "Backstep shows the instruction it undid" \
        not in words


def test_a_register_number_travels_as_its_bits_and_its_tip_names_the_register(app, tmp_path):
    """The number on A3 is 1101, as the table's Binary row shows it; the tip says which register
    that is, and the register file's word names it."""
    loaded(app, tmp_path, """        .global _start
_start: LDR     SP, =0x4000
        SVC     #10
""")
    window = connected(app)
    app.run("step")
    to_end(window)
    assert resting(window, "A3", "regfile") == "1101"
    assert "Now: 1101 (R13)" in window.tip_text("wire:A3")
    assert "Now: 1101 (R13)" in window.tip_text("wire:Rd")
    assert window._block_word("RegFile") == "WRITE R13"


def test_the_two_status_headings_are_names(app, tmp_path):
    assert tool.RUNS_NEXT == "Runs next" and tool.NOTHING_LEFT == "Nothing to show"
    assert "Nothing to show means that Backstep has" in tool.HELP


def test_the_next_instruction_stays_in_the_panel_during_the_film(app, tmp_path):
    """While the film plays, the panel already names the instruction that runs next, where it
    stands at the end; what the instruction did comes at the end."""
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    app.run("step")
    at(window, window.film.seconds / 2)
    text = window.panel_text()
    assert text.startswith("Next: PC = 0x00000004,") and "What it did" not in text
    middle = window.canvas.itemcget(window.panels[1], "text").splitlines()
    to_end(window)
    end = window.canvas.itemcget(window.panels[1], "text").splitlines()
    assert "What it did:" in window.panel_text()
    assert middle[-2:] == end[-2:] and middle[-2].startswith("Next: PC = ")

