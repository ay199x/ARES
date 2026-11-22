# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The look of the ARM X-Ray's windows inside its blocks, as the picture's (ares.gui.tools.
xray_look): parts pale when the instruction does not use them, waiting in the calm blue, lit
while they work and with a lighter tint once done; values in the colours of their nets on the
picture; what the instruction writes on the green of the Registers pane's changed rows from the
clock edge on; and every text, line and outline with a contrast of at least 3 to 1 on what it
lies on, at every moment where a window's picture changes."""

import pytest
from test_gui_run import loaded
from test_gui_xray import (HALFWORDS, HALFWORDS_INSIDE, LARGEST, MULTIPLE, SHIFTS, WRITE_BACK,
                           connected, steps)
from test_gui_xray_inside import BLOCKS, EXAMPLES, OUTSIDE

from ares import xray
from ares.gui.tools import xray_look as look
from ares.gui.tools.xray_inside import (CHANGED, DONE_FILL, FILLS, IDLE, UNUSED_FILL, WAITING_FILL,
                                        WORKING_FILL, bit_text, steps_of, works_in)
from ares.gui.tools.xray_inside_control import FLAGS_BOX, control_steps
from ares.xray_film import MUXES, hex32

MEMORY = """\
        .data
cell:   .word   0x11223344, 0x55667788
        .global _start
        .text
_start: LDR     R1, =cell
        MOV     R2, #0x9A
        CMP     R2, R2
        STR     R2, [R1]            @ 4: a store
        LDRB    R5, [R1, #6]        @ 5: a load
        STRNE   R2, [R1]            @ 6: a store whose condition fails
        ADDS    R3, R2, #1          @ 7: the flags written
        SUB     R4, R3, #1          @ 8: the flags kept
        MOV     PC, PC              @ 9: a write to R15
        SVC     #10
"""
# Where each window's picture changes within one of its block's steps (the shares of the step
# at which its parts light, its values leave and its writes happen): a share on each side.
SHARES = {"ALU": (0.15, 0.45, 0.7, 0.95), "IMem": (0.15, 0.5, 0.8, 0.95),
          "DMem": (0.15, 0.5, 0.8, 0.95), "RegFile": (0.15, 0.45, 0.75, 0.95),
          "Control": (0.1, 0.4, 0.8), "Extend": (0.3, 0.8), "Shifter": (0.25, 0.75)}
LEAST = 3                               # the least contrast of a text, line or outline


def hex_of(canvas, colour):
    """colour as "#RRGGBB", whatever Tk calls it."""
    red, green, blue = canvas.winfo_rgb(colour)
    return f"#{red >> 8:02X}{green >> 8:02X}{blue >> 8:02X}"


def holds(kind, coords, x, y):
    """True when the rectangle or polygon of coords holds the point (x, y)."""
    if kind == "rectangle":
        left, top, right, bottom = coords
        return left <= x <= right and top <= y <= bottom
    points = list(zip(coords[::2], coords[1::2]))
    inside = False
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (x2 - x1) * (y - y1) / (y2 - y1):
            inside = not inside
    return inside


