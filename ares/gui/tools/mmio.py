# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Tools > Keyboard and Display MMIO Simulator: a keyboard and a text display on the
DE1-SoC's JTAG UART.

The display shows what the program stores to the JTAG UART's data register,
as Run I/O does; a form feed clears it, and a bell makes it a grid of
characters with a cursor the program places. Keys typed in the keyboard area
go to the JTAG UART's input at once, as keys typed in Run I/O while the
program runs do. The JTAG UART reports what it outputs to the connected tool
itself (ares.observers), so the tool adds no hook to the emulator and costs
nothing for a program that does not use the JTAG UART.
"""

import codecs
import re
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from ...settings import FONT_SIZES
from ..dialogs import font_families
from ..messages import COMMAND, CONTROL, WINDOWS_ALT, _is_text
from ..style import SCROLLBAR_WIDTH, TEXT, default_button, group, sunken
from ..style import WINDOW as FIELD
from ..widgets import TAB_STOP, ReadOnlyText, Tooltip, px, show_bar, tab_moves_on
from .frame import ToolModel, ToolWindow, place_over

COLUMNS, ROWS = 64, 16          # the display in characters, and its grid after a bell
KEYBOARD_ROWS = 4
LIMIT = 100_000                 # characters an area keeps (the newest)
BATCH = 4096                    # values written that are taken in without waiting for update()
BELL, FORM_FEED = 0x07, 0x0C
_SPECIAL = re.compile(b"[%c%c]" % (BELL, FORM_FEED))
_LINE_OR_TAB = re.compile("(\n|\t)")

DISPLAY_TITLE = "Display: what the program stores to the JTAG UART (0xFF201000)"
KEYBOARD_TITLE = "Keyboard: keys typed here go to the JTAG UART's input"
RESET_TIP = "Clear the display and the keyboard area"
FONT_TIP = "Choose the font of the display and the keyboard area"
SAMPLE = "Hello, JTAG UART! 0123456789"

HELP = """\
The Keyboard and Display MMIO Simulator is a keyboard and a text display on the JTAG UART
of the DE1-SoC computer: the serial port at 0xFF201000 that programs use for text input
and output through memory-mapped I/O (MMIO), reading and writing its registers as memory.

Click Connect to ARM, then run the program (Go, Step). While the tool is connected, the
display shows what the program writes to the JTAG UART, and keys typed in the keyboard
area go to the program. Disconnect from ARM stops this; what the tool shows stays. Close
closes the tool.

Display: what the program stores to the JTAG UART's data register (0xFF201000) appears in
the display at once, as it does in Run I/O, which keeps showing it: the low byte of each
value stored, the bytes read as UTF-8 text. Text printed by system calls (SVC) appears only
in Run I/O. Long lines wrap, and the display keeps the
newest 100,000 characters. A program never has to wait before it writes: the JTAG UART's
control register (0xFF201004) always reports room for 64 characters in its bits 31-16, and
each character shows at once.

Keyboard: each key typed in the keyboard area goes at once to the JTAG UART's input and
appears in the area. Return gives a line feed (10), Tab 9 and BackSpace 8, which also takes
the last character away in the area; Paste types the clipboard's text. The program reads
the input from the data register (0xFF201000), a byte at each read: bit 15 (RVALID) is 1
when a byte is there, bits 7-0 are the byte and bits 31-16 count the bytes still waiting
after it. A key outside ASCII comes as its UTF-8 bytes. ARES has no interrupts: a program
reads the data register again and again until RVALID is 1.

