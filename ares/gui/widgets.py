# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Small widgets and helpers shared by the parts of the window."""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

TOOLTIP_DELAY = 600             # milliseconds the mouse rests before a tooltip shows
TOOLTIP_BACKGROUND = "#B8CFE5"
LINE_HEIGHT = 17 / 12           # a line of the editor and the message panes, in font sizes
# Bind tag for the window's keyboard shortcuts on text widgets: it comes before
# the Text class, whose own bindings for Ctrl+O, Ctrl+K, Ctrl+T, undo, copy ...
# would otherwise run as well.
SHORTCUT_TAG = "AresShortcuts"
TAB_STOP = 8                    # characters ("0") between a text's tab stops, as Tk has them
# Marks of a text with hiding scroll bars: after its first character (back at 1.0 once the
# start is deleted), at the start of the last line measured and of the widest line before it.
START, LAST, WIDEST = "bars_start", "bars_last", "bars_widest"
FEW_CHARACTERS = 32             # a text of no more different characters: count each one


def use_shortcuts(widget):
    """Give the window's keyboard shortcuts priority over the widget's class bindings."""
    tags = list(widget.bindtags())
    if SHORTCUT_TAG not in tags:
        tags.insert(1, SHORTCUT_TAG)
        widget.bindtags(tuple(tags))


def line_spacing(widget, font):
    """(spacing1, spacing3) of a text on widget's display: the room a line of font gets above
    and below it, so that it is LINE_HEIGHT times as high as the font's size."""
    size = font.actual("size")
    pixels = -size if size < 0 else widget.winfo_fpixels(f"{size}p")
    room = max(0, round(pixels * LINE_HEIGHT) - font.metrics("linespace"))
    return room // 2, room - room // 2


def is_aqua(widget):
    """True when Tk draws with macOS's own windowing system."""
    return widget.tk.call("tk", "windowingsystem") == "aqua"


def scale(widget):
    """Screen pixels per design pixel: 1.0 at 96 dots per inch, 2.25 at 216.

    Tk on macOS works in points, so sizes need no scaling there.
    """
    if is_aqua(widget):
        return 1.0
    return max(1.0, widget.winfo_fpixels("1i") / 96)


def px(widget, size):
    """A size in design pixels, in screen pixels."""
    return round(size * scale(widget))


