@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ For the ARM X-Ray: every instruction lies inside the datapath, so each one that runs animates.
@ Open the tool, click Connect to ARM, then Step: each Step plays the film of its instruction.
@ It adds up the numbers and keeps the largest: 0x17 and 0x9 follow them in the Data Segment,
@ a loop copies the numbers after them, and the system prints the total, 23, in Run I/O.
@ PUSH, POP and STM make one pass through the datapath for each register; MUL and MLA use the
@ multiplier inside the ALU; a shift by a register reads its amount on A4, and ADC takes the C
@ flag on CarryIn. MOVW and MOVT build -100 in two halves; STRH stores a halfword of it, and
@ LDRSB and LDRH read it back, widened by the data memory's load extender.

        .data
numbers: .word  3, 9, 4, 7
total:  .word   0
largest: .word  0
copy:   .space  16
        .space  32
stack:  .word   0

        .global _start
        .text
_start: LDR     SP, =stack      @ the stack, for PUSH and POP
        LDR     R0, =numbers    @ a load: the address of the numbers
        MOV     R1, #4          @ an immediate operand: how many numbers
        BL      add_up          @ BL: LR takes the address of the next instruction
        LDR     R4, =total
        STMIA   R4, {R2, R3}    @ STM: a pass for each register, the total and the largest
        BL      twice
        MUL     R9, R2, R3      @ MUL: the multiplier in the ALU, the total times the largest
        MLA     R10, R2, R3, R5 @ MLA adds a third register, read on A4: R9 + twice the total
        MOV     R11, R2, LSL R1 @ a shift by a register: R1, read on A4, gives the amount: 23 x 16
        CMP     R11, R10        @ C = 1: 368 is not below 253
        ADC     R12, R9, #0     @ ADC adds the C flag, which CarryIn brings to the ALU: R9 + 1
        LDR     R0, =numbers
        LDR     R8, =copy
        MOV     R6, #4
copy_next:
        LDR     R7, [R0], #4    @ post-indexing: the address is R0, then R0 moves on by 4
        STR     R7, [R8], #4    @ the store's base moves on the same way
        SUBS    R6, R6, #1
        BNE     copy_next
        MOVW    R6, #0xFF9C     @ MOVW: a 16-bit immediate, with zeros above: 0x0000FF9C
        MOVT    R6, #0xFFFF     @ MOVT: the high half; the low half stays: R6 = -100
        STRH    R6, [R8]        @ STRH: its low half, 0xFF9C, after the copy
        LDRSB   R7, [R8]        @ LDRSB: the byte 0x9C, its sign copied into bits 31:8: -100
        LDRH    R4, [R8]        @ LDRH: the halfword with zeros above: 0xFF9C = 65436
        MOV     R0, R2
        SVC     #1              @ a system call: the system prints R0
stop:   B       stop            @ a branch to itself ends the program

@ add_up: R0 = the numbers, R1 = how many. R2 = their total, R3 = the largest.
add_up: PUSH    {R4, R6, R7, LR}        @ PUSH: from the highest register, SP moves down
        MOV     R2, #0
        MOV     R3, #0
        MOV     R6, #0          @ R6 = which number
next:   LDR     R7, [R0, R6, LSL #2]    @ a load with a register offset
        ADD     R2, R2, R7      @ a register operand
        CMP     R7, R3          @ CMP writes only the flags
        MOVGT   R3, R7          @ runs only when R7 is the larger: watch PCPlus4 when it does not
        ADD     R6, R6, #1
        CMP     R6, R1
        BLT     next            @ a conditional branch
        POP     {R4, R6, R7, PC}        @ POP: its last pass loads the PC, the return

@ twice: R5 = twice the total.
twice:  MOV     R5, R2, LSL #1  @ the shifter: twice the total
        BX      LR              @ the return: LR goes through the ALU to the PC
