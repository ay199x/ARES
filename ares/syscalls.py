# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""System calls made with ``SVC #N``.

N is the immediate of the SVC instruction. Arguments are passed in R0-R3 and
results returned in R0 (and R1 where listed). Every register that is not a
result keeps its value, and so do the flags.

Floating-point values are passed in S0 (single) or D0 (double), and are
written and read as ares.floats writes and reads them (``1.5``, ``1.0E-5``).

A service that needs typed input or a dialog answer asks the machine for it;
when the answer is not there yet, the machine stops and runs the same SVC
again once it has arrived. Such services therefore change nothing before
they have their answer.
"""

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict

from .errors import RuntimeFault
from .floats import (double_bits, format_double, format_single, parse_double, parse_single,
                     single_bits)

STDIN, STDOUT, STDERR = 0, 1, 2
FIRST_FILE = 3

# Dialog kinds (Request.dialog)
CONFIRM = "confirm"                 # answer: 0 yes, 1 no, 2 cancel
INPUT_INTEGER = "input integer"     # answer: text, or None when cancelled
INPUT_FLOAT = "input float"         # answer: text, or None when cancelled
INPUT_DOUBLE = "input double"       # answer: text, or None when cancelled
INPUT_STRING = "input string"       # answer: text, or None when cancelled
MESSAGE = "message"                 # value: 0 error, 1 information, 2 warning, 3 question
MESSAGE_INTEGER = "message integer"  # value: the integer shown after the message
MESSAGE_FLOAT = "message float"     # value: the text of the number shown after the message
MESSAGE_DOUBLE = "message double"   # value: the text of the number shown after the message
MESSAGE_STRING = "message string"   # value: the text shown after the message
INPUT_DIALOGS = (INPUT_INTEGER, INPUT_FLOAT, INPUT_DOUBLE, INPUT_STRING)     # with a field
VALUE_MESSAGES = (MESSAGE_INTEGER, MESSAGE_FLOAT, MESSAGE_DOUBLE, MESSAGE_STRING)

# Dialog status codes (R1)
OK, NOT_A_NUMBER, CANCELLED, NO_INPUT, CUT_TO_FIT = 0, -1, -2, -3, -4

MIDI_DEFAULTS = (60, 1000, 0, 100)  # pitch, duration ms, instrument, volume

_INTEGER = re.compile(r"([+-]?)0*([1-9][0-9]*|0)")   # one way to match: fast on long texts
WRITE_PIECE = 0x100000              # SVC 15 copies memory 1 MB at a time


@dataclass(frozen=True)
class Service:
    number: int
    name: str
    arguments: str
    result: str
    handler: Callable


SERVICES: Dict[int, Service] = {}


def service(number, name, arguments="", result=""):
    """Register the decorated function as service number."""
    def register(handler):
        SERVICES[number] = Service(number, name, arguments, result, handler)
        return handler
    return register


def to_signed(value):
    """A 32-bit register value as a signed integer."""
    return value - (1 << 32) if value & 0x80000000 else value


def call(machine, number):
    """Run service number on machine; raises RuntimeFault for unknown numbers."""
    entry = SERVICES.get(number)
    if entry is None:
        raise RuntimeFault(f"unknown service number {number} (SVC #{number})")
    entry.handler(machine)


def dialog_text(request):
    """The text a dialog shows: the message, plus the value of services 56 and 59."""
    if request.dialog in VALUE_MESSAGES:
        return f"{request.message}{request.value}"
    return request.message


def parse_integer(text):
    """A typed integer (optional sign, decimal digits), or None if it is not one."""
    match = _INTEGER.fullmatch(text.strip())
    if not match or len(match[2]) > 10:     # leading zeros may be many, digits not
        return None
    value = int(match[1] + match[2])
    return value if -(1 << 31) <= value < (1 << 31) else None


def _text(data):
    return data.decode("utf-8", errors="replace")


def _strip_newline(line):
    if line.endswith(b"\n"):
        line = line[:-1]
    return line[:-1] if line.endswith(b"\r") else line


class JavaRandom:
    """Java's linear congruential generator, so seeded sequences match other tools."""

    _MULTIPLIER = 0x5DEECE66D
    _MASK = (1 << 48) - 1

    def __init__(self, seed):
        self._seed = (seed ^ self._MULTIPLIER) & self._MASK

    def _next(self, bits):
        self._seed = (self._seed * self._MULTIPLIER + 0xB) & self._MASK
        return self._seed >> (48 - bits)

    def next_int(self):
        """A 32-bit random value (as an unsigned register value)."""
        return self._next(32)

    def next_float(self):
        """A random single from 0 up to (not including) 1, as a Python float."""
        return self._next(24) / (1 << 24)

    def next_double(self):
        """A random double from 0 up to (not including) 1."""
        return ((self._next(26) << 27) + self._next(27)) / (1 << 53)

    def next_below(self, bound):
        """A random value in 0 .. bound-1 (bound > 0)."""
        r = self._next(31)
        if bound & (bound - 1) == 0:
            return (bound * r) >> 31
        u = r
        r = u % bound
        while u - r + bound - 1 >= 1 << 31:     # the Java int overflow test
            u = self._next(31)
            r = u % bound
        return r


