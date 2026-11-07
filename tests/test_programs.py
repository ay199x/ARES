# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Run every tests/programs/*.s that has a .out file through the command-line runner."""

import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import PROGRAMS, ROOT

CASES = sorted(p for p in PROGRAMS.glob("*.s") if p.with_suffix(".out").is_file())


def test_cases_found():
    names = {p.name for p in CASES}
    assert {"hello.s", "sum_dec.s", "sum_hex.s", "count_dec.s", "count_hex.s", "leaf.s",
            "fact.s", "jtag.s", "read_sum.s", "circle.s"} <= names


@pytest.mark.parametrize("source", CASES, ids=lambda p: p.name)
def test_program_output(source):
    """Standard input comes from the .in file next to the program, if there is one."""
    typed = source.with_suffix(".in")
    proc = subprocess.run(
        [sys.executable, "-m", "ares.cli", str(source.relative_to(ROOT))],
        cwd=ROOT, capture_output=True, timeout=120,
        input=typed.read_bytes() if typed.is_file() else b"")
    expected = source.with_suffix(".out").read_bytes().replace(b"\r\n", b"\n")
    assert proc.stderr.decode() == ""
    assert proc.stdout.replace(b"\r\n", b"\n").decode() == expected.decode()
    assert proc.returncode == 0


