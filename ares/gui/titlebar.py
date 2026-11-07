# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""ARES's icon in the system's title bars and the taskbar.

set_icon() puts it in place of Tk's. The title bars themselves stay the
system's own, light with dark text.
"""

import ctypes
import functools
import sys

from . import icons
from .widgets import is_aqua

# Windows' numbers for a window's icons.
WM_SETICON = 0x0080
ICON_SMALL, ICON_BIG = 0, 1
SM_CXICON, SM_CXSMICON = 11, 49
GCLP_HICON, GCLP_HICONSM = -14, -34
ICON_VERSION = 0x00030000           # the format of the picture CreateIconFromResourceEx takes


def set_icon(root, pictures):
    """Make pictures (PhotoImages, the smallest first) the icon of root's windows.

    Windows made later get them too. The caller keeps the pictures. On
    macOS nothing changes: the Dock shows the application's own icon, and
    title bars have none.

    Tk 8.6 on Windows takes for the title bar the picture that is exactly
    16 pixels, for the taskbar the one of 32, and else the first one. It
    makes the frames of all its windows from one window class; given the
    icon before that class exists (it is made with the first frame), Tk
    makes the class with the taskbar's picture alone, and Windows shrinks
    that one for the title bar. So once the main window is shown the icon
    is given again: to the class, and to the window, which Windows then
    draws with it at once. Above 100 % Windows would smooth Tk's two
    pictures to the sizes it draws, so exact_icons() then gives it those.
    """
    if is_aqua(root):
        return
    root.iconphoto(True, *pictures)
    if sys.platform != "win32":
        return
    # Only the main window has its class: the binding sees the window's own <Map> alone.
    tag = root.winfo_class()

    def shown():
        root.tk.call("bind", tag, "<Map>", "")
        root.iconphoto(True, *pictures)
        root.iconphoto(False, *pictures)        # this window's, drawn at once
        exact_icons(root)
    root.tk.call("bind", tag, "<Map>", root.register(shown))


@functools.cache
def _user32():
    """Windows' user32 with the functions exact_icons() calls, or None where it is missing."""
    try:
        user32 = ctypes.WinDLL("user32")
    except (AttributeError, OSError):
        return None
    pointer, size = ctypes.c_void_p, ctypes.c_size_t
    user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.CreateIconFromResourceEx.argtypes = (
        ctypes.c_char_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32, ctypes.c_int,
        ctypes.c_int, ctypes.c_uint)
    user32.CreateIconFromResourceEx.restype = pointer
    user32.SendMessageW.argtypes = (pointer, ctypes.c_uint, size, pointer)
    user32.SendMessageW.restype = pointer
    user32.SetClassLongPtrW.argtypes = (pointer, ctypes.c_int, pointer)
    user32.SetClassLongPtrW.restype = pointer
    return user32


def exact_icons(root):
    """Give root's windows the helmet at exactly the sizes Windows draws it at.

    Those are 16 and 32 pixels at 100 %, and the display's scale times those
    above it: a picture of another size is smoothed by Windows. Each is
    given to the main window and to the class of all Tk's frames, which
    the windows made later use. The icons live until ARES ends. Errors are
    ignored: the windows keep Tk's icon.
    """
    user32 = _user32()
    if user32 is None:
        return
    frame = int(root.tk.call("wm", "frame", root), 16)
    for which, metric, index in ((ICON_SMALL, SM_CXSMICON, GCLP_HICONSM),
                                 (ICON_BIG, SM_CXICON, GCLP_HICON)):
        size = user32.GetSystemMetrics(metric)
        data = icons.window_png(size)
        handle = user32.CreateIconFromResourceEx(data, len(data), True, ICON_VERSION, size, size,
                                                 0)
        if handle:
            user32.SendMessageW(frame, WM_SETICON, which, handle)
            user32.SetClassLongPtrW(frame, index, handle)
