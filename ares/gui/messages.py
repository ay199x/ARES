# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The ARES Messages and Run I/O panes below the editor."""

import tkinter as tk
import unicodedata
from tkinter import ttk

from .style import TEXT, WINDOW, page_padding, sunken
from .tabs import Notebook
from .widgets import HidingBars, ReadOnlyText, keep_size, line_spacing, px, use_shortcuts

MESSAGES = "ARES Messages"
RUN_IO = "Run I/O"
RUN_IO_LIMIT = 1_000_000        # characters of output Run I/O keeps (the newest)
CONTROL = 0x4                   # event.state bits of modifier keys
COMMAND = 0x8                   # Command on macOS (Alt on X11, Num Lock on Windows)
WINDOWS_ALT = 0x20000


def _is_text(text):
    """True when text has no control characters and no halves of surrogate pairs."""
    return all(unicodedata.category(char) not in ("Cc", "Cs") for char in text)


def keys_as_line(keys):
    """Keys typed for the program, as the start of a line to change.

    Each BackSpace takes back the character before it; other control
    characters, except Tab, are left out.
    """
    line = []
    for char in keys:
        if char in "\b\x7f":
            if line:
                line.pop()
        elif char == "\t" or _is_text(char):
            line.append(char)
    return "".join(line)


# Run I/O's widget command, in Tcl: the program's output is written with the
# original command; the user may change text only after the mark "input",
# and only while a line is being typed (::ares_typing(<original>) exists).
# A deletion stops before the last line break: Tk would also delete the line
# break before a range that reaches the end (a triple-click selects to it).
_RUN_IO = """{original args} {
    switch -exact -- [lindex $args 0] {
        insert - delete - replace {
            if {![info exists ::ares_typing($original)]} {return}
            set last [expr {[lindex $args 0] eq "insert" ? 1 : 2}]
            foreach index [lrange $args 1 $last] {
                if {[$original compare $index < input]} {return}
            }
            if {$last == 2} {
                if {[llength $args] == 2} {lappend args "[lindex $args 1] + 1c"}
                if {[$original compare [lindex $args 2] > "end - 1c"]} {
                    lset args 2 "end - 1c"
                }
            }
        }
    }
    tailcall $original {*}$args
}"""


class RunIO(ReadOnlyText):
    """Run I/O: the program's output, and the line typed for it at the end.

    Its text cursor shows only while a line can be typed; at all other
    times Tk draws none, also where a click put it. A cursor no pixels
    wide is not drawn.
    """

    COMMAND = _RUN_IO

    def __init__(self, master=None, **options):
        super().__init__(master, **options)
        self._cursor_width = self.cget("insertwidth")       # Tk's, while a line is typed
        self.configure(insertwidth=0)

    @property
    def typing(self):
        """True while a line can be typed."""
        return bool(int(self.tk.call("info", "exists", f"::ares_typing({self._original})")))

    def _set_typing(self, typing):
        """Let a line be typed, or no longer; the text cursor shows exactly while one can be."""
        name = f"::ares_typing({self._original})"
        if typing:
            self.tk.call("set", name, 1)
        else:
            self.tk.call("unset", name)
        self.configure(insertwidth=self._cursor_width if typing else 0)

    def begin_line(self, text=""):
        """Let the user type a line after the output, starting with text."""
        self.tk.call(self._original, "mark", "set", "input", "end-1c")
        self.tk.call(self._original, "mark", "gravity", "input", "left")
        self._set_typing(True)
        self.insert("end-1c", text.replace("\x00", ""))   # Tk would end the text there
        self.mark_set("insert", "end-1c")
        self.see_end()

    def send_line(self):
        """Enter: no more typing; returns the typed line, which stays shown, and the rest.

        A line break pasted into the line ends it: the text after it, the
        rest, is taken away (it is empty without one).
        """
        if not self.typing:
            return None
        line_end = self.index("input lineend")
        rest = self.get(f"{line_end} + 1c", "end-1c")
        self.tk.call(self._original, "delete", line_end, "end-1c")
        self._set_typing(False)
        return self.get("input", "end-1c"), rest

    def end_line(self):
        """No more typing, the line unsent: returns it and takes it away (None if none was)."""
        if not self.typing:
            return None
        text = self.get("input", "end-1c")
        self.tk.call(self._original, "delete", "input", "end-1c")
        self._set_typing(False)
        return text

    def to_line(self):
        """Put the cursor back in the typed line, and keep a selection to the line."""
        if self.compare("insert", "<", "input"):
            self.mark_set("insert", "end-1c")
        if self.tag_ranges("sel") and self.compare("sel.first", "<", "input"):
            self.tag_remove("sel", "1.0", "input")


