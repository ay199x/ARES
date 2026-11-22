# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The ARM X-Ray's windows inside its blocks: a click on a block opens what is inside it.

Each window shows the inside of one block of the datapath for the instruction
the tool shows, and plays with the tool's film: the main window calls draw()
with the film and the moment whenever it draws the picture, so the inside moves
at the same speed, stops when the film pauses, and follows the program when it
steps. A window draws its block idle before the block's step of the film, at
work during it (fraction of the step) and finished after it.

INSIDE maps a block's name in the picture to its window class; the classes
live in the modules xray_inside_*.

The windows look as the picture does (ares.gui.tools.xray_look): a part the
instruction does not use is pale, one it uses waits in a calm blue until its
inputs have arrived, lights while it works and keeps a lighter tint once done;
with no instruction shown every part rests in the calm blue. What the
instruction changes, the register written, the memory word written and the
flags, rests on the green of the changed rows of the Registers pane once the
clock edge has written it. A value has the colour of its net on the picture
wherever it goes, and the gray of what is not in use lies only on white or on
the pale fill: on any other fill it is a darker gray.

A window's heading is a name for what it shows; the mouse resting on it shows
a tip with what the block does. A register number that arrives on a wire shows
its four bits, as on the picture (A1 = 0001); a register's name stays where the
block reads or writes it.
"""

import math
import tkinter as tk
from collections import namedtuple
from dataclasses import dataclass
from tkinter import font as tkfont

from ... import xray, xray_film
from ..menubar import screen_area
from ..widgets import px, scale, tip_window
from .frame import frame_of, give_maximize_box, place_over, when_settled
from .xray_look import (CHANGED, DIM, DONE_FILL, IDLE, INK, MARK, OFF, ON, UNUSED_FILL,
                        WAITING_FILL, WHITE, WORKING_FILL, fill_of, net_colours, signal_colour)
from .xray_picture import fitted_zoom, points

FIELD = WHITE                   # the canvas's background
IDLE_STATE, WORKING, DONE = "idle", "working", "done"
# The looks of a part inside a block: (outline, fill, words), the words being those that do not
# say that the part is at work. A part is "unused" when the instruction does not use it, "waiting"
# while it waits for its inputs (and with no instruction shown), "working" while it works, "done"
# after, and "changed" when it holds what the instruction wrote. The fills are the picture's
# blocks' (xray_look.fill_of()).
Look = namedtuple("Look", "outline fill words")
LOOKS = {"unused": Look(IDLE, fill_of(IDLE_STATE, used=False), IDLE),
         "waiting": Look(DIM, fill_of(IDLE_STATE), INK),
         "working": Look(INK, fill_of(WORKING), INK), "done": Look(INK, fill_of(DONE), INK),
         "changed": Look(INK, CHANGED, INK)}
# The fills a part may have, from the looks.
FILLS = tuple(look.fill for look in LOOKS.values())
# What a window says where the instruction leaves a part without a value (Trace.values None):
# bits that are no field of it, or a part that only such bits or an X would steer. Nothing
# travels there, and the part stays gray. UNUSED_LINES is the same on two lines.
UNUSED = "not used by this instruction"
UNUSED_LINES = "not used by\nthis instruction"
TIP_DELAY = 600                 # milliseconds the mouse rests on a part before its tip shows
HEADING_TAG = "tip:heading"     # the heading's tag, which its tip goes with


@dataclass
class Context:
    """What an inside window needs besides the film: the view the tool shows, the registers
    before the instruction and after it (None when it has not run), the memory as a peek
    that never touches a device (peek(address, size) gives bytes or None), and the memory
    writes of the instruction: [(address, bytes before, bytes after)]."""
    view: object
    trace: object
    registers_before: list
    registers_after: list
    peek: object
    writes: list


def opening_zoom(tool, size):
    """The zoom a window inside a block opens at: the tool's, or less where the window would not
    fit the work area of the tool's screen at it (a maximized tool's zoom is larger than the
    screen holds for some windows); never under 1. size is the window's design size."""
    master = tool.window
    k = scale(master)
    try:
        x = master.winfo_rootx() + master.winfo_width() // 2
        y = master.winfo_rooty() + master.winfo_height() // 2
        left, top, right, bottom = screen_area(master, x, y)
        _, _, _, _, side, title = frame_of(master)
    except tk.TclError:
        return tool.zoom
    room = min((right - left - 2 * side) / (size[0] * k),
               (bottom - top - title - side) / (size[1] * k))
    return max(1.0, min(tool.zoom, math.floor(room * 100) / 100))


