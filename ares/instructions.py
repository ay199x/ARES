# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The instructions of the Help window's lists, without a window.

BASIC holds every ARMv7 instruction ARES accepts, a row for each form of its operands, and
EXTENDED every alias and pseudo-instruction, which the assembler turns into another instruction.
A row is an example line and what it does. Its condition codes and S form are not written here:
variants() makes them from the names in ares.tokens, the tables that the highlighting and the
capitals rule use, so the lists cannot drift from them. LEFT_OUT names the mnemonics of those
tables that are on neither list, with the reason.

The tables are text, a row on a line: ``example | description``. In the table of Neon
instructions a ``*`` at the start asks for the same row on quad registers too.
"""

import re
from dataclasses import dataclass
from functools import cache
from itertools import product

from .tokens import _PARALLEL, mnemonic_base, mnemonic_forms

GAP = 2                         # between an example and its description
OPEN, CLOSED, NO_GROUP = "- ", "+ ", "  "       # what starts a row, before its example
VARIANT = "    "                                # what starts a row of a group

# The condition codes as a row shows them: code, when it runs, what the flags say.
CONDITIONS = (
    ("EQ", "equal", "Z set"),
    ("NE", "not equal", "Z clear"),
    ("CS", "carry set; unsigned higher or same", "C set"),
    ("HS", "unsigned higher or same", "C set"),
    ("CC", "carry clear; unsigned lower", "C clear"),
    ("LO", "unsigned lower", "C clear"),
    ("MI", "negative", "N set"),
    ("PL", "positive or zero", "N clear"),
    ("VS", "overflow", "V set"),
    ("VC", "no overflow", "V clear"),
    ("HI", "unsigned higher", "C set and Z clear"),
    ("LS", "unsigned lower or same", "C clear or Z set"),
    ("GE", "signed greater or equal", "N equals V"),
    ("LT", "signed less", "N differs from V"),
    ("GT", "signed greater", "Z clear and N equals V"),
    ("LE", "signed less or equal", "Z set or N differs from V"),
    ("AL", "always", "any"),
)

# What the S form of an instruction sets.
_SETS_ALL = "ADC ADD NEG RSB RSC SBC SUB".split()
_SETS_CARRY = "AND ASR BIC EOR LSL LSR MOV MVN ORR ROR RRX".split()
_SETS_SIGN = "MLA MUL SMLAL SMULL UMLAL UMULL".split()
_FLAGS_SET = {**dict.fromkeys(_SETS_ALL, "N, Z, C and V"), **dict.fromkeys(_SETS_CARRY, "N, Z and C"),
              **dict.fromkeys(_SETS_SIGN, "N and Z")}

# What ares.tokens takes as a word with a condition, and the assembler refuses in these lines.
_NO_CONDITION = frozenset("BKPT HLT RRX UDF".split())
_NO_VARIANTS = re.compile(r"BLX label$|MOV R1, #0x1234$")
_WHOLE_D = r"\bD(\d)\b(?!\[)"     # a D register, not one of its lanes


@dataclass(frozen=True)
class Row:
    """A row of a list: an example line and what it does."""
    example: str
    description: str
    conditional: bool = True    # False: a form that takes no condition, such as a Neon one

    @property
    def word(self):
        """The mnemonic of the example, with its data types: VADD.F32."""
        return self.example.split(" ", 1)[0]

    @property
    def base(self):
        """The instruction the example belongs to in ares.tokens."""
        return mnemonic_base(self.word)


def _condition_form(row, code):
    """The row's mnemonic with a condition, in the place the assembler wants it: an ending
    follows it, as in LDREQB and LDMEQIA."""
    core, dot, types = row.word.partition(".")
    base = row.base
    form = base + code + core[len(base):]
    return form + dot + types if mnemonic_base(form) == base else None


def has_variants(row):
    """True when a row has a group under it, without making the group."""
    if not row.conditional:
        return False
    if row.base not in _NO_CONDITION and _condition_form(row, "EQ"):
        return True
    return row.base in _FLAGS_SET and mnemonic_base(row.word + "S") == row.base


@cache
def variants(row):
    """The rows of the group under a row: its condition codes, then its S form."""
    if not row.conditional:
        return ()
    operands = row.example[len(row.word):]
    rows = []
    for code, words, flags in CONDITIONS:
        form = None if row.base in _NO_CONDITION else _condition_form(row, code)
        if form is not None:
            rows.append(Row(form + operands, f"As {row.word}, if {words} ({flags})", False))
    flags = _FLAGS_SET.get(row.base)
    if flags and mnemonic_base(row.word + "S") == row.base:
        rows.append(Row(row.word + "S" + operands, f"As {row.word}, and sets {flags}", False))
    return tuple(rows)


def text_of(row, width, start=NO_GROUP):
    """A row as the list shows it: the example padded to width, then the description."""
    return (start + row.example).ljust(width) + row.description


def column(rows):
    """Where the descriptions of a list start: past its longest example, also with a condition."""
    longest = max(len(row.example) + (2 if row.conditional else 0) for row in rows)
    return len(VARIANT) + longest + GAP


def _table(text, conditional=True):
    """The rows of a table: ``example | description`` on each line."""
    rows = []
    for line in text.strip().split("\n"):
        example, description = (part.strip() for part in line.split(" | "))
        both = example.startswith("*")
        example = example.lstrip("* ")
        allowed = conditional and not _NO_VARIANTS.search(example)
        rows.append(Row(example, description, allowed))
        if both:
            rows.append(Row(_quad(example, example), _quad(description, example), allowed))
    return rows


def _quad(text, example):
    """text with Q for the D registers of example that are whole registers, not lanes."""
    numbers = "|".join(re.findall(_WHOLE_D, example))
    return re.sub(_WHOLE_D.replace(r"\d", numbers), r"Q\1", text) if numbers else text


def _three_operands(name, words, formula):
    """The forms of an instruction with a flexible last operand: formula has {} in its place."""
    rows = [("R1, R2, R3", "R3"), ("R1, R2, #100", "100"),
            ("R1, R2, R3, LSL #2", "R3 shifted"), ("R1, R2, R3, LSL R4", "R3 shifted by R4")]
    return [Row(f"{name} {operands}", f"{words}: R1 = {formula.format(value)}")
            for operands, value in rows]


def _two_operands(name, words, formula):
    """The forms of MOV, CMP and their kind: formula has {} in the place of the last operand."""
    rows = [("R1, R2", "R2"), ("R1, #100", "100"), ("R1, R2, LSL #2", "R2 shifted"),
            ("R1, R2, LSL R3", "R2 shifted by R3")]
    return [Row(f"{name} {operands}", f"{words}: {formula.format(value)}")
            for operands, value in rows]


def _load_store(name, words, target, forms):
    """The rows of a load or a store: forms are (operand, what the address is)."""
    return [Row(f"{name} {target}, {operand}", f"{words}: {address}") for operand, address in forms]


_ADDRESS_R2 = ("[R2]", "address R2")
_ADDRESS_OFFSET = ("[R2, #100]", "address R2 + 100")
_ADDRESS_REGISTER = ("[R2, R3]", "address R2 + R3")
_ADDRESS_SHIFTED = ("[R2, R3, LSL #2]", "address R2 + R3 shifted")
_ADDRESS_FIRST = ("[R2, #100]!", "address R2 + 100, then R2 keeps it")
_ADDRESS_REGISTER_FIRST = ("[R2, R3]!", "address R2 + R3, then R2 keeps it")
_ADDRESS_SHIFTED_FIRST = ("[R2, R3, LSL #2]!", "address R2 + R3 shifted, then R2 keeps it")
_ADDRESS_AFTER = ("[R2], #100", "address R2, then 100 is added to R2")
_ADDRESS_REGISTER_AFTER = ("[R2], R3", "address R2, then R3 is added to R2")
_ADDRESS_SHIFTED_AFTER = ("[R2], R3, LSL #2", "address R2, then R3 shifted is added to R2")
_ADDRESS_LABEL = ("label", "address of label, near the instruction")
_WORD_FORMS = (_ADDRESS_R2, _ADDRESS_OFFSET, _ADDRESS_REGISTER, _ADDRESS_SHIFTED, _ADDRESS_FIRST,
               _ADDRESS_REGISTER_FIRST, _ADDRESS_SHIFTED_FIRST, _ADDRESS_AFTER,
               _ADDRESS_REGISTER_AFTER, _ADDRESS_SHIFTED_AFTER, _ADDRESS_LABEL)
_HALF_FORMS = (_ADDRESS_R2, _ADDRESS_OFFSET, _ADDRESS_REGISTER, _ADDRESS_FIRST,
               _ADDRESS_REGISTER_FIRST, _ADDRESS_AFTER, _ADDRESS_REGISTER_AFTER, _ADDRESS_LABEL)
_USER_FORMS = (("[R2]", "address R2, with User mode's rights"),
               ("[R2], #4", "the same, then 4 is added to R2"))

_MULTIPLE = (("IA", "from R1 upwards"), ("IB", "from above R1 upwards"),
             ("DA", "from R1 downwards"), ("DB", "from below R1 downwards"))


def _multiple(name, words):
    """The rows of LDM or STM."""
    rows = [Row(f"{name} R1, {{R2, R3}}", f"{words}: from R1 upwards"),
            Row(f"{name} R1!, {{R2, R3}}", f"{words}: from R1 upwards, then R1 follows")]
    for ending, place in _MULTIPLE:
        rows.append(Row(f"{name}{ending} R1, {{R2, R3}}", f"{words}: {place}"))
        rows.append(Row(f"{name}{ending} R1!, {{R2, R3}}", f"{words}: {place}, then R1 follows"))
    return rows


_PARALLEL_PREFIX = {"S": "Signed", "Q": "Saturating signed", "SH": "Halving signed",
                    "U": "Unsigned", "UQ": "Saturating unsigned", "UH": "Halving unsigned"}
_PARALLEL_OPERATION = {
    "ADD16": "add of each halfword", "ADD8": "add of each byte",
    "ASX": "add and subtract, R3's halves crossed",
    "SAX": "subtract and add, R3's halves crossed",
    "SUB16": "subtract of each halfword", "SUB8": "subtract of each byte"}
_PARALLEL_OLD_NAME = {"ADDSUBX": "ASX", "SUBADDX": "SAX"}


def _parallel():
    """Parallel add and subtract: (basic rows, rows of their old names)."""
    prefixes, operations = _PARALLEL
    basic, old = [], []
    for prefix, operation in product(prefixes.split(), operations.split()):
        example = f"{prefix}{operation} R1, R2, R3"
        if operation in _PARALLEL_OLD_NAME:
            old.append(Row(example, f"Old name of {prefix}{_PARALLEL_OLD_NAME[operation]}"))
        else:
            words = f"{_PARALLEL_PREFIX[prefix]} {_PARALLEL_OPERATION[operation]}"
            basic.append(Row(example, words))
    return basic, old


_INTEGER = """
B label | Branch to label
BFC R1, #4, #8 | Bit field clear: 8 bits of R1 from bit 4 become 0
BFI R1, R2, #4, #8 | Bit field insert: 8 bits of R1 from bit 4 = low 8 bits of R2
BL label | Branch with link: LR = the next instruction, then go to label
BLX R1 | Branch with link to the address in R1, which can change state
BLX label | Branch with link to Thumb code at label, which ARES does not support
BX R1 | Branch to the address in R1, which can change state
BXJ R1 | Branch to Jazelle state; on this CPU, as BX R1
CLZ R1, R2 | Count leading zeros: R1 = the zero bits above R2's highest 1
MOVT R1, #0x1234 | Move top: high half of R1 = 0x1234, low half stays
MOVW R1, #0x1234 | Move wide: R1 = any 16-bit value
MRS R1, APSR | Copy the flags to a register
MRS R1, CPSR | Copy CPSR to a register
MRS R1, SPSR | Copy the saved SPSR of the current mode to a register
MSR APSR_nzcvq, R1 | Set the flags and Q from the top five bits of R1
MSR CPSR_c, R1 | Set the mode and interrupt bits of CPSR from R1
MSR CPSR_f, #0xF0000000 | Set the flags from a value
MSR CPSR_f, R1 | Set the flags of CPSR from R1
PKHBT R1, R2, R3 | Pack: low half of R2 with high half of R3
PKHBT R1, R2, R3, LSL #4 | Pack: low half of R2 with high half of R3 shifted left
PKHTB R1, R2, R3 | Pack: high half of R2 with low half of R3
PKHTB R1, R2, R3, ASR #4 | Pack: high half of R2 with low half of R3 shifted right
QADD R1, R2, R3 | Saturating add: R1 = R2 + R3, held at the signed limits, sets Q
QDADD R1, R2, R3 | Saturating add of double: R1 = R2 + 2 x R3, sets Q
QDSUB R1, R2, R3 | Saturating subtract of double: R1 = R2 - 2 x R3, sets Q
QSUB R1, R2, R3 | Saturating subtract: R1 = R2 - R3, held at the limits, sets Q
RBIT R1, R2 | Reverse bits: bit 31 of R2 to bit 0 of R1, and so on
REV R1, R2 | Reverse the four bytes of R2
REV16 R1, R2 | Reverse the two bytes of each half of R2
REVSH R1, R2 | Reverse the low two bytes of R2 and extend the sign
SBFX R1, R2, #4, #8 | Signed bit field: R1 = 8 bits of R2 from bit 4, sign extended
SEL R1, R2, R3 | Select each byte from R2 or R3, as the GE flags say
SSAT R1, #8, R2 | Saturate R2 to 8 signed bits; sets Q when it changes
SSAT R1, #8, R2, LSL #2 | Saturate R2 shifted to 8 signed bits
SSAT16 R1, #8, R2 | Saturate each half of R2 to 8 signed bits
SVC #4 | System call: ask ARES for service 4 (see Syscalls)
SWP R1, R2, [R3] | Swap: R1 = the word at R3, which becomes R2; deprecated
SWPB R1, R2, [R3] | Swap a byte: R1 = the byte at R3, which becomes R2; deprecated
SXTAB R1, R2, R3 | R1 = R2 + the low byte of R3, sign extended
SXTAB R1, R2, R3, ROR #8 | The same, with R3 rotated first: 8, 16 or 24
SXTAB16 R1, R2, R3 | Add bytes 0 and 2 of R3, sign extended, to the halves of R2
SXTAH R1, R2, R3 | R1 = R2 + the low half of R3, sign extended
SXTB R1, R2 | R1 = the low byte of R2, sign extended
SXTB R1, R2, ROR #8 | The same, with R2 rotated first: 8, 16 or 24
SXTB16 R1, R2 | Sign extend bytes 0 and 2 of R2 into the halves of R1
SXTH R1, R2 | R1 = the low half of R2, sign extended
UBFX R1, R2, #4, #8 | Unsigned bit field: R1 = 8 bits of R2 from bit 4
USAT R1, #8, R2 | Saturate R2 to 8 unsigned bits; sets Q when it changes
USAT R1, #8, R2, LSL #2 | Saturate R2 shifted to 8 unsigned bits
USAT16 R1, #8, R2 | Saturate each half of R2 to 8 unsigned bits
USAD8 R1, R2, R3 | Sum of the absolute differences of the bytes of R2 and R3
USADA8 R1, R2, R3, R4 | The same, added to R4
UXTAB R1, R2, R3 | R1 = R2 + the low byte of R3
UXTAB R1, R2, R3, ROR #8 | The same, with R3 rotated first: 8, 16 or 24
UXTAB16 R1, R2, R3 | Add bytes 0 and 2 of R3 to the halves of R2
UXTAH R1, R2, R3 | R1 = R2 + the low half of R3
UXTB R1, R2 | R1 = the low byte of R2
UXTB R1, R2, ROR #8 | The same, with R2 rotated first: 8, 16 or 24
UXTB16 R1, R2 | Put bytes 0 and 2 of R2 in the halves of R1
UXTH R1, R2 | R1 = the low half of R2
"""

_MULTIPLY = """
MLA R1, R2, R3, R4 | Multiply and add: R1 = R2 x R3 + R4
MLS R1, R2, R3, R4 | Multiply and subtract: R1 = R4 - R2 x R3
MUL R1, R2, R3 | Multiply: R1 = R2 x R3, the low 32 bits
SMLABB R1, R2, R3, R4 | R1 = R4 + low half of R2 x low half of R3, sets Q on overflow
SMLABT R1, R2, R3, R4 | R1 = R4 + low half of R2 x high half of R3
SMLAD R1, R2, R3, R4 | R1 = R4 + the sum of the products of the halves of R2 and R3
SMLADX R1, R2, R3, R4 | The same, with the halves of R3 crossed
SMLAL R1, R2, R3, R4 | Signed: R2:R1 += R3 x R4, 64 bits
SMLALBB R1, R2, R3, R4 | R2:R1 += low half of R3 x low half of R4
SMLALBT R1, R2, R3, R4 | R2:R1 += low half of R3 x high half of R4
SMLALD R1, R2, R3, R4 | R2:R1 += the sum of the products of the halves of R3 and R4
SMLALDX R1, R2, R3, R4 | The same, with the halves of R4 crossed
SMLALTB R1, R2, R3, R4 | R2:R1 += high half of R3 x low half of R4
SMLALTT R1, R2, R3, R4 | R2:R1 += high half of R3 x high half of R4
SMLATB R1, R2, R3, R4 | R1 = R4 + high half of R2 x low half of R3
SMLATT R1, R2, R3, R4 | R1 = R4 + high half of R2 x high half of R3
SMLAWB R1, R2, R3, R4 | R1 = R4 + top 32 bits of R2 x low half of R3
SMLAWT R1, R2, R3, R4 | R1 = R4 + top 32 bits of R2 x high half of R3
SMLSD R1, R2, R3, R4 | R1 = R4 + the difference of the products of the halves
SMLSDX R1, R2, R3, R4 | The same, with the halves of R3 crossed
SMLSLD R1, R2, R3, R4 | R2:R1 += the difference of the products of the halves
SMLSLDX R1, R2, R3, R4 | The same, with the halves of R4 crossed
SMMLA R1, R2, R3, R4 | R1 = R4 + the high 32 bits of R2 x R3
SMMLAR R1, R2, R3, R4 | The same, rounded
SMMLS R1, R2, R3, R4 | R1 = R4 - the high 32 bits of R2 x R3
SMMLSR R1, R2, R3, R4 | The same, rounded
SMMUL R1, R2, R3 | R1 = the high 32 bits of R2 x R3, signed
SMMULR R1, R2, R3 | The same, rounded
SMUAD R1, R2, R3 | R1 = the sum of the products of the halves of R2 and R3
SMUADX R1, R2, R3 | The same, with the halves of R3 crossed
SMULBB R1, R2, R3 | R1 = low half of R2 x low half of R3, signed
SMULBT R1, R2, R3 | R1 = low half of R2 x high half of R3
SMULL R1, R2, R3, R4 | Signed multiply: R2:R1 = R3 x R4, 64 bits
SMULTB R1, R2, R3 | R1 = high half of R2 x low half of R3
SMULTT R1, R2, R3 | R1 = high half of R2 x high half of R3
SMULWB R1, R2, R3 | R1 = top 32 bits of R2 x low half of R3
SMULWT R1, R2, R3 | R1 = top 32 bits of R2 x high half of R3
SMUSD R1, R2, R3 | R1 = the difference of the products of the halves of R2 and R3
SMUSDX R1, R2, R3 | The same, with the halves of R3 crossed
UMAAL R1, R2, R3, R4 | Unsigned: R2:R1 = R3 x R4 + R1 + R2, 64 bits
UMLAL R1, R2, R3, R4 | Unsigned: R2:R1 += R3 x R4, 64 bits
UMULL R1, R2, R3, R4 | Unsigned multiply: R2:R1 = R3 x R4, 64 bits
"""

_LOAD_STORE = """
LDRD R0, R1, [R2] | Load two words: R0 and R1, from address R2
LDRD R0, R1, [R2, #8] | Load two words: address R2 + 8
LDRD R0, R1, [R2, R3] | Load two words: address R2 + R3
LDRD R0, R1, [R2, #8]! | Load two words: address R2 + 8, then R2 keeps it
LDRD R0, R1, [R2], #8 | Load two words: address R2, then 8 is added to R2
LDRD R0, R1, label | Load two words: address of label, near the instruction
LDREX R1, [R2] | Load a word and watch its address, for STREX
LDREXB R1, [R2] | Load a byte and watch its address, for STREXB
LDREXD R0, R1, [R2] | Load two words and watch their address, for STREXD
LDREXH R1, [R2] | Load a halfword and watch its address, for STREXH
STRD R0, R1, [R2] | Store two words: R0 and R1, at address R2
STRD R0, R1, [R2, #8] | Store two words: address R2 + 8
STRD R0, R1, [R2, R3] | Store two words: address R2 + R3
STRD R0, R1, [R2, #8]! | Store two words: address R2 + 8, then R2 keeps it
STRD R0, R1, [R2], #8 | Store two words: address R2, then 8 is added to R2
STREX R1, R3, [R2] | Store R3 if the address is still watched: R1 = 0 if it was
STREXB R1, R3, [R2] | The same with a byte
STREXD R1, R2, R3, [R4] | The same with two words, R2 and R3
STREXH R1, R3, [R2] | The same with a halfword
"""

_SYSTEM = """
BKPT #1 | Breakpoint instruction: ends the program with a runtime error
CDP P1, 1, C1, C2, C3, 2 | Coprocessor operation
CDP2 P1, 1, C1, C2, C3, 2 | Coprocessor operation, the second encoding
CLREX | Stop watching the address of the last LDREX
CPS #19 | Change the processor's mode; 19 is Supervisor
CPSID I | Mask interrupts: I, F or A
CPSID I, #19 | Mask interrupts and change the mode
CPSIE I | Unmask interrupts: I, F or A
CPSIE I, #19 | Unmask interrupts and change the mode
CSDB | Barrier against speculation; does nothing here
DBG #1 | Debug hint; does nothing here
DMB | Data memory barrier; does nothing here
DMB ISH | Data memory barrier for an option such as ISH, SY or ST
DSB | Data synchronization barrier; does nothing here
DSB ISH | Data synchronization barrier for an option
HLT #1 | Halt for a debugger: ends the program with a runtime error
ISB | Instruction synchronization barrier; does nothing here
IT EQ | If-Then of Thumb state: makes no code in ARM state
ITE EQ | If-Then-Else of Thumb state: makes no code in ARM state
ITT EQ | If-Then-Then of Thumb state: makes no code in ARM state
ITTE EQ | If-Then-Then-Else of Thumb state: makes no code in ARM state
LDC P1, C1, [R2] | Load a coprocessor register from address R2
LDC2 P1, C1, [R2] | The same, the second encoding
LDC2L P1, C1, [R2] | The same, a long transfer
LDCL P1, C1, [R2] | Load a coprocessor register, a long transfer
MCR P15, 0, R1, C13, C0, 2 | Copy R1 to a coprocessor register
MCR2 P1, 0, R1, C1, C0, 0 | The same, the second encoding
MCRR P1, 0, R1, R2, C3 | Copy two registers to a coprocessor
MCRR2 P1, 0, R1, R2, C3 | The same, the second encoding
MRC P15, 0, R1, C0, C0, 0 | Copy a coprocessor register to R1; this one is the CPU's ID
MRC2 P1, 0, R1, C0, C0, 0 | The same, the second encoding
MRRC P1, 0, R1, R2, C3 | Copy from a coprocessor to two registers
MRRC2 P1, 0, R1, R2, C3 | The same, the second encoding
PLD [R1] | Hint: the data at address R1 will be read; does nothing here
PLD [R1, #100] | The same, at address R1 + 100
PLD [R1, R2] | The same, at address R1 + R2
PLDW [R1] | Hint: the data at address R1 will be written; does nothing here
PLI [R1] | Hint: code at address R1 will run; does nothing here
PSSBB | Barrier against speculative loads; does nothing here
RFEDA R1 | Return from exception: PC and CPSR, from R1 downwards
RFEDB R1 | Return from exception: PC and CPSR, from below R1
RFEIA R1 | Return from exception: PC and CPSR, from R1 upwards
RFEIA R1! | The same, then R1 follows
RFEIB R1 | Return from exception: PC and CPSR, from above R1
SEV | Send event; does nothing here
SETEND BE | Change the order of bytes in memory: BE or LE
SMC #1 | Secure monitor call: ends the program with a runtime error
SRSDA SP, #19 | Store LR and SPSR on the stack of mode 19, at SP and below
SRSDB SP, #19 | Store LR and SPSR on the stack of mode 19, below SP
SRSDB SP!, #19 | The same, then that SP follows
SRSIA SP, #19 | Store LR and SPSR on the stack of mode 19, from SP up
SRSIB SP, #19 | Store LR and SPSR on the stack of mode 19, above SP
SSBB | Barrier against speculative stores; does nothing here
STC P1, C1, [R2] | Store a coprocessor register at address R2
STC2 P1, C1, [R2] | The same, the second encoding
STC2L P1, C1, [R2] | The same, a long transfer
STCL P1, C1, [R2] | Store a coprocessor register, a long transfer
UDF #1 | Undefined instruction: ends the program with a runtime error
WFE | Wait for event; does nothing here
WFI | Wait for interrupt; does nothing here
YIELD | Hint to other threads; does nothing here
"""

_FLOAT = """
* VDUP.32 D0, R1 | Neon: copy a core register to every lane
VMOV.32 D0[1], R1 | Copy a core register to a lane
VMOV.32 R1, D0[1] | Copy a lane to a core register
VABS.F32 S1, S2 | Absolute value: S1 = |S2|
VABS.F64 D1, D2 | Absolute value: D1 = |D2|
VADD.F32 S1, S2, S3 | Add: S1 = S2 + S3
VADD.F64 D1, D2, D3 | Add: D1 = D2 + D3
VCMP.F32 S1, #0.0 | Compare with zero: sets FPSCR's N, Z, C and V
VCMP.F32 S1, S2 | Compare: sets FPSCR's N, Z, C and V
VCMP.F64 D1, #0.0 | Compare with zero: sets FPSCR's N, Z, C and V
VCMP.F64 D1, D2 | Compare: sets FPSCR's N, Z, C and V
VCMPE.F32 S1, S2 | Compare, and a NaN sets the invalid operation flag
VCMPE.F64 D1, D2 | Compare, and a NaN sets the invalid operation flag
VCVT.F32.F64 S1, D2 | Convert double to single precision
VCVT.F32.S32 S1, S2 | Convert a signed integer to single precision
VCVT.F32.S32 S1, S1, #8 | Convert signed fixed point, 8 fraction bits, to single
VCVT.F32.U32 S1, S2 | Convert an unsigned integer to single precision
VCVT.F64.F32 D1, S2 | Convert single to double precision
VCVT.F64.S32 D1, S2 | Convert a signed integer to double precision
VCVT.F64.U32 D1, S2 | Convert an unsigned integer to double precision
VCVT.S32.F32 S1, S2 | Convert single precision to a signed integer, towards zero
VCVT.S32.F64 S1, D2 | Convert double precision to a signed integer, towards zero
VCVT.U32.F32 S1, S2 | Convert single precision to an unsigned integer, towards zero
VCVT.U32.F64 S1, D2 | Convert double precision to an unsigned integer, towards zero
VCVTB.F16.F32 S1, S2 | Single precision to the low half of S1, half precision
VCVTB.F32.F16 S1, S2 | The low half of S2, half precision, to single precision
VCVTR.S32.F32 S1, S2 | Convert to a signed integer, rounding as FPSCR says
VCVTR.U32.F64 S1, D2 | Convert to an unsigned integer, rounding as FPSCR says
VCVTT.F16.F32 S1, S2 | Single precision to the high half of S1, half precision
VCVTT.F32.F16 S1, S2 | The high half of S2, half precision, to single precision
VDIV.F32 S1, S2, S3 | Divide: S1 = S2 / S3
VDIV.F64 D1, D2, D3 | Divide: D1 = D2 / D3
VLDM R1, {S1, S2} | Load registers from R1 upwards
VLDMDB R1!, {S1, S2} | Load registers from below R1, then R1 follows
VLDMIA R1!, {D1, D2} | Load registers from R1 upwards, then R1 follows
VLDR D1, [R1] | Load a double from address R1
VLDR D1, [R1, #8] | Load a double from address R1 + 8
VLDR D1, label | Load a double from label, near the instruction
VLDR S1, [R1] | Load a single from address R1
VLDR S1, [R1, #4] | Load a single from address R1 + 4
VLDR S1, label | Load a single from label, near the instruction
VMLA.F32 S1, S2, S3 | Multiply and add: S1 = S1 + S2 x S3
VMLA.F64 D1, D2, D3 | Multiply and add: D1 = D1 + D2 x D3
VMLS.F32 S1, S2, S3 | Multiply and subtract: S1 = S1 - S2 x S3
VMLS.F64 D1, D2, D3 | Multiply and subtract: D1 = D1 - D2 x D3
VMOV D1, R1, R2 | Copy two core registers into D1: R1 low, R2 high
VMOV R1, R2, D1 | Copy D1 into two core registers: R1 low, R2 high
VMOV R1, R2, S1, S2 | Copy two S registers, one after the other, to core registers
VMOV R1, S1 | Copy an S register to a core register
VMOV S1, R1 | Copy a core register to an S register
VMOV S1, S2, R1, R2 | Copy two core registers to S1 and S2, one after the other
VMOV.F32 S1, #1.0 | Load a simple constant
VMOV.F32 S1, S2 | Copy a single
VMOV.F64 D1, #1.0 | Load a simple constant
VMOV.F64 D1, D2 | Copy a double
VMRS APSR_nzcv, FPSCR | Copy FPSCR's flags to CPSR's: conditions then see a VCMP
VMRS R1, FPSCR | Copy FPSCR to a core register
VMSR FPSCR, R1 | Copy a core register to FPSCR
VMUL.F32 S1, S2, S3 | Multiply: S1 = S2 x S3
VMUL.F64 D1, D2, D3 | Multiply: D1 = D2 x D3
VNEG.F32 S1, S2 | Change the sign: S1 = -S2
VNEG.F64 D1, D2 | Change the sign: D1 = -D2
VNMLA.F32 S1, S2, S3 | Negated: S1 = -S1 - S2 x S3
VNMLA.F64 D1, D2, D3 | Negated: D1 = -D1 - D2 x D3
VNMLS.F32 S1, S2, S3 | Negated: S1 = -S1 + S2 x S3
VNMLS.F64 D1, D2, D3 | Negated: D1 = -D1 + D2 x D3
VNMUL.F32 S1, S2, S3 | Negated multiply: S1 = -(S2 x S3)
VNMUL.F64 D1, D2, D3 | Negated multiply: D1 = -(D2 x D3)
VSQRT.F32 S1, S2 | Square root of S2
VSQRT.F64 D1, D2 | Square root of D2
VSTM R1, {S1, S2} | Store registers from R1 upwards
VSTMDB R1!, {S1, S2} | Store registers below R1, then R1 follows
VSTMIA R1!, {D1, D2} | Store registers from R1 upwards, then R1 follows
VSTR D1, [R1] | Store a double at address R1
VSTR D1, [R1, #8] | Store a double at address R1 + 8
VSTR S1, [R1] | Store a single at address R1
VSTR S1, [R1, #4] | Store a single at address R1 + 4
VSUB.F32 S1, S2, S3 | Subtract: S1 = S2 - S3
VSUB.F64 D1, D2, D3 | Subtract: D1 = D2 - D3
"""

_NEON = """
* VABA.S32 D0, D1, D2 | Neon: add the absolute differences of D1 and D2 to D0
VABAL.S32 Q0, D1, D2 | Neon: the same, into lanes twice as wide
* VABD.S32 D0, D1, D2 | Neon: absolute difference of each lane
* VABD.F32 D0, D1, D2 | Neon: absolute difference of each lane of singles
VABDL.S32 Q0, D1, D2 | Neon: absolute difference, into lanes twice as wide
* VABS.S32 D0, D1 | Neon: absolute value of each lane
* VACGE.F32 D0, D1, D2 | Neon: all ones in a lane where |D1| >= |D2|
* VACGT.F32 D0, D1, D2 | Neon: all ones in a lane where |D1| > |D2|
* VADD.F32 D0, D1, D2 | Neon: add each lane of singles
* VADD.I32 D0, D1, D2 | Neon: add each lane
VADDHN.I32 D0, Q1, Q2 | Neon: add, keeping the high half of each lane
VADDL.S32 Q0, D1, D2 | Neon: add into lanes twice as wide
VADDW.S32 Q0, Q1, D2 | Neon: add narrow lanes to wide lanes
* VAND D0, D1, D2 | Neon: AND of all the bits
* VBIC D0, D1, D2 | Neon: clear the bits set in D2
* VBIC.I32 D0, #0xFF | Neon: clear the bits of a value in each lane
* VBIF D0, D1, D2 | Neon: insert bits of D1 where D2 has zeros
* VBIT D0, D1, D2 | Neon: insert bits of D1 where D2 has ones
* VBSL D0, D1, D2 | Neon: select bits of D1 or D2, as D0 says
* VCEQ.I32 D0, D1, D2 | Neon: all ones in a lane where D1 = D2
* VCEQ.I32 D0, D1, #0 | Neon: all ones in a lane where D1 = 0
* VCGE.S32 D0, D1, D2 | Neon: all ones in a lane where D1 >= D2
* VCGE.S32 D0, D1, #0 | Neon: all ones in a lane where D1 >= 0
* VCGT.S32 D0, D1, D2 | Neon: all ones in a lane where D1 > D2
* VCGT.S32 D0, D1, #0 | Neon: all ones in a lane where D1 > 0
* VCLE.S32 D0, D1, #0 | Neon: all ones in a lane where D1 <= 0
* VCLS.S32 D0, D1 | Neon: count the bits under the sign that equal it
* VCLT.S32 D0, D1, #0 | Neon: all ones in a lane where D1 < 0
* VCLZ.I32 D0, D1 | Neon: count leading zeros of each lane
* VCNT.8 D0, D1 | Neon: count the ones of each byte
* VCVT.F32.S32 D0, D1 | Neon: convert each integer lane to single precision
* VCVT.F32.S32 D0, D1, #8 | Neon: convert fixed point, 8 fraction bits, to single
* VCVT.S32.F32 D0, D1 | Neon: convert each lane of singles to integers
VCVT.F16.F32 D0, Q1 | Neon: convert each lane to half precision
VCVT.F32.F16 Q0, D1 | Neon: convert each lane from half precision
* VDUP.32 D0, D1[1] | Neon: copy a lane to every lane
* VEOR D0, D1, D2 | Neon: exclusive OR of all the bits
* VEXT.8 D0, D1, D2, #3 | Neon: bytes of D1 from byte 3 on, then bytes of D2
* VHADD.S32 D0, D1, D2 | Neon: add each lane and halve
* VHSUB.S32 D0, D1, D2 | Neon: subtract each lane and halve
VLD1.32 {D0, D1}, [R1] | Neon: load registers from address R1
VLD1.32 {D0, D1}, [R1]! | Neon: the same, then R1 follows
VLD1.32 {D0, D1}, [R1], R2 | Neon: the same, then R2 is added to R1
VLD1.32 {D0[1]}, [R1] | Neon: load one lane
VLD1.32 {D0[]}, [R1] | Neon: load one value into every lane
VLD2.32 {D0, D1}, [R1] | Neon: load pairs, the first of each to D0, the second to D1
VLD3.32 {D0, D1, D2}, [R1] | Neon: load groups of three into three registers
VLD4.32 {D0, D1, D2, D3}, [R1] | Neon: load groups of four into four registers
* VMAX.F32 D0, D1, D2 | Neon: the greater of each lane of singles
* VMAX.S32 D0, D1, D2 | Neon: the greater of each lane
* VMIN.F32 D0, D1, D2 | Neon: the smaller of each lane of singles
* VMIN.S32 D0, D1, D2 | Neon: the smaller of each lane
* VMLA.F32 D0, D1, D2 | Neon: multiply and add each lane of singles
* VMLA.I32 D0, D1, D2 | Neon: multiply and add each lane
* VMLA.I32 D0, D1, D2[1] | Neon: multiply by one lane of D2 and add
VMLAL.S32 Q0, D1, D2 | Neon: multiply and add into lanes twice as wide
VMLAL.S32 Q0, D1, D2[1] | Neon: the same, by one lane of D2
* VMLS.F32 D0, D1, D2 | Neon: multiply and subtract each lane of singles
* VMLS.I32 D0, D1, D2 | Neon: multiply and subtract each lane
* VMLS.I32 D0, D1, D2[1] | Neon: multiply by one lane of D2 and subtract
VMLSL.S32 Q0, D1, D2 | Neon: multiply and subtract into lanes twice as wide
VMLSL.S32 Q0, D1, D2[1] | Neon: the same, by one lane of D2
* VMOV D0, D1 | Neon: copy a register
* VMOV.I32 D0, #0xFF | Neon: put a value in every lane
VMOVL.S32 Q0, D1 | Neon: widen each lane
VMOVN.I32 D0, Q1 | Neon: narrow each lane, keeping its low half
* VMUL.F32 D0, D1, D2 | Neon: multiply each lane of singles
* VMUL.I32 D0, D1, D2 | Neon: multiply each lane
* VMUL.I32 D0, D1, D2[1] | Neon: multiply by one lane of D2
* VMUL.P8 D0, D1, D2 | Neon: multiply each byte as a polynomial
VMULL.P8 Q0, D1, D2 | Neon: polynomial multiply into lanes twice as wide
VMULL.S32 Q0, D1, D2 | Neon: multiply into lanes twice as wide
VMULL.S32 Q0, D1, D2[1] | Neon: the same, by one lane of D2
* VMVN D0, D1 | Neon: invert all the bits
* VMVN.I32 D0, #0xFF | Neon: put the inverted value in every lane
* VNEG.S32 D0, D1 | Neon: change the sign of each lane
* VORN D0, D1, D2 | Neon: OR with the inverted bits of D2
* VORR D0, D1, D2 | Neon: OR of all the bits
* VORR.I32 D0, #0xFF | Neon: set the bits of a value in each lane
* VPADAL.S32 D0, D1 | Neon: add neighbouring lanes of D1 to D0's wider lanes
VPADD.F32 D0, D1, D2 | Neon: add neighbouring lanes of singles
VPADD.I32 D0, D1, D2 | Neon: add neighbouring lanes
* VPADDL.S32 D0, D1 | Neon: add neighbouring lanes into wider lanes
VPMAX.F32 D0, D1, D2 | Neon: the greater of neighbouring lanes of singles
VPMAX.S32 D0, D1, D2 | Neon: the greater of neighbouring lanes
VPMIN.F32 D0, D1, D2 | Neon: the smaller of neighbouring lanes of singles
VPMIN.S32 D0, D1, D2 | Neon: the smaller of neighbouring lanes
* VQABS.S32 D0, D1 | Neon: saturating absolute value
* VQADD.S32 D0, D1, D2 | Neon: saturating add
VQDMLAL.S32 Q0, D1, D2 | Neon: saturating double multiply and add, wider
VQDMLSL.S32 Q0, D1, D2 | Neon: saturating double multiply and subtract, wider
* VQDMULH.S32 D0, D1, D2 | Neon: saturating double multiply, keeping the high half
VQDMULL.S32 Q0, D1, D2 | Neon: saturating double multiply, wider
VQMOVN.S32 D0, Q1 | Neon: narrow each lane, saturating
VQMOVUN.S32 D0, Q1 | Neon: narrow signed lanes to unsigned, saturating
* VQNEG.S32 D0, D1 | Neon: saturating change of sign
* VQRDMULH.S32 D0, D1, D2 | Neon: the same as VQDMULH, rounded
* VQRSHL.S32 D0, D1, D2 | Neon: saturating rounding shift, by the lanes of D2
VQRSHRN.S32 D0, Q1, #4 | Neon: saturating rounding shift right, narrowing
VQRSHRUN.S32 D0, Q1, #4 | Neon: the same, signed lanes to unsigned
* VQSHL.S32 D0, D1, D2 | Neon: saturating shift, by the lanes of D2
* VQSHL.S32 D0, D1, #4 | Neon: saturating shift left
* VQSHLU.S32 D0, D1, #4 | Neon: saturating shift left, signed lanes to unsigned
VQSHRN.S32 D0, Q1, #4 | Neon: saturating shift right, narrowing
VQSHRUN.S32 D0, Q1, #4 | Neon: the same, signed lanes to unsigned
* VQSUB.S32 D0, D1, D2 | Neon: saturating subtract
VRADDHN.I32 D0, Q1, Q2 | Neon: add, keeping the rounded high half of each lane
* VRECPE.F32 D0, D1 | Neon: estimate of 1 / x in each lane
* VRECPS.F32 D0, D1, D2 | Neon: a step towards a better 1 / x
* VREV16.8 D0, D1 | Neon: reverse the bytes of each halfword
* VREV32.8 D0, D1 | Neon: reverse the bytes of each word
* VREV64.8 D0, D1 | Neon: reverse the bytes of each doubleword
* VRHADD.S32 D0, D1, D2 | Neon: add each lane and halve, rounded
* VRSHL.S32 D0, D1, D2 | Neon: rounding shift, by the lanes of D2
* VRSHR.S32 D0, D1, #4 | Neon: rounding shift right
VRSHRN.I32 D0, Q1, #4 | Neon: rounding shift right, narrowing
* VRSQRTE.F32 D0, D1 | Neon: estimate of 1 / square root of x in each lane
* VRSQRTS.F32 D0, D1, D2 | Neon: a step towards a better 1 / square root
* VRSRA.S32 D0, D1, #4 | Neon: rounding shift right and add to D0
VRSUBHN.I32 D0, Q1, Q2 | Neon: subtract, keeping the rounded high half of each lane
* VSHL.I32 D0, D1, #4 | Neon: shift left
* VSHL.S32 D0, D1, D2 | Neon: shift, by the lanes of D2
VSHLL.S32 Q0, D1, #4 | Neon: shift left into lanes twice as wide
* VSHR.S32 D0, D1, #4 | Neon: shift right
VSHRN.I32 D0, Q1, #4 | Neon: shift right, narrowing
* VSLI.32 D0, D1, #4 | Neon: shift left and insert into D0
* VSRA.S32 D0, D1, #4 | Neon: shift right and add to D0
* VSRI.32 D0, D1, #4 | Neon: shift right and insert into D0
VST1.32 {D0, D1}, [R1] | Neon: store registers at address R1
VST1.32 {D0, D1}, [R1]! | Neon: the same, then R1 follows
VST1.32 {D0, D1}, [R1], R2 | Neon: the same, then R2 is added to R1
VST1.32 {D0[1]}, [R1] | Neon: store one lane
VST2.32 {D0, D1}, [R1] | Neon: store pairs, one from D0 and one from D1
VST3.32 {D0, D1, D2}, [R1] | Neon: store groups from three registers
VST4.32 {D0, D1, D2, D3}, [R1] | Neon: store groups from four registers
* VSUB.F32 D0, D1, D2 | Neon: subtract each lane of singles
* VSUB.I32 D0, D1, D2 | Neon: subtract each lane
VSUBHN.I32 D0, Q1, Q2 | Neon: subtract, keeping the high half of each lane
VSUBL.S32 Q0, D1, D2 | Neon: subtract into lanes twice as wide
VSUBW.S32 Q0, Q1, D2 | Neon: subtract narrow lanes from wide lanes
* VSWP D0, D1 | Neon: swap two registers
VTBL.8 D0, {D1}, D2 | Neon: look up the bytes of D2 in a table; 0 outside it
VTBX.8 D0, {D1}, D2 | Neon: the same; D0's byte stays outside it
* VTRN.32 D0, D1 | Neon: swap lanes crosswise between two registers
* VTST.32 D0, D1, D2 | Neon: all ones in a lane where D1 AND D2 is not 0
* VUZP.16 D0, D1 | Neon: separate the even and the odd lanes
* VZIP.16 D0, D1 | Neon: interleave the lanes of two registers
"""

_ALIASES = """
ADD R1, R2, #-1 | Becomes SUB R1, R2, #1
ADR R1, label | Address of a label nearby: ADD or SUB R1, PC, #offset
ADRL R1, label | Address of label in two instructions, for one further away
AND R1, R2, #0xFFFFFFF0 | Becomes BIC R1, R2, #0xF
ASR R1, R2, #2 | Arithmetic shift right, keeping the sign: MOV R1, R2, ASR #2
ASR R1, R2, R3 | Arithmetic shift right by R3: MOV R1, R2, ASR R3
CMP R1, #-1 | Becomes CMN R1, #1
CPY R1, R2 | Old name of MOV R1, R2
LDMEA R1!, {R2, R3} | Load from an empty ascending stack: LDMDB
LDMED R1!, {R2, R3} | Load from an empty descending stack: LDMIB
LDMFA R1!, {R2, R3} | Load from a full ascending stack: LDMDA
LDMFD R1!, {R2, R3} | Load from a full descending stack: LDMIA, as POP does
LDR R1, =100000 | Load any value: a MOV if it fits, else from a word near the code
LDR R1, =label | Load the address of label, from a word near the code
LDSB R1, [R2] | Old name of LDRSB R1, [R2]
LDSH R1, [R2] | Old name of LDRSH R1, [R2]
LSL R1, R2, #2 | Logical shift left: MOV R1, R2, LSL #2
LSL R1, R2, R3 | Logical shift left by R3: MOV R1, R2, LSL R3
LSR R1, R2, #2 | Logical shift right, with zeros: MOV R1, R2, LSR #2
LSR R1, R2, R3 | Logical shift right by R3: MOV R1, R2, LSR R3
MOV R1, #0x1234 | Becomes MOVW R1, #0x1234: a value MOV cannot encode
MOV R1, #0xFFFFFFFF | Becomes MVN R1, #0: the value inverted fits
NEG R1, R2 | Negate: RSB R1, R2, #0
NOP | No operation: nothing happens
POP {R1, R2} | Load registers from the stack: LDMIA SP!, {R1, R2}
POP {R4, PC} | Load registers and return from a function
PUSH {R1, R2} | Store registers on the stack: STMDB SP!, {R1, R2}
PUSH {R4, LR} | Store registers at the start of a function
RFE R1 | Return from exception: RFEIA R1
RFEEA R1 | Return from exception on an empty ascending stack: RFEDB
RFEED R1 | Return from exception on an empty descending stack: RFEIB
RFEFA R1 | Return from exception on a full ascending stack: RFEDA
RFEFD R1 | Return from exception on a full descending stack: RFEIA
ROR R1, R2, #8 | Rotate right: MOV R1, R2, ROR #8
ROR R1, R2, R3 | Rotate right by R3: MOV R1, R2, ROR R3
RRX R1, R2 | Rotate right through the carry by one: MOV R1, R2, RRX
SRS SP, #19 | Store LR and SPSR on the stack of mode 19: SRSIA SP, #19
SRSEA SP, #19 | Store on an empty ascending stack of mode 19: SRSIA
SRSED SP, #19 | Store on an empty descending stack of mode 19: SRSDA
SRSFA SP, #19 | Store on a full ascending stack of mode 19: SRSIB
SRSFD SP, #19 | Store on a full descending stack of mode 19: SRSDB
STMEA R1!, {R2, R3} | Store on an empty ascending stack: STMIA
STMED R1!, {R2, R3} | Store on an empty descending stack: STMDA
STMFA R1!, {R2, R3} | Store on a full ascending stack: STMIB
STMFD R1!, {R2, R3} | Store on a full descending stack: STMDB, as PUSH does
SWI #4 | Old name of SVC #4
VACLE.F32 D0, D1, D2 | Neon: VACGE with D1 and D2 changed round
VACLT.F32 D0, D1, D2 | Neon: VACGT with D1 and D2 changed round
VCLE.S32 D0, D1, D2 | Neon: VCGE with D1 and D2 changed round
VCLT.S32 D0, D1, D2 | Neon: VCGT with D1 and D2 changed round
VCVTZ.S32.F32 S1, S2 | Becomes VCVT.S32.F32 S1, S2, which rounds towards zero
VPOP {D1, D2} | Load registers from the stack: VLDMIA SP!, {D1, D2}
VPOP {S1, S2} | Load registers from the stack: VLDMIA SP!, {S1, S2}
VPUSH {D1, D2} | Store registers on the stack: VSTMDB SP!, {D1, D2}
VPUSH {S1, S2} | Store registers on the stack: VSTMDB SP!, {S1, S2}
"""

# The floating-point instructions under their old names.
_OLD_VFP = """
    FABSD FABSS FADDD FADDS FCMPD FCMPED FCMPES FCMPEZD FCMPEZS FCMPS FCMPZD
    FCMPZS FCONSTD FCONSTS FCPYD FCPYS FCVTDS FCVTSD FDIVD FDIVS FLDD FLDMDBD
    FLDMDBS FLDMDBX FLDMEAD FLDMEAS FLDMEAX FLDMFDD FLDMFDS FLDMFDX FLDMIAD
    FLDMIAS FLDMIAX FLDS FMACD FMACS FMDHR FMDLR FMDRR FMRDH FMRDL FMRRD FMRRS
    FMRS FMRX FMSCD FMSCS FMSR FMSRR FMSTAT FMULD FMULS FMXR FNEGD FNEGS FNMACD
    FNMACS FNMSCD FNMSCS FNMULD FNMULS FSHTOD FSHTOS FSITOD FSITOS FSLTOD FSLTOS
    FSQRTD FSQRTS FSTD FSTMDBD FSTMDBS FSTMDBX FSTMEAD FSTMEAS FSTMEAX FSTMFDD
    FSTMFDS FSTMFDX FSTMIAD FSTMIAS FSTMIAX FSTS FSUBD FSUBS FTOSHD FTOSHS FTOSID
    FTOSIS FTOSIZD FTOSIZS FTOSLD FTOSLS FTOUHD FTOUHS FTOUID FTOUIS FTOUIZD
    FTOUIZS FTOULD FTOULS FUHTOD FUHTOS FUITOD FUITOS FULTOD FULTOS"""

# Mnemonics of ares.tokens on neither list: (names, why).
LEFT_OUT = (
    (tuple(_OLD_VFP.split()),
     "The floating-point instructions under the names they had before the V names. Each does "
     "the same as a V instruction on the Basic list, and ARES takes them in old programs."),
)
# Forms of listed instructions that the lists do not show: (form, why).
FORMS_LEFT_OUT = (
    ("CMPP, CMNP, TSTP, TEQP", "old forms of the comparisons for User mode's flags"),
    ("VADDQ.I32 and the like", "Neon names with Q added: the Q registers already say it"),
    ("ADDUL and the like", "UL is another way to write the condition LO"),
    ("CMPS, CMNS, TSTS, TEQS", "S on a comparison is out of date: a comparison always sets the "
                               "flags"),
    ("MOVEQ R1, #0x1234 and the like", "the conditions of the alias are those of MOVW, on the "
                                       "Basic list"),
    ("LDRBEQ, LDMIAEQ and the like", "the assembler wants the condition before the ending, "
                                     "LDREQB and LDMEQIA, unless the program has "
                                     "`.syntax unified`"),
)


def _basic():
    rows = []
    for name, words, formula in (
            ("ADC", "Add with carry", "R2 + {} + C"), ("ADD", "Add", "R2 + {}"),
            ("AND", "Bitwise AND", "R2 AND {}"), ("BIC", "Bit clear", "R2 AND NOT {}"),
            ("EOR", "Exclusive OR", "R2 EOR {}"), ("ORR", "Bitwise OR", "R2 OR {}"),
            ("RSB", "Reverse subtract", "{} - R2"),
            ("RSC", "Reverse subtract with carry", "{} - R2 - NOT C"),
            ("SBC", "Subtract with carry", "R2 - {} - NOT C"), ("SUB", "Subtract", "R2 - {}")):
        rows += _three_operands(name, words, formula)
    for name, words, formula in (
            ("CMN", "Compare negative", "flags of R1 + {}"),
            ("CMP", "Compare", "flags of R1 - {}"), ("MOV", "Move", "R1 = {}"),
            ("MVN", "Move inverted", "R1 = NOT {}"), ("TEQ", "Test equal", "flags of R1 EOR {}"),
            ("TST", "Test bits", "flags of R1 AND {}")):
        rows += _two_operands(name, words, formula)
    for name, words in (("LDR", "Load a word"), ("STR", "Store a word"), ("LDRB", "Load a byte"),
                        ("STRB", "Store a byte")):
        forms = _WORD_FORMS[:-1] if name.startswith("STR") else _WORD_FORMS
        rows += _load_store(name, words, "R1", forms)
    for name, words in (("LDRH", "Load a halfword"), ("STRH", "Store a halfword"),
                        ("LDRSB", "Load a signed byte"),
                        ("LDRSH", "Load a signed halfword")):
        forms = _HALF_FORMS[:-1] if name.startswith("STR") else _HALF_FORMS
        rows += _load_store(name, words, "R1", forms)
    for name, words in (("LDRT", "Load a word"), ("LDRBT", "Load a byte"),
                        ("LDRHT", "Load a halfword"),
                        ("LDRSBT", "Load a signed byte"),
                        ("LDRSHT", "Load a signed halfword"),
                        ("STRT", "Store a word"), ("STRBT", "Store a byte"),
                        ("STRHT", "Store a halfword")):
        rows += _load_store(name, words, "R1", _USER_FORMS)
    rows += _multiple("LDM", "Load registers") + _multiple("STM", "Store registers")
    rows += _parallel()[0]
    for table in (_INTEGER, _MULTIPLY, _LOAD_STORE, _SYSTEM, _FLOAT):
        rows += _table(table)
    rows += _table(_NEON, conditional=False)
    return rows


def _sorted(rows):
    return tuple(sorted(rows, key=lambda row: row.example))


BASIC = _sorted(_basic())
EXTENDED = _sorted(_table(_ALIASES) + _parallel()[1])


def left_out_names():
    """Every mnemonic of LEFT_OUT."""
    return {name for names, why in LEFT_OUT for name in names}


def listed_bases():
    """The instructions of ares.tokens with a row on one of the lists."""
    return {row.base for row in BASIC + EXTENDED}


def token_bases():
    """Every instruction of ares.tokens."""
    return {mnemonic_base(form) for form in mnemonic_forms()}
