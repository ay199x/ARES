# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The look of the ARM X-Ray (ares.gui.tools.xray_look): colours that follow the data, the fills
of the blocks, values that light and stay readable, the green of what an instruction changes, no
bit numbers on the wires and no key, what it did beside the table, the strip in the Pipeline
Simulator's colours, and a contrast of at least 3 to 1 for every text and line on what it lies
on."""

import re
from pathlib import Path

import pytest
from test_gui_run import loaded
from test_gui_xray import (HALFWORDS, HIGH, LARGEST, MIXED, MULTIPLE, MULTIPLY, PROGRAM,
                           SHIFTS, WRITE_BACK, at, connected, resting, sentence, steps, text_of,
                           wire_colour)
from test_xray import stepped, sweep_sources
from xray_layout import clashes, low_contrasts

from ares import xray, xray_film
from ares.assembler import assemble
from ares.gui.registers import CHANGED
from ares.gui.tools import pipeline
from ares.gui.tools import xray as tool
from ares.gui.tools import xray_look as look
from ares.gui.tools import xray_picture as picture
from ares.machine import Machine
from ares.program import Program
from ares.xray_film import MUX_OUTPUTS, MUXES

PROGRAMS = {"largest": LARGEST, "mixed": MIXED, "multiply": MULTIPLY, "shifts": SHIFTS,
            "halfwords": HALFWORDS, "multiple": MULTIPLE, "write_back": WRITE_BACK}
COUNTS = {"largest": 14, "shifts": 23, "halfwords": 18}    # instructions to step; else 13


def films_of(path, folder, limit=3000):
    """The film of each instruction of the program at path, each pass of an LDM, STM, PUSH or POP
    on its own."""
    result = assemble(Path(path).read_text(), folder)
    if not result.ok:
        return
    machine = Machine(Program(result.elf_path), base_dir=folder)
    try:
        for trace in stepped(machine, limit=limit):
            film = xray_film.film(trace)
            yield from film.passes or (film,)
    finally:
        machine.close()


@pytest.fixture(scope="module")
def all_films(tmp_path_factory):
    """Every film of the programs of the tests and the examples."""
    found = []
    for path in sweep_sources():
        found += [film for film in films_of(path, tmp_path_factory.mktemp("look"))
                  if film.steps]
    return found


def test_a_wire_after_a_multiplexer_has_the_colour_of_the_input_taken(all_films):
    """For each multiplexer and each of its inputs, in some instruction that takes it: the
    output's colour is the colour of the input taken, as the film's decision marks it."""
    seen = set()
    for film in all_films:
        colours = look.net_colours(film.trace)
        moved = set(film.used())
        for step in film.steps:
            for decision in step.decisions:
                output = MUX_OUTPUTS[decision.mux]
                taken = MUXES[decision.mux][1][decision.taken]
                if output not in moved:
                    continue
                assert colours[output] == colours[taken], (film.trace.text, decision)
                seen.add((decision.mux, decision.taken))
    every = {(mux, number) for mux, (_, inputs) in MUXES.items() for number in range(len(inputs))}
    assert every - seen == set()


def test_a_value_keeps_the_colour_of_the_field_it_comes_from(all_films):
    """Rn's number, the value read for it and SrcA; the second register, its value, the shifter's
    output and the data stored; the immediate and ExtImm; Rd and A3: one colour each, the
    field's. A register read as R15 is PCPlus8: the PC's colour."""
    checked = 0
    for film in all_films:
        trace, colours = film.trace, look.net_colours(film.trace)
        moved = set(film.used())
        values = trace.values
        if "RA1" in moved:
            assert colours["SrcA"] == (look.VALUES["pc"] if values["RA1"] == 15
                                       else colours["RA1"])
        if "RD2" in moved:
            assert colours["RD2"] == (look.VALUES["pc"] if values["RA2"] == 15
                                      else colours["RA2"]) == colours["Shifted"]
        if "ExtImm" in moved and trace.signals["ImmSrc"] != "011":
            assert colours["ExtImm"] == colours["Imm"]
        if "Rn" in moved and "RA1" in moved and values["RA1"] == trace.word >> 16 & 0xF \
                and look.taken_inputs(trace)["RA1Mux"] == 0:
            assert colours["RA1"] == colours["Rn"] == look.VALUES["rn"]
            checked += 1
        if "A3" in moved and look.taken_inputs(trace)["A3Mux"] == 0:
            assert colours["A3"] == colours["Rd"] == look.VALUES["rd"]
    assert checked > 100


def test_new_values_have_colours_of_their_own(all_films):
    for film in all_films[:50]:
        colours = look.net_colours(film.trace)
        assert colours["PC"] == colours["PCPlus4"] == colours["PCPlus8"] == look.VALUES["pc"]
        assert colours["ALUResult"] == look.VALUES["alu"]
        assert colours["ReadData"] == look.VALUES["memory"]
    assert len({look.VALUES[kind] for kind in ("pc", "alu", "memory")}) == 3


def test_the_strip_shares_the_pipeline_simulators_colours():
    assert [look.STAGES[part] for part in xray_film.PARTS[:5]] == \
        [pipeline.COLOURS[stage] for stage in ("IF", "ID", "EX", "MEM", "WB")]
    assert look.STAGES[xray_film.NEXT_PC] not in pipeline.COLOURS.values()
    assert look.CHANGED == CHANGED


def test_every_colour_keeps_3_to_1_on_the_fills_it_lies_on():
    fills = list(look.FILLS.values()) + [look.WHITE]
    for colour in set(look.VALUES.values()) | {look.INK, look.DIM, look.ON, look.OFF,
                                               look.MARK}:
        for fill in fills:
            assert look.contrast(colour, fill) >= 3, (colour, fill)
    for colour in set(look.VALUES.values()) | {look.ON, look.OFF}:
        assert look.contrast(colour, look.WHITE) >= 4.5, colour     # white letters on its band
        fill, text = look.band(colour)
        assert look.contrast(text, fill) >= 4.5, colour
        for changed in (False, True):
            fill, text = look.rest(colour, changed)
            assert look.contrast(text, fill) >= 4.5, colour
            assert look.contrast(colour, fill) >= 3, colour         # its outline
    for fill in (look.WHITE, look.UNUSED_FILL):                     # gray only on these
        assert look.contrast(look.IDLE, fill) >= 3


def test_the_fills_of_a_block():
    assert look.fill_of("idle", used=False) == look.fill_of("done", used=False) == \
        look.UNUSED_FILL
    assert look.fill_of("idle") == look.WAITING_FILL
    assert look.fill_of("working") == look.WORKING_FILL
    assert look.fill_of("done") == look.DONE_FILL
    assert len(set(look.FILLS.values())) == 4


# The window ----------------------------------------------------------------------------------

def every_third(film):
    return film.steps[::3]


def busiest(film):
    """The step of film in which the most values travel."""
    return [max(film.steps, key=lambda step: len(step.moves))]


def stepped_pictures(app, tmp_path, source, count, moments=None, finished=True):
    """Step source count times in a connected tool; yields the window first with nothing run,
    then for each instruction at the middle of the steps moments(film) gives, if any, and
    finished (with finished)."""
    loaded(app, tmp_path, source)
    window = connected(app)
    yield window                                # nothing has run: every block waits
    for _ in range(count):
        app.run("step")
        if app.runner.state.name in ("WAITING", "FINISHED"):
            return
        film = window.film
        if moments is not None and film.steps:
            for step in moments(film):
                window.test_clock.now = window.player.start + step.start + step.duration / 2
                window._tick()
                yield window
        window.skip()
        if finished:
            yield window


def fill_of(window, block):
    return window.canvas.itemcget(window.picture.blocks[block], "fill")


def where(window):
    return text_of(window, window.view_text), sentence(window)


@pytest.mark.parametrize("name", list(PROGRAMS))
def test_every_text_and_line_keeps_3_to_1_on_what_it_lies_on(app, tmp_path, name):
    """On white, on the fills of the blocks, on the strip and the table and on the bands and
    tints of the values: every text, line, dot and outline, at still moments of the films and
    at their ends."""
    seen = 0
    for window in stepped_pictures(app, tmp_path, PROGRAMS[name], COUNTS.get(name, 13),
                                   every_third):
        assert low_contrasts(window.canvas) == [], where(window)
        seen += 1
    assert seen > 30


@pytest.mark.parametrize("name", list(PROGRAMS))
def test_nothing_lies_over_anything_while_the_values_travel(app, tmp_path, name):
    """The layout checker at a still moment of each instruction's film, where the most values
    travel, for every kind (the finished pictures have their own tests); a value on its way may
    pass over anything."""
    seen = 0
    for window in stepped_pictures(app, tmp_path, PROGRAMS[name], COUNTS.get(name, 13), busiest,
                                   finished=False):
        moving = lambda item: "moving" in window.canvas.gettags(item)  # noqa: E731
        assert clashes(window.canvas, ignore=moving) == [], where(window)
        seen += 1
    assert seen > 10


def test_an_instruction_outside_the_datapath_stays_pale_and_keeps_3_to_1(app, tmp_path):
    loaded(app, tmp_path, PROGRAM)
    window = connected(app)
    steps(app, 8)                               # UMULL: outside the datapath
    assert window.film.steps == ()
    assert {fill_of(window, block) for block in window.picture.blocks} == {look.UNUSED_FILL}
    assert low_contrasts(window.canvas) == []


@pytest.mark.parametrize("name", ["mixed", "shifts", "halfwords", "multiple", "write_back"])
def test_the_table_and_the_picture_give_a_field_one_colour(app, tmp_path, name):
    """The table is the key: each field's cells have the colour of the wire that carries it on the
    picture; and a wire after a multiplexer has the colour of the input taken."""
    fields = muxes = 0
    for window in stepped_pictures(app, tmp_path, PROGRAMS[name], COUNTS.get(name, 13)):
        if window.film is None or not window.film.steps:
            continue
        shown = window._pass_shown()[1]
        used = set(shown.used())
        for cell in window.cells:
            if cell.kind == "constant":
                continue
            texts = {window.canvas.itemcget(item, "fill")
                     for item in [cell.label] * (cell.label is not None) + list(cell.digits)}
            for net, (high, low) in tool.WORD_NETS.items():
                if net in used and high >= cell.high and cell.low >= low \
                        and xray_film.KINDS[net] == cell.kind:
                    assert wire_colour(window, net) == texts, (cell, net)
                    fields += 1
        for step in shown.steps:
            for decision in step.decisions:
                output = MUX_OUTPUTS[decision.mux]
                taken = MUXES[decision.mux][1][decision.taken]
                if wire_colour(window, output) and wire_colour(window, taken):
                    assert wire_colour(window, output) == wire_colour(window, taken), decision
                    muxes += 1
    assert fields > 20 and muxes > 20


def test_the_blocks_wait_light_up_and_keep_a_tint(app, tmp_path):
    """No instruction: every block waits in the calm blue. In a film a block the instruction does
    not use stays pale; one it uses waits until its step, lights while it works and keeps a
    lighter tint once it is done."""
    loaded(app, tmp_path, LARGEST)
    window = connected(app)
    blocks = window.picture.blocks
    assert {fill_of(window, block) for block in blocks} == {look.WAITING_FILL}
    steps(app, 6)                               # LDR R3, [R1]
    film = window.film
    used = picture.used_blocks(film)
    assert "Shifter" not in used and "ALU" in used
    for number, step in enumerate(film.steps):
        window.test_clock.now = window.player.start + step.start + step.duration / 2
        window._tick()
        working = {block for block, _ in step.lights} | {d.mux for d in step.decisions}
        before = picture.used_blocks(xray_film.Film(None, film.steps[:number], 0))
        for block in blocks:
            expected = (look.WORKING_FILL if block in working else look.DONE_FILL
                        if block in before else look.WAITING_FILL if block in used
                        else look.UNUSED_FILL)
            assert fill_of(window, block) == expected, (step.sentence, block)
    window.skip()
    for block in blocks:
        assert fill_of(window, block) == (look.DONE_FILL if block in used else look.UNUSED_FILL)
    titles = window.picture.titles
    assert window.canvas.itemcget(titles["Shifter"][0], "fill") == look.IDLE
    assert window.canvas.itemcget(titles["ALU"][0], "fill") == look.INK


def label_look(window, key):
    """(fill, text colour) of the value resting at key, (net, branch); None when none rests."""
    box, text = window.picture.rests[key]
    canvas = window.canvas
    if canvas.itemcget(box, "state") == "hidden":
        return None
    return canvas.itemcget(box, "fill"), canvas.itemcget(text, "fill")


def test_a_value_lights_on_a_band_of_its_colour_and_then_stays_readable(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    window = connected(app)
    steps(app, 6)                               # LDR R3, [R1]
    film = window.film
    colour = look.net_colours(film.trace)["SrcA"]
    number = next(n for n, step in enumerate(film.steps)
                  if any(move.net == "SrcA" for move in step.moves))
    step = film.steps[number]
    window.test_clock.now = window.player.start + step.start + step.duration / 2
    window._tick()
    travelling = [window.picture.labels[("SrcA", index)] for index in range(2)]
    shown = [(window.canvas.itemcget(box, "fill"), window.canvas.itemcget(text, "fill"))
             for box, text in travelling if window.canvas.itemcget(box, "state") == "normal"]
    assert shown and set(shown) == {(colour, look.WHITE)}     # it travels on a band
    for later, lit in ((number, True), (number + 1, True), (number + 2, False)):
        step = film.steps[later]
        window.test_clock.now = window.player.start + step.start + step.duration * 0.999
        window._tick()
        expected = (colour, look.WHITE) if lit else (look.tint(colour), look.INK)
        assert label_look(window, ("SrcA", "alu")) == expected, later
    window.skip()
    assert label_look(window, ("SrcA", "alu")) == (look.tint(colour), look.INK)


@pytest.mark.parametrize("source, count, written, kept", [
    (MIXED, 5, [("WD3", "regfile"), ("PC'", "pcreg")], [("ALUFlags", "control"),
                                                         ("A3", "regfile")]),
    (MIXED, 6, [("WriteData", "dmem")], [("WD3", "regfile")]),
    (MIXED, 10, [("WD3", "regfile"), ("ALUFlags", "control")], []),
    (WRITE_BACK, 5, [("WD3", "regfile"), ("ALUResult", "wd5")], [("ALUResult", "result")]),
    (PROGRAM, 5, [("PC'", "pcreg")], [("WD3", "regfile")]),
], ids=["add", "store", "ands", "post-indexed load", "condition failed"])
def test_what_the_instruction_changes_rests_on_the_registers_green(app, tmp_path, source, count,
                                                                    written, kept):
    """The register written, the base written, the memory word, the flags and the PC rest on the
    green of the Registers pane's changed rows; a write the condition closed does not."""
    loaded(app, tmp_path, source)
    window = connected(app)
    steps(app, count)
    window.skip()
    for key in written:
        assert label_look(window, key) == (CHANGED, look.INK), key
    for key in kept:
        assert label_look(window, key) is None or label_look(window, key)[0] != CHANGED, key


