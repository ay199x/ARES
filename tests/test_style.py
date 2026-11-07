# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The look of ARES: the ares98 theme of every Tk root, made of parts Tk draws itself."""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

import pytest
from conftest import new_root

from ares.gui import style, widgets
from ares.gui.app import App
from ares.gui.widgets import px

SCALES = (1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 3.0)    # display scales; 1.0 is 100 % (96 dpi)
ARROWS = {"Vertical": ("uparrow", "downarrow"), "Horizontal": ("leftarrow", "rightarrow")}
# What ARES draws on canvases is compared as text, one letter for each colour of the look.
LETTERS = {style.FACE: ".", style.HIGHLIGHT: "H", style.LIGHT: "L", style.SHADOW: "S",
           style.DARK_SHADOW: "#", style.TITLE: "T", style.NAVY: "N"}
SOFT_RAISED = (("H", "#"), ("L", "S"))      # the rings of a raised heading, as letters


def bevelled(width, height, ring, rings, inside="."):
    """A picture: the rings of a bevel, each ring pixels wide, around the inside's letter.

    rings are (top and left, bottom and right) letters, outside in. As
    Windows draws them, the bottom and right sides of each ring run to its
    corners, over the ends of the top and left ones.
    """
    rows = [[inside] * width for _ in range(height)]

    def paint(letter, x0, y0, x1, y1):
        for y in range(y0, y1):
            rows[y][x0:x1] = [letter] * (x1 - x0)
    for k, (top_left, bottom_right) in enumerate(rings):
        left, top, right, bottom = k * ring, k * ring, width - k * ring, height - k * ring
        paint(top_left, left, top, right, top + ring)
        paint(top_left, left, top, left + ring, bottom)
        paint(bottom_right, left, bottom - ring, right, bottom)
        paint(bottom_right, right - ring, top, right, bottom)
    return ["".join(row) for row in rows]


@pytest.fixture
def make_root(tk_root, monkeypatch):
    """make_root(scale): a new hidden Tk root shown at that display scale.

    Tk keeps the scale per display, which all the roots of the test run
    may share: it is put back at the end of the test. On macOS px() does not
    scale (Tk works in points there); here it follows the emulated scale too.
    """
    monkeypatch.setattr(widgets, "is_aqua", lambda widget: False)
    original = tk_root.tk.call("tk", "scaling")
    roots = []

    def make(scale=1.0):
        root = new_root()
        roots.append(root)
        root.tk.call("tk", "scaling", scale * 96 / 72)
        return root
    yield make
    for root in roots:
        try:
            root.destroy()
        except tk.TclError:
            pass                        # already closed by the test
    tk_root.tk.call("tk", "scaling", original)


def lookup(root, name, option, state=()):
    """The value the current theme gives an option of a style in a state, as text.

    A list is its words joined by spaces ("4 4 4 0"); "" when the theme gives none.
    """
    value = root.tk.call("ttk::style", "lookup", name, f"-{option}", list(state))
    words = value if isinstance(value, tuple) else root.tk.splitlist(str(value))
    return " ".join(str(word) for word in words)


def scroll_bars(root):
    """{path: orient} of every ttk scroll bar of root, those made by Tk's own scripts too."""
    found = {}
    paths = ["."]
    while paths:
        path = paths.pop()
        if root.tk.call("winfo", "class", path) == "TScrollbar":
            found[path] = str(root.tk.call(path, "cget", "-orient"))
        paths.extend(root.tk.splitlist(root.tk.call("winfo", "children", path)))
    return found


def requested(root, path):
    return tuple(int(root.tk.call("winfo", f"req{side}", path)) for side in ("width", "height"))


def node(name, *children, **options):
    """A layout node as ttk gives it back: options with their own order, children last."""
    if children:
        options["children"] = list(children)
    return (name, options)


# Tk cannot be asked how an element was made, so the root's ttk::style command is
# wrapped to note the type of each element made on its way to Tk.
NOTE_ELEMENTS = r"""
    rename ::ttk::style ::ttk::style_unnoted
    set ::made_elements {}
    proc ::ttk::style {args} {
        if {[lrange $args 0 1] eq {element create}} {
            lappend ::made_elements [lindex $args 2] [lindex $args 3]
        }
        tailcall ::ttk::style_unnoted {*}$args
    }
"""


def made_elements(root):
    """{name: type} of the elements made since NOTE_ELEMENTS was run in root."""
    words = root.tk.splitlist(root.tk.eval("set ::made_elements"))
    return {str(name): str(kind) for name, kind in zip(words[::2], words[1::2])}


