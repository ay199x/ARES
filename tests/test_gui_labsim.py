# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Digital Lab Sim's window: the board it draws, its switches and keys, and what
survives Assemble, Reset, Backstep and closing the program's file."""

from conftest import native, press_key
from test_gui_assemble import assemble
from test_gui_look import all_buttons
from test_gui_run import go_to_end, loaded, run_until
from test_responsiveness import pictures

from ares.devices import EDGE_CAPTURE, HEX3_HEX0, KEYS, LEDS, SWITCHES
from ares.gui import tools
from ares.gui.execute import CHANGED
from ares.gui.tools import frame
from ares.gui.tools.labsim import (COLUMN, DARK_LED, DARK_SEGMENT, KEY_TIP, LIT_LED,
                                   LIT_SEGMENT, RESET_TIP, SLOT, SWITCH_TIP, LabSimWindow)
from ares.gui.widgets import px
from ares.gui.tools.frame import paragraphs

# 3 2 1 0 on HEX3-HEX0, 5 4 on HEX5 and HEX4, LEDR9, LEDR5 and LEDR0.
SHOW = """\
        .data
digits: .word   0x4F5B063F, 0x6D66
        .global _start
        .text
_start: LDR     R0, =0xFF200000
        LDR     R1, =digits
        LDR     R2, [R1]
        STR     R2, [R0, #0x20]
        LDR     R2, [R1, #4]
        STR     R2, [R0, #0x30]
        LDR     R2, =0x221
        STR     R2, [R0]
        SVC     #10
"""
DIGITS = (0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D)
# Each switch lights its LED; KEY0 ends the program.
FOLLOW = """\
        .global _start
        .text
_start: LDR     R0, =0xFF200000
        STR     R0, [R0, #0x5C]
loop:   LDR     R1, [R0, #0x40]
        STR     R1, [R0]
        LDR     R2, [R0, #0x5C]
        TST     R2, #1
        BEQ     loop
        SVC     #10
"""


def labsim(app):
    """Open the Digital Lab Sim (or bring it to the front); returns its window."""
    app.run("tool_labsim")
    return app.tool_windows["tool_labsim"]


def connected(app):
    window = labsim(app)
    window.connect_button.invoke()
    assert window.model.connected
    return window


def lit(canvas, items, colour):
    """The bits of the items drawn in colour: bit k for item k."""
    return sum(1 << k for k, item in enumerate(items) if canvas.itemcget(item, "fill") == colour)


def segments(window, display):
    return lit(window.displays, window.segment_items[display], LIT_SEGMENT)


def leds(window):
    return lit(window.leds, window.led_items, LIT_LED)


def switches_up(window):
    """The switches as drawn: bit k is 1 while the knob of SWk is in the upper half."""
    canvas = window.switches
    middle = px(canvas, SLOT[1]) / 2
    return sum(1 << k for k in range(10)
               if min(canvas.coords(item)[1] for item in canvas.find_withtag(f"knob{k}")) < middle)


def click_switch(window, switch):
    canvas = window.switches
    native(canvas)
    column = px(canvas, COLUMN)
    x = (9 - switch) * column + column // 2
    canvas.event_generate("<ButtonPress-1>", x=x, y=px(canvas, 10))
    canvas.event_generate("<ButtonRelease-1>", x=x, y=px(canvas, 10))


def key_event(window, key, sequence, held=False):
    button = window.key_buttons[key]
    native(button)
    button.event_generate(sequence, x=3, y=3, state=0x100 if held else 0)


def press(window, key):
    key_event(window, key, "<ButtonPress-1>")


def release(window, key):
    key_event(window, key, "<ButtonRelease-1>", held=True)


# The window --------------------------------------------------------------------------

