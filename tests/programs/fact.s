@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ Recursive factorial: prints 5! = 120.

        .global _start
        .text
_start:
        MOV     R0, #5
        BL      factorial
        SVC     #1
        MOV     R0, #'\n'
        SVC     #11
        SVC     #10

@ R0 = n! for n in R0.
factorial:
        PUSH    {R4, LR}
        MOV     R4, R0
        CMP     R0, #1
        MOVLE   R0, #1
        BLE     done
        SUB     R0, R0, #1
        BL      factorial
        MUL     R0, R4, R0
done:
        POP     {R4, PC}
