# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Checks for a window made of widgets, laid out at a chosen size while it stays hidden.

A hidden window keeps the size it had when it first updated (conftest.fixed_screen), so
at_size() lays the window's contents out in a frame of the size asked for instead: the one
part packed in the window is placed at that size, and everything in it is arranged as on the
screen (conftest.lay_out). clashes() then lists what would look wrong on the screen.
"""

from conftest import lay_out, pump

TEXT_CLASSES = {"TLabel", "Label", "TButton", "Button", "TCheckbutton", "Checkbutton",
                "TRadiobutton", "Radiobutton"}
PLACED = ("pack", "grid", "place")      # the geometry managers of widgets inside a window


def at_size(window, width, height):
    """Lay out the contents of window (a Toplevel holding one packed part) as if its inside
    were width x height pixels. Returns that part."""
    parts = [child for child in window.winfo_children() if child.winfo_manager() in PLACED]
    assert len(parts) == 1, "a tool's window holds one packed part"
    part = parts[0]
    if part.winfo_manager() != "place":
        part.pack_forget()
    part.place(x=0, y=0, width=width, height=height)
    lay_out(window)
    pump(window)
    return part


def inside(widget):
    """widget and every widget in it, without other windows (tips, menus, dialogs)."""
    yield widget
    for child in widget.winfo_children():
        if child.winfo_manager() in PLACED:
            yield from inside(child)


def box(widget):
    """(left, top, right, bottom) of widget on the screen as laid out."""
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    return x, y, x + widget.winfo_width(), y + widget.winfo_height()


def clashes(part, slack=1):
    """What would look wrong in part, laid out by at_size(): a widget sticking out of the
    widget that holds it, two widgets in one holder that overlap, a label or button narrower
    or lower than its text needs. slack: pixels a box may pass by."""
    found = []
    for widget in inside(part):
        if widget is not part:
            holder = widget.nametowidget(widget.winfo_parent())
            left, top, right, bottom = box(widget)
            h_left, h_top, h_right, h_bottom = box(holder)
            if (left < h_left - slack or top < h_top - slack or right > h_right + slack
                    or bottom > h_bottom + slack):
                found.append(f"{widget} sticks out of {holder}")
        if widget.winfo_class() in TEXT_CLASSES and (
                widget.winfo_width() + slack < widget.winfo_reqwidth()
                or widget.winfo_height() + slack < widget.winfo_reqheight()):
            found.append(f"{widget} is cut off: {widget.winfo_width()}x{widget.winfo_height()} "
                         f"for {widget.winfo_reqwidth()}x{widget.winfo_reqheight()}")
        children = [child for child in widget.winfo_children()
                    if child.winfo_manager() in PLACED
                    and child.winfo_width() > 1 and child.winfo_height() > 1]
        boxes = [(child, box(child)) for child in children]
        for index, (first, a) in enumerate(boxes):
            for second, b in boxes[index + 1:]:
                if (min(a[2], b[2]) - max(a[0], b[0]) > slack
                        and min(a[3], b[3]) - max(a[1], b[1]) > slack):
                    found.append(f"{first} overlaps {second}")
    return found
