# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Bitmap Display's window: its settings, its picture, and how it follows the program."""

import time
import tkinter

import pytest
from conftest import native, press_key
from test_gui_look import all_buttons, framed, move_focus
from test_gui_run import go_to_end, loaded
from test_responsiveness import pictures

from ares.gui.tools import bitmap
from ares.gui.tools.bitmap import DATA, HEAP, BitmapWindow, data_start
from ares.machine import DDR_END
from ares.runner import State
from ares.gui.tools.frame import paragraphs

RED, GREEN, BLUE, YELLOW = 0xFF0000, 0x00FF00, 0x0000FF, 0xFFFF00
NO_DATA, NO_HEAP = ".data: no program assembled", "heap: no program assembled"
PICTURE = """\
        .data
screen: .word   0x00FF0000, 0x0000FF00      @ red, green: the first two units
        .space  62 * 4
        .global _start
        .text
_start: LDR     R1, =screen
        LDR     R0, =0x000000FF             @ blue
        STR     R0, [R1, #8]                @ the third unit
        STR     R0, [R1, #4 * 8]            @ the first unit of the second row
        MOV     R0, #0
        STR     R0, [R1]                    @ the first unit black again
        SVC     #10
"""
HEAP_PICTURE = """\
        .data
color:  .word   0x00FFFF00                  @ yellow
        .global _start
        .text
_start: MOV     R0, #256                    @ bytes for 64 units
        SVC     #9                          @ R0 = their address, the start of the heap
        LDR     R1, =color
        LDR     R1, [R1]
        STR     R1, [R0, #4]                @ the second unit
        SVC     #10
"""
# Writes every unit of a 512 x 512 display of 1-pixel units, each word 0x010101 more than
# the word before it.
FILL = """\
        .data
screen: .space  512 * 512 * 4
        .global _start
        .text
_start: LDR     R1, =screen
        LDR     R2, =512 * 512
        LDR     R3, =0x00010101
        MOV     R0, #0
fill:   STR     R0, [R1], #4
        ADD     R0, R0, R3
        SUBS    R2, R2, #1
        BNE     fill
        SVC     #10
"""
# Counts to 7,500,000 in the first word of .data (30,000,000 instructions).
COUNT = """\
        .data
screen: .word   0
        .global _start
        .text
_start: LDR     R1, =screen
        LDR     R2, =7500000
        MOV     R0, #0
count:  ADD     R0, R0, #1
        STR     R0, [R1]
        SUBS    R2, R2, #1
        BNE     count
        SVC     #10
"""


def fill_color(unit):
    """The colour FILL gives the unit-th word."""
    return unit * 0x010101 & 0xFFFFFF


def bitmap_window(app):
    """Open the Bitmap Display (or bring it to the front); returns its window."""
    app.run("tool_bitmap")
    window = app.tool_windows["tool_bitmap"]
    native(window.window)               # generated events reach widgets with a native window
    return window


def choose(box, value):
    """Choose value in a drop-down list, as a click in its list does."""
    box.set(value)
    box.event_generate("<<ComboboxSelected>>")


def small(app, connect=True):
    """The Bitmap Display set to 8 x 8 units of 8 x 8 pixels (64 x 64 pixels)."""
    window = bitmap_window(app)
    for name, value in (("unit_width", 8), ("unit_height", 8), ("width", 64), ("height", 64)):
        choose(window.size_boxes[name], value)
    if connect:
        window.connect_button.invoke()
    return window


