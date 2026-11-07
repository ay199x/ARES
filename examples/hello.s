@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ The first program: prints a line of text with a system call.

        .data
hello:  .asciz  "Hello, world!\n"

        .global _start
        .text
_start: LDR     R0, =hello      @ R0 = the address of the text
        SVC     #4              @ print string
        SVC     #10             @ exit
