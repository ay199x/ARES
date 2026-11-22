# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Inside the instruction memory and inside the data memory: the windows of ARM X-Ray for these
two blocks.

Each window shows the words around the address its block is given, four before it and four
after it, with their addresses: the instruction memory the instruction each word holds, the
data memory each word's four bytes, the byte at the lowest address first. The word read or
written is lit. The windows read the memory with the tool's peek, which never touches a device:
where there is no memory they say which device of the DE1-SoC is there, or that there is none.

The table shows the memory as it was before the instruction. When the instruction has run, the
peek gives the memory after it, so the bytes its writes replaced are put back; for a store that
has not run yet, the memory after it is the memory now with WD's bytes written in.

In the block's step of the film its inputs arrive first, then it works (lit, with its word),
then its result leaves; a store's new value comes in at the end of the step, where the clock
edge writes it. A load has no data to write and a store reads nothing: WD of a load and RD of
a store stay gray and say that they are not used by the instruction. The block waits in the
calm blue before its step and keeps a lighter tint after it; one the instruction does not use
stays pale. The word read is framed on a tint of the colour of the value it gives, the word a
store writes on a tint of the data's colour until the clock edge, and on the green of a change
after it.

Size says how many bytes the data memory moves: a word, a halfword or a byte. What a load reads
goes through the load extender, at the right of the data memory before RD: it fills the bits
above a halfword or a byte with zeros, or, when Signed is 1, with copies of its sign bit. Only a
load uses it; for any other instruction it stays gray.
"""

from ... import xray
from ...devices import (EDGE_CAPTURE, HEX3_HEX0, HEX5_HEX4, INTERRUPT_MASK, KEYS, LEDS, PORT_SIZE,
                        SWITCHES)
from ...disasm import basic
from ...machine import DEVICES_BASE, DEVICES_SIZE, JTAG_UART, JTAG_UART_SIZE
from ...xray_film import hex32
from .xray_inside import (CHANGED, DIM, DONE, DONE_FILL, IDLE, IDLE_STATE, INK, INSIDE, LOOKS,
                          MARK, UNUSED, UNUSED_LINES, WAITING_FILL, WORKING, WORKING_FILL,
                          InsideWindow, gray_on, signal_colour, steps_of, system_note)
from .xray_look import rest
from .xray_picture import IDLE_32, IDLE_BIT, WIDTH_32, WIDTH_BIT

MASK = 0xFFFFFFFF
AROUND = 4                      # the words shown before the one at the address, and after it
ROW = 20                        # design pixels from one row of the table to the next
ARRIVE = 0.3                    # the inputs arrive in this share of the block's step,
LEAVE = 0.7                     # the result leaves from this share of it on
GROW = 0.15                     # and takes this share of it to reach the end of its wire
LATER = "not here yet"

# The DE1-SoC's devices: (first address, bytes, name in a row, name in a sentence, a part of
# the board that the Digital Lab Sim brings to life).
DEVICES = (
    (JTAG_UART, 4, "JTAG UART data", "the JTAG UART's data register", False),
    (JTAG_UART + 4, JTAG_UART_SIZE - 4, "JTAG UART control", "the JTAG UART's control register",
     False),
    (LEDS, PORT_SIZE, "red LEDs", "the red LEDs LEDR9-0", True),
    (HEX3_HEX0, PORT_SIZE, "displays HEX3-0", "the seven-segment displays HEX3-HEX0", True),
    (HEX5_HEX4, PORT_SIZE, "displays HEX5-4", "the seven-segment displays HEX5 and HEX4", True),
    (SWITCHES, PORT_SIZE, "switches SW9-0", "the slide switches SW9-0", True),
    (INTERRUPT_MASK, 4, "keys Interruptmask", "the push buttons' Interruptmask register", True),
    (EDGE_CAPTURE, 4, "keys Edgecapture", "the push buttons' Edgecapture register", True),
    (KEYS, PORT_SIZE, "push buttons KEY3-0", "the push buttons KEY3-0", True),
)
NO_MEMORY = "no memory here"


def device_at(address):
    """What a program reaches at address, where the peek finds no memory: (the name for a row,
    a sentence for it, True for a device ARES simulates, True for a part of the board)."""
    address &= MASK
    for first, size, short, name, board in DEVICES:
        if first <= address < first + size:
            return short, f"it is the address of {name}, a device of the DE1-SoC", True, board
    if DEVICES_BASE <= address < DEVICES_BASE + DEVICES_SIZE:
        return NO_MEMORY, ("it is among the addresses of the DE1-SoC's devices, but no device "
                           "is simulated there: reads give 0 and writes are ignored"), False, False
    return NO_MEMORY, "nothing is there, and an access stops the program with a runtime error", \
        False, False


def memory_before(context):
    """What reads the memory as it was before the instruction: the peek, with the bytes the
    instruction's writes replaced put back. It gives None where there is no memory."""
    peek, writes = context.peek, context.writes

    def read(address, size):
        data = peek(address & MASK, size)
        if data is None or not writes:
            return data
        data = bytearray(data)
        for start, old, _ in reversed(writes):
            for index, byte in enumerate(old):
                offset = (start + index - address) & MASK
                if offset < size:
                    data[offset] = byte
        return bytes(data)
    return read