class ServiceState:
    """What the services remember during one run: open files, random generators."""

    def __init__(self):
        self.files = {}
        self.next_descriptor = FIRST_FILE
        self.randoms = {}

    def random(self, generator):
        if generator not in self.randoms:
            self.randoms[generator] = JavaRandom(time.time_ns())
        return self.randoms[generator]

    def close(self):
        for f in self.files.values():
            f.close()
        self.files.clear()


# Output --------------------------------------------------------------------

@service(1, "print integer", "R0 = integer")
def print_integer(machine):
    machine.console.write_text(str(to_signed(machine.reg(0))))


@service(2, "print float", "S0 = float")
def print_float(machine):
    machine.console.write_text(format_single(machine.single(0)))


@service(3, "print double", "D0 = double")
def print_double(machine):
    machine.console.write_text(format_double(machine.double(0)))


@service(4, "print string", "R0 = address of zero-terminated string")
def print_string(machine):
    machine.console.write_bytes(machine.read_cstring(machine.reg(0)))


@service(11, "print character", "R0 = character")
def print_character(machine):
    machine.console.write_bytes(bytes([machine.reg(0) & 0xFF]))


@service(34, "print hexadecimal", "R0 = integer")
def print_hexadecimal(machine):
    machine.console.write_text(f"0x{machine.reg(0):08x}")


@service(35, "print binary", "R0 = integer")
def print_binary(machine):
    machine.console.write_text(f"{machine.reg(0):032b}")


@service(36, "print unsigned", "R0 = integer")
def print_unsigned(machine):
    machine.console.write_text(str(machine.reg(0)))


# Input ---------------------------------------------------------------------

@service(5, "read integer", result="R0 = integer")
def read_integer(machine):
    value = parse_integer(_text(machine.input_line(5)))
    if value is None:
        raise RuntimeFault("invalid integer input (SVC #5)")
    machine.set_reg(0, value)


@service(6, "read float", result="S0 = float")
def read_float(machine):
    bits = parse_single(_text(machine.input_line(6)))
    if bits is None:
        raise RuntimeFault("invalid float input (SVC #6)")
    machine.set_single(0, bits)


@service(7, "read double", result="D0 = double")
def read_double(machine):
    bits = parse_double(_text(machine.input_line(7)))
    if bits is None:
        raise RuntimeFault("invalid double input (SVC #7)")
    machine.set_double(0, bits)


@service(8, "read string", "R0 = buffer address, R1 = maximum length")
def read_string(machine):
    """Like fgets: at most n-1 characters, a newline if it fits, then a zero byte."""
    line = _strip_newline(machine.input_line(8))
    size = to_signed(machine.reg(1))
    data = line[:max(size - 1, 0)]
    if len(data) < size - 1:
        data += b"\n"
    if size >= 1:
        data += b"\0"
    machine.write_memory(machine.reg(0), data)


@service(12, "read character", result="R0 = character")
def read_character(machine):
    line = machine.input_line(12)
    if not line:
        raise RuntimeFault("invalid character input (SVC #12)")
    machine.set_reg(0, line[0])


# Program control and memory -----------------------------------------------

@service(9, "allocate heap memory", "R0 = number of bytes", "R0 = address")
def allocate_heap(machine):
    from .machine import DDR_END        # imported here: the machine module imports this one
    size = to_signed(machine.reg(0))
    if size < 0:
        raise RuntimeFault(f"negative heap size {size} (SVC #9)")
    address = machine.heap
    new_heap = (address + size + 3) & ~3
    # The heap grows up to the top of DDR3, but stays below SP when SP is in
    # DDR3 above the heap's start. With SP's start value 0 the stack is in
    # on-chip memory; a stack at or below the heap's start grows away from it.
    sp = machine.reg(13)
    limit = sp if machine.heap_start < sp <= DDR_END else DDR_END
    if new_heap > limit:
        raise RuntimeFault(f"not enough memory for {size} bytes of heap (SVC #9)")
    machine.heap = new_heap
    machine.set_reg(0, address)


