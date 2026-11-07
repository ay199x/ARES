# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The menu bar of the main window: Windows 98's menu bar and menus, drawn by Tk.

On Windows ARES has its own menu bar instead of the system's: a soft gradient from white
down to a light gray, its titles dark in the interface font (Tk's TkMenuFont)
with their access letters underlined. The title under the mouse, or selected
with the keyboard, is raised by a thin bevel; the title whose menu is open is
pressed in, its text one pixel lower right. An etched line separates the bar
from the toolbar below it.

The menus are ARES's own pop-up windows, a canvas in a window without a frame:
Tk's menus on Windows are the system's own, which Windows 11 draws with
rounded corners, a flat border and a shadow that Tk cannot change. A menu has
the square raised border of Windows 98, its highlighted item blue with dark
text, shortcuts at the right, disabled items etched in gray, etched
separators and check marks. An item with an arrow at its right side opens a
submenu, a menu of the same kind beside the item: at its right, or at its left
where it does not fit there. Like Windows' own menus they float above the
other windows, and they never take the activation from the main window, so
its title bar stays active. Each menu is made once, at start-up; opening it
only shows the current states and check marks and places it below its title.

The keyboard works as in Windows. Alt pressed and released alone, or F10,
activates the bar with its first title selected, and deactivates it again;
Alt and a title's underlined letter open that menu. On the active bar Left
and Right move between the titles; Down, Up, Enter or a title's letter open
its menu; Escape deactivates the bar. In a menu Up and Down move between the
items, Left and Right open the menu beside it, Enter chooses the highlighted
item, an item's letter chooses it (or moves among the items that share the
letter), Escape closes the menu and Alt or F10 close every menu. Right, Enter
or the letter of an item with a submenu open it with its first item
highlighted. While it is open the keys work in it: Left and Escape close just
the submenu, and Right opens the menu beside as in a menu. While the
bar is in use a key pressed with Alt still held down does what it does
alone: Alt and F, then X, choose Exit, as in Windows. The mouse opens a
menu with a press on its title and chooses an item when it is released over
it. A press on an item with a submenu opens it at once, and so does the mouse
resting on that item for a moment; a moment after the mouse went on to another
item the submenu closes, so that the way into it may cross other items. A
press outside the menus closes them and does nothing else; so does
ARES losing the keyboard focus. While the bar is in use it has the keyboard
focus, which goes back where it was before a chosen command runs.

