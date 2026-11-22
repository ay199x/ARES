# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Pipeline Simulator's window: its numbers, branch lines, reservation table, key and tips,
the Settings and Check Dependency windows, and its layout at four display scales."""

import time
import tkinter as tk
from types import SimpleNamespace

import pytest
import window_layout
from conftest import ROOT, lay_out, press_key
from test_gui_assemble import assemble
from test_gui_run import go_to_end, loaded, run_until
from test_style import make_root  # noqa: F401  (a fixture: a root at a display scale)
from xray_layout import clashes

from ares import credits, helptext, pipeline
from ares.gui.app import App
from ares.gui.tools import pipeline as tool
from ares.gui.tools.pipeline import (EMPTY, CheckWindow, PipelineWindow, SettingsWindow,
                                     numbers, two_places)
from ares.pipeline import DYNAMIC, EX, FLUSH, MEM, STALL, STATIC, Row, Settings

# The start of the example: two equal values, BNE not taken, BEQ taken over three lines, a
# load and its use.
BENCH = """\
        .data
value:  .word   5
        .global _start
        .text
_start: MOV     R0, #20
        MOV     R1, #20
        CMP     R0, R1
        BNE     next
        MOV     R2, #30
        MOV     R3, #30
        MOV     R4, #30
        CMP     R3, R4
        BEQ     end
next:   MOV     R5, #8
        MOV     R6, #8
        MOV     R7, #8
end:    MOV     R8, #8
        LDR     R9, =value
        LDR     R10, [R9]
        ADD     R10, R10, R8
        SVC     #10
"""
LOOP = """\
        .global _start
        .text
