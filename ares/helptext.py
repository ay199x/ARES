# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The text of the Help window, without a window.

A page is plain text with a little markup, turned into blocks by parse():

- ``# Title`` is a line of the title of the page, in the middle;
- ``## Title`` is a heading of the page;
- a line starting with four spaces belongs to a program example;
- ``- text`` is a bullet, its next lines are indented by two spaces;
- ``| cell | cell |`` is a row of a table, the first row being its heading;
- anything else is a paragraph, up to the next empty line.

In a paragraph, a bullet or a table cell, ``text`` in backquotes is shown in the font of
programs. The system calls, the keyboard shortcuts and the condition codes are made from the tables
the program itself uses, and the tools' pages from their own help texts, so they cannot differ from
what ARES does. The instruction lists are in ares.instructions.
"""

import re
import textwrap
from dataclasses import dataclass

from . import APP_FULL_NAME, APP_NAME, __version__, credits, instructions
from .syscalls import SERVICES

TITLE, HEADING, PARAGRAPH, BULLET, CODE, TABLE = ("title", "heading", "paragraph", "bullet", "code",
                                                  "table")
DOCUMENT = "document"           # a text file as it is, made by license_blocks()
TABLE_WIDTH = 92                # the widest a table may be, in characters of the code font
COLUMN_GAP = 2                  # between two columns of a table


@dataclass(frozen=True)
class Block:
    kind: str
    text: str = ""              # the words; the lines of an example
    rows: tuple = ()            # of a table: the rows, each a tuple of its cells


def parse(page):
    """The blocks of a page."""
    blocks = []
    lines = page.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif line.startswith("# "):
            blocks.append(Block(TITLE, line[2:].strip()))
            i += 1
        elif line.startswith("## "):
            blocks.append(Block(HEADING, line[3:].strip()))
            i += 1
        elif line.startswith("    "):
            start = i
            while i < len(lines) and (lines[i].startswith("    ") or not lines[i].strip()):
                i += 1
            code = [text[4:] for text in lines[start:i]]
            while not code[-1].strip():
                code.pop()
            blocks.append(Block(CODE, "\n".join(code)))
        elif line.startswith("| "):
            rows = []
            while i < len(lines) and lines[i].startswith("| "):
                rows.append(tuple(cell.strip() for cell in lines[i].strip().strip("|").split(" | ")))
                i += 1
            blocks.append(Block(TABLE, rows=tuple(rows)))
        elif line.startswith("- "):
            words = [line[2:].strip()]
            i += 1
            while i < len(lines) and lines[i].startswith("  ") and lines[i].strip():
                words.append(lines[i].strip())
                i += 1
            blocks.append(Block(BULLET, " ".join(words)))
        else:
            words = []
            while (i < len(lines) and lines[i].strip()
                   and not lines[i].startswith(("# ", "## ", "- ", "| ", "    "))):
                words.append(lines[i].strip())
                i += 1
            blocks.append(Block(PARAGRAPH, " ".join(words)))
    return blocks


def plain(text):
    """Text without the backquotes around its parts in the font of programs."""
    return text.replace("`", "")


def spans(text):
    """The parts of a text: (part, True when it is in the font of programs)."""
    return [(part, i % 2 == 1) for i, part in enumerate(text.split("`")) if part]


def column_widths(rows, limit=TABLE_WIDTH, gap=COLUMN_GAP):
    """The width of each column of a table, in characters, so that it fits in limit.

    A column keeps the room of its widest cell while that fits; else the widest columns give
    up room, not below their longest word.
    """
    count = len(rows[0])
    widths = [max(len(plain(row[i])) for row in rows) for i in range(count)]
    least = [max(len(word) for row in rows for word in plain(row[i]).split() or [""])
             for i in range(count)]
    room = limit - gap * (count - 1)
    while sum(widths) > room:
        candidates = [i for i in range(count) if widths[i] > least[i]]
        if not candidates:
            break
        widths[max(candidates, key=lambda i: widths[i])] -= 1
    return widths


def table_lines(rows, limit=TABLE_WIDTH, gap=COLUMN_GAP):
    """A table as text: [(lines of a row)], each cell wrapped in its column."""
    widths = column_widths(rows, limit, gap)
    table = []
    for row in rows:
        cells = [textwrap.wrap(plain(cell), width, break_long_words=False) or [""]
                 for cell, width in zip(row, widths)]
        height = max(len(cell) for cell in cells)
        lines = []
        for i in range(height):
            parts = [(cell[i] if i < len(cell) else "").ljust(width)
                     for cell, width in zip(cells, widths)]
            lines.append((" " * gap).join(parts).rstrip())
        table.append(lines)
    return table


def tool_page(text):
    """A tool's help text as a page: a short line alone, without a full stop, is a heading."""
    blocks = []
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        lines = paragraph.split("\n")
        words = " ".join(line.strip() for line in lines)
        if len(lines) == 1 and len(words) <= 60 and not words.endswith((".", ":", ",", ";")):
            blocks.append(Block(HEADING, words))
        else:
            blocks.append(Block(PARAGRAPH, words))
    return blocks


