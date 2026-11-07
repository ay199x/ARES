# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Edit tab: one tab per open file, with line numbers, colours and a status line."""

import codecs
import os
import re
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from .. import capitals
from ..files import write_file
from .highlight import Highlighter
from .style import page_padding, sunken
from .textedit import TrackedText, line_tags, one_undo_step, put_back_line_tags
from .tabs import ClosableNotebook
from .widgets import line_spacing, px, use_shortcuts

BACKGROUND = "#FFFFFF"
GUTTER_BACKGROUND = "#F7F7F7"
LINE_NUMBER_COLOUR = "#999999"
CURRENT_LINE_BACKGROUND = "#F7FAFA"
ERROR_MARKER_COLOUR = "#E0301E"
# Lines with assembler errors carry this tag (with no look of its own), so Tk
# moves the markers with the text and drops them with their lines.
ERROR_TAG = "error_line"
UNTITLED = "untitled{}.s"
STATUS_HEIGHT = 24          # the status line, in design pixels

_INDENT = re.compile(r"[ \t]*")
_SHIFT_OR_CONTROL = 0x5                 # in a key event's state


def decode(data):
    """(text, encoding, has byte-order mark) for the bytes of a source file.

    Files that are not UTF-8 are read as Latin-1, which keeps every byte; the
    byte-order mark is not part of the text, and saving writes it back.
    """
    bom = data.startswith(codecs.BOM_UTF8)
    if bom:
        data = data[len(codecs.BOM_UTF8):]
    try:
        return data.decode("utf-8"), "utf-8", bom
    except UnicodeDecodeError:
        return data.decode("latin-1"), "latin-1", bom


def same_file(a, b):
    """True when paths a and b name the same file, however each is spelt.

    Files that exist are compared by identity, which sees through links,
    junctions and short names; other paths by their real path.
    """
    try:
        first, second = os.stat(a), os.stat(b)
    except OSError:
        first = second = None
    if first is not None and first.st_ino and second.st_ino:     # 0 where there are none
        return os.path.samestat(first, second)
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def marked_lines(text, first, last):
    """The numbers of the lines first..last with an error marker on any of their characters."""
    index, stop = f"{first}.0", f"{last}.end +1c"
    above = text.tag_prevrange(ERROR_TAG, index)
    ranges = [above] if above and text.compare(above[1], ">", index) else []
    while True:
        found = text.tag_nextrange(ERROR_TAG, index, stop)
        if not found:
            break
        ranges.append(found)
        index = found[1]
    lines = set()
    for start, end in ranges:
        lines.update(range(max(first, int(str(start).split(".")[0])),
                           min(last, int(text.index(f"{end} -1c").split(".")[0])) + 1))
    return lines


class Gutter(tk.Canvas):
    """Line numbers beside a text widget, with red markers on lines that have errors.

    Without line numbers it is a narrow column for the markers, shown only
    while a line has one.
    """

    def __init__(self, master, text, font):
        super().__init__(master, background=GUTTER_BACKGROUND, borderwidth=0,
                         highlightthickness=0, width=1, takefocus=False)
        self.text = text
        self.font = font
        self.numbers = True
        self._pending = None
        self.bind("<Configure>", lambda event: self.schedule())
        # The mouse wheel scrolls the text as it does over the text: the Text
        # class's own wheel bindings, run for the text.
        for sequence in self.tk.splitlist(self.tk.call("bind", "Text")):
            if "MouseWheel" in sequence or sequence.endswith(("Button-4>", "Button-5>")):
                self.bind(sequence, self.tk.call("bind", "Text", sequence).replace("%W", text._w))

    def schedule(self):
        """Redraw once the current changes are done."""
        if self._pending is None:
            self._pending = self.after_idle(self.redraw)

    def destroy(self):
        if self._pending is not None:
            self.after_cancel(self._pending)
            self._pending = None
        super().destroy()

    def redraw(self):
        """Draw the numbers and markers of the lines in view, or hide a gutter with neither."""
        if self._pending is not None:
            self.after_cancel(self._pending)
            self._pending = None
        self.delete("all")
        text = self.text
        if not (self.numbers or text.tag_nextrange(ERROR_TAG, "1.0")):
            if self.winfo_manager():
                self.grid_remove()
            return
        if not self.winfo_manager():
            self.grid()
        last = text.line_count()
        # A character's width at each side of the numbers; the markers go in the left one.
        pad = self.font.measure("9")
        marker = max(4, min(pad - 2, round(self.font.metrics("linespace") * 0.55)))
        width = 2 * pad
        if self.numbers:
            width += self.font.measure("9" * max(2, len(str(last))))
        if int(self.cget("width")) != width:
            self.configure(width=width)
        first = int(text.index("@0,0").split(".")[0])
        rows = []
        for line in range(first, last + 1):
            info = text.dlineinfo(f"{line}.0")
            if info is None:
                break
            rows.append((line, info))
        marked = marked_lines(text, first, first + len(rows) - 1) if rows else ()
        descent = self.font.metrics("descent")
        for line, (_, y, _, height, baseline) in rows:
            if line in marked:
                top = y + (height - marker) // 2
                self.create_oval(1, top, 1 + marker, top + marker,
                                 fill=ERROR_MARKER_COLOUR, outline=ERROR_MARKER_COLOUR)
            if self.numbers:
                self.create_text(width - pad, y + baseline + descent, anchor="se",
                                 text=str(line), fill=LINE_NUMBER_COLOUR, font=self.font)


