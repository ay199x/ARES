# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Data Segment and the Registers: pages, places, number formats, changes and editing."""

from types import SimpleNamespace

import pytest
from conftest import press_key, use_test_clipboard
from test_gui_assemble import assemble, open_source
from test_gui_run import ECHO, go_to_end, run_until, slow

from ares.gui.execute import (CHANGED, LAST_PAGE, PAGE, ascii_text, page_start,
                              value_heading)
from ares.gui.places import STACK_TEXT
from ares.gui.registers import CHANGED as REGISTER_CHANGED
from ares.gui.registers import CPSR_ROW, ROWS, SPSR_ROW, parse_value
from ares.gui.table import MARK_OFF, STRIPE, off_colour
from ares.machine import DDR_END, JTAG_UART
from ares.runner import State
from ares.settings import Settings

PROGRAM = """\
        .global _start
_start: LDR     R1, =value
        MOV     R0, #0x41
        STR     R0, [R1]
        PUSH    {R0, R1}
        SVC     #10
        .data
value:  .word   7
text:   .asciz  "Hi\\n"
"""
VALUE = 0x18            # address of value: (.data after 5 instructions and a literal)


def loaded(app, tmp_path, source=PROGRAM):
    open_source(app, tmp_path, source)
    assemble(app)
    return app.execute.data_segment


def cells(data, row):
    return data._row(row).cells


def row_of(name):
    return ROWS.index(name)


def register_cells(app, name):
    return app.registers._row(row_of(name)).cells


# Pages and places ---------------------------------------------------------

def test_page_start_keeps_a_page_in_memory():
    assert page_start(0x1C) == 0x00
    assert page_start(0x23) == 0x20
    assert page_start(DDR_END - 4) == DDR_END - PAGE
    assert page_start(DDR_END) == DDR_END
    assert page_start(0xFFFFFFF0) == LAST_PAGE
    assert page_start(JTAG_UART) == JTAG_UART


def test_ascii_shows_the_bytes_in_memory_order():
    assert ascii_text(0x6C6C6548) == " H e l l"
    assert ascii_text(0x00000A6F) == " o\\n\\0\\0"
    assert ascii_text(0x7F09FF0D) == "\\r .\\t ."


def test_value_headings():
    assert value_heading(0x1C, True) == "Value (+1c)"
    assert value_heading(28, False) == "Value (+28)"


def test_the_data_of_the_program_is_shown_after_assembling(app, tmp_path):
    data = loaded(app, tmp_path)
    assert app.program.label_address("value") == VALUE
    assert data.base == 0 and data.table.count == 16
    assert cells(data, 0)[0] == "0x00000000"
    assert cells(data, 0)[7:9] == ("0x00000007", "0x000a6948")       # value, then "Hi\n"
    assert cells(data, 1)[0] == "0x00000020"
    assert data.places.get() == "0x00000018 (.data)"
    assert data.places.cget("values") == ("0x00000018 (.data)", STACK_TEXT,
                                          "0x00000000 (.text)", "0xff201000 (JTAG UART)")
    for widget in (data.previous_button, data.next_button):
        assert widget.instate(["!disabled"])


def test_without_data_the_page_starts_after_the_program(app, tmp_path):
    data = loaded(app, tmp_path, ".global _start\n_start: B .\n")
    assert data.data_start() == 4 and data.places.get() == "0x00000004 (.data)"


def choose(data, index):
    data.places.current(index)
    data._place_chosen()


def test_places_of_the_list(app, tmp_path):
    data = loaded(app, tmp_path)
    choose(data, 3)
    assert data.base == JTAG_UART
    assert cells(data, 0)[1:3] == ("0x00000000", "0x00400000")     # data, then control
    choose(data, 1)             # current SP 0: the last page, where the first push stores
    assert data.base == LAST_PAGE and cells(data, 0)[0] == "0xfffffe00"
    assert cells(data, 15)[0] == "0xffffffe0" and cells(data, 15)[8] == "0x00000000"
    app.runner.run(time_limit=5)
    app.show_state()
    choose(data, 1)
    assert app.machine.reg(13) == 0xFFFFFFF8 and data.base == LAST_PAGE
    assert cells(data, 15)[7:9] == ("0x00000041", "0x00000018")    # the pushed R0 and R1
    choose(data, 2)
    assert data.base == 0 and cells(data, 0)[1] == "0xe59f100c"
    choose(data, 0)
    assert data.base == 0


