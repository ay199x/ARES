# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Help > About ARES, and where the licence and the third-party notices are."""

import tkinter as tk
from tkinter import ttk

from .. import APP_FULL_NAME, APP_NAME, APP_TITLE, credits
from ..toolchain import document_path
from . import icons
from .style import default_button
from .tools.frame import place_over
from .widgets import px

LICENCE = "© 2026 The ARES Project. GPL-2.0-or-later: the License tab of Help has the rest."
ICONS = "Toolbar and menu icons drawn for ARES"
HELMET_FACTOR = 2               # design pixels per pixel of the helmet's grid
MARGIN = (16, 10)               # inside the box, in design pixels: at the sides, above and below
GAP = 15                        # between the helmet and the text
WRAP = 400                      # the width of the text
LINE_GAP = 3                    # under each line of the text
BLANK = 14                      # the height of a blank line
OK_GAP = 6                      # above OK
BULLET = "• "                   # the mark of an advisor's line
MARK = 12                       # the room of a bullet's mark, before its words
MARK_GAP = 4                    # between the mark and the words


def credit_lines():
    """The credits as the box shows them: plain lines, the advisors as bullets."""
    return (credits.CREATED_BY, credits.ADVISORS_HEADING,
            *(BULLET + advisor for advisor in credits.ADVISORS), credits.FIRST_USED)


def read_document(name):
    """The text of the file called name, or a line that says it could not be read."""
    try:
        return document_path(name).read_text(encoding="utf-8")
    except OSError as e:
        return f"{name} could not be read: {e.strerror or e}"


class AboutDialog:
    """Help > About ARES, a message box: the helmet at the left, the text at the right, and one
    OK in the middle under them."""

    def __init__(self, master):
        window = self.window = tk.Toplevel(master)
        window.withdraw()
        window.title(f"About {APP_NAME}")
        window.transient(master)
        window.resizable(False, False)
        side, around = (px(window, size) for size in MARGIN)
        body = ttk.Frame(window, padding=(side, around, side, around))
        body.pack(fill="both", expand=True)
        message = ttk.Frame(body)
        message.pack(side="top", fill="x")
        factor = icons.design_factor(window, HELMET_FACTOR)
        self.helmet = icons.helmet_photo(window, icons.HELMET_32, factor)
        ttk.Label(message, image=self.helmet).pack(side="left", anchor="n",
                                                   padx=(0, px(window, GAP)))
        lines = ttk.Frame(message)
        lines.pack(side="left", anchor="n")
        self.lines = (APP_TITLE, APP_FULL_NAME, "", *credit_lines(), "", LICENCE, ICONS)
        for text in self.lines:
            if text.startswith(BULLET):
                # A bullet: its mark, then its words, whose wrapped lines stay under the words.
                row = ttk.Frame(lines)
                row.pack(side="top", anchor="w", pady=(0, px(window, LINE_GAP)))
                ttk.Label(row, text=BULLET.strip()).grid(row=0, column=0, sticky="nw")
                ttk.Label(row, text=text[len(BULLET):], justify="left",
                          wraplength=px(window, WRAP) - px(window, MARK)).grid(
                    row=0, column=1, sticky="nw", padx=(px(window, MARK_GAP), 0))
            elif text:
                ttk.Label(lines, text=text, wraplength=px(window, WRAP), justify="left").pack(
                    side="top", anchor="w", pady=(0, px(window, LINE_GAP)))
            else:
                ttk.Frame(lines, height=px(window, BLANK)).pack(side="top")
        self.ok_button = ttk.Button(body, text="OK", command=self.close)
        self.ok_button.pack(side="top", pady=(px(window, OK_GAP), 0))
        default_button(self.ok_button, (self.ok_button,))
        for sequence in ("<Return>", "<KP_Enter>"):
            window.bind(sequence, lambda event: self.ok_button.invoke())
        window.bind("<Escape>", lambda event: self.close())
        window.protocol("WM_DELETE_WINDOW", self.close)
        place_over(window, master)
        window.deiconify()
        self.ok_button.focus_set()

    def lift(self):
        self.window.deiconify()
        self.window.lift()
        self.ok_button.focus_set()

    def close(self):
        if self.window is not None:
            self.window.destroy()
            self.window = None