@service(10, "exit")
def exit_program(machine):
    machine.exit()


@service(17, "exit with value", "R0 = value")
def exit_with_value(machine):
    machine.exit(to_signed(machine.reg(0)))


@service(30, "system time", result="R0 = low 32 bits, R1 = high 32 bits (milliseconds)")
def system_time(machine):
    ms = time.time_ns() // 1_000_000
    machine.set_reg(0, ms & 0xFFFFFFFF)
    machine.set_reg(1, (ms >> 32) & 0xFFFFFFFF)


def _midi_arguments(machine):
    """Pitch, duration, instrument and volume, with defaults for bad values."""
    values = [to_signed(machine.reg(n)) for n in range(4)]
    limits = (127, None, 127, 127)
    return [v if 0 <= v and (limit is None or v <= limit) else default
            for v, limit, default in zip(values, limits, MIDI_DEFAULTS)]


@service(31, "MIDI out", "R0 = pitch, R1 = duration (ms), R2 = instrument, R3 = volume")
def midi_out(machine):
    _midi_arguments(machine)            # no synthesizer: the note is not played


@service(32, "sleep", "R0 = milliseconds")
def sleep(machine):
    machine.sleep(32, to_signed(machine.reg(0)))


@service(33, "MIDI out and wait",
         "R0 = pitch, R1 = duration (ms), R2 = instrument, R3 = volume")
def midi_out_wait(machine):
    machine.sleep(33, _midi_arguments(machine)[1])


# Files ---------------------------------------------------------------------

_OPEN_MODES = {0: "rb", 1: "wb", 9: "ab"}


@service(13, "open file", "R0 = file name, R1 = flags (0 read, 1 write, 9 append), "
         "R2 = mode (ignored)", "R0 = file descriptor, negative on error")
def open_file(machine):
    name = _text(machine.read_cstring(machine.reg(0)))
    mode = _OPEN_MODES.get(machine.reg(1))
    descriptor = -1
    if name and mode:
        try:
            f = open(machine.base_dir / Path(name), mode)
        except (OSError, ValueError):
            pass
        else:
            state = machine.services
            descriptor = state.next_descriptor
            state.next_descriptor += 1
            state.files[descriptor] = f
    machine.set_reg(0, descriptor)


@service(14, "read from file", "R0 = file descriptor, R1 = buffer address, "
         "R2 = maximum length", "R0 = number of bytes read, 0 at end of file, "
         "negative on error")
def read_file(machine):
    descriptor, size = to_signed(machine.reg(0)), to_signed(machine.reg(2))
    f = machine.services.files.get(descriptor)
    if size < 0 or (descriptor != STDIN and f is None):
        machine.set_reg(0, -1)
        return
    if descriptor == STDIN:
        data = machine.input_bytes(14, size) if size else b""
    else:
        try:
            data = f.read(size)
        except (OSError, ValueError):
            machine.set_reg(0, -1)
            return
    machine.write_memory(machine.reg(1), data)
    machine.set_reg(0, len(data))


@service(15, "write to file", "R0 = file descriptor, R1 = buffer address, "
         "R2 = number of bytes", "R0 = number of bytes written, negative on error")
def write_file(machine):
    descriptor, size = to_signed(machine.reg(0)), to_signed(machine.reg(2))
    f = machine.services.files.get(descriptor)
    if size < 0 or (descriptor not in (STDOUT, STDERR) and f is None):
        machine.set_reg(0, -1)
        return
    address = machine.reg(1)
    machine.check_range(address, size)  # a bad range fails before anything is written
    for offset in range(0, size, WRITE_PIECE):
        data = machine.read_memory(address + offset, min(WRITE_PIECE, size - offset))
        if f is None:
            machine.console.write_bytes(data)
            continue
        try:
            f.write(data)
        except (OSError, ValueError):
            machine.set_reg(0, -1)
            return
    if f is not None:
        try:
            f.flush()                   # on disk at once, even if the run is stopped
        except (OSError, ValueError):
            machine.set_reg(0, -1)
            return
    machine.set_reg(0, size)


@service(16, "close file", "R0 = file descriptor")
def close_file(machine):
    f = machine.services.files.pop(to_signed(machine.reg(0)), None)
    if f is not None:
        f.close()


# Random numbers ------------------------------------------------------------

