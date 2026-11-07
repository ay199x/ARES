# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The look of the window and its dialogs: inner windows with title bars, no title strips,
sunken borders, raised headings, shaded rows, raised highlights, blue selections, the
interface font and the face colour."""

import contextlib
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

import pytest
from conftest import fixed_screen, lay_out, press_key, pump
from test_gui_data import loaded
from test_gui_dialogs import asked, program
from test_style import LETTERS, SOFT_RAISED, bevelled, lookup, make_root  # noqa: F401

from ares.gui import style
from ares.gui.execute import CHANGED as WORD_CHANGED
from ares.gui.execute import CURRENT, FAILED, InnerWindow
from ares.gui.registers import CHANGED as REGISTER_CHANGED
from ares.gui.table import PLAIN, SHADED, STRIPE, STRIPED, WHITE, Column, Row, Table, edges
from ares.gui.widgets import px


def message_pages(app):
    """{title: page} of the tabs ARES Messages and Run I/O."""
    return {app.messages.tab(tab, "text"): app.root.nametowidget(tab)
            for tab in app.messages.tabs()}


def tables(app):
    execute = app.execute
    return [execute.text_segment.table, execute.data_segment.table, execute.labels.table,
            app.registers.table, app.coproc10.table, app.coproc11.table]


def padding(widget):
    """A ttk widget's padding as a list of pixels."""
    value = widget.cget("padding")
    words = value if isinstance(value, tuple) else widget.tk.splitlist(str(value))
    return [int(str(word)) for word in words]


def canvas_letters(canvas, width, height):
    """The picture the rectangles of a canvas paint, one letter for each pixel (? for none).

    Each rectangle without an outline fills x0 <= x < x1, y0 <= y < y1, in
    the order the canvas draws its items.
    """
    rows = [["?"] * width for _ in range(height)]
    for item in canvas.find_all():
        if canvas.type(item) != "rectangle":
            continue
        letter = LETTERS.get(str(canvas.itemcget(item, "fill")).upper(), "?")
        x0, y0, x1, y1 = (round(value) for value in canvas.coords(item))
        for y in range(max(0, y0), min(height, y1)):
            rows[y][max(0, x0):min(width, x1)] = [letter] * (min(width, x1) - max(0, x0))
    return ["".join(row) for row in rows]


def classic_family(root):
    """The classic interface font installed here, or None."""
    classic = style.classic_font(root)
    return None if classic is None else classic[0]


def layout_parts(layout):
    """The names of the elements of a ttk layout, outside in."""
    for name, options in layout:
        yield name
        yield from layout_parts(options.get("children", ()))


def widgets_of(widget, kind):
    """The widgets of a class inside a widget, in the order they were made."""
    found = []
    for child in widget.winfo_children():
        if isinstance(child, kind):
            found.append(child)
        found += widgets_of(child, kind)
    return found


def move_focus(old, new):
    """Send what Tk sends when the keyboard focus moves from old to new (None: another window).

    Hidden windows never get the focus, so the events are generated.
    """
    for widget, sequence in ((old, "<FocusOut>"), (new, "<FocusIn>")):
        if widget is not None:
            widget.winfo_id()                   # generated events need the widget's window
            widget.event_generate(sequence)


def drawn(widget, *options):
    """The values the theme draws a ttk widget with, in the widget's state now."""
    s = ttk.Style(widget)
    name = str(widget.cget("style")) or widget.winfo_class()
    return tuple(str(s.lookup(name, option, widget.state())) for option in options)


SELECTION = ("selectbackground", "selectforeground")
BLUE_SELECTION = (style.SELECTION, style.TEXT)
UNSEEN_SELECTION = (style.WINDOW, style.TEXT)       # the colours of the field around it


# Titles appear once ---------------------------------------------------------------------------

def every_widget(widget):
    found = []
    for child in widget.winfo_children():
        found += [child] + every_widget(child)
    return found


def test_a_tab_or_a_title_bar_names_a_pane_and_nothing_else_does(app):
    pages = message_pages(app)
    assert list(pages) == ["ARES Messages", "Run I/O"]
    names = ("Text Segment", "Data Segment", "Labels", "Registers", "Coproc 10", "Coproc 11",
             "ARES Messages", "Run I/O")
    for widget in every_widget(app.root):
        if widget.winfo_class() in ("TLabel", "Label"):
            assert widget.cget("text") not in names, widget
    assert [app.side.tab(tab, "text") for tab in app.side.tabs()] == [
        "Registers", "Coproc 10", "Coproc 11"]
    # A register tab holds its table and nothing else.
    assert app.registers.pack_slaves() == [app.registers.table]
    assert not hasattr(style, "title_strip")


def test_the_inner_windows_have_a_raised_frame_and_a_small_title_bar(app):
    root = app.root
    execute = app.execute
    ring = px(root, 1)
    for window, title in ((execute.text_segment, "Text Segment"),
                          (execute.data_segment, "Data Segment"), (execute.labels, "Labels")):
        assert isinstance(window, InnerWindow) and window.title == title
        assert str(window.cget("relief")) == "raised"
        assert int(window.cget("borderwidth")) == 2 * ring
        assert int(window.cget("padx")) == int(window.cget("pady")) == px(root, 2)
        assert window.pack_slaves()[0] is window.bar
        assert int(window.bar.cget("height")) == px(root, 23)
        assert window.bar.itemcget(window.text, "text") == title
        assert window.bar.itemcget(window.text, "font") == "TkDefaultFont"     # bold
        assert window.bar.cget("background") == style.FACE
        assert window.bar.itemcget(window.accent, "state") == "hidden"
        assert window.table.master is window


