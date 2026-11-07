# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Data Cache Simulator's model: the cache, what counts as an access, and what survives
Assemble and Reset."""

import random
import time

import pytest
from test_benchmark import BENCHMARK, TOOL_SECONDS
from unicorn import UC_MEM_READ, UC_MEM_WRITE

from ares.gui.tools.cache import (DIRECT, EMPTY, FULL, HIT, LOG_LIMIT, LRU, MISS, RANDOM, SEED,
                                  SET, SIZES, CacheModel, set_sizes, table_shape)
from ares.machine import CHUNK, MEMORY_CHUNK, Machine, StopReason
from ares.runner import Runner, State


class Reference:
    """The cache looked up one access at a time, as the tool describes it.

    Each block has a tag, whether it holds one, and the number of the access
    that used it last. An access searches its set from its first block: a
    block holding its tag is a hit; the first empty one is a miss that it
    fills; a full set is a miss that replaces the block the policy chooses.
    """

    def __init__(self, replacement, blocks, block_words, set_size):
        self.replacement, self.block_words, self.set_size = replacement, block_words, set_size
        self.sets = blocks // set_size
        self.valid = [False] * blocks
        self.tag = [0] * blocks
        self.used = [0] * blocks
        self.state = [EMPTY] * blocks
        self.accesses = self.hits = 0
        self.random = random.Random(SEED)

    def access(self, address):
        self.accesses += 1
        block_address = address // 4 // self.block_words
        tag = block_address // self.sets
        first = block_address % self.sets * self.set_size
        last = first + self.set_size - 1
        for block in range(first, last + 1):
            if self.valid[block] and self.tag[block] == tag:
                self.hits += 1
                self.state[block] = HIT
                break
            if not self.valid[block]:
                self.valid[block], self.tag[block] = True, tag
                self.state[block] = MISS
                break
        else:
            if first == last:
                block = first
            elif self.replacement == RANDOM:
                block = first + self.random.getrandbits(self.set_size.bit_length() - 1)
            else:
                block = min(range(first, last + 1), key=self.used.__getitem__)
            self.tag[block] = tag
            self.state[block] = MISS
        self.used[block] = self.accesses

    def tags(self):
        return [tag if valid else None for valid, tag in zip(self.valid, self.tag)]


def organized(placement=DIRECT, replacement=LRU, blocks=8, block_words=4, set_size=None):
    """A model with this organization (set_size: the first its list offers)."""
    model = CacheModel()
    model.set_blocks(blocks)
    model.set_block_words(block_words)
    model.set_placement(placement)
    if set_size is not None:
        model.set_set_size(set_size)
    model.set_replacement(replacement)
    return model


def feed(model, addresses, size=1, access=UC_MEM_READ):
    """Accesses as the memory hook reports them: each of size bytes, one word for the cache."""
    for address in addresses:
        model.accessed(None, access, address, size, 0, None)


def summary(model):
    return model.accesses, model.hits, model.misses, list(model.states), list(model.tags)


def same_as_reference(model, reference):
    assert (model.accesses, model.hits, model.misses) == (
        reference.accesses, reference.hits, reference.accesses - reference.hits)
    assert list(model.states) == reference.state
    assert model.tags == reference.tags()


# The organization ---------------------------------------------------------------------

def test_the_default_organization():
    model = CacheModel()
    assert (model.placement, model.replacement, model.blocks, model.block_words,
            model.set_size) == (DIRECT, LRU, 8, 4, 1)
    assert model.cache_bytes == 128
    assert (model.accesses, model.hits, model.misses) == (0, 0, 0)
    assert list(model.states) == [EMPTY] * 8 and model.tags == [None] * 8
    assert not model.logging and not model.log
    assert SIZES == (1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048)


def test_the_set_sizes_follow_the_placement_and_the_number_of_blocks():
    assert set_sizes(DIRECT, 8) == (1,)
    assert set_sizes(FULL, 8) == (8,)
    assert set_sizes(SET, 8) == (1, 2, 4, 8)
    assert set_sizes(SET, 1) == (1,) and set_sizes(FULL, 2048) == (2048,)
    model = CacheModel()
    model.set_placement(FULL)
    assert model.set_size == 8
    model.set_blocks(32)
    assert model.set_size == 32                 # all of them, as the list offers
    model.set_placement(SET)
    assert model.set_size == 1                  # the first of its list
    model.set_set_size(4)
    model.set_block_words(8)
    assert model.set_size == 4                  # a new block size keeps it
    model.set_blocks(64)
    assert model.set_size == 1                  # a new number of blocks: the first again
    model.set_placement(DIRECT)
    assert model.set_size == 1


def test_the_cache_size_in_bytes():
    assert organized(blocks=8, block_words=4).cache_bytes == 128
    assert organized(blocks=2048, block_words=2048).cache_bytes == 2048 * 2048 * 4
    assert organized(blocks=1, block_words=1).cache_bytes == 4


def test_the_block_table_has_columns_of_32_blocks():
    assert table_shape(1) == (1, 1) and table_shape(8) == (1, 8) and table_shape(32) == (1, 32)
    assert table_shape(64) == (2, 32) and table_shape(2048) == (64, 32)


# Looking up ---------------------------------------------------------------------------

def test_direct_mapping_by_hand():
    """8 blocks of 4 words: 128 bytes; address 0x80 has the set of address 0."""
    model = organized()
    feed(model, [0x00, 0x04, 0x0C, 0x10, 0x80, 0x00, 0x1C])
    model.update()
    assert (model.accesses, model.hits, model.misses) == (7, 3, 4)
    # 0x00 miss (set 0), 0x04 and 0x0C hits, 0x10 miss (set 1), 0x80 miss replaces set 0's
    # block, 0x00 miss replaces it again, 0x1C a hit in set 1.
    assert list(model.states) == [MISS, HIT] + [EMPTY] * 6
    assert model.tags == [0, 0] + [None] * 6


def test_fully_associative_lru_by_hand():
    """Two blocks of one word: the least recently used one makes room."""
    model = organized(FULL, LRU, blocks=2, block_words=1)
    a, b, c = 0x100, 0x200, 0x300
    feed(model, [a, b, a, c])                   # c replaces b, unused since the 2nd access
    model.update()
    assert model.tags == [a >> 2, c >> 2] and list(model.states) == [HIT, MISS]
    feed(model, [b])                            # b replaces a
    model.update()
    assert model.tags == [b >> 2, c >> 2] and (model.hits, model.misses) == (1, 4)


def test_set_associative_by_hand():
    """4 blocks of 2 words in 2 sets of 2: bit 3 of the address chooses the set."""
    model = organized(SET, LRU, blocks=4, block_words=2, set_size=2)
    feed(model, [0x00, 0x10, 0x20, 0x08, 0x10])
    model.update()
    # 0x00 set 0 tag 0 -> block 0; 0x10 set 0 tag 1 -> block 1; 0x20 set 0 tag 2 replaces
    # block 0 (LRU); 0x08 set 1 tag 0 -> block 2; 0x10 a hit in block 1.
    assert model.tags == [2, 1, 0, None]
    assert list(model.states) == [MISS, HIT, MISS, EMPTY]
    assert (model.accesses, model.hits, model.misses) == (5, 1, 4)


def test_random_replacement_chooses_within_the_set():
    model = organized(FULL, RANDOM, blocks=4, block_words=1)
    feed(model, range(0, 4 * 400, 4))           # every access a miss once the set is full
    model.update()
    assert model.misses == 400 and all(state == MISS for state in model.states)
    reference = Reference(RANDOM, 4, 1, 4)
    for address in range(0, 4 * 400, 4):
        reference.access(address)
    same_as_reference(model, reference)


ORGANIZATIONS = [
    (DIRECT, LRU, 8, 4, None), (DIRECT, RANDOM, 16, 1, None), (FULL, LRU, 8, 2, None),
    (FULL, RANDOM, 8, 2, None), (SET, LRU, 16, 2, 4), (SET, RANDOM, 16, 2, 4),
    (SET, LRU, 32, 1, 2), (SET, RANDOM, 64, 4, 8), (FULL, LRU, 1, 1, None),
    (SET, RANDOM, 4, 8, 4), (DIRECT, LRU, 2048, 1, None), (FULL, RANDOM, 2048, 1, None),
]


def accesses_with_locality(count, seed=1):
    """Addresses as a program makes them: runs through arrays, a stack, loops, strays."""
    rng = random.Random(seed)
    addresses = []
    while len(addresses) < count:
        kind = rng.random()
        if kind < 0.4:                                      # an array, word by word
            start = rng.randrange(0, 0x4000, 4)
            addresses += range(start, start + 4 * rng.randrange(1, 64), 4)
        elif kind < 0.6:                                    # the stack
            addresses += [0xFFFFFFFC - 4 * rng.randrange(16) for _ in range(8)]
        elif kind < 0.8:                                    # bytes of a string
            start = rng.randrange(0x8000, 0x9000)
            addresses += range(start, start + rng.randrange(1, 40))
        else:                                               # anywhere
            addresses += [rng.randrange(0, 0x40000000) & ~3 for _ in range(4)]
    return addresses[:count]


@pytest.mark.parametrize("organization", ORGANIZATIONS, ids=str)
def test_looking_up_later_gives_what_looking_up_at_once_gives(organization):
    """Collected and looked up in batches of any length, the accesses give exactly what
    looking each up at once (the reference) gives, also in the log."""
    placement, replacement, blocks, block_words, set_size = organization
    addresses = accesses_with_locality(6000)
    reference = Reference(replacement, blocks, block_words,
                          set_size or set_sizes(placement, blocks)[0])     # as organized()
    at_once, batches = organized(*organization), organized(*organization)
    at_once.set_logging(True)
    batches.set_logging(True)
    rng = random.Random(2)
    start = 0
    for address in addresses:
        reference.access(address)
        feed(at_once, [address])
        at_once.update()
    while start < len(addresses):
        length = rng.choice([1, 2, 7, 100, 1500])
        feed(batches, addresses[start:start + length])
        batches.update()
        start += length
    same_as_reference(at_once, reference)
    assert summary(batches) == summary(at_once)
    assert list(batches.log) == list(at_once.log) and len(at_once.log) == LOG_LIMIT
    assert batches.log_added == at_once.log_added == len(addresses)


def test_a_new_replacement_policy_applies_from_the_next_replacement():
    """Accesses collected before the choice made room the old way."""
    addresses = accesses_with_locality(3000, seed=5)
    reference = Reference(LRU, 16, 1, 16)
    model = organized(FULL, LRU, blocks=16, block_words=1)
    for address in addresses[:1000]:
        reference.access(address)
    feed(model, addresses[:1000])
    model.set_replacement(RANDOM)               # not looked up yet: with LRU all the same
    reference.replacement = RANDOM
    for address in addresses[1000:2000]:
        reference.access(address)
    feed(model, addresses[1000:2000])
    model.set_replacement(LRU)
    reference.replacement = LRU
    for address in addresses[2000:]:
        reference.access(address)
    feed(model, addresses[2000:])
    model.update()
    same_as_reference(model, reference)
    assert model.accesses == 3000               # the numbers stayed


@pytest.mark.parametrize("change", ["placement", "blocks", "block_words", "set_size"])
def test_a_new_organization_starts_with_an_empty_cache(change):
    model = organized(SET, RANDOM, blocks=8, block_words=2, set_size=2)
    model.set_logging(True)
    feed(model, accesses_with_locality(500))
    model.update()
    cleared = model.log_cleared
    feed(model, [0x40, 0x44])                       # not looked up: dropped with the rest
    {"placement": lambda: model.set_placement(FULL),
     "blocks": lambda: model.set_blocks(16),
     "block_words": lambda: model.set_block_words(4),
     "set_size": lambda: model.set_set_size(4)}[change]()
    assert (model.accesses, model.hits, model.misses) == (0, 0, 0)
    assert set(model.states) == {EMPTY} and set(model.tags) == {None}
    assert len(model.states) == model.blocks
    assert not model.log and model.log_cleared > cleared and model.logging
    assert not model.update()
    feed(model, accesses_with_locality(500))        # the random choices start again too
    model.update()
    reference = Reference(model.replacement, model.blocks, model.block_words, model.set_size)
    for address in accesses_with_locality(500):
        reference.access(address)
    same_as_reference(model, reference)


def test_reset_empties_the_cache_and_repeats_the_random_choices():
    model = organized(FULL, RANDOM, blocks=8, block_words=1)
    model.set_logging(True)
    addresses = accesses_with_locality(2000, seed=3)
    feed(model, addresses)
    model.update()
    first, log = summary(model), list(model.log)
    feed(model, [0x10])
    model.reset()
    assert (model.accesses, model.hits, model.misses) == (0, 0, 0)
    assert set(model.states) == {EMPTY} and not model.log and not model.update()
    assert model.replacement == RANDOM and model.blocks == 8 and model.logging   # stay
    feed(model, addresses)
    model.update()
    assert summary(model) == first and list(model.log) == log


def test_a_word_that_reaches_into_the_next_counts_for_both():
    """The hook takes each word of an access as an access of its own."""
    model = organized(DIRECT, LRU, blocks=8, block_words=1)
    for access, address, size in [
            (UC_MEM_READ, 0x100, 8),            # a doubleword: two words
            (UC_MEM_WRITE, 0x201, 4),           # an unaligned word: two
            (UC_MEM_READ, 0x303, 2),            # a halfword across two words
            (UC_MEM_READ, 0x402, 8),            # an unaligned doubleword: three
            (UC_MEM_READ, 0x501, 1),            # a byte: one
            (UC_MEM_READ, 0x602, 2),            # a halfword in its word: one
            (UC_MEM_READ, 0xFFFFFFFE, 4)]:      # wraps to address 0
        model.accessed(None, access, address, size, 0, None)
    assert list(model._pending) == [0x100, 0x104, 0x201, 0x204, 0x303, 0x304, 0x402, 0x404,
                                    0x408, 0x501, 0x602, 0xFFFFFFFE, 0]
    model.update()
    assert model.accesses == 13 and not model._pending


# The log ------------------------------------------------------------------------------

def test_the_log_of_a_direct_mapped_cache():
    """Four blocks of one word: each set is one block."""
    model = organized(DIRECT, LRU, blocks=4, block_words=1)
    model.set_logging(True)
    feed(model, [0x00, 0x02, 0x10, 0x04])
    model.update()
    assert list(model.log) == [
        "(1) address 0x00000000, tag 0x00000000, set 0 (block 0)\n     miss, block 0 was empty",
        "(2) address 0x00000002, tag 0x00000000, set 0 (block 0)\n     hit in block 0",
        "(3) address 0x00000010, tag 0x00000001, set 0 (block 0)\n     miss, block 0 replaced",
        "(4) address 0x00000004, tag 0x00000000, set 1 (block 1)\n     miss, block 1 was empty",
    ]


def test_the_log_of_a_set_associative_cache():
    """Four blocks of one word in two sets of two: bit 2 of the address chooses the set."""
    model = organized(SET, LRU, blocks=4, block_words=1, set_size=2)
    model.set_logging(True)
    feed(model, [0x10, 0x11, 0x18, 0x20, 0x14, 0x30])
    model.set_replacement(RANDOM)
    feed(model, [0x40, 0x48])
    model.update()
    lines = [line for entry in model.log for line in entry.split("\n")]
    choices = random.Random(SEED)       # the organization's last change started them
    first, second = choices.getrandbits(1), choices.getrandbits(1)
    assert lines == [
        "(1) address 0x00000010, tag 0x00000002, set 0 (blocks 0-1)",
        "     miss, block 0 was empty",
        "(2) address 0x00000011, tag 0x00000002, set 0 (blocks 0-1)",
        "     hit in block 0",
        "(3) address 0x00000018, tag 0x00000003, set 0 (blocks 0-1)",
        "     miss, block 1 was empty",
        "(4) address 0x00000020, tag 0x00000004, set 0 (blocks 0-1)",
        "     miss, block 0 replaced (LRU, last used at access 2)",
        "(5) address 0x00000014, tag 0x00000002, set 1 (blocks 2-3)",
        "     miss, block 2 was empty",
        "(6) address 0x00000030, tag 0x00000006, set 0 (blocks 0-1)",
        "     miss, block 1 replaced (LRU, last used at access 3)",
        "(7) address 0x00000040, tag 0x00000008, set 0 (blocks 0-1)",
        f"     miss, block {first} replaced (random)",
        "(8) address 0x00000048, tag 0x00000009, set 0 (blocks 0-1)",
        f"     miss, block {second} replaced (random)",
    ]


def test_the_log_keeps_the_newest_accesses():
    model = organized()
    model.set_logging(True)
    feed(model, range(0, 4 * (LOG_LIMIT + 250), 4))
    model.update()
    assert len(model.log) == LOG_LIMIT and model.log_added == LOG_LIMIT + 250
    assert model.log[0].startswith("(251) address 0x000003e8,")
    assert model.log[-1].startswith(f"({LOG_LIMIT + 250}) ")


def test_logging_starts_and_ends_with_an_empty_log():
    model = organized()
    feed(model, [0, 4])                         # before logging: not logged
    model.set_logging(True)
    assert not model.log and model.accesses == 2
    feed(model, [8])
    model.update()
    assert len(model.log) == 1 and model.log[0].startswith("(3) ")
    cleared = model.log_cleared
    model.set_logging(False)
    feed(model, [12])
    model.update()
    assert not model.log and model.log_cleared == cleared + 1 and model.accesses == 4


# What the program's accesses are ------------------------------------------------------

def make(build, source):
    machine = Machine(build(source))
    return machine, Runner(machine)


def counted(build, body, data=""):
    """The word addresses the cache saw while a program ran (data first, then body)."""
    source = (f"        .data\n        .balign 8\nvalue:  .word   1, 2, 3, 4, 5, 6, 7, 8\n{data}"
              f"        .global _start\n        .text\n_start: LDR     R1, =value\n{body}"
              "        SVC     #10\n")
    machine, runner = make(build, source)
    model = organized(FULL, LRU, blocks=2048, block_words=1)
    model.set_logging(True)
    model.connect(machine)
    assert runner.run() is State.FINISHED
    model.update()
    value = machine.program.label_address("value")
    seen = [int(entry.split("address ")[1][:10], 16) for entry in model.log]
    assert seen[0] != value                     # LDR R1, =value reads the literal pool
    return machine, [address - value for address in seen[1:]], model


@pytest.mark.parametrize("body, words", [
    ("", []),
    ("        LDR     R2, [R1]\n", [0]),
    ("        STR     R2, [R1, #4]\n", [4]),
    ("        LDRB    R2, [R1, #3]\n        STRB    R2, [R1, #5]\n", [3, 5]),
    ("        LDRH    R2, [R1, #2]\n        STRH    R2, [R1, #6]\n", [2, 6]),
    ("        LDRD    R2, R3, [R1]\n        STRD    R2, R3, [R1, #8]\n", [0, 4, 8, 12]),
    ("        VLDR    D1, [R1, #8]\n        VSTR    D1, [R1]\n", [8, 12, 0, 4]),
    ("        VLDR    S1, [R1, #8]\n", [8]),
    ("        LDM     R1, {R2-R5}\n", [0, 4, 8, 12]),
    ("        ADD     R2, R1, #16\n        STMDB   R2, {R3, R4}\n", [8, 12]),
    ("        LDR     R2, [R1, #1]\n        LDRH    R2, [R1, #7]\n", [1, 4, 7, 8]),
    ("        SWP     R2, R2, [R1]\n", [0, 0]),
    ("        STREX   R3, R2, [R1]\n", []),           # no LDREX before: it fails
    ("        LDREX   R2, [R1]\n        STREX   R3, R2, [R1]\n", [0, 0, 0]),
    ("        VLDM    R1, {S0-S2}\n        VLDM    R1, {D0}\n", [0, 4, 8, 0, 4]),
])
def test_what_each_load_and_store_counts(build, body, words):
    """Each word read or written is an access; instruction fetches are not."""
    _, seen, model = counted(build, body)
    assert seen == words
    assert model.accesses == 1 + len(words)


def test_the_stack_counts(build):
    """SP starts at 0: the first push stores at the top of the on-chip memory."""
    machine, seen, model = counted(build, "        PUSH    {R4, LR}\n        POP     {R4, LR}\n"
                                          "        VPUSH   {D8}\n        VPOP    {D8}\n")
    stack = [(address + machine.program.label_address("value")) & 0xFFFFFFFF
             for address in seen]
    assert stack == [0xFFFFFFF8, 0xFFFFFFFC, 0xFFFFFFF8, 0xFFFFFFFC] * 2
    assert model.accesses == 1 + 8


def test_a_new_memory_page_counts_once(build):
    """The first access to a DDR3 page maps it; it is still one access."""
    machine, seen, model = counted(build, "        MOV     R6, #0x00300000\n"
                                          "        STR     R2, [R6]\n"
                                          "        LDR     R2, [R6, #4]\n")
    value = machine.program.label_address("value")
    assert [(address + value) & 0xFFFFFFFF for address in seen] == [0x00300000, 0x00300004]
    assert model.accesses == 3           # the literal, the store and the load


def test_system_calls_and_devices_are_not_cached(build):
    """SVC #4 reads its string and SVC #8 stores the typed line without the CPU; the
    DE1-SoC devices (the JTAG UART, and one not simulated) are not cached."""
    source = """\
        .data
