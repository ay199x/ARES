@ SPDX-License-Identifier: GPL-2.0-or-later
@ Copyright (c) 2026 The ARES Project
@
@ For the Bitmap Display: draws a picture.
@ Open Tools > Bitmap Display, leave its settings as they are (512 x 256 pixels in units of
@ 1 x 1, base address .data), click Connect to ARM, then run the program.

        .data
screen: .space  524288          @ 512 x 256 words, one for each pixel

        .global _start
        .text
_start: LDR     R4, =screen     @ R4: the next word of the picture
        MOV     R1, #0          @ R1: the row
row:    MOV     R0, #0          @ R0: the column
column: LSR     R2, R0, #1      @ red grows from 0 to 255 from left to right
        LSL     R2, R2, #16
        ORR     R2, R2, R1, LSL #8      @ green grows from 0 to 255 from top to bottom
        CMP     R0, R1, LSL #1  @ on the diagonal, where column = 2 x row ...
        LDREQ   R2, =0x00FFFFFF @ ... the pixel is white
        STR     R2, [R4], #4
        ADD     R0, R0, #1
        CMP     R0, #512
        BNE     column
        ADD     R1, R1, #1
        CMP     R1, #256
        BNE     row
        SVC     #10             @ exit