def test_the_wires_carry_no_bit_numbers_and_keep_their_widths_and_arrows(app, tmp_path):
    loaded(app, tmp_path, MIXED)
    window = connected(app)
    steps(app, 5)
    window.skip()
    canvas, k = window.canvas, window.k
    top, bottom = picture.ORIGIN[1] * k, (picture.ORIGIN[1] + picture.SIZE[1]) * k
    texts = [canvas.itemcget(item, "text") for item in canvas.find_all()
             if canvas.type(item) == "text" and canvas.itemcget(item, "text")
             and top <= canvas.bbox(item)[1] <= bottom]
    assert texts and not [text for text in texts if re.fullmatch(r"\d+:\d+", text)]
    widths = {canvas.itemcget(item, "text") for item in canvas.find_withtag("slash")
              if canvas.type(item) == "text"}
    assert {"32", "4"} <= widths and canvas.find_withtag("mid")
    for net, bits in (("Cond", "31:28"), ("Op", "27:26"), ("Funct", "25:20"), ("Rn", "19:16"),
                      ("Rd", "15:12"), ("Rm", "3:0"), ("Imm", "23:0")):
        assert bits in window.tip_text(f"wire:{net}"), net         # they stay in the tips
    assert tool.SIGNAL_LOOK in window.tip_text("wire:RegWrite")    # red, gray, dashed X