def faint(canvas):
    """[(what, its colour, the fill under it, the ratio)] of every visible text, line and
    outline with a contrast under LEAST on what lies under it: the topmost filled rectangle or
    polygon drawn before it that holds the point, else the canvas's background. A text is
    measured at its middle and near its two ends, a line at a quarter, half and three quarters
    of each of its segments, an outline on its own fill and at the middle of each edge."""
    background = hex_of(canvas, canvas.cget("background"))
    items = canvas.find_all()
    shown = [item for item in items if canvas.itemcget(item, "state") != "hidden"]
    filled = [(position, canvas.type(item), canvas.coords(item),
               hex_of(canvas, canvas.itemcget(item, "fill")))
              for position, item in enumerate(items)
              if item in shown and canvas.type(item) in ("rectangle", "polygon")
              and canvas.itemcget(item, "fill")]
    order = {item: position for position, item in enumerate(items)}

    def under(item, x, y):
        fill = background
        for position, kind, coords, colour in filled:
            if position >= order[item]:
                break
            if holds(kind, coords, x, y):
                fill = colour
        return fill
    found = []
    for item in shown:
        kind = canvas.type(item)
        own = None
        if kind == "text":
            what = canvas.itemcget(item, "text")
            if not what.strip():
                continue
            colour = canvas.itemcget(item, "fill")
            left, top, right, bottom = canvas.bbox(item)
            middle = (top + bottom) / 2
            points = [((left + right) / 2, middle), (left + 2, middle), (right - 2, middle)]
        elif kind == "line":
            what, colour = f"line {canvas.gettags(item)}", canvas.itemcget(item, "fill")
            coords = canvas.coords(item)
            ends = list(zip(coords[::2], coords[1::2]))
            points = [(x1 + (x2 - x1) * share, y1 + (y2 - y1) * share)
                      for (x1, y1), (x2, y2) in zip(ends, ends[1:]) for share in (0.25, 0.5, 0.75)]
        elif kind in ("rectangle", "polygon"):
            what, colour = f"outline {canvas.gettags(item)}", canvas.itemcget(item, "outline")
            coords = canvas.coords(item)
            if kind == "rectangle":
                left, top, right, bottom = coords
                coords = [left, top, right, top, right, bottom, left, bottom]
            ends = list(zip(coords[::2], coords[1::2]))
            points = [((x1 + x2) / 2, (y1 + y2) / 2)
                      for (x1, y1), (x2, y2) in zip(ends, ends[1:] + ends[:1])]
            own = canvas.itemcget(item, "fill")
        else:
            continue
        if not colour:
            continue
        colour = hex_of(canvas, colour)
        fills = [under(item, x, y) for x, y in points] + ([hex_of(canvas, own)] if own else [])
        for fill in set(fills):
            ratio = look.contrast(colour, fill)
            if ratio < LEAST:
                found.append((what, colour, fill, round(ratio, 2)))
    return found


def show(tool, moment):
    """Show the tool's film, and the windows inside the blocks with it, at moment, paused there
    (tool.skip() shows its end)."""
    tool.stop_film()
    tool.player.play(tool.film, moment)
    tool.player.pause()


def moments(film, block):
    """The moments of film at which the window inside block changes its picture: before its
    block's steps, on each side of every share where its picture changes within each of them
    (SHARES), in the middle of the other steps (between its steps), and at the end; for each
    pass of an LDM, STM, PUSH or POP."""
    found = []
    for sub in film.passes or (film,):
        own = [number for number, step in enumerate(sub.steps) if works_in(step, block)]
        found.append(sub.offset)
        for number, step in enumerate(sub.steps):
            if number in own:
                found += [sub.offset + step.start + share * step.duration
                          for share in SHARES[block]]
            elif own and own[0] < number < own[-1]:
                found.append(sub.offset + step.start + step.duration / 2)
        found.append(sub.offset + sub.seconds * 0.999)
    return found


def pictures(tool, windows):
    """(block, its window, the moment) for each window inside a block at each moment where its
    picture changes (moments()), shown, and then for every window at the end of the film, as
    a finished instruction shows it."""
    film = tool.film
    if not film.steps:                  # no instruction, or one outside the datapath: no film
        for block, window in windows.items():
            yield block, window, None
        return
    for block, window in windows.items():
        for moment in moments(film, block):
            show(tool, moment)
            yield block, window, moment
    tool.skip()
    for block, window in windows.items():
        yield block, window, film.seconds


def checked(tool, windows):
    """Every window, at every moment where its picture changes: nothing faint."""
    trace = tool.film.trace
    for block, window, moment in pictures(tool, windows):
        assert faint(window.canvas) == [], (block, trace and trace.text, moment)


CASES = {"examples": (EXAMPLES, range(1, 11)), "shifts": (SHIFTS, (5, 7, 11, 13, 14, 17, 19, 20)),
         "halfwords": (HALFWORDS, HALFWORDS_INSIDE), "passes": (MULTIPLE, (5, 8, 9, 13)),
         "write_back": (WRITE_BACK, (4, 5, 8)), "memory": (MEMORY, (4, 5, 6, 7, 8, 9)),
         "outside": (OUTSIDE, (2,))}


@pytest.mark.parametrize("case", list(CASES))
def test_every_text_line_and_outline_keeps_3_to_1_on_what_it_lies_on(app, tmp_path, case):
    """The gray of what is not in use only on white or on the pale fill, the darker gray on the
    others; values, signals and words on every fill: before, during and after each step of the
    instructions of each kind, an SVC, a failed condition, the passes of PUSH, POP, LDM and STM,
    and an instruction outside the datapath."""
    source, counts = CASES[case]
    loaded(app, tmp_path, source)
    tool = connected(app)
    windows = {block: tool.open_inside(block) for block in BLOCKS}
    done = 0
    for count in counts:
        steps(app, count - done)
        done = count
        checked(tool, windows)


