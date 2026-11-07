# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Execute tab: Text Segment rows, breakpoints, the next instruction, Labels and dividers."""

import time
import weakref
from tkinter import font as tkfont
from tkinter import ttk
from types import SimpleNamespace

import pytest
from conftest import VIRTUAL_DISPLAY, press_key, use_test_clipboard
from test_gui_assemble import assemble, open_source, wait_for_assembly

from ares import disasm
from ares.gui import app as app_module
from ares.gui import icons
from ares.gui import execute as execute_module
from ares.gui.execute import CURRENT, ExecutePane
from ares.program import Program
from ares.runner import State
from ares.settings import Settings

PROGRAM = """\
        .global _start
_start: LDR     R0, =0x12345678
        MOV     R1, #1
loop:   ADD     R1, R1, #1
        CMP     R1, #5
        BNE     loop
        SVC     #10
        .ltorg
        .data
value:  .word   7
"""
LOOP = 0x08             # address of loop:
POOL = 6                # row of the literal pool word


def loaded(app, tmp_path, source=PROGRAM):
    path, tab = open_source(app, tmp_path, source)
    assemble(app)
    return app.execute.text_segment


def cells(segment, index):
    return segment._row(index).cells


def click(table, index, column):
    """Click the middle of a cell of a row on the screen."""
    left = 0
    for c in table.columns:
        if c.id == column:
            break
        left += c.width
    y = (index - table.top) * table.row_height + table.row_height // 2
    table._press(SimpleNamespace(x=left + 2, y=y))


def test_a_successful_assemble_shows_the_execute_tab(app, tmp_path, hidden_windows):
    segment = loaded(app, tmp_path)
    assert app.views.select() == str(app.execute)
    assert segment.table.count == 7
    assert [cells(segment, i)[3] for i in range(7)] == [
        "LDR R0, [PC, #0x10]", "MOV R1, #1", "ADD R1, R1, #1", "CMP R1, #5", "BNE #8",
        "SVC #0xA", ".word 0x12345678"]
    # Keys typed now must not change the editor, which is no longer on the screen.
    assert hidden_windows.focus is segment.table.body
    assert app.machine.pc == 0 and app.runner.state is State.READY


def test_columns_of_a_row(app, tmp_path):
    segment = loaded(app, tmp_path)
    box, address, code, basic, source = cells(segment, 2)
    assert box == (False, True)                       # unchecked, enabled
    assert (address, code, basic) == ("0x00000008", "0xe2811001", "ADD R1, R1, #1")
    assert source == "4: loop:   ADD     R1, R1, #1"
    assert cells(segment, POOL) == (None, "0x00000018", "0x12345678", ".word 0x12345678", "")


def test_the_next_instruction_is_highlighted(app, tmp_path):
    segment = loaded(app, tmp_path)
    assert segment.pc_row == 0 and segment._row(0).background == CURRENT
    assert segment._row(1).background == ""
    segment.set_pc(LOOP)
    assert segment.pc_row == 2 and segment._row(2).background == CURRENT
    assert segment._row(0).background == ""
    segment.set_pc(0x1000)                              # no row there
    assert segment.pc_row is None
    segment.set_pc(None)
    assert segment.pc_row is None


def test_the_next_instruction_is_scrolled_into_view(app, tmp_path):
    source = ".global _start\n_start:\n" + "    NOP\n" * 300 + "    SVC #10\n"
    segment = loaded(app, tmp_path, source)
    table = segment.table
    segment.set_pc(4 * 250)
    assert table.top <= 250 < table.top + table.page
    segment.set_pc(4 * 3)
    assert table.top == 3


def test_the_next_instruction_stays_in_view_when_the_table_gets_its_size(app, tmp_path):
    source = ".global _start\nhelper:\n" + "    NOP\n" * 30 + "    BX LR\n_start: BL helper\n"
    segment = loaded(app, tmp_path, source + "    SVC #10\n")
    table = segment.table
    assert segment.pc_row == 31
    table.fit(10 * table.row_height + 7)        # the first Configure of the shown tab
    assert table.top <= 31 < table.top + table.page