def test_the_inner_window_last_used_is_the_active_one(app):
    execute = app.execute
    windows = (execute.text_segment, execute.data_segment, execute.labels)
    assert not any(window.active for window in windows)     # none at the start
    data = execute.data_segment
    data.table.body.winfo_id()
    execute.text_segment.table.body.winfo_id()
    data.table.body.event_generate("<FocusIn>")
    assert [window.active for window in windows] == [False, True, False]
    assert data.bar.cget("background") == style.TITLE
    assert data.bar.itemcget(data.accent, "state") == "normal"
    assert data.bar.itemcget(data.accent, "fill").upper() == style.ACCENT
    execute.text_segment.table.body.event_generate("<FocusIn>")
    assert [window.active for window in windows] == [True, False, False]
    assert data.bar.cget("background") == style.FACE
    assert data.bar.itemcget(data.accent, "state") == "hidden"


def test_a_press_on_a_title_bar_gives_its_table_the_keyboard_focus(app, hidden_windows):
    window = app.execute.data_segment
    window.bar.winfo_id()
    window.bar.event_generate("<ButtonPress-1>", x=5, y=5)
    assert hidden_windows.focus is window.table.body


def test_the_accent_line_runs_along_the_bottom_of_the_title_bar(app):
    window = app.execute.text_segment
    window.bar.winfo_id()
    window.bar.event_generate("<Configure>", width=500, height=int(window.bar.cget("height")))
    height, ring = int(window.bar.cget("height")), px(app.root, 1)
    assert window.bar.coords(window.accent) == [0, height - ring, 500, height]


# Sunken borders ---------------------------------------------------------------------

def test_the_window_parts_have_sunken_borders(app):
    app.cmd_new()
    ring = px(app.root, 1)
    texts = [app.editor.current.text, app.messages.messages, app.messages.run_io]
    for frame in tables(app) + [text.master for text in texts]:
        # A Tk frame, which draws its border itself: a ttk frame would draw a picture of its
        # whole size each time (25-50 ms for a page at 4K).
        assert isinstance(frame, tk.Frame) and not isinstance(frame, ttk.Widget), frame
        assert (str(frame.cget("relief")), frame.winfo_pixels(frame.cget("borderwidth"))) == (
            "sunken", 2 * ring), frame
        # The text or table with its scroll bars inside the border.
        assert "TScrollbar" in {child.winfo_class() for child in frame.winfo_children()}, frame
    assert app.editor.current.gutter.master is app.editor.current.field
    for table in tables(app):
        assert table.header.master is table and table.body.master is table


@pytest.mark.parametrize("scale", [1.0, 2.25])
def test_a_sunken_frame_insets_its_contents_by_its_border(make_root, scale):
    root = make_root(scale)
    style.apply(root)
    root.geometry("400x300")                # a withdrawn window with a size lays out its parts
    ring = px(root, 1)
    for kind in (ttk.Frame, tk.Frame):
        for thin, rings in ((False, 2), (True, 1)):
            frame = style.sunken(kind(root), thin=thin)
            frame.place(x=0, y=0, width=120, height=80)
            inside = tk.Frame(frame)
            inside.pack(fill="both", expand=True)
            root.update_idletasks()
            border = rings * ring
            assert (inside.winfo_x(), inside.winfo_y(), inside.winfo_width(),
                    inside.winfo_height()) == (border, border, 120 - 2 * border,
                                               80 - 2 * border), (kind, thin)
            frame.destroy()
    # A table: its headings and rows start inside its border.
    font = tkfont.Font(root=root, family="Courier New", size=10)
    table = Table(root, [Column("a", "A", 50, stretch=True)], font)
    table.place(x=0, y=0, width=300, height=200)
    root.update_idletasks()
    assert (table.header.winfo_x(), table.header.winfo_y()) == (2 * ring, 2 * ring)
    assert table.body.winfo_x() == 2 * ring
    assert table.body.winfo_y() == 2 * ring + table.header.winfo_height()


# Table headings -------------------------------------------------------------------------

def headings_shown(table):
    """[(column, its heading cell as letters)] of a table, and the texts of its headings."""
    header = table.header
    height = int(header.cget("height"))
    widths = [column.width for column in table.columns]
    shown = canvas_letters(header, sum(widths), height)
    cells, x0 = [], 0
    for column, width in zip(table.columns, widths):
        cells.append((column, [row[x0:x0 + width] for row in shown]))
        x0 += width
    texts = [header.itemcget(item, "text") for item in header.find_all()
             if header.type(item) == "text"]
    return cells, texts


def test_the_headings_are_raised_buttons(app):
    ring = px(app.root, 1)
    for table in tables(app):
        assert table.header.cget("background") == style.FACE
        height = int(table.header.cget("height"))
        cells, texts = headings_shown(table)
        for column, cell in cells:
            assert cell == bevelled(column.width, height, ring, SOFT_RAISED), column.id
        assert texts == [column.heading for column in table.columns]


def test_the_headings_at_225_percent(make_root):
    root = make_root(2.25)
    style.apply(root)
    font = tkfont.Font(root=root, family="Courier New", size=10)
    table = Table(root, [Column("a", "Address", 120), Column("b", "Value", 80, stretch=True)],
                  font)
    table.fill(400)
    height = int(table.header.cget("height"))
    cells, texts = headings_shown(table)
    assert [column.width for column, _ in cells] == [120, 280]
    for column, cell in cells:
        assert cell == bevelled(column.width, height, 2, SOFT_RAISED), column.id
    assert texts == ["Address", "Value"]


