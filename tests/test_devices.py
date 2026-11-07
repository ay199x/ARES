# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The DE1-SoC's red LEDs, seven-segment displays, slide switches and push buttons: their
registers, and the program's access to them while a board is connected to the machine."""

import pytest
from test_machine import DEVICE_WARNING

from ares.devices import (EDGE_CAPTURE, HEX3_HEX0, HEX5_HEX4, INTERRUPT_MASK, KEYS, LEDS,
                          SWITCHES, Board)
from ares.machine import Machine, StopReason

# The digits 0-9 as the seven-segment displays show them (bit k lights segment k).
DIGITS = (0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F)


def word(board, address):
    return board.read(address, 4)


# The registers -----------------------------------------------------------------------

def test_the_ports_are_at_their_de1_soc_addresses():
    assert (LEDS, HEX3_HEX0, HEX5_HEX4, SWITCHES, KEYS) == (
        0xFF200000, 0xFF200020, 0xFF200030, 0xFF200040, 0xFF200050)
    assert (INTERRUPT_MASK, EDGE_CAPTURE) == (0xFF200058, 0xFF20005C)
    board = Board()
    inside = [0xFF200000, 0xFF20000F, 0xFF200020, 0xFF20002F, 0xFF200030, 0xFF200040,
              0xFF200050, 0xFF20005F]
    outside = [0xFF1FFFFF, 0xFF200010, 0xFF20001F, 0xFF200060, 0xFF201000, 0xFF20FFFC]
    assert all(address in board for address in inside)
    assert not any(address in board for address in outside)


def test_a_new_board_is_dark_with_its_switches_down():
    board = Board()
    assert (board.leds, board.hex3_hex0, board.hex5_hex4, board.switches, board.keys,
            board.interrupt_mask, board.edges) == (0, 0, 0, 0, 0, 0, 0)
    assert [word(board, address) for address in range(0xFF200000, 0xFF200060, 4)] == [0] * 24


def test_the_red_leds_keep_ten_bits():
    board = Board()
    board.write(LEDS, 4, 0xFFFFFFFF)
    assert board.leds == 0x3FF and word(board, LEDS) == 0x3FF      # the upper bits are ignored
    board.write(LEDS, 4, 0x205)
    assert word(board, LEDS) == 0x205


def test_the_seven_segment_displays_keep_32_bits_and_drive_hex0_to_hex5():
    board = Board()
    board.write(HEX3_HEX0, 4, DIGITS[3] << 24 | DIGITS[2] << 16 | DIGITS[1] << 8 | DIGITS[0])
    board.write(HEX5_HEX4, 4, 0xFFFF0000 | DIGITS[5] << 8 | DIGITS[4])
    assert [board.segments(n) for n in range(6)] == list(DIGITS[:6])
    assert word(board, HEX5_HEX4) == 0xFFFF0000 | DIGITS[5] << 8 | DIGITS[4]     # read back
    board.write(HEX3_HEX0, 4, 0x80808080 | DIGITS[8])        # bit 7 of a byte drives nothing
    assert [board.segments(n) for n in range(4)] == [DIGITS[8], 0, 0, 0]
    assert word(board, HEX3_HEX0) == 0x80808080 | DIGITS[8]


def test_the_switches_are_read_only():
    board = Board()
    board.flip(0)
    board.flip(9)
    assert board.switches == 0x201 and word(board, SWITCHES) == 0x201
    board.write(SWITCHES, 4, 0)
    assert word(board, SWITCHES) == 0x201
    board.flip(0)
    assert word(board, SWITCHES) == 0x200