text:   .asciz  "Hi\\n"
        .balign 4
line:   .space  16
        .global _start
        .text
_start: LDR     R0, =text
        SVC     #4
        LDR     R0, =line
        MOV     R1, #16
        SVC     #8
        LDR     R1, =0xFF201000
        MOV     R2, #'A'
        STR     R2, [R1]
        LDR     R2, [R1, #4]
        LDR     R1, =0xFF200000
        LDR     R2, [R1]
        STR     R2, [R1]
        SVC     #10
"""
    machine, runner = make(build, source)
    machine.console.feed("typed\n")
    model = CacheModel()
    model.connect(machine)
    assert runner.run() is State.FINISHED and machine.console.text.startswith("Hi\n")
    model.update()
    assert model.accesses == 4                  # the four literals of LDR Rn, =...


def test_an_access_out_of_range_is_not_counted(build):
    """The store fails: the program ends with a runtime error, the cache never sees it."""
    machine, runner = make(build, "        .data\nvalue:  .word   5\n        .global _start\n"
                                  "        .text\n_start: LDR     R2, =value\n"
                                  "        LDR     R3, [R2]\n        MOV     R1, #0x50000000\n"
                                  "        STR     R3, [R1]\n        SVC     #10\n")
    model = CacheModel()
    model.connect(machine)
    runner.run()
    assert machine.stop_reason is StopReason.ERROR
    model.update()
    assert model.accesses == 2                  # the literal and the load


# Connected, disconnected, Reset and Assemble -------------------------------------------

LOOP = """\
        .data
        .balign 16
array:  .word   1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16
        .global _start
        .text
_start: LDR     R1, =array
        MOV     R2, #16
        MOV     R0, #0
loop:   LDR     R3, [R1], #4
        ADD     R0, R0, R3
        SUBS    R2, R2, #1
        BNE     loop
        SVC     #10
"""
# The literal (after the code, at 0x20), then 16 words at 0x30 in 4 blocks of 4 words: 5
# misses (the literal's block and the array's 4) and 12 hits in the default cache (8 blocks
# of 4 words, direct mapping).
ACCESSES, MISSES = 17, 5


def test_it_follows_the_program(build):
    machine, runner = make(build, LOOP)
    model = CacheModel()
    model.connect(machine)
    assert model.connected and model.machine is machine and machine.observers.active
    assert runner.run() is State.FINISHED
    assert model.update() and not model.update()
    assert (model.accesses, model.hits, model.misses) == (ACCESSES, ACCESSES - MISSES, MISSES)
    assert list(model.states).count(EMPTY) == 8 - MISSES


def test_nothing_is_observed_while_disconnected(build):
    machine, runner = make(build, LOOP)
    model = CacheModel()
    model.observe(machine)                      # not connected: the program is not observed
    assert model.machine is None and not machine.observers.active
    runner.step()                               # the literal
    model.connect(machine)
    runner.step()
    runner.step()
    runner.step()                               # the first word of the array
    model.disconnect()
    assert not machine.observers.active and model.accesses == 1
    runner.run()
    assert not model.update() and model.accesses == 1


def test_it_keeps_its_cache_across_reset_backstep_and_assemble(build):
    machine, runner = make(build, LOOP)
    model = CacheModel()
    model.connect(machine)
    for _ in range(4):
        runner.step()                           # the literal and the array's first word
    runner.backstep()                           # undone, but the access happened
    model.update()
    assert (model.accesses, model.misses) == (2, 2)
    runner.reset()                              # Reset, F12: the cache stays
    runner.run()
    model.update()
    assert (model.accesses, model.misses) == (2 + ACCESSES, 2 + MISSES - 2)
    other, other_runner = make(build, LOOP)     # a new Assemble: the window passes the machine
    model.observe(other)
    assert not machine.observers.active and model.machine is other
    other_runner.run()
    model.update()
    assert (model.accesses, model.misses) == (2 + 2 * ACCESSES, MISSES)
    model.observe(None)                         # the program's file closed: still connected
    assert model.connected and not other.observers.active


def test_connected_without_a_program_it_observes_the_next_one(build):
    model = CacheModel()
    model.connect(None)
    assert model.connected and model.machine is None and not model.update()
    machine, runner = make(build, LOOP)
    model.observe(machine)
    runner.run()
    model.update()
    assert model.accesses == ACCESSES


def test_disconnecting_takes_in_what_ran(build):
    machine, runner = make(build, LOOP)
    model = CacheModel()
    model.connect(machine)
    runner.run()
    model.disconnect()                          # no update before: taken in now
    assert model.accesses == ACCESSES


def test_two_tools_on_memory_each_see_every_access(build):
    machine, runner = make(build, LOOP)
    first, second = CacheModel(), CacheModel()
    first.connect(machine)
    second.connect(machine)
    second.set_blocks(1)
    runner.run()
    first.update()
    second.update()
    assert first.accesses == second.accesses == ACCESSES
    first.disconnect()
    assert machine.observers.active
    second.disconnect()
    assert not machine.observers.active


# Speed --------------------------------------------------------------------------------

COUNTDOWN = """\
        .data
value:  .word   0
        .global _start
        .text
_start: LDR     R4, =value
        LDR     R0, =10000
loop:   LDR     R3, [R4]
        SUBS    R0, R0, #1
        BNE     loop
        SVC     #10
"""


def emulator_calls(machine):
    """The instruction counts the machine asks the emulator for, from now on."""
    counts = []
    emu_start = machine.uc.emu_start

    def counted(begin, until, timeout=0, count=0):
        counts.append(count)
        return emu_start(begin, until, timeout, count)
    machine.uc.emu_start = counted
    return counts


def test_a_run_has_short_chunks_while_the_cache_watches_memory(build):
    """Each access calls Python, up to 16 for one instruction (LDM, VLDM): while the cache
    is connected the machine runs MEMORY_CHUNK instructions per emulator call, so that a
    slice, and looking up its accesses, stays short; else CHUNK, as without tools."""
    program = build(COUNTDOWN)
    machine = Machine(program)
    model = CacheModel()
    model.connect(machine)
    assert machine.observers.watches_memory
    counts = emulator_calls(machine)
    assert machine.run() is StopReason.EXIT
    assert len(counts) > 20 and set(counts) == {MEMORY_CHUNK}
    model.disconnect()
    assert not machine.observers.watches_memory
    machine = Machine(program)
    counts = emulator_calls(machine)
    assert machine.run() is StopReason.EXIT
    assert set(counts) == {CHUNK}


@pytest.mark.serial
def test_ten_million_instructions_with_the_data_cache_simulator(build):
    """Connected, the cache takes 4,000,004 accesses; collecting them is all a run pays,
    looking them up comes after (here once, at the end)."""
    machine = Machine(build(BENCHMARK.read_text()))
    model = CacheModel()
    model.connect(machine)
    start = time.perf_counter()
    assert machine.run() is StopReason.EXIT
    model.update()
    elapsed = time.perf_counter() - start
    # Two literals at 0x38 and 0x3C (one block), then always the word total at 0x40.
    assert machine.program.label_address("total") == 0x40
    assert (model.accesses, model.misses) == (4_000_004, 2)
    assert elapsed < TOOL_SECONDS, f"{elapsed:.3f} s"