def system_calls_page():
    """The System calls page, its table made from the services of ares.syscalls."""
    rows = ["| N | Service | Arguments | Result |"]
    for number in sorted(SERVICES):
        service = SERVICES[number]
        rows.append(f"| {number} | {service.name} | {service.arguments or '-'} | "
                    f"{service.result or '-'} |")
    return SYSTEM_CALLS.replace("{table}", "\n".join(rows))


def shortcut_rows(menus, label_of):
    """The table rows of a menu table's shortcuts: "| key | command |"."""
    rows = []
    for title, entries in menus:
        for entry in entries or ():
            if entry is not None and entry[2]:
                rows.append(f"| {entry[2]} | {label_of(title)} > {label_of(entry[1])} |")
    return rows


def keyboard_page(menus, label_of):
    """The Keyboard shortcuts page, its first table made from the window's menu table."""
    rows = ["| Key | Command |"] + shortcut_rows(menus, label_of)
    return KEYBOARD.replace("{table}", "\n".join(rows))


def intro_page():
    """The Intro page: who made ARES and why, then how to start."""
    first = [f"# {APP_NAME} - {APP_FULL_NAME}", f"# Version {__version__}", *credits.MOTIVATION,
             credits.FUN_FACT, "## Credits", credits.credits_markup()]
    return "\n\n".join(first) + "\n\n" + INTRO


def limits_page():
    """The Limits page, ending with the mnemonics that are on neither instruction list."""
    lines = [LEFT_OUT]
    for names, why in instructions.LEFT_OUT:
        lines.append(f"- {why} {', '.join(names)}.")
    lines.append(LEFT_OUT_FORMS)
    for form, why in instructions.FORMS_LEFT_OUT:
        lines.append(f"- {form}: {why}.")
    return LIMITS + "\n" + "\n".join(lines) + "\n"


def acknowledgements_page():
    """The Acknowledgements page: the credits, then the programs and work ARES stands on."""
    return ("## Credits\n\n" + credits.credits_markup() + "\n\n" + ACKNOWLEDGEMENTS
            + "\n" + credits.TEXTBOOK + "\n")


def license_blocks(licence, notices, others=()):
    """The License page, with the texts of LICENSE and THIRD_PARTY_NOTICES.txt, then others: each
    a (heading, text) of a licence that comes with a packaged ARES."""
    blocks = parse(LICENSE_WORDS) + [
        Block(HEADING, "The licence"), Block(DOCUMENT, licence),
        Block(HEADING, "Third-party notices"), Block(DOCUMENT, notices)]
    for heading, text in others:
        blocks += [Block(HEADING, heading), Block(DOCUMENT, text)]
    return blocks


INTRO = f"""\
## What ARES is

{APP_NAME}, the {APP_FULL_NAME}, runs programs in ARMv7 assembly language on a simulated DE1-SoC
computer. It supports the ARMv7 instruction set, with the same assembler and options as CPUlator's
ARMv7 DE1-SoC system, so programs written for CPUlator assemble here too, once they are in capitals
(see the IDE tab). ARES simulates no interrupts or timers.

## A first program

Choose File > New and type this program. In ARES a program starts with its data, then `.global
_start` and `.text`, and instructions and registers are written in capitals.

            .data
    hello:  .asciz  "Hello, world!\\n"

            .global _start
            .text
    _start: LDR     R0, =hello      @ R0 = the address of the text
            SVC     #4              @ print the string
            SVC     #10             @ end the program

## Assemble and run

- Save the file with File > Save (Ctrl+S).
- Press F3 (Run > Assemble). Errors appear in ARES Messages, each with its file and line: click
  one to go to the line. Without errors ARES shows the Execute tab.
- Press F5 (Go). The text appears in Run I/O, followed by `-- program is finished running --`.
- Press F12 (Reset) to start again.

## Where to read on

The ARM tab of the Help window is about the language: every instruction, the directives, the
system calls, the registers and the memory. Its ARES tab is about the program: IDE for the window,
Debugging for going through a program, Settings, Tools, Keyboard shortcuts, and Limits for what
ARES does not do.

## Example programs

File > Open Example lists the short programs that come with ARES, among them one for most of the
tools. Choosing one opens a copy as a new file that is not saved yet: run it, change it, and save
it where you like. The example itself stays as it is.
"""

