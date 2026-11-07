# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""What every tool has: its own window, its model, and the parts tools share.

A ToolWindow is a tool's own window, not modal (several tools can be open at
once, each once): its title bar names it, a large heading may say what it
does, then come the tool's controls, and at the bottom the group box Tool
Control with the buttons Connect to ARM (Disconnect from ARM while
connected), Reset and Close. A tool observes the program only while it is
connected; closing its window disconnects it. It opens centred over the main
window, and a dialog it opens (such as Font...) centred over it
(place_over()).

A ToolModel is what a tool observes and the numbers it keeps, without a
window: the window shows them, tests and the benchmark use the model alone.
The main window tells the tool windows about each program it loads or
unloads (machine_changed) and has them refresh after every slice of a run,
Step, Backstep, Reset and register change.
"""

import re
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from ..menubar import screen_area
from ..style import (FACE, HEADING, HIGHLIGHT, NAVY, SHADOW, TEXT, WINDOW, default_button,
                     draw_bevel, group)
from ..widgets import Tooltip, px

# Tk's "WxH+X+Y" of a window, as width, height, x and y; a position left of or above the main
# screen looks like "+-8".
GEOMETRY = re.compile(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)")
CONNECT = "Connect to ARM"
DISCONNECT = "Disconnect from ARM"
TIPS = {
    CONNECT: "Let the tool observe the program from now on",
    DISCONNECT: "Stop observing the program; what the tool shows stays",
    "Reset": "Start the tool's numbers again from zero",
    "Close": "Close the tool (it stops observing the program)",
}
CONTROL = "Tool Control"        # the group box of the buttons
MARGIN = 4                      # around a tool's window, in design pixels
GAP = 5                         # between its heading, controls and Tool Control
BAR_WIDTH = 148                 # a percentage bar, in design pixels
BAR_HEIGHT = 21
WIDEST = "100.0%"               # the widest text a percentage bar shows


class ToolModel:
    """What a tool observes and the numbers it keeps (no window).

    While connected it observes the machine given to connect() or
    observe(): the program's machine, which changes at every Assemble (None
    while no program is loaded). Subclasses install their hooks in attach()
    and remove them in detach(), and take in what happened since the last
    time in update().
    """

    def __init__(self):
        self.connected = False
        self.machine = None             # the machine observed now

    def connect(self, machine):
        """Observe the program of machine (None: the next one loaded) from now on."""
        self.connected = True
        self.observe(machine)

    def disconnect(self):
        self.observe(None)
        self.connected = False

    def observe(self, machine):
        """The program's machine is now machine (None: no program is loaded)."""
        machine = machine if self.connected else None
        if machine is self.machine:
            return
        if self.machine is not None:
            self.detach(self.machine)
        self.machine = machine
        if machine is not None:
            self.attach(machine)

    def attach(self, machine):
        """Start observing machine."""

    def detach(self, machine):
        """Stop observing machine, taking in what it did until now."""

    def reset(self):
        """Start the numbers again from zero."""

    def update(self):
        """Take in what the program did since the last update; True when something changed."""
        return False