class MessagesPane(Notebook):
    """Two tabs, each with a Clear button at its left edge and a read-only text.

    A text's scroll bars show only while its contents do not fit that way
    (widgets.HidingBars); they never move the dividers of the window.
    on_click(target) is called when the user clicks a message written with
    a target, such as the line of an assembler error. In Run I/O, a line
    typed after begin_line() goes to on_line(text, rest) when Enter is
    pressed, or when a line break is pasted into it: rest is the text after
    that line break (typed ahead), else empty. While keys_wanted is true,
    characters typed there go to on_keys(text) at once, without being shown
    (the program shows them if it wants to). on_cleared() is called when
    Run I/O is cleared. ARES Messages never shows a text cursor, and Run I/O
    only while a line is typed there (RunIO); text can be selected and
    copied in both.
    """

    def __init__(self, master, font, on_click):
        super().__init__(master)
        self.on_click = on_click
        self.on_line = self.on_keys = self.on_cleared = None
        self.keys_wanted = False
        self.windowing_system = self._windowingsystem   # which keys are the shortcuts' modifiers
        self._targets = {}              # tag of a clickable message -> its target
        self._output = 0                # characters in Run I/O
        self._bars = {}                 # each text -> its scroll bars
        self.messages = self._add_page(MESSAGES, font, ReadOnlyText)
        self.messages.configure(insertwidth=0)      # no cursor
        self.run_io = self._add_page(RUN_IO, font, RunIO)
        self.messages.tag_bind("link", "<Enter>",
                               lambda e: self.messages.configure(cursor="hand2"))
        self.messages.tag_bind("link", "<Leave>",
                               lambda e: self.messages.configure(cursor=""))
        self.messages.bind("<ButtonRelease-1>", self._clicked, add="+")
        self.run_io.bind("<Return>", self._enter)
        self.run_io.bind("<KP_Enter>", self._enter)
        self.run_io.bind("<KeyPress>", self._key)
        self.run_io.bind("<<Paste>>", lambda e: self._paste_from("CLIPBOARD"))
        self.run_io.bind("<<PasteSelection>>", lambda e: self._paste_from("PRIMARY"))

    def _add_page(self, title, font, kind):
        tab = tk.Frame(self)
        clear = ttk.Button(tab, text="Clear", takefocus=False,
                           command=lambda: self.clear(text))
        clear.pack(side="left", padx=px(self, 6))
        page = sunken(tk.Frame(tab))            # the text and its scroll bars, in grid columns 1-2
        keep_size(page)
        page.pack(side="left", fill="both", expand=True)
        above, below = line_spacing(self, font)
        text = kind(page, font=font, wrap="none", height=6, background=WINDOW,
                    foreground=TEXT, insertbackground=TEXT, borderwidth=0,
                    highlightthickness=0, padx=px(self, 1), pady=0, spacing1=above,
                    spacing3=below)
        use_shortcuts(text)
        yscroll = ttk.Scrollbar(page, orient="vertical", command=text.yview)
        xscroll = ttk.Scrollbar(page, orient="horizontal", command=text.xview)
        text.grid(row=0, column=1, sticky="nsew")
        yscroll.grid(row=0, column=2, sticky="ns")
        xscroll.grid(row=1, column=1, sticky="ew")
        page.rowconfigure(0, weight=1)
        page.columnconfigure(1, weight=1)
        self._bars[text] = HidingBars(text, yscroll, xscroll)
        self.add(tab, text=title, padding=page_padding(self))
        return text

    def _changed(self, text):
        """Decide the text's scroll bars again once the changes of the moment are done."""
        self._bars[text].schedule()

    def write_message(self, line, target=None):
        """Add a line to ARES Messages; with a target the line can be clicked."""
        if target is None:
            self.messages.write(line + "\n")
        else:
            tag = f"target{len(self._targets)}"
            self._targets[tag] = target
            self.messages.write(line + "\n", "link", tag)
        self.messages.see("end")
        self._changed(self.messages)

    def write_output(self, text):
        """Add program output to Run I/O; the oldest output goes past RUN_IO_LIMIT characters.

        Zero bytes are left out: Tk would end the text at the first one.
        """
        text = text.replace("\x00", "")
        if not text:
            return
        self.run_io.write(text)
        self._output += len(text)
        if self._output > RUN_IO_LIMIT:
            drop = self._output - RUN_IO_LIMIT * 9 // 10
            self.run_io.tk.call(self.run_io._original, "delete", "1.0", f"1.0 + {drop} chars")
            self._output -= drop
        self.run_io.see_end()
        self._changed(self.run_io)

    def finish_line(self):
        """End Run I/O's last line if the output stopped within it (before a new run)."""
        if self.run_io.get("end-2c", "end-1c") not in ("", "\n"):
            self.write_output("\n")

    def clear(self, text):
        typed = self.run_io.end_line() if text is self.run_io else None
        text.clear()
        self._changed(text)
        if text is self.messages:
            self._targets.clear()
            return
        self._output = 0
        if typed is not None:
            self.run_io.begin_line(typed)       # keep typing, now at the top
        if self.on_cleared is not None:
            self.on_cleared()

    def show_messages(self):
        self.select(0)

    def show_run_io(self):
        self.select(1)

    # Typing for the program ------------------------------------------------

    def begin_line(self, text=""):
        """Show Run I/O and let the user type a line there for the program, starting with text."""
        self.show_run_io()
        self.run_io.begin_line(text)
        self.run_io.focus_set()
        self._changed(self.run_io)

    def end_line(self):
        """Stop the typing of a line without sending it; returns the unsent text (or None)."""
        self._changed(self.run_io)
        return self.run_io.end_line()

    def paste(self, text):
        """Paste into Run I/O: into the typed line, or to the program as keys; False if neither."""
        if self.run_io.typing:
            self._changed(self.run_io)
            self.run_io.to_line()
            if self.run_io.tag_ranges("sel"):
                self.run_io.delete("sel.first", "sel.last")
            self.run_io.insert("insert", text.replace("\x00", ""))
            self.run_io.see("insert")
            if "\n" in text:
                self._enter()                   # a line break ends the line, as Enter does
        elif self.keys_wanted and self.on_keys is not None:
            self.on_keys(text)
        else:
            return False
        return True

    def _paste_from(self, selection):
        """Tk's paste events (Shift+Insert, the middle button) in Run I/O, as the Paste command.

        As with Tk's own bindings, releasing the middle button after dragging
        with it (to scroll) pastes nothing.
        """
        if selection == "PRIMARY" and int(self.run_io.tk.eval(
                "expr {[info exists ::tk::Priv(mouseMoved)] && $::tk::Priv(mouseMoved)}")):
            return "break"
        try:        # as Tk's own paste bindings read it
            text = self.run_io.tk.call("::tk::GetSelection", self.run_io._w, selection)
        except tk.TclError:                     # nothing to paste
            return "break"
        self.paste(text)
        return "break"

    def _enter(self, event=None):
        if self.run_io.typing:
            line, rest = self.run_io.send_line()
            self._output += len(line)           # it stays in Run I/O, like the output
            self.write_output("\n")
            if self.on_line is not None:
                self.on_line(line, rest)
            return "break"
        return self._key(event, "\n")

    def _key(self, event, char=None):
        """A key typed in Run I/O: into the typed line, or to on_keys at once while keys_wanted.

        Keys held with Control (but not AltGr, which is Control and Alt), Alt
        (Windows) or Command (macOS) belong to the window's menus and shortcuts.
        """
        char = event.char if char is None else char
        typed = bool(char) and (char in "\n\t\b\x7f" or _is_text(char))
        if self.run_io.typing:
            self._changed(self.run_io)          # Tk's bindings may change the line next
            if typed:
                self.run_io.to_line()           # a click or Home may have left the line
            return None
        if not self.keys_wanted or not typed or char == "\x7f" or self._shortcut(event):
            return None
        if self.on_keys is not None:
            self.on_keys(char)
        return "break"

    def _shortcut(self, event):
        """True when the key was pressed with a modifier of the window's shortcuts."""
        state = getattr(event, "state", 0)
        if self.windowing_system == "aqua":
            return bool(state & COMMAND)
        alt = WINDOWS_ALT if self.windowing_system == "win32" else COMMAND
        if state & CONTROL and state & alt:
            return False                        # AltGr: a character of the keyboard
        return bool(state & (CONTROL | alt))

    def _clicked(self, event):
        if self.messages.tag_ranges("sel"):
            return                      # the user selected text, for example to copy it
        for tag in self.messages.tag_names(f"@{event.x},{event.y}"):
            if tag in self._targets:
                self.on_click(self._targets[tag])
                return
