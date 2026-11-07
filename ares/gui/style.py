# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The look of every window ARES draws: classic panes, drawn the Windows 98 way.

apply() is called once for each Tk root before its widgets are made. It
makes the ttk theme "ares98" current, gives Tk's named fonts the interface
font, and sets the option database for Tk's own widgets, so the main window,
its dialogs and every later window of that root share the look: light gray
faces, raised buttons that press in, sunken white fields, tabs joined to a
framed page, checkboxes, radio buttons and thick scroll bars, etched group
boxes, and light blue selections.

Everything is drawn in flat colours with crisp bevels and no pictures; only the
menu bar and the toolbar's strip have a soft gradient, a canvas item for each
row of pixels (draw_gradient()). Tk draws every part itself: the theme is made
of ttk's built-in elements with widths scaled with the display. It has no image
elements; only the icons are pictures (ares.gui.icons). With Tk 8.6 a picture
element draws its picture tile by tile, each tile with new drawing objects of
the system: at 4K a page of the window takes seconds. A thin bright accent line
marks the active title bar, and nothing larger.

For the window's own parts: sunken() gives a frame the sunken border of a
field and insets its contents by it, group() makes an etched group box,
draw_bevel() draws a bevel on a canvas (the raised headings of the tables),
draw_gradient() a gradient from top to bottom of a canvas,
draw_checkbox() draws a checkbox on a canvas (the breakpoints of the Text
Segment), and default_button() gives a dialog's default button the black
frame, which moves to whichever push button has the keyboard focus.
"""

from tkinter import font as tkfont
from tkinter import ttk

from .widgets import px, scale

# Colours.
FACE = "#EEEEEE"            # buttons, bars and window backgrounds
HIGHLIGHT = "#FFFFFF"       # bevels: the brightest lit lines
LIGHT = "#F7F7F7"           # bevels: the softer lit lines
SHADOW = "#8E8E8E"          # bevels: gray shaded lines; disabled text
DARK_SHADOW = "#000000"     # bevels: black shaded lines
ARROW = "#333333"           # the triangles on arrow buttons
TROUGH = "#DADADA"          # the groove of a slider
WINDOW = "#FFFFFF"          # the inside of fields, checkboxes and radio buttons
TEXT = "#333333"            # text on the faces and in fields
TAB = "#C8DDF2"             # the selected tab and the band around its page
TAB_BORDER = "#6382BF"      # the outline of the selected tab, and the line above a page
MENU_BAR = ("#FFFFFF", "#DEDEDE")       # the menu bar's gradient: its top and bottom rows
TOOL_STRIP = ("#FFFFFF", "#DCDCDC")     # the gradient behind the toolbar's buttons
BAR_LINE = "#CCCCCC"        # the line under the menu bar, and under the toolbar
TITLE = "#B8CFE5"           # the active title bar, and a scroll bar's thumb
SELECTION = "#B8CFE5"       # selected rows and text, with TEXT
MENU_SELECTION = "#A3B8CC"  # the highlighted menu item, and a list that has the focus
GRID = "#7A8A99"            # the lines between the cells of a table
NAVY = "#000080"            # the blocks of a percentage bar
ACCENT = "#00E5FF"          # the thin bright line on the selected tab and active title bar

# The rings of a bevel, from the outside in: (colour of the top and left
# sides, colour of the bottom and right sides), as Windows 98 draws them. Tk
# draws the bevels of the theme from the face colour: white and the face
# above, its dark shade and black below; these are for what ARES draws on a
# canvas (table headings, checkboxes).
RAISED = ((LIGHT, DARK_SHADOW), (HIGHLIGHT, SHADOW))
SOFT_RAISED = ((HIGHLIGHT, DARK_SHADOW), (LIGHT, SHADOW))
SUNKEN = ((SHADOW, HIGHLIGHT), (DARK_SHADOW, LIGHT))

# Sizes in design pixels; widgets.px() turns them into pixels of the display.
SCROLLBAR_WIDTH = 15        # thickness of a scroll bar; its arrow buttons are square
EDITOR_SCROLLBAR_WIDTH = 17     # the editor's scroll bars are a little thicker
BEVEL = 1                   # thickness of each ring of a bevel
GRADIENT_WIDTH = 32000      # pixels, not design pixels: wider than any desktop, within Tk's reach
SLIDER = (11, 19)           # the slider's thumb: along the channel, across it
CHANNEL = 5                 # thickness of the slider's channel
CHECKBOX_SIZE = 13          # a checkbox or radio button, square
CHECKBOX_ROOM = 16          # the row a checkbox on a canvas lies in, with its line
CHECK_GAP = 4               # between a checkbox or radio button and its text
FIELD_PADDING = (2, 1)      # between a field's border and its text: across, down
BUTTON_HEIGHT = 26          # a push button
BUTTON_SIDE = 17            # from a push button's edge to its text
TOOL_BUTTON = 34            # a toolbar button, square
CHECK_HEIGHT = 24           # a checkbox or radio button with its text
FIELD_HEIGHT = 20           # a field
COMBOBOX_HEIGHT = 25        # a list to choose from
COMBOBOX_ARROW = 20         # the arrow button of a list
TAB_HEIGHT = 19             # a tab
TAB_SIDE = 10               # from a tab's edge to its text
TAB_TOP = 2                 # above the tabs
TAB_LEFT = 2                # left of the first tab
GROUP_PADDING = 5           # inside a group box, at the sides and the bottom
# A page's distance from its notebook's edge, for the lines and the band of the selected
# tab's colour around it: left, top, right, bottom.
PAGE_BAND = (2, 4, 3, 3)

THEME = "ares98"
# The interface font of each windowing system, in order of preference, and its size in
# points: 12 pixels at 96 dots per inch. Controls, labels and menus use it in bold; table
# headings, fields and tooltips in its plain form.
FAMILIES = {"win32": ("Arial", "Microsoft Sans Serif", "Tahoma"),
            "aqua": ("Arial", "Helvetica", "Geneva"),
            "x11": ("Arial", "Liberation Sans", "Arimo", "Nimbus Sans", "FreeSans", "DejaVu Sans")}
FONT_SIZES = {"win32": 9, "aqua": 12}
FONT_SIZE = 9               # points, elsewhere
BOLD_FONTS = ("TkDefaultFont", "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont", "TkMenuFont")
PLAIN_FONTS = ("TkTextFont", "TkHeadingFont", "TkTooltipFont")
HEADING_FONT = "AresHeadingFont"    # the large heading of a tool's window
HEADING_SCALE = 1.5         # its size: 18 design pixels against 12
HEADING = "Heading.TLabel"      # the style of that heading
SUNKEN_FRAME = "Sunken.TFrame"  # a frame with a sunken border (see sunken())
STATUS_FRAME = "Status.TFrame"  # a frame with the thin sunken border of a status line

# The elements of the theme: each a built-in element of ttk, copied from the theme
# that has it (theme, element); Tk draws them all.
ELEMENTS = {
    "Ares.border": ("default", "border"),      # a bevel of rings of any width
    "Ares.default": ("classic", "highlight"),  # a solid ring around the widget: the default frame
    "Ares.field": ("default", "field"),        # a sunken white field
    "Ares.tab": ("default", "tab"),
    "Ares.page.client": ("alt", "trough"),     # the band around a page, in the tab's colour
    "Ares.uparrow": ("default", "uparrow"),    # a raised button with a triangle
    "Ares.downarrow": ("default", "downarrow"),
    "Ares.leftarrow": ("default", "leftarrow"),
    "Ares.rightarrow": ("default", "rightarrow"),
    "Ares.bar.thumb": ("alt", "trough"),       # a raised thumb in a colour of its own
    "Ares.bar.length": ("default", "padding"),     # inside it, unseen: makes it square at least
    "Ares.bar.trough": ("default", "fill"),    # where it slides, in the face colour
    "Ares.trough": ("alt", "trough"),          # its own ring width, and a groove for the slider
    "Ares.slider": ("default", "slider"),
    "Ares.separator": ("default", "separator"),
    "Ares.Checkbutton.indicator": ("clam", "Checkbutton.indicator"),  # sized for the display
    "Ares.Radiobutton.indicator": ("clam", "Radiobutton.indicator"),
}
# The check mark of a checkbox drawn on a canvas, 7 x 7 pixels from (3, 3): each
# column is three pixels long and starts at this row.
CHECK_MARK = (2, 3, 4, 3, 2, 1, 0)


def apply(widget):
    """Give the Tk root of widget the look of ARES.

    It is called before the root's widgets are made: the theme "ares98" is
    made current, Tk's named fonts get the interface font, and the option
    database gives Tk's own windows and widgets (every Toplevel, texts,
    entries and lists) the face colour, white entries and lists with dark
    text, and light blue selections. Calling it again for the same root
    changes nothing.
    """
    root = widget._root()
    style = ttk.Style(root)
    new = THEME not in style.theme_names()
    if new:
        _set_fonts(root)
        style.theme_create(THEME, parent="alt")
        style.theme_use(THEME)
        sizes = _sizes(root)
        for name, (theme, element) in ELEMENTS.items():
            style.element_create(name, "from", theme, element)
        _settings(style, root, sizes)
        _layouts(style)
    elif style.theme_use() != THEME:
        style.theme_use(THEME)
    _set_options(root)
    if new:
        _fit_controls(style, root)


def group(master, title, **options):
    """An etched group box with its title centred on its top line; what it holds is packed or
    gridded in it, inset by the group boxes' padding."""
    gap = px(master, GROUP_PADDING)
    options.setdefault("padding", (gap, 0, gap, gap))
    options.setdefault("labelanchor", "n")
    return ttk.Labelframe(master, text=title, **options)


