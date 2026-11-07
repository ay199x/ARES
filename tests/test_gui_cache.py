# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Data Cache Simulator's window: its lists, numbers, block table and log."""

import time
import tkinter as tk
from tkinter import ttk

import pytest
from conftest import lay_out, native, press_key
from test_cache import ACCESSES, LOOP, MISSES
from test_gui_assemble import assemble
from test_gui_look import RETURN_KEYS, all_buttons, framed, move_focus, tab_cycle, widgets_of
from test_gui_run import go_to_end, loaded, run_until
from test_responsiveness import pictures
from test_runner import quiet_gc  # noqa: F401  (a fixture: collections walk ARES's objects only)
from unicorn import UC_MEM_READ

from ares.gui.style import FACE, WINDOW
from ares.gui.tools.cache import (COLOURS, EMPTY, HIT, LOG_LIMIT, MISS, PLACEMENTS,
                                  REPLACEMENTS, SIZES, CacheWindow)
from ares.gui.widgets import px
from ares.gui.tools.frame import paragraphs

FOREVER = """\
        .data
value:  .word   0
        .global _start
        .text
_start: LDR     R1, =value
loop:   LDR     R0, [R1]
        ADD     R0, R0, #1
        STR     R0, [R1]
        B       loop
"""
# count words from 0x100000 + start, one after the other. LDR R2, =count reads a literal at
# 0x1C, unless count fits a MOV (40 does, 1300 does not).
SWEEP = """\
        .global _start
_start: MOV     R1, #0x100000
        ADD     R1, R1, #{start}
        LDR     R2, ={count}
loop:   LDR     R0, [R1], #4
        SUBS    R2, R2, #1
        BNE     loop
        SVC     #10
"""
# 64 KB copied onto itself again and again, 32 words to a VLDM or VSTM.
LOADS = """\
        .data
        .balign 64
array:  .space  65536
        .global _start
        .text
_start: LDR     R1, =array
again:  MOV     R0, R1
        MOV     R2, #512
loop:   VLDM    R0, {D0-D15}
        VSTM    R0!, {D0-D15}
        SUBS    R2, R2, #1
        BNE     loop
        B       again
"""


def simulator(app):
    """Open the Data Cache Simulator (or bring it to the front); returns its window."""
    app.run("tool_cache")
    return app.tool_windows["tool_cache"]


def connected(app):
    window = simulator(app)
    window.connect_button.invoke()
    assert window.model.connected
    return window


def choose(box, value):
    """Choose value in a list, as a click on it in the list's drop-down does."""
    native(box)
    box.set(value)
    box.event_generate("<<ComboboxSelected>>")


def shown(window):
    """(accesses, hits, misses, hit rate) as the window shows them."""
    return (int(window.accesses.get()), int(window.hits.get()), int(window.misses.get()),
            window.rate.shown[0])


def colours(window):
    return [window.table.itemcget(cell, "fill") for cell in window.cells]


def log_text(window):
    return window.log_text.get("1.0", "end-1c")


# Opening it ----------------------------------------------------------------------------

def test_it_opens_from_the_tools_menu(app, hidden_windows):
    menu = app._menu_items["tool_cache"][0]
    menu.invoke(app._menu_items["tool_cache"][1])
    window = app.tool_windows["tool_cache"]
    assert isinstance(window, CacheWindow) and hidden_windows.shows(window.window)
    assert window.window.title() == "Data Cache Simulator"
    assert list(all_buttons(window.window)) == ["Connect to ARM", "Reset", "Close"]
    groups = [str(box.cget("text")) for box in widgets_of(window.window, ttk.Labelframe)]
    assert groups == ["Cache Organization", "Cache Performance", "Run-time Log", "Tool Control"]
    assert hidden_windows.focus is window.connect_button


