# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Safe saving: a failure leaves the old file as it was."""

import errno
import os
import sys

import pytest

from ares import files
from ares.files import write_file

OLD = b"_start:\n    B _start\n" * 10


def full_disk_for_new_files(monkeypatch):
    """Make the system say the disk is full when a new file is made next to the target."""
    real_open = os.open

    def open_(path, flags, *args):
        if str(path).endswith(".tmp"):
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_open(path, flags, *args)
    monkeypatch.setattr(files.os, "open", open_)


def test_a_full_disk_while_making_the_new_file_keeps_the_old_file(tmp_path, monkeypatch):
    path = tmp_path / "prog.s"
    path.write_bytes(OLD)
    full_disk_for_new_files(monkeypatch)
    with pytest.raises(OSError) as error:
        write_file(path, b"@ new\n" + OLD)
    assert error.value.errno == errno.ENOSPC
    assert path.read_bytes() == OLD and list(tmp_path.iterdir()) == [path]


def test_a_failure_while_writing_keeps_the_old_file(tmp_path, monkeypatch):
    path = tmp_path / "prog.s"
    path.write_bytes(OLD)

    def fail(*args):
        raise OSError(errno.EIO, "Input/output error")
    monkeypatch.setattr(files.os, "fsync", fail)
    with pytest.raises(OSError):
        write_file(path, b"@ new\n")
    assert path.read_bytes() == OLD and list(tmp_path.iterdir()) == [path]


@pytest.mark.skipif(sys.platform != "win32", reason="the 260-character limit is Windows'")
def test_a_long_path_is_saved_through_a_new_file_too(tmp_path, monkeypatch):
    folder = tmp_path
    while len(str(folder)) < 200:
        folder = folder / ("d" * min(40, 210 - len(str(folder))))
    folder.mkdir(parents=True)
    path = folder / ("f" * (250 - len(str(folder)) - 3) + ".s")
    assert len(str(path)) <= 259 < len(str(path) + ".12345678.tmp")    # only the new file's
    path.write_bytes(OLD)
    write_file(path, b"@ one\n" + OLD)
    assert path.read_bytes() == b"@ one\n" + OLD and list(folder.iterdir()) == [path]

    def fail(*args):
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(files.os, "fsync", fail)
    with pytest.raises(OSError):
        write_file(path, b"@ two\n")
    assert path.read_bytes() == b"@ one\n" + OLD and list(folder.iterdir()) == [path]


def test_saving_a_file_with_another_name_keeps_both_names_the_same_file(tmp_path):
    first, second = tmp_path / "first.s", tmp_path / "second.s"
    first.write_bytes(OLD)
    try:
        os.link(first, second)
    except OSError:
        pytest.skip("hard links cannot be made here")
    write_file(second, b"@ new\n")
    assert first.read_bytes() == b"@ new\n" and os.path.samefile(first, second)


def test_a_new_file_is_written(tmp_path):
    path = tmp_path / "new.s"
    write_file(path, b"NOP\n")
    assert path.read_bytes() == b"NOP\n" and list(tmp_path.iterdir()) == [path]