def fit_button(root, name, image, width, height):
    """Give the buttons of style name, showing image, a size in pixels: the padding left once
    Tk's own parts are measured."""
    style = ttk.Style(root)
    style.configure(name, padding=0)
    button = ttk.Button(root, image=image, style=name)
    left, right = fit(width, button.winfo_reqwidth())
    above, below = fit(height, button.winfo_reqheight())
    button.destroy()
    style.configure(name, padding=(left, above, right, below))


def page_padding(widget):
    """The padding of a notebook's page: the band of the selected tab's colour inside its
    frame."""
    return tuple(px(widget, side) for side in PAGE_BAND)


def sunken(frame, thin=False):
    """Give a frame the sunken border of a field, and inset its contents by it.

    A Tk frame draws the border itself, around its contents. A ttk frame
    insets its contents by its padding only, not by its border: the padding
    is the border's width. The large frames of the window are Tk frames: a
    ttk widget draws itself into a picture of its whole size on every
    redraw, which takes a sunken page 25-50 ms at 4K and a Tk frame 1-3 ms.
    thin gives the one-ring border of a status line. Returns the frame.
    """
    width = (1 if thin else 2) * px(frame, BEVEL)
    if isinstance(frame, ttk.Widget):
        frame.configure(style=STATUS_FRAME if thin else SUNKEN_FRAME, padding=width)
    else:
        frame.configure(relief="sunken", borderwidth=width)
    return frame


