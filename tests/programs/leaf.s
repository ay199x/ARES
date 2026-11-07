@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ Calls a leaf function twice. print_value calls no other function, so it
@ returns with BX LR without saving LR: the system calls keep LR.

        .global _start
        .text
_start:
        MOV     R0, #7
        BL      print_value
        MOV     R0, #35
        BL      print_value
        SVC     #10

@ Prints R0 and a newline.
print_value:
        SVC     #1
        MOV     R0, #'\n'
        SVC     #11
        BX      LR
