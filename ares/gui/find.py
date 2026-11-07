# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Find and Replace for the editor: search functions and a non-modal dialog.

Patterns are literal text, found by Python's re module in the widget's text.
Tk's own search is not used: without case, it reports matches a character or
two too early after letters that get shorter in UTF-8 when made lower case
(the Kelvin sign, the dotted capital I). The text is read without the
newline Tk keeps at the end, which is not part of the file.
"""

import re
import tkinter as tk
from tkinter import ttk

from .style import default_button
from .textedit import line_tags, one_undo_step, put_back_line_tags

_BEYOND_BMP = re.compile("[\U00010000-\U0010FFFF]")


def find(text, pattern, start="insert", match_case=False, whole_word=False, wrap=True):
    """The next match at or after start, as (first, last) indices, or None.

    With wrap, the search goes on from the top when there is no match below
    start. A whole word has no letter, digit or underscore just before or
    after it. An empty pattern matches nothing.
    """
    if not pattern:
        return None
    start = text.index(start)
    match = _search(text, pattern, match_case, whole_word, start)
    if match is None and wrap and start != "1.0":
        match = _search(text, pattern, match_case, whole_word, "1.0", int(start.split(".")[0]))
    return match


def replace_all(text, pattern, replacement, match_case=False, whole_word=False):
    """Replace every match as one undo step and return how many there were.

    All matches are found before anything changes, so inserted text is never
    searched again.
    """
    if not pattern:
        return 0
    source = text.get("1.0", "end-1c")
    spans = [match.span() for match in _compile(pattern, match_case, whole_word).finditer(source)]
    if not spans:
        return 0
    # One edit from the first match to the last: Tk undoes a step edit by
    # edit, moving the cursor and scrolling each time, so an edit per match
    # would make Undo take seconds in a long file. The edit takes the tags
    # off the text it covers, so the line tags (the editor's error markers)
    # go back on their lines afterwards, and the cursor back by its text.
    start, end = spans[0][0], spans[-1][1]
    pieces, position = [], start
    for first, last in spans:
        pieces += (source[position:first], replacement)
        position = last
    middle = "".join(pieces)
    first_index = _index(text, source, start)
    shift = replacement.count("\n") - pattern.count("\n")
    tags = _line_tags(text, source, spans, shift)
    line, column = (int(part) for part in text.index("insert").split("."))
    rest = source.split("\n", line - 1)[-1]            # the text from the cursor's line on
    cursor = len(source) - len(rest) + _position(text, rest, column)
    with one_undo_step(text):
        text.replace(first_index, _index(text, source, end), middle)
    # The last line the edit reaches ends with the newline after the last match.
    put_back_line_tags(text, int(first_index.split(".")[0]),
                       source.count("\n", 0, end) + 1 + len(spans) * shift, tags)
    moved = text.index("insert")
    if start <= cursor <= end:
        moved = _index(text, source[:start] + middle + source[end:],
                       _after_replacing(cursor, spans, len(replacement) - len(pattern)))
    # Set even where it stays, so that the editor marks the cursor's line again.
    text.mark_set("insert", moved)
    return len(spans)


def _search(text, pattern, match_case, whole_word, start, last_line=None):
    """The first match that starts at start or after it, on last_line at the latest.

    The text is read a few lines at a time, more each time, so that a search
    stops reading at the match: Tk takes long to read a line with thousands
    of colours.
    """
    regex = _compile(pattern, match_case, whole_word)
    newlines = pattern.count("\n")
    final_line = int(text.index("end-1c").split(".")[0])
    last_line = final_line if last_line is None else min(last_line, final_line)
    line, column = (int(part) for part in start.split("."))
    size = 1
    while line <= last_line:
        stop = min(line + size, last_line + 1)      # a match must start before line stop
        # Read on to the end of a match that starts on line stop - 1.
        source = text.get(f"{line}.0", f"{min(stop - 1 + newlines, final_line)}.end")
        match = regex.search(source, _position(text, source, column))
        if match is not None and source.count("\n", 0, match.start()) < stop - line:
            return tuple(_index(text, source, offset, line) for offset in match.span())
        line, column, size = stop, 0, 2 * size
    return None


def _compile(pattern, match_case, whole_word):
    """A regular expression that finds pattern as literal text."""
    expression = re.escape(pattern)
    if whole_word:
        # \w is a character that str.isalnum() accepts, or the underscore.
        expression = rf"(?<!\w){expression}(?!\w)"
    return re.compile(expression, 0 if match_case else re.IGNORECASE)


def _index(text, source, offset, first_line=1):
    """The widget's index for a position in source, the widget's text from first_line on."""
    line_start = source.rfind("\n", 0, offset) + 1
    line = first_line + source.count("\n", 0, line_start)
    column = offset - line_start
    if _BEYOND_BMP.search(source, line_start, offset) and _wide(text):
        column += len(_BEYOND_BMP.findall(source, line_start, offset))
    return f"{line}.{column}"


def _position(text, source, column):
    """The position in source of a column, as the widget counts columns, on source's first line."""
    if not (_BEYOND_BMP.search(source, 0, column) and _wide(text)):
        return column
    position = 0
    while column > 0:
        column -= 1 + (source[position] > "\uffff")
        position += 1
    return position