IDE = """\
## The window

- Edit: your files, one tab each. Keywords are coloured as you type.
- Execute: the Text Segment (each instruction with its address, code and source line), the Data
  Segment (memory, eight words a row) and, with Settings > Show Labels Window, the Labels.
- Registers, Coproc 10 and Coproc 11: the registers (see the Registers tab under ARM).
- ARES Messages: what the assembler and the commands report.
- Run I/O: what the program prints, and where it reads what you type.

The title bar shows the file on top, with `*` after its name while it has changes that are not
saved, and the version: `hello.s* - ARES 1.0`. The dividers between the parts can be dragged and the
window resized, for as long as ARES runs: every start opens maximized, with the default layout. A
scroll bar shows only while what it scrolls does not
fit; the editor always has both. The toolbar holds the commands used most, in the order of the
menus: New, Open, Save, Save As, Undo, Redo, Cut, Copy, Paste, Find/Replace, Assemble, Go, Step,
Backstep, Pause, Stop, Reset and Help. Rest the mouse on a button to read what it does. A gray
button or menu item is not available at the moment. At the right of the toolbar the Run speed
slider sets how fast Go runs (see the Debugging tab).

## The editor

- File > New opens a new file, File > Open an existing one, and each has a tab with a close button.
  File > Open Example opens a copy of one of the programs that come with ARES, as a new file with
  the example's name that is not saved yet; File > Save then asks where to save it.
  ARES asks before it closes a file with changes that are not saved, also at File > Exit.
- Under the text the status line shows `Line: x  Column: y`, and Show Line Numbers turns the numbers
  at the left on and off.
- Edit has Undo, Redo, Cut, Copy, Paste and Select All. Edit > Find/Replace finds and replaces
  text, with Match case and Whole word, one at a time or all at once. There, Return presses the
  button that has the focus, else Find.
- A new line starts as far in as the line above it. The Tab key inserts spaces, or a tab with
  Settings > Editor Font.
- The colours are CPUlator's: registers blue, numbers green, labels being defined dark green and
  bold, directives teal, comments brown and strings dark red.

## Assembling

Run > Assemble (F3) assembles the file on top with the GNU assembler. ARES Messages shows what
happens, and each error or warning as `Error in hello.s line 7: ...`, with a red mark at the left
of the line until the next Assemble. A click on the message selects the line in the editor.

A program with no `_start` is a warning, not an error: it starts at address 0x00000000.

After an Assemble without errors ARES shows the Execute tab. Opening a file or going to another
file's tab changes nothing there: only Assemble loads a program. Closing the file of the assembled
program unloads it, and ARES goes back to the state it has at the start, keeping the text of ARES
Messages and Run I/O.

File > Dump Memory saves the program's code or data to a file, as binary or as hexadecimal text.

## Input

When the program reads input (for example with `SVC #5`), Run I/O comes to the front with a blinking
text cursor: type the line and press Enter. At other times ARES Messages and Run I/O show no text
cursor; their text can still be selected with the mouse and copied with Ctrl+C. With Settings >
Popup Dialog for Input on, a small dialog asks for the line instead.

## Capital letters

With Settings > Require Capital Letters on, as it is at first, ARES refuses a program whose
instructions or registers are not in capitals, and shows each line corrected. Directives are in
lowercase. Edit > Capitalize Instructions corrects the whole file. Comments and strings are not
checked, and labels can be spelled in any way, as long as it is always the same.
"""

