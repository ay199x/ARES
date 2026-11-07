# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Single and double values as text, and typed numbers rounded to them."""

import random
import time
from fractions import Fraction

import pytest

from ares.floats import (DOUBLE_NAN, SINGLE_NAN, double, double_bits, format_double,
                         format_single, parse_double, parse_single, single, single_bits)

# The texts Java 21's Float.toString writes for these singles (checked with Java).
SINGLE_TEXTS = [
    (0x00000000, "0.0"), (0x80000000, "-0.0"), (0x7F800000, "Infinity"),
    (0xFF800000, "-Infinity"), (0x7FC00000, "NaN"), (0xFFC00001, "NaN"), (0x7F800001, "NaN"),
    (0x3FC00000, "1.5"), (0x3DCCCCCD, "0.1"), (0x3727C5AC, "1.0E-5"), (0x4B189680, "1.0E7"),
    (0x4B18967F, "9999999.0"), (0x3A83126F, "0.001"), (0x38D1B717, "1.0E-4"),
    (0x7F7FFFFF, "3.4028235E38"), (0x00000001, "1.4E-45"), (0x00000002, "2.8E-45"),
    (0x00000003, "4.2E-45"), (0x00000009, "1.3E-44"), (0x00800000, "1.1754944E-38"),
    (0x4B800000, "1.6777216E7"), (0x42C80000, "100.0"), (0x47F12065, "123456.79"),
    (0xC0200000, "-2.5"), (0x3EAAAAAB, "0.33333334"), (0x3A800000, "9.765625E-4"),
    (0x3E99999A, "0.3"), (0x3F800001, "1.0000001"), (0x3F7FFFFF, "0.99999994"),
    (0x501502F9, "1.0E10"), (0x2EDBE6FF, "1.0E-10"), (0x3A83126E, "9.999999E-4"),
    (0x4996B438, "1234567.0"),
]

# The texts Java 21's Double.toString writes for these doubles (checked with Java).
DOUBLE_TEXTS = [
    (0x3FD3333333333334, "0.30000000000000004"), (0x0000000000000001, "4.9E-324"),
    (0x0000000000000002, "9.9E-324"), (0x0000000000000003, "1.5E-323"),
    (0x0000000000000009, "4.4E-323"), (0x0000000000000007, "3.5E-323"),
    (0x7FEFFFFFFFFFFFFF, "1.7976931348623157E308"),
    (0x0010000000000000, "2.2250738585072014E-308"), (0x44B52D02C7E14AF6, "1.0E23"),
    (0x44C52D02C7E14AF6, "2.0E23"), (0x3F60624DD2F1A9FC, "0.002"),
    (0x416312D000000000, "1.0E7"), (0x4132D68700000000, "1234567.0"),
    (0x416312CFFFFFFFFF, "9999999.999999998"), (0x3F50624DD2F1A9FC, "0.001"),
    (0x3F50624DD2F1A9FB, "9.999999999999998E-4"), (0x43E0000000000000, "9.223372036854776E18"),
    (0x3FD5555555555555, "0.3333333333333333"), (0x4059000000000000, "100.0"),
    (0x8000000000000000, "-0.0"), (0xBFF8000000000000, "-1.5"),
    (0x7FF8000000000000, "NaN"), (0xFFF0000000000000, "-Infinity"),
    (0x7FF0000000000001, "NaN"), (0x01A56E1FC2F8F359, "1.0E-300"),
    (0x405EDD2F1A9FBE77, "123.456"),
]


@pytest.mark.parametrize("bits, text", SINGLE_TEXTS)
def test_singles_as_text(bits, text):
    assert format_single(bits) == text


@pytest.mark.parametrize("bits, text", DOUBLE_TEXTS)
def test_doubles_as_text(bits, text):
    assert format_double(bits) == text


def test_text_reads_back_as_the_same_value():
    rng = random.Random(4)
    for _ in range(3000):
        bits = rng.getrandbits(32)
        if bits & 0x7F800000 != 0x7F800000:            # not infinity or NaN
            assert parse_single(format_single(bits)) == bits
        bits = rng.getrandbits(64)
        if bits & 0x7FF0000000000000 != 0x7FF0000000000000:
            assert parse_double(format_double(bits)) == bits


def test_no_shorter_text_reads_back():
    # 0.1f is 0.100000001490116...: one digit is enough; 1/3 needs eight.
    assert format_single(single_bits(0.1)) == "0.1"
    assert format_single(single_bits(1 / 3)) == "0.33333334"
    assert parse_single("0.3333333") != single_bits(1 / 3)