def default_button(default, buttons, typed=()):
    """Draw the black frame of the default button on the push button that Return presses.

    For a dialog whose Return presses the push button that has the keyboard
    focus, else default: buttons are its push buttons, default among them.
    As Windows 98 draws it, the frame is on the button that has the focus,
    and on default while the focus is on another part of the dialog. typed
    are the dialog's fields where Return takes what was typed and presses no
    button: while one of them has the focus, no button has the frame. A
    button with the frame is in the state "alternate" (see the theme's
    Ares.default).
    """
    buttons, typed = tuple(buttons), tuple(typed)

    def frame(event=None):
        widget = event.widget if event is not None else None
        if any(widget is field for field in typed):
            framed = None
        elif any(widget is button for button in buttons):
            framed = widget
        else:
            framed = default
        for button in buttons:
            button.configure(default="active" if button is framed else "normal")
    # Each widget of the window has the window's bindings too: the FocusIn of any of
    # them comes here. When the window is activated, its own FocusIn comes before
    # that of the widget with the focus.
    default.winfo_toplevel().bind("<FocusIn>", frame, add="+")
    frame()


def bevel(x0, y0, x1, y1, ring, rings):
    """The pieces of a bevel along the edges of a box, in painting order.

    Returns [(colour, (x0, y0, x1, y1))]: each ring is ring pixels wide, the
    outer one first, and covers x0 <= x < x1, y0 <= y < y1 of its box. As
    Windows draws it, the bottom and right sides of a ring run to its
    corners, over the ends of the top and left ones.
    """
    pieces = []
    for k, (top_left, bottom_right) in enumerate(rings):
        left, top, right, bottom = x0 + k * ring, y0 + k * ring, x1 - k * ring, y1 - k * ring
        pieces += [(top_left, (left, top, right, top + ring)),
                   (top_left, (left, top, left + ring, bottom)),
                   (bottom_right, (left, bottom - ring, right, bottom)),
                   (bottom_right, (right - ring, top, right, bottom))]
    return pieces


