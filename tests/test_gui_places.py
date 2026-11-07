# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The lists of places: the Data Segment's, and the base addresses of the Memory Reference
Visualization and the Bitmap Display, before a program is assembled, with one and after it is
unloaded. A place of no program shows no address and cannot be chosen; current SP says where
the stack starts while SP has its start value 0."""

import gc
import weakref
from tkinter import font as tkfont
from tkinter import ttk

import pytest
from test_gui_assemble import assemble
from test_gui_bitmap import HEAP_PICTURE, YELLOW, bells, bitmap_window, small, top_row, type_base
from test_gui_data import PROGRAM as DATA_PROGRAM
from test_gui_data import cells
from test_gui_memref import BLACK, PROGRAM as MEMREF_PROGRAM
from test_gui_memref import colours, connected, visualization
from test_gui_run import go_to_end, loaded

from ares.gui.execute import page_start
from ares import helptext
from ares.gui.places import (NO_PROGRAM, STACK_TEXT, gray_unavailable, list_width,
                             place_text)
from ares.gui.style import SHADOW
from ares.gui.tools import memref
from ares.gui.tools.bitmap import DATA, HEAP, data_start
from ares.gui.tools.memref import entries
from ares.machine import Machine

NO_DATA, NO_HEAP, NO_TEXT = (f"{name}: no program assembled"
                             for name in (".data", "heap", ".text"))
# Moves SP from its start value 0 through the on-chip memory and DDR3, then back to 0.
STACK = """\
        .global _start
_start: MOV     R0, #7
        PUSH    {R0}                    @ SP = 0xfffffffc
        LDR     SP, =0x00100008
        PUSH    {R0}                    @ SP = 0x00100004
        MOV     SP, #0
        SVC     #10
