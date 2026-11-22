# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""ARES's own message box: its look, its keys, its wait, and every place ARES shows it."""

import errno
import sys
import tkinter as tk
from tkinter import font as tkfont
from types import SimpleNamespace

import pytest
from conftest import Box, new_root, press_key
from test_gui_assemble import assemble, open_source
from test_gui_dialogs import DUMPED, open_dump
from window_layout import at_size, clashes

from ares.gui import app as app_module
from ares.gui import dialogs, icons, msgbox, style
from ares.gui.msgbox import (CANCEL, ERROR, INFORMATION, NO, OK, QUESTION, WARNING, YES,
                             MessageBox)
from ares.gui.widgets import px

SAVE_TEXT = ("Changes to f.s will be lost unless you save.  Do you wish to save all changes "
             "now?")
KINDS = (WARNING, ERROR, INFORMATION, QUESTION)


@pytest.fixture
def root():
    """A hidden Tk root of the test alone, with ARES's look."""
    root = new_root()
    style.apply(root)
    yield root
    root.destroy()


def make(root, kind=WARNING, buttons=(YES, NO, CANCEL), text=SAVE_TEXT, **options):
    return MessageBox(root, kind, "Save program changes?", text, buttons, **options)


def pixels(image):
    return [image.get(x, y) for y in range(image.height()) for x in range(image.width())]


def laid_out(box):
    """Lay the hidden box out at the size it asks for, as on the screen; nothing in it may be
    cut off or overlap."""
    window = box.window
    window.update_idletasks()
    assert clashes(at_size(window, window.winfo_reqwidth(), window.winfo_reqheight())) == []


# The box ----------------------------------------------------------------------------------

@pytest.mark.parametrize("kind, name, colour", [
    (WARNING, "message_warning", icons.YELLOW), (ERROR, "message_error", icons.RED),
    (INFORMATION, "message_information", icons.BLUE),
    (QUESTION, "message_question", icons.BLUE)])
def test_each_kind_draws_its_sign_at_the_left(root, kind, name, colour):
    box = make(root, kind, (OK,))
    image, size = box.sign_image, px(root, msgbox.SIGN_SIZE)
    assert box.sign_name == name and box.sign.cget("image")[0] == image.name
    assert (image.width(), image.height()) == (size, size)
    drawn = pixels(image)
    assert drawn == pixels(icons.photo(root, name, size)) and colour in drawn
    assert int(box.sign.grid_info()["column"]) == 0 and int(box.label.grid_info()["column"]) == 1


def test_the_four_signs_differ(root):
    assert len({tuple(pixels(make(root, kind).sign_image)) for kind in KINDS}) == 4


def test_the_title_the_bold_text_and_the_buttons_in_order(root):
    box = make(root)
    assert box.window.title() == "Save program changes?"
    assert box.label.cget("text") == SAVE_TEXT and "\n" not in SAVE_TEXT
    assert str(box.label.cget("font")) == "TkDefaultFont"
    assert tkfont.nametofont("TkDefaultFont", root=root).actual("weight") == "bold"
    buttons = list(box.buttons.values())
    assert [b.cget("text") for b in buttons] == ["Yes", "No", "Cancel"]
    assert [int(b.grid_info()["column"]) for b in buttons] == [0, 2, 4]
    assert [int(b.cget("underline")) for b in buttons] == [0, 0, -1]     # Y and N


def test_the_buttons_are_as_wide_as_the_widest_and_centred_under_the_text(root):
    box = make(root)
    laid_out(box)
    buttons = list(box.buttons.values())
    assert {b.winfo_width() for b in buttons} == {max(b.winfo_reqwidth() for b in buttons)}
    gaps = [b.winfo_x() - (a.winfo_x() + a.winfo_width()) for a, b in zip(buttons, buttons[1:])]
    assert gaps == [px(root, msgbox.BUTTON_GAP)] * 2
    row, body = box.button_row, box.button_row.master
    assert row.grid_info()["columnspan"] == 2 and row.grid_info()["sticky"] == ""
    assert abs(row.winfo_x() + row.winfo_width() / 2 - body.winfo_reqwidth() / 2) <= 1
    assert row.winfo_y() >= box.sign.winfo_y() + box.sign.winfo_height()
    # One line of text stands beside the middle of the sign.
    sign_middle = box.sign.winfo_y() + box.sign.winfo_height() / 2
    assert abs(box.label.winfo_y() + box.label.winfo_height() / 2 - sign_middle) <= 1


