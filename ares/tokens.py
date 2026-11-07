# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Split ARM assembly source into tokens for highlighting and the capitals check.

The rules follow the GNU assembler for ARM: ``@`` and ``//`` start a comment
that runs to the end of the line, and so does ``#`` at the start of a
statement; ``/* */`` comments may span lines; ``;`` separates statements.
A statement is any number of label definitions, then a directive or an
instruction, then its operands. Register names count only where the
instruction reads a register: a branch target, the label in
``LDR R0, label`` and a name after ``#`` are symbols, even when called
``s1`` or ``lr``.
"""

import re
from itertools import product
from typing import NamedTuple

MNEMONIC = "mnemonic"
REGISTER = "register"
SHIFT = "shift"
NUMBER = "number"
LABEL_DEF = "label_def"
SYMBOL = "symbol"
DIRECTIVE = "directive"
COMMENT = "comment"
STRING = "string"
CHAR = "char"
PUNCT = "punct"


class Token(NamedTuple):
    """One piece of a line: its kind and columns (end exclusive)."""
    kind: str
    start: int
    end: int


# Instruction mnemonics ----------------------------------------------------

# UL is the assembler's other name for LO.
CONDITIONS = ("EQ", "NE", "CS", "HS", "CC", "LO", "UL", "MI", "PL", "VS", "VC",
              "HI", "LS", "GE", "LT", "GT", "LE", "AL")

# Conditional, with an S suffix in unified order (ADDSEQ) or divided order (ADDEQS).
_FLAG_SETTING = """
    ADC ADD AND ASR BIC CMN CMP EOR LSL LSR MLA MOV MUL MVN NEG ORR ROR RRX RSB
    RSC SBC SMLAL SMULL SUB TEQ TST UMLAL UMULL"""

# Conditional, with endings that come after the condition in divided syntax
# (LDREQB, STMEQFD) and before it in unified syntax (LDRBEQ, STMFDEQ).
_ENDINGS = {
    "ADR": "L",
    "LDC": "L",
    "LDM": "IA IB DA DB FD FA ED EA",
    "LDR": "B BT D H HT SB SBT SH SHT T",
    "LDS": "B H",       # the old names of LDRSB and LDRSH; LDS alone is not one
    "STC": "L",
    "STM": "IA IB DA DB FD FA ED EA",
    "STR": "B BT D H HT T",
    "SWP": "B",
}

# Old forms whose P ending only follows the condition: CMPP, CMPEQP.
_P_ENDING = "CMN CMP TEQ TST"

# Conditional: B, BEQ. The F... names are the older VFP mnemonics.
_CONDITIONAL = """
    B BL BLX BX BXJ CLZ CPY DBG MLS MOVT MOVW MRS MSR NOP POP PUSH SEV SMC SVC
    SWI UDF WFE WFI YIELD
    LDREX LDREXB LDREXD LDREXH STREX STREXB STREXD STREXH
    BFC BFI PKHBT PKHTB RBIT REV REV16 REVSH SBFX SEL SSAT SSAT16 UBFX USAT USAT16
    SXTAB SXTAB16 SXTAH SXTB SXTB16 SXTH UXTAB UXTAB16 UXTAH UXTB UXTB16 UXTH
    QADD QDADD QDSUB QSUB
    SMLABB SMLABT SMLATB SMLATT SMLAWB SMLAWT SMULBB SMULBT SMULTB SMULTT SMULWB
    SMULWT SMLALBB SMLALBT SMLALTB SMLALTT SMLAD SMLADX SMLALD SMLALDX SMLSD
    SMLSDX SMLSLD SMLSLDX SMMLA SMMLAR SMMLS SMMLSR SMMUL SMMULR SMUAD SMUADX
    SMUSD SMUSDX UMAAL USAD8 USADA8
    CDP MCR MCRR MRC MRRC
    VABS VADD VCMP VCMPE VCVT VCVTB VCVTR VCVTT VCVTZ VDIV VDUP VLDM VLDMDB
    VLDMIA VLDR VMLA VMLS VMOV VMRS VMSR VMUL VNEG VNMLA VNMLS VNMUL VPOP VPUSH
    VSQRT VSTM VSTMDB VSTMIA VSTR VSUB
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

