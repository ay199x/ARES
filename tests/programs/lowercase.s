@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ An instruction in lowercase: the capital-letters check stops the assembly.

        .global _start
        .text
_start:
        add r0, r1, #1
        MOV     R0, #0
        SVC     #10             @ exit
