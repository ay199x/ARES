@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ The JTAG UART: prints text through the DE1-SoC's serial port, with no system call. Such a
@ program also runs on CPUlator's DE1-SoC system.

        .data
text:   .asciz  "Hello from the JTAG UART\n"

        .global _start
        .text
_start: LDR     R0, =0xFF201000 @ the data register; the control register is 4 bytes on
        LDR     R1, =text
next:   LDRB    R2, [R1], #1    @ the next character, and R1 moves on
        CMP     R2, #0
        BEQ     done
wait:   LDR     R3, [R0, #4]    @ bits 31-16 of the control register: the room for output
        LSRS    R3, R3, #16
        BEQ     wait            @ no room: ask again
        STR     R2, [R0]        @ write the character
        B       next
done:   B       .               @ a branch to itself: the end
