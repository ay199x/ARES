# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""TrackedText: change and cursor reports for every way the text can change."""

import random
import tkinter as tk

import pytest

from ares.gui.textedit import TrackedText, line_tags

TEXT = "first\nsecond\nthird"


class Recorder:
    """The reports of a TrackedText, and a copy of its lines kept from the reports alone."""

    def __init__(self, text):
        self.text = text
        self.lines = text.get("1.0", "end-1c").split("\n")
        self.changes = []
        self.moves = 0
        text.add_change_listener(self.changed)
        text.add_cursor_listener(self.moved)

    def changed(self, first, removed, added):
        self.changes.append((first, removed, added))
        new_lines = self.text.get(f"{first}.0", f"{first + added - 1}.end").split("\n")
        self.lines[first - 1:first - 1 + removed] = new_lines

    def moved(self):
        self.moves += 1

    def copy_matches(self):
        """True when every report was well formed and the copy equals the text."""
        return (all(removed >= 1 and added >= 1 for _, removed, added in self.changes)
                and self.lines == self.text.get("1.0", "end-1c").split("\n"))


@pytest.fixture(autouse=True)
def callback_errors(tk_root):
    """Fail the test on an exception inside a Tk callback, which Tk would only print.

    A test that expects some takes the list and clears it.
    """
    errors = []
    tk_root.report_callback_exception = lambda *exc_info: errors.append(exc_info)
    yield errors
    del tk_root.report_callback_exception
    if errors:
        raise errors[0][1]


@pytest.fixture
def text(tk_root):
    widget = TrackedText(tk_root, undo=True)
    widget.insert("1.0", TEXT)
    widget.edit_reset()
    yield widget
    widget.destroy()


@pytest.fixture
def recorder(text):
    return Recorder(text)


@pytest.fixture
def clipboard(tk_root):
    """A clipboard of the test's own for Tk's paste and cut bindings.

    The system clipboard stays as it was, whatever it holds, and no other
    program can get in the way.
    """
    tk_root.tk.eval("""
        rename ::clipboard ::saved_clipboard
        rename ::tk::GetSelection ::tk::saved_GetSelection
        set ::test_clipboard ""
        proc ::clipboard {option args} {
            switch -- $option {
                clear {set ::test_clipboard ""}
                append {append ::test_clipboard [lindex $args end]}
                get {return $::test_clipboard}
            }
        }
        proc ::tk::GetSelection {w {selection PRIMARY}} {return $::test_clipboard}
    """)
    yield tk_root
    tk_root.tk.eval("""
        rename ::clipboard {}
        rename ::tk::GetSelection {}
        rename ::saved_clipboard ::clipboard
        rename ::tk::saved_GetSelection ::tk::GetSelection
        unset ::test_clipboard
    """)


def run_event_loop(root):
    """Run mainloop() briefly; it would raise any error a Python command let out into Tcl."""
    root.after(1, root.quit)
    root.mainloop()


# Change reports ----------------------------------------------------------