# Selections ---------------------------------------------------------------------------

def test_selections_are_blue_with_dark_text(app):
    app.cmd_new()
    for table in tables(app):
        assert (table.select_background, table.select_foreground) == BLUE_SELECTION
    # The editor, ARES Messages and Run I/O; their selection stays blue while another
    # window (Find) has the focus.
    for text in (app.editor.current.text, app.messages.messages, app.messages.run_io):
        assert (text.cget("selectbackground"), text.cget("selectforeground"),
                text.cget("inactiveselectbackground")) == (*BLUE_SELECTION, style.SELECTION)
    # The list of a combobox.
    box = app.execute.data_segment.places
    app.root.tk.call("ttk::combobox::PopdownWindow", box)       # made but not shown
    assert [str(app.root.tk.call(f"{box}.popdown.f.l", "cget", f"-{option}")) for option in (
        "selectbackground", "selectforeground", "background")] == [style.MENU_SELECTION,
                                                                    style.TEXT, style.WINDOW]
    # The field of a register's value being changed: white with dark text and cursor, whatever
    # the system's colours.
    pane = app.registers
    pane.editable = True
    pane.edit(0)
    assert (pane.editor.cget("selectbackground"), pane.editor.cget("selectforeground")) \
        == BLUE_SELECTION
    assert (pane.editor.cget("background"), pane.editor.cget("foreground"),
            pane.editor.cget("insertbackground")) == (style.WINDOW, style.TEXT, style.TEXT)
    pane.cancel_edit()


def test_selected_text_in_the_editor_is_dark_on_blue_over_its_colours(app):
    app.cmd_new()
    text = app.editor.current.text
    text.insert("1.0", "_start: MOV R0, #42       @ answer\n")
    text.tag_add("sel", "1.0", "end")
    # Tk shows the colours of the highest tag: the selection is above every colour.
    coloured = [tag for tag in text.tag_names() if str(text.tag_cget(tag, "foreground"))]
    assert coloured[-1] == "sel" and len(coloured) > 1
    for index, tag in (("1.0", "label"), ("1.12", "register"), ("1.16", "number"),
                       ("1.26", "comment")):
        assert {tag, "sel"} <= set(text.tag_names(index)), index
    assert str(text.tag_cget("sel", "background")) == style.SELECTION
    assert str(text.tag_cget("sel", "foreground")) == style.TEXT


# Fonts and colours of the window and its dialogs ---------------------------------------------

def test_the_window_uses_the_classic_interface_font(app):
    family = classic_family(app.root)
    if family is None:
        pytest.skip("no classic interface font here")
    for name in ("TkDefaultFont", "TkTextFont", "TkHeadingFont"):
        font = tkfont.nametofont(name, root=app.root)
        assert (font.actual("family"), font.cget("size")) == style.classic_font(app.root)
    # The editor, the tables, ARES Messages and Run I/O keep their own monospace fonts.
    assert app.messages.messages.cget("font") == str(app.pane_font)
    assert app.execute.text_segment.table.font is app.pane_font
    assert app.registers.table.font is app.register_font


def test_the_dialogs_have_the_face_colour(app, tmp_path):
    assert app.root.cget("background") == style.FACE
    app.cmd_new()
    app.run("find")
    app.run("memory_map")
    app._open_line_dialog("")
    windows = [app.find_dialog.window, app.memory_map.window, app.line_dialog.window]
    app.run("editor_font")
    windows.append(app.font_dialog.window)
    # The font's sample is shown in a sunken white field.
    field = app.font_dialog.preview.master
    assert str(field.cget("style")) == style.SUNKEN_FRAME
    assert app.font_dialog.preview.cget("background") == "#FFFFFF"
    for window in windows:
        assert window.cget("background") == style.FACE, window.title()
    app.font_dialog.cancel()
    app._close_line_dialog()
    app.memory_map.close()
    app.find_dialog.close()
    dialog = asked(app, tmp_path, program(50))          # a dialog the program asked for
    assert dialog.window.cget("background") == style.FACE


def all_buttons(widget):
    """{text: button} of the ttk buttons in a window."""
    found = {}
    for child in widget.winfo_children():
        if isinstance(child, ttk.Button):
            found[str(child.cget("text"))] = child
        found.update(all_buttons(child))
    return found


def test_the_button_return_presses_is_drawn_as_the_default_button(app, tmp_path):
    app.cmd_new()
    app.run("find")
    app.run("editor_font")
    app._open_line_dialog("")
    for window, default in ((app.find_dialog.window, "Find"), (app.font_dialog.window, "OK"),
                            (app.line_dialog.window, "OK")):
        assert [text for text, button in all_buttons(window).items()
                if button.instate(["alternate"])] == [default], window.title()
    app._close_line_dialog()
    app.font_dialog.cancel()
    app.find_dialog.close()
    dialog = asked(app, tmp_path, program(50))
    assert [label for label, button in dialog.buttons.items()
            if button.instate(["alternate"])] == ["Yes"]


def test_the_file_tabs_have_their_close_buttons(app):
    """The close icon stands after the tab's text, and is raised while the mouse is on it."""
    notebook = app.editor.notebook
    assert notebook.close_images == app.close_images
    assert str(notebook.strip.cget("background")).upper() == style.TAB


def test_the_breakpoints_are_classic_checkboxes(app, tmp_path):
    """Drawn on the table's canvas: a sunken white square, gray while switched off."""
    loaded(app, tmp_path)
    table = app.execute.text_segment.table
    column = next(column for column in table.columns if column.id == "bkpt")
    assert column.checkbox
    box = table._boxes[table.slots[0][2]]
    assert [table.body.itemcget(item, "state") for item in box[:9]] == ["normal"] * 9
    assert table.body.itemcget(box[0], "fill").upper() == style.WINDOW
    assert table.body.itemcget(box[9], "state") == "hidden"            # not checked