# The theme and its elements -------------------------------------------------------

def test_the_theme_has_no_image_elements_and_draws_no_pictures(make_root, tmp_path):
    """Tk draws every part of the look: a picture element draws its picture tile by tile,
    with new drawing objects for each tile, which makes a page of the window take seconds at
    4K. Only icons are pictures."""
    root = make_root(2.25)
    root.tk.eval(NOTE_ELEMENTS)
    before = set(root.tk.splitlist(root.tk.call("image", "names")))
    style.apply(root)
    assert set(root.tk.splitlist(root.tk.call("image", "names"))) == before
    app = App(root, settings_path=tmp_path / "settings.json")      # its own elements too
    try:
        made = made_elements(root)
        assert made and not [name for name, kind in made.items() if kind == "image"], made
        assert set(made.values()) == {"from"}
    finally:
        app.close()


def test_the_elements_are_copies_of_tk_s_own(make_root):
    root = make_root()
    s = ttk.Style(root)
    style.apply(root)
    assert set(s.element_names()) == set(style.ELEMENTS)
    for name, (theme, element) in style.ELEMENTS.items():
        options = s.element_options(name)
        s.theme_use(theme)
        assert options == s.element_options(element), name
        s.theme_use(style.THEME)


def test_the_ares98_theme_is_made_from_alt_once_for_each_root(make_root):
    root = make_root()
    s = ttk.Style(root)
    assert s.theme_use() != style.THEME
    style.apply(root)
    assert s.theme_use() == style.THEME
    assert list(s.theme_names()).count(style.THEME) == 1
    assert s.layout("TMenubutton")[0][0] == "Menubutton.border"     # from alt
    s.theme_use("alt")                              # another window chose another theme
    style.apply(root)
    assert s.theme_use() == style.THEME and list(s.theme_names()).count(style.THEME) == 1


def test_applying_again_changes_nothing(make_root):
    root = make_root()
    style.apply(root)
    s = ttk.Style(root)
    layouts = {name: s.layout(name) for name in ("TButton", "Vertical.TScrollbar")}
    settings = s.configure(".")
    style.apply(root)
    assert {name: s.layout(name) for name in layouts} == layouts
    assert s.configure(".") == settings


def test_a_second_root_gets_the_same_look(make_root):
    first, second = make_root(), make_root()
    style.apply(first)
    style.apply(second)
    for name in ("TButton", "Toolbutton", "TEntry", "Vertical.TScrollbar", "TNotebook.Tab"):
        assert ttk.Style(second).layout(name) == ttk.Style(first).layout(name), name
    assert ttk.Style(second).configure(".") == ttk.Style(first).configure(".")


def test_the_layouts_are_made_of_the_theme_s_parts(make_root):
    root = make_root()
    style.apply(root)
    s = ttk.Style(root)
    expected = {
        "TButton": [node("Ares.default", node("Ares.border", node("Button.focus", node(
            "Button.padding", node("Button.label", sticky="nswe"), sticky="nswe"),
            sticky="nswe"), sticky="nswe"), sticky="nswe")],
        "Toolbutton": [node("Ares.border", node("Toolbutton.padding", node(
            "Toolbutton.label", sticky="nswe"), sticky="nswe"), sticky="nswe")],
        "TNotebook": [node("Ares.page.client", sticky="nswe")],
        "TEntry": [node("Ares.field", node("Entry.padding", node(
            "Entry.textarea", sticky="nswe"), sticky="nswe"), sticky="nswe", border="1")],
        "Vertical.TScrollbar": [node("Ares.bar.trough",
                                     node("Ares.uparrow", side="top", sticky=""),
                                     node("Ares.downarrow", side="bottom", sticky=""),
                                     node("Ares.bar.thumb", node("Ares.bar.length", sticky="nswe"),
                                          sticky="nswe", unit="1"), sticky="ns")],
        "Horizontal.TScrollbar": [node("Ares.bar.trough",
                                       node("Ares.leftarrow", side="left", sticky=""),
                                       node("Ares.rightarrow", side="right", sticky=""),
                                       node("Ares.bar.thumb", node("Ares.bar.length", sticky="nswe"),
                                            sticky="nswe", unit="1"), sticky="we")],
        "Horizontal.TScale": [node("Horizontal.Scale.focus", node("Ares.trough", node(
            "Ares.slider", side="left", sticky=""), sticky="nswe"), sticky="nswe")],
        "Horizontal.TSeparator": [node("Ares.separator", sticky="nswe")],
        "TLabelframe": [node("Ares.border", sticky="nswe")],
        style.SUNKEN_FRAME: [node("Ares.border", sticky="nswe")],
        style.STATUS_FRAME: [node("Ares.border", sticky="nswe")],
    }
    for name, layout in expected.items():
        assert s.layout(name) == layout, name
    tab = s.layout("TNotebook.Tab")[0]
    assert tab[0] == "Ares.tab"
    for kind in ("Checkbutton", "Radiobutton"):
        parts = str(s.layout(f"T{kind}"))
        assert f"Ares.{kind}.indicator" in parts
    for name in ("TCombobox", "TSpinbox"):
        assert s.layout(name)[0][0] == "Ares.field", name
    assert "Ares.downarrow" in str(s.layout("TCombobox"))
    assert "Ares.uparrow" in str(s.layout("TSpinbox"))