def test_its_lists_and_what_it_shows_at_first(app):
    window = simulator(app)
    assert window.placement_box.cget("values") == PLACEMENTS
    assert window.replacement_box.cget("values") == REPLACEMENTS
    for box in (window.blocks_box, window.block_words_box):
        assert tuple(int(value) for value in box.cget("values")) == SIZES
    assert (window.placement_box.get(), window.replacement_box.get(), window.set_size_box.get(),
            window.blocks_box.get(), window.block_words_box.get(),
            window.cache_size.get()) == ("Direct Mapping", "LRU", "1", "8", "4", "128")
    assert [str(value) for value in window.set_size_box.cget("values")] == ["1"]
    assert all(str(box.cget("state")) == "readonly"
               for box in widgets_of(window.window, ttk.Combobox))
    assert shown(window) == (0, 0, 0, "0.0%")
    assert colours(window) == [COLOURS[EMPTY]] * 8 and COLOURS[EMPTY] == WINDOW
    assert window.table_order.cget("text") == "(block 0 at top)"
    assert not window.logging.get() and log_text(window) == ""
    assert window.log_text.cget("background") == FACE


# The organization ----------------------------------------------------------------------

def test_choosing_the_organization(app):
    window = simulator(app)
    model = window.model
    choose(window.placement_box, "N-way Set Associative")
    assert [int(value) for value in window.set_size_box.cget("values")] == [1, 2, 4, 8]
    assert window.set_size_box.get() == "1" and model.set_size == 1
    choose(window.set_size_box, "4")
    assert model.set_size == 4
    choose(window.blocks_box, "16")
    assert model.blocks == 16 and window.set_size_box.get() == "1" and model.set_size == 1
    assert len(window.cells) == 16 and window.cache_size.get() == "256"
    choose(window.block_words_box, "8")
    assert model.block_words == 8 and window.cache_size.get() == "512"
    choose(window.placement_box, "Fully Associative")
    assert [int(value) for value in window.set_size_box.cget("values")] == [16]
    assert window.set_size_box.get() == "16"
    choose(window.replacement_box, "Random")
    assert model.replacement == 1
    choose(window.placement_box, "Direct Mapping")
    assert window.set_size_box.get() == "1" and model.set_size == 1


def test_a_new_organization_starts_again_and_a_new_replacement_does_not(app, tmp_path):
    loaded(app, tmp_path, LOOP)
    window = connected(app)
    go_to_end(app)
    assert shown(window)[0] == ACCESSES
    choose(window.replacement_box, "Random")
    assert shown(window)[0] == ACCESSES and window.model.machine is app.machine
    choose(window.block_words_box, "2")
    assert shown(window) == (0, 0, 0, "0.0%")
    assert colours(window) == [COLOURS[EMPTY]] * 8
    assert window.model.connected


def test_many_blocks_have_columns_of_32(app):
    window = simulator(app)
    canvas = window.table
    assert int(canvas.cget("width")) == px(canvas, 40)
    assert int(canvas.cget("height")) == px(canvas, 128)
    choose(window.blocks_box, "2048")
    assert len(window.cells) == 2048 and len(canvas.find_all()) == 2048
    assert int(canvas.cget("width")) == px(canvas, 64 * 4)
    assert window.table_order.cget("text") == "(block 0 at top left)"
    first, second = (canvas.coords(window.cells[block]) for block in (0, 32))
    assert first[1] == second[1] == 0 and second[0] > first[0]         # 32 starts column 2
    assert canvas.coords(window.cells[31])[3] == int(canvas.cget("height")) - 1
    choose(window.blocks_box, "1")
    assert len(canvas.find_all()) == 1 and window.table_order.cget("text") == "(block 0 at top)"


# Following the program -------------------------------------------------------------------

