@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ A tour of the five-stage pipeline. Open Tools > Pipeline Simulator, click Connect to ARM,
@ then step through the program (F7) or run it (F5) and watch the reservation table. Then try
@ other settings with Settings... and see what each one does to the cycles and the CPI.

        .data
value:  .word   5

        .global _start
        .text
@ Two equal values: BNE is not taken, BEQ is taken over three lines, which a pipeline that
@ guesses wrong fetches and throws away (Flush).
_start: MOV     R0, #20
        MOV     R1, #20
        CMP     R0, R1          @ R0 equals R1: Z = 1
        BNE     next            @ not taken
        MOV     R2, #30
        MOV     R3, #30
        MOV     R4, #30
        CMP     R3, R4
        BEQ     end             @ taken: the next three lines do not run
next:   MOV     R5, #8
        MOV     R6, #8
        MOV     R7, #8
end:    MOV     R8, #8

@ A load, then its use: even with forwarding, ADD waits one cycle for the value LDR loads.
        LDR     R9, =value
        LDR     R10, [R9]       @ R10 = 5
        ADD     R10, R10, R8    @ uses R10 at once: R10 = 13

@ A short loop: BNE is taken twice, then not taken.
        MOV     R11, #3
loop:   ADD     R10, R10, #1
        SUBS    R11, R11, #1
        BNE     loop

        MOV     R0, R10         @ 16
        SVC     #1              @ print integer
        MOV     R0, #'\n'
        SVC     #11             @ print character
        SVC     #10             @ exit
