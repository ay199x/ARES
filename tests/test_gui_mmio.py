# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Keyboard and Display MMIO Simulator's window: the display, the keyboard area, Reset,
Font... and what survives Assemble, Reset and closing the program's file."""

import time
from types import SimpleNamespace

import pytest
from conftest import lay_out, native, press_key, pump, use_test_clipboard
from test_gui_assemble import assemble
from test_gui_look import (RETURN_KEYS, all_buttons, check_return_presses_the_framed_button,
                           framed, move_focus, tab, tab_cycle, traversal)
from test_gui_run import ECHO, READ_INT, go_to_end, loaded, run_io, run_until, type_line
from test_responsiveness import pictures

from ares.gui.tools import mmio
from ares.gui.tools.mmio import COLUMNS, KEYBOARD_ROWS, LIMIT, ROWS, KeyboardDisplayWindow
from ares.runner import State
from ares.gui.tools.frame import paragraphs

PRINT = """\
        .data
text:   .asciz  "Hi\\n"
        .global _start
        .text
_start: LDR     R0, =0xFF201000
        LDR     R1, =text
next:   LDRB    R2, [R1], #1
        CMP     R2, #0
        BEQ     done
        STRB    R2, [R0]
        B       next
done:   SVC     #10
"""
GRID = """\
        .global _start
        .text
_start: LDR     R0, =0xFF201000
        MOV     R1, #'x'
        STRB    R1, [R0]
        MOV     R1, #12         @ form feed: clears the display
        STRB    R1, [R0]
        MOV     R1, #'A'
        STRB    R1, [R0]
        LDR     R1, =0x00300207 @ bell: column 3, row 2
        STR     R1, [R0]
        MOV     R1, #'O'
        STRB    R1, [R0]
        MOV     R1, #'K'
        STRB    R1, [R0]
        SVC     #10
"""
LINES = """\
        .global _start
        .text
_start: LDR     R0, =0xFF201000
        MOV     R2, #20
again:  MOV     R1, #'L'
        STRB    R1, [R0]
        MOV     R1, #'\\n'
        STRB    R1, [R0]
        SUBS    R2, R2, #1
        BNE     again
        SVC     #10
"""
MANY = """\
        .data
line:   .asciz  "The quick brown fox jumps over the lazy dog\\n"
        .global _start
        .text
_start: LDR     R0, =0xFF201000
        LDR     R3, =3000
again:  LDR     R1, =line
next:   LDRB    R2, [R1], #1
        CMP     R2, #0
        BEQ     done
        STRB    R2, [R0]
        B       next
done:   SUBS    R3, R3, #1
        BNE     again
        SVC     #10
"""
LONG_LINE = """\
        .global _start
        .text
_start: LDR     R0, =0xFF201000
        LDR     R2, =60000
        MOV     R1, #'x'
again:  STRB    R1, [R0]
        SUBS    R2, R2, #1
        BNE     again
        SVC     #10
"""


def tool(app):
    """Open the tool (or bring it to the front); returns its window."""
    app.run("tool_mmio")
    return app.tool_windows["tool_mmio"]


def connected(app):
    window = tool(app)
    window.connect_button.invoke()
    assert window.model.connected
    return window


def key(window, char, state=0):
    """Type char in the keyboard area."""
    return window._key(SimpleNamespace(char=char, state=state))


def shown(text):
    return text.get("1.0", "end-1c")


def bells(window):
    rings = []
    window.keyboard.bell = lambda: rings.append(1)
    return rings


def test_the_tool_opens_from_the_menu(app, hidden_windows):
    assert app.is_enabled("tool_mmio")
    menu, index = app._menu_items["tool_mmio"]
    menu.invoke(index)
    window = app.tool_windows["tool_mmio"]
    assert isinstance(window, KeyboardDisplayWindow) and hidden_windows.shows(window.window)
    assert window.window.title() == "Keyboard and Display MMIO Simulator"
    assert list(all_buttons(window.window)) == ["Font...", "Connect to ARM", "Reset", "Close"]
    content = window.window.winfo_children()[0]
    boxes = [child for child in content.pack_slaves()[0].winfo_children()
             if child.winfo_class() == "TLabelframe"]
    assert [box.cget("text") for box in boxes] == [mmio.DISPLAY_TITLE, mmio.KEYBOARD_TITLE]
    assert (window.display.cget("width"), window.display.cget("height")) == (COLUMNS, ROWS)
    assert (window.keyboard.cget("width"), window.keyboard.cget("height")) == (
        COLUMNS, KEYBOARD_ROWS)
    assert window.font.actual() == app.pane_font.actual()          # Run I/O's font
    assert window.status.cget("text") == f"Area {COLUMNS} x {ROWS}"
    assert window.tips[window.reset_button].text == mmio.RESET_TIP
    assert window.font_tip.text == mmio.FONT_TIP
    assert hidden_windows.focus is window.connect_button