def test_the_numbers_and_the_table_follow_the_program(app, tmp_path):
    loaded(app, tmp_path, LOOP)
    window = connected(app)
    app.run("step")                             # LDR R1, =array: a miss
    assert shown(window) == (1, 0, 1, "0.0%")
    assert colours(window).count(COLOURS[MISS]) == 1
    go_to_end(app)
    rate = f"{100 * (ACCESSES - MISSES) / ACCESSES:.1f}%"
    assert shown(window) == (ACCESSES, ACCESSES - MISSES, MISSES, rate)
    states = list(window.model.states)
    assert colours(window) == [COLOURS[state] for state in states]
    assert states.count(HIT) == 4 and states.count(MISS) == 1      # the literal's block
    assert COLOURS[HIT] == "#00FF00" and COLOURS[MISS] == "#FF0000"


def test_it_keeps_its_cache_across_reset_backstep_assemble_and_closing(app, tmp_path):
    loaded(app, tmp_path, LOOP)
    window = connected(app)
    for _ in range(4):
        app.run("step")
    app.run("backstep")                         # undone, but the accesses happened
    assert shown(window)[:3] == (2, 0, 2)
    app.run("reset")                            # Reset, F12: the cache stays
    assert shown(window)[:3] == (2, 0, 2)
    go_to_end(app)
    assert shown(window)[0] == 2 + ACCESSES
    assemble(app)                               # a new program: still connected
    assert window.model.connected and window.model.machine is app.machine
    go_to_end(app)
    assert shown(window)[:3] == (2 + 2 * ACCESSES, 2 + 2 * ACCESSES - MISSES, MISSES)
    app.run("close")                            # the program's file closed: it all stays
    assert window.model.connected and window.model.machine is None
    assert shown(window)[0] == 2 + 2 * ACCESSES
    assert window.connect_button.cget("text") == "Disconnect from ARM"


def test_it_opens_during_a_run(app, tmp_path):
    loaded(app, tmp_path, FOREVER)
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) > 100)
    window = connected(app)
    run_until(app, lambda: shown(window)[0] > 1000)     # refreshed after the slices
    app.run("stop")
    accesses, hits, misses, _ = shown(window)
    assert misses == 1 and hits == accesses - 1         # value's block, again and again


def test_the_tools_refresh_before_the_next_slice_is_due(app, tmp_path):
    """Looking up a slice's accesses takes a while: were the next slice scheduled first, it
    would be due at once, again and again, and Tk would never redraw the window (it
    redraws only while nothing is due)."""
    loaded(app, tmp_path, FOREVER)
    window = connected(app)
    scheduled = []
    refresh = window.refresh
    window.refresh = lambda: scheduled.append(app._tick_job is not None) or refresh()
    app.run("go")
    run_until(app, lambda: len(scheduled) > 3)
    app.run("stop")
    assert not any(scheduled)


@pytest.mark.serial
def test_no_slice_keeps_the_window_waiting_200_ms(app, tmp_path, quiet_gc):
    """The most a slice can bring: VLDM and VSTM of 16 D registers, 32 words each, in 2048
    blocks of one word, logged. A slice and looking up its accesses take the processor less
    than 200 ms (its time, so that other programs running meanwhile do not count)."""
    loaded(app, tmp_path, LOADS)
    window = connected(app)
    choose(window.blocks_box, "2048")
    choose(window.block_words_box, "1")
    window.log_check.invoke()
    busy = []
    tick = app._tick

    def timed():
        start = time.thread_time()
        tick()
        busy.append(time.thread_time() - start)
    app._tick = timed
    app.run("go")
    run_until(app, lambda: len(busy) > 12)
    app.run("stop")
    assert window.model.accesses > 100_000
    assert max(busy[1:]) < 0.2, [round(1000 * seconds) for seconds in busy]


def test_the_reset_button(app, tmp_path):
    loaded(app, tmp_path, LOOP)
    window = connected(app)
    window.log_check.invoke()
    assert window.model.logging
    go_to_end(app)
    assert log_text(window)
    window.reset_button.invoke()
    assert shown(window) == (0, 0, 0, "0.0%")
    assert colours(window) == [COLOURS[EMPTY]] * 8 and log_text(window) == ""
    assert window.model.connected and window.model.logging
    app.run("reset")
    app.run("step")
    assert shown(window)[:3] == (1, 0, 1)


