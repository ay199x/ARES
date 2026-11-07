# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Tools > Digital Lab Sim: the DE1-SoC's red LEDs, seven-segment displays, slide switches
and push buttons.

The board (ares.devices.Board) is the tool's. While the tool is connected the
program's loads and stores at the four ports' addresses reach it, through the
machine's device accesses (Machine.board), and the window shows what the
program wrote; the switches and keys are worked with the mouse. A connected
Lab Sim adds no hook to the emulator: device accesses call Python anyway.
"""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from ...devices import (DISPLAY_COUNT, HEX3_HEX0, HEX5_HEX4, KEY_COUNT, KEYS, LED_COUNT, LEDS,
                        SEGMENT_COUNT, SWITCH_COUNT, SWITCHES, Board)
from ..style import (DARK_SHADOW, FACE, HIGHLIGHT, LIGHT, RAISED, SHADOW, SUNKEN, TEXT, draw_bevel,
                     group as group_box)
from ..widgets import Tooltip, px
from .frame import ToolModel, ToolWindow

# Sizes in design pixels.
DIGIT = (28, 50)                # a seven-segment digit: width and height
STROKE = 6                      # the thickness of a segment
DIGIT_GAP = 14                  # between two digits
PANEL_PADDING = 8               # around the digits, inside the displays' black panel
COLUMN = 28                     # the width of an LED's or a switch's column
LED_SIZE = 13                   # an LED with its sunken ring
SLOT = (14, 30)                 # a switch's slot: width and height; the knob fills half

PANEL = "#000000"
LIT_SEGMENT = "#FF0000"
DARK_SEGMENT = "#400000"
LIT_LED = "#FF0000"
DARK_LED = "#800000"

# Where segment k of a digit lies: ("h", y, x from, x to) for one across the digit and
# ("v", x, y from, y to) for one down it, as shares of the box its middle lines run on.
SEGMENTS = (("h", 0, 0, 1),         # 0 top
            ("v", 1, 0, 0.5),       # 1 upper right
            ("v", 1, 0.5, 1),       # 2 lower right
            ("h", 1, 0, 1),         # 3 bottom
            ("v", 0, 0.5, 1),       # 4 lower left
            ("v", 0, 0, 0.5),       # 5 upper left
            ("h", 0.5, 0, 1))       # 6 middle

RESET_TIP = "Switch the board off: LEDs and displays dark, switches down"
SWITCH_TIP = "Click a switch to flip it: up is 1, down is 0"
KEY_TIP = "Pressed while the mouse button is held down on it"

HELP = """\
The Digital Lab Sim is the DE1-SoC board's red LEDs, its six seven-segment displays, its
slide switches and its push buttons, at their DE1-SoC addresses and with their bit
formats, as Intel's DE1-SoC Computer System documentation describes them. CPUlator's
DE1-SoC system has the same devices.

Click Connect to ARM: from then on the program's loads and stores at the addresses below
reach the board in this window. While the tool is not connected these devices are not
simulated: writes to them are ignored, reads give 0, and ARES Messages warns once for each
address. The tool stays connected when the program is assembled again or its file is
closed. Close closes the tool, and the program no longer reaches the board.

Red LEDs LEDR9-LEDR0, at 0xFF200000: bit k of the word there lights LEDRk (LEDR9 is at the
left, as on the board). The program writes the word and reads it back; bits 31-10 are
ignored and read 0.

Seven-segment displays HEX5-HEX0: the word at 0xFF200020 drives HEX0 with bits 6-0, HEX1
with bits 14-8, HEX2 with bits 22-16 and HEX3 with bits 30-24; the word at 0xFF200030
drives HEX4 with bits 6-0 and HEX5 with bits 14-8. In the bits of a display, bit 0 lights
the top segment, bit 1 the upper right one, bit 2 the lower right one, bit 3 the bottom
one, bit 4 the lower left one, bit 5 the upper left one and bit 6 the middle one. The
digits 0 to 9 are 0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F and 0x6F: with R0
= 0xFF200000, MOV R1, #0x3F and STR R1, [R0, #0x20] show 0 on HEX0 and switch HEX1 to HEX3
off. Bit 7 of each byte drives nothing. Both words are read back as they were written.