def test_a_key_reads_1_while_pressed_and_its_edge_stays_until_written():
    board = Board()
    board.press(1)
    assert word(board, KEYS) == 0b0010 and word(board, EDGE_CAPTURE) == 0b0010
    board.press(3)
    board.release(1)
    assert word(board, KEYS) == 0b1000 and word(board, EDGE_CAPTURE) == 0b1010
    board.write(KEYS, 4, 0xF)                       # the Data register is read-only
    assert word(board, KEYS) == 0b1000
    board.write(EDGE_CAPTURE, 4, 0)                 # any value clears every bit
    assert word(board, EDGE_CAPTURE) == 0
    board.release(3)
    board.press(0)
    board.release(0)
    assert word(board, KEYS) == 0 and word(board, EDGE_CAPTURE) == 0b0001
    board.write(EDGE_CAPTURE + 3, 1, 0x80)          # a byte of it clears it too
    assert word(board, EDGE_CAPTURE) == 0


def test_the_interrupt_mask_keeps_four_bits():
    board = Board()
    board.write(INTERRUPT_MASK, 4, 0xFFFFFFFF)
    assert word(board, INTERRUPT_MASK) == 0xF
    board.press(2)                                  # and enables nothing: ARES has no interrupts
    assert word(board, INTERRUPT_MASK) == 0xF and word(board, EDGE_CAPTURE) == 0b0100


@pytest.mark.parametrize("address", [LEDS + 4, LEDS + 8, LEDS + 12, HEX3_HEX0 + 4,
                                     HEX3_HEX0 + 12, HEX5_HEX4 + 8, SWITCHES + 4,
                                     SWITCHES + 12, KEYS + 4], ids=hex)
def test_registers_a_port_does_not_have_read_0_and_ignore_writes(address):
    board = Board()
    board.flip(4)
    board.press(1)
    board.write(address, 4, 0xFFFFFFFF)
    assert word(board, address) == 0
    assert (board.leds, board.hex3_hex0, board.hex5_hex4, board.switches, board.keys,
            board.interrupt_mask, board.edges) == (0, 0, 0, 0x10, 0b10, 0, 0b10)


def test_byte_and_halfword_accesses_act_on_the_bytes_of_the_register():
    board = Board()
    board.write(HEX3_HEX0, 4, 0x4F5B063F)            # 3 2 1 0
    assert board.read(HEX3_HEX0 + 1, 1) == DIGITS[1]
    assert board.read(HEX3_HEX0 + 2, 2) == 0x4F5B
    board.write(HEX3_HEX0 + 1, 1, DIGITS[7])        # HEX1 alone
    assert [board.segments(n) for n in range(4)] == [DIGITS[0], DIGITS[7], DIGITS[2], DIGITS[3]]
    board.write(HEX3_HEX0 + 2, 2, DIGITS[9] << 8 | DIGITS[8])     # HEX3 and HEX2
    assert word(board, HEX3_HEX0) == 0x6F7F073F
    board.write(HEX5_HEX4 + 1, 1, DIGITS[5])
    assert (board.segments(4), board.segments(5)) == (0, DIGITS[5])
    board.write(LEDS + 1, 1, 0xFF)                  # bits 15-8: LEDR9 and LEDR8 only
    assert word(board, LEDS) == 0x300
    board.write(LEDS, 2, 0x0001)
    assert word(board, LEDS) == 0x001
    board.flip(9)
    assert board.read(SWITCHES + 1, 1) == 0b10 and board.read(SWITCHES, 1) == 0


def test_an_access_across_registers_takes_each_byte_from_its_own():
    board = Board()
    board.write(HEX5_HEX4, 4, 0x11223344)
    assert board.read(HEX5_HEX4 - 2, 4) == 0x33440000      # after two bytes of no register
    board.write(HEX3_HEX0 + 14, 4, 0x77665544)              # the same bytes written
    assert board.hex3_hex0 == 0 and board.hex5_hex4 == 0x11227766
    board.press(0)
    assert board.read(EDGE_CAPTURE - 1, 2) == 0x0100         # the mask's last byte, then the edges
    assert board.read(EDGE_CAPTURE + 3, 2) == 0             # past the end of the board