def test_current_sp_in_ddr3(app, tmp_path):
    data = loaded(app, tmp_path, ".global _start\n_start: LDR SP, =0x40000000\n"
                                 "        MOV R0, #0x66\n        PUSH {R0}\n"
                                 "        LDR SP, =0x00100008\n        SVC #10\n")
    app.run("step")                             # SP at the top of DDR3: an empty stack there
    choose(data, 1)
    assert data.base == DDR_END - PAGE and cells(data, 15)[0] == "0x3fffffe0"
    app.run("step")
    app.run("step")                             # PUSH {R0}
    choose(data, 1)
    assert data.base == DDR_END - PAGE and cells(data, 15)[8] == "0x00000066"
    app.run("step")                             # elsewhere: the page starts with SP's row
    choose(data, 1)
    assert data.base == 0x00100000


def test_previous_and_next_page(app, tmp_path):
    data = loaded(app, tmp_path)
    data.turn(1)
    assert data.base == PAGE and cells(data, 0)[0] == "0x00000200"
    data.turn(-1)
    data.turn(-1)
    assert data.base == 0
    data.show(LAST_PAGE)
    data.turn(1)
    assert data.base == LAST_PAGE
    data.next_button.invoke()
    data.previous_button.invoke()
    assert data.base == LAST_PAGE - PAGE


def test_addresses_without_memory_are_empty(app, tmp_path):
    data = loaded(app, tmp_path)
    data.show(DDR_END)
    assert cells(data, 0) == ("0x40000000",) + ("",) * 8


def test_showing_the_jtag_uart_takes_no_typed_character(app, tmp_path):
    data = loaded(app, tmp_path)
    app.machine.console.feed("xy")
    data.show(JTAG_UART)
    assert cells(data, 0)[1] == "0x00018078"           # one more waiting, valid, "x"
    data.refresh()
    assert app.machine.console.pending() == 2 and app.machine.take_warnings() == []


def test_a_key_typed_before_the_run_shows_in_the_jtag_uart(app, tmp_path):
    data = loaded(app, tmp_path, ECHO)
    data.show(JTAG_UART)
    app.messages._key(SimpleNamespace(char="x", state=0))
    assert cells(data, 0)[1] == "0x00008078"           # valid, "x"


def test_a_key_typed_in_a_slow_run_is_not_the_next_instruction_s_change(app, tmp_path):
    data = loaded(app, tmp_path, ECHO)
    data.show(JTAG_UART)
    slow(app, 1)
    app.run("go")
    for _ in range(3):                                  # LDR, LDR and TST
        app._cancel_tick()
        app._tick()
    app._cancel_tick()
    assert app.machine.pc == 0xC                        # BEQ is next
    app.messages._key(SimpleNamespace(char="x", state=0))
    assert cells(data, 0)[1] == "0x00008078"           # shown at once
    app._tick()                                         # BEQ
    assert app.machine.pc == 0x4 and data._row(0).cell_backgrounds == {}
    app.run("stop")


def test_backstep_does_not_show_the_line_it_gives_back_as_its_change(app, tmp_path):
    data = loaded(app, tmp_path, ".global _start\n_start: MOV R1, #1\n        SVC #5\n"
                                 "        SVC #10\n")
    data.show(JTAG_UART)
    app.run("step")
    app.run("step")                                     # the read waits
    assert app.runner.state is State.WAITING
    app.messages.paste("9")
    app.run("backstep")                                 # MOV undone; "9" goes back to the input
    assert cells(data, 0)[1] == "0x00008039"
    assert data._row(0).cell_backgrounds == {}


