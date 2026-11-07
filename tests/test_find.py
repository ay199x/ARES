# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Find and Replace: the search functions and the dialog."""

import time
import tkinter
from tkinter import ttk

import pytest
from conftest import press_key

from ares.gui.find import FindReplaceDialog, find, replace_all
from ares.gui.textedit import TrackedText


def put(text, content, insert="1.0"):
    """Give text new content, an empty undo history and the cursor at insert."""
    text.delete("1.0", "end")
    text.insert("1.0", content)
    text.edit_reset()
    text.edit_modified(False)
    text.mark_set("insert", insert)


def content(text):
    return text.get("1.0", "end-1c")


def selection(text):
    return tuple(text.index(index) for index in text.tag_ranges("sel"))


def can_undo(text):
    return bool(text.tk.call(text._w, "edit", "canundo"))


@pytest.fixture
def text(tk_root):
    widget = tkinter.Text(tk_root, undo=True)
    yield widget
    widget.destroy()


# find ----------------------------------------------------------------------

def test_find_returns_the_next_match_at_or_after_start(text):
    put(text, "MOV R0, #1\nMOV R1, #2\nMOV R2, #3")
    assert find(text, "MOV", "1.0") == ("1.0", "1.3")
    assert find(text, "MOV", "1.1") == ("2.0", "2.3")
    assert find(text, "R1", "1.0") == ("2.4", "2.6")


def test_find_starts_at_the_cursor_by_default(text):
    put(text, "B loop\nloop: B loop", insert="2.0")
    assert find(text, "loop") == ("2.0", "2.4")
    text.mark_set("insert", "2.1")
    assert find(text, "loop") == ("2.8", "2.12")


def test_find_wraps_round_to_the_top(text):
    put(text, "MOV R0, #1\nMOV R1, #2\nMOV R2, #3")
    assert find(text, "MOV", "3.1") == ("1.0", "1.3")
    assert find(text, "R0", "end") == ("1.4", "1.6")


def test_find_wraps_round_to_a_match_around_the_cursor(text):
    put(text, "LDR R0, =value")
    assert find(text, "value", "1.11") == ("1.9", "1.14")


def test_find_without_wrap_stops_at_the_end(text):
    put(text, "MOV R0, #1\nMOV R1, #2")
    assert find(text, "MOV", "2.1", wrap=False) is None
    assert find(text, "MOV", "1.1", wrap=False) == ("2.0", "2.3")


def test_find_ignores_case_unless_asked(text):
    put(text, "add ADD Add")
    assert find(text, "ADD", "1.0") == ("1.0", "1.3")
    assert find(text, "ADD", "1.0", match_case=True) == ("1.4", "1.7")
    assert find(text, "Add", "1.0", match_case=True) == ("1.8", "1.11")
    assert find(text, "aDd", "1.0", match_case=True) is None


def test_find_matches_mixed_case(text):
    put(text, "Loop: SUBS r0, R0, #1\n      BNE LoOp")
    assert find(text, "loop", "1.1") == ("2.10", "2.14")
    assert find(text, "R0", "1.0") == ("1.11", "1.13")
    assert find(text, "R0", "1.12") == ("1.15", "1.17")
    assert find(text, "R0", "1.0", match_case=True) == ("1.15", "1.17")


def test_whole_word_skips_matches_inside_longer_words(text):
    put(text, "_start start2 start")
    assert find(text, "start", "1.0") == ("1.1", "1.6")
    assert find(text, "start", "1.0", whole_word=True) == ("1.14", "1.19")


def test_whole_word_matches_at_line_start_and_end(text):
    put(text, "start: B start\nstart")
    assert find(text, "start", "1.0", whole_word=True) == ("1.0", "1.5")
    assert find(text, "start", "1.1", whole_word=True) == ("1.9", "1.14")
    assert find(text, "start", "1.10", whole_word=True) == ("2.0", "2.5")
    assert find(text, "start", "2.1", whole_word=True) == ("1.0", "1.5")


def test_whole_word_ends_at_punctuation_not_at_letters(text):
    put(text, "R1,R10 [R1] R1\u00e9")
    assert find(text, "R1", "1.0", whole_word=True) == ("1.0", "1.2")
    assert find(text, "R1", "1.1", whole_word=True) == ("1.8", "1.10")
    assert find(text, "R1", "1.9", whole_word=True) == ("1.0", "1.2")


def test_whole_word_without_a_whole_match_finds_nothing(text):
    put(text, "_start start2 restart")
    assert find(text, "start", "1.5", whole_word=True) is None


