@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ For the Memory Reference Visualization: a bubble sort, which reads and writes the same few
@ words again and again. Open the tool, choose .data, click Connect to ARM and run.

        .data
numbers: .word  42, 7, 19, 88, 3, 56, 24, 71
        .equ    COUNT, 8
space:  .asciz  " "
newline: .asciz "\n"

        .global _start
        .text
_start: LDR     R4, =numbers
        MOV     R5, #COUNT - 1  @ R5: the comparisons in this pass
pass:   MOV     R1, #0          @ R1: the index
compare:
        ADD     R2, R4, R1, LSL #2
        LDR     R0, [R2]        @ this element ...
        LDR     R3, [R2, #4]    @ ... and the next one
        CMP     R0, R3
        STRGT   R3, [R2]        @ in the wrong order: swap them
        STRGT   R0, [R2, #4]
        ADD     R1, R1, #1
        CMP     R1, R5
        BLT     compare
        SUBS    R5, R5, #1      @ the largest left is in its place now
        BNE     pass

        MOV     R1, #0          @ print the sorted numbers
print:  LDR     R0, [R4, R1, LSL #2]
        SVC     #1              @ print integer
        LDR     R0, =space
        SVC     #4              @ print string
        ADD     R1, R1, #1
        CMP     R1, #COUNT
        BNE     print
        LDR     R0, =newline
        SVC     #4
        SVC     #10             @ exit