# Parallel add and subtract, conditional: SADD16, UQSUB8, SHASX ...
_PARALLEL = ("S Q SH U UQ UH", "ADD16 ADD8 ASX SAX SUB16 SUB8 ADDSUBX SUBADDX")

# Never conditional in ARM state, including every Neon-only instruction.
_UNCONDITIONAL = """
    BKPT CLREX CPS CPSID CPSIE CSDB DMB DSB HLT ISB PLD PLDW PLI PSSBB SETEND
    SSBB
    RFE RFEDA RFEDB RFEEA RFEED RFEFA RFEFD RFEIA RFEIB
    SRS SRSDA SRSDB SRSEA SRSED SRSFA SRSFD SRSIA SRSIB
    CDP2 LDC2 LDC2L MCR2 MCRR2 MRC2 MRRC2 STC2 STC2L
    VABA VABAL VABD VABDL VACGE VACGT VACLE VACLT VADDHN VADDL VADDW VAND VBIC
    VBIF VBIT VBSL VCEQ VCGE VCGT VCLE VCLS VCLT VCLZ VCNT VEOR VEXT VHADD VHSUB
    VLD1 VLD2 VLD3 VLD4 VMAX VMIN VMLAL VMLSL VMOVL VMOVN VMULL VMVN VORN VORR
    VPADAL VPADD VPADDL VPMAX VPMIN VQABS VQADD VQDMLAL VQDMLSL VQDMULH VQDMULL
    VQMOVN VQMOVUN VQNEG VQRDMULH VQRSHL VQRSHRN VQRSHRUN VQSHL VQSHLU VQSHRN
    VQSHRUN VQSUB VRADDHN VRECPE VRECPS VREV16 VREV32 VREV64 VRHADD VRSHL VRSHR
    VRSHRN VRSQRTE VRSQRTS VRSRA VRSUBHN VSHL VSHLL VSHR VSHRN VSLI VSRA VSRI
    VST1 VST2 VST3 VST4 VSUBHN VSUBL VSUBW VSWP VTBL VTBX VTRN VTST VUZP VZIP"""

# Neon instructions that also have a Q form for quad registers only (VADDQ).
_NEON_Q = """
    VABA VABD VABS VACGE VACGT VACLE VACLT VADD VAND VBIC VBIF VBIT VBSL VCEQ
    VCGE VCGT VCLE VCLS VCLT VCLZ VCNT VCVT VDUP VEOR VEXT VHADD VHSUB VMAX VMIN
    VMLA VMLS VMOV VMUL VMVN VNEG VORN VORR VPADAL VPADDL VQABS VQADD VQDMULH
    VQNEG VQRDMULH VQRSHL VQSHL VQSHLU VQSUB VRECPE VRECPS VREV16 VREV32 VREV64
    VRHADD VRSHL VRSHR VRSQRTE VRSQRTS VRSRA VSHL VSHR VSLI VSRA VSRI VSUB VSWP
    VTRN VTST VUZP VZIP"""

_WIDTHS = frozenset(("W", "N"))
# F alone means F32 and D means F64.
_TYPES = frozenset("""
    I8 I16 I32 I64 S8 S16 S32 S64 U8 U16 U32 U64 F16 F32 F64 P8 P16 P64
    8 16 32 64 F D""".split())


