@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ Arithmetic and loops: adds 1 to 10, then multiplies 1 to 5.

        .data
sum:    .asciz  "1 + 2 + ... + 10 = "
product: .asciz "5 factorial = "
newline: .asciz "\n"

        .global _start
        .text
_start: MOV     R1, #0          @ R1: the sum so far
        MOV     R2, #1          @ R2: the number to add
add:    ADD     R1, R1, R2
        ADD     R2, R2, #1
        CMP     R2, #10
        BLE     add             @ go on while R2 <= 10

        LDR     R0, =sum
        SVC     #4              @ print string
        MOV     R0, R1
        SVC     #1              @ print integer
        LDR     R0, =newline
        SVC     #4

        MOV     R1, #1          @ R1: the product so far
        MOV     R2, #5          @ R2: counts down to 1
multiply:
        MUL     R1, R1, R2
        SUBS    R2, R2, #1      @ S: set the flags, Z when R2 reaches 0
        BNE     multiply

        LDR     R0, =product
        SVC     #4
        MOV     R0, R1
        SVC     #1
        LDR     R0, =newline
        SVC     #4
        SVC     #10             @ exit