def test_with_no_instruction_every_part_rests_in_the_calm_blue(app, tmp_path):
    loaded(app, tmp_path, EXAMPLES)
    tool = connected(app)
    windows = {block: tool.open_inside(block) for block in BLOCKS}
    assert tool.model.view.trace is None
    for block, window in windows.items():
        assert faint(window.canvas) == [], block
        fills = part_fills(window)
        assert fills <= {WAITING_FILL, ""}, (block, fills)
        if block not in ("Extend", "Shifter"):      # these show no parts without an instruction
            assert WAITING_FILL in fills, block


# The fills ----------------------------------------------------------------------------------

def part_fills(window):
    """The fills of the parts drawn in the window: its rectangles and polygons."""
    canvas = window.canvas
    return {canvas.itemcget(item, "fill") for item in canvas.find_all()
            if canvas.type(item) in ("rectangle", "polygon")
            and canvas.itemcget(item, "state") != "hidden"}


def tints(trace):
    """The tints of the colours of trace's values: a word read or written rests on one."""
    return {look.rest(colour)[0] for colour in look.net_colours(trace).values()}


@pytest.mark.parametrize("case", ["examples", "halfwords", "passes"])
def test_the_parts_take_only_the_pictures_fills(app, tmp_path, case):
    """Pale, calm blue, lit, a lighter tint and the green of a change, and for a word read or
    written in a memory a tint of its value's colour: no other fill, and no white part."""
    source, counts = CASES[case]
    loaded(app, tmp_path, source)
    tool = connected(app)
    windows = {block: tool.open_inside(block) for block in BLOCKS}
    done = 0
    for count in counts:
        steps(app, count - done)
        done = count
        for block, window, moment in pictures(tool, windows):
            trace = tool._context.trace
            extra = tints(trace) if block in ("IMem", "DMem") else set()
            assert part_fills(window) <= set(FILLS) | extra | {""}, (block, moment)


def fill_of_block(window, tag):
    canvas = window.canvas
    (fill,) = {canvas.itemcget(item, "fill") for item in canvas.find_withtag(tag)
               if canvas.type(item) in ("rectangle", "polygon")}
    return fill


def at_share(tool, block, share, number=0):
    """Show the film at share of block's step number (a negative share: before it)."""
    step = steps_of(tool.film, block)[number]
    show(tool, step.start + share * step.duration)


def test_a_part_waits_in_the_calm_blue_lights_while_it_works_and_keeps_a_tint(app, tmp_path):
    """The shifter for ADD R0, R1, R2: calm before its step, lit in it, tinted after; for LDR
    R3, [R1], which reads no register through RD2, pale throughout. The adder for CMP R3, R0:
    calm, lit while the units work, and still lit when the multiplexer takes its sum, the units
    it rejects turning pale."""
    loaded(app, tmp_path, EXAMPLES)
    tool = connected(app)
    shifter, alu = tool.open_inside("Shifter"), tool.open_inside("ALU")
    steps(app, 4)                                           # LDR R3, [R1]
    for moment in (0.0, tool.film.seconds / 2, tool.film.seconds):
        show(tool, moment)
        assert part_fills(shifter) == {UNUSED_FILL}
    steps(app, 2)                                           # ADD R0, R1, R2: no shift
    show(tool, 0.0)                                         # the amount multiplexer: pale
    assert part_fills(shifter) == {WAITING_FILL, UNUSED_FILL}
    at_share(tool, "Shifter", 0.5)
    assert part_fills(shifter) == {WORKING_FILL, UNUSED_FILL}
    tool.skip()
    assert part_fills(shifter) == {DONE_FILL, UNUSED_FILL}
    steps(app, 1)                                           # CMP R3, R0
    show(tool, 0.0)
    assert fill_of_block(alu, "block:Adder") == WAITING_FILL
    at_share(tool, "ALU", 0.45)
    assert fill_of_block(alu, "block:Adder") == fill_of_block(alu, "block:AND") == WORKING_FILL
    at_share(tool, "ALU", 0.7)
    assert fill_of_block(alu, "block:Adder") == WORKING_FILL
    assert fill_of_block(alu, "block:AND") == UNUSED_FILL
    tool.skip()
    assert fill_of_block(alu, "block:Adder") == fill_of_block(alu, "block:ResultMux") == DONE_FILL


