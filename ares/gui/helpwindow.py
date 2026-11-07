# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Help window: tabs in two levels, with scrollable pages.

Its pages are in ares.helptext and its instruction lists in ares.instructions. A page is made and
filled the first time it is shown, so that the window opens at once and the tools' modules are
imported only when the Tools tab is looked at.

Keys: Ctrl+Tab and Ctrl+Shift+Tab go round the tabs inside ARM or ARES, the top tab that holds the
page; License and Acknowledgements have none inside, so there they go round the top tabs. Ctrl+Page
Down and Ctrl+Page Up go round the top tabs from anywhere.
"""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from .. import APP_TITLE, helptext, instructions
from . import bumps
from .about import document_path, read_document
from .menubar import access_letter, screen_area
from .style import FACE, SELECTION, TAB, TEXT, WINDOW, default_button, page_padding, sunken
from .tabs import Notebook
from .tools import TOOLS, window_class
from .tools.frame import frame_of, place_over
from .widgets import ReadOnlyText, line_spacing, px, tab_moves_on

CONTROL = 0x4                   # the Control key in an event's state
SIZE = (788, 565)               # the inside of the window at first: 800 x 600 with its frame
SMALLEST_HEIGHT = 320
KEY_SHARE = 120 / SIZE[1]       # the operand key's share of the height: 20 % of the 600
KEY_BACKGROUND = "#CCFF99"      # the operand key
ROW_SHADE = "#EEEEEE"           # every other row of an instruction list, the first one too
AROUND_TABLE = 48               # beside a table: the insets, the frames and the scroll bar
MARGIN = 6                      # between the list of tools and the page beside it
DIVIDER = 10                    # the divider under the operand key
CLOSE_GAP = 5                   # above and under Close
INSET = 8                       # between a page's edge and its text
BULLET_INDENT = 16              # from a bullet to its text
LIST_WIDTH = 34                 # the list of tools, in characters
SHADED = "#E0E0E0"              # every other row of a table, as in the register tables
EXAMPLE = "#F4F4F4"             # behind a program example
HEADING_SCALE = 1.25            # a heading's size against the text's
# Keys that would move a page's hidden text cursor, and Tk brings the cursor into view.
CURSOR_KEYS = ("Left", "Right", "BackSpace", "Delete")
SCROLL_KEYS = {"<Key-Up>": ("scroll", -1, "units"), "<Key-Down>": ("scroll", 1, "units"),
               "<Key-Prior>": ("scroll", -1, "pages"), "<Key-Next>": ("scroll", 1, "pages"),
               "<Key-Home>": ("moveto", 0), "<Key-End>": ("moveto", 1)}
COMMON = "What every tool has"
MEMORY_MAP = "Memory Map"
LICENSE_FILE = "LICENSE"
NOTICES_FILE = "THIRD_PARTY_NOTICES.txt"
# The texts that only a packaged ARES holds, where nothing else would show them to the user of a
# single file: the licences of the assembler and linker, of what starts the package, and Python's.
PACKAGED_LICENCES = (("GNU General Public License, version 3 (GNU binutils)",
                      "licenses/GPL-3.0.txt"),
                     ("Apache License, version 2.0 (PyInstaller's run-time hooks)",
                      "licenses/Apache-2.0.txt"),
                     ("Python's licence", "licenses/Python-LICENSE.txt"),
                     ("The licences of the software inside Python",
                      "licenses/Python-parts.txt"))


def notebook(master, strip=FACE):
    """A notebook of the Help window; strip is the colour behind its tabs."""
    return Notebook(master, strip=strip)


class Fonts:
    """The fonts of the pages of a Help window, which keeps them: Tk forgets a font that is
    no longer named."""

    def __init__(self, master, code):
        self.body = tkfont.nametofont("TkTextFont", root=master)
        self.code = code
        self.heading = tkfont.Font(root=master, **{
            **self.body.actual(), "weight": "bold",
            "size": round(self.body.actual("size") * HEADING_SCALE)})
        self.key_heading = tkfont.Font(root=master, **{**self.heading.actual(), "slant": "italic"})
        self.bold_code = tkfont.Font(root=master, **{**code.actual(), "weight": "bold"})


class Page(ttk.Frame):
    """A text page: read-only text with a scroll bar, which shows blocks of ares.helptext."""

    def __init__(self, master, fonts, background=WINDOW):
        super().__init__(master)
        field = sunken(tk.Frame(self))
        field.pack(fill="both", expand=True)
        inset = px(self, INSET)
        body = fonts.body
        text = self.text = ReadOnlyText(field, wrap="word", font=body, background=background,
                                        foreground=TEXT, borderwidth=0, highlightthickness=0,
                                        padx=inset, pady=inset, width=1, height=1, insertwidth=0,
                                        selectbackground=SELECTION, selectforeground=TEXT)
        tab_moves_on(text)
        for sequence, command in SCROLL_KEYS.items():
            text.bind(sequence, lambda event, command=command: self.scroll(command))
        text.bind("<KeyPress>", self._key)
        bar = self.bar = ttk.Scrollbar(field, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        line = body.metrics("linespace")
        bullet = px(self, BULLET_INDENT)
        text.tag_configure(helptext.TITLE, font=fonts.heading, justify="center",
                           spacing3=line // 2)
        text.tag_configure(helptext.HEADING, font=fonts.heading, spacing1=line,
                           spacing3=line // 3)
        text.tag_configure("first", spacing1=0)
        text.tag_configure(helptext.PARAGRAPH, spacing3=line // 2)
        text.tag_configure(helptext.BULLET, lmargin1=0, lmargin2=bullet, spacing3=line // 3,
                           tabs=(bullet,))
        text.tag_configure(helptext.CODE, font=fonts.code, background=EXAMPLE, wrap="none",
                           lmargin1=inset, lmargin2=inset)
        text.tag_configure("inline", font=fonts.code)
        text.tag_configure(helptext.TABLE, font=fonts.code, wrap="none")
        text.tag_configure(helptext.DOCUMENT, font=fonts.code)
        text.tag_configure("shaded", background=SHADED)
        text.tag_configure("table_heading", font=fonts.bold_code)
        text.tag_configure("gap", font=body, spacing3=line // 2)
        self.filled = False

    def _key(self, event):
        """Keep the view where it is at a key that types or moves the cursor: nothing is typed
        here, but Tk would still bring the cursor, at the end of the text, into view."""
        typed = event.char and event.char.isprintable() and not event.state & CONTROL
        if typed or event.keysym in CURSOR_KEYS:
            return "break"
        return None

    def scroll(self, command):
        """Scroll with a key: a page has no text cursor for the keys to move."""
        self.text.yview(*command)
        return "break"

    def focus_widget(self):
        """The widget that takes the keyboard focus when the page comes to the front."""
        return self.text

    def key_widgets(self):
        """The widgets of the page that can hold the keyboard focus."""
        return (self.text,)

    def show(self, blocks):
        """Show blocks in place of what the page holds."""
        text = self.text
        text.clear()
        for block in blocks:
            getattr(self, "_write_" + block.kind)(block)
        self.filled = True
        text.yview_moveto(0)

    def _words(self, words, *tags):
        for part, in_code in helptext.spans(words):
            self.text.write(part, *tags, *(("inline",) if in_code else ()))

    def _write_title(self, block):
        self.text.write(block.text + "\n", helptext.TITLE)

    def _write_heading(self, block):
        first = ("first",) if not self.plain_text() else ()
        self.text.write(block.text + "\n", helptext.HEADING, *first)

    def _write_paragraph(self, block):
        self._words(block.text + "\n", helptext.PARAGRAPH)

    def _write_bullet(self, block):
        self.text.write("•\t", helptext.BULLET)
        self._words(block.text + "\n", helptext.BULLET)

    def _write_document(self, block):
        self.text.write(block.text.rstrip("\n") + "\n", helptext.DOCUMENT)

    def _write_code(self, block):
        self.text.write(block.text + "\n", helptext.CODE)
        self.text.write("\n", "gap")

    def _write_table(self, block):
        table = helptext.table_lines(block.rows)
        width = max(len(line) for lines in table for line in lines)
        for number, lines in enumerate(table):
            tags = (helptext.TABLE,)
            lines = [line.ljust(width) for line in lines]
            if number == 0:
                tags += ("table_heading",)
            elif number % 2 == 1:
                tags += ("shaded",)
            self.text.write("\n".join(lines) + "\n", *tags)
        self.text.write("\n", "gap")

    def plain_text(self):
        """All the words of the page."""
        return self.text.get("1.0", "end-1c")


class KeyPage(Page):
    """The operand key above the ARM tab's pages: green, its heading and tables in the middle."""

    def __init__(self, master, fonts):
        super().__init__(master, fonts, background=KEY_BACKGROUND)
        text = self.text
        text.tag_configure(helptext.HEADING, font=fonts.key_heading, justify="center")
        text.tag_configure("shaded", background=KEY_BACKGROUND)
        text.tag_configure(helptext.TABLE, justify="center")
        self.show(helptext.parse(helptext.operand_key()))