def test_loading_again_without_clearing_first(app, tmp_path):
    source = ".global _start\n_start:\n" + "".join(f"L{i}: NOP\n" for i in range(60))
    segment = loaded(app, tmp_path, source + "    SVC #10\n")
    program, listing = segment.program, segment.listing
    small = disasm.Listing(listing.rows[:5], listing.instructions[:5], listing.sources,
                           listing.tab_size, listing.widest_basic, listing.widest_source)
    segment.load(program, small)
    assert segment.table.count == 5
    labels = app.execute.labels
    labels.load(program.labels[:3])
    assert labels.table.count == 3


def test_loading_takes_no_time_per_row_in_the_window(app, tmp_path, monkeypatch):
    segment = loaded(app, tmp_path)

    def is_code(self, address):
        raise AssertionError("the window worked out the rows itself")
    monkeypatch.setattr(Program, "is_code", is_code)
    segment.load(segment.program, segment.listing)
    assert segment._code == [True] * 6 + [False]


def test_a_failure_while_loading_leaves_a_working_window(app, tmp_path, monkeypatch,
                                                         hidden_windows):
    path, tab = open_source(app, tmp_path, PROGRAM)
    app.views.select(app.execute)

    def broken(*args, **options):
        raise MemoryError("no memory for the machine")
    monkeypatch.setattr(app_module, "Machine", broken)
    lines = assemble(app)
    assert "Assemble: operation completed successfully." in lines
    assert any("Internal error: MemoryError" in line for line in lines)
    assert app.program is None and app.machine is None and app.runner is None
    assert app.is_enabled("assemble") and not app.is_enabled("toggle_breakpoints")
    assert app.execute.text_segment.table.count == 0
    assert app.views.select() == str(app.editor) and hidden_windows.focus is tab.text
    monkeypatch.undo()
    assemble(app)
    assert app.machine is not None


def test_a_queued_assemble_runs_after_a_failure_while_loading(app, tmp_path, monkeypatch):
    path, tab = open_source(app, tmp_path, PROGRAM)
    monkeypatch.setattr(app_module, "Machine", lambda *a, **o: 1 / 0)
    app.run("assemble")
    app.cmd_assemble()                          # as opening a file while assembling does
    wait_for_assembly(app)
    wait_for_assembly(app)
    starts = [line for line in app.messages.messages.get("1.0", "end-1c").splitlines()
              if line.startswith("Assemble: assembling")]
    assert len(starts) == 2 and app.is_enabled("assemble") and not app._assemble_next


def test_assembling_again_frees_the_old_machine_memory(app, tmp_path):
    loaded(app, tmp_path)
    machine = app.machine
    assert list(machine.uc.mem_regions())
    machine.close()                         # what assembling again does first
    assert list(machine.uc.mem_regions()) == []


def test_assembling_again_frees_the_old_emulator(app, tmp_path):
    loaded(app, tmp_path)
    emulator = weakref.ref(app.machine.uc)
    assemble(app)
    assert emulator() is None and app.machine is not None


def test_reset_gives_back_the_memory_of_the_replaced_emulator(app, tmp_path):
    loaded(app, tmp_path)
    old = app.machine.uc
    app.run("reset")
    assert app.machine.uc is not old and list(old.mem_regions()) == []


def test_source_column_follows_a_new_tab_width(app, tmp_path):
    segment = loaded(app, tmp_path, ".global _start\n_start:\tMOV\tR0, #1\n\tSVC\t#10\n")
    assert cells(segment, 0)[4] == "2: _start: MOV R0, #1"
    width = segment.table.columns[4].width
    app.settings.tab_size = 8
    app.apply_settings()
    assert cells(segment, 0)[4] == "2: _start: MOV     R0, #1"
    assert cells(segment, 1)[4] == "3:         SVC     #10"
    assert segment.table.columns[4].width >= width if VIRTUAL_DISPLAY \
        else segment.table.columns[4].width > width     # mapped, the column has room already