class Tooltip:
    """A short note that appears below a widget while the mouse rests on it."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self._pending = None
        self._window = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")
        widget.bind("<Destroy>", self.hide, add="+")

    def _schedule(self, event=None):
        self._cancel()
        self._pending = self.widget.after(TOOLTIP_DELAY, self.show)

    def _cancel(self):
        if self._pending is not None:
            self.widget.after_cancel(self._pending)
            self._pending = None

    def show(self):
        self._pending = None
        if self._window is not None or not self.widget.winfo_ismapped():
            return
        widget = self.widget
        self._window = tip_window(widget, self.text, widget.winfo_rootx(),
                                  widget.winfo_rooty() + widget.winfo_height())

    def hide(self, event=None):
        self._cancel()
        if self._window is not None:
            self._window.destroy()
            self._window = None

    def set_text(self, text):
        """Show text from now on; a tooltip on the screen with the old text goes away."""
        if text != self.text:
            self.text = text
            if self._window is not None:
                self.hide()


def keep_size(frame):
    """Make a frame in a divided window ask for a small size that never changes.

    A scroll bar coming or going in a frame's grid changes the size the
    frame asks for, and a ttk paned window then gives the pane holding it its
    natural size again and places every divider anew. In such a window the
    dividers alone decide the frame's size. Elsewhere (a dialog that fits
    its contents) the frame keeps asking for what its grid needs. Returns
    True when the frame is in a divided window.
    """
    widget = frame.master
    while widget is not None:
        if widget.winfo_class() == "TPanedwindow":
            frame.grid_propagate(False)
            frame.configure(width=1, height=1)
            return True
        widget = widget.master
    return False


def bars_needed(fits_height, fits_width, width, height, thickness):
    """(vertical, horizontal): which scroll bars a content needs in a room of width x height.

    fits_height(pixels) and fits_width(pixels) tell whether the content
    fits in that height or width; thickness is (the vertical bar's width,
    the horizontal bar's height). The room holds the bars as well, so it
    does not change when they come or go. The vertical bar is needed when
    the content is too high for the room, the horizontal one when it is too
    wide for what the vertical bar leaves, and then the vertical one also
    when the content is too high for what the horizontal bar leaves. A bar
    never makes itself or the other unneeded, so neither switches on and off.
    """
    bar_width, bar_height = thickness
    vertical = not fits_height(height)
    horizontal = not fits_width(width - bar_width if vertical else width)
    if horizontal and not vertical:
        vertical = not fits_height(height - bar_height)
    return vertical, horizontal


def show_bar(bar, shown):
    """Put a gridded scroll bar back in its cell, or take it out of the grid."""
    if shown and not bar.winfo_manager():
        bar.grid()
    elif not shown and bar.winfo_manager():
        bar.grid_remove()


class HidingBars:
    """A text's scroll bars, shown only while its contents do not fit.

    The text and its bars are gridded in a frame of their own, the vertical
    bar at the text's right and the horizontal one below it; this becomes
    the text's scroll commands, which also set the bars. A bar leaves the
    grid while everything fits that way and comes back in its cell as soon
    as something does not. Both bars are decided at once with bars_needed(),
    from the size of the whole contents (the lines off the screen too) and
    the room inside the frame, which the bars do not change. They are
    decided once the changes of the moment are done: after the text scrolled
    or redrew, after the frame changed size, and after schedule(), which
    whoever changes the text calls (Tk calls no scroll command for a change
    that leaves its view of the lines as it was, such as clearing lines that
    fitted it); but not before the frame has a size. The horizontal bar
    makes the text shorter, and Tk keeps the text's top line: a view that
    showed the end of the text goes back to the end once the text has its
    new size, so the newest line (a prompt the program waits at) stays in
    view. The editor keeps both of its scroll bars and does not use this.

    The lines are one font high (no wrapping). A line is as wide as Tk lays
    it out: its characters, its tabs at Tk's stops (the n-th tab goes to the
    n-th stop, or a space on when the line has already reached it), and one
    character more for the insertion cursor. Text is added at the end and
    deleted at the start (Clear, the oldest output dropped) or at the end,
    so only the lines from the last one measured on are measured again, and
    of that one only what was added to it; a deletion takes all of it to be
    measured anew only when the widest line went with it.
    """

    def __init__(self, text, yscroll, xscroll):
        self.text, self.yscroll, self.xscroll = text, yscroll, xscroll
        self.frame = text.master
        self.font = tkfont.Font(root=text, font=text.cget("font"))
        self._fixed = self.font.metrics("fixed")
        self._char = self.font.measure("0")
        self._space = self.font.measure(" ")
        self._widths = {}               # character -> its pixels
        self._line_height = self.font.metrics("linespace") + sum(
            text.winfo_pixels(text.cget(option)) for option in ("spacing1", "spacing3"))
        border = sum(text.winfo_pixels(text.cget(option))
                     for option in ("borderwidth", "highlightthickness"))
        left, top, right, bottom = _padding(self.frame)
        self._inset_x = left + right + 2 * (text.winfo_pixels(text.cget("padx")) + border)
        self._inset_y = top + bottom + 2 * (text.winfo_pixels(text.cget("pady")) + border)
        self._widest = 0                # pixels of the widest line before line self._line
        self._line = 1                  # the last line measured
        self._tail = ("", (0, 0))       # its text then, and where it ended (pixels, tabs)
        self._pending = None            # the idle job that decides
        self._to_end = False            # the text's next size change brings the end into view
        for mark, index in ((START, "1.0 + 1c"), (LAST, "1.0"), (WIDEST, "1.0")):
            text.mark_set(mark, index)
            text.mark_gravity(mark, "left")
        text.configure(yscrollcommand=self._yscrolled, xscrollcommand=self._xscrolled)
        self.frame.bind("<Configure>", self.schedule, add="+")
        text.bind("<Configure>", self._resized, add="+")
        text.bind("<Destroy>", self._cancel, add="+")

    def _yscrolled(self, first, last):
        self.yscroll.set(first, last)
        self.schedule()

    def _xscrolled(self, first, last):
        self.xscroll.set(first, last)
        self.schedule()

    def schedule(self, event=None):
        """Decide the bars once the current changes are done."""
        if self._pending is None:
            self._pending = self.text.after_idle(self.decide)

    def _cancel(self, event=None):
        if self._pending is not None:
            self.text.after_cancel(self._pending)
            self._pending = None

    def decide(self, event=None):
        """Show or hide both scroll bars for the contents and the frame's size now."""
        self._cancel()
        width, height = self.frame.winfo_width(), self.frame.winfo_height()
        if width <= 1 or height <= 1:
            return                      # not laid out yet
        lines, widest = self._measure()
        vertical, horizontal = bars_needed(
            lambda room: lines * self._line_height <= room,
            lambda room: widest + self._char <= room,
            width - self._inset_x, height - self._inset_y,
            (self.yscroll.winfo_reqwidth(), self.xscroll.winfo_reqheight()))
        if not horizontal:
            self._to_end = False
        elif not self.xscroll.winfo_manager():                  # the horizontal bar comes
            self._to_end = self.text.yview()[1] == 1.0
        show_bar(self.yscroll, vertical)
        show_bar(self.xscroll, horizontal)

    def _resized(self, event=None):
        """The text has a new size: back to the end if the view was there when the bar came."""
        if self._to_end:
            self._to_end = False
            self.text.yview_moveto(1.0)

    def _measure(self):
        """(lines, pixels of the widest line) of the whole text."""
        text = self.text
        last = _line(text, "end - 1c")
        if text.compare(START, "==", "1.0"):        # the start was deleted
            if text.compare(LAST, "==", "1.0") or text.compare(WIDEST, "==", "1.0"):
                self._widest, self._line = 0, 1     # the widest line went: measure all again
            else:
                self._line = _line(text, LAST)
        if last < self._line:                       # lines at the end were deleted
            self._widest, self._line = 0, 1
        first = self._line
        lines = text.get(f"{first}.0", "end - 1c").split("\n")
        known, end = self._tail         # the last line as measured before: it may have grown
        if not lines[0].startswith(known):
            known, end = "", (0, 0)
        end = self._extend(*end, lines[0][len(known):])
        widths = []                     # of the lines before the last one, which may still grow
        if len(lines) > 1:
            widths = [end[0]] + [self._extend(0, 0, line)[0] for line in lines[1:-1]]
            end = self._extend(0, 0, lines[-1])
        widest = None
        for number, width in enumerate(widths, first):
            if width >= self._widest:
                self._widest, widest = width, number
        if widest is not None:
            text.mark_set(WIDEST, f"{widest}.0")
        self._line = last
        self._tail = (lines[-1], end)
        text.mark_set(LAST, f"{last}.0")
        text.mark_set(START, "1.0 + 1c")
        return last, max(self._widest, end[0])

    def _width(self, line):
        """Pixels of a line of the text."""
        return self._extend(0, 0, line)[0]

    def _extend(self, x, tabs, chars):
        """Where a line that ended x pixels in, after that many tabs, ends with chars added:
        (pixels, tabs)."""
        if self._fixed and chars.isascii() and chars.isprintable():    # no tab either
            return x + len(chars) * self._char, tabs
        for number, part in enumerate(chars.split("\t")):
            if number:
                tabs += 1
                stop = tabs * TAB_STOP * self._char
                x = stop if x < stop else x + self._space
            x += self._chars_width(part)
        return x, tabs

    def _chars_width(self, chars):
        """Pixels of characters other than tabs.

        In a fixed font a printable ASCII character is as wide as "0"; any
        other (a carriage return may have no width) is measured once: Tk
        takes a third of a millisecond or more to measure even a short text,
        seconds for every line of Run I/O.
        """
        if self._fixed and chars.isascii() and chars.isprintable():
            return len(chars) * self._char
        widths = self._widths
        distinct = set(chars)
        for char in distinct.difference(widths):
            widths[char] = self.font.measure(char)
        if len(distinct) <= FEW_CHARACTERS:
            return sum(widths[char] * chars.count(char) for char in distinct)
        return sum(map(widths.__getitem__, chars))


