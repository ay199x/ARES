# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Tools > Memory Map: how the stack starts, in the on-chip memory's rows, and SP's value now."""

from test_gui_assemble import assemble
from test_gui_run import loaded, run_until

from ares.gui.table import STRIPE, TEXT, WHITE, column_width
from ares.runner import State

DEVICES = ("0xff200000 - 0xff20ffff",
           "DE1-SoC devices: writes are ignored and reads give 0, except for the JTAG UART")
# The on-chip memory's rows: its range, then the rest of its text in indented rows of its
# own, without addresses. They come last, before the row of the other addresses, with a
# program and without.
ON_CHIP = [
    ("0xffff0000 - 0xffffffff", "On-chip memory, 64 KB (the stack): SP starts at 0x00000000, so"),
    ("", "    the first PUSH wraps around and stores at 0xfffffffc, the top of"),
    ("", "    the on-chip memory, as in CPUlator. A program that sets SP itself,"),
    ("", "    for example LDR SP, =0x3FFFFFF8, puts its stack in DDR3 instead."),
]
OTHER = ("other addresses", "no memory: the program stops with a runtime error")
STACK = """\
        .global _start
_start: MOV     R0, #7
        PUSH    {R0}
        LDR     SP, =0x3FFFFFF8
        PUSH    {R0}
        SVC     #10
"""
PUSH_FOREVER = """\
        .global _start
_start: PUSH    {R0}
loop:   ADD     R1, R1, #1
        B       loop
"""


def sp_line(app):
    return app.memory_map.sp_line.cget("text")


def colours(dialog):
    """The colour each row of the map is drawn in, top to bottom (every row is shown)."""
    table = dialog.table
    return [table.body.itemcget(table.slots[index][0], "fill") for index in range(table.count)]


def spy(monkeypatch, dialog):
    """Record the texts the SP line is given, and count the dialog's refreshes."""
    drawn, refreshed = [], []
    configure, refresh = dialog.sp_line.configure, dialog.refresh
    monkeypatch.setattr(dialog.sp_line, "configure",
                        lambda **kw: drawn.append(kw.get("text")) or configure(**kw))
    monkeypatch.setattr(dialog, "refresh", lambda: refreshed.append(True) or refresh())
    return drawn, refreshed


# The rows ------------------------------------------------------------------------

def test_the_on_chip_memory_says_how_the_stack_starts(app, tmp_path):
    """Said once, in the on-chip memory's rows: no row of its own for SP's start value."""
    app.run("memory_map")
    assert app.memory_map.rows[-5:] == ON_CHIP + [OTHER]
    loaded(app, tmp_path, STACK)
    rows = app.memory_map.rows
    assert ".text of the program" in rows[1][1]
    assert rows[-5:] == ON_CHIP + [OTHER]
    assert not any("SP at the start" in text for _, text in rows)
    app.memory_map.close()


def test_the_window_is_as_wide_with_a_program_as_without(app, tmp_path):
    """The devices' row is the widest, with a program and without: no on-chip row, and no
    row shown only with a program, is wider. So the Contents column needs the same width,
    the one that row needs, and the window keeps its width when a program is loaded."""
    app.run("memory_map")
    dialog = app.memory_map
    widths = []
    for source in (None, STACK):
        if source is not None:
            loaded(app, tmp_path, source)
        assert max(dialog.rows, key=lambda row: len(row[1])) == DEVICES
        dialog.window.update_idletasks()
        widths.append((dialog.table.columns[1].base, dialog.window.winfo_reqwidth()))
    assert widths[0] == widths[1]
    assert widths[0][0] == column_width(dialog.window, dialog.font, len(DEVICES[1]), "Contents")
    dialog.close()


def test_the_rows_of_an_entry_have_one_colour(app, tmp_path):
    """The stripes go by entry, not by row: the on-chip memory's further lines have the colour
    of its first row, so the four rows read as one entry, and the entries are white and gray
    in turn. A selected row keeps its colour and black text, framed (the rows have no
    action)."""
    app.run("memory_map")
    dialog = app.memory_map
    # DDR3, the devices, the JTAG UART, the on-chip memory (four rows), other addresses
    assert colours(dialog) == [WHITE, STRIPE, WHITE] + [STRIPE] * 4 + [WHITE]
    table = dialog.table
    table.select(5)                                         # a further line
    assert colours(dialog)[5] == STRIPE
    assert table.body.itemcget(table.slots[5][4], "fill") == TEXT
    assert table.body.itemcget(table._frame, "state") == "normal"
    loaded(app, tmp_path, STACK)
    # DDR3, its .text, the devices, the JTAG UART, the on-chip memory, other addresses
    assert colours(dialog) == [WHITE, STRIPE, WHITE, STRIPE] + [WHITE] * 4 + [STRIPE]
    dialog.close()