def _build_forms():
    forms = {}

    def add(base, before, after=""):
        forms[before + after] = base
        for cond in CONDITIONS:
            forms[before + cond + after] = base

    for base in _FLAG_SETTING.split():
        add(base, base)
        add(base, base + "S")
        add(base, base, "S")
    for base, endings in _ENDINGS.items():
        if base != "LDS":
            add(base, base)
        for ending in endings.split():
            add(base, base + ending)
            add(base, base, ending)
    for base in _P_ENDING.split():
        add(base, base, "P")
    for base in _CONDITIONAL.split():
        add(base, base)
    prefixes, operations = _PARALLEL
    for prefix, operation in product(prefixes.split(), operations.split()):
        add(prefix + operation, prefix + operation)
    for base in _UNCONDITIONAL.split():
        forms[base] = base
    for base in _NEON_Q.split():
        forms[base + "Q"] = base
    add("VDUP", "VDUPQ")        # from a core register it may be conditional: VDUPQEQ
    for count in range(4):
        for then_else in product("TE", repeat=count):
            forms["IT" + "".join(then_else)] = "IT"
    return forms


_FORMS = _build_forms()


def mnemonic_forms():
    """Every recognised mnemonic without qualifiers, in capitals: ADD, ADDSEQ, LDREQB ..."""
    return sorted(_FORMS)


def mnemonic_base(word):
    """The instruction a mnemonic belongs to (``addeqs`` -> ``ADD``), or None.

    Any case is accepted. Qualifiers follow a dot: a width (``.W``, ``.N``) on
    any instruction, or one or two data types on V instructions
    (``VADD.F32``, ``VCVT.F32.S32``).
    """
    core, dot, qualifiers = word.upper().partition(".")
    base = _FORMS.get(core)
    if base is None or not dot:
        return base
    parts = qualifiers.split(".")
    if len(parts) == 1 and parts[0] in _WIDTHS:
        return base
    if core[0] == "V" and len(parts) <= 2 and all(p in _TYPES for p in parts):
        return base
    return None


def is_mnemonic(word):
    """True when word is an ARMv7-A instruction mnemonic, in any case."""
    return mnemonic_base(word) is not None


# Registers -----------------------------------------------------------------

_CORE_REGISTERS = frozenset(
    [f"R{n}" for n in range(16)] + "SP LR PC FP IP SB SL".split()
    + [f"A{n}" for n in range(1, 5)] + [f"V{n}" for n in range(1, 9)])
_VECTOR_REGISTERS = frozenset(
    [f"S{n}" for n in range(32)] + [f"D{n}" for n in range(32)]
    + [f"Q{n}" for n in range(16)])
REGISTERS = _CORE_REGISTERS | _VECTOR_REGISTERS | frozenset(
    "CPSR SPSR APSR FPSCR FPEXC FPSID FPINST FPINST2 MVFR0 MVFR1".split())
SHIFTS = frozenset("LSL LSR ASR ROR RRX ASL".split())

# A status register with fields, e.g. CPSR_fc or APSR_nzcv.
_PSR_FIELDS = re.compile(r"(?:CPSR|SPSR|APSR)_[A-Z]+", re.IGNORECASE)
_COPROCESSOR_REGISTER = re.compile(r"(?:[PC]|CR)(?:1[0-5]|[0-9])", re.IGNORECASE)


def register_name(word):
    """The capitalised form of a register name: ``sp`` -> ``SP``, ``d0.f32`` -> ``D0.F32``.

    Field suffixes stay as written, because the assembler accepts them only in
    lowercase: ``cpsr_fc`` -> ``CPSR_fc``.
    """
    base, underscore, fields = word.partition("_")
    return base.upper() + underscore + fields


# Tokenizing ----------------------------------------------------------------

_NUMBER = r"(?:0[xX][0-9A-Fa-f]+|0[bB][01]+|\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
_NAME_PART = r"\\(?:\(\)|@|\w)"           # macro arguments: \arg, \(), \@
# The assembler takes every character above 0x7F as a letter: año, étiquette.
_NAME = (rf"(?:[A-Za-z_.$\x80-\U0010FFFF]|{_NAME_PART})"
         rf"(?:[\w.$\x80-\U0010FFFF]|{_NAME_PART})*")