def _line(text, index):
    """The number of the line of an index of a text."""
    return int(text.index(index).split(".")[0])


def _padding(frame):
    """(left, top, right, bottom): the pixels by which a frame insets its contents.

    A Tk frame insets them by its border, its focus ring and its padding; a
    ttk frame by its padding.
    """
    if not isinstance(frame, ttk.Widget):
        ring = sum(frame.winfo_pixels(frame.cget(option))
                   for option in ("borderwidth", "highlightthickness"))
        across, down = (ring + frame.winfo_pixels(frame.cget(option)) for option in ("padx", "pady"))
        return across, down, across, down
    values = [frame.winfo_pixels(value) for value in frame.tk.splitlist(frame.cget("padding"))]
    left, top, right, bottom = (values + [None] * 4)[:4]
    left = left or 0
    top = left if top is None else top
    right = left if right is None else right
    bottom = top if bottom is None else bottom
    return left, top, right, bottom


def tip_window(widget, text, x, y):
    """A tooltip showing text just below the screen point (x, y); destroy() removes it."""
    window = tk.Toplevel(widget)
    window.withdraw()
    window.wm_overrideredirect(True)
    if is_aqua(window):
        window.tk.call("::tk::unsupported::MacWindowStyle", "style", window._w,
                       "help", "noActivates")
    tk.Label(window, text=text, background=TOOLTIP_BACKGROUND, foreground="#333333",
             font="TkTooltipFont", relief="solid", borderwidth=1, padx=px(window, 4),
             pady=px(window, 2), justify="left").pack()
    window.update_idletasks()
    x = max(0, min(x, window.winfo_screenwidth() - window.winfo_reqwidth()))
    window.wm_geometry(f"+{x}+{y + px(window, 2)}")
    window.deiconify()
    return window