# The focus: selections, read-only lists, the slider and the default button ---------------------

def test_find_shows_the_selection_of_the_field_with_the_focus_only(app):
    """Both fields keep their selection (they do not export it); only one is shown."""
    app.cmd_new()
    app.run("find")
    dialog = app.find_dialog
    find, replace = dialog.find_entry, dialog.replace_entry
    replace.insert(0, "ADD")
    dialog.show("MOV")                          # its text selected, ready to be typed over
    move_focus(None, find)
    assert drawn(find, *SELECTION) == BLUE_SELECTION
    move_focus(find, replace)                   # Tab: the text of Replace with is selected
    replace.event_generate("<<TraverseIn>>")
    assert find.selection_present() and replace.selection_present()
    assert drawn(replace, *SELECTION) == BLUE_SELECTION
    assert drawn(find, *SELECTION) == UNSEEN_SELECTION
    move_focus(replace, None)                   # the editor is clicked: neither is shown
    assert drawn(replace, *SELECTION) == UNSEEN_SELECTION
    dialog.close()


def test_a_chosen_place_is_highlighted_only_while_its_list_has_the_focus(app, tmp_path):
    data = loaded(app, tmp_path)
    places = data.places
    places.winfo_id()
    app.root.tk.call("ttk::combobox::SelectEntry", places, 1)  # chosen in the list, which
    move_focus(None, places)                                    # gives the box the focus
    app.root.update()
    assert places.get() == "current SP: stack at 0xfffffffc"
    assert places.selection_present()
    assert places.instate(["readonly", "focus"])
    # Dark on blue inside a ring of white dots.
    assert drawn(places, "foreground", "focuscolor") == (style.TEXT, style.WINDOW)
    assert drawn(places, "fieldbackground") == (style.MENU_SELECTION,)
    assert drawn(places, *SELECTION) == BLUE_SELECTION
    # A click in the table takes the focus: the place stays selected, unseen.
    move_focus(places, data.table.body)
    assert places.selection_present() and not places.instate(["focus"])
    assert drawn(places, "foreground") == (style.TEXT,)
    assert drawn(places, *SELECTION) == UNSEEN_SELECTION


def test_the_editor_font_dialog_opens_with_its_font_list_showing_the_focus(app, hidden_windows):
    """A read-only list shows no caret: the blue fill and the ring of dots show its focus."""
    app.run("editor_font")
    box = app.font_dialog.family_box
    assert hidden_windows.focus is box
    move_focus(None, box)
    assert box.instate(["readonly", "focus"]) and not box.selection_present()
    assert drawn(box, "foreground", "focuscolor", "fieldbackground") == (
        style.TEXT, style.WINDOW, style.MENU_SELECTION)
    parts = list(layout_parts(ttk.Style(app.root).layout("TCombobox")))
    assert parts[-2:] == ["Combobox.focus", "Combobox.textarea"]
    app.font_dialog.cancel()


@contextlib.contextmanager
def traversal(widget):
    """Let Tk's keyboard traversal work in the hidden window of widget while this lasts.

    Tk's traversal skips widgets that are not viewable, and nothing in a hidden
    window is. While this lasts, a widget counts as viewable when it and its
    masters up to its window are managed, a page of a notebook only while it is
    selected. A hidden window never gets the keyboard focus either: Tk's focus
    command notes in ::focus_given the last widget it was asked to give it to.

    Tk reads tk_focusNext and tk_focusPrev from focus.tcl when one is first used.
    Under pytest's capture of the output, Tcl on Windows can fail to read that
    file ("No error"): the capture closes handles that Tcl's standard channels
    still hold, and Tcl will not open a file that Windows gives one of those
    handles again. So the file is read here and Tcl only runs its text.
    """
    if not widget.tk.call("info", "commands", "::tk_focusPrev"):
        library = Path(widget.tk.eval("set ::tk_library"))
        widget.tk.eval((library / "focus.tcl").read_text(encoding="utf-8"))
    widget.tk.eval(r"""
        rename ::winfo ::hidden_winfo
        proc ::winfo {option args} {
            if {$option ne "viewable"} {
                return [::hidden_winfo $option {*}$args]
            }
            set w [lindex $args 0]
            while {[::hidden_winfo toplevel $w] ne $w} {
                set master [::hidden_winfo parent $w]
                if {[::hidden_winfo manager $w] eq ""} {
                    return 0
                }
                if {[::hidden_winfo class $master] eq "TNotebook" && [$master select] ne $w} {
                    return 0
                }
                set w $master
            }
            return 1
        }
        rename ::focus ::hidden_focus
        set ::focus_given {}
        proc ::focus {args} {
            if {[llength $args] == 1 && [string index [lindex $args 0] 0] eq "."} {
                set ::focus_given [lindex $args 0]
            }
            return [::hidden_focus {*}$args]
        }
    """)
    try:
        yield
    finally:
        widget.tk.eval("rename ::winfo {}; rename ::hidden_winfo ::winfo; "
                       "rename ::focus {}; rename ::hidden_focus ::focus")


def focus_before(widget):
    """The widget that Shift+Tab gives the keyboard focus to from widget, as Tk finds it."""
    with traversal(widget):
        return widget.nametowidget(str(widget.tk.call("tk_focusPrev", widget)))


