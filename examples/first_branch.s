@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ A first walkthrough: a comparison and a conditional branch, one step at a time.
@ Predict first: is 7 greater than or equal to 12, so will BGE branch? Press F3 to assemble,
@ then F7 to step. After CMP, look at N, Z, C and V in CPSR; after BGE, see which line runs
@ next; press F8 (Backstep) to go back and look at the flags again. Then open Tools > ARM X-Ray,
@ click Connect to ARM and step through CMP and BGE once more.

        .data
larger: .asciz  "The larger number is "
newline: .asciz "\n"

        .global _start
        .text
_start: MOV     R1, #7          @ R1 = 7
        MOV     R2, #12         @ R2 = 12
        CMP     R1, R2          @ R1 - R2 sets N, Z, C and V; the difference is not kept
        BGE     first           @ taken when R1 >= R2, signed: when N equals V
        MOV     R3, R2          @ not taken: R2 is the larger
        B       show
first:  MOV     R3, R1          @ taken: R1 is the larger
show:   LDR     R0, =larger
        SVC     #4              @ print string
        MOV     R0, R3
        SVC     #1              @ print integer
        LDR     R0, =newline
        SVC     #4
        SVC     #10             @ exit