MenuBar and DropDown answer the part of tk.Menu's interface that the window
uses, so the window makes its menus the same way everywhere: menu_bar() gives
macOS's screen menu bar (Tk's own menus) on macOS, and new_menu() a menu for
a bar of either kind, or a submenu for a menu of either kind.
"""

import sys
import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont

from .style import (BAR_LINE, BEVEL, CHECK_MARK, FACE, HIGHLIGHT, MENU_BAR, MENU_SELECTION, RAISED,
                    SHADOW, TEXT, bevel,
                    check_mark, draw_gradient)
from .widgets import is_aqua, px, scale

MENU_BAR_CLASS = "AresMenubar"  # the bar's widget class: it has the keyboard focus while in use
MENU_CLASS = "AresMenu"         # the widget class of the menus' pop-up windows
FONT = "TkMenuFont"
# Sizes in design pixels.
TITLE_PADDING = 6.5     # left and right of a title's text
TITLE_HEIGHT = 20       # a title; with a larger font, its text and TITLE_ROOM
TITLE_ROOM = 5
ITEM_HEIGHT = 17        # an item of a menu; with a larger font, its text and ITEM_ROOM
ITEM_ROOM = 4
SEPARATOR_HEIGHT = 9
MARGIN = 1              # between a menu's raised border and its items
CHECK_WIDTH = 13        # the column of the check marks, at the left of the items
TEXT_LEFT = 17          # from an item's left side to its text
SHORTCUT_GAP = 12       # at least, between the widest text and the widest shortcut
RIGHT_SPACE = 13        # after the shortcuts, as wide as the check marks' column
SUBMENU_DELAY = 400     # ms the mouse rests before a submenu opens or closes, as in Windows
# The arrow of an item with a submenu, in the room after the shortcuts: its rows' lengths.
ARROW = (1, 2, 3, 4, 3, 2, 1)
# The thin bevel of a title: raised under the mouse or selected, sunken while its menu is open.
RAISED_TITLE = ((HIGHLIGHT, SHADOW),)
SUNKEN_TITLE = ((SHADOW, HIGHLIGHT),)
SHIFT, CONTROL = 0x1, 0x4       # event.state bits; Alt's depends on the windowing system
# Windows' own values for the pop-up windows of the menus.
GWL_EXSTYLE, WS_EX_NOACTIVATE = -20, 0x08000000
GWLP_WNDPROC = -4
WM_MOUSEACTIVATE, MA_NOACTIVATE = 0x0021, 3
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
MONITOR_DEFAULTTONEAREST = 2


def access_letter(text):
    """A label of the menu table without its "&", and the index of the letter the "&"
    marks (the access letter, underlined), or -1."""
    index = text.find("&")
    if index < 0:
        return text, -1
    return text[:index] + text[index + 1:], index


def menu_bar(root):
    """The main window's menu bar: macOS's screen menu bar (Tk's own) on macOS, elsewhere
    ARES's own bar, packed across the top of the window."""
    if is_aqua(root):
        bar = tk.Menu(root, tearoff=False)
        root.configure(menu=bar)
    else:
        bar = MenuBar(root)
        bar.pack(side="top", fill="x")
    return bar


def new_menu(parent):
    """An empty menu for a title of parent, a menu bar from menu_bar(), or for a submenu of
    parent, a menu from new_menu()."""
    if isinstance(parent, tk.Menu):
        return tk.Menu(parent, tearoff=False)
    return DropDown(parent.bar if isinstance(parent, DropDown) else parent)


def place_menu(x, top, bottom, size, area):
    """The screen point of the top left corner of a menu of size (width, height) for a title
    from x that spans top to bottom: below the title, their left sides aligned, kept on the
    screen area (left, top, right, bottom): moved left at its right side, and above the
    title when there is no room below it."""
    width, height = size
    left, upper, right, lower = area
    x = max(left, min(x, right - width))
    if bottom + height <= lower:
        return x, bottom
    if top - height >= upper:
        return x, top - height
    return x, max(upper, lower - height)


def place_submenu(left, right, top, size, area):
    """The screen point of the top left corner of a submenu of size (width, height) that opens
    at top beside a menu reaching from left to right: at its right side, at its left side
    when it does not fit there, kept on the screen area (left, top, right, bottom)."""
    width, height = size
    area_left, upper, area_right, lower = area
    if right + width <= area_right:
        x = right
    elif left - width >= area_left:
        x = left - width
    else:
        x = max(area_left, area_right - width)
    return x, max(upper, min(top, lower - height))


def menu_arrow(x0, y0, pixel):
    """The outline of the arrow of an item with a submenu from (x0, y0) as polygon points, each
    pixel pixel x pixel: down the right ends of its rows, then back up its left side."""
    ends = [point for k, length in enumerate(ARROW) for point in ((length, k), (length, k + 1))]
    outline = [(0, 0), *ends, (0, len(ARROW))]
    return [value for x, y in outline for value in (x0 + x * pixel, y0 + y * pixel)]


def screen_area(widget, x, y):
    """(left, top, right, bottom) of the screen at the point (x, y): on Windows the work
    area of the monitor there (without the taskbar), elsewhere Tk's screen."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class MonitorInfo(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                        ("work", wintypes.RECT), ("flags", wintypes.DWORD)]
        try:
            user32 = ctypes.WinDLL("user32")
            user32.MonitorFromPoint.restype = ctypes.c_void_p
            user32.MonitorFromPoint.argtypes = (wintypes.POINT, wintypes.DWORD)
            user32.GetMonitorInfoW.argtypes = (ctypes.c_void_p, ctypes.POINTER(MonitorInfo))
            monitor = user32.MonitorFromPoint(wintypes.POINT(x, y), MONITOR_DEFAULTTONEAREST)
            info = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
            if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                work = info.work
                return work.left, work.top, work.right, work.bottom
        except (AttributeError, OSError, ctypes.ArgumentError):
            pass
    return 0, 0, widget.winfo_screenwidth(), widget.winfo_screenheight()


def float_inactive(window):
    """Keep a pop-up window on the screen above the other windows, as Windows' own menus
    are, without it ever taking the activation from the main window, also when it is
    clicked: WS_EX_NOACTIVATE on its frame, and the frame refuses the activation a press
    asks for (refuse_activation()). Only on Windows, for a window on the screen; an error
    leaves the window as it is."""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        if not window.winfo_viewable():
            return
        user32 = _user32()
        frame = int(window.wm_frame(), 16)
        style = user32.GetWindowLongW(frame, GWL_EXSTYLE)
        user32.SetWindowLongW(frame, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
        user32.SetWindowPos(frame, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
        refuse_activation(window, frame)
    except (AttributeError, OSError, ValueError, tk.TclError, ctypes.ArgumentError):
        pass


def refuse_activation(window, frame):
    """Make window's frame (the Windows window frame) answer "do not activate" when a mouse
    press asks whether to activate it, and still take the press (MA_NOACTIVATE).

    Before Windows passes a press to a window that is not active, it asks the
    window with WM_MOUSEACTIVATE whether to activate it. Tk answers yes for a
    window inside its grab, which an open menu is. Activated, the menu's
    window would take the keyboard focus from the main window, and the menus
    close as soon as the focus leaves it, before the press comes. The frame
    gets a window procedure of its own that answers this question and hands
    every other message to Tk's procedure; Tk's comes back when the window is
    destroyed. Once per frame window.
    """
    known = getattr(window, "_refusal", None)
    if known is not None and known[0] == frame:
        return
    import ctypes
    user32 = _user32()
    tk_procedure = user32.get_procedure(frame, GWLP_WNDPROC)
    if not tk_procedure:
        return

    def procedure(hwnd, message, wparam, lparam):
        if message == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE
        return user32.CallWindowProcW(tk_procedure, hwnd, message, wparam, lparam)

    callback = user32.WNDPROC(procedure)
    user32.set_procedure(frame, GWLP_WNDPROC, ctypes.cast(callback, ctypes.c_void_p))
    if known is None:
        window.bind("<Destroy>", lambda event: _give_procedure_back(window, event), add="+")
    window._refusal = (frame, callback, tk_procedure)     # the procedure lives with the window


def _give_procedure_back(window, event):
    """Tk's own window procedure for the frame of a window being destroyed, before Tk
    destroys the frame (the window's own procedure must not outlive it)."""
    known = getattr(window, "_refusal", None)
    if event.widget is not window or known is None:
        return
    frame, _, tk_procedure = known
    user32 = _user32()
    if user32.IsWindow(frame):
        user32.set_procedure(frame, GWLP_WNDPROC, tk_procedure)


_USER32 = []


def _user32():
    """Windows' user32 with the prototypes of the functions the pop-up windows use, made
    once (Windows only). get_procedure and set_procedure read and set a window's procedure
    (the Ptr functions of 64-bit Windows, which 32-bit Windows has without Ptr)."""
    if not _USER32:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32")
        user32.GetWindowLongW.argtypes = (ctypes.c_void_p, ctypes.c_int)
        user32.SetWindowLongW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_long)
        user32.SetWindowPos.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint)
        user32.IsWindow.argtypes = (ctypes.c_void_p,)
        user32.CallWindowProcW.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                                           wintypes.WPARAM, wintypes.LPARAM)
        user32.CallWindowProcW.restype = wintypes.LPARAM          # LRESULT
        own = ctypes.WinDLL("user32")       # function objects of its own, with their prototypes
        pointer = hasattr(own, "GetWindowLongPtrW")
        get = own.GetWindowLongPtrW if pointer else own.GetWindowLongW
        put = own.SetWindowLongPtrW if pointer else own.SetWindowLongW
        get.argtypes = (ctypes.c_void_p, ctypes.c_int)
        put.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p)
        get.restype = put.restype = ctypes.c_void_p
        user32.get_procedure, user32.set_procedure = get, put
        user32.WNDPROC = ctypes.WINFUNCTYPE(wintypes.LPARAM, ctypes.c_void_p, ctypes.c_uint,
                                            wintypes.WPARAM, wintypes.LPARAM)
        _USER32.append(user32)
    return _USER32[0]


