@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ DE1-SoC style output through the JTAG UART, without system calls.

        .global _start
        .text
_start:
        LDR     SP, =0x3FFFFFF8
        MOV     R0, #'O'
        BL      print_char
        MOV     R0, #'K'
        BL      print_char
        MOV     R0, #'\n'
        BL      print_char
        B       .

print_char:
        PUSH    {R1, LR}
        LDR     R1, =0xFF201000 @ JTAG UART data register
        STRB    R0, [R1]
        POP     {R1, PC}
