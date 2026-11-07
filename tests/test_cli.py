# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The command-line runner's output when a program jumps where there is no program code."""

import subprocess
import sys

import pytest
from conftest import ROOT


# DDR3 never written, and the DE1-SoC devices (their registers hold no program).
@pytest.mark.parametrize("target", [0x30000000, 0xFF200000, 0xFF201000], ids=hex)
def test_a_jump_where_there_is_no_program_code_ends_the_run(tmp_path, target):
    source = tmp_path / "jump.s"
    source.write_text(f"        .global _start\n_start:\n        LDR R0, =0x{target:08X}\n"
                      "        BX R0\n")
    proc = subprocess.run([sys.executable, "-m", "ares.cli", str(source)],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 2 and proc.stderr == ""
    assert proc.stdout == (f"Runtime error at address 0x{target:08x}: "
                           f"no program code at 0x{target:08x}\n"
                           "-- program is finished running (runtime error) --\n")