def tab(widget, back=False):
    """Press Tab (Shift+Tab when back) in widget, inside traversal(): the widget that Tk's
    bindings then give the keyboard focus to, or None when they give it to none."""
    widget.tk.eval("set ::focus_given {}")
    if back:
        press_key(widget, "<Shift-Key-Tab>", "<<PrevWindow>>")
    else:
        press_key(widget, "<Key-Tab>", "<<NextWindow>>")
    given = str(widget.tk.eval("set ::focus_given"))
    return widget.nametowidget(given) if given else None


def tab_cycle(start, back=False, limit=40):
    """The widgets that Tab (Shift+Tab when back) takes the keyboard focus to from start, one
    press after the other, up to start again. It ends early with a widget that keeps the
    focus (twice in a row), or with None when a press gave the focus to no widget."""
    order, widget = [], start
    with traversal(start):
        while len(order) < limit:
            following = tab(widget, back)
            order.append(following)
            if following is None or following is widget or following is start:
                break
            widget = following
    return order


def test_the_run_speed_slider_shows_the_focus(app):
    """Shift+Tab from the Edit and Execute tabs reaches it; the arrow keys then move it."""
    speed = app.speed
    assert str(speed.cget("style")) == "" and str(speed.cget("takefocus")) == "ttk::takefocus"
    parts = list(layout_parts(ttk.Style(app.root).layout("Horizontal.TScale")))
    assert parts == ["Horizontal.Scale.focus", "Ares.trough", "Ares.slider"]
    ring = px(app.root, 1)
    assert speed.winfo_reqheight() == px(app.root, style.SLIDER[1]) + 2 * ring
    for page in (app.editor, app.execute):
        app.views.select(page)
        assert focus_before(app.views) is speed, app.views.tab(page, "text")
    # Left and Right (Tk's <<PrevChar>> and <<NextChar>>) move it one step.
    assert app.speed_label.cget("text") == "Run speed at max (no interaction)"
    press_key(speed, "<<PrevChar>>")
    assert app.speed_label.cget("text") == "Run speed 30 inst/sec" and app.run_speed == 30
    press_key(speed, "<<NextChar>>")
    assert app.speed_label.cget("text") == "Run speed at max (no interaction)"
    assert app.run_speed is None


def framed(buttons):
    """The labels of the buttons drawn with the black frame of the default button."""
    return [label for label, button in buttons.items() if button.instate(["alternate"])]


RETURN_KEYS = ["<Key-Return>", "<Key-KP_Enter>"]        # Return and the keypad's Enter


def check_return_presses_the_framed_button(buttons, widgets, pressed, key):
    """Move the focus to each widget in turn: key presses the one button with the frame.

    The buttons' actions are replaced: each appends its label to pressed.
    """
    for label, button in buttons.items():
        button.configure(command=lambda label=label: pressed.append(label))
    previous = None
    for widget in widgets:
        move_focus(previous, widget)
        previous = widget
        (label,) = framed(buttons)
        count = len(pressed)
        press_key(widget, key)
        assert pressed[count:] == [label], (widget, label)


@pytest.mark.parametrize("key", RETURN_KEYS)
def test_the_frame_follows_the_button_return_presses_in_the_editor_font_dialog(app, key):
    app.run("editor_font")
    dialog = app.font_dialog
    buttons = all_buttons(dialog.window)
    assert framed(buttons) == ["OK"]
    pressed = []
    dialog.ok = lambda: pressed.append("OK")    # what Return does outside the buttons
    fields = [dialog.family_box, *widgets_of(dialog.window, ttk.Spinbox),
              *widgets_of(dialog.window, ttk.Checkbutton)]
    assert len(fields) == 4
    check_return_presses_the_framed_button(buttons, [
        *fields, buttons["OK"], buttons["Cancel"], dialog.family_box, buttons["Cancel"],
        buttons["OK"]], pressed, key)
    assert pressed == ["OK"] * 5 + ["Cancel", "OK", "Cancel", "OK"]
    dialog.cancel()


@pytest.mark.parametrize("key", RETURN_KEYS)
def test_the_frame_follows_the_button_return_presses_in_the_input_dialog(app, key):
    app._open_line_dialog("")
    dialog = app.line_dialog
    buttons = all_buttons(dialog.window)
    assert framed(buttons) == ["OK"]
    pressed = []
    dialog.ok = lambda: pressed.append("OK")
    check_return_presses_the_framed_button(buttons, [
        dialog.entry, buttons["Cancel"], dialog.entry, buttons["Cancel"], buttons["OK"]],
        pressed, key)
    assert pressed == ["OK", "Cancel", "OK", "Cancel", "OK"]
    app._close_line_dialog()


@pytest.mark.parametrize("key", RETURN_KEYS)
def test_the_frame_follows_the_button_return_presses_in_find_and_replace(app, key):
    """Return presses the button with the focus there too."""
    app.cmd_new()
    app.run("find")
    dialog = app.find_dialog
    buttons = all_buttons(dialog.window)
    assert list(buttons) == ["Find", "Replace", "Replace All", "Close"]
    assert framed(buttons) == ["Find"]
    pressed = []
    dialog._find = lambda: pressed.append("Find")      # what Return does outside the buttons
    boxes = widgets_of(dialog.window, ttk.Checkbutton)
    assert len(boxes) == 2
    check_return_presses_the_framed_button(buttons, [
        dialog.find_entry, dialog.replace_entry, *boxes, buttons["Close"],
        buttons["Replace All"], buttons["Replace"], dialog.find_entry, buttons["Find"]],
        pressed, key)
    assert pressed == ["Find"] * 4 + ["Close", "Replace All", "Replace", "Find", "Find"]
    dialog.close()