def test_find_takes_the_pattern_literally(text):
    put(text, "LDR R0, [R1, #-4]  @ R1+4 .*")
    assert find(text, "[R1", "1.0") == ("1.8", "1.11")
    assert find(text, "-4", "1.0") == ("1.14", "1.16")
    assert find(text, "R1+4", "1.0") == ("1.21", "1.25")
    assert find(text, ".*", "1.0") == ("1.26", "1.28")


def test_empty_pattern_finds_nothing(text):
    put(text, "MOV R0, #1")
    assert find(text, "", "1.0") is None
    assert replace_all(text, "", "x") == 0
    assert content(text) == "MOV R0, #1"


def test_wide_characters_keep_indices_right(text):
    source = "@ \U0001F600start start\U0001F600\nstart"
    put(text, source)
    first, last = find(text, "start", "1.0", whole_word=True)
    assert text.get(f"{first} - 1 chars", last) == "\U0001F600start"
    first, last = find(text, "start", last, whole_word=True)
    assert text.get(first, f"{last} + 1 chars") == "start\U0001F600"
    assert find(text, "start", last) == ("2.0", "2.5")
    assert replace_all(text, "start", "go") == 3
    assert content(text) == source.replace("start", "go")


# Letters whose lower case takes fewer bytes in UTF-8: the dotted capital I,
# the Kelvin, Ohm and Angstrom signs, the capital sharp s, L with middle
# tilde and H with hook.
@pytest.mark.parametrize("letter", "\u0130\u212a\u2126\u212b\u1e9e\u2c62\ua7aa")
def test_ignoring_case_finds_matches_where_they_are_after_any_letter(text, letter):
    source = f"@ {letter}{letter}: R0, r0\nMOV R0, #1"
    put(text, source)
    assert find(text, "r0", "1.0") == ("1.6", "1.8")
    assert find(text, "R0", "1.7") == ("1.10", "1.12")
    assert find(text, "r0", "1.0", whole_word=True) == ("1.6", "1.8")
    assert replace_all(text, "r0", "R5") == 3
    assert content(text) == f"@ {letter}{letter}: R5, R5\nMOV R5, #1"


def test_a_pattern_never_matches_the_newline_tk_keeps_at_the_end(text):
    put(text, "NOP\nNOP")
    assert find(text, "NOP\n", "1.1", wrap=False) is None
    assert find(text, "NOP\n", "1.1") == ("1.0", "2.0")
    assert replace_all(text, "NOP\n", "") == 1
    assert content(text) == "NOP"
    put(text, "a\nb")
    assert find(text, "\n", "1.2") == ("1.1", "2.0")
    assert replace_all(text, "\n", " ") == 1
    assert content(text) == "a b"


@pytest.mark.serial
def test_long_lines_take_time_in_proportion_to_their_length(text):
    started = time.perf_counter()
    put(text, "table: .word " + ", ".join(["0x00"] * 8000) + "\n")
    assert replace_all(text, "0x", "0X") == 8000
    assert find(text, "0", "1.0", whole_word=True) is None
    put(text, "@ " + "x" * 20000)
    assert find(text, "x", "1.0", whole_word=True) is None
    assert time.perf_counter() - started < 1


@pytest.mark.serial
def test_find_reads_no_further_than_the_match(text):
    # Tk takes seconds to read a line with thousands of colours.
    put(text, "loop: B loop\n" * 20 + "table: .word 0\nend: B end")
    reads = []
    get = text.get
    text.get = lambda first, last=None: reads.append(text.index(last or first)) or get(first, last)
    assert find(text, "loop", "1.2") == ("1.8", "1.12")
    assert find(text, "B", "3.0") == ("3.6", "3.7")
    assert max((int(index.split(".")[0]) for index in reads), default=0) < 21
    assert find(text, "end", "3.0") == ("22.0", "22.3")


# replace_all -----------------------------------------------------------------

def test_replace_all_replaces_every_match_and_counts_them(text):
    put(text, "MOV R0, #1\nADD R0, R0, R1\n")
    assert replace_all(text, "R0", "R2") == 3
    assert content(text) == "MOV R2, #1\nADD R2, R2, R1\n"