@dataclass
class _Title:
    label: str
    underline: int
    menu: object
    x0: int                     # its box on the bar's canvas, from x0 to x1
    x1: int
    text: int                   # its canvas item

    @property
    def letter(self):
        return _letter_of(self.label, self.underline)


@dataclass
class _Entry:
    kind: str                   # "command", "checkbutton", "cascade" or "separator"
    label: str = ""
    underline: int = -1
    accelerator: str = ""
    command: object = None
    variable: object = None     # a check item's tk.BooleanVar
    menu: object = None         # the submenu of a cascade item
    state: str = "normal"       # or "disabled"
    text: int = None            # its canvas items: the text and its etched copy,
    shadow: int = None
    key: int = None             # the shortcut and its etched copy,
    key_shadow: int = None
    check: int = None           # the check mark,
    arrow: int = None           # the arrow of a submenu and its etched copy,
    arrow_shadow: int = None
    lines: tuple = ()           # a separator's two lines
    top: int = 0                # its row on the canvas
    bottom: int = 0

    @property
    def letter(self):
        return _letter_of(self.label, self.underline)


def _letter_of(label, underline):
    return label[underline].lower() if 0 <= underline < len(label) else ""


def _typed_letter(event):
    """The letter or digit of a key event, in lower case ("" for other keys)."""
    keysym = event.keysym
    char = keysym if len(keysym) == 1 else event.char
    return char.lower() if char and char.isprintable() and not char.isspace() else ""