def light_word(film, block):
    """What block says it does in its step of film, as the picture shows it ("" for nothing)."""
    for step in steps_of(film, block):
        for name, word in step.lights:
            if name == block:
                return word
    return ""


def value_of(data):
    return None if data is None else int.from_bytes(data, "little")


class _MemoryWindow(InsideWindow):
    """What the windows of the two memories share: the block with its ports and its table of
    words, and how its step of the film plays."""

    NAME = ""                       # the block's name, written in it
    LEFT, RIGHT, TOP, BOTTOM = 180, 600, 56, 292
    IN_X, OUT_X = 24, 720           # where the inputs' wires start and the output's wire ends
    MIDDLE = None                   # where the words of a block that does not work stand,
    WORDS_WIDTH = None              # and how wide they may be (None: one line)

    def row_y(self, number):
        return self.TOP + 48 + number * ROW

    def measure(self, text, font="code"):
        """The width of text in design pixels."""
        return self.fonts[font].measure(text) / self.k

    def fit(self, text, width, font="code"):
        """text, shortened with "..." when it is wider than width design pixels."""
        if self.measure(text, font) <= width:
            return text
        while text and self.measure(text + "...", font) > width:
            text = text[:-1]
        return text + "..."

    def struck(self):
        """The name of the font of a value struck out: the code font with a line through it."""
        if "code_struck" not in self.fonts:
            font = self.fonts["code"].copy()
            font.configure(overstrike=1)
            self.fonts["code_struck"] = font
        return "code_struck"

    # What moves within the block's step ---------------------------------------------------

    def begin(self, state, trace):
        """Start a picture for state of trace's instruction: within the block's step, what
        changes is kept for animate(). With no instruction shown (trace None) the block rests
        in the calm blue."""
        self._moving = {"in": [], "out": [], "looks": []} if state == WORKING else None
        self._reached = None
        self.resting = trace is None
        self.gray = IDLE                # the gray of what is not in use on the block: block()

    def look(self, item, state, before, working=None, left=None, idle=None, done=None):
        """Give item its options for now. Within the block's step: before until the inputs
        arrive, working while the block works, left once the result has left. Before the step
        idle (else before), after it done (else the last of them given)."""
        working = before if working is None else working
        left = working if left is None else left
        if state == WORKING:
            self._moving["looks"].append((item, (before, working, left)))
            return
        options = (before if idle is None else idle) if state == IDLE_STATE else \
            (left if done is None else done)
        if options:
            self.canvas.itemconfigure(item, **options)

    def wire(self, points, colour, width, state, way, tags):
        """A value's own line over its gray wire: none before the block's step, growing along
        the wire while it travels in the step (way "in" or "out"), whole after it."""
        item = self.line(points, fill=colour, width=width, arrow="last", tags=tags)
        if state != DONE:
            self.canvas.itemconfigure(item, state="hidden")
        if state == WORKING:
            self._moving[way].append([item, points, 0.0])
        return item

    def animate(self, film, moment, context, state, fraction):
        moving = getattr(self, "_moving", None)
        if moving is None or state != WORKING:
            return
        come = min(1.0, fraction / ARRIVE)
        go = min(1.0, max(0.0, (fraction - LEAVE) / GROW))
        for entry in moving["in"]:
            self._grow(entry, come)
        for entry in moving["out"]:
            self._grow(entry, go)
        reached = 2 if go >= 1 else 1 if fraction >= ARRIVE else 0
        if reached == self._reached:
            return
        self._reached = reached
        for item, looks in moving["looks"]:
            if looks[reached]:
                self.canvas.itemconfigure(item, **looks[reached])

    def _grow(self, entry, share):
        item, points, drawn = entry
        if share == drawn:
            return
        entry[2] = share
        if share <= 0:
            self.canvas.itemconfigure(item, state="hidden")
            return
        (x1, y1), (x2, y2) = points
        tip = (x1 + (x2 - x1) * share, y1 + (y2 - y1) * share)
        self.canvas.coords(item, *self.flat([(x1, y1), tip]))
        self.canvas.itemconfigure(item, state="normal")

    # The parts of the picture -------------------------------------------------------------

    def block(self, state, word):
        """The block's outline, its name and its word. A block with a word works in its step:
        it waits in the calm blue for its inputs, lights once they have arrived and keeps a
        lighter tint after its step. One without stays pale, as the picture leaves it, or with
        no instruction shown rests in the calm blue."""
        tags = (f"block:{self.BLOCK}",)
        idle = LOOKS["waiting" if word or self.resting else "unused"]
        self.gray = gray_on(idle.fill)  # what is not in use, readable on the block
        outline = self.box(self.LEFT, self.TOP, self.RIGHT, self.BOTTOM, outline=idle.outline,
                           fill=idle.fill, tags=tags)
        name = self.text((self.LEFT + self.RIGHT) / 2, self.BOTTOM - 5, self.NAME, anchor="s",
                         font="bold", fill=idle.words, tags=tags)
        said = self.text(self.LEFT + 8, self.TOP + 6, "", font="bold", fill=INK, tags=tags)
        if not word:
            return
        ready = {"outline": INK, "width": self.d(1.6), "fill": WAITING_FILL}
        self.look(outline, state, ready, dict(ready, fill=WORKING_FILL),
                  idle={"outline": DIM, "width": self.d(1), "fill": WAITING_FILL},
                  done=dict(ready, fill=DONE_FILL))
        self.look(name, state, {"fill": INK}, idle={"fill": DIM})
        self.look(said, state, {"text": ""}, {"text": word})

    def port(self, x, y, text, anchor, state, works=True):
        """The name of a port, inside the block: gray while the block does not work through it,
        in the gray that reads on the block's fill."""
        return self.text(x, y, text, anchor=anchor,
                         fill=INK if works and state != IDLE_STATE else self.gray,
                         tags=(f"block:{self.BLOCK}",))

    def input(self, net, y, value, state, closed=False, used=True, note=""):
        """A value that comes in from the left at height y: its gray wire, its own line over it
        in the net's colour (thinner, with a bar at the port, when a closed write keeps it out),
        its name above the wire and its value under it. One that is not used has only its gray
        wire and name, and note under the wire."""
        tags = (f"wire:{net}",)
        points = [(self.IN_X, y), (self.LEFT, y)]
        self.line(points, fill=IDLE, width=IDLE_32, arrow="last", tags=tags)
        name = self.text(self.IN_X + 4, y - 5, net, anchor="sw", fill=IDLE, tags=tags)
        if note:
            self.text(self.IN_X + 4, y + 5, note, anchor="nw", fill=IDLE, tags=tags)
        if not used:
            return
        colour = self.colour(net)
        shown = self.text(self.IN_X + 4, y + 5, "", anchor="nw", font="code", tags=tags)
        self.look(name, state, {"fill": IDLE}, {"fill": INK})
        self.look(shown, state, {"text": LATER, "fill": IDLE}, {"text": value, "fill": colour})
        self.wire(points, colour, max(WIDTH_32 * 0.6, WIDTH_BIT) if closed else WIDTH_32, state,
                  "in", tags)
        if closed:
            x = self.LEFT - 6
            bar = self.line([(x, y - 6), (x, y + 6)], fill=MARK, width=2.4, tags=tags)
            self.look(bar, state, {"state": "hidden"}, {"state": "normal"})

    def output(self, net, y, value, state, used=True, note=""):
        """The value that leaves at the right at height y: its gray wire, its own line growing
        out of the block in the net's colour, its name above the wire and its value under it.
        One that is not used has only its gray wire and name, and note under the wire."""
        tags = (f"wire:{net}",)
        points = [(self.RIGHT, y), (self.OUT_X, y)]
        self.line(points, fill=IDLE, width=IDLE_32, arrow="last", tags=tags)
        name = self.text(self.RIGHT + 8, y - 5, net, anchor="sw", fill=IDLE, tags=tags)
        if note:
            self.text(self.RIGHT + 8, y + 5, note, anchor="nw", fill=IDLE, tags=tags)
        if not used:
            return
        colour = self.colour(net)
        shown = self.text(self.RIGHT + 8, y + 5, "", anchor="nw", font="code", fill=colour,
                          tags=tags)
        self.look(name, state, {"fill": IDLE}, None, {"fill": INK})
        self.look(shown, state, {"text": ""}, None, {"text": value})
        self.wire(points, colour, WIDTH_32, state, "out", tags)

    def lines_below(self, lines, state, top):
        """Sentences under the block on what it did: shown once its result has left."""
        for number, line in enumerate(lines):
            item = self.text(16, top + 18 * number, "", fill=INK)
            self.look(item, state, {"text": ""}, None, {"text": line})

    def outside(self, trace, ports):
        """No instruction, or one outside the datapath: the block stays pale (with no
        instruction it rests in the calm blue), with one line. ports: (net, port, y, side) of
        the wires at the sides, gray."""
        self.block(IDLE_STATE, "")
        self.parts_inside()
        for net, port, y, side in ports:
            if side == "in":
                self.input(net, y, "", IDLE_STATE, used=False)
                self.port(self.LEFT + 6, y, port, "w", IDLE_STATE)
            else:
                self.output(net, y, "", IDLE_STATE, used=False)
                self.port(self.RIGHT - 6, y, port, "e", IDLE_STATE)
        why = "No instruction is shown." if trace is None else \
            system_note(trace, "the data memory") or "This instruction does not use this datapath."
        middle = self.MIDDLE or (self.LEFT + self.RIGHT) / 2
        wrap = {"width": self.WORDS_WIDTH * self.k, "justify": "center"} if self.WORDS_WIDTH \
            else {}
        self.text(middle, (self.TOP + self.BOTTOM) / 2, why, anchor="center", fill=INK,
                  tags=(f"block:{self.BLOCK}",), **wrap)

    def parts_inside(self):
        """What the block holds besides its table, not in use, under the names of its ports:
        nothing here; the data memory has its load extender."""

    def frame(self, left, right, y, state, colour, written=False):
        """The frame around the row lit, from the moment the inputs arrive: on a tint of colour,
        the colour of the value read or written there, and for a word written (written) on the
        green of a change from the clock edge on."""
        item = self.box(left, y - ROW / 2 + 1, right, y + ROW / 2 - 1, outline="", fill="")
        on = {"outline": INK, "width": self.d(1.2), "fill": rest(colour)[0]}
        self.look(item, state, {"outline": "", "fill": ""}, on,
                  dict(on, fill=CHANGED) if written else None)
        return item