# Widths, colours and states -----------------------------------------------------------

@pytest.mark.parametrize("scale", SCALES)
def test_the_rings_and_sizes_follow_the_display(make_root, scale):
    """Each ring of a bevel is one design pixel; Tk draws the bevels two rings wide."""
    root = make_root(scale)
    style.apply(root)
    ring = px(root, style.BEVEL)
    assert lookup(root, ".", "borderwidth") == str(2 * ring)
    assert lookup(root, style.STATUS_FRAME, "borderwidth") == str(ring)
    assert lookup(root, "TButton", "highlightthickness") == str(ring)   # the default frame
    assert lookup(root, "TScale", "troughborderwidth") == str(ring)
    assert lookup(root, "TScale", "groovewidth") == str(px(root, style.CHANNEL))
    assert (lookup(root, "TScale", "sliderlength"), lookup(root, "TScale", "sliderthickness")) \
        == (str(px(root, style.SLIDER[0])), str(px(root, style.SLIDER[1])))
    for name in ("TCheckbutton", "TRadiobutton"):
        assert lookup(root, name, "indicatorsize") == str(px(root, style.CHECKBOX_SIZE)), name
    assert lookup(root, "TNotebook", "tabmargins") == \
        f"{px(root, style.TAB_LEFT)} {px(root, style.TAB_TOP)} 0 0"


@pytest.mark.parametrize("scale", SCALES)
def test_a_scroll_bar_is_15_pixels_thick_and_17_in_the_editor_scaled_with_the_display(make_root,
                                                                                      scale):
    root = make_root(scale)
    style.apply(root)
    side = px(root, style.SCROLLBAR_WIDTH)
    vertical, horizontal = (ttk.Scrollbar(root, orient=o) for o in ("vertical", "horizontal"))
    assert vertical.winfo_reqwidth() == horizontal.winfo_reqheight() == side
    side = px(root, style.EDITOR_SCROLLBAR_WIDTH)
    vertical = ttk.Scrollbar(root, orient="vertical", style="Editor.Vertical.TScrollbar")
    horizontal = ttk.Scrollbar(root, orient="horizontal", style="Editor.Horizontal.TScrollbar")
    assert vertical.winfo_reqwidth() == horizontal.winfo_reqheight() == side


def test_raised_parts_press_in_and_sunken_parts_stay_sunken(make_root):
    root = make_root()
    style.apply(root)
    for name in ("TButton", "Toolbutton", "TScrollbar"):
        assert lookup(root, name, "relief") == "raised", name
        assert lookup(root, name, "relief", ("pressed",)) == "sunken", name
    assert lookup(root, "TButton", "relief", ("pressed", "disabled")) == "raised"
    assert lookup(root, "Heading", "relief") == "raised"
    for name in (style.SUNKEN_FRAME, style.STATUS_FRAME):
        assert lookup(root, name, "relief") == "sunken", name
    assert lookup(root, "TScale", "troughrelief") == "sunken"
    assert lookup(root, "TScale", "sliderrelief") == "raised"
    assert lookup(root, "TLabelframe", "relief") == "groove"
    assert lookup(root, "TScrollbar", "troughrelief") == "raised"       # the thumb
    assert lookup(root, "TScrollbar", "troughrelief", ("pressed",)) == "sunken"


def test_the_default_button_has_a_black_frame(make_root):
    """Tk draws a ring around a push button: black on the default one, else the face colour."""
    root = make_root(2.25)
    style.apply(root)
    assert lookup(root, "TButton", "highlightcolor") == style.FACE
    assert lookup(root, "TButton", "highlightcolor", ("alternate",)) == style.DARK_SHADOW
    assert "alternate" in ttk.Button(root, default="active").state()
    assert "alternate" not in ttk.Button(root).state()