def test_addresses_follow_the_setting(app, tmp_path):
    segment = loaded(app, tmp_path)
    app.cmd_restore_defaults()
    app.setting_vars["show_labels"].set(True)
    app._setting_toggled("show_labels")
    app.setting_vars["hex_addresses"].set(False)
    app._setting_toggled("hex_addresses")
    assert cells(segment, 2)[1:3] == ("8", "0xe2811001")      # Code stays hexadecimal
    assert app.execute.labels._row(1).cells == ("loop", "8")
    shown = [segment.table.body.itemcget(segment.table.slots[2][4], "text")]
    assert shown == ["8"]
    app.setting_vars["hex_addresses"].set(True)
    app._setting_toggled("hex_addresses")
    assert cells(segment, 2)[1] == "0x00000008"


def test_clicking_a_checkbox_sets_and_clears_a_breakpoint(app, tmp_path):
    segment = loaded(app, tmp_path)
    click(segment.table, 2, "bkpt")
    assert segment.breakpoints == {LOOP} and app.machine.breakpoints == {LOOP}
    assert cells(segment, 2)[0] == (True, True)
    click(segment.table, 2, "address")                  # other columns only select
    assert app.machine.breakpoints == {LOOP} and segment.table.selected == 2
    click(segment.table, 2, "bkpt")
    assert segment.breakpoints == set() and app.machine.breakpoints == set()


def test_literal_pool_words_have_no_checkbox(app, tmp_path):
    segment = loaded(app, tmp_path)
    click(segment.table, POOL, "bkpt")
    assert segment.breakpoints == set() and app.machine.breakpoints == set()
    segment.toggle_breakpoint(0x18)
    segment.toggle_breakpoint(0x1000)
    assert app.machine.breakpoints == set()


def test_double_click_on_a_checkbox_changes_it_twice(app, tmp_path):
    segment = loaded(app, tmp_path)
    table = segment.table
    click(table, 1, "bkpt")
    y = table.row_height + 1
    table._double(SimpleNamespace(x=2, y=y))            # the second click of the two
    assert app.machine.breakpoints == set()


def test_a_breakpoint_stops_the_run(app, tmp_path):
    segment = loaded(app, tmp_path)
    segment.toggle_breakpoint(LOOP + 4)
    assert app.runner.run(time_limit=5) is State.PAUSED
    assert app.machine.pc == LOOP + 4 and app.machine.reg(1) == 2


def test_breakpoint_commands_need_a_program(app, tmp_path):
    for name in ("clear_breakpoints", "toggle_breakpoints"):
        assert not app.is_enabled(name)
    loaded(app, tmp_path)
    for name in ("clear_breakpoints", "toggle_breakpoints"):
        assert app.is_enabled(name)


def test_toggle_all_breakpoints_switches_them_off_and_on(app, tmp_path):
    segment = loaded(app, tmp_path)
    segment.toggle_breakpoint(0x04)
    segment.toggle_breakpoint(LOOP)
    app.run("toggle_breakpoints")
    assert app.machine.breakpoints == set() and segment.breakpoints == {0x04, LOOP}
    assert cells(segment, 1)[0] == (True, False)          # gray, still checked
    assert cells(segment, 3)[0] == (False, False)
    assert app.runner.run(time_limit=5) is State.FINISHED
    app.runner.reset()
    app.run("toggle_breakpoints")
    assert app.machine.breakpoints == {0x04, LOOP}
    assert cells(segment, 1)[0] == (True, True)


def test_a_click_on_the_bkpt_heading_toggles_all_breakpoints(app, tmp_path):
    segment = loaded(app, tmp_path)
    segment.toggle_breakpoint(LOOP)
    table = segment.table
    table._heading_press(SimpleNamespace(x=3, y=5))
    table._heading_release(SimpleNamespace(x=3, y=5))
    assert app.machine.breakpoints == set() and not segment.enabled
    table._heading_press(SimpleNamespace(x=3, y=5))
    table._heading_release(SimpleNamespace(x=3, y=5))
    assert app.machine.breakpoints == {LOOP}


def test_unchecking_while_switched_off_keeps_the_rest_off(app, tmp_path):
    segment = loaded(app, tmp_path)
    segment.toggle_breakpoint(LOOP)
    app.run("toggle_breakpoints")
    click(segment.table, 1, "bkpt")                    # checked, but all are off
    assert segment.breakpoints == {0x04, LOOP} and app.machine.breakpoints == set()
    app.run("toggle_breakpoints")
    assert app.machine.breakpoints == {0x04, LOOP}


