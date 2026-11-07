# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Saving a file so that a failure part of the way leaves the old file as it was."""

import contextlib
import os
import stat
import sys

_NEW_FILE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
_LONG = "\\\\?\\"                       # Windows' prefix for paths over 259 characters


def write_file(path, data):
    """Write data to the file at path so that a failure leaves the file as it was.

    The data goes to a new file in the same folder, which then takes the
    place of the file (of the file a link leads to), with its permissions.
    A file that cannot be written, such as a read-only one, is refused as
    writing it directly would be. The file is written directly where the
    folder refuses new files, and when it has other names (hard links), which
    a new file would leave with the old text.
    """
    path = os.path.realpath(path)
    try:
        os.close(os.open(path, os.O_WRONLY))
        info = os.stat(path)
    except FileNotFoundError:
        info = None
    mode = 0o666 if info is None else stat.S_IMODE(info.st_mode)
    made = None if info is not None and info.st_nlink > 1 else _new_file_beside(path, mode)
    if made is None:
        with open(path, "wb") as f:
            f.write(data)
        return
    handle, temporary = made
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if info is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(temporary)
        raise


def _new_file_beside(path, mode):
    """(handle, path) of a new empty file next to path, or None where the folder refuses one.

    Not tempfile.mkstemp: on Windows, in a folder that refuses new files, it
    takes each refusal for a name in use and tries other names for days. Any
    other failure, such as a full disk, is raised: writing the file in place
    could then lose it.
    """
    for _ in range(100):
        temporary = _long_form(f"{path}.{os.urandom(4).hex()}.tmp")
        try:
            return os.open(temporary, _NEW_FILE, mode), temporary
        except FileExistsError:
            pass
        except PermissionError:
            return None
    return None


def _long_form(path):
    """path in the form Windows accepts beyond 259 characters (it is that long with the
    temporary name's ending, though the file's own path is not)."""
    if sys.platform != "win32" or len(path) < 260 or path.startswith(_LONG):
        return path
    path = os.path.normpath(path)
    if path.startswith("\\\\"):                          # \\server\share\...
        return _LONG + "UNC\\" + path[2:]
    return _LONG + path
