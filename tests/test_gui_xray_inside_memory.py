# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The ARM X-Ray's windows inside the instruction memory and inside the data memory: the words
they show, the ports an instruction does not use, how they follow the film and the program, and
their layout."""

import tkinter

import pytest
from test_gui_run import loaded
from test_gui_xray import LARGEST, at, connected, steps, to_end
from test_gui_xray_inside import EXAMPLE, Event, block_point, example, middle_of
from xray_layout import clashes

from ares.disasm import basic
from ares.gui.tools import xray_inside_memory as memory
from ares.gui.tools.xray_inside import (DIM, DONE, IDLE, IDLE_STATE, INK, UNUSED, UNUSED_LINES,
                                        WORKING, WORKING_FILL, phase, steps_of)

MEMORY = """\
        .data
cell:   .word   0x11223344, 0x55667788
        .global _start
        .text
_start: LDR     R1, =cell
        MOV     R2, #0x9A
        ADDS    R3, R2, #1
        SUB     R4, R3, R2, LSL #2
        STR     R2, [R1]
        STRB    R2, [R1, #5]
        LDRB    R5, [R1, #6]
        CMP     R2, R2
        STRNE   R4, [R1]
        BL      next
next:   LDR     R0, =0xFF201000
        MOV     R6, #0x41
        STR     R6, [R0]
        LDR     R7, [R0, #4]
        SUB     R0, R0, #0x1000
        STR     R6, [R0]
        SVC     #10
"""
COUNT = 17                              # instructions in MEMORY
NOWHERE = """\
        .global _start
_start: MOV     R8, #0x80000000
        LDR     R9, [R8]
        SVC     #10
"""


@pytest.fixture(autouse=True)
def no_timer_left(app):
    """at() draws the film by hand, so the film's own timer is still waiting when a test ends:
    cancel it, or it fires in the next test, after its windows are gone."""
    yield
    root = app.root
    try:
        for job in root.tk.splitlist(root.tk.call("after", "info")):
            root.after_cancel(job)
    except tkinter.TclError:
        pass                            # the test closed the windows itself


def hex32(value):
    return f"0x{value:08X}"


def items(window):
    """The texts that show on the window's canvas."""
    canvas = window.canvas
    return [item for item in canvas.find_all() if canvas.type(item) == "text"
            and canvas.itemcget(item, "state") != "hidden"
            and canvas.itemcget(item, "text").strip()]


def shown(window):
    return [window.canvas.itemcget(item, "text") for item in items(window)]


def words(window):
    return " ".join(shown(window))


def in_block(window, item):
    left = window.canvas.bbox(item)[0] / window.k
    return window.LEFT < left < window.RIGHT


def row_items(window, address):
    """The texts in the table's row of address, from left to right. Its address is the
    leftmost text that says it: a word in the next column may say the same."""
    canvas = window.canvas
    first = min((item for item in items(window)
                 if canvas.itemcget(item, "text") == hex32(address) and in_block(window, item)),
                key=lambda item: canvas.bbox(item)[0])
    y = canvas.coords(first)[1]
    same = [item for item in items(window)
            if in_block(window, item) and abs(canvas.coords(item)[1] - y) < 0.5]
    return sorted(same, key=lambda item: canvas.bbox(item)[0])


def row(window, address):
    return [window.canvas.itemcget(item, "text") for item in row_items(window, address)]


def cell(window, address, text):
    """The text in the row of address that says text."""
    return next(item for item in row_items(window, address)
                if window.canvas.itemcget(item, "text") == text)


def right_of_block(window):
    """The texts at the right of the block: the output's name and value."""
    return [window.canvas.itemcget(item, "text") for item in items(window)
            if window.canvas.bbox(item)[0] / window.k > window.RIGHT]


def font(window, item, option):
    canvas = window.canvas
    return canvas.tk.call("font", "actual", canvas.itemcget(item, "font"), f"-{option}")


def bold(window, address, text):
    return font(window, cell(window, address, text), "weight") == "bold"


def struck(window, address, text):
    return int(font(window, cell(window, address, text), "overstrike")) == 1


def lit(window):
    canvas = window.canvas
    return any(canvas.itemcget(item, "fill") == WORKING_FILL for item in canvas.find_all()
               if canvas.type(item) == "rectangle" and canvas.itemcget(item, "state") != "hidden")


def marked(window):
    """The bytes in the small frames that mark the bytes read or written."""
    canvas = window.canvas
    found = []
    for item in canvas.find_all():
        if canvas.type(item) != "rectangle" or canvas.itemcget(item, "state") == "hidden" \
                or canvas.itemcget(item, "fill") \
                or canvas.itemcget(item, "outline") in ("", INK, IDLE):
            continue
        left, top, right, bottom = canvas.coords(item)
        for text in items(window):
            x1, y1, x2, y2 = canvas.bbox(text)
            if left <= (x1 + x2) / 2 <= right and top <= (y1 + y2) / 2 <= bottom:
                found.append(canvas.itemcget(text, "text"))
    return found


def laid_out(window):
    """No text lies over another text, a line or a block's outline, and none is cut off."""
    canvas = window.canvas
    assert clashes(canvas) == []
    width, height = float(canvas.cget("width")), float(canvas.cget("height"))
    for item in items(window):
        left, top, right, bottom = canvas.bbox(item)
        assert left >= 0 and top >= 0 and right <= width and bottom <= height, \
            canvas.itemcget(item, "text")


def play(tool, block, share):
    """Show the tool's film at share of block's step; give the block's phase then."""
    step = steps_of(tool.film, block)[0]
    moment = step.start + step.duration * share
    at(tool, tool.player.start + moment - tool.test_clock.now)
    return phase(tool.film, tool.player.moment, block)


def opened(app, tmp_path, source, count, *blocks):
    """The tool connected and the windows inside blocks open, count instructions run."""
    loaded(app, tmp_path, source)
    tool = connected(app)
    windows = [tool.open_inside(block) for block in blocks]
    steps(app, count)
    to_end(tool)
    return (tool, *windows)


# Opening and closing ---------------------------------------------------------------------

def test_a_click_on_either_memory_opens_its_window_and_closing_works(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    tool = connected(app)
    for block, kind, title in (("IMem", memory.InstructionMemoryWindow,
                                "ARM X-Ray: Inside the Instruction Memory"),
                               ("DMem", memory.DataMemoryWindow,
                                "ARM X-Ray: Inside the Data Memory")):
        tool._clicked(Event(*block_point(tool, block)))
        window = tool.insides[block]
        assert isinstance(window, kind) and window.window.title() == title
        assert window.SIZE[0] <= 760 and window.SIZE[1] <= 480
    inside, data = tool.insides["IMem"], tool.insides["DMem"]
    inside.close()
    assert inside.window is None and list(tool.insides) == ["DMem"]
    app.run("step")                     # a closed window draws nothing
    again = tool.open_inside("IMem")
    assert again is not inside and again.window is not None
    tool.close()
    assert data.window is None and again.window is None and tool.insides == {}


# Inside the instruction memory ---------------------------------------------------------

def test_the_instruction_memory_shows_the_words_around_the_pc(app, tmp_path):
    tool, window = opened(app, tmp_path, LARGEST, 6, "IMem")        # LDR R3, [R1]
    trace = tool.model.view.trace
    pc = trace.pc
    for number in range(-4, 5):
        address = pc + 4 * number
        word = int.from_bytes(app.machine.read_memory(address, 4), "little")
        cells = row(window, address)
        assert cells[cells.index(hex32(address)):][:3] == [hex32(address), hex32(word),
                                                           basic(word, address)]
    assert row(window, pc) == ["A", hex32(pc), hex32(trace.word), "LDR R3, [R1]", "RD"]
    assert bold(window, pc, "LDR R3, [R1]") and bold(window, pc, hex32(pc))
    assert not bold(window, pc + 4, hex32(pc + 4))
    assert hex32(pc) in shown(window)                               # A, under the PC's wire
    assert right_of_block(window) == ["Instr", hex32(trace.word)]
    assert f"The word at {hex32(pc)} is {hex32(trace.word)}" in words(window)
    laid_out(window)


def test_the_instruction_memory_is_idle_then_reads_then_finished(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    tool = connected(app)
    window = tool.open_inside("IMem")
    steps(app, 6)
    word = hex32(tool.model.view.trace.word)
    assert phase(tool.film, tool.player.moment, "IMem")[0] == IDLE_STATE   # the PC comes
    assert "not here yet" in shown(window) and not lit(window)
    assert "READ" not in shown(window) and right_of_block(window) == ["Instr"]
    laid_out(window)
    assert play(tool, "IMem", 0.5) == (WORKING, pytest.approx(0.5))
    assert lit(window) and "READ" in shown(window) and "not here yet" not in shown(window)
    assert right_of_block(window) == ["Instr"]                      # the word has not left yet
    laid_out(window)
    play(tool, "IMem", 0.95)
    assert lit(window) and right_of_block(window) == ["Instr", word]
    laid_out(window)
    to_end(tool)
    assert phase(tool.film, tool.player.moment, "IMem")[0] == DONE
    assert not lit(window) and "READ" in shown(window) and right_of_block(window) == ["Instr", word]


def test_the_instruction_memory_follows_the_program(app, tmp_path):
    tool, window = opened(app, tmp_path, LARGEST, 1, "IMem")        # LDR R0, =intro at 0
    assert tool.model.view.trace.pc == 0
    assert row(window, 0xFFFFFFF0)[:2] == [hex32(0xFFFFFFF0), hex32(0)]     # wraps round
    assert bold(window, 0, hex32(0)) and row(window, 0)[0] == "A"
    laid_out(window)
    steps(app, 5)                                                   # LDR R3, [R1]
    to_end(tool)
    pc = tool.model.view.trace.pc
    steps(app, 1)                                                   # CMP R3, R0
    to_end(tool)
    trace = tool.model.view.trace
    assert trace.pc == pc + 4
    assert row(window, trace.pc) == ["A", hex32(trace.pc), hex32(trace.word), "CMP R3, R0", "RD"]
    assert bold(window, trace.pc, "CMP R3, R0") and not bold(window, pc, "LDR R3, [R1]")
    assert row(window, pc)[0] != "A"
    laid_out(window)


# Inside the data memory ----------------------------------------------------------------

def test_a_load_reads_the_word_at_its_address(app, tmp_path):
    tool, window = opened(app, tmp_path, LARGEST, 6, "DMem")        # LDR R3, [R1]
    address = app.machine.reg(1)
    assert row(window, address) == ["A", hex32(address), "0x0000000C", "0C", "00", "00", "00",
                                    "RD"]
    for number in range(-4, 5):
        here = address + 4 * number
        word = int.from_bytes(app.machine.read_memory(here, 4), "little")
        assert row(window, here)[row(window, here).index(hex32(here)) + 1] == hex32(word)
    assert app.machine.reg(3) == 12 and right_of_block(window) == ["ReadData", "0x0000000C"]
    assert marked(window) == ["0C", "00", "00", "00"] and bold(window, address, "0x0000000C")
    assert {"MemWrite = 0: closed", "Size = 00: a whole word", "READ"} <= set(shown(window))
    assert {"in: 0x0000000C", "a word: it passes", "on unchanged", "Signed = 0"} <= \
        set(shown(window))                                          # the load extender
    assert f"reads the word at {hex32(address)}" in words(window)
    laid_out(window)


def test_a_store_strikes_out_the_old_word_and_shows_the_new_one(app, tmp_path):
    tool, window = opened(app, tmp_path, MEMORY, 5, "DMem")         # STR R2, [R1]
    address = app.machine.reg(1)
    assert app.machine.read_memory(address, 4) == bytes([0x9A, 0, 0, 0])
    stored = ["A", hex32(address), "0x11223344", "9A", "00", "00", "00", "0x0000009A", "RD"]
    assert row(window, address) == stored
    assert struck(window, address, "0x11223344")
    assert not struck(window, address + 4, "0x55667788")
    assert "After the write" in shown(window) and "WRITE" in shown(window)
    assert {"MemWrite = 1: open", "Size = 00: a whole word", "0x0000009A"} <= set(shown(window))
    assert "Signed = 0" not in shown(window)                       # a store reads nothing
    assert right_of_block(window) == ["ReadData", UNUSED_LINES]     # nothing is read
    laid_out(window)
    app.run("backstep")                 # the instruction before, finished: no memory access
    assert app.machine.read_memory(address, 4) == bytes([0x44, 0x33, 0x22, 0x11])
    assert tool.model.view.trace.text == "SUB R4, R3, R2, LSL #2"
    assert "This instruction does not use the data memory." in shown(window)
    assert "MemWrite = 0: closed" in shown(window) and "WRITE" not in shown(window)
    laid_out(window)
    steps(app, 1)                       # the store again: the window follows
    to_end(tool)
    assert row(window, address) == stored and struck(window, address, "0x11223344")
    laid_out(window)


def test_after_backstep_both_memories_show_the_instruction_the_tool_shows(app, tmp_path):
    tool, inside, data = opened(app, tmp_path, MEMORY, 6, "IMem", "DMem")  # STRB R2, [R1, #5]
    app.run("backstep")                 # STR R2, [R1] finished
    trace = tool.model.view.trace
    assert trace.text == "STR R2, [R1]" and not tool.player.playing
    address = app.machine.reg(1)
    assert row(inside, trace.pc) == ["A", hex32(trace.pc), hex32(trace.word), "STR R2, [R1]",
                                     "RD"]
    assert "the instruction STR R2, [R1]." in words(inside)
    assert row(data, address) == ["A", hex32(address), "0x11223344", "9A", "00", "00", "00",
                                  "0x0000009A", "RD"]
    assert struck(data, address, "0x11223344") and "WRITE" in shown(data)
    laid_out(inside)
    laid_out(data)


def test_the_instruction_memory_names_the_instruction_as_written(app, tmp_path):
    source = MEMORY.replace("MOV     R2, #0x9A", "MOV     R2, #154")
    tool, window = opened(app, tmp_path, source, 2, "IMem")        # MOV R2, #154
    trace = tool.model.view.trace
    assert row(window, trace.pc)[3] == "MOV R2, #0x9A"              # the memory's word
    assert f"is {hex32(trace.word)}: the instruction MOV R2, #154." in words(window)
    laid_out(window)


def test_a_byte_store_and_a_byte_load_mark_their_byte(app, tmp_path):
    tool, window = opened(app, tmp_path, MEMORY, 6, "DMem")         # STRB R2, [R1, #5]
    word = app.machine.reg(1) + 4
    assert row(window, word) == ["A", hex32(word), "0x55667788", "88", "9A", "66", "55",
                                 "0x55669A88", "RD"]
    assert marked(window) == ["9A"] and struck(window, word, "0x55667788")
    assert "Size = 10: one byte" in shown(window) and "WRITE BYTE" in shown(window)
    assert "writes the byte 0x9A, the low byte of WD" in words(window)
    laid_out(window)
    steps(app, 1)                                                   # LDRB R5, [R1, #6]
    to_end(tool)
    assert row(window, word) == ["A", hex32(word), "0x55669A88", "88", "9A", "66", "55", "RD"]
    assert marked(window) == ["66"] and not struck(window, word, "0x55669A88")
    assert app.machine.reg(5) == 0x66 and right_of_block(window) == ["ReadData", "0x00000066"]
    laid_out(window)


def test_an_instruction_without_a_memory_access_says_so_with_its_address(app, tmp_path):
    tool, window = opened(app, tmp_path, MEMORY, 3, "DMem")         # ADDS R3, R2, #1
    for count, text in ((3, "ADDS R3, R2, #1"), (4, "SUB R4, R3, R2, LSL #2"), (10, "BL ")):
        steps(app, count - tool.model.change.number)
        to_end(tool)
        trace = tool.model.view.trace
        assert trace.text.startswith(text)
        address = hex32(trace.values["ALUResult"])
        assert "This instruction does not use the data memory." in shown(window)
        assert f"A gets {address} from ALUResult" in words(window) and address in shown(window)
        assert "MemWrite = 0: closed" in shown(window)
        assert not lit(window) and marked(window) == [] and "Address" not in shown(window)
        laid_out(window)


def tagged(window, tag):
    """The texts with tag that show."""
    canvas = window.canvas
    return [canvas.itemcget(item, "text") for item in canvas.find_withtag(tag)
            if canvas.type(item) == "text" and canvas.itemcget(item, "state") != "hidden"
            and canvas.itemcget(item, "text")]


def port_colour(window, name):
    """The colour of the name of a port inside the block."""
    canvas = window.canvas
    (port,) = [item for item in canvas.find_withtag("block:DMem")
               if canvas.type(item) == "text" and canvas.itemcget(item, "text") == name]
    return canvas.itemcget(port, "fill")


@pytest.mark.parametrize("text", list(EXAMPLE))
def test_a_load_writes_no_data_and_a_store_reads_none(app, tmp_path, text):
    """WD of a load and RD of a store are not used by the instruction: gray, and saying so
    from the start; the store's data is R0, as the trace has it. The other instructions do not
    use the data memory."""
    tool, (window,) = example(app, tmp_path, text, "DMem")
    values = tool.film.trace.values
    load = text.startswith("LDR")
    if not load and not text.startswith("STR"):
        to_end(tool)
        assert values["WriteData"] is None and values["ReadData"] is None
        assert "This instruction does not use the data memory." in shown(window)
        assert tagged(window, "wire:WriteData") == ["WriteData"]
        assert tagged(window, "wire:ReadData") == ["ReadData"]
        laid_out(window)
        return
    for moment in ("start", "middle", "end"):
        if moment == "middle":
            middle_of(tool)
        elif moment == "end":
            to_end(tool)
        if load:
            assert values["WriteData"] is None
            assert tagged(window, "wire:WriteData") == ["WriteData", UNUSED]
        else:
            assert values["ReadData"] is None and values["WriteData"] == app.machine.reg(0)
            assert tagged(window, "wire:ReadData") == ["ReadData", UNUSED_LINES]
        laid_out(window)
    assert port_colour(window, "WD" if load else "RD") == DIM     # the gray on the block's fill
    assert port_colour(window, "RD" if load else "WD") == INK
    if load:
        assert right_of_block(window) == ["ReadData", hex32(values["ReadData"])]
        assert values["ReadData"] == 7
    else:
        assert tagged(window, "wire:WriteData") == ["WriteData", hex32(values["WriteData"])]
        assert hex32(values["ALUResult"]) == hex32(app.machine.reg(1) + 4)


def test_a_failed_condition_neither_writes_nor_reads(app, tmp_path):
    tool, window = opened(app, tmp_path, MEMORY, 9, "DMem")         # STRNE R4, [R1], Z = 1
    address = app.machine.reg(1)
    assert app.machine.read_memory(address, 4) == bytes([0x9A, 0, 0, 0])
    assert "The condition failed (CondEx 0)" in words(window) and "MemWrite = 0: closed" in \
        shown(window)
    assert row(window, address) == ["A", hex32(address), "0x0000009A", "9A", "00", "00", "00",
                                    "RD"]
    assert not lit(window) and marked(window) == []
    assert not struck(window, address, "0x0000009A") and not bold(window, address, "0x0000009A")
    laid_out(window)


def test_a_device_is_named_and_never_read(app, tmp_path):
    tool, window = opened(app, tmp_path, MEMORY, 13, "DMem")        # STR R6, [R0]
    assert row(window, 0xFF201000) == ["A", "0xFF201000", "-", "JTAG UART data", "RD"]
    assert row(window, 0xFF201004) == ["0xFF201004", "-", "JTAG UART control"]
    assert row(window, 0xFF200FFC) == ["0xFF200FFC", "-", "no memory here"]
    assert "There is no memory at 0xFF201000: it is the address of the JTAG UART's data " \
           "register, a device of the DE1-SoC." in shown(window)
    assert "The store hands WD = 0x00000041 to the device." in shown(window)
    laid_out(window)
    app.machine.console.feed("x")       # a read of the JTAG UART's data register would take it
    window.close()
    window = tool.open_inside("DMem")
    assert "JTAG UART data" in shown(window) and app.machine.console.pending() == 1
    steps(app, 1)                                                   # LDR R7, [R0, #4]
    to_end(tool)
    assert app.machine.reg(7) == 0x00400000
    assert right_of_block(window) == ["ReadData", "0x00400000"]
    assert "The load got 0x00400000 from the device: it leaves on RD." in shown(window)
    laid_out(window)
    steps(app, 2)                                                   # STR R6, [R0]: the LEDs
    to_end(tool)
    assert row(window, 0xFF200000) == ["A", "0xFF200000", "-", "red LEDs", "RD"]
    assert row(window, 0xFF200010)[2] == "no memory here"          # no device there
    assert "The Digital Lab Sim simulates it while it is connected; else reads give 0 and " \
           "writes are ignored." in shown(window)
    laid_out(window)


def test_an_address_without_memory_or_device_says_so(app, tmp_path):
    tool, window = opened(app, tmp_path, NOWHERE, 2, "DMem")        # LDR R9, [R8]: an error
    assert "out of range" in tool.model.view.heading
    assert row(window, 0x80000000) == ["A", "0x80000000", "-", "no memory here", "RD"]
    assert "There is no memory at 0x80000000: nothing is there, and an access stops the " \
           "program with a runtime error." in shown(window)
    assert right_of_block(window) == ["ReadData"]                   # nothing was read
    laid_out(window)
    assert memory.device_at(0xFF200000)[0] == "red LEDs"
    assert memory.device_at(0xFF20002C)[0] == "displays HEX3-0"
    assert memory.device_at(0xFF20005C)[0] == "keys Edgecapture"
    assert memory.device_at(0xFF201007)[0] == "JTAG UART control"
    for address in (0xFF200010, 0xFF201008, 0xFF20FFFC):            # no device simulated there
        short, said, device, board = memory.device_at(address)
        assert short == "no memory here" and "reads give 0" in said and not device
    assert memory.device_at(0x50000000)[:3] == ("no memory here", "nothing is there, and an "
                                                "access stops the program with a runtime error",
                                                False)


def test_the_data_memory_is_idle_then_writes_then_finished(app, tmp_path):
    loaded(app, tmp_path, MEMORY)
    tool = connected(app)
    window = tool.open_inside("DMem")
    steps(app, 5)                                                   # STR R2, [R1]
    address = app.machine.reg(1)
    assert play(tool, "DMem", -0.5)[0] == IDLE_STATE
    assert shown(window).count("not here yet") == 2 and "MemWrite: not here yet" in shown(window)
    assert not lit(window) and not struck(window, address, "0x11223344") and marked(window) == []
    laid_out(window)
    assert play(tool, "DMem", 0.5) == (WORKING, pytest.approx(0.5))
    assert lit(window) and "WRITE" in shown(window) and "MemWrite = 1: open" in shown(window)
    assert marked(window) == ["44", "33", "22", "11"]
    assert not struck(window, address, "0x11223344") and "0x0000009A" not in row(window, address)
    laid_out(window)
    play(tool, "DMem", 0.95)                                        # the clock edge
    assert struck(window, address, "0x11223344") and "0x0000009A" in row(window, address)
    laid_out(window)
    to_end(tool)
    assert phase(tool.film, tool.player.moment, "DMem")[0] == DONE
    assert not lit(window) and struck(window, address, "0x11223344") and "WRITE" in shown(window)


def test_an_svc_is_fetched_but_does_not_use_the_data_memory(app, tmp_path):
    tool, inside, data = opened(app, tmp_path, LARGEST, 2, "IMem", "DMem")  # SVC #4
    assert "An SVC does not use the data memory: the system performs the service." in shown(data)
    assert "0xEF000004" in shown(inside) and "does not use" not in words(inside)
    for window in (inside, data):
        assert not lit(window) and "not here yet" not in shown(window)
        laid_out(window)


@pytest.mark.parametrize("zoom", [1.0, 1.6])
def test_no_text_clashes_at_any_instruction_or_zoom(app, tmp_path, zoom):
    loaded(app, tmp_path, MEMORY)
    tool = connected(app)
    tool._make_canvas(zoom)
    windows = [tool.open_inside(block) for block in ("IMem", "DMem")]
    assert all(window.zoom == zoom for window in windows)
    for _ in range(COUNT):
        app.run("step")
        for window in windows:
            # A block this instruction does not use has no step of its own (no gate, no
            # light): its window is checked at the end only.
            working = tool.film.steps and steps_of(tool.film, window.BLOCK)
            for share in (0.1, 0.5, 0.95) if working else ():
                play(tool, window.BLOCK, share)
                laid_out(window)
        to_end(tool)
        for window in windows:
            laid_out(window)



HALVES = """\
        .data
cell:   .word   0x11223344, 0x55667788
        .global _start
        .text
_start: LDR     R1, =cell
        MOVW    R2, #0x80FE
        STRH    R2, [R1, #2]
        LDRSH   R3, [R1, #2]
        LDRSB   R4, [R1, #3]
        LDRH    R5, [R1, #2]
        SVC     #10
"""


def test_the_load_extender_widens_a_halfword_or_a_byte(app, tmp_path):
    """STRH writes two bytes, and the load extender is not used; LDRSH and LDRSB copy the sign
    bit into the bits above, LDRH fills them with zeros: the extender says which and how."""
    tool, window = opened(app, tmp_path, HALVES, 3, "DMem")         # STRH R2, [R1, #2]
    address = app.machine.reg(1)
    assert row(window, address) == ["A", hex32(address), "0x11223344", "44", "33", "FE", "80",
                                    "0x80FE3344", "RD"]
    assert marked(window) == ["FE", "80"] and "WRITE HALF" in shown(window)
    assert "Size = 01: a halfword" in shown(window) and "Signed = 1" not in shown(window)
    assert "writes the halfword 0x80FE, the low half of WD" in words(window)
    assert UNUSED_LINES in tagged(window, "block:Extender")
    laid_out(window)
    for count, text, value, said in ((1, "LDRSH", 0xFFFF80FE, ("sign bit 1 copied",
                                                               "into bits 31:16")),
                                     (1, "LDRSB", 0xFFFFFF80, ("sign bit 1 copied",
                                                               "into bits 31:8")),
                                     (1, "LDRH", 0x000080FE, ("zeros in bits 31:16",))):
        steps(app, count)
        to_end(tool)
        assert tool.model.view.trace.text.startswith(text)
        extender = tagged(window, "block:Extender")
        assert set(said) <= set(extender) and "Load extender" in extender
        assert right_of_block(window) == ["ReadData", hex32(value)]
        signed = "1" if text.startswith("LDRS") else "0"
        assert f"Signed = {signed}" in shown(window)
        assert f"ReadData = {hex32(value)}." in words(window)
        laid_out(window)
    assert "READ HALF" in shown(window)


def test_a_load_whose_condition_fails_brings_size_and_signed_but_widens_nothing(app, tmp_path):
    """As in the picture, Size and Signed reach the data memory with every load; when its
    condition fails, nothing is read, and the load extender says so."""
    from test_gui_xray import HALFWORDS
    tool, window = opened(app, tmp_path, HALFWORDS, 14, "DMem")          # LDRHEQ R10, [R1]: Z is 0
    assert tool.model.view.trace.text.startswith("LDRHEQ")
    assert "Size = 01: a halfword" in shown(window) and "Signed = 0" in shown(window)
    assert "nothing is read:\nthe condition failed" in tagged(window, "block:Extender")
    assert right_of_block(window) == ["ReadData"]
    laid_out(window)