"""


def pick(box, index):
    """Choose entry index of a drop-down list, as a click in its list or the mouse wheel does
    (Tk's SelectEntry: the field takes the entry's text, then <<ComboboxSelected>>)."""
    box.winfo_id()                      # generated events need the widget's window
    box.tk.call("ttk::combobox::SelectEntry", box, index)
    box.update()


def wheel(box, notch):
    """Turn the mouse wheel a notch over a drop-down list, down (1) or up (-1): Tk chooses
    the next or the previous entry without opening the list, so its -postcommand does not
    run and the entries are those of its last look-up (ttk::combobox::Scroll)."""
    box.winfo_id()                      # generated events need the widget's window
    box.tk.call("ttk::combobox::Scroll", box, notch)
    box.update()


def selected(box):
    """True when the field's whole text is selected, the cursor at its end, as Tk leaves the
    field after a choice."""
    end = len(box.get())
    return (box.selection_present() and box.index("sel.first") == 0
            and box.index("sel.last") == end and box.index("insert") == end)


def opened(box):
    """Do what Tk does as the list opens (ttk::combobox::Post), without showing it: run its
    -postcommand, then make and fill the list."""
    box.tk.eval(box.cget("postcommand"))
    box.tk.call("ttk::combobox::PopdownWindow", box)
    box.tk.call("ttk::combobox::ConfigureListbox", box)


def gray(box):
    """The entries of the list drawn gray, once it opened (opened())."""
    opened(box)
    listbox = f"{box}.popdown.f.l"
    assert box.tk.call(listbox, "get", 0, "end") == box.cget("values")   # filled as by Tk
    found = []
    for index in range(len(box.cget("values"))):
        drawn = {str(box.tk.call(listbox, "itemcget", index, option))
                 for option in ("-foreground", "-selectforeground")}
        assert drawn in ({""}, {SHADOW}), drawn                     # dark, or gray throughout
        if drawn == {SHADOW}:
            found.append(index)
    return found


def unload(app, how):
    """Unload the program: close its file, or assemble it with an error."""
    if how == "close":
        app.run("close")
    else:
        app.editor.current.text.insert("end", "        BOGUS   R0\n")
        assemble(app)
    assert app.machine is None


# The texts -------------------------------------------------------------------------

def test_a_place_shows_its_address_or_that_no_program_is_assembled():
    assert place_text(".data", 0x30) == "0x00000030 (.data)"
    assert place_text("JTAG UART", 0xFF201000) == "0xff201000 (JTAG UART)"
    assert place_text(".data", None) == NO_DATA and place_text("heap", None) == NO_HEAP
    assert NO_PROGRAM == "no program assembled"
    assert STACK_TEXT == "current SP: stack at 0xfffffffc"


def test_a_list_is_wide_enough_for_each_of_its_texts(tk_root):
    font = tkfont.nametofont("TkDefaultFont", root=tk_root)
    texts = (STACK_TEXT, NO_DATA, "0x00000030 (.data)")
    width = list_width(tk_root, texts)
    assert all(font.measure(text) < width * font.measure("0") for text in texts)
    assert list_width(tk_root, ("00",)) == 3            # and one character for the cursor


def test_entries_not_available_are_gray_in_the_list(tk_root):
    box = ttk.Combobox(tk_root, values=["0x00000030 (.data)", NO_HEAP, STACK_TEXT])
    try:
        gray_unavailable(box, [True, False, True])
        listbox = f"{box}.popdown.f.l"
        assert box.tk.call(listbox, "get", 0, "end") == box.cget("values")
        drawn = [(str(box.tk.call(listbox, "itemcget", k, "-foreground")),
                  str(box.tk.call(listbox, "itemcget", k, "-selectforeground")))
                 for k in range(3)]
        assert drawn == [("", ""), (SHADOW, SHADOW), ("", "")]
        assert not box.tk.call("winfo", "ismapped", f"{box}.popdown")      # not shown
        gray_unavailable(box, [True, True, True])           # available again: as the others
        assert str(box.tk.call(listbox, "itemcget", 1, "-foreground")) == ""
    finally:
        box.destroy()


def test_the_memory_reference_places_and_their_texts(build):
    assert entries(None) == [(".data", None, NO_DATA), ("heap", None, NO_HEAP),
                             ("current SP", 0xFFFFFE00, STACK_TEXT), (".text", None, NO_TEXT)]
    machine = Machine(build(STACK))
    end = machine.heap_start            # no data: .data and heap start after the program
    assert [text for _, _, text in entries(machine)] == [
        f"0x{end:08x} (.data)", f"0x{end:08x} (heap)", STACK_TEXT, "0x00000000 (.text)"]
    assert entries(machine)[2] == ("current SP", 0xFFFFFE00, STACK_TEXT)
    machine.set_reg(13, 0x00100004)
    assert entries(machine)[2] == ("current SP", 0x00100000, "0x00100000 (current SP)")
    machine.set_reg(13, 0x40000000)                     # an empty stack at the top of DDR3
    assert entries(machine)[2] == ("current SP", 0x3FFFFE00, "0x3ffffe00 (current SP)")


# The Data Segment -------------------------------------------------------------------

@pytest.mark.parametrize("how", ["close", "errors"])
def test_the_data_segments_places_before_with_and_after_a_program(app, tmp_path, how):
    data = app.execute.data_segment
    box = data.places
    assert box.get() == NO_DATA and box.instate(["disabled"]) and data.table.count == 0
    loaded(app, tmp_path, DATA_PROGRAM)
    assert box.get() == "0x00000018 (.data)" and box.instate(["!disabled"])
    assert box.cget("values") == ("0x00000018 (.data)", STACK_TEXT, "0x00000000 (.text)",
                                  "0xff201000 (JTAG UART)")
    assert gray(box) == []
    unload(app, how)
    assert box.get() == NO_DATA and box.instate(["disabled"]) and data.table.count == 0


def test_the_data_segments_current_sp(app, tmp_path):
    loaded(app, tmp_path, STACK)
    data = app.execute.data_segment
    box = data.places
    assert box.cget("values")[1] == STACK_TEXT
    pick(box, 1)                        # SP's start value 0: the page of 0xfffffffc
    assert box.get() == STACK_TEXT and data.base == 0xFFFFFE00
    assert cells(data, 15)[0] == "0xffffffe0" and cells(data, 15)[8] == "0x00000000"
    app.run("step")
    app.run("step")                     # PUSH {R0}: SP = 0xfffffffc
    opened(box)                         # the list opens: the field shows the entry chosen
    assert box.cget("values")[1] == "current SP" and box.get() == "current SP"
    pick(box, 1)
    assert data.base == 0xFFFFFE00 and cells(data, 15)[8] == "0x00000007"
    app.run("step")
    app.run("step")                     # SP = 0x00100004: the page from SP's row
    pick(box, 1)
    assert data.base == 0x00100000 and cells(data, 0)[2] == "0x00000007"
    pick(box, 0)
    app.run("step")                     # MOV SP, #0: the start value again
    opened(box)
    assert box.cget("values")[1] == STACK_TEXT and box.get() == box.cget("values")[0]
    pick(box, 1)
    assert box.get() == STACK_TEXT and data.base == 0xFFFFFE00


def test_the_data_segments_current_sp_chosen_with_the_wheel(app, tmp_path):
    """The wheel chooses from the texts of the list's last look-up: the field then says
    what SP is now, as the page shown does, and its text is selected as after a click."""
    data = app.execute.data_segment
    box = data.places
    wheel(box, 1)                       # no program: the list is disabled
    assert box.get() == NO_DATA and data.table.count == 0
    loaded(app, tmp_path, STACK)
    for _ in range(4):
        app.run("step")                 # SP = 0x00100004; the list was looked up at SP 0
    wheel(box, 1)                       # .data -> current SP
    assert box.get() == "current SP" and box.cget("values")[1] == "current SP"
    assert data.base == 0x00100000 and selected(box)
    opened(box)                         # looked up at SP 0x00100004
    pick(box, 0)
    app.run("step")                     # MOV SP, #0
    wheel(box, 1)
    assert box.get() == STACK_TEXT and box.cget("values")[1] == STACK_TEXT
    assert data.base == 0xFFFFFE00 and selected(box)
    wheel(box, -1)                      # .data: as listed
    assert box.current() == 0 and data.base == page_start(data.data_start())
    assert selected(box)


# The Memory Reference Visualization ------------------------------------------------------

def test_memref_without_a_program_lists_no_address_of_the_program(app):
    window = visualization(app)
    box, model = window.base_list, window.model
    assert list(box.cget("values")) == [NO_DATA, NO_HEAP, STACK_TEXT, NO_TEXT]
    assert box.get() == NO_DATA and str(box.cget("state")) == "readonly"
    assert gray(box) == [0, 1, 3]
    assert not any(model.counts) and colours(window, 256) == [BLACK] * 256


def test_memref_cannot_choose_a_place_not_available(app):
    window = visualization(app)
    box, model = window.base_list, window.model
    base = model.base
    for index in (0, 1, 3):
        pick(box, index)
        assert box.get() == NO_DATA and model.base == base
    pick(box, 2)                        # current SP: the page that holds 0xfffffffc
    assert box.get() == STACK_TEXT and model.base == 0xFFFFFE00
    assert model.unit_of(0xFFFFFFFC) == 127
    pick(box, 3)
    assert box.get() == STACK_TEXT and model.base == 0xFFFFFE00


def test_memref_counts_the_next_program_on_the_stack_chosen_without_one(app, tmp_path):
    window = connected(app)
    pick(window.base_list, 2)
    loaded(app, tmp_path, MEMREF_PROGRAM)       # SP 0 again: the same page, connected
    assert window.model.base == 0xFFFFFE00 and window.base_list.get() == STACK_TEXT
    go_to_end(app)                              # PUSH {R0, R1}: the last two words of memory
    assert window.model.counts[126:128] == [1, 1] and sum(window.model.counts) == 2


def test_memref_with_a_program_every_place_has_its_address(app, tmp_path):
    window = visualization(app)
    loaded(app, tmp_path, MEMREF_PROGRAM)
    box, model = window.base_list, window.model
    values = app.machine.program.label_address("values")
    texts = [f"0x{values:08x} (.data)", f"0x{values + 16:08x} (heap)", STACK_TEXT,
             "0x00000000 (.text)"]
    assert list(box.cget("values")) == texts
    assert box.get() == texts[0] and model.base == values and gray(box) == []
    pick(box, 3)
    assert box.get() == texts[3] and model.base == 0


@pytest.mark.parametrize("how", ["close", "errors"])
def test_memref_after_the_program_is_unloaded(app, tmp_path, how):
    loaded(app, tmp_path, MEMREF_PROGRAM)
    window = connected(app)
    go_to_end(app)
    box, model = window.base_list, window.model
    base, counts = model.base, list(model.counts)
    assert counts[:4] == [1, 2, 0, 10]
    unload(app, how)
    assert list(box.cget("values")) == [NO_DATA, NO_HEAP, STACK_TEXT, NO_TEXT]
    assert box.get() == NO_DATA and gray(box) == [0, 1, 3]
    assert model.base == base and model.counts == counts        # the display stays
    pick(box, 1)
    assert box.get() == NO_DATA and model.base == base and model.counts == counts
    if how == "close":
        loaded(app, tmp_path, MEMREF_PROGRAM, "again.s")        # the same place: counts go on
        assert box.get() == f"0x{base:08x} (.data)" and model.counts == counts


def test_memref_current_sp(app, tmp_path):
    loaded(app, tmp_path, STACK)
    window = visualization(app)
    box, model = window.base_list, window.model
    pick(box, 2)
    assert box.get() == STACK_TEXT and model.base == 0xFFFFFE00
    for _ in range(4):
        app.run("step")                 # SP = 0x00100004
    opened(box)
    assert box.cget("values")[2] == "0x00100000 (current SP)"
    assert box.get() == STACK_TEXT      # the base stays until it is chosen again
    pick(box, 2)
    assert box.get() == "0x00100000 (current SP)" and model.base == 0x00100000
    app.run("step")                     # MOV SP, #0
    opened(box)
    assert box.cget("values")[2] == STACK_TEXT and box.get() == "0x00100000 (current SP)"
    app.run("close")                    # unloaded: current SP stays as chosen, available
    assert box.get() == "0x00100000 (current SP)" and model.base == 0x00100000
    assert box.cget("values")[2] == STACK_TEXT and gray(box) == [0, 1, 3]


def test_memref_current_sp_chosen_with_the_wheel(app, tmp_path):
    """The wheel chooses from the texts of the list's last look-up: current SP is SP's page
    as SP is now, in the field as in the display."""
    loaded(app, tmp_path, STACK)
    window = visualization(app)
    box, model = window.base_list, window.model
    for _ in range(4):
        app.run("step")                 # SP = 0x00100004; the list was looked up at SP 0
    wheel(box, 1)
    wheel(box, 1)                       # .data -> heap -> current SP
    assert box.get() == "0x00100000 (current SP)" and model.base == 0x00100000
    assert box.cget("values")[2] == box.get() and selected(box)
    opened(box)                         # looked up at SP 0x00100004
    pick(box, 1)
    app.run("step")                     # MOV SP, #0
    wheel(box, 1)
    assert box.get() == STACK_TEXT and model.base == 0xFFFFFE00
    assert box.cget("values")[2] == STACK_TEXT and selected(box)


def test_memref_the_wheel_passes_no_place_not_available(app):
    window = visualization(app)
    box, model = window.base_list, window.model
    base = model.base
    wheel(box, 1)                       # .data -> heap: not available
    assert box.get() == NO_DATA and model.base == base and selected(box)
    pick(box, 2)
    for notch in (1, -1):               # .text, heap: not available
        wheel(box, notch)
        assert box.get() == STACK_TEXT and model.base == 0xFFFFFE00 and selected(box)


# The Bitmap Display -------------------------------------------------------------------

def test_bitmap_without_a_program_lists_no_address(app):
    window = bitmap_window(app)
    box = window.base_box
    assert box.cget("values") == (NO_DATA, NO_HEAP)
    assert box.get() == NO_DATA and window.model.base == DATA
    assert gray(box) == [0, 1]
    assert top_row(window) == [0, 0, 0]                # black: no words are read


def test_bitmap_cannot_choose_a_place_without_a_program(app):
    window = small(app, connect=False)
    box, model = window.base_box, window.model
    rings = bells(window)
    pick(box, 1)
    assert box.get() == NO_DATA and model.base == DATA and rings == []
    wheel(box, 1)
    assert box.get() == NO_DATA and model.base == DATA and selected(box)
    for typed in ("heap", NO_HEAP, ".data"):            # typed: refused as a wrong address
        type_base(window, typed)
        assert box.get() == NO_DATA and model.base == DATA
    assert rings == [1, 1, 1]
    type_base(window, "0x00100000")                     # an address of DDR3 stays allowed
    assert model.base == 0x00100000 and box.get() == "0x00100000" and rings == [1, 1, 1]
    pick(box, 0)
    assert box.get() == "0x00100000" and model.base == 0x00100000
    box.delete(0, "end")
    box.insert(0, "0x2000")                             # typed, not applied yet
    pick(box, 1)
    assert box.get() == "0x2000" and model.base == 0x00100000      # the field keeps it


def test_a_closed_bitmap_display_is_let_go(app):
    """The trace that follows its field's text goes with the window: Tcl would otherwise
    keep the window's object, and the words of its display."""
    window = bitmap_window(app)
    variable = window.field_text
    assert len(variable.trace_info()) == 1
    alive = weakref.ref(window)
    window.close()
    window.close()                      # a second time changes nothing
    assert variable.trace_info() == []
    app._open_tools()                   # the main window forgets the closed one
    del window
    gc.collect()
    assert alive() is None


