@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ For the Dynamic Instruction Counter: uses every category and every encoding format.
@ Open the tool, click Connect to ARM and run: each line of its two panels gets a count.

        .data
values: .word   3, 5, 7, 11
bytes:  .byte   1, 2, 3, 4
        .balign 4
text:   .asciz  "Result: "
newline: .asciz "\n"

        .global _start
        .text
_start: LDR     R4, =values     @ Load/Store (Immediate)
        LDR     R5, =bytes
        MOV     R6, #0          @ Data Processing (Immediate)
        MOV     R1, #0
loop:   LDR     R0, [R4, R1, LSL #2]    @ Load/Store (Register)
        LDRB    R2, [R5, R1]    @ Memory (Byte Access)
        MUL     R3, R0, R2      @ Multiply
        ADD     R6, R6, R3      @ Data Processing (Register)
        ADD     R1, R1, #1
        CMP     R1, #4
        LDRNE   R0, [R4]        @ Conditional Load & Others
        BNE     loop            @ Branch

        PUSH    {R4, R6}        @ Load/Store Multiple
        POP     {R4, R6}

        LDR     R0, =text
        SVC     #4              @ Supervisor Call & Others
        MOV     R0, R6
        SVC     #1
        LDR     R0, =newline
        SVC     #4
        SVC     #10