def draw_bevel(canvas, x0, y0, x1, y1, rings=SOFT_RAISED, face=FACE, tags=()):
    """Draw a face with a bevel on a canvas, covering x0 <= x < x1, y0 <= y < y1.

    The default is a raised heading cell. Returns the ids of the items made.
    """
    ring = px(canvas, BEVEL)
    items = [canvas.create_rectangle(x0, y0, x1, y1, fill=face, width=0, tags=tags)]
    for colour, box in bevel(x0, y0, x1, y1, ring, rings):
        items.append(canvas.create_rectangle(*box, fill=colour, width=0, tags=tags))
    return items


def gradient(top, bottom, rows):
    """The colours "#RRGGBB" of rows rows, in a straight line from top to bottom: the first
    row is exactly top, the last exactly bottom, and each colour is rounded to the nearest."""
    if rows < 2:
        return [top][:rows]
    ends = [(int(top[i:i + 2], 16), int(bottom[i:i + 2], 16)) for i in (1, 3, 5)]
    last = rows - 1
    return ["#" + "".join(f"{((first * (last - k) + second * k) * 2 + last) // (2 * last):02X}"
                          for first, second in ends) for k in range(rows)]


def draw_gradient(canvas, ends, height):
    """Draw a gradient on a canvas from its top down, height pixels, between ends, its top and
    bottom colours: one rectangle for each row of pixels, wide enough for any window, so that
    resizing the window draws nothing new. Returns the ids of the items made."""
    return [canvas.create_rectangle(0, y, GRADIENT_WIDTH, y + 1, fill=colour, width=0)
            for y, colour in enumerate(gradient(*ends, height))]


def check_mark(x0, y0, pixel):
    """The outline of the check mark from (x0, y0) as polygon points, each pixel pixel x pixel:
    along the tops of its columns, then back along their bottoms."""
    top = [point for k, start in enumerate(CHECK_MARK) for point in ((k, start), (k + 1, start))]
    bottom = [point for k, start in reversed(list(enumerate(CHECK_MARK)))
              for point in ((k + 1, start + 3), (k, start + 3))]
    return [value for x, y in top + bottom for value in (x0 + x * pixel, y0 + y * pixel)]


