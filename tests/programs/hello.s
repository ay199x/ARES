@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ Prints a greeting and a number with system calls.

        .global _start
        .text
_start:
        LDR     R0, =greeting
        SVC     #4              @ print string
        MOV     R0, #42
        SVC     #1              @ print integer
        MOV     R0, #'\n'
        SVC     #11             @ print character
        SVC     #10             @ exit

        .data
greeting:
        .asciz  "Hello from ARMv7! The answer is "