@pytest.mark.parametrize("action, change, result", [
    (lambda t: t.insert("2.3", "XY"), (2, 1, 1), "first\nsecXYond\nthird"),
    (lambda t: t.insert("2.3", "X\nY\nZ"), (2, 1, 3), "first\nsecX\nY\nZond\nthird"),
    (lambda t: t.insert("1.0", "a\n", "tag", "b\nc", ()), (1, 1, 3),
     "a\nb\ncfirst\nsecond\nthird"),
    (lambda t: t.insert("end", "!"), (3, 1, 1), "first\nsecond\nthird!"),
    (lambda t: t.insert("end", "\nfourth"), (3, 1, 2), "first\nsecond\nthird\nfourth"),
    (lambda t: t.delete("2.1", "2.3"), (2, 1, 1), "first\nsond\nthird"),
    (lambda t: t.delete("2.1"), (2, 1, 1), "first\nscond\nthird"),
    (lambda t: t.delete("1.end"), (1, 2, 1), "firstsecond\nthird"),
    (lambda t: t.delete("1.2", "3.1"), (1, 3, 1), "fihird"),
    (lambda t: t.tk.call(str(t), "delete", "1.0", "1.1", "3.0", "3.2"), (1, 3, 3),
     "irst\nsecond\nird"),
    (lambda t: t.tk.call(str(t), "delete", "1.0", "1.1", "2.end"), (1, 3, 2),
     "irst\nsecondthird"),
    (lambda t: t.delete("2.3", "end"), (2, 2, 1), "first\nsec"),
    # Tk keeps the final newline and deletes the one before line 2 instead.
    (lambda t: t.delete("2.0", "end"), (1, 3, 1), "first"),
    (lambda t: t.delete("1.0", "end"), (1, 3, 1), ""),
    (lambda t: t.replace("1.2", "2.3", "Q\nR\nS"), (1, 2, 3), "fiQ\nR\nSond\nthird"),
    (lambda t: t.replace("2.0", "end", "X\nY"), (1, 3, 2), "firstX\nY"),
    # Tk accepts a subcommand abbreviated as far as it stays unambiguous.
    (lambda t: t.tk.call(str(t), "ins", "2.3", "X\nY\nZ"), (2, 1, 3),
     "first\nsecX\nY\nZond\nthird"),
    (lambda t: t.tk.call(str(t), "del", "1.2", "3.1"), (1, 3, 1), "fihird"),
    (lambda t: t.tk.call(str(t), "r", "1.2", "2.3", "Q\nR\nS"), (1, 2, 3),
     "fiQ\nR\nSond\nthird"),
], ids=["insert", "insert lines", "insert pieces", "insert at end", "insert lines at end",
        "delete in line", "delete one character", "delete newline", "delete across lines",
        "delete ranges", "delete ranges and one character", "delete to end",
        "delete lines to end", "delete all", "replace", "replace to end",
        "abbreviated insert", "abbreviated delete", "abbreviated replace"])
def test_change_report(text, recorder, action, change, result):
    action(text)
    assert recorder.changes == [change]
    assert text.get("1.0", "end-1c") == result
    assert recorder.copy_matches()


def test_empty_ranges_change_nothing(text, recorder):
    text.delete("2.2", "2.2")
    text.delete("2.2", "1.0")           # the second index first: nothing to delete
    text.replace("2.2", "2.2", "")
    text.delete("end")
    text.insert("2.2", "")
    assert text.get("1.0", "end-1c") == TEXT
    assert recorder.copy_matches()


def test_indices_are_read_before_the_change(text, recorder):
    text.tag_add("sel", "2.0", "3.2")
    text.delete("sel.first", "sel.last")
    text.mark_set("insert", "2.0")
    text.insert("insert", "A\nB")
    text.insert("@0,0", "Z")
    assert recorder.changes == [(2, 2, 1), (2, 1, 2), (1, 1, 1)]
    assert text.get("1.0", "end-1c") == "Zfirst\nA\nBird"


def test_deleting_the_empty_last_line(text, recorder):
    text.insert("end", "\n")
    text.delete("end-1c")
    assert recorder.changes == [(3, 1, 2), (3, 2, 1)]
    assert text.get("1.0", "end-1c") == TEXT


def test_backspace_and_delete_keys_join_lines(text, recorder):
    """The keys' own bindings delete one character: insert-1c and insert."""
    def press(key):
        text.tk.eval(text.tk.call("bind", "Text", key).replace("%W", str(text)))

    text.mark_set("insert", "2.0")
    press("<BackSpace>")
    text.mark_set("insert", "1.end")
    press("<Delete>")
    assert text.get("1.0", "end-1c") == "firstsecondthird"
    assert recorder.changes == [(1, 2, 1), (1, 2, 1)]


def test_typing(text, recorder):
    """A key press inserts through Tk's own procedure, which replaces a selection."""
    text.mark_set("insert", "3.2")
    text.tk.call("tk::TextInsert", str(text), "k")
    text.tag_add("sel", "1.1", "2.1")
    text.mark_set("insert", "1.3")
    text.tk.call("tk::TextInsert", str(text), "!")
    assert text.get("1.0", "end-1c") == "f!econd\nthkird"
    assert recorder.changes == [(3, 1, 1), (1, 2, 1), (1, 1, 1)]
    assert recorder.copy_matches()


