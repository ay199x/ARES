@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ For the BHT Simulator: three kinds of conditional branches.
@ Open the tool, click Connect to ARM and run. The inner loop's branch is nearly always taken, the
@ outer one's mostly, and the branch on odd numbers changes every time: compare 1 and 2 history
@ bits on it.

        .data
odd:    .asciz  "Odd numbers: "
newline: .asciz "\n"

        .global _start
        .text
_start: MOV     R4, #0          @ R4: the odd numbers seen
        MOV     R1, #8          @ R1: the outer loop's count
outer:  MOV     R2, #16         @ R2: the inner loop's count
inner:  TST     R2, #1
        BEQ     even            @ taken every second time
        ADD     R4, R4, #1
even:   SUBS    R2, R2, #1
        BNE     inner           @ the inner loop
        SUBS    R1, R1, #1
        BNE     outer           @ the outer loop

        LDR     R0, =odd
        SVC     #4              @ print string
        MOV     R0, R4
        SVC     #1              @ print integer
        LDR     R0, =newline
        SVC     #4
        SVC     #10             @ exit
