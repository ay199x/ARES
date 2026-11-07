@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ Strings and input: reads a word and a number, then prints the word that many times.

        .data
ask_word: .asciz "A word: "
ask_times: .asciz "How many times? "
length: .asciz  "Letters: "
newline: .asciz "\n"
word:   .space  32              @ the buffer for the line typed

        .global _start
        .text
_start: LDR     R0, =ask_word
        SVC     #4              @ print string
        LDR     R0, =word
        MOV     R1, #32
        SVC     #8              @ read string: at most 31 characters, then a zero byte

        @ Find the end of the line, and put a zero byte in place of its line feed.
        LDR     R4, =word
        MOV     R5, #0          @ R5: the letters so far
count:  LDRB    R0, [R4, R5]
        CMP     R0, #0
        BEQ     counted
        CMP     R0, #10         @ the line feed
        BEQ     cut
        ADD     R5, R5, #1
        B       count
cut:    MOV     R0, #0
        STRB    R0, [R4, R5]

counted:
        LDR     R0, =length
        SVC     #4
        MOV     R0, R5
        SVC     #1              @ print integer
        LDR     R0, =newline
        SVC     #4

        LDR     R0, =ask_times
        SVC     #4
        SVC     #5              @ read integer: into R0
        MOV     R6, R0          @ R6: counts down to 0
again:  CMP     R6, #0
        BLE     done
        MOV     R0, R4
        SVC     #4              @ print the word
        MOV     R0, #' '
        SVC     #11             @ print character
        SUB     R6, R6, #1
        B       again

done:   LDR     R0, =newline
        SVC     #4
        SVC     #10             @ exit