# The colours of the values -----------------------------------------------------------------

def colour_of_text(window, text, tag=None):
    """The colour of the text that says text (with tag, when given)."""
    canvas = window.canvas
    found = {canvas.itemcget(item, "fill") for item in canvas.find_withtag(tag or "all")
             if canvas.type(item) == "text" and canvas.itemcget(item, "text") == text
             and canvas.itemcget(item, "state") != "hidden"}
    assert len(found) == 1, (text, found)
    return found.pop()


def taken_input(trace, mux):
    """The net of the input that mux takes for trace's instruction."""
    return MUXES[mux][1][look.taken_inputs(trace)[mux]]


@pytest.mark.parametrize("case", ["examples", "shifts", "halfwords", "write_back"])
def test_each_value_has_the_colour_of_its_net_on_the_picture(app, tmp_path, case):
    """A field's colour carried through its blocks and a multiplexer's output the colour of the
    input taken, in every window as on the picture: the ALU's operands, its result, its carry in
    and its flags; the shifter's value and amount; ExtImm; the register file's addresses, the
    values read and written; the memories' addresses, words and data; the control unit's
    fields, in the colours of the instruction table under the picture."""
    source, counts = CASES[case]
    loaded(app, tmp_path, source)
    tool = connected(app)
    windows = {block: tool.open_inside(block) for block in BLOCKS}
    done = checked_values = 0
    for count in counts:
        steps(app, count - done)
        done = count
        tool.skip()
        trace = tool.film.trace
        if not trace.signals or trace.kind in (xray.SYSTEM_CALL, xray.NO_OPERATION) or \
                trace.passes:
            continue
        colours, values, signals = look.net_colours(trace), trace.values, trace.signals
        alu, registers = windows["ALU"], windows["RegFile"]
        assert colours["SrcB"] == colours[taken_input(trace, "ALUSrcMux")]
        assert colour_of_text(alu, "SrcB", "wire:SrcB") == colours["SrcB"]
        if values["SrcA"] is not None:
            assert colour_of_text(alu, "SrcA", "wire:SrcA") == colours["SrcA"]
            assert colour_of_text(registers, hex32(values["SrcA"]), "wire:RD1") == colours["SrcA"]
            assert colour_of_text(registers, f"A1 = {values['RA1']:04b}" + (
                " (Rs)" if trace.kind == xray.MULTIPLY else ""), "wire:A1") == colours["RA1"]
        assert colour_of_text(alu, f"ALUResult = {hex32(values['ALUResult'])}",
                              "wire:ALUResult") == colours["ALUResult"]
        if signals["ALUControl"] in xray.CARRY_CODES:   # ADC, SBC, RSC: CarryIn is taken
            carry = values["CarryIn"]
            assert colour_of_text(alu, f"carry in = {carry}", "wire:CarryInAdder") == \
                colours["CarryIn"]
        if values["RD2"] is not None:
            shifter = windows["Shifter"]
            assert colour_of_text(shifter, bit_text(values["RD2"])) == colours["RD2"]
            assert colour_of_text(shifter, bit_text(values["Shifted"])) == colours["Shifted"] \
                == colours["RD2"]
            by_register = signals.get("ShiftReg") == "1"
            amount = values["RD4"] & 0xFF if by_register else trace.word >> 7 & 0x1F
            if signals["Shift"] == "1" or by_register:
                assert colour_of_text(shifter, f"amount = {amount}") == \
                    colours["RD4" if by_register else "Shamt"]
        if values["ExtImm"] is not None:
            assert colour_of_text(windows["Extend"], f"ExtImm = {hex32(values['ExtImm'])}") == \
                colours["ExtImm"] == colours["Imm"]
        if values["A3"] is not None and values["WD3"] is not None:
            assert colour_of_text(registers, f"WD3 = {hex32(values['WD3'])}", "wire:WD3") == \
                colours["WD3"] == colours[taken_input(trace, "WD3Mux")]
            assert colour_of_text(registers, f"A3 = {values['A3']:04b}", "wire:A3") == colours["A3"]
        memory = windows["DMem"]
        if signals["MemWrite"] == "1":
            assert colour_of_text(memory, hex32(values["WriteData"]), "wire:WriteData") == \
                colours["WriteData"] == colours[taken_input(trace, "StoreMux")]
        if signals["MemtoReg"] == "1" and signals["CondEx"] == "1" and \
                values["ReadData"] is not None:
            assert colour_of_text(memory, hex32(values["ReadData"]), "wire:ReadData") == \
                colours["ReadData"]
            assert colour_of_text(memory, hex32(values["Address"]), "wire:Address") == \
                colours["Address"] == colours[taken_input(trace, "AdrSrcMux")]
        imem = windows["IMem"]
        assert colour_of_text(imem, hex32(trace.pc), "wire:PC") == colours["PC"]
        assert colour_of_text(imem, hex32(trace.word), "wire:Instr") == colours["Instr"]
        control = windows["Control"]
        assert colour_of_text(control, f"Cond {trace.word >> 28:04b}") == colours["Cond"]
        for items, shown, kinds in control.in_rows:
            for item, value, kind in zip(items, shown, kinds):
                if value != "-" and kind != "control":
                    assert control.canvas.itemcget(item, "fill") == look.field_colour(kind)
        checked_values += 1
    assert checked_values >= 3


