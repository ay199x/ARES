# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The lists of places to show memory from: the Data Segment's, and the base addresses of
the Memory Reference Visualization and the Bitmap Display.

A list shows a place with its address, as "0x00000030 (.data)". The places
of the program (.data, heap and .text) have no address while no program is
loaded: the list says so (".data: no program assembled"), their entries are
gray, and choosing one changes nothing. current SP is SP's place; while SP
has its start value 0 it says where the stack starts instead, at the word
that the first push stores to. A list looks its places up as it opens and
again at each choice: the mouse wheel chooses without opening the list,
from the texts of its last look-up, and SP may have moved since.
"""

from tkinter import font as tkfont

from ..machine import INITIAL_SP
from .style import SHADOW

NO_PROGRAM = "no program assembled"
CURRENT_SP = "current SP"
STACK_START = (INITIAL_SP - 4) & 0xFFFFFFFF     # the first push stores here: 0xfffffffc
STACK_TEXT = f"{CURRENT_SP}: stack at 0x{STACK_START:08x}"


def place_text(name, address):
    """How a list shows a place: "0x00000030 (.data)"; for a place without an address
    (None: a place of the program while none is loaded) ".data: no program assembled"."""
    if address is None:
        return f"{name}: {NO_PROGRAM}"
    return f"0x{address:08x} ({name})"


def list_width(widget, texts):
    """The width in characters (those of "0") of a list that shows each of texts whole,
    with room for the cursor, in a list's font: the bold interface font."""
    font = tkfont.nametofont("TkDefaultFont", root=widget)
    return -(-max(font.measure(text) for text in texts) // font.measure("0")) + 1


def select_text(box):
    """Select the whole text of a combobox's field, the cursor at its end, as Tk leaves it
    after a choice in its list (ttk::combobox::SelectEntry)."""
    box.selection_range(0, "end")
    box.icursor("end")


def put_back(box, text):
    """Show text in a combobox's field again, selected as after a choice in its list: a
    place chosen that is not available changes nothing."""
    box.set(text)
    select_text(box)


def gray_unavailable(box, available):
    """Gray the entries of a combobox's drop-down list whose place is not available
    (available[k] false): their text is gray, also on the selection bar, as a disabled
    menu item's. Called as the list opens, its values set: the list is filled here as Tk
    fills it when it opens (ttk::combobox::Post)."""
    popdown = box.tk.call("ttk::combobox::PopdownWindow", box)
    box.tk.call("ttk::combobox::ConfigureListbox", box)
    listbox = f"{popdown}.f.l"
    for index, ok in enumerate(available):
        colour = "" if ok else SHADOW
        box.tk.call(listbox, "itemconfigure", index, "-foreground", colour,
                    "-selectforeground", colour)
