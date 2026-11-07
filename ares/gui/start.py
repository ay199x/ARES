# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Starting ARES: the splash screen first, then the rest of the program and the main window.

Only what the splash screen needs is imported at the top, so that it shows before the engines
are loaded.
"""

import sys
import tkinter as tk
import traceback
from tkinter import messagebox

from .. import APP_NAME
from .splash import Splash

IMPORTED = 0.25                 # the share of the bar once the program is imported


def dpi_aware():
    """Draw sharply on Windows displays scaled above 100 % (Tk scales itself on macOS)."""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def main(argv=None):
    """Start the window; argv holds files to open."""
    files = sys.argv[1:] if argv is None else argv
    dpi_aware()
    root = tk.Tk(className=APP_NAME)
    root.withdraw()
    splash = Splash(root)
    try:
        from .app import App
        splash.advance(IMPORTED)
        app = App(root, progress=lambda share: splash.advance(IMPORTED + (1 - IMPORTED) * share))
        root.update()                   # the main window is on the screen
    except Exception:
        splash.close()
        messagebox.showerror(APP_NAME, "ARES could not start:\n\n" + traceback.format_exc(),
                             parent=root)
        root.destroy()
        raise
    splash.close()
    # After the splash, which stays on top: a file that cannot be opened shows a message box.
    app.open_paths(files)
    app.editor_changed()
    root.mainloop()
    return 0