class InstructionMemoryWindow(_MemoryWindow):
    """Inside the instruction memory (see the module's description)."""

    BLOCK = "IMem"
    TITLE = "Inside the Instruction Memory"
    HEADING = "Words Around the PC"
    ABOUT = ("The instruction memory puts the word at address A on RD: the instruction to\n"
             "run. A word is 4 bytes, so the addresses go up by 4. The PC gives A: the\n"
             "address of this instruction.")
    NAME = "Instruction Memory"
    SIZE = (740, 344)

    def redraw(self, film, moment, context, state, fraction):
        trace = context.trace
        self.begin(state, trace)
        self.heading(16, 10)
        y = self.row_y(AROUND)
        if trace is None or not trace.signals:
            self.outside(trace, (("PC", "A", y, "in"), ("Instr", "RD", y, "out")))
            return
        pc = trace.pc & MASK
        self.block(state, light_word(film, self.BLOCK))
        self.port(self.LEFT + 6, y, "A", "w", state)
        rd = self.port(self.RIGHT - 6, y, "RD", "e", state)
        self.input("PC", y, hex32(pc), state)
        self.output("Instr", y, hex32(trace.word), state)
        # The table: address, word and instruction of each word.
        digits = self.measure("0x00000000")
        x_address = self.LEFT + 26
        x_word = x_address + digits + 16
        x_text = x_word + digits + 16
        rd_left = self.canvas.bbox(rd)[0] / self.k
        ink = {"fill": INK}
        dim = {"fill": self.gray}
        for x, title in ((x_address, "Address"), (x_word, "Word"), (x_text, "Instruction")):
            item = self.text(x, self.TOP + 28, title, anchor="w")
            self.look(item, state, ink, idle=dim)
        read = memory_before(context)
        for number in range(2 * AROUND + 1):
            address = (pc + 4 * (number - AROUND)) & MASK
            row = self.row_y(number)
            if number == AROUND:
                word, text = trace.word, trace.text
                self.frame(x_address - 6, rd_left - 6, row, state, self.colour("Instr"))
                room = rd_left - 12 - x_text
            else:
                word = value_of(read(address, 4))
                text = "-" if word is None else basic(word, address)
                room = self.RIGHT - 8 - x_text
            texts = (f"0x{address:08X}", "-" if word is None else f"0x{word:08X}",
                     self.fit(text, room))
            for x, said in zip((x_address, x_word, x_text), texts):
                item = self.text(x, row, said, anchor="w", font="code")
                if number == AROUND:
                    self.look(item, state, dict(ink, font=self.fonts["code"]),
                              dict(ink, font=self.fonts["code_bold"]),
                              idle=dict(dim, font=self.fonts["code"]))
                else:
                    self.look(item, state, ink, idle=dim)
        said = f"The word at {hex32(pc)} is {hex32(trace.word)}: the instruction "
        room = self.SIZE[0] - 24 - self.measure(said + ".", "small")
        name = self.fit(xray.named(context.view.written, trace.text), room, "small")
        self.lines_below((f"{said}{name}.",     # as the student wrote it, else its Basic form
                          "It leaves on RD as Instr, and then splits into its fields."),
                         state, self.BOTTOM + 14)


