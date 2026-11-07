# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Command-line runner: ``python -m ares.cli program.s``.

Assembles the program, runs it at full speed and writes its Run I/O to
standard output. Typed input for the read services and the JTAG UART comes
from standard input. Assembler messages, run-time warnings and dialogs go to
standard error; dialogs are answered on standard input.
Exit status: 0 finished, 1 assembly failed, 2 runtime error, 130 interrupted
(Ctrl+C), 141 standard output was closed.
"""

import argparse
import io
import os
import queue
import signal
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import syscalls
from .assembler import assemble
from .console import Console
from .machine import Machine, StopReason
from .program import Program
from .runner import Runner, State
from .toolchain import ToolchainMissingError

EXIT_FINISHED = 0
EXIT_ASSEMBLY_FAILED = 1
EXIT_RUNTIME_ERROR = 2
EXIT_INTERRUPTED = 130
EXIT_OUTPUT_CLOSED = 141

READ_CHUNKS = 4                 # chunks of up to 64 KB read ahead of the program
FEED_LIMIT = 0x10000            # typed bytes passed on before the program takes them


class OutputClosed(Exception):
    """Standard output can no longer be written (e.g. ``| head`` has ended)."""


def standard_input():
    """An unbuffered binary stream on standard input, or None.

    The reader thread must not use sys.stdin: a thread waiting inside its
    buffered reader makes Python abort when the program exits. On a Windows
    console the raw stream still delivers UTF-8.
    """
    try:
        return io.open(sys.stdin.fileno(), "rb", buffering=0, closefd=False)
    except (AttributeError, OSError, ValueError):
        return None


class InputReader:
    """Standard input, read in the background once the program wants input.

    Whatever arrives is passed on at once, so the JTAG UART sees each typed
    byte; the console splits it into lines for the read services. A CR LF line
    end (Windows) becomes LF, as Enter is in the window.
    """

    def __init__(self, stream, interrupted=None):
        self._stream = stream
        self._interrupted = interrupted or threading.Event()
        self._chunks = queue.Queue(maxsize=READ_CHUNKS)    # so an endless input waits
        self._thread = None
        self.ended = stream is None

    def start(self):
        if self._thread is None and not self.ended:
            self._thread = threading.Thread(target=self._read, daemon=True)
            self._thread.start()

    def _read(self):
        carry = b""                     # a CR that may be half of a CR LF
        try:
            while True:
                data = self._stream.read(0x10000)
                if not data:
                    break
                data = carry + data
                carry = b"\r" if data.endswith(b"\r") else b""
                data = data[:len(data) - len(carry)].replace(b"\r\n", b"\n")
                if data:
                    self._chunks.put(data)
        except (OSError, ValueError):
            pass
        if carry:
            self._chunks.put(carry)
        self._chunks.put(None)

    def _deliver(self, chunk, console):
        if chunk is None:
            self.ended = True
            console.close_input()
        else:
            console.feed(chunk)

    def feed_available(self, console):
        """Pass on what has been read so far (the JTAG UART polls for it)."""
        while (self._thread is not None and not self.ended
               and console.pending() < FEED_LIMIT):
            try:
                chunk = self._chunks.get_nowait()
            except queue.Empty:
                return
            self._deliver(chunk, console)

    def wait_for_line(self, console):
        """Pass on input until console holds a whole line or the input has ended."""
        self.start()
        while not console.has_line():
            if self.ended:
                console.close_input()
                break
            if self._interrupted.is_set():
                raise KeyboardInterrupt
            try:
                chunk = self._chunks.get(timeout=0.1)
            except queue.Empty:
                continue
            self._deliver(chunk, console)


def dialog_handler(next_line, err):
    """Answer dialog services in the terminal."""
    def answer(request):
        text = syscalls.dialog_text(request)
        confirm = request.dialog == syscalls.CONFIRM
        asks = confirm or request.dialog in syscalls.INPUT_DIALOGS
        _report(err, f"{text} [y/n/c]" if confirm else text)
        if not asks:
            return None
        line = next_line()
        if line is None:
            return 2 if confirm else None
        line = line.decode("utf-8", errors="replace").rstrip("\r\n")
        if confirm:
            return {"y": 0, "n": 1}.get(line.strip()[:1].lower(), 2)
        return line
    return answer


def _write(stream, text):
    """Write and flush; raises OutputClosed when the stream cannot be written."""
    if text:
        try:
            stream.write(text)
            stream.flush()
        except (AttributeError, OSError, ValueError) as e:
            # None when Python started without the stream; EINVAL on Windows or
            # BrokenPipeError elsewhere when the reader has gone.
            raise OutputClosed from e


def _report(err, text):
    """A line on standard error (messages, warnings, dialogs); dropped if there is none."""
    if err is not None:
        _write(err, text + "\n")


def _use_utf8(stream, errors):
    """Run I/O is UTF-8 text, also when the output is redirected to a file."""
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors=errors)


def _drop_output():
    """Send what is still buffered for a closed output nowhere."""
    for stream in (sys.stdout, sys.stderr):
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), stream.fileno())
        except (AttributeError, OSError, ValueError):
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m ares.cli",
        description="Assemble and run an ARMv7 assembly program.")
    parser.add_argument("source", help="assembly source file (.s)")
    args = parser.parse_args(argv)

    out, err = sys.stdout, sys.stderr
    _use_utf8(out, "replace")
    _use_utf8(err, "backslashreplace")
    # Ctrl+C only sets a flag, checked between steps of the work: a
    # KeyboardInterrupt raised inside a Unicorn callback would be lost.
    interrupted = threading.Event()
    on_main_thread = threading.current_thread() is threading.main_thread()
    if on_main_thread:
        previous = signal.signal(signal.SIGINT, lambda signum, frame: interrupted.set())
    try:
        return _assemble_and_run(Path(args.source), out, err, interrupted)
    except OutputClosed:
        _drop_output()
        return EXIT_OUTPUT_CLOSED
    finally:
        if on_main_thread:
            signal.signal(signal.SIGINT,
                          previous if previous is not None else signal.default_int_handler)


def _assemble_and_run(path, out, err, interrupted):
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        _report(err, f"Error: cannot read {path}: {e.strerror}")
        return EXIT_ASSEMBLY_FAILED

    try:
        with tempfile.TemporaryDirectory(prefix="ares-") as work:
            result = assemble(source, work, display_name=str(path), cancel=interrupted)
            if interrupted.is_set():        # Ctrl+C also stops the assembler
                return EXIT_INTERRUPTED
            for message in result.messages:
                _report(err, message.format())
            if not result.ok:
                return EXIT_ASSEMBLY_FAILED
            program = Program(result.elf_path)
    except ToolchainMissingError as e:
        _report(err, f"Error: {e}")
        return EXIT_ASSEMBLY_FAILED

    reader = InputReader(standard_input(), interrupted)
    console = Console(keep_text=False)
    console.input_wanted = reader.start
    machine = Machine(program, console, base_dir=path.resolve().parent)

    def wait_for_line(request=None):
        reader.wait_for_line(console)
        return b""                      # the console already holds the input

    def next_line():
        reader.wait_for_line(console)
        return console.read_line() or None

    runner = Runner(machine, dialogs=dialog_handler(next_line, err),
                    input_source=wait_for_line)

    def flush():
        _write(out, console.take())
        for warning in machine.take_warnings():
            _report(err, warning)

    runner.go()
    try:
        while runner.state in (State.RUNNING, State.WAITING):
            if interrupted.is_set():
                raise KeyboardInterrupt
            reader.feed_available(console)
            runner.run_slice()
            flush()
            delay = runner.sleep_remaining()
            if delay:
                time.sleep(min(delay, 0.05))
        flush()
    except KeyboardInterrupt:
        runner.stop()
        try:
            flush()
        except OutputClosed:
            _drop_output()
        return EXIT_INTERRUPTED
    except OutputClosed:
        runner.stop()
        raise
    if machine.stop_reason is StopReason.ERROR:
        return EXIT_RUNTIME_ERROR
    return EXIT_FINISHED


if __name__ == "__main__":
    sys.exit(main())