def test_buttons_wider_than_a_short_text_leave_the_sign_and_the_text_at_the_left(root):
    box = make(root, QUESTION, text="Do you wish to continue?")
    laid_out(box)
    side, sign, gap = (px(root, size) for size in (msgbox.SIDE, msgbox.SIGN_SIZE,
                                                    msgbox.SIGN_GAP))
    assert box.button_row.winfo_reqwidth() > sign + gap + box.label.winfo_reqwidth()
    assert box.sign.winfo_x() == side and box.label.winfo_x() == side + sign + gap


def test_text_with_line_breaks_shows_its_lines_and_a_line_breaks_only_at_the_screens_width(
        root):
    text = "Save operation could not be completed due to an error:\nf.s (Permission denied)"
    box = make(root, ERROR, (OK,), text)
    assert box.label.cget("text") == text
    assert int(box.label.cget("wraplength")) >= root.winfo_screenwidth() - px(root, 200)


def test_yes_is_the_default_and_has_the_focus(root, hidden_windows):
    box = make(root)
    assert hidden_windows.focus is box.buttons[YES]
    assert [str(b.cget("default")) for b in box.buttons.values()] == ["active", "normal",
                                                                      "normal"]
    box = make(root, buttons=(YES, NO), default=1)
    assert hidden_windows.focus is box.default is box.buttons[NO]
    assert str(box.buttons[NO].cget("default")) == "active"


def test_the_box_belongs_to_its_window_is_centred_on_it_and_keeps_its_size(root, monkeypatch):
    placed = []
    monkeypatch.setattr(msgbox, "place_over", lambda window, parent: placed.append(
        (window, parent)))
    box = make(root)
    assert str(box.window.transient()) == str(root) and placed == [(box.window, root)]
    assert [int(v) for v in box.window.tk.splitlist(
        box.window.tk.call("wm", "resizable", box.window))] == [0, 0]
    assert str(box.window.cget("background")).upper() == style.FACE


def test_a_minimized_window_comes_back_with_its_box(root, monkeypatch):
    restored = []
    monkeypatch.setattr(root, "state", lambda *args: "iconic")
    monkeypatch.setattr(root, "deiconify", lambda: restored.append(root))
    make(root)
    assert restored == [root]


def test_a_box_of_no_window_opens_in_the_middle_of_the_screen_in_front(root, monkeypatch):
    monkeypatch.setattr(msgbox, "screen_area", lambda widget, x, y: (100, 0, 1100, 800))
    forced = []
    monkeypatch.setattr(tk.Misc, "focus_force", lambda widget: forced.append(widget))
    box = make(root, ERROR, (OK,), owned=False)
    assert str(box.window.transient()) == "" and box.parent is None
    x, y = (int(v) for v in box.window.geometry().split("+")[1:])
    assert x == 100 + (1000 - box.window.winfo_reqwidth()) // 2
    assert y == (800 - box.window.winfo_reqheight()) // 2
    assert forced == [box.buttons[OK]]          # nothing else of ARES brings it to the front
    make(root)
    assert forced == [box.buttons[OK]]          # a box over its window takes the focus there


@pytest.mark.parametrize("sequence", ["<Return>", "<KP_Enter>"])
def test_return_presses_the_button_with_the_focus_else_the_default(root, sequence):
    box = make(root)
    press_key(box.buttons[YES], sequence)
    assert box.answer == YES and box.window is None
    box = make(root)
    press_key(box.buttons[CANCEL], sequence)        # the focus moved to Cancel
    assert box.answer == CANCEL
    box = make(root)
    press_key(box.window, sequence)
    assert box.answer == YES


@pytest.mark.parametrize("buttons, answer", [((YES, NO, CANCEL), CANCEL), ((OK,), OK),
                                             ((YES, NO), NO)])
def test_escape_and_the_close_button_answer_cancel_else_ok_else_no(root, buttons, answer):
    box = make(root, buttons=buttons)
    press_key(box.buttons[buttons[0]], "<Escape>")
    assert box.answer == answer and box.window is None
    box = make(root, buttons=buttons)
    box.window.tk.call(box.window.protocol("WM_DELETE_WINDOW"))
    assert box.answer == answer and box.window is None


@pytest.mark.parametrize("key, answer", [("y", YES), ("Y", YES), ("n", NO), ("N", NO)])
def test_y_and_n_press_yes_and_no(root, key, answer):
    box = make(root)
    press_key(box.buttons[CANCEL], f"<Key-{key}>")
    assert box.answer == answer and box.window is None


def test_y_and_n_with_control_or_alt_press_nothing(root):
    assert msgbox.key_alone(0, "win32") and msgbox.key_alone(0x1 | 0x2, "win32")  # Shift, Lock
    assert msgbox.key_alone(0x8, "win32")                       # Num Lock on Windows
    for state in (0x4, 0x20000, 0x4 | 0x20000):
        assert not msgbox.key_alone(state, "win32")
    assert not msgbox.key_alone(0x8, "x11") and not msgbox.key_alone(0x10, "aqua")
    box = make(root)
    assert box._letter(SimpleNamespace(state=0x4), YES, "win32") is None
    assert box.answer is None and box.window is not None
    assert box._letter(SimpleNamespace(state=0x1), NO, "win32") == "break"
    assert box.answer == NO
    assert not make(root, buttons=(OK,)).window.bind("<Key-y>")