DEBUGGING = """\
## Going through a program

- F7 (Step) runs one instruction. The next instruction is highlighted in the Text Segment, and
  the registers and memory it changed are highlighted too.
- F8 (Backstep) undoes the last step, up to 2,000 steps back. A run at full speed keeps no history
  unless Settings > Enable Backstep While Running is on.
- A tick in the Bkpt column of the Text Segment sets a breakpoint: Go stops before that
  instruction. Ctrl+K clears all the breakpoints, Ctrl+T turns them off and on.
- The Run speed slider runs 1 to 30 instructions a second, showing each one. At its right end the
  program runs at full speed.
- F9 (Pause) and F11 (Stop) halt a running program.
- F12 (Reset) loads the program again, with the registers and memory as at its start.

## What the colours say

| Colour | In | What it says |
| light yellow | Text Segment | the next instruction |
| light red | Text Segment | the instruction that ended the program with a runtime error |
| light blue | Data Segment | a word the last step or run changed |
| lime green | the register tabs | a register the last step changed |

## Looking at memory

The Data Segment shows 128 words at a time. Its Previous and Next buttons go to the page before
and after; Hexadecimal Addresses, Hexadecimal Values and ASCII change how it shows them.

Below the Data Segment, a list jumps to a place: `.data` (the start of the program's data),
current SP (the page of the stack pointer), `.text` (the program's code) and JTAG UART. While no
program is assembled the Data Segment is empty and the list is gray, reading ".data: no program
assembled". While SP has its start value 0, the current SP entry reads "current SP: stack at
0xfffffffc" and shows the last page of the on-chip memory, where the first PUSH stores.

With Settings > Show Labels Window on, a double-click on a label shows its address in the Text
Segment or the Data Segment. While no program is running, the values of the registers can be
changed by hand: the Registers tab under ARM tells how.

## How a program ends

- `SVC #10` or `SVC #17`, and a branch to itself (`B .`), end it with `-- program is finished
  running --`.
- Running past the last instruction ends it with `-- program is finished running (dropped off
  bottom) --`.
- An error, such as an access to an address with no memory, stops it with a runtime error in ARES
  Messages and Run I/O, and the instruction turns light red. The registers and memory stay as they
  were, to see what happened; Reset starts the program again. Backstep still works, to see what
  led to the error, as far as it has history.
"""

SETTINGS = """\
The Settings menu keeps its choices from one time to the next, for each user of the computer. They
are kept in the file `settings.json` in the folder `ARES` of the user's application data, with the
last folder used. The window's size and dividers are not kept.

| Setting | At first | What it does |
| Show Labels Window | off | shows the Labels beside the Text Segment and the Data Segment |
| Assemble File Upon Opening | off | assembles a file as soon as it is opened |
| Addresses in Hexadecimal | on | shows addresses in hexadecimal, else in decimal |
| Values in Hexadecimal | on | shows the values of registers and memory in hexadecimal, else in decimal |
| Require Capital Letters | on | refuses a program whose instructions or registers are not in capitals |
| Popup Dialog for Input | off | asks for typed input in a small dialog, not in Run I/O |
| Enable Backstep While Running | off | keeps the history of a run at full speed, which makes it slower |

Editor Font opens a dialog with the font and the size of the editor, the Tab width, and Tab key
inserts spaces, which is on at first. Show Line Numbers, under the editor, is kept too.

Restore Defaults puts all of this back as it was at first, except the last folder used.
"""

LIMITS = """\
ARES is made for learning, and simulates what a program needs to run. This is what it does not do.

## The computer

- ARES is made for ARM state. Thumb code is not supported: it can run for a while, but `SVC` does
  not work in it, and `BLX label` to Thumb code at the end of the program leaves the program.
- There are no interrupts and no timers. Nothing is ever taken as an exception: `SVC` goes to ARES's
  own services, and an undefined instruction or an access to an address with no memory ends the
  program with a runtime error, with no exception vector and no handler.
- There is no memory management unit and no cache: the Data Cache Simulator is a model that counts.
- ARES counts instructions, not time: there are no cycles.
- The Cortex-A9 has no divide instruction: use a loop, or floating point.
- Only these coprocessor instructions work: those of the floating-point unit, coprocessors 10 and
  11, and `MRC` and `MCR` on a register of 14, the debug unit, or 15, the system's, that can be read
  or written that way. Any other, such as `CDP` or `MRRC` on 14 or 15, is an undefined instruction:
  unless its condition fails, it ends the program with a runtime error.
- The only device without a tool is the JTAG UART. The other DE1-SoC devices ignore writes and read
  as 0, and ARES Messages warns once for each address that a program uses; the Digital Lab Sim
  brings the red LEDs, the seven-segment displays, the switches and the push buttons to life.
- Memory is what the Memory and devices tab lists: 1 GB of DDR3 and 64 KB of on-chip memory.

## The program and the window

- A program is one file: Assemble takes the file on top and links nothing else with it.
- Backstep goes back at most 2,000 steps.
- System calls 31 and 33 play no sound.
- The numbers of the system calls are those of the Syscalls tab; any other number ends the program
  with a runtime error.

## The tools

- A connected tool can make a run at full speed take longer, as its page says.
- BHT Simulator: only conditional branches are predicted, not B without a condition, BL, BX or
  other instructions that change PC.
- Digital Lab Sim: the program cannot write the switches, and the interrupt mask is only stored.
- Dynamic Instruction Counter: it counts instructions and has no cycles.
- Keyboard and Display MMIO Simulator: text printed by system calls shows only in Run I/O.
- Memory Reference Visualization: memory that a system call reads or writes for the program does
  not count."""

