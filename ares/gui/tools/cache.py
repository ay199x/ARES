# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Tools > Data Cache Simulator: how a data cache would serve the program's loads and stores.

The cache's organization is chosen in the window: where a block of memory
may be kept (direct mapping, fully associative, N-way set associative),
which block of a full set makes room (LRU or random), the number of blocks,
the words in a block and the blocks in a set. The tool counts the memory
accesses, the hits and the misses, shows the hit rate and a table of the
blocks, each coloured by its last access, and logs each access if asked.

Each word a load or store reads or writes is one memory access. A memory
hook (ares.observers) on DDR3 and the on-chip memory reports them: not the
DE1-SoC devices, not the instruction fetches, not the system calls' own
reads and writes. The hook only collects the addresses; they are looked up
in the cache at the next refresh, in the order they happened, which comes
to exactly what looking up each one at once would. A run pays for the
hook alone.
"""

import random
import tkinter as tk
from array import array
from collections import OrderedDict, deque
from itertools import islice
from tkinter import ttk

from ...machine import DDR_BASE, DDR_END, ONCHIP_BASE, ONCHIP_SIZE
from ..style import FACE, SHADOW, TEXT, group, sunken
from ..style import WINDOW as WHITE
from ..widgets import HidingBars, ReadOnlyText, Tooltip, px, scale, tab_moves_on
from .frame import PercentBar, ToolModel, ToolWindow

PLACEMENTS = ("Direct Mapping", "Fully Associative", "N-way Set Associative")
DIRECT, FULL, SET = range(len(PLACEMENTS))
REPLACEMENTS = ("LRU", "Random")
LRU, RANDOM = range(len(REPLACEMENTS))
SIZES = tuple(1 << k for k in range(12))    # the choices of blocks, and of words in a block
WORD = 4                                    # bytes
DEFAULTS = {"placement": DIRECT, "replacement": LRU, "blocks": 8, "block_words": 4}
EMPTY, HIT, MISS = range(3)                 # a block as its last access left it
SEED = 0                    # random replacement starts from here again at each Reset
LOG_LIMIT = 1000            # accesses the log keeps, the newest
INDENT = " " * 5            # the second line of an access in the log
# What a data cache keeps: DDR3 and the on-chip memory, not the DE1-SoC devices.
CACHED = ((DDR_BASE, DDR_END - 1), (ONCHIP_BASE, ONCHIP_BASE + ONCHIP_SIZE - 1))
# How the cache served an access, for the log.
_HIT, _FILLED, _REPLACED, _LRU, _RANDOM = range(5)

# The window, in design pixels and characters.
COLOURS = {EMPTY: WHITE, HIT: "#00FF00", MISS: "#FF0000"}
TABLE_HEIGHT = 128          # the block table
TABLE_ROWS = 32             # blocks in a column of the table, at most
COLUMN_WIDTH = 40           # the table's width while it has a single column
CELL = 4                    # a block's least width and height
SWATCH = 11                 # a colour of the legend
CHOICE_WIDTHS = {"placement": 21, "replacement": 8, "sizes": 5}
FIELD_WIDTH = 11            # characters of a count
SIZE_WIDTH = 9              # characters of the cache size
LOG_SIZE = (72, 5)          # the log's text, in characters and lines

HELP = """\
The Data Cache Simulator shows how a data cache would serve the program's loads and
stores: which memory accesses find their word in the cache (hits), and which have to
bring its block into the cache first (misses).

Choose the cache's organization, click Connect to ARM, then run the program (Go,
Step): the numbers, the block table and the log follow the program, also while it runs
at full speed. Disconnect from ARM stops the observing; what the tool shows stays.
Reset empties the cache and the log and sets the numbers to 0. Close closes the tool and
stops the observing.

Cache Organization

Placement policy: where a block of memory may be kept. Direct Mapping: in one block of
the cache, which its address decides. Fully Associative: in any block. N-way Set
Associative: in any block of one set of N blocks, which its address decides.

Block replacement policy: which block of a full set makes room for the new one. LRU:
the one unused for the longest time. Random: one chosen at random; after Reset the
choices are the same again, so a run can be repeated. A new choice applies from the
next replacement on: the cache and the numbers stay.

Number of blocks and Cache block size (words): the blocks of the cache, and the words of
4 bytes in each block, 1 to 2048 of each.

