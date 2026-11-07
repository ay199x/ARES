# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Dialog windows: settings, input and dialogs for the program, memory map and dump."""

import struct
import tkinter as tk
from tkinter import filedialog, ttk
from tkinter import font as tkfont

from .. import APP_NAME, syscalls
from ..files import write_file
from ..machine import (DDR_BASE, DDR_END, DEVICES_BASE, DEVICES_SIZE, JTAG_UART, JTAG_UART_SIZE,
                       ONCHIP_BASE)
from ..settings import FONT_SIZES, TAB_SIZES, installed_family
from .style import default_button, sunken
from .table import STRIPE, WHITE, Column, Row, Table, column_width
from .tools.frame import place_over
from .widgets import px

SAMPLE = "_start:  MOV R0, #42    @ 0123456789"


def font_families(widget):
    """Installed font families, sorted; vertical CJK variants (named @...) are left out."""
    return sorted({f for f in tkfont.families(widget) if not f.startswith("@")}, key=str.lower)


class EditorFontDialog:
    """Settings > Editor Font...: font family and size, tab width, and what Tab inserts.

    on_apply() is called after OK has stored valid values in settings.
    """

    def __init__(self, master, settings, on_apply):
        self.settings = settings
        self.on_apply = on_apply
        window = self.window = tk.Toplevel(master)
        window.withdraw()
        window.title("Editor Font")
        window.transient(master)
        window.resizable(False, False)
        self.families = font_families(window)
        # The family the editor really draws with, where the default one is not installed.
        family = installed_family(settings.font_family, set(tkfont.families(window)))
        self.family = tk.StringVar(master=window, value=family)
        self.size = tk.StringVar(master=window, value=str(settings.font_size))
        self.tab_size = tk.StringVar(master=window, value=str(settings.tab_size))
        self.tab_spaces = tk.BooleanVar(master=window, value=settings.tab_spaces)
        self.preview_font = tkfont.Font(root=window, family=family, size=settings.font_size)

        gap = px(window, 6)
        body = ttk.Frame(window, padding=px(window, 12))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, pad=2 * gap)        # space between the labels and the fields
        ttk.Label(body, text="Font:").grid(row=0, column=0, sticky="w", pady=gap)
        self.family_box = ttk.Combobox(body, textvariable=self.family, values=self.families,
                                       state="readonly", width=28)
        self.family_box.grid(row=0, column=1, columnspan=2, sticky="we", pady=gap)
        ttk.Label(body, text="Size:").grid(row=1, column=0, sticky="w", pady=gap)
        ttk.Spinbox(body, textvariable=self.size, from_=FONT_SIZES.start,
                    to=FONT_SIZES.stop - 1, width=5).grid(row=1, column=1, sticky="w", pady=gap)
        ttk.Label(body, text="Tab width:").grid(row=2, column=0, sticky="w", pady=gap)
        ttk.Spinbox(body, textvariable=self.tab_size, from_=TAB_SIZES.start,
                    to=TAB_SIZES.stop - 1, width=5).grid(row=2, column=1, sticky="w", pady=gap)
        ttk.Checkbutton(body, text="Tab key inserts spaces", variable=self.tab_spaces).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=gap)
        field = sunken(ttk.Frame(body))
        field.grid(row=4, column=0, columnspan=3, sticky="we", pady=gap)
        self.preview = tk.Label(field, text=SAMPLE, font=self.preview_font, anchor="w",
                                background="#FFFFFF", foreground="#000000", borderwidth=0,
                                padx=gap, pady=gap)
        self.preview.pack(fill="x")
        self.status = ttk.Label(body, text="", foreground="#B00000")
        self.status.grid(row=5, column=0, columnspan=3, sticky="w")
        buttons = ttk.Frame(body)
        buttons.grid(row=6, column=0, columnspan=3, sticky="e", pady=(gap, 0))
        ok = ttk.Button(buttons, text="OK", command=self.ok)
        ok.pack(side="left", padx=(0, gap))
        cancel = ttk.Button(buttons, text="Cancel", command=self.cancel)
        cancel.pack(side="left")
        # Return presses the button that has the focus, else OK: it has the black frame.
        default_button(ok, (ok, cancel))
        body.columnconfigure(2, weight=1)

        for var in (self.family, self.size):
            var.trace_add("write", self._update_preview)
        window.bind("<Return>", self._return)
        window.bind("<KP_Enter>", self._return)
        window.bind("<Escape>", lambda event: self.cancel())
        window.protocol("WM_DELETE_WINDOW", self.cancel)
        place_over(window, master)
        window.deiconify()
        window.grab_set()
        self.family_box.focus_set()

    def _values(self):
        """(family, size, tab size) when all are valid, else None."""
        try:
            size, tab_size = int(self.size.get()), int(self.tab_size.get())
        except ValueError:
            return None
        family = self.family.get()
        if size not in FONT_SIZES or tab_size not in TAB_SIZES or not family.strip():
            return None
        return family, size, tab_size

    def _update_preview(self, *args):
        values = self._values()
        if values is not None:
            self.preview_font.configure(family=values[0], size=values[1])

    def _return(self, event):
        """Return presses the button that has the focus, else OK (ttk buttons ignore Return)."""
        if isinstance(event.widget, ttk.Button):
            event.widget.invoke()
        else:
            self.ok()

    def ok(self):
        values = self._values()
        if values is None:
            self.status.configure(text=f"Size must be {FONT_SIZES.start} to "
                                       f"{FONT_SIZES.stop - 1} and tab width "
                                       f"{TAB_SIZES.start} to {TAB_SIZES.stop - 1}.")
            self.window.bell()
            return
        s = self.settings
        s.font_family, s.font_size, s.tab_size = values
        s.tab_spaces = self.tab_spaces.get()
        self.window.destroy()
        self.on_apply()

    def cancel(self):
        self.window.destroy()