class InstructionList(ttk.Frame):
    """A list of example lines and what they do: the rows of ares.instructions, in stripes.

    A row with a group, its condition codes and S form, opens and closes at a click, and at
    Right and Left on the row that the keys are on. The list starts with every group closed.
    """

    def __init__(self, master, fonts, rows):
        super().__init__(master)
        self.rows = rows
        self.column = instructions.column(rows)
        self.shown = []                 # (row, the row whose group it is in, or None), in order
        self.opened = set()             # the rows whose group shows
        self.filled = False
        field = sunken(tk.Frame(self))
        field.pack(fill="both", expand=True)
        # A list's rows have no spacing of their own: the selection's border makes them as high
        # as the lines of the editor.
        border = sum(line_spacing(self, fonts.code)) // 2
        box = self.list = tk.Listbox(field, width=1, height=1, font=fonts.code, borderwidth=0,
                                     highlightthickness=0, activestyle="none", background=WINDOW,
                                     foreground=TEXT, selectbackground=SELECTION,
                                     selectforeground=TEXT, selectborderwidth=border,
                                     selectmode="browse", exportselection=False)
        bar = ttk.Scrollbar(field, orient="vertical", command=box.yview)
        self.sideways = ttk.Scrollbar(field, orient="horizontal", command=box.xview)
        box.configure(yscrollcommand=bar.set, xscrollcommand=self._scrolled_sideways)
        box.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        self.sideways.grid(row=1, column=0, sticky="ew")
        self.sideways.grid_remove()
        field.rowconfigure(0, weight=1)
        field.columnconfigure(0, weight=1)
        box.bind("<Button-1>", self._pressed, add="+")
        box.bind("<ButtonRelease-1>", self._released)
        box.bind("<Key-Right>", lambda event: self._open_active())
        box.bind("<Key-Left>", lambda event: self._close_active())
        box.bind("<Key-Prior>", lambda event: self._move_page(-1))
        box.bind("<Key-Next>", lambda event: self._move_page(1))
        box.bind("<Key-Home>", lambda event: self._go_to(0))
        box.bind("<Key-End>", lambda event: self._go_to(len(self.shown) - 1))
        self._pressed_on = None         # the row a press of the mouse button was on

    def _scrolled_sideways(self, first, last):
        """The bar under the list shows only while the rows are wider than the list. It makes
        the list lower, not narrower, so showing it cannot change what it depends on."""
        self.sideways.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            self.sideways.grid_remove()
        else:
            self.sideways.grid()

    def _text(self, row, group):
        if group is not None:
            return instructions.text_of(row, self.column, instructions.VARIANT)
        if not instructions.has_variants(row):
            start = instructions.NO_GROUP
        else:
            start = instructions.OPEN if row in self.opened else instructions.CLOSED
        return instructions.text_of(row, self.column, start)

    def fill(self):
        self.shown = [(row, None) for row in self.rows]
        self.list.insert(0, *(self._text(row, None) for row in self.rows))
        self._stripe(0)
        self.filled = True

    def _stripe(self, start):
        for index in range(start, len(self.shown)):
            self.list.itemconfigure(index, background=ROW_SHADE if index % 2 == 0 else WINDOW)

    def focus_widget(self):
        return self.list

    def key_widgets(self):
        return (self.list,)

    def plain_text(self):
        """All the rows that show."""
        return "\n".join(self.list.get(0, "end"))

    def active(self):
        """The index of the row the keys are on."""
        return min(self.list.index("active"), len(self.shown) - 1)

    def _go_to(self, index):
        """Put the keys, the selection and the view on a row."""
        box = self.list
        box.selection_clear(0, "end")
        box.selection_set(index)
        box.activate(index)
        box.see(index)
        return "break"

    def _move_page(self, step):
        box = self.list
        height = box.nearest(box.winfo_height()) - box.nearest(0)
        return self._go_to(min(max(self.active() + step * max(height, 1), 0), len(self.shown) - 1))

    def _replace(self, index):
        """Show the row at index again, with its mark for an open or a closed group."""
        box = self.list
        selected = box.selection_includes(index)
        box.delete(index)
        box.insert(index, self._text(*self.shown[index]))
        if selected:
            box.selection_set(index)

    def open_group(self, index):
        """Show the group of the row at index, if it has one that is closed."""
        row, group = self.shown[index]
        members = instructions.variants(row)
        if group is not None or not members or row in self.opened:
            return
        self.opened.add(row)
        self.shown[index + 1:index + 1] = [(member, row) for member in members]
        self._replace(index)
        self.list.insert(index + 1, *(self._text(member, row) for member in members))
        self._stripe(index)
        if self.list.bbox(index + len(members)) is None:
            self.list.yview(index)      # all of the group that fits, from its row on

    def close_group(self, index):
        """Hide the group of the row at index."""
        row, group = self.shown[index]
        if row not in self.opened:
            return
        self.opened.discard(row)
        count = len(instructions.variants(row))
        del self.shown[index + 1:index + 1 + count]
        self.list.delete(index + 1, index + count)
        self._replace(index)
        self._stripe(index)

    def toggle(self, index):
        row = self.shown[index][0]
        (self.close_group if row in self.opened else self.open_group)(index)

    def _open_active(self):
        index = self.active()
        self.open_group(index)
        return self._go_to(index)

    def _close_active(self):
        """Close the group of the row, or the group it is in, whose first row the keys go to."""
        index = self.active()
        group = self.shown[index][1]
        if group is not None:
            index = next(i for i, (row, _) in enumerate(self.shown) if row == group)
        self.close_group(index)
        return self._go_to(index)

    def _row_at(self, y):
        """The index of the row at a height in the list, or None under the last one."""
        index = self.list.nearest(y)
        place = self.list.bbox(index)
        return index if place and place[1] <= y < place[1] + place[3] else None

    def _pressed(self, event):
        self._pressed_on = self._row_at(event.y)

    def _released(self, event):
        """A press and a release on one row, not a drag, opens or closes its group."""
        index = self._row_at(event.y)
        if index is not None and index == self._pressed_on:
            self.toggle(index)
            self._go_to(index)
        self._pressed_on = None


