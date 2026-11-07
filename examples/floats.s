@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ Floating point: a circle's area in single precision, and 1 / 3 in double precision.
@ Constants live in .data and are loaded through their address.

        .data
pi_single: .float 3.14159274
radius: .float  2.5
        .balign 8
one:    .double 1.0
three:  .double 3.0
area:   .asciz  "Area: "
third:  .asciz  "One third: "
newline: .asciz "\n"

        .global _start
        .text
_start: LDR     R1, =pi_single
        VLDR    S1, [R1]
        LDR     R1, =radius
        VLDR    S2, [R1]
        VMUL.F32 S0, S2, S2     @ radius x radius
        VMUL.F32 S0, S0, S1     @ S0 = pi x radius x radius

        LDR     R0, =area
        SVC     #4              @ print string
        SVC     #2              @ print float: S0
        LDR     R0, =newline
        SVC     #4

        LDR     R1, =one
        VLDR    D1, [R1]
        LDR     R1, =three
        VLDR    D2, [R1]
        VDIV.F64 D0, D1, D2     @ D0 shares its storage with S0 and S1

        LDR     R0, =third
        SVC     #4
        SVC     #3              @ print double: D0
        LDR     R0, =newline
        SVC     #4
        SVC     #10             @ exit