def test_paste_and_cut(tk_root, text, recorder, clipboard):
    clipboard.clipboard_clear()
    clipboard.clipboard_append("P\nQ")
    text.mark_set("insert", "2.3")
    text.event_generate("<<Paste>>")
    assert text.get("1.0", "end-1c") == "first\nsecP\nQond\nthird"
    text.tag_add("sel", "1.1", "2.2")
    text.event_generate("<<Cut>>")
    assert text.get("1.0", "end-1c") == "fcP\nQond\nthird"
    assert clipboard.clipboard_get() == "irst\nse"
    assert recorder.changes == [(2, 1, 2), (1, 2, 1)]
    assert recorder.copy_matches()
    # On Windows and macOS the paste first tried to delete a selection, and
    # Tk caught the error; the event loop must not see it again.
    run_event_loop(tk_root)


def test_undo_and_redo(text, recorder):
    text.insert("2.3", "X\nY")
    text.edit_separator()
    text.delete("1.0", "2.0")
    recorder.changes.clear()
    text.edit_undo()
    assert text.get("1.0", "end-1c") == "first\nsecX\nYond\nthird"
    text.event_generate("<<Undo>>")
    assert text.get("1.0", "end-1c") == TEXT
    text.edit_redo()
    text.event_generate("<<Redo>>")
    assert text.get("1.0", "end-1c") == "secX\nYond\nthird"
    assert recorder.changes == [(1, 1, 2), (2, 2, 1), (2, 1, 2), (1, 2, 1)]
    assert recorder.copy_matches()


def test_reports_of_random_edits_rebuild_the_text(text, recorder):
    rng = random.Random(2026)
    pieces = ["x", "\n", "ab\ncd", "\n\n", ""]

    def anywhere():
        # Columns past the end of a line and the line after the last ("end") included.
        return f"{rng.randint(1, text.line_count() + 1)}.{rng.randint(0, 8)}"

    def inside():
        return f"{rng.randint(1, text.line_count())}.{rng.randint(0, 8)}"

    for _ in range(400):
        choice = rng.randrange(7)
        if choice == 0:
            text.insert(anywhere(), rng.choice(pieces))
        elif choice == 1:
            text.delete(anywhere())
        elif choice == 2:
            text.delete(anywhere(), anywhere())
        elif choice == 3:
            # Pairs inside the text: Tk 8.6.12 itself crashes on some deletes of
            # several ranges where one reaches "end" (delete 2.0 4.1 3.7 on "r\n\n").
            pairs = 2 * rng.randint(1, 3)
            text.tk.call(str(text), "delete", *(inside() for _ in range(pairs)))
        elif choice == 4:
            first, last = anywhere(), anywhere()
            if text.compare(first, ">", last):
                first, last = last, first
            text.replace(first, last, rng.choice(pieces))
        elif choice == 5 and text.edit("canundo"):
            text.edit_undo()
        elif choice == 6 and text.edit("canredo"):
            text.edit_redo()
        assert recorder.copy_matches()
    assert len(recorder.changes) > 300


def test_new_text_gets_only_the_tags_its_command_names(text):
    text.tag_add("t", "1.0", "3.0")
    text.insert("1.2", "X")                         # between two tagged characters
    text.insert("2.0", "A", ("u",), "B")
    text.replace("2.4", "2.5", "R")
    text.tk.call(str(text), "ins", "1.0", "Y")      # abbreviated
    assert [text.tag_names(index) for index in ("1.0", "1.3", "2.0", "2.1", "2.4")] == [
        (), (), ("u",), (), ()]
    assert text.tag_names("1.2") == ("t",)


def line_ends(text, tag="line"):
    """The lines whose newline has the tag."""
    return [line for line in range(1, text.line_count() + 1)
            if tag in text.tag_names(f"{line}.end")]