def test_a_button_answers_once(root):
    box = make(root)
    box.buttons[NO].invoke()
    box.press(YES)
    assert box.answer == NO


def test_wait_takes_all_input_until_the_box_is_answered(root):
    box = make(root)
    window, during = str(box.window), []

    def answer():
        during.append(str(root.tk.call("grab", "current", str(root))))
        if sys.platform == "win32":
            during.append(root.attributes("-disabled"))
        box.buttons[NO].invoke()
    root.after(1, answer)
    root.after(5000, lambda: box.window is not None and box.window.destroy())   # never long
    assert box.wait() == NO
    # Meanwhile the box held the grab, and on Windows its window refused all input.
    assert during == [window, 1] if sys.platform == "win32" else during == [window]
    assert str(root.tk.call("grab", "current", str(root))) == ""
    if sys.platform == "win32":
        assert not root.attributes("-disabled")


@pytest.mark.skipif(sys.platform != "win32", reason="a window refuses input only on Windows")
def test_a_window_that_refused_input_before_the_box_still_does_after_it(root):
    root.attributes("-disabled", True)              # under another box, for example
    box = make(root)
    root.after(1, box.buttons[YES].invoke)
    root.after(5000, lambda: box.window is not None and box.window.destroy())
    assert box.wait() == YES and root.attributes("-disabled")
    root.attributes("-disabled", False)
    box = make(root)
    box.buttons[NO].invoke()                        # answered before it waited: nothing changes
    assert not root.attributes("-disabled") and box.wait() == NO


def test_wait_gives_back_a_grab_held_before(root):
    other = tk.Toplevel(root)
    other.grab_set()
    box = make(root)
    root.after(1, box.buttons[YES].invoke)
    root.after(5000, lambda: box.window is not None and box.window.destroy())
    assert box.wait() == YES
    assert str(root.tk.call("grab", "current", str(root))) == str(other)
    other.grab_release()


def test_show_builds_the_box_and_waits_for_it(root, monkeypatch, message_boxes):
    assert msgbox.show == message_boxes.show            # in tests the box never waits
    waited = []

    def wait(self):
        waited.append(self)
        self.buttons[NO].invoke()
        return self.answer
    monkeypatch.setattr(MessageBox, "wait", wait)
    assert message_boxes.real_show(root, ERROR, "T", "x", (YES, NO), 1, owned=False) == NO
    box, = waited
    assert (box.kind, box.window, box.parent, box.text) == (ERROR, None, None, "x")
    assert box.default is box.buttons[NO]


# Where ARES shows it ----------------------------------------------------------------------

def test_the_save_question_before_closing_and_at_exit(app, tmp_path, message_boxes):
    path = tmp_path / "f.s"
    path.write_bytes(b"NOP\n")
    tab = app.open_path(path)
    tab.text.insert("1.0", "X")
    message_boxes.answer(CANCEL, CANCEL, NO)
    app.cmd_close()
    app.cmd_exit()
    assert app.editor.tabs == [tab] and app.root.winfo_exists()
    app.cmd_close()                                     # No: closed, the file as it was
    assert app.editor.tabs == [] and path.read_bytes() == b"NOP\n"
    assert message_boxes.shown == [Box(WARNING, "Save program changes?", SAVE_TEXT,
                                       (YES, NO, CANCEL), 0, True)] * 3
    assert message_boxes.masters == [app.root] * 3


def test_yes_to_the_save_question_saves(app, tmp_path, message_boxes):
    path = tmp_path / "f.s"
    path.write_bytes(b"NOP\n")
    app.open_path(path).text.insert("1.0", "X")
    message_boxes.answer(YES)
    app.cmd_close()
    assert path.read_bytes() == b"XNOP\n" and app.editor.tabs == []


def save_dialog(monkeypatch, module, *paths):
    """Make the system's save dialog give paths in turn; returns the options of each call."""
    asked, given = [], list(paths)

    def ask(**options):
        asked.append(options)
        return given.pop(0)
    monkeypatch.setattr(module.filedialog, "asksaveasfilename", ask)
    return asked


def overwrite(name):
    return Box(WARNING, "Overwrite existing file?",
               f"File {name} already exists.  Do you wish to overwrite it?", (YES, NO, CANCEL),
               0, True)


