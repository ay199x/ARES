# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Assembler and linker: options, message parsing, results."""

import pytest

from ares.assembler import (AS_OPTIONS, ERROR, INFO, WARNING, Message, assemble,
                            parse_assembler_output, parse_linker_output)


def test_uses_cpulator_options():
    assert AS_OPTIONS == ["-mfloat-abi=softfp", "-march=armv7-a", "-mcpu=cortex-a9",
                          "-mfpu=neon-fp16", "--gdwarf2"]


# Message parsing ---------------------------------------------------------

def test_parse_assembler_errors():
    output = ("prog.s: Assembler messages:\n"
              "prog.s:4: Error: bad instruction `foo R1,R2'\n"
              "prog.s:7: Error: invalid constant (12345) after fixup\n")
    assert parse_assembler_output(output, "lab1.s") == [
        Message("lab1.s", 4, ERROR, "bad instruction `foo R1,R2'"),
        Message("lab1.s", 7, ERROR, "invalid constant (12345) after fixup"),
    ]


def test_parse_assembler_warning_info_and_fatal():
    output = ("prog.s:9: Warning: careful\r\n"
              "prog.s:12:  Info: macro invoked from here\n"
              "prog.s: Fatal error: can't create prog.o\n"
              "Error: unrecognized option -mfoo\n")
    assert parse_assembler_output(output) == [
        Message("prog.s", 9, WARNING, "careful"),
        Message("prog.s", 12, INFO, "macro invoked from here"),
        Message("prog.s", None, ERROR, "can't create prog.o"),
        Message(None, None, ERROR, "unrecognized option -mfoo"),
    ]


def test_parse_assembler_keeps_other_file_names():
    output = "C:\\work\\lib.s:3: Error: bad instruction `x'\n"
    assert parse_assembler_output(output, "main.s") == [
        Message("C:\\work\\lib.s", 3, ERROR, "bad instruction `x'")]


def test_parse_linker_undefined_reference_windows_path():
    output = ("C:\\ARES\\vendor\\windows-x64\\bin\\arm-none-eabi-ld.exe: prog.o: "
              "in function `_start':\n"
              "C:\\Temp\\ares-x1/prog.s:3:(.text+0x0): undefined reference to `missing'\n")
    assert parse_linker_output(output, "main.s") == [
        Message("main.s", 3, ERROR, "undefined reference to `missing'")]


def test_parse_linker_warning_and_section_messages():
    output = ("/opt/ares/bin/arm-none-eabi-ld: warning: cannot find entry symbol _start;"
              " defaulting to 00000000\n"
              "arm-none-eabi-ld: prog.o:(.text+0x8): relocation truncated to fit: "
              "R_ARM_JUMP24 against `far'\n")
    assert parse_linker_output(output, "main.s") == [
        Message("main.s", None, WARNING,
                "No global _start label: execution starts at address 0x00000000. "
                "Add .global _start and _start: before your first instruction."),
        Message("main.s", None, ERROR, "relocation truncated to fit: R_ARM_JUMP24 against `far'"),
    ]


def test_message_format():
    assert Message("a.s", 7, ERROR, "x").format() == "Error in a.s line 7: x"
    assert Message("a.s", None, WARNING, "y").format() == "Warning in a.s: y"
    assert Message(None, None, ERROR, "z").format() == "Error: z"


# Running the tools -------------------------------------------------------

def test_assemble_success(tmp_path):
    result = assemble("        .global _start\n_start:\n        B .", tmp_path)
    assert result.ok
    assert result.messages == []
    assert result.elf_path.is_file()


def test_assemble_reports_errors_with_lines(tmp_path):
    source = ("        .global _start\n_start:\n        MOV R0, #1\n"
              "        FOO R1, R2\n        MOV R0, #0x12345\n")
    result = assemble(source, tmp_path, display_name="lab.s")
    assert not result.ok
    assert result.elf_path is None
    assert [(m.file, m.line, m.severity) for m in result.messages] == [
        ("lab.s", 4, ERROR), ("lab.s", 5, ERROR)]


def test_assemble_reports_linker_errors(tmp_path):
    result = assemble("        .global _start\n_start:\n        BL missing\n        B .\n",
                      tmp_path, display_name="lab.s")
    assert not result.ok
    assert result.messages == [
        Message("lab.s", 3, ERROR, "undefined reference to `missing'")]


START_WARNING = ("No global _start label: execution starts at address 0x00000000. "
                 "Add .global _start and _start: before your first instruction.")


@pytest.mark.parametrize("source", [
    "start:\n        B .\n",                            # no _start at all
    "_start:\n        B .\n",                           # _start is not global
    "        .global _start\nmain:\n        B .\n",     # .global but no label
])
def test_missing_start_is_a_clear_warning(tmp_path, source):
    result = assemble(source, tmp_path, display_name="lab.s")
    assert result.ok
    assert result.messages == [Message("lab.s", None, WARNING, START_WARNING)]
    assert result.messages[0].format() == "Warning in lab.s: " + START_WARNING


# Capital-letters rule ----------------------------------------------------

LOWERCASE = ("        .global _start\n"
             "_start:\n"
             "        add r0, r1, #1\n"
             "        MOV R2, #3\n"
             "        .Word 7\n"
             "        b .\n")


def test_capitals_checked_before_assembling(tmp_path):
    result = assemble(LOWERCASE + "        FOO R1\n", tmp_path, display_name="lab.s")
    assert not result.ok
    assert result.elf_path is None
    assert result.messages == [
        Message("lab.s", 3, ERROR, "write instructions and registers in capitals: ADD R0, R1, #1"),
        Message("lab.s", 5, ERROR, "write directives in lowercase: .word 7"),
        Message("lab.s", 6, ERROR, "write instructions and registers in capitals: B ."),
    ]
    assert [m.format() for m in result.messages][0] == (
        "Error in lab.s line 3: write instructions and registers in capitals: ADD R0, R1, #1")
    assert not (tmp_path / "prog.o").exists()


def test_capitals_rule_can_be_switched_off(tmp_path):
    result = assemble(LOWERCASE, tmp_path, require_capitals=False)
    assert result.ok
    assert result.messages == []
    assert result.elf_path.is_file()


def test_assemble_replaces_previous_output(tmp_path):
    assert assemble("        .global _start\n_start:\n        B .\n", tmp_path).ok
    result = assemble("        .global _start\n_start:\n        FOO\n", tmp_path)
    assert not result.ok
    assert not (tmp_path / "prog.elf").exists()


SLOW = ".set Q, 0\n.rept 1000\n.rept 1000\n.set Q, Q+1\n.endr\n.endr\n"


def test_assembler_time_limit_gives_a_message(tmp_path, monkeypatch):
    import ares.assembler
    monkeypatch.setattr(ares.assembler, "TOOL_TIMEOUT", 0.2)
    result = assemble(SLOW, tmp_path, display_name="slow.s")
    assert not result.ok
    assert result.messages == [Message("slow.s", None, ERROR,
                                       "the assembler did not finish within 0.2 seconds")]


@pytest.mark.serial
def test_assembling_can_be_cancelled(tmp_path):
    import threading
    import time
    cancel = threading.Event()
    threading.Timer(0.2, cancel.set).start()
    start = time.perf_counter()
    result = assemble(SLOW, tmp_path, display_name="slow.s", cancel=cancel)
    assert time.perf_counter() - start < 0.6
    assert result.messages == [Message("slow.s", None, ERROR, "assembling was cancelled")]
