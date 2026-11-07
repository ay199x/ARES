# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""ARM instruction formats and classes, as DynARMic classifies them.

DynARMic (GLSVLSI 2026), a dynamic ARM instruction counting tool, sorts each
executed ARM instruction into an encoding format (data processing with a
register or an immediate operand, load/store with an immediate or a register
offset, branch, multiply, load/store multiple, supervisor call and others)
and a class, the category the Dynamic Instruction Counter shows (ALU,
Branch, Memory (Byte Access), Memory (Reg-to-Reg), Conditional Load &
Others). Its two rules, classify_format_safe() and classify_insn(), are used
here unchanged (with its author's permission), on Capstone's ARM decoding with
details and Capstone's default register names: R9 is "sb" and R12 "ip", which
the load/store register-offset rule depends on (an offset in R9-R12, SP or LR
counts as an immediate offset there). These are not the options of ARES's own
disassembly (ares.disasm).

A word Capstone cannot decode is classified as both rules classify an
instruction they know nothing about: data processing (register) and ALU.
DynARMic itself stops a program there; ARES runs whatever the CPU runs.
"""

import re
import struct
from types import SimpleNamespace

from capstone import CS_ARCH_ARM, CS_GRP_CALL, CS_GRP_INT, CS_GRP_JUMP, CS_GRP_RET, CS_MODE_ARM, Cs

# The formats and classes, in the order the Dynamic Instruction Counter shows them.
FORMATS = ("fmt_dp_reg", "fmt_dp_imm", "fmt_ls_imm", "fmt_ls_reg", "fmt_branch", "fmt_mul",
           "fmt_lsm", "fmt_svc")
CLASSES = ("alu", "branch", "memory", "reg_transfer", "cond_load_other")

COND_CODES = ['eq', 'ne', 'cs', 'hs', 'cc', 'lo', 'mi', 'pl', 'vs', 'vc', 'hi', 'ls', 'ge', 'lt',
              'gt', 'le']
_REGISTER_OFFSET = re.compile(r'\[\s*\w+\s*,\s*-?r\w+')
_NOTHING = SimpleNamespace(mnemonic="", op_str="", groups=[])     # a word Capstone cannot decode
_disassembler = None
_cache = {}                     # instruction word -> (format index, class index)


def classify_insn(insn):
    """DynARMic's class of a Capstone instruction: 'alu', 'branch', 'memory' (byte
    accesses), 'reg_transfer' or 'cond_load_other'."""
    mn = insn.mnemonic.lower()
    g = insn.groups
    if any(x in g for x in (CS_GRP_JUMP, CS_GRP_CALL, CS_GRP_RET)):
        return 'branch'
    is_cond_load = False
    if mn.startswith('ldr') or mn.startswith('str'):
        for cc in COND_CODES:
            if cc != 'al' and mn.endswith(cc):
                is_cond_load = True
                break
    if is_cond_load or CS_GRP_INT in g or mn in ('svc', 'swi', 'bkpt'):
        return 'cond_load_other'
    if mn in ('ldrb', 'strb', 'ldrsb', 'ldrexb', 'strexb'):
        return 'memory'
    if mn.startswith('ldr') or mn.startswith('str') or mn in ('push', 'pop', 'ldm', 'stm', 'ldmia',
                                                              'stmia'):
        return 'reg_transfer'
    return 'alu'


def classify_format_safe(insn):
    """DynARMic's format of a Capstone instruction (one of FORMATS)."""
    mn = (insn.mnemonic or "").lower()
    ops = (insn.op_str or "").lower()
    if mn in ('svc', 'swi', 'bkpt'):
        return 'fmt_svc'
    if mn in ('cbz', 'cbnz'):
        return 'fmt_branch'
    if (mn.startswith('b') and mn not in ('bic', 'bfi', 'bfc', 'bkpt') and not mn.startswith('bic')
            and not mn.startswith('bfi') and not mn.startswith('bfc')):
        return 'fmt_branch'
    if mn.startswith(('mul', 'mla', 'mls', 'smul', 'umul', 'smlal', 'umlal', 'smmul', 'smmla')):
        return 'fmt_mul'
    if mn.startswith(('push', 'pop', 'ldm', 'stm')):
        return 'fmt_lsm'
    if mn.startswith(('ldr', 'str')):
        if _REGISTER_OFFSET.search(ops):
            return 'fmt_ls_reg'
        return 'fmt_ls_imm'
    if '#' in ops:
        return 'fmt_dp_imm'
    return 'fmt_dp_reg'


def classify(word):
    """(format index, class index) of an ARM instruction word, in FORMATS and CLASSES.

    Neither rule depends on the instruction's address, so the result is kept
    for each word.
    """
    found = _cache.get(word)
    if found is None:
        global _disassembler
        if _disassembler is None:
            _disassembler = Cs(CS_ARCH_ARM, CS_MODE_ARM)
            _disassembler.detail = True
        insn = next(_disassembler.disasm(struct.pack("<I", word), 0), None) or _NOTHING
        found = _cache[word] = (FORMATS.index(classify_format_safe(insn)),
                                CLASSES.index(classify_insn(insn)))
    return found


def tally(data):
    """(formats, classes) of the ARM instructions in data: how many of them have each
    format and each class, as tuples in the order of FORMATS and CLASSES."""
    formats, classes = [0] * len(FORMATS), [0] * len(CLASSES)
    for (word,) in struct.iter_unpack("<I", data[:len(data) // 4 * 4]):
        kind, group = classify(word)
        formats[kind] += 1
        classes[group] += 1
    return tuple(formats), tuple(classes)
