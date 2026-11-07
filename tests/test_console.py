# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Run I/O console: output decoding, end-of-run lines, input."""

import time

import pytest

from ares.console import Console


def test_utf8_bytes_join_across_writes():
    console = Console()
    for byte in "é!".encode("utf-8"):
        console.write_bytes([byte])
    assert console.text == "é!"


def test_end_line_starts_on_new_line():
    console = Console()
    console.write_text("abc")
    console.end_line("-- done --")
    assert console.text == "abc\n-- done --\n"


def test_end_line_after_newline_adds_no_blank_line():
    console = Console()
    console.write_text("abc\n")
    console.end_line("-- done --")
    assert console.text == "abc\n-- done --\n"


def test_end_line_on_empty_output():
    console = Console()
    console.end_line("-- done --")
    assert console.text == "-- done --\n"


def test_take_returns_only_new_output():
    console = Console()
    console.write_text("ab")
    assert console.take() == "ab"
    console.write_bytes(b"c")
    assert console.take() == "c"
    assert console.take() == ""
    assert console.text == "abc"


def test_input_bytes():
    console = Console()
    console.feed("hé")
    assert console.pending() == 3
    assert console.read_byte() == ord("h")
    assert console.read_byte() == 0xC3
    assert console.read_byte() == 0xA9
    assert console.read_byte() is None


def test_read_line_waits_for_enter():
    console = Console()
    console.feed("ab")
    assert not console.has_line() and console.read_line() is None
    console.feed("c\nde\n")
    assert console.has_line()
    assert console.read_line() == b"abc\n"
    assert console.read_line() == b"de\n"
    assert console.read_line() is None


def test_read_line_after_input_closed():
    console = Console()
    console.feed("last")
    console.close_input()
    assert console.has_line() and console.input_closed
    assert console.read_line() == b"last"
    assert console.read_line() == b""


def test_read_bytes_stops_at_end_of_line():
    console = Console()
    console.feed("hello\nworld\n")
    assert console.read_bytes(3) == b"hel"
    assert console.read_bytes(10) == b"lo\n"
    assert console.read_bytes(10) == b"world\n"
    assert console.read_bytes(10) is None


def test_jtag_reads_ask_for_input_when_empty():
    console = Console()
    calls = []
    console.input_wanted = lambda: calls.append(1)
    assert console.read_byte() is None
    console.feed(b"x")
    assert console.read_byte() == ord("x")
    assert calls == [1]


def test_peek_byte_takes_nothing_and_asks_for_nothing():
    console = Console()
    calls = []
    console.input_wanted = lambda: calls.append(1)
    assert console.peek_byte() is None
    console.feed(b"xy")
    assert console.peek_byte() == ord("x") and console.peek_byte() == ord("x")
    assert console.pending() == 2 and calls == []
    assert console.read_byte() == ord("x") and console.peek_byte() == ord("y")


def test_take_pending_takes_the_unread_bytes():
    console = Console()
    console.feed(b"ab")
    console.read_byte()
    console.feed(b"cd")
    assert console.take_pending() == b"bcd" and console.pending() == 0
    assert console.read_byte() is None


def test_take_pending_leaves_the_rest_of_a_character_read_in_part():
    console = Console()
    console.feed("\u00e9a")
    console.read_byte()                                 # the first of its two bytes
    assert console.take_pending() == b"a" and console.pending() == 1
    assert console.read_byte() == 0xA9


def test_a_zero_byte_after_a_newline_needs_no_line_break_before_the_end_line():
    console = Console()
    console.write_bytes(b"Hello\n\x00")
    console.end_line("-- done --")
    assert console.text == "Hello\n\x00-- done --\n"


def test_line_ended_keeps_the_start_of_a_character():
    console = Console()
    console.write_bytes(b"\xc3")
    console.line_ended()                                # Run I/O was cleared
    console.write_bytes(b"\xa9")
    console.end_line("-- done --")
    assert console.text == "\u00e9\n-- done --\n"


def test_feed_replaces_half_a_surrogate_pair():
    console = Console()
    console.feed("a\ud83db")
    assert console.take_pending() == b"a?b"


def test_line_ended_avoids_an_empty_line_before_the_end_line():
    console = Console()
    console.write_text("Number? ")
    console.line_ended()                    # the window showed the typed line and Enter
    console.end_line("-- end --")
    assert console.text == "Number? -- end --\n"


@pytest.mark.serial
def test_reading_a_long_line_in_pieces_is_linear():
    console = Console()
    console.feed(b"x" * 400_000 + b"\n" + b"y\n")
    start = time.perf_counter()
    pieces = []
    while True:
        piece = console.read_bytes(16)
        pieces.append(piece)
        if piece.endswith(b"\n"):
            break
    assert b"".join(pieces) == b"x" * 400_000 + b"\n"
    assert time.perf_counter() - start < 1.0
    assert console.read_line() == b"y\n" and console.pending() == 0


def test_console_without_history_keeps_only_untaken_output():
    console = Console(keep_text=False)
    console.write_bytes("é".encode("utf-8")[:1])
    console.write_bytes("é".encode("utf-8")[1:] + b"!")
    assert console.take() == "é!"
    console.end_line("-- end --")
    assert console.take() == "\n-- end --\n"
    assert console._parts == []
    with pytest.raises(RuntimeError):
        console.text