def test_no_key_and_what_it_did_stands_beside_the_table(app, tmp_path):
    """The key and the right column are gone: the picture takes the full width, and what the
    instruction did stands beside the table, in two columns."""
    loaded(app, tmp_path, MIXED)
    window = connected(app)
    steps(app, 5)
    window.skip()
    canvas = window.canvas
    texts = [canvas.itemcget(item, "text") for item in canvas.find_all()
             if canvas.type(item) == "text"]
    assert "Key" not in texts and tool.CANVAS[0] <= picture.SIZE[0] + 10
    table = [canvas.bbox(item) for item in canvas.find_withtag("cells")]
    hint = canvas.bbox(window.hint)
    for item in window.panels:
        left, top, right, bottom = canvas.bbox(item)
        assert left >= max(box[2] for box in table) and top >= hint[3] - 1
        assert right <= float(canvas.cget("width")) and bottom <= float(canvas.cget("height"))
    assert "What it did:" in canvas.itemcget(window.panels[0], "text")
    assert canvas.itemcget(window.panels[1], "text").startswith("  Flags NZCV")


@pytest.mark.parametrize("count", [0, 5])
def test_what_it_shows_and_the_click_line_stand_bold_at_the_bottom_right(app, tmp_path, count):
    """Nothing above the picture but the large heading. Under the picture, at the right of the
    strip and the table: what the tool shows ("Just executed" with the address and the
    instruction; "Nothing has run yet"), and under it "To see inside a block, click it.", both
    in the bold font of the picture's names; what the instruction did follows them."""
    loaded(app, tmp_path, MIXED)
    window = connected(app)
    steps(app, count)
    window.skip()
    canvas, k = window.canvas, window.k
    above = [item for item in canvas.find_all() if canvas.type(item) == "text"
             and canvas.itemcget(item, "text") and canvas.bbox(item)[1] < picture.ORIGIN[1] * k]
    assert above == ([window.heading_item] if count else [])  # no instruction: no heading
    bold = str(window.fonts["bold"])
    assert canvas.itemcget(window.view_heading, "font") == bold
    assert canvas.itemcget(window.hint, "font") == bold
    assert str(canvas.itemcget(window.view_text, "font")) == str(window.fonts["code_bold"])
    assert canvas.itemcget(window.hint, "text") == tool.CLICK_HINT
    if count:
        assert canvas.itemcget(window.view_heading, "text") == "Just executed"
        assert text_of(window, window.view_text) == "0x00000010  ADD R4, R0, R3, LSL #1"
    else:
        assert canvas.itemcget(window.view_heading, "text") == "Nothing has run yet"
    datapath = (picture.ORIGIN[1] + picture.SIZE[1]) * k
    strip = max(canvas.bbox(box)[2] for box, _ in window.strip)
    table = max(canvas.bbox(item)[2] for item in canvas.find_withtag("cells"))
    shows, hint = canvas.bbox(window.view_heading), canvas.bbox(window.hint)
    assert datapath <= shows[1] and max(strip, table) <= shows[0]
    if count:                                   # the address and instruction, on its line
        address = canvas.bbox(window.view_text)
        assert shows[2] < address[0] and abs(shows[1] + shows[3] - address[1] - address[3]) <= 2
        assert address[2] <= float(canvas.cget("width"))
    assert hint[0] == shows[0] and hint[1] >= shows[3] - 0.25 * (shows[3] - shows[1])
    panel = [canvas.bbox(item) for item in window.panels]
    assert min(box[1] for box in panel) >= hint[3] - 0.25 * (hint[3] - hint[1])
    assert clashes(canvas) == [] and low_contrasts(canvas) == []


