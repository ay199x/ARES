@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ Reads the radius of a circle and prints its area, once in single precision
@ (SVC #6 reads S0, SVC #2 prints S0) and once in double precision (SVC #7
@ reads D0, SVC #3 prints D0).

        .data
ask:    .asciz  "Radius: "
area:   .asciz  "Area: "
        .balign 4
pi_single:
        .float  3.14159265
        .balign 8
pi_double:
        .double 3.141592653589793

        .global _start
        .text
_start:
        LDR     R0, =ask
        SVC     #4              @ print string
        SVC     #6              @ read float into S0
        VMUL.F32 S0, S0, S0     @ r * r
        LDR     R1, =pi_single
        VLDR    S1, [R1]
        VMUL.F32 S0, S0, S1     @ pi * r * r
        LDR     R0, =area
        SVC     #4
        SVC     #2              @ print float S0
        MOV     R0, #'\n'
        SVC     #11

        LDR     R0, =ask
        SVC     #4
        SVC     #7              @ read double into D0
        VMUL.F64 D0, D0, D0
        LDR     R1, =pi_double
        VLDR    D1, [R1]
        VMUL.F64 D0, D0, D1
        LDR     R0, =area
        SVC     #4
        SVC     #3              @ print double D0
        MOV     R0, #'\n'
        SVC     #11
        SVC     #10
