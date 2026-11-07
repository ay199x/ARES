# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The DE1-SoC's red LEDs, seven-segment displays, slide switches and push buttons.

A Board holds the registers of these four parallel ports as Intel's "DE1-SoC
Computer System with ARM Cortex-A9" (for Quartus Prime 16.1, November 2016)
describes them. A parallel port has its Data register at its base address,
a Direction register at base + 4, an Interruptmask register at base + 8 and
an Edgecapture register at base + 0xC, each where the port has it (section
2.5.6):

- Red LEDs LEDR9-0 (section 2.5.7): a 10-bit Data register at 0xFF200000,
  written and read back with word accesses; bit k lights LEDRk. The upper
  bits are ignored: they read 0.
- Seven-segment displays HEX5-HEX0 (section 2.5.8): two 32-bit Data
  registers, written and read back with word accesses. The one at
  0xFF200020 drives HEX0 with bits 6-0, HEX1 with bits 14-8, HEX2 with bits
  22-16 and HEX3 with bits 30-24; the one at 0xFF200030 drives HEX4 with
  bits 6-0 and HEX5 with bits 14-8. Within a display's bits, bit k lights
  segment k: 0 the top one, 1 upper right, 2 lower right, 3 the bottom one,
  4 lower left, 5 upper left and 6 the middle one (0x3F shows 0, 0x06
  shows 1). Bit 7 of each byte drives nothing.
- Slide switches SW9-0 (section 2.5.9): a 10-bit read-only Data register at
  0xFF200040; bit k is 1 while SWk is up.
- Push buttons KEY3-0 (sections 2.5.10 and 3.4.1), three 4-bit registers
  from 0xFF200050: the read-only Data register has bit k = 1 while KEYk is
  pressed; the Interruptmask register at 0xFF200058 keeps its bits (ARES has
  no interrupts, so they enable nothing); in the Edgecapture register at
  0xFF20005C a key's bit becomes 1 when the key is pressed and stays 1 until
  the program writes any value to the register, which clears every bit.