def test_reset_switches_the_board_off():
    board = Board()
    board.write(LEDS, 4, 0x3FF)
    board.write(HEX3_HEX0, 4, 0x7F7F7F7F)
    board.write(HEX5_HEX4, 4, 0x7F7F)
    board.write(INTERRUPT_MASK, 4, 0xF)
    board.flip(3)
    board.press(2)
    board.reset()
    assert (board.leds, board.hex3_hex0, board.hex5_hex4, board.switches, board.keys,
            board.interrupt_mask, board.edges) == (0, 0, 0, 0, 0, 0, 0)


def test_changes_count_what_changed():
    board = Board()
    changes = board.changes
    board.write(LEDS, 4, 0)                 # the same value: nothing changed
    board.write(SWITCHES, 4, 5)             # read-only
    board.write(EDGE_CAPTURE, 4, 1)         # already clear
    assert board.changes == changes
    board.write(LEDS, 4, 1)
    assert board.changes == changes + 1
    board.flip(0)
    board.press(1)                          # its Data and its Edgecapture bit
    board.release(1)
    assert board.changes == changes + 5


def test_put_back_restores_what_the_program_wrote():
    """Backstep: the bytes a write replaced go back; switches and keys stay the user's,
    and keys pressed since a write cleared the Edgecapture register keep their bits."""
    board = Board()
    board.write(HEX3_HEX0, 4, 0x3F)
    board.put_back(HEX3_HEX0 + 1, b"\x06")
    assert word(board, HEX3_HEX0) == 0x063F
    board.put_back(LEDS, (0xFFFF).to_bytes(4, "little"))
    assert word(board, LEDS) == 0x3FF
    board.put_back(INTERRUPT_MASK, b"\x05\x00\x00\x00")
    assert word(board, INTERRUPT_MASK) == 5
    board.flip(1)
    board.press(0)
    board.put_back(SWITCHES, bytes(4))
    board.put_back(KEYS, bytes(4))
    assert (board.switches, board.keys) == (0b10, 0b1)
    board.write(EDGE_CAPTURE, 4, 0)         # the program clears the bit of KEY0 ...
    board.press(2)                          # ... and KEY2 is pressed afterwards
    board.put_back(EDGE_CAPTURE, b"\x01\x00\x00\x00")
    assert word(board, EDGE_CAPTURE) == 0b0101
    board.put_back(0xFF200060, b"\x01")     # past the board: nothing
    board.put_back(0xFF200010, b"\x01")


def test_before_write_keeps_the_whole_registers_a_write_reaches():
    """What Backstep keeps of a write: whole words, since a write to one byte of the
    Edgecapture register clears all four bits."""
    board = Board()
    board.write(HEX3_HEX0, 4, 0x4F5B063F)
    board.press(2)
    assert board.before_write(HEX3_HEX0 + 1, 1) == (HEX3_HEX0, bytes.fromhex("3f065b4f"))
    assert board.before_write(EDGE_CAPTURE + 1, 1) == (EDGE_CAPTURE, bytes.fromhex("04000000"))
    assert board.before_write(HEX3_HEX0 - 2, 4) == (                # from the gap into HEX1-0
        HEX3_HEX0 - 4, bytes.fromhex("000000003f065b4f"))
    assert board.before_write(HEX3_HEX0 - 8, 4) is None                # the gap alone
    assert board.before_write(KEYS + 0x10, 4) is None                  # past the board


# The program and the board --------------------------------------------------------------

LIGHTS = """\
        .global _start
_start: LDR     R0, =0xFF200000
        LDR     R1, =0x2A5
        STR     R1, [R0]                @ LEDR9-0
        LDR     R2, =0x4F5B063F
        STR     R2, [R0, #0x20]         @ HEX3-HEX0: 3 2 1 0
        MOV     R2, #0x6D
        STRB    R2, [R0, #0x31]         @ HEX5: 5
        LDR     R3, [R0, #0x40]         @ SW9-0
        LDR     R4, [R0, #0x50]         @ KEY3-0
        LDR     R5, [R0, #0x5C]         @ Edgecapture
        STR     R5, [R0, #0x5C]
        LDR     R6, [R0, #0x5C]
        LDRB    R7, [R0, #0x22]
        LDR     R8, [R0]
        B       .
"""