def test_replace_all_is_one_undo_step(text):
    put(text, "MOV R0, #1\nMOV R0, #2")
    # Tk would merge neighbouring replace commands into one undo step.
    text.replace("2.0", "2.4", "")
    assert replace_all(text, "R0", "R3") == 2
    text.replace("1.0", "1.0", "@ ")
    assert content(text) == "@ MOV R3, #1\nR3, #2"
    text.edit_undo()
    assert content(text) == "MOV R3, #1\nR3, #2"
    text.edit_undo()
    assert content(text) == "MOV R0, #1\nR0, #2"
    text.edit_undo()
    assert content(text) == "MOV R0, #1\nMOV R0, #2"


@pytest.mark.serial
def test_undo_after_replacing_thousands_of_matches_is_quick(text):
    source = "SUBS R0, R0, #1\n" * 1500
    put(text, source)
    assert replace_all(text, "R0", "R12") == 3000
    start = time.perf_counter()
    text.edit_undo()
    assert time.perf_counter() - start < 1
    assert content(text) == source


@pytest.mark.parametrize("autoseparators", [True, False])
def test_replace_all_keeps_the_autoseparators_setting(text, autoseparators):
    text.configure(autoseparators=autoseparators)
    put(text, "a b a")
    assert replace_all(text, "a", "c") == 2
    assert text.getboolean(text.cget("autoseparators")) is autoseparators


def test_replace_all_never_searches_the_replacement(text):
    put(text, "a ba\naa")
    assert replace_all(text, "a", "aa") == 4
    assert content(text) == "aa baa\naaaa"


def test_replace_all_whole_words_only(text):
    put(text, "R1 R10 R1, xR1 R1_ (R1)")
    assert replace_all(text, "R1", "R2", whole_word=True) == 3
    assert content(text) == "R2 R10 R2, xR1 R1_ (R2)"


def test_replace_all_can_match_case(text):
    put(text, "add ADD Add")
    assert replace_all(text, "add", "SUB", match_case=True) == 1
    assert content(text) == "SUB ADD Add"
    assert replace_all(text, "add", "SUB") == 2
    assert content(text) == "SUB SUB SUB"


def test_replace_all_without_a_match_changes_nothing(text):
    put(text, "MOV R0, #1")
    assert replace_all(text, "R9", "R2") == 0
    assert content(text) == "MOV R0, #1"
    assert not text.edit_modified()
    assert not can_undo(text)


def mark_lines(text, lines):
    """Tag whole lines, newline included, as the editor marks lines with errors."""
    for line in lines:
        text.tag_add("error_line", f"{line}.0", f"{line}.0 lineend +1c")


def marked(text):
    return [text.index(index) for index in text.tag_ranges("error_line")]


def test_replace_all_keeps_line_tags_on_lines_it_does_not_change(text):
    put(text, "MOV R0, #1\nMOVV R1, #2\nADDD R2, R2\nMOV R0, #3\n")
    mark_lines(text, [2, 3])
    assert replace_all(text, "R0", "R4") == 2
    assert marked(text) == ["2.0", "4.0"]


def test_replace_all_keeps_line_tags_on_changed_lines_and_spreads_none(text):
    put(text, "MOV R0, #1\nMOVV R1, #2\nADDD R2, R2\nMOV R0, #3\n")
    mark_lines(text, [1, 4])
    assert replace_all(text, "R0", "R12") == 2
    assert marked(text) == ["1.0", "2.0", "4.0", "5.0"]


def test_line_tags_move_with_their_lines(text):
    put(text, "NOP\nNOP\nMOVV R1, #2\nNOP\nADDD R2\n")
    mark_lines(text, [2, 3, 5])
    assert replace_all(text, "NOP\n", "") == 3
    assert content(text) == "MOVV R1, #2\nADDD R2\n"
    assert marked(text) == ["1.0", "3.0"]
    put(text, "MOV R0, #1\nADDD R2\nMOV R0, #2")
    mark_lines(text, [2])
    assert replace_all(text, "R0", "R0\n@") == 2
    assert content(text) == "MOV R0\n@, #1\nADDD R2\nMOV R0\n@, #2"
    assert marked(text) == ["3.0", "4.0"]


def test_a_line_that_a_replacement_splits_keeps_its_line_tags_on_its_first_part(text):
    put(text, "    MOV R0, R1 @ x\n    NOP\nB . @ x\n", insert="1.2")
    mark_lines(text, [1, 2])
    text.tag_add("current", "1.0", "2.0")           # the editor's current line
    assert replace_all(text, "@ x", "@ x\n    @ y") == 2
    assert content(text) == "    MOV R0, R1 @ x\n    @ y\n    NOP\nB . @ x\n    @ y\n"
    assert marked(text) == ["1.0", "2.0", "3.0", "4.0"]
    assert [text.index(index) for index in text.tag_ranges("current")] == ["1.0", "2.0"]
    put(text, "x\nB x", insert="2.0")
    mark_lines(text, [2])
    assert replace_all(text, "x", "\n") == 2         # also where the line starts with a match
    assert content(text) == "\n\nB \n"
    assert marked(text) == ["3.0", "4.0"]


