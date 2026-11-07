# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Scroll bars that show only while the content does not fit.

The texts are laid out as on the screen (conftest.lay_out), so Tk redraws
them and calls their scroll commands by itself, and the event loop must go
idle within a bounded number of events (conftest.pump).
"""

from types import SimpleNamespace
from tkinter import font as tkfont
from tkinter import ttk

import pytest
from conftest import PROGRAMS, fixed_screen, lay_out, pump
from test_gui_assemble import assemble, open_source

from ares.gui import style
from ares.gui.app import PANE_FONT_SIZE
from ares.gui.messages import MESSAGES, RUN_IO, MessagesPane
from ares.gui.widgets import HidingBars, ReadOnlyText, bars_needed, line_spacing
from ares.settings import DEFAULT_FONT


def scroll_bars(text):
    """The vertical and horizontal scroll bars beside a text."""
    bars = {str(w.cget("orient")): w for w in text.master.winfo_children()
            if isinstance(w, ttk.Scrollbar)}
    return bars["vertical"], bars["horizontal"]


def bars(text):
    """(vertical, horizontal): which of a text's scroll bars are in the grid."""
    return tuple(bool(bar.winfo_manager()) for bar in scroll_bars(text))


def test_both_scroll_bars_are_decided_at_once():
    def needed(width, height):
        """The bars for contents of 100 x 50 pixels in a room of width x height (bars 10 thick)."""
        return bars_needed(lambda room: 50 <= room, lambda room: 100 <= room, width, height,
                           (10, 10))
    assert needed(100, 50) == (False, False)
    assert needed(110, 49) == (True, False)         # too high; beside the bar it is wide enough
    assert needed(100, 49) == (True, True)          # too high, and then too wide beside the bar
    assert needed(99, 60) == (False, True)
    assert needed(99, 50) == (True, True)
    # Each fits only without the other's bar, so neither is needed: the case that would
    # switch both bars on and off if each were decided alone.
    assert needed(109, 59) == (False, False)
    for width in range(85, 125):
        for height in range(35, 75):
            vertical, horizontal = needed(width, height)
            left = (width - 10 * vertical, height - 10 * horizontal)       # for the contents
            assert vertical == (50 > left[1]) and horizontal == (100 > left[0]), (width, height)


def hiding_text(area, width, height):
    """A read-only text with hiding scroll bars in a sunken frame, as in the message panes."""
    frame = area(width, height)
    page = style.sunken(ttk.Frame(frame))
    page.pack(fill="both", expand=True)
    font = tkfont.Font(root=frame, family=DEFAULT_FONT, size=PANE_FONT_SIZE)
    text = ReadOnlyText(page, font=font, wrap="none", padx=4, pady=2, borderwidth=0,
                        highlightthickness=0)
    yscroll = ttk.Scrollbar(page, orient="vertical", command=text.yview)
    xscroll = ttk.Scrollbar(page, orient="horizontal", command=text.xview)
    text.grid(row=0, column=0, sticky="nsew")
    yscroll.grid(row=0, column=1, sticky="ns")
    xscroll.grid(row=1, column=0, sticky="ew")
    page.rowconfigure(0, weight=1)
    page.columnconfigure(0, weight=1)
    return frame, text, HidingBars(text, yscroll, xscroll)


def test_a_text_shows_its_scroll_bars_only_while_its_contents_do_not_fit(area):
    frame, text, hiding = hiding_text(area, 600, 200)
    text.write("".join(f"line {k}\n" for k in range(40)))
    assert lay_out(frame.winfo_toplevel())
    assert bars(text) == (True, False)
    text.clear()
    assert pump(frame)
    assert bars(text) == (False, False)
    text.write("x" * 100)
    assert pump(frame)
    assert bars(text) == (False, True)
    text.write("".join(f"\nline {k}" for k in range(40)))
    assert pump(frame)
    assert bars(text) == (True, True)
    text.clear()
    assert pump(frame)
    assert bars(text) == (False, False)
    for k in range(3):
        text.write(f"line {k}\n")
    assert pump(frame)
    assert bars(text) == (False, False)