def test_close_disconnects(app, tmp_path):
    loaded(app, tmp_path, LOOP)
    window = connected(app)
    window.close_button.invoke()
    assert window.window is None and not window.model.connected
    assert not app.machine.observers.active
    again = simulator(app)
    assert not again.model.connected and shown(again)[0] == 0


# The log ------------------------------------------------------------------------------

def test_the_log(app, tmp_path):
    loaded(app, tmp_path, LOOP)
    window = connected(app)
    app.run("step")                             # before the log is enabled: not logged
    window.log_check.invoke()
    assert window.logging.get() and window.model.logging
    assert window.log_text.cget("background") == WINDOW and log_text(window) == ""
    app.run("step")                             # MOV
    app.run("step")                             # MOV
    app.run("step")                             # the array's first word
    lines = log_text(window).split("\n")
    assert len(lines) == 2 and lines[0].startswith("(2) address 0x00000030, tag ")
    assert lines[1] == "     miss, block 3 was empty"
    app.run("step")
    app.run("step")
    app.run("step")
    app.run("step")                             # the array's second word
    assert log_text(window).split("\n")[2:] == [
        "(3) address 0x00000034, tag 0x00000000, set 3 (block 3)", "     hit in block 3"]
    window.log_check.invoke()
    assert not window.model.logging and log_text(window) == ""
    assert window.log_text.cget("background") == FACE
    go_to_end(app)
    assert log_text(window) == ""


def test_the_log_keeps_the_newest_accesses(app, tmp_path):
    count = LOG_LIMIT + 300
    loaded(app, tmp_path, SWEEP.format(start=0, count=count))
    window = connected(app)
    window.log_check.invoke()
    for _ in range(6):
        app.run("step")                         # a few logged one by one, then the rest
    go_to_end(app)
    lines = log_text(window).split("\n")
    assert len(lines) == 2 * LOG_LIMIT          # the literal and count words: the newest
    assert lines[0].startswith(f"({count + 1 - LOG_LIMIT + 1}) address ")
    assert lines[-2].startswith(f"({count + 1}) address 0x{0x100000 + 4 * (count - 1):08x},")


def test_the_log_text_drops_its_oldest_accesses(app):
    window = simulator(app)
    window.log_check.invoke()
    model = window.model
    for start in range(0, 1500, 300):           # five refreshes of 300 accesses
        for word in range(start, start + 300):
            model.accessed(None, UC_MEM_READ, 4 * word, 4, 0, None)
        window.refresh()
    lines = log_text(window).split("\n")
    assert len(lines) == 2 * LOG_LIMIT
    assert lines[0].startswith("(501) address 0x000007d0,") and lines[-2].startswith("(1500) ")


def test_the_log_shows_its_scroll_bars_only_when_needed(app, tmp_path, monkeypatch):
    """The room of the text and its bars keeps its size: the window does not change."""
    loaded(app, tmp_path, SWEEP.format(start=0, count=20))
    # Tk lays out no window that belongs to a hidden one, and placing the window before it
    # is shown settles that for good: this one belongs to no window.
    monkeypatch.setattr(tk.Wm, "transient", lambda window, master=None: "")
    window = connected(app)
    top = window.window
    assert lay_out(top) and lay_out(top)        # the window's size, then its parts'
    bars, size = window.log_bars, (top.winfo_reqwidth(), top.winfo_reqheight())
    window.log_check.invoke()
    bars.decide()
    assert not bars.yscroll.winfo_manager() and not bars.xscroll.winfo_manager()
    go_to_end(app)                              # 21 accesses: 42 lines
    bars.decide()
    assert bars.yscroll.winfo_manager() and not bars.xscroll.winfo_manager()
    assert (top.winfo_reqwidth(), top.winfo_reqheight()) == size


# The window ---------------------------------------------------------------------------