def test_save_as_onto_a_file_that_exists_asks_and_no_asks_for_another_name(
        app, tmp_path, monkeypatch, message_boxes):
    lab = tmp_path / "lab.s"
    lab.write_bytes(b"old\n")
    asked = save_dialog(monkeypatch, app_module, str(lab), str(lab))
    app.cmd_new()
    tab = app.editor.current
    tab.text.insert("1.0", "NOP")
    message_boxes.answer(NO, YES)
    assert app.save_as(tab)
    assert message_boxes.shown == [overwrite("lab.s")] * 2
    assert lab.read_bytes() == b"NOP" and tab.path == lab
    # The system's dialog asks nothing itself; after No it opens again at the name chosen.
    assert [options["confirmoverwrite"] for options in asked] == [False, False]
    assert (asked[0]["initialfile"], asked[1]["initialfile"]) == ("untitled1.s", "lab.s")
    assert asked[1]["initialdir"] == tmp_path


def test_cancel_to_the_overwrite_question_saves_nothing(app, tmp_path, monkeypatch,
                                                        message_boxes):
    lab = tmp_path / "lab.s"
    lab.write_bytes(b"old\n")
    asked = save_dialog(monkeypatch, app_module, str(lab))
    app.cmd_new()
    tab = app.editor.current
    tab.text.insert("1.0", "NOP")
    message_boxes.answer(CANCEL)
    assert app.save_as(tab) is False
    assert len(asked) == 1 and lab.read_bytes() == b"old\n" and tab.path is None


def test_a_new_name_asks_nothing(app, tmp_path, monkeypatch, message_boxes):
    save_dialog(monkeypatch, app_module, str(tmp_path / "new.s"))
    app.cmd_new()
    assert app.save_as(app.editor.current)
    assert message_boxes.shown == []


def test_a_save_that_fails_says_so_for_save_and_for_save_as(app, tmp_path, monkeypatch,
                                                            message_boxes):
    path = tmp_path / "f.s"
    path.write_bytes(b"NOP\n")
    tab = app.open_path(path)
    tab.text.insert("1.0", "X")

    def refused(where=None):
        raise PermissionError(errno.EACCES, "Permission denied")
    monkeypatch.setattr(tab, "save", refused)
    other = tmp_path / "other.s"
    save_dialog(monkeypatch, app_module, str(other))
    message_boxes.answer(OK, OK)
    assert app.save(tab) is False and app.save_as(tab) is False
    assert message_boxes.shown == [
        Box(ERROR, "Save Operation Failed", "Save operation could not be completed due to an "
            f"error:\n{path} (Permission denied)", (OK,), 0, True),
        Box(ERROR, "Save As Operation Failed", "Save As operation could not be completed due "
            f"to an error:\n{other} (Permission denied)", (OK,), 0, True)]


def test_the_other_errors_say_what_they_are(app, tmp_path, monkeypatch, message_boxes):
    missing = tmp_path / "missing.s"
    message_boxes.answer(OK, OK)
    assert app.open_path(missing) is None
    _, open_tab = open_source(app, tmp_path, "NOP\n", "open.s")
    save_dialog(monkeypatch, app_module, str(tmp_path / "open.s"))
    app.cmd_new()
    assert app.save_as(app.editor.current) is False
    (kind, title, text), refused = [box[:3] for box in message_boxes.shown]
    assert (kind, title) == (ERROR, "Cannot open file") and text.startswith(
        f"Cannot open {missing}:\n")
    assert refused == (ERROR, "File already open", "open.s is open in another tab; close it "
                       "first.")
    assert open_tab.get_text() == "NOP\n"


def test_dump_memory_asks_before_writing_over_a_file(app, tmp_path, monkeypatch,
                                                     message_boxes):
    open_source(app, tmp_path, DUMPED)
    assemble(app)
    created, init = open_dump(app)
    monkeypatch.setattr(dialogs.DumpMemoryDialog, "__init__", init)
    old = tmp_path / "old.bin"
    old.write_bytes(b"old")
    asked = save_dialog(monkeypatch, dialogs, str(old), str(old), str(old))
    app.run("dump_memory")
    dialog = created[-1]
    message_boxes.answer(CANCEL)                    # back to Dump Memory
    assert dialog.dump() is None and dialog.window is not None and old.read_bytes() == b"old"
    message_boxes.answer(NO, YES)                   # another name, then the same: written over
    assert dialog.dump() == str(old) and old.read_bytes() != b"old"
    assert message_boxes.shown == [overwrite("old.bin")] * 3
    assert message_boxes.masters[0] is not app.root and all(
        master is message_boxes.masters[0] for master in message_boxes.masters)
    assert [options["confirmoverwrite"] for options in asked] == [False] * 3
    assert asked[2]["initialfile"] == "old.bin" and asked[2]["initialdir"] == str(tmp_path)