# SP now --------------------------------------------------------------------------

def test_sp_now_without_a_program(app):
    """SP's start value, as the Registers show it, on a line of its own under the table, at
    its left edge, above Close."""
    app.run("memory_map")
    dialog = app.memory_map
    assert sp_line(app) == "SP now: 0x00000000"
    assert dialog.window.pack_slaves() == [dialog.table, dialog.sp_line, dialog.close_button]
    place = dialog.sp_line.pack_info()
    assert place["anchor"] == "w" and place["padx"] == dialog.table.pack_info()["padx"]
    dialog.close()


def test_sp_now_follows_step_backstep_and_reset(app, tmp_path):
    loaded(app, tmp_path, STACK)
    app.run("memory_map")
    assert sp_line(app) == "SP now: 0x00000000"
    shown = []
    for _ in range(4):                  # MOV, PUSH, LDR SP, PUSH
        app.run("step")
        shown.append(sp_line(app))
    assert shown == ["SP now: 0x00000000", "SP now: 0xfffffffc", "SP now: 0x3ffffff8",
                     "SP now: 0x3ffffff4"]
    app.run("backstep")
    assert sp_line(app) == "SP now: 0x3ffffff8"
    app.run("reset")
    assert sp_line(app) == "SP now: 0x00000000"
    app.memory_map.close()


def test_sp_now_follows_a_value_typed_for_sp(app, tmp_path):
    loaded(app, tmp_path, STACK)
    app.run("memory_map")
    registers = app.registers
    registers.edit(13)                                      # SP
    registers.editor.delete(0, "end")
    registers.editor.insert(0, "0x3FFFFFF8")
    registers.commit()
    assert app.machine.reg(13) == 0x3FFFFFF8
    assert sp_line(app) == "SP now: 0x3ffffff8"
    app.memory_map.close()


def test_sp_now_when_the_map_opens_and_when_programs_come_and_go(app, tmp_path):
    """Opened after a PUSH, it shows SP at once; closing the program's file brings back
    the start value, and so does assembling again."""
    loaded(app, tmp_path, STACK)
    app.run("step")
    app.run("step")                                         # PUSH {R0}
    app.run("memory_map")
    assert sp_line(app) == "SP now: 0xfffffffc"
    assemble(app)
    assert app.runner is not None and sp_line(app) == "SP now: 0x00000000"
    app.run("step")
    app.run("step")
    assert sp_line(app) == "SP now: 0xfffffffc"
    app.run("close")
    assert app.program is None and sp_line(app) == "SP now: 0x00000000"
    app.memory_map.close()


def test_sp_now_follows_a_run_and_is_drawn_again_only_when_it_changed(app, tmp_path,
                                                                     monkeypatch):
    loaded(app, tmp_path, PUSH_FOREVER)
    app.run("memory_map")
    dialog = app.memory_map
    drawn, refreshed = spy(monkeypatch, dialog)
    app.run("go")
    run_until(app, lambda: len(refreshed) >= 5)             # five slices of the run
    assert app.runner.state is State.RUNNING
    app.run("stop")
    assert drawn == ["SP now: 0xfffffffc"]                  # once, after the first slice
    app.run("memory_map")                                   # chosen again: the same window
    assert dialog.window is not None and app.memory_map is dialog
    app._flag_toggled("CPSR", 31)                           # N: SP stays as it is
    assert drawn == ["SP now: 0xfffffffc"]
    app.memory_map.close()


def test_a_step_that_leaves_sp_alone_draws_nothing(app, tmp_path, monkeypatch):
    loaded(app, tmp_path, STACK)
    app.run("memory_map")
    drawn, refreshed = spy(monkeypatch, app.memory_map)
    app.run("step")                                         # MOV R0, #7
    assert refreshed and drawn == []
    app.run("step")                                         # PUSH {R0}
    assert drawn == ["SP now: 0xfffffffc"]
    app.memory_map.close()