class MenuBar(tk.Frame):
    """ARES's menu bar across the top of the main window, with its menus (see the module).

    It answers tk.Menu's add_cascade(), index() and entrycget() for its
    titles. It is active while a title is selected from the keyboard or a
    menu is open: it then has the keyboard focus, and a grab brings it the
    mouse's events outside it and its menus. A menu of a title can have
    submenus, one open at a time; they do not have submenus of their own.
    """

    def __init__(self, master):
        super().__init__(master, class_=MENU_BAR_CLASS, background=FACE, borderwidth=0,
                         highlightthickness=0, takefocus=0)
        self.font = tkfont.nametofont(FONT, root=self)
        self.menus = []                 # the menu of each title, in order
        self.active = False
        self.selected = None            # the index of the selected title while active
        self.open_menu = None           # the menu on the screen
        self.sub_menu = None            # the submenu on the screen beside it
        self._sub_index = None          # the item of the open menu it belongs to
        self._titles = []
        self._hot = None                # the title under the mouse while not active
        self._previous = None           # the widget that had the keyboard focus before
        self._held = set()              # "Alt" and "F10" held down since a press the bar took
        self._alone = None              # "Alt" or "F10" pressed with no other key since
        self._eating = False            # a press outside closed the menus: its release ends here
        self._settle_job = None         # looks where the keyboard focus went (_focus_left)
        self._wait_job = None           # opens or closes a submenu once the mouse rested
        self._window = self.winfo_toplevel()
        self._alt = 0x20000 if self._windowingsystem == "win32" else 0x8
        ring = self._ring = px(self, BEVEL)
        line = self.font.metrics("linespace")
        self._title_height = max(px(self, TITLE_HEIGHT), line + px(self, TITLE_ROOM))
        self._text_y = (self._title_height - line) // 2
        canvas = self.canvas = tk.Canvas(self, height=self._title_height + 3 * ring,
                                         background=FACE, borderwidth=0, highlightthickness=0,
                                         takefocus=0)
        canvas.pack(fill="x")
        top = self._title_height + ring
        self._rows = draw_gradient(canvas, MENU_BAR, top)       # under all the rest
        self._bevel = [canvas.create_rectangle(0, 0, 0, 0, width=0, state="hidden")
                       for _ in range(4)]
        # Under the titles a gap of the face colour, then the bar's gray line.
        self._lines = [canvas.create_rectangle(0, top, 0, top + ring, fill=FACE, width=0),
                       canvas.create_rectangle(0, top + ring, 0, top + 2 * ring, fill=BAR_LINE,
                                               width=0)]
        canvas.bind("<Configure>", self._resized)
        canvas.bind("<Motion>", self._moved)
        canvas.bind("<Leave>", self._left)
        canvas.bind("<ButtonPress-1>", self._pressed)
        canvas.bind("<ButtonRelease>", self._released)
        # During the grab the mouse's events elsewhere in ARES come to the bar itself.
        self.bind("<Motion>", self._moved)
        self.bind("<ButtonPress>", self._pressed)
        self.bind("<ButtonRelease>", self._released)
        self.bind("<KeyPress>", self._key)
        self.bind("<FocusIn>", self._focus_came)
        window = self._window
        window.bind_class(window.winfo_class(), "<Configure>", self._window_configured, add="+")
        self._originals = {}
        self._bind_window_keys()
        self._prepare_job = self.after_idle(self._prepare)

    def destroy(self):
        for job in (self._prepare_job, self._settle_job, self._wait_job):
            if job is not None:
                self.after_cancel(job)
        self._prepare_job = self._settle_job = self._wait_job = None
        for sequence, original in self._originals.items():
            self.tk.call("bind", "all", sequence, original)
        super().destroy()

    # tk.Menu's interface -------------------------------------------------------

    def add_cascade(self, label="", menu=None, underline=-1):
        """Add a title at the right, for menu (a DropDown of this bar)."""
        x0 = self._titles[-1].x1 if self._titles else 0
        padding = px(self, TITLE_PADDING)
        x1 = x0 + self.font.measure(label) + 2 * padding
        text = self.canvas.create_text(x0 + padding, self._text_y, anchor="nw", text=label,
                                       font=FONT, fill=TEXT, underline=underline)
        self._titles.append(_Title(label, underline, menu, x0, x1, text))
        self.menus.append(menu)

    def index(self, index):
        if index in ("end", "last"):
            return len(self._titles) - 1 if self._titles else None
        return int(index)

    def entrycget(self, index, option):
        title = self._titles[index]
        if option == "label":
            return title.label
        if option == "underline":
            return title.underline
        if option == "menu":
            return str(title.menu)
        raise tk.TclError(f'unknown option "-{option}"')

    # Opening and closing ---------------------------------------------------------

    def activate(self, index=0):
        """Activate the bar with title index selected, its menu closed (Alt or F10)."""
        if not self.active:
            self._start()
        self._close_menu()
        self.selected = index
        self._paint()

    def open(self, index, first=False):
        """Open the menu of title index below it; first highlights its first item."""
        if not self.active:
            self._start()
        menu = self.menus[index]
        if self.open_menu is not menu:
            self._close_menu()
            self.open_menu, self.selected = menu, index
            self._paint()
            menu.show(*self._place(index, menu), first=first)
        elif first and menu.active is None:
            menu.move(1)

    def open_submenu(self, index, first=False):
        """Open the submenu of item index of the open menu beside it, at once; first highlights
        its first item."""
        menu = self.open_menu
        self._stop_waiting()
        if self._sub_index != index:
            self._close_submenu()
            sub = self.sub_menu = menu.entries[index].menu
            self._sub_index = index
            menu.highlight(index)
            sub.show(*self._place_submenu(index, menu, sub), first=first)
        elif first and self.sub_menu.active is None:
            self.sub_menu.move(1)

    def close(self):
        """Close the menus and deactivate the bar: the keyboard focus goes back where it was."""
        if self.active:
            self._end()
            self._give_back()

    def choose(self, index, menu=None, first=False):
        """Choose item index of menu (the open menu, unless the open submenu is given): the
        menus close and the focus goes back, then its command runs. An item with a submenu
        opens it (first: see open_submenu()). A disabled item or a separator does nothing."""
        menu = self.open_menu if menu is None else menu
        if menu is None or not menu.enabled(index):
            return
        if menu.type(index) == "cascade":
            self.open_submenu(index, first)
            return
        self.close()
        menu.invoke(index)

    def _start(self):
        """Activate the bar: it takes the keyboard focus and a grab."""
        previous = self._focus_now()
        if isinstance(previous, tk.Misc) and previous is not self:
            self._previous = previous
        self.active = True
        self._hot = self._alone = None
        self._eating = False
        self.focus_set()
        try:
            self.grab_set()
        except tk.TclError:             # no grab: the menus work, a press outside acts too
            pass

    def _end(self):
        """Hide the open menu and deactivate the bar; the keyboard focus stays where it is.
        The grab stays while the release of a press outside is awaited (_released)."""
        self._close_menu()
        self.active = False
        self.selected = None
        if not self._eating:
            self.grab_release()
        self._paint()

    def _stop_eating(self):
        """Let the mouse go once the release of the press outside came (or never will)."""
        if self._eating:
            self._eating = False
            if not self.active:
                self.grab_release()

    def _close_submenu(self):
        """Hide the open submenu; its menu stays open."""
        self._stop_waiting()
        sub, self.sub_menu, self._sub_index = self.sub_menu, None, None
        if sub is not None:
            sub.hide()

    def _close_menu(self):
        """Hide the open menu; the bar stays active with its title selected."""
        self._close_submenu()
        menu, self.open_menu = self.open_menu, None
        if menu is not None:
            menu.hide()
            self._paint()

    def _give_back(self):
        """Give the keyboard focus back to the widget that had it before (else the window)."""
        widget, self._previous = self._previous, None
        if widget is None or not widget.winfo_exists():
            widget = self._window
        widget.focus_set()

    def _focus_now(self):
        """The widget with the keyboard focus: None while ARES has none, the path of one
        tkinter does not know (Tk's own pop-ups)."""
        try:
            return self._window.focus_get()
        except KeyError:
            return str(self.tk.call("focus"))

    def _place(self, index, menu):
        """Where the menu of title index goes on the screen."""
        title, canvas = self._titles[index], self.canvas
        x, top = canvas.winfo_rootx() + title.x0, canvas.winfo_rooty()
        menu.lay_out()
        return place_menu(x, top, top + self._title_height, (menu.width, menu.height),
                          screen_area(self, x, top))

    def _place_submenu(self, index, menu, sub):
        """Where the submenu of item index of menu goes on the screen: its first item level
        with that item, its border over the menu's."""
        x, y = menu.spot
        frame = menu._sides[0]
        top = y + menu.entries[index].top - frame
        sub.lay_out()
        return place_submenu(x + frame, x + menu.width - frame, top, (sub.width, sub.height),
                             screen_area(self, x, top))

    def _prepare(self):
        """Lay the menus out at start-up, so that opening one only shows it."""
        self._prepare_job = None
        for menu in self.menus:
            menu.lay_out()

    # Drawing -----------------------------------------------------------------------

    def _paint(self):
        """Give the title that has one its bevel, and press in the text of an open title."""
        if self.open_menu is not None:
            index, rings = self.selected, SUNKEN_TITLE
        elif self.active:
            index, rings = self.selected, RAISED_TITLE
        else:
            index, rings = self._hot, RAISED_TITLE
        canvas, ring = self.canvas, self._ring
        padding = px(self, TITLE_PADDING)
        for k, title in enumerate(self._titles):
            shift = ring if k == index and rings is SUNKEN_TITLE else 0
            canvas.coords(title.text, title.x0 + padding + shift, self._text_y + shift)
        if index is None:
            for item in self._bevel:
                canvas.itemconfigure(item, state="hidden")
            return
        title = self._titles[index]
        for item, (colour, box) in zip(self._bevel, bevel(title.x0, 0, title.x1,
                                                          self._title_height, ring, rings)):
            canvas.coords(item, *box)
            canvas.itemconfigure(item, fill=colour, state="normal")

    def _resized(self, event):
        for item in self._lines:
            x0, y0, x1, y1 = self.canvas.coords(item)
            self.canvas.coords(item, 0, y0, event.width, y1)

    # The mouse -----------------------------------------------------------------------

    def _locate(self, x, y, widget):
        """What is at the screen point (x, y): ("title", index), ("item", index) in the open
        menu, ("sub", index) in the open submenu (index None on a border or a separator), or
        None. Where they cover each other, widget, the window the event came to, decides; a
        submenu lies over the others."""
        def title():
            canvas = self.canvas
            bx, by = x - canvas.winfo_rootx(), y - canvas.winfo_rooty()
            if 0 <= by < self._title_height:
                for index, box in enumerate(self._titles):
                    if box.x0 <= bx < box.x1:
                        return "title", index
            return None

        def inside(kind, menu):
            if menu is None:
                return None
            mx, my = x - menu.canvas.winfo_rootx(), y - menu.canvas.winfo_rooty()
            if 0 <= mx < menu.width and 0 <= my < menu.height:
                return kind, menu.entry_at(mx, my)
            return None

        def item():
            return inside("item", self.open_menu)

        def sub():
            return inside("sub", self.sub_menu)
        if widget is self.canvas:
            order = title, sub, item
        elif self.open_menu is not None and widget is self.open_menu.canvas:
            order = item, sub, title
        else:
            order = sub, item, title
        return order[0]() or order[1]() or order[2]()

    def _event_place(self, event):
        return self._locate(event.x_root, event.y_root, event.widget)

    def _moved(self, event):
        """The mouse moved: over the bar a title is raised (or its menu opened while another
        is open); in the open menus the item under it is highlighted."""
        place = self._event_place(event)
        kind, index = place if place is not None else (None, None)
        if not self.active:
            hot = index if kind == "title" else None
            if hot != self._hot:
                self._hot = hot
                self._paint()
        elif kind == "title":
            if index != self.selected:
                if self.open_menu is not None:
                    self.open(index)
                else:
                    self.activate(index)
        elif self.open_menu is not None:
            self._hovered(kind, index)

    def _hovered(self, kind, index):
        """The mouse moved in the open menu (kind "item"), in its submenu ("sub") or away from
        them (None). An open submenu stays open with its item highlighted, unless the mouse
        is on another item of the menu."""
        menu, sub = self.open_menu, self.sub_menu
        if kind == "item" or sub is None:
            menu.highlight(index if kind == "item" else None)
        else:
            menu.highlight(self._sub_index)
        if sub is not None:
            sub.highlight(index if kind == "sub" else None)
        if self._highlighted_submenu() == self._sub_index:
            self._stop_waiting()
        elif self._wait_job is None:
            self._wait_job = self.after(SUBMENU_DELAY, self._rested)

    def _highlighted_submenu(self):
        """The index of the highlighted item of the open menu if it opens a submenu, else
        None."""
        menu = self.open_menu
        index = menu.active
        return index if index is not None and menu.enabled(index) and menu.type(
            index) == "cascade" else None

    def _rested(self):
        """The wait of the mouse is over: the highlighted item decides which submenu is open."""
        self._wait_job = None
        index = self._highlighted_submenu()
        if index is None:
            self._close_submenu()
        else:
            self.open_submenu(index)

    def _stop_waiting(self):
        if self._wait_job is not None:
            self.after_cancel(self._wait_job)
            self._wait_job = None

    def _left(self, event):
        if not self.active and self._hot is not None:
            self._hot = None
            self._paint()

    def _pressed(self, event):
        """A mouse press on the bar, in a menu, or anywhere else while the bar is active.

        A press on a title opens its menu, or closes it when it is open; a press
        on an item with a submenu opens that; a press outside the bar and the
        menus closes them and does nothing else (Windows takes such a click, its
        release too). The press ends here: it never applies an open register
        field.
        """
        self._alone = None
        self._stop_eating()             # the release of the last press outside never came
        place = self._event_place(event)
        if place is None:
            self._eating = self.active
            self.close()
        elif place[0] == "title" and event.num == 1:
            index = place[1]
            if self.open_menu is not None and index == self.selected:
                self.close()
            else:
                self.open(index)
        elif place[0] == "item" and place[1] is not None and event.num == 1:
            menu = self.open_menu
            if menu.enabled(place[1]) and menu.type(place[1]) == "cascade":
                self.open_submenu(place[1])
        return "break"

    def _released(self, event):
        """A release over an enabled item of the open menus chooses it, also at the end of a
        press on its title that was dragged into the menu. The release of a press outside
        that closed the menus ends here, with the grab: it does nothing either (an error
        message's link, for one, would take it as a click)."""
        if self._eating:
            self._stop_eating()
            return "break"
        place = self._event_place(event)
        if event.num == 1 and place is not None and place[1] is not None:
            if place[0] == "item":
                self.choose(place[1])
            elif place[0] == "sub":
                self.choose(place[1], self.sub_menu)
        return "break"

    # The keyboard ------------------------------------------------------------------------

    def _key(self, event):
        """A key pressed while the bar has the keyboard focus.

        While the bar is active every key but Alt and F10 (the window's, see
        _bind_window_keys) ends here, as Windows' menus take every key, also
        one pressed with Alt still held down: Alt and F, then X, choose Exit.
        A key ends the wait of the mouse, and an open submenu then has it.
        """
        keysym = event.keysym
        if not self.active or keysym in ("Alt_L", "Alt_R", "F10"):
            return None
        menu, sub = self.open_menu, self.sub_menu
        self._stop_waiting()
        if sub is not None:
            menu.highlight(self._sub_index)
        if keysym == "Right" and self._can_enter_submenu():
            self.open_submenu(menu.active, first=True)
        elif keysym == "Left" and sub is not None:
            self._close_submenu()
        elif keysym in ("Left", "Right"):
            index = (self.selected + (1 if keysym == "Right" else -1)) % len(self._titles)
            if menu is None:
                self.activate(index)
            else:
                self.open(index, first=True)
        elif keysym in ("Up", "Down") and menu is not None:
            (menu if sub is None else sub).move(1 if keysym == "Down" else -1)
        elif keysym in ("Up", "Down", "Return", "KP_Enter") and menu is None:
            self.open(self.selected, first=True)
        elif keysym in ("Return", "KP_Enter"):
            target = sub if sub is not None and sub.active is not None else menu
            if target.active is not None:
                self.choose(target.active, target, first=True)
        elif keysym == "Escape":
            if menu is None:
                self.close()
            elif sub is not None:
                self._close_submenu()
            else:
                self._close_menu()
        elif not event.state & CONTROL:
            self._letter(_typed_letter(event), event.char)
        return "break"

    def _can_enter_submenu(self):
        """True when Right opens the highlighted item's submenu, or goes into the open one
        that has no highlighted item yet (the mouse opened it)."""
        return (self.open_menu is not None and self._highlighted_submenu() is not None
                and (self.sub_menu is None or self.sub_menu.active is None))

    def _letter(self, letter, char):
        """A letter typed on the active bar opens the menu of the title it is the access
        letter of; in a menu or the open submenu it chooses the item it is the access letter
        of, or moves the highlight among the items that share it. A letter no title or item
        has rings."""
        menu = self.open_menu if self.sub_menu is None else self.sub_menu
        if not letter:
            if char and char.isprintable():
                self.bell()
            return
        if menu is None:
            index = self._title_with(letter)
            if index is None:
                self.bell()
            else:
                self.open(index, first=True)
            return
        matches = [k for k, entry in enumerate(menu.entries) if entry.letter == letter]
        if not matches:
            self.bell()
        elif len(matches) == 1 and menu.enabled(matches[0]):
            self.choose(matches[0], menu, first=True)
        else:
            later = [k for k in matches if menu.active is not None and k > menu.active]
            menu.highlight((later or matches)[0])

    def _title_with(self, letter):
        return next((k for k, title in enumerate(self._titles)
                     if letter and title.letter == letter), None)

    def _bind_window_keys(self):
        """Bind Alt, F10 and Alt+letter, and the keyboard focus leaving, on every widget (the
        "all" tag, which the field of a register's value has too).

        Tk's own bindings for these keys there work Windows' own menu bar: they
        run only when the bar leaves a key alone, as for the keys of ARES's
        other windows, Alt+Space (the window menu), Alt+F4, and keys held with
        Control (AltGr is Control and Alt).
        """
        for sequence, handler in (("<Key-Alt_L>", self._menu_key_pressed),
                                  ("<Key-Alt_R>", self._menu_key_pressed),
                                  ("<Key-F10>", self._menu_key_pressed),
                                  ("<KeyRelease-Alt_L>", self._menu_key_released),
                                  ("<KeyRelease-Alt_R>", self._menu_key_released),
                                  ("<KeyRelease-F10>", self._menu_key_released),
                                  ("<Alt-Key>", self._alt_key),
                                  ("<FocusOut>", self._focus_left)):
            original = str(self.tk.call("bind", "all", sequence))
            self._originals[sequence] = original
            self.bind_class("all", sequence, handler)
            ours = str(self.tk.call("bind", "all", sequence))
            self.tk.call("bind", "all", sequence, ours + original)

    def _in_window(self, event):
        """True when a key event is for a widget of the main window (not a dialog or tool)."""
        try:
            return str(self.tk.call("winfo", "toplevel", str(event.widget))) == str(self._window)
        except tk.TclError:
            return False

    def _menu_key_pressed(self, event):
        """Alt or F10 pressed: on the active bar they close everything; pressed alone, their
        release activates the bar."""
        name = "F10" if event.keysym == "F10" else "Alt"
        others = CONTROL | (SHIFT | self._alt if name == "F10" else 0)
        if event.state & others or not self._in_window(event):
            self._alone = None
            return None
        if name in self._held:
            return "break"              # held down, the key repeats
        self._held.add(name)
        if self.active:
            self.close()
        else:
            self._alone = name
        return "break"

    def _menu_key_released(self, event):
        """Alt or F10 released: pressed alone, it activates the bar. Windows never gets the
        release in the main window, which would start its own menu mode (but for AltGr)."""
        name = "F10" if event.keysym == "F10" else "Alt"
        self._held.discard(name)                # released, also in another window
        if not self._in_window(event) or (name == "Alt" and event.state & CONTROL):
            self._alone = None
            return None
        if self._alone == name:
            self._alone = None
            self.activate()
        return "break"

    def _alt_key(self, event):
        """Alt and another key: a title's access letter opens its menu with its first item
        highlighted; Tk has the other keys. Windows may then take Alt's release (Alt+Space
        opens its window menu), so Alt counts as released."""
        self._alone = None
        if event.state & CONTROL or not self._in_window(event):
            return None
        index = self._title_with(_typed_letter(event))
        if index is None:
            self._held.discard("Alt")
            return None
        self.open(index, first=True)
        return "break"

    # The keyboard focus and the window ---------------------------------------------------

    def _focus_left(self, event):
        """The keyboard focus left a widget. Once it has left ARES, Alt and F10 start afresh
        and the mouse is let go (their release went to another program); once it has left
        the bar, the menus close (another program or another ARES window came to the
        front).

        When it seems to have left ARES, where it went is known once the focus
        changes of the moment are done (_focus_settled): a menu's window that
        Windows activated at a press takes it from the main window just before
        that press comes, and the menus must still be open for the press.
        """
        focus = self._focus_now()
        if focus is None:
            self._held.clear()
            self._alone = None
            self._stop_eating()
            if self.active and self._settle_job is None:
                self._settle_job = self.after_idle(self._focus_settled)
            return
        self._follow_focus(focus)

    def _focus_settled(self):
        self._settle_job = None
        self._follow_focus(self._focus_now())

    def _follow_focus(self, focus):
        """The bar in use keeps the keyboard focus on itself, also when the open menu gets
        it; when another window has it, or none of ARES's, the menus close."""
        if not self.active or focus is self:
            return
        if self._in_open_menu(focus):
            self.focus_set()            # the menu was given the focus: the bar keeps it
        else:
            self._end()

    def _in_open_menu(self, widget):
        """True when widget is the open menu, its submenu or one of their parts."""
        try:
            return widget is not None and str(self.tk.call("winfo", "toplevel", str(widget))) in (
                str(self.open_menu), str(self.sub_menu))
        except tk.TclError:
            return False

    def _focus_came(self, event):
        """The bar has the keyboard focus while not in use: the window was activated again
        after its menus closed. The focus goes back where it was before the menus."""
        if not self.active and self._focus_now() is self:
            self._give_back()

    def _window_configured(self, event):
        """The window was moved or resized: the menus close, as when its title bar is clicked."""
        if event.widget is self._window and self.active:
            self.close()