@pytest.mark.parametrize("key", RETURN_KEYS)
@pytest.mark.parametrize("service, labels", [(50, ["Yes", "No", "Cancel"]), (51, ["OK", "Cancel"])])
def test_the_frame_follows_the_button_return_presses_in_a_dialog_of_the_program(
        app, tmp_path, service, labels, key):
    dialog = asked(app, tmp_path, program(service))
    buttons = dialog.buttons
    assert list(buttons) == labels and framed(buttons) == labels[:1]
    pressed = []
    fields = [dialog.entry] if dialog.entry is not None else []
    order = [*fields, *(buttons[label] for label in reversed(labels)), *fields,
             buttons[labels[-1]]]
    check_return_presses_the_framed_button(buttons, order, pressed, key)
    assert pressed == ([labels[0]] if fields else []) + labels[::-1] + (
        [labels[0]] if fields else []) + [labels[-1]]


@pytest.mark.parametrize("key", RETURN_KEYS)
def test_the_frame_follows_the_button_return_presses_in_dump_memory(
        app, tmp_path, hidden_windows, key):
    loaded(app, tmp_path)
    app.run("dump_memory")
    dialog = app.dump_dialog
    buttons = all_buttons(dialog.window)
    assert list(buttons) == ["Dump To File...", "Cancel"]
    assert framed(buttons) == ["Dump To File..."]
    lists = widgets_of(dialog.window, ttk.Combobox)         # Part of memory, then Format
    assert len(lists) == 2 and lists[0] is dialog.segment_box
    assert hidden_windows.focus is dialog.segment_box
    pressed = []
    dialog.dump = lambda: pressed.append("Dump To File...")  # what Return does outside the buttons
    check_return_presses_the_framed_button(buttons, [
        *lists, buttons["Cancel"], buttons["Dump To File..."], dialog.window,
        buttons["Cancel"], dialog.segment_box], pressed, key)
    assert pressed == ["Dump To File..."] * 2 + ["Cancel"] + ["Dump To File..."] * 2 + [
        "Cancel", "Dump To File..."]
    dialog.close()


@pytest.mark.parametrize("key", RETURN_KEYS)
def test_return_presses_close_in_the_memory_map(app, hidden_windows, key):
    """Close has the black frame and the focus; Return presses it, in the table too."""
    app.run("memory_map")
    dialog = app.memory_map
    buttons = all_buttons(dialog.window)
    assert list(buttons) == ["Close"] and framed(buttons) == ["Close"]
    assert hidden_windows.focus is buttons["Close"]
    pressed = []
    check_return_presses_the_framed_button(buttons, [
        buttons["Close"], dialog.table.body, dialog.window, buttons["Close"]], pressed, key)
    assert pressed == ["Close"] * 4
    buttons["Close"].configure(command=dialog.close)        # its own action again
    press_key(dialog.table.body, key)
    assert dialog.window is None


# Rows, grid lines and highlights ---------------------------------------------------------

def cell_fill(table, place, k):
    """The colour a cell shows: its own, else its row's."""
    items = table.slots[place]
    body = table.body
    if body.itemcget(items[1 + 2 * k], "state") == "normal":
        return body.itemcget(items[1 + 2 * k], "fill").upper()
    return body.itemcget(items[0], "fill").upper()


def shaded_table(make_table_font, rows):
    frame, font = make_table_font
    columns = [Column("a", "A", 60, shade=PLAIN), Column("b", "B", 60, shade=STRIPED),
               Column("c", "C", 60, shade=SHADED), Column("d", "D", 60, shade=SHADED)]
    table = Table(frame, columns, font)
    table.fit(table.row_height * 6)
    table.fill(240)
    table.set_rows(len(rows), rows.__getitem__)
    return table


@pytest.fixture
def table_parts(tk_root):
    frame = tk.Frame(tk_root)
    yield frame, tkfont.Font(root=tk_root, family="Courier New", size=10)
    frame.destroy()


def test_each_column_shows_the_rows_colours_as_its_shade_says(table_parts):
    """Stripes from a gray first row; a row's own colour only in the shaded columns; the
    plain ones stay white."""
    rows = [Row(("", "", "", "")), Row(("", "", "", "")), Row(("", "", "", ""), CURRENT),
            Row(("", "", "", ""), CURRENT)]
    table = shaded_table(table_parts, rows)
    fills = [[cell_fill(table, place, k) for k in range(4)] for place in range(4)]
    assert fills == [[WHITE, STRIPE, STRIPE, STRIPE], [WHITE, WHITE, WHITE, WHITE],
                     [WHITE, STRIPE, CURRENT, CURRENT], [WHITE, WHITE, CURRENT, CURRENT]]


def test_a_highlight_is_raised_by_a_thin_crisp_edge(table_parts):
    """Lit at its top and left, shaded at its bottom and right, inside the grid lines, across
    the columns that show it; they go with the highlight."""
    rows = [Row(("", "", "", "")), Row(("", "", "", ""), CURRENT), Row(("", "", "", ""))]
    table = shaded_table(table_parts, rows)
    ring, height = table._ring, table.row_height
    lit, shaded = edges(CURRENT)
    drawn = [(table.body.itemcget(item, "fill").upper(), table.body.coords(item))
             for item in table._raised[1]]
    x0, x1, y0, y1 = 120, 240 - ring, height, 2 * height - ring
    assert drawn == [(lit, [x0, y0, x1, y0 + ring]), (lit, [x0, y0, x0 + ring, y1]),
                     (shaded, [x0, y1 - ring, x1, y1]), (shaded, [x1 - ring, y0, x1, y1])]
    rows[1] = Row(("", "", "", ""))
    table.refresh()
    assert not table._raised and not table.body.find_withtag("edge")