@pytest.mark.parametrize("sequence", RETURN_KEYS)
def test_return_presses_the_framed_button_font_included(app, sequence):
    """Return presses the button that has the focus, Font... too, else Connect; in the
    keyboard area it is a key for the program (test_return_tab_and_backspace)."""
    window = tool(app)
    buttons = all_buttons(window.window)
    assert framed(buttons) == ["Connect to ARM"]
    widgets = [buttons[label] for label in ("Font...", "Close", "Reset")]
    check_return_presses_the_framed_button(
        buttons, widgets + [window.display, buttons["Connect to ARM"]], [], sequence)


def test_no_button_has_the_frame_while_the_keyboard_area_has_the_focus(app):
    """Return there is a key for the program and presses no button
    (test_return_tab_and_backspace)."""
    window = tool(app)
    buttons = all_buttons(window.window)
    move_focus(None, window.keyboard)
    assert framed(buttons) == []
    move_focus(window.keyboard, window.display)
    assert framed(buttons) == ["Connect to ARM"]
    move_focus(window.display, window.font_button)
    assert framed(buttons) == ["Font..."]


def test_tab_leaves_the_display(app):
    """Tab never goes into the display, which takes no keys, but a click does: Tab and
    Shift+Tab then move on from it. In the keyboard area Tab is a key for the program."""
    window = tool(app)
    native(window.window)
    assert window.display not in tab_cycle(window.connect_button)
    with traversal(window.display):
        assert tab(window.display) is window.font_button
        assert tab(window.display, back=True) is window.close_button


def test_keys_go_to_the_program_and_its_echo_to_the_display(app, tmp_path):
    loaded(app, tmp_path, ECHO)
    window = connected(app)
    app.run("go")
    run_until(app, lambda: app.machine.pc > 4)              # polling the JTAG UART
    for char in "hi.":
        assert key(window, char) == "break"
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert shown(window.display) == "hi." and shown(window.keyboard) == "hi."
    assert run_io(app) == "hi.\n-- program is finished running --\n"   # Run I/O shows it too


def test_keys_need_the_tool_connected_and_a_program_that_takes_them(app, tmp_path):
    window = tool(app)
    rings = bells(window)
    assert key(window, "a") == "break"                      # not connected
    window.connect_button.invoke()
    key(window, "b")                                        # no program
    assert len(rings) == 2 and shown(window.keyboard) == ""
    loaded(app, tmp_path, READ_INT)
    key(window, "4")                                        # before Go: waits for the program
    assert app.machine.console.pending() == 1 and shown(window.keyboard) == "4"
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    assert app.messages.run_io.get("input", "end-1c") == "4"    # the start of the line read
    key(window, "5")                                        # a read waits: type in Run I/O
    assert len(rings) == 3 and shown(window.keyboard) == "4"
    type_line(app, "1")
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert app.machine.reg(0) == 42
    key(window, "6")                                        # the program has ended
    assert len(rings) == 4
    app.run("reset")
    window.connect_button.invoke()                          # disconnected
    key(window, "7")
    assert len(rings) == 5 and shown(window.keyboard) == "4"
    assert app.machine.console.pending() == 0


def test_return_tab_and_backspace(app, tmp_path):
    loaded(app, tmp_path, ECHO)
    window = connected(app)
    pressed = []
    window.connect_button.configure(command=lambda: pressed.append(1))
    for sequence in ("<Key-Return>", "<Key-KP_Enter>"):
        press_key(window.keyboard, sequence)
    key(window, "\t")
    key(window, "a")
    key(window, "\b")                       # sent, and the area takes the a away
    assert pressed == []                    # Return typed: it did not press Connect
    assert app.machine.console.take_pending() == b"\n\n\ta\b"
    assert shown(window.keyboard) == "\n\n\t"


@pytest.mark.parametrize("state, sent", [(0, True), (0x4, False), (0x20004, True)])
def test_keys_with_a_shortcut_modifier_are_left_to_the_window(app, tmp_path, monkeypatch,
                                                             state, sent):
    loaded(app, tmp_path, ECHO)
    window = connected(app)
    monkeypatch.setattr(window, "windowing_system", "win32")
    assert (key(window, "f", state) == "break") is sent      # AltGr+F is a character
    assert key(window, "f", 0x20000) is None                # Alt+F
    assert key(window, "") is None                          # arrows, F5
    assert key(window, "\x7f") is None                      # Delete
    assert key(window, "\x1b") is None                      # Escape closes the tool
    assert key(window, "\ud83d") is None                    # half of a surrogate pair
    assert app.machine.console.pending() == (1 if sent else 0)


