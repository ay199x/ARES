@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ For the Digital Lab Sim: a light runs along the red LEDs while HEX0 counts from 0 to 9, then
@ the slide switches that are up at that moment light their LEDs and the program ends.
@ Open Tools > Digital Lab Sim, click Connect to ARM, then run the program, and move a few
@ switches up during the two seconds it counts.

        .data
digits: .byte   0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F  @ 0 to 9 on a display

        .global _start
        .text
_start: LDR     R4, =0xFF200000 @ the LEDs; the other devices are at offsets from here
        LDR     R5, =digits
        MOV     R6, #0          @ R6: the count
        MOV     R7, #1          @ R7: the LED that is lit
next:   STR     R7, [R4]        @ show it
        LDRB    R0, [R5, R6]
        STR     R0, [R4, #0x20] @ HEX0 shows the count
        MOV     R0, #200
        SVC     #32             @ sleep for 200 milliseconds
        LSL     R7, R7, #1
        ADD     R6, R6, #1
        CMP     R6, #10
        BNE     next
        LDR     R0, [R4, #0x40] @ the slide switches ...
        STR     R0, [R4]        @ ... light their LEDs
        SVC     #10             @ exit