def test_the_lab_sim_opens_from_the_tools_menu(app, hidden_windows):
    assert tools.available("tool_labsim") and app.is_enabled("tool_labsim")
    menu, index = app._menu_items["tool_labsim"]
    assert menu.entrycget(index, "state") == "normal"
    menu.invoke(index)
    window = app.tool_windows["tool_labsim"]
    assert isinstance(window, LabSimWindow) and hidden_windows.shows(window.window)
    assert window.window.title() == "Digital Lab Sim"
    buttons = all_buttons(window.window)
    assert [buttons[name] for name in ("Connect to ARM", "Reset", "Close")] == list(
        window.buttons)
    assert hidden_windows.focus is window.connect_button
    assert window.tips[window.reset_button].text == RESET_TIP


def test_the_board_is_laid_out_as_on_the_de1_soc(app):
    window = labsim(app)
    groups = window.window.winfo_children()[0].pack_slaves()[0].winfo_children()
    assert [group.cget("text") for group in groups] == [
        "Seven-segment displays (0xff200020, 0xff200030)", "Red LEDs (0xff200000)",
        "Slide switches (0xff200040)", "Push buttons (0xff200050)"]
    displays, leds_canvas, switches = window.displays, window.leds, window.switches
    names = [displays.itemcget(item, "text") for item in displays.find_all()
             if displays.type(item) == "text"]
    assert names == [f"HEX{n}" for n in range(5, -1, -1)]               # HEX5 at the left
    assert [len(items) for items in window.segment_items] == [7] * 6
    x = [displays.coords(items[0])[0] for items in window.segment_items]
    assert x == sorted(x, reverse=True)                                 # HEX0 at the right
    for canvas in (leds_canvas, switches):
        numbers = [canvas.itemcget(item, "text") for item in canvas.find_all()
                   if canvas.type(item) == "text"]
        assert numbers == [str(n) for n in range(9, -1, -1)]          # 9 at the left
    assert int(leds_canvas.cget("width")) == int(switches.cget("width"))   # LEDRk above SWk
    led_x = [leds_canvas.coords(item)[0] for item in window.led_items]
    assert led_x == sorted(led_x, reverse=True)
    row = window.key_buttons[0].master
    assert [button.cget("text") for button in row.pack_slaves()] == [
        "KEY3", "KEY2", "KEY1", "KEY0"]
    assert [button.cget("text") for button in window.key_buttons] == [
        "KEY0", "KEY1", "KEY2", "KEY3"]
    assert not any(button.cget("takefocus") for button in window.key_buttons)


def test_bit_k_of_a_display_is_drawn_as_its_segment_k(app):
    """0 top, 1 upper right, 2 lower right, 3 bottom, 4 lower left, 5 upper left, 6 middle:
    the middle of each segment, as a share of its digit's width and height."""
    expected = [(0.5, 0), (1, 0.25), (1, 0.75), (0.5, 1), (0, 0.75), (0, 0.25), (0.5, 0.5)]
    window = labsim(app)
    canvas = window.displays
    for items in window.segment_items:
        corners = [canvas.coords(item) for item in items]
        xs = [x for points in corners for x in points[0::2]]
        ys = [y for points in corners for y in points[1::2]]
        for points, (share_x, share_y) in zip(corners, expected):
            middle_x, middle_y = sum(points[0::2]) / 6, sum(points[1::2]) / 6
            assert abs((middle_x - min(xs)) / (max(xs) - min(xs)) - share_x) < 0.15
            assert abs((middle_y - min(ys)) / (max(ys) - min(ys)) - share_y) < 0.15


def test_a_new_board_is_dark_with_its_switches_down(app):
    window = labsim(app)
    assert [segments(window, n) for n in range(6)] == [0] * 6 and leds(window) == 0
    assert all(window.displays.itemcget(item, "fill") == DARK_SEGMENT
               for items in window.segment_items for item in items)
    assert all(window.leds.itemcget(item, "fill") == DARK_LED for item in window.led_items)
    assert switches_up(window) == 0


def test_the_window_shows_what_the_program_writes(app, tmp_path):
    loaded(app, tmp_path, SHOW)
    window = connected(app)
    go_to_end(app)
    assert [segments(window, n) for n in range(6)] == list(DIGITS)
    assert leds(window) == 0x221
    assert app.messages.messages.get("1.0", "end-1c").count("not simulated") == 0