def connected(build, source, board=None):
    machine = Machine(build(source))
    machine.board = board if board is not None else Board()
    return machine


def test_the_program_drives_a_connected_board(build):
    board = Board()
    board.flip(0)
    board.flip(7)
    board.press(1)
    machine = connected(build, LIGHTS, board)
    assert machine.run(time_limit=10) is StopReason.SELF_BRANCH
    assert board.leds == 0x2A5 and machine.reg(8) == 0x2A5
    assert [board.segments(n) for n in range(6)] == [*DIGITS[:4], 0, DIGITS[5]]
    assert (machine.reg(3), machine.reg(4), machine.reg(5), machine.reg(6)) == (
        0x81, 0b10, 0b10, 0)
    assert machine.reg(7) == DIGITS[2]
    assert board.edges == 0 and board.keys == 0b10
    assert machine.warnings == []


def test_other_device_addresses_still_warn_while_a_board_is_connected(build):
    machine = connected(build, """\
        .global _start
_start: LDR     R0, =0xFF200010         @ no device there
        MOV     R1, #1
        STR     R1, [R0]
        LDR     R2, [R0]
        LDR     R0, =0xFF200060         @ JP1, not simulated
        STR     R1, [R0]
        LDR     R0, =0xFF202000         @ the interval timer: ARES has none
        LDR     R3, [R0]
        LDR     R0, =0xFF201000
        MOV     R1, #'A'
        STR     R1, [R0]                @ the JTAG UART works as always
        B       .
""")
    assert machine.run(time_limit=10) is StopReason.SELF_BRANCH
    assert machine.warnings == [DEVICE_WARNING.format(a)
                                for a in (0xFF200010, 0xFF200060, 0xFF202000)]
    assert machine.console.text.startswith("A")


def test_without_a_board_the_addresses_are_not_simulated(build):
    machine = Machine(build(LIGHTS))
    assert machine.board is None
    assert machine.run(time_limit=10) is StopReason.SELF_BRANCH
    assert machine.reg(8) == 0 and machine.reg(7) == 0
    assert DEVICE_WARNING.format(0xFF200000) in machine.warnings


def test_the_board_stays_connected_across_reset(build):
    board = Board()
    machine = connected(build, LIGHTS, board)
    machine.run(time_limit=10)
    machine.reset()
    assert machine.board is board and board.leds == 0x2A5        # the board keeps it all
    board.write(LEDS, 4, 0)
    machine.run(time_limit=10)
    assert board.leds == 0x2A5


def test_peek_words_shows_the_board_without_warnings(build):
    board = Board()
    board.flip(2)
    machine = Machine(build(".global _start\n_start: B .\n"))
    assert machine.peek_words(SWITCHES, 1) == [0]
    machine.board = board
    board.write(HEX3_HEX0, 4, 0x3F)
    board.press(3)
    assert machine.peek_words(LEDS, 24) == [0] * 8 + [0x3F, 0, 0, 0] + [0] * 4 + [
        0b100, 0, 0, 0, 0b1000, 0, 0, 0b1000]
    assert machine.peek_words(0xFF201000, 2) == [0, 64 << 16]          # the JTAG UART
    assert machine.warnings == [] and board.edges == 0b1000


STEPS = """\
        .global _start
_start: LDR     R0, =0xFF200000
        MOV     R1, #0x3F
        STR     R1, [R0, #0x20]         @ HEX0: 0
        MOV     R1, #0x06
        STRB    R1, [R0, #0x21]         @ HEX1: 1
        STR     R1, [R0]                @ LEDR2 and LEDR1
        STR     R1, [R0, #0x58]         @ Interruptmask
        STR     R1, [R0, #0x5C]         @ clears Edgecapture
        STR     R1, [R0, #0x40]         @ the switches: read-only
        B       .
"""


