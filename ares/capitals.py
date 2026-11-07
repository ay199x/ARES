# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The capital-letters rule: instructions and registers in capitals, directives in lowercase.

Instruction mnemonics (with condition codes, suffixes and qualifiers),
register names and shift names are written in capitals; directives in
lowercase. Labels, symbols, numbers, comments, strings and character
constants may be written in any case and are never changed.
"""

from dataclasses import dataclass

from .tokens import (DIRECTIVE, LABEL_DEF, MNEMONIC, PUNCT, REGISTER, SHIFT, SYMBOL,
                     register_name, tokenize)

# Directives whose first operand defines a symbol.
_DEFINING_DIRECTIVES = frozenset((".set", ".equ", ".equiv", ".eqv", ".comm", ".lcomm"))
_ALIAS_DIRECTIVES = frozenset((".req", ".dn", ".qn"))


@dataclass(frozen=True)
class Offence:
    """A line that breaks the rule, with the line as it should be written."""
    line: int
    corrected: str          # without leading and trailing whitespace
    instructions: bool      # a mnemonic, register or shift is not in capitals
    directives: bool        # a directive is not in lowercase

    @property
    def message(self):
        if self.instructions and self.directives:
            rule = "write instructions and registers in capitals and directives in lowercase"
        elif self.instructions:
            rule = "write instructions and registers in capitals"
        else:
            rule = "write directives in lowercase"
        return f"{rule}: {self.corrected}"


def _defined_names(lines, token_lines):
    """Names the program defines: labels, symbols and register aliases.

    A symbol may be called like a register (``s1 = 4``, then ``MOV R0, s1``
    in unified syntax); such a name used as an operand is left alone, since
    changing its case would make it a different symbol.
    """
    names = set()
    for line, tokens in zip(lines, token_lines):
        for i, token in enumerate(tokens):
            text = line[token.start:token.end]
            if token.kind == LABEL_DEF:
                names.add(text.rstrip(":").rstrip())
            elif token.kind == SYMBOL and i + 1 < len(tokens):
                after = tokens[i + 1]
                word = line[after.start:after.end]
                if (after.kind == PUNCT and word == "=") or (
                        after.kind == DIRECTIVE and word.lower() in _ALIAS_DIRECTIVES):
                    names.add(text)
            elif (token.kind == DIRECTIVE and text.lower() in _DEFINING_DIRECTIVES
                  and i + 1 < len(tokens) and tokens[i + 1].kind == SYMBOL):
                after = tokens[i + 1]
                names.add(line[after.start:after.end])
    return names


def _corrections(text):
    """Yield (line number, corrected line, instructions wrong, directives wrong)."""
    lines = text.split("\n")
    token_lines = tokenize(text)
    defined = _defined_names(lines, token_lines)
    for number, (line, tokens) in enumerate(zip(lines, token_lines), 1):
        pieces = []
        done = 0
        instructions = directives = False
        for token in tokens:
            kind = token.kind
            if kind not in (MNEMONIC, REGISTER, SHIFT, DIRECTIVE):
                continue
            word = line[token.start:token.end]
            if kind == DIRECTIVE:
                fixed = word.lower()
            elif kind == MNEMONIC:
                fixed = word.upper()
            elif word in defined:       # a label called like a register
                continue
            else:
                fixed = register_name(word)
            if fixed == word:
                continue
            if kind == DIRECTIVE:
                directives = True
            else:
                instructions = True
            pieces.append(line[done:token.start])
            pieces.append(fixed)
            done = token.end
        if pieces:
            pieces.append(line[done:])
            yield number, "".join(pieces), instructions, directives


def offences(text):
    """Every line of text that breaks the rule."""
    return [Offence(number, corrected.strip(), instructions, directives)
            for number, corrected, instructions, directives in _corrections(text)]


def check(text):
    """``(line number, corrected line)`` for every line that breaks the rule."""
    return [(o.line, o.corrected) for o in offences(text)]


def capitalize(text):
    """Text with the rule applied to every line; nothing else changes."""
    lines = text.split("\n")
    for number, corrected, _, _ in _corrections(text):
        lines[number - 1] = corrected
    return "\n".join(lines)
