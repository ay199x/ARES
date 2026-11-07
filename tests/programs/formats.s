@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ Every encoding format and instruction category the Dynamic Instruction
@ Counter tells apart: data processing with a register or an immediate
@ operand, loads and stores with an immediate or a register offset (also in
@ R9-R12, and conditional, byte and halfword ones), multiplies, PUSH/POP and
@ LDM/STM, branches (B, BNE, BL, BLX, BX) and system calls. Prints 2145.

        .data
table:  .word   1, 2, 3, 4, 5, 6, 7, 8
bytes:  .byte   10, 20, 30, 40
halves: .hword  100, 200
        .balign 4
copy:   .space  8
total:  .word   0

        .global _start
        .text
_start:
        LDR     R1, =table
        MOV     R9, #4              @ offsets in R9-R12 (SB, SL, FP, IP)
        MOV     R10, #8
        MOV     R11, #12
        MOV     R12, #16
        LDR     R2, [R1, R9]        @ 2
        LDR     R3, [R1, R10]       @ 3
        LDR     R4, [R1, R11]       @ 4
        LDR     R5, [R1, R12]       @ 5
        ADD     R0, R2, R3
        ADD     R0, R0, R4
        ADD     R0, R0, R5          @ 14
        MOV     R6, #5
        LDR     R7, [R1, R6, LSL #2]    @ table[5] = 6
        ADD     R0, R0, R7          @ 20
        MOV     R6, #4
        ADD     R8, R1, #28
        LDR     R7, [R8, -R6]       @ table[6] = 7
        ADD     R0, R0, R7          @ 27
        LDR     R8, =copy
        STMIA   R8, {R2, R3}
        LDMIA   R8, {R4, R5}
        ADD     R0, R0, R4
        ADD     R0, R0, R5          @ 32
        MOV     R4, #3
        MUL     R5, R4, R4          @ 9
        MLA     R0, R5, R4, R0      @ 59
        UMULL   R6, R7, R5, R4      @ 27
        ADD     R0, R0, R6          @ 86
        LDR     R1, =bytes
        LDRB    R2, [R1]            @ 10
        LDRB    R3, [R1, #3]        @ 40
        LDRSB   R4, [R1, #1]        @ 20
        ADD     R0, R0, R2
        ADD     R0, R0, R3
        ADD     R0, R0, R4          @ 156
        STRB    R2, [R1, #2]
        LDR     R1, =halves
        LDRH    R2, [R1, #2]        @ 200
        ADD     R0, R0, R2          @ 356
        LDR     R3, [R1], R9        @ post-indexed by R9
        LDR     R1, =table
        MOV     R4, #0
        CMP     R4, #0
        LDREQ   R2, [R1]            @ 1
        LDRNE   R3, [R1]            @ condition fails
        ADDEQ   R0, R0, R2          @ 357
        LDRNEB  R3, [R1]
        STREQ   R0, [R1]
        BL      triple              @ 1071
        LDR     R3, =twice
        BLX     R3                  @ 2142
        MOV     R2, #3
again:  ADD     R0, R0, #1
        SUBS    R2, R2, #1
        BNE     again               @ 2145
        B       print
        MOV     R0, #0              @ never runs
print:  LDR     R1, =total
        STR     R0, [R1]
        SVC     #1
        MOV     R0, #'\n'
        SVC     #11
        SVC     #10

@ R0 = 3 * R0, keeping R4 (saved on the stack with LR).
triple:
        PUSH    {R4, LR}
        ADD     R4, R0, R0, LSL #1
        MOV     R0, R4
        POP     {R4, PC}

@ R0 = 2 * R0, returning with BX LR.
twice:
        LSL     R0, R0, #1
        BX      LR
