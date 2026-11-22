# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""ARES's own message box: a question, a warning, an error or a piece of information.

The box's title says what it asks or tells. At its left is the sign of its
kind, 32 design pixels: a yellow triangle with "!" for a warning (also a
question whose answer can lose work), a red disc with a white x for an error,
a speech bubble with "i" for information and one with "?" for a plain
question, the same signs as the dialogs a program asks for. Beside the sign
is the text in bold, on one line or on the lines the text breaks itself;
under them, in the middle, are the buttons, all as wide as the widest.

The first button (or the one given as default) has the keyboard focus and the
black frame of the default button: Return presses it, or the button that has
the focus. Escape and the window's close button answer Cancel; in a box
without Cancel, OK, or else No. Y and N, without Control or Alt, press Yes and
No, whose letters are underlined.

show() is the one function that waits. It builds the box over a window of
ARES: the box belongs to that window, stays in front of it and opens centred
on it, and the window takes no input until the box is answered, as under a
system message box. It returns the name of the button chosen. The other
functions are the boxes ARES shows.
"""

import sys
import tkinter as tk
from tkinter import ttk

from . import icons
from .menubar import screen_area
from .style import apply as apply_style
from .style import default_button
from .tools.frame import place_over
from .widgets import px

# The kinds of box, and the icon of each one's sign (ares.gui.icons).
WARNING, ERROR, INFORMATION, QUESTION = "warning", "error", "information", "question"
SIGNS = {WARNING: "message_warning", ERROR: "message_error",
         INFORMATION: "message_information", QUESTION: "message_question"}
# The buttons, by the names show() returns.
YES, NO, CANCEL, OK = "yes", "no", "cancel", "ok"
LABELS = {YES: "Yes", NO: "No", CANCEL: "Cancel", OK: "OK"}
KEYS = {YES: "y", NO: "n"}      # the keys that press these buttons: their first letters
# Sizes in design pixels.
SIGN_SIZE = 32                  # the sign, square
SIDE = 11                       # inside the box: left and right of its contents
ABOVE = 10                      # above the sign
BELOW = 12                      # under the buttons
SIGN_GAP = 15                   # between the sign and the text
BUTTONS_GAP = 9                 # between the sign or the text and the buttons
BUTTON_GAP = 7                  # between two buttons
FRAME = 40                      # room for the box's frame, where the text must fit the screen
LEAST_WRAP = 200                # the narrowest width of text a line is broken at
# Bits of a key event's state: Control, and Alt (Option and Command on macOS).
CONTROL = 0x4
ALT = {"win32": 0x20000, "aqua": 0x8 | 0x10, "x11": 0x8}

SAVE_CHANGES = "Save program changes?"
OVERWRITE = "Overwrite existing file?"


def key_alone(state, system):
    """True when a key event's state (its modifier bits) holds neither Control nor Alt, on the
    windowing system system ("win32", "aqua" or "x11"); Shift and Caps Lock may be on."""
    return not state & (CONTROL | ALT.get(system, ALT["x11"]))


class MessageBox:
    """One message box over master, shown at once (see the module's docstring).

    buttons are names of LABELS, in their order from the left; default is the
    index of the default button. parent is the window the box belongs to,
    master's own window; with owned False it is None, and the box opens in the
    middle of the screen: a window that belongs to a hidden one stays hidden.
    answer holds the name of the button chosen once the box is closed, else
    None. wait() waits for it.
    """

    def __init__(self, master, kind, title, text, buttons=(OK,), default=0, owned=True):
        self.kind = kind
        self.text = text
        self.answer = None
        self.parent = master.winfo_toplevel() if owned else None
        self._refused = None                # while wait() waits: did parent refuse input before
        if self.parent is not None and self.parent.state() == "iconic":
            # A window that belongs to a minimized one stays hidden with it: the box asks
            # about the window, which comes back with it.
            self.parent.deiconify()
        apply_style(master)                 # also before the main window has its look
        window = self.window = tk.Toplevel(master)
        window.withdraw()
        window.title(title)
        if self.parent is not None:
            window.transient(self.parent)
        window.resizable(False, False)
        body = ttk.Frame(window, padding=(px(window, SIDE), px(window, ABOVE), px(window, SIDE),
                                          px(window, BELOW)))
        body.pack(fill="both", expand=True)
        self.sign_name = SIGNS[kind]
        self.sign_image = icons.photo(window, self.sign_name, px(window, SIGN_SIZE))
        self.sign = ttk.Label(body, image=self.sign_image)
        self.sign.grid(row=0, column=0, sticky="nw", padx=(0, px(window, SIGN_GAP)))
        body.columnconfigure(1, weight=1)   # buttons wider than the text leave room after it
        # A line is broken only where it would not fit the screen.
        wrap = window.winfo_screenwidth() - px(window, 2 * SIDE + SIGN_SIZE + SIGN_GAP + FRAME)
        self.label = ttk.Label(body, text=text, font="TkDefaultFont", justify="left",
                               wraplength=max(px(window, LEAST_WRAP), wrap))
        self.label.grid(row=0, column=1, sticky="w")
        row = self.button_row = ttk.Frame(body)
        row.grid(row=1, column=0, columnspan=2, pady=(px(window, BUTTONS_GAP), 0))
        self.buttons = {}
        for i, name in enumerate(buttons):
            button = ttk.Button(row, text=LABELS[name], underline=0 if name in KEYS else -1,
                                command=lambda name=name: self.press(name))
            # Every other column holds a button, all of one width; those between them are gaps.
            row.columnconfigure(2 * i, uniform="button")
            if i:
                row.columnconfigure(2 * i - 1, minsize=px(window, BUTTON_GAP))
            button.grid(row=0, column=2 * i, sticky="we")
            self.buttons[name] = button
        names = list(self.buttons)
        self.default = self.buttons[names[default]]
        self.escape = next((name for name in (CANCEL, OK, NO) if name in self.buttons), names[-1])
        default_button(self.default, self.buttons.values())
        system = str(window.tk.call("tk", "windowingsystem"))
        for name, letter in KEYS.items():
            if name in self.buttons:
                for key in (letter, letter.upper()):
                    window.bind(f"<Key-{key}>", lambda event, name=name: self._letter(
                        event, name, system))
        for sequence in ("<Return>", "<KP_Enter>"):
            window.bind(sequence, self._return)
        window.bind("<Escape>", lambda event: self.press(self.escape))
        window.protocol("WM_DELETE_WINDOW", lambda: self.press(self.escape))
        if self.parent is not None:
            place_over(window, self.parent)
        else:
            centre_on_screen(window)
        window.deiconify()
        if self.parent is not None:
            self.default.focus_set()
        else:
            # Nothing else of ARES is on the screen to bring the box to the front with it.
            self.default.focus_force()

    def _letter(self, event, name, system):
        """Y or N: presses Yes or No, unless Control or Alt is held with it."""
        if key_alone(event.state, system):
            self.press(name)
            return "break"
        return None

    def _return(self, event):
        """Return presses the button that has the focus, else the default (ttk buttons ignore
        Return)."""
        button = next((b for b in self.buttons.values() if event.widget is b), self.default)
        button.invoke()
        return "break"

    def press(self, name):
        """Close the box with the answer name."""
        if self.window is None:
            return
        self.answer = name
        # Before the box goes, or Windows would make another program's window the active one.
        self._give_input_back()
        self.window.destroy()
        self.window = None

    def wait(self):
        """Take all input of ARES until the box is answered; the name of the button chosen.

        Meanwhile the window the box belongs to refuses input, as under a system
        message box: its close button would ask a question of its own. A grab
        held before the box is given back after it.
        """
        window = self.window
        if window is None:
            return self.answer
        before = str(window.tk.call("grab", "current", str(window)))
        status = str(window.tk.call("grab", "status", before)) if before else "none"
        try:
            window.grab_set()
        except tk.TclError:
            pass                            # another program holds the grab
        self._refuse_input()
        try:
            window.wait_window()
        finally:
            self._give_input_back()
        try:
            if before and window.tk.getboolean(window.tk.call("winfo", "exists", before)):
                window.tk.call("grab", *(("-global",) if status == "global" else ()), before)
        except tk.TclError:
            pass                            # it cannot take the grab now
        return self.answer

    def _refuse_input(self):
        """Make the window the box belongs to refuse input while the box waits: on Windows. Tk
        has no such state elsewhere, where the grab alone keeps input from it."""
        if self.parent is None or sys.platform != "win32":
            return
        try:
            self._refused = self.parent.tk.getboolean(self.parent.attributes("-disabled"))
            self.parent.attributes("-disabled", True)
        except tk.TclError:
            self._refused = None

    def _give_input_back(self):
        """Let the window the box belongs to take input as it did before the box waited."""
        if self._refused is None:
            return
        refused, self._refused = self._refused, None
        try:
            self.parent.attributes("-disabled", refused)
        except tk.TclError:
            pass                            # destroyed meanwhile


def centre_on_screen(window):
    """Put a window that is not shown yet in the middle of the work area of the main screen."""
    window.update_idletasks()
    width, height = window.winfo_reqwidth(), window.winfo_reqheight()
    left, top, right, bottom = screen_area(window, window.winfo_screenwidth() // 2,
                                           window.winfo_screenheight() // 2)
    window.geometry(f"+{left + max(0, (right - left - width) // 2)}"
                    f"+{top + max(0, (bottom - top - height) // 2)}")


def show(master, kind, title, text, buttons=(OK,), default=0, owned=True):
    """Show a message box over master (see MessageBox) and wait for its answer: the name of the
    button chosen, None if the box was closed otherwise (its window destroyed)."""
    return MessageBox(master, kind, title, text, buttons, default, owned).wait()


def ask_save(master, name):
    """Before the changes to the file called name are lost: save them? YES, NO or CANCEL."""
    return show(master, WARNING, SAVE_CHANGES,
                f"Changes to {name} will be lost unless you save.  Do you wish to save all "
                "changes now?", (YES, NO, CANCEL))


def ask_overwrite(master, name):
    """Before a file called name is written over: YES (write over it), NO (choose another name)
    or CANCEL."""
    return show(master, WARNING, OVERWRITE,
                f"File {name} already exists.  Do you wish to overwrite it?", (YES, NO, CANCEL))


def show_error(master, title, text, owned=True):
    """An error, with OK alone."""
    return show(master, ERROR, title, text, (OK,), owned=owned)