Slide switches SW9-SW0, at 0xFF200040: bit k of the word there is 1 while SWk is up. Click
a switch to flip it. The program cannot write the switches.

Push buttons KEY3-KEY0, from 0xFF200050: a key is pressed while the mouse button is held
down on it. The word at 0xFF200050 has bit k = 1 while KEYk is pressed. In the word at
0xFF20005C (Edgecapture) bit k becomes 1 when KEYk is pressed and stays 1 after it is let
go, until the program writes any value there, which sets all four bits to 0: a program
that polls this word sees every press, even a short one, as long as it writes there only
after it read a bit that is 1: a write also forgets a press that came after the read. The word
at 0xFF200058
(Interruptmask) keeps the four bits written there, but ARES has no interrupts and no
timers: a program polls the keys.

Intel's documentation describes word accesses (LDR, STR). A byte or halfword access
(LDRB, STRB, LDRH, STRH) reads or writes those bytes of the word: STRB to 0xFF200021
changes HEX1 alone. Writes to the switches and to the keys' word at 0xFF200050
are ignored, and so are the other words of these ports (such as 0xFF200004), which read
0. While the tool is connected the Data Segment shows the words at 0xFF200000-0xFF20005F
as the program reads them.

Like a real board, the board keeps its state when the program is assembled again, reset
(Reset, F12) or its file is closed: the LEDs and displays keep what the program wrote, and
the switches stay where they are. Backstep undoes what the instruction stepped back wrote
to the LEDs, displays, Interruptmask and Edgecapture; the switches and keys stay as they
are. The tool's Reset button switches the board off: LEDs and displays dark, switches
down, Interruptmask and Edgecapture 0.

