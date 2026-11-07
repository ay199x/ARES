@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ For the Keyboard and Display MMIO Simulator: types what you type, in capitals, until Return.
@ Open the tool, click Connect to ARM, run the program, then type in the keyboard area.

        .global _start
        .text
_start: LDR     R0, =0xFF201000 @ the JTAG UART's data register
read:   LDR     R1, [R0]        @ bit 15 (RVALID) says a key was there
        TST     R1, #0x8000
        BEQ     read            @ no key yet: read again
        AND     R1, R1, #0xFF   @ the key
        CMP     R1, #'a'
        BLT     show
        CMP     R1, #'z'
        SUBLE   R1, R1, #32     @ a small letter becomes a capital
show:   STR     R1, [R0]        @ show it on the display
        CMP     R1, #10         @ Return ends the program
        BNE     read
        SVC     #10             @ exit
