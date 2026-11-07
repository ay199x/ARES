@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ Reads two integers typed by the user and prints their sum.

        .global _start
        .text
_start:
        SVC     #5              @ read integer
        MOV     R4, R0
        SVC     #5
        ADD     R0, R0, R4
        SVC     #1
        MOV     R0, #'\n'
        SVC     #11
        SVC     #10
