# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Floating Point Representation window: its fields, how they are applied, the formula
and the triangles, and following a register S0-S31 of the program while connected.

Hidden windows never give a widget the keyboard focus: a test tells the window
where the focus went when it leaves a field (see test_gui_editing).
"""

import time
from tkinter import font as tkfont

import pytest
from conftest import press_key
from test_gui_assemble import assemble
from test_gui_look import RETURN_KEYS, all_buttons, framed, move_focus
from test_gui_run import go_to_end, loaded, run_until
from test_responsiveness import pictures

from ares.floats import SINGLE_NAN
from ares.gui.tools.fpr import (ALONE, DIGITS, EXPLAINED, FIELDS, FOLLOWS, HEX_COLOUR,
                                NO_PROGRAM, NOTES, SAY, TIPS, WRITES, FloatWindow, formula,
                                texts, wrong)
from ares.runner import State
from ares.gui.tools.frame import paragraphs

PROGRAM = """\
        .data
values: .float  1.5, -0.1
        .global _start
        .text
_start: LDR     R1, =values
        VLDR    S2, [R1]
        VLDR    S3, [R1, #4]
        VADD.F32 S4, S2, S3
        SVC     #10
"""
ONE_AND_A_HALF, MINUS_A_TENTH, SUM = 0x3FC00000, 0xBDCCCCCD, 0x3FB33333     # 1.5, -0.1, 1.4
SPIN = """\
        .global _start
        .text
_start: ADD     R0, R0, #1
        VMOV    S0, R0
        B       _start
"""
READ = ".global _start\n_start: SVC #5\n        MOV R2, #9\n        SVC #10\n"


def fpr(app):
    """Open the tool (or bring it to the front); returns its window."""
    app.run("tool_fpr")
    return app.tool_windows["tool_fpr"]


def choose(window, register):
    """Choose Sregister in the list at the bottom, as a click in it does."""
    box = window.register_box
    box.current(register)
    box.winfo_id()                      # generated events need the widget's window
    box.event_generate("<<ComboboxSelected>>")


def connected(app, register=0):
    window = fpr(app)
    choose(window, register)
    window.connect_button.invoke()
    assert window.model.connected
    return window


def shown(window):
    return {name: variable.get() for name, variable in window.variables.items()}


def type_into(window, field, text, key="<Key-Return>"):
    """Type text into a field (in place of what it shows) and press key there."""
    window.variables[field].set(text)
    press_key(window.entries[field], key)


def leave(window, field, monkeypatch, widget):
    """The keyboard focus left a field for widget (None: another program came to the front)."""
    monkeypatch.setattr(window, "_focus_path", lambda: str(widget) if widget is not None else "")
    entry = window.entries[field]
    entry.winfo_id()
    entry.event_generate("<FocusOut>")
    entry.update_idletasks()


def test_on_the_way_to_another_ares_window_no_widget_has_the_focus_for_a_while(app, monkeypatch):
    # Windows takes the focus away first and gives it to the main window after that.
    window = fpr(app)
    entry = window.entries["decimal"]
    entry.delete(0, "end")
    entry.insert(0, "1.5")
    monkeypatch.setattr(window, "_focus_path", lambda: "")
    entry.winfo_id()
    entry.event_generate("<FocusOut>")
    monkeypatch.setattr(window, "_focus_path", lambda: str(app.root))
    entry.update_idletasks()
    assert shown(window) == texts(ONE_AND_A_HALF)


def bells(window, field):
    rings = []
    window.entries[field].bell = lambda: rings.append(1)
    return rings


def instructions(window):
    return window.instructions.cget("text")


def read_only(window):
    states = {entry.instate(["readonly"]) for entry in window.entries.values()}
    assert len(states) == 1
    return states.pop()


def formula_items(window):
    """The canvas items of the formula that are shown, from the left."""
    canvas = window.canvas
    return [item for item in canvas.find_withtag("formula")
            if canvas.itemcget(item, "state") != "hidden"]


def drawn_formula(window):
    return [window.canvas.itemcget(item, "text") for item in formula_items(window)]


def font_of(widget, item=None):
    """The font of a widget, or of a canvas item."""
    name = widget.cget("font") if item is None else widget.itemcget(item, "font")
    return tkfont.nametofont(str(name), root=widget)


# Opening -----------------------------------------------------------------------------

def test_the_tool_opens_from_the_menu(app, hidden_windows):
    menu, index = app._menu_items["tool_fpr"]
    assert menu.entrycget(index, "state") == "normal"
    menu.invoke(index)
    window = app.tool_windows["tool_fpr"]
    assert isinstance(window, FloatWindow) and hidden_windows.shows(window.window)
    assert window.window.title() == "Floating Point Representation"
    assert list(all_buttons(window.window)) == ["Connect to ARM", "Reset", "Close"]
    assert hidden_windows.focus is window.connect_button
    assert shown(window) == texts(0) == {"hex": "00000000", "sign": "0", "exponent": "0" * 8,
                                         "fraction": "0" * 23, "decimal": "0.0"}
    assert window.register_box.cget("values") == tuple(f"S{n}" for n in range(32))
    assert window.register_box.get() == "S0" and window.register_box.instate(["readonly"])
    assert instructions(window) == SAY[ALONE] and not read_only(window)
    assert window.instructions.master.cget("text") == "Instructions"
    assert {name: tip.text for name, tip in window.field_tips.items()} == TIPS
    canvas = window.canvas
    assert [canvas.itemcget(item, "text") for item in canvas.find_withtag("explanation")
            if canvas.type(item) == "text"] == list(EXPLAINED)
    assert [canvas.itemcget(item, "text") for item in canvas.find_withtag("label")] == [
        "sign", "exponent", "fraction"]


def test_the_fields_fonts_and_colours(app):
    window = fpr(app)
    entries = window.entries
    assert str(entries["hex"].cget("foreground")) == HEX_COLOUR
    assert str(entries["decimal"].cget("foreground")) == "#0000FF"
    for name in FIELDS:
        assert font_of(entries[name]).metrics("fixed"), name    # monospace: digits line up
        assert str(entries[name].cget("justify")) == "right"
        if name in DIGITS:                                   # the text fills the field exactly
            assert int(entries[name].cget("width")) == DIGITS[name]
    assert font_of(entries["hex"]).actual("size") > font_of(entries["sign"]).actual("size")


# Typing ------------------------------------------------------------------------------

def test_a_value_typed_into_any_field_shows_in_all(app):
    window = fpr(app)
    type_into(window, "decimal", "1.5")
    assert shown(window) == texts(ONE_AND_A_HALF)
    type_into(window, "hex", "40490fdb")
    assert shown(window)["hex"] == "40490FDB" and shown(window)["decimal"] == "3.1415927"
    type_into(window, "sign", "1", "<Key-KP_Enter>")
    assert shown(window)["decimal"] == "-3.1415927"
    type_into(window, "exponent", "10000001")       # 129: twice as much
    assert shown(window)["decimal"] == "-6.2831855"
    type_into(window, "fraction", "1")               # filled up with zeros on the left
    assert shown(window) == texts(0xC0800001) and shown(window)["decimal"] == "-4.0000005"
    assert window.model.bits == 0xC0800001 and not window.model.connected
    assert instructions(window) == SAY[ALONE]


def test_leaving_a_field_applies_it(app, monkeypatch):
    window = fpr(app)
    window.variables["hex"].set("3f800000")
    leave(window, "hex", monkeypatch, window.entries["sign"])       # Tab to the sign
    assert shown(window)["decimal"] == "1.0" and shown(window)["hex"] == "3F800000"
    window.variables["decimal"].set("2")
    leave(window, "decimal", monkeypatch, None)         # another program in front: it waits
    assert shown(window)["decimal"] == "2" and window.model.bits == 0x3F800000
    leave(window, "decimal", monkeypatch, app.root)     # then a click in the main window
    assert window.model.bits == 0x40000000 and shown(window)["decimal"] == "2.0"
    window.variables["sign"].set("1")
    leave(window, "sign", monkeypatch, window.entries["sign"])      # the focus stayed there
    assert window.model.bits == 0x40000000


@pytest.mark.parametrize("field, text", [
    ("hex", "XYZ"), ("hex", "123456789"), ("sign", "2"), ("exponent", "111111111"),
    ("fraction", "1" * 24), ("decimal", "1.5.5"), ("decimal", "0x3fc00000"),
])
def test_a_wrong_entry_rings_and_stays_in_its_field(app, hidden_windows, monkeypatch, field,
                                                     text):
    window = fpr(app)
    type_into(window, "decimal", "1.5")
    rings = bells(window, field)
    type_into(window, field, text)
    assert rings == [1] and hidden_windows.focus is window.entries[field]
    assert shown(window) == {**texts(ONE_AND_A_HALF), field: text}
    assert window.model.bits == ONE_AND_A_HALF and instructions(window) == wrong(field, text)
    other = window.entries["hex" if field != "hex" else "decimal"]
    hidden_windows.focus = None
    leave(window, field, monkeypatch, other)            # leaving it: the same again
    assert rings == [1, 1] and hidden_windows.focus is window.entries[field]
    assert shown(window)[field] == text
    type_into(window, field, texts(ONE_AND_A_HALF)[field])     # put back as it was
    assert shown(window) == texts(ONE_AND_A_HALF) and instructions(window) == SAY[ALONE]
    type_into(window, field, text)
    type_into(window, field, texts(0xC0490FDB)[field])  # corrected: it is taken
    assert window.model.bits != ONE_AND_A_HALF and instructions(window) == SAY[ALONE]


def test_a_wrong_entry_stays_when_the_focus_passes_through_another_field(app, hidden_windows,
                                                                         monkeypatch):
    """Tab, or a click in another field, after a wrong entry: the wrong field takes the focus
    back at once, so the other field loses it again; the wrong entry stays as it is."""
    window = fpr(app)
    type_into(window, "decimal", "1.5")
    rings, other_rings = bells(window, "hex"), bells(window, "sign")
    type_into(window, "hex", "XYZ")
    leave(window, "hex", monkeypatch, window.entries["sign"])       # Tab to the sign
    assert rings == [1, 1] and hidden_windows.focus is window.entries["hex"]
    leave(window, "sign", monkeypatch, window.entries["hex"])       # the focus comes back
    assert shown(window) == {**texts(ONE_AND_A_HALF), "hex": "XYZ"} and other_rings == []
    assert instructions(window) == wrong("hex", "XYZ") and window.model.bits == ONE_AND_A_HALF
    type_into(window, "hex", "3F800000")                            # corrected: it is taken
    assert shown(window) == texts(0x3F800000) and instructions(window) == SAY[ALONE]


def test_escape_puts_back_what_the_field_showed(app):
    window = fpr(app)
    window.variables["hex"].set("12")
    press_key(window.entries["hex"], "<Key-Escape>")
    assert shown(window)["hex"] == "00000000" and window.window is not None
    bells(window, "sign")
    type_into(window, "sign", "7")
    press_key(window.entries["sign"], "<Key-Escape>")
    assert shown(window) == texts(0) and instructions(window) == SAY[ALONE]
    press_key(window.entries["sign"], "<Key-Escape>")   # left as it was: Escape closes
    assert window.window is None


def test_a_nan_keeps_its_bits(app, tmp_path, monkeypatch):
    window = fpr(app)
    type_into(window, "hex", "7FC00001")
    assert shown(window)["decimal"] == "NaN"
    type_into(window, "decimal", "NaN")                 # left as it was
    assert window.model.bits == 0x7FC00001
    window.variables["decimal"].set(" NaN ")
    leave(window, "decimal", monkeypatch, window.entries["hex"])
    assert window.model.bits == 0x7FC00001 and shown(window)["decimal"] == "NaN"
    type_into(window, "decimal", "nan")                 # typed: the default NaN
    assert window.model.bits == SINGLE_NAN and shown(window)["hex"] == "7FC00000"
    loaded(app, tmp_path, PROGRAM)
    app.change_single(5, 0xFFC00001)                    # a negative NaN with a payload
    choose(window, 5)
    window.connect_button.invoke()
    assert shown(window)["hex"] == "FFC00001" and shown(window)["decimal"] == "NaN"
    type_into(window, "decimal", "NaN")
    assert app.machine.single(5) == 0xFFC00001 and shown(window)["hex"] == "FFC00001"


# What the window draws -------------------------------------------------------------------

def test_the_formula_shows_how_the_bits_give_the_value(app):
    window = fpr(app)
    canvas = window.canvas
    type_into(window, "decimal", "-0.1")
    parts, label, note = formula(MINUS_A_TENTH)
    assert drawn_formula(window) == [text for text, _, _ in parts]
    assert "".join(drawn_formula(window)) == "(-1)1 × 2-4 × 1.10011001100110011001101 ="
    items = formula_items(window)
    tops = [canvas.bbox(item)[1] for item in items]
    for item, top, (text, kind, _) in zip(items, tops, parts):
        font = font_of(canvas, item)
        assert font.actual("underline") == (kind == "hidden"), text
        if kind == "power":                             # raised, and smaller
            assert top < tops[0]
            assert font.actual("size") < font_of(canvas, items[0]).actual("size")
    assert canvas.itemcget(window.label, "text") == label == "123 - 127"
    assert canvas.itemcget(window.note, "text") == note == NOTES["normal"]
    check_arrows(window, parts)
    type_into(window, "hex", "00000001")
    assert canvas.itemcget(window.label, "text") == "0 + 1 - 127"
    assert canvas.itemcget(window.note, "text") == NOTES["small"]
    assert drawn_formula(window)[3] == "-126" and drawn_formula(window)[5] == "0"
    type_into(window, "hex", "FF800000")
    assert drawn_formula(window) == ["(-1)", "1", " × ", "Infinity", " ="]
    assert canvas.itemcget(window.label, "text") == "255"
    assert canvas.itemcget(window.note, "text") == NOTES["infinite"]
    check_arrows(window, formula(0xFF800000)[0])
    type_into(window, "hex", "7FC00000")
    assert drawn_formula(window) == ["NaN", " ="]
    assert canvas.itemcget(window.note, "text") == NOTES["nan"]
    check_arrows(window, formula(SINGLE_NAN)[0])


def check_arrows(window, parts):
    """Each binary field's arrow starts below the field and ends above the parts made from it;
    the exponent's label sits on its arrow."""
    canvas = window.canvas
    items = formula_items(window)
    for name, arrow in window.arrows.items():
        x0, y0, x1, y1 = canvas.coords(arrow)
        left, top, right, bottom = canvas.bbox(window.items[name])
        assert left < x0 < right and y0 > bottom
        boxes = [canvas.bbox(item) for item, (_, _, roles) in zip(items, parts) if name in roles]
        assert min(box[0] for box in boxes) <= x1 <= max(box[2] for box in boxes), name
        assert y1 <= min(box[1] for box in boxes)
    x0, y0, x1, y1 = canvas.coords(window.arrows["exponent"])
    left, top, right, bottom = canvas.bbox(window.label)
    assert left < (x0 + x1) / 2 < right and top < (y0 + y1) / 2 < bottom


def test_each_hexadecimal_digit_points_at_its_four_bits(app):
    window = fpr(app)
    canvas = window.canvas

    def characters(name):
        """(left, right) of each character the field shows."""
        entry = window.entries[name]
        font = font_of(entry)
        width, count = font.measure("0"), DIGITS[name]
        assert font.measure(shown(window)[name]) == count * width
        x = canvas.coords(window.items[name])[0] + (entry.winfo_reqwidth() - count * width) / 2
        return [(x + k * width, x + (k + 1) * width) for k in range(count)]
    bits = characters("sign") + characters("exponent") + characters("fraction")
    digits = characters("hex")
    hex_bottom = canvas.coords(window.items["hex"])[1] + window.entries["hex"].winfo_reqheight()
    bits_top = canvas.coords(window.items["sign"])[1]
    triangles = canvas.find_withtag("triangle")
    assert len(triangles) == 8
    for digit, item in enumerate(triangles):
        x, y, left, base, right, base_again = canvas.coords(item)
        assert digits[digit][0] < x < digits[digit][1] and y == hex_bottom
        assert base == base_again == bits_top
        assert bits[4 * digit][0] <= left < bits[4 * digit][1]
        assert bits[4 * digit + 3][0] < right <= bits[4 * digit + 3][1]
        assert canvas.itemcget(item, "fill") == HEX_COLOUR
    # The fields do not overlap, and the explanations and the decimal field are right of all.
    boxes = [canvas.bbox(window.items[name]) for name in ("sign", "exponent", "fraction")]
    assert boxes[0][2] < boxes[1][0] and boxes[1][2] < boxes[2][0]
    right = canvas.coords(window.items["decimal"])[0]
    assert all(min(canvas.coords(item)[::2]) >= right
               for item in canvas.find_withtag("explanation"))
    assert max(box[2] for box in boxes) < right
    assert canvas.bbox("formula")[2] < right and canvas.bbox(window.note)[2] < right


# Connected ---------------------------------------------------------------------------

def test_connected_it_follows_the_register(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app, 3)
    assert window.model.machine is app.machine
    assert instructions(window) == SAY[WRITES].format(register="S3")
    for _ in range(3):
        app.run("step")
    assert shown(window) == texts(MINUS_A_TENTH)
    app.run("backstep")
    assert shown(window)["decimal"] == "0.0"
    go_to_end(app)
    assert shown(window)["decimal"] == "-0.1"
    app.run("reset")                                    # Reset, F12: S3 is 0 again
    assert shown(window)["decimal"] == "0.0"
    for _ in range(3):
        app.run("step")
    assert shown(window)["decimal"] == "-0.1"
    pane = app.coproc10                                 # a change in the register tabs
    pane.edit(3)
    pane.editor.delete(0, "end")
    pane.editor.insert(0, "2.5")
    pane.commit()
    assert shown(window)["decimal"] == "2.5"
    app.coproc11.edit(1)                                # D1: S3 is its high half
    app.coproc11.editor.delete(0, "end")
    app.coproc11.editor.insert(0, "0x3ff0000000000000")
    app.coproc11.commit()
    assert shown(window)["hex"] == "3FF00000"
    assemble(app)                                       # a new program: still connected
    assert window.model.connected and window.model.machine is app.machine
    assert shown(window)["decimal"] == "0.0"


def test_a_value_typed_goes_into_the_register_and_the_tabs_show_it(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app, 4)
    type_into(window, "decimal", "2.5")                 # ready
    assert app.machine.single(4) == 0x40200000
    assert app.coproc10.values()[4] == 0x40200000 and app.coproc11.values()[2] == 0x40200000
    app.run("step")                                     # paused
    type_into(window, "hex", "3F800000")
    assert app.machine.single(4) == 0x3F800000 and app.coproc10.values()[4] == 0x3F800000
    go_to_end(app)                                      # finished: VADD wrote S4
    assert shown(window)["decimal"] == "1.4"
    type_into(window, "sign", "1")
    assert app.machine.single(4) == 0xBFB33333 and app.coproc10.values()[4] == 0xBFB33333
    assert app.machine.single(5) == 0                   # only the register followed


def test_while_the_program_runs_the_fields_only_follow(app, tmp_path):
    loaded(app, tmp_path, SPIN)
    window = connected(app, 0)
    assert not read_only(window)
    app.run("go")
    run_until(app, lambda: window.model.bits != 0)      # it follows during the run
    assert read_only(window) and instructions(window) == SAY[FOLLOWS].format(register="S0")
    assert shown(window) == texts(window.model.bits)
    window.reset_button.invoke()                        # the fields only follow: nothing
    assert window.model.bits != 0
    app.run("pause")
    assert not read_only(window) and instructions(window) == SAY[WRITES].format(register="S0")
    assert shown(window) == texts(app.machine.single(0))
    type_into(window, "decimal", "-1")
    assert app.machine.single(0) == 0xBF800000
    app.run("stop")
    type_into(window, "decimal", "-2")                  # stopped: values can change
    assert app.machine.single(0) == 0xC0000000


def test_while_the_program_waits_for_input_the_fields_only_follow(app, tmp_path):
    loaded(app, tmp_path, READ)
    window = connected(app, 1)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    assert read_only(window) and instructions(window) == SAY[FOLLOWS].format(register="S1")
    app.run("pause")
    assert app.machine.request is not None and not read_only(window)
    type_into(window, "hex", "40490FDB")
    assert app.machine.single(1) == 0x40490FDB
    # As after a change in the register tabs, the read asks again when the program goes on.
    assert app.machine.request is None
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)


