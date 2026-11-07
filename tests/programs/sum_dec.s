@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ Adds two integers and prints the sum in decimal.

        .global _start
        .text
_start:
        MOV     R10, #42
        LDR     R11, =341
        ADD     R12, R10, R11
        LDR     R0, =label
        SVC     #4              @ print string
        MOV     R0, R12
        SVC     #1              @ print integer
        MOV     R0, #'\n'
        SVC     #11             @ print character
        SVC     #10             @ exit

        .data
label:  .asciz  "Sum of 2 integers in Decimal: "
