# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The ARM X-Ray's picture at every zoom the window can take, from its least size (zoom 1) to
maximized, in steps of 0.01: no text lies over a text, a wire or a block's outline, and names
one under the other keep a gap between their letters (xray_layout.clashes), on the whole
canvas, for finished pictures of each kind of instruction, at 225 % and at 100 %."""

import pytest
from test_gui_run import loaded
from window_layout import at_size
from xray_layout import clashes

from conftest import lay_out
from ares.gui.widgets import scale

HIGH = 3.0                              # Tk's scaling at 225 % on Windows (216 dots per inch)
# A maximized window's inside: the work area under the taskbar, less the title bar.
MAXIMIZED = {"225 %": ((3840, 2000),), "100 %": ((1920, 1017), (3840, 2097))}
STEP = 0.01                             # the steps of the zoom the window chooses
COARSE = 0.05                           # from the largest 1920 x 1080 zoom to the 3840 x 2160 one

PROGRAM = """\
        .global _start
_start: LDR     SP, =stack
        LDR     R1, =table
        MOV     R2, #4              @ a move of an immediate
        LDR     R0, [R1, #4]!       @ a load, with write-back
        STR     R0, [R1, R2]        @ a store, with a register offset
        MLA     R4, R0, R2, R1      @ a multiply: MUL's wires and the value it adds
        PUSH    {R4, R5, LR}        @ a push: one pass for each register
        BL      there               @ a taken branch, with link
        NOP
there:  UMULL   R6, R7, R0, R0      @ an instruction outside the datapath
        SVC     #1                  @ a system call: print an integer
        SVC     #10
        .data
table:  .word   7, 8, 9, 10
        .space  64
stack:  .word   0
"""
# Each kind: the steps that run it, and how its text starts.
KINDS = {"move": (3, "MOV"), "load": (4, "LDR R0"), "store": (5, "STR"), "multiply": (6, "MLA"),
         "push": (7, "PUSH"), "branch": (8, "BL"), "outside": (9, "UMULL"), "svc": (10, "SVC")}


def opened(app):
    app.run("tool_xray")
    window = app.tool_windows["tool_xray"]
    window.connect_button.invoke()
    return window


# Where the names down the control unit's left edge stood when they ran into each other at
# 225 % (RegSrc0 on RegSrc1, Link on Mul), in design pixels from the datapath's top.
CROWDED = {"Op2": 85, "RegSrc0": 93.5, "RegSrc1": 102, "ShiftReg": 112.5, "Link": 121.25,
           "Mul": 130}


@pytest.mark.parametrize("zoom", [1.0, 1.44])
def test_names_that_run_into_each_other_are_caught(app, zoom):
    """The checker reports the control unit's names as they stood when they ran into each
    other at 225 %, at the least zoom and maximized; and none of them as they stand now."""
    before = float(app.root.tk.call("tk", "scaling"))
    app.root.tk.call("tk", "scaling", HIGH)
    try:
        app.run("tool_xray")
        window = app.tool_windows["tool_xray"]
        window.rezoom(zoom)
        canvas, picture = window.canvas, window.picture
        names = dict(picture.signal_names)
        names["Op2"] = next(item for item in picture.titles["Control"]
                            if canvas.itemcget(item, "text") == "Op2")
        now = {pair[:2] for pair in clashes(canvas)}
        assert not {pair for pair in now if set(pair) & set(CROWDED)}
        for name, y in CROWDED.items():
            canvas.coords(names[name], *picture.xy(390, y))
        found = {frozenset(pair[:2]) for pair in clashes(canvas)}
        assert {frozenset(("RegSrc0", "RegSrc1")), frozenset(("Link", "Mul"))} <= found
    finally:
        app.root.tk.call("tk", "scaling", before)


def zooms_of(window, size):
    """Every zoom of the window, from 1 to the zoom it takes maximized on the screens of size:
    in steps of 0.01 up to the first screen's, then in steps of 0.05 up to the second's."""
    found = []
    for (width, height), step in zip(MAXIMIZED[size], (STEP, COARSE)):
        at_size(window.window, width, height)
        window._room_settled()          # the zoom it chooses once its size has settled
        lay_out(window.window)
        last = window.zoom
        zoom = 1.0 if not found else round(found[-1] + step, 2)
        while zoom < last - 1e-9:
            found.append(zoom)
            zoom = round(zoom + step, 2)
        found.append(last)
    return found


# The picture of each zoom is drawn again from nothing (the window's own rezoom()), so a test
# takes about a second for each zoom it checks; the kinds take turns over the zooms, each
# checking every eighth zoom: every zoom is checked once, each kind at five or six zooms at
# 225 % and at a dozen at 100 %, in 16 tests that the workers share.
@pytest.mark.parametrize("size", list(MAXIMIZED))
@pytest.mark.parametrize("kind", list(KINDS))
def test_no_text_lies_over_anything_at_any_zoom(app, tmp_path, kind, size):
    before = float(app.root.tk.call("tk", "scaling"))
    if size == "225 %":
        app.root.tk.call("tk", "scaling", HIGH)
    try:
        loaded(app, tmp_path, PROGRAM)
        window = opened(app)
        window.animate.set(False)       # each Step shows the instruction finished at once
        steps, text = KINDS[kind]
        for _ in range(steps):
            app.run("step")
        assert window.model.view.trace.text.startswith(text)
        if size == "225 %":
            assert scale(window.window) == pytest.approx(2.25, abs=0.01)
        zooms = zooms_of(window, size)
        assert zooms[0] == 1.0 and len(zooms) > {"225 %": 30, "100 %": 80}[size]
        mine = zooms[list(KINDS).index(kind)::len(KINDS)]
        for zoom in mine:
            window.rezoom(zoom)
            assert window.zoom == zoom
            assert clashes(window.canvas) == [], (kind, size, zoom)
    finally:
        app.root.tk.call("tk", "scaling", before)


# Tk's scaling at 125 % and 200 %: the large heading's comma once came down on List's wire there.
OTHER_SCALES = {"125 %": 1.25 * 96 / 72, "200 %": 2.0 * 96 / 72}


@pytest.mark.parametrize("size, zoom", [("125 %", 2.08), ("200 %", 1.6)])
def test_the_large_heading_stays_clear_of_list_at_other_scales(app, tmp_path, size, zoom):
    """A PUSH's last pass, finished, at the zooms where the heading once touched List's wire."""
    before = float(app.root.tk.call("tk", "scaling"))
    app.root.tk.call("tk", "scaling", OTHER_SCALES[size])
    try:
        loaded(app, tmp_path, PROGRAM)
        window = opened(app)
        window.animate.set(False)
        for _ in range(KINDS["push"][0]):
            app.run("step")
        assert window.model.view.trace.text.startswith("PUSH")
        window.rezoom(zoom)
        assert clashes(window.canvas) == [], (size, zoom)
    finally:
        app.root.tk.call("tk", "scaling", before)