FAILS = """        .global _start
_start: LDR     R1, =0x50000000
        LDR     R0, [R1]
"""


def test_a_runtime_error_stands_whole_beside_the_table(app, tmp_path):
    """The heading at the top left may be cut short beside the large heading; the panel has the
    error whole, across its two columns."""
    loaded(app, tmp_path, FAILS)
    window = connected(app)
    steps(app, 2)
    view = window.model.view
    assert view.kind == xray.FAILED and view.trace.text == "LDR R0, [R1]"
    window.skip()
    assert window.panel_text().split() == view.heading.split()
    canvas = window.canvas
    right = canvas.bbox(window.panels[0])[2]
    assert right <= float(canvas.cget("width"))
    assert clashes(canvas) == [] and low_contrasts(canvas) == []


def test_a_change_too_wide_for_its_column_breaks_before_its_new_value(app, tmp_path):
    """An 8-byte memory word (VSTR of a D register, for one) is wider than the left column: it
    breaks before its new value and takes two of the column's lines."""
    loaded(app, tmp_path, MIXED)
    window = connected(app)
    steps(app, 6)                               # STR R4, [R1, R2]
    window.skip()
    view = window.model.view
    wide = "Memory 0x00003ff8: 0x0000000000000000 -> 0x0000000200000001"
    window.model.view = xray.View(view.kind, view.heading, view.trace, (wide,), view.ended,
                                  view.written)
    window._fill_panel()
    lines = window.panel_text().splitlines()
    assert lines[:3] == ["What it did:", "  Memory 0x00003FF8: 0x0000000000000000 ->",
                         "      0x0000000200000001"]
    canvas = window.canvas
    assert canvas.bbox(window.panels[0])[2] < canvas.bbox(window.panels[1])[0]
    many = (wide,) * 2 + ("R1 0x00000000 -> 0x00000001",) * 3
    window.model.view = xray.View(view.kind, view.heading, view.trace, many, view.ended,
                                  view.written)
    window._fill_panel()
    lines = canvas.itemcget(window.panels[0], "text").splitlines()
    assert lines == ["What it did:", "  Memory 0x00003FF8: 0x0000000000000000 ->",
                     "      0x0000000200000001", "  and 3 more"]
    right = canvas.itemcget(window.panels[1], "text").splitlines()
    assert right[0] == "  R1 0x00000000 -> 0x00000001" and right[-2].startswith("Next: PC = ")