class ToolWindow:
    """A tool's own window (see the module's description).

    Subclasses set NAME (the menu's and the title bar's), HELP (its help
    text), HEADING (the large line at the top of the window that says what
    the tool does; none when it would only repeat the title bar), MODEL
    (the model's class), and make their controls in build(); show() puts
    the model's numbers on the screen. build() also sets typed: the fields
    where Return takes what was typed and presses no button.
    """

    NAME = ""
    HELP = ""
    HEADING = ""
    MODEL = ToolModel
    typed = ()

    def __init__(self, app):
        self.app = app
        self.model = self.MODEL()
        window = self.window = tk.Toplevel(app.root)
        window.withdraw()
        window.title(self.NAME)
        window.transient(app.root)
        window.resizable(False, False)
        gap = px(window, GAP)
        content = ttk.Frame(window, padding=px(window, MARGIN))
        content.pack(fill="both", expand=True)
        if self.HEADING:
            ttk.Label(content, text=self.HEADING, style=HEADING).pack(side="top",
                                                                      pady=(0, gap))
        body = ttk.Frame(content)
        body.pack(side="top", fill="both", expand=True)
        self.build(body)
        control = group(content, CONTROL)
        control.pack(side="top", fill="x", pady=(gap, 0))
        font = tkfont.nametofont("TkDefaultFont", root=window)
        letters = -(-max(font.measure(CONNECT), font.measure(DISCONNECT)) // font.measure("0"))
        self.connect_button = ttk.Button(control, text=CONNECT, width=letters + 2,
                                         command=self.toggle_connection)
        self.reset_button = ttk.Button(control, text="Reset", command=self.reset)
        self.close_button = ttk.Button(control, text="Close", command=self.close)
        self.buttons = (self.connect_button, self.reset_button, self.close_button)
        for column, button in zip((0, 2, 4), self.buttons):
            button.grid(row=0, column=column)
        for column in (1, 3):                   # the room left over: between the buttons
            control.columnconfigure(column, weight=1)
        self.tips = {button: Tooltip(button, TIPS[button.cget("text")])
                     for button in self.buttons}
        # Return presses the button that has the focus, else Connect: it has the black frame;
        # none has it in a typed field, where Return presses no button.
        default_button(self.connect_button, self.buttons, self.typed)
        window.bind("<Return>", self._return)
        window.bind("<KP_Enter>", self._return)
        window.bind("<Escape>", lambda event: self.close())
        window.protocol("WM_DELETE_WINDOW", self.close)
        self.show()
        place_over(window, app.root)
        window.deiconify()
        self.connect_button.focus_set()

    def build(self, body):
        """Make the tool's controls in body."""

    def show(self):
        """Show the model's numbers."""

    # The buttons -----------------------------------------------------------

    def _return(self, event):
        """Return presses the button that has the focus, else Connect (ttk buttons ignore it)."""
        button = event.widget if event.widget in self.buttons else self.connect_button
        button.invoke()
        return "break"

    def toggle_connection(self):
        model = self.model
        if model.connected:
            model.disconnect()
        else:
            model.connect(self.app.machine)
        text = DISCONNECT if model.connected else CONNECT
        self.connect_button.configure(text=text)
        self.tips[self.connect_button].set_text(TIPS[text])
        self.show()

    def reset(self):
        self.model.reset()
        self.show()

    def close(self):
        """Close the window; the tool stops observing the program."""
        if self.window is None:
            return
        if self.model.connected:
            self.model.disconnect()
        self.window.destroy()
        self.window = None

    def lift(self):
        """Bring the window to the front where it is (the tool was chosen again)."""
        self.window.deiconify()
        self.window.lift()
        self.connect_button.focus_set()

    # Called by the main window --------------------------------------------------

    def machine_changed(self, machine):
        """A program was loaded (its machine) or unloaded (None)."""
        self.model.observe(machine)
        self.show()

    def refresh(self):
        """Show what the program did since the last refresh."""
        if self.model.update():
            self.show()


# Where the windows open ---------------------------------------------------------------------

def place_over(window, parent, size=None):
    """Put a window that is not shown yet centred over parent, a window on the screen, with
    its whole frame on the work area of parent's monitor (see centred()).

    Only its place is given: it keeps the size its contents ask for, or the size it was
    given, (width, height). Without
    a place, Windows opens a window that belongs to another one (a transient
    window) at the top left corner of the screen, where anything at the
    screen's edge hides its corner.
    """
    window.update_idletasks()               # the size its contents ask for
    size = size or (window.winfo_reqwidth(), window.winfo_reqheight())
    box = frame_of(parent)
    _, _, width, height, _, _ = box
    middle = (parent.winfo_rootx() + width // 2, parent.winfo_rooty() + height // 2)
    x, y = centred(size, box, screen_area(parent, *middle))
    window.geometry(f"+{x}+{y}")


def frame_of(window):
    """(x, y, width, height, side, top) of a window on the screen: the top left corner of its
    frame, the size of its inside, and the widths of its frame at the sides and the bottom
    (side) and at the top, title bar included (top).

    Tk's geometry of a maximized window keeps the place it had before, so
    that place cannot be used then: winfo_x and winfo_y tell where the frame is.
    """
    inside_x, inside_y = window.winfo_rootx(), window.winfo_rooty()
    match = GEOMETRY.fullmatch(window.wm_geometry())
    if str(window.state()) == "zoomed":
        x, y = window.winfo_x(), window.winfo_y()
    else:
        x, y = (int(match[3]), int(match[4])) if match else (inside_x, inside_y)
    return (x, y, window.winfo_width(), window.winfo_height(),
            max(0, inside_x - x), max(0, inside_y - y))


def centred(size, parent, area):
    """The top left corner of a window's frame on the screen, for the window centred over
    parent with its whole frame on area.

    size is the window's inside (width, height); parent is the window it goes
    over, as frame_of() gives it, and area is (left, top, right, bottom). The
    window's frame is taken to be as wide as parent's: on Windows a tool's
    window and the main window have the same frame (8 pixels at the sides and
    the bottom and 31 at the top at 100 %, 14 and 65 at 225 %). A window that
    would cross an edge of area is moved in from it; one larger than area is
    at its top left corner, so that its title bar is on the screen.
    """
    width, height = size
    x, y, parent_width, parent_height, side, top = parent
    left, upper, right, lower = area
    x = max(left, min(x + (parent_width - width) // 2, right - width - 2 * side))
    y = max(upper, min(y + (parent_height - height) // 2, lower - height - top - side))
    return x, y


def paragraphs(text):
    """text with the lines of each paragraph joined, for a text widget that wraps them:
    blank lines separate the paragraphs."""
    return "\n\n".join(" ".join(part.split()) for part in text.strip().split("\n\n"))


class PercentBar:
    """A Windows 98 progress bar showing a share of a whole.

    A sunken field filled from the left with navy blocks as far as the share
    reaches, and the percentage with one decimal written across its middle:
    dark on the field and white on the blocks, so it reads whatever the
    share. The blocks and the white text are on a second canvas laid over
    the filled part, which cuts them off where the share ends. Each
    gap between the blocks that the text can cross holds a small canvas on
    the second one, with a dark copy of the text in line with the white
    one: the white text lies on navy only.
    """

    def __init__(self, master, width=BAR_WIDTH):
        font = tkfont.nametofont("TkDefaultFont", root=master)
        ring, inset = px(master, 1), px(master, 2)
        width = px(master, width)
        height = max(px(master, BAR_HEIGHT), font.metrics("linespace") + 2 * inset)
        self.canvas = canvas = tk.Canvas(master, width=width, height=height, background=FACE,
                                         borderwidth=0, highlightthickness=0, takefocus=False)
        draw_bevel(canvas, 0, 0, width, height, rings=((SHADOW, HIGHLIGHT),))
        self.left = self.top = ring + px(master, 1)
        self.room = width - 2 * self.left               # the blocks' room
        inner = height - 2 * self.top
        self.text = canvas.create_text(width // 2, height // 2, text="", fill=TEXT, font=font)
        self.cover = cover = tk.Canvas(canvas, background=FACE, borderwidth=0,
                                       highlightthickness=0, takefocus=False)
        block, gap = max(1, round(inner * 2 / 3)), px(master, 2)
        for x in range(0, self.room, block + gap):
            cover.create_rectangle(x, 0, x + block, inner, fill=NAVY, width=0)
        middle, y = width // 2 - self.left, height // 2 - self.top     # the text's, on the cover
        self.cover_text = cover.create_text(middle, y, text="", fill=WINDOW, font=font)
        self.copies = [(canvas, self.text), (cover, self.cover_text)]  # (canvas, text item)
        reach = font.measure(WIDEST) // 2 + inset       # from the middle to the text's ends
        for x in range(block, self.room, block + gap):  # the gaps
            if middle - reach < x + gap and x < middle + reach:
                piece = tk.Canvas(cover, width=gap, height=inner, background=FACE,
                                  borderwidth=0, highlightthickness=0, takefocus=False)
                piece.place(x=x, y=0)
                self.copies.append((piece, piece.create_text(middle - x, y, text="", fill=TEXT,
                                                             font=font)))
        self.inner = inner
        self.shown = None               # (percentage text, pixels filled)
        self.set(0, 0)

    def set(self, part, whole):
        """Show part of whole (0 % when whole is 0), the percentage rounded half up as by
        hand (3 of 48 is 6.3 %; Python's own rounding would show 6.2 %)."""
        share = part / whole if whole else 0.0
        tenths = (2000 * part + whole) // (2 * whole) if whole else 0     # of a per cent
        self.show(f"{tenths // 10}.{tenths % 10}%", round(share * self.room))

    def show(self, text, filled):
        """Write text across the bar, with its blocks reaching filled pixels of self.room."""
        shown = (text, filled)
        if shown == self.shown:
            return
        if self.shown is None or text != self.shown[0]:
            for canvas, item in self.copies:
                canvas.itemconfigure(item, text=text)
        self.shown = shown
        if filled:
            self.cover.place(x=self.left, y=self.top, width=filled, height=self.inner)
        else:
            self.cover.place_forget()