def _field_text(entry):
    """The text typed in an entry, without halves of surrogate pairs.

    Tk 8.6 keeps a character beyond U+FFFF as two halves, and its BackSpace
    and Delete take away only one of them.
    """
    return "".join(char for char in entry.get() if not "\ud800" <= char <= "\udfff")


class LineDialog:
    """Asks for one line of input for the program (Settings > Popup Dialog for Input).

    on_done(line) is called with the typed line after OK, or with None after
    Cancel, Escape or closing the window; close() closes it without a call.
    Once it is closed, text holds what was typed in it. A line break pasted
    into it ends the line, as Return does: rest then holds the text after
    it (typed ahead of the next read), else it is empty.
    It does not take a grab: the window's Pause, Stop, Reset and Backstep
    still work, and close it.
    """

    def __init__(self, master, title, prompt, on_done, text=""):
        self.on_done = on_done
        self.text = text
        self.rest = ""
        window = self.window = tk.Toplevel(master)
        window.withdraw()
        window.title(title)
        window.transient(master)
        window.resizable(False, False)
        gap = px(window, 6)
        body = ttk.Frame(window, padding=px(window, 12))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=prompt).pack(anchor="w")
        self.entry = ttk.Entry(body, width=40)
        self.entry.insert(0, text)
        self.entry.pack(fill="x", pady=gap)
        buttons = ttk.Frame(body)
        buttons.pack(anchor="e")
        ok = ttk.Button(buttons, text="OK", command=self.ok)
        ok.pack(side="left", padx=(0, gap))
        cancel = ttk.Button(buttons, text="Cancel", command=self.cancel)
        cancel.pack(side="left")
        # Return presses the button that has the focus, else OK: it has the black frame.
        default_button(ok, (ok, cancel))
        window.bind("<Return>", self._return)
        window.bind("<KP_Enter>", self._return)
        window.bind("<Escape>", lambda event: self.cancel())
        window.bind("<<Paste>>", self._pasted)              # after the field's own paste
        window.bind("<<PasteSelection>>", self._pasted)
        window.protocol("WM_DELETE_WINDOW", self.cancel)
        place_over(window, master)
        window.deiconify()
        self.entry.focus_set()

    def _return(self, event):
        """Return presses the button that has the focus, else OK (ttk buttons ignore Return)."""
        if isinstance(event.widget, ttk.Button):
            event.widget.invoke()
        else:
            self.ok()

    def _pasted(self, event):
        """A line break pasted into the field ends the line, as Return does."""
        if "\n" in self.entry.get():
            self.ok()

    def ok(self):
        line, _, self.rest = _field_text(self.entry).partition("\n")
        self._finish(line)

    def cancel(self):
        self._finish(None)

    def close(self):
        """Close the window without an answer (the program no longer waits)."""
        if self.window is not None:
            self.text = _field_text(self.entry)
            self.window.destroy()
            self.window = None

    def _finish(self, line):
        if self.window is not None:
            self.close()
            self.on_done(line)


