@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ A function using PUSH and POP: factorial, which calls itself.

        .data
text:   .asciz  "6 factorial = "
newline: .asciz "\n"

        .global _start
        .text
_start: LDR     R0, =text
        SVC     #4              @ print string
        MOV     R0, #6
        BL      factorial       @ the result comes back in R0
        SVC     #1              @ print integer
        LDR     R0, =newline
        SVC     #4
        SVC     #10             @ exit

@ factorial: R0 = n, returns n! in R0. Each call keeps its own n and return address on the stack.
factorial:
        PUSH    {R4, LR}
        MOV     R4, R0          @ R4: this call's n
        CMP     R0, #1
        MOVLE   R0, #1          @ 1! = 1 and 0! = 1: no more calls
        BLE     return
        SUB     R0, R0, #1
        BL      factorial       @ R0 = (n - 1)!
        MUL     R0, R4, R0      @ R0 = n x (n - 1)!
return: POP     {R4, PC}        @ back to the caller, with R4 as it was