@pytest.mark.parametrize("how", ["close", "errors"])
def test_bitmap_places_with_a_program_and_after_it(app, tmp_path, how):
    window = small(app)
    box, model = window.base_box, window.model
    loaded(app, tmp_path, HEAP_PICTURE)
    data, heap = data_start(app.program), app.machine.heap_start
    assert box.cget("values") == (f"0x{data:08x} (.data)", f"0x{heap:08x} (heap)")
    assert box.get() == f"0x{data:08x} (.data)" and gray(box) == []
    pick(box, 1)
    assert model.base == HEAP and box.get() == f"0x{heap:08x} (heap)"
    go_to_end(app)
    assert top_row(window) == [0, YELLOW, 0]
    unload(app, how)
    assert box.cget("values") == (NO_DATA, NO_HEAP) and box.get() == NO_HEAP
    assert gray(box) == [0, 1] and model.base == HEAP
    assert top_row(window) == [0, YELLOW, 0]           # the picture stays
    pick(box, 0)
    assert box.get() == NO_HEAP and model.base == HEAP


# Widths ---------------------------------------------------------------------------------

def test_each_list_shows_its_longest_text_whole(app):
    """In the font of the field, which is bold, and of its open list."""
    def fits(box, text):
        font = tkfont.nametofont(str(box.cget("font")), root=app.root)
        return font.measure(text) < int(box.cget("width")) * font.measure("0")
    assert fits(app.execute.data_segment.places, STACK_TEXT)
    assert fits(visualization(app).base_list, STACK_TEXT)
    assert fits(bitmap_window(app).base_box, NO_DATA)


def test_a_list_field_and_its_open_list_have_the_font_list_width_measures_in(app):
    box = app.execute.data_segment.places
    assert str(box.cget("font")) == "TkDefaultFont"
    popdown = box.tk.call("ttk::combobox::PopdownWindow", box)
    assert str(box.tk.call(f"{popdown}.f.l", "cget", "-font")) == "TkDefaultFont"


# Help -----------------------------------------------------------------------------------

def test_the_help_quotes_the_list_as_it_reads():
    words = " ".join(helptext.DEBUGGING.split())
    assert f'reads "{STACK_TEXT}"' in words


def test_the_memory_reference_help_keeps_current_sp_apart_from_the_data_segment():
    """current SP can be chosen without a program; the Data Segment's list cannot (it is
    disabled until a program is assembled), and the Help does not say it can."""
    text = " ".join(memref.HELP.split())
    assert ("current SP is the page of the stack pointer, as the Data Segment shows it. "
            "Unlike the places of the program, it can be chosen also without a program. "
            "While SP has its start value 0 the list says "
            '"current SP: stack at 0xfffffffc"') in text