MESSAGE_ICONS = {0: "message_error", 1: "message_information", 2: "message_warning",
                 3: "message_question"}
DIALOG_ICON_SIZE = 32       # icons of the dialogs a program asks for, in design pixels


class ServiceDialog:
    """A dialog window a program asked for with SVC #50 to #59 (an ares.machine.Request).

    on_answer(value) is called once with the answer: 0, 1 or 2 for Yes, No
    and Cancel of the confirm dialog; the typed text, or None after Cancel,
    for the input dialogs; None for a message. close() closes the window
    without a call (the program no longer waits). images holds the icons by
    name (MESSAGE_ICONS). Like LineDialog it takes no grab.
    """

    def __init__(self, master, request, on_answer, images):
        self.on_answer = on_answer
        self.kind = kind = request.dialog
        window = self.window = tk.Toplevel(master)
        window.withdraw()
        window.title(APP_NAME)
        window.transient(master)
        window.resizable(False, False)
        gap = px(window, 8)
        body = ttk.Frame(window, padding=px(window, 14))
        body.pack(fill="both", expand=True)
        if kind == syscalls.MESSAGE:
            icon = MESSAGE_ICONS.get(request.value, "message_information")
        elif kind in syscalls.VALUE_MESSAGES:
            icon = "message_information"
        else:
            icon = "message_question"
        ttk.Label(body, image=images[icon]).grid(row=0, column=0, rowspan=2, sticky="n",
                                                 padx=(0, 2 * gap))
        self.text = syscalls.dialog_text(request)
        ttk.Label(body, text=self.text, wraplength=px(window, 420), justify="left").grid(
            row=0, column=1, sticky="w")
        self.entry = None
        if kind in syscalls.INPUT_DIALOGS:
            self.entry = ttk.Entry(body, width=40)
            self.entry.grid(row=1, column=1, sticky="we", pady=(gap, 0))
        if kind == syscalls.CONFIRM:
            answers = (("Yes", 0), ("No", 1), ("Cancel", 2))
            self.cancel_value = 2
        elif self.entry is not None:
            answers = (("OK", ...), ("Cancel", None))
            self.cancel_value = None
        else:
            answers = (("OK", None),)
            self.cancel_value = None
        buttons = ttk.Frame(body)
        buttons.grid(row=2, column=0, columnspan=2, sticky="e", pady=(2 * gap, 0))
        self.buttons = {}
        for label, value in answers:
            button = ttk.Button(buttons, text=label, command=lambda v=value: self.answer(v))
            button.pack(side="left", padx=(gap, 0))
            self.buttons[label] = button
        # Return presses the button that has the focus, else the first one: it has the
        # black frame.
        default_button(self.buttons[answers[0][0]], self.buttons.values())
        window.bind("<Return>", self._return)
        window.bind("<KP_Enter>", self._return)
        window.bind("<Escape>", lambda event: self.answer(self.cancel_value))
        window.protocol("WM_DELETE_WINDOW", lambda: self.answer(self.cancel_value))
        place_over(window, master)
        window.deiconify()
        (self.entry or self.buttons[answers[0][0]]).focus_set()

    def _return(self, event):
        """Return presses the button that has the focus, else the first one."""
        if isinstance(event.widget, ttk.Button):
            event.widget.invoke()
        else:
            next(iter(self.buttons.values())).invoke()

    def answer(self, value):
        """Close the window and give the answer (... is the typed text)."""
        if self.window is None:
            return
        if value is ...:
            value = _field_text(self.entry)
        self.close()
        self.on_answer(value)

    def close(self):
        """Close the window without an answer."""
        if self.window is not None:
            self.window.destroy()
            self.window = None


# Tools > Memory Map: (first address, last address, contents); None for the program's sections.
# A line of the contents after the first is a row of its own, indented, without addresses and
# in its entry's colour; each is kept no wider than the devices' row, so that it does not widen
# the window. The on-chip memory's rows say how the stack starts there.
MEMORY_MAP = [
    (DDR_BASE, DDR_END - 1, "DDR3 memory, 1 GB (the program, its data and the heap)"),
    None,
    (DEVICES_BASE, DEVICES_BASE + DEVICES_SIZE - 1,
     "DE1-SoC devices: writes are ignored and reads give 0, except for the JTAG UART"),
    (JTAG_UART, JTAG_UART + JTAG_UART_SIZE - 1, "JTAG UART: data register, then control register"),
    (ONCHIP_BASE, 0xFFFFFFFF,
     "On-chip memory, 64 KB (the stack): SP starts at 0x00000000, so\n"
     "the first PUSH wraps around and stores at 0xfffffffc, the top of\n"
     "the on-chip memory, as in CPUlator. A program that sets SP itself,\n"
     "for example LDR SP, =0x3FFFFFF8, puts its stack in DDR3 instead."),
]
# The rows under another row start with INDENT: the program's parts, and a text's further lines.
INDENT = "    "