def test_replace_all_sets_the_cursor_again_once_the_line_tags_are_back(tk_root):
    """The editor marks the cursor's line when the cursor is set, after the old line's tags."""
    text = TrackedText(tk_root, undo=True)

    def current_line():
        text.tag_remove("current", "1.0", "end")
        text.tag_add("current", "insert linestart", "insert lineend +1c")
    text.add_cursor_listener(current_line)
    put(text, "MOV R0, R1 @ x  \nNOP", insert="1.16")     # after the match
    assert replace_all(text, "@ x", "@ x\n@ y") == 1
    assert text.index("insert") == "2.5"
    assert [text.index(index) for index in text.tag_ranges("current")] == ["2.0", "3.0"]
    text.destroy()


def test_replace_all_leaves_the_cursor_by_its_text(text):
    put(text, "MOV R0, R0\n" * 100, insert="50.4")
    assert replace_all(text, "R0", "R12") == 200
    assert text.index("insert") == "50.4"
    put(text, "MOV R0, R0", insert="1.6")       # just after a match
    replace_all(text, "R0", "R12")
    assert text.index("insert") == "1.7"
    put(text, "MOV R0, R0", insert="1.9")       # inside a match
    replace_all(text, "R0", "")
    assert text.index("insert") == "1.6"
    put(text, "@\U0001F600 R0 R0")
    text.mark_set("insert", "1.0 lineend -2c")
    replace_all(text, "R0", "R12")
    assert text.index("insert") == text.index("1.0 lineend -3c")


# The dialog ------------------------------------------------------------------

@pytest.fixture
def window(tk_root):
    """A stand-in for the main window: the dialog's parent (hidden, as all test windows)."""
    top = tkinter.Toplevel(tk_root)
    yield top
    top.destroy()


@pytest.fixture
def editor(window):
    widget = tkinter.Text(window, undo=True, wrap="none", width=40, height=5)
    widget.pack()
    return widget


@pytest.fixture
def dialog(window, editor):
    return FindReplaceDialog(window, lambda: editor)


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def press(dialog, label):
    """Click the dialog's button or check box with this label."""
    found = [w for w in descendants(dialog.window)
             if isinstance(w, (ttk.Button, ttk.Checkbutton)) and str(w.cget("text")) == label]
    assert len(found) == 1, label
    found[0].invoke()


def type_into(entry, value):
    entry.delete(0, "end")
    entry.insert(0, value)


def status(dialog):
    return str(dialog.status.cget("text"))


def test_show_makes_one_window_and_reuses_it(dialog, window, hidden_windows):
    dialog.show()
    first = dialog.window
    assert first.title() == "Find and Replace"
    assert str(first.wm_transient()) == str(window)
    assert hidden_windows.shows(first)
    dialog.close()
    assert not hidden_windows.shows(first)
    dialog.show()
    assert dialog.window is first
    assert hidden_windows.shows(first)
    assert [w for w in window.winfo_children() if isinstance(w, tkinter.Toplevel)] == [first]


def test_show_puts_the_initial_text_in_find_selected_and_focused(dialog, hidden_windows):
    dialog.show("loop")
    entry = dialog.find_entry
    assert entry.get() == "loop"
    assert entry.selection_present()
    assert (entry.index("sel.first"), entry.index("sel.last")) == (0, 4)
    assert hidden_windows.focus is entry
    dialog.close()
    assert hidden_windows.focus is dialog.get_text()       # back to the text
    entry.selection_clear()
    dialog.show()
    assert entry.get() == "loop"
    assert entry.selection_present()


def test_find_selects_the_match_and_moves_the_cursor(dialog, editor):
    put(editor, "MOV R0, #1\nmov r1, #2\nB .")
    dialog.show("mov")
    press(dialog, "Find")
    assert selection(editor) == ("1.0", "1.3")
    assert editor.index("insert") == "1.3"
    assert status(dialog) == ""
    press(dialog, "Find")
    assert selection(editor) == ("2.0", "2.3")
    assert editor.index("insert") == "2.3"
    press(dialog, "Find")
    assert selection(editor) == ("1.0", "1.3")


