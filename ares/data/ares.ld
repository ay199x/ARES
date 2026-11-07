/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright (c) 2026 The ARES Project */

/* Program layout in DDR3 memory: .text from address 0, then .rodata,
   .data and .bss, each word-aligned and directly after the previous one. */

OUTPUT_FORMAT("elf32-littlearm")
OUTPUT_ARCH(arm)
ENTRY(_start)

PHDRS
{
    code PT_LOAD FLAGS(5);      /* read, execute */
    data PT_LOAD FLAGS(6);      /* read, write */
}

SECTIONS
{
    . = 0x00000000;
    .text : { *(.text .text.*) } :code
    .rodata ALIGN(4) : { *(.rodata .rodata.*) } :code
    .data ALIGN(4) : { *(.data .data.*) } :data
    .bss ALIGN(4) : { *(.bss .bss.* COMMON) } :data
}
