# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The main window: menus, toolbar, panes, keyboard shortcuts and the commands behind them."""

import gc
import shutil
import sys
import tempfile
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from .. import APP_NAME, APP_TITLE, disasm
from ..assembler import ERROR, Message, assemble
from ..console import FINISHED_STOPPED, Console
from ..examples import example_folders, example_programs
from ..machine import DIALOG, INITIAL_CPSR, INITIAL_SP, INPUT, SLEEP, Machine
from ..program import Program
from ..runner import CAN_START, Runner, State
from ..settings import DEFAULT_FONT, DEFAULT_SIZE, Settings, default_path, installed_family
from ..toolchain import ToolchainMissingError
from . import bumps, icons, titlebar, tools
from .about import AboutDialog
from .dialogs import (DIALOG_ICON_SIZE, MESSAGE_ICONS, DumpMemoryDialog, EditorFontDialog,
                      LineDialog, MemoryMapDialog, ServiceDialog, segment_ranges)
from .editor import EditorPane, same_file
from .execute import PAGE_BUTTON, SEGMENT_SASH, ExecutePane
from .find import FindReplaceDialog
from .helpwindow import HelpWindow
from .menubar import MENU_BAR_CLASS, access_letter, menu_bar, new_menu
from .messages import MessagesPane, keys_as_line
from .registers import DOUBLES, NAMES, CoprocPane, RegistersPane, register_fonts
from .style import (BAR_LINE, BEVEL, SHADOW, SLIDER, TOOL_BUTTON, TOOL_STRIP, draw_gradient, fit,
                    fit_button, page_padding)
from .style import apply as apply_style
from .table import Table
from .tabs import Notebook, frame_lines
from .widgets import (SHORTCUT_TAG, ReadOnlyText, Tooltip, is_aqua, px,
                      scale)

ICON_SIZE = 24                  # toolbar icons, in design pixels
CLOSE_ICON_SIZE = 14            # close buttons on file tabs
PAGE_ICON_SIZE = 20             # Previous and Next page of the Data Segment
PANE_FONT_SIZE = DEFAULT_SIZE    # messages, Run I/O and the Execute tab's tables
# The toolbar's row, in design pixels.
ROW_GAP = 5                     # around the toolbar and the Run speed slider
GRIP_WIDTH = 16                 # the grip at the toolbar's left end
GRIP_INSET = 2                  # its dots: from its left edge
GRIP_DOTS = 10                  # and how wide they are
GROUP_GAP = 10                  # between two groups of buttons
SPEED_WIDTH = 200               # the Run speed label and slider
SPEED_TICKS = 9                 # tick marks under the slider
TICK_HEIGHT = 7
SPEED_LABEL = 16                # the height of its label
BUTTONS_ABOVE = 3               # the buttons stand this much above the row's middle
SASH = 10                       # the window's dividers
LEAST_WIDTHS = (200, 150)       # the left part and the registers keep this much
LEAST_HEIGHTS = (120, 60)       # Edit and Execute, and the messages, keep this much
NORMAL_SIZE = (0.958, 0.894)    # the window not maximized: shares of the screen
SPLIT_MAIN = 0.732              # at every start: the left part's share of the window's width
SPLIT_LEFT = 0.771              # and Edit and Execute's share of the left part's height
BODY_INSET = 1                  # around the window's panes: their outer line lies here
MAX_SPEED = 31                  # the speed slider's last position: as fast as possible
SOURCE_TYPES = [("Assembly files", "*.s *.S *.asm"), ("All files", "*.*")]
CLOSE_WAIT = 2                  # seconds to wait at exit for the assembler to stop
SLEEP_TICK = 0.05               # longest wait between looks at a program that sleeps (s)
# Commands that act on an open register field itself; any other first applies its value.
FIELD_COMMANDS = {"cut", "copy", "paste", "select_all", "undo", "redo"}
# Widget classes whose mouse press leaves an open register field open: the scroll bars and
# the dividers (it moves with its row, as when the mouse wheel scrolls), and the menu bar
# (a command chosen from a menu applies it first, as every command does).
KEEP_FIELD = {"TScrollbar", "TPanedwindow", MENU_BAR_CLASS}
# Bind tag put first on the tables' headings: their own bindings end a mouse press there.
PRESS_TAG = "AresPress"
NOT_ASSEMBLED = "Assemble a program first to change register values."
RUN_FAILED = "Go: execution terminated with errors."     # ARES Messages after a runtime error
NO_EXAMPLES = "(no examples found)"     # the one gray item of File > Open Example without them

# Menus: (command, label, shortcut); None is a separator. A label's "&" marks its access
# letter (underlined; Alt and it open a menu, or choose an item of the open menu), unique
# within its menu. The Settings menu is built from SETTINGS_MENU; "open_example" is a
# submenu of the example programs.
MENUS = [
    ("&File", [
        ("new", "&New", "Ctrl+N"),
        ("open", "&Open...", "Ctrl+O"),
        ("open_example", "Open &Example", None),
        ("close", "&Close", None),
        ("close_all", "Close A&ll", None),
        None,
        ("save", "&Save", "Ctrl+S"),
        ("save_as", "Save &As...", None),
        ("save_all", "Sa&ve All", None),
        None,
        ("dump_memory", "&Dump Memory...", None),
        None,
        ("exit", "E&xit", None),
    ]),
    ("&Edit", [
        ("undo", "&Undo", "Ctrl+Z"),
        ("redo", "&Redo", "Ctrl+Y"),
        None,
        ("cut", "Cu&t", "Ctrl+X"),
        ("copy", "&Copy", "Ctrl+C"),
        ("paste", "&Paste", "Ctrl+V"),
        None,
        ("find", "&Find/Replace...", "Ctrl+F"),
        ("select_all", "Select &All", "Ctrl+A"),
        None,
        ("capitalize", "Capitali&ze Instructions", None),
    ]),
    ("&Run", [
        ("assemble", "&Assemble", "F3"),
        ("go", "&Go", "F5"),
        ("step", "&Step", "F7"),
        ("backstep", "&Backstep", "F8"),
        ("pause", "&Pause", "F9"),
        ("stop", "S&top", "F11"),
        ("reset", "&Reset", "F12"),
        None,
        ("clear_breakpoints", "&Clear All Breakpoints", "Ctrl+K"),
        ("toggle_breakpoints", "T&oggle All Breakpoints", "Ctrl+T"),
    ]),
    ("&Settings", None),
    ("&Tools", tools.MENU),
    ("&Help", [
        ("help", "&Help", None),
        ("about", "&About ARES", None),
    ]),
]

# Settings menu: on/off settings (Settings field, label), then commands.
SETTINGS_MENU = [
    ("show_labels", "Show &Labels Window"),
    ("assemble_on_open", "Assemble File Upon &Opening"),
    ("hex_addresses", "&Addresses in Hexadecimal"),
    ("hex_values", "&Values in Hexadecimal"),
    ("require_capitals", "Require &Capital Letters"),
    ("popup_input", "&Popup Dialog for Input"),
    ("backstep_while_running", "Enable &Backstep While Running"),
]
SETTINGS_COMMANDS = [
    ("editor_font", "Editor &Font...", None),
    ("restore_defaults", "&Restore Defaults", None),
]

# Toolbar: (command, tooltip); None is a separator.
TOOLBAR = [
    ("new", "New file"),
    ("open", "Open a file"),
    ("save", "Save the current file"),
    ("save_as", "Save the current file under a new name"),
    None,
    ("undo", "Undo the last edit"),
    ("redo", "Redo the last undone edit"),
    None,
    ("cut", "Cut"),
    ("copy", "Copy"),
    ("paste", "Paste"),
    None,
    ("find", "Find and replace text"),
    None,
    ("assemble", "Assemble the current file"),
    None,
    ("go", "Run the program"),
    ("step", "Run one instruction"),
    ("backstep", "Undo the last instruction"),
    ("pause", "Pause the running program"),
    ("stop", "Stop the program"),
    ("reset", "Reset the program to its start"),
    None,
    ("help", "Help"),
]


