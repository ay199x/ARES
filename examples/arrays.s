@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ Arrays in memory: walks an array of words to find its sum and its largest element.

        .data
numbers: .word  12, 7, 31, -4, 25, 18
        .equ    COUNT, 6
sum:    .asciz  "Sum: "
largest: .asciz "Largest: "
newline: .asciz "\n"

        .global _start
        .text
_start: LDR     R4, =numbers    @ R4: the array's address
        MOV     R5, #0          @ R5: the index of the element
        MOV     R6, #0          @ R6: the sum
        LDR     R7, [R4]        @ R7: the largest so far, at first the first element

next:   LDR     R0, [R4, R5, LSL #2]    @ element R5 is 4 x R5 bytes from the start
        ADD     R6, R6, R0
        CMP     R0, R7
        MOVGT   R7, R0          @ a larger one (signed): keep it
        ADD     R5, R5, #1
        CMP     R5, #COUNT
        BLT     next

        LDR     R0, =sum
        SVC     #4              @ print string
        MOV     R0, R6
        SVC     #1              @ print integer
        LDR     R0, =newline
        SVC     #4
        LDR     R0, =largest
        SVC     #4
        MOV     R0, R7
        SVC     #1
        LDR     R0, =newline
        SVC     #4
        SVC     #10             @ exit
