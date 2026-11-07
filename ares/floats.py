# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Single (32-bit) and double (64-bit) floating-point values: bits, numbers and text.

Values are written as Java's Float.toString and Double.toString write them:
the shortest decimal that reads back as the same value, plain from 0.001 up
to 10,000,000 and with an exponent outside that range (``1.5``, ``0.1``,
``1.0E-5``, ``3.4028235E38``), and ``NaN``, ``Infinity``, ``-0.0``.

Typed numbers are rounded to the nearest value, ties to the even one, as the
VFP rounds; a number too large becomes infinity.
"""

import re
import struct
from decimal import ROUND_CEILING, ROUND_FLOOR, Context, Decimal

SINGLE_SIGN = 1 << 31
SINGLE_INFINITY = 0x7F800000
SINGLE_NAN = 0x7FC00000             # the default NaN
DOUBLE_SIGN = 1 << 63
DOUBLE_INFINITY = 0x7FF0000000000000
DOUBLE_NAN = 0x7FF8000000000000

_SINGLE_TOP = 2.0 ** 128            # where the next single after the largest would be
# Each digit can match in one way only, so a long text that is no number fails fast.
_NUMBER = re.compile(r"([+-]?)((?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
                     r"|inf|infinity|nan)", re.ASCII | re.IGNORECASE)
_EXACT = Context(prec=2000)         # more digits than any double has: arithmetic is exact
_FLOOR = {n: Context(prec=n, rounding=ROUND_FLOOR) for n in range(1, 18)}
_CEILING = {n: Context(prec=n, rounding=ROUND_CEILING) for n in range(1, 18)}


def single(bits):
    """The value of a single as a Python float (exactly)."""
    return struct.unpack("<f", struct.pack("<I", bits & 0xFFFFFFFF))[0]


def double(bits):
    """The value of a double as a Python float."""
    return struct.unpack("<d", struct.pack("<Q", bits & 0xFFFFFFFFFFFFFFFF))[0]


def single_bits(value):
    """The bits of the single nearest a Python float (ties to even); too large: infinity."""
    try:
        return struct.unpack("<I", struct.pack("<f", value))[0]
    except OverflowError:
        return SINGLE_INFINITY | (SINGLE_SIGN if value < 0 else 0)


def double_bits(value):
    """The bits of a Python float."""
    return struct.unpack("<Q", struct.pack("<d", value))[0]


# Typed numbers ------------------------------------------------------------------

def parse_single(text):
    """The bits of the single nearest a typed number; None when text is not a number.

    A number is decimal, with an optional sign, point and exponent (``-1.5``,
    ``2e-3``, ``.5``), or ``inf``, ``infinity`` or ``nan`` in any case.
    """
    number = _number(text)
    if number is None:
        return None
    sign, digits = number
    if digits == "nan":
        return sign << 31 | SINGLE_NAN
    if digits.startswith("inf"):
        return sign << 31 | SINGLE_INFINITY
    return sign << 31 | _nearest_single(digits)


def parse_double(text):
    """The bits of the double nearest a typed number; None when text is not a number.

    Numbers are written as for parse_single.
    """
    number = _number(text)
    if number is None:
        return None
    sign, digits = number
    if digits == "nan":
        return sign << 63 | DOUBLE_NAN
    return sign << 63 | double_bits(float(digits))  # nearest, ties to even; too large: inf


def _number(text):
    """(1 for a minus sign else 0, the rest in lowercase) of a typed number, or None."""
    match = _NUMBER.fullmatch(text.strip())
    if match is None:
        return None
    return int(match[1] == "-"), match[2].lower()


def _nearest_single(digits):
    """The bits of the single nearest the decimal number digits (no sign).

    The nearest double is rounded to the nearest single. That rounds twice,
    which goes wrong only when the double lies exactly halfway between two
    singles: then the decimal itself decides.
    """
    value = float(digits)
    bits = single_bits(value)
    if single(bits) == value:
        return bits
    below, above = (bits, bits + 1) if single(bits) < value else (bits - 1, bits)
    top = _SINGLE_TOP if above == SINGLE_INFINITY else single(above)
    # Both differences are exact: the three values lie within a factor of 2.
    if value - single(below) != top - value:
        return bits
    exact, halfway = Decimal(digits), Decimal(value)
    if exact == halfway:
        return bits                 # a real tie: single_bits chose the even one
    return above if exact > halfway else below


# Text ----------------------------------------------------------------------------

def format_single(bits):
    """A single as text: ``1.5``, ``1.0E-5``, ``NaN``, ``-Infinity`` ..."""
    bits &= 0xFFFFFFFF
    special = _special(bits & ~SINGLE_SIGN, SINGLE_INFINITY, bits >> 31)
    if special is not None:
        return special
    return "-" * (bits >> 31) + _shortest(single(bits & ~SINGLE_SIGN), bits & ~SINGLE_SIGN, 9,
                                          _nearest_single)


def format_double(bits):
    """A double as text, written as format_single writes a single."""
    bits &= 0xFFFFFFFFFFFFFFFF
    special = _special(bits & ~DOUBLE_SIGN, DOUBLE_INFINITY, bits >> 63)
    if special is not None:
        return special
    value = double(bits & ~DOUBLE_SIGN)
    # Python's repr is a shortest decimal too: no decimal with fewer digits reads back.
    least = len(Decimal(repr(value)).normalize(_EXACT).as_tuple().digits)
    return "-" * (bits >> 63) + _shortest(value, bits & ~DOUBLE_SIGN, 17,
                                          lambda text: double_bits(float(text)), least)


def _special(magnitude, infinity, negative):
    if magnitude > infinity:
        return "NaN"
    if magnitude == infinity:
        return "-Infinity" if negative else "Infinity"
    if magnitude == 0:
        return "-0.0" if negative else "0.0"
    return None


def _shortest(value, bits, most, read, least=1):
    """The text of a positive value whose bits are bits; read(text) gives the bits text reads as.

    The decimal is the one with the fewest digits that reads back as value
    (at least two digits when one would do), and of those the nearest to
    value, or the one with an even last digit when two are as near. No
    decimal of fewer than least digits reads back.
    """
    exact = Decimal(value)
    for count in range(least, most + 1):
        found = _reading_back(exact, count, bits, read)
        if found:
            break
    if count == 1:
        found = _reading_back(exact, 2, bits, read)
        count = 2

    def distance(number):
        last_digit = int(number.scaleb(count - 1 - number.adjusted())) % 2
        return abs(_EXACT.subtract(number, exact)), last_digit

    return _java_text(min(found, key=distance))


def _reading_back(exact, count, bits, read):
    """The decimals of count digits next to exact (below and above) that read back as bits."""
    near = {_FLOOR[count].plus(exact), _CEILING[count].plus(exact)}
    return [number for number in near if read(str(number)) == bits]


def _java_text(number):
    """A positive Decimal written plain from 0.001 to below 10,000,000, else with an exponent."""
    _, digit_tuple, exponent = number.normalize(_EXACT).as_tuple()
    digits = "".join(map(str, digit_tuple))
    power = exponent + len(digits) - 1      # 10 ** power <= number < 10 ** (power + 1)
    if not -3 <= power < 7:
        return f"{digits[0]}.{digits[1:] or '0'}E{power}"
    if power < 0:
        return "0." + "0" * (-power - 1) + digits
    return f"{digits[:power + 1].ljust(power + 1, '0')}.{digits[power + 1:] or '0'}"