Set size (blocks): the blocks of a set. Direct Mapping has sets of 1 block, Fully
Associative one set of all the blocks, N-way Set Associative sets of 1, 2, 4 ... blocks,
up to all of them.

Cache size (bytes): the number of blocks times the words in a block times 4.

Choosing a placement policy, a number of blocks, a block size or a set size starts again
with an empty cache, the numbers at 0 and an empty log. A new placement policy or number
of blocks also sets the set size to the first one its list offers.

Where an address goes: its block address is the address divided by the bytes of a
block. The set is the block address modulo the number of sets, and the tag the block
address divided by the number of sets. An access is a hit when a block of its set holds
its tag. On a miss the tag goes into the set's first empty block, or, when the set is
full, into the block the replacement policy chooses.

Cache Performance

Memory access count, Cache hit count and Cache miss count: the accesses since the tool
was opened, reset or given a new organization, and how many of them were hits and
misses. Cache hit rate: the hits as a share of the accesses.

The cache block table shows every block of the cache, block 0 at the top: white while
it is empty, green when its last access was a hit, red when it was a miss. With more
than 32 blocks the table has columns of 32 blocks, block 0 at the top left.

Run-time Log

Check Enabled to log each access from then on: its number, its address, tag and set,
and on the next line whether it was a hit, or which block it filled or replaced (with
LRU: the access that used that block last). The log keeps the newest 1,000 accesses.
Checking or clearing Enabled empties the log, as Reset does.

What counts as a memory access

Each word that a load or store instruction reads or writes is one memory access, in
DDR3 and in the on-chip memory where the stack is. A byte or a halfword is an access to
the block of its word.

LDR, STR, LDRB, STRB, LDRH, STRH: one access, two when an unaligned one reaches into the
next word.

LDRD and STRD, and VLDR and VSTR of a D register: two accesses, one for each word.

LDM, STM, PUSH and POP: one access for each register. VLDM, VSTM, VPUSH and VPOP: one for
each S register, two for each D register.

SWP: two accesses (it reads its word, then writes it).

LDREX: one access. STREX: none when it fails without touching memory (no LDREX before it,
another address, CLREX); two when it stores, or fails because the word changed after LDREX, as
the processor ARES simulates reads the word before it writes it.

LDR R1, =value: one access, which reads value from the literal pool after the code. A
number that fits a MOV instruction is no access: the assembler makes LDR R2, =40 a MOV.

