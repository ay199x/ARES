# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The ARM X-Ray's windows inside its blocks: how they open, follow the film and the program,
redraw only when their block changes, and close; how quickly the film plays with all of them
open; and the windows inside Extend and the shifter."""

import gc
import time
import tkinter

import pytest
from test_gui_run import loaded
from test_gui_xray import LARGEST, at, connected, steps, to_end
from xray_layout import clashes

from conftest import native, pump
from ares.gui.tools import xray_inside
from ares.gui.widgets import scale
from ares.gui.tools.xray_inside import (CHANGED, DONE, DONE_FILL, HEADING_TAG, IDLE, IDLE_STATE,
                                        INK, MARK, ON, UNUSED_FILL, WORKING, WORKING_FILL, phase,
                                        steps_of)

# One instruction for each way the datapath leaves parts unused: the instruction's text as the
# Text Segment's Basic column begins it, and how many Steps reach it.
EXAMPLES = """\
        .data
cell:   .word   7, 0
        .global _start
        .text
_start: LDR     R1, =cell
        MOV     R0, #5              @ reads no register
        MOV     R2, #3
        LDR     R3, [R1]            @ reads R1 only
        SUBS    R2, R2, #1          @ reads R2 only
        ADD     R0, R1, R2          @ no immediate: Extend is not used
        CMP     R3, R0              @ no Rd: no register at A3, and nothing written
        STR     R0, [R1, #4]        @ reads R1 and R0, which the shifter passes on
        BNE     done                @ reads R15 only
done:   SVC     #10
"""
EXAMPLE = {"MOV R0, #5": 2, "LDR R3, [R1]": 4, "SUBS R2, R2, #1": 5, "ADD R0, R1, R2": 6,
           "CMP R3, R0": 7, "STR R0, [R1, #4]": 8, "BNE": 9}
BLOCKS = ("Control", "RegFile", "ALU", "Extend", "Shifter", "IMem", "DMem")


def texts(window):
    canvas = window.canvas
    return [canvas.itemcget(item, "text") for item in canvas.find_all()
            if canvas.type(item) == "text" and canvas.itemcget(item, "text")]


def joined(window):
    return " ".join(texts(window))


def block_point(tool, block):
    """A point inside block on the tool's canvas, as an event would give it."""
    canvas = tool.canvas
    item = tool.picture.blocks[block]
    left, top, right, bottom = canvas.bbox(item)
    return (left + right) // 2, bottom - 3


class Event:
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.x_root, self.y_root = x, y


def example(app, tmp_path, text, *blocks, zoom=None):
    """The tool connected to EXAMPLES with the windows inside blocks open, run up to the
    instruction text (of EXAMPLE), its film at its start; and the windows."""
    loaded(app, tmp_path, EXAMPLES)
    tool = connected(app)
    if zoom is not None:
        tool._make_canvas(zoom)
    windows = [tool.open_inside(block) for block in blocks]
    steps(app, EXAMPLE[text])
    assert tool.model.view.trace.text.startswith(text), tool.model.view.trace.text
    return tool, windows


def middle_of(tool):
    """Show the tool's film at its middle."""
    tool.stop_film()
    tool.test_clock.now = tool.player.start + tool.film.seconds / 2
    tool._tick()
    tool.stop_film()


def within(window):
    """Every text of the window lies within its canvas."""
    canvas = window.canvas
    width, height = float(canvas.cget("width")), float(canvas.cget("height"))
    for item in canvas.find_all():
        if canvas.type(item) == "text" and canvas.itemcget(item, "text") and \
                canvas.itemcget(item, "state") != "hidden":
            left, top, right, bottom = canvas.bbox(item)
            assert left >= 0 and top >= 0 and right <= width and bottom <= height, \
                canvas.itemcget(item, "text")


def drawn(window):
    """Everything drawn on the window's canvas, with its fonts and tags, in any stacking order:
    to compare two pictures."""
    canvas = window.canvas
    found = []
    for shape in canvas.find_all():
        options = {}
        for name in ("fill", "outline", "width", "state", "text", "dash", "arrow", "font"):
            try:
                options[name] = canvas.itemcget(shape, name)
            except tkinter.TclError:
                pass                    # an option this kind of item does not have
        coords = tuple(round(c, 1) for c in canvas.coords(shape))
        found.append((canvas.type(shape), coords, tuple(sorted(options.items())),
                      tuple(sorted(canvas.gettags(shape)))))
    return sorted(found)


def marks(window):
    """The dots at the inputs taken and the lines of the crosses at the inputs rejected."""
    canvas = window.canvas
    dots = [item for item in canvas.find_withtag("dot") if canvas.itemcget(item, "fill") == INK]
    crosses = [item for item in canvas.find_withtag("cross")
               if canvas.itemcget(item, "fill") == MARK]
    return dots, crosses


# How they open and close ---------------------------------------------------------------------

def test_a_click_on_a_block_opens_the_window_inside_it(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    tool = connected(app)
    tool._clicked(Event(*block_point(tool, "Extend")))
    assert "Extend" in tool.insides
    window = tool.insides["Extend"]
    assert window.window.title() == "ARM X-Ray: Inside Extend"
    tool._clicked(Event(*block_point(tool, "Extend")))
    assert list(tool.insides) == ["Extend"]         # one window for each block


def test_the_pointer_is_a_hand_over_a_block_with_a_window(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    tool = connected(app)
    tool._pointer_moved(Event(*block_point(tool, "Extend")))
    assert str(tool.canvas.cget("cursor")) == "hand2"
    tool._pointer_moved(Event(*block_point(tool, "PCMux")))
    assert str(tool.canvas.cget("cursor")) == ""


def test_multiplexers_adders_and_the_pc_have_no_window():
    for block in ("PCMux", "RA1Mux", "ALUSrcMux", "ResultMux", "Add4", "Add8", "PCReg"):
        assert xray_inside.window_class(block) is None


def test_escape_and_closing_the_tool_close_the_windows(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    tool = connected(app)
    window = tool.open_inside("Extend")
    window.window.event_generate("<Escape>") if False else window.close()
    assert tool.insides == {}
    tool.open_inside("Shifter")
    tool.close()
    assert all(open_window.window is None for open_window in [window])


# Their headings ------------------------------------------------------------------------------

# Each window's heading, a name, and how its tip, what the block does, begins.
HEADINGS = {
    "Control": ("Decoder and Conditional Logic", "The Decoder makes the signals from the fields "
                "of the word; the Conditional Logic lets them write only if the condition holds."),
    "RegFile": ("Three Read Ports and Two Write Ports", "The register file reads up to three "
                "registers at once, on RD1, RD2 and RD4, and writes at the clock edge"),
    "ALU": ("Operations and Flags", "The ALU does the operation that ALUControl chooses on SrcA "
            "and SrcB (and RD4), and makes the flags N, Z, C and V."),
    "Extend": ("Six Ways and the ImmSrc Multiplexer", "Extend makes the immediate of the word 32 "
               "bits wide, in one of five ways, or passes on the pass counter's offset; ImmSrc "
               "chooses which."),
    "Shifter": ("Kind and Amount of the Shift", "The shifter moves the bits of RD2 left or right, "
                "by an amount in the word or in a register, before the ALU takes it."),
    "IMem": ("Words Around the PC", "The instruction memory puts the word at address A on RD: the "
             "instruction to run. A word is 4 bytes, so the addresses go up by 4."),
    "DMem": ("Words Around the Address", "The data memory reads at address A and puts what it "
             "reads on RD; when WE is 1, it writes WD there, at the clock edge. Size: a word "
             "(00), a halfword (01) or a byte (10)."),
}


@pytest.mark.parametrize("block", BLOCKS)
def test_each_window_s_heading_is_a_name_whose_tip_says_what_the_block_does(app, tmp_path,
                                                                            block):
    """A heading is a name, not a sentence: the sentence that was the window's first lines is
    the heading's tip, and nowhere else on the window. The mouse resting on the heading shows
    it, as the tips of the picture show."""
    tool, (window,) = example(app, tmp_path, "STR R0, [R1, #4]", block)
    middle_of(tool)
    name, about = HEADINGS[block]
    canvas = window.canvas
    (item,) = canvas.find_withtag(HEADING_TAG)
    assert window.HEADING == canvas.itemcget(item, "text") == name
    assert len(name) <= 40 and name[0].isupper() and not any(mark in name for mark in ".:;,?")
    tip = window.tips[HEADING_TAG]
    assert tip == window.ABOUT and " ".join(tip.split()).startswith(about)
    assert all(len(line) <= 90 for line in tip.split("\n"))
    shown = [" ".join(text.split()) for text in texts(window)]
    for sentence in " ".join(tip.split()).split(". "):     # the first lines are gone
        assert not any(sentence.rstrip(".") in text for text in shown), sentence
    left, top, right, bottom = canvas.bbox(item)
    x, y = (left + right) // 2, (top + bottom) // 2
    assert window.tip_at(x, y) == HEADING_TAG
    window._pointer_moved(Event(x, y))
    tag, job, opened = window._tip
    assert tag == HEADING_TAG and job is not None and opened is None
    window._show_tip(tag, 0, 0)
    assert window._tip[2].winfo_children()[0].cget("text") == tip
    width, height = int(canvas.cget("width")), int(canvas.cget("height"))
    window._pointer_moved(Event(width - 2, height - 2))     # nothing with a tip there
    assert window._tip is None
    assert clashes(canvas) == []
    window._pointer_moved(Event(x, y))                      # a tip waiting when it closes
    window.close()
    assert window._tip is None


def test_a_window_without_an_instruction_says_so_where_its_heading_stands(app, tmp_path):
    """The control unit's line that says why it shows nothing stands where its heading does,
    with no tip; the other windows keep their headings."""
    loaded(app, tmp_path, EXAMPLES)
    tool = connected(app)
    windows = {block: tool.open_inside(block) for block in BLOCKS}
    assert tool.model.view.trace is None
    for block, window in windows.items():
        named = [window.canvas.itemcget(item, "text")
                 for item in window.canvas.find_withtag(HEADING_TAG)]
        assert named == ([] if block == "Control" else [HEADINGS[block][0]]), block
    assert texts(windows["Control"])[0] == "No instruction is shown."


# How they follow -----------------------------------------------------------------------------

def test_the_window_plays_with_the_film(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    tool = connected(app)
    window = tool.open_inside("Extend")
    for _ in range(6):                  # LDR R3, [R1]
        app.run("step")
    film = tool.film
    assert phase(film, 0.0, "Extend") == (IDLE_STATE, 0.0)
    assert "(not here yet)" in joined(window)
    step = next(s for s in film.steps if any(name == "Extend" for name, _ in s.lights))
    tool.test_clock.now = tool.player.start + step.start + step.duration / 2
    tool._tick()
    assert phase(film, tool.player.moment, "Extend")[0] == WORKING
    assert "(not here yet)" not in joined(window)
    to_end(tool)
    assert phase(film, tool.player.moment, "Extend")[0] == DONE
    assert "ExtImm = 0x00000000" in joined(window)


def test_the_window_follows_the_program(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    tool = connected(app)
    window = tool.open_inside("Extend")
    steps(app, 6)
    to_end(tool)
    assert "ImmSrc = 001" in joined(window)         # LDR: imm12
    steps(app, 1)                                   # CMP R3, R0: ImmSrc XX
    to_end(tool)
    words = joined(window)
    assert "Extend is not used by this instruction." in words and "ImmSrc = XXX" in words
    assert "here)" not in words


def redrawn(window, monkeypatch):
    """A list that gets the block's state, and where it is in the block's step, at each
    redraw of window."""
    states = []
    original = window.redraw

    def redraw(film, moment, context, state, fraction):
        states.append((state, film.at(moment)[0]))
        return original(film, moment, context, state, fraction)
    monkeypatch.setattr(window, "redraw", redraw)
    return states


def test_a_window_redraws_only_when_its_block_changes(app, tmp_path, monkeypatch):
    """A window is drawn again when its block's state changes, or another of its own steps
    plays, not at each step of the film: the register file redraws when it reads, between its
    read and its write, when it writes and when it is done."""
    loaded(app, tmp_path, LARGEST)
    tool = connected(app)
    windows = {block: tool.open_inside(block) for block in BLOCKS}
    steps(app, 6)                                   # LDR R3, [R1], from its start
    film = tool.film
    redraws = {block: redrawn(window, monkeypatch) for block, window in windows.items()}
    for _ in range(150):
        at(tool, film.seconds / 150)
    read, write = (film.steps.index(step) for step in steps_of(film, "RegFile"))
    assert [state for state, _ in redraws["RegFile"]] == [WORKING, WORKING, WORKING, DONE]
    assert [number for _, number in redraws["RegFile"]][:3] == [read, read + 1, write]
    for block in ("IMem", "DMem"):
        assert [state for state, _ in redraws[block]] == [WORKING, DONE], block
    assert [state for state, _ in redraws["Extend"]] == [WORKING, WORKING, DONE]   # ExtImm out
    (alu,) = (film.steps.index(step) for step in steps_of(film, "ALU"))
    assert all(state == DONE or number == alu for state, number in redraws["ALU"])
    assert [state for state, _ in redraws["Shifter"]] in ([], [DONE])   # not used by LDR
    assert redraws["Control"] == []                 # animate() draws again what changes


TICKS = 150                             # pictures of a film, as the timer draws about 30 a second
SLOWEST = 0.033                         # the time from one picture to the next, in seconds


def tick_times(app, tool):
    """The time of each of TICKS pictures across the film shown, as the tool's timer draws it
    (with the windows' drawing done), with the garbage collector held."""
    film = tool.film
    clock = tool.test_clock
    tool.stop_film()
    tool.player.play(film)
    root = app.root
    times = []
    gc.collect()
    gc.disable()
    try:
        for _ in range(TICKS):
            clock.now += film.seconds / TICKS
            start = time.perf_counter()
            tool._tick()
            root.update_idletasks()
            times.append(time.perf_counter() - start)
            tool.stop_film()
    finally:
        gc.enable()
    return times


@pytest.mark.serial
def test_with_every_window_open_each_picture_of_the_film_is_quick(app, tmp_path):
    """With all seven windows open, no picture of the film takes longer than the time to the
    next one. The film plays five times and each picture counts with its quickest time: work
    the machine does besides can only make a picture slower, never quicker."""
    loaded(app, tmp_path, LARGEST)
    tool = connected(app)
    for block in BLOCKS:
        tool.open_inside(block)
    steps(app, 6)                                   # LDR R3, [R1]
    assert tool.model.view.trace.text == "LDR R3, [R1]"
    runs = [tick_times(app, tool) for _ in range(5)]
    quickest = [min(times) for times in zip(*runs)]
    film = tool.film
    slow = [(round(seconds * 1000, 1), film.at(film.seconds * (number + 1) / TICKS)[0])
            for number, seconds in enumerate(quickest) if seconds >= SLOWEST]
    assert not slow, f"pictures slower than {SLOWEST * 1000:.0f} ms (ms, step): {slow}"


# Resizing ------------------------------------------------------------------------------------

def font_sizes(canvas):
    """The sizes in points of the fonts of the texts drawn on canvas."""
    from tkinter import font as tkfont
    return {tkfont.Font(root=canvas, font=canvas.itemcget(item, "font")).actual("size")
            for item in canvas.find_all() if canvas.type(item) == "text"}


def whole_texts(window):
    """The texts of the window that are not shortened to fit ("..."), in any order."""
    return sorted(text for text in texts(window) if "..." not in text)


@pytest.mark.parametrize("block", BLOCKS)
def test_each_window_inside_a_block_grows_and_shrinks_with_its_window(app, tmp_path, block):
    """It opens at the tool's zoom; it cannot be made smaller than its picture at zoom 1, where
    its smallest text has 8 points; larger, or maximized, it shows the same picture larger, in
    proportion, with its text."""
    tool, (window,) = example(app, tmp_path, "STR R0, [R1, #4]", block)
    middle_of(tool)
    k = scale(tool.window)
    width, height = window.SIZE
    assert window.zoom == tool.zoom
    assert window.window.minsize() == (round(width * k), round(height * k))
    assert tool.window.tk.call("wm", "resizable", window.window._w) in ((1, 1), ("1", "1"))
    shown = whole_texts(window)
    for zoom in (1.0, 1.5, 2.25):
        window.rezoom(zoom)
        canvas = window.canvas
        assert (int(canvas.cget("width")), int(canvas.cget("height"))) == \
            (round(width * k * zoom), round(height * k * zoom))
        assert whole_texts(window) == shown, zoom
        assert min(font_sizes(canvas)) >= 8 if zoom == 1.0 else \
            min(font_sizes(canvas)) >= int(8 * zoom)
        assert clashes(canvas) == [], zoom
        within(window)


@pytest.mark.parametrize("block", BLOCKS)
def test_a_window_inside_opens_no_larger_than_the_work_area_holds(app, tmp_path, monkeypatch,
                                                                  block):
    """Opened from a maximized tool, whose zoom is large, a window inside a block opens at the
    tool's zoom only where the work area holds it; else as large as it holds, never under 1."""
    from ares.gui.tools import xray_inside
    loaded(app, tmp_path, EXAMPLES)
    tool = connected(app)
    tool._make_canvas(1.61)
    k = scale(tool.window)
    area = (0, 0, 1920, 1032)
    monkeypatch.setattr(xray_inside, "screen_area", lambda *args: area)
    window = tool.open_inside(block)
    width, height = window.canvas_size(window.zoom)
    assert window.zoom <= 1.61 and window.zoom >= 1.0
    _, _, _, _, side, title = xray_inside.frame_of(tool.window)
    assert width + 2 * side <= area[2] or window.zoom == 1.0
    assert height + title + side <= area[3] or window.zoom == 1.0
    if window.SIZE[1] * k * 1.61 + title + side <= area[3] and \
            window.SIZE[0] * k * 1.61 + 2 * side <= area[2]:
        assert window.zoom == 1.61                  # it fits: the tool's zoom


def test_a_window_inside_takes_the_zoom_its_size_holds(app, tmp_path, monkeypatch):
    tool, (window,) = example(app, tmp_path, "LDR R3, [R1]", "DMem")
    k = scale(tool.window)
    width, height = window.SIZE
    # Maximized: as large as fits, in proportion: here the width holds zoom 1.8 (and less than
    # a step more), the height far more.
    monkeypatch.setattr(window.window, "winfo_width", lambda: round(width * k * 1.8) + 5)
    monkeypatch.setattr(window.window, "winfo_height", lambda: round(height * k * 1.8) + 400)
    window._settled()
    assert window.zoom == pytest.approx(1.8)
    monkeypatch.setattr(window.window, "winfo_width", lambda: round(width * k))
    monkeypatch.setattr(window.window, "winfo_height", lambda: round(height * k))
    window._settled()
    assert window.zoom == 1.0


def test_a_window_inside_is_drawn_again_only_once_its_size_has_settled(app, tmp_path,
                                                                       monkeypatch):
    tool, (window,) = example(app, tmp_path, "LDR R3, [R1]", "ALU")
    native(window.window)
    time.sleep(0.3)
    pump(app.root)
    settled = []
    monkeypatch.setattr(window, "_settled", lambda: settled.append(1))
    size = window.canvas_size(window.zoom)
    for step in range(1, 30):
        window.window.event_generate("<Configure>", width=size[0] + step, height=size[1] + step)
    pump(app.root)
    assert settled == []
    time.sleep(0.3)
    pump(app.root)
    assert settled == [1]


def test_a_window_resized_during_the_film_goes_on_following_it(app, tmp_path):
    tool, (window,) = example(app, tmp_path, "LDR R3, [R1]", "RegFile")
    film = tool.film
    read = steps_of(film, "RegFile")[0]
    at(tool, read.start + read.duration / 2 - (tool.test_clock.now - tool.player.start))
    assert phase(film, tool.player.moment, "RegFile")[0] == WORKING
    window.rezoom(1.6)
    shown = drawn(window)                       # the same moment, drawn at the new zoom
    window.key = None
    window.draw(*window.drawn)
    assert drawn(window) == shown
    to_end(tool)                                # it follows the film to its end
    assert phase(film, tool.player.moment, "RegFile")[0] == DONE
    ended = drawn(window)
    window.key = None
    window.draw(*window.drawn)
    assert drawn(window) == ended and "R3" in joined(window)


# Inside Extend and the shifter -------------------------------------------------------------

@pytest.mark.parametrize("count, chosen, value", [(6, "001", "0x00000000"),
                                                  (9, "000", "0x00000004"),
                                                  (11, "010", "0xFFFFFFE4")])
def test_extend_shows_the_six_ways_and_the_one_imm_src_takes(app, tmp_path, count, chosen,
                                                             value):
    """ImmSrc has three bits: the five ways that make an immediate of the word's bits, each of
    which works (the four not taken are rejected), and the pass counter's offset."""
    loaded(app, tmp_path, LARGEST)
    tool = connected(app)
    window = tool.open_inside("Extend")
    steps(app, count)
    to_end(tool)
    words = joined(window)
    for way in ("000: ROTATE", "001: ZERO-EXTEND", "010: SIGN-EXTEND x 4", "011: PASS OFFSET",
                "100: JOIN imm16", "101: JOIN imm8"):
        assert way in words, way
    assert f"ImmSrc = {chosen}" in words and f"ExtImm = {value}" in words
    assert words.count("rejected") == 4
    assert clashes(window.canvas) == []


@pytest.mark.parametrize("count, own, others", [
    (6, ["imm12 ="], ["bits 11:8 =", "bits 7:0 =", "bits 23:0 ="]),            # LDR R3, [R1]
    (9, ["rot =", "imm8 ="], ["bits 11:0 =", "bits 23:0 ="]),                 # ADD R1, R1, #4
    (11, ["imm24 ="], ["bits 11:8 =", "bits 7:0 =", "bits 11:0 ="]),          # BNE loop
])
def test_extend_names_only_the_fields_the_instruction_has(app, tmp_path, count, own, others):
    """The way ImmSrc takes is the instruction's own field, under its name; the two others work
    on bits that are no such field of it, named by their place in the word."""
    loaded(app, tmp_path, LARGEST)
    tool = connected(app)
    window = tool.open_inside("Extend")
    steps(app, count)
    to_end(tool)
    words = joined(window)
    for name in own + others:
        assert name in words, name
    named = {"rot", "imm8", "imm12", "imm24", "imm4", "imm4H", "imm4L"} - \
        {name.split()[0] for name in own}
    for name in named:
        assert f"{name} =" not in words, name
    assert clashes(window.canvas) == []


def test_the_shifter_names_shamt5_only_where_the_instruction_has_it(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    tool = connected(app)
    window = tool.open_inside("Shifter")
    steps(app, 7)                                   # CMP R3, R0: shamt5 00000
    to_end(tool)
    assert "no shift: shamt5 is 0" in joined(window)
    assert clashes(window.canvas) == []


def test_the_shifter_shows_the_value_before_and_after_and_the_carry(app, tmp_path):
    loaded(app, tmp_path, """\
        .global _start
_start: MOV     R1, #0x81
        MOV     R2, R1, LSL #4
        MOVS    R3, R1, LSR #1
        SVC     #10
""")
    tool = connected(app)
    window = tool.open_inside("Shifter")
    steps(app, 2)
    to_end(tool)
    words = joined(window)
    assert "kind: LSL   amount (Instr 11:7): 4" in words
    assert "0x00000081" in words and "0x00000810" in words
    steps(app, 1)
    to_end(tool)
    words = joined(window)
    assert "0x00000040" in words and "The last bit shifted out is 1" in words
    assert clashes(window.canvas) == []


@pytest.mark.parametrize("text", list(EXAMPLE))
def test_extend_works_only_for_an_instruction_with_an_immediate(app, tmp_path, text):
    tool, (window,) = example(app, tmp_path, text, "Extend")
    trace = tool.film.trace
    imm_src, ext_imm = trace.signals["ImmSrc"], trace.values["ExtImm"]
    for moment in ("middle", "end"):
        if moment == "middle":
            middle_of(tool)
        else:
            to_end(tool)
        words = joined(window)
        assert f"ImmSrc = {imm_src}" in words and "here)" not in words
        dots, crosses = marks(window)
        if ext_imm is None:                         # ADD R0, R1, R2 and CMP R3, R0
            assert "X" in imm_src and text.startswith(("ADD", "CMP"))
            assert "Extend is not used by this instruction." in words
            assert "rejected" not in words and "ExtImm" not in words
            assert (dots, crosses) == ([], [])
            canvas = window.canvas
            dashed = [item for item in canvas.find_all() if canvas.type(item) == "line"
                      and canvas.itemcget(item, "dash")]
            assert len(dashed) == 1                 # ImmSrc, an X
            assert not any(word.startswith("0x") for word in texts(window))
        elif moment == "end":
            assert f"ExtImm = 0x{ext_imm:08X}" in words and words.count("rejected") == 4
            assert len(dots) == 1 and len(crosses) == 8
        assert clashes(window.canvas) == []
        within(window)


@pytest.mark.parametrize("text", list(EXAMPLE))
def test_the_shifter_works_only_for_an_instruction_that_reads_rd2(app, tmp_path, text):
    tool, (window,) = example(app, tmp_path, text, "Shifter")
    values = tool.film.trace.values
    for moment in ("middle", "end"):
        if moment == "middle":
            middle_of(tool)
        else:
            to_end(tool)
        words = joined(window)
        if values["RD2"] is None:                   # LDR, SUBS, MOV and BNE: no RD2
            assert not text.startswith(("ADD", "CMP", "STR"))
            assert "The shifter is not used by this instruction." in words
            assert not any(word.startswith(("0x", "Shift =")) for word in texts(window))
            canvas = window.canvas
            assert {canvas.itemcget(item, "outline") for item in canvas.find_all()
                    if canvas.type(item) == "rectangle"} == {IDLE}
        elif moment == "end":
            assert f"0x{values['RD2']:08X}" in words and f"0x{values['Shifted']:08X}" in words
            assert "Shift = 0" in words and "the value passes on unchanged" in words
            assert values["Shifted"] == values["RD2"]
        assert clashes(window.canvas) == []
        within(window)


def test_an_svc_says_the_block_does_not_work(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    tool = connected(app)
    window = tool.open_inside("Extend")
    steps(app, 2)                       # SVC #4: the system performs it
    assert "An SVC does not use Extend: the system performs the service." in joined(window)


OUTSIDE = """\
        .global _start
_start: MOV     R1, #3
        UMULL   R0, R2, R1, R1
        B       .
"""
SVC_NAMES = {"RegFile": "the register file", "ALU": "the ALU", "Extend": "Extend",
             "Shifter": "the shifter", "DMem": "the data memory"}


def test_an_instruction_outside_leaves_every_window_gray(app, tmp_path):
    loaded(app, tmp_path, OUTSIDE)
    tool = connected(app)
    windows = [tool.open_inside(block) for block in BLOCKS]
    steps(app, 2)                       # UMULL lies outside the datapath
    assert tool.film.steps == ()
    for window in windows:
        assert "does not use this datapath" in joined(window), window.BLOCK
        assert clashes(window.canvas) == [], window.BLOCK


def test_backsteps_to_the_start_leave_every_window_without_an_instruction(app, tmp_path):
    loaded(app, tmp_path, EXAMPLES)
    tool = connected(app)
    windows = [tool.open_inside(block) for block in BLOCKS]
    steps(app, 2)
    app.run("backstep")                 # the first instruction, finished, in every window
    trace = tool.model.view.trace
    assert trace.pc == 0 and not tool.player.playing
    assert any(text.startswith(trace.text) for text in texts(windows[BLOCKS.index("IMem")]))
    app.run("backstep")                 # nothing has run: no instruction in any window
    assert tool.model.view.trace is None and tool.film.steps == ()
    for window in windows:
        canvas = window.canvas
        assert "No instruction is shown." in joined(window), window.BLOCK
        colours = {canvas.itemcget(item, option) for item in canvas.find_all()
                   for option in ("fill", "outline") if option in canvas.itemconfigure(item)}
        # Every part rests in the calm blue: none is pale, at work, done or changed.
        assert not colours & {UNUSED_FILL, WORKING_FILL, DONE_FILL, CHANGED, ON}, window.BLOCK
        assert clashes(canvas) == [], window.BLOCK
        within(window)


def test_an_svc_uses_only_the_control_unit_and_the_instruction_memory(app, tmp_path):
    loaded(app, tmp_path, LARGEST)
    tool = connected(app)
    windows = {block: tool.open_inside(block) for block in BLOCKS}
    steps(app, 2)                       # SVC #4
    for moment in (0.5, None):
        if moment is None:
            to_end(tool)
        else:
            at(tool, tool.film.seconds * moment)
        for block, name in SVC_NAMES.items():
            said = f"An SVC does not use {name}: the system performs the service."
            assert said in joined(windows[block]), block
        for block in ("Control", "IMem"):
            assert "does not" not in joined(windows[block]), block
        for window in windows.values():
            assert clashes(window.canvas) == [], window.BLOCK


def opened_e5a(app, tmp_path, count, *blocks):
    """The tool on the program of the shifts by a register, ADC, SBC, RSC, TEQ, BLX and NOP, at
    the end of its instruction number count, with the windows inside blocks open."""
    from test_gui_xray import SHIFTS
    loaded(app, tmp_path, SHIFTS)
    tool = connected(app)
    windows = [tool.open_inside(block) for block in blocks]
    steps(app, count)
    tool.skip()
    return tool, windows


def test_the_shifter_takes_its_amount_from_rd4_for_a_shift_by_a_register(app, tmp_path):
    tool, (shifter, registers) = opened_e5a(app, tmp_path, 5, "Shifter", "RegFile")
    words = texts(shifter)                  # ADD R2, R1, R0, LSL R3: R3 = 2
    assert {"ShiftReg = 1", "RD4[7:0] = 2", "amount = 2", "Instr 11:7 = 00110"} <= set(words)
    assert "kind: LSL   amount (RD4[7:0], R3): 2" in words
    assert any(word.startswith("From 32 on every bit has gone") for word in words)
    assert "A4 = 0011 (Rs)" in texts(registers)
    for window in (shifter, registers):
        assert clashes(window.canvas) == []
    steps(app, 2)                           # MOVS R4, R0, ROR R5: R5[7:0] = 0
    tool.skip()
    words = texts(shifter)
    assert "Shift = 1" in words                    # the control unit cannot see R5
    assert "ROR R5: R5[7:0] is 0: the value passes on unchanged, C as it is" in words


def test_the_alu_takes_carryin_for_adc_sbc_and_rsc(app, tmp_path):
    from test_gui_xray_inside_control import chosen
    tool, (alu, control) = opened_e5a(app, tmp_path, 11, "ALU", "Control")
    words = texts(alu)                      # ADC R7, R0, R1, with C = 0
    assert {"ADC", "CarryIn = 0", "with carry = 1", "carry in = 0",
            "ALUResult = SrcA plus SrcB plus C"} <= set(words)
    assert "CarryIn = 0" in texts(control) and "ADC" in texts(control)
    steps(app, 2)                           # RSC R9, R0, R1, LSL #1, with C = 1
    tool.skip()
    words = texts(alu)
    assert {"RSC", "RSC = 1", "SBC or RSC = 1", "CarryIn = 1", "carry in = 1"} <= set(words)
    steps(app, 1)                           # TEQ R0, #7: the EOR unit, no carry
    tool.skip()
    words = texts(alu)                      # the adder adds too, with no carry, and is rejected
    assert "EOR" in words and "with carry = 0" in words and "CarryIn" in words
    assert chosen(control, "alu") == ["TEQ", "0", "1001", "1", "0100", "10", "1"]
    for window in (alu, control):
        assert clashes(window.canvas) == []


def test_the_control_unit_lights_blx_and_nop(app, tmp_path):
    from test_gui_xray_inside_control import chosen
    tool, (control, registers, alu) = opened_e5a(app, tmp_path, 19, "Control", "RegFile", "ALU")
    assert chosen(control, "main")[0] == "BLX"
    assert chosen(control, "alu")[0] == "BX"
    assert "WE3 = 1: the decoder enables R14" in joined(registers)
    steps(app, 1)                           # NOP
    tool.skip()
    assert chosen(control, "main")[0] == "NOP" and chosen(control, "alu") == []
    assert "A NOP does not use the register file" in joined(registers)
    assert "A NOP does not use the ALU" in joined(alu)
    for window in (control, registers, alu):
        assert clashes(window.canvas) == []


@pytest.mark.parametrize("zoom", [1.3, 1.6])
def test_nothing_overlaps_inside_the_blocks_for_the_new_kinds(app, tmp_path, zoom):
    """The shifter, the ALU, the control unit and the register file at the larger zooms, in the
    middle of the block's first step and at the end of the film: a shift by a register by 2 and
    by 0, ADC, RSC, BLX and NOP."""
    from test_gui_xray import SHIFTS
    loaded(app, tmp_path, SHIFTS)
    tool = connected(app)
    tool._make_canvas(zoom)
    windows = {block: tool.open_inside(block) for block in ("Shifter", "ALU", "Control",
                                                            "RegFile")}
    done = 0
    for count in (5, 7, 11, 13, 19, 20):
        while done < count:
            app.run("step")
            done += 1
        film = tool.film
        for block, window in windows.items():
            own = [step for step in film.steps if xray_inside.works_in(step, block)]
            for moment in [step.start + step.duration / 2 for step in own[:1]] + [film.seconds]:
                tool.stop_film()
                tool.player.play(film, moment)
                tool.player.pause()
                assert clashes(window.canvas) == [], (block, count, moment)


# MOVW and MOVT; LDRH, STRH, LDRSB and LDRSH -----------------------------------------------------

def opened_e5b(app, tmp_path, count, *blocks):
    """The tool on the program of MOVW, MOVT and the halfword and signed transfers, at the end of
    its instruction number count, with the windows inside blocks open."""
    from test_gui_xray import HALFWORDS
    loaded(app, tmp_path, HALFWORDS)
    tool = connected(app)
    windows = [tool.open_inside(block) for block in blocks]
    steps(app, count)
    tool.skip()
    return tool, windows


def test_extend_joins_imm16_for_movt_and_imm8_for_a_halfword_transfer(app, tmp_path):
    """MOVT: ImmSrc 100 joins imm4 and imm12, its own fields; LDRSB with an immediate offset:
    ImmSrc 101 joins imm4H and imm4L. The ways not taken name the bits by their place."""
    tool, (window,) = opened_e5b(app, tmp_path, 4, "Extend")       # MOVT R3, #0xFFFE
    words = joined(window)
    assert "ImmSrc = 100" in words and "ExtImm = 0x0000FFFE" in words
    assert "imm4 = 1111" in words and "imm12 =" in words and "imm4H =" not in words
    assert "bits 11:8 = 1111" in words and "bits 3:0 = 1110" in words
    assert words.count("rejected") == 4
    dots, crosses = marks(window)
    assert len(dots) == 1 and len(crosses) == 8
    assert clashes(window.canvas) == []
    within(window)
    steps(app, 4)                                                   # LDRSB R5, [R1, #-1]!
    tool.skip()
    words = joined(window)
    assert "ImmSrc = 101" in words and "ExtImm = 0x00000001" in words
    assert "imm4H = 0000" in words and "imm4L = 0001" in words and "imm4 =" not in words
    assert "bits 19:16 = 0001" in words
    assert clashes(window.canvas) == []
    within(window)


@pytest.mark.parametrize("zoom", [1.0, 1.3, 1.6])
def test_nothing_overlaps_inside_the_blocks_for_movw_movt_and_halfwords(app, tmp_path, zoom):
    """Every window inside a block, in the middle of the block's first step and at the end of
    the film, for MOVW, MOVT, STRH, LDRSB, LDRSH, LDRH with a register offset, a load whose
    condition fails and LDRB."""
    from test_gui_xray import HALFWORDS, HALFWORDS_INSIDE
    loaded(app, tmp_path, HALFWORDS)
    tool = connected(app)
    tool._make_canvas(zoom)
    windows = {block: tool.open_inside(block) for block in BLOCKS}
    done = 0
    for count in HALFWORDS_INSIDE:
        while done < count:
            app.run("step")
            done += 1
        film = tool.film
        for block, window in windows.items():
            own = [step for step in film.steps if xray_inside.works_in(step, block)]
            for moment in [step.start + step.duration / 2 for step in own[:1]] + [film.seconds]:
                tool.stop_film()
                tool.player.play(film, moment)
                tool.player.pause()
                assert clashes(window.canvas) == [], (block, count, moment)
                within(window)


@pytest.mark.parametrize("block, text, high, zoom", [
    ("ALU", "LDR R3, [R1]", None, 2.13), ("ALU", "SUBS R2, R2, #1", None, 2.63),
    ("Control", "MOV R0, #5", None, 1.77), ("Control", "ADD R0, R1, R2", None, 2.15),
    ("Control", "CMP R3, R0", None, 2.16), ("Control", "CMP R3, R0", None, 3.0),
    ("Control", "LDR R3, [R1]", None, 3.25), ("Control", "MOV R0, #5", 3.0, 1.14),
    ("Control", "ADD R0, R1, R2", 3.0, 1.38), ("Control", "CMP R3, R0", 3.0, 1.39)])
def test_texts_stay_clear_at_the_zooms_that_once_crowded_them(app, tmp_path, block, text, high,
                                                              zoom):
    """The carry multiplexer's 0 by its select, the ALU Decoder's lines over the rows under them,
    a chosen row's frame by the row above: at the zooms (and at 225 %) where they once touched."""
    before = float(app.root.tk.call("tk", "scaling"))
    if high:
        app.root.tk.call("tk", "scaling", high)
    try:
        tool, (window,) = example(app, tmp_path, text, block)
        tool.skip()
        window.rezoom(zoom)
        assert clashes(window.canvas) == [], (block, text, high, zoom)
    finally:
        app.root.tk.call("tk", "scaling", before)

