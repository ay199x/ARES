# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Editor colours: ARM assembly coloured as in CPUlator's ARMv7 editor.

The Highlighter keeps the tokenizer state at the start of every line. After
a change it tokenizes the changed lines again, then the lines after them
only while their start state differs from the stored one: a /* comment
opened or closed, or a macro defined or removed.
"""

import re

from ..tokens import (COMMENT, DIRECTIVE, LABEL_DEF, NUMBER, REGISTER, STRING, SYMBOL,
                      tokenize_line)

# Measured from CPUlator's ARMv7 editor. Mnemonics, shift names, symbols,
# character constants and punctuation keep the default black.
COLOURS = {"register": "#354BF5", "number": "#63A645", "label": "#2F5D16",
           "directive": "#3F7576", "comment": "#A1896A", "string": "#942F29"}
TAGS = tuple(COLOURS)

_TAG_OF = {REGISTER: "register", NUMBER: "number", LABEL_DEF: "label",
           DIRECTIVE: "directive", COMMENT: "comment", STRING: "string"}
_MACRO = re.compile(r"\.macro", re.IGNORECASE)
_BEYOND_BMP = re.compile("[\U00010000-\U0010FFFF]")


def line_spans(line, state=False, macros=frozenset()):
    """The coloured pieces of one line as [(tag, start, end)], and the state after it.

    state and macros are those of tokens.tokenize_line: whether the line
    starts inside a /* comment, and the names of the macros defined before it.
    """
    tokens, state = tokenize_line(line, state, macros)
    return [(_TAG_OF[t.kind], t.start, t.end) for t in tokens if t.kind in _TAG_OF], state


def _macros_after(line, state, macros):
    """The macro names known after a line, counted as tokens.tokenize does.

    A macro counts from its .macro line on; a .macro inside a comment defines nothing.
    """
    tokens, _ = tokenize_line(line, state, macros)
    return macros | {line[name.start:name.end].upper()
                     for directive, name in zip(tokens, tokens[1:])
                     if directive.kind == DIRECTIVE and name.kind == SYMBOL
                     and line[directive.start:directive.end].lower() == ".macro"}


def _tk_columns(line, spans):
    """spans with the columns Tk 8.6 uses, where a character beyond U+FFFF counts as two."""
    shift = [0]
    for char in line:
        shift.append(shift[-1] + (ord(char) > 0xFFFF))
    return [(tag, start + shift[start], end + shift[end]) for tag, start, end in spans]


class Highlighter:
    """Colours a TrackedText and keeps the colours up to date as the text changes."""

    def __init__(self, text, bold_font):
        self.text = text
        for tag, colour in COLOURS.items():
            text.tag_configure(tag, foreground=colour)
        self.set_bold_font(bold_font)
        text.tag_raise("sel")           # selected text stays readable
        # Tk 8.6 counts a character beyond U+FFFF as two columns, Tk 9 as one.
        self._wide = int(text.tk.call("string", "length", "\U00010000")) == 2
        self._starts = []               # (comment state, macro names) at the start of each line
        text.add_change_listener(self._changed)
        self.highlight_all()

    def set_bold_font(self, bold_font):
        """Show label definitions in bold_font, a tkinter.font.Font."""
        self._bold_font = bold_font     # Tk deletes a named font once Python lets go of it
        self.text.tag_configure("label", font=bold_font)

    def highlight_all(self):
        """Colour the whole text again, for example after loading a file."""
        count = self.text.line_count()
        self._starts = [(False, frozenset())] + [None] * (count - 1)
        self._colour(1, count)

    def _changed(self, first, removed, added):
        """Forget the start states of the lines that were replaced, then colour the new ones."""
        self._starts[first:first + removed - 1] = [None] * (added - 1)
        self._colour(first, first + added - 1)

    def _colour(self, first, last):
        """Colour lines first..last, then each later line whose start state has changed."""
        starts = self._starts
        count = len(starts)
        ranges = {tag: [] for tag in TAGS}
        start = starts[first - 1]
        number = first
        for line in self._lines(first, last):
            state, macros = start
            spans, after = line_spans(line, state, macros)
            if self._wide and not line.isascii() and _BEYOND_BMP.search(line):
                spans = _tk_columns(line, spans)
            for tag, begin, end in spans:
                ranges[tag] += (f"{number}.{begin}", f"{number}.{end}")
            if _MACRO.search(line):
                macros = _macros_after(line, state, macros)
            start = (after, macros)
            if number == count or (number >= last and starts[number] == start):
                break
            starts[number] = start
            number += 1
        self._paint(first, number, ranges)

    def _lines(self, first, last):
        """The text of lines first..last, then of the lines after them in growing chunks."""
        count = len(self._starts)
        size = 32
        while first <= count:
            yield from self.text.get(f"{first}.0", f"{last}.end").split("\n")
            first, last = last + 1, min(count, last + size)
            size *= 2

    def _paint(self, first, last, ranges):
        """Replace the colour tags of lines first..last, with one Tcl call per tag for each."""
        text = self.text
        begin, end = f"{first}.0", f"{last + 1}.0"
        for tag in TAGS:
            text.tag_remove(tag, begin, end)
        for tag, indices in ranges.items():
            if indices:
                text.tag_add(tag, *indices)