@service(40, "set random seed", "R0 = generator number, R1 = seed")
def set_random_seed(machine):
    machine.services.randoms[machine.reg(0)] = JavaRandom(to_signed(machine.reg(1)))


@service(41, "random integer", "R0 = generator number", "R0 = random integer")
def random_integer(machine):
    machine.set_reg(0, machine.services.random(machine.reg(0)).next_int())


@service(42, "random integer below a bound", "R0 = generator number, R1 = bound",
         "R0 = random integer from 0 to bound-1")
def random_below(machine):
    bound = to_signed(machine.reg(1))
    if bound <= 0:
        raise RuntimeFault(f"the bound must be positive, not {bound} (SVC #42)")
    machine.set_reg(0, machine.services.random(machine.reg(0)).next_below(bound))


@service(43, "random float", "R0 = generator number", "S0 = random float from 0 up to 1")
def random_float(machine):
    machine.set_single(0, single_bits(machine.services.random(machine.reg(0)).next_float()))


@service(44, "random double", "R0 = generator number", "D0 = random double from 0 up to 1")
def random_double(machine):
    machine.set_double(0, double_bits(machine.services.random(machine.reg(0)).next_double()))


# Dialogs -------------------------------------------------------------------

def _message(machine):
    return _text(machine.read_cstring(machine.reg(0)))


@service(50, "confirm dialog", "R0 = message", "R0 = 0 yes, 1 no, 2 cancel")
def confirm_dialog(machine):
    answer = machine.dialog(50, CONFIRM, _message(machine))
    machine.set_reg(0, answer if answer in (0, 1, 2) else 2)


@service(51, "input dialog, integer", "R0 = message", "R0 = integer, R1 = status")
def input_integer_dialog(machine):
    _input_number(machine, 51, INPUT_INTEGER, parse_integer, machine.set_reg)


@service(52, "input dialog, float", "R0 = message", "S0 = float, R1 = status")
def input_float_dialog(machine):
    _input_number(machine, 52, INPUT_FLOAT, parse_single, machine.set_single)


@service(53, "input dialog, double", "R0 = message", "D0 = double, R1 = status")
def input_double_dialog(machine):
    _input_number(machine, 53, INPUT_DOUBLE, parse_double, machine.set_double)


def _input_number(machine, number, kind, parse, store):
    """Ask for a number: store(0, its value) puts it (0 if there is none) into R0, S0 or D0."""
    text = machine.dialog(number, kind, _message(machine))
    value, status = 0, OK
    if text is None:
        status = CANCELLED
    elif not text.strip():
        status = NO_INPUT
    else:
        value = parse(text)
        if value is None:
            value, status = 0, NOT_A_NUMBER
    store(0, value)
    machine.set_reg(1, status)


@service(54, "input dialog, string", "R0 = message, R1 = buffer address, "
         "R2 = maximum length", "R1 = status")
def input_string_dialog(machine):
    text = machine.dialog(54, INPUT_STRING, _message(machine))
    if text is None:
        machine.set_reg(1, CANCELLED)
        return
    if not text:
        machine.set_reg(1, NO_INPUT)
        return
    data, size = text.encode("utf-8", "replace"), to_signed(machine.reg(2))
    if size >= 1:
        kept = data[:size - 1]
        machine.write_memory(machine.reg(1),
                             kept + (b"\n\0" if len(data) < size - 1 else b"\0"))
    machine.set_reg(1, CUT_TO_FIT if len(data) > max(size - 1, 0) else OK)


@service(55, "message dialog", "R0 = message, R1 = type (0 error, 1 information, "
         "2 warning, 3 question)")
def message_dialog(machine):
    machine.dialog(55, MESSAGE, _message(machine), machine.reg(1))


@service(56, "message dialog, integer", "R0 = message, R1 = integer")
def message_integer_dialog(machine):
    machine.dialog(56, MESSAGE_INTEGER, _message(machine), to_signed(machine.reg(1)))


@service(57, "message dialog, float", "R0 = message, S0 = float")
def message_float_dialog(machine):
    machine.dialog(57, MESSAGE_FLOAT, _message(machine), format_single(machine.single(0)))


@service(58, "message dialog, double", "R0 = message, D0 = double")
def message_double_dialog(machine):
    machine.dialog(58, MESSAGE_DOUBLE, _message(machine), format_double(machine.double(0)))


@service(59, "message dialog, string", "R0 = message, R1 = address of string")
def message_string_dialog(machine):
    machine.dialog(59, MESSAGE_STRING, _message(machine),
                   _text(machine.read_cstring(machine.reg(1))))
