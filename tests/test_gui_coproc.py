# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The floating-point tabs: Coproc 10 (S0 to S31) and Coproc 11 (D0 to D31) with FPSCR."""

from types import SimpleNamespace

import pytest
from conftest import press_key, use_test_clipboard
from test_gui_assemble import assemble
from test_gui_run import READ_INT, go_to_end, loaded, run_until
from unicorn import arm_const as arm

from ares.gui import table as table_module
from ares.gui.app import NOT_ASSEMBLED
from ares.gui.registers import (CHANGED, DOUBLE_CHARS, DOUBLES, FPSCR_ROW, SINGLE_CHARS,
                                SINGLES, double_tip, fpscr_flags_chars, fpscr_mark_bit,
                                fpscr_marks, fpscr_tip, parse_vfp_value, single_tip)
from ares.gui.table import MARK_OFF, STRIPE, TEXT, off_colour
from ares.runner import State

PROGRAM = """\
        .global _start
_start: LDR     R1, =0x3FC00000     @ 1.5
        VMOV    S0, R1
        VADD.F32 S1, S0, S0         @ 3.0
        VCVT.F64.F32 D1, S1         @ 3.0 as a double: S2 and S3
        VMOV.F64 D17, D1            @ D16 to D31 have no S names
        VCMP.F32 S0, S1             @ 1.5 is less than 3.0: N
        VMRS    APSR_nzcv, FPSCR
        SVC     #10
"""
FLAG_TEXTS = ["N", "Z", "C", "V"]


def pane_of(app, name):
    return app.coproc10 if name.startswith("S") else app.coproc11


def row_of(name):
    return (SINGLES if name.startswith("S") else DOUBLES).index(name)


def value(app, name):
    return pane_of(app, name)._row(row_of(name)).cells[1]


def changed(app, name):
    return pane_of(app, name)._row(row_of(name)).background == CHANGED


def hexadecimal(app, on):
    app.setting_vars["hex_values"].set(on)
    app._setting_toggled("hex_values")


def fpscr_shown(pane):
    """FPSCR's row as a tab draws it: (value, [(text, colour) of each letter], background)."""
    table = pane.table
    table.see(FPSCR_ROW)
    items = table.slots[FPSCR_ROW - table.top]
    body = table.body
    marks = [(body.itemcget(item, "text"), body.itemcget(item, "fill"))
             for item in items[1 + 2 * len(table.columns):]
             if body.itemcget(item, "state") != "hidden"]
    return body.itemcget(items[4], "text"), marks, body.itemcget(items[0], "fill")


def drawn_rows(pane):
    """{name: value} as a tab's table draws them."""
    table = pane.table
    rows = {}
    for items in table.slots:
        if table.body.itemcget(items[0], "state") != "hidden":
            name, text = (table.body.itemcget(items[2 + 2 * k], "text") for k in range(2))
            rows[name] = text
    return rows


def edit(app, name, text):
    """Double-click a floating-point value, type text and press Enter; the bell is recorded."""
    pane = pane_of(app, name)
    rings = []
    pane.table.see(row_of(name))
    y = (row_of(name) - pane.table.top) * pane.table.row_height + 2
    x = pane.table.columns[0].width + 5
    pane.table._clicked = None
    pane.table._double(SimpleNamespace(x=x, y=y))
    if pane.editor is None:
        return None
    pane.editor.bell = lambda: rings.append(1)
    pane.editor.delete(0, "end")
    pane.editor.insert(0, text)
    press_key(pane.editor, "<Return>")
    return rings