def test_disconnected_the_program_is_warned_and_the_board_keeps_what_it_shows(app, tmp_path):
    loaded(app, tmp_path, SHOW)
    window = connected(app)
    go_to_end(app)
    window.connect_button.invoke()                  # Disconnect from ARM
    app.run("reset")
    go_to_end(app)
    messages = app.messages.messages.get("1.0", "end-1c")
    assert "DE1-SoC device at 0xff200020 is not simulated" in messages
    assert leds(window) == 0x221 and segments(window, 5) == DIGITS[5]


def test_a_click_flips_a_switch_and_the_program_reads_it(app, tmp_path):
    loaded(app, tmp_path, FOLLOW)
    window = connected(app)
    click_switch(window, 3)
    click_switch(window, 9)
    assert window.model.board.switches == 0x208 and switches_up(window) == 0x208
    for _ in range(4):
        app.run("step")
    assert leds(window) == 0x208
    click_switch(window, 3)                         # down again
    assert switches_up(window) == 0x200
    for _ in range(5):
        app.run("step")
    assert leds(window) == 0x200


def test_a_key_is_pressed_while_the_mouse_button_is_held_on_it(app):
    window = labsim(app)
    board = window.model.board
    press(window, 2)
    assert (board.keys, board.edges) == (0b100, 0b100)
    assert window.key_buttons[2].instate(["pressed"])                   # drawn pressed in
    key_event(window, 2, "<Leave>", held=True)       # the mouse leaves it: let go
    assert (board.keys, board.edges) == (0, 0b100)
    key_event(window, 2, "<Enter>", held=True)       # and comes back: pressed again
    assert board.keys == 0b100
    release(window, 2)
    assert (board.keys, board.edges) == (0, 0b100)
    assert not window.key_buttons[2].instate(["pressed"])
    key_event(window, 1, "<Enter>")                  # passing over a key presses nothing
    key_event(window, 1, "<Leave>")
    assert (board.keys, board.edges) == (0, 0b100)


def test_a_program_sees_a_key_press(app, tmp_path):
    loaded(app, tmp_path, FOLLOW)
    window = connected(app)
    app.run("go")
    run_until(app, lambda: app.machine.reg(15) > 8)             # polling
    click_switch(window, 0)
    run_until(app, lambda: leds(window) == 1)                   # refreshed after a slice
    press(window, 0)
    release(window, 0)
    run_until(app, lambda: app.runner.state.name == "FINISHED")
    assert window.model.board.edges == 1


def test_the_board_survives_reset_assemble_and_closing_the_file(app, tmp_path):
    loaded(app, tmp_path, SHOW)
    window = connected(app)
    click_switch(window, 6)
    go_to_end(app)
    app.run("reset")                                # Reset, F12: the board keeps it all
    assert leds(window) == 0x221 and segments(window, 0) == DIGITS[0]
    assert app.machine.board is window.model.board
    assemble(app)                                   # a new program: still connected
    assert window.model.connected and app.machine.board is window.model.board
    assert leds(window) == 0x221 and switches_up(window) == 1 << 6
    app.run("close")
    assert app.machine is None and window.model.connected
    assert window.connect_button.cget("text") == frame.DISCONNECT
    assert leds(window) == 0x221 and [segments(window, n) for n in range(6)] == list(DIGITS)


def test_backstep_undoes_a_write_to_the_displays(app, tmp_path):
    loaded(app, tmp_path, SHOW)
    window = connected(app)
    for _ in range(4):
        app.run("step")
    assert segments(window, 0) == DIGITS[0]
    app.run("backstep")
    assert segments(window, 0) == 0
    app.run("step")
    assert segments(window, 0) == DIGITS[0]


def test_the_reset_button_switches_the_board_off(app, tmp_path):
    loaded(app, tmp_path, SHOW)
    window = connected(app)
    click_switch(window, 1)
    go_to_end(app)
    window.reset_button.invoke()
    assert [segments(window, n) for n in range(6)] == [0] * 6
    assert leds(window) == 0 and switches_up(window) == 0
    assert window.model.connected and window.model.board.switches == 0