def test_a_pass_takes_passreg_in_its_colour_through_the_pass_multiplexer(app, tmp_path):
    loaded(app, tmp_path, MULTIPLE)
    tool = connected(app)
    registers = tool.open_inside("RegFile")
    steps(app, 6)                           # STMIA R8, {R4, R5}: A4 takes PassReg
    for sub in tool.film.passes:
        show(tool, sub.offset + sub.seconds * 0.999)
        colours = look.net_colours(sub.trace)
        register = sub.trace.values["PassReg"]
        assert colour_of_text(registers, f"PassReg = {register:04b}", "wire:PassReg") == \
            colours["PassReg"]
        canvas = registers.canvas
        lines = {canvas.itemcget(item, "fill") for item in canvas.find_withtag("wire:PassA4")
                 if canvas.type(item) == "line"}
        assert colours["PassReg"] in lines            # the output: the colour of PassReg


# What the instruction writes ---------------------------------------------------------------

def rows_on(window, fill):
    """The registers whose rows have fill."""
    canvas = window.canvas
    return {tag[7:] for item in canvas.find_all() if canvas.type(item) == "rectangle"
            and canvas.itemcget(item, "fill") == fill
            for tag in canvas.gettags(item) if tag.startswith("block:R")}


def test_a_register_written_rests_on_the_green_from_the_clock_edge(app, tmp_path):
    """LDR R3, [R1]: R3 waits, turns green at the clock edge and stays green; R1, read, is lit
    and then tinted; the other rows are pale. A write to R15 and a failed condition change no
    row; a load with write-back changes its register and its base."""
    loaded(app, tmp_path, EXAMPLES)
    tool = connected(app)
    window = tool.open_inside("RegFile")
    steps(app, 4)                                           # LDR R3, [R1]
    read, write = steps_of(tool.film, "RegFile")
    show(tool, 0.0)
    assert rows_on(window, WAITING_FILL) == {"1", "3"} and rows_on(window, CHANGED) == set()
    assert len(rows_on(window, UNUSED_FILL)) == 14
    at_share(tool, "RegFile", 0.45)
    assert rows_on(window, WORKING_FILL) == {"1"}
    at_share(tool, "RegFile", 0.5, number=1)                # before the clock edge
    assert rows_on(window, CHANGED) == set() and rows_on(window, DONE_FILL) == {"1"}
    at_share(tool, "RegFile", 0.85, number=1)               # after it
    assert rows_on(window, CHANGED) == {"3"}
    tool.skip()
    assert rows_on(window, CHANGED) == {"3"} and rows_on(window, DONE_FILL) == {"1"}
    canvas = window.canvas
    new = hex32(app.machine.reg(3))
    assert colour_of_text(window, new, "block:R3") == look.net_colours(tool.film.trace)["WD3"]
    assert look.contrast(look.net_colours(tool.film.trace)["WD3"], CHANGED) >= 3
    assert {canvas.itemcget(item, "fill") for item in canvas.find_withtag("strike:R3")} == \
        {look.MARK}