_start: MOV     R0, #200
loop:   LDR     R1, [SP, #-4]
        ADD     R2, R1, #1
        SUBS    R0, R0, #1
        BNE     loop
        SVC     #10
"""
MISSED = Settings(prediction=STATIC, static_taken=False, branch_stage=MEM)


def opened(app):
    """The Pipeline Simulator's window, from the Tools menu (or brought to the front)."""
    app.run("tool_pipeline")
    window = app.tool_windows["tool_pipeline"]
    assert isinstance(window, PipelineWindow)
    return window


def connected(app):
    window = opened(app)
    window.connect_button.invoke()
    assert window.model.connected
    return window


def fields(window):
    return [variable.get() for variable in window.fields]


def log_lines(window):
    return window.log.get("1.0", "end-1c").splitlines()


def drawn_cells(window):
    """{(row number, cycle): (stage drawn, its rectangle's colour)} of the cells in view."""
    canvas, found = window.table.canvas, {}
    for item in canvas.find_all():
        for tag in canvas.gettags(item):
            if tag.startswith("cell:"):
                index, cycle = map(int, tag[5:].split("."))
                entry = found.setdefault((index, cycle), ["", ""])
                if canvas.type(item) == "text":
                    entry[0] = canvas.itemcget(item, "text")
                else:
                    entry[1] = canvas.itemcget(item, "fill")
    return {cell: tuple(entry) for cell, entry in found.items()}


# The window --------------------------------------------------------------------------------

def test_the_window_has_its_heading_toolbar_numbers_table_and_tool_control(app):
    window = opened(app)
    assert window.window.title() == "Pipeline Simulator"
    assert window.HEADING == "Five-Stage Pipeline and Branch Prediction"
    assert list(window.tool_buttons) == ["assemble", "step", "backstep"]
    assert window.settings_button.cget("text") == "Settings..."
    assert window.check_button.cget("text") == "Check Dependency"
    assert window.connect_button.cget("text") == "Connect to ARM"
    assert fields(window) == ["0", "0", "0", "0", "", "", "no prediction"]
    assert window.table.rows == [] and window.table.message == EMPTY[False]
    assert str(window.summary.cget("text")) == "Settings: " + Settings().summary()


def test_connected_it_follows_a_run_to_its_end(app, tmp_path):
    loaded(app, tmp_path, BENCH)
    window = connected(app)
    assert window.table.message == EMPTY[True]
    go_to_end(app)
    model = window.model
    assert model.totals.instructions == 14
    assert fields(window) == list(numbers(model.totals, model.settings))
    assert window.table.rows == model.rows() and len(window.table.rows) == 14
    assert [line.split("]")[0] for line in log_lines(window)] == ["[BNE next", "[BEQ end"]
    assert "No prediction | Actual: Taken" in log_lines(window)[1]


def test_the_toolbar_steps_and_backsteps_the_program(app, tmp_path):
    loaded(app, tmp_path, BENCH)
    window = connected(app)
    assert window.tool_buttons["step"].instate(["!disabled"])
    for _ in range(3):
        window.tool_buttons["step"].invoke()
    assert len(window.table.rows) == 3
    rows_in_view = window.table.in_view()[0]
    assert window.table.top + rows_in_view >= 3        # the newest row in view
    window.tool_buttons["backstep"].invoke()
    assert len(window.table.rows) == 2                 # taken out of the pipeline again
    assert app.machine.pc == app.program.entry + 8
    window.tool_buttons["step"].invoke()
    assert len(window.table.rows) == 3
    assert window.table.rows[-1].text == "CMP R0, R1"


def test_a_stall_cell_says_what_it_waits_for(app, tmp_path):
    loaded(app, tmp_path, BENCH)
    window = connected(app)
    go_to_end(app)
    table = window.table
    table.yview("moveto", 0)
    table.xview("moveto", 0)
    cells = drawn_cells(window)
    index = next(number for number, row in enumerate(table.rows) if row.text == "CMP R0, R1")
    waiting = sorted(cycle for (number, cycle), (stage, _) in cells.items()
                     if number == index and stage == STALL)
    assert len(waiting) == 3
    assert cells[index, waiting[0]][1] == tool.COLOURS[STALL]
    canvas = table.canvas
    item = canvas.find_withtag(f"cell:{index}.{waiting[0]}")[0]
    left, top, right, bottom = canvas.bbox(item)
    cell = table.cell_at((left + right) // 2, (top + bottom) // 2)
    assert cell == (index, waiting[0])
    assert table.tip(cell) == "waits for R1 from MOV R1, #20 at 0x00000004"


def test_the_instructions_thrown_away_end_in_flush(app, tmp_path):
    loaded(app, tmp_path, BENCH)
    window = connected(app)
    window.confirm(MISSED)
    go_to_end(app)
    thrown = [row for row in window.table.rows if row.flushed]
    # BNE is predicted not taken, and is not taken; BEQ is taken against the prediction.
    assert [row.text for row in thrown] == ["MOV R5, #8", "MOV R6, #8", "MOV R7, #8"]
    assert [row.cells[-1] for row in thrown] == [FLUSH] * 3
    assert thrown[0].note == ("thrown away: the branch BEQ end at 0x00000020 was taken, "
                              "against the prediction")
    assert int(window.fields[3].get()) == window.model.totals.flushes == 3


def test_the_table_shows_the_last_500_rows_and_scrolls_both_ways(app, tmp_path):
    loaded(app, tmp_path, LOOP)
    window = connected(app)
    go_to_end(app)
    table = window.table
    rows_in_view, cycles_in_view = table.in_view()
    assert len(table.rows) == pipeline.ROWS
    assert table.top == pipeline.ROWS - rows_in_view and table.left == table.count - cycles_in_view
    last_cycle = table.first + table.count - 1
    heads = [window.table.canvas.itemcget(item, "text")
             for item in table.canvas.find_withtag(f"head:cycle{last_cycle}")
             if table.canvas.type(item) == "text"]
    assert heads == [str(last_cycle)]                   # the newest cycle in view
    table.yview("moveto", 0)
    table.xview("moveto", 0)
    assert (table.top, table.left) == (0, 0)
    table.xview("scroll", 1, "pages")
    table.yview("scroll", 2, "units")
    assert (table.top, table.left) == (2, cycles_in_view)
    table.yview("scroll", 10 ** 6, "units")
    assert table.top == pipeline.ROWS - rows_in_view


def test_while_running_at_full_speed_the_table_waits(app, tmp_path, monkeypatch):
    loaded(app, tmp_path, BENCH)
    window = connected(app)
    monkeypatch.setattr(window, "_racing", lambda: True)
    app.runner.run()
    window.refresh()
    assert fields(window)[0] == "14" and window.table.rows == [] and window._stale
    monkeypatch.setattr(window, "_racing", lambda: False)
    window.refresh()
    assert len(window.table.rows) == 14 and len(log_lines(window)) == 2


def test_reset_starts_again_and_disconnect_keeps_what_is_shown(app, tmp_path):
    loaded(app, tmp_path, BENCH)
    window = connected(app)
    go_to_end(app)
    window.connect_button.invoke()
    assert not window.model.connected and len(window.table.rows) == 14
    window.reset_button.invoke()
    assert fields(window)[:4] == ["0", "0", "0", "0"] and window.table.rows == []
    assert log_lines(window) == []


def test_the_numbers_are_rounded_as_by_hand():
    assert two_places(4, 3) == "1.33" and two_places(7, 4) == "1.75" and two_places(2, 1) == "2.00"
    assert two_places(5, 0) == ""
    totals = pipeline.Totals(8, 14, 0, 2, 1, 1)
    assert numbers(totals, Settings(prediction=DYNAMIC)) == (
        "8", "14", "0", "2", "1.75", "1.25", "1 of 2")


# Backstep, Reset and Assemble ------------------------------------------------------------------

def test_a_step_and_a_backstep_leave_the_tool_empty(app, tmp_path):
    loaded(app, tmp_path, BENCH)
    window = connected(app)
    app.run("step")
    assert len(window.table.rows) == 1 and fields(window)[:2] == ["1", "5"]
    app.run("backstep")
    assert window.table.rows == [] and fields(window)[:4] == ["0", "0", "0", "0"]
    assert log_lines(window) == [] and window.table.message == EMPTY[True]


def test_a_backstep_over_a_branch_takes_its_line_out(app, tmp_path):
    loaded(app, tmp_path, BENCH)
    window = connected(app)
    for _ in range(4):                                  # MOV, MOV, CMP, BNE
        app.run("step")
    assert [line.split("]")[0] for line in log_lines(window)] == ["[BNE next"]
    app.run("backstep")
    assert log_lines(window) == [] and len(window.table.rows) == 3
    go_to_end(app)
    assert [line.split("]")[0] for line in log_lines(window)] == ["[BNE next", "[BEQ end"]
    assert fields(window) == list(numbers(window.model.totals, window.model.settings))
    assert window.model.totals.instructions == 14


def test_after_a_run_kept_for_backstep_each_backstep_takes_one_out(app, tmp_path):
    app.settings.backstep_while_running = True
    loaded(app, tmp_path, BENCH)
    window = connected(app)
    go_to_end(app)
    for left in (13, 12, 11):
        app.run("backstep")
        assert fields(window)[0] == str(left)
        assert len([row for row in window.table.rows if not row.flushed]) == left


def test_reset_and_assemble_empty_the_tool(app, tmp_path):
    loaded(app, tmp_path, BENCH)
    window = connected(app)
    go_to_end(app)
    assert len(window.table.rows) == 14
    app.run("reset")
    assert window.table.rows == [] and fields(window)[:4] == ["0", "0", "0", "0"]
    assert log_lines(window) == []
    go_to_end(app)
    assert len(window.table.rows) == 14                 # one run, not two
    assemble(app)
    assert window.model.connected and window.table.rows == [] and fields(window)[0] == "0"


def test_disconnect_and_connect_keep_what_the_tool_shows(app, tmp_path):
    loaded(app, tmp_path, BENCH)
    window = connected(app)
    for _ in range(3):
        app.run("step")
    window.connect_button.invoke()                      # Disconnect from ARM
    window.connect_button.invoke()                      # Connect to ARM
    assert len(window.table.rows) == 3
    app.run("step")
    assert len(window.table.rows) == 4


# Instructions as written -----------------------------------------------------------------------

def test_the_table_names_instructions_as_written_and_its_tip_gives_the_basic_form(app,
                                                                              tmp_path):
    loaded(app, tmp_path, BENCH)
    window = connected(app)
    go_to_end(app)
    table = window.table
    table.yview("moveto", 0)
    texts = [row.text for row in table.rows]
    assert texts[:4] == ["MOV R0, #20", "MOV R1, #20", "CMP R0, R1", "BNE next"]
    assert "LDR R9, =value" in texts
    canvas = table.canvas
    items = canvas.find_withtag("row:0")
    assert [canvas.itemcget(item, "text") for item in items] == ["0x00000000", "MOV R0, #20"]
    left, top, right, bottom = canvas.bbox(items[1])
    spot = table.spot_at((left + right) // 2, (top + bottom) // 2)
    assert spot == (0, None) and table.tip(spot) == "Basic: MOV R0, #0x14"
    assert table.tip((texts.index("CMP R0, R1"), None)) == ""   # the same in both forms
    window.open_check()
    listing = window.check_window.text.get("1.0", "end-1c").splitlines()
    assert "0x00000000  MOV R0, #20" in listing and "0x0000000c  BNE next" in listing
    assert listing[0] == "_start:" and "next:" in listing


def test_a_long_instruction_s_tip_gives_all_of_it(app):
    window = opened(app)
    text = "ADRL    R2, a_label_far_away"
    window.table.show([Row(0, text, False, 1, 1, 2, ("IF", "ID", "EX", "MEM", "WB"),
                           basic="ADD R2, PC, #0x40")])
    assert window.table.tip((0, None)) == text + "\nBasic: ADD R2, PC, #0x40"


def test_rows_of_a_program_no_longer_loaded_show_their_basic_form(app, tmp_path):
    loaded(app, tmp_path, BENCH)
    window = connected(app)
    for _ in range(2):
        app.run("step")
    window.connect_button.invoke()                      # Disconnect: the rows stay
    loaded(app, tmp_path, LOOP, name="other.s")
    assert [row.text for row in window.table.rows] == ["MOV R0, #0x14", "MOV R1, #0x14"]


# The numbers' tips ---------------------------------------------------------------------------

def test_each_number_has_a_tip_with_its_sum(app, tmp_path):
    """The first Step of the tour: 1 instruction, 5 cycles, CPI 5.00 and steady-state CPI
    1.00, as the help says; at its end the help's example, 62 / 28 = 2.21."""
    loaded(app, tmp_path, (ROOT / "examples" / "pipeline_tour.s").read_text(encoding="utf-8"))
    window = connected(app)
    app.run("step")
    assert all(label.text == field.text for label, field in window.number_tips)
    shown = [field.text for _, field in window.number_tips]
    assert shown[1].startswith("Cycles = instructions + 4 + cycles lost = 1 + 4 + 0 = 5\n")
    assert shown[4].startswith("CPI = cycles / instructions = 5 / 1 = 5.00\n")
    assert shown[5].startswith("Steady-state CPI = (cycles - 4) / instructions = (5 - 4) / 1 = "
                               "1.00\n")
    go_to_end(app)
    assert window.number_tips[4][1].text.startswith("CPI = cycles / instructions = 62 / 28 = 2.21")
    words = " ".join(tool.HELP.split())
    for phrase in ("CPI 5 / 1 = 5.00", "(5 - 4) / 1 = 1.00", "62 / 28 = 2.21",
                   "CPI 5.00 and steady-state CPI 1.00"):
        assert phrase in words, phrase


def test_the_tips_say_what_each_number_is():
    texts = tool.tips(pipeline.Totals(8, 14, 0, 2, 1, 1), Settings(prediction=DYNAMIC))
    assert texts[0] == "Instructions: how many instructions the program executed = 8"
    assert texts[1].startswith("Cycles = instructions + 4 + cycles lost = 8 + 4 + 2 = 14\n")
    assert texts[2].startswith("Lost to stalls = the cycles lost while instructions waited = 0\n")
    assert texts[3].startswith("Lost to flushes = the cycles lost to instructions thrown away "
                               "= 2\n")
    assert texts[4].startswith("CPI = cycles / instructions = 14 / 8 = 1.75\n")
    assert texts[5].startswith("Steady-state CPI = (cycles - 4) / instructions = (14 - 4) / 8 "
                               "= 1.25\n")
    assert texts[6].startswith("Predictions right = 1 of 2 predictions (1 right + 1 wrong = 2)")
    none = tool.tips(pipeline.Totals(), Settings())
    assert none[4].startswith("CPI = cycles / instructions\n")
    assert "no branch is predicted" in none[6]
    assert all(len(line) <= 90 for text in texts for line in text.split("\n"))


# Settings... --------------------------------------------------------------------------------

def test_the_settings_window_has_three_groups_and_greys_what_does_not_apply(app):
    window = opened(app)
    window.open_settings()
    settings = window.settings_window
    assert isinstance(settings, SettingsWindow) and settings.window.title() == settings.TITLE
    enabled = lambda name: all(widget.instate(["!disabled"])  # noqa: E731
                               for widget in settings.parts[name])
    assert enabled("same_cycle") and not enabled("static_taken") and not enabled("bits")
    settings.variables["forwarding"].set(1)
    settings._grey()
    assert not enabled("same_cycle")
    settings.variables["prediction"].set(DYNAMIC)
    settings._grey()
    assert enabled("bits") and enabled("first_state_1") and not enabled("first_state_2")
    assert settings.one_state.instate(["!disabled"])
    settings.variables["bits"].set(2)
    settings._grey()
    assert enabled("first_state_2") and not enabled("first_state_1")
    window.open_settings()
    assert window.settings_window is settings          # once
    settings.reset_button.invoke()
    assert settings.settings() == Settings()


def test_confirm_settings_works_the_numbers_out_again(app, tmp_path):
    loaded(app, tmp_path, BENCH)
    window = connected(app)
    go_to_end(app)
    before = fields(window)
    window.open_settings()
    settings = window.settings_window
    settings.variables["forwarding"].set(1)
    settings.variables["prediction"].set(DYNAMIC)
    settings.variables["bits"].set(2)
    settings.variables["first_state_2"].set(1)
    settings.confirm_button.invoke()
    assert window.settings_window is None
    assert window.model.settings == Settings(forwarding=True, prediction=DYNAMIC, bits=2,
                                             first_state_2=1)
    assert fields(window) != before and fields(window)[6] == "1 of 2"
    assert "[State: 1]" in log_lines(window)[0]


def test_escape_leaves_the_settings_as_they_were(app):
    window = opened(app)
    window.open_settings()
    settings = window.settings_window
    settings.variables["forwarding"].set(1)
    press_key(settings.window, "<Escape>")
    assert window.settings_window is None and window.model.settings == Settings()


def test_the_settings_are_names_and_their_tips_say_what_they_mean(app):
    """Each choice has a name, not a sentence; what the name does not say is in its tip."""
    window = opened(app)
    window.open_settings()
    settings = window.settings_window
    names = {name: str(widgets[0].cget("text")) for name, widgets in settings.parts.items()}
    assert names["same_cycle"] == "WB and ID in the same cycle:"
    assert names["branch_stage"] == "Branch stage:" and names["jump_stage"] == "Jump stage:"
    for name in names.values():
        assert len(name) <= 30 and name.endswith(":") and "?" not in name, name
    assert str(settings.ladder.cget("text")).splitlines() == [
        "State 0 <--> State 1 <--> State 2 <--> State 3", "States 0, 1: not taken; 2, 3: taken"]
    tips = {name: tip.text for name, tip in settings.tips.items()}
    assert set(tips) == {"same_cycle", "branch_stage", "jump_stage", "ladder"}
    assert tips["same_cycle"].startswith("Without forwarding, may WB and ID use the registers in "
                                         "the same cycle?")
    assert tips["branch_stage"] == "The stage in which a branch (B with a condition) updates the PC"
    assert "B or BL without a condition" in tips["jump_stage"]
    assert tips["ladder"].startswith("States 0 and 1 predict not taken, states 2 and 3 taken.")
    assert all(len(line) <= 90 for tip in tips.values() for line in tip.split("\n"))
    assert settings.tips["same_cycle"].widget is settings.parts["same_cycle"][0]


# Check Dependency ---------------------------------------------------------------------------

NOP = " " * 12 + "NOP".ljust(28) + CheckWindow.MARK     # a line the checker adds
# BENCH under the first settings, as the listing shows it: a label on a line of its own, each
# instruction with its address and as it is written, and the NOPs where the checker puts them.
BENCH_LISTING = ["_start:", "0x00000000  MOV R0, #20", "0x00000004  MOV R1, #20", NOP, NOP, NOP,
                 "0x00000008  CMP R0, R1", "0x0000000c  BNE next", NOP, NOP,
                 "0x00000010  MOV R2, #30", "0x00000014  MOV R3, #30", "0x00000018  MOV R4, #30",
                 NOP, NOP, NOP, "0x0000001c  CMP R3, R4", "0x00000020  BEQ end", NOP, NOP,
                 "next:", "0x00000024  MOV R5, #8", "0x00000028  MOV R6, #8",
                 "0x0000002c  MOV R7, #8", "end:", "0x00000030  MOV R8, #8",
                 "0x00000034  LDR R9, =value", NOP, NOP, NOP, "0x00000038  LDR R10, [R9]", NOP,
                 NOP, NOP, "0x0000003c  ADD R10, R10, R8", "0x00000040  SVC #10"]


def all_widgets(widget):
    found = []
    for child in widget.winfo_children():
        found += [child] + all_widgets(child)
    return found


def labels_of(window):
    """The texts of the labels in window, in their order."""
    return [str(widget.cget("text")) for widget in all_widgets(window)
            if widget.winfo_class() == "TLabel"]


def test_check_dependency_shows_the_corrected_program_code_and_the_nops_added(app, tmp_path,
                                                                              hidden_windows):
    """As the paper's window: its title, one short line with the count over the listing, and
    no button."""
    window = opened(app)
    window.open_check()
    check = window.check_window
    assert isinstance(check, CheckWindow)
    assert check.window.title() == "Corrected Program Code"
    assert labels_of(check.window) == ["No program assembled"]
    assert check.text.get("1.0", "end-1c") == ""
    assert hidden_windows.focus is check.text           # its keys, Escape among them, reach it
    loaded(app, tmp_path, BENCH)                        # assembled while the window is open
    assert window.check_window is check
    assert labels_of(check.window) == ["NOPs added: 16"]
    assert [widget for widget in all_widgets(check.window)
            if widget.winfo_class() in ("TButton", "Button")] == []
    assert not hasattr(check, "close_button")
    listing = check.text.get("1.0", "end-1c").splitlines()
    assert listing == BENCH_LISTING                     # the listing, as it always was
    assert listing.count(NOP) == window.model.check(app.program)[2] == 3 + 2 + 3 + 2 + 3 + 3
    window.confirm(Settings(forwarding=True, prediction=DYNAMIC))
    assert labels_of(check.window) == ["NOPs added: 2"]


def test_check_dependency_counts_the_nops_of_the_walk_as_the_help_says(app, tmp_path):
    """pipeline_tour.s: NOPs added: 26 under the walk's first settings, 8 with forwarding and 2
    with prediction."""
    loaded(app, tmp_path, (ROOT / "examples" / "pipeline_tour.s").read_text(encoding="utf-8"))
    window = opened(app)
    window.open_check()
    check = window.check_window
    shown = []
    for settings in tool.TOUR_SETTINGS:
        window.confirm(settings)
        shown.append(labels_of(check.window))
    assert shown == [["NOPs added: 26"], ["NOPs added: 8"], ["NOPs added: 2"]]
    words = " ".join(tool.HELP.split())
    assert "Check Dependency says NOPs added: 26 for the first settings, 8 with forwarding and 2 " \
           "with prediction" in words


def test_escape_and_the_close_box_close_check_dependency(app, tmp_path):
    loaded(app, tmp_path, BENCH)
    window = opened(app)
    window.open_check()
    check = window.check_window
    press_key(check.text, "<Escape>")                  # from the listing, which has the focus
    assert window.check_window is None and check.window is None
    window.open_check()
    check = window.check_window
    check.window.tk.call(check.window.protocol("WM_DELETE_WINDOW"))
    assert window.check_window is None and check.window is None
    window.open_check()
    window.open_check()                                 # brought to the front: still one
    check = window.check_window
    window.close()                                      # and it closes with the tool
    assert check.window is None


# Layout ------------------------------------------------------------------------------------

def laid_out(monkeypatch):
    """Let the tool's windows be laid out although the main window is hidden: Tk lays out no
    window that belongs to a hidden one (see the Data Cache Simulator's tests)."""
    monkeypatch.setattr(tk.Wm, "transient", lambda window, master=None: "")


def measured(widget):
    """The widgets in widget that have a place and a size."""
    found = []
    for child in widget.winfo_children():
        if child.winfo_manager() and child.winfo_width() > 1:
            found += [child] + measured(child)
    return found


def overlaps(widget):
    """[(one, other)] of the children of each container that lie over each other."""
    found = []
    children = [child for child in widget.winfo_children() if child.winfo_width() > 1
                and child.winfo_manager()]
    for number, one in enumerate(children):
        a = (one.winfo_x(), one.winfo_y(), one.winfo_x() + one.winfo_width(),
             one.winfo_y() + one.winfo_height())
        for other in children[number + 1:]:
            b = (other.winfo_x(), other.winfo_y(), other.winfo_x() + other.winfo_width(),
                 other.winfo_y() + other.winfo_height())
            if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                found.append((str(one), str(other)))
    for child in children:
        found += overlaps(child)
    return found


@pytest.mark.parametrize("scale", [1.0, 1.3, 1.6, 2.25])
def test_no_text_lies_over_another_at_each_scale(make_root, tmp_path, monkeypatch, scale):
    """At the X-Ray's scales, and at 225 %."""
    laid_out(monkeypatch)
    root = make_root(scale)
    app = App(root, settings_path=tmp_path / "settings.json")
    try:
        window = opened(app)
        assert lay_out(window.window) and lay_out(window.window)
        assert len(measured(window.window)) > 30
        assert clashes(window.table.canvas) == [] and clashes(window.key.canvas) == []
        loaded(app, tmp_path, BENCH)
        window.connect_button.invoke()
        window.confirm(MISSED)
        go_to_end(app)
        assert lay_out(window.window)
        table = window.table
        stages = {stage for row in table.rows for stage in row.cells}
        assert stages == {"IF", "ID", "EX", "MEM", "WB", STALL, FLUSH}
        for top in range(0, len(table.rows), 4):
            table.yview("moveto", top / len(table.rows))
            for left in range(0, table.count, 5):
                table.xview("moveto", left / table.count)
                assert clashes(table.canvas) == [], (top, left)
        assert overlaps(window.window) == []
        assert table.canvas.winfo_width() > 1 and table.in_view()[1] >= tool.LEAST_CYCLES
        window.open_settings()
        settings = window.settings_window.window
        assert lay_out(settings) and lay_out(settings) and len(measured(settings)) > 30
        assert overlaps(settings) == []
        window.settings_window.close()
        window.open_check()
        check = window.check_window.window
        assert lay_out(check) and lay_out(check) and len(measured(check)) >= 4
        assert overlaps(check) == []
    finally:
        app.close()


def test_the_window_fits_a_small_screen(app, monkeypatch):
    monkeypatch.setattr(tool, "screen_area", lambda widget, x, y: (0, 0, 1024, 600))
    window = opened(app)
    rows, cycles = window.table.usual                   # in view at the usual size
    assert rows < tool.VISIBLE_ROWS and cycles <= tool.VISIBLE_CYCLES
    assert window.usual[1] <= 600 or rows == tool.LEAST_ROWS
    assert window.window.winfo_reqheight() == window.usual[1]
    assert window.min_size()[1] <= window.usual[1]


# Resizing ------------------------------------------------------------------------------------

@pytest.mark.parametrize("scale", [1.0, 2.25])
def test_the_window_at_its_least_usual_and_a_large_size(make_root, tmp_path, monkeypatch,
                                                        scale):
    """It opens at its usual size and shrinks to its least, five rows of the table, the line
    of numbers keeping the width; larger, the table shows more rows and cycles, the newest
    still in view; nothing clashes at any of the three sizes."""
    laid_out(monkeypatch)
    root = make_root(scale)
    app = App(root, settings_path=tmp_path / "settings.json")
    try:
        window = opened(app)
        table, seen, log = window.table, {}, window.log.master
        least, usual = window.min_size(), window.usual
        assert tuple(int(n) for n in window.window.wm_minsize()) == least
        # Only the table's rows make the difference (none on a screen too small for more).
        assert least == (usual[0], usual[1] - (table.usual[0] - tool.LEAST_ROWS) * table.row_height)
        assert (window.window.winfo_reqwidth(), window.window.winfo_reqheight()) == usual
        loaded(app, tmp_path, LOOP)
        window.connect_button.invoke()
        go_to_end(app)
        large = (usual[0] * 8 // 5, usual[1] * 8 // 5)
        for name, size in (("least", least), ("usual", usual), ("large", large)):
            part = window_layout.at_size(window.window, *size)
            assert window_layout.clashes(part) == [], name
            table.fit()
            seen[name] = (table.in_view(), log.winfo_width(), log.winfo_height())
            assert clashes(table.canvas) == [] and clashes(window.key.canvas) == []
            rows, cycles = seen[name][0]
            assert table.top + rows == len(table.rows) and table.left + cycles == table.count
        assert seen["least"][0][0] == tool.LEAST_ROWS
        assert seen["usual"][0][0] == table.usual[0] and seen["usual"][0][1] >= table.usual[1]
        assert seen["large"][0][0] > seen["usual"][0][0]
        assert seen["large"][0][1] > seen["usual"][0][1]
        assert seen["large"][1] > seen["usual"][1] and seen["large"][2] == seen["usual"][2]
    finally:
        app.close()


def test_the_table_is_drawn_again_once_its_size_has_settled(app, tmp_path, monkeypatch):
    loaded(app, tmp_path, LOOP)
    window = connected(app)
    go_to_end(app)
    table = window.table
    table.canvas.winfo_id()                             # a native window: it gets <Configure>
    table._sized = True
    draws = []
    monkeypatch.setattr(table, "draw", lambda: draws.append(table.in_view()))
    for width in range(600, 700, 10):                   # a drag of the window's edge
        table.canvas.event_generate("<Configure>", width=width, height=300, when="now")
    assert draws == []
    run_until(app, lambda: draws, limit=5.0)
    later = time.monotonic() + 0.4
    run_until(app, lambda: time.monotonic() > later)
    assert len(draws) == 1


def test_check_dependency_grows_and_shrinks_with_its_window(app, tmp_path, monkeypatch):
    laid_out(monkeypatch)
    loaded(app, tmp_path, BENCH)
    window = opened(app)
    window.open_check()
    check = window.check_window
    assert check.window.resizable() == (True, True)
    least, usual = check.least, check.usual
    assert tuple(int(n) for n in check.window.wm_minsize()) == least
    assert least[0] == usual[0] and least[1] < usual[1]
    heights = []
    for size in (least, usual, (usual[0] * 2, usual[1] * 3 // 2)):
        part = window_layout.at_size(check.window, *size)
        assert window_layout.clashes(part) == [], size
        heights.append(check.text.winfo_height())
    assert heights[0] < heights[1] < heights[2]
    # Other settings change only the count and the listing: still nothing is cut off.
    window.confirm(Settings(same_cycle=True, branch_stage=MEM, jump_stage=EX,
                            prediction=DYNAMIC, bits=2, first_state_2=3, one_state=True))
    for size in (least, usual):
        part = window_layout.at_size(check.window, *size)
        assert window_layout.clashes(part) == [], size


def test_the_settings_window_stays_a_dialog_of_its_own_size(app, monkeypatch):
    laid_out(monkeypatch)
    window = opened(app)
    window.open_settings()
    dialog = window.settings_window.window
    assert dialog.resizable() == (False, False)
    lay_out(dialog)
    part = window_layout.at_size(dialog, dialog.winfo_reqwidth(), dialog.winfo_reqheight())
    assert window_layout.clashes(part) == []


def test_the_longest_settings_fit_the_window_s_least_width(app):
    """The line of the settings never needs more than the line of numbers' width."""
    window = opened(app)
    summary = window.summary
    longest = Settings(same_cycle=True, branch_stage=MEM, jump_stage=EX, prediction=DYNAMIC,
                       bits=2, first_state_2=3, one_state=True)
    summary.configure(text="Settings: " + longest.summary()
                      + " (the numbers count from instruction 1,000,001)")
    summary.update_idletasks()
    assert summary.winfo_reqwidth() <= window.min_size()[0]


# The mouse on the table ----------------------------------------------------------------------

def test_the_mouse_wheel_scrolls_the_rows_and_with_shift_the_cycles(app, tmp_path):
    loaded(app, tmp_path, LOOP)
    window = connected(app)
    go_to_end(app)
    table = window.table
    top, left = table.top, table.left
    assert table._wheel(SimpleNamespace(delta=120)) == "break"        # one notch up
    assert (table.top, table.left) == (top - tool.WHEEL, left)
    table._wheel(SimpleNamespace(delta=-240))                          # two notches down
    assert table.top == top                                            # no further than the end
    table._wheel(SimpleNamespace(delta=120), sideways=True)
    assert (table.top, table.left) == (top, left - tool.WHEEL)


def test_resting_on_a_stall_cell_shows_its_tip(app, tmp_path):
    loaded(app, tmp_path, BENCH)
    window = connected(app)
    go_to_end(app)
    table = window.table
    table.yview("moveto", 0)
    table.xview("moveto", 0)
    index = next(number for number, row in enumerate(table.rows) if row.text == "CMP R0, R1")
    cycle = table.rows[index].fetched + 1               # its first cell waiting in ID
    left, top, right, bottom = table.canvas.bbox(table.canvas.find_withtag(
        f"cell:{index}.{cycle}")[0])
    event = SimpleNamespace(x=(left + right) // 2, y=(top + bottom) // 2, x_root=0, y_root=0)
    table._moved(event)
    cell, job, shown = table._tip
    assert cell == (index, cycle) and job is not None and shown is None
    table._show_tip(cell, table.tip(cell), 0, 0)
    label = table._tip[2].winfo_children()[0]
    assert label.cget("text") == "waits for R1 from MOV R1, #20 at 0x00000004"
    table._moved(SimpleNamespace(x=1, y=1, x_root=0, y_root=0))       # the heading: no tip
    assert table._tip is None


# The help ------------------------------------------------------------------------------------

HEADINGS = ["What the window shows", "The settings", "Check Dependency",
            "How ARES differs from the tool it follows, and why", "A walk through pipeline_tour.s",
            "How much of the run the tool keeps", "Backstep, Reset and Assemble"]


def test_the_help_says_what_the_tool_shows_and_what_ares_does_differently():
    words = " ".join(tool.HELP.split())
    for phrase in ("ARES says ID where the tool it follows says DEC", "in the Registers pane",
                   "up to 1,000,000", "waits for R3 from LDR R3, [R1] at 0x00000014",
                   "Reset Default Settings", "Confirm Settings", "One state for all branches",
                   "the last 500 rows", "the last 1,000 lines", *tool.TOUR,
                   "ARM X-Ray shows one instruction going through a datapath that does "
                   "everything in one clock cycle", "with several instructions inside at once",
                   "the program's results never differ", "MOV R0, #20, not MOV R0, #0x14",
                   "Rest the mouse on an instruction in the table to see its Basic form",
                   "Backstep takes the instruction it undoes out again",
                   "Settings > Enable Backstep While Running", "Reset (F12) and Assemble empty",
                   "the table shows more rows and more cycles", credits.PIPELINE_ORIGIN,
                   "Check Dependency opens Corrected Program Code", "NOPs added: 26",
                   "No program assembled", "Escape or its close box closes it",
                   "WB and ID in the same cycle (No at first)", "Branch stage, the stage in which "
                   "a branch updates the PC", "Jump stage, the stage in which a jump does"):
        assert phrase in words, phrase
    for gone in ("May WB and ID use", "how many it added", "shows 26 NOPs"):
        assert gone not in words, gone
    assert words.endswith(credits.PIPELINE_ORIGIN)
    page = helptext.tool_page(tool.HELP)
    assert [block.text for block in page if block.kind == helptext.HEADING] == HEADINGS