class DataMemoryWindow(_MemoryWindow):
    """Inside the data memory (see the module's description)."""

    BLOCK = "DMem"
    TITLE = "Inside the Data Memory"
    HEADING = "Words Around the Address"
    ABOUT = ("The data memory reads at address A and puts what it reads on RD; when WE is 1,\n"
             "it writes WD there, at the clock edge. Size: a word (00), a halfword (01) or a\n"
             "byte (10). The load extender widens a halfword or a byte read to 32 bits.")
    NAME = "Data Memory"
    SIZE = (760, 420)
    LEFT, RIGHT, TOP, BOTTOM = 172, 672, 80, 324
    OUT_X = 744
    WD_Y = 304                      # the height of the WD port
    SIZE_X, WE_X = 300, 450         # where Size and WE come in at the top
    TABLE_RIGHT = 548               # the table of words ends here; the load extender follows
    MIDDLE, WORDS_WIDTH = (LEFT + TABLE_RIGHT) / 2, 320
    EXTENDER = (556, 150, 672, 266)     # left, top, right, bottom: the load extender, before RD
    SIZE_IN, SIGNED_X = 572, 640    # where Size and Signed come into the load extender
    MEANINGS = {xray.SIZE_WORD: "a whole word", xray.SIZE_HALF: "a halfword",
                xray.SIZE_BYTE: "one byte"}

    def redraw(self, film, moment, context, state, fraction):
        trace = context.trace
        self.begin(state, trace)
        self.heading(16, 10)
        y = self.row_y(AROUND)
        if trace is None or not trace.signals or system_note(trace, ""):
            self.outside(trace, (("Address", "A", y, "in"), ("WriteData", "WD", self.WD_Y, "in"),
                                 ("ReadData", "RD", y, "out")))
            self.signal("Size", "Size", self.SIZE_X, "", "", IDLE_STATE, used=False)
            self.signal("MemWrite", "WE", self.WE_X, "", "", IDLE_STATE, used=False)
            return
        s, v = trace.signals, trace.values
        uses = s["MemW"] == "1" or s["MemtoReg"] == "1"
        # The address comes from the AdrSrc multiplexer: ALUResult, or for post-indexing RD1.
        address = (v["Address"] if uses and v.get("Address") is not None else v["ALUResult"]) & MASK
        runs = s["CondEx"] == "1"
        load = s["MemtoReg"] == "1" and runs
        store = s["MemWrite"] == "1"
        writes = v["WriteData"] is not None             # a store, whether it runs or not
        size = xray.SIZES[s["Size"]]
        word = light_word(film, self.BLOCK).replace("\n", " ")    # one line: the block is wide
        self.block(state, word)
        works = bool(word)
        self.extender(trace, state, y, works and load and not writes,
                      comes=uses and s["MemtoReg"] == "1")
        self.port(self.LEFT + 6, y, "A", "w", state, works)
        self.port(self.LEFT + 6, self.WD_Y, "WD", "w", state, works and writes)
        self.port(self.RIGHT - 6, y, "RD", "e", state, works and not writes)
        self.signal("Size", "Size", self.SIZE_X, s["Size"], self.MEANINGS[s["Size"]], state,
                    works=works)
        self.signal("MemWrite", "WE", self.WE_X, s["MemWrite"], "open" if store else "closed",
                    state, works=works)
        if not uses:
            self.unused(address, y, state)
            return
        self.input("Address", y, hex32(address), state)
        if writes:
            self.input("WriteData", self.WD_Y, hex32(v["WriteData"]), state, closed=not store)
        else:                           # a load has no data to write
            self.input("WriteData", self.WD_Y, "", state, used=False, note=UNUSED)
        # A read that cannot be known yet (a device not read yet), or that stopped the program,
        # sends nothing on, as in the picture; a store reads nothing.
        self.output("ReadData", y, hex32(v["ReadData"]), state,
                    used=load and v["ReadData"] is not None,
                    note=UNUSED_LINES if writes else "")
        first = ((address & ~3) - 4 * AROUND) & MASK
        rows = [(first + 4 * number) & MASK for number in range(2 * AROUND + 1)]
        read = memory_before(context)
        olds = [read(row, 4) for row in rows]
        data = None
        if store:
            data = (v["WriteData"] & (1 << 8 * size) - 1).to_bytes(size, "little")
        news = self.after(context, rows, olds, address, data) if store else olds
        touched = [(address + number) & MASK for number in range(size)] if load or store else []
        self.table(rows, olds, news, touched, store, "ReadData" if load else "WriteData", state,
                   works)
        old = value_of(read(address, size))
        new = None
        if store:
            ran = context.registers_after is not None
            new = value_of(context.peek(address, size) if ran else data)
        self.lines_below(self.sentences(trace, address, olds[AROUND], old, new, load, store,
                                        size, runs), state, self.BOTTOM + 14)

    def parts_inside(self):
        self.extender(None, IDLE_STATE, self.row_y(AROUND))

    def extender(self, trace, state, y, works=False, comes=False):
        """The load extender, at the block's right before RD: Size, a branch of the wire that
        comes into the memory, and Signed come in at its top; it takes what the memory read and
        fills the bits above a halfword or a byte with zeros, or with copies of its sign bit when
        Signed is 1. Only a load that runs uses it (works): else it stays gray. Size's branch and
        Signed come with every load (comes), as they reach the data memory in the picture, also
        when its condition fails and nothing is read. Its wires inside the data memory are in
        the gray that reads on the block's fill."""
        left, top, right, bottom = self.EXTENDER
        tags = ("block:Extender",)
        idle = LOOKS["waiting" if works or self.resting else "unused"]
        edge = self.gray if idle.outline == IDLE else idle.outline     # it lies on the block
        outline = self.box(left, top, right, bottom, outline=edge, fill=idle.fill, tags=tags)
        title = self.text(left + 6, top + 22, "Load extender", font="bold", fill=idle.words,
                          tags=tags)
        names = [self.text(x, top + 3, name, anchor="n", fill=idle.words, tags=tags)
                 for x, name in ((self.SIZE_IN, "Size"), (self.SIGNED_X, "Signed"))]
        branch = [[(self.SIZE_X, self.TOP - 24), (self.SIZE_IN, self.TOP - 24)],
                  [(self.SIZE_IN, self.TOP - 24), (self.SIZE_IN, top)]]
        stub = [(self.SIGNED_X, self.TOP - 30), (self.SIGNED_X, top)]
        for points, arrow, net in ((branch[0], "none", "Size"), (branch[1], "last", "Size"),
                                   (stub, "last", "Signed")):
            self.line(points, fill=self.gray, width=IDLE_BIT, arrow=arrow, tags=(f"wire:{net}",))
        read = [(self.TABLE_RIGHT, y), (left, y)]
        self.line(read, fill=self.gray, width=IDLE_32, arrow="last", tags=("wire:Read",))
        said = self.text(self.SIGNED_X + 6, self.TOP - 16, "Signed", anchor="w", fill=IDLE,
                         tags=("wire:Signed",))
        if trace is None:
            return
        s, value = trace.signals, trace.values["ReadData"]
        if comes:                       # Signed and Size's branch, with their values
            colour = signal_colour(s["Signed"])
            self.look(said, state, {"text": f"Signed: {LATER}", "fill": IDLE},
                      {"text": f"Signed = {s['Signed']}", "fill": colour})
            self.wire(stub, colour, WIDTH_BIT, state, "in", ("wire:Signed",))
            size_colour = signal_colour(s["Size"])
            for points in branch:
                self.wire(points, size_colour, WIDTH_BIT, state, "in", ("wire:Size",))
        if not works:                   # a store, no access, a failed condition: it widens nothing
            self.text(left + 6, top + 40, "nothing is read:\nthe condition failed" if comes
                      else UNUSED_LINES, fill=IDLE, tags=tags)
            return
        ready = {"outline": INK, "width": self.d(1.6), "fill": WAITING_FILL}
        self.look(outline, state, ready, dict(ready, fill=WORKING_FILL),
                  idle={"outline": DIM, "width": self.d(1), "fill": WAITING_FILL},
                  done=dict(ready, fill=DONE_FILL))
        for item in [title] + names:
            self.look(item, state, {"fill": DIM}, {"fill": INK})
        line = self.line(read, fill=self.colour("ReadData"), width=WIDTH_32, arrow="last",
                         tags=("wire:Read",))
        self.look(line, state, {"state": "hidden"}, {"state": "normal"})
        count = xray.SIZES[s["Size"]]
        if value is None:               # a device not read yet: nothing comes in
            lines = ("in: not known yet", "", "")
        else:
            raw, high = value & (1 << 8 * count) - 1, 8 * count
            shown = f"in: 0x{raw:0{2 * count}X}"
            if count == 4:
                lines = (shown, "a word: it passes", "on unchanged")
            elif s["Signed"] == "1":
                lines = (shown, f"sign bit {raw >> high - 1} copied", f"into bits 31:{high}")
            else:
                lines = (shown, f"zeros in bits 31:{high}", "")
        for number, (text, at) in enumerate(zip(lines, (40, 72, 88))):
            item = self.text(left + 6, top + at, "", font="code" if number == 0 else "small",
                             fill=self.colour("ReadData") if number == 0 else INK, tags=tags)
            if number == 0:
                self.look(item, state, {"text": ""}, {"text": text})
            else:
                self.look(item, state, {"text": ""}, None, {"text": text})

    def signal(self, net, port, x, value, meaning, state, used=True, works=False):
        """A control signal that comes in from the top at x: its gray wire, its own line, the
        port's name inside the block, and the signal's value with what it means beside the
        wire."""
        tags = (f"wire:{net}",)
        points = [(x, self.TOP - 30), (x, self.TOP)]
        self.line(points, fill=IDLE, width=IDLE_BIT, arrow="last", tags=tags)
        self.port(x, self.TOP + 4, port, "n", state, works)
        said = self.text(x + 6, self.TOP - 16, net if not used else "", anchor="w", fill=IDLE,
                         tags=tags)
        if not used:
            return
        colour = signal_colour(value)
        self.look(said, state, {"text": f"{net}: {LATER}", "fill": IDLE},
                  {"text": f"{net} = {value}: {meaning}", "fill": colour})
        self.wire(points, colour, WIDTH_BIT, state, "in", tags)

    def unused(self, address, y, state):
        """An instruction that neither loads nor stores: the address it is given, and why
        nothing happens there."""
        self.input("WriteData", self.WD_Y, "", state, used=False)
        self.output("ReadData", y, "", state, used=False)
        tags = ("wire:ALUResult",)
        self.line([(self.IN_X, y), (self.LEFT, y)], fill=IDLE, width=IDLE_32, arrow="last",
                  tags=tags)
        self.text(self.IN_X + 4, y - 5, "ALUResult", anchor="sw", fill=IDLE, tags=tags)
        given = self.text(self.IN_X + 4, y + 5, "", anchor="nw", font="code", fill=IDLE, tags=tags)
        self.look(given, state, {"text": ""}, {"text": hex32(address)})
        middle = self.MIDDLE
        tags = (f"block:{self.BLOCK}",)
        self.text(middle, y - 22, "This instruction does not use the data memory.",
                  anchor="center", font="bold", fill=INK, tags=tags)
        for number, line in enumerate((f"A gets {hex32(address)} from ALUResult, but MemWrite "
                                       "is 0:",
                                       "nothing is written there, and nothing reads RD.")):
            item = self.text(middle, y + 4 + 18 * number, "", anchor="center", fill=INK,
                             tags=tags)
            self.look(item, state, {"text": ""}, {"text": line})

    def after(self, context, rows, olds, address, data):
        """The bytes of each row after the store: the memory now when it has run, else the
        bytes before with data written at address."""
        if context.registers_after is not None:
            return [None if old is None else context.peek(row, 4)
                    for row, old in zip(rows, olds)]
        news = []
        for row, old in zip(rows, olds):
            if old is None:
                news.append(None)
                continue
            new = bytearray(old)
            for number, byte in enumerate(data):
                offset = (address + number - row) & MASK
                if offset < 4:
                    new[offset] = byte
            news.append(bytes(new))
        return news

    def table(self, rows, olds, news, touched, store, net, state, works):
        """The words around the address: each one's address, value and four bytes, and what
        is there where there is no memory. The bytes the instruction reads or writes are
        marked in the colour of net, the value read or the data written, their rows lit; a
        store's old value is struck out when its new one comes. The table of a block that does
        not work stays gray."""
        digits = self.measure("0x00000000")
        pair = self.measure("00")
        x_address = self.LEFT + 26
        x_word = x_address + digits + 14
        x_bytes = x_word + digits + 14
        cell = pair + 10
        x_last = x_bytes + 4 * cell + 6
        dim = {"fill": self.gray}
        ink = {"fill": INK} if works else dim
        code, bold = self.fonts["code"], self.fonts["code_bold"]
        colour = self.colour(net)
        header = "After the write" if store and olds[AROUND] is not None else \
            "What is there" if None in olds else ""
        titles = [(x_address, "Address"), (x_word, "Word"), (x_last, header)]
        titles += [(x_bytes + cell * number, f"+{number}") for number in range(4)]
        for x, title in titles:
            item = self.text(x, self.TOP + 28, title, anchor="w")
            self.look(item, state, ink, idle=dim)
        for number, (row, old, new) in enumerate(zip(rows, olds, news)):
            y = self.row_y(number)
            mine = [(address - row) & MASK for address in touched if (address - row) & MASK < 4]
            right = self.TABLE_RIGHT
            if mine:
                self.frame(x_address - 6, right, y, state, colour, written=store)
            plain, working, idle = dict(ink, font=code), dict(ink, font=bold if mine else code), \
                dict(dim, font=code)
            item = self.text(x_address, y, f"0x{row:08X}", anchor="w", font="code")
            self.look(item, state, plain, working, idle=idle)
            if old is None:
                self.text(x_word, y, "-", anchor="w", font="code", fill=self.gray)
                item = self.text(x_last, y, self.fit(device_at(row)[0], right - 4 - x_last,
                                                     "small"), anchor="w")
                self.look(item, state, ink, idle=dim)
                continue
            item = self.text(x_word, y, f"0x{value_of(old):08X}", anchor="w", font="code")
            gone = {"fill": MARK, "font": self.fonts[self.struck()]} if mine and store else None
            self.look(item, state, plain, working, gone, idle=idle)
            for index in range(4):
                x = x_bytes + cell * index
                item = self.text(x, y, f"{old[index]:02X}", anchor="w", font="code")
                if index not in mine:
                    self.look(item, state, ink, idle=dim)
                    continue
                mark = self.box(x - 3, y - 8, x + pair + 3, y + 8, outline=colour, fill="",
                                width=1.2)
                self.look(mark, state, {"state": "hidden"}, {"state": "normal"})
                was = f"{old[index]:02X}"
                written = {"text": f"{new[index]:02X}", "fill": colour, "font": bold} if store \
                    else None
                self.look(item, state, dict(plain, text=was), dict(working, text=was), written,
                          idle=dict(idle, text=was))
            if mine and store:
                item = self.text(x_last, y, "", anchor="w", font="code_bold", fill=colour)
                self.look(item, state, {"text": ""}, None, {"text": f"0x{value_of(new):08X}"})

    def sentences(self, trace, address, row, old, new, load, store, size, runs):
        """What the data memory did, in a few sentences: row is the bytes of the word at the
        address (None: no memory), old and new the value there before and after, size the bytes
        it moves."""
        v = trace.values
        a = hex32(address)
        where = f"byte +{address & 3} of the word at {hex32(address & ~3 & MASK)}"
        if not runs:
            return (f"The condition failed (CondEx 0): MemWrite is 0, so nothing is written at "
                    f"{a}.",
                    "Nothing is read there either: RD is not used.")
        if row is None:
            _, said, device, board = device_at(address)
            lines = [f"There is no memory at {a}: {said}."]
            if device:
                if store:
                    lines.append(f"The store hands WD = {hex32(v['WriteData'])} to the device.")
                elif v["ReadData"] is None:
                    lines.append("What RD gets is known only when the program reads the device.")
                else:
                    lines.append(f"The load got {hex32(v['ReadData'])} from the device: it "
                                 "leaves on RD.")
                if board:
                    lines.append("The Digital Lab Sim simulates it while it is connected; else "
                                 "reads give 0 and writes are ignored.")
                lines.append("This window never reads a device: a read can take its data, such "
                             "as a typed character.")
            return tuple(lines)
        if store and size == 1:
            return (f"MemWrite is 1: at the clock edge the data memory writes the byte "
                    f"0x{new:02X}, the low byte of WD, at {a}.",
                    f"It is {where}; it was 0x{old:02X}. Nothing is read: RD is not used.")
        if store and size == 2:
            return (f"MemWrite is 1: at the clock edge the data memory writes the halfword "
                    f"0x{new:04X}, the low half of WD, at {a}.",
                    f"It was 0x{old:04X}. Nothing is read: RD is not used.")
        if store:
            return (f"MemWrite is 1: at the clock edge the data memory writes WD = {hex32(new)} "
                    f"at {a}.",
                    f"The word there was {hex32(old)}. Nothing is read: RD is not used.")
        read = hex32(v["ReadData"])
        if size == 1:
            first = (f"MemWrite is 0, so nothing is written. The data memory reads the byte at "
                     f"{a}: 0x{old:02X}, {where}.")
        elif size == 2:
            first = (f"MemWrite is 0, so nothing is written. The data memory reads the halfword "
                     f"at {a}: 0x{old:04X}.")
        else:
            return (f"MemWrite is 0, so nothing is written. The data memory reads the word at "
                    f"{a}.", f"It leaves on RD: ReadData = {read}.")
        high = 8 * size
        if trace.signals["Signed"] == "1":
            return (first, f"The load extender copies its sign bit, {old >> high - 1}, into bits "
                           f"31:{high}: ReadData = {read}.")
        return (first, f"The load extender fills bits 31:{high} with zeros: ReadData = {read}.")


INSIDE["IMem"] = InstructionMemoryWindow
INSIDE["DMem"] = DataMemoryWindow