def test_only_the_cells_that_change_are_coloured_again(app, tmp_path):
    """64 blocks of a word: the words are blocks 8 to 47 (LDR R2, =40 is a MOV)."""
    loaded(app, tmp_path, SWEEP.format(start=32, count=40))
    window = connected(app)
    choose(window.blocks_box, "64")
    choose(window.block_words_box, "1")
    coloured = []
    configure = window.table.itemconfigure
    window.table.itemconfigure = lambda item, **options: coloured.append(item) or configure(
        item, **options)
    for _ in range(4):
        app.run("step")                         # MOV, ADD, MOV, the first word
    assert coloured == [window.cells[8]]
    app.run("step")                             # SUBS: nothing changes
    assert len(coloured) == 1
    go_to_end(app)
    assert len(coloured) == 40 and colours(window).count(COLOURS[MISS]) == 40


def test_refreshing_shows_only_what_changed(app, tmp_path):
    loaded(app, tmp_path, LOOP)
    window = connected(app)
    shows = []
    show = window.show
    window.show = lambda: shows.append(1) or show()
    app.run("step")
    app.run("step")                             # MOV: no access, nothing to show
    app.run("reset")
    assert len(shows) == 1


@pytest.mark.parametrize("key", RETURN_KEYS)
def test_return_presses_the_framed_button(app, key):
    window = simulator(app)
    buttons = all_buttons(window.window)
    assert framed(buttons) == ["Connect to ARM"]
    pressed = []
    for label, button in buttons.items():
        button.configure(command=lambda label=label: pressed.append(label))
    order = [buttons["Close"], buttons["Reset"], window.placement_box,
             window.log_check, window.log_text, buttons["Connect to ARM"]]
    previous = None
    for widget in order:
        move_focus(previous, widget)
        previous = widget
        press_key(widget, key)
    assert pressed == ["Close", "Reset"] + ["Connect to ARM"] * 4


def test_tab_goes_round_the_lists_enabled_the_log_and_the_buttons(app):
    """Tab and Shift+Tab never stay in the log, and they pass it by while it is gray and
    empty (Enabled not checked), as a field that is switched off."""
    window = simulator(app)
    native(window.window)
    connect = window.connect_button
    stops = [window.reset_button, window.close_button,
             *widgets_of(window.window, ttk.Combobox), window.log_check]
    assert len(stops) == 2 + 5 + 1
    assert tab_cycle(connect) == stops + [connect]
    assert tab_cycle(connect, back=True) == stops[::-1] + [connect]
    window.log_check.invoke()                   # Enabled: the log is white, and takes the focus
    stops.append(window.log_text)
    assert tab_cycle(connect) == stops + [connect]
    assert tab_cycle(connect, back=True) == stops[::-1] + [connect]
    window.log_check.invoke()
    assert window.log_text not in tab_cycle(connect)


def test_escape_closes(app, tmp_path):
    loaded(app, tmp_path, LOOP)
    window = connected(app)
    press_key(window.window, "<Key-Escape>")
    assert window.window is None and not app.machine.observers.active


def test_the_help_text(app):
    window = simulator(app)
    text = paragraphs(window.HELP)
    for words in ("Placement policy", "Direct Mapping", "Fully Associative",
                  "N-way Set Associative", "LRU", "Random", "Number of blocks",
                  "Cache block size (words)", "Set size (blocks)", "Cache size (bytes)",
                  "Memory access count", "Cache hit rate", "green", "red", "Enabled",
                  "LDRD", "VLDR", "PUSH", "STREX", "DE1-SoC", "literal pool", "Reset"):
        assert words in text, words
    assert "\n\n" in text


def test_no_pictures_are_made_for_the_simulator(app, tmp_path):
    made = pictures(app.root)
    loaded(app, tmp_path, LOOP)
    window = connected(app)
    window.log_check.invoke()
    go_to_end(app)
    choose(window.blocks_box, "2048")
    window.reset_button.invoke()
    window.close()
    assert pictures(app.root) == made
