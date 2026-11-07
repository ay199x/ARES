# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Assemble and link a program with the bundled GNU assembler and linker."""

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from . import capitals
from .toolchain import ASSEMBLER, LINKER, tool_path

# The options CPUlator's ARMv7 system uses, so the same programs assemble.
AS_OPTIONS = ["-mfloat-abi=softfp", "-march=armv7-a", "-mcpu=cortex-a9",
              "-mfpu=neon-fp16", "--gdwarf2"]
LINKER_SCRIPT = Path(__file__).resolve().parent / "data" / "ares.ld"

SOURCE_NAME = "prog.s"
OBJECT_NAME = "prog.o"
ELF_NAME = "prog.elf"
TOOL_TIMEOUT = 60

ERROR = "error"
WARNING = "warning"
INFO = "info"


@dataclass(frozen=True)
class Message:
    """One assembler or linker message."""
    file: Optional[str]
    line: Optional[int]
    severity: str
    text: str

    def format(self):
        """Text for the messages pane, e.g. ``Error in prog.s line 3: ...``."""
        kind = self.severity.capitalize()
        if self.file and self.line:
            return f"{kind} in {self.file} line {self.line}: {self.text}"
        if self.file:
            return f"{kind} in {self.file}: {self.text}"
        return f"{kind}: {self.text}"


@dataclass
class AssembleResult:
    ok: bool
    messages: List[Message] = field(default_factory=list)
    elf_path: Optional[Path] = None

    @property
    def errors(self):
        return [m for m in self.messages if m.severity == ERROR]


_SEVERITIES = {"error": ERROR, "fatal error": ERROR, "warning": WARNING, "info": INFO}

_AS_WITH_LINE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):\s*(?P<sev>Error|Fatal error|Warning|Info): (?P<text>.*)$")
_AS_WITHOUT_LINE = re.compile(
    r"^(?P<file>.+?):\s*(?P<sev>Error|Fatal error|Warning|Info): (?P<text>.*)$")
_AS_PLAIN = re.compile(r"^(?P<sev>Error|Fatal error|Warning|Info): (?P<text>.*)$")

_LD_PREFIX = re.compile(r"^(?:.*[\\/])?[\w.-]*ld(?:\.exe)?: ", re.IGNORECASE)
_LD_WITH_LINE = re.compile(r"^(?P<file>.+?):(?P<line>\d+):\(.*?\): (?P<text>.*)$")
_LD_WITH_SECTION = re.compile(r"^(?P<file>.+?):\(.*?\): (?P<text>.*)$")
_LD_CONTEXT = re.compile(r"^.+?: in function `.*':$")
_LD_SEVERITY = re.compile(r"^(?P<sev>warning|error|fatal error): (?P<text>.*)$", re.IGNORECASE)
_LD_NO_ENTRY = re.compile(
    r"^cannot find entry symbol _start; defaulting to (?P<address>[0-9a-fA-F]+)$")

# Shown instead of the linker's warning; the program then starts at the ELF entry.
NO_START_WARNING = ("No global _start label: execution starts at address 0x{:08x}. "
                    "Add .global _start and _start: before your first instruction.")


def _display(file, display_name):
    """Show the working copy of the source under the user's file name."""
    if file is None:
        return None
    if Path(file).name in (SOURCE_NAME, OBJECT_NAME):
        return display_name
    return file


def parse_assembler_output(output, display_name=SOURCE_NAME):
    """Turn the assembler's error output into Message records."""
    messages = []
    for raw in output.splitlines():
        line = raw.rstrip()
        m = _AS_WITH_LINE.match(line)
        if m:
            messages.append(Message(_display(m["file"], display_name), int(m["line"]),
                                    _SEVERITIES[m["sev"].lower()], m["text"]))
            continue
        m = _AS_WITHOUT_LINE.match(line) or _AS_PLAIN.match(line)
        if m:
            file = m.groupdict().get("file")
            messages.append(Message(_display(file, display_name), None,
                                    _SEVERITIES[m["sev"].lower()], m["text"]))
    return messages