def unit_color(window, column, row):
    """The colour 0xRRGGBB of the picture in the middle of a unit."""
    model, factor = window.model, window.factor
    across, down = model.unit_width * factor, model.unit_height * factor
    red, green, blue = window.image.get(column * across + across // 2, row * down + down // 2)
    return red << 16 | green << 8 | blue


def top_row(window, count=3):
    return [unit_color(window, column, 0) for column in range(count)]


def type_base(window, text, key="<Key-Return>"):
    box = window.base_box
    box.delete(0, "end")
    box.insert(0, text)
    ran = press_key(box, key)
    box.update_idletasks()              # the focus's way ends: the field decides
    return ran


def bells(window):
    rings = []
    window.window.bell = lambda: rings.append(1)
    return rings


# The window ---------------------------------------------------------------------

def test_the_bitmap_display_opens_from_the_menu(app, hidden_windows):
    menu, index = app._menu_items["tool_bitmap"]
    assert menu.entrycget(index, "state") == "normal" and app.is_enabled("tool_bitmap")
    menu.invoke(index)
    window = app.tool_windows["tool_bitmap"]
    assert isinstance(window, BitmapWindow) and hidden_windows.shows(window.window)
    assert window.window.title() == "Bitmap Display"
    assert list(all_buttons(window.window)) == ["Connect to ARM", "Reset", "Close"]
    assert window.tips[window.reset_button].text == bitmap.RESET_TIP
    assert hidden_windows.focus is window.connect_button
    boxes = window.size_boxes
    assert [boxes[name].get() for name in ("unit_width", "unit_height", "width", "height")] == [
        "1", "1", "512", "256"]
    assert boxes["unit_width"].cget("values") == ("1", "2", "4", "8", "16", "32")
    assert boxes["height"].cget("values") == ("64", "128", "256", "512", "1024")
    assert all(str(box.cget("state")) == "readonly" for box in boxes.values())
    assert window.base_box.cget("values") == (NO_DATA, NO_HEAP)        # no program yet
    assert window.base_box.get() == NO_DATA and str(window.base_box.cget("state")) == "normal"
    factor = window.factor
    assert (window.image.width(), window.image.height()) == (512 * factor, 256 * factor)
    assert (window.canvas.winfo_reqwidth(), window.canvas.winfo_reqheight()) == (
        512 * factor, 256 * factor)
    assert unit_color(window, 0, 0) == unit_color(window, 511, 255) == 0      # black


def test_the_picture_is_made_once_when_the_window_opens(app, tmp_path):
    made = pictures(app.root)
    window = small(app, connect=False)
    picture = pictures(app.root) - made
    assert picture == {window.image.name}
    loaded(app, tmp_path, PICTURE)
    window.connect_button.invoke()
    app.run("step")
    go_to_end(app)
    app.run("backstep")
    app.run("reset")
    choose(window.size_boxes["width"], 1024)
    choose(window.size_boxes["unit_width"], 1)
    window.reset_button.invoke()
    assert pictures(app.root) == made | picture
    window.close()
    assert pictures(app.root) == made                   # it goes with the window
    assert window.window is None and not window.model.connected
    again = bitmap_window(app)                          # a new window, with the defaults
    assert again is not window and not again.model.connected
    assert (again.model.width, again.model.unit_width, again.model.base) == (512, 1, DATA)


def test_connected_before_a_program_is_loaded(app, tmp_path):
    window = small(app)
    assert window.model.connected and window.model.machine is None
    loaded(app, tmp_path, PICTURE)
    assert window.model.machine is app.machine and top_row(window) == [RED, GREEN, 0]
    assert window.base_box.get() == f"0x{data_start(app.program):08x} (.data)"


def test_the_picture_shows_the_words_memory_holds(app, tmp_path):
    loaded(app, tmp_path, PICTURE)
    window = small(app)
    factor = window.factor
    assert window.image.width() == window.image.height() == 64 * factor
    assert top_row(window) == [RED, GREEN, 0]               # the program's first values
    for _ in range(3):
        app.run("step")
    assert top_row(window) == [RED, GREEN, BLUE]
    for _ in range(3):
        app.run("step")
    assert top_row(window) == [0, GREEN, BLUE] and unit_color(window, 0, 1) == BLUE
    app.run("backstep")                                     # memory gets red back
    assert top_row(window) == [RED, GREEN, BLUE]
    go_to_end(app)
    app.run("reset")                                        # F12: the first values again
    assert top_row(window) == [RED, GREEN, 0] and unit_color(window, 0, 1) == 0
    # Each word is a block of 8 x 8 pixels (times the screen's whole pixels per pixel).
    block = 8 * factor
    corners = [(0, 0), (block - 1, 0), (0, block - 1), (block - 1, block - 1)]
    assert {window.image.get(x, y) for x, y in corners} == {(255, 0, 0)}
    assert window.image.get(block, 0) == (0, 255, 0)


def test_a_refresh_draws_only_the_rows_that_changed(app, tmp_path):
    loaded(app, tmp_path, PICTURE)
    window = small(app)
    drawn = []
    draw = window._draw
    window._draw = lambda first, end: drawn.append((first, end)) or draw(first, end)
    app.run("step")
    app.run("step")
    assert drawn == []                                      # the display did not change
    app.run("step")
    assert drawn == [(0, 1)]
    app.run("step")
    assert drawn == [(0, 1), (1, 2)]
    app._register_edited("R0", 5)                           # registers: nothing to draw
    assert len(drawn) == 2


def test_a_new_size_resizes_the_picture(app, tmp_path):
    loaded(app, tmp_path, PICTURE)
    window = small(app)
    factor = window.factor
    choose(window.size_boxes["width"], 128)                 # 16 units across: words flow on
    assert window.model.columns == 16
    assert (window.image.width(), window.image.height()) == (128 * factor, 64 * factor)
    assert window.canvas.winfo_reqwidth() == 128 * factor
    assert [unit_color(window, column, 0) for column in (0, 1, 2, 8)] == [RED, GREEN, 0, 0]
    app.run("step")
    app.run("step")
    app.run("step")
    app.run("step")
    assert unit_color(window, 8, 0) == BLUE                 # the ninth word
    choose(window.size_boxes["unit_height"], 32)            # 16 x 2 units of 8 x 32 pixels
    assert window.model.rows == 2 and window.image.height() == 64 * factor
    assert unit_color(window, 2, 0) == BLUE


def test_disconnected_the_picture_stays_and_a_new_setting_makes_it_black(app, tmp_path):
    loaded(app, tmp_path, PICTURE)
    window = small(app)
    window.connect_button.invoke()                          # Disconnect from ARM
    go_to_end(app)
    assert top_row(window) == [RED, GREEN, 0]               # as it was when disconnected
    choose(window.size_boxes["unit_width"], 16)             # 4 units across
    assert window.model.columns == 4 and top_row(window, 4) == [0] * 4
    window.connect_button.invoke()
    assert top_row(window, 4) == [0, GREEN, BLUE, 0]        # memory as the run left it


def test_the_reset_button_draws_the_display_again(app, tmp_path):
    loaded(app, tmp_path, PICTURE)
    window = small(app)
    window.image.blank()                                    # as if the picture were lost
    window.reset_button.invoke()
    assert top_row(window) == [RED, GREEN, 0] and window.model.connected
    window.connect_button.invoke()
    window.reset_button.invoke()                            # not connected: black
    assert top_row(window) == [0, 0, 0]


def test_assemble_and_closing_the_programs_file(app, tmp_path):
    loaded(app, tmp_path, PICTURE)
    window = small(app)
    data = data_start(app.program)
    assert window.base_box.get() == f"0x{data:08x} (.data)"
    loaded(app, tmp_path, HEAP_PICTURE, "other.s")          # still connected: the new program
    assert window.model.connected and window.model.machine is app.machine
    assert top_row(window) == [YELLOW, 0, 0]
    app.run("close")                                        # unloaded: the picture stays
    assert app.machine is None and window.model.connected
    assert top_row(window) == [YELLOW, 0, 0]
    assert window.base_box.cget("values") == (NO_DATA, NO_HEAP)
    assert window.base_box.get() == NO_DATA
    assert window.connect_button.cget("text") == "Disconnect from ARM"


def test_the_base_address(app, tmp_path):
    loaded(app, tmp_path, HEAP_PICTURE)
    window = small(app)
    box, model = window.base_box, window.model
    data, heap = data_start(app.program), app.machine.heap_start
    labels = (f"0x{data:08x} (.data)", f"0x{heap:08x} (heap)")
    assert box.cget("values") == labels and box.get() == labels[0]
    assert top_row(window) == [YELLOW, 0, 0]
    choose(box, labels[1])
    assert model.base == HEAP and box.get() == labels[1] and top_row(window) == [0, 0, 0]
    go_to_end(app)
    assert top_row(window) == [0, YELLOW, 0]                # SVC #9's memory
    rings = bells(window)
    assert type_base(window, "0x00000000") == [str(box)]    # Return goes no further
    assert model.base == 0 and box.get() == "0x00000000" and rings == []
    assert model.connected                                  # Return did not press Connect
    for wrong in ("0x00000002", "abc", f"0x{DDR_END:08x}", ""):
        type_base(window, wrong)
        assert model.base == 0 and box.get() == "0x00000000"
    assert rings == [1] * 4
    type_base(window, str(data), "<Key-KP_Enter>")          # decimal
    assert model.base == data and box.get() == f"0x{data:08x}" and top_row(window, 1) == [YELLOW]
    type_base(window, "heap")                               # a place by its name
    assert model.base == HEAP and box.get() == labels[1]
    type_base(window, labels[0])
    assert model.base == DATA


def test_leaving_the_base_field_applies_the_typed_address(app, monkeypatch):
    window = small(app, connect=False)
    box, model = window.base_box, window.model
    rings = bells(window)
    focus = []
    monkeypatch.setattr(window, "_focus_path", lambda: focus[-1])
    for path in ("", f"{box}.popdown.f.l"):     # another program in front; the field's list
        focus.append(path)
        type_base(window, "0x00100000", "<FocusOut>")
        assert model.base == DATA and box.get() == "0x00100000"     # it waits
    focus.append(str(window.connect_button))   # a click elsewhere in the window
    type_base(window, "0x00100000", "<FocusOut>")
    assert model.base == 0x00100000 and box.get() == "0x00100000" and rings == []
    type_base(window, "0x00100001", "<FocusOut>")
    assert model.base == 0x00100000 and box.get() == "0x00100000" and rings == [1]


def test_a_display_that_would_reach_past_ddr3_is_refused(app):
    window = small(app, connect=False)
    rings = bells(window)
    type_base(window, f"0x{DDR_END - 64 * 4:08x}")          # 64 words just fit
    assert window.model.base == DDR_END - 256 and rings == []
    choose(window.size_boxes["unit_width"], 4)              # 128 words would not
    assert rings == [1] and window.size_boxes["unit_width"].get() == "8"
    assert window.model.unit_width == 8 and window.model.columns == 8
    choose(window.size_boxes["unit_width"], 16)             # fewer words do
    assert window.model.columns == 4 and rings == [1]


def test_a_large_display_fits_the_screen(app, monkeypatch):
    monkeypatch.setattr(bitmap, "scale", lambda widget: 2.25)
    monkeypatch.setattr(tkinter.Misc, "winfo_screenwidth", lambda self: 3840)
    monkeypatch.setattr(tkinter.Misc, "winfo_screenheight", lambda self: 2160)
    window = bitmap_window(app)
    assert window.factor == 2 and window.image.width() == 1024     # 512 x 256 at 225 %
    choose(window.size_boxes["height"], 1024)               # 2048 high would not fit: 1:1
    assert window.factor == 1 and (window.image.width(), window.image.height()) == (512, 1024)
    assert not window.vbar.winfo_manager() and not window.hbar.winfo_manager()
    assert window.canvas.winfo_reqheight() == 1024
    monkeypatch.setattr(bitmap, "scale", lambda widget: 1.0)
    monkeypatch.setattr(tkinter.Misc, "winfo_screenwidth", lambda self: 1920)
    monkeypatch.setattr(tkinter.Misc, "winfo_screenheight", lambda self: 1080)
    choose(window.size_boxes["width"], 1024)                # does not fit: a scroll bar
    assert window.factor == 1 and window.vbar.winfo_manager() == "grid"
    assert not window.hbar.winfo_manager()
    assert window.canvas.winfo_reqheight() == 756          # 70 % of 1080
    assert window.canvas.winfo_reqwidth() == 1024
    assert window.canvas.cget("scrollregion") == "0 0 1024 1024"
    choose(window.size_boxes["height"], 256)                # fits again: no bar
    assert not window.vbar.winfo_manager() and window.canvas.winfo_reqheight() == 256


def test_the_display_takes_at_most_60_percent_of_the_screens_width(app, monkeypatch):
    """A 1600 x 900 screen at 100 % leaves the display 960 x 630 pixels (60 % of the width,
    70 % of the height), so 1024 pixels across need a horizontal scroll bar. On a 3200 x 1800
    screen at 200 %, 1024 pixels drawn 2 x 2 would be wider than 1920 (60 % of 3200): they
    are drawn 1 x 1."""
    monkeypatch.setattr(bitmap, "scale", lambda widget: 1.0)
    monkeypatch.setattr(tkinter.Misc, "winfo_screenwidth", lambda self: 1600)
    monkeypatch.setattr(tkinter.Misc, "winfo_screenheight", lambda self: 900)
    window = bitmap_window(app)
    choose(window.size_boxes["width"], 1024)                # 1024 x 256: too wide only
    assert window.factor == 1 and window.hbar.winfo_manager() == "grid"
    assert not window.vbar.winfo_manager()
    assert (window.canvas.winfo_reqwidth(), window.canvas.winfo_reqheight()) == (960, 256)
    choose(window.size_boxes["height"], 1024)               # too high as well: both bars
    assert window.vbar.winfo_manager() == window.hbar.winfo_manager() == "grid"
    assert window.canvas.winfo_reqwidth() == 960 - window.vbar.winfo_reqwidth()
    assert window.canvas.winfo_reqheight() == 630 - window.hbar.winfo_reqheight()
    monkeypatch.setattr(bitmap, "scale", lambda widget: 2.0)
    monkeypatch.setattr(tkinter.Misc, "winfo_screenwidth", lambda self: 3200)
    monkeypatch.setattr(tkinter.Misc, "winfo_screenheight", lambda self: 1800)
    choose(window.size_boxes["height"], 256)                # 2048 x 512 would not fit
    assert window.factor == 1 and (window.image.width(), window.image.height()) == (1024, 256)
    assert not window.vbar.winfo_manager() and not window.hbar.winfo_manager()
    choose(window.size_boxes["width"], 512)                 # 1024 x 512 fits: 2 x 2
    assert window.factor == 2 and (window.image.width(), window.image.height()) == (1024, 512)


def test_on_a_scaled_screen_the_units_are_drawn_in_their_place(app, tmp_path, monkeypatch):
    """At 225 % each pixel of the display is 2 x 2 screen pixels: a unit of 8 x 8 pixels
    covers 16 x 16, and a row that changed is put at its own place in the picture."""
    monkeypatch.setattr(bitmap, "scale", lambda widget: 2.25)
    monkeypatch.setattr(tkinter.Misc, "winfo_screenwidth", lambda self: 3840)
    monkeypatch.setattr(tkinter.Misc, "winfo_screenheight", lambda self: 2160)
    loaded(app, tmp_path, PICTURE)
    window = small(app)
    assert window.factor == 2 and window.image.width() == window.image.height() == 128

    def pixels(columns, rows):
        return {window.image.get(x, y) for x in columns for y in rows}
    for _ in range(4):
        app.run("step")                 # the third unit, then the first of the second row
    assert pixels(range(16), range(16)) == {(255, 0, 0)}
    assert pixels(range(16, 32), range(16)) == {(0, 255, 0)}
    assert pixels(range(32, 48), range(16)) == {(0, 0, 255)}
    assert pixels(range(16), range(16, 32)) == {(0, 0, 255)}
    assert pixels(range(16, 32), range(16, 32)) == {(0, 0, 0)}
    choose(window.size_boxes["unit_height"], 1)             # 8 x 64 units of 8 x 1 pixels
    assert window.model.rows == 64 and window.image.height() == 128
    assert pixels(range(16), (0, 1)) == {(255, 0, 0)}         # the ninth word: row 1
    assert pixels(range(16), (2, 3)) == {(0, 0, 255)} and pixels(range(16), (4, 5)) == {(0, 0, 0)}


@pytest.mark.serial
def test_a_full_display_is_drawn_quickly(app, tmp_path):
    """512 x 512 units of 1 pixel, all changing: each refresh stays well under the 200 ms
    a window may stall (generous here: other tests may run at the same time)."""
    loaded(app, tmp_path, FILL)
    window = bitmap_window(app)
    choose(window.size_boxes["height"], 512)
    window.connect_button.invoke()
    times = []
    refresh = window.refresh

    def timed():
        start = time.perf_counter()
        refresh()
        times.append(time.perf_counter() - start)
    window.refresh = timed
    go_to_end(app)
    assert times and max(times) < 0.5, f"{max(times):.3f} s"
    assert unit_color(window, 1, 0) == fill_color(1)
    assert unit_color(window, 0, 1) == fill_color(512)
    assert unit_color(window, 511, 511) == fill_color(512 * 512 - 1)


def test_while_the_program_runs_the_display_takes_a_quarter_of_the_time_at_most(
        app, tmp_path, monkeypatch):
    """A refresh that took t keeps the next one away while the program runs, until 4 t
    after it began: a display that is slow to read and draw slows a run down by a third at
    most. Once the program stops, the display shows memory at once."""
    loaded(app, tmp_path, PICTURE)
    window = small(app)
    now, reads = [10.0], []
    update = window.model.update

    def slow_update():                  # reading and drawing take 50 ms
        reads.append(now[0])
        now[0] += 0.05
        return update()
    window.clock = lambda: now[0]
    monkeypatch.setattr(window.model, "update", slow_update)
    monkeypatch.setattr(app.runner, "state", State.RUNNING)
    window.refresh()
    for later in (10.1, 10.15):         # the next one comes at 10.2 at the earliest
        now[0] = later
        window.refresh()
    assert reads == [10.0]
    now[0] = 10.25
    window.refresh()
    assert reads == [10.0, 10.25]
    monkeypatch.setattr(app.runner, "state", State.PAUSED)
    now[0] = 10.31
    window.refresh()
    assert reads == [10.0, 10.25, 10.31]


def test_a_run_ends_with_memory_shown_also_when_refreshes_were_left_out(app, tmp_path):
    """COUNT writes into the display's first unit all the time: with reading and drawing
    made slow, fewer refreshes read memory than the run has, and the display shows the
    final count."""
    loaded(app, tmp_path, COUNT)
    window = bitmap_window(app)
    window.connect_button.invoke()
    calls, reads = [], []
    refresh, update = window.refresh, window.model.update

    def counted():
        calls.append(1)
        refresh()

    def slow_update():
        reads.append(1)
        time.sleep(0.05)
        return update()
    window.refresh = counted
    window.model.update = slow_update
    go_to_end(app, limit=60)
    assert app.runner.state is State.FINISHED
    assert len(calls) > 4 and len(reads) <= len(calls) / 2 + 1, (len(reads), len(calls))
    assert unit_color(window, 0, 0) == 7_500_000


def test_the_help_text(app):
    window = bitmap_window(app)
    text = paragraphs(window.HELP)
    for words in ("0x00RRGGBB", "Unit Width in Pixels", "Display Height in Pixels",
                  "Base address for display", ".data", "heap", "SVC #9", "Backstep",
                  "Reset", "0x3FFFFFFF"):
        assert words in text, words


@pytest.mark.parametrize("key", ["<Key-Return>", "<Key-KP_Enter>"])
def test_return_in_a_size_list_presses_connect(app, tmp_path, key):
    loaded(app, tmp_path, PICTURE)
    window = bitmap_window(app)
    press_key(window.size_boxes["width"], key)
    assert window.model.connected


def test_no_button_has_the_frame_while_the_base_field_has_the_focus(app):
    """Return there applies the address and presses no button (test_the_base_address)."""
    window = bitmap_window(app)
    buttons = all_buttons(window.window)
    assert framed(buttons) == ["Connect to ARM"]
    move_focus(None, window.base_box)
    assert framed(buttons) == []
    move_focus(window.base_box, window.size_boxes["width"])
    assert framed(buttons) == ["Connect to ARM"]
