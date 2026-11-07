# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Memory Reference Visualization's window: its controls, the display in colour, the base
addresses, the colours, and what it draws again."""

import pytest
from conftest import press_key
from test_gui_assemble import assemble
from test_gui_look import RETURN_KEYS, all_buttons, framed, move_focus
from test_gui_run import go_to_end, loaded, run_until
from test_memref import ODD_CODE
from test_responsiveness import pictures

from ares.gui import tools
from ares.gui.places import STACK_TEXT
from ares.gui.tools import memref
from ares.gui.tools.memref import COUNTS, PLACES, VisualizationWindow
from ares.gui.widgets import px
from ares.gui.tools.frame import paragraphs

PROGRAM = """\
        .data
values: .word   1, 2, 3, 4
        .global _start
        .text
_start: LDR     R1, =values
        LDR     R0, [R1]            @ values[0]: read once
        STR     R0, [R1, #4]        @ values[1]: written twice
        STR     R0, [R1, #4]
        MOV     R2, #5
loop:   LDR     R0, [R1, #12]       @ values[3]: read and written 5 times
        STR     R0, [R1, #12]
        SUBS    R2, R2, #1
        BNE     loop
        PUSH    {R0, R1}
        SVC     #10
"""
# The colours of values[0] to values[3] at the end: 1, 2, 0 and 10 accesses.
BLUE, GREEN, BLACK, RED = (0, 0, 255), (0, 255, 0), (0, 0, 0), (255, 0, 0)
END_COLOURS = [BLUE, GREEN, BLACK, RED]
# Data that starts one word later: the same program with one more instruction.
LATER = PROGRAM.replace("        SVC     #10", "        MOV     R0, #0\n        SVC     #10")
# A word in each of the first three rows of the display (16 words a row).
COLUMN = """\
        .data
values: .space  1024
        .global _start
        .text
_start: LDR     R1, =values
        STR     R0, [R1, #4]            @ row 0, column 1
        STR     R0, [R1, #68]           @ row 1, column 1
        STR     R0, [R1, #136]          @ row 2, column 2
        SVC     #10
"""
FOREVER = """\
        .data
value:  .word   0
        .global _start
        .text
_start: LDR     R1, =value
loop:   ADD     R0, R0, #1
        STR     R0, [R1]
        B       loop
"""


def visualization(app):
    """Open the tool (or bring it to the front); returns its window."""
    app.run("tool_memref")
    return app.tool_windows["tool_memref"]


def connected(app):
    window = visualization(app)
    window.connect_button.invoke()
    assert window.model.connected
    return window


def colour_at(window, unit):
    """The colour of the middle of a unit on the display."""
    width, height = window.unit_size
    columns = window.model.columns
    return window.picture.get((unit % columns) * width + width // 2,
                              (unit // columns) * height + height // 2)


def colours(window, units=4):
    return [colour_at(window, unit) for unit in range(units)]


def choose(box, value):
    """Choose a value in a drop-down list, as a click in its list does."""
    box.winfo_id()                          # generated events need the widget's window
    box.current(list(box.cget("values")).index(value))
    box.event_generate("<<ComboboxSelected>>")


def grid_lines(window):
    return window.canvas.find_withtag("grid")


def line_colours(window):
    return {window.canvas.itemcget(line, "fill") for line in grid_lines(window)}


# The window --------------------------------------------------------------------------

def test_it_opens_from_the_tools_menu(app, hidden_windows):
    menu, index = app._menu_items["tool_memref"]
    assert tools.available("tool_memref") and app.is_enabled("tool_memref")
    assert menu.entrycget(index, "state") == "normal"
    menu.invoke(index)
    window = app.tool_windows["tool_memref"]
    assert isinstance(window, VisualizationWindow) and hidden_windows.shows(window.window)
    assert window.window.title() == "Memory Reference Visualization"
    assert list(all_buttons(window.window)) == ["", "Connect to ARM", "Reset", "Close"]
    assert hidden_windows.focus is window.connect_button


def test_its_settings_start_as_listed(app):
    window = visualization(app)
    assert {name: box.get() for name, box in window.lists.items()} == {
        "words_per_unit": "1", "unit_width": "16", "unit_height": "16", "width": "256",
        "height": "256"}
    assert window.lists["words_per_unit"].cget("values")[-1] == "2048"
    assert list(window.lists["unit_width"].cget("values")) == ["1", "2", "4", "8", "16", "32"]
    assert list(window.lists["height"].cget("values")) == ["64", "128", "256", "512", "1024"]
    assert all(str(box.cget("state")) == "readonly" for box in window.lists.values())
    assert window.grid_shown.get() and window.grid_box.cget("text") == "Grid lines between units"
    # Without a program the program's places have no address (test_gui_places).
    assert list(window.base_list.cget("values")) == [
        ".data: no program assembled", "heap: no program assembled", STACK_TEXT,
        ".text: no program assembled"]
    assert window.base_list.get() == ".data: no program assembled"
    assert COUNTS[round(window.slider.get())] == 10
    assert window.count_label.cget("text") == "10 or more accesses"
    unit = px(window.canvas, 16)
    assert window.unit_size == (unit, unit)
    assert (int(window.canvas.cget("width")), int(window.canvas.cget("height"))) == (16 * unit,
                                                                                     16 * unit)
    assert (window.picture.width(), window.picture.height()) == (16 * unit, 16 * unit)
    assert (window.units.width(), window.units.height()) == (16, 16)
    assert colours(window, 256) == [BLACK] * 256


def test_the_base_addresses_are_the_programs(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = visualization(app)
    values = app.machine.program.label_address("values")
    assert list(window.base_list.cget("values")) == [
        f"0x{values:08x} (.data)", f"0x{values + 16:08x} (heap)", STACK_TEXT,
        "0x00000000 (.text)"]
    assert window.base_list.get() == f"0x{values:08x} (.data)" and window.model.base == values


def test_a_program_whose_data_starts_off_a_word(app, tmp_path):
    """The display then starts at the word that holds the data's first byte."""
    window = connected(app)
    loaded(app, tmp_path, ODD_CODE)
    assert app.machine.program.label_address("table") == 1
    assert window.model.base == 0 and window.model.machine is app.machine
    assert window.base_list.get() == "0x00000000 (.data)"


def test_connected_it_shows_the_counts_in_colour(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    assert app.machine.observers.active
    app.run("step")
    app.run("step")
    assert colours(window) == [BLUE, BLACK, BLACK, BLACK]       # LDR R0, [R1]
    go_to_end(app)
    assert colours(window) == END_COLOURS
    assert window.model.counts[:4] == [1, 2, 0, 10]
    assert colour_at(window, 4) == BLACK


def test_connected_during_a_run_it_follows_the_run(app, tmp_path):
    loaded(app, tmp_path, FOREVER)
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) > 100)
    window = connected(app)
    count = app.machine.reg(0)
    run_until(app, lambda: colour_at(window, 0) == RED)     # refreshed after the slices
    app.run("stop")
    assert 10 <= window.model.counts[0] <= app.machine.reg(0) - count + 1


def painted_areas(window):
    """The areas the window paints from now on: (first row, last row, first column, last
    column)."""
    painted = []
    paint = window._paint
    window._paint = lambda *area: painted.append(area) or paint(*area)
    return painted


def test_a_step_draws_only_the_units_that_changed(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    painted = painted_areas(window)
    app.run("step")                         # LDR R1, =values: nothing shown changes
    assert painted == []
    app.run("step")                         # values[0] read: unit 0
    assert painted == [(0, 0, 0, 0)]
    app.run("step")                         # values[1] written: blue
    app.run("step")                         # and again: green
    assert painted == [(0, 0, 0, 0), (0, 0, 1, 1), (0, 0, 1, 1)]
    assert colours(window) == [BLUE, GREEN, BLACK, BLACK]


def test_a_refresh_draws_the_columns_that_changed_in_the_rows_that_changed(app, tmp_path):
    """Units changed down a column (an array walked by columns) draw a narrow band, however
    wide the display."""
    loaded(app, tmp_path, COLUMN)
    window = connected(app)
    painted = painted_areas(window)
    go_to_end(app)
    assert painted == [(0, 2, 1, 2)]
    assert [colour_at(window, unit) for unit in (0, 1, 2, 16, 17, 18, 32, 33, 34, 35)] == [
        BLACK, BLUE, BLACK, BLACK, BLUE, BLACK, BLACK, BLACK, BLUE, BLACK]
    app.run("reset")
    go_to_end(app)                          # once more: green, the others stay
    assert painted[1:] == [(0, 2, 1, 2)]
    assert [colour_at(window, unit) for unit in (1, 2, 17, 18, 33, 34)] == [
        GREEN, BLACK, GREEN, BLACK, BLACK, GREEN]


def test_choosing_a_base_address_starts_the_display_again(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    go_to_end(app)
    app.run("reset")
    choose(window.base_list, STACK_TEXT)    # SP 0: the page of 0xfffffffc
    assert window.model.base == 0xFFFFFE00 and not any(window.model.counts)
    assert window.base_list.get() == STACK_TEXT
    assert colours(window) == [BLACK] * 4
    go_to_end(app)                          # PUSH {R0, R1}: the last two words of memory
    assert colour_at(window, 126) == colour_at(window, 127) == BLUE
    choose(window.base_list, "0x00000000 (.text)")
    go_to_end(app)                          # nothing: the program has finished
    app.run("reset")
    go_to_end(app)
    # The instructions as reads of their words: those of the loop ran 5 times (orange).
    loop = app.machine.program.label_address("loop") // 4
    assert [colour_at(window, unit) for unit in (0, loop, loop + 3, loop + 4)] == [
        BLUE, (255, 200, 0), (255, 200, 0), BLUE]


def test_current_sp_is_looked_up_when_the_list_opens(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n.text\n_start: LDR SP, =0x40000000\n"
                          "        PUSH {R0}\n        SVC #10\n")
    window = visualization(app)
    app.run("step")
    assert STACK_TEXT in window.base_list.cget("values")
    window.base_list.tk.eval(window.base_list.cget("postcommand"))      # the list opens
    assert "0x3ffffe00 (current SP)" in window.base_list.cget("values")
    choose(window.base_list, "0x3ffffe00 (current SP)")
    window.connect_button.invoke()
    go_to_end(app)
    assert colour_at(window, (0x3FFFFFFC - 0x3FFFFE00) // 4) == BLUE


def test_the_settings_change_the_display(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    go_to_end(app)
    choose(window.lists["unit_width"], "32")
    model = window.model
    assert (model.columns, model.rows, model.unit_width) == (8, 16, 32)
    width, height = window.unit_size
    assert width == px(window.canvas, 32) and int(window.canvas.cget("width")) == 8 * width
    assert window.picture.width() == 8 * width and window.units.width() == 8
    assert not any(model.counts) and colours(window) == [BLACK] * 4
    assert len(grid_lines(window)) == 8 + 16
    choose(window.lists["width"], "1024")
    choose(window.lists["height"], "64")
    choose(window.lists["unit_height"], "4")
    assert (model.columns, model.rows) == (32, 16) and len(model.counts) == 512
    choose(window.lists["words_per_unit"], "2")
    assert model.words_per_unit == 2
    app.run("reset")
    go_to_end(app)
    # 2 words per unit: values[0] and [1] (3 accesses, yellow), values[2] and [3] (red).
    assert colours(window, 2) == [(255, 255, 0), RED]


def test_the_grid_lines(app):
    window = visualization(app)
    lines = grid_lines(window)
    assert len(lines) == 16 + 16
    assert line_colours(window) == {"#FFFFFF"}
    unit, line = window.unit_size[0], px(window.canvas, 1)
    assert window.canvas.coords(lines[1]) == [unit, 0, unit + line, 16 * unit]  # a left edge
    window.grid_box.invoke()
    assert not window.grid_shown.get() and grid_lines(window) == ()
    window.grid_box.invoke()
    assert len(grid_lines(window)) == 32


def test_the_grid_lines_keep_the_counts(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    go_to_end(app)
    window.grid_box.invoke()
    window.grid_box.invoke()
    assert window.model.counts[:4] == [1, 2, 0, 10] and colours(window) == END_COLOURS


def test_a_click_on_the_slider_gives_it_the_keyboard_focus(app, hidden_windows):
    window = visualization(app)
    press_key(window.slider, "<ButtonPress-1>")
    assert hidden_windows.focus is window.slider


def test_the_slider_chooses_the_count_whose_colour_the_button_shows(app):
    window = visualization(app)
    patch = window.patch
    middle = (patch.width() // 2, patch.height() // 2)
    assert patch.get(*middle) == RED and patch.get(0, 0) == BLACK      # with its black edge
    window.slider.set(COUNTS.index(3))
    assert window.count_label.cget("text") == "3 to 4 accesses"
    assert patch.get(*middle) == (255, 255, 0)
    window.slider.set(4.4)                  # stops at whole positions
    assert window.slider.get() == 4 and window.count_label.cget("text") == "4 accesses"
    window.slider.set(1)
    assert window.count_label.cget("text") == "1 access" and patch.get(*middle) == BLUE
    window.slider.set(len(COUNTS) - 1)
    assert window.count_label.cget("text") == "1,000,000 or more accesses"


def test_changing_a_colour(app, tmp_path, monkeypatch):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    go_to_end(app)
    asked = []

    def askcolor(colour, title, parent):
        asked.append((colour, title, parent))
        return (0x12, 0x34, 0x56), "#123456"
    monkeypatch.setattr(memref, "askcolor", askcolor)
    window.slider.set(1)
    window.colour_button.invoke()
    assert asked == [("#0000FF", "Colour of 1 access", window.window)]
    assert colours(window) == [(0x12, 0x34, 0x56), GREEN, BLACK, RED]
    assert window.patch.get(window.patch.width() // 2, window.patch.height() // 2) == (
        0x12, 0x34, 0x56)
    window.slider.set(0)                    # no access: the grid lines take the opposite
    window.colour_button.invoke()
    assert colour_at(window, 2) == (0x12, 0x34, 0x56)
    assert line_colours(window) == {"#EDCBA9"}
    window.slider.set(COUNTS.index(20))     # inside 10 or more: 20 or more get their own
    window.colour_button.invoke()
    assert window.count_label.cget("text") == "20 or more accesses"
    assert window.colours.last(10) == 19 and colour_at(window, 3) == RED
    monkeypatch.setattr(memref, "askcolor", lambda colour, title, parent: (None, None))
    window.slider.set(1)
    window.colour_button.invoke()           # cancelled: nothing changes
    assert colour_at(window, 0) == (0x12, 0x34, 0x56)


def test_grid_lines_drawn_again_take_the_colour_opposite_to_no_access(app, monkeypatch):
    """After the colour of no access changed, the lines that the check box or a setting draws
    again are in its opposite colour too, also when it changed while they were hidden."""
    window = visualization(app)
    monkeypatch.setattr(memref, "askcolor",
                        lambda colour, title, parent: ((255, 255, 255), "#ffffff"))
    window.slider.set(0)
    window.colour_button.invoke()           # no access white: the lines turn black
    assert line_colours(window) == {"#000000"}
    window.grid_box.invoke()
    window.grid_box.invoke()                # drawn again
    assert len(grid_lines(window)) == 16 + 16 and line_colours(window) == {"#000000"}
    choose(window.lists["unit_width"], "32")    # the display laid out again
    assert len(grid_lines(window)) == 8 + 16 and line_colours(window) == {"#000000"}
    window.grid_box.invoke()                # hidden while no access changes colour
    monkeypatch.setattr(memref, "askcolor",
                        lambda colour, title, parent: ((0x12, 0x34, 0x56), "#123456"))
    window.colour_button.invoke()
    assert grid_lines(window) == ()
    window.grid_box.invoke()
    assert len(grid_lines(window)) == 8 + 16 and line_colours(window) == {"#EDCBA9"}


@pytest.mark.parametrize("key", RETURN_KEYS)
def test_return_presses_the_framed_button(app, key, monkeypatch):
    window = visualization(app)
    buttons = all_buttons(window.window)
    assert framed(buttons) == ["Connect to ARM"]
    pressed = []
    for label, button in buttons.items():
        button.configure(command=lambda label=label: pressed.append(label))
    order = [window.colour_button, window.lists["width"], window.slider, buttons["Close"],
             window.window, buttons["Connect to ARM"]]
    previous = None
    for widget in order:
        move_focus(previous, widget)
        previous = widget
        press_key(widget, key)
    assert pressed == ["", "Connect to ARM", "Connect to ARM", "Close", "Connect to ARM",
                       "Connect to ARM"]
    move_focus(window.window, window.colour_button)
    assert framed(buttons) == [""]


# What survives -------------------------------------------------------------------------

def test_counts_survive_reset_backstep_and_assemble_at_the_same_place(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    for _ in range(3):
        app.run("step")
    app.run("backstep")                     # undone, but the access happened
    assert colours(window) == [BLUE, BLUE, BLACK, BLACK]
    app.run("reset")
    assert colours(window) == [BLUE, BLUE, BLACK, BLACK]
    app.run("step")
    app.run("step")
    assemble(app)                           # the same program: the same place
    assert window.model.machine is app.machine and window.model.connected
    assert colours(window) == [GREEN, BLUE, BLACK, BLACK]


def test_assembled_with_other_addresses_the_display_moves(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    go_to_end(app)
    values = app.machine.program.label_address("values")
    loaded(app, tmp_path, LATER, "later.s")
    assert window.model.base == values + 4 == app.machine.program.label_address("values")
    assert window.base_list.get() == f"0x{values + 4:08x} (.data)"
    assert not any(window.model.counts) and colours(window) == [BLACK] * 4
    assert window.model.machine is app.machine
    go_to_end(app)
    assert colours(window) == END_COLOURS


def test_closing_the_programs_file_keeps_the_display(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    go_to_end(app)
    base = window.model.base
    app.run("close")
    assert app.machine is None and window.model.connected and window.model.machine is None
    assert window.model.base == base and colours(window) == END_COLOURS
    assert window.base_list.get() == ".data: no program assembled"
    assert window.connect_button.cget("text") == "Disconnect from ARM"
    loaded(app, tmp_path, PROGRAM, "other.s")
    assert window.model.machine is app.machine and colours(window) == END_COLOURS
    go_to_end(app)
    assert window.model.counts[:4] == [2, 4, 0, 20]


def test_the_reset_button_clears_the_display(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    go_to_end(app)
    window.reset_button.invoke()
    assert not any(window.model.counts) and colours(window) == [BLACK] * 4
    assert window.model.connected


def test_close_disconnects_and_lets_its_pictures_go(app, tmp_path):
    made = pictures(app.root)
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    assert len(pictures(app.root) - made) == 3          # the display's two, the button's
    window.close_button.invoke()
    assert window.window is None
    assert not window.model.connected and not app.machine.observers.active
    assert pictures(app.root) == made
    go_to_end(app)
    again = visualization(app)
    assert not again.model.connected and not any(again.model.counts)


def test_no_pictures_are_made_after_it_opened(app, tmp_path, monkeypatch):
    window = visualization(app)
    made = pictures(app.root)
    loaded(app, tmp_path, PROGRAM)
    window.connect_button.invoke()
    go_to_end(app)
    choose(window.lists["width"], "512")
    choose(window.lists["unit_height"], "1")
    choose(window.base_list, window.base_list.cget("values")[3])
    monkeypatch.setattr(memref, "askcolor", lambda colour, title, parent: (None, "#808080"))
    window.colour_button.invoke()
    window.grid_box.invoke()
    window.reset_button.invoke()
    app.run("reset")
    go_to_end(app)
    assert pictures(app.root) == made


def test_the_help_text(app):
    window = visualization(app)
    text = paragraphs(window.HELP)
    for words in ("Words per unit", "Unit width", "Display width", "Base address",
                  "Grid lines between units", "SVC #9", *PLACES,
                  "as in the Dynamic Instruction Counter",
                  "once for each word it reads or writes, in the unit of that word",
                  "an unaligned LDR R0, [R1, #2] reads from two words", "STREX counts two"):
        assert words in text, words