@pytest.mark.parametrize("record", ["step", "slice"])
def test_backstep_undoes_the_programs_writes_to_the_board(build, record):
    board = Board()
    board.flip(5)
    board.press(0)
    machine = connected(build, STEPS, board)
    if record == "step":
        for _ in range(9):
            machine.step()
    else:
        machine.run_slice(record=True)
    assert (board.hex3_hex0, board.leds, board.interrupt_mask, board.edges) == (
        0x063F, 0x06, 0x06, 0)
    board.press(3)                          # pressed after the program cleared the edges
    assert machine.backstep()               # the store to the switches: nothing to undo
    assert machine.backstep()
    assert board.edges == 0b1001            # KEY0's press is back; KEY3's stays
    assert machine.backstep() and board.interrupt_mask == 0
    assert machine.backstep() and board.leds == 0
    assert machine.backstep() and board.hex3_hex0 == 0x3F
    machine.backstep()
    assert machine.backstep() and board.hex3_hex0 == 0
    assert board.switches == 0b100000 and board.keys == 0b1001
    assert machine.warnings == []


def test_backstep_brings_back_the_edges_a_byte_or_halfword_write_cleared(build):
    board = Board()
    board.press(0)
    board.press(2)
    machine = connected(build, """\
        .global _start
_start: LDR     R0, =0xFF200000
        MOV     R1, #0
        STRB    R1, [R0, #0x5D]         @ clears all of Edgecapture
        STRH    R1, [R0, #0x5E]
        B       .
""", board)
    for _ in range(3):
        machine.step()
    assert board.edges == 0
    board.press(1)                          # pressed after the program cleared the edges
    machine.step()
    assert board.edges == 0
    assert machine.backstep() and board.edges == 0b0010
    assert machine.backstep() and board.edges == 0b0111


def test_backstep_undoes_an_unaligned_store_from_the_gap_into_the_displays(build):
    board = Board()
    machine = connected(build, """\
        .global _start
_start: LDR     R0, =0xFF20001E
        LDR     R1, =0x063F0000
        STR     R1, [R0]                @ 0xFF20001E-0xFF20001F: no device; then HEX0, HEX1
        B       .
""", board)
    for _ in range(3):
        machine.step()
    assert board.hex3_hex0 == 0x063F
    assert machine.backstep() and board.hex3_hex0 == 0
    assert machine.warnings == [DEVICE_WARNING.format(a) for a in (0xFF20001E, 0xFF20001F)]


def test_backstep_with_the_board_disconnected_leaves_it_alone(build):
    board = Board()
    machine = connected(build, STEPS, board)
    for _ in range(5):
        machine.step()
    machine.board = None
    assert machine.backstep() and machine.backstep()
    assert board.hex3_hex0 == 0x063F and machine.warnings == []


def test_a_polling_program_sees_the_switches_and_keys_change(build):
    """Each switch lights its LED until KEY1 is pressed: the board changes between runs."""
    board = Board()
    machine = connected(build, """\
        .global _start
_start: LDR     R0, =0xFF200000
        STR     R0, [R0, #0x5C]         @ forget earlier presses
loop:   LDR     R1, [R0, #0x40]
        STR     R1, [R0]
        LDR     R2, [R0, #0x5C]
        TST     R2, #2
        BEQ     loop
        SVC     #10
""", board)
    assert machine.run(time_limit=0.05) is None             # still polling
    assert board.leds == 0
    board.flip(3)
    board.flip(8)
    assert machine.run(time_limit=0.05) is None
    assert board.leds == 0x108
    board.press(0)                                          # not KEY1
    assert machine.run(time_limit=0.05) is None
    board.press(1)
    board.release(1)
    assert machine.run(time_limit=10) is StopReason.EXIT
    assert board.edges == 0b11