def double_click_flag(pane, text):
    """Double-click a letter of FPSCR's Flags cell in a tab, where the table draws it."""
    table = pane.table
    table.see(FPSCR_ROW)
    number = [mark.text for mark in fpscr_marks(pane.fpscr)].index(text)
    x0, y0, x1, y1 = table.mark_box(FPSCR_ROW, "flags", number)
    table._clicked = None
    table._double(SimpleNamespace(x=(x0 + x1) // 2 - int(table.body.canvasx(0)),
                                  y=(y0 + y1) // 2))


def fpscr(app):
    return app.machine.vfp()[1]


def test_the_coproc_tabs_show_every_register(app):
    for pane, names in ((app.coproc10, SINGLES), (app.coproc11, DOUBLES)):
        table = pane.table
        table.fit(40 * table.row_height)
        rows = drawn_rows(pane)
        assert list(rows) == names + ["FPSCR"]                  # FPSCR is the last row
        assert set(rows[name] for name in names) == {"0x00000000" if pane is app.coproc10
                                                     else "0x0000000000000000"}
        # FPSCR is the 33rd row: gray.
        assert fpscr_shown(pane)[:2] == ("0x00000000", [(text, off_colour(STRIPE))
                                                        for text in FLAG_TEXTS] + [("RN", TEXT)])
        assert all(pane._row(row_of(name)).cells[2] == () for name in names)   # no flags
    assert DOUBLES == [f"D{n}" for n in range(32)] and SINGLES == [f"S{n}" for n in range(32)]
    hexadecimal(app, False)
    shown = {**drawn_rows(app.coproc10), **drawn_rows(app.coproc11)}
    assert {text for name, text in shown.items() if name != "FPSCR"} == {"0.0"}
    assert shown["FPSCR"] == "0x00000000"                       # FPSCR stays hexadecimal


def test_the_coproc_tabs_show_a_run(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    go_to_end(app)
    assert value(app, "S0") == "0x3fc00000" and value(app, "S1") == "0x40400000"
    assert value(app, "D0") == "0x404000003fc00000"
    assert value(app, "D1") == "0x4008000000000000" and value(app, "S3") == "0x40080000"
    assert value(app, "D17") == "0x4008000000000000" and value(app, "D16") == "0x" + "0" * 16
    for pane in (app.coproc10, app.coproc11):
        shown, marks, background = fpscr_shown(pane)
        assert shown == "0x80000000" and background == CHANGED
        assert marks == [("N", TEXT)] + [(text, off_colour(CHANGED)) for text in "ZCV"] + [
            ("RN", TEXT)]
    hexadecimal(app, False)
    assert value(app, "S0") == "1.5" and value(app, "S1") == "3.0"
    assert value(app, "D0") == "32.00000759959221"         # S1:S0 read as one double
    assert value(app, "D1") == value(app, "D17") == "3.0" and value(app, "S2") == "0.0"
    assert value(app, "S3") == "2.125"                      # the high half of 3.0


def test_changed_rows_and_fpscr_are_highlighted(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    app.run("step")                                         # LDR
    app.run("step")                                         # VMOV S0, R1
    assert changed(app, "S0") and changed(app, "D0") and not changed(app, "S1")
    app.run("step")                                         # VADD.F32 S1, S0, S0
    assert changed(app, "S1") and changed(app, "D0") and not changed(app, "S0")
    app.run("step")                                         # VCVT into D1
    assert changed(app, "D1") and changed(app, "S3") and not changed(app, "S2")
    app.run("step")                                         # VMOV.F64 D17, D1
    assert changed(app, "D17") and not changed(app, "D1")
    assert fpscr_shown(app.coproc11)[2] != CHANGED
    app.run("step")                                         # VCMP
    assert fpscr_shown(app.coproc10)[2] == fpscr_shown(app.coproc11)[2] == CHANGED
    app.run("backstep")
    assert fpscr_shown(app.coproc11)[:2] == fpscr_shown(app.coproc10)[:2]
    assert fpscr_shown(app.coproc11)[0] == "0x00000000"
    assert fpscr_shown(app.coproc10)[2] == CHANGED          # the undone step changed it
    app.run("reset")
    assert not changed(app, "S0") and fpscr_shown(app.coproc10)[2] != CHANGED


def test_fpscr_is_a_row_and_no_box(app):
    for pane in (app.coproc10, app.coproc11):
        assert not hasattr(pane, "fpscr_panel")
        assert pane.ROWS[FPSCR_ROW] == "FPSCR" and len(pane.ROWS) == FPSCR_ROW + 1
        assert [column.anchor for column in pane.table.columns][:2] == ["w", "e"]
        assert pane.table.columns[2].marks == 11                # N Z C V, RN, six flags
        assert all(column.stretch for column in pane.table.columns)


def test_a_shown_rounding_tooltip_goes_when_the_mode_changes(app, tmp_path, monkeypatch):
    loaded(app, tmp_path, ".global _start\n_start: LDR R0, =0x00C00000\n"
                          "        VMSR FPSCR, R0\n        SVC #10\n")
    table = app.coproc10.table
    shown = []
    monkeypatch.setattr(table_module, "tip_window",
                        lambda widget, text, x, y: shown.append(text) or SimpleNamespace(
                            destroy=lambda: shown.append("gone")))
    monkeypatch.setattr(table.body, "winfo_ismapped", lambda: True)
    table.see(FPSCR_ROW)
    item = table.slots[FPSCR_ROW - table.top][7 + 4]        # the rounding mode
    monkeypatch.setattr(table.body, "find_withtag", lambda tag: (item,))
    table._mark_entered(None)
    table._show_tip()
    assert shown == ["Rounding mode (bits 23-22): round to nearest. Programs change it "
                     "with VMSR."]
    app.run("step")
    app.run("step")
    assert shown[-1] == "gone" and table.body.itemcget(item, "text") == "RZ"
    assert table._tips[item].startswith("Rounding mode (bits 23-22): round towards zero")


def test_a_green_fpscr_row_keeps_its_off_letters_visible(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    for _ in range(6):
        app.run("step")
    _, marks, background = fpscr_shown(app.coproc10)
    assert background == CHANGED and marks[1] == ("Z", off_colour(CHANGED)) and marks[0][1] == TEXT


def test_fpscr_flags_rounding_and_tooltips():
    marks = fpscr_marks(0x80C00093)                 # N, RZ, IOC, DZC, IXC, IDC
    assert [mark.text for mark in marks] == FLAG_TEXTS + ["RZ", "IOC", "DZC", "IXC", "IDC"]
    assert [mark.text for mark in marks if mark.on] == ["N", "RZ", "IOC", "DZC", "IXC", "IDC"]
    assert [mark.tip for mark in marks[5:]] == [
        "IOC (bit 0): invalid operation", "DZC (bit 1): divide by zero", "IXC (bit 4): inexact",
        "IDC (bit 7): input denormal"]
    assert marks[0].tip == "N (bit 31): negative" and not marks[1].space
    assert all(mark.space for mark in marks[4:])           # "NZCV RZ IOC DZC IXC IDC"
    assert [fpscr_marks(mode << 22)[4].text for mode in range(4)] == ["RN", "RP", "RM", "RZ"]
    assert len(fpscr_marks(0)) == 5                         # no exception flag set: none shown
    assert fpscr_marks(1 << 22)[4].tip.startswith(
        "Rounding mode (bits 23-22): round towards plus infinity")
    assert [fpscr_mark_bit(0x80C00093, number) for number in range(10)] == [
        31, 30, 29, 28, None, 0, 1, 4, 7, None]
    assert fpscr_flags_chars(0) == len("NZCV RN") and fpscr_flags_chars(2) == len("NZCV RN DZC")
    assert fpscr_tip(0x82).splitlines() == [
        "Cumulative exception flags (shown after the rounding mode while set):",
        "IOC (bit 0): invalid operation = 0", "DZC (bit 1): divide by zero = 1",
        "OFC (bit 2): overflow = 0", "UFC (bit 3): underflow = 0", "IXC (bit 4): inexact = 0",
        "IDC (bit 7): input denormal = 1"]


def test_the_cumulative_exception_flags_show(app, tmp_path):
    loaded(app, tmp_path, """\
        .global _start
_start: VMOV.F32 S0, #1.0
        VSUB.F32 S1, S0, S0         @ 0.0
        VDIV.F32 S2, S0, S1         @ 1 / 0: divide by zero
        VDIV.F32 S3, S1, S1         @ 0 / 0: invalid operation
        SVC     #10
""")
    go_to_end(app)
    marks = fpscr_shown(app.coproc10)[1]
    assert [text for text, _ in marks] == FLAG_TEXTS + ["RN", "IOC", "DZC"]   # "NZCV RN IOC DZC"
    assert [text for text, colour in marks if colour == TEXT] == ["RN", "IOC", "DZC"]
    assert fpscr(app) == 0x3
    assert app.coproc11._row(FPSCR_ROW).tip == fpscr_tip(0x3)
    hexadecimal(app, False)
    assert value(app, "S2") == "Infinity" and value(app, "S3") == "NaN"
    flags = app.coproc11._row(FPSCR_ROW).cells[2]
    assert flags[6].tip == "DZC (bit 1): divide by zero" and flags[4].tip.startswith("Rounding")


def test_the_flags_column_makes_room_for_the_flags_that_are_set(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    table = app.coproc10.table
    base = table.columns[2].base
    app.machine.set_fpscr_flag(0, True)                     # IOC
    app.machine.set_fpscr_flag(7, True)                     # IDC
    app.show_state()
    char = table.font.measure("0")
    assert table.columns[2].base == base + len(" IOC IDC") * char
    assert [text for text, _ in fpscr_shown(app.coproc10)[1]][-2:] == ["IOC", "IDC"]


def test_the_value_column_makes_room_for_the_values_as_written(app):
    for pane, chars in ((app.coproc10, SINGLE_CHARS), (app.coproc11, DOUBLE_CHARS)):
        char = pane.table.font.measure("0")
        hex_base = pane.table.columns[1].base
        hexadecimal(app, False)
        assert pane.table.columns[1].base - hex_base == (chars[1] - chars[0]) * char
        hexadecimal(app, True)
        assert pane.table.columns[1].base == hex_base


def test_double_clicking_an_fpscr_flag_changes_it(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    double_click_flag(app.coproc10, "Z")
    assert fpscr(app) == 0x40000000
    assert fpscr_shown(app.coproc11)[0] == "0x40000000"     # both tabs show it at once
    assert app.machine.cpsr >> 28 == 0                      # CPSR's flags are others
    double_click_flag(app.coproc11, "Z")
    assert fpscr(app) == 0
    app.machine.set_fpscr_flag(7, True)                     # IDC, set by the program
    app.machine.set_fpscr_flag(1, True)                     # DZC
    app.show_state()
    double_click_flag(app.coproc11, "IDC")                  # a shown exception flag
    assert fpscr(app) == 0x2 and "IDC" not in [text for text, _ in fpscr_shown(app.coproc10)[1]]
    double_click_flag(app.coproc10, "DZC")
    assert fpscr(app) == 0
    double_click_flag(app.coproc10, "RN")                   # the rounding mode: no change
    assert fpscr(app) == 0


def test_no_fpscr_change_without_a_program_or_while_running(app, tmp_path):
    double_click_flag(app.coproc10, "N")
    assert fpscr_shown(app.coproc10)[0] == "0x00000000"
    assert app.messages.messages.get("1.0", "end-1c") == NOT_ASSEMBLED + "\n"
    loaded(app, tmp_path, ".global _start\n_start: B _start\n")
    app.run("go")
    double_click_flag(app.coproc10, "N")
    app.run("stop")
    assert fpscr(app) == 0
    double_click_flag(app.coproc10, "N")
    assert fpscr(app) == 0x80000000


def test_the_fpscr_value_opens_no_field(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    for pane in (app.coproc10, app.coproc11):
        pane.request_edit(FPSCR_ROW)
        assert pane.editor is None


def test_the_fpscr_row_tooltip_lists_every_exception_flag(app, tmp_path, monkeypatch):
    loaded(app, tmp_path, PROGRAM)
    app.machine.set_fpscr_flag(1, True)
    app.show_state()
    table = app.coproc11.table
    shown = []
    monkeypatch.setattr(table_module, "tip_window",
                        lambda widget, text, x, y: shown.append(text) or SimpleNamespace(
                            destroy=lambda: shown.append("gone")))
    monkeypatch.setattr(table.body, "winfo_ismapped", lambda: True)
    monkeypatch.setattr(table.body, "find_withtag", lambda tag: ())   # not over a letter
    table.see(FPSCR_ROW)
    y = (FPSCR_ROW - table.top) * table.row_height + 2
    table._row_motion(SimpleNamespace(x=5, y=y))
    assert table._tip_job is not None
    table._show_tip()
    assert shown == [fpscr_tip(0x2)] and "DZC (bit 1): divide by zero = 1" in shown[0]
    table._row_motion(SimpleNamespace(x=9, y=y))            # still on the row: it stays
    assert shown == [fpscr_tip(0x2)]
    table._row_motion(SimpleNamespace(x=5, y=y - table.row_height))     # D31: its own tooltip
    assert shown[-1] == "gone" and table._tip_job is not None
    table._show_tip()
    assert shown[-1] == "D16-D31 have no S registers"
    table._row_motion(SimpleNamespace(x=5, y=y))
    app.machine.set_fpscr_flag(0, True)                     # the flags change: it goes
    app.show_state()
    assert table._tip_item is None


def test_parse_vfp_value():
    assert parse_vfp_value("1.5", double=False) == 0x3FC00000
    assert parse_vfp_value(" 0x3F800000 ", double=False) == 0x3F800000
    assert parse_vfp_value("0X3ff8000000000000", double=True) == 0x3FF8000000000000
    assert parse_vfp_value("0x0000000003f800000", double=False) == 0x3F800000
    assert parse_vfp_value("-1", double=True) == 0xBFF0000000000000
    for bad, double in (("0x100000000", False), ("0x10000000000000000", True), ("-0x1", False),
                        ("0x", False), ("abc", True), ("1.5.5", False), ("0x1p3", True)):
        assert parse_vfp_value(bad, double) is None, bad


def test_editing_singles_and_doubles(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    assert edit(app, "S0", "2.5") == []
    assert app.machine.double(0) == 0x40200000 and value(app, "S0") == "0x40200000"
    assert value(app, "D0") == "0x0000000040200000"          # Coproc 11 shows it at once
    assert app.coproc10.editor is None
    assert edit(app, "D1", "-0.5") == [] and app.machine.double(1) == 0xBFE0000000000000
    assert value(app, "S3") == "0xbfe00000" and value(app, "S2") == "0x00000000"
    assert edit(app, "S5", "0x3f800000") == [] and app.machine.double(2) == 0x3F80000000000000
    assert edit(app, "D31", "0.1") == [] and app.machine.double(31) == 0x3FB999999999999A
    hexadecimal(app, False)
    assert value(app, "S3") == "-1.75" and value(app, "S5") == "1.0" and value(app, "D31") == "0.1"
    assert edit(app, "S6", "1e39") == [] and value(app, "S6") == "Infinity"
    assert edit(app, "S7", "-0") == [] and value(app, "S7") == "-0.0"
    assert edit(app, "D4", "nan") == [] and app.machine.double(4) == 0x7FF8000000000000


def test_a_wrong_value_keeps_the_field_open(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    for name, text in (("S1", "abc"), ("S1", "1.5.5"), ("S1", "0x100000000"), ("D20", "x")):
        assert edit(app, name, text) == [1], text
        assert pane_of(app, name).editor is not None
        pane_of(app, name).cancel_edit()
    assert app.machine.vfp() == ([0] * 32, 0)


def test_the_field_shows_the_value_and_unchanged_text_keeps_a_nan(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    app.machine.set_single(0, 0xFFC00001)                   # a NaN with a sign and a payload
    app.show_state()
    hexadecimal(app, False)
    app.coproc10.edit(row_of("S0"))
    assert app.coproc10.editor.get() == "NaN" and app.coproc10.editor.selection_present()
    app.coproc10.commit()
    assert app.machine.single(0) == 0xFFC00001
    assert edit(app, "S0", "nan") == [] and app.machine.single(0) == 0x7FC00000


def test_no_editing_without_a_program_or_while_running(app, tmp_path):
    app.coproc10.edit(row_of("S0"))
    assert app.coproc10.editor is None
    loaded(app, tmp_path, ".global _start\n_start: B _start\n")
    app.run("go")
    assert app.runner.state is State.RUNNING
    assert not app.coproc10.editable and not app.coproc11.editable
    app.coproc11.edit(row_of("D0"))
    assert app.coproc11.editor is None
    app.run("stop")
    assert app.coproc10.editable and app.coproc11.editable


def test_the_tabs_show_zeros_again_without_a_program(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    go_to_end(app)
    tab = app.editor.current
    tab.text.insert("end", "        BAD\n")
    assemble(app)
    assert value(app, "S0") == "0x00000000" and value(app, "D17") == "0x" + "0" * 16
    assert fpscr_shown(app.coproc11)[0] == "0x00000000"
    assert not app.coproc10.editable and app.coproc10.baseline is None


@pytest.mark.parametrize("change", ["edit", "flag"])
def test_a_change_while_paused_in_a_read_asks_again(app, tmp_path, change):
    loaded(app, tmp_path, READ_INT)
    app.run("go")
    run_until(app, lambda: app.runner.state is State.WAITING)
    app.run("pause")
    assert app.machine.request is not None
    if change == "edit":
        assert edit(app, "S0", "1") == []
    else:
        double_click_flag(app.coproc10, "V")
    assert app.machine.request is None                      # the read runs again, as changed


@pytest.mark.parametrize("pane", ["registers", "coproc10", "coproc11"])
def test_the_edit_commands_reach_the_field_with_the_focus(app, tmp_path, monkeypatch, pane):
    use_test_clipboard(app.root)
    loaded(app, tmp_path, PROGRAM)
    source = app.editor.current.get_text()
    getattr(app, pane).edit(1)
    field = getattr(app, pane).editor
    monkeypatch.setattr(app.root, "focus_get", lambda: field)
    app.root.clipboard_append("0x1")
    app.run("select_all")
    app.run("paste")
    assert field.get() == "0x1"
    app.run("select_all")
    app.run("cut")
    assert field.get() == "" and app.root.clipboard_get() == "0x1"
    app.run("paste")
    app.run("select_all")
    app.run("copy")
    assert app.editor.current.get_text() == source
    getattr(app, pane).commit()
    assert {"registers": app.machine.reg(1), "coproc10": app.machine.double(0),
            "coproc11": app.machine.double(1)}[pane] == {
        "registers": 1, "coproc10": 1 << 32, "coproc11": 1}[pane]


@pytest.mark.parametrize("command", ["copy", "cut"])
def test_copy_and_cut_in_a_field_with_a_character_beyond_u_ffff(app, tmp_path, monkeypatch,
                                                                command):
    use_test_clipboard(app.root)
    loaded(app, tmp_path, PROGRAM)
    app.coproc10.edit(0)
    field = app.coproc10.editor
    monkeypatch.setattr(app.root, "focus_get", lambda: field)
    field.delete(0, "end")
    field.insert(0, "\U0001F600" + "1.5")
    field.select_range(2, "end")            # Tk counts the emoji as two: the selection is 1.5
    app.run(command)
    assert app.root.clipboard_get() == "1.5"
    assert field.get() == ("\U0001F600" if command == "cut" else "\U0001F600" + "1.5")


def test_no_field_opens_once_the_programs_file_is_closed(app, tmp_path):
    # Closing the program's file unloads it, so no field opens without a file.
    loaded(app, tmp_path, PROGRAM)
    go_to_end(app)
    app.cmd_close()
    assert not app.is_enabled("cut") and not app.is_enabled("paste")
    app.coproc11.edit(row_of("D2"))
    assert app.coproc11.editor is None
    assert not app.is_enabled("cut") and not app.is_enabled("paste")


def test_go_step_backstep_and_reset_close_a_field(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    for command in ("step", "backstep", "reset", "go"):
        app.coproc10.edit(row_of("S4"))
        assert app.coproc10.editor is not None, command
        app.run(command)
        assert app.coproc10.editor is None, command


def test_the_machine_shows_d16_to_d31(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    app.machine.uc.reg_write(arm.UC_ARM_REG_D30, 0x4000000000000000)
    app.show_state()
    assert value(app, "D30") == "0x4000000000000000"


def test_every_row_says_which_registers_share_its_bits():
    # S2 and S3 are D1's halves, D16-D31 have no S names.
    assert [single_tip(n) for n in (0, 1, 2, 3, 31)] == [
        "S0: low half of D0", "S1: high half of D0", "S2: low half of D1",
        "S3: high half of D1", "S31: high half of D15"]
    assert double_tip(0) == "D0 = S0 (low half) and S1 (high half)"
    assert double_tip(1) == "D1 = S2 (low half) and S3 (high half)"
    assert double_tip(15) == "D15 = S30 (low half) and S31 (high half)"
    assert {double_tip(n) for n in range(16, 32)} == {"D16-D31 have no S registers"}


def test_the_coproc_rows_show_their_sharing_tooltips(app, tmp_path, monkeypatch):
    loaded(app, tmp_path, PROGRAM)
    for pane, names in ((app.coproc10, SINGLES), (app.coproc11, DOUBLES)):
        tips = [pane._row(index).tip for index in range(len(names))]
        assert tips == [(double_tip if pane.double else single_tip)(n) for n in range(32)]
        assert pane._row(FPSCR_ROW).tip == fpscr_tip(pane.fpscr)
    table = app.coproc10.table
    shown = []
    monkeypatch.setattr(table_module, "tip_window",
                        lambda widget, text, x, y: shown.append(text) or SimpleNamespace(
                            destroy=lambda: shown.append("gone")))
    monkeypatch.setattr(table.body, "winfo_ismapped", lambda: True)
    monkeypatch.setattr(table.body, "find_withtag", lambda tag: ())
    table.see(3)
    table._row_motion(SimpleNamespace(x=5, y=(3 - table.top) * table.row_height + 2))
    table._show_tip()
    assert shown == ["S3: high half of D1"]
    table._row_motion(SimpleNamespace(x=5, y=(2 - table.top) * table.row_height + 2))
    table._show_tip()
    assert shown == ["S3: high half of D1", "gone", "S2: low half of D1"]