def test_clear_all_breakpoints(app, tmp_path):
    segment = loaded(app, tmp_path)
    segment.toggle_breakpoint(0x04)
    segment.toggle_breakpoint(LOOP)
    app.run("toggle_breakpoints")
    app.run("clear_breakpoints")
    assert segment.breakpoints == set() and app.machine.breakpoints == set()
    assert segment.enabled                              # new breakpoints work at once
    segment.toggle_breakpoint(LOOP)
    assert app.machine.breakpoints == {LOOP}


def test_breakpoint_shortcuts_work_from_the_table(app, tmp_path):
    segment = loaded(app, tmp_path)
    segment.toggle_breakpoint(LOOP)
    press_key(segment.table.body, "<Control-Key-t>")
    assert not segment.enabled and app.machine.breakpoints == set()
    press_key(segment.table.body, "<Control-Key-k>")
    assert segment.enabled and segment.breakpoints == set()


def test_assembling_again_starts_without_breakpoints(app, tmp_path):
    segment = loaded(app, tmp_path)
    segment.toggle_breakpoint(LOOP)
    machine = app.machine
    assemble(app)
    assert app.machine is not machine
    assert segment.breakpoints == set() and app.machine.breakpoints == set()
    assert segment.enabled


def test_a_failed_assemble_empties_the_execute_tab(app, tmp_path, hidden_windows):
    segment = loaded(app, tmp_path)
    tab = app.editor.current
    tab.text.insert("end", "        BAD     R0\n")
    lines = assemble(app)
    assert lines[-1] == "Assemble: operation completed with errors."
    assert app.views.select() == str(app.editor) and hidden_windows.focus is tab.text
    assert segment.table.count == 0 and app.execute.labels.table.count == 0
    assert app.program is None and app.machine is None and app.runner is None
    assert not app.is_enabled("toggle_breakpoints")


def test_the_execute_tab_is_emptied_while_assembling(app, tmp_path):
    segment = loaded(app, tmp_path)
    app.run("assemble")
    assert segment.table.count == 0 and app.machine is None
    wait_for_assembly(app)
    assert segment.table.count == 7


def test_cut_and_paste_in_the_table_leave_the_editor_alone(app, tmp_path, monkeypatch):
    use_test_clipboard(app.root)
    segment = loaded(app, tmp_path)
    tab = app.editor.current
    text = tab.get_text()
    monkeypatch.setattr(app.root, "focus_get", lambda: segment.table.body)
    app.root.clipboard_append("PASTED")
    for key, command in (("Ctrl+X", "cut"), ("Ctrl+V", "paste")):
        press_key(segment.table.body, app._sequences(key)[0])
        app.run(command)
    assert tab.get_text() == text and app.views.select() == str(app.execute)


def test_copy_and_select_all_in_the_table_leave_the_editor_alone(app, tmp_path, monkeypatch):
    use_test_clipboard(app.root)
    segment = loaded(app, tmp_path)
    tab = app.editor.current
    monkeypatch.setattr(app.root, "focus_get", lambda: segment.table.body)
    app.root.clipboard_append("BEFORE")
    for key in ("Ctrl+A", "Ctrl+C"):
        press_key(segment.table.body, app._sequences(key)[0])
    app.run("select_all")
    app.run("copy")
    assert not tab.text.tag_ranges("sel") and app.root.clipboard_get() == "BEFORE"
    assert app.views.select() == str(app.execute)


def test_copy_and_select_all_with_the_execute_tab_in_front(app, tmp_path, monkeypatch):
    use_test_clipboard(app.root)
    loaded(app, tmp_path)
    tab = app.editor.current
    monkeypatch.setattr(app.root, "focus_get", lambda: app.views)  # a click on a tab's name
    app.root.clipboard_append("BEFORE")
    app.run("select_all")
    app.run("copy")
    assert not tab.text.tag_ranges("sel") and app.root.clipboard_get() == "BEFORE"
    app.views.select(app.editor)
    app.run("select_all")
    assert tab.text.tag_ranges("sel")