def tool_entries():
    """The Tools tab's list: (name, blocks of its page), made when they are needed."""
    entries = [(COMMON, lambda: helptext.parse(helptext.TOOLS_INTRO))]
    for tool in TOOLS:
        entries.append((access_letter(tool.label)[0],
                        lambda command=tool.command: helptext.tool_page(
                            window_class(command).HELP)))
    entries.append((MEMORY_MAP, lambda: helptext.parse(helptext.MEMORY_MAP)))
    return entries


class ToolsPage(ttk.Frame):
    """The Tools tab: a list of the tools at the left, the chosen tool's page at the right."""

    def __init__(self, master, fonts):
        super().__init__(master)
        self.entries = tool_entries()
        gap = px(self, MARGIN)
        field = sunken(tk.Frame(self))
        field.pack(side="left", fill="y", padx=(0, gap))
        self.list = tk.Listbox(field, width=LIST_WIDTH, borderwidth=0, highlightthickness=0,
                               activestyle="none", background=WINDOW, foreground=TEXT,
                               selectbackground=SELECTION, selectforeground=TEXT,
                               font="TkTextFont", exportselection=False)
        self.list.pack(fill="both", expand=True)
        for name, blocks in self.entries:
            self.list.insert("end", name)
        self.page = Page(self, fonts)
        self.page.pack(side="left", fill="both", expand=True)
        self.list.bind("<<ListboxSelect>>", lambda event: self.show_selected())
        # Up and Down choose in the list; the other keys scroll the page beside it.
        for sequence, command in SCROLL_KEYS.items():
            if sequence not in ("<Key-Up>", "<Key-Down>"):
                self.list.bind(sequence, lambda event, command=command: self.page.scroll(command))
        self.filled = False

    def fill(self):
        self.select(COMMON)
        self.filled = True

    def focus_widget(self):
        return self.list

    def key_widgets(self):
        return (self.list, self.page.text)

    def select(self, name):
        """Show the page of the entry called name."""
        index = [entry[0] for entry in self.entries].index(name)
        self.list.selection_clear(0, "end")
        self.list.selection_set(index)
        self.list.see(index)
        self.list.activate(index)
        self.show_selected()

    def show_selected(self):
        chosen = self.list.curselection()
        if chosen:
            self.page.show(self.entries[chosen[0]][1]())