def _wide(text):
    """True when Tk counts a character beyond U+FFFF as two columns (Tk 8.6 does, Tk 9 not)."""
    return int(text.tk.call("string", "length", "\U00010000")) == 2


def _line_tags(text, source, spans, shift):
    """[(line, line tags)] of each line from the first match's to the last match's.

    The tags are those of textedit.line_tags(), such as the editor's error
    markers. line is the number of the line where the line starts once every
    match is replaced, each replacement adding shift newlines: a line that a
    replacement splits keeps its tags on its first part. A line whose newline
    is part of a match is joined to the next, and only the last one counts.
    """
    result = []
    line = source.count("\n", 0, spans[0][0]) + 1
    newline = source.rfind("\n", 0, spans[0][0])      # the one before the line, or -1
    before = done = 0       # matches that start before the line, that end before its newline
    while newline < spans[-1][1]:
        start, newline = newline + 1, source.find("\n", newline + 1)
        if newline < 0:
            newline = len(source)           # the newline Tk keeps at the end
        while before < len(spans) and spans[before][0] < start:
            before += 1
        while done < len(spans) and spans[done][1] <= newline:
            done += 1
        if done == len(spans) or newline < spans[done][0]:
            result.append((line + before * shift, line_tags(text, line)))
        line += 1
    return result


def _after_replacing(position, spans, growth):
    """Where a position in the text goes once every span has grown by growth characters.

    A position inside a span goes to the end of its replacement.
    """
    for first, last in spans:
        if first < position < last:
            position = last
    return position + growth * sum(last <= position for _, last in spans)