class FileTab(tk.Frame):
    """One open file: its text with line numbers and scroll bars, in a sunken border.

    Every tab keeps room under the border for the status line, which the file on top has
    (EditorPane): a text that changed height with it would move its view.
    """

    def __init__(self, pane, name, path=None):
        super().__init__(pane.notebook)
        field = self.field = sunken(tk.Frame(self))
        field.pack(side="top", fill="both", expand=True, pady=(0, px(self, STATUS_HEIGHT)))
        self.pane = pane
        self.name = name
        self.path = path
        self.encoding = "utf-8"
        self.newline = "\n"
        self.bom = False
        self._applied = None            # the settings the text was last given (apply_settings)
        app = pane.app
        text = self.text = TrackedText(
            field, wrap="none", undo=True, autoseparators=True, maxundo=-1,
            font=app.editor_font, background=BACKGROUND, foreground="#000000",
            insertbackground="#000000", borderwidth=0, highlightthickness=0,
            padx=px(self, 4), pady=0, width=1, height=1)
        self.gutter = Gutter(field, text, app.editor_font)
        yscroll = ttk.Scrollbar(field, orient="vertical", command=text.yview,
                                style="Editor.Vertical.TScrollbar")
        xscroll = ttk.Scrollbar(field, orient="horizontal", command=text.xview,
                                style="Editor.Horizontal.TScrollbar")

        def scrolled(*args):
            yscroll.set(*args)
            self.gutter.schedule()
        text.configure(yscrollcommand=scrolled, xscrollcommand=xscroll.set)
        self.gutter.grid(row=0, column=0, sticky="ns")
        text.grid(row=0, column=1, sticky="nsew")
        yscroll.grid(row=0, column=2, sticky="ns")
        xscroll.grid(row=1, column=0, columnspan=2, sticky="ew")
        field.rowconfigure(0, weight=1)
        field.columnconfigure(1, weight=1)

        # Keep the selection visible while another window (Find) has the focus;
        # on Windows Tk hides it by default.
        text.configure(inactiveselectbackground=text.cget("selectbackground"))
        text.tag_configure("current_line", background=CURRENT_LINE_BACKGROUND)
        text.tag_lower("current_line")
        text.line_marks = (ERROR_TAG,)  # a marker anywhere on a line marks the line
        self.highlighter = Highlighter(text, app.editor_bold)
        self._changes = None
        text.add_change_listener(self._changed)
        text.add_cursor_listener(self._cursor_moved)
        use_shortcuts(text)
        text.bind("<Tab>", self._tab)
        text.bind("<Return>", self._newline)
        text.bind("<KP_Enter>", self._newline)
        self._was_modified = False
        self.apply_settings()
        self._cursor_moved()

    # State ---------------------------------------------------------------

    @property
    def modified(self):
        return bool(self.text.edit_modified())

    def title(self):
        """The file name, with * while there are unsaved changes."""
        return self.name + ("*" if self.modified else "")

    def get_text(self):
        return self.text.get("1.0", "end-1c")

    def can_undo(self):
        return bool(self.text.tk.call(self.text._w, "edit", "canundo"))

    def can_redo(self):
        return bool(self.text.tk.call(self.text._w, "edit", "canredo"))

    def undo(self):
        if self.can_undo():
            self._undo_or_redo(self.text.edit_undo)

    def redo(self):
        if self.can_redo():
            self._undo_or_redo(self.text.edit_redo)

    def _undo_or_redo(self, edit):
        """Undo or redo between two separators, as Tk's own Undo key does.

        An undo can take away the separator on top of the undo stack; the
        next typing would then join the step below it. Tk puts text back
        without its tags; where a step replaces lines with as many lines
        (Capitalize Instructions), those that had error markers keep them.
        """
        text = self.text
        marked = self.error_lines()
        before = self.get_text() if marked else None
        separators = text.cget("autoseparators")
        self._changes = []
        try:
            if separators:
                text.edit_separator()
            edit()
            if separators:
                text.edit_separator()
        finally:
            changes, self._changes = self._changes, None
        # Only a step that changed nothing but letter case keeps the lines'
        # markers; after any other, a marker could land on a line that came back.
        if len(changes) == 2 and self.get_text().lower() == (before or "").lower():
            (first, removed, added), again = changes
            if added == 1 and again == (first, 1, removed):
                last = first + removed - 1
                put_back_line_tags(text, first, last, [(line, {ERROR_TAG}) for line in marked
                                                       if first <= line <= last])
        # The change listeners ran in the middle of the undo or redo, before Tk
        # moved the step to the other stack and, back at the saved text,
        # cleared the modified flag: update everything again.
        text.see("insert")
        self._sync_modified()

    def _sync_modified(self):
        """Show the modified mark as it is now, and update the window."""
        if self.modified != self._was_modified:
            self._was_modified = self.modified
            self.pane.tab_changed(self)
        else:
            self.pane.app.editor_changed()

    # Files ---------------------------------------------------------------

    def load(self, path):
        """Read a file into the tab, replacing its text (raises OSError).

        Line ends are kept: CR LF, LF, or CR in a file with no other. A file
        that mixes CR LF and LF is saved with the more common of the two (LF
        if neither is), and any other CR stays a character of its line; so a
        file saved without changes is written back byte for byte unless it
        mixes line ends.
        """
        path = Path(path)
        self._read(path)
        self.path = path
        self.name = path.name
        self._saved()

    def load_copy(self, path):
        """Read a file into the tab as a new file of the same name that is not saved yet (raises
        OSError). The tab has no path, so Save asks where; Undo goes back to this text, no
        further, and the tab stays marked as unsaved until it is saved.
        """
        path = Path(path)
        self._read(path)
        self.name = path.name
        self.text.edit_modified(True)
        self._was_modified = True

    def _read(self, path):
        """Put the text of the file at path in the tab, with an empty undo history."""
        text, self.encoding, self.bom = decode(path.read_bytes())
        if "\r" in text and "\n" not in text:
            self.newline, text = "\r", text.replace("\r", "\n")
        else:
            crlf = text.count("\r\n")
            self.newline = "\r\n" if crlf > text.count("\n") - crlf else "\n"
            text = text.replace("\r\n", "\n")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.text.edit_reset()
        self.text.mark_set("insert", "1.0")
        self.text.see("1.0")

    def save(self, path=None):
        """Write the text to path (default: its own file); raises OSError.

        A save that fails leaves the file as it was (write_file).
        """
        path = Path(path) if path is not None else self.path
        text = self.get_text().replace("\n", self.newline)
        try:
            data = text.encode(self.encoding)
            encoding = self.encoding
        except UnicodeEncodeError:          # a character Latin-1 cannot hold was typed
            data, encoding = text.encode("utf-8"), "utf-8"
        if self.bom:
            data = codecs.BOM_UTF8 + data
        write_file(path, data)
        self.encoding = encoding
        self.path = path
        self.name = path.name
        self._saved()

    def _saved(self):
        """The text now equals the file: clear the modified mark."""
        self.text.edit_modified(False)
        self._was_modified = False
        self.pane.tab_changed(self)

    # Editing -------------------------------------------------------------

    def _tab(self, event=None):
        """Tab: spaces to the next tab stop, or a tab character, as set.

        With Shift or Control held, Tk's own Text bindings handle the key.
        """
        if event is not None and event.state & _SHIFT_OR_CONTROL:
            return None
        settings = self.pane.app.settings
        size = settings.tab_size
        if settings.tab_spaces:
            self._type(lambda before: " " * (size - len(before.expandtabs(size)) % size))
        else:
            self._type(lambda before: "\t")
        return "break"

    def _newline(self, event=None):
        """Enter: a new line indented like the one before it."""
        self._type(lambda before: "\n" + _INDENT.match(before).group())
        if self.text.cget("autoseparators"):
            self.text.edit_separator()
        return "break"

    def _type(self, chars):
        """Type the text chars(text left of the cursor) gives, as a key does.

        Like typing, it replaces a selection the cursor is in, in the same
        undo step; the selection goes first, so chars sees what is left.
        """
        text = self.text
        if text.tag_ranges("sel") and text.compare("sel.first", "<=", "insert") \
                and text.compare("insert", "<=", "sel.last"):
            with one_undo_step(text):
                text.delete("sel.first", "sel.last")
                text.tk.call("tk::TextInsert", text._w,
                             chars(text.get("insert linestart", "insert")))
        else:
            text.tk.call("tk::TextInsert", text._w, chars(text.get("insert linestart", "insert")))

    def select_line(self, line):
        """Select a line's text, put the cursor at its start and show it."""
        self.text.tag_remove("sel", "1.0", "end")
        self.text.tag_add("sel", f"{line}.0", f"{line}.0 lineend")
        self.text.mark_set("insert", f"{line}.0")
        self.text.see(f"{line}.0")

    def capitalize(self):
        """Apply the capital-letters rule to the whole file as one edit and one undo step.

        Line tags (error markers) stay on their lines, through Undo and Redo
        too, and the cursor where it was. Returns the number of lines changed.
        """
        old = self.get_text().split("\n")
        new = capitals.capitalize("\n".join(old)).split("\n")
        changed = [number for number, (line, was) in enumerate(zip(new, old), 1) if line != was]
        if not changed:
            return 0
        # One edit from the first changed line to the last: Tk undoes a step
        # edit by edit, each with every listener. The line count stays.
        first, last = changed[0], changed[-1]
        text = self.text
        insert = text.index("insert")
        tags = [(line, line_tags(text, line)) for line in range(first, last + 1)]
        with one_undo_step(text):
            text.replace(f"{first}.0", f"{last}.end", "\n".join(new[first - 1:last]))
        put_back_line_tags(text, first, last, tags)
        text.mark_set("insert", insert)
        return len(changed)

    def set_error_lines(self, lines):
        """Mark lines with assembler errors in the gutter (until the next assemble)."""
        self.text.tag_remove(ERROR_TAG, "1.0", "end")
        for line in lines:
            self.text.tag_add(ERROR_TAG, f"{line}.0", f"{line}.0 lineend +1c")
        self.gutter.redraw()

    def error_lines(self):
        """The numbers of the lines marked with errors, where those lines are now."""
        return marked_lines(self.text, 1, self.text.line_count())

    def apply_settings(self):
        """Give the text the editor's settings, when they changed.

        Tk lays every line of a text out again when its tab stops are set, even
        to the same ones: in a 2,000-line file at 4K that is most of the time
        a setting of the tables takes.
        """
        settings = self.pane.app.settings
        font = self.pane.app.editor_font
        applied = (font.cget("family"), font.cget("size"), settings.tab_size,
                   settings.show_line_numbers)
        if applied == self._applied:
            return
        self._applied = applied
        above, below = line_spacing(self.text, font)
        self.text.configure(tabs=(font.measure(" " * settings.tab_size),),
                            tabstyle="wordprocessor", spacing1=above, spacing3=below)
        self.gutter.numbers = settings.show_line_numbers
        self.gutter.redraw()

    def _changed(self, first, removed, added):
        if self._changes is not None:           # in an undo or redo
            self._changes.append((first, removed, added))
        self.gutter.schedule()
        self._sync_modified()

    def _cursor_moved(self):
        text = self.text
        text.tag_remove("current_line", "1.0", "end")
        text.tag_add("current_line", "insert linestart", "insert lineend +1c")
        if self.pane.current is self:
            self.pane.show_position()