class DropDown(tk.Toplevel):
    """A menu of a MenuBar: Windows 98's raised pop-up with its items, on a canvas.

    It answers tk.Menu's add_command(), add_checkbutton(), add_cascade(),
    add_separator(), index(), type(), entrycget(), entryconfigure() and
    invoke(). Its items are laid out once (lay_out()); show() puts it on the
    screen with the current states and check marks, hide() takes it away.
    """

    def __init__(self, bar):
        super().__init__(bar, class_=MENU_CLASS, background=FACE, borderwidth=0,
                         highlightthickness=0)
        self.withdraw()
        self.overrideredirect(True)             # no frame; float_inactive() when shown
        self.bar = bar
        self.entries = []
        self.active = None              # the highlighted item
        self.width = self.height = 0
        self.spot = (0, 0)              # the screen point of its top left corner, when shown
        self._sides = (0, 0)            # the items' left and right sides
        self._border = []               # the rectangles of the raised border
        self._laid_out = False
        canvas = self.canvas = tk.Canvas(self, background=FACE, borderwidth=0,
                                         highlightthickness=0, takefocus=0)
        canvas.pack()
        self._lit = canvas.create_rectangle(0, 0, 0, 0, fill=MENU_SELECTION, width=0,
                                            state="hidden")
        canvas.bind("<Motion>", bar._moved)
        canvas.bind("<ButtonPress>", bar._pressed)
        canvas.bind("<ButtonRelease-1>", bar._released)
        self.bind("<Map>", self._mapped)

    # tk.Menu's interface -------------------------------------------------------

    def add_command(self, label="", command=None, accelerator="", underline=-1, state="normal"):
        self._add(_Entry("command", label, underline, accelerator, command, state=state))

    def add_checkbutton(self, label="", variable=None, command=None, underline=-1):
        self._add(_Entry("checkbutton", label, underline, "", command, variable))

    def add_cascade(self, label="", menu=None, underline=-1):
        """Add an item that opens menu, a DropDown of the same bar, as a submenu."""
        self._add(_Entry("cascade", label, underline, menu=menu))

    def add_separator(self):
        self._add(_Entry("separator"))

    def index(self, index):
        if index in ("end", "last"):
            return len(self.entries) - 1 if self.entries else None
        return int(index)

    def type(self, index):
        return self.entries[index].kind

    def entrycget(self, index, option):
        if option == "menu":
            return str(self.entries[index].menu)
        if option not in ("label", "accelerator", "state", "underline", "command", "variable"):
            raise tk.TclError(f'unknown option "-{option}"')
        return getattr(self.entries[index], option)

    def entryconfigure(self, index, **options):
        """Change an item's state ("normal" or "disabled"); an open menu shows it at once."""
        entry = self.entries[index]
        for option, value in options.items():
            if option != "state":
                raise tk.TclError(f'unknown option "-{option}"')
            entry.state = str(value)
        if self.bar.open_menu is self or self.bar.sub_menu is self:
            self._paint(index)

    entryconfig = entryconfigure

    def invoke(self, index):
        """Carry out item index as when it is chosen; a check item first changes its
        variable. A disabled item does nothing."""
        entry = self.entries[index]
        if not self.enabled(index):
            return None
        if entry.variable is not None:
            entry.variable.set(not entry.variable.get())
        return entry.command() if entry.command is not None else None

    # The items -----------------------------------------------------------------------

    def enabled(self, index):
        """True when item index can be chosen (not disabled, not a separator)."""
        entry = self.entries[index]
        return entry.kind != "separator" and entry.state != "disabled"

    def _add(self, entry):
        """Make the canvas items of an entry; lay_out() puts them in place."""
        canvas = self.canvas
        if entry.kind == "separator":
            entry.lines = tuple(canvas.create_rectangle(0, 0, 0, 0, fill=colour, width=0)
                                for colour in (SHADOW, HIGHLIGHT))
        else:
            # Disabled, a text is gray on a white copy one pixel lower right.
            entry.shadow, entry.text = (
                canvas.create_text(0, 0, anchor="nw", text=entry.label, font=FONT, fill=fill,
                                   underline=entry.underline, state=state)
                for fill, state in ((HIGHLIGHT, "hidden"), (TEXT, "normal")))
            if entry.accelerator:
                entry.key_shadow, entry.key = (
                    canvas.create_text(0, 0, anchor="ne", text=entry.accelerator, font=FONT,
                                       fill=fill, state=state)
                    for fill, state in ((HIGHLIGHT, "hidden"), (TEXT, "normal")))
            if entry.kind == "checkbutton":
                entry.check = canvas.create_polygon(0, 0, 0, 0, 0, 0, width=0, fill=TEXT,
                                                    state="hidden")
            elif entry.kind == "cascade":
                entry.arrow_shadow, entry.arrow = (
                    canvas.create_polygon(0, 0, 0, 0, 0, 0, width=0, fill=fill, state=state)
                    for fill, state in ((HIGHLIGHT, "hidden"), (TEXT, "normal")))
        self.entries.append(entry)
        self._laid_out = False

    def lay_out(self):
        """Place the items and draw the raised border, once for the items there are; the same
        for its submenus."""
        if self._laid_out:
            return
        self._laid_out = True
        canvas, font = self.canvas, self.bar.font
        ring = px(self, BEVEL)
        frame = 2 * ring + px(self, MARGIN)
        line = font.metrics("linespace")
        row = max(px(self, ITEM_HEIGHT), line + px(self, ITEM_ROOM))
        texts = max((font.measure(e.label) for e in self.entries if e.kind != "separator"),
                    default=0)
        keys = max((font.measure(e.accelerator) for e in self.entries if e.accelerator),
                   default=0)
        width = (2 * frame + px(self, TEXT_LEFT) + texts
                 + (px(self, SHORTCUT_GAP) + keys if keys else 0) + px(self, RIGHT_SPACE))
        left, right = self._sides = frame, width - frame
        pixel = max(1, round(scale(self)))      # the check mark's pixels, as on the tables
        mark = len(CHECK_MARK) * pixel
        arrow_width, arrow_height = max(ARROW) * pixel, len(ARROW) * pixel
        y = frame
        for entry in self.entries:
            if entry.kind == "separator":
                height = px(self, SEPARATOR_HEIGHT)
                middle = y + height // 2
                for k, item in enumerate(entry.lines):
                    canvas.coords(item, left + ring, middle + k * ring, right - ring,
                                  middle + (k + 1) * ring)
            else:
                height = row
                text_y = y + (row - line) // 2
                x = left + px(self, TEXT_LEFT)
                canvas.coords(entry.text, x, text_y)
                canvas.coords(entry.shadow, x + ring, text_y + ring)
                if entry.key is not None:
                    x = right - px(self, RIGHT_SPACE)
                    canvas.coords(entry.key, x, text_y)
                    canvas.coords(entry.key_shadow, x + ring, text_y + ring)
                if entry.check is not None:
                    canvas.coords(entry.check, *check_mark(
                        left + (px(self, CHECK_WIDTH) - mark) // 2, y + (row - mark) // 2, pixel))
                if entry.arrow is not None:
                    x = right - (px(self, RIGHT_SPACE) + arrow_width) // 2
                    arrow_y = y + (row - arrow_height) // 2
                    canvas.coords(entry.arrow, *menu_arrow(x, arrow_y, pixel))
                    canvas.coords(entry.arrow_shadow, *menu_arrow(x + ring, arrow_y + ring, pixel))
                    entry.menu.lay_out()
            entry.top, entry.bottom = y, y + height
            y += height
        height = y + frame
        pieces = bevel(0, 0, width, height, ring, RAISED)
        if not self._border:
            self._border = [canvas.create_rectangle(0, 0, 0, 0, fill=colour, width=0)
                            for colour, _ in pieces]
        for item, (_, box) in zip(self._border, pieces):
            canvas.coords(item, *box)
        canvas.configure(width=width, height=height)
        self.width, self.height = width, height

    def entry_at(self, x, y):
        """The item at (x, y) of the canvas, or None (the border, a separator)."""
        left, right = self._sides
        if left <= x < right:
            for index, entry in enumerate(self.entries):
                if entry.top <= y < entry.bottom:
                    return None if entry.kind == "separator" else index
        return None

    def _paint(self, index):
        """Colour item index for its state: highlighted (on blue), disabled (gray,
        etched unless highlighted) or neither; show its check mark when its variable is on."""
        entry = self.entries[index]
        if entry.kind == "separator":
            return
        lit, enabled = index == self.active, entry.state != "disabled"
        colour = SHADOW if not enabled else TEXT
        etched = "normal" if not enabled and not lit else "hidden"
        canvas = self.canvas
        for text, shadow in ((entry.text, entry.shadow), (entry.key, entry.key_shadow),
                             (entry.arrow, entry.arrow_shadow)):
            if text is not None:
                canvas.itemconfigure(text, fill=colour)
                canvas.itemconfigure(shadow, state=etched)
        if entry.check is not None:
            canvas.itemconfigure(entry.check, fill=colour,
                                 state="normal" if entry.variable.get() else "hidden")

    def highlight(self, index):
        """Highlight item index (None, or a separator: no item)."""
        if index is not None and self.entries[index].kind == "separator":
            index = None
        if index == self.active:
            return
        previous, self.active = self.active, index
        if previous is not None:
            self._paint(previous)
        if index is None:
            self.canvas.itemconfigure(self._lit, state="hidden")
            return
        entry = self.entries[index]
        left, right = self._sides
        self.canvas.coords(self._lit, left, entry.top, right, entry.bottom)
        self.canvas.itemconfigure(self._lit, state="normal")
        self._paint(index)

    def move(self, step):
        """Highlight the next item down (1) or up (-1), round the menu, past the separators;
        with none highlighted, the first or the last."""
        count = len(self.entries)
        index = self.active if self.active is not None else (-1 if step > 0 else count)
        for _ in range(count):
            index = (index + step) % count
            if self.entries[index].kind != "separator":
                self.highlight(index)
                return

    # On the screen -----------------------------------------------------------------------

    def show(self, x, y, first=False):
        """Show the menu with its top left corner at the screen point (x, y), with the current
        states and check marks; first highlights the first item (as the keyboard opens it)."""
        self.lay_out()
        self.highlight(None)
        for index in range(len(self.entries)):
            self._paint(index)
        if first:
            self.move(1)
        self.spot = x, y
        self.geometry(f"+{x}+{y}")
        self.deiconify()

    def hide(self):
        self.withdraw()
        self.highlight(None)

    def _mapped(self, event):
        if event.widget is self:
            float_inactive(self)