def test_the_data_segment_is_empty_without_a_program(app, tmp_path):
    data = app.execute.data_segment
    assert data.table.count == 0 and data.places.get() == ".data: no program assembled"
    for widget in (data.previous_button, data.next_button, data.places):
        assert widget.instate(["disabled"])
    loaded(app, tmp_path)
    tab = app.editor.current
    tab.text.insert("end", "        BAD\n")
    assemble(app)
    assert data.table.count == 0 and data.machine is None
    assert data.previous_button.instate(["disabled"])


# Number formats -------------------------------------------------------------

def test_hexadecimal_checkboxes_are_the_settings(app, tmp_path):
    data = loaded(app, tmp_path)
    data.hex_values.set(False)
    data._checked("hex_values", data.hex_values)
    assert app.settings.hex_values is False and app.setting_vars["hex_values"].get() is False
    assert Settings.load(tmp_path / "settings.json").hex_values is False
    assert cells(data, 0)[7] == "7" and cells(data, 0)[1] == str(0xe59f100c - (1 << 32))
    assert register_cells(app, "SP")[2] == "0"
    data.hex_addresses.set(False)
    data._checked("hex_addresses", data.hex_addresses)
    assert cells(data, 1)[0] == "32"
    assert [c.heading for c in data.table.columns][1:3] == ["Value (+0)", "Value (+4)"]
    assert data.table.columns[-1].heading == "Value (+28)"
    app.setting_vars["hex_addresses"].set(True)
    app._setting_toggled("hex_addresses")             # the menu changes the checkbox
    assert data.hex_addresses.get() is True and data.table.columns[-1].heading == "Value (+1c)"


def test_ascii_checkbox(app, tmp_path):
    data = loaded(app, tmp_path)
    data.ascii.set(True)
    data._checked(None, data.ascii)
    assert cells(data, 0)[7:9] == (" .\\0\\0\\0", " H i\\n\\0")
    assert app.settings.hex_values is True              # not a setting
    data.ascii.set(False)
    data._checked(None, data.ascii)
    assert cells(data, 0)[7] == "0x00000007"


# Changed words and registers ----------------------------------------------

def test_words_changed_by_a_step_are_highlighted(app, tmp_path):
    data = loaded(app, tmp_path)
    data.mark()
    app.registers.mark()
    for _ in range(3):                                  # LDR, MOV, STR
        app.runner.step()
    app.show_state()
    row = data._row(0)
    assert row.cell_backgrounds == {"6": CHANGED} and row.cells[7] == "0x00000041"
    assert app.registers._row(row_of("R0")).background == REGISTER_CHANGED
    assert app.registers._row(row_of("R1")).background == REGISTER_CHANGED
    assert app.registers._row(row_of("R2")).background == ""
    assert app.registers._row(row_of("PC")).background == REGISTER_CHANGED
    data.mark()
    app.registers.mark()
    assert data._row(0).cell_backgrounds == {}
    assert app.registers._row(row_of("R0")).background == ""


def test_changes_show_on_another_page_shown_later(app, tmp_path):
    data = loaded(app, tmp_path)
    data.show(LAST_PAGE)
    data.mark()
    data.show(0)
    app.runner.run(time_limit=5)
    data.show(LAST_PAGE)                                # the stack, marked before the run
    assert data._row(15).cell_backgrounds == {"6": CHANGED, "7": CHANGED}


def test_double_clicking_a_data_label_shows_its_word(app, tmp_path):
    data = loaded(app, tmp_path)
    data.show(0x2000)
    app.setting_vars["show_labels"].set(True)
    app._setting_toggled("show_labels")
    labels = app.execute.labels
    index = [label.name for label in labels.labels].index("text")
    text_selected = app.execute.text_segment.table.selected
    labels.table._double(SimpleNamespace(x=5, y=index * labels.table.row_height + 1))
    assert data.base == 0x00 and data.table.selected == 0
    assert app.execute.text_segment.table.selected == text_selected


# Editing registers ------------------------------------------------------------