A connected Digital Lab Sim costs nothing while the program does not use these devices;
each access to them takes a little time.
"""


class LabSimModel(ToolModel):
    """The board, connected to the program's machine while the tool is connected.

    The board is the tool's: what it shows and the positions of its switches
    stay across Assemble, Reset and the program's file being closed, as on a
    real board. Only reset() switches it off.
    """

    def __init__(self):
        super().__init__()
        self.board = Board()
        self._changes = self.board.changes      # the board's changes taken in by update()

    def attach(self, machine):
        machine.board = self.board

    def detach(self, machine):
        if machine.board is self.board:
            machine.board = None

    def reset(self):
        self.board.reset()

    def update(self):
        changes = self.board.changes
        changed, self._changes = changes != self._changes, changes
        return changed


class LabSimWindow(ToolWindow):
    """Tools > Digital Lab Sim."""

    NAME = "Digital Lab Sim"
    HELP = HELP
    MODEL = LabSimModel

    def __init__(self, app):
        super().__init__(app)
        self.tips[self.reset_button].set_text(RESET_TIP)

    def build(self, body):
        gap = px(body, 6)
        font = tkfont.nametofont("TkDefaultFont", root=body)
        groups = [group_box(body, text) for text in (
            f"Seven-segment displays (0x{HEX3_HEX0:08x}, 0x{HEX5_HEX4:08x})",
            f"Red LEDs (0x{LEDS:08x})",
            f"Slide switches (0x{SWITCHES:08x})",
            f"Push buttons (0x{KEYS:08x})")]
        for row, group in enumerate(groups):
            group.grid(row=row, column=0, sticky="we", pady=(0 if row == 0 else gap, 0))
        body.columnconfigure(0, weight=1)
        self.displays = self._make_displays(groups[0], font)
        self.leds = self._make_leds(groups[1], font)
        self.switches = self._make_switches(groups[2], font)
        self.key_buttons = self._make_keys(groups[3])
        self.switch_tip = Tooltip(self.switches, SWITCH_TIP)
        self.key_tips = [Tooltip(button, KEY_TIP) for button in self.key_buttons]
        self._segments_shown = [0] * DISPLAY_COUNT      # as drawn: all dark, switches down
        self._leds_shown = 0
        self._switches_shown = 0

    def _make_displays(self, group, font):
        """The black panel of the six digits, HEX5 at the left, with their names below."""
        width, height = px(group, DIGIT[0]), px(group, DIGIT[1])
        stroke, space = px(group, STROKE), px(group, DIGIT_GAP)
        ring, padding = px(group, 1), px(group, PANEL_PADDING)
        border = 2 * ring + padding                 # the panel's sunken bevel, then the padding
        panel_width = 2 * border + DISPLAY_COUNT * width + (DISPLAY_COUNT - 1) * space
        panel_height = 2 * border + height
        line = font.metrics("linespace")
        canvas = tk.Canvas(group, width=panel_width, height=panel_height + px(group, 2) + line,
                           background=FACE, borderwidth=0, highlightthickness=0, takefocus=False)
        canvas.pack()
        draw_bevel(canvas, 0, 0, panel_width, panel_height, rings=SUNKEN, face=PANEL)
        self.segment_items = []
        for column in range(DISPLAY_COUNT):
            display = DISPLAY_COUNT - 1 - column
            x, y = border + column * (width + space), border
            box = (x + stroke / 2, y + stroke / 2, x + width - stroke / 2, y + height - stroke / 2)
            self.segment_items.insert(0, [
                canvas.create_polygon(*segment_corners(k, *box, stroke, ring), fill=DARK_SEGMENT,
                                      width=0)
                for k in range(SEGMENT_COUNT)])
            canvas.create_text(x + width / 2, panel_height + px(group, 2), anchor="n",
                               text=f"HEX{display}", fill=TEXT, font=font)
        return canvas

    def _make_leds(self, group, font):
        """The ten LEDs, LEDR9 at the left, each with its number below."""
        column, size, ring = px(group, COLUMN), px(group, LED_SIZE), px(group, 1)
        canvas = tk.Canvas(group, width=LED_COUNT * column,
                           height=size + px(group, 2) + font.metrics("linespace"),
                           background=FACE, borderwidth=0, highlightthickness=0, takefocus=False)
        canvas.pack()
        self.led_items = []
        for index in range(LED_COUNT):
            led = LED_COUNT - 1 - index
            x0 = index * column + (column - size) // 2
            for inset, (top_left, bottom_right) in enumerate(((SHADOW, HIGHLIGHT),
                                                              (DARK_SHADOW, LIGHT))):
                box = (x0 + inset * ring, inset * ring, x0 + size - inset * ring,
                       size - inset * ring)
                canvas.create_arc(*box, start=45, extent=180, style="arc", outline=top_left,
                                  width=ring)
                canvas.create_arc(*box, start=225, extent=180, style="arc",
                                  outline=bottom_right, width=ring)
            self.led_items.insert(0, canvas.create_oval(
                x0 + 2 * ring, 2 * ring, x0 + size - 2 * ring, size - 2 * ring, fill=DARK_LED,
                width=0))
            canvas.create_text(index * column + column / 2, size + px(group, 2), anchor="n",
                               text=str(led), fill=TEXT, font=font)
        return canvas

    def _make_switches(self, group, font):
        """The ten switches, SW9 at the left, each with its number below; all down."""
        column, ring = px(group, COLUMN), px(group, 1)
        width, height = px(group, SLOT[0]), px(group, SLOT[1])
        canvas = tk.Canvas(group, width=SWITCH_COUNT * column,
                           height=height + px(group, 2) + font.metrics("linespace"),
                           background=FACE, borderwidth=0, highlightthickness=0, takefocus=False)
        canvas.pack()
        inner = height - 4 * ring
        self._travel = inner - inner // 2           # how far a knob moves when flipped
        for index in range(SWITCH_COUNT):
            switch = SWITCH_COUNT - 1 - index
            x0 = index * column + (column - width) // 2
            draw_bevel(canvas, x0, 0, x0 + width, height, rings=SUNKEN, face=SHADOW)
            draw_bevel(canvas, x0 + 2 * ring, 2 * ring + self._travel, x0 + width - 2 * ring,
                       height - 2 * ring, rings=RAISED, tags=(f"knob{switch}",))
            canvas.create_text(index * column + column / 2, height + px(group, 2), anchor="n",
                               text=str(switch), fill=TEXT, font=font)
        canvas.bind("<ButtonPress-1>", self._switch_clicked)
        return canvas

    def _make_keys(self, group):
        """The four keys, KEY3 at the left."""
        row = ttk.Frame(group)
        row.pack()
        buttons = []
        for index in range(KEY_COUNT):
            key = KEY_COUNT - 1 - index
            button = ttk.Button(row, text=f"KEY{key}", takefocus=False)
            button.pack(side="left", padx=(0 if index == 0 else px(group, 6), 0))
            # Pressed while the mouse button is held down on it, as the button looks.
            for sequence, down in (("<ButtonPress-1>", True), ("<B1-Enter>", True),
                                   ("<ButtonRelease-1>", False), ("<B1-Leave>", False)):
                button.bind(sequence, lambda event, key=key, down=down: self._key(key, down))
            buttons.insert(0, button)
        return buttons

    # The user's switches and keys ------------------------------------------------------

    def _switch_clicked(self, event):
        self.switch_tip.hide()
        index = int(event.x // px(self.switches, COLUMN))
        if 0 <= index < SWITCH_COUNT:
            self.model.board.flip(SWITCH_COUNT - 1 - index)
            self._board_changed()

    def _key(self, key, down):
        self.key_tips[key].hide()
        if down:
            self.model.board.press(key)
        else:
            self.model.board.release(key)
        self._board_changed()

    def _board_changed(self):
        """The user changed the board: show it, and what the program now reads."""
        self.show()
        self._memory_changed()

    def _memory_changed(self):
        """The Data Segment shows the board's words while the tool is connected: show them
        again."""
        if self.app.machine is not None:
            self.app.execute.data_segment.refresh()

    # The buttons -----------------------------------------------------------------------

    def toggle_connection(self):
        super().toggle_connection()
        self._memory_changed()

    def reset(self):
        super().reset()
        self._memory_changed()

    def close(self):
        connected = self.window is not None and self.model.connected
        super().close()
        if connected:
            self._memory_changed()

    # Showing the board -----------------------------------------------------------------

    def show(self):
        board = self.model.board
        for display, items in enumerate(self.segment_items):
            self._segments_shown[display] = _light(self.displays, items, board.segments(display),
                                                   self._segments_shown[display], LIT_SEGMENT,
                                                   DARK_SEGMENT)
        self._leds_shown = _light(self.leds, self.led_items, board.leds, self._leds_shown,
                                  LIT_LED, DARK_LED)
        moved, self._switches_shown = board.switches ^ self._switches_shown, board.switches
        for switch in range(SWITCH_COUNT):
            if moved >> switch & 1:
                up = board.switches >> switch & 1
                self.switches.move(f"knob{switch}", 0, -self._travel if up else self._travel)


def segment_corners(k, left, top, right, bottom, stroke, space):
    """The six corners of segment k, a long hexagon stroke thick, in a digit whose segments'
    middle lines run on the box left, top, right, bottom; space is left at each end."""
    way, at, start, end = SEGMENTS[k]
    half = stroke / 2
    if way == "h":
        y = top + at * (bottom - top)
        x0, x1 = left + start * (right - left) + space, left + end * (right - left) - space
        return (x0, y, x0 + half, y - half, x1 - half, y - half, x1, y, x1 - half, y + half,
                x0 + half, y + half)
    x = left + at * (right - left)
    y0, y1 = top + start * (bottom - top) + space, top + end * (bottom - top) - space
    return (x, y0, x + half, y0 + half, x + half, y1 - half, x, y1, x - half, y1 - half,
            x - half, y0 + half)


def _light(canvas, items, bits, shown, lit, dark):
    """Colour the items whose bits changed since shown, item k by bit k; returns bits."""
    for k, item in enumerate(items):
        if (bits ^ shown) >> k & 1:
            canvas.itemconfigure(item, fill=lit if bits >> k & 1 else dark)
    return bits


WINDOW = LabSimWindow