LEFT_OUT = """\
## Instructions on neither list

Every instruction ARES accepts has a row on the Basic or the Extended list, except these:

"""

LEFT_OUT_FORMS = """\

## Forms the lists do not show

"""

DIRECTIVES = """\
Directives tell the assembler what to do; they are written in lowercase. A program has its data
first, then its code:

            .data
    count:  .word   10
    name:   .asciz  "ARES"

            .global _start
            .text
    _start: LDR     R1, =count
            LDR     R0, [R1]
            SVC     #1              @ print 10
            SVC     #10

A line can start with a label, a name followed by a colon, which stands for the address of what
comes next. A comment runs from `@` or `//` to the end of the line.

## Sections and names

| Directive | What it does | Example |
| .data | what follows is data | `.data` |
| .text | what follows is code | `.text` |
| .global | make a label known outside the file; the program starts at `_start` | `.global _start` |
| .equ | give a value a name | `.equ SIZE, 16` |

## Data

| Directive | What it does | Example |
| .word | words of 4 bytes | `.word 1, 2, 3` |
| .hword | halfwords of 2 bytes | `.hword 500` |
| .byte | bytes | `.byte 65, 66` |
| .float | single-precision numbers | `.float 1.5` |
| .double | double-precision numbers | `.double 2.5` |
| .ascii | the bytes of a text, with nothing after it | `.ascii "Hi"` |
| .asciz | the bytes of a text, then a zero byte | `.asciz "Hi"` |
| .space | that many bytes of zeros | `.space 64` |

## Placement

| Directive | What it does | Example |
| .balign | go on to an address that is a multiple of a number of bytes | `.balign 4` |
| .align | the same, in powers of two: 2 means 4 bytes | `.align 2` |
| .ltorg | put the waiting `LDR R0, =value` constants here | `.ltorg` |

Words must start at an address that is a multiple of 4. After text or bytes, use `.balign 4`
before the next `.word`, `.float` or `.double`. The assembler places `LDR R0, =value` constants at
the end of the section; `.ltorg` is needed only in a program so long that they would be out of
reach.
"""

SYSTEM_CALLS = """\
A program asks ARES for a service with `SVC #N`, where N is the service's number. Arguments go in
R0 to R3, floating-point ones in S0 or D0, and results come back in the registers listed. Every
other register keeps its value, and so do the flags.

{table}

## Notes

- Output formats: 1 prints a signed number, 36 an unsigned one, 34 `0x` and eight lowercase
  hexadecimal digits, and 35 thirty-two binary digits.
- 8 reads at most R1 - 1 characters, keeps the end of the line if it fits, and ends with a zero
  byte.
- File descriptors 0, 1 and 2 are Run I/O's input, output and error output.
- Status of the input dialogs: 0 OK, -1 not a number, -2 cancelled, -3 OK with no input; 54 gives
  -4 when the text was cut to fit.
- 31 and 33 play no sound: ARES has no synthesizer. 33 still waits for the note's duration.
- An unknown number ends the program with a runtime error.
"""

