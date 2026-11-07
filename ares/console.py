# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Run I/O: what the program prints and the characters typed for it."""

import codecs

FINISHED = "-- program is finished running --"
FINISHED_DROPPED = "-- program is finished running (dropped off bottom) --"
FINISHED_STOPPED = "-- program is finished running (stopped) --"
FINISHED_ERROR = "-- program is finished running (runtime error) --"
NEWLINE = 10


class Console:
    """Collects program output as text and holds typed input bytes.

    With keep_text=False only the output not yet taken is kept (``text`` is
    then not available): a runner that passes the output on at once does not
    need it, and an endless print loop would otherwise fill the memory.
    """

    def __init__(self, keep_text=True):
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._keep_text = keep_text
        self._parts = []        # everything output so far
        self._new = []          # output not yet returned by take()
        self._at_line_start = True
        self._input = bytearray()
        self._start = 0             # first unread input byte
        self._scanned = 0           # no newline in _input[_start:_scanned]
        self._input_closed = False
        self.input_wanted = None    # called when the JTAG UART finds no input

    # Output -------------------------------------------------------------

    def _append(self, text):
        if text:
            if self._keep_text:
                self._parts.append(text)
            self._new.append(text)
            shown = text.replace("\x00", "")    # a zero byte shows nothing
            if shown:
                self._at_line_start = shown.endswith("\n")

    def write_bytes(self, data):
        """Output bytes from the program (UTF-8, decoded across calls)."""
        self._append(self._decoder.decode(bytes(data)))

    def write_text(self, text):
        self._flush_decoder()
        self._append(text)

    def line_ended(self):
        """The output shown ends with a line break now (a typed line was shown after it).

        The first bytes of a character still wait for the rest of it.
        """
        self._at_line_start = True

    def end_line(self, message):
        """Write a status line, such as the end-of-run message, on a line of its own."""
        self._flush_decoder()
        if not self._at_line_start:
            self._append("\n")
        self._append(message + "\n")

    def _flush_decoder(self):
        self._append(self._decoder.decode(b"", final=True))

    @property
    def text(self):
        """Everything output so far."""
        if not self._keep_text:
            raise RuntimeError("this console does not keep its output")
        if len(self._parts) > 1:
            self._parts[:] = ["".join(self._parts)]
        return self._parts[0] if self._parts else ""

    def take(self):
        """Output added since the previous call."""
        new = "".join(self._new)
        self._new.clear()
        return new

    def clear(self):
        self._decoder.reset()
        self._parts.clear()
        self._new.clear()
        self._at_line_start = True

    # Input --------------------------------------------------------------
    # Typed characters form one byte stream. The JTAG UART takes single bytes;
    # the read services take whole lines, so they wait until Enter is typed.

    def feed(self, text):
        """Add typed characters for the program to read (? for one UTF-8 cannot hold)."""
        self._input += text.encode("utf-8", "replace") if isinstance(text, str) else bytes(text)

    def clear_input(self):
        """Forget the typed input the program has not read (the program starts again)."""
        self._input.clear()
        self._start = self._scanned = 0

    def close_input(self):
        """No more input will come (end of a piped standard input)."""
        self._input_closed = True

    @property
    def input_closed(self):
        return self._input_closed

    def pending(self):
        """Number of input bytes waiting to be read."""
        return len(self._input) - self._start

    def take_pending(self):
        """Take the typed bytes not read yet (a line not finished), to show them for editing.

        The rest of a character the program has read only in part stays for it.
        """
        start = self._start
        while start < len(self._input) and 0x80 <= self._input[start] < 0xC0:
            start += 1
        data = bytes(self._input[start:])
        del self._input[start:]
        self._scanned = min(self._scanned, start)
        return data

    def peek_byte(self):
        """Next input byte without taking it (and without asking for input), or None."""
        return self._input[self._start] if self.pending() else None

    def read_byte(self):
        """Next input byte, or None when nothing is waiting."""
        if self.pending():
            return self._take(1)[0]
        if self.input_wanted is not None:
            self.input_wanted()
        return None

    def has_line(self):
        """True when read_line() can answer without waiting."""
        return self._input_closed or self._line_end() is not None

    def read_line(self):
        """Next line including its newline; None while it is still being typed.

        After close_input() the last line may lack its newline, and b"" means
        the input has ended.
        """
        end = self._line_end()
        if end is None:
            if not self._input_closed:
                return None
            end = len(self._input)
        return self._take(end - self._start)

    def read_bytes(self, count):
        """Up to count bytes from the current line (waits like read_line)."""
        if not self.has_line():
            return None
        end = self._line_end() or len(self._input)
        return self._take(min(count, end - self._start))

    def _line_end(self):
        """Index just after the next newline, or None. Each byte is searched once."""
        found = self._input.find(NEWLINE, max(self._scanned, self._start))
        if found < 0:
            self._scanned = len(self._input)
            return None
        self._scanned = found
        return found + 1

    def _take(self, size):
        data = bytes(self._input[self._start:self._start + size])
        self._start += size
        if self._start > 0x10000 and 2 * self._start > len(self._input):
            del self._input[:self._start]       # drop what has been read
            self._scanned = max(self._scanned - self._start, 0)
            self._start = 0
        return data