def test_tags_on_a_newline_stay_with_its_line(text):
    """Tags that mark a whole line, newline included, as the editor's error markers do."""
    text.tag_add("line", "2.0", "3.0")
    text.tag_add("sel", "2.end")
    text.insert("2.end", "\nnew")                   # at the end of the line
    assert [str(index) for index in text.tag_ranges("line")] == ["2.0", "3.0"]
    assert [str(index) for index in text.tag_ranges("sel")] == ["3.3", "4.0"]
    text.edit_undo()                                # a deletion back to the end of the line
    assert text.get("1.0", "end-1c") == TEXT
    assert [str(index) for index in text.tag_ranges("line")] == ["2.0", "3.0"]
    text.insert("2.3", "X\nY")                      # inside the line: as Tk leaves them
    assert line_ends(text) == [3] and "line" in text.tag_names("2.0")
    text.insert("2.0", "A\n")                       # at the start: the line moves down
    assert line_ends(text) == [4] and "line" not in text.tag_names("2.0")
    text.tag_add("line", "5.0", "end")              # the last line, with Tk's final newline
    text.insert("end", "\nlast")
    assert line_ends(text) == [4, 5]
    text.tag_add("line", "1.0", "2.0")
    text.delete("1.3", "2.end")                     # joins line 1 to the rest of line 2
    assert text.get("1.0", "1.end") == "fir" and line_ends(text) == [1, 3, 4]
    text.tag_remove("line", "1.0", "end")
    text.tag_add("line", "2.0", "3.0")
    text.delete("1.3", "2.end")                     # a line without the tags joined to one with
    assert line_ends(text) == []


def test_disabled_text_reports_nothing(text, recorder):
    text.configure(state="disabled")
    text.insert("1.0", "x")
    text.delete("1.0", "end")
    text.replace("1.0", "2.0", "y")
    assert text.get("1.0", "end-1c") == TEXT
    assert recorder.changes == []
    assert recorder.moves == 0


# Cursor reports and listener order ----------------------------------------

def test_cursor_reports(text, recorder):
    text.mark_set("insert", "2.1")
    assert recorder.moves == 1
    text.tk.call(str(text), "ma", "s", "insert", "2.2")     # abbreviated, as Tk allows
    assert recorder.moves == 2
    text.mark_set("other", "1.0")
    text.tk.call(str(text), "mark", "se", "other", "1.1")
    text.mark_unset("other")
    text.mark_gravity("insert", "left")
    text.see("insert")
    assert recorder.moves == 2
    text.insert("1.0", "x")
    assert recorder.moves == 3


def test_listeners_run_in_order_once_the_change_is_made(text):
    text.mark_set("insert", "1.0")
    calls = []
    text.add_change_listener(lambda *change: calls.append(("a", change, text.get("1.0", "1.4"))))
    text.add_change_listener(lambda *change: calls.append(("b", change)))
    text.add_cursor_listener(lambda: calls.append(("cursor", text.index("insert"))))
    text.insert("1.0", "new ")
    assert calls == [("a", (1, 1, 1), "new "), ("b", (1, 1, 1)), ("cursor", "1.4")]


def test_a_failing_listener_is_reported_and_the_others_still_run(text, callback_errors):
    calls = []

    def failing(*args):
        raise RuntimeError("listener")

    text.add_change_listener(failing)
    text.add_change_listener(lambda *change: calls.append(change))
    text.add_cursor_listener(failing)
    text.add_cursor_listener(lambda: calls.append("cursor"))
    text.insert("2.0", "x\n")
    text.mark_set("insert", "1.0")
    assert calls == [(2, 1, 2), "cursor", "cursor"]
    assert [type(error) for _, error, _ in callback_errors] == [RuntimeError] * 3
    callback_errors.clear()


# Failures, results and clean-up ------------------------------------------