def test_the_bars_stay_as_they_are_until_the_text_has_a_size(tk_root):
    page = ttk.Frame(tk_root)                   # never placed: the window was never laid out
    text = ReadOnlyText(page)
    yscroll = ttk.Scrollbar(page, orient="vertical", command=text.yview)
    xscroll = ttk.Scrollbar(page, orient="horizontal", command=text.xview)
    text.grid(row=0, column=0, sticky="nsew")
    yscroll.grid(row=0, column=1, sticky="ns")
    xscroll.grid(row=1, column=0, sticky="ew")
    try:
        hiding = HidingBars(text, yscroll, xscroll)
        for command in ("yscrollcommand", "xscrollcommand"):
            text.tk.call(text.cget(command), "0.25", "0.75")
        # The commands set the bars' thumbs.
        assert [tuple(map(float, bar.get())) for bar in (yscroll, xscroll)] == [(0.25, 0.75)] * 2
        assert pump(tk_root)
        assert bars(text) == (True, True)
        hiding.schedule()
        job = hiding._pending
    finally:
        page.destroy()
    # A decision still to come goes with the text: it would call a command gone with it.
    assert job not in tk_root.tk.splitlist(tk_root.tk.call("after", "info"))


def test_tabs_and_wide_characters_are_measured_as_tk_lays_them_out(area):
    frame, text, hiding = hiding_text(area, 900, 200)
    assert lay_out(frame.winfo_toplevel())
    padx = text.winfo_pixels(text.cget("padx"))
    # Tk's stops: the n-th tab goes to the n-th stop, or a space on when the line is past it.
    for line in ("ab\tX", "abcdefgh\tX", "abcdefghij\tX", "a\tb\tX", "abcdefghijklmnopq\tb\tX",
                 "\t\tX", "éè\tX", "éabcdefghijk\t\tX", "计数X", "café au lait",
                 "abc\rdef\rX", "ab\r\tX", "a\x07b\x1b[31mcX",
                 "".join(map(chr, range(0x41, 0x7B))) + "éX"):       # many different characters
        text.clear()
        text.write(line)
        assert pump(frame)
        x, _, width, _ = text.bbox("1.end - 1c")
        assert hiding._width(line) == x - padx + width, line
        # Measured as it grows, a part at a time, it is as wide.
        text.clear()
        hiding.decide()
        for part in (line[:len(line) // 2], line[len(line) // 2:]):
            text.write(part)
            hiding.decide()
        assert hiding._measure() == (1, x - padx + width), line


def test_only_what_was_added_is_measured_until_the_widest_line_goes(area, monkeypatch):
    """Run I/O keeps up to a million characters: measuring them all whenever it scrolls, or
    whenever its oldest output is dropped, would hold the window up; and so would measuring
    the whole last line, which can be most of them, whenever the program adds to it."""
    frame, text, hiding = hiding_text(area, 600, 200)
    assert lay_out(frame.winfo_toplevel())
    measured = []
    extend = hiding._extend
    monkeypatch.setattr(hiding, "_extend",
                        lambda x, tabs, chars: measured.append(chars) or extend(x, tabs, chars))

    def decide():
        """The characters measured to decide the bars, as the parts they were measured in."""
        measured.clear()
        hiding.decide()
        return list(measured)
    text.write("x" * 200 + "\n" + "".join(f"line {k}\n" for k in range(1000)) + "y" * 100)
    assert len(decide()) == 1002 and bars(text) == (True, True)
    text.write("z\nlast")
    assert decide() == ["z", "last"]            # what the last line got, and the new one
    text.write("\tmore é")
    assert decide() == ["\tmore é"]
    assert decide() == [""]                     # nothing new
    drop = text.tk.call
    drop(text._original, "delete", "1.0", "1.0 + 2 chars")      # the widest line cut short
    assert len(decide()) == 1003
    drop(text._original, "delete", "1.0", "2.0")                # and dropped
    assert len(decide()) == 1002 and bars(text) == (True, True)    # the y line is the widest
    drop(text._original, "delete", "1.0", "4.0")                # three short lines dropped
    assert decide() == [""]
    drop(text._original, "delete", "998.0", "end")              # the y line and the last one
    assert len(decide()) == 997 and bars(text) == (True, False)
    text.clear()
    text.write("short")
    assert decide() == ["short"] and bars(text) == (False, False)


# The message panes ---------------------------------------------------------------------

def message_pane(area, width, height):
    frame = area(width, height)
    font = tkfont.Font(root=frame, family=DEFAULT_FONT, size=PANE_FONT_SIZE)
    pane = MessagesPane(frame, font, lambda target: None)
    pane.pack(fill="both", expand=True)
    assert lay_out(frame.winfo_toplevel())
    return frame, pane, font


def inner_size(text):
    """The text's size inside its padding: with no bar shown, the room of its lines."""
    return (text.winfo_width() - 2 * text.winfo_pixels(text.cget("padx")),
            text.winfo_height() - 2 * text.winfo_pixels(text.cget("pady")))


def test_lines_after_clear_that_fit_only_without_the_other_bar_settle(area):
    """From 'vertical bar only', Clear and new lines at once: the lines fitted only without
    the horizontal bar and the long one only without the vertical bar. Each bar decided from
    Tk's view of the lines on the screen switched the other on and off for ever."""
    frame, pane, font = message_pane(area, 700, 200)
    text = pane.messages
    char = font.measure("0")
    line_height = font.metrics("linespace") + sum(line_spacing(pane, font))
    width, height = inner_size(text)
    frame.configure(height=200 - height % line_height + 2)     # 2 pixels below the last line
    assert lay_out(frame.winfo_toplevel())
    width, height = inner_size(text)
    lines = height // line_height
    long = (width - char) // char       # the longest line that fits (with the cursor after it)
    across, down = scroll_bars(text)[0].winfo_reqwidth(), scroll_bars(text)[1].winfo_reqheight()
    assert (long + 1) * char > width - across and height % line_height == 2 < down
    for _ in range(2):
        pane.clear(text)
        for k in range(40):
            pane.write_message(f"line {k}")
        assert pump(frame)
        assert bars(text) == (True, False)
        pane.clear(text)
        for k in range(lines - 2):      # with the long line and the empty last one: all fit
            pane.write_message(f"short {k}")
        pane.write_message("x" * long)
        assert pump(frame, 3000), "the scroll bars switch each other on and off"
        assert bars(text) == (False, False)


@pytest.mark.parametrize("showing", [2, 6, 10, 14])
def test_a_long_bottom_line_shown_in_part_keeps_its_bar(area, showing):
    """The bar comes when a long line is the last row on the screen, shown in part; the text,
    now shorter, leaves that line off the screen and Tk's view of the lines left fits. The bar
    stays: were it to go, the line would come back, and so on without end."""
    frame, pane, font = message_pane(area, 1000, 220)
    text = pane.messages
    line_height = font.metrics("linespace") + sum(line_spacing(pane, font))
    for k in range(1, 41):
        pane.write_message("LONG " + "x" * 400 if k == 30 else f"line {k}")
    text.yview("1.0")
    assert pump(frame)
    _, height = inner_size(text)
    text.yview_moveto((29 * line_height + showing - height) / (41 * line_height))
    assert pump(frame, 3000), "the horizontal bar switches on and off"
    assert bars(text) == (True, True)


def test_the_horizontal_bar_stays_while_a_long_line_is_off_the_screen(area):
    frame, pane, font = message_pane(area, 700, 200)
    text = pane.run_io
    pane.show_run_io()
    pane.write_output("x" * 200 + "\n")
    assert pump(frame)
    assert bars(text) == (False, True)
    pane.write_output("".join(f"short {k}\n" for k in range(40)))
    assert pump(frame)
    assert text.xview() == (0.0, 1.0)           # Tk sees only the short lines on the screen
    assert bars(text) == (True, True)


def last_line_shown(text):
    """True when the text's last line is in view, all of it: the view is at the end."""
    line = text.dlineinfo("end - 1c")
    bottom = text.winfo_height() - text.winfo_pixels(text.cget("pady"))
    return line is not None and line[1] + line[3] <= bottom and text.yview()[1] == 1.0


@pytest.mark.parametrize("name", [MESSAGES, RUN_IO])
def test_the_newest_line_stays_in_view_when_the_horizontal_bar_comes(area, name):
    """The bar makes the text shorter, and Tk keeps the text's top line where it was: the
    newest line, such as the prompt a program waits at, slid under the bar."""
    frame, pane, font = message_pane(area, 700, 200)
    text, write = page_of(pane, name)
    for k in range(40):
        write(f"line {k}")
    assert pump(frame) and bars(text) == (True, False) and last_line_shown(text)
    write("x" * 300)                            # at once: a line wider than the pane,
    if name == RUN_IO:
        pane.write_output("Radius: ")           # and the prompt the program waits at
        pane.begin_line()
    else:
        write("newest")
    assert pump(frame) and bars(text) == (True, True)
    assert last_line_shown(text)


@pytest.mark.parametrize("at_end", [True, False])
def test_a_bar_that_comes_keeps_the_view_at_the_end_only_if_it_was(area, at_end):
    """The bar comes here because the pane gets narrower, below a long last line. The view
    moves only up or down: lines the user scrolled back to, or the start of that line, stay."""
    frame, pane, font = message_pane(area, 700, 200)
    text, write = page_of(pane, RUN_IO)
    char = font.measure("0")
    for k in range(40):
        write(f"line {k}")
    assert pump(frame) and bars(text) == (True, False)
    pane.write_output("y" * (inner_size(text)[0] // char - 3))     # it fits, just
    if not at_end:
        text.yview_moveto(0)
    assert pump(frame) and bars(text) == (True, False)
    frame.configure(width=700 - 6 * char)
    assert lay_out(frame.winfo_toplevel()) and bars(text) == (True, True)
    assert last_line_shown(text) if at_end else text.yview()[0] == 0.0
    assert text.xview()[0] == 0.0


def test_output_before_run_io_was_ever_shown_moves_its_view_only_up_or_down(area):
    """The first program's output comes as Run I/O is shown for the first time, before Tk has
    given its text a size. Tk scrolls the 1 x 1 pixel text sideways, past the start of the
    prompt, and the text does not keep that once it has its size."""
    frame, pane, font = message_pane(area, 700, 200)        # ARES Messages in front
    text = pane.run_io
    pane.show_run_io()
    assert text.winfo_width() == 1
    pane.write_output("".join(f"line {k}\n" for k in range(40)) + "x" * 300 + "\nNumber: ")
    pane.begin_line()
    assert pump(frame) and bars(text) == (True, True)
    assert text.xview()[0] == 0.0 and last_line_shown(text)


def test_a_bar_that_comes_and_goes_at_once_brings_no_end_back_later(area):
    """The text never got shorter: a later change of its size, after the user scrolled away
    from the end, keeps the lines the user scrolled to."""
    frame, text, hiding = hiding_text(area, 600, 200)
    text.write("".join(f"line {k}\n" for k in range(40)))
    assert lay_out(frame.winfo_toplevel()) and bars(text) == (True, False)
    text.write("x" * 300)
    text.see("end")
    hiding.decide()                             # the bar comes, with the view at the end,
    text.tk.call(text._original, "delete", "end - 301c", "end - 1c")
    hiding.decide()                             # and goes before the text got shorter
    assert pump(frame) and bars(text) == (True, False)
    text.yview_moveto(0)
    assert pump(frame)
    frame.configure(height=150)
    assert lay_out(frame.winfo_toplevel()) and text.yview()[0] == 0.0


def test_each_message_bar_goes_when_the_text_fits(area):
    frame, pane, font = message_pane(area, 700, 200)
    text = pane.run_io
    pane.show_run_io()
    assert pump(frame)
    assert bars(text) == (False, False)
    pane.write_output("".join(f"line {k}\n" for k in range(40)))
    assert pump(frame)
    assert bars(text) == (True, False)
    pane.clear(text)
    assert pump(frame)
    assert bars(text) == (False, False)
    pane.write_output("y" * 300)                # a line still being written
    assert pump(frame)
    assert bars(text) == (False, True)
    pane.clear(text)
    pane.write_output("z" * 10)
    assert pump(frame)
    assert bars(text) == (False, False)


def page_of(pane, name):
    """The text of a message pane's page, shown, and how a line is written to it."""
    if name == MESSAGES:
        pane.show_messages()
        return pane.messages, pane.write_message
    pane.show_run_io()
    return pane.run_io, lambda line: pane.write_output(line + "\n")


@pytest.mark.parametrize("name", [MESSAGES, RUN_IO])
def test_a_line_as_wide_as_the_text_has_its_bar_until_it_goes(area, name):
    """Tk calls no scroll command for a change that leaves its view of the lines as it was. A
    line as wide as the text fits that view, but not with the cursor after it: its bar goes
    with Clear and the output after it, and comes with nothing before the line."""
    frame, pane, font = message_pane(area, 700, 200)
    text, write = page_of(pane, name)
    assert pump(frame)
    char = font.measure("0")
    fit = inner_size(text)[0] // char       # as wide as the text

    def shows(*lines):
        """The bars once the page is cleared and the lines written at once."""
        pane.clear(text)
        for line in lines:
            write(line)
        assert pump(frame)
        return bars(text)
    assert shows("x" * (fit + 7)) == (False, True)
    assert shows("x" * fit) == (False, True) and text.xview() == (0.0, 1.0)
    assert shows() == (False, False)
    assert shows("x" * fit) == (False, True)            # after a page that showed no bar
    assert shows("short") == (False, False)
    assert shows("x" * (fit + 7)) == (False, True)
    wide = -(-font.measure("\r") // char)      # a carriage return, as wide as the font has it
    assert shows("x" * (fit - 1 - wide) + "\r") == (False, False)


def test_the_bars_follow_the_size_of_the_pane(area):
    """Tk's view of a line as wide as the text is the same one character wider (it fits):
    only the pane's new size decides."""
    frame, pane, font = message_pane(area, 700, 200)
    text = pane.messages
    char = font.measure("0")
    pane.write_message("x" * (inner_size(text)[0] // char))
    assert pump(frame) and bars(text) == (False, True)
    for width, shown in ((700 + char, False), (700, True)):
        frame.configure(width=width)
        assert lay_out(frame.winfo_toplevel())
        assert bars(text) == (False, shown) and text.xview() == (0.0, 1.0)


def test_typing_in_run_io_shows_and_hides_its_bars(area):
    """Each change below leaves Tk's view of the line as it was (it fits)."""
    frame, pane, font = message_pane(area, 700, 200)
    text, _ = page_of(pane, RUN_IO)
    assert pump(frame)
    fit = inner_size(text)[0] // font.measure("0")

    def type_key(char):
        """A key as Tk handles it: seen by the pane, then typed by the Text class's bindings."""
        pane._key(SimpleNamespace(char=char, state=0))
        if char == "\b":
            text.delete("insert - 1c")
        else:
            text.insert("insert", char)
    pane.begin_line()
    for char in "x" * (fit - 1):
        type_key(char)
    assert pump(frame) and bars(text) == (False, False)
    type_key("x")                   # as wide as the text
    assert pump(frame) and bars(text) == (False, True) and text.xview() == (0.0, 1.0)
    type_key("\b")
    assert pump(frame) and bars(text) == (False, False)
    pane.paste("y")
    assert pump(frame) and bars(text) == (False, True)
    pane.end_line()                 # the line taken away
    assert pump(frame) and bars(text) == (False, False)


def test_the_message_panes_show_scroll_bars_only_while_their_text_does_not_fit(make_app,
                                                                              monkeypatch):
    fixed_screen(monkeypatch)
    app = make_app()
    assert lay_out(app.root)
    pane = app.messages
    char = app.pane_font.measure("0")
    for name in (MESSAGES, RUN_IO):
        text, write = page_of(pane, name)
        assert pump(app.root)
        assert bars(text) == (False, False)
        for k in range(40):
            write(f"line {k}")
        assert pump(app.root)
        assert bars(text) == (True, False)
        write("x" * 300)
        assert pump(app.root)
        assert bars(text) == (True, True)
        assert (int(scroll_bars(text)[0].grid_info()["row"]),
                int(scroll_bars(text)[1].grid_info()["column"])) == (0, 1)
        pane.clear(text)
        assert pump(app.root)
        assert bars(text) == (False, False)
        write("x" * (inner_size(text)[0] // char))     # as wide as the text
        assert pump(app.root) and bars(text) == (False, True)
        pane.clear(text)
        assert pump(app.root) and bars(text) == (False, False)


def test_the_editor_keeps_both_scroll_bars_at_all_times(app):
    tab = app.editor.new_file()
    text = tab.text
    vertical, horizontal = scroll_bars(text)
    for option in ("yscrollcommand", "xscrollcommand"):
        text.tk.call(text.cget(option), "0.0", "1.0")   # everything shows
    assert vertical.winfo_manager() == horizontal.winfo_manager() == "grid"


def test_the_execute_tables_show_a_scroll_bar_only_while_their_rows_do_not_fit(app, tmp_path):
    open_source(app, tmp_path, (PROGRAMS / "circle.s").read_text())
    assemble(app)
    execute = app.execute
    for table in (execute.text_segment.table, execute.data_segment.table, execute.labels.table):
        rows = table.count
        assert rows > 1
        table.fit(rows * table.row_height)
        assert table.vscroll.winfo_manager() == ""
        table.fit((rows - 1) * table.row_height)
        assert table.vscroll.winfo_manager() == "grid"