@pytest.mark.parametrize("source, count, written", [
    (MEMORY, 9, set()),                                     # MOV PC, PC: the PC takes it
    (LARGEST, 14, set()),                                   # MOVGT R0, R3: the condition fails
    (WRITE_BACK, 4, {"0", "1"}),                            # LDR R0, [R1, #4]!
], ids=["to-pc", "failed", "write-back"])
def test_only_an_open_write_turns_a_register_green(app, tmp_path, source, count, written):
    loaded(app, tmp_path, source)
    tool = connected(app)
    window = tool.open_inside("RegFile")
    steps(app, count)
    tool.skip()
    assert rows_on(window, CHANGED) == written
    if written:                             # the base, by WD5, in ALUResult's colour
        base = tool.film.trace.values["A5"]
        assert colour_of_text(window, hex32(app.machine.reg(base)), f"block:R{base}") == \
            look.net_colours(tool.film.trace)["ALUResult"]


def frames(window):
    """The fills of the frames around the rows of the words read or written."""
    canvas = window.canvas
    left = window.LEFT + 20                 # where the table's frames begin
    return [canvas.itemcget(item, "fill") for item in canvas.find_all()
            if canvas.type(item) == "rectangle" and canvas.itemcget(item, "state") != "hidden"
            and abs(canvas.coords(item)[0] / window.k - left) < 0.5]


def test_a_word_stored_rests_on_the_green_from_the_clock_edge(app, tmp_path):
    """STR R2, [R1]: its word is framed on a tint of WriteData's colour, green from the clock
    edge on; LDRB R5, [R1, #6]: its word on a tint of ReadData's colour, never green; STRNE that
    does not run: no frame."""
    loaded(app, tmp_path, MEMORY)
    tool = connected(app)
    window = tool.open_inside("DMem")
    steps(app, 4)                                           # STR R2, [R1]
    colours = look.net_colours(tool.film.trace)
    at_share(tool, "DMem", -0.5)
    assert frames(window) == [""]
    at_share(tool, "DMem", 0.5)
    assert frames(window) == [look.rest(colours["WriteData"])[0]]
    at_share(tool, "DMem", 0.95)
    assert frames(window) == [CHANGED]
    tool.skip()
    assert frames(window) == [CHANGED]
    steps(app, 1)                                           # LDRB R5, [R1, #6]
    tool.skip()
    assert frames(window) == [look.rest(look.net_colours(tool.film.trace)["ReadData"])[0]]
    steps(app, 1)                                           # STRNE R2, [R1]: Z is 1
    tool.skip()
    assert frames(window) == [] and CHANGED not in part_fills(window)


def test_the_flags_register_rests_on_the_green_once_it_has_taken_the_flags(app, tmp_path):
    """ADDS: the flags register lights in its step and is green from its clock edge on; SUB,
    without S, keeps its flags: done, never green. The ALU's own flags are done once they
    leave: only the register in the control unit writes them."""
    loaded(app, tmp_path, MEMORY)
    tool = connected(app)
    control, alu = tool.open_inside("Control"), tool.open_inside("ALU")
    steps(app, 7)                                           # ADDS R3, R2, #1
    decoding, writing = control_steps(tool.film)
    step = tool.film.steps[writing]
    show(tool, step.start + 0.25 * step.duration)
    canvas = control.canvas

    def register():
        """The fill of the flags register."""
        return {canvas.itemcget(item, "fill") for item in canvas.find_all()
                if canvas.type(item) == "rectangle"
                and abs(canvas.coords(item)[0] / control.k - FLAGS_BOX[0]) < 0.5
                and abs(canvas.coords(item)[1] / control.k - FLAGS_BOX[1]) < 0.5}
    assert register() == {WORKING_FILL}
    show(tool, step.start + 0.75 * step.duration)
    assert register() == {CHANGED}
    tool.skip()
    assert register() == {CHANGED}
    assert fill_of_block(alu, "block:FlagN") == DONE_FILL
    steps(app, 1)                                           # SUB R4, R3, #1
    tool.skip()
    assert register() == {DONE_FILL}


def test_the_gray_of_a_port_not_in_use_reads_on_the_blocks_fill(app, tmp_path):
    """WD of a load inside the data memory at work: the darker gray, never the light gray of
    what lies on white or on the pale fill."""
    loaded(app, tmp_path, MEMORY)
    tool = connected(app)
    window = tool.open_inside("DMem")
    steps(app, 5)                                           # LDRB R5, [R1, #6]
    for share in (-0.5, 0.15, 0.5, 0.95, None):
        if share is None:
            tool.skip()
        else:
            at_share(tool, "DMem", share)
        assert colour_of_text(window, "WD", "block:DMem") != IDLE
        assert faint(window.canvas) == []