@pytest.mark.parametrize("action", [
    lambda t: t.delete("sel.first", "sel.last"),
    lambda t: t.insert("nowhere", "x"),
    lambda t: t.replace("3.0", "1.0", "x"),
    lambda t: t.mark_set("insert", "nowhere"),
    # Tk would insert the text before it reads the malformed tag list after it.
    lambda t: t.tk.call(str(t), "insert", "2.0", "x\n", "{bad"),
    lambda t: t.tk.call(str(t), "insert", "2.0", "x\n", "", "y", "{bad"),
    lambda t: t.tk.call(str(t), "replace", "1.0", "2.0", "x\n", "{bad"),
    lambda t: t.tk.call(str(t), "replace", "3.0", "1.0", "x", "{bad"),
    lambda t: t.tk.call(str(t), "insert", "nowhere", "x", "{bad"),
    # Tk's messages name the widget.
    lambda t: t.tk.call(str(t), "insert", "1.0"),
    lambda t: t.tk.call(str(t), "mark", "set", "insert"),
    lambda t: t.tk.call(str(t)),
    lambda t: t.tk.call(str(t), "in", "1.0", "x"),
], ids=["delete without selection", "bad index", "replace backwards", "bad mark index",
        "bad tag list", "bad second tag list", "replace with a bad tag list",
        "replace backwards with a bad tag list", "bad index and bad tag list",
        "insert without text", "mark set without index", "no subcommand",
        "ambiguous subcommand"])
def test_failing_command_raises_tk_error_and_reports_nothing(tk_root, text, recorder, action):
    plain = tk.Text(tk_root)
    plain.insert("1.0", TEXT)
    with pytest.raises(tk.TclError) as expected:
        action(plain)
    plain.destroy()
    with pytest.raises(tk.TclError) as raised:
        action(text)
    assert (str(raised.value).replace(str(text), "<text>")
            == str(expected.value).replace(str(plain), "<text>"))
    assert recorder.changes == []
    assert recorder.moves == 0
    assert text.get("1.0", "end-1c") == TEXT
    run_event_loop(tk_root)


def test_commands_return_the_widget_result(text):
    count = tk.IntVar(master=text)
    assert text.search("ir", "1.0", count=count) == "1.1"
    assert count.get() == 2             # -count sets a variable in the caller's frame
    assert text.index("end") == "4.0"
    assert text.get("2.0", "2.end") == "second"
    assert text.tk.call(str(text), "insert", "1.0", "x") == ""
    assert "insert" in text.mark_names()


def test_line_count(text):
    assert text.line_count() == 3
    text.insert("end", "\n")
    assert text.line_count() == 4
    text.delete("1.0", "end")
    assert text.line_count() == 1


def test_destroy_removes_every_tcl_command(tk_root):
    def commands():
        """The Tcl commands, visible and hidden."""
        return {name for kind in (("info", "commands"), ("interp", "hidden"))
                for name in tk_root.tk.splitlist(tk_root.tk.call(*kind))}

    before = commands()
    paths = []
    for _ in range(100):
        text = TrackedText(tk_root, undo=True)
        text.add_change_listener(lambda *change: None)
        text.insert("1.0", "x\ny")
        paths.append(str(text))
        text.destroy()
    frame = tk.Frame(tk_root)
    inner = TrackedText(frame)
    paths.append(str(inner))
    frame.destroy()                     # takes the text with it
    inner.destroy()                     # a second destroy does no harm
    assert commands() == before
    frame = tk.Frame(tk_root)
    paths.append(str(TrackedText(frame)))
    tk_root.tk.call("destroy", str(frame))      # by Tcl alone, unknown to Python
    assert commands() == before
    frame.destroy()                     # and Python's destroy() after it does no harm
    assert commands() == before
    assert not set(paths) & commands()


def test_line_marks_count_wherever_they_are_on_a_line(tk_root):
    text = TrackedText(tk_root)
    try:
        text.insert("1.0", "ab\n \ncd\nef")
        text.line_marks = ("mark",)
        text.tag_add("mark", "1.0", "2.1")      # from line 1 over its newline into line 2
        text.tag_add("mark", "3.1", "3.2")      # one character inside line 3
        assert [sorted(line_tags(text, line)) for line in (1, 2, 3, 4)] == [
            ["mark"], ["mark"], ["mark"], []]
        text.line_marks = ()
        assert [sorted(line_tags(text, line)) for line in (1, 2, 3, 4)] == [
            ["mark"], [], [], []]
    finally:
        text.destroy()