def test_a_push_of_four_registers_shows_sp_and_counts_the_words_it_cannot_list(app,
                                                                               tmp_path):
    """SP and the four words of the tour's PUSH {R4, R6, R7, LR}: the next instruction keeps its
    two lines, so SP stands in the right column above the flags, two words in the left and the
    other two are counted."""
    loaded(app, tmp_path, """        .global _start
_start: LDR     SP, =0x4000
        PUSH    {R4, R6, R7, LR}
        SVC     #10
""")
    window = connected(app)
    steps(app, 2)
    window.skip()
    left = window.canvas.itemcget(window.panels[0], "text").splitlines()
    right = window.canvas.itemcget(window.panels[1], "text").splitlines()
    assert left[0] == "What it did:" and left[-1] == "  and 2 more"
    assert [line for line in left if "Memory 0x00003F" in line] == [
        "  Memory 0x00003FF0: 0x00000000 -> 0x00000000",
        "  Memory 0x00003FF4: 0x00000000 -> 0x00000000"]
    assert right == ["  SP 0x00004000 -> 0x00003FF0", "  Flags NZCV 0000 -> 0000",
                     "Next: PC = 0x00000008,", "      SVC #10"]
    assert len(left) <= tool.PANEL_LINES
    canvas = window.canvas
    assert canvas.bbox(window.panels[0])[2] < canvas.bbox(window.panels[1])[0]