class EditorPane(tk.Frame):
    """The Edit tab: a notebook with one tab per open file, and the status line.

    Its master is the window's notebook of the Edit and Execute tabs. The
    status line shows in the tab on top, under its text, and not while no
    file is open.
    """

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.tabs = []
        self._untitled = 0
        self.notebook = ClosableNotebook(self, app.close_images)
        self.notebook.pack(side="top", fill="both", expand=True)
        self.status = status = tk.Frame(self, height=px(self, STATUS_HEIGHT))
        status.pack_propagate(False)
        self.position = ttk.Label(status)
        self.position.pack(side="left")
        self.line_numbers = tk.BooleanVar(master=self, value=app.settings.show_line_numbers)
        ttk.Checkbutton(status, text="Show Line Numbers", variable=self.line_numbers,
                        command=self._toggle_line_numbers, takefocus=False).pack(side="left")
        self.notebook.bind("<<NotebookTabChanged>>", self._selected, add="+")
        self.notebook.bind("<<CloseTab>>", self._close_clicked)

    @property
    def current(self):
        """The tab on top, or None when no file is open."""
        selected = self.notebook.select()
        for tab in self.tabs:
            if str(tab) == selected:
                return tab
        return None

    def new_file(self):
        self._untitled += 1
        return self._add(FileTab(self, UNTITLED.format(self._untitled)))

    def open_file(self, path):
        """Open a file in a new tab (raises OSError)."""
        tab = FileTab(self, Path(path).name, Path(path))
        return self._filled(tab, tab.load, path)

    def open_copy(self, path):
        """Open a copy of a file in a new tab, as a new file not saved yet (raises OSError)."""
        tab = FileTab(self, Path(path).name)
        return self._filled(tab, tab.load_copy, path)

    def _filled(self, tab, load, path):
        """Add a tab once load(path) has filled it; it goes away when that fails."""
        try:
            load(path)
        except (OSError, tk.TclError):
            tab.destroy()
            raise
        return self._add(tab)

    def _add(self, tab):
        self.tabs.append(tab)
        self.notebook.add(tab, text=tab.title(), padding=page_padding(self))
        self.select(tab)
        tab.text.focus_set()
        return tab

    def find(self, path):
        """The tab showing the file at path, or None."""
        for tab in self.tabs:
            if tab.path is not None and same_file(tab.path, path):
                return tab
        return None

    def select(self, tab):
        """Bring a tab to the top, and the Edit tab to the front of the window.

        (<<NotebookTabChanged>> would only come later.)
        """
        self.master.select(self)
        self.notebook.select(tab)
        self._selected()

    def remove(self, tab):
        """Close a tab without asking anything."""
        self.tabs.remove(tab)
        self.notebook.forget(tab)
        tab.destroy()
        current = self.current
        if current is not None:
            current.text.focus_set()
        self._selected()

    def tab_changed(self, tab):
        """Show a tab's new name or modified mark."""
        if tab in self.tabs:
            self.notebook.tab(tab, text=tab.title())
        self.app.editor_changed()

    def show_position(self):
        tab = self.current
        if tab is None:
            self.position.configure(text="")
        else:
            line, column = tab.text.index("insert").split(".")
            self.position.configure(text=f"Line: {line}  Column: {int(column) + 1}")

    def apply_settings(self):
        self.line_numbers.set(self.app.settings.show_line_numbers)
        for tab in self.tabs:
            tab.apply_settings()

    def _toggle_line_numbers(self):
        self.app.settings.show_line_numbers = self.line_numbers.get()
        self.app.apply_settings()

    def _selected(self, event=None):
        tab = self.current
        if tab is None:
            self.status.place_forget()
        else:
            self.status.place(in_=tab, relx=0, rely=1, relwidth=1, anchor="sw")
            self.status.lift()
        self.show_position()
        self.app.editor_changed()

    def _close_clicked(self, event=None):
        for tab in self.tabs:
            if str(tab) == self.notebook.closing:
                self.app.close_tab(tab)
                return
