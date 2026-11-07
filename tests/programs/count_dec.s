@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ Counts from 0 to 15, one number per line, in decimal.

        .global _start
        .text
_start:
        MOV     R4, #0
loop:
        MOV     R0, R4
        SVC     #1
        MOV     R0, #'\n'
        SVC     #11
        ADD     R4, R4, #1
        CMP     R4, #16
        BLT     loop
        SVC     #10