def test_colours_of_the_theme(make_root):
    root = make_root()
    style.apply(root)
    assert (lookup(root, ".", "background"), lookup(root, ".", "foreground"),
            lookup(root, ".", "fieldbackground"), lookup(root, ".", "troughcolor")) == (
        style.FACE, style.TEXT, style.WINDOW, style.TROUGH)
    assert lookup(root, ".", "foreground", ("disabled",)) == style.SHADOW
    assert lookup(root, ".", "embossed", ("disabled",)) == "1"
    assert lookup(root, "TScale", "troughcolor") == style.TITLE
    assert lookup(root, "TScrollbar", "troughcolor") == style.TITLE     # the thumb
    assert lookup(root, "TNotebook", "troughcolor") == style.TAB        # a page's frame
    # Arrows are dark, gray while their scroll bar, list or spinbox is disabled.
    for name in ("TScrollbar", "TCombobox", "TSpinbox"):
        assert lookup(root, name, "arrowcolor") == style.ARROW, name
        assert lookup(root, name, "arrowcolor", ("disabled",)) == style.SHADOW, name


def test_fields_are_white_and_gray_while_disabled_or_read_only(make_root):
    root = make_root()
    style.apply(root)
    for name in ("TEntry", "TSpinbox"):
        assert lookup(root, name, "fieldbackground") == style.WINDOW, name
        for state in (("disabled",), ("readonly",)):
            assert lookup(root, name, "fieldbackground", state) == style.FACE, (name, state)
    # A read-only combobox is a list to choose from: white; blue while it has the focus,
    # inside a dotted ring.
    assert lookup(root, "TCombobox", "fieldbackground", ("readonly",)) == style.WINDOW
    assert lookup(root, "TCombobox", "fieldbackground", ("readonly", "focus")) \
        == style.MENU_SELECTION
    assert lookup(root, "TCombobox", "foreground", ("readonly", "focus")) == style.TEXT
    assert lookup(root, "TCombobox", "fieldbackground", ("disabled",)) == style.FACE
    assert lookup(root, "TCombobox", "focusthickness") == str(px(root, 1))


def test_checkboxes_and_radio_buttons_in_every_state(make_root):
    root = make_root(2.25)
    style.apply(root)
    for name in ("TCheckbutton", "TRadiobutton"):
        assert lookup(root, name, "indicatorbackground") == style.WINDOW
        for state in (("pressed",), ("disabled",), ("disabled", "selected")):
            assert lookup(root, name, "indicatorbackground", state) == style.FACE, state
        assert lookup(root, name, "indicatorforeground") == style.TEXT
        assert lookup(root, name, "indicatorforeground", ("disabled",)) == style.SHADOW
        assert (lookup(root, name, "upperbordercolor"),
                lookup(root, name, "lowerbordercolor")) == (style.SHADOW, style.HIGHLIGHT)
        # The gap before the text.
        assert lookup(root, name, "indicatormargin") == f"0 0 {px(root, style.CHECK_GAP)} 0"
    check = ttk.Checkbutton(root, text="Option")
    assert check.winfo_reqwidth() >= px(root, style.CHECKBOX_SIZE + style.CHECK_GAP)


def test_a_field_shows_its_selection_only_while_it_has_the_focus(make_root):
    """As in Windows 98: without the focus, the selection has the colours of the rest of the field.

    The Find dialog's two fields both keep their selection, and a place
    chosen in the Data Segment stays selected in its list.
    """
    root = make_root()
    style.apply(root)

    def selection(name, *state):
        return (lookup(root, name, "selectbackground", state),
                lookup(root, name, "selectforeground", state))
    blue, plain = (style.SELECTION, style.TEXT), (style.WINDOW, style.TEXT)
    for name in ("TEntry", "TCombobox", "TSpinbox"):
        assert selection(name, "focus") == selection(name, "focus", "readonly") == blue, name
        assert selection(name) == selection(name, "!focus") == plain, name
    # A read-only entry or spinbox is gray inside; a read-only combobox is a white list.
    for name in ("TEntry", "TSpinbox"):
        assert selection(name, "readonly") == (style.FACE, style.TEXT), name
    assert selection("TCombobox", "readonly") == plain


def test_tabs_and_their_pages(make_root):
    root = make_root(2.25)
    style.apply(root)
    # A page lies on a flat band of the tab colour, its lines drawn by ares.gui.tabs.
    assert lookup(root, "TNotebook.Tab", "background", ("selected",)) == style.TAB
    assert lookup(root, "TNotebook", "background") == style.FACE
    assert (lookup(root, "TNotebook", "troughcolor"), lookup(root, "TNotebook", "troughrelief"),
            lookup(root, "TNotebook", "troughborderwidth")) == (style.TAB, "flat", "0")
    assert style.page_padding(root) == tuple(px(root, side) for side in (2, 4, 3, 3))