def test_a_tab_width_changed_while_assembling_fits_the_source_column(app, tmp_path):
    source = ".global _start\n_start:\tMOV\tR0, #1\t\t\t\t\t\t\t\t@ c\n\tSVC\t#10\n"
    open_source(app, tmp_path, source)
    app.run("assemble")
    app.settings.tab_size = 8               # Editor Font... while the assembler works
    app.apply_settings()
    wait_for_assembly(app)
    segment = app.execute.text_segment
    table = segment.table
    shown = table.body.itemcget(table.slots[0][2 + 2 * 4], "text")
    assert shown == segment.listing.sources.text(2, 8) and shown.endswith("@ c")


@pytest.mark.parametrize("split_labels", [0.75, 0.6])
@pytest.mark.parametrize("at_start", [False, True], ids=["turned on later", "on from the start"])
def test_the_segments_reach_the_divider_of_the_labels(mapped_area, monkeypatch, split_labels,
                                                       at_start):
    """A divider moved while its window places its panes takes effect for the panes after it
    only: the segments must not keep their width, with a blank strip beside them, or run under
    the Labels."""
    inside = mapped_area(1400, 600)
    monkeypatch.setattr(execute_module, "SPLIT_LABELS", split_labels)
    settings = Settings(show_labels=at_start)
    font = tkfont.Font(root=inside, family="Courier New", size=10)
    images = {name: icons.photo(inside, name, 16) for name in ("page_previous", "page_next")}
    notebook = ttk.Notebook(inside)
    pane = ExecutePane(notebook, settings, font, images)
    notebook.add(pane, text="Execute")
    notebook.place(x=0, y=0, width=1400, height=600)
    inside.update()
    if not at_start:
        settings.show_labels = True
        pane.apply_settings()
        inside.update()
    assert abs(pane.sashpos(0) - split_labels * pane.winfo_width()) <= 2
    assert pane.segments.winfo_width() == pane.sashpos(0)
    assert pane.labels.winfo_x() >= pane.sashpos(0)


def test_labels_turned_on_later_get_their_width(tk_root):
    """With real sizes: the Labels shown after the Execute tab had its size."""
    settings = Settings()
    font = tkfont.Font(root=tk_root, family="Courier New", size=10)
    images = {name: icons.photo(tk_root, name, 16) for name in ("page_previous", "page_next")}
    pane = ExecutePane(tk_root, settings, font, images)
    pane.place(x=0, y=0, width=1000, height=600)
    tk_root.update_idletasks()
    assert pane.winfo_width() == 1000
    settings.show_labels = True
    pane.apply_settings()
    tk_root.update_idletasks()
    assert abs(pane.sashpos(0) - 750) <= 10 and pane.labels.winfo_width() > 150
    assert pane.segments.winfo_width() == pane.sashpos(0)
    settings.show_labels = False
    pane.apply_settings()
    assert abs(pane.split_labels - 0.75) < 0.02
    settings.show_labels = True
    pane.apply_settings()
    tk_root.update_idletasks()
    assert pane.labels.winfo_width() > 150
    pane.destroy()


def test_labels_window_follows_the_setting(app, tmp_path):
    loaded(app, tmp_path)
    execute = app.execute
    assert execute.panes() == (str(execute.segments),)
    app.setting_vars["show_labels"].set(True)
    app._setting_toggled("show_labels")
    assert execute.panes() == (str(execute.segments), str(execute.labels))
    assert [execute.labels._row(i).cells for i in range(3)] == [
        ("_start", "0x00000000"), ("loop", "0x00000008"), ("value", "0x0000001c")]
    app.setting_vars["show_labels"].set(False)
    app._setting_toggled("show_labels")
    assert execute.panes() == (str(execute.segments),)


def test_labels_are_sorted_by_address_then_name(app, tmp_path):
    source = (".global _start\n_start:\nzeta:\nalpha: NOP\nbeta: SVC #10\n"
              ".data\nlate: .word 1\nearly: .word 2\n")
    loaded(app, tmp_path, source)
    labels = app.execute.labels
    assert [label.name for label in labels.labels] == [
        "_start", "alpha", "zeta", "beta", "late", "early"]