def test_lowercase_program_fails_the_capitals_check():
    source = str(Path("tests") / "programs" / "lowercase.s")
    proc = subprocess.run([sys.executable, "-m", "ares.cli", source],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr == (f"Error in {source} line 9: "
                           "write instructions and registers in capitals: ADD R0, R1, #1\n")


def test_cli_reports_assembler_errors(tmp_path):
    source = tmp_path / "bad.s"
    source.write_text("        .global _start\n_start:\n        FOO R1, R2\n")
    proc = subprocess.run([sys.executable, "-m", "ares.cli", str(source)],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert f"Error in {source} line 3: bad instruction `foo R1,R2'" in proc.stderr


def test_cli_reports_runtime_errors(tmp_path):
    source = tmp_path / "crash.s"
    source.write_text("        .global _start\n_start:\n        MOV R0, #0x50000000\n"
                      "        LDR R1, [R0]\n        SVC #10\n")
    proc = subprocess.run([sys.executable, "-m", "ares.cli", str(source)],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 2
    assert proc.stdout == ("Runtime error at line 4 (address 0x00000004): "
                           "memory access out of range at 0x50000000\n"
                           "-- program is finished running (runtime error) --\n")


def run_cli(tmp_path, source, typed=""):
    """Run source through the CLI; bytes for typed are passed exactly (no newline changes)."""
    path = tmp_path / "prog.s"
    path.write_text(source)
    return subprocess.run([sys.executable, "-m", "ares.cli", str(path)], cwd=ROOT,
                          capture_output=True, text=isinstance(typed, str), timeout=120,
                          input=typed)


def test_cli_answers_dialogs_on_the_terminal(tmp_path):
    proc = run_cli(tmp_path, """\
        .global _start
_start:
        LDR     R0, =ask
        SVC     #51
        MOV     R1, R0
        LSL     R1, R1, #1
        LDR     R0, =tell
        SVC     #56
        LDR     R0, =ask
        SVC     #50
        SVC     #1
        SVC     #10
        .data
ask:    .asciz  "Number?"
tell:   .asciz  "Twice: "
""", typed="21\nn\n")
    assert proc.returncode == 0
    assert proc.stderr == "Number?\nTwice: 42\nNumber? [y/n/c]\n"
    assert proc.stdout == "1\n-- program is finished running --\n"


def test_cli_answers_float_dialogs_on_the_terminal(tmp_path):
    proc = run_cli(tmp_path, """\
        .global _start
_start:
        LDR     R0, =ask
        SVC     #52
        VADD.F32 S0, S0, S0
        LDR     R0, =tell
        SVC     #57
        LDR     R0, =ask
        SVC     #53
        SVC     #3
        SVC     #10
        .data
ask:    .asciz  "Number?"
tell:   .asciz  "Twice: "
""", typed="1.25\n0.1\n")
    assert proc.returncode == 0
    assert proc.stderr == "Number?\nTwice: 2.5\nNumber?\n"
    assert proc.stdout == "0.1\n-- program is finished running --\n"


def test_cli_feeds_the_jtag_uart(tmp_path):
    proc = run_cli(tmp_path, """\
        .global _start
_start:
        LDR     R1, =0xFF201000
wait:   LDR     R0, [R1]
        TST     R0, #0x8000         @ RVALID
        BEQ     wait
        STRB    R0, [R1]            @ echo the character
        AND     R0, R0, #0xFF
        CMP     R0, #'.'
        BNE     wait
        B       .
""", typed="ok.\n")
    assert proc.returncode == 0
    assert proc.stdout == "ok.\n-- program is finished running --\n"


def test_cli_end_of_input_stops_a_read(tmp_path):
    proc = run_cli(tmp_path, "        .global _start\n_start:\n        SVC #5\n        B .\n")
    assert proc.returncode == 2
    assert proc.stdout == ("Runtime error at line 3 (address 0x00000000): "
                           "invalid integer input (SVC #5)\n"
                           "-- program is finished running (runtime error) --\n")


def test_cli_prints_device_warnings(tmp_path):
    proc = run_cli(tmp_path, "        .global _start\n_start:\n        LDR R0, =0xFF200000\n"
                             "        STR R0, [R0]\n        B .\n")
    assert proc.returncode == 0
    assert proc.stderr == ("Warning: DE1-SoC device at 0xff200000 is not simulated: "
                           "writes are ignored, reads return 0\n")


# Regressions -----------------------------------------------------------------

READ_ONE = ("        .global _start\n_start:\n        SVC #5\n        SVC #1\n"
            "        MOV R0, #10\n        SVC #11\n        SVC #10\n")


def test_cli_exits_cleanly_while_stdin_stays_open(tmp_path):
    path = tmp_path / "prog.s"
    path.write_text(READ_ONE)
    proc = subprocess.Popen([sys.executable, "-m", "ares.cli", str(path)], cwd=ROOT,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    proc.stdin.write(b"5\n")
    proc.stdin.flush()                          # stdin is not closed
    try:
        out, err = proc.communicate(timeout=60)
    finally:
        proc.kill()
    assert err == b""
    assert out.replace(b"\r\n", b"\n") == b"5\n-- program is finished running --\n"
    assert proc.returncode == 0


def test_cli_turns_crlf_input_into_lf(tmp_path):
    proc = run_cli(tmp_path, """\
        .global _start
_start:
        SVC     #12             @ empty line: 10
        SVC     #1
        MOV     R0, #0
        LDR     R1, =buffer
        MOV     R2, #16
        SVC     #14             @ the line "hi" from descriptor 0
        MOV     R2, R0
        MOV     R0, #1
        SVC     #15
        LDR     R1, =0xFF201000
wait:   LDR     R0, [R1]        @ then echo through the JTAG UART
        TST     R0, #0x8000
        BEQ     wait
        STRB    R0, [R1]
        AND     R0, R0, #0xFF
        CMP     R0, #10
        BNE     wait
        SVC     #10
        .data
buffer: .space  16
""", typed=b"\r\nhi\r\nok\r\n")
    assert proc.stdout.replace(b"\r\n", b"\n") == (
        b"10hi\nok\n-- program is finished running --\n")


def test_cli_writes_utf8(tmp_path):
    path = tmp_path / "prog.s"
    path.write_text('        .global _start\n_start:\n        LDR R0, =text\n        SVC #4\n'
                    '        SVC #10\n        .data\n'
                    r'text:   .asciz "caf\303\251 \342\234\223\n"' "\n")
    proc = subprocess.run([sys.executable, "-m", "ares.cli", str(path)], cwd=ROOT,
                          capture_output=True, timeout=120)
    assert proc.stdout.replace(b"\r\n", b"\n") == (
        "café ✓\n-- program is finished running --\n".encode("utf-8"))


DIALOGS = """\
        .global _start
_start:
        LDR     R0, =ask
        SVC     #50
        MOV     R4, R0
        LDR     R0, =ask
        LDR     R1, =buffer
        MOV     R2, #8
        SVC     #54
        MOV     R5, R1
        LDR     R0, =ask
        SVC     #51
        MOV     R6, R1
        MOV     R0, R4
        SVC     #1
        MOV     R0, R5
        SVC     #1
        MOV     R0, R6
        SVC     #1
        LDR     R0, =buffer
        SVC     #4
        SVC     #10
        .data
ask:    .asciz  "?"
buffer: .space  8
"""


@pytest.mark.parametrize("typed, text", [
    ("maybe\r\nhi\r\n", "20-2hi\n"),        # unknown answer = cancel; CR removed; EOF = cancel
    ("y\n", "0-2-2\n"),                     # end of input cancels the input dialogs
])
def test_cli_dialog_answers(tmp_path, typed, text):
    proc = run_cli(tmp_path, DIALOGS, typed=typed)
    assert proc.returncode == 0
    assert proc.stdout == text + "-- program is finished running --\n"


def test_cli_stops_quietly_when_the_output_is_closed(tmp_path):
    path = tmp_path / "prog.s"
    path.write_text("        .global _start\n_start:\nloop:   MOV R0, #1\n        SVC #1\n"
                    "        MOV R0, #10\n        SVC #11\n        B loop\n")
    proc = subprocess.Popen([sys.executable, "-m", "ares.cli", str(path)], cwd=ROOT,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    assert proc.stdout.read(10)
    proc.stdout.close()
    try:
        err = proc.stderr.read()
        proc.wait(timeout=60)
    finally:
        proc.kill()
    assert b"Traceback" not in err and b"Fatal" not in err
    assert proc.returncode == 141


@pytest.mark.serial
def test_ctrl_c_stops_a_device_polling_program(tmp_path, capsys):
    import _thread
    import signal
    import threading

    from ares import cli
    path = tmp_path / "poll.s"
    path.write_text("        .global _start\n_start:\n        LDR R1, =0xFF201000\n"
                    "wait:   LDR R0, [R1]\n        TST R0, #0x8000\n        BEQ wait\n"
                    "        B .\n")
    timer = threading.Timer(0.5, _thread.interrupt_main, (signal.SIGINT,))
    timer.start()
    start = time.perf_counter()
    try:
        assert cli.main([str(path)]) == cli.EXIT_INTERRUPTED
    finally:
        timer.cancel()
    assert time.perf_counter() - start < 5
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler


def test_ctrl_c_during_assembly_returns_130(tmp_path, monkeypatch, capsys):
    import _thread
    import signal

    from ares import cli
    real_assemble = cli.assemble

    def assemble_then_interrupt(*args, **kwargs):
        result = real_assemble(*args, **kwargs)
        _thread.interrupt_main(signal.SIGINT)
        time.sleep(0.1)                         # let the handler run
        return result

    monkeypatch.setattr(cli, "assemble", assemble_then_interrupt)
    path = tmp_path / "prog.s"
    path.write_text(READ_ONE)
    assert cli.main([str(path)]) == cli.EXIT_INTERRUPTED


def test_the_previous_ctrl_c_handler_comes_back(capsys):
    import signal

    from ares import cli
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    try:
        assert cli.main([str(PROGRAMS / "hello.s")]) == cli.EXIT_FINISHED
        assert signal.getsignal(signal.SIGINT) is signal.SIG_DFL
    finally:
        signal.signal(signal.SIGINT, signal.default_int_handler)


def test_missing_standard_output_counts_as_closed(monkeypatch, capsys):
    from ares import cli
    monkeypatch.setattr(sys, "stdout", None)
    assert cli.main([str(PROGRAMS / "hello.s")]) == cli.EXIT_OUTPUT_CLOSED


def test_dialog_to_closed_output_stops_quietly(tmp_path):
    path = tmp_path / "prog.s"
    path.write_text("""\
        .global _start
_start:
        LDR     R0, =line
        SVC     #4
        LDR     R1, =40000000
delay:  SUBS    R1, R1, #1
        BNE     delay
        LDR     R0, =line
        SVC     #50
        SVC     #10
        .data
line:   .asciz  "line\\n"
""")
    proc = subprocess.Popen([sys.executable, "-m", "ares.cli", str(path)], cwd=ROOT,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)       # like 2>&1 | head -1
    try:
        assert proc.stdout.readline().strip() == b"line"
        proc.stdout.close()
        proc.wait(timeout=60)
    finally:
        proc.kill()
    assert proc.returncode == 141


def test_jtag_uart_gets_bytes_before_enter(tmp_path):
    path = tmp_path / "key.s"
    path.write_text("        .global _start\n_start:\n        LDR R1, =0xFF201000\n"
                    "wait:   LDR R0, [R1]\n        TST R0, #0x8000\n        BEQ wait\n"
                    "        STRB R0, [R1]\n        SVC #10\n")
    proc = subprocess.Popen([sys.executable, "-m", "ares.cli", str(path)], cwd=ROOT,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    proc.stdin.write(b"y")                      # no Enter, and stdin stays open
    proc.stdin.flush()
    try:
        proc.wait(timeout=30)
        out = proc.stdout.read()
    finally:
        proc.kill()
    assert out.replace(b"\r\n", b"\n") == b"y\n-- program is finished running --\n"


def test_endless_input_is_not_read_ahead_without_limit():
    from ares import cli
    from ares.console import Console

    class Endless:
        def read(self, size):
            return b"y\n" * (size // 2)

    reader = cli.InputReader(Endless())
    console = Console()
    reader.start()
    time.sleep(0.3)
    assert reader._chunks.qsize() <= cli.READ_CHUNKS
    for _ in range(100):
        reader.feed_available(console)
    assert console.pending() < cli.FEED_LIMIT + 0x10000
    assert console.read_line() == b"y\n"