@pytest.mark.parametrize("scale", SCALES)
def test_the_sizes_of_the_controls_follow_the_display(make_root, scale):
    """Height of a push button, a list and a check box with its text."""
    root = make_root(scale)
    style.apply(root)
    assert ttk.Button(root, text="Clear").winfo_reqheight() == px(root, style.BUTTON_HEIGHT)
    assert ttk.Combobox(root, state="readonly").winfo_reqheight() \
        == px(root, style.COMBOBOX_HEIGHT)
    assert ttk.Checkbutton(root, text="ASCII").winfo_reqheight() == px(root, style.CHECK_HEIGHT)


def test_a_push_button_takes_its_text_and_17_pixels_at_each_side(make_root):
    root = make_root(1.0)
    style.apply(root)
    font = tkfont.nametofont("TkDefaultFont", root=root)
    assert ttk.Button(root, text="Clear").winfo_reqwidth() \
        == font.measure("Clear") + 2 * style.BUTTON_SIDE


def test_a_group_box_is_etched_with_its_title_centred(make_root):
    root = make_root(2.25)
    style.apply(root)
    box = style.group(root, "Tool Control")
    assert box.cget("text") == "Tool Control"
    assert str(box.cget("labelanchor")) == "n"
    assert lookup(root, "TLabelframe", "relief") == "groove"
    assert str(style.group(root, "Instructions", labelanchor="nw").cget("labelanchor")) == "nw"


# What ARES draws on canvases -------------------------------------------------------------

def test_the_bevels_are_those_of_windows_98():
    assert style.SOFT_RAISED == ((style.HIGHLIGHT, style.DARK_SHADOW), (style.LIGHT, style.SHADOW))
    assert style.RAISED == ((style.LIGHT, style.DARK_SHADOW), (style.HIGHLIGHT, style.SHADOW))
    assert style.SUNKEN == ((style.SHADOW, style.HIGHLIGHT), (style.DARK_SHADOW, style.LIGHT))
    # Each ring: top, left, bottom and right; the bottom and right run to the corners.
    assert style.bevel(0, 0, 10, 8, 2, style.SOFT_RAISED[:1]) == [
        (style.HIGHLIGHT, (0, 0, 10, 2)), (style.HIGHLIGHT, (0, 0, 2, 8)),
        (style.DARK_SHADOW, (0, 6, 10, 8)), (style.DARK_SHADOW, (8, 0, 10, 8))]


def covered(points, width, height):
    """{(x, y)} of the pixels whose centres a polygon covers (even-odd rule)."""
    corners = list(zip(points[::2], points[1::2]))
    inside = set()
    for y in range(height):
        for x in range(width):
            cx, cy, odd = x + 0.5, y + 0.5, False
            for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1]):
                if (y0 > cy) != (y1 > cy) and cx < x0 + (cy - y0) * (x1 - x0) / (y1 - y0):
                    odd = not odd
            if odd:
                inside.add((x, y))
    return inside


@pytest.mark.parametrize("pixel", [1, 2, 3])
def test_the_check_mark_of_a_canvas_checkbox(pixel):
    """Seven columns of three pixels each, down and up again, each pixel pixel x pixel large."""
    mark = covered(style.check_mark(0, 0, pixel), 7 * pixel, 7 * pixel)
    expected = {(x * pixel + i, (top + k) * pixel + j)
                for x, top in enumerate(style.CHECK_MARK) for k in range(3)
                for i in range(pixel) for j in range(pixel)}
    assert mark == expected