def gray_on(fill):
    """The gray of what is not in use where it lies on fill: IDLE on white and on the pale fill,
    DIM on any other, where IDLE would not keep a contrast of 3 to 1."""
    return IDLE if fill in ("", WHITE, UNUSED_FILL) else DIM


def look_of(used, working=False, done=False, resting=False):
    """The name of a part's look (LOOKS): "unused" when the instruction does not use it, else
    "working" while it works, "done" after, and "waiting" before; with no instruction shown
    (resting) "waiting"."""
    if resting:
        return "waiting"
    if not used:
        return "unused"
    return "working" if working else "done" if done else "waiting"


def works_in(step, block):
    """True when block works in step: it lights, it has a gate there, or it decides."""
    return (any(name == block for name, _ in step.lights)
            or any(gate.block == block for gate in step.gates)
            or any(decision.mux == block for decision in step.decisions))


def phase(film, moment, block, inclusive=False):
    """(state, fraction) of block at moment: IDLE_STATE before its first step of the film,
    WORKING with how far into that step, DONE after its last one."""
    steps = [number for number, step in enumerate(film.steps) if works_in(step, block)]
    if not steps:
        return (DONE, 1.0) if film.steps and moment >= film.seconds else (IDLE_STATE, 0.0)
    number, fraction = film.at(moment, inclusive)
    if number < steps[0]:
        return IDLE_STATE, 0.0
    if number > steps[-1]:
        return DONE, 1.0
    if number in steps:
        return WORKING, fraction
    return WORKING, 1.0


def steps_of(film, block):
    """The steps of film in which block works, in order."""
    return [step for step in film.steps
            if any(name == block for name, _ in step.lights)
            or any(gate.block == block for gate in step.gates)]