Instruction fetches are not memory accesses here, nor are the system calls' own reads and
writes (SVC #4 reading its string, SVC #8 storing the typed line), nor the DE1-SoC
devices at 0xFF200000-0xFF20FFFF, the JTAG UART among them: a cache does not keep them.

The cache and its numbers stay when the program is assembled again, reset (Reset, F12) or
stepped back (Backstep undoes an instruction, but its accesses happened), and when the
program's file is closed; the tool stays connected. Only the tool's Reset and a new
organization empty the cache.

While the tool is connected a run takes longer: ARES hands the tool every memory access.
A loop of 10,000,000 instructions with 4,000,000 accesses takes about 3 seconds instead of
a tenth of a second.
"""


def set_sizes(placement, blocks):
    """The set sizes (in blocks) a placement policy allows in a cache of blocks blocks."""
    if placement == DIRECT:
        return (1,)
    if placement == FULL:
        return (blocks,)
    return tuple(size for size in SIZES if size <= blocks)


def table_shape(blocks):
    """(columns, rows) of the block table: a single column of up to TABLE_ROWS blocks,
    else columns of TABLE_ROWS."""
    rows = min(blocks, TABLE_ROWS)
    return blocks // rows, rows


class CacheModel(ToolModel):
    """The cache and its numbers (see the module's description).

    The organization: placement, replacement, blocks, block_words and
    set_size, changed only through the set_ methods. The numbers: accesses,
    hits and misses; for each block its state (EMPTY, HIT or MISS, in
    states) and its tag (None while empty, in tags). log holds the newest
    LOG_LIMIT logged accesses (two lines each) while logging is on;
    log_added counts those added since log_cleared last went up.

    accessed() is the memory hook, with Unicorn's own arguments (the tests
    call it too). The cache stays across Assemble, Reset and Backstep: only
    reset() and a new organization empty it.
    """

    def __init__(self):
        super().__init__()
        self.placement = DEFAULTS["placement"]
        self.replacement = DEFAULTS["replacement"]
        self.blocks = DEFAULTS["blocks"]
        self.block_words = DEFAULTS["block_words"]
        self.set_size = set_sizes(self.placement, self.blocks)[0]
        self.logging = False
        self.log = deque(maxlen=LOG_LIMIT)
        self.log_added = self.log_cleared = 0
        pending = self._pending = array("L")    # the words accessed and not yet looked up
        add = pending.append

        def accessed(handle, access, address, size, value, key):
            add(address)
            if (address & 3) + size > WORD:     # it reaches into the next words too
                for word in range((address | 3) + 1, address + size, WORD):
                    add(word & 0xFFFFFFFF)
        self.accessed = accessed
        self._empty()

    @property
    def cache_bytes(self):
        return self.blocks * self.block_words * WORD

    # Observing ----------------------------------------------------------------

    def attach(self, machine):
        for begin, end in CACHED:
            machine.observers.watch_memory(self, self.accessed, begin=begin, end=end, raw=True)

    def detach(self, machine):
        self.update()
        machine.observers.forget(self)

    def update(self):
        pending = self._pending
        if not pending:
            return False
        if self.logging and len(pending) > LOG_LIMIT:
            self._look_up(pending[:-LOG_LIMIT])     # the log would not keep their lines
            self.log_added += len(pending) - LOG_LIMIT
            self._look_up(pending[-LOG_LIMIT:], log=True)
        else:
            self._look_up(pending, log=self.logging)
        del pending[:]
        return True

    def reset(self):
        """Empty the cache, and start the numbers, the log and the random choices again."""
        del self._pending[:]
        self._empty()

    # The organization ---------------------------------------------------------

    def set_placement(self, placement):
        self.placement = placement
        self.set_size = set_sizes(placement, self.blocks)[0]
        self.reset()

    def set_blocks(self, blocks):
        self.blocks = blocks
        self.set_size = set_sizes(self.placement, blocks)[0]
        self.reset()

    def set_block_words(self, words):
        self.block_words = words
        self.reset()

    def set_set_size(self, size):
        self.set_size = size
        self.reset()

    def set_replacement(self, replacement):
        """Make room the new way from the next replacement on; the cache stays."""
        self.update()               # the accesses so far made room the old way
        self.replacement = replacement

    def set_logging(self, on):
        """Log each access from now on, or no longer; either way the log starts empty."""
        self.update()
        self.logging = on
        self._clear_log()

    # The cache ---------------------------------------------------------------

    def _empty(self):
        blocks = self.blocks
        self.accesses = self.hits = self.misses = 0
        self.states = bytearray(blocks)             # EMPTY
        self.tags = [None] * blocks
        self._used = [0] * blocks                   # the access that used each block last
        # Each set's tags and their blocks, least recently used first.
        self._sets = [OrderedDict() for _ in range(blocks // self.set_size)]
        self._last = -1, -1         # the block address of the last access, and its block
        self._random = random.Random(SEED)
        self._clear_log()

    def _clear_log(self):
        self.log.clear()
        self.log_added = 0
        self.log_cleared += 1

    def _look_up(self, addresses, log=False):
        """Look the addresses up in the cache, one after the other; with log, log each.

        An access to the block of the access before is a hit at once (that
        block is its set's most recently used). Such hits in a row are
        settled together: the block's state and last use are set once, at
        the next access to another block or at the end.
        """
        sets, set_size = self._sets, self.set_size
        shift = (self.block_words * WORD).bit_length() - 1     # address -> block address
        set_bits = (len(sets) - 1).bit_length()
        mask = len(sets) - 1
        choose = (self._random.getrandbits if self.replacement == RANDOM and set_size > 1
                  else None)
        choice_bits = set_size.bit_length() - 1
        tags, states, used = self.tags, self.states, self._used
        misses = self.misses
        last, last_block = self._last
        settled = number = self.accesses        # the accesses whose block shows them
        notes = [] if log else None
        for number, address in enumerate(addresses, number + 1):
            block_address = address >> shift
            if block_address == last:
                if notes is not None:
                    notes.append((number, address, block_address, last_block, _HIT, 0))
                continue
            if number - 1 > settled:            # hits in the block of the access before
                used[last_block] = number - 1
                states[last_block] = HIT
            settled = number
            ways = sets[block_address & mask]
            tag = block_address >> set_bits
            block = ways.get(tag)
            if block is not None:
                ways.move_to_end(tag)
                states[block] = HIT
                outcome = _HIT
            else:
                misses += 1
                if len(ways) < set_size:                    # the set's first empty block
                    block = (block_address & mask) * set_size + len(ways)
                    outcome = _FILLED
                elif choose is not None:
                    block = (block_address & mask) * set_size + choose(choice_bits)
                    del ways[tags[block]]
                    outcome = _RANDOM
                else:                                       # the least recently used one
                    block = ways.popitem(last=False)[1]
                    outcome = _LRU if set_size > 1 else _REPLACED
                ways[tag] = block
                tags[block] = tag
                states[block] = MISS
            if notes is not None:
                notes.append((number, address, block_address, block, outcome, used[block]))
            used[block] = number
            last, last_block = block_address, block
        if number > settled:
            used[last_block] = number
            states[last_block] = HIT
        self._last = last, last_block
        self.accesses, self.hits, self.misses = number, number - misses, misses
        if notes:
            self._write_log(notes, set_bits)

    def _write_log(self, notes, set_bits):
        """Add to the log the accesses noted by _look_up()."""
        set_size, mask = self.set_size, len(self._sets) - 1
        for number, address, block_address, block, outcome, since in notes:
            first = (block_address & mask) * set_size
            where = (f"block {first}" if set_size == 1
                     else f"blocks {first}-{first + set_size - 1}")
            if outcome == _HIT:
                what = f"hit in block {block}"
            elif outcome == _FILLED:
                what = f"miss, block {block} was empty"
            elif outcome == _LRU:
                what = f"miss, block {block} replaced (LRU, last used at access {since})"
            elif outcome == _RANDOM:
                what = f"miss, block {block} replaced (random)"
            else:
                what = f"miss, block {block} replaced"
            self.log.append(f"({number}) address 0x{address:08x}, tag "
                            f"0x{block_address >> set_bits:08x}, set {block_address & mask} "
                            f"({where})\n{INDENT}{what}")
        self.log_added += len(notes)


class CacheWindow(ToolWindow):
    """Tools > Data Cache Simulator."""

    NAME = "Data Cache Simulator"
    HEADING = "Data cache performance, access by access"
    HELP = HELP
    MODEL = CacheModel

    def build(self, body):
        gap = px(body, 6)
        self._build_organization(body, gap)
        self._build_performance(body, gap)
        self._build_log(body, gap)
        self._show_organization()

    def _build_organization(self, body, gap):
        box = group(body, "Cache Organization")
        box.pack(fill="x")
        self.placement_box = self._choice(box, PLACEMENTS, CHOICE_WIDTHS["placement"],
                                          self._placement_chosen)
        self.replacement_box = self._choice(box, REPLACEMENTS, CHOICE_WIDTHS["replacement"],
                                            self._replacement_chosen)
        self.set_size_box = self._choice(box, (), CHOICE_WIDTHS["sizes"], self._set_size_chosen)
        self.blocks_box = self._choice(box, SIZES, CHOICE_WIDTHS["sizes"], self._blocks_chosen)
        self.block_words_box = self._choice(box, SIZES, CHOICE_WIDTHS["sizes"],
                                            self._block_words_chosen)
        self.cache_size = tk.StringVar(master=box)
        size = _field(box, self.cache_size, SIZE_WIDTH)
        pairs = ((("Placement policy:", self.placement_box),
                  ("Number of blocks:", self.blocks_box)),
                 (("Block replacement policy:", self.replacement_box),
                  ("Cache block size (words):", self.block_words_box)),
                 (("Set size (blocks):", self.set_size_box),
                  ("Cache size (bytes):", size)))
        for row, pair in enumerate(pairs):
            for column, (label, widget) in enumerate(pair):
                ttk.Label(box, text=label).grid(row=row, column=2 * column, sticky="w",
                                                padx=(4 * gap if column else 0, 0))
                widget.grid(row=row, column=2 * column + 1, sticky="e", padx=(gap, 0),
                            pady=px(body, 2))
        for column in (1, 3):                   # the room left over, after each list
            box.columnconfigure(column, weight=1)

    def _build_performance(self, body, gap):
        box = group(body, "Cache Performance")
        box.pack(fill="x", pady=(gap, 0))
        numbers = ttk.Frame(box)
        numbers.pack(side="left", anchor="n")
        self.accesses, self.hits, self.misses = (tk.StringVar(master=box, value="0")
                                                 for _ in range(3))
        fields = (("Memory access count:", self.accesses), ("Cache hit count:", self.hits),
                  ("Cache miss count:", self.misses))
        for row, (label, variable) in enumerate(fields):
            ttk.Label(numbers, text=label).grid(row=row, column=0, sticky="w")
            field = _field(numbers, variable, FIELD_WIDTH)
            field.grid(row=row, column=1, sticky="w", padx=(gap, 0), pady=px(body, 2))
        ttk.Label(numbers, text="Cache hit rate:").grid(row=len(fields), column=0, sticky="w")
        self.rate = PercentBar(numbers, width=field.winfo_reqwidth() / scale(body))
        self.rate.canvas.grid(row=len(fields), column=1, sticky="w", padx=(gap, 0),
                              pady=px(body, 2))
        table = ttk.Frame(box)
        table.pack(side="right", anchor="n", padx=(4 * gap, 0))
        legend = ttk.Frame(table)
        legend.pack(side="left", anchor="n", padx=(0, gap))
        ttk.Label(legend, text="Cache block table").pack(anchor="w")
        self.table_order = ttk.Label(legend)
        self.table_order.pack(anchor="w", pady=(0, gap))
        for state, name in ((EMPTY, "empty"), (HIT, "hit"), (MISS, "miss")):
            row = ttk.Frame(legend)
            row.pack(anchor="w", pady=px(body, 1))
            _swatch(row, COLOURS[state]).pack(side="left")
            ttk.Label(row, text=f"= {name}").pack(side="left", padx=(gap, 0))
        frame = sunken(tk.Frame(table))
        frame.pack(side="left", anchor="n")
        self.table = tk.Canvas(frame, background=WHITE, borderwidth=0, highlightthickness=0,
                               takefocus=False)
        self.table.pack()
        self.cells = []             # the table's rectangles, block 0 first
        self._shown = bytearray()   # the state each shows

    def _build_log(self, body, gap):
        box = group(body, "Run-time Log")
        box.pack(fill="both", expand=True, pady=(gap, 0))
        self.logging = tk.BooleanVar(master=box, value=False)
        self.log_check = ttk.Checkbutton(box, text="Enabled", variable=self.logging,
                                         command=self._logging_chosen)
        self.log_check.pack(side="left")
        page = sunken(tk.Frame(box))                # the text and its scroll bars
        page.pack(side="left", fill="both", expand=True, padx=(gap, 0))
        width, height = LOG_SIZE
        # Gray and empty while Enabled is not checked: Tab passes it by then (_logging_chosen).
        text = self.log_text = ReadOnlyText(
            page, font=self.app.pane_font, wrap="none", width=width, height=height,
            background=FACE, foreground=TEXT, borderwidth=0, highlightthickness=0,
            padx=px(body, 4), pady=px(body, 2), takefocus=False)
        tab_moves_on(text)
        yscroll = ttk.Scrollbar(page, orient="vertical", command=text.yview)
        xscroll = ttk.Scrollbar(page, orient="horizontal", command=text.xview)
        text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)
        # Room for the text and both bars, which come and go inside it.
        border = 2 * int(page.cget("borderwidth"))
        page.grid_propagate(False)
        page.configure(width=text.winfo_reqwidth() + yscroll.winfo_reqwidth() + border,
                       height=text.winfo_reqheight() + xscroll.winfo_reqheight() + border)
        self.log_bars = HidingBars(text, yscroll, xscroll)
        self.log_tip = Tooltip(text, "Each memory access and how the cache served it, while "
                                     "Enabled is checked")
        self._log_shown = (self.model.log_cleared, 0)       # (log_cleared, log_added)
        self._log_entries = 0                               # accesses in the text

    @staticmethod
    def _choice(master, values, width, chosen):
        """A list to choose from; chosen() is called for each choice made in it."""
        box = ttk.Combobox(master, values=values, state="readonly", width=width)
        box.bind("<<ComboboxSelected>>", lambda event: chosen())
        return box

    # Choices -------------------------------------------------------------------------

    def _placement_chosen(self):
        self.model.set_placement(self.placement_box.current())
        self._organized()

    def _blocks_chosen(self):
        self.model.set_blocks(int(self.blocks_box.get()))
        self._organized()

    def _block_words_chosen(self):
        self.model.set_block_words(int(self.block_words_box.get()))
        self._organized()

    def _set_size_chosen(self):
        self.model.set_set_size(int(self.set_size_box.get()))
        self._organized()

    def _replacement_chosen(self):
        self.model.set_replacement(self.replacement_box.current())
        self.show()

    def _logging_chosen(self):
        on = self.logging.get()
        self.model.set_logging(on)
        self.log_text.configure(background=WHITE if on else FACE, takefocus=on)
        self.show()

    def _organized(self):
        self._show_organization()
        self.show()

    # Showing -------------------------------------------------------------------------

    def _show_organization(self):
        model = self.model
        self.placement_box.current(model.placement)
        self.replacement_box.current(model.replacement)
        self.blocks_box.set(model.blocks)
        self.block_words_box.set(model.block_words)
        self.set_size_box.configure(values=set_sizes(model.placement, model.blocks))
        self.set_size_box.set(model.set_size)
        self.cache_size.set(str(model.cache_bytes))
        if len(self.cells) != model.blocks:
            self._make_table()

    def _make_table(self):
        """Draw a cell for each block of the model's cache, all empty."""
        canvas, blocks = self.table, self.model.blocks
        columns, rows = table_shape(blocks)
        width = px(canvas, columns * max(CELL, COLUMN_WIDTH // columns))
        height = px(canvas, TABLE_HEIGHT)
        canvas.delete("all")
        canvas.configure(width=width, height=height)
        # The outlines of neighbours overlap, so the lines between the cells are one pixel.
        xs = [round(k * (width - 1) / columns) for k in range(columns + 1)]
        ys = [round(k * (height - 1) / rows) for k in range(rows + 1)]
        self.cells = [canvas.create_rectangle(xs[block // rows], ys[block % rows],
                                              xs[block // rows + 1], ys[block % rows + 1],
                                              fill=COLOURS[EMPTY], outline=SHADOW)
                      for block in range(blocks)]
        self._shown = bytearray(blocks)
        self.table_order.configure(text="(block 0 at top)" if columns == 1
                                   else "(block 0 at top left)")

    def show(self):
        model = self.model
        for variable, number in ((self.accesses, model.accesses), (self.hits, model.hits),
                                 (self.misses, model.misses)):
            _set(variable, number)
        self.rate.set(model.hits, model.accesses)
        self._show_blocks()
        self._show_log()

    def _show_blocks(self):
        """Colour the cells whose block changed state since they were last coloured."""
        states, shown = self.model.states, self._shown
        if states == shown:
            return
        canvas, cells = self.table, self.cells
        for block, (state, was) in enumerate(zip(states, shown)):
            if state != was:
                canvas.itemconfigure(cells[block], fill=COLOURS[state])
        self._shown = bytearray(states)

    def _show_log(self):
        """Add the accesses logged since the last time; the text keeps the newest LOG_LIMIT."""
        model, text = self.model, self.log_text
        cleared, added = self._log_shown
        self._log_shown = (model.log_cleared, model.log_added)
        emptied = cleared != model.log_cleared
        new = min(model.log_added - (0 if emptied else added), len(model.log))
        if emptied or new == LOG_LIMIT:         # nothing the text holds stays
            text.clear()
            self._log_entries = 0
        if new > 0:
            entries = islice(model.log, len(model.log) - new, None)
            text.write(("\n" if self._log_entries else "") + "\n".join(entries))
            self._log_entries += new
            extra = self._log_entries - LOG_LIMIT
            if extra > 0:                       # the oldest go, two lines each
                text.tk.call(text._original, "delete", "1.0", f"{2 * extra + 1}.0")
                self._log_entries = LOG_LIMIT
            text.see_end()
        if emptied or new > 0:
            self.log_bars.schedule()


def _field(master, variable, width):
    """A read-only field showing a number."""
    return ttk.Entry(master, textvariable=variable, state="readonly", width=width,
                     justify="right", takefocus=False)


def _swatch(master, colour):
    """A small square of a colour of the block table, for its legend."""
    size = px(master, SWATCH)
    canvas = tk.Canvas(master, width=size, height=size, background=FACE, borderwidth=0,
                       highlightthickness=0, takefocus=False)
    canvas.create_rectangle(0, 0, size - 1, size - 1, fill=colour, outline=SHADOW)
    return canvas


def _set(variable, number):
    text = str(number)
    if variable.get() != text:
        variable.set(text)


WINDOW = CacheWindow