@pytest.mark.parametrize("scale", [1.0, 2.25])
def test_a_checkbox_on_a_canvas(make_root, scale):
    root = make_root(scale)
    style.apply(root)
    canvas = tk.Canvas(root)
    items = style.draw_checkbox(canvas, tags=("box",))
    assert len(items) == 10 and all(canvas.itemcget(i, "state") == "hidden" for i in items)
    pixel = max(1, round(scale))
    size = style.checkbox_size(canvas)
    assert size == style.CHECKBOX_SIZE * pixel
    style.place_checkbox(canvas, items, 10, 20)
    assert canvas.coords(items[0]) == [10, 20, 10 + size, 20 + size]
    rings = [canvas.coords(item) for item in items[1:9]]
    assert rings == [list(box) for _, box in style.bevel(10, 20, 10 + size, 20 + size, pixel,
                                                         style.SUNKEN)]
    assert [canvas.itemcget(item, "fill").upper() for item in items[1:9]] == [
        colour.upper() for colour, _ in style.bevel(0, 0, 1, 1, 1, style.SUNKEN)]
    for value, inside, mark, shown in (((False, True), style.WINDOW, None, "hidden"),
                                       ((True, True), style.WINDOW, style.DARK_SHADOW, "normal"),
                                       ((True, False), style.FACE, style.SHADOW, "normal"),
                                       ((False, False), style.FACE, None, "hidden")):
        style.show_checkbox(canvas, items, value)
        assert canvas.itemcget(items[0], "fill").upper() == inside
        assert canvas.itemcget(items[9], "state") == shown
        if mark:
            assert canvas.itemcget(items[9], "fill").upper() == mark
    style.show_checkbox(canvas, items, None)
    assert all(canvas.itemcget(item, "state") == "hidden" for item in items)


# Roots, fonts and the option database ------------------------------------------------------

def test_the_interface_font_is_bold_on_controls_and_plain_in_fields(make_root):
    root = make_root()
    classic = style.classic_font(root)
    if classic is None:
        pytest.skip("no interface font here")
    family, size = classic
    style.apply(root)
    for names, weight in ((style.BOLD_FONTS, "bold"), (style.PLAIN_FONTS, "normal")):
        for name in names:
            font = tkfont.nametofont(name, root=root)
            assert (font.actual("family"), font.cget("size"), font.actual("weight")) \
                == (family, size, weight), name
    assert set(style.BOLD_FONTS) | set(style.PLAIN_FONTS) == set(tkfont.names(root=root)) & {
        "TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkTooltipFont", "TkCaptionFont",
        "TkSmallCaptionFont", "TkIconFont", "TkMenuFont"}
    heading = tkfont.Font(root=root, name=style.HEADING_FONT, exists=True)
    assert (heading.actual("family"), heading.cget("size"), heading.actual("weight")) == (
        family, round(size * style.HEADING_SCALE), "bold")


def test_windows_gets_arial_9_the_size_of_12_pixels_at_96_dots_per_inch(make_root):
    assert style.FAMILIES["win32"][0] == "Arial" and style.FONT_SIZES["win32"] == 9
    assert style.FAMILIES["aqua"][0] == "Arial" and style.FONT_SIZES["aqua"] == 12
    root = make_root()
    if str(root.tk.call("tk", "windowingsystem")) != "win32":
        pytest.skip("Windows only")
    assert style.classic_font(root) == ("Arial", 9)


def test_without_the_classic_font_the_fonts_stay(make_root, monkeypatch):
    root = make_root()
    monkeypatch.setattr(style, "FAMILIES", {"win32": ("No Such Font",), "aqua": ("No Such Font",),
                                            "x11": ("No Such Font",)})
    names = style.BOLD_FONTS + style.PLAIN_FONTS
    before = {name: tkfont.nametofont(name, root=root).actual("family") for name in names}
    style.apply(root)
    assert {name: tkfont.nametofont(name, root=root).actual("family")
            for name in names} == before
    heading = tkfont.Font(root=root, name=style.HEADING_FONT, exists=True)
    assert heading.actual("family") == before["TkDefaultFont"]
    assert heading.actual("weight") == "bold"


def test_tk_windows_and_widgets_get_the_face_colour_and_blue_selections(make_root):
    root = make_root()
    style.apply(root)
    assert root.cget("background") == style.FACE
    assert tk.Toplevel(root).cget("background") == style.FACE
    assert tk.Frame(root).cget("background") == style.FACE
    assert tk.Label(root).cget("background") == style.FACE
    for widget in (tk.Text(root), tk.Entry(root)):
        assert (widget.cget("selectbackground"), widget.cget("selectforeground")) == (
            style.SELECTION, style.TEXT), widget.winfo_class()
    assert (tk.Listbox(root).cget("selectbackground"), tk.Listbox(root).cget("selectforeground")) \
        == (style.MENU_SELECTION, style.TEXT)
    assert tk.Text(root).cget("inactiveselectbackground") == style.SELECTION
    # Entries and lists are white with dark text, whatever the system's colours; an entry's
    # cursor is dark.
    entry, listbox = tk.Entry(root), tk.Listbox(root)
    assert (entry.cget("background"), entry.cget("foreground"),
            entry.cget("insertbackground")) == (style.WINDOW, style.TEXT, style.TEXT)
    assert (listbox.cget("background"), listbox.cget("foreground")) == (style.WINDOW, style.TEXT)
    # Colours a widget is given stay its own.
    assert tk.Label(root, background="#FFFFE1").cget("background") == "#FFFFE1"


