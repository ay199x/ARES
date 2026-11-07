@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ For the Floating Point Representation tool: puts three numbers in S0, one after the other.
@ Step through the program and type each value of Coproc 10 into the tool to see its sign,
@ exponent and fraction. It also prints each number's 32 bits in hexadecimal.

        .data
numbers: .float 1.0, -0.5, 0.1
        .equ    COUNT, 3
newline: .asciz "\n"

        .global _start
        .text
_start: LDR     R4, =numbers
        MOV     R5, #COUNT      @ R5: counts down to 0
next:   VLDR    S0, [R4]
        ADD     R4, R4, #4
        VMOV    R0, S0          @ the same 32 bits, in an integer register
        SVC     #34             @ print hexadecimal
        LDR     R0, =newline
        SVC     #4              @ print string
        SUBS    R5, R5, #1
        BNE     next
        SVC     #10             @ exit