def test_escape_closes_the_tool(app, tmp_path):
    loaded(app, tmp_path, ECHO)
    window = connected(app)
    press_key(window.keyboard, "<Key-Escape>")
    assert window.window is None and not app.machine.observers.active


def test_paste_types_the_clipboard(app, tmp_path):
    use_test_clipboard(app.root)
    app.root.clipboard_append("ok.")
    loaded(app, tmp_path, ECHO)
    window = connected(app)
    app.run("go")
    press_key(window.keyboard, "<<Paste>>")
    run_until(app, lambda: app.runner.state is State.FINISHED)
    assert shown(window.display) == shown(window.keyboard) == "ok."


def test_a_form_feed_and_a_bell_on_the_display(app, tmp_path):
    loaded(app, tmp_path, GRID)
    window = connected(app)
    after = {3: "x", 5: "", 7: "A"}
    for number in range(1, 8):
        app.run("step")
        if number in after:
            assert shown(window.display) == after[number], number
    go_to_end(app)
    lines = shown(window.display).split("\n")
    assert len(lines) == ROWS and lines[2] == "   OK" + " " * (COLUMNS - 5)
    assert all(line == " " * COLUMNS for index, line in enumerate(lines) if index != 2)
    assert window.status.cget("text") == f"Cursor (5, 2), area {COLUMNS} x {ROWS}"
    assert run_io(app).startswith("x\x0cA\x07OK")


def test_the_areas_keep_their_text_across_reset_backstep_assemble_and_close(app, tmp_path):
    loaded(app, tmp_path, PRINT)
    window = connected(app)
    key(window, "k")
    go_to_end(app)
    assert shown(window.display) == "Hi\n"
    app.run("reset")                                        # Reset, F12
    assert shown(window.display) == "Hi\n" and shown(window.keyboard) == "k"
    for _ in range(6):                                      # up to the STRB of "H"
        app.run("step")
    app.run("backstep")
    assert shown(window.display) == "Hi\nH"
    assemble(app)
    assert window.model.connected and window.model.machine is app.machine
    go_to_end(app)
    assert shown(window.display) == "Hi\nHHi\n"
    app.run("close")
    assert app.machine is None and window.model.connected and window.model.machine is None
    assert shown(window.display) == "Hi\nHHi\n" and shown(window.keyboard) == "k"
    assert window.connect_button.cget("text") == "Disconnect from ARM"


def test_reset_clears_both_areas(app, tmp_path, hidden_windows):
    loaded(app, tmp_path, GRID)
    window = connected(app)
    key(window, "x")
    go_to_end(app)
    assert window.status.cget("text").startswith("Cursor")
    window.reset_button.invoke()
    assert shown(window.display) == shown(window.keyboard) == ""
    assert window.status.cget("text") == f"Area {COLUMNS} x {ROWS}"
    assert window.model.connected and hidden_windows.focus is window.keyboard


def test_close_disconnects(app, tmp_path):
    loaded(app, tmp_path, PRINT)
    window = connected(app)
    window.close_button.invoke()
    assert window.window is None and not window.model.connected
    assert not app.machine.observers.active
    again = tool(app)
    assert again is not window and not again.model.connected and shown(again.display) == ""


def test_the_font_dialog(app):
    window = tool(app)
    window.font_button.invoke()
    dialog = window.font_dialog
    assert dialog.window.title() == "Font"
    assert str(dialog.window.wm_transient()) == str(window.window)
    rings = []
    dialog.window.bell = lambda: rings.append(1)
    family = next(name for name in dialog.families if name != window.font.cget("family"))
    dialog.family.set(family)
    dialog.size.set("200")
    dialog.ok()                                             # refused: the dialog stays
    assert dialog.window is not None and dialog.status.cget("text") and rings
    dialog.size.set("14")
    assert dialog.preview_font.cget("size") == 14
    press_key(dialog.family_box, "<Key-Return>")            # OK
    assert dialog.window is None
    assert (window.font.cget("family"), window.font.cget("size")) == (family, 14)
    for text in (window.display, window.keyboard):
        assert str(text.cget("font")) == window.font.name
    assert (window.display.cget("width"), window.display.cget("height")) == (COLUMNS, ROWS)
    assert app.pane_font.cget("size") != 14                 # Run I/O keeps its font
    window.font_button.invoke()
    window.font_dialog.size.set("20")
    press_key(window.font_dialog.window, "<Key-Escape>")    # Cancel
    assert window.font_dialog.window is None and window.font.cget("size") == 14


def test_the_help_text(app):
    window = tool(app)
    text = paragraphs(window.HELP)
    for words in ("0xFF201000", "0xFF201004", "RVALID", "form feed (12) clears it",
                  "A bell (7) moves", "bits 31-20", "64 columns and 16 rows",
                  "Reset clears the display and the keyboard area", "ARES has no interrupts",
                  "100,000", "CPUlator"):
        assert words in text, words
    assert "\n\n" in text and "keyboard\narea" not in text      # paragraphs wrap