def test_the_default_frame_moves_to_the_push_button_with_the_focus(make_root):
    """For a dialog whose Return presses the push button with the focus, else the default one."""
    root = make_root()
    style.apply(root)
    window = tk.Toplevel(root)
    entry = ttk.Entry(window)
    check = ttk.Checkbutton(window, text="Option")
    yes, no, cancel = buttons = [ttk.Button(window, text=text) for text in ("Yes", "No", "Cancel")]
    window.winfo_id()
    for widget in (entry, check, *buttons):
        widget.pack()
        widget.winfo_id()               # generated events reach a widget that has a window
    style.default_button(yes, buttons)

    def framed():
        return [str(button.cget("text")) for button in buttons if button.instate(["alternate"])]
    assert framed() == ["Yes"]
    assert [str(button.cget("default")) for button in buttons] == ["active", "normal", "normal"]
    for widget, expected in ((cancel, "Cancel"), (no, "No"), (entry, "Yes"), (cancel, "Cancel"),
                             (check, "Yes"), (yes, "Yes"), (no, "No")):
        widget.event_generate("<FocusIn>")
        assert framed() == [expected], widget
    # While another window is active the frame stays; back, the window gets the focus
    # first, then the button that has it.
    no.event_generate("<FocusOut>")
    assert framed() == ["No"]
    window.event_generate("<FocusIn>")
    no.event_generate("<FocusIn>")
    assert framed() == ["No"]


# The window ---------------------------------------------------------------------

def test_the_window_and_a_second_window_use_the_ares98_theme(make_root, tmp_path):
    for root in (make_root(), make_root()):
        app = App(root, settings_path=tmp_path / "settings.json")
        try:
            assert ttk.Style(root).theme_use() == style.THEME
        finally:
            app.close()


@pytest.mark.parametrize("orient", ["Vertical", "Horizontal"])
def test_a_scroll_bars_thumb_is_one_element_with_what_lies_inside_it(make_root, orient):
    """Tk starts a drag, and sinks the thumb, only where identify names the thumb. Inside it lies
    what makes it square at least, which identify would name instead: a press on the thumb's
    middle would do nothing, only one on its rim."""
    def nodes(layout):
        for name, options in layout:
            yield name, options
            yield from nodes(options.get("children", ()))
    root = make_root(1.0)
    style.apply(root)
    thumb = dict(nodes(ttk.Style(root).layout(f"{orient}.TScrollbar")))["Ares.bar.thumb"]
    assert thumb["children"]
    assert str(thumb.get("unit")) == "1"