def test_parse_value():
    assert parse_value("12") == 12 and parse_value("+12") == 12
    assert parse_value("-1") == 0xFFFFFFFF
    assert parse_value("0x1F") == 0x1F and parse_value(" 0XfF ") == 0xFF
    assert parse_value("-0x10") == 0xFFFFFFF0
    assert parse_value("4294967295") == 0xFFFFFFFF
    assert parse_value("-2147483648") == 0x80000000
    for bad in ("", "x", "0x", "--1", "- 1", "1_000", "4294967296", "-2147483649", "1.5",
                "0b1", "12 3"):
        assert parse_value(bad) is None, bad


def edit(app, name, text):
    """Double-click a register's value, type text and press Enter; the bell is recorded."""
    registers = app.registers
    rings = []
    y = (row_of(name) - registers.table.top) * registers.table.row_height + 2
    x = sum(c.width for c in registers.table.columns[:2]) + 5
    registers.table._double(SimpleNamespace(x=x, y=y))
    if registers.editor is None:
        return None
    registers.editor.bell = lambda: rings.append(1)
    registers.editor.delete(0, "end")
    registers.editor.insert(0, text)
    press_key(registers.editor, "<Return>")
    return rings


def test_editing_a_register(app, tmp_path):
    loaded(app, tmp_path)
    assert edit(app, "R1", "0x10") == []
    assert app.machine.reg(1) == 0x10 and register_cells(app, "R1")[2] == "0x00000010"
    assert app.registers.editor is None
    assert edit(app, "R2", "-2") == [] and app.machine.reg(2) == 0xFFFFFFFE


def test_a_wrong_value_keeps_the_field_open(app, tmp_path):
    loaded(app, tmp_path)
    assert edit(app, "R1", "twelve") == [1]
    assert app.registers.editor is not None and app.machine.reg(1) == 0
    app.registers.cancel_edit(refocus=True)
    assert app.registers.editor is None and app.machine.reg(1) == 0


def test_escape_leaves_the_value(app, tmp_path):
    from conftest import press_key
    loaded(app, tmp_path)
    edit(app, "R1", "5")
    app.registers.edit(row_of("R3"))
    editor = app.registers.editor
    editor.insert("end", "9")
    press_key(editor, "<Key-Escape>")
    assert app.registers.editor is None and app.machine.reg(3) == 0


def test_the_field_shows_the_value_selected(app, tmp_path):
    loaded(app, tmp_path)
    app.registers.edit(row_of("SP"))
    editor = app.registers.editor
    assert editor.get() == "0x00000000" and editor.selection_present()
    assert str(app.root) not in editor.bindtags()      # the window's shortcuts wait