class InsideWindow:
    """A window with what is inside one block (see the module's description).

    Subclasses set BLOCK (the block's name in the picture), TITLE and SIZE (design pixels at
    zoom 1), HEADING (a name for what the window shows) and ABOUT (the heading's tip: what the
    block does), and write redraw(), which draws everything the block shows for the block's
    state (phase()) and its step, and, when something moves within a step, animate(). draw()
    clears the canvas and calls redraw() only when what the picture depends on changed
    (key_of(): the film, the instruction, the block's state and which of its own steps plays);
    at every other picture it calls animate() alone. A window whose picture depends on more
    overrides key_of().

    The window opens at the tool's zoom. Made larger or maximized, it draws its picture again
    as large as it holds it, in proportion, once its size has settled (rezoom()); it cannot be
    made smaller than the picture at zoom 1, where the smallest text has 8 points. A window
    that keeps what depends on its fonts' sizes forgets it in rezoomed().

    A part drawn with tipped() has a tip: the mouse resting on it for TIP_DELAY shows it, as
    on the picture. tips maps each part's "tip:" tag to its tip; the heading's is HEADING_TAG.
    """

    BLOCK = ""
    TITLE = ""
    HEADING = ""
    ABOUT = ""
    SIZE = (720, 440)
    FONTS = {"small": (8, "normal"), "bold": (8, "bold"), "title": (11, "bold"),
             "code": (8, "normal"), "code_bold": (8, "bold"), "code_struck": (8, "normal")}

    def __init__(self, tool):
        self.tool = tool
        master = tool.window
        window = self.window = tk.Toplevel(master, background=FIELD)
        window.withdraw()
        window.title(f"ARM X-Ray: {self.TITLE}")
        window.transient(master)
        window.resizable(True, True)
        self.zoom = opening_zoom(tool, self.SIZE)
        self.k = scale(master) * self.zoom
        width, height = self.canvas_size(self.zoom)
        self.canvas = tk.Canvas(window, width=width, height=height, background=FIELD,
                                borderwidth=0, highlightthickness=0, takefocus=False)
        self.canvas.place(relx=0.5, rely=0.5, anchor="center")
        window.configure(width=width, height=height)    # its usual size: placing asks for none
        window.minsize(*self.canvas_size(1.0))
        self.fonts = {}
        self._size_fonts()
        self.tips = {}                  # "tip:" tag -> what the mouse resting on its parts shows
        self._tip = None                # (tag, pending job, tip window) while the mouse rests
        self.canvas.bind("<Motion>", self._pointer_moved, add="+")
        self.canvas.bind("<Leave>", lambda event: self.hide_tip(), add="+")
        window.bind("<Escape>", lambda event: self.close())
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.bind("<Map>", self._mapped, add="+")
        when_settled(window, lambda: self._settled())
        self.key = None                 # what the canvas shows now: key_of(), or None
        self.drawn = None               # (film, moment, context) of the last draw()
        self.painted = (None, net_colours(None))    # (trace, its nets' colours): colour()
        place_over(window, master)
        window.deiconify()

    def canvas_size(self, zoom):
        """The canvas's size in screen pixels at zoom."""
        k = scale(self.tool.window) * zoom
        return round(self.SIZE[0] * k), round(self.SIZE[1] * k)

    def _size_fonts(self):
        """Make the window's fonts, or give them their sizes at the window's zoom (FONTS); a
        canvas text keeps its font, which takes the new size."""
        window = self.window
        family = tkfont.nametofont("TkTextFont", root=window).actual("family")
        code = self.tool.app.pane_font.cget("family")
        for name, (size, weight) in self.FONTS.items():
            font = self.fonts.get(name)
            if font is None and name != "code_struck":
                font = self.fonts[name] = tkfont.Font(
                    root=window, family=code if name.startswith("code") else family,
                    weight=weight)
            if font is not None:
                font.configure(size=points(size, self.zoom))

    def _mapped(self, event):
        if event.widget is self.window:
            give_maximize_box(self.window)

    def _settled(self):
        """The window's size has settled: draw it again as large as it holds the picture."""
        if self.window is None:
            return
        window = self.window
        zoom = fitted_zoom((window.winfo_width(), window.winfo_height()), self.SIZE,
                           scale(window), self.zoom)
        if zoom is not None and zoom != self.zoom:
            self.rezoom(zoom)

    def rezoom(self, zoom):
        """Draw the window again at zoom, its picture in proportion and its text with it, never
        under 8 points: it shows what it showed, and goes on following the film."""
        if self.window is None:
            return
        self.hide_tip()
        self.zoom = zoom
        self.k = scale(self.tool.window) * zoom
        self._size_fonts()
        width, height = self.canvas_size(zoom)
        self.canvas.configure(width=width, height=height)
        self.key = None
        self.rezoomed()
        if self.drawn is not None:
            self.draw(*self.drawn)

    def rezoomed(self):
        """Forget what depends on the fonts' sizes (the window is drawn again at a new zoom)."""

    # Drawing helpers, in design pixels ----------------------------------------------------

    def xy(self, x, y):
        return x * self.k, y * self.k

    def flat(self, points):
        return [c for point in points for c in self.xy(*point)]

    def d(self, size):
        return max(1, size * self.k)

    def text(self, x, y, text, anchor="nw", font="small", fill=INK, **options):
        return self.canvas.create_text(*self.xy(x, y), text=text, anchor=anchor,
                                       font=self.fonts[font], fill=fill, **options)

    def box(self, left, top, right, bottom, outline=IDLE, fill=FIELD, width=1, **options):
        return self.canvas.create_rectangle(*self.xy(left, top), *self.xy(right, bottom),
                                            outline=outline, fill=fill, width=self.d(width),
                                            **options)

    def line(self, points, fill=IDLE, width=1.2, arrow="none", dash="", **options):
        return self.canvas.create_line(*self.flat(points), fill=fill, width=self.d(width),
                                       arrow=arrow, dash=dash,
                                       arrowshape=(self.d(6), self.d(6), self.d(2.5)), **options)

    def mux(self, left, top, right, bottom, outline=IDLE, fill=FIELD):
        """A multiplexer, wider at its inputs (left) than at its output."""
        slope = (bottom - top) / 5
        points = [(left, top), (right, top + slope), (right, bottom - slope), (left, bottom)]
        return self.canvas.create_polygon(*self.flat(points), outline=outline, fill=fill,
                                          width=self.d(1.2))

    def gate(self, kind, x, y, outline=IDLE, fill=FIELD, size=18):
        """An AND, OR or NOT gate with its inputs at the left, its output at (x + size, y)."""
        canvas = self.canvas
        half = size / 2
        if kind == "AND":
            points = [(x, y - half), (x + half, y - half)]
            points += [(x + half + half * _cos(a), y + half * _sin(a)) for a in range(-90, 91, 15)]
            points += [(x + half, y + half), (x, y + half)]
        elif kind == "OR":
            points = [(x, y - half), (x + size * 0.6, y - half * 0.9), (x + size, y),
                      (x + size * 0.6, y + half * 0.9), (x, y + half), (x + size * 0.25, y)]
        else:                           # NOT: a triangle and a ring
            points = [(x, y - half), (x + size - 4, y), (x, y + half)]
        item = canvas.create_polygon(*self.flat(points), outline=outline, fill=fill,
                                     width=self.d(1.2), smooth=kind == "OR")
        if kind == "NOT":
            cx, cy = self.xy(x + size - 2, y)
            r = self.d(2)
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline=outline, fill=FIELD,
                               width=self.d(1.2))
        return item

    def colour(self, net):
        """The colour of net on the picture for the instruction shown (xray_look.net_colours()):
        a field's colour carried through, a multiplexer's output the colour of the input taken,
        a control signal's red or gray by its value. A name that is no net is an error."""
        return self.painted[1][net]

    def heading(self, x, y, instead=None):
        """The heading at (x, y): HEADING in bold, with ABOUT as its tip; or instead, the line
        that says why the block shows nothing (no instruction, or one it does not work for)."""
        if instead is not None:
            return self.text(x, y, instead, font="bold", fill=INK)
        return self.tipped(self.text(x, y, self.HEADING, font="bold", fill=INK), HEADING_TAG,
                           self.ABOUT)

    # Tips ---------------------------------------------------------------------------------

    def tipped(self, item, tag, tip):
        """Give item (a canvas item or a tag) the tip tip, under tag ("tip:" and a name)."""
        self.canvas.addtag_withtag(tag, item)
        self.tips[tag] = tip
        return item

    def tip_at(self, x, y):
        """The tag of the topmost part with a tip at the canvas point (x, y), or None."""
        canvas = self.canvas
        for item in reversed(canvas.find_overlapping(x - 2, y - 2, x + 2, y + 2)):
            if canvas.itemcget(item, "state") == "hidden":
                continue
            for tag in canvas.gettags(item):
                if tag in self.tips:
                    return tag
        return None

    def _pointer_moved(self, event):
        tag = self.tip_at(event.x, event.y)
        if self._tip is not None and self._tip[0] == tag:
            return
        self.hide_tip()
        if tag is not None:
            job = self.canvas.after(TIP_DELAY, lambda: self._show_tip(tag, event.x_root,
                                                                      event.y_root))
            self._tip = (tag, job, None)

    def _show_tip(self, tag, x, y):
        if self.window is None or self._tip is None or self._tip[0] != tag:
            return
        canvas = self.canvas
        self._tip = (tag, None, tip_window(canvas, self.tips[tag], x + px(canvas, 12),
                                           y + px(canvas, 8)))

    def hide_tip(self):
        if self._tip is not None:
            _, job, window = self._tip
            self._tip = None
            if job is not None:
                self.canvas.after_cancel(job)
            if window is not None:
                window.destroy()

    # Called by the tool -----------------------------------------------------------------

    def draw(self, film, moment, context):
        """Show the block for film at moment; context is a Context. The tool calls this at
        every picture of its film, so it does little unless the block's own state changed."""
        if self.window is None:
            return
        self.drawn = (film, moment, context)
        if self.painted[0] is not context.trace:    # the nets' colours, once an instruction
            self.painted = (context.trace, net_colours(context.trace))
        state, fraction = phase(film, moment, self.BLOCK)
        key = self.key_of(film, moment, context, state, fraction)
        if key != self.key:
            self.key = key
            self.canvas.delete("all")
            self.redraw(film, moment, context, state, fraction)
        self.animate(film, moment, context, state, fraction)

    def key_of(self, film, moment, context, state, fraction):
        """What the picture depends on: the film, the context, the block's state and the
        number of the step that plays when the block works in it (None before, between and
        after its steps). The key holds the film and the context themselves, so that a new
        one never passes for the old one."""
        number = None
        if state == WORKING:
            number = film.at(moment)[0]
            if number >= len(film.steps) or not works_in(film.steps[number], self.BLOCK):
                number = None
        return film, context, state, number

    def redraw(self, film, moment, context, state, fraction):
        """Draw everything the block shows now (the canvas is empty)."""

    def animate(self, film, moment, context, state, fraction):
        """Move what moves within the step (fraction from 0 to 1 while WORKING)."""

    def close(self):
        if self.window is None:
            return
        self.hide_tip()
        self.window.destroy()
        self.window = None
        self.tool.inside_closed(self)

    def lift(self):
        self.window.deiconify()
        self.window.lift()