def test_a_changed_cell_has_its_own_raised_edge(table_parts):
    rows = [Row(("", "", "", ""), "", {"c": WORD_CHANGED, "d": WORD_CHANGED})]
    table = shaded_table(table_parts, rows)
    assert len(table._raised[0]) == 8                   # four sides of each of the two cells
    assert cell_fill(table, 0, 2) == cell_fill(table, 0, 3) == WORD_CHANGED


def test_the_edges_of_a_highlight_keep_its_hue():
    assert edges("#FFFF99") == ("#FFFFDB", "#8C8C54")
    assert edges("#99CCFF") == ("#DBEDFF", "#54708C")


def luminance(colour):
    values = [int(colour[k:k + 2], 16) / 255 for k in (1, 3, 5)]
    r, g, b = ((v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4) for v in values)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_the_highlights_keep_black_text_easy_to_read():
    """The retro lime green of a changed register above all: contrast 15 to 1 at least."""
    for colour in (REGISTER_CHANGED, CURRENT, FAILED, WORD_CHANGED):
        assert (luminance(colour) + 0.05) / 0.05 >= 10, colour
    assert REGISTER_CHANGED == "#B5F03C"
    assert (luminance(REGISTER_CHANGED) + 0.05) / 0.05 >= 15


def test_the_text_segment_shades_its_columns_as_they_are_meant(app):
    columns = {column.id: column.shade for column in app.execute.text_segment.table.columns}
    assert columns == {"bkpt": PLAIN, "address": PLAIN, "code": STRIPED, "basic": SHADED,
                       "source": SHADED}
    columns = {column.id: column.shade for column in app.execute.data_segment.table.columns}
    assert columns.pop("address") == PLAIN and set(columns.values()) == {SHADED}
    assert {column.shade for column in app.execute.labels.table.columns} == {PLAIN}
    assert {column.shade for column in app.registers.table.columns} == {SHADED}


def test_the_rows_of_a_table_without_stripes_are_white_and_plain_rows_have_no_edges(table_parts):
    """The BHT Simulator's table, and the Memory Map's entries, white or gray by entry."""
    frame, font = table_parts
    table = Table(frame, [Column("a", "A", 60)], font, stripes=False)
    table.fit(table.row_height * 4)
    table.fill(60)
    rows = [Row(("",)), Row(("",)), Row(("",), STRIPE), Row(("",), WHITE)]
    table.set_rows(len(rows), rows.__getitem__)
    assert [cell_fill(table, place, 0) for place in range(4)] == [WHITE, WHITE, STRIPE, WHITE]
    assert not table._raised


def test_tables_have_a_face_below_their_rows_and_at_least_the_usual_sizes(app):
    for table in tables(app):
        assert table.body.cget("background") == style.FACE
        assert table.row_height >= px(app.root, 16)
        assert int(table.header.cget("height")) >= px(app.root, 20)


def test_label_names_are_in_the_plain_interface_font(app):
    labels = app.execute.labels
    column = labels.table.columns[0]
    assert column.font is labels.name_font
    assert labels.name_font.actual("family") == tkfont.nametofont(
        "TkTextFont", root=app.root).actual("family")
    assert labels.table.columns[1].font is None         # the addresses: the pane font


# The toolbar, status line and messages -----------------------------------------------------

def test_the_toolbar_has_a_grip_square_buttons_and_tick_marks(app):
    root = app.root
    assert app.grip.master is app.buttons["new"].master
    assert app.grip.master.pack_slaves()[0] is app.grip
    assert int(app.grip.cget("width")) == px(root, 16)
    assert int(app.ticks.cget("width")) == px(root, 200)
    assert len(app.ticks.find_all()) == 9
    assert str(app.speed_label.cget("anchor")) == "center"
    button = app.buttons["new"]
    assert (button.winfo_reqwidth(), button.winfo_reqheight()) == (px(root, 34), px(root, 34))


def rows_of(canvas):
    """The fill colours of a canvas's rectangles, in drawing order."""
    return [canvas.itemcget(item, "fill").upper() for item in canvas.find_all()
            if canvas.type(item) == "rectangle"]


def test_the_toolbar_strip_is_a_gradient_behind_its_buttons(app):
    strip, height = app.grip.master, px(app.root, style.TOOL_BUTTON)
    assert strip.winfo_class() == "Canvas"
    assert rows_of(strip) == style.gradient(*style.TOOL_STRIP, height)
    assert rows_of(strip)[0] == "#FFFFFF" and rows_of(strip)[-1] == "#DCDCDC"
    assert {strip.type(item) for item in strip.find_all()} == {"rectangle"}     # no picture


def test_the_grip_continues_the_gradient_under_its_dots(app):
    strip, grip = app.grip.master, app.grip
    assert rows_of(grip) == rows_of(strip)
    kinds = [grip.type(item) for item in grip.find_all()]
    assert kinds.index("polygon") == len(rows_of(grip))     # the dots lie on the rows


def test_the_gaps_between_the_groups_show_the_gradient(app):
    # Nothing stands in a gap: the first button of a group keeps its distance by itself.
    strip, gap = app.grip.master, px(app.root, 10)
    assert strip.pack_slaves() == [app.grip, *app.buttons.values()]
    starts = {name for name, button in app.buttons.items()
              if button.pack_info()["padx"] == (gap, 0)}
    assert starts == {"undo", "cut", "find", "assemble", "go", "help"}
    others = set(app.buttons) - starts
    assert all(app.buttons[name].pack_info()["padx"] == 0 for name in others)