The keyboard area and Run I/O type into the same input: keys typed in Run I/O while the
program runs go there too, and keys the program has not read when a read service (such as
SVC #5 or SVC #8) waits become the start of the line it reads. While a read service waits
for its line, type the line in Run I/O. The keyboard area takes keys while the tool is
connected and a program is assembled and ready, running or paused; at other times a key
rings the bell.

Two characters do more on the display. A form feed (12) clears it. A bell (7) moves the
display's cursor to a column and a row given in the other bits of the word stored with it:
the column in bits 31-20 and the row in bits 19-8 (store the word with STR; a byte stored
with STRB moves the cursor to column 0, row 0). Column 0, row 0 is the top left corner; a
column or row past the edge counts as the last one.

From the first bell on, the display is a grid of 64 columns and 16 rows, filled with
spaces. Each character replaces the one at the cursor, which moves one column right, from
the last column to the start of the next row; in the bottom right corner it stays. A line
feed (10) moves the cursor to the start of the next row (on the bottom row, to its own
start), a carriage return (13) to the start of its row, a tab (9) to the next column that
is a multiple of 8, and a BackSpace (8) one column left. A form feed fills the grid with
spaces again and moves the cursor to column 0, row 0. Below the display the tool shows the
cursor's column and row, and the size of the grid. With the grid a program can draw a
screen of text, such as the board of a game.

Reset clears the display and the keyboard area, and makes the display plain text again.
Nothing else clears them: they keep their text when the program is assembled again, reset
(Reset, F12) or stepped back, and when its file is closed; the tool stays connected.

Font... chooses the font of the display and the keyboard area. The display stays 64
characters wide and 16 lines high, and the window takes the size the font needs.

The JTAG UART is the one of the DE1-SoC computer as CPUlator simulates it, so programs that
use it run there as well; clearing with a form feed and moving the cursor with a bell are
features of this tool's display.
"""


class Area:
    """The text one of the tool's areas shows, and how it changed, for its window to follow.

    Its lines are broken as the area wraps them: a line break goes before a
    character that would go past its last column (a tab goes on to the next
    multiple of TAB_STOP). So the window's text has no long lines, which Tk
    lays out in a time that grows with the square of their length when it
    wraps them itself (a refresh takes seconds for a line of 60,000 characters).

    state is (version, added, dropped): a new version replaced the whole
    text; within a version, added characters were added at the end and
    dropped ones taken from the start, so a window that showed the text at
    an earlier state of the same version adds and drops the difference.
    """

    def __init__(self, columns=COLUMNS):
        self.columns = columns
        self.text = ""
        self.column = 0                 # where the last line ends
        self.version = 0
        self.added = self.dropped = 0

    @property
    def state(self):
        return self.version, self.added, self.dropped

    def add(self, text):
        """Add text at the end; past LIMIT characters the oldest go, down to nine tenths."""
        text = self._broken(text)
        if not text:
            return
        self.text += text
        self.added += len(text)
        if len(self.text) > LIMIT:
            drop = len(self.text) - LIMIT * 9 // 10
            self.text = self.text[drop:]
            self.dropped += drop

    def replace(self, text):
        self.column = 0
        self.text = self._broken(text)[-LIMIT:]
        self.version += 1
        self.added = self.dropped = 0

    def _broken(self, text):
        """text, going on after the last line, with its lines broken at the last column.

        A return shows nothing: Tk would give it a column of its own, also when the line feed
        after it comes later.
        """
        columns, column, parts = self.columns, self.column, []
        for part in _LINE_OR_TAB.split(text.replace("\r", "")):
            if part == "\n":
                column = 0
            elif part:
                if column == columns:           # the line is full: the part starts the next
                    parts.append("\n")
                    column = 0
                if part == "\t":
                    column = min(column - column % TAB_STOP + TAB_STOP, columns)
                else:
                    room = columns - column
                    lines = [part[:room]] + [part[start:start + columns]
                                             for start in range(room, len(part), columns)]
                    column = (column if len(lines) == 1 else 0) + len(lines[-1])
                    part = "\n".join(lines)
            parts.append(part)
        self.column = column
        return "".join(parts)


class KeyboardDisplayModel(ToolModel):
    """The display and the keyboard area: what the program stored to the JTAG UART while the
    tool was connected, and the keys typed for it.

    The display is text (display.text: the bytes as UTF-8, as Run I/O shows
    them, zero bytes left out, its lines broken at the last column) until
    the program writes a bell. From then on it is a grid of rows of columns
    characters with a cursor at column x of row y, and display.text shows
    the grid row by row. The values written wait until update() takes them
    in, or until BATCH of them wait.
    """

    def __init__(self, columns=COLUMNS, rows=ROWS):
        super().__init__()
        self.columns, self.rows = columns, rows
        self.display, self.keyboard = Area(columns), Area(columns)
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._changed = False           # the display changed since the last update()
        self.reset()

    def attach(self, machine):
        self._decoder.reset()           # each program's output starts afresh, as in Run I/O
        machine.observers.watch_jtag(self, self._written)

    def detach(self, machine):
        self.update()
        machine.observers.forget(self)

    def reset(self):
        """Clear both areas, and make the display text again."""
        self._values = []               # written before the Reset: not shown
        self._decoder.reset()
        self.grid = None
        self.x = self.y = 0
        self.keys = ""                  # the keys the keyboard area shows, its lines not broken
        self.display.replace("")
        self.keyboard.replace("")

    def update(self):
        self._take_in()
        changed, self._changed = self._changed, False
        return changed

    @property
    def cursor(self):
        """(column, row) where the next character goes on the grid; None while the display is
        text."""
        if self.grid is None:
            return None
        if self.x < self.columns:
            return self.x, self.y
        return (0, self.y + 1) if self.y + 1 < self.rows else (self.columns - 1, self.y)

    def typed(self, text):
        """Show keys typed for the program in the keyboard area, as the program gets them (a
        half of a surrogate pair as ?); a BackSpace takes the character before it away."""
        text = text.encode("utf-8", "replace").decode("utf-8")
        if "\b" not in text:
            self.keys = (self.keys + text)[-LIMIT:]
            self.keyboard.add(text)
            return
        first, *rest = text.split("\b")
        keys = self.keys + first
        for part in rest:
            keys = keys[:-1] + part
        self.keys = keys[-LIMIT:]
        self.keyboard.replace(self.keys)

    # What the program writes ------------------------------------------------------------

    def _written(self, value):
        """The program stored value to the JTAG UART's data register (Observers.watch_jtag)."""
        values = self._values
        values.append(value)
        if len(values) >= BATCH:
            self._take_in()

    def _take_in(self):
        """Show the values written since the last time."""
        values, self._values = self._values, []
        if not values:
            return
        self._changed = True
        data = bytes(value & 0xFF for value in values)
        start = 0
        for special in _SPECIAL.finditer(data):
            at = special.start()
            self._show(data[start:at])
            if data[at] == FORM_FEED:
                self._form_feed()
            else:
                self._bell(values[at])
            start = at + 1
        self._show(data[start:])
        if self.grid is not None:
            self.display.replace("\n".join("".join(row) for row in self.grid))

    def _show(self, data):
        text = self._decoder.decode(data).replace("\x00", "")     # a zero byte shows nothing
        if self.grid is None:
            self.display.add(text)
        else:
            for char in text:
                self._put(char)

    def _form_feed(self):
        """Clear the display; the grid's cursor goes back to the top left."""
        if self.grid is None:
            self.display.replace("")
        else:
            self._fill()

    def _bell(self, value):
        """Move the cursor to the column in bits 31-20 of value and the row in bits 19-8, at
        most the last ones; the first bell makes the display a grid of spaces."""
        if self.grid is None:
            self._fill()
        self.x = min((value >> 20) & 0xFFF, self.columns - 1)
        self.y = min((value >> 8) & 0xFFF, self.rows - 1)

    def _fill(self):
        self.grid = [[" "] * self.columns for _ in range(self.rows)]
        self.x = self.y = 0

    def _put(self, char):
        """Write char at the cursor and move on; a line feed, carriage return, tab or
        BackSpace moves the cursor instead."""
        if char == "\n":
            self.x, self.y = 0, min(self.y + 1, self.rows - 1)
        elif char == "\r":
            self.x = 0
        elif char == "\t":
            self.x = min((self.x // TAB_STOP + 1) * TAB_STOP, self.columns)
        elif char == "\b":
            self.x = max(self.x - 1, 0)
        else:
            if self.x == self.columns:          # after the last column: on in the next row,
                if self.y + 1 < self.rows:      # but the bottom right cell stays the last
                    self.x, self.y = 0, self.y + 1
                else:
                    self.x = self.columns - 1
            self.grid[self.y][self.x] = char
            self.x += 1


class KeyboardDisplayWindow(ToolWindow):
    """Tools > Keyboard and Display MMIO Simulator."""

    NAME = "Keyboard and Display MMIO Simulator"
    HELP = HELP
    MODEL = KeyboardDisplayModel

    def __init__(self, app):
        pane = app.pane_font            # Run I/O's font, until Font... chooses another
        self.font = tkfont.Font(root=app.root, family=pane.cget("family"), size=pane.cget("size"))
        self.font_dialog = None
        super().__init__(app)
        self.tips[self.reset_button].set_text(RESET_TIP)
        # Font... is a push button too: while it has the focus, Return presses it.
        self.buttons += (self.font_button,)
        default_button(self.connect_button, self.buttons, self.typed)

    def build(self, body):
        gap = px(body, 6)
        model = self.model
        self._shown = {}                # each area's text -> the area's state it shows
        self.windowing_system = body._windowingsystem   # which keys are the shortcuts' modifiers
        box = group(body, DISPLAY_TITLE)
        box.pack(fill="x")
        self.display, self.display_bar = _field(box, self.font, model.columns, model.rows,
                                                takefocus=False, insertwidth=0)
        tab_moves_on(self.display)      # once a click put the focus there
        line = ttk.Frame(box)
        line.pack(fill="x", pady=(gap, 0))
        self.font_button = ttk.Button(line, text="Font...", command=self.choose_font)
        self.font_button.pack(side="left")
        self.status = ttk.Label(line, text="")
        self.status.pack(side="left", padx=(gap, 0))
        self.font_tip = Tooltip(self.font_button, FONT_TIP)
        box = group(body, KEYBOARD_TITLE)
        box.pack(fill="x", pady=(gap, 0))
        self.keyboard, self.keyboard_bar = _field(box, self.font, model.columns, KEYBOARD_ROWS,
                                                  insertbackground=TEXT)
        keyboard = self.keyboard
        keyboard.bind("<KeyPress>", self._key)
        for sequence in ("<Return>", "<KP_Enter>"):     # never Connect, the default button
            keyboard.bind(sequence, lambda event: self._key(event, "\n") or "break")
        keyboard.bind("<<Paste>>", self._paste)
        self.typed = (keyboard,)

    def show(self):
        model = self.model
        self._follow(self.display, model.display)
        self._follow(self.keyboard, model.keyboard)
        area, cursor = f"{model.columns} x {model.rows}", model.cursor
        status = (f"Area {area}" if cursor is None
                  else f"Cursor ({cursor[0]}, {cursor[1]}), area {area}")
        if self.status.cget("text") != status:
            self.status.configure(text=status)

    def _follow(self, text, area):
        """Bring text, which shows area as it was at an earlier state, up to date."""
        shown = self._shown.get(text)
        if shown == area.state:
            return
        version, added, dropped = shown or (None, 0, 0)
        new = area.added - added
        if version != area.version or new > len(area.text):
            text.clear()
            text.write(area.text)
        else:
            if new:
                text.write(area.text[-new:])
            if area.dropped > dropped:
                text.tk.call(text._original, "delete", "1.0",
                             f"1.0 + {area.dropped - dropped} chars")
        self._shown[text] = area.state
        text.mark_set("insert", "end")
        text.see_end()

    def reset(self):
        super().reset()
        self.keyboard.focus_set()       # ready for typing again

    def choose_font(self):
        self.font_dialog = FontDialog(self.window, self.font)

    # The keyboard ----------------------------------------------------------------------

    def _key(self, event, char=None):
        """A key typed in the keyboard area: a character, as Run I/O takes them, goes to the
        program (type_keys()); moving and function keys and keys held with a modifier of
        shortcuts (copying, for one) are left to Tk."""
        char = event.char if char is None else char
        if not char or self._shortcut(event) or not (char in "\n\t\b" or _is_text(char)):
            return None
        self.type_keys(char)
        return "break"

    def _shortcut(self, event):
        """True when the key was held with a modifier of shortcuts, as Run I/O decides:
        Control (but not AltGr, which is Control and Alt), Alt (Windows) or Command (macOS)."""
        state = getattr(event, "state", 0)
        system = self.windowing_system
        if system == "aqua":
            return bool(state & COMMAND)
        alt = WINDOWS_ALT if system == "win32" else COMMAND
        if state & CONTROL and state & alt:
            return False
        return bool(state & (CONTROL | alt))

    def _paste(self, event=None):
        """Paste: the clipboard's text, as typed keys."""
        try:        # as Tk's own paste bindings read it
            text = self.keyboard.tk.call("::tk::GetSelection", self.keyboard._w, "CLIPBOARD")
        except tk.TclError:                     # nothing to paste
            return "break"
        if text:
            self.type_keys(text)
        return "break"

    def type_keys(self, text):
        """Give text to the program as keys typed in Run I/O while it runs, and show it in
        the keyboard area; True when the program could take keys now (the tool is
        connected and Run I/O would pass keys on), else the bell rings."""
        messages = self.app.messages
        if self.model.machine is None or not messages.keys_wanted:
            self.keyboard.bell()
            return False
        messages.on_keys(text)
        self.model.typed(text)
        self.show()
        return True


def _field(master, font, columns, rows, **options):
    """A white sunken field of columns x rows characters, lines wrapped, with a vertical
    scroll bar while its text does not fit; returns (its read-only text, the bar).

    The bar's room is kept when the bar is hidden, so the field keeps its
    size and the text its lines.
    """
    field = sunken(tk.Frame(master, background=FIELD))
    field.pack(fill="x")
    text = ReadOnlyText(field, font=font, width=columns, height=rows, wrap="char",
                        background=FIELD, foreground=TEXT, borderwidth=0, highlightthickness=0,
                        padx=px(field, 4), pady=px(field, 2), **options)
    bar = ttk.Scrollbar(field, orient="vertical", command=text.yview)
    text.grid(row=0, column=0, sticky="nsew")
    bar.grid(row=0, column=1, sticky="ns")
    bar.grid_remove()
    field.columnconfigure(1, minsize=px(field, SCROLLBAR_WIDTH))

    def scrolled(first, last):
        bar.set(first, last)
        show_bar(bar, float(first) > 0 or float(last) < 1)
    text.configure(yscrollcommand=scrolled)
    return text, bar


class FontDialog:
    """Font...: the family and size of the font of the display and the keyboard area.

    It is modal, and opens centred over the tool's window (place_over()). OK
    gives font (the areas' font) the family and size chosen, if the size is
    one of FONT_SIZES; Cancel, Escape and the close box leave it as it was.
    """

    def __init__(self, master, font):
        self.font = font
        window = self.window = tk.Toplevel(master)
        window.withdraw()
        window.title("Font")
        window.transient(master)
        window.resizable(False, False)
        self.families = font_families(window)
        family, size = font.cget("family"), font.cget("size")
        self.family = tk.StringVar(master=window, value=family)
        self.size = tk.StringVar(master=window, value=str(size))
        self.preview_font = tkfont.Font(root=window, family=family, size=size)

        gap = px(window, 6)
        body = ttk.Frame(window, padding=2 * gap)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, pad=2 * gap)        # space between the labels and the fields
        ttk.Label(body, text="Font:").grid(row=0, column=0, sticky="w", pady=gap)
        self.family_box = ttk.Combobox(body, textvariable=self.family, values=self.families,
                                       state="readonly", width=28)
        self.family_box.grid(row=0, column=1, sticky="we", pady=gap)
        ttk.Label(body, text="Size:").grid(row=1, column=0, sticky="w", pady=gap)
        ttk.Spinbox(body, textvariable=self.size, from_=FONT_SIZES.start,
                    to=FONT_SIZES.stop - 1, width=5).grid(row=1, column=1, sticky="w", pady=gap)
        field = sunken(ttk.Frame(body))
        field.grid(row=2, column=0, columnspan=2, sticky="we", pady=gap)
        self.preview = tk.Label(field, text=SAMPLE, font=self.preview_font, anchor="w",
                                background=FIELD, foreground=TEXT, borderwidth=0, padx=gap,
                                pady=gap)
        self.preview.pack(fill="x")
        self.status = ttk.Label(body, text="", foreground="#B00000")
        self.status.grid(row=3, column=0, columnspan=2, sticky="w")
        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(gap, 0))
        ok = ttk.Button(buttons, text="OK", command=self.ok)
        ok.pack(side="left", padx=(0, gap))
        cancel = ttk.Button(buttons, text="Cancel", command=self.cancel)
        cancel.pack(side="left")
        # Return presses the button that has the focus, else OK: it has the black frame.
        default_button(ok, (ok, cancel))

        for variable in (self.family, self.size):
            variable.trace_add("write", self._update_preview)
        window.bind("<Return>", self._return)
        window.bind("<KP_Enter>", self._return)
        window.bind("<Escape>", lambda event: self.cancel())
        window.protocol("WM_DELETE_WINDOW", self.cancel)
        place_over(window, master)
        window.deiconify()
        window.grab_set()
        self.family_box.focus_set()

    def _size(self):
        """The size typed, or None when it is not one of FONT_SIZES."""
        try:
            size = int(self.size.get())
        except ValueError:
            return None
        return size if size in FONT_SIZES else None

    def _update_preview(self, *args):
        size = self._size()
        if size is not None:
            self.preview_font.configure(family=self.family.get(), size=size)

    def _return(self, event):
        """Return presses the button that has the focus, else OK (ttk buttons ignore Return)."""
        if isinstance(event.widget, ttk.Button):
            event.widget.invoke()
        else:
            self.ok()
        return "break"

    def ok(self):
        size = self._size()
        if size is None:
            self.status.configure(text=f"Size must be {FONT_SIZES.start} to "
                                       f"{FONT_SIZES.stop - 1}.")
            self.window.bell()
            return
        self.font.configure(family=self.family.get(), size=size)
        self.close()

    def cancel(self):
        self.close()

    def close(self):
        if self.window is not None:
            self.window.destroy()
            self.window = None


WINDOW = KeyboardDisplayWindow