REGISTERS = """\
## The Registers tab

R0 to R12 are for the program. R13 is SP, the stack pointer, R14 is LR, which holds the return
address of a BL, and R15 is PC, the address of the next instruction. Their values show in
hexadecimal or in decimal, as Settings > Values in Hexadecimal says.

CPSR holds the flags and the processor's mode. After its value the Flags column shows the letters
N, Z, C, V and I and the mode: a letter is black when its bit is 1 and light gray when it is 0.

| Letter | Bit | Meaning |
| N | 31 | negative |
| Z | 30 | zero |
| C | 29 | carry |
| V | 28 | overflow |
| I | 7 | IRQ interrupts disabled; ARES simulates no interrupts |

The mode comes from bits 4-0: USR, FIQ, IRQ, SVC, MON, ABT, HYP, UND or SYS, and ? for any other
value. A program starts in SVC, Supervisor mode, with CPSR at `0x000001d3`. SPSR shows the saved
copy of the current mode the same way; User and System modes have none, and show -.

While no program is running, a double-click on a value, or Enter or F2 on a selected row, opens a
field: type a decimal or 0x hexadecimal number and press Enter, or Escape to leave it. A
double-click on N, Z, C, V or I changes that bit. The mode can only be changed by the program,
with MSR or CPS. Rows changed by the last step are highlighted.

## The Coproc 10 and Coproc 11 tabs

ARM's floating-point unit is coprocessors 10 and 11. Coproc 10 shows the single-precision registers
S0 to S31, and Coproc 11 the double-precision registers D0 to D31. Their values show in
hexadecimal, or as numbers with Settings > Values in Hexadecimal off.

The S and D registers share their storage. For D0 to D15, S(2n) is the low half and S(2n+1) the
high half of Dn:

| D register | Low half | High half |
| D0 | S0 | S1 |
| D1 | S2 | S3 |
| D2 | S4 | S5 |
| ... | ... | ... |
| D15 | S30 | S31 |

So S2 and S3 are the two halves of D1, and a change to one shows in both tabs at once. D16 to D31
have no S registers. Resting the mouse on a row tells which registers share its bits.

## FPSCR

FPSCR, the floating-point status and control register, is the last row of both tabs. Its Flags
column shows N, Z, C and V, which VCMP sets and `VMRS APSR_nzcv, FPSCR` copies to CPSR, then the
rounding mode from bits 23-22, and then the exception flags while they are set:

| Name | Bit | Meaning |
| RN, RP, RM, RZ | 23-22 | round to nearest, towards plus infinity, towards minus infinity, towards zero |
| IOC | 0 | invalid operation |
| DZC | 1 | division by zero |
| OFC | 2 | overflow |
| UFC | 3 | underflow |
| IXC | 4 | inexact result |
| IDC | 7 | input denormal |

The exception flags stay set until the program or a double-click clears them.

## Floating point in a program

.F32 is single precision, in the S registers, and .F64 double precision, in the D registers. Keep
floating-point constants in `.data` and load them through their address:

            .data
    pi_single:
            .float  3.14159274

            .global _start
            .text
    _start: LDR     R1, =pi_single
            VLDR    S0, [R1]
            SVC     #2              @ print the float in S0
            SVC     #10
"""

DEVICES = """\
## The memory map

ARES simulates the memory of the DE1-SoC computer. Tools > Memory Map shows it, with the parts of
the assembled program.

| Addresses | What is there |
| 0x00000000 - 0x3fffffff | DDR3 memory, 1 GB: the program, its data and the heap |
| 0xff200000 - 0xff20ffff | the DE1-SoC devices: writes are ignored and reads give 0, except for the JTAG UART and the devices of a connected tool |
| 0xff201000 - 0xff201007 | the JTAG UART: its data register, then its control register |
| 0xffff0000 - 0xffffffff | on-chip memory, 64 KB: the stack |
| other addresses | no memory: an access stops the program with a runtime error |

The program starts at address 0, and its data follows its code. `SVC #9` takes memory from the heap,
which starts after the program.

## Why SP starts at 0x00000000

As in CPUlator, SP starts at 0x00000000 and the program need not set it. The stack grows downwards,
so the first PUSH subtracts 4 from 0, wraps around, and stores at 0xfffffffc, the top of the
on-chip memory. The next one stores at 0xfffffff8, and so on.

            .global _start
            .text
    _start: MOV     R0, #7
            PUSH    {R0}            @ stores 7 at 0xfffffffc, SP = 0xfffffffc
            POP     {R1}            @ R1 = 7, SP = 0x00000000 again
            SVC     #10

A stack deeper than the 64 KB of on-chip memory stops the program with "memory access out of range
at 0xfffefffc". A program that sets SP itself, for example with `LDR SP, =0x3FFFFFF8`, puts its
stack in DDR3 instead.

"SP now:" under the table of Tools > Memory Map shows SP's value at this moment, and the window can
stay open while the program runs.

## The JTAG UART

The JTAG UART is the DE1-SoC's serial port, which CPUlator programs use for text. In ARES it writes
to and reads from Run I/O.

| Register | Address | Reading | Writing |
| Data | 0xFF201000 | bit 15 (RVALID) is 1 when a character was there, bits 7-0 are the character, bits 31-16 count those still waiting | the low byte goes to Run I/O |
| Control | 0xFF201004 | bits 31-16 give the room for output, always 64 | ignored |

            .data
    text:   .asciz  "Hi\\n"

            .global _start
            .text
    _start: LDR     R0, =0xFF201000 @ the JTAG UART
            LDR     R1, =text
    next:   LDRB    R2, [R1], #1    @ the next character
            CMP     R2, #0
            BEQ     done
            STR     R2, [R0]        @ print it
            B       next
    done:   B       .               @ the end

ARES has no interrupts: a program that reads the JTAG UART reads its data register again and again
until RVALID is 1. The Keyboard and Display MMIO Simulator gives the JTAG UART a display and a
keyboard of its own.

## The board

The red LEDs, the seven-segment displays, the switches and the push buttons of the DE1-SoC come
alive while the Digital Lab Sim is connected; its page in the Tools tab has their addresses.
Without it, ARES Messages warns once for each of their addresses that a program uses.
"""