The rest of the four ports reads 0 and ignores writes: the registers a port
does not have (such as the LEDs' Direction register at 0xFF200004), and the
read-only ones when written. The manual speaks of word accesses; a byte or
halfword access reads or writes those bytes of the registers, as part of a
word access would: a byte written to 0xFF200021 changes HEX1 alone, and a
write to any byte of the Edgecapture register clears it. No device of the
DE1-SoC is at 0xFF200010-0xFF20001F, between the LEDs and the displays.
"""

LEDS = 0xFF200000               # red LEDs LEDR9-0
HEX3_HEX0 = 0xFF200020          # seven-segment displays HEX3-HEX0
HEX5_HEX4 = 0xFF200030          # seven-segment displays HEX5 and HEX4
SWITCHES = 0xFF200040           # slide switches SW9-0
KEYS = 0xFF200050               # push buttons KEY3-0: their Data register
INTERRUPT_MASK = KEYS + 8
EDGE_CAPTURE = KEYS + 0xC
PORT_SIZE = 0x10                # a parallel port's four registers

LED_COUNT = 10
DISPLAY_COUNT = 6
SEGMENT_COUNT = 7               # in a display's byte; bit 7 drives nothing
SWITCH_COUNT = 10
KEY_COUNT = 4
_LED_BITS = (1 << LED_COUNT) - 1
_KEY_BITS = (1 << KEY_COUNT) - 1

# The registers the program reads: address -> the Board attribute that holds the value.
_REGISTERS = {LEDS: "leds", HEX3_HEX0: "hex3_hex0", HEX5_HEX4: "hex5_hex4",
              SWITCHES: "switches", KEYS: "keys", INTERRUPT_MASK: "interrupt_mask",
              EDGE_CAPTURE: "edges"}
# The registers the program writes (all but the Edgecapture's write clearing it):
# address -> the attribute, and the bits it keeps.
_WRITABLE = {LEDS: ("leds", _LED_BITS), HEX3_HEX0: ("hex3_hex0", 0xFFFFFFFF),
             HEX5_HEX4: ("hex5_hex4", 0xFFFFFFFF), INTERRUPT_MASK: ("interrupt_mask", _KEY_BITS)}


class Board:
    """The registers of the four ports, and the positions of the switches and keys.

    The program reads and writes the registers with read() and write(), the
    user flips the switches and presses the keys. changes counts every change
    of a register, a switch or a key, so a window can tell when to draw the
    board again.
    """

    def __init__(self):
        self.changes = 0
        self.reset()

    def reset(self):
        """The board as when it is switched on: LEDs and displays dark, switches down,
        keys up, Interruptmask and Edgecapture 0."""
        for name in _REGISTERS.values():
            self._set(name, 0)

    def __contains__(self, address):
        """True for an address of the four ports (the gap after the LEDs is not theirs)."""
        return LEDS <= address < LEDS + PORT_SIZE or HEX3_HEX0 <= address < KEYS + PORT_SIZE

    def segments(self, display):
        """The bits of display HEXn (n = display): bit k lights its segment k."""
        word = self.hex3_hex0 if display < 4 else self.hex5_hex4
        return word >> 8 * (display % 4) & ((1 << SEGMENT_COUNT) - 1)

    # The program's accesses ----------------------------------------------------------

    def read(self, address, size):
        """The value of size bytes from address, as the program reads them; reading changes
        nothing."""
        offset = address & 3
        if offset + size > 4:                   # across registers: each gives its bytes
            low = 4 - offset
            return self.read(address, low) | self.read(address + low, size - low) << 8 * low
        name = _REGISTERS.get(address - offset)
        word = 0 if name is None else getattr(self, name)
        return word >> 8 * offset & (1 << 8 * size) - 1

    def write(self, address, size, value):
        """The program writes the low size bytes of value to address."""
        self._put(address, size, value, False)

    def before_write(self, address, size):
        """What Backstep keeps of the program's write of size bytes at address, before it
        is made: (the first address, the bytes) of the whole words the write reaches, as a
        write to one byte of the Edgecapture register clears all of it; None when the write
        reaches none of the four ports."""
        start, end = address & ~3, (address + size + 3) & ~3
        if not any(word in self for word in range(start, end, 4)):
            return None
        return start, self.read(start, end - start).to_bytes(end - start, "little")

    def put_back(self, address, old):
        """Backstep: the bytes old, which the program's write at address replaced, are back.

        Keys pressed since a write cleared the Edgecapture register keep their
        bits there; the switches and keys themselves are the user's.
        """
        self._put(address, len(old), int.from_bytes(old, "little"), True)

    def _put(self, address, size, value, back):
        """Write the low size bytes of value to address; with back, put them back."""
        offset = address & 3
        if offset + size > 4:
            low = 4 - offset
            self._put(address, low, value, back)
            self._put(address + low, size - low, value >> 8 * low, back)
            return
        base = address - offset
        if base == EDGE_CAPTURE:        # a write clears it; put back, its bits join the presses
            self._set("edges", (self.edges | value << 8 * offset & _KEY_BITS) if back else 0)
        elif base in _WRITABLE:
            name, bits = _WRITABLE[base]
            mask = (1 << 8 * size) - 1 << 8 * offset
            self._set(name, (getattr(self, name) & ~mask | value << 8 * offset & mask) & bits)

    def _set(self, name, value):
        if getattr(self, name, None) != value:
            setattr(self, name, value)
            self.changes += 1

    # The user's switches and keys ------------------------------------------------------

    def flip(self, switch):
        """The user flips switch SWn (n = switch)."""
        self._set("switches", self.switches ^ 1 << switch)

    def press(self, key):
        """Key KEYn (n = key) is pressed: its bits in the Data and Edgecapture registers
        become 1."""
        self._set("keys", self.keys | 1 << key)
        self._set("edges", self.edges | 1 << key)

    def release(self, key):
        """Key KEYn (n = key) is let go."""
        self._set("keys", self.keys & ~(1 << key))