class App:
    """The ARES window on a Tk root.

    settings_path is where the settings are kept (the per-user file when
    not given); files are opened at start.
    """

    def __init__(self, root, settings_path=None, files=(), progress=None):
        """progress(share), when given, hears how far the window is: a number up to 1."""
        progress = progress or (lambda share: None)
        self.root = root
        self.settings_path = Path(settings_path) if settings_path else default_path()
        self.settings = Settings.load(self.settings_path)
        self.workdir = Path(tempfile.mkdtemp(prefix="ares-"))
        self.program = None             # the program of the last assemble without errors
        self.program_tab = None         # the file tab whose text it is; closing it unloads it
        self.machine = None             # the computer running it, and its controls
        self.runner = None
        self._tick_job = None           # the next slice of a run, while one is scheduled
        self._error_shown = False       # the runtime error of the run is in ARES Messages
        self.line_dialog = None         # Popup Dialog for Input, while one is open
        self.service_dialog = None      # a dialog the program asked for, while it is open
        self.memory_map = None          # Tools > Memory Map, while it is open
        self.help_window = None         # Help > Help, while it is open
        self.about_dialog = None        # Help > About ARES, while it is open
        self.tool_windows = {}          # command -> the window of a tool of the Tools menu
        self.dump_dialog = None         # File > Dump Memory, while it is open
        self._stale = False             # the tables do not show where a fast run is now
        self._assembly = None           # (thread, tab, file, job) while assembling
        self._assemble_next = False     # assemble the tab on top when the assembly ends
        self._assemble_later = None     # a tab opened during a run: assembled when it stops
        self._cancel = threading.Event()    # stops the assembler when the window closes
        self.font_dialog = None
        self._enabled = {}
        root.withdraw()
        root.title(APP_TITLE)
        root.report_callback_exception = self.report_error
        self.aqua = is_aqua(root)
        self._make_fonts()
        self._make_styles()
        progress(0.2)
        self._make_images()
        progress(0.4)
        self._make_menus()
        self._make_toolbar()
        progress(0.6)
        self._make_body()
        progress(0.9)
        self._bind_shortcuts()
        self._bind_presses()
        self.find_dialog = FindReplaceDialog(root, self._shown_text)
        root.protocol("WM_DELETE_WINDOW", self.cmd_exit)
        if self.aqua:
            # Through CallWrapper, so an error goes to report_error and not out of mainloop.
            root.createcommand("tk::mac::Quit", tk.CallWrapper(self.cmd_exit, None, root))
        self._restore_window()
        self.open_paths(files)
        self.editor_changed()
        progress(1)

    # Building the window ------------------------------------------------

    def _make_fonts(self):
        s = self.settings
        self.families = set(tkfont.families(self.root))
        family = installed_family(s.font_family, self.families)
        self.editor_font = tkfont.Font(root=self.root, family=family, size=s.font_size)
        self.editor_bold = tkfont.Font(root=self.root, family=family, size=s.font_size,
                                       weight="bold")
        self.pane_font = tkfont.Font(root=self.root, size=PANE_FONT_SIZE,
                                     family=installed_family(DEFAULT_FONT, self.families))

    def _make_styles(self):
        root = self.root
        apply_style(root)               # the look, before any widget is made
        self.register_font, self.register_heading_font = register_fonts(root, self.pane_font)
        style = ttk.Style(root)
        style.configure("Registers.Treeview", font=self.pane_font,
                        rowheight=self.pane_font.metrics("linespace") + px(root, 4))
        # Tk does not scale pixel sizes with the display: dividers would be thin.
        style.configure("Sash", sashthickness=px(root, SASH))
        for orient in ("Vertical", "Horizontal"):
            style.configure(f"Inner.TPanedwindow.{orient}.Sash",
                            sashthickness=px(root, SEGMENT_SASH))

    def _make_images(self):
        root = self.root
        size = round(ICON_SIZE * scale(root))
        self.images = {name: (icons.photo(root, name, size),
                              icons.photo(root, name, size, disabled=True))
                       for name in icons.TOOLBAR}
        close = round(CLOSE_ICON_SIZE * scale(root))
        self.close_images = (icons.photo(root, "close", close),
                             icons.photo(root, "close_active", close))
        size = round(DIALOG_ICON_SIZE * scale(root))
        self.message_images = {name: icons.photo(root, name, size)
                               for name in MESSAGE_ICONS.values()}
        size = round(PAGE_ICON_SIZE * scale(root))
        self.page_images = {name: (icons.photo(root, name, size), "disabled",
                                   icons.photo(root, name, size, disabled=True))
                            for name in ("page_previous", "page_next")}
        # A Previous or Next page button: wider than its icon, as high as a push button.
        style = ttk.Style(root)
        style.layout("Page.TButton", style.layout("Toolbutton"))
        style.configure("Page.TButton", relief="raised", shiftrelief=px(root, BEVEL))
        style.map("Page.TButton", relief=[("pressed !disabled", "sunken")])
        fit_button(root, "Page.TButton", self.page_images["page_next"][0],
                   px(root, PAGE_BUTTON[0]), px(root, PAGE_BUTTON[1]))
        fit_button(root, "Toolbutton", self.images["new"][0], px(root, TOOL_BUTTON),
                   px(root, TOOL_BUTTON))
        # ARES's own icon in the title bars and the taskbar, in place of Tk's.
        self.window_images = icons.window_photos(root)
        titlebar.set_icon(root, self.window_images)

    def _make_menus(self):
        """The menus of MENUS: in ARES's own Windows 98 menu bar at the top of the window, or
        in macOS's screen menu bar (ares.gui.menubar), the same way for both."""
        self.menubar = menu_bar(self.root)
        self._menu_items = {}           # command -> (menu, index)
        self._keys = {}                 # command -> shortcut
        self.setting_vars = {}
        for title, entries in MENUS:
            menu = new_menu(self.menubar)
            label, underline = access_letter(title)
            self.menubar.add_cascade(label=label, menu=menu, underline=underline)
            if entries is None:
                self._fill_settings_menu(menu)
                continue
            for entry in entries:
                if entry is None:
                    menu.add_separator()
                elif entry[0] == "open_example":
                    self._add_examples(menu, entry[1])
                else:
                    self._add_command(menu, *entry)

    def _add_examples(self, menu, label):
        """The submenu of the bundled example programs, one item each. It is always available,
        as New is; the first letter of a name chooses it, or moves among the names it starts."""
        submenu = new_menu(menu)
        self.examples = example_programs()
        for path in self.examples:
            submenu.add_command(label=path.name, underline=0,
                                command=lambda path=path: self.run("open_example", path))
        if not self.examples:
            submenu.add_command(label=NO_EXAMPLES, state="disabled")
        label, underline = access_letter(label)
        menu.add_cascade(label=label, underline=underline, menu=submenu)

    def _add_command(self, menu, name, label, key):
        options = {}
        if key:
            self._keys[name] = key
            options["accelerator"] = self._accelerator(key)
        label, underline = access_letter(label)
        menu.add_command(label=label, underline=underline, command=lambda: self.run(name),
                         **options)
        self._menu_items[name] = (menu, menu.index("end"))

    def _fill_settings_menu(self, menu):
        for name, label in SETTINGS_MENU:
            var = tk.BooleanVar(master=self.root, value=getattr(self.settings, name))
            self.setting_vars[name] = var
            label, underline = access_letter(label)
            menu.add_checkbutton(label=label, underline=underline, variable=var,
                                 command=lambda n=name: self._setting_toggled(n))
        menu.add_separator()
        name, label, key = SETTINGS_COMMANDS[0]
        self._add_command(menu, name, label, key)
        menu.add_separator()
        name, label, key = SETTINGS_COMMANDS[1]
        self._add_command(menu, name, label, key)

    def _accelerator(self, key):
        """Shortcut text for a menu: Ctrl+N, or Command-N on macOS (shown as a symbol)."""
        if self.aqua and key.startswith("Ctrl+"):
            return "Command-" + key[len("Ctrl+"):]
        return key

    def _sequences(self, key):
        """Tk event sequences for a shortcut, also with Caps Lock on."""
        if not key.startswith("Ctrl+"):
            return [f"<Key-{key}>"]
        letter = key[len("Ctrl+"):].lower()
        modifier = "Command" if self.aqua else "Control"
        return [f"<{modifier}-Key-{letter}>", f"<{modifier}-Lock-Key-{letter.upper()}>"]

    def _view_pressed(self, index):
        """Bring a pressed Edit or Execute tab to the front in place of Tk's binding of notebooks.

        That binding draws everything pending before it gives the page the keyboard focus,
        which would draw the large panes twice: there, and for the Expose events that follow.
        Here they are drawn once, and the focus comes after.
        """
        views = self.views
        if index == views.index("current"):
            return False
        stays = str(views.tk.call("focus")) == str(views)       # Tk leaves it there
        views.select(index)
        views.focus_set()               # for now, as Tk's binding of notebooks does
        if not stays:
            views.after_idle(self._focus_view)
        return True

    def _focus_view(self):
        """Give the page on top the keyboard focus, which Tk's binding left on the notebook.

        Not when something took it back meanwhile, nor while a register's field is open: it
        holds a wrong value and keeps the focus, even out of view, where the focus waits
        until it is mapped again.
        """
        views = self.views
        if (any(pane.editor is not None for pane in self.register_panes)
                or str(views.tk.call("focus", "-lastfor", views._w)) != str(views)):
            return
        first = str(views.tk.call("ttk::focusFirst", views.select()))
        if not first:                   # pack and grid map the page's tables in idle jobs
            views.update_idletasks()
            first = str(views.tk.call("ttk::focusFirst", views.select()))
        if first:
            views.tk.call("ttk::traverseTo", first)

    def _make_toolbar(self):
        root = self.root
        gap = px(root, ROW_GAP)
        bar = ttk.Frame(root, padding=(gap, gap, gap, gap - px(root, BEVEL)))
        bar.pack(side="top", fill="x")
        self.buttons = {}
        self.tooltips = {}
        strip = self._gradient_canvas(bar)      # takes its size from what is packed in it
        strip.pack(side="left", anchor="center", pady=(0, px(root, BUTTONS_ABOVE)))
        self.toolbar_line = tk.Frame(bar, background=BAR_LINE, borderwidth=0,
                                     highlightthickness=0, takefocus=False)
        self.toolbar_line.place(in_=strip, x=0, rely=1, y=px(root, BEVEL), relwidth=1,
                                height=px(root, BEVEL))
        self.grip = self._toolbar_grip(strip)
        self.grip.pack(side="left")
        space = 0                       # before the next button: the gradient shows there
        for item in TOOLBAR:
            if item is None:
                space = px(root, GROUP_GAP)
                continue
            name, tip = item
            normal, disabled = self.images[name]
            button = ttk.Button(strip, image=(normal, "disabled", disabled), style="Toolbutton",
                                takefocus=False, command=lambda n=name: self.run(n))
            button.pack(side="left", padx=(space, 0))
            space = 0
            key = self._keys.get(name)
            self.tooltips[name] = Tooltip(button, f"{tip} ({self._accelerator(key)})" if key
                                          else tip)
            self.buttons[name] = button
        speed = ttk.Frame(bar)
        speed.pack(side="left", padx=(gap, 0))
        above, below = fit(px(root, SPEED_LABEL),
                           tkfont.nametofont("TkDefaultFont", root=root).metrics("linespace"))
        self.speed_label = ttk.Label(speed, anchor="center", padding=(0, above, 0, below))
        self.speed_label.pack(side="top", fill="x")
        self.speed = ttk.Scale(speed, from_=1, to=MAX_SPEED, orient="horizontal",
                               length=px(root, SPEED_WIDTH), command=self._speed_moved)
        self.speed.pack(side="top", fill="x")
        self.ticks = self._speed_ticks(speed)
        self.ticks.pack(side="top", fill="x")
        self.speed.set(MAX_SPEED)
        self._speed_moved(MAX_SPEED)

    def _gradient_canvas(self, master, width=0):
        """A canvas as high as a toolbar button with the gradient of the toolbar's strip."""
        root = self.root
        height = px(root, TOOL_BUTTON)
        canvas = tk.Canvas(master, width=width, height=height, borderwidth=0, highlightthickness=0,
                           takefocus=False, background=TOOL_STRIP[1])
        draw_gradient(canvas, TOOL_STRIP, height)
        return canvas

    def _toolbar_grip(self, master):
        """The dotted grip at the left end of the toolbar, on the strip's gradient: a canvas
        over it, so it has the same rows."""
        root = self.root
        grip = self._gradient_canvas(master, px(root, GRIP_WIDTH))
        bumps.draw(grip, px(root, GRIP_INSET), 0, px(root, GRIP_INSET + GRIP_DOTS),
                   px(root, TOOL_BUTTON))
        return grip

    def _speed_ticks(self, master):
        """The tick marks under the Run speed slider."""
        root = self.root
        ring = px(root, BEVEL)
        height = px(root, TICK_HEIGHT)
        ticks = tk.Canvas(master, width=px(root, SPEED_WIDTH), height=height, borderwidth=0,
                          highlightthickness=0, takefocus=False,
                          background=ttk.Style(root).lookup(".", "background"))
        reach = px(root, SPEED_WIDTH) - px(root, SLIDER[0]) - 2 * ring
        for k in range(SPEED_TICKS):
            x = ring + px(root, SLIDER[0]) // 2 + k * reach // (SPEED_TICKS - 1)
            ticks.create_rectangle(x, 0, x + ring, height, fill=SHADOW, width=0)
        return ticks

    def _make_body(self):
        root = self.root
        inset = px(root, BODY_INSET)
        self.main_split = ttk.PanedWindow(root, orient="horizontal")
        self.main_split.pack(side="top", fill="both", expand=True, padx=inset, pady=inset)
        self.body_lines = frame_lines(root, self.main_split)
        left = self.left_part = ttk.Frame(self.main_split, padding=inset)   # lines of its own
        self.left_split = ttk.PanedWindow(left, orient="vertical")
        self.left_split.pack(fill="both", expand=True)
        self.left_lines = frame_lines(left, self.left_split)
        self.main_split.add(left, weight=3)

        self.views = Notebook(self.left_split)
        self.editor = EditorPane(self.views, self)
        self.execute = ExecutePane(self.views, self.settings, self.pane_font, self.page_images)
        self.execute.text_segment.on_breakpoints = self._breakpoints_changed
        self.execute.data_segment.on_setting = self._set_setting
        band = page_padding(root)
        self.views.add(self.editor, text="Edit", padding=band)
        self.views.add(self.execute, text="Execute", padding=band)
        self.views.on_press = self._view_pressed
        self.left_split.add(self.views, weight=4)

        self.messages = MessagesPane(self.left_split, self.pane_font, self._message_clicked)
        self.messages.on_line = self._line_typed
        self.messages.on_keys = self._keys_typed
        self.messages.on_cleared = self._run_io_cleared
        self.left_split.add(self.messages, weight=1)

        self.side = Notebook(self.main_split)
        fonts = self.register_font, self.register_heading_font
        self.registers = RegistersPane(self.side, self.settings, *fonts)
        self.registers.on_edit = self._register_edited
        self.side.add(self.registers, text="Registers", padding=band)
        # ARM's floating-point unit is coprocessors 10 (single precision) and 11 (double).
        self.coproc10 = CoprocPane(self.side, self.settings, *fonts, double=False)
        self.coproc11 = CoprocPane(self.side, self.settings, *fonts, double=True)
        self.side.add(self.coproc10, text="Coproc 10", padding=band)
        self.side.add(self.coproc11, text="Coproc 11", padding=band)
        self.register_panes = (self.registers, self.coproc10, self.coproc11)
        for pane in self.register_panes:
            pane.on_field = self.editor_changed
            pane.on_toggle = self._flag_toggled
            pane.on_blocked = self._register_blocked
            pane.on_show = lambda pane=pane: self.side.select(pane)    # its field kept open
        for pane in (self.coproc10, self.coproc11):
            pane.on_edit = self._vfp_edited
        self.main_split.add(self.side, weight=1)
        sash = px(root, SASH)
        self.dividers = (
            bumps.Divider(self.main_split, left, sash, self._pixels(LEAST_WIDTHS)),
            bumps.Divider(self.left_split, self.views, sash, self._pixels(LEAST_HEIGHTS)))

    def _bind_shortcuts(self):
        for name, key in self._keys.items():
            def handler(event, name=name):
                self.run(name)
                return "break"
            for sequence in self._sequences(key):
                self.root.bind(sequence, handler)
                self.root.bind_class(SHORTCUT_TAG, sequence, handler)

    def _bind_presses(self):
        """Let a mouse press anywhere in the window reach _pressed.

        The window's own bind tag sees it on every widget whose bindings let
        it through. The tables' rows end it there, but take the focus, which
        applies a field; their headings get PRESS_TAG first.
        """
        self.root.bind("<ButtonPress-1>", self._pressed, add="+")
        self.root.bind_class(PRESS_TAG, "<ButtonPress-1>", self._pressed)
        execute = self.execute
        for pane in (execute.text_segment, execute.data_segment, execute.labels,
                     *self.register_panes):
            header = pane.table.header
            header.bindtags((PRESS_TAG,) + header.bindtags())

    def _pressed(self, event):
        """A mouse press elsewhere in the window applies an open register field.

        The field's own presses do not come here: its bind tags leave the
        window's out. The toolbar's available buttons apply it through their
        commands, as the menus do.
        """
        widget = event.widget
        if (self.root.tk.call("winfo", "class", str(widget)) in KEEP_FIELD
                or any(widget is divider.canvas for divider in self.dividers)
                or (widget in self.buttons.values() and widget.instate(["!disabled"]))):
            return
        for pane in self.register_panes:
            pane.pressed_elsewhere()

    # Window size and splits ---------------------------------------------

    def _restore_window(self):
        root = self.root
        root.minsize(px(root, 640), px(root, 400))
        root.geometry(self._start_geometry())
        self._splits_pending = True
        for divided in (self.main_split, self.left_split):      # whichever has its size last
            divided.bind("<Configure>", self._set_splits, add="+")
        root.deiconify()
        try:
            root.state("zoomed")
        except tk.TclError:             # X11 has no zoomed state
            root.attributes("-zoomed", True)

    def _start_geometry(self):
        """The window's size when it is not maximized: most of the screen, from its top left
        corner. It is the same at every start: the window's layout is not kept."""
        width, height = NORMAL_SIZE
        return (f"{int(self.root.winfo_screenwidth() * width)}"
                f"x{int(self.root.winfo_screenheight() * height)}+0+0")

    def _pixels(self, sizes):
        return tuple(px(self.root, size) for size in sizes)

    def _set_splits(self, event=None):
        """Put the dividers in their default places, once both divided windows have their
        real size. The left part passes through small heights on its way there: a divider placed
        then would stay under the toolbar.
        """
        width, height = self.main_split.winfo_width(), self.left_split.winfo_height()
        inset = 2 * px(self.root, BODY_INSET)
        if (not self._splits_pending or width <= 1 or height <= 1
                or height < self.main_split.winfo_height() - inset):
            return
        self._splits_pending = False
        self.main_split.sashpos(0, round(width * SPLIT_MAIN))
        self.left_split.sashpos(0, round(height * SPLIT_LEFT))

    # Command dispatch and states -----------------------------------------

    def run(self, name, *arguments):
        """Carry out a menu, toolbar or shortcut command if it is available now.

        A value typed in a register's field is applied first, as by a click
        elsewhere; when it is wrong, the bell rings, the field stays open and
        the command waits.
        """
        if self._enabled.get(name, True):
            if name not in FIELD_COMMANDS and not self._apply_fields():
                return
            command = getattr(self, "cmd_" + name, None)
            if command is not None:
                command(*arguments)
            elif tools.available(name):
                self.open_tool(name)

    def _apply_fields(self):
        """Apply the value of an open register field; False when it is wrong and stays open."""
        return all(pane.leave_field() for pane in self.register_panes)

    def editor_changed(self):
        """Update the title and which commands are available (after edits, tab changes...)."""
        tab = self.editor.current
        self.root.title(f"{tab.title()} - {APP_TITLE}" if tab else APP_TITLE)
        has_file = tab is not None
        loaded = self.machine is not None
        state = self.runner.state if loaded else None
        running = state in (State.RUNNING, State.WAITING)
        keys = state in (State.READY, State.RUNNING, State.PAUSED)
        typing = self.messages.run_io.typing
        # The edit commands act on a register's value field while one is open.
        field = any(pane.editor is not None for pane in self.register_panes)
        states = {
            "close": has_file, "close_all": has_file, "save": has_file, "save_as": has_file,
            "save_all": has_file, "cut": has_file or field,
            "paste": has_file or keys or typing or field,
            "find": has_file,
            "capitalize": has_file,
            "assemble": has_file and self._assembly is None and not running,
            "undo": has_file and tab.can_undo(), "redo": has_file and tab.can_redo(),
            "clear_breakpoints": loaded, "toggle_breakpoints": loaded,
            "go": state in CAN_START, "step": state in CAN_START,
            "backstep": loaded and state is not State.RUNNING and bool(self.machine.history),
            "pause": running, "stop": running or state is State.PAUSED, "reset": loaded,
            "dump_memory": loaded and bool(segment_ranges(self.program)),
        }
        for pane in self.register_panes:
            pane.editable = state in (State.READY, State.PAUSED, State.FINISHED)
        self.messages.keys_wanted = keys
        for name in list(self._menu_items) + list(self.buttons):
            available = ((hasattr(self, "cmd_" + name) or tools.available(name))
                         and states.get(name, True))
            self._set_enabled(name, available)

    def _set_enabled(self, name, on):
        if self._enabled.get(name) == on:
            return
        self._enabled[name] = on
        if name in self._menu_items:
            menu, index = self._menu_items[name]
            menu.entryconfigure(index, state="normal" if on else "disabled")
        if name in self.buttons:
            self.buttons[name].state(["!disabled"] if on else ["disabled"])

    def is_enabled(self, name):
        return self._enabled.get(name, False)

    def _speed_moved(self, value):
        speed = round(float(value))
        if self.speed.get() != speed:
            self.speed.set(speed)
        if speed >= MAX_SPEED:
            self.speed_label.configure(text="Run speed at max (no interaction)")
            if self.runner is not None and self.runner.state is State.RUNNING:
                self.execute.text_segment.set_pc(None)      # no next instruction while racing
                self._stale = True                          # a slow speed shows it first again
                if self._tick_job is not None:              # not after the slow delay
                    self._cancel_tick()
                    self._schedule_tick(0)
        else:
            self.speed_label.configure(text=f"Run speed {speed} inst/sec")

    @property
    def run_speed(self):
        """Instructions per second chosen with the slider, or None for as fast as possible."""
        speed = round(float(self.speed.get()))
        return None if speed >= MAX_SPEED else speed

    # File commands ---------------------------------------------------------

    def cmd_new(self):
        self.editor.new_file()

    def cmd_open(self):
        paths = filedialog.askopenfilenames(parent=self.root, title="Open",
                                            initialdir=self.settings.last_folder or None,
                                            filetypes=SOURCE_TYPES)
        self.open_paths(paths)

    def cmd_open_example(self, path):
        """Open a copy of the example at path as a new file that is not saved yet; its tab, or
        None after saying why it cannot be opened. Each choice opens a tab of its own."""
        try:
            tab = self.editor.open_copy(path)
        except OSError as e:
            self._cannot_open(f"Cannot open {path}:\n{e.strerror or e}")
            return None
        self._assemble_upon_opening()
        return tab

    def open_path(self, path):
        """Open a file in a new tab (or show its tab if it is open); None on failure."""
        return self.open_paths([path])

    def open_paths(self, paths):
        """Open files (or show their tabs if open); the last one's tab, None on failure.

        With Assemble File Upon Opening, once all are open, the tab on top is
        assembled if a file was newly opened (_assemble_upon_opening).
        """
        tab, opened = None, False
        for path in map(Path, paths):
            tab = self.editor.find(path)
            if tab is not None:
                self.editor.select(tab)
                tab.text.focus_set()
                continue
            tab = self._open_file(path)
            if tab is not None:
                opened = True
                self.settings.last_folder = str(path.resolve().parent)
        if opened:
            self._assemble_upon_opening()
        return tab

    def _assemble_upon_opening(self):
        """With Assemble File Upon Opening, assemble the tab on top, just opened; while a
        program runs or waits, that happens when it stops."""
        if self.settings.assemble_on_open:
            if self.runner is not None and self.runner.state in (State.RUNNING, State.WAITING):
                self._assemble_later = self.editor.current
            else:
                self.cmd_assemble()

    def _open_file(self, path):
        """A new tab for a file that is not open; None after saying why it cannot be opened."""
        try:
            if not path.is_dir():
                return self.editor.open_file(path)
            problem = f"{path} is a folder, not a file."       # Windows says "Permission denied"
        except OSError as e:
            problem = f"Cannot open {path}:\n{e.strerror or e}"
        self._cannot_open(problem)
        return None

    def _cannot_open(self, problem):
        messagebox.showerror(APP_NAME, problem, parent=self.root)

    def cmd_close(self):
        if self.editor.current is not None:
            self.close_tab(self.editor.current)

    def cmd_close_all(self):
        for tab in list(self.editor.tabs):
            if not self.close_tab(tab):
                return False
        return True

    def close_tab(self, tab):
        """Close a tab, asking first about unsaved changes; False when cancelled.

        As the commands do, the close button on the tab first applies an open
        register field: the tab stays while the field's value is wrong.
        Closing the file of the assembled program unloads the program.
        """
        if not self._apply_fields() or (tab.modified and not self._offer_save(tab)):
            return False
        self.editor.remove(tab)
        if tab is self.program_tab:
            self._close_program()
        return True

    def _close_program(self):
        """The program's file was closed: ARES is as right after start-up.

        A program that runs, is paused or waits is stopped first, as by Stop;
        ARES Messages and Run I/O keep their text.
        """
        if self.runner is not None and self.runner.state in (
                State.RUNNING, State.WAITING, State.PAUSED):
            self.cmd_stop()
        self._unload_program()
        self.editor_changed()

    def _offer_save(self, tab):
        """Ask whether to save the tab's changes; False when the user cancels."""
        self.views.select(self.editor)
        self.editor.select(tab)
        answer = messagebox.askyesnocancel(APP_NAME, f"Save changes to {tab.name}?",
                                           parent=self.root)
        if answer is None:
            return False
        return self.save(tab) if answer else True

    def cmd_save(self):
        if self.editor.current is not None:
            self.save(self.editor.current)

    def cmd_save_as(self):
        if self.editor.current is not None:
            self.save_as(self.editor.current)

    def cmd_save_all(self):
        for tab in list(self.editor.tabs):
            if tab.modified and not self.save(tab):
                return

    def save(self, tab):
        """Save a tab to its file (asking for a name if it has none); True when saved."""
        if tab.path is None:
            return self.save_as(tab)
        return self._write(tab, tab.path)

    def save_as(self, tab):
        self.editor.select(tab)
        folder = tab.path.parent if tab.path else self._folder_for_new_file()
        path = filedialog.asksaveasfilename(parent=self.root, title="Save As",
                                            initialdir=folder or None, initialfile=tab.name,
                                            defaultextension=".s", filetypes=SOURCE_TYPES)
        if not path:
            return False
        other = self.editor.find(Path(path))
        if other is not None and other is not tab:
            messagebox.showerror(APP_NAME, f"{Path(path).name} is open in another tab; "
                                 "close it first.", parent=self.root)
            return False
        if not self._write(tab, Path(path)):
            return False
        self.settings.last_folder = str(Path(path).resolve().parent)
        return True

    def _folder_for_new_file(self):
        """Where Save As starts for a file without a path: the last folder, but not the bundled
        examples' own, where a copy under the name offered would replace its example."""
        folder = self.settings.last_folder
        if folder and any(same_file(folder, place) for place in example_folders()):
            return None
        return folder

    def _write(self, tab, path):
        try:
            tab.save(path)
        except OSError as e:
            messagebox.showerror(APP_NAME, f"Cannot save {path}:\n{e.strerror or e}",
                                 parent=self.root)
            return False
        return True

    def cmd_exit(self):
        for tab in list(self.editor.tabs):
            if tab.modified and not self._offer_save(tab):
                return
        self.save_settings()
        self.close()

    def close(self):
        """Close the window without asking anything."""
        self._cancel.set()
        self._cancel_tick()
        if self.machine is not None:
            self.machine.close()                # also the files the program opened
        self.root.destroy()
        if self._assembly is not None:
            # The worker stops within about 0.1 s; until then it may write to the folder,
            # and Windows cannot remove files the assembler holds open.
            self._assembly[0].join(CLOSE_WAIT)
        shutil.rmtree(self.workdir, ignore_errors=True)

    # Edit commands -----------------------------------------------------------

    def _current_text(self):
        tab = self.editor.current
        return tab.text if tab is not None else None

    def _shown_tab(self):
        """The tab on top, with the Edit tab brought to the front; None when no file is open."""
        tab = self.editor.current
        if tab is not None:
            self.views.select(self.editor)
        return tab

    def _shown_text(self):
        """The text of the tab on top, shown (see _shown_tab), or None."""
        tab = self._shown_tab()
        return tab.text if tab is not None else None

    def _tab_to_edit(self):
        """The tab on top, shown, with the keyboard focus in its text.

        A click on the Execute tab gives the focus to the Edit/Execute tabs,
        where the next arrow key would bring Execute back.
        """
        tab = self._shown_tab()
        tab.text.focus_set()
        return tab

    def _focused_text(self):
        """The text widget of the main window that has the focus, else the editor's.

        None while a table has the focus or the Execute tab is in front: Copy
        and Select All then do nothing, rather than act on the editor out of
        sight.
        """
        widget = self.root.focus_get()
        if isinstance(widget, tk.Text) and widget.winfo_toplevel() is self.root:
            return widget
        if self._focus_in_pane() or self.views.select() != str(self.editor):
            return None
        return self._current_text()

    def _focus_in_pane(self):
        """True when the focus is in ARES Messages, Run I/O or a table.

        Cut and Paste then do nothing: a key pressed there must not change the editor.
        """
        widget = self.root.focus_get()
        return (isinstance(widget, (ReadOnlyText, ttk.Treeview))
                or isinstance(getattr(widget, "master", None), Table)
                or self._in_field(widget))

    def _in_field(self, widget=None):
        """True when the focus is in the field of a register value being changed."""
        return self._field_pane(widget) is not None

    def _field_pane(self, widget=None):
        """The register pane whose value field has the focus (or is widget), else None."""
        widget = self.root.focus_get() if widget is None else widget
        return next((pane for pane in self.register_panes
                     if widget is not None and widget is pane.editor), None)

    def cmd_undo(self):
        if not self._typing_here():
            self._tab_to_edit().undo()

    def cmd_redo(self):
        if not self._typing_here():
            self._tab_to_edit().redo()

    def _typing_here(self):
        """True when keys go into Run I/O or a register field: Undo must not reach the editor."""
        return self.root.focus_get() is self.messages.run_io or self._in_field()

    def cmd_cut(self):
        pane = self._field_pane()
        if pane is not None:
            pane.field_command("cut")
        elif not self._focus_in_pane() and self.editor.current is not None:
            self._tab_to_edit().text.event_generate("<<Cut>>")

    def cmd_copy(self):
        pane = self._field_pane()
        if pane is not None:
            pane.field_command("copy")
            return
        text = self._focused_text()
        if text is not None:
            text.event_generate("<<Copy>>")

    def cmd_paste(self):
        if self.root.focus_get() is self.messages.run_io:
            try:
                text = self.root.clipboard_get()
            except tk.TclError:                         # nothing to paste
                return
            self.messages.paste(text)                   # the typed line, or keys for the program
        elif self._in_field():
            self._field_pane().field_command("paste")
        elif not self._focus_in_pane() and self.editor.current is not None:
            self._tab_to_edit().text.event_generate("<<Paste>>")

    def cmd_select_all(self):
        pane = self._field_pane()
        if pane is not None:
            pane.field_command("select_all")
            return
        text = self._focused_text()
        if text is not None:
            text.tag_add("sel", "1.0", "end-1c")

    def cmd_find(self):
        # The Find window takes the focus; the editor gets it back when that window closes.
        text = self._tab_to_edit().text
        selected = ""
        if text.tag_ranges("sel"):
            selected = text.get("sel.first", "sel.last")
        self.find_dialog.show(selected if "\n" not in selected else "")

    def cmd_capitalize(self):
        self._tab_to_edit().capitalize()

    # Run commands --------------------------------------------------------------

    @property
    def assembling(self):
        return self._assembly is not None

    def cmd_assemble(self):
        """Assemble the current tab's text in the background (its file is not saved).

        While another assembly runs, the tab on top is assembled when it ends.
        """
        if self._assembly is not None:
            self._assemble_next = True
            return
        tab = self.editor.current
        file = tab.path if tab.path is not None else tab.name      # the file messages name
        name = str(file)
        self.messages.show_messages()
        self.messages.write_message(f"Assemble: assembling {name}")
        tab.set_error_lines(())
        self._unload_program()
        job = {}
        source, require_capitals = tab.get_text(), self.settings.require_capitals
        tab_size = self.settings.tab_size

        def work():
            try:
                job["result"] = build(source, self.workdir / "build", name, require_capitals,
                                      self._cancel, tab_size)
            except Exception:
                job["error"] = sys.exc_info()
        thread = threading.Thread(target=work, daemon=True)
        self._assembly = (thread, tab, file, job)
        self.editor_changed()
        thread.start()
        self.root.after(20, self._assembled)

    def _assembled(self):
        """Show the result once the worker thread has finished."""
        thread, tab, file, job = self._assembly
        if thread.is_alive():
            self.root.after(20, self._assembled)
            return
        self._assembly = None
        if "error" in job:
            self.report_error(*job["error"])
        stopped = [Message(None, None, ERROR, "assembling stopped")], None, None
        messages, program, listing = job.get("result", stopped)
        errors = set()
        for message in messages:
            target = None
            if message.file == str(file) and message.line:
                target = (tab, file, message.line)
                if message.severity == ERROR:
                    errors.add(message.line)
            self.messages.write_message(message.format(), target)
        if tab in self.editor.tabs:
            tab.set_error_lines(errors)
        outcome = "completed successfully" if program is not None else "completed with errors"
        self.messages.write_message(f"Assemble: operation {outcome}.")
        try:
            if program is not None and tab not in self.editor.tabs:
                pass                            # its file was closed meanwhile: not loaded
            elif program is not None:
                self._load_program(program, listing, file, tab)
            elif self.editor.current is not None:
                self._tab_to_edit()             # the Execute tab is empty now
        except Exception:
            self._unload_program()
            self.report_error(*sys.exc_info())
            if self.editor.current is not None:
                self._tab_to_edit()             # the Execute tab is empty
        self.editor_changed()
        if self._assemble_next:
            self._assemble_next = False
            if self.editor.current is not None:
                self.cmd_assemble()

    def _load_program(self, program, listing, file, tab):
        """Make an assembled program ready to run and show it on the Execute tab.

        tab is the file tab whose text it is: closing that tab unloads it.

        File services take names relative to the folder of the source file
        (the last folder used, for an untitled file).
        """
        if isinstance(file, Path):
            folder = file.resolve().parent
        else:
            folder = Path(self.settings.last_folder or Path.home())
        # The window passes the output on at once: the console need not keep it.
        machine = Machine(program, console=Console(keep_text=False), base_dir=folder)
        runner = Runner(machine, record_while_running=self.settings.backstep_while_running)
        self.program, self.machine, self.runner = program, machine, runner
        self.program_tab = tab
        self.messages.finish_line()             # its output starts on a line of its own
        self.execute.load(machine, listing)
        for pane in self.register_panes:
            pane.unmark()
        self.show_state()
        if self.memory_map is not None and self.memory_map.window is not None:
            self.memory_map.show_program(program)
        self._tools_observe(machine)
        self.views.select(self.execute)
        # The editor is no longer on the screen; keys must not change it unseen.
        self.execute.text_segment.table.body.focus_set()

    def _unload_program(self):
        """Forget the assembled program: it no longer matches the source."""
        self._cancel_tick()
        self._abandon_input(keep=False)
        if self.dump_dialog is not None:
            self.dump_dialog.close()
            self.dump_dialog = None
        self._tools_observe(None)               # while the machine still has its memory
        if self.machine is not None:
            self.machine.close()                # its memory now, not at Python's next collection
        self.program = self.machine = self.runner = self.program_tab = None
        self.execute.clear()
        if self.memory_map is not None and self.memory_map.window is not None:
            self.memory_map.show_program(None)
        # Unicorn's hooks tie the emulator and the machine together: only a
        # collection frees the rest of the emulator (about 6 MB, 10 ms here).
        gc.collect()
        for pane in self.register_panes:
            pane.unmark()
        self.registers.set_values([0] * 13 + [INITIAL_SP, 0, 0], INITIAL_CPSR, 0)
        for pane in (self.coproc10, self.coproc11):
            pane.set_values([0] * len(DOUBLES), 0)

    def show_state(self):
        """Show the machine's registers, its memory and its next instruction.

        A finished program has no next instruction, unless it stopped with a
        runtime error: then the instruction that failed is shown, in light red,
        also after PC was changed.
        """
        machine = self.machine
        self.registers.set_values([machine.reg(n) for n in range(16)], machine.cpsr,
                                  machine.spsr)
        doubles, fpscr = machine.vfp()
        for pane in (self.coproc10, self.coproc11):
            pane.set_values(doubles, fpscr)
        self.execute.data_segment.refresh()
        segment = self.execute.text_segment
        if machine.error_address is not None:
            segment.set_pc(machine.error_address, failed=True)
        else:
            segment.set_pc(None if self.runner.state is State.FINISHED else machine.pc)
        self._stale = False

    # Run commands ----------------------------------------------------------------

    def cmd_go(self):
        self._before_run()
        self.runner.go(slow=self.run_speed is not None)
        self._after_run()

    def cmd_step(self):
        self._before_run()
        self.runner.step()
        self._after_run()

    def cmd_backstep(self):
        self._abandon_input(keep=True)
        self._close_fields()
        self._mark()
        self.runner.backstep()
        self._after_run()

    def cmd_pause(self):
        self.runner.pause()
        self._after_run()

    def cmd_stop(self):
        self.runner.stop()
        self._abandon_input(keep=False)         # before the end line is written after it
        self.machine.console.clear_input()      # also what Pause gave back to the input
        self.machine.console.end_line(FINISHED_STOPPED)
        self._after_run()

    def cmd_reset(self):
        """Load the program again in its initial state; breakpoints stay."""
        self._cancel_tick()
        self._abandon_input(keep=False)
        self._close_fields()
        self.runner.reset()
        self.machine.console.clear_input()
        self.machine.console.clear()
        self.messages.finish_line()             # the next run starts on a line of its own
        for pane in self.register_panes:
            pane.unmark()
        self.execute.data_segment.unmark()
        self.show_state()
        self._refresh_tools()
        self.editor_changed()
        if self._assemble_later is not None:
            self._assemble_opened()

    def _before_run(self):
        """What Go and Step do first: changes from here on are highlighted."""
        self._close_fields()
        self._mark()
        self._error_shown = False
        self.messages.show_run_io()

    def _abandon_input(self, keep):
        """The program no longer waits: stop the typing of its line, close its dialogs.

        With keep (Pause, Backstep), an unsent line goes back to the typed
        input: keys typed meanwhile add to it, and a read that waits starts its
        line with it. Otherwise it is forgotten.
        """
        # The line is typed in Run I/O or in the input dialog, not in both.
        unsent = (self.messages.end_line() or "") + (self._close_line_dialog() or "")
        if keep and unsent:
            self.machine.console.feed(unsent)
        self._close_service_dialog()

    def _mark(self):
        for pane in self.register_panes:
            pane.mark()
        self.execute.data_segment.mark()

    def _close_fields(self):
        """Close a register's value field, leaving the value unchanged."""
        for pane in self.register_panes:
            pane.cancel_edit()

    def _after_run(self):
        """Pass on the output, and show what the program does now (runs, waits or stopped)."""
        runner = self.runner
        state = runner.state
        if state is not State.WAITING:          # before the output: it goes after the line
            self._abandon_input(keep=state is not State.FINISHED)
        self._flush()
        self._cancel_tick()
        # The tools before the next slice is scheduled: it is due a moment later, and Tk
        # redraws the window only while nothing is due.
        self._refresh_tools()
        if state is State.RUNNING:
            remaining = runner.sleep_remaining()
            if self.run_speed is not None:      # the next instruction is shown before it runs
                self.show_state()
                delay = max(remaining, 1 / self.run_speed)
            else:
                self.execute.text_segment.set_pc(None)  # no next instruction while racing
                self._stale = True
                # Asleep: look again when the time is up. Else Tk handles the
                # window's events in between.
                delay = min(remaining, SLEEP_TICK) if remaining else 0.001
            self._schedule_tick(delay)
        else:
            self.show_state()
            if state is State.WAITING:
                self._wait(runner.request)
        if state is State.FINISHED and self.machine.error and not self._error_shown:
            self._error_shown = True            # Run I/O has the error: ARES Messages too
            self.messages.write_message(self.machine.error)
            self.messages.write_message(RUN_FAILED)
        self.editor_changed()
        if self._assemble_later is not None and state not in (State.RUNNING, State.WAITING):
            self._assemble_opened()

    def _tick(self):
        """One slice of a run (or one instruction at a slow speed)."""
        self._tick_job = None
        runner = self.runner
        if runner is None or runner.state is not State.RUNNING:
            return
        slow = self.run_speed is not None
        runner.set_slow(slow)
        if slow:
            machine, request = self.machine, self.machine.request
            if self._stale:                     # first show the instruction that runs next
                self.show_state()
                self._schedule_tick(max(runner.sleep_remaining(), 1 / self.run_speed))
                return
            if request is not None and request.kind == SLEEP and not machine.request_done():
                self._schedule_tick(runner.sleep_remaining())   # nothing runs before it ends
                return
            if (machine.request_done() and not machine.breakpoint_here()
                    and not machine.ends_here()):
                self._mark()                    # highlight what this instruction changes
        runner.run_slice()                      # a read or dialog not answered makes it wait
        self._after_run()

    def _schedule_tick(self, seconds):
        self._tick_job = self.root.after(max(1, round(seconds * 1000)), self._tick)

    def _cancel_tick(self):
        if self._tick_job is not None:
            self.root.after_cancel(self._tick_job)
            self._tick_job = None

    def _flush(self):
        """Pass the program's new output to Run I/O and its warnings to ARES Messages."""
        machine = self.machine
        self.messages.write_output(machine.console.take())
        for warning in machine.take_warnings():
            self.messages.write_message(warning)

    def _wait(self, request):
        """The program waits: let the user type its line, or answer its dialog."""
        if request.kind == INPUT:
            if self.messages.run_io.typing or self.line_dialog is not None:
                return
            # Keys typed before the read are the start of its line: shown, and changeable.
            text = keys_as_line(self.machine.console.take_pending().decode(
                "utf-8", errors="replace"))
            if self.settings.popup_input:
                self._open_line_dialog(text)
            else:
                self.messages.begin_line(text)
        elif request.kind == DIALOG:
            self.show_dialog(request)

    def _line_typed(self, line, rest=""):
        """A line typed in Run I/O (or the input dialog): the program reads it and goes on.

        rest, the text after a line break pasted into the line, is typed ahead
        of the next read.
        """
        machine, runner = self.machine, self.runner
        if runner is None or runner.state is not State.WAITING:
            return
        machine.console.feed(line + "\n" + rest)
        machine.console.line_ended()            # Run I/O shows the line and its newline
        runner.run_slice()                      # the waiting service runs again
        self._after_run()

    def _keys_typed(self, text):
        """Keys typed in Run I/O when no line is typed: the JTAG UART reads them as typed."""
        if self.machine is not None:
            self.machine.console.feed(text)
            if not self._stale:                 # the Data Segment shows them waiting
                self.execute.data_segment.refresh()

    def _run_io_cleared(self):
        if self.machine is not None:
            self.machine.console.line_ended()   # the next end line needs no line break first

    def _open_line_dialog(self, text=""):
        if self.line_dialog is None:
            self.line_dialog = LineDialog(self.root, "Input", "Enter the input for the program:",
                                          self._dialog_line, text)
            self._bind_run_keys(self.line_dialog.window)

    def _bind_run_keys(self, window):
        """Let the run keys (Backstep, Pause, Stop, Reset) work in a window of the program."""
        for name in ("backstep", "pause", "stop", "reset"):
            for sequence in self._sequences(self._keys[name]):
                window.bind(sequence, lambda event, name=name: self.run(name) or "break")

    def _dialog_line(self, line):
        """The input dialog closed: OK gives the line, Cancel None (then type it in Run I/O)."""
        dialog, self.line_dialog = self.line_dialog, None
        if line is None:
            self.messages.begin_line(dialog.text)       # with what was typed in the dialog
            self.editor_changed()
            return
        line = line.replace("\x00", "")         # the program reads the line Run I/O shows
        self.messages.write_output(line + "\n")   # Run I/O shows what was typed, as in the pane
        self._line_typed(line, dialog.rest)

    def _close_line_dialog(self):
        """Close the input dialog; returns the text typed in it (None when none was open)."""
        if self.line_dialog is None:
            return None
        dialog, self.line_dialog = self.line_dialog, None
        dialog.close()
        return dialog.text

    def show_dialog(self, request):
        """Show the dialog window a program asked for (SVC #50 to #59)."""
        if self.service_dialog is None:
            self.service_dialog = ServiceDialog(self.root, request, self._dialog_answered,
                                                self.message_images)
            self._bind_run_keys(self.service_dialog.window)

    def _dialog_answered(self, value):
        self.service_dialog = None
        runner = self.runner
        if runner is None or runner.state is not State.WAITING:
            return
        runner.answer(value)
        runner.run_slice()                      # the service runs again with the answer
        self._after_run()

    def _close_service_dialog(self):
        if self.service_dialog is not None:
            dialog, self.service_dialog = self.service_dialog, None
            dialog.close()

    # Tools -----------------------------------------------------------------------

    def open_tool(self, command):
        """Open the window of a tool of the Tools menu (ares.gui.tools), or bring it to the
        front when it is open: each tool has one window."""
        window = self.tool_windows.get(command)
        if window is not None and window.window is not None:
            window.lift()
        else:
            self.tool_windows[command] = tools.window_class(command)(self)

    def _open_tools(self):
        self.tool_windows = {command: window for command, window in self.tool_windows.items()
                             if window.window is not None}
        return list(self.tool_windows.values())

    def _tools_observe(self, machine):
        """Tell the open tools that a program was loaded (its machine) or unloaded (None)."""
        for window in self._open_tools():
            window.machine_changed(machine)

    def _refresh_tools(self):
        """Have the open tools show what the program did since they last looked, and an open
        Memory Map SP's value now."""
        for window in self._open_tools():
            window.refresh()
        if self.memory_map is not None and self.memory_map.window is not None:
            self.memory_map.refresh()

    def _sp_now(self):
        """SP's value now; its start value while no program is loaded, as the Registers show."""
        return self.machine.reg(13) if self.machine is not None else INITIAL_SP

    def cmd_memory_map(self):
        if self.memory_map is not None and self.memory_map.window is not None:
            self.memory_map.show_program(self.program)
            self.memory_map.window.lift()
            return
        self.memory_map = MemoryMapDialog(self.root, self.program, self.pane_font, self._sp_now)

    def cmd_help(self):
        if self.help_window is not None and self.help_window.window is not None:
            self.help_window.lift()
            return
        self.help_window = HelpWindow(self.root, self.pane_font, MENUS,
                                      lambda label: access_letter(label)[0])

    def cmd_about(self):
        if self.about_dialog is not None and self.about_dialog.window is not None:
            self.about_dialog.lift()
            return
        self.about_dialog = AboutDialog(self.root)

    def cmd_dump_memory(self):
        if self.dump_dialog is not None and self.dump_dialog.window is not None:
            self.dump_dialog.window.lift()
            return
        self.dump_dialog = DumpMemoryDialog(self.root, self.machine, self.settings.last_folder,
                                            self.messages.write_message)

    def _register_edited(self, name, value):
        """Put a value typed in the Registers into the machine; False when it cannot be."""
        if self.machine is None:
            return False
        number = NAMES.index(name)
        if number == 15 and value % 4:          # ARM instructions are at multiples of 4
            return False
        self.machine.set_reg(number, value)
        self._register_changed()
        return True

    def _vfp_edited(self, name, value):
        """Put the bits typed for an S or D register into the machine."""
        if self.machine is None:
            return False
        if name.startswith("S"):
            self.machine.set_single(int(name[1:]), value)
        else:
            self.machine.set_double(int(name[1:]), value)
        self._register_changed()
        return True

    def change_single(self, n, bits):
        """A tool puts bits into Sn, as a value typed in Coproc 10 does; False when values
        cannot be changed now: no program is loaded, or it runs or waits."""
        runner = self.runner
        if runner is None or runner.state not in (State.READY, State.PAUSED, State.FINISHED):
            return False
        return self._vfp_edited(f"S{n}", bits)

    def _flag_toggled(self, name, bit):
        """A double-click on a flag of CPSR, SPSR or FPSCR: the bit changes."""
        machine = self.machine
        if machine is None:
            return
        if name == "CPSR":
            machine.set_flag(bit, not machine.cpsr >> bit & 1)
        elif name == "SPSR":
            machine.set_spsr_flag(bit, not machine.spsr >> bit & 1)
        else:
            machine.set_fpscr_flag(bit, not machine.vfp()[1] >> bit & 1)
        self._register_changed()

    def _register_blocked(self):
        """A value or flag was double-clicked while it cannot be changed.

        Before a program is assembled ARES Messages says why; while a program
        runs or waits nothing happens.
        """
        if self.machine is None:
            self.messages.write_message(NOT_ASSEMBLED)
            self.messages.show_messages()

    def _register_changed(self):
        request = self.machine.request
        if request is not None and request.kind != SLEEP:
            self.machine.drop_request()         # paused in a service: it runs again, as changed
        self.show_state()
        self._refresh_tools()

    def _assemble_opened(self):
        """Assemble the tab opened while the program ran (Assemble File Upon Opening)."""
        tab, self._assemble_later = self._assemble_later, None
        if tab in self.editor.tabs and self.settings.assemble_on_open:
            self.editor.select(tab)
            self.cmd_assemble()

    def _breakpoints_changed(self, addresses):
        """Make the machine stop at exactly these addresses."""
        if self.runner is None:
            return
        for address in self.machine.breakpoints - addresses:
            self.runner.set_breakpoint(address, False)
        for address in addresses - self.machine.breakpoints:
            self.runner.set_breakpoint(address, True)

    def cmd_clear_breakpoints(self):
        self.execute.text_segment.clear_breakpoints()

    def cmd_toggle_breakpoints(self):
        self.execute.text_segment.toggle_all()

    # Settings ------------------------------------------------------------------

    def _setting_toggled(self, name):
        """A check item of the Settings menu: like the other commands, it first applies an
        open register field; while its value is wrong the setting waits, its tick as it was."""
        var = self.setting_vars[name]
        if not self._apply_fields():
            var.set(getattr(self.settings, name))
            return
        setattr(self.settings, name, var.get())
        self.apply_settings()

    def _set_setting(self, name, value):
        """A setting changed elsewhere than in the Settings menu (the Data Segment's checkboxes).

        The press on the checkbox has already applied an open register field;
        a field still open holds a wrong value (the bell rang), and the
        setting waits as from the Settings menu, its tick as it was.
        """
        if any(pane.editor is not None for pane in self.register_panes):
            self.execute.data_segment.apply_settings()
            return
        setattr(self.settings, name, value)
        self.apply_settings()

    def cmd_editor_font(self):
        self.font_dialog = EditorFontDialog(self.root, self.settings, self.apply_settings)

    def cmd_restore_defaults(self):
        self.settings.restore_defaults()
        self.apply_settings()

    def apply_settings(self):
        """Show the current settings everywhere and save them."""
        s = self.settings
        for name, var in self.setting_vars.items():
            var.set(getattr(s, name))
        # Configured, even unchanged, a font has Tk lay out every text that shows it again.
        family = installed_family(s.font_family, self.families)
        for font in (self.editor_font, self.editor_bold):
            if (font.cget("family"), font.cget("size")) != (family, s.font_size):
                font.configure(family=family, size=s.font_size)
        self.editor.apply_settings()
        for pane in self.register_panes:
            pane.refresh()
        if self.runner is not None:
            self.runner.record_while_running = s.backstep_while_running
        self.execute.apply_settings()
        self.save_settings()

    def save_settings(self):
        self.settings.save(self.settings_path)

    # Messages ------------------------------------------------------------------

    def go_to_line(self, target):
        """Show a line of an open file: target is (tab, line number)."""
        tab, line = target
        if tab in self.editor.tabs:
            self.views.select(self.editor)
            self.editor.select(tab)
            tab.select_line(line)
            tab.text.focus_set()

    def _message_clicked(self, target):
        """Show the line a clicked message names.

        target is (tab, file, line number): the tab that was assembled and its
        file then (a path, or the name of an untitled file). The line is shown
        in that tab while it is open, even saved under another name; after it
        was closed, in the tab that has the file open now.
        """
        tab, file, line = target
        if tab not in self.editor.tabs and isinstance(file, Path):
            tab = self.editor.find(file)
        self.go_to_line((tab, line))

    def report_error(self, kind, value, trace):
        """Show an unexpected error in ARES Messages instead of losing it."""
        text = "".join(traceback.format_exception(kind, value, trace))
        if sys.stderr is not None:
            sys.stderr.write(text)
        try:
            self.messages.write_message(f"Internal error: {value!r}")
            for line in text.rstrip().splitlines():
                self.messages.write_message(line)
            self.messages.show_messages()
        except tk.TclError:
            pass


def build(source, workdir, name, require_capitals, cancel, tab_size):
    """Assemble and load a program in a worker thread.

    Returns (messages, Program, ares.disasm.Listing of its Text Segment),
    with None for the program and the listing when assembling failed.
    """
    try:
        result = assemble(source, workdir, display_name=name,
                          require_capitals=require_capitals, cancel=cancel)
    except ToolchainMissingError as e:
        return [Message(None, None, ERROR, str(e))], None, None
    if not result.ok:
        return result.messages, None, None
    program = Program(result.elf_path)
    return result.messages, program, disasm.listing(program, source, tab_size)


