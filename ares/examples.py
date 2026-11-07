# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The example programs that come with ARES."""

import sys
from pathlib import Path

from .toolchain import document_path

FOLDER = "examples"
SOURCE_SUFFIX = ".s"


def examples_folder():
    """The folder of the examples: next to the program, or inside a packaged ARES."""
    return document_path(FOLDER)


def example_folders():
    """Every folder of the bundled examples: the one ARES reads and, in a folder package, the
    copy beside the program that users see."""
    folders = [examples_folder()]
    if getattr(sys, "frozen", False):
        folders.append(Path(sys.executable).parent / FOLDER)
    return folders


def example_programs():
    """The paths of the example programs, sorted by name; none when the folder is missing."""
    try:
        files = [path for path in examples_folder().iterdir()
                 if path.suffix == SOURCE_SUFFIX and path.is_file()]
    except OSError:
        return []
    return sorted(files, key=lambda path: path.name.lower())