def test_the_data_segment_shows_the_board_while_connected(app, tmp_path):
    loaded(app, tmp_path, SHOW)
    segment = app.execute.data_segment
    window = labsim(app)
    click_switch(window, 2)
    segment.show(LEDS)
    words = segment.words
    assert words[(SWITCHES - LEDS) // 4] == 0                   # not connected: not simulated
    window.connect_button.invoke()
    assert segment.words[(SWITCHES - LEDS) // 4] == 0b100
    click_switch(window, 4)
    assert segment.words[(SWITCHES - LEDS) // 4] == 0b10100
    press(window, 3)
    assert segment.words[(KEYS - LEDS) // 4] == 0b1000
    release(window, 3)
    assert segment.words[(KEYS - LEDS) // 4] == 0
    assert segment.words[(EDGE_CAPTURE - LEDS) // 4] == 0b1000
    window.reset_button.invoke()
    assert segment.words[(EDGE_CAPTURE - LEDS) // 4] == 0
    click_switch(window, 0)
    window.close()                                              # no longer connected
    assert segment.words[(SWITCHES - LEDS) // 4] == 0


def test_the_data_segment_highlights_the_board_word_a_step_wrote(app, tmp_path):
    loaded(app, tmp_path, SHOW)
    connected(app)
    segment = app.execute.data_segment
    segment.show(LEDS)
    for _ in range(4):
        app.run("step")                             # STR R2, [R0, #0x20]
    assert segment.words[(HEX3_HEX0 - LEDS) // 4] == 0x4F5B063F
    assert segment._row(1).cell_backgrounds == {"0": CHANGED}       # 0xff200020


def test_the_tooltips(app):
    window = labsim(app)
    assert window.switch_tip.text == SWITCH_TIP and window.switch_tip.widget is window.switches
    assert [tip.text for tip in window.key_tips] == [KEY_TIP] * 4
    assert [tip.widget for tip in window.key_tips] == window.key_buttons


def test_a_press_hides_the_tooltip(app, hidden_windows, monkeypatch):
    """The keys' and the switches' own bindings of the mouse button come before the
    tooltip's, which would hide it: they hide it themselves."""
    window = labsim(app)
    for tip, act in ((window.key_tips[2], lambda: press(window, 2)),
                     (window.switch_tip, lambda: click_switch(window, 4))):
        monkeypatch.setattr(tip.widget, "winfo_ismapped", lambda: True)
        tip.show()
        assert hidden_windows.shows(tip._window)
        act()
        assert tip._window is None


def test_the_help_text(app):
    window = labsim(app)
    text = paragraphs(window.HELP)
    for words in ("0xFF200000", "0xFF200020", "0xFF200030", "0xFF200040", "0xFF200050",
                  "0xFF200058", "0xFF20005C", "Edgecapture", "0x3F", "Backstep", "Reset",
                  "Connect to ARM", "not simulated"):
        assert words in text, words


def test_no_pictures_are_made_for_the_lab_sim(app, tmp_path):
    made = pictures(app.root)
    loaded(app, tmp_path, SHOW)
    window = connected(app)
    go_to_end(app)
    click_switch(window, 1)
    press(window, 0)
    release(window, 0)
    window.reset_button.invoke()
    window.close()
    assert pictures(app.root) == made


def test_refreshing_redraws_only_what_changed(app, tmp_path):
    loaded(app, tmp_path, SHOW)
    window = connected(app)
    configured = []
    for canvas in (window.displays, window.leds):
        itemconfigure = canvas.itemconfigure
        canvas.itemconfigure = (lambda item, itemconfigure=itemconfigure, **options:
                                configured.append(item) or itemconfigure(item, **options))
    go_to_end(app)
    lit_segments = sum(bin(digit).count("1") for digit in DIGITS)
    assert len(configured) == lit_segments + 3                  # and the three LEDs
    del configured[:]
    app.run("reset")
    go_to_end(app)                                              # the same values again
    assert configured == []