def test_a_tool_changes_a_register_only_when_values_can_change(app, tmp_path):
    """App.change_single, as an edit in Coproc 10: not without a program, nor while it runs
    or waits; else the register tabs show the value at once."""
    assert not app.change_single(1, 0x3F800000)
    loaded(app, tmp_path, READ)
    assert app.change_single(1, 0x3F800000)
    assert app.machine.single(1) == 0x3F800000 and app.coproc10.values()[1] == 0x3F800000
    assert app.coproc11.values()[0] == 0x3F80000000000000
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    assert not app.change_single(1, 0x40000000) and app.machine.single(1) == 0x3F800000
    app.run("stop")
    assert app.change_single(1, 0x40000000) and app.coproc10.values()[1] == 0x40000000


def test_choosing_another_register(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = fpr(app)
    go_to_end(app)
    choose(window, 2)                                   # not connected: nothing changes
    assert window.model.register == 2 and shown(window) == texts(0)
    assert instructions(window) == SAY[ALONE]
    window.connect_button.invoke()
    assert shown(window) == texts(ONE_AND_A_HALF)
    assert instructions(window) == SAY[WRITES].format(register="S2")
    choose(window, 4)
    assert shown(window) == texts(SUM)
    assert instructions(window) == SAY[WRITES].format(register="S4")
    type_into(window, "decimal", "8")
    assert app.machine.single(4) == 0x41000000 and app.machine.single(2) == ONE_AND_A_HALF


def test_connected_without_a_program_nothing_is_written(app, tmp_path):
    window = connected(app)
    assert window.model.machine is None
    assert instructions(window) == SAY[NO_PROGRAM].format(register="S0")
    type_into(window, "decimal", "1.5")
    assert shown(window) == texts(ONE_AND_A_HALF) and not read_only(window)
    loaded(app, tmp_path, PROGRAM)                      # S0 of the program
    assert shown(window) == texts(0) and instructions(window) == SAY[WRITES].format(
        register="S0")


def test_closing_the_programs_file_keeps_it_connected(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app, 2)
    go_to_end(app)
    app.run("close")
    assert app.machine is None and window.model.connected and window.model.machine is None
    assert shown(window)["decimal"] == "1.5"
    assert instructions(window) == SAY[NO_PROGRAM].format(register="S2")
    assert window.connect_button.cget("text") == "Disconnect from ARM"
    type_into(window, "decimal", "3")
    assert shown(window)["decimal"] == "3.0"
    loaded(app, tmp_path, PROGRAM, "other.s")
    assert window.model.machine is app.machine and shown(window)["decimal"] == "0.0"


def test_the_reset_button(app, tmp_path):
    window = fpr(app)
    type_into(window, "decimal", "1.5")
    window.reset_button.invoke()
    assert shown(window) == texts(0) and instructions(window) == SAY[ALONE]
    loaded(app, tmp_path, PROGRAM)
    choose(window, 2)
    window.connect_button.invoke()
    go_to_end(app)
    assert shown(window)["decimal"] == "1.5"
    window.reset_button.invoke()                        # the register too
    assert shown(window) == texts(0)
    assert app.machine.single(2) == 0 and app.coproc10.values()[2] == 0


def test_disconnecting_keeps_the_value(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app, 4)
    go_to_end(app)
    window.connect_button.invoke()
    assert not window.model.connected and shown(window)["decimal"] == "1.4"
    assert instructions(window) == SAY[ALONE]
    type_into(window, "decimal", "2")
    assert app.machine.single(4) == SUM                 # a converter again: nothing written
    app.run("reset")
    assert shown(window)["decimal"] == "2.0"


def test_refreshing_shows_only_what_changed(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app, 2)
    shows = []
    show = window.show
    window.show = lambda: shows.append(1) or show()
    app.run("step")                                     # LDR: S2 stays 0
    assert shows == []
    app.run("step")                                     # VLDR S2
    assert len(shows) == 1
    app.run("step")
    app.run("reset")                                    # back to 0
    assert len(shows) == 2


# Keys, help, pictures and speed ---------------------------------------------------------

@pytest.mark.parametrize("key", RETURN_KEYS)
def test_return_in_a_field_applies_it_and_presses_no_button(app, key):
    """No button has the black frame while a field has the focus."""
    window = fpr(app)
    buttons = all_buttons(window.window)
    pressed = []
    for label, button in buttons.items():
        button.configure(command=lambda label=label: pressed.append(label))
    for name in FIELDS:
        move_focus(None, window.entries[name])
        assert framed(buttons) == [], name
        press_key(window.entries[name], key)
    assert pressed == []
    move_focus(window.entries["decimal"], window.register_box)
    assert framed(buttons) == ["Connect to ARM"]
    press_key(window.register_box, key)                 # elsewhere: the framed button
    assert pressed == ["Connect to ARM"]


def test_the_help_text(app):
    window = fpr(app)
    text = paragraphs(window.HELP)
    for words in ("IEEE 754", "S0 to S31", "a NaN keeps its bits", "hidden bit",
                  "Coproc 10 and Coproc 11", "0x before them", "Disconnect from ARM",
                  "costs the program nothing"):
        assert words in text, words


def test_no_pictures_are_made_for_the_tool(app, tmp_path):
    made = pictures(app.root)
    loaded(app, tmp_path, PROGRAM)
    window = connected(app, 2)
    app.run("step")
    type_into(window, "decimal", "1.5")
    go_to_end(app)
    window.reset_button.invoke()
    window.close()
    assert pictures(app.root) == made


@pytest.mark.parametrize("closed", ["tool", "main window"])
def test_nothing_is_left_to_run_when_the_window_goes_during_a_run(make_app, tmp_path, closed):
    app = make_app()
    loaded(app, tmp_path, SPIN)
    window = connected(app, 0)
    app.run("go")
    run_until(app, lambda: window.model.bits != 0)
    window.refresh()                                    # the display waits for idle time
    pending = window._idle
    assert pending is not None
    if closed == "tool":
        window.close()
    else:
        app.close()
    assert window._idle is None
    assert pending not in app.root.tk.splitlist(app.root.tk.call("after", "info"))


@pytest.mark.serial
def test_the_window_stays_responsive_while_the_tool_follows_a_run(app, tmp_path):
    """S0 changes all the time: the tool shows it while the run goes on, and Tk still has
    idle time between the run's slices, when it redraws the window."""
    loaded(app, tmp_path, SPIN)
    window = connected(app, 0)
    costs = []
    show = window.show

    def timed():
        start = time.perf_counter()
        show()
        costs.append(time.perf_counter() - start)
    window.show = timed
    beats = []

    def beat():
        beats.append(time.perf_counter())
        if app.runner.state is State.RUNNING:
            app.root.after(5, lambda: app.root.after_idle(beat))
    app.run("go")
    app.root.after(5, lambda: app.root.after_idle(beat))
    app.root.after(1000, lambda: app.run("stop"))       # a timer: it comes even without idle time
    run_until(app, lambda: app.runner.state is State.FINISHED, 10)
    gaps = [b - a for a, b in zip(beats, beats[1:])]
    assert len(costs) > 2, costs                            # it followed the run
    assert sorted(costs)[len(costs) // 2] < 0.01 and max(costs) < 0.2, costs
    assert len(beats) > 10 and max(gaps) < 0.2, (len(beats), max(gaps, default=None))
    assert shown(window) == texts(app.machine.single(0))