_CHAR = r"'(?:\\(?:x[0-9A-Fa-f]+|[0-7]{1,3}|.)|[^\\])'?"
_STRING = r'"(?:[^"\\]|\\.?)*"?'

_LEX = re.compile(rf"""
    (?P<space>\s+)
  | (?P<block>/\*)
  | (?P<comment>@|//)
  | (?P<string>{_STRING})
  | (?P<char>{_CHAR})
  | (?P<hash>\#(?:[-+]?{_NUMBER}(?![\w$]))?)
  | (?P<number>{_NUMBER}(?![\w$]))
  | (?P<local>\d+[bBfF](?![\w$]))
  | (?P<dollar>\d+\$(?![\w$]))
  | (?P<othernumber>\d[\w.$]*)
  | (?P<name>{_NAME})
  | (?P<punct>.)
""", re.VERBOSE | re.ASCII)

# A whole literal-pool operand: =0x3FFFFFF8, =covid_genome, =label + 4.
_LITERAL = re.compile(rf"""
    =(?:[^\s@;/'"] | /(?![/*]) | {_CHAR} | {_STRING}
       | \s+(?=[^\s@;/] | /(?![/*])))*
""", re.VERBOSE | re.ASCII)

_LABEL_COLON = re.compile(r"[ \t]*:")
_DEFINITION = re.compile(r"[ \t]*=")
_ALIAS = re.compile(r"[ \t]+(\.(?:req|dn|qn))(?![\w.$])", re.IGNORECASE)
_MORE_OPERANDS = re.compile(r"[^,;@/]*,")
_MACRO_DIRECTIVE = re.compile(r"\.macro\b", re.IGNORECASE)

# How the operands of a statement are read: bit flags.
_EXPRESSION = 0     # directive, symbol definition, macro call, branch target: no registers
_REGISTERS = 1      # registers, shifts and =literals
_COPROC = 2         # also p0-p15, c0-c15 and cr0-cr15
_ADDRESS = 4        # a last operand outside [ ] is a label: LDR R0, label
_CORE = 8           # core registers only: BLX LR, but BLX label

_MODES = {
    "B": _EXPRESSION,
    "BL": _EXPRESSION,
    "BLX": _REGISTERS | _CORE,
    **dict.fromkeys("ADR LDR LDS STR VLDR VSTR FLDD FLDS FSTD FSTS PLD PLDW PLI".split(),
                    _REGISTERS | _ADDRESS),
    **dict.fromkeys("CDP CDP2 MCR MCR2 MCRR MCRR2 MRC MRC2 MRRC MRRC2".split(),
                    _REGISTERS | _COPROC),
    **dict.fromkeys("LDC LDC2 LDC2L STC STC2 STC2L".split(), _REGISTERS | _COPROC | _ADDRESS),
}


def _operand_kind(word, mode):
    upper = word.upper()
    if mode & _CORE:
        return REGISTER if upper in _CORE_REGISTERS else SYMBOL
    if upper in REGISTERS or _PSR_FIELDS.fullmatch(word):
        return REGISTER
    if upper in SHIFTS:
        return SHIFT
    if mode & _COPROC and _COPROCESSOR_REGISTER.fullmatch(word):
        return REGISTER
    register, dot, data_type = upper.partition(".")
    if dot and register in _VECTOR_REGISTERS and data_type in _TYPES:
        return REGISTER                 # a Neon register with a type: d0.f32
    return SYMBOL