@pytest.mark.parametrize("orient", ["vertical", "horizontal"])
def test_a_drag_starts_anywhere_on_a_scroll_bars_thumb(mapped_area, orient):
    inside = mapped_area(400, 400)
    moved = []
    bar = ttk.Scrollbar(inside, orient=orient, command=lambda *args: moved.append(args))
    vertical = orient == "vertical"
    bar.place(x=0, y=0, **({"height": 300} if vertical else {"width": 300}))
    bar.set(0.25, 0.75)
    inside.update()
    length = bar.winfo_height() if vertical else bar.winfo_width()
    across = (bar.winfo_width() if vertical else bar.winfo_height()) // 2

    def point(along):
        return (across, along) if vertical else (along, across)
    thumb = [along for along in range(length) if 0.3 < bar.fraction(*point(along)) < 0.7]
    assert thumb
    assert {bar.identify(*point(along)) for along in thumb} == {"Ares.bar.thumb"}
    x, y = point(length // 2)
    bar.event_generate("<ButtonPress-1>", x=x, y=y)
    bar.event_generate("<B1-Motion>", x=x + (0 if vertical else 40), y=y + (40 if vertical else 0))
    bar.event_generate("<ButtonRelease-1>", x=x, y=y)
    assert moved and moved[-1][0] == "moveto" and float(moved[-1][1]) > 0.25


@pytest.mark.parametrize("scale", [1, 1.25, 1.5, 1.75, 2, 2.25, 2.5, 3])
def test_a_checkbox_fits_a_table_row(make_root, scale):
    """Its pixels are enlarged by whole ones, which at 150 % could make it taller than a row."""
    root = make_root(scale)
    style.apply(root)
    canvas = tk.Canvas(root)
    size = style.checkbox_size(canvas)
    assert size <= px(root, 16) - px(root, style.BEVEL)
    items = style.draw_checkbox(canvas)
    style.place_checkbox(canvas, items, 0, 0)
    assert canvas.coords(items[0]) == [0, 0, size, size]


@pytest.mark.parametrize("scale", [1.0, 2.25])
def test_every_scroll_bar_of_the_window_and_its_dialogs_is_classic(make_root, tmp_path, scale):
    root = make_root(scale)
    app = App(root, settings_path=tmp_path / "settings.json")
    try:
        app.cmd_new()
        app.run("memory_map")
        app.run("editor_font")
        boxes = (app.execute.data_segment.places, app.font_dialog.family_box)
        for box in boxes:
            root.tk.call("ttk::combobox::PopdownWindow", box)   # its list, made but not shown
        bars = scroll_bars(root)
        side = px(root, style.SCROLLBAR_WIDTH)
        wide = px(root, style.EDITOR_SCROLLBAR_WIDTH)
        for path, orient in bars.items():
            thickness = requested(root, path)[0 if orient == "vertical" else 1]
            if path.startswith(f"{app.editor.current}."):
                assert str(root.tk.call(path, "cget", "-style")) \
                    == f"Editor.{orient.title()}.TScrollbar", path
                assert thickness == wide, path
            else:
                assert str(root.tk.call(path, "cget", "-style")) == "", path
                assert thickness == side, path
        parts = [app.editor.current, app.messages, app.execute.text_segment,
                 app.execute.data_segment, app.execute.labels, app.registers, app.coproc10,
                 app.coproc11, app.memory_map.window] + [f"{box}.popdown" for box in boxes]
        for part in parts:
            assert any(path.startswith(f"{part}.") for path in bars), f"no scroll bar in {part}"
        assert sum(path.startswith(f"{app.messages}.") for path in bars) == 4  # Messages, Run I/O
        assert ttk.Style(root).layout("Vertical.TScrollbar")[0][0] == "Ares.bar.trough"
        app.font_dialog.cancel()
    finally:
        app.close()


# Gradients -----------------------------------------------------------------------------------

def test_a_gradient_starts_and_ends_exactly_on_its_two_colours():
    for rows in (2, 3, 20, 21, 34, 47, 77):
        colours = style.gradient("#FFFFFF", "#DCDCDC", rows)
        assert len(colours) == rows
        assert (colours[0], colours[-1]) == ("#FFFFFF", "#DCDCDC")


def test_a_gradient_is_an_exact_straight_line_between_its_colours():
    assert style.gradient("#000000", "#FFFFFF", 3) == ["#000000", "#808080", "#FFFFFF"]
    assert style.gradient("#102030", "#50A0F0", 5) == ["#102030", "#204060", "#306090",
                                                       "#4080C0", "#50A0F0"]
    assert style.gradient("#FFFFFF", "#DEDEDE", 4) == ["#FFFFFF", "#F4F4F4", "#E9E9E9", "#DEDEDE"]
    for rows in (21, 47):
        for k, colour in enumerate(style.gradient("#FFFFFF", "#DEDEDE", rows)):
            assert abs(int(colour[1:3], 16) - (255 - 33 * k / (rows - 1))) <= 0.5


def test_a_gradient_of_one_row_or_none():
    assert style.gradient("#FFFFFF", "#DEDEDE", 1) == ["#FFFFFF"]
    assert style.gradient("#FFFFFF", "#DEDEDE", 0) == []


@pytest.mark.parametrize("scale", SCALES)
def test_a_gradient_is_drawn_as_one_item_for_each_row_of_pixels(make_root, scale):
    root = make_root(scale)
    canvas = tk.Canvas(root)
    height = px(root, 34)
    rows = style.draw_gradient(canvas, ("#FFFFFF", "#DCDCDC"), height)
    assert list(canvas.find_all()) == rows and len(rows) == height
    assert {canvas.type(row) for row in rows} == {"rectangle"}
    assert [canvas.coords(row) for row in rows] == [[0, y, style.GRADIENT_WIDTH, y + 1]
                                                    for y in range(height)]
    assert ([canvas.itemcget(row, "fill").upper() for row in rows]
            == style.gradient("#FFFFFF", "#DCDCDC", height))
    assert {canvas.itemcget(row, "width") for row in rows} == {"0.0"}


def test_a_gradient_is_wider_than_any_desktop():
    assert 3 * 7680 < style.GRADIENT_WIDTH < 2 ** 15    # three 8K screens, within Tk's coordinates


def test_the_two_bars_have_the_colours_of_their_gradients():
    assert style.MENU_BAR == ("#FFFFFF", "#DEDEDE")
    assert style.TOOL_STRIP == ("#FFFFFF", "#DCDCDC")