def double_click_mark(app, name, number):
    """Double-click mark number (N, Z, C, V, I, then the mode) of CPSR or SPSR."""
    table = app.registers.table
    table.see(row_of(name))
    x0, y0, x1, y1 = table.mark_box(row_of(name), "flags", number)
    table._clicked = None
    table._double(SimpleNamespace(x=(x0 + x1) // 2 - int(table.body.canvasx(0)),
                                  y=(y0 + y1) // 2))


def test_double_clicking_a_flag_changes_it(app, tmp_path):
    loaded(app, tmp_path)
    double_click_mark(app, "CPSR", 1)                   # Z
    assert app.machine.cpsr == 0x400001D3
    assert register_cells(app, "CPSR")[2] == "0x400001d3"
    assert register_cells(app, "CPSR")[3][1].on
    double_click_mark(app, "CPSR", 4)                   # I
    assert app.machine.cpsr == 0x40000153
    double_click_mark(app, "CPSR", 5)                   # the mode: not changed here
    assert app.machine.cpsr == 0x40000153
    double_click_mark(app, "CPSR", 1)
    double_click_mark(app, "CPSR", 4)
    assert app.machine.cpsr == 0x1D3
    double_click_mark(app, "SPSR", 0)                   # N of the SPSR of Supervisor mode
    assert app.machine.spsr == 0x80000000 and app.machine.cpsr == 0x1D3
    assert register_cells(app, "SPSR")[2] == "0x80000000"


def test_a_double_clicked_flag_is_black_on_its_selected_row(app, tmp_path):
    loaded(app, tmp_path)
    table = app.registers.table
    x0, y0, x1, y1 = table.mark_box(row_of("CPSR"), "flags", 1)              # Z
    event = SimpleNamespace(x=(x0 + x1) // 2, y=(y0 + y1) // 2)
    table._press(event)                         # Tk: a press, then the double press
    table._double(event)
    items = table.slots[row_of("CPSR") - table.top]
    assert app.machine.cpsr == 0x400001D3 and table.selected == row_of("CPSR")
    assert table.body.itemcget(items[0], "fill") == STRIPE               # not filled blue
    off = off_colour(STRIPE)
    assert [table.body.itemcget(item, "fill") for item in items[9:15]] == [
        off, "#000000", off, off, "#000000", "#000000"]
    assert table.body.itemcget(table._frame, "state") == "normal"


def test_off_flags_stay_visible_on_a_green_row(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: MOVS R1, #0\n        SVC #10\n")
    app.run("step")
    table = app.registers.table
    items = table.slots[row_of("CPSR") - table.top]
    assert table.body.itemcget(items[0], "fill") == REGISTER_CHANGED
    assert table.body.itemcget(items[9], "fill") == off_colour(REGISTER_CHANGED)     # N
    assert table.body.itemcget(items[10], "fill") == "#000000"                     # Z


def test_cpsr_and_spsr_are_changed_through_their_flags_only(app, tmp_path):
    loaded(app, tmp_path)
    assert edit(app, "CPSR", "0") is None and edit(app, "SPSR", "0") is None


def test_flags_and_modes_have_tooltips():
    from ares.gui.registers import psr_marks
    marks = psr_marks(0x800001D3, "CPSR")
    assert [mark.text for mark in marks] == ["N", "Z", "C", "V", "I", "SVC"]
    assert [mark.on for mark in marks] == [True, False, False, False, True, True]
    assert [mark.tip for mark in marks[:5]] == [
        "N (bit 31): negative", "Z (bit 30): zero", "C (bit 29): carry",
        "V (bit 28): overflow", "I (bit 7): IRQ interrupts disabled"]
    assert marks[5].tip.startswith("Supervisor mode (bits 4-0: 0x13). It cannot be changed here")
    assert "MSR or CPS" in marks[5].tip and marks[5].space
    names = {mode: psr_marks(mode, "SPSR")[5].text
             for mode in (0x10, 0x11, 0x12, 0x13, 0x16, 0x17, 0x1A, 0x1B, 0x1F, 0x00, 0x15)}
    assert names == {0x10: "USR", 0x11: "FIQ", 0x12: "IRQ", 0x13: "SVC", 0x16: "MON",
                     0x17: "ABT", 0x1A: "HYP", 0x1B: "UND", 0x1F: "SYS", 0x00: "?", 0x15: "?"}
    assert psr_marks(0x1F, "SPSR")[5].tip.startswith("System mode")
    assert psr_marks(0x15, "SPSR")[5].tip.startswith("Not a processor mode (bits 4-0: 0x15)")


def test_the_headings_of_the_register_tables(app):
    assert [c.heading for c in app.registers.table.columns] == ["Name", "Number", "Value", "Flags"]
    for pane in (app.coproc10, app.coproc11):
        assert [c.heading for c in pane.table.columns] == ["Name", "Value", "Flags"]


def on_marks(app, name):
    return [mark.text for mark in register_cells(app, name)[3] if mark.on]


def test_the_flags_follow_flag_setting_instructions_after_step_and_go(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: MOVS R1, #0\n        CMP R1, #1\n"
                          "        MSR CPSR_f, #0x60000000\n        CPS #0x17\n        SVC #10\n")
    app.run("step")                                             # MOVS R1, #0: Z
    assert on_marks(app, "CPSR") == ["Z", "I", "SVC"]
    assert app.registers._row(CPSR_ROW).background == REGISTER_CHANGED
    app.run("step")                                             # CMP R1, #1: N (0 - 1)
    assert on_marks(app, "CPSR") == ["N", "I", "SVC"]
    app.run("reset")
    go_to_end(app)                                              # ends in Abort mode
    assert register_cells(app, "CPSR")[2] == "0x600001d7"
    assert on_marks(app, "CPSR") == ["Z", "C", "I", "ABT"]
    assert register_cells(app, "SPSR")[2] == "0x00000000"      # Abort mode's own SPSR
    assert app.registers._row(CPSR_ROW).background == REGISTER_CHANGED


def test_every_cpsr_and_spsr_flag_toggles(app, tmp_path):
    loaded(app, tmp_path)
    for name, read in (("CPSR", lambda: app.machine.cpsr), ("SPSR", lambda: app.machine.spsr)):
        for number, bit in enumerate((31, 30, 29, 28, 7)):
            before = read()
            double_click_mark(app, name, number)
            assert read() == before ^ 1 << bit, (name, number)
            double_click_mark(app, name, number)
            assert read() == before
    double_click_mark(app, "SPSR", 5)                           # its mode: not changed
    assert app.machine.spsr == 0 and app.machine.cpsr == 0x1D3


def test_no_flag_changes_without_a_program_or_while_running(app, tmp_path):
    table = app.registers.table
    table.on_mark(row_of("CPSR"), "flags", 1)                   # no program
    assert register_cells(app, "CPSR")[2] == "0x000001d3"
    loaded(app, tmp_path, ".global _start\n_start: B _start\n")
    app.run("go")
    assert app.runner.state is State.RUNNING
    table.on_mark(row_of("CPSR"), "flags", 1)
    app.run("stop")
    assert app.machine.cpsr == 0x1D3
    table.on_mark(row_of("CPSR"), "flags", 1)
    assert app.machine.cpsr == 0x400001D3


def test_the_spsr_dash_of_user_mode_cannot_be_changed(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: CPS #0x10\n        B .\n")
    app.run("step")                                             # User mode
    cells = register_cells(app, "SPSR")
    assert cells[2] == "-" and [mark.text for mark in cells[3]] == ["-"]
    assert cells[3][0].tip == "User and System modes have no SPSR"
    assert on_marks(app, "CPSR") == ["I", "USR"]
    app.registers.table.on_mark(row_of("SPSR"), "flags", 0)
    assert register_cells(app, "SPSR")[2] == "-" and app.machine.spsr == 0


def test_toggling_i_does_not_change_the_run(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: MOV R0, #5\n        SVC #1\n        SVC #10\n")
    double_click_mark(app, "CPSR", 4)                           # I off
    assert app.machine.cpsr == 0x153
    go_to_end(app)
    assert app.messages.run_io.get("1.0", "end-1c") == "5\n-- program is finished running --\n"
    assert app.machine.error is None and app.machine.cpsr == 0x153


def test_every_mode_has_its_full_name_in_the_tooltip():
    from ares.gui.registers import psr_marks
    names = {0x10: "User", 0x11: "FIQ", 0x12: "IRQ", 0x13: "Supervisor", 0x16: "Monitor",
             0x17: "Abort", 0x1A: "Hypervisor", 0x1B: "Undefined", 0x1F: "System"}
    for mode, name in names.items():
        assert psr_marks(mode, "CPSR")[5].tip == (
            f"{name} mode (bits 4-0: 0x{mode:02x}). It cannot be changed here: programs "
            "change it with MSR or CPS.")
        assert psr_marks(mode, "SPSR")[5].tip.endswith("programs change it with MSR.")


def test_the_registers_follow_mode_changes(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: MRS R0, CPSR\n        MSR SPSR_fsxc, R0\n"
                          "        CPS #0x1F\n        CPS #0x12\n        SVC #10\n")
    for _ in range(2):
        app.run("step")
    assert register_cells(app, "SPSR")[2] == "0x000001d3"      # the SPSR of Supervisor mode
    app.run("step")                                             # CPS #0x1F: System mode
    assert register_cells(app, "CPSR")[3][5].text == "SYS"
    spsr = register_cells(app, "SPSR")
    assert spsr[2] == "-" and [mark.text for mark in spsr[3]] == ["-"]
    assert app.registers._row(SPSR_ROW).background
    sp = app.registers._row(row_of("SP"))
    assert sp.cells[2] == "0x00000000" and sp.background == ""     # System mode's SP is 0 too
    app.run("step")                                             # CPS #0x12: IRQ mode
    assert register_cells(app, "CPSR")[3][5].text == "IRQ"
    assert register_cells(app, "SPSR")[2] == "0x00000000"      # IRQ mode's own SPSR


def test_editing_pc_moves_the_next_instruction(app, tmp_path):
    loaded(app, tmp_path)
    assert edit(app, "PC", "0x8") == []
    assert app.execute.text_segment.pc_row == 2
    assert edit(app, "PC", "6") == [1] and app.machine.pc == 8
    app.registers.cancel_edit()


def test_no_editing_without_a_program(app):
    app.registers.edit(row_of("R1"))
    assert app.registers.editor is None


def test_the_field_moves_with_its_row_when_the_table_scrolls(app, tmp_path):
    loaded(app, tmp_path)
    table = app.registers.table
    table.body.unbind("<Configure>")            # this test decides the size
    table.fit(5 * table.row_height)
    app.registers.edit(row_of("R1"))
    item = app.registers._editing[1]
    assert table.body.coords(item)[1] == table.row_height
    table.scroll_to(10)                         # R1 out of view: its field goes along
    assert app.registers.editor is not None
    assert table.body.coords(item)[1] == (1 - 10) * table.row_height
    table.scroll_to(0)
    assert table.body.coords(item)[1] == table.row_height
    app.registers.cancel_edit()
    app.registers.edit(row_of("R12"))
    table.fit(3 * table.row_height)             # smaller: the row moves into view
    item = app.registers._editing[1]
    assert table.body.coords(item)[1] == (12 - table.top) * table.row_height


def test_registers_show_the_initial_state_again_without_a_program(app, tmp_path):
    loaded(app, tmp_path)
    edit(app, "R1", "7")
    tab = app.editor.current
    tab.text.insert("end", "        BAD\n")
    assemble(app)
    assert register_cells(app, "R1")[2] == "0x00000000" and not app.registers.editable
    assert app.registers.baseline is None


@pytest.mark.parametrize("name", ["R0", "LR", "PC"])
def test_every_row_but_cpsr_and_spsr_can_be_edited(app, tmp_path, name):
    loaded(app, tmp_path)
    app.registers.edit(row_of(name))
    assert app.registers.editor is not None
    app.registers.cancel_edit()
    assert row_of("CPSR") == CPSR_ROW and row_of("SPSR") == SPSR_ROW


# Regressions ----------------------------------------------------------------------

def test_current_sp_in_on_chip_memory(app, tmp_path):
    data = loaded(app, tmp_path, ".global _start\n_start: LDR SP, =0xFFFF8000\n"
                                 "        MOV R0, #0x55\n        PUSH {R0}\n        SVC #10\n")
    app.runner.run(time_limit=5)
    app.show_state()
    data.places.current(1)
    data._place_chosen()
    assert data.base == 0xFFFF7FE0 and cells(data, 0)[8] == "0x00000055"


def test_headings_follow_the_saved_addresses_setting_at_start(make_app, tmp_path):
    Settings(hex_addresses=False).save(tmp_path / "settings.json")
    app = make_app()
    data = app.execute.data_segment
    assert data.table.columns[-1].heading == "Value (+28)"


def test_enter_gives_the_focus_back_to_the_registers(app, tmp_path, hidden_windows):
    loaded(app, tmp_path)
    assert edit(app, "R1", "5") == []
    assert hidden_windows.focus is app.registers.table.body


def test_parse_value_takes_many_leading_zeros():
    assert parse_value("0" * 4300 + "7") == 7
    assert parse_value("-" + "0" * 5000 + "1") == 0xFFFFFFFF
    assert parse_value("0x" + "0" * 5000 + "1F") == 0x1F
    assert parse_value("1" + "0" * 4400) is None and parse_value("0x" + "1" * 9) is None
    assert parse_value("12345678901") is None and parse_value("0x000000001") == 1


def test_a_very_long_number_in_a_field_rings_the_bell(app, tmp_path):
    loaded(app, tmp_path)
    assert edit(app, "R1", "0" * 4300 + "7") == [] and app.machine.reg(1) == 7
    assert edit(app, "R2", "1" * 5000) == [1] and app.machine.reg(2) == 0
    app.registers.cancel_edit()


def test_parse_value_takes_only_plain_numbers():
    assert parse_value(" +0x10 ") == 16 and parse_value("-0X1f") == 0xFFFFFFE1
    for bad in ("0x-1", "0x 1", "0x+1", "\u0661\u0662", "\uff11", "+ 1"):
        assert parse_value(bad) is None, bad


def test_page_turns_keep_the_columns_scrolled_sideways(app, tmp_path, monkeypatch):
    data = loaded(app, tmp_path)
    moves = []
    monkeypatch.setattr(data.table.body, "xview", lambda *args: (0.4, 0.9))
    monkeypatch.setattr(data.table.body, "xview_moveto", moves.append)
    data.turn(1)
    assert moves[-1] == 0.4


def test_cut_copy_paste_and_select_all_in_a_register_field(app, tmp_path, monkeypatch):
    use_test_clipboard(app.root)
    loaded(app, tmp_path)
    tab = app.editor.current
    source = tab.get_text()
    app.registers.edit(row_of("R1"))
    field = app.registers.editor
    monkeypatch.setattr(app.root, "focus_get", lambda: field)
    app.root.clipboard_append("0x12")
    app.run("select_all")
    app.run("paste")
    assert field.get() == "0x12"
    app.run("select_all")
    app.run("cut")
    assert field.get() == "" and app.root.clipboard_get() == "0x12"
    app.run("paste")
    app.run("select_all")
    app.run("copy")
    assert tab.get_text() == source and app.views.select() == str(app.execute)
    app.registers.commit()
    assert app.machine.reg(1) == 0x12


def test_words_written_by_a_step_show_on_another_page(app, tmp_path):
    data = loaded(app, tmp_path, ".global _start\n_start: LDR R1, =0x00100000\n"
                                 "        MOV R0, #7\n        STR R0, [R1]\n        SVC #10\n")
    for _ in range(2):
        app.run("step")
    app.run("step")                                     # STR, while .data is shown
    data.show(0x00100000)
    assert data._row(0).cell_backgrounds == {"0": CHANGED}
    app.run("backstep")                                 # undone: nothing written now
    data.show(0x00100000)
    assert data._row(0).cell_backgrounds == {"0": CHANGED}  # differs from the step before


def test_words_written_by_a_long_recorded_run_show_after_a_step_too(app, tmp_path):
    app.settings.backstep_while_running = True
    data = loaded(app, tmp_path, ".global _start\n_start: LDR R1, =0x00100000\n"
                                 "        MOV R0, #0\nloop:   ADD R0, R0, #1\n"
                                 "        STR R0, [R1]\n        B loop\n")
    app.run("step")                                     # the history is not empty at Go
    app.run("go")
    run_until(app, lambda: app.machine.reg(0) > 1000)  # more than the history keeps
    app.run("pause")
    data.show(0x00100000)
    assert data._row(0).cell_backgrounds == {"0": CHANGED}


def test_no_register_field_opens_once_the_programs_file_is_closed(app, tmp_path):
    # Closing the program's file unloads it, so no field opens without a file.
    loaded(app, tmp_path)
    go_to_end(app)
    app.cmd_close()
    assert not app.is_enabled("cut") and not app.is_enabled("paste")
    app.registers.edit(row_of("R2"))
    assert app.registers.editor is None
    assert not app.is_enabled("cut") and not app.is_enabled("paste")