def tokenize_line(text, in_comment=False, macros=frozenset()):
    """Split one line into tokens.

    ``in_comment`` is false when the line starts outside a ``/* */`` comment.
    Otherwise it is the ``in_comment_after`` of the line before, a true value
    that also remembers the statement the comment interrupted (``True`` alone
    means none). ``macros`` holds the names, in capitals, of the macros
    defined so far: a statement that calls one is not an instruction.
    Returns ``(tokens, in_comment_after)``; the tokens cover every non-blank
    piece of the line.
    """
    tokens = []
    append = tokens.append
    line = text.rstrip()
    end = len(line)
    pos = 0
    head, mode, immediate = True, _EXPRESSION, False    # at the start of a statement
    if in_comment:
        if in_comment is not True:
            head, mode, immediate = in_comment
        start = end - len(line.lstrip())
        close = line.find("*/")
        if close < 0:
            if start < end:
                append(Token(COMMENT, start, end))
            return tokens, in_comment
        pos = close + 2
        append(Token(COMMENT, start, pos))

    match = _LEX.match
    while pos < end:
        m = match(line, pos)
        group = m.lastgroup
        start, pos = m.span()
        if group == "space":
            continue
        if group == "comment" or (group == "hash" and head):
            append(Token(COMMENT, start, end))
            break
        if group == "block":
            close = line.find("*/", pos)
            if close < 0:
                append(Token(COMMENT, start, end))
                # The assembler reads the comment as a space: the statement goes on.
                return tokens, (head, mode, immediate)
            pos = close + 2
            append(Token(COMMENT, start, pos))
            continue

        if head:
            if group in ("name", "number", "dollar"):
                colon = _LABEL_COLON.match(line, pos)
                if colon:
                    pos = colon.end()
                    append(Token(LABEL_DEF, start, pos))
                    continue
            head = False
            if group == "name":
                if _DEFINITION.match(line, pos):
                    append(Token(SYMBOL, start, pos))
                    continue
                alias = _ALIAS.match(line, pos)
                if alias:
                    append(Token(SYMBOL, start, pos))
                    append(Token(DIRECTIVE, alias.start(1), alias.end(1)))
                    pos = alias.end()
                    mode = _REGISTERS
                    continue
                word = m.group()
                if word[0] == "." and len(word) > 1:
                    append(Token(DIRECTIVE, start, pos))
                    continue
                base = None if macros and word.upper() in macros else mnemonic_base(word)
                if base is None:
                    append(Token(SYMBOL, start, pos))
                else:
                    mode = _MODES.get(base, _REGISTERS)
                    append(Token(MNEMONIC, start, pos))
                continue

        if group == "name":
            if mode == _EXPRESSION or immediate:
                kind = SYMBOL
            else:
                kind = _operand_kind(m.group(), mode)
                if kind != SYMBOL and mode & _ADDRESS and not _MORE_OPERANDS.match(line, pos):
                    kind = SYMBOL       # LDR R0, s1 loads from the label s1
        elif group == "hash":
            kind = NUMBER
            immediate = True            # #s1 is the value of the symbol s1
        elif group in ("number", "othernumber"):
            kind = NUMBER
        elif group in ("local", "dollar"):
            kind = SYMBOL
        elif group == "string":
            kind = STRING
        elif group == "char":
            kind = CHAR
        else:
            kind = PUNCT
            char = line[start]
            if char == ";":
                head, mode, immediate = True, _EXPRESSION, False
            elif char in ",]}":
                immediate = False
            elif char == "[":
                mode &= ~_ADDRESS
            elif char == "=" and mode:
                pos = _LITERAL.match(line, start).end()
                kind = NUMBER
        append(Token(kind, start, pos))
    return tokens, False


def _macro_names(line, tokens):
    """The names, in capitals, that ``.macro`` directives on a tokenized line define."""
    words = [line[t.start:t.end] for t in tokens]
    return {words[i + 1].upper() for i, t in enumerate(tokens[:-1])
            if t.kind == DIRECTIVE and words[i].lower() == ".macro"
            and tokens[i + 1].kind == SYMBOL}


def tokenize(text):
    """Tokens for every line of text (split at ``\\n``), one list per line.

    A macro counts from its ``.macro`` line on, as in the assembler.
    """
    result = []
    in_comment = False
    macros = set()
    for line in text.split("\n"):
        tokens, in_comment = tokenize_line(line, in_comment, macros)
        result.append(tokens)
        if _MACRO_DIRECTIVE.search(line):
            macros |= _macro_names(line, tokens)
    return result