# The read-only text's widget command, in Tcl: a Python command that raised
# an error (Tk's bindings catch failing commands, such as copying with nothing
# selected) would make mainloop() raise that error later.
_READ_ONLY = """{original args} {
    switch -exact -- [lindex $args 0] {
        insert - delete - replace {return}
    }
    tailcall $original {*}$args
}"""


def tab_moves_on(text):
    """Let Tab and Shift+Tab move the keyboard focus on from a text that takes no keys (a
    log, a help text), as from a button or a list: Tk's Text keeps them in the text, for
    typing a tab. With Control held they move on too."""
    for sequence, neighbour in (("<Tab>", "tk_focusNext"), ("<Shift-Tab>", "tk_focusPrev")):
        text.bind(sequence, f"tk::TabToWindow [{neighbour} %W]; break")


LONG_LINE = 8000                # characters of a line that ReadOnlyText still follows sideways


class ReadOnlyText(tk.Text):
    """A Text widget the user can select and copy from but not change.

    Typing, pasting, cutting and dragging go through the widget command and
    are ignored; the program writes with write() and clear(). A subclass can
    give another widget command in COMMAND.
    """

    COMMAND = _READ_ONLY

    def __init__(self, master=None, **options):
        super().__init__(master, **options)
        self.configure(inactiveselectbackground=self.cget("selectbackground"))
        self._original = self._w + "_original"
        self.tk.call("rename", self._w, self._original)
        self.tk.call("interp", "alias", "", self._w, "", "apply", self.COMMAND, self._original)
        self._end_waits = False         # see_end() is waiting for the text to have a size
        self.bind("<Configure>", self._sized, add="+")

    def write(self, text, *tags):
        """Add text at the end, with the given tags."""
        self.tk.call(self._original, "insert", "end", text, tags)

    def see_end(self):
        """Bring the end of the text into view, now or once the text has a size.

        Tk scrolls a text that was never laid out as if it were 1 x 1 pixels:
        sideways past the start of a last line that is not empty, which the
        text keeps once it has its size. To show a place far along a line Tk
        measures the line up to it each time it draws, which takes seconds at
        60,000 characters (the time grows with the square of the place): a
        last line longer than LONG_LINE is shown from its start.
        """
        if self.winfo_width() <= 1:
            self._end_waits = True
        elif int(self.index("end-1c").split(".")[1]) > LONG_LINE:
            self.xview_moveto(0)
            self.yview_moveto(1)
        else:
            self.see("end")

    def _sized(self, event=None):
        if self._end_waits and self.winfo_width() > 1:
            self._end_waits = False
            self.see_end()

    def clear(self):
        self.tk.call(self._original, "delete", "1.0", "end")

    def destroy(self):
        super().destroy()
        try:
            self.tk.call("rename", self._w, "")     # the alias; Tk removed the original
        except tk.TclError:
            pass