def _cos(degrees):
    import math
    return math.cos(math.radians(degrees))


def _sin(degrees):
    import math
    return math.sin(math.radians(degrees))


def system_note(trace, name):
    """For an SVC, which the control unit hands to the system, and for a NOP, which does nothing,
    the line that says that the block called name does not work for it; "" for any other
    instruction."""
    if trace is not None and trace.kind == xray.SYSTEM_CALL:
        return f"An SVC does not use {name}: the system performs the service."
    if trace is not None and trace.kind == xray.NO_OPERATION:
        return f"A NOP does not use {name}: nothing is read and nothing is written."
    return ""


def bit_text(value, width=32, group=4):
    """value in binary, in groups of group bits (None: question marks)."""
    if value is None:
        return "?" * width
    text = f"{value & (1 << width) - 1:0{width}b}"
    return " ".join(text[i:i + group] for i in range(0, width, group))


def register_bits(number):
    """A register number as its four bits, as the picture's wires carry it: 1101, not R13."""
    return f"{number & 0xF:04b}"


INSIDE = {}                         # block -> window class: filled by the modules
MODULES = {                         # block -> the module of this package with its window
    "Control": "xray_inside_control", "RegFile": "xray_inside_registers",
    "ALU": "xray_inside_alu", "Extend": "xray_inside_extend", "Shifter": "xray_inside_extend",
    "IMem": "xray_inside_memory", "DMem": "xray_inside_memory",
}


def window_class(block):
    """The class of the window inside block, or None when the block has none (multiplexers,
    adders and the PC register have only their tips)."""
    if block not in INSIDE and block in MODULES:
        import importlib
        import importlib.util
        name = f"{__package__}.{MODULES[block]}"
        if importlib.util.find_spec(name) is not None:
            importlib.import_module(name)
    return INSIDE.get(block)


__all__ = ["Context", "InsideWindow", "INSIDE", "phase", "steps_of", "works_in", "signal_colour",
           "bit_text", "register_bits", "system_note", "UNUSED", "UNUSED_LINES", "IDLE_STATE",
           "WORKING", "DONE", "HEADING_TAG", "TIP_DELAY",
           "Look", "LOOKS", "FILLS", "gray_on", "look_of", "CHANGED", "DIM", "DONE_FILL", "IDLE",
           "INK", "MARK", "ON", "OFF", "UNUSED_FILL", "WAITING_FILL", "WORKING_FILL", "FIELD",
           "xray_film"]
