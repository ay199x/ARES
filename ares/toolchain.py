# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Location of the bundled GNU assembler and linker, and of the other bundled files."""

import os
import platform
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

ASSEMBLER = "arm-none-eabi-as"
LINKER = "arm-none-eabi-ld"
# Names the folder that holds bin/ with the two programs, in place of the usual one.
TOOLCHAIN_VARIABLE = "ARES_TOOLCHAIN"


class ToolchainMissingError(RuntimeError):
    """The assembler or linker is not installed where ARES expects it."""


def platform_tag(system=None, machine=None):
    """Return the toolchain platform name for this computer.

    One of ``windows-x64``, ``macos-arm64``, ``macos-x86_64`` or ``linux-x86_64``.
    """
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    if system == "Windows" and machine in ("amd64", "x86_64"):
        return "windows-x64"
    if system == "Darwin" and machine in ("arm64", "aarch64"):
        return "macos-arm64"
    if system == "Darwin" and machine == "x86_64":
        return "macos-x86_64"
    if system == "Linux" and machine in ("amd64", "x86_64"):
        return "linux-x86_64"
    raise ToolchainMissingError(f"unsupported platform: {system} {machine}")


def document_path(name):
    """Where the file or folder called name is: next to the program, or inside a packaged
    ARES."""
    bundle = getattr(sys, "_MEIPASS", None)
    return (Path(bundle) if bundle else PROJECT_ROOT) / name


def toolchain_dir():
    """Folder holding ``bin/`` with the assembler and linker."""
    chosen = os.environ.get(TOOLCHAIN_VARIABLE)
    if chosen:
        return Path(chosen)
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle) / "toolchain"
    return PROJECT_ROOT / "vendor" / platform_tag()


def tool_path(name):
    """Full path of a toolchain program; raises if it is missing."""
    exe = name + (".exe" if platform.system() == "Windows" else "")
    path = toolchain_dir() / "bin" / exe
    if not path.is_file():
        raise ToolchainMissingError(
            f"{exe} not found in {path.parent}; run tools/fetch_toolchain.py")
    return path