TOOLS_INTRO = """\
The Tools menu holds tools that show what a program does, each in a window of its own. Choose one
in the list to read about it.

## What every tool has

- Each tool opens centred over the ARES window and does not block it. Several tools can be open at
  once; choosing an open tool again brings its window to the front.
- Connect to ARM: the tool observes the program from now on, also later programs. It can be
  connected before anything is assembled, and stays connected when the program is assembled again
  or its file is closed.
- Disconnect from ARM: the tool stops observing; what it shows stays.
- Reset: the tool's own numbers start again from zero. The program is not touched, except by
  Floating Point Representation, whose Reset also sets its register to 0.0.
- Close: closes the tool and disconnects it. Escape does the same.
- Return or Enter presses the focused button, else Connect to ARM.
- The numbers follow the program after every Step and several times a second while it runs.

A tool that is not connected costs nothing; a connected one can make a run at full speed take
longer, as its page says.
"""

MEMORY_MAP = """\
Tools > Memory Map shows the memory of the simulated DE1-SoC computer, one entry per range, as the
Memory and devices tab describes it. While a program is assembled, its parts (.text, .data) are
listed under the DDR3 memory with their sizes.

"SP now:" under the table shows SP's value at this moment. It changes as the program runs, steps,
backsteps or is reset, and when you change SP in the Registers tab. Without an assembled program it
shows SP's start value, 0x00000000.

The window can stay open while you work and while the program runs. Choosing Tools > Memory Map
again brings it to the front.
"""

KEYBOARD = """\
On macOS, Command takes the place of Ctrl in the menus' shortcuts and in Ctrl+C.

## Commands

{table}

## The menus

| Key | What it does |
| Alt or F10 | select the menu bar, or leave it |
| Alt+F, E, R, S, T, H | open File, Edit, Run, Settings, Tools or Help |
| Left, Right | move along the bar, or to the menu beside the open one |
| Up, Down | move between the items; on the bar, open the menu |
| Enter | choose the highlighted item |
| An underlined letter | open that menu, or choose that item |
| Escape | close the menu, or leave the bar |

An item with an arrow at its right opens a submenu: Right, Enter or its letter open it, Left or
Escape close just the submenu, and the keys above work in it. While a menu is open the shortcuts
wait. A click outside the menus closes them and does nothing else. On macOS the menus are in the
screen menu bar.

## The registers

| Key | What it does |
| Double-click, Enter or F2 | open the field of the selected value |
| Enter | apply the value |
| Escape | leave the field as it was |

## The tables and the Help window

| Key | What it does |
| Up, Down, Page Up, Page Down | move through the rows or the text |
| Home, End | go to the start or the end of a Help page |
| Up, Down in the Tools tab | choose a tool; the other keys scroll its page |
| Up, Down in an instruction list | go to the row above or below |
| Right, Left in an instruction list | open or close the row's group; a click does the same |
| Left, Right elsewhere | scroll the columns of a table |
| Ctrl+Tab, Ctrl+Shift+Tab | go round the tabs inside ARM or ARES; in License and Acknowledgements, the top tabs |
| Ctrl+Page Down, Ctrl+Page Up | go to the next or the previous top tab of the Help window |
| Ctrl+C | copy the selected text |
| Enter, Escape | close the Help window |
| Escape | close a tool |
"""

ACKNOWLEDGEMENTS = """\
## The engines

ARES is built from these programs, whose authors made them free for everyone.

| Program | What it does in ARES |
| GNU binutils | the assembler and the linker |
| Unicorn | the processor and the memory, from QEMU's emulator |
| Capstone | the disassembler of the Basic column |
| pyelftools | reads the assembled program and its line numbers |
| Python | the language of ARES |
| Tcl/Tk | the windows |

## The Dynamic Instruction Counter and the textbook

The Dynamic Instruction Counter and the way it sorts instructions come from DynARMic
(GLSVLSI 2026). The textbook behind the ARM X-Ray:
"""

LICENSE_WORDS = """\
ARES is open source. Anyone may use it, study how it works, change it and share it. Changed versions
that are shared must stay open source too, under the same licence.

ARES is under the GNU General Public License, version 2 or any later version (GPL-2.0-or-later),
because it includes Unicorn, which is under version 2 of that licence. So a licence such as MIT could
not replace it.

The full licence comes first below, then the notices of the programs inside ARES.
"""