def test_no_pictures_are_made_for_the_tool(app, tmp_path):
    made = pictures(app.root)
    loaded(app, tmp_path, ECHO)
    window = connected(app)
    app.run("go")
    key(window, ".")
    run_until(app, lambda: app.runner.state is State.FINISHED)
    window.font_button.invoke()
    window.font_dialog.cancel()
    window.reset_button.invoke()
    window.close()
    assert pictures(app.root) == made


def test_refreshing_shows_only_what_changed(app, tmp_path):
    loaded(app, tmp_path, PRINT)
    window = connected(app)
    shows, clears = [], []
    show, clear = window.show, window.display.clear
    window.show = lambda: shows.append(1) or show()
    window.display.clear = lambda: clears.append(1) or clear()
    for _ in range(5):                                      # nothing written yet
        app.run("step")
    assert shows == []
    app.run("step")
    assert len(shows) == 1 and shown(window.display) == "H"
    for _ in range(5):
        app.run("step")
    assert shown(window.display) == "Hi" and clears == []   # added to, not written again


def test_the_scroll_bar_shows_only_while_the_text_does_not_fit(app, tmp_path):
    loaded(app, tmp_path, LINES)
    window = connected(app)
    assert lay_out(window.window)
    field = window.display.master
    width, height = field.winfo_reqwidth(), field.winfo_reqheight()
    assert not window.display_bar.winfo_manager() and not window.keyboard_bar.winfo_manager()
    go_to_end(app)
    pump(app.root)
    assert window.display_bar.winfo_manager() == "grid"
    assert (field.winfo_reqwidth(), field.winfo_reqheight()) == (width, height)
    window.reset_button.invoke()
    pump(app.root)
    assert not window.display_bar.winfo_manager()


@pytest.mark.serial
def test_each_refresh_is_quick_while_a_program_prints(app, tmp_path):
    """132,000 characters to the JTAG UART with the tool connected: each refresh after a
    slice takes in what the slice wrote (several thousand characters) in a few milliseconds
    (measured: 2 to 4 ms, at most 21 ms on a busy machine)."""
    loaded(app, tmp_path, MANY)
    window = connected(app)
    took = []
    refresh = window.refresh

    def timed():
        start = time.perf_counter()
        refresh()
        took.append(time.perf_counter() - start)
    window.refresh = timed
    app.run("go")
    run_until(app, lambda: app.runner.state is State.FINISHED, 60)
    assert len(took) >= 2 and max(took) < 0.1, (len(took), max(took))
    text = shown(window.display)
    assert text == window.model.display.text and len(text) <= LIMIT
    assert text.endswith("over the lazy dog\nThe quick brown fox jumps over the lazy dog\n")
    assert run_io(app).endswith("lazy dog\n-- program is finished running --\n")


def timed_refreshes(app, window):
    """The time each refresh of the window takes, Tk's layout of the text included."""
    took = []
    refresh = window.refresh

    def timed():
        start = time.perf_counter()
        refresh()
        app.root.update_idletasks()
        took.append(time.perf_counter() - start)
    window.refresh = timed
    return took


def test_a_long_line_is_quick_to_show(app, tmp_path):
    """60,000 characters without a line break: the display breaks them into lines of 64
    characters, as it shows them, so no refresh stalls the window. Tk lays out a long line
    that it wraps itself slowly, in a time that grows with the square of its length: as one
    line, a refresh takes up to 2.4 s and the run 6 s; broken, the run takes 0.2 s."""
    loaded(app, tmp_path, LONG_LINE)
    window = connected(app)
    assert lay_out(window.window)
    took = timed_refreshes(app, window)
    go_to_end(app, 60)
    assert app.runner.state is State.FINISHED
    assert len(took) >= 2 and max(took) < 0.2, (len(took), max(took))
    full, rest = divmod(60000, COLUMNS)
    assert shown(window.display).split("\n") == ["x" * COLUMNS] * full + ["x" * rest]


@pytest.mark.serial
def test_a_long_paste_is_quick_to_show(app, tmp_path):
    """The keyboard area breaks its lines in the same way: pasting 30,000 characters a
    second time takes 2.4 s when the area is one long line."""
    use_test_clipboard(app.root)
    app.root.clipboard_append("y" * 30000)
    loaded(app, tmp_path, ECHO)
    window = connected(app)
    assert lay_out(window.window)
    for _ in range(2):
        start = time.perf_counter()
        press_key(window.keyboard, "<<Paste>>")
        app.root.update_idletasks()
        assert time.perf_counter() - start < 0.2
    full, rest = divmod(60000, COLUMNS)
    assert shown(window.keyboard) == "\n".join(["y" * COLUMNS] * full + ["y" * rest])
    assert app.machine.console.pending() == 60000
