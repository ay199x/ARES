@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ For the ARM X-Ray: every instruction lies inside the datapath, so each one that runs animates.
@ Open the tool, click Connect to ARM, then Step, or Play on an instruction.
@ It adds up the numbers and keeps the largest: 0x17 and 0x9 follow them in the Data Segment.

        .data
numbers: .word  3, 9, 4, 7
total:  .word   0
largest: .word  0

        .global _start
        .text
_start: LDR     R0, =numbers    @ a load: the address of the numbers
        MOV     R1, #4          @ an immediate operand: how many numbers
        BL      add_up          @ BL: LR takes the address of the next instruction
        LDR     R4, =total
        STR     R2, [R4]        @ a store with an immediate offset
        STR     R3, [R4, #4]
        MOV     R5, R2, LSL #1  @ the shifter: twice the total
stop:   B       stop            @ a branch to itself ends the program

@ add_up: R0 = the numbers, R1 = how many. R2 = their total, R3 = the largest.
add_up: MOV     R2, #0
        MOV     R3, #0
        MOV     R6, #0          @ R6 = which number
next:   LDR     R7, [R0, R6, LSL #2]    @ a load with a register offset
        ADD     R2, R2, R7      @ a register operand
        CMP     R7, R3          @ CMP writes only the flags
        MOVGT   R3, R7          @ runs only when R7 is the larger: watch PCPlus4 when it does not
        ADD     R6, R6, #1
        CMP     R6, R1
        BLT     next            @ a conditional branch
        BX      LR              @ the return: LR goes through the ALU to the PC
