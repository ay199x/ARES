@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ For the Data Cache Simulator: walks a table of 16 x 16 words by rows, then by columns.
@ Open the tool, leave its organization as it is, click Connect to ARM, set a breakpoint on the
@ line at columns, and run: the walk by rows finds 3 of 4 words in the cache, as its neighbours
@ came in with the same block. Press Go again: the walk by columns finds almost none.

        .data
table:  .space  1024            @ 16 rows of 16 words
total:  .asciz  "Total: "
newline: .asciz "\n"

        .global _start
        .text
_start: LDR     R4, =table      @ rows: fill the table, word after word
        MOV     R0, #0
fill:   STR     R0, [R4, R0, LSL #2]
        ADD     R0, R0, #1
        CMP     R0, #256
        BNE     fill

columns:
        MOV     R5, #0          @ R5: the column
        MOV     R6, #0          @ R6: the total
column: MOV     R1, #0          @ R1: the row
down:   ADD     R2, R5, R1, LSL #4      @ word number 16 x row + column
        LDR     R0, [R4, R2, LSL #2]
        ADD     R6, R6, R0
        ADD     R1, R1, #1
        CMP     R1, #16
        BNE     down
        ADD     R5, R5, #1
        CMP     R5, #16
        BNE     column

        LDR     R0, =total
        SVC     #4              @ print string
        MOV     R0, R6
        SVC     #1              @ print integer
        LDR     R0, =newline
        SVC     #4
        SVC     #10             @ exit