class HelpWindow:
    """Help > Help: its own window, which stays open beside the main window."""

    def __init__(self, master, code_font, menus, label_of):
        self.menus, self.label_of = menus, label_of
        window = self.window = self.new_window(master)
        window.title(f"{APP_TITLE} Help")
        self.close_button = ttk.Button(window, text="Close", command=self.close)
        gap = px(window, CLOSE_GAP)
        self.close_button.pack(side="bottom", pady=gap)
        self.tabs = notebook(window)
        self.tabs.pack(side="top", fill="both", expand=True)
        self.notebooks = [self.tabs]
        self.inner = {}                 # top tab -> the notebook inside it
        self.holders = {}               # title of a tab that shows a page -> the frame for it
        self.pages = {}                 # title of a tab -> its page, once it has been shown
        self.top_of = {}                # top tab -> what it holds
        self.fonts = Fonts(window, code_font)
        self.split = self.key = self.divider = None
        self.placed = False             # the operand key has its share of the window
        band = page_padding(window)
        for title, inside in helptext.TABS:
            self.top_of[title] = self._top_tab(title, inside, band)
            self.tabs.add(self.top_of[title], text=title, padding=band)
        for book in self.notebooks:
            book.bind("<<NotebookTabChanged>>", self._tab_changed, add="+")
            # A click on the tab on top changes nothing, but Tk gives the tabs the keyboard focus.
            book.bind("<<TabClicked>>", lambda event: self.focus_page(), add="+")
        self._bind_tab_keys(window, self.key.text, *self.notebooks)
        self._fill(self.current())
        default_button(self.close_button, (self.close_button,))
        window.bind("<Escape>", self._close)
        # Return presses Close, which has the black frame; in the pages as well.
        for sequence in ("<Return>", "<KP_Enter>"):
            window.bind(sequence, self._close)
        window.protocol("WM_DELETE_WINDOW", self.close)
        smallest = self.smallest_width()
        window.minsize(smallest, px(window, SMALLEST_HEIGHT))
        size = max(px(window, SIZE[0]), smallest), self.first_height(master)
        window.geometry(f"{size[0]}x{size[1]}")
        place_over(window, master, size)
        self.split.bind("<Configure>", self._place_divider, add="+")
        window.deiconify()
        self.focus_page()

    def new_window(self, master):
        """The window, not shown yet."""
        window = tk.Toplevel(master, background=FACE)
        window.withdraw()
        return window

    def _top_tab(self, title, inside, band):
        """Make what a top tab holds: a page, or a notebook of pages (under the key in ARM's)."""
        if not inside:
            self.holders[title] = ttk.Frame(self.tabs)
            return self.holders[title]
        holder = self.tabs
        if title == helptext.TABS[0][0]:
            holder = self.split = ttk.PanedWindow(self.tabs, orient="vertical")
            self.key = KeyPage(holder, self.fonts)
        book = self.inner[title] = notebook(holder, TAB)
        self.notebooks.append(book)
        for name in inside:
            self.holders[name] = ttk.Frame(book)
            book.add(self.holders[name], text=name, padding=band)
        if holder is self.tabs:
            return book
        holder.add(self.key, weight=1)
        holder.add(book, weight=4)
        self.divider = bumps.Divider(holder, self.key, px(holder, DIVIDER))
        return holder

    def _bind_tab_keys(self, *widgets):
        """The keys that change tabs. On a page's text they must be its own: Tk's Text class
        takes Ctrl+Tab before the window."""
        for widget in widgets:
            widget.bind("<Control-Key-Tab>", lambda event: self._next_tab(1))
            widget.bind("<Control-Shift-Key-Tab>", lambda event: self._next_tab(-1))
            widget.bind("<Control-Key-Next>", lambda event: self._next_top(1))
            widget.bind("<Control-Key-Prior>", lambda event: self._next_top(-1))

    def _page(self, title, master):
        if title == "Tools":
            return ToolsPage(master, self.fonts)
        if title == "Basic Instructions":
            return InstructionList(master, self.fonts, instructions.BASIC)
        if title == "Extended (pseudo) Instructions":
            return InstructionList(master, self.fonts, instructions.EXTENDED)
        return Page(master, self.fonts)

    def _place_divider(self, event):
        """Give the operand key its share of the window, once the window has its size."""
        if event.height > 1 and not self.placed:
            self.placed = True
            self.split.sashpos(0, round(self.window.winfo_height() * KEY_SHARE))
            self.divider.place()

    def first_height(self, master):
        """The window's height at first: its usual one, or the work area's when that is less,
        so that Close is on the screen."""
        window = self.window
        area = screen_area(master, master.winfo_rootx(), master.winfo_rooty())
        *_, side, top = frame_of(master)
        room = area[3] - area[1] - top - side
        return max(min(px(window, SIZE[1]), room), px(window, SMALLEST_HEIGHT))

    def smallest_width(self):
        """The narrowest the window can be with all its tabs and the widest table whole."""
        window = self.window
        window.update_idletasks()
        table = self.fonts.code.measure("0") * helptext.TABLE_WIDTH + px(window, AROUND_TABLE)
        return max(max(book.winfo_reqwidth() for book in self.notebooks), table)

    def _tab_changed(self, event):
        self._fill(self.current())
        self.focus_page()

    def _round(self, book, step):
        """Bring the next or the previous tab of a notebook to the top, going round at the ends."""
        tabs = book.tabs()
        book.select(tabs[(tabs.index(book.select()) + step) % len(tabs)])
        self._fill(self.current())
        return "break"

    def _next_tab(self, step):
        """Go round the tabs inside the top tab, or the top tabs when it has none inside."""
        return self._round(self.inner.get(self.top(), self.tabs), step)

    def _next_top(self, step):
        return self._round(self.tabs, step)

    def focus_page(self):
        """Give the page on top the keyboard focus, for the keys that scroll it."""
        self._fill(self.current())
        self.pages[self.current()].focus_widget().focus_set()

    def top(self):
        """The title of the top tab on top."""
        return self.tabs.tab(self.tabs.select(), "text")

    def current(self):
        """The title of the tab that shows the page on top."""
        book = self.inner.get(self.top())
        return book.tab(book.select(), "text") if book else self.top()

    def blocks(self, title):
        """The blocks of a page of text."""
        if title == "License":
            return helptext.license_blocks(
                read_document(LICENSE_FILE), read_document(NOTICES_FILE),
                [(heading, read_document(name)) for heading, name in PACKAGED_LICENCES
                 if document_path(name).is_file()])
        if title == "Keyboard shortcuts":
            return helptext.parse(helptext.keyboard_page(self.menus, self.label_of))
        made = {"Intro": helptext.intro_page, "Limits": helptext.limits_page,
                "Syscalls": helptext.system_calls_page,
                "Acknowledgements": helptext.acknowledgements_page}.get(title)
        return helptext.parse(made() if made else helptext.PAGES[title])

    def _fill(self, title):
        """Make and fill the page of a tab, the first time it is shown."""
        if title in self.pages:
            return
        page = self.pages[title] = self._page(title, self.holders[title])
        page.pack(fill="both", expand=True)
        self._bind_tab_keys(*page.key_widgets())
        if isinstance(page, Page):
            page.show(self.blocks(title))
        else:
            page.fill()

    def select(self, title):
        """Bring the tab called title to the top, a top tab or a tab inside one."""
        for top, inside in helptext.TABS:
            if title == top or title in inside:
                self.tabs.select(self.top_of[top])
                if title in inside:
                    self.inner[top].select(self.holders[title])
        self._fill(self.current())

    def lift(self):
        self.window.deiconify()
        self.window.lift()
        self.focus_page()

    def _close(self, event=None):
        self.close()
        return "break"

    def close(self):
        if self.window is not None:
            self.window.destroy()
            self.window = None