class MemoryMapDialog:
    """Tools > Memory Map: the memory of the simulated DE1-SoC computer, the program's parts
    and SP's value now.

    sp_now() gives SP's value now (its start value while no program is loaded);
    refresh() shows it again, which draws the line only when the value changed.
    """

    def __init__(self, master, program, font, sp_now):
        self.font = font
        self.sp_now = sp_now
        self.sp_shown = None            # the value the SP line shows
        window = self.window = tk.Toplevel(master)
        window.withdraw()
        window.title("Memory Map")
        window.transient(master)
        self.table = Table(window, [
            Column("range", "Addresses", column_width(window, font, 23, "Addresses")),
            Column("contents", "Contents", column_width(window, font, 40, "Contents"),
                   stretch=True),
        ], font)
        self.table.pack(fill="both", expand=True, padx=px(window, 8), pady=px(window, 8))
        self.sp_line = ttk.Label(window)
        self.sp_line.pack(anchor="w", padx=px(window, 8), pady=(0, px(window, 8)))
        self.close_button = ttk.Button(window, text="Close", command=self.close)
        self.close_button.pack(pady=(0, px(window, 8)))
        # Return presses Close, which has the black frame; in the table as well, which would
        # otherwise keep Return for its selected row.
        default_button(self.close_button, (self.close_button,))
        self.show_program(program)
        for widget in (window, self.table.body):
            widget.bind("<Return>", self._return)
            widget.bind("<KP_Enter>", self._return)
        window.bind("<Escape>", lambda event: self.close())
        window.protocol("WM_DELETE_WINDOW", self.close)
        place_over(window, master)
        window.deiconify()
        self.close_button.focus_set()

    def _return(self, event):
        """Return presses Close, the only button (ttk buttons ignore Return)."""
        self.close_button.invoke()
        return "break"

    def show_program(self, program):
        """Show the map with the parts of program (None: the map alone), and SP's value now."""
        rows = []
        for entry in MEMORY_MAP:
            if entry is not None:
                first, last, text = entry
                head, *more = text.split("\n")
                rows.append((f"0x{first:08x} - 0x{last:08x}", head))
                rows.extend(("", INDENT + line) for line in more)
            elif program is not None:
                for section in program.sections:
                    last = section.end - 1 if section.size else section.address
                    rows.append((f"0x{section.address:08x} - 0x{last:08x}",
                                 f"{INDENT}{section.name} of the program, {section.size} bytes"))
        rows.append(("other addresses", "no memory: the program stops with a runtime error"))
        self.rows = rows
        # The entries are white and gray in turn: a row without addresses goes on with the
        # entry above it and has its colour, so that the lines of one text read as one entry.
        colours, entry = [], -1
        for address, _ in rows:
            entry += bool(address)
            colours.append(STRIPE if entry % 2 else WHITE)
        widest = max(len(text) for _, text in rows)
        table = self.table
        table.set_rows(len(rows), lambda index: Row(rows[index], colours[index]), {
            "contents": column_width(self.window, self.font, widest, "Contents")})
        table.fit(len(rows) * table.row_height)
        table.body.configure(height=len(rows) * table.row_height,
                             width=sum(c.width for c in table.columns))
        self.refresh()

    def refresh(self):
        """Show SP's value now; the line is drawn again only when the value changed."""
        value = self.sp_now()
        if value != self.sp_shown:
            self.sp_shown = value
            self.sp_line.configure(text=f"SP now: 0x{value:08x}")

    def close(self):
        if self.window is not None:
            self.window.destroy()
            self.window = None


DUMP_FORMATS = [("Binary", ".bin"), ("Hexadecimal text", ".txt")]


def segment_ranges(program):
    """{name: (first address, end address)} of the program's .text (code) and .data parts."""
    ranges = {}
    for name, code in ((".text", True), (".data", False)):
        sections = [s for s in program.sections if s.executable == code and s.size]
        if sections:
            ranges[name] = (min(s.address for s in sections), max(s.end for s in sections))
    return ranges