class FindReplaceDialog:
    """A Find and Replace window that stays open while the editor is used.

    get_text() returns the Text widget to work on, or None when no file is
    open. The window is made by the first show() and kept when closed.
    """

    def __init__(self, master, get_text):
        self.master = master
        self.get_text = get_text
        self.window = None

    def show(self, initial=""):
        """Open the dialog, or bring it to the front, ready to type what to find.

        initial, when given, replaces the text in Find.
        """
        if self.window is None:
            self._build()
        else:
            self.window.deiconify()
            self.window.lift()
        entry = self.find_entry
        if initial:
            entry.delete(0, "end")
            entry.insert(0, initial)
        entry.select_range(0, "end")
        entry.icursor("end")
        entry.focus_set()
        self.status.configure(text="")

    def close(self):
        """Hide the dialog, and give the text back the keyboard focus; show() brings it back."""
        if self.window is not None:
            self.window.withdraw()
            text = self.get_text()
            if text is not None:
                text.focus_set()

    # Window -------------------------------------------------------------

    def _build(self):
        parent = self.master.winfo_toplevel()
        window = self.window = tk.Toplevel(self.master)
        window.withdraw()                   # until it is in place
        window.title("Find and Replace")
        window.transient(parent)
        window.resizable(True, False)
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.bind("<Escape>", lambda event: self.close())
        window.bind("<Return>", self._return)
        window.bind("<KP_Enter>", self._return)

        body = ttk.Frame(window, padding="6p")
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        self.find_entry = self._entry(body, 0, "Find:")
        self.replace_entry = self._entry(body, 1, "Replace with:")

        self.match_case = tk.BooleanVar(master=window)
        self.whole_word = tk.BooleanVar(master=window)
        options = ttk.Frame(body)
        options.grid(row=2, column=1, sticky="w", pady="2p")
        ttk.Checkbutton(options, text="Match case", variable=self.match_case).pack(side="left")
        ttk.Checkbutton(options, text="Whole word", variable=self.whole_word).pack(
            side="left", padx=("8p", 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=("6p", 0))
        pushed = []
        for label, command in (("Find", self._find), ("Replace", self._replace),
                               ("Replace All", self._replace_all), ("Close", self.close)):
            pushed.append(ttk.Button(buttons, text=label, command=command))
            pushed[-1].pack(side="left", padx=("4p", 0))
        # Return presses the button that has the focus, else Find: it has the black frame.
        default_button(pushed[0], pushed)

        self.status = ttk.Label(body)
        self.status.grid(row=4, column=0, columnspan=2, sticky="w", pady=("4p", 0))

        # Near the top right of the main window, where it hides little of the editor.
        window.update_idletasks()
        margin = window.winfo_pixels("12p")
        x = parent.winfo_rootx() + max(0, parent.winfo_width() - window.winfo_reqwidth() - margin)
        window.geometry(f"+{x}+{parent.winfo_rooty() + margin}")
        window.deiconify()

    def _entry(self, parent, row, label):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, "4p"))
        # Not exported, so selecting text here never takes the selection (the
        # match to replace) away from the editor.
        entry = ttk.Entry(parent, width=30, exportselection=False)
        entry.grid(row=row, column=1, sticky="ew", pady="2p")
        return entry

    def _return(self, event):
        """Return presses the button that has the focus, else Find (ttk buttons ignore Return)."""
        if isinstance(event.widget, ttk.Button):
            event.widget.invoke()
        else:
            self._find()

    # Actions ------------------------------------------------------------

    def _find(self):
        text = self._text()
        if text is not None:
            self._find_next(text)

    def _replace(self):
        text = self._text()
        if text is None:
            return
        match = self._selected_match(text)
        if match is not None:
            with one_undo_step(text):
                text.delete(*match)
                text.mark_set("insert", match[0])
                text.insert("insert", self.replace_entry.get())
        self._find_next(text)

    def _replace_all(self):
        text = self._text()
        if text is None:
            return
        count = replace_all(text, self.find_entry.get(), self.replace_entry.get(),
                            *self._options())
        if count == 0:
            message = "No matches"
        elif count == 1:
            message = "1 replacement"
        else:
            message = f"{count} replacements"
        self.status.configure(text=message)

    def _text(self):
        """The Text widget to work on, or None after saying that no file is open."""
        text = self.get_text()
        if text is None:
            self.status.configure(text="No file is open")
        return text

    def _options(self):
        """Match case and Whole word, in the order find() takes them."""
        return self.match_case.get(), self.whole_word.get()

    def _find_next(self, text):
        """Select the next match after the cursor, or after a selected match."""
        selected = self._selected_match(text)
        start = selected[1] if selected is not None else "insert"
        match = find(text, self.find_entry.get(), start, *self._options())
        if match is None:
            self.status.configure(text="Not found")
            return
        first, last = match
        text.tag_remove("sel", "1.0", "end")
        text.tag_add("sel", first, last)
        text.mark_set("insert", last)
        text.see(last)          # the end first, so a match just past the right edge shows whole
        text.see(first)
        self.status.configure(text="")

    def _selected_match(self, text):
        """The selection as (first, last) when it is exactly a match, else None."""
        selection = tuple(text.index(index) for index in text.tag_ranges("sel"))
        pattern = self.find_entry.get()
        if len(selection) != 2 or not pattern or text.compare(selection[1], ">", "end-1c"):
            return None
        first, last = selection
        # Only the selection is read, with the character on each side for Whole word.
        before, selected = text.get(f"{first} -1c", first), text.get(first, last)
        around = before + selected + text.get(last, f"{last} +1c")
        match = _compile(pattern, *self._options()).match(around, len(before))
        if match is None or match.end() != len(before) + len(selected):
            return None
        return selection