def operand_key():
    """The pane over the ARM tab's pages: what the example lines mean."""
    rows = "\n".join(f"| {code} | {words} | {flags} |"
                     for code, words, flags in instructions.CONDITIONS)
    return OPERAND_KEY.replace("{conditions}", rows)


OPERAND_KEY = """\
## Operand key for the example lines

| In an example | What may stand there |
| `label`, `=label` | any label of the program |
| `R1`, `R2`, `R3`, `R4` | any of the core registers R0 to R12, SP or LR, and PC where it makes sense |
| `R0, R1` of LDRD and STRD | two registers in a row, the first one even-numbered |
| `S1`, `S2`, `S3` | any single-precision register, S0 to S31 |
| `D0`, `D1`, `D2`, `D3` | any double-precision register, D0 to D31 |
| `Q0`, `Q1`, `Q2` | any quad register, Q0 to Q15 |
| `D2[1]` | one lane of a D register |
| `#100` | a constant: eight bits rotated by an even number of bits |
| `#0x1234` of MOVW, MOVT | any 16-bit constant |
| `=100000` | any 32-bit value |
| `LSL #2`, `LSL R4` | a shift by a constant or a register: LSL, LSR, ASR or ROR; or RRX, alone |
| `{R2, R3}` | a list of registers, in order, with ranges: {R0-R3, R7, LR} |
| `R1!` | R1 follows the registers stored or loaded |
| `.F32`, `.F64`, `.F16` | single, double and half precision |
| `.I32`, `.S32`, `.U32`, `.32` | a lane of 32 bits; also 8, 16 and 64 where the instruction has them |
| `P1`, `C1` | a coprocessor and one of its registers; see the Limits tab under ARES |

A row with + opens to show the instruction with each condition and with S; a click on it, or Right
and Left, opens and closes it. S and a condition go together too: `ADDEQS R1, R2, R3`.

ARES takes every ARMv7 instruction its assembler knows; the Basic column of the Text Segment shows
what each line became. The last value can be a register shifted on the way: `ADD R0, R1, R2, LSL #2`
adds four times R2. A constant must fit in eight bits rotated by an even number of bits; `LDR R0,
=value` loads any value. CMP, CMN, TST and TEQ only set the flags. LDRB and LDRH load with zeros
above, LDRSB and LDRSH keep the sign. A function ends with `BX LR`, or with `POP {..., PC}` when it
pushed LR.

## Addressing modes

| Form | The address | Example |
| [Rn] | the value of Rn | `LDR R0, [R1]` |
| [Rn, #offset] | Rn plus the offset | `LDR R0, [R1, #4]` |
| [Rn, Rm] | Rn plus Rm | `LDR R0, [R1, R2]` |
| [Rn, Rm, LSL #n] | Rn plus Rm shifted: an array's element | `LDR R0, [R1, R2, LSL #2]` |
| [Rn, #offset]! | Rn plus the offset, which stays in Rn | `LDR R0, [R1, #4]!` |
| [Rn], #offset | Rn, then the offset is added to Rn | `LDR R0, [R1], #4` |
| =value | any value or label, from a word near the code | `LDR R0, =table` |

## Condition codes

Written after an instruction, a condition makes it run only when the flags agree: `BEQ done`,
`ADDNE R0, R0, #1`, `MOVGT R0, R1`.

| Code | Runs when | Flags |
{conditions}

## The flags

An instruction sets the flags when it has an S after its name, as in `ADDS R0, R0, R1`, and CMP,
CMN, TST and TEQ always do. N is the result's sign, Z says it is zero, C is the carry out of an
addition or the absence of a borrow in a subtraction, and V says a signed result overflowed.
"""

# The tabs of the Help window, in order: (top tab, the tabs inside it).
TABS = (
    ("ARM", ("Basic Instructions", "Extended (pseudo) Instructions", "Directives", "Syscalls",
             "Registers", "Memory and devices")),
    ("ARES", ("Intro", "IDE", "Debugging", "Settings", "Tools", "Keyboard shortcuts", "Limits")),
    ("License", ()),
    ("Acknowledgements", ()),
)
# The pages of plain text; the others are made by the functions above.
PAGES = {"Directives": DIRECTIVES, "Registers": REGISTERS, "Memory and devices": DEVICES,
         "IDE": IDE, "Debugging": DEBUGGING, "Settings": SETTINGS}