# Typed numbers ---------------------------------------------------------------

def test_typed_numbers():
    assert parse_single("1.5") == 0x3FC00000 and parse_double("1.5") == 0x3FF8000000000000
    assert parse_single("  -2.5 ") == 0xC0200000
    assert parse_single("+.5") == 0x3F000000 and parse_single("5.") == 0x40A00000
    assert parse_single("1e3") == parse_single("1000") == parse_single("1E+3") == 0x447A0000
    assert parse_single("2e-3") == single_bits(0.002)
    assert parse_single("0") == 0 and parse_single("-0") == 0x80000000
    assert parse_double("-0.0") == 1 << 63
    assert parse_single("0001.2500") == 0x3FA00000


def test_words_for_infinity_and_nan():
    assert parse_single("inf") == parse_single("Infinity") == 0x7F800000
    assert parse_single("-INF") == 0xFF800000
    assert parse_double("infinity") == 0x7FF0000000000000
    assert parse_single("NaN") == SINGLE_NAN and parse_single("-nan") == 0xFFC00000
    assert parse_double("nan") == DOUBLE_NAN


@pytest.mark.parametrize("text", [
    "", " ", "x", "1.2.3", "1e", "e5", "--1", "+-1", "- 1", "1 2", ".", "1e+", "0x10",
    "1_000", "1,5", "infin", "nana", "١٢", "１", "1.5f", "0b1", "1e5.5"])
def test_not_numbers(text):
    assert parse_single(text) is None and parse_double(text) is None


def test_too_large_numbers_become_infinity():
    assert parse_single("1e39") == 0x7F800000 and parse_single("-1e39") == 0xFF800000
    assert parse_single("3.4028235e38") == 0x7F7FFFFF
    assert parse_double("1e309") == 0x7FF0000000000000
    assert parse_single("1e" + "9" * 5000) == 0x7F800000


def test_too_small_numbers_become_zero():
    assert parse_single("1e-46") == 0 and parse_single("-1e-46") == 0x80000000
    assert parse_double("1e-400") == 0
    assert parse_single("7.1e-46") == 1                 # just over half the smallest single


def test_halfway_between_two_singles():
    # 1 + 2**-24 lies halfway between 1 and the next single: ties go to the even one.
    half = Fraction(1) + Fraction(1, 2 ** 24)
    assert parse_single(_decimal(half)) == 0x3F800000
    # A hair above or below, too little for a double to tell, still decides.
    assert parse_single(_decimal(half) + "0" * 40 + "1") == 0x3F800001
    assert parse_single(_decimal(half - Fraction(1, 10 ** 60))) == 0x3F800000
    # Halfway to the next odd one goes up to the even one.
    up = Fraction(single(0x3F800001)) + Fraction(1, 2 ** 24)
    assert parse_single(_decimal(up)) == 0x3F800002
    assert parse_single(_decimal(up - Fraction(1, 10 ** 60))) == 0x3F800001


def test_the_largest_single_and_infinity():
    # Halfway between the largest single and 2**128 becomes infinity; anything less does not.
    limit = Fraction(2 ** 128 - 2 ** 103)
    assert parse_single(_decimal(limit)) == 0x7F800000
    assert parse_single(_decimal(limit - Fraction(1, 10 ** 30))) == 0x7F7FFFFF


@pytest.mark.serial
def test_a_long_text_that_is_no_number_is_refused_at_once():
    start = time.perf_counter()
    digits = "1" * 200_000
    for text in (digits + "x", digits + "e", digits + "..", "." + digits + "e+"):
        assert parse_single(text) is None and parse_double(text) is None
    assert time.perf_counter() - start < 1.0


def test_very_long_numbers():
    assert parse_single("1" * 100000 + "e-99990") == single_bits(1.1111111111e9)
    assert parse_double("0." + "0" * 5000 + "1e5001") == double_bits(1.0)


def test_values_and_bits():
    assert single(0x3FC00000) == 1.5 and double(0x3FF8000000000000) == 1.5
    assert single_bits(1.5) == 0x3FC00000 and double_bits(-2.0) == 0xC000000000000000
    assert single_bits(1e39) == 0x7F800000 and single_bits(-1e39) == 0xFF800000


def _decimal(fraction):
    """The exact decimal text of a fraction whose denominator divides a power of 10."""
    for digits in range(400):
        scaled = fraction * 10 ** digits
        if scaled.denominator == 1:
            text = str(scaled.numerator).rjust(digits + 1, "0")
            return f"{text[:-digits]}.{text[-digits:]}" if digits else text
    raise ValueError(fraction)