def _checkbox_pixel(widget):
    """Screen pixels per pixel of a checkbox drawn on a canvas: whole ones, that fit its row."""
    room = px(widget, CHECKBOX_ROOM) - px(widget, BEVEL)
    return max(1, min(round(scale(widget)), room // CHECKBOX_SIZE))


def checkbox_size(widget):
    """Pixels of the side of a checkbox drawn on a canvas: its pixels enlarged by whole ones."""
    return CHECKBOX_SIZE * _checkbox_pixel(widget)


def draw_checkbox(canvas, tags=()):
    """Make the items of a classic checkbox on a canvas, hidden.

    place_checkbox() puts them in place and show_checkbox() shows them.
    Returns their ids: the inside, the eight pieces of its sunken bevel and
    the check mark.
    """
    items = [canvas.create_rectangle(0, 0, 0, 0, width=0, state="hidden", tags=tags)]
    for colour, _ in bevel(0, 0, 1, 1, 1, SUNKEN):
        items.append(canvas.create_rectangle(0, 0, 0, 0, fill=colour, width=0, state="hidden",
                                             tags=tags))
    items.append(canvas.create_polygon(0, 0, 0, 0, 0, 0, width=0, state="hidden", tags=tags))
    return items


def place_checkbox(canvas, items, x0, y0):
    """Put a checkbox made by draw_checkbox() with its top left corner at (x0, y0)."""
    pixel = _checkbox_pixel(canvas)
    size = CHECKBOX_SIZE * pixel
    canvas.coords(items[0], x0, y0, x0 + size, y0 + size)
    for item, (_, box) in zip(items[1:9], bevel(x0, y0, x0 + size, y0 + size, pixel, SUNKEN)):
        canvas.coords(item, *box)
    canvas.coords(items[9], *check_mark(x0 + 3 * pixel, y0 + 3 * pixel, pixel))


def show_checkbox(canvas, items, value):
    """Show a checkbox made by draw_checkbox(): value is (checked, enabled), or None to hide it.

    Enabled, it is white with a black check mark; disabled, gray with a gray one.
    """
    if value is None:
        for item in items:
            canvas.itemconfigure(item, state="hidden")
        return
    checked, enabled = value
    canvas.itemconfigure(items[0], fill=WINDOW if enabled else FACE, state="normal")
    for item in items[1:9]:
        canvas.itemconfigure(item, state="normal")
    canvas.itemconfigure(items[9], fill=DARK_SHADOW if enabled else SHADOW,
                         state="normal" if checked else "hidden")


# Fonts and the option database ------------------------------------------------

def classic_font(root):
    """(family, size in points) of the interface font for root, or None when the windowing
    system has none of its families installed."""
    system = str(root.tk.call("tk", "windowingsystem"))
    installed = set(tkfont.families(root))
    family = next((name for name in FAMILIES.get(system, ()) if name in installed), None)
    return None if family is None else (family, FONT_SIZES.get(system, FONT_SIZE))


def _set_fonts(root):
    """Give Tk's named fonts the interface font, bold or plain, and make the heading font.

    Where the interface family is not installed, the fonts keep their family.
    """
    classic = classic_font(root)
    for names, weight in ((BOLD_FONTS, "bold"), (PLAIN_FONTS, "normal")):
        for name in names:
            font = tkfont.nametofont(name, root=root)
            if classic is not None:
                family, size = classic
                font.configure(family=family, size=size)
            font.configure(weight=weight)
    default = tkfont.nametofont("TkDefaultFont", root=root).actual()
    # Made with Tk's own command: a tkinter Font would delete it once Python forgot it.
    command = "configure" if HEADING_FONT in root.tk.splitlist(root.tk.call("font", "names")) \
        else "create"
    root.tk.call("font", command, HEADING_FONT, "-family", default["family"],
                 "-size", round(default["size"] * HEADING_SCALE), "-weight", "bold")


def _set_options(root):
    """Give Tk's own windows and widgets the face colour, white fields and blue selections.

    Entries and lists are white with dark text whatever the system's colours
    are, which differ in high-contrast and dark schemes.
    """
    root.configure(background=FACE)
    for pattern, value in (
            ("*Toplevel.background", FACE),
            ("*Frame.background", FACE),
            ("*Label.background", FACE),
            ("*Text.selectBackground", SELECTION),
            ("*Text.selectForeground", TEXT),
            ("*Text.inactiveSelectBackground", SELECTION),
            ("*Entry.background", WINDOW),           # the field of a register's value
            ("*Entry.foreground", TEXT),
            ("*Entry.insertBackground", TEXT),
            ("*Entry.selectBackground", SELECTION),
            ("*Entry.selectForeground", TEXT),
            ("*Listbox.background", WINDOW),         # the lists of comboboxes, among others
            ("*Listbox.foreground", TEXT),
            ("*Listbox.selectBackground", MENU_SELECTION),
            ("*Listbox.selectForeground", TEXT),
            ("*TCombobox*Listbox.font", "TkDefaultFont"),
            ("*TCombobox.font", "TkDefaultFont")):
        root.option_add(pattern, value)


# The theme ------------------------------------------------------------------------

def _sizes(root):
    """Sizes in pixels of the display that the theme's parts share.

    ring: a ring of a bevel; padding: around the text of an entry or spinbox;
    button: the width of a scroll bar, and the size of its arrow buttons;
    gap: after a checkbox or radio button.
    """
    across, down = (px(root, size) for size in FIELD_PADDING)
    return {"ring": px(root, BEVEL), "padding": (across, down),
            "button": px(root, SCROLLBAR_WIDTH), "gap": px(root, CHECK_GAP)}


def fit(total, used):
    """(before, after): the room left of total once used is taken, in two halves."""
    room = max(0, total - used)
    return room // 2, room - room // 2


def bar_padding(thickness, border):
    """The padding inside a scroll bar's thumb, of border pixels' bevel, that makes the thumb
    at least thickness pixels long and wide."""
    before, after = fit(thickness, 2 * border)
    return before, before, after, after


def _settings(style, root, sizes):
    """Configure and map the styles of the theme: colours, rings, fonts, padding, states."""
    ring, button = sizes["ring"], sizes["button"]
    two = 2 * ring
    one = px(root, 1)
    bold = tkfont.nametofont("TkDefaultFont", root=root).metrics("linespace")
    # Tk's arrow buttons come out an odd number of pixels: a thumb at least as long as the
    # bar is thick makes the bar exactly SCROLLBAR_WIDTH design pixels (bar_padding()).
    style.configure(".", background=FACE, foreground=TEXT, troughcolor=TROUGH,
                    bordercolor=DARK_SHADOW, fieldbackground=WINDOW, selectbackground=SELECTION,
                    selectforeground=TEXT, insertcolor=TEXT, font="TkDefaultFont",
                    borderwidth=two, arrowcolor=ARROW, arrowsize=button - 1,
                    highlightcolor=FACE, highlightthickness=ring)
    # Disabled text is gray and etched: drawn in white one pixel lower right first.
    style.map(".", foreground=[("disabled", SHADOW)], embossed=[("disabled", 1)])
    # Raised buttons press in; the text of a pressed button moves one ring right and down.
    # The default button has a black frame around its bevel (default_button()).
    style.configure("TButton", anchor="center", width=0, relief="raised", shiftrelief=ring)
    style.map("TButton", relief=[("pressed !disabled", "sunken")],
              highlightcolor=[("alternate", DARK_SHADOW)])
    style.configure("Toolbutton", anchor="center", padding=one, relief="raised",
                    shiftrelief=ring)
    style.map("Toolbutton", relief=[("pressed !disabled", "sunken")])
    # Checkboxes and radio buttons: white squares and circles, gray while pressed or
    # disabled, sized for the display.
    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(name, indicatorsize=px(root, CHECKBOX_SIZE),
                        indicatormargin=(0, 0, sizes["gap"], 0), indicatorbackground=WINDOW,
                        indicatorforeground=TEXT, upperbordercolor=SHADOW,
                        lowerbordercolor=HIGHLIGHT)
        style.map(name, indicatorbackground=[("disabled", FACE), ("pressed", FACE)],
                  indicatorforeground=[("disabled", SHADOW)])
    # As in Windows 98 a field shows its selection only while it has the keyboard
    # focus: without it, the selection has the colours of the rest of the field.
    for name in ("TEntry", "TSpinbox"):
        style.map(name, selectbackground=[("readonly !focus", FACE), ("!focus", WINDOW)],
                  selectforeground=[("!focus", TEXT)],
                  fieldbackground=[("disabled", FACE), ("readonly", FACE)])
    # A read-only combobox (a list to choose from) shows the focus: blue inside a dotted
    # ring. Elsewhere the dots have the field's colour.
    style.configure("TCombobox", focuscolor=WINDOW, focusthickness=ring,
                    arrowsize=px(root, COMBOBOX_ARROW) - 1, relief="raised")
    style.map("TCombobox", foreground=[("disabled", SHADOW)],
              fieldbackground=[("disabled", FACE), ("readonly focus", MENU_SELECTION)],
              selectbackground=[("!focus", WINDOW)], selectforeground=[("!focus", TEXT)],
              focuscolor=[("disabled", FACE)])
    # Scroll bars: raised arrow buttons and a raised blue thumb on the face colour; while
    # everything fits (Tk disables the bar) the arrows are gray. The thumb is a trough
    # element, so that its colour is its own: arrows and thumbs share one background.
    style.configure("TScrollbar", relief="raised", troughcolor=TITLE, troughrelief="raised",
                    troughborderwidth=two, groovewidth=-1, width=button,
                    padding=bar_padding(button, two))
    style.map("TScrollbar", relief=[("pressed", "sunken")], arrowcolor=[("disabled", SHADOW)],
              troughrelief=[("pressed", "sunken")])
    wide = px(root, EDITOR_SCROLLBAR_WIDTH)
    for orient in ("Vertical", "Horizontal"):
        style.configure(f"Editor.{orient}.TScrollbar", width=wide, arrowsize=wide - 1,
                        padding=bar_padding(wide, two))
    style.map("TCombobox", arrowcolor=[("disabled", SHADOW)])
    style.map("TSpinbox", arrowcolor=[("disabled", SHADOW)])
    # The slider: a raised thumb on a sunken channel, inside the dotted focus ring.
    style.configure("TScale", focusthickness=ring, troughcolor=TITLE, troughrelief="sunken",
                    troughborderwidth=ring, groovewidth=px(root, CHANNEL),
                    sliderlength=px(root, SLIDER[0]), sliderthickness=px(root, SLIDER[1]),
                    sliderrelief="raised")
    # A notebook: a flat band in the selected tab's colour around its page. Its tabs are
    # hidden under the strip of ares.gui.tabs, which also draws the lines: here they only
    # reserve the row.
    style.configure("TNotebook", tabmargins=(px(root, TAB_LEFT), px(root, TAB_TOP), 0, 0),
                    troughcolor=TAB, troughrelief="flat", troughborderwidth=0, groovewidth=-1)
    above, below = fit(px(root, TAB_HEIGHT), 2 * ring + 2 + bold)
    style.configure("TNotebook.Tab", padding=(px(root, TAB_SIDE) - ring, above,
                                              px(root, TAB_SIDE) - ring, below))
    style.map("TNotebook.Tab", background=[("selected", TAB)])
    style.configure("TLabel", borderwidth=0)
    style.configure("TLabelframe", relief="groove",
                    labelmargins=(px(root, 6), 0, px(root, 6), px(root, 2)))
    style.configure(SUNKEN_FRAME, relief="sunken")
    style.configure(STATUS_FRAME, relief="sunken", borderwidth=ring)
    style.configure("TSeparator", background=FACE)
    style.configure(HEADING, font=HEADING_FONT, anchor="center")
    style.configure("Treeview", background=WINDOW, fieldbackground=WINDOW, foreground=TEXT)
    style.map("Treeview", background=[("selected", SELECTION)],
              foreground=[("selected", TEXT)])
    style.configure("Heading", background=FACE, font="TkHeadingFont", relief="raised")
    style.configure("ComboboxPopdownFrame", relief="solid", borderwidth=1)
    style.configure("TMenubutton", width=-11, padding=(px(root, 3), px(root, 3)),
                    relief="raised")
    style.configure("TProgressbar", background=NAVY)


def _fit_controls(style, root):
    """Give the controls their sizes: the padding left once Tk's own parts are measured.

    What a control takes without padding (its rings, focus ring, the font's
    line) depends on the display and the font; the rest is padding.
    """
    ring = px(root, BEVEL)

    def bare(kind, name, **options):
        style.configure(name, padding=0)
        widget = kind(root, **options)
        size = widget.winfo_reqwidth(), widget.winfo_reqheight()
        widget.destroy()
        return size
    width, height = bare(ttk.Button, "TButton", text="")
    left, right = fit(2 * px(root, BUTTON_SIDE), width)
    above, below = fit(px(root, BUTTON_HEIGHT), height)
    style.configure("TButton", padding=(left, above, right, below))
    for name, kind in (("TCheckbutton", ttk.Checkbutton), ("TRadiobutton", ttk.Radiobutton)):
        above, below = fit(px(root, CHECK_HEIGHT), bare(kind, name, text="x")[1])
        style.configure(name, padding=(px(root, CHECK_GAP), above, px(root, CHECK_GAP), below))
    across = px(root, FIELD_PADDING[0])
    height = bare(ttk.Entry, "TEntry")[1]
    above, below = fit(px(root, FIELD_HEIGHT), height)
    for name in ("TEntry", "TSpinbox"):
        style.configure(name, padding=(across, above, across, below))
    # The arrow button must leave a list its height.
    arrow = px(root, COMBOBOX_ARROW) - 1
    height = bare(ttk.Combobox, "TCombobox")[1]
    while height > px(root, COMBOBOX_HEIGHT) and arrow > 1:
        arrow -= 2
        style.configure("TCombobox", arrowsize=arrow)
        height = bare(ttk.Combobox, "TCombobox")[1]
    above, below = fit(px(root, COMBOBOX_HEIGHT), height)
    style.configure("TCombobox", padding=(ring, above, ring, below))


def _node(name, children=(), **options):
    if children:
        options["children"] = list(children)
    return (name, options)


def _layouts(style):
    """The layouts of the theme's widgets, made of its elements."""
    node = _node
    style.layout("TButton", [node("Ares.default", [node("Ares.border", [
        node("Button.focus", [node("Button.padding", [
            node("Button.label", sticky="nswe")], sticky="nswe")], sticky="nswe")],
        sticky="nswe")], sticky="nswe")])
    style.layout("Toolbutton", [node("Ares.border", [
        node("Toolbutton.padding", [node("Toolbutton.label", sticky="nswe")], sticky="nswe")],
        sticky="nswe")])
    style.layout("TNotebook", [node("Ares.page.client", sticky="nswe")])
    style.layout("TNotebook.Tab", [node("Ares.tab", [
        node("Notebook.padding", [node("Notebook.focus", [
            node("Notebook.label", side="top", sticky="")], side="top", sticky="nswe")],
            side="top", sticky="nswe")], sticky="nswe")])
    style.layout("TEntry", [node("Ares.field", [
        node("Entry.padding", [node("Entry.textarea", sticky="nswe")], sticky="nswe")],
        sticky="nswe", border=1)])
    style.layout("TCombobox", [node("Ares.field", [
        node("Ares.downarrow", side="right", sticky=""),
        node("Combobox.padding", [node("Combobox.focus", [
            node("Combobox.textarea", sticky="nswe")], sticky="nswe")], sticky="nswe")],
        sticky="nswe")])
    style.layout("TSpinbox", [node("Ares.field", [
        node("null", [node("Ares.uparrow", side="top", sticky="e"),
                      node("Ares.downarrow", side="bottom", sticky="e")],
             side="right", sticky=""),
        node("Spinbox.padding", [node("Spinbox.textarea", sticky="nswe")], sticky="nswe")],
        side="top", sticky="we")])
    for kind in ("Checkbutton", "Radiobutton"):
        style.layout(f"T{kind}", [node(f"{kind}.padding", [
            node(f"Ares.{kind}.indicator", side="left", sticky=""),
            node(f"{kind}.focus", [node(f"{kind}.label", sticky="nswe")], side="left",
                 sticky="w")], sticky="nswe")])
    for orient, (first, last) in (("Vertical", ("uparrow", "downarrow")),
                                  ("Horizontal", ("leftarrow", "rightarrow"))):
        vertical = orient == "Vertical"
        start, end = ("top", "bottom") if vertical else ("left", "right")
        style.layout(f"{orient}.TScrollbar", [node("Ares.bar.trough", [
            node(f"Ares.{first}", side=start, sticky=""),
            node(f"Ares.{last}", side=end, sticky=""),
            # One unit: Tk starts a drag only where identify names the thumb.
            node("Ares.bar.thumb", [node("Ares.bar.length", sticky="nswe")], sticky="nswe",
                 unit=1)],
            sticky="ns" if vertical else "we")])
        style.layout(f"{orient}.TScale", [node(f"{orient}.Scale.focus", [
            node("Ares.trough", [node("Ares.slider", side="top" if vertical else "left",
                                      sticky="")], sticky="nswe")], sticky="nswe")])
        style.layout(f"{orient}.TSeparator", [node("Ares.separator", sticky="nswe")])
    style.layout("TLabelframe", [node("Ares.border", sticky="nswe")])
    for name in (SUNKEN_FRAME, STATUS_FRAME):
        style.layout(name, [node("Ares.border", sticky="nswe")])