def test_find_goes_on_after_a_selected_match(dialog, editor):
    put(editor, "MOV\nMOV\nMOV", insert="2.0")
    editor.tag_add("sel", "2.0", "2.3")
    dialog.show("MOV")
    press(dialog, "Find")
    assert selection(editor) == ("3.0", "3.3")


def test_find_says_when_nothing_is_found(dialog, editor):
    put(editor, "MOV R0, #1", insert="1.4")
    editor.tag_add("sel", "1.4", "1.6")
    dialog.show("R9")
    press(dialog, "Find")
    assert status(dialog) == "Not found"
    assert selection(editor) == ("1.4", "1.6")
    assert editor.index("insert") == "1.4"
    type_into(dialog.find_entry, "#1")
    press(dialog, "Find")
    assert status(dialog) == ""
    assert selection(editor) == ("1.8", "1.10")


def test_show_clears_the_status(dialog, editor):
    put(editor, "MOV R0, #1")
    dialog.show("R9")
    press(dialog, "Find")
    dialog.close()
    dialog.show()
    assert status(dialog) == ""


def test_find_scrolls_the_match_into_view(dialog, editor, window):
    put(editor, "NOP\n" * 200 + "target: B target\n")
    window.update()
    assert editor.bbox("201.0") is None
    dialog.show("target")
    press(dialog, "Find")
    editor.update_idletasks()
    assert editor.bbox("201.0") is not None


def test_enter_in_either_entry_finds(dialog, editor):
    put(editor, "B loop\nloop: B loop")
    dialog.show("loop")
    assert str(dialog.window) in press_key(dialog.find_entry, "<Key-Return>")
    assert selection(editor) == ("1.2", "1.6")
    assert str(dialog.window) in press_key(dialog.replace_entry, "<Key-KP_Enter>")
    assert selection(editor) == ("2.0", "2.4")


def test_return_presses_the_button_that_has_the_focus(dialog, editor, hidden_windows):
    """As in the other dialogs; anywhere else Return finds."""
    put(editor, "B loop\nloop: B loop")
    dialog.show("loop")
    type_into(dialog.replace_entry, "next")
    match_case = [w for w in descendants(dialog.window) if isinstance(w, ttk.Checkbutton)][0]
    press_key(match_case, "<Key-Return>")                   # on a check box: Find
    assert selection(editor) == ("1.2", "1.6") and not dialog.match_case.get()
    buttons = {str(w.cget("text")): w for w in descendants(dialog.window)
               if isinstance(w, ttk.Button)}
    press_key(buttons["Replace"], "<Key-KP_Enter>")
    assert content(editor) == "B next\nloop: B loop" and selection(editor) == ("2.0", "2.4")
    press_key(buttons["Replace All"], "<Key-Return>")
    assert content(editor) == "B next\nnext: B next" and status(dialog) == "2 replacements"
    press_key(buttons["Find"], "<Key-Return>")
    assert status(dialog) == "Not found"
    press_key(buttons["Close"], "<Key-Return>")
    assert not hidden_windows.shows(dialog.window)


def test_escape_close_and_the_title_bar_hide_the_dialog(dialog, hidden_windows):
    dialog.show()
    window = dialog.window
    assert str(window) in press_key(dialog.find_entry, "<Key-Escape>")
    assert not hidden_windows.shows(window)
    dialog.show()
    press(dialog, "Close")
    assert not hidden_windows.shows(window)
    dialog.show()
    window.tk.eval(window.protocol("WM_DELETE_WINDOW"))
    assert not hidden_windows.shows(window)
    dialog.show()
    assert dialog.window is window
    assert hidden_windows.shows(window)


def test_replace_replaces_the_selected_match_then_selects_the_next(dialog, editor):
    put(editor, "MOV R0, #1\nMOV R1, #2")
    dialog.show("mov")
    type_into(dialog.replace_entry, "ADD")
    press(dialog, "Replace")                # nothing selected yet: it only finds
    assert content(editor) == "MOV R0, #1\nMOV R1, #2"
    assert selection(editor) == ("1.0", "1.3")
    press(dialog, "Replace")
    assert content(editor) == "ADD R0, #1\nMOV R1, #2"
    assert selection(editor) == ("2.0", "2.3")
    press(dialog, "Replace")
    assert content(editor) == "ADD R0, #1\nADD R1, #2"
    assert status(dialog) == "Not found"