def parse_linker_output(output, display_name=SOURCE_NAME):
    """Turn the linker's error output into Message records."""
    messages = []
    for raw in output.splitlines():
        line = _LD_PREFIX.sub("", raw.rstrip(), count=1)
        if not line or _LD_CONTEXT.match(line):
            continue
        file = line_no = None
        m = _LD_WITH_LINE.match(line)
        if m:
            file, line_no, line = m["file"], int(m["line"]), m["text"]
        else:
            m = _LD_WITH_SECTION.match(line)
            if m:
                file, line = m["file"], m["text"]
        severity = ERROR
        m = _LD_SEVERITY.match(line)
        if m:
            severity = _SEVERITIES[m["sev"].lower()]
            line = m["text"]
        m = _LD_NO_ENTRY.match(line)
        if m:
            messages.append(Message(display_name, None, WARNING,
                                    NO_START_WARNING.format(int(m["address"], 16))))
            continue
        messages.append(Message(_display(file, display_name), line_no, severity, line))
    return messages


class _Stopped(Exception):
    """A tool did not run to its end; the text says why."""


def _run(args, cwd, tool, cancel):
    """(exit code, stdout, stderr) of a tool; raises _Stopped when it cannot finish.

    The tool is stopped when cancel (a threading.Event) is set, or after
    TOOL_TIMEOUT seconds.
    """
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    env = dict(os.environ, LC_ALL="C", LANG="C")
    try:
        proc = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, creationflags=flags)
    except OSError as e:
        raise _Stopped(f"cannot start the {tool}: {e.strerror or e}") from e
    deadline = time.monotonic() + TOOL_TIMEOUT
    while True:
        try:
            out, err = proc.communicate(timeout=0.1)
            return proc.returncode, out, err
        except subprocess.TimeoutExpired:
            if cancel is not None and cancel.is_set():
                reason = "assembling was cancelled"
            elif time.monotonic() > deadline:
                reason = f"the {tool} did not finish within {TOOL_TIMEOUT} seconds"
            else:
                continue
            proc.kill()
            proc.communicate()
            raise _Stopped(reason)


def _decode(data):
    return data.decode("utf-8", errors="replace")


def assemble(source, workdir, display_name=SOURCE_NAME, require_capitals=True,
             cancel=None):
    """Assemble and link source text inside workdir.

    With ``require_capitals`` the capital-letters rule is checked first, and
    lines that break it are reported without running the assembler. Setting
    ``cancel`` (a threading.Event) stops the assembler or linker.
    Returns an AssembleResult; ``elf_path`` is set when both steps succeed.
    """
    try:
        return _assemble(source, Path(workdir), display_name, require_capitals, cancel)
    except _Stopped as stopped:
        return AssembleResult(False, [Message(display_name, None, ERROR, str(stopped))])


def _assemble(source, workdir, display_name, require_capitals, cancel):
    workdir.mkdir(parents=True, exist_ok=True)
    if not source.endswith("\n"):
        source += "\n"
    (workdir / SOURCE_NAME).write_text(source, encoding="utf-8", newline="\n")
    for name in (OBJECT_NAME, ELF_NAME):
        (workdir / name).unlink(missing_ok=True)

    if require_capitals:
        messages = [Message(display_name, o.line, ERROR, o.message)
                    for o in capitals.offences(source)]
        if messages:
            return AssembleResult(False, messages)

    code, out, err = _run([str(tool_path(ASSEMBLER)), *AS_OPTIONS, "-o", OBJECT_NAME,
                           SOURCE_NAME], workdir, "assembler", cancel)
    messages = parse_assembler_output(_decode(err) + _decode(out), display_name)
    if code != 0 or any(m.severity == ERROR for m in messages):
        if not any(m.severity == ERROR for m in messages):
            messages.append(Message(display_name, None, ERROR,
                                    f"assembler failed with exit code {code}"))
        return AssembleResult(False, messages)

    try:
        code, out, err = _run([str(tool_path(LINKER)), "--script", str(LINKER_SCRIPT),
                               "-e", "_start", "-u", "_start", "-o", ELF_NAME, OBJECT_NAME],
                              workdir, "linker", cancel)
    except _Stopped as stopped:
        return AssembleResult(False, messages + [Message(display_name, None, ERROR,
                                                         str(stopped))])
    link_messages = parse_linker_output(_decode(err) + _decode(out), display_name)
    messages.extend(link_messages)
    if code != 0 or any(m.severity == ERROR for m in link_messages):
        if not any(m.severity == ERROR for m in link_messages):
            messages.append(Message(None, None, ERROR,
                                    f"linker failed with exit code {code}"))
        return AssembleResult(False, messages)
    return AssembleResult(True, messages, workdir / ELF_NAME)