def test_a_change_taken_back_to_count_the_others_goes_whole_also_when_broken_in_two(app,
                                                                                  tmp_path):
    """With both columns full and a change that fits nowhere, the last change shown makes room
    for the line that counts them: both its lines when it was broken over two."""
    loaded(app, tmp_path, """        .global _start
_start: MOV     R0, #1
        SVC     #10
""")
    window = connected(app)
    words = [f"  Memory 0x{0x100 + 4 * n:08X}: 0x00000000 -> 0x{n:08X}" for n in range(5)]
    left, right = window._placed(words, 3, 2)
    assert left == words[:3]
    assert right == ["  and 2 more"]
    left, right = window._placed(words, 3, 3)   # room for the fourth, broken in two
    assert left == words[:3]
    assert right == ["  Memory 0x0000010C:", "    0x00000000 -> 0x00000003", "  and 1 more"]


def test_the_heading_stays_above_the_values_in_flight(app, tmp_path):
    """A PUSH's register list travels to the control unit just under the large heading: the
    heading stays whole above it (what the tool shows stands under the picture now)."""
    loaded(app, tmp_path, """        .global _start
_start: LDR     SP, =0x4000
        PUSH    {R4, LR}
        SVC     #10
""")
    window = connected(app)
    steps(app, 2)
    film = window.film
    first = film.passes[0]
    step = next(step for step in first.steps if "List" in {move.net for move in step.moves})
    window.stop_film()
    window.player.play(film, first.offset + step.start + 0.5 * step.duration)
    canvas = window.canvas
    order = canvas.find_all()                   # from the bottom up
    moving = [order.index(item) for item in canvas.find_withtag("moving")]
    assert moving
    list_value = [item for item in canvas.find_withtag("moving")
                  if canvas.type(item) == "text" and canvas.itemcget(item, "text").startswith("0100")]
    assert list_value                           # the register list is on its way
    bottom = (picture.ORIGIN[1] + picture.SIZE[1]) * window.k
    for item in (window.view_heading, window.view_text, window.hint):
        assert canvas.bbox(item)[1] >= bottom
    assert order.index(window.heading_item) > max(moving)