def test_replace_is_one_undo_step(dialog, editor):
    put(editor, "MOV R0, #1")
    editor.tag_add("sel", "1.4", "1.6")
    dialog.show("R0")
    type_into(dialog.replace_entry, "R12")
    press(dialog, "Replace")
    assert content(editor) == "MOV R12, #1"
    editor.insert("1.0", "@ ")
    editor.edit_undo()
    assert content(editor) == "MOV R12, #1"
    editor.edit_undo()
    assert content(editor) == "MOV R0, #1"
    assert not can_undo(editor)


def test_replace_with_a_selection_that_is_not_a_match_only_finds(dialog, editor):
    put(editor, "MOV R0, R0", insert="1.4")
    editor.tag_add("sel", "1.4", "1.7")
    dialog.show("R0")
    type_into(dialog.replace_entry, "R1")
    press(dialog, "Replace")
    assert content(editor) == "MOV R0, R0"
    assert selection(editor) == ("1.4", "1.6")


def test_selecting_the_find_text_keeps_the_editor_selection(dialog, editor, window):
    put(editor, "MOV R0, #1")
    editor.tag_add("sel", "1.4", "1.6")
    dialog.show("R0")
    window.update()
    assert selection(editor) == ("1.4", "1.6")
    type_into(dialog.replace_entry, "R5")
    press(dialog, "Replace")
    assert content(editor) == "MOV R5, #1"


def test_replace_all_reports_how_many_were_replaced(dialog, editor):
    put(editor, "MOV R0, R1\nMOV R0, R2")
    dialog.show("R0")
    type_into(dialog.replace_entry, "R3")
    press(dialog, "Replace All")
    assert status(dialog) == "2 replacements"
    assert content(editor) == "MOV R3, R1\nMOV R3, R2"
    type_into(dialog.find_entry, "R1")
    press(dialog, "Replace All")
    assert status(dialog) == "1 replacement"
    assert content(editor) == "MOV R3, R3\nMOV R3, R2"
    press(dialog, "Replace All")
    assert status(dialog) == "No matches"
    editor.edit_undo()
    assert content(editor) == "MOV R3, R1\nMOV R3, R2"


def test_find_and_replace_after_a_letter_that_is_shorter_in_lower_case(dialog, editor):
    put(editor, "@ \u0130lk deger: R0\nMOV R0, #1")
    dialog.show("R0")
    type_into(dialog.replace_entry, "R7")
    press(dialog, "Find")
    assert editor.get(*selection(editor)) == "R0"
    press(dialog, "Replace")
    assert content(editor) == "@ \u0130lk deger: R7\nMOV R0, #1"
    assert selection(editor) == ("2.4", "2.6")


def test_line_breaks_in_find_never_match_the_newline_tk_keeps_at_the_end(dialog, editor):
    put(editor, "NOP\nNOP")
    dialog.show("NOP\n")                    # as after pasting two copied lines into Find
    press(dialog, "Replace All")
    assert status(dialog) == "1 replacement"
    assert content(editor) == "NOP"
    put(editor, "R0")
    editor.tag_add("sel", "1.0", "end")     # Select All takes in Tk's own newline
    type_into(dialog.find_entry, "R0\n")
    press(dialog, "Replace")
    assert content(editor) == "R0"
    assert status(dialog) == "Not found"


def test_the_check_boxes_set_the_options(dialog, editor):
    put(editor, "R1 R10 r1 R1")
    dialog.show("R1")
    type_into(dialog.replace_entry, "R2")
    press(dialog, "Whole word")
    press(dialog, "Match case")
    press(dialog, "Replace All")
    assert status(dialog) == "2 replacements"
    assert content(editor) == "R2 R10 r1 R2"


def test_each_action_works_on_the_current_text(window):
    first = tkinter.Text(window, undo=True)
    second = tkinter.Text(window, undo=True)
    current = [first]
    dialog = FindReplaceDialog(window, lambda: current[0])
    put(first, "MOV R0, #1")
    put(second, "B .\nMOV R1, #2")
    dialog.show("MOV")
    press(dialog, "Find")
    assert selection(first) == ("1.0", "1.3")
    current[0] = second
    press(dialog, "Find")
    assert selection(second) == ("2.0", "2.3")


def test_without_a_file_the_buttons_only_say_so(window):
    dialog = FindReplaceDialog(window, lambda: None)
    dialog.show("MOV")
    for label in ("Find", "Replace", "Replace All"):
        dialog.status.configure(text="")
        press(dialog, label)
        assert status(dialog) == "No file is open"
