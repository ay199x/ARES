@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ Speed benchmark: a loop of 10,000,000 instructions (5 x 2,000,000)
@ that adds 2,000,000 + ... + 1 into a word in memory, then prints it.

        .global _start
        .text
_start:
        LDR     R0, =2000000
        MOV     R3, #0
        LDR     R4, =total
        STR     R3, [R4]
loop:
        LDR     R3, [R4]
        ADD     R3, R3, R0
        STR     R3, [R4]
        SUBS    R0, R0, #1
        BNE     loop

        LDR     R0, [R4]
        SVC     #34             @ print hexadecimal
        MOV     R0, #'\n'
        SVC     #11
        SVC     #10

        .data
total:  .word   0