def test_double_clicking_a_label_shows_its_instruction(app, tmp_path):
    source = ".global _start\n_start:\n" + "    NOP\n" * 300 + "far: SVC #10\n"
    segment = loaded(app, tmp_path, source)
    labels = app.execute.labels
    index = [label.name for label in labels.labels].index("far")
    labels.table._double(SimpleNamespace(x=5, y=index * labels.table.row_height + 1))
    table = segment.table
    assert table.selected == 300
    assert table.top == 300 - (table.page - 1) // 2 or table.top == table.count - table.page


def test_double_clicking_a_data_label_leaves_the_text_segment(app, tmp_path):
    segment = loaded(app, tmp_path)
    labels = app.execute.labels
    segment.table.select(1)
    labels.table._double(SimpleNamespace(x=5, y=2 * labels.table.row_height + 1))   # value
    assert segment.table.selected == 1


def test_source_column_uses_the_tab_width(app, tmp_path):
    app.settings.tab_size = 8
    segment = loaded(app, tmp_path, ".global _start\n_start:\tMOV\tR0, #1\n\tSVC\t#10\n")
    assert segment.rows[0].source == "2: _start: MOV     R0, #1"
    assert segment.rows[1].source == "3:         SVC     #10"


@pytest.mark.serial
def test_a_program_of_5000_instructions_opens_within_a_second(app, tmp_path):
    lines = [".global _start", "_start:"]
    for i in range(5000):
        if i % 50 == 0:
            lines.append(f"L{i}:")
        lines.append(f"    ADD R{i % 8}, R{(i + 1) % 8}, #{i % 200}      @ instruction {i}")
    lines.append("    SVC #10")
    open_source(app, tmp_path, "\n".join(lines) + "\n")
    times = []
    for attempt in range(2):                        # the better of two: the PC may be busy
        start = time.perf_counter()
        app.run("assemble")
        wait_for_assembly(app)
        times.append(time.perf_counter() - start)
        assert app.execute.text_segment.table.count == 5001
        assert app.views.select() == str(app.execute)
    assert min(times) < 1.0, f"opening took {min(times):.3f} s"


# Tables that fill their width -----------------------------------------------------

def widths(table):
    return [column.width for column in table.columns]


def test_source_takes_the_width_the_other_columns_leave(app, tmp_path):
    loaded(app, tmp_path)
    table = app.execute.text_segment.table
    fixed = [column.base for column in table.columns[:4]]
    table.fill(2000)
    assert widths(table)[:4] == fixed and sum(widths(table)) == 2000
    table.fill(300)                     # narrower than the columns need: they keep that
    assert widths(table) == [column.base for column in table.columns]
    assert table.hscroll.winfo_manager() == "grid"


def test_the_data_segment_shares_its_width_equally(app, tmp_path):
    loaded(app, tmp_path)
    table = app.execute.data_segment.table
    assert len(table.columns) == 9 and all(column.stretch for column in table.columns)
    table.fill(1800)
    assert widths(table) == [200] * 9
    assert [column.anchor for column in table.columns] == ["e"] * 9


def test_the_register_tabs_share_their_width_equally(app):
    registers = app.registers.table
    registers.fill(800)
    assert widths(registers) == [200] * 4
    # Name left, Number and Value right, Flags from the left.
    assert [column.anchor for column in registers.columns[:3]] == ["w", "e", "e"]
    assert registers.columns[3].marks
    for pane in (app.coproc10, app.coproc11):
        pane.table.fill(900)
        assert widths(pane.table) == [300] * 3
        assert [column.anchor for column in pane.table.columns[:2]] == ["w", "e"]


def test_the_labels_share_their_width(app, tmp_path):
    loaded(app, tmp_path)
    table = app.execute.labels.table
    table.fill(400)
    assert widths(table) == [200, 200]


def test_the_registers_fill_their_tab_on_the_screen(app, tmp_path):
    """The window's own size reaches the Registers tab although the window stays hidden.

    (Tk lays out a hidden window once a size request reaches it: opening a file does.)
    """
    loaded(app, tmp_path)
    table = app.registers.table
    table.body.winfo_id()               # its first <Configure> comes when its window is made
    app.root.update_idletasks()
    width = table.body.winfo_width()
    assert width > 1 and table._available == width
    assert sum(widths(table)) == max(width, sum(column.base for column in table.columns))