def test_only_the_strip_of_the_toolbar_has_the_gradient(app):
    toolbar = app.grip.master.master
    assert str(ttk.Style(app.root).lookup(toolbar.winfo_class(), "background")).upper() == style.FACE
    speed = app.speed.master
    assert speed.master is toolbar and speed.winfo_class() == "TFrame"
    assert str(app.ticks.cget("background")).upper() == style.FACE


def test_the_gradient_keeps_the_toolbar_where_it_was(make_mapped_app):
    app = make_mapped_app()
    root = app.root
    root.update()
    strip, buttons = app.grip.master, app.buttons
    toolbar = strip.master
    assert toolbar.winfo_height() == px(root, 53)
    assert strip.winfo_rooty() - root.winfo_rooty() == px(root, 31)
    assert (strip.winfo_x(), strip.winfo_height()) == (px(root, 5), px(root, 34))
    assert (app.grip.winfo_x(), app.grip.winfo_y()) == (0, 0)
    assert (app.grip.winfo_width(), app.grip.winfo_height()) == (px(root, 16), px(root, 34))
    x = px(root, 16)
    for name, button in buttons.items():
        if name in ("undo", "cut", "find", "assemble", "go", "help"):
            x += px(root, 10)
        assert (button.winfo_x(), button.winfo_y()) == (x, 0)
        assert (button.winfo_width(), button.winfo_height()) == (px(root, 34), px(root, 34))
        x += px(root, 34)
    assert strip.winfo_width() == x
    line = app.toolbar_line
    assert (line.winfo_y(), line.winfo_height()) == (
        strip.winfo_y() + strip.winfo_height() + px(root, 1), px(root, 1))
    assert (line.winfo_x(), line.winfo_width()) == (strip.winfo_x(), strip.winfo_width())


def test_the_status_line_is_in_the_tab_on_top_and_gone_without_a_file(app):
    editor = app.editor
    assert not editor.status.winfo_manager()
    first = app.cmd_new() or editor.current
    assert editor.status.place_info()["in"] is first
    second = app.cmd_new() or editor.current
    assert editor.status.place_info()["in"] is second
    assert editor.status.place_info()["anchor"] == "sw"
    assert int(editor.status.cget("height")) == px(app.root, 24)
    editor.select(first)
    editor._selected()
    assert editor.status.place_info()["in"] is first
    assert str(editor.position.cget("style")) == ""     # no panel around it
    app.run("close_all")
    assert not editor.tabs and not editor.status.winfo_manager()
    app.cmd_new()
    assert editor.status.place_info()["in"] is editor.current


def long_file(tmp_path, name):
    path = tmp_path / name
    path.write_text("".join(f"        NOP     @ line {n}\n" for n in range(1, 401)),
                    encoding="utf-8")
    return path


def test_a_file_tab_keeps_its_height_whichever_tab_has_the_status_line(make_app, tmp_path,
                                                                        monkeypatch):
    """A text that changes height with the status line moves its view: the line with the
    cursor, or the one a message led to, would end up just below it."""
    fixed_screen(monkeypatch)
    app = make_app()
    assert lay_out(app.root)
    first = app.open_path(long_file(tmp_path, "first.s"))
    second = app.open_path(long_file(tmp_path, "second.s"))
    assert lay_out(app.root)
    editor = app.editor
    text = second.text
    text.mark_set("insert", "401.0 - 1 lines")
    text.see("insert")
    assert pump(app.root)
    height = text.winfo_height()
    assert text.dlineinfo("insert") is not None
    editor.select(first)
    assert pump(app.root)
    assert text.winfo_height() == first.text.winfo_height() == height
    editor.select(second)
    assert pump(app.root)
    assert text.winfo_height() == height
    assert text.dlineinfo("insert") is not None


def test_the_line_a_message_leads_to_is_in_view(make_app, tmp_path, monkeypatch):
    fixed_screen(monkeypatch)
    app = make_app()
    assert lay_out(app.root)
    first = app.open_path(long_file(tmp_path, "first.s"))
    second = app.open_path(long_file(tmp_path, "second.s"))
    assert lay_out(app.root)
    assert pump(app.root)
    last = int(second.text.index("@0,%d" % (second.text.winfo_height() - 1)).split(".")[0])
    app.editor.select(first)
    assert pump(app.root)
    for line in range(last + 1, last + 8):
        app.editor.select(first)
        assert pump(app.root)
        app.editor.select(second)
        second.select_line(line)
        assert pump(app.root)
        assert second.text.dlineinfo(f"{line}.0") is not None, line


def test_every_page_has_the_band_of_the_tab_colour(app):
    band = tuple(str(side) for side in style.page_padding(app.root))
    for notebook in (app.views, app.side, app.messages):
        for tab in notebook.tabs():
            padding = notebook.tab(tab, "padding")
            words = padding if isinstance(padding, (tuple, list)) else str(padding).split()
            assert tuple(str(word) for word in words) == band


def test_the_editor_and_message_panes_space_their_lines(app):
    app.cmd_new()
    for text, font in ((app.editor.current.text, app.editor_font),
                       (app.messages.messages, app.pane_font),
                       (app.messages.run_io, app.pane_font)):
        above, below = int(text.cget("spacing1")), int(text.cget("spacing3"))
        pixels = text.winfo_fpixels(f"{font.actual('size')}p")
        assert font.metrics("linespace") + above + below == round(pixels * 17 / 12)