def dump_bytes(data, binary):
    """The contents of a dump file: the bytes as they are, or one word per line in hex."""
    if binary:
        return data
    data += bytes(-len(data) % 4)
    return "".join(f"{word:08x}\n" for (word,) in struct.iter_unpack("<I", data)).encode("ascii")


class DumpMemoryDialog:
    """File > Dump Memory...: write the program's .text or .data part to a file.

    The memory is read as it is now, after whatever the program changed.
    on_dumped(message) is called after a file was written. It takes no grab:
    a dialog of the running program may open meanwhile. The window closes it
    when the program is assembled again.
    """

    def __init__(self, master, machine, last_folder, on_dumped):
        self.machine = machine
        self.last_folder = last_folder
        self.on_dumped = on_dumped
        self.ranges = segment_ranges(machine.program)
        window = self.window = tk.Toplevel(master)
        window.withdraw()
        window.title("Dump Memory")
        window.transient(master)
        window.resizable(False, False)
        gap = px(window, 6)
        body = ttk.Frame(window, padding=px(window, 12))
        body.pack(fill="both", expand=True)
        self.segment = tk.StringVar(master=window, value=next(iter(self.ranges), ""))
        self.format = tk.StringVar(master=window, value=DUMP_FORMATS[0][0])
        ttk.Label(body, text="Part of memory:").grid(row=0, column=0, sticky="w", pady=gap)
        self.segment_box = ttk.Combobox(body, textvariable=self.segment, state="readonly",
                                        width=34, values=list(self.ranges))
        self.segment_box.grid(row=0, column=1, sticky="w", pady=gap)
        self.range_label = ttk.Label(body)
        self.range_label.grid(row=1, column=1, sticky="w")
        ttk.Label(body, text="Format:").grid(row=2, column=0, sticky="w", pady=gap)
        ttk.Combobox(body, textvariable=self.format, state="readonly", width=34,
                     values=[name for name, _ in DUMP_FORMATS]).grid(row=2, column=1, sticky="w",
                                                                     pady=gap)
        self.status = ttk.Label(body, text="", foreground="#B00000")
        self.status.grid(row=3, column=0, columnspan=2, sticky="w")
        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(gap, 0))
        dump = ttk.Button(buttons, text="Dump To File...", command=self.dump)
        dump.pack(side="left", padx=(0, gap))
        cancel = ttk.Button(buttons, text="Cancel", command=self.close)
        cancel.pack(side="left")
        # Return presses the button that has the focus, else Dump To File...: it has the
        # black frame.
        default_button(dump, (dump, cancel))
        self.segment.trace_add("write", self._show_range)
        self._show_range()
        window.bind("<Return>", self._return)
        window.bind("<KP_Enter>", self._return)
        window.bind("<Escape>", lambda event: self.close())
        window.protocol("WM_DELETE_WINDOW", self.close)
        place_over(window, master)
        window.deiconify()
        self.segment_box.focus_set()

    def _return(self, event):
        """Return presses the button that has the focus, else Dump To File..."""
        if isinstance(event.widget, ttk.Button):
            event.widget.invoke()
        else:
            self.dump()

    def _show_range(self, *args):
        first, end = self.ranges.get(self.segment.get(), (0, 0))
        self.range_label.configure(text=f"0x{first:08x} to 0x{end - 1:08x}, {end - first} bytes"
                                   if end > first else "")

    def dump(self):
        """Ask for a file name and write the dump; None when cancelled."""
        name = self.segment.get()
        if name not in self.ranges:
            return None
        first, end = self.ranges[name]
        binary = self.format.get() == DUMP_FORMATS[0][0]
        extension = DUMP_FORMATS[0][1] if binary else DUMP_FORMATS[1][1]
        path = filedialog.asksaveasfilename(
            parent=self.window, title="Dump Memory", initialdir=self.last_folder or None,
            initialfile=name.strip(".") + extension, defaultextension=extension,
            filetypes=[("Dump files", "*" + extension), ("All files", "*.*")])
        if not path:
            return None
        data = dump_bytes(self.machine.read_memory(first, end - first), binary)
        try:
            write_file(path, data)
        except OSError as e:
            self.status.configure(text=f"Cannot write {path}: {e.strerror or e}")
            self.window.bell()
            return None
        self.close()
        self.on_dumped(f"Dump Memory: {name} (0x{first:08x} to 0x{end - 1:08x}) written to "
                       f"{path}")
        return path

    def close(self):
        if self.window is not None:
            self.window.destroy()
            self.window = None