# The usual zoom at 100 %, and the zooms of a window maximized on 1920 x 1080 and on 3840 x 2160
# at 225 % (test_gui_xray.MAXIMIZED_ZOOMS, MAXIMIZED_HIGH); 1.0 is the least at both scales.
SIZES = [(None, 1.0), (None, 1.35), (None, 1.61), (HIGH, 1.0), (HIGH, 1.25), (HIGH, 1.44)]


@pytest.mark.parametrize("scaling, zoom", SIZES,
                         ids=[f"{'225' if s else '100'}%-{z}" for s, z in SIZES])
def test_under_the_picture_nothing_clashes_and_all_keeps_3_to_1_at_every_size(app, tmp_path,
                                                                           scaling, zoom):
    """The strip, the table, what the tool shows, the line on the blocks and the panel: with
    nothing run, after a load, a store, a PUSH whose changes are counted and an instruction
    outside the datapath with its note, at the least size, the usual one and maximized, at
    100 % and at 225 %."""
    before = float(app.root.tk.call("tk", "scaling"))
    if scaling is not None:
        app.root.tk.call("tk", "scaling", scaling)
    try:
        loaded(app, tmp_path, """        .global _start
_start: LDR     SP, =0x4000
        LDR     R1, =table
        STR     R1, [R1, #4]
        PUSH    {R0-R7}
        UMULL   R4, R5, R1, R1
        SVC     #10
table:  .word   1, 2
""")
        window = connected(app)
        window._make_canvas(zoom)
        window.show()
        canvas = window.canvas
        bottom = (picture.ORIGIN[1] + picture.SIZE[1]) * window.k
        for count in range(6):
            if count:
                app.run("step")
                window.skip()
            under = [item for item in canvas.find_all() if canvas.bbox(item)
                     and canvas.bbox(item)[1] >= bottom]
            assert under, count
            assert clashes(canvas) == [], (count, where(window))
            assert low_contrasts(canvas) == [], (count, where(window))
            width, height = float(canvas.cget("width")), float(canvas.cget("height"))
            for item in under:
                left, top, right, low = canvas.bbox(item)
                assert right <= width + 1 and low <= height + 1, canvas.itemcget(item, "text")
            assert (" more" in window.panel_text()) == (count == 4)     # the PUSH: counted
            assert bool(text_of(window, window.note_item)) == (count == 5)   # UMULL: a note
    finally:
        app.root.tk.call("tk", "scaling", before)
