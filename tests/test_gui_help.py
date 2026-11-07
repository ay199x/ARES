# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Help window, its instruction lists, the About box and the splash screen."""

import sys
import tkinter as tk
import tkinter.font

import pytest

from ares import APP_FULL_NAME, __version__, credits, helptext, instructions
from ares.gui import about, helpwindow, icons, splash, start, tools
from ares.gui.style import TAB
from ares.gui.helpwindow import (COMMON, KEY_BACKGROUND, MEMORY_MAP, ROW_SHADE, HelpWindow,
                                 InstructionList, KeyPage, Page, ToolsPage)
from ares.gui.style import NAVY, WINDOW
from ares.gui.widgets import LONG_LINE, px
from conftest import ROOT, lay_out, native, press_key


def words(page):
    return " ".join(page.plain_text().split())


# Help ---------------------------------------------------------------------------------------

def test_the_help_commands_are_available(app):
    assert app.is_enabled("help") and app.is_enabled("about")
    assert app.buttons["help"].instate(["!disabled"])
    menu, index = app._menu_items["help"]
    assert menu.entrycget(index, "state") == "normal"


def test_the_toolbar_button_opens_the_help(app, hidden_windows):
    app.buttons["help"].invoke()
    assert hidden_windows.shows(app.help_window.window)


def test_the_menu_opens_the_help_once(app):
    app.run("help")
    window = app.help_window
    app.run("help")
    assert app.help_window is window


def test_a_closed_help_opens_again(app):
    app.run("help")
    app.help_window.close()
    app.run("help")
    assert app.help_window.window.winfo_exists()


TEXT_PAGES = [title for top, inside in helptext.TABS for title in inside or (top,)
              if title not in ("Basic Instructions", "Extended (pseudo) Instructions", "Tools")]


def titles(book):
    return [book.tab(tab, "text") for tab in book.tabs()]


def test_the_window_has_the_tabs_in_order(app):
    app.run("help")
    help_window = app.help_window
    assert titles(help_window.tabs) == ["ARM", "ARES", "License", "Acknowledgements"]
    for top, inside in helptext.TABS:
        if inside:
            assert titles(help_window.inner[top]) == list(inside)
    assert help_window.current() == "Basic Instructions"


def test_every_notebook_comes_from_the_one_helper(app, monkeypatch):
    made = []
    original = helpwindow.notebook
    monkeypatch.setattr(helpwindow, "notebook",
                        lambda master, *more: made.append(original(master, *more)) or made[-1])
    app.run("help")
    assert made == app.help_window.notebooks and len(made) == 3


def test_the_title_has_the_version(app):
    app.run("help")
    assert app.help_window.window.title() == f"ARES {__version__} Help" == "ARES 1.0 Help"


def test_a_page_is_filled_the_first_time_it_is_shown(app):
    app.run("help")
    help_window = app.help_window
    assert help_window.pages["Basic Instructions"].filled
    assert list(help_window.pages) == ["Basic Instructions"]
    help_window.select("Registers")
    assert help_window.pages["Registers"].filled
    assert "S2 and S3 are the two halves of D1" in words(help_window.pages["Registers"])
    assert "Intro" not in help_window.pages


def test_opening_the_help_imports_no_tool():
    # The tools' modules wait for the Tools tab: ares.gui.tools.window_class() imports them.
    assert "window_class" not in HelpWindow.__init__.__code__.co_names


@pytest.mark.parametrize("title", TEXT_PAGES)
def test_every_page_shows_text_and_a_scroll_bar(app, title):
    app.run("help")
    help_window = app.help_window
    help_window.select(title)
    page = help_window.pages[title]
    assert isinstance(page, Page) and len(page.plain_text()) > 200
    assert str(page.text.cget("yscrollcommand"))


def test_the_system_calls_table_is_shown(app):
    app.run("help")
    app.help_window.select("Syscalls")
    text = app.help_window.pages["Syscalls"].plain_text()
    assert "print integer" in text and "message dialog, string" in text


def test_the_shortcuts_are_shown(app):
    app.run("help")
    app.help_window.select("Keyboard shortcuts")
    text = words(app.help_window.pages["Keyboard shortcuts"])
    assert "F5 Run > Go" in text and "Ctrl+S File > Save" in text


def test_the_intro_shows_the_story_and_the_credits(app):
    app.run("help")
    app.help_window.select("Intro")
    page = app.help_window.pages["Intro"]
    text = words(page)
    assert text.startswith("ARES - ARM Educational Simulator Version 1.0")
    for part in (*credits.MOTIVATION, credits.FUN_FACT, *credits.CREDITS):
        assert part in text
    assert page.text.tag_ranges(helptext.TITLE)


def test_the_acknowledgements_show_the_credits(app):
    app.run("help")
    app.help_window.select("Acknowledgements")
    text = words(app.help_window.pages["Acknowledgements"])
    for credit in credits.CREDITS:
        assert credit in text


def test_the_license_tab_shows_both_files_in_the_font_of_programs(app):
    app.run("help")
    app.help_window.select("License")
    page = app.help_window.pages["License"]
    text = page.plain_text()
    assert text.index("open source") < text.index("GNU GENERAL PUBLIC LICENSE")
    assert text.index("GNU GENERAL PUBLIC LICENSE") < text.index("Third-party notices")
    assert about.read_document("THIRD_PARTY_NOTICES.txt").strip() in text
    assert about.read_document("LICENSE").strip() in text
    first, last = page.text.tag_ranges(helptext.DOCUMENT)[:2]
    assert "GNU GENERAL" in page.text.get(first, last)
    assert page.text.tag_cget(helptext.DOCUMENT, "font") == str(app.help_window.fonts.code)


def test_the_texts_a_package_holds_follow_the_notices(app, monkeypatch, tmp_path):
    folder = tmp_path / "licenses"
    folder.mkdir()
    (folder / "GPL-3.0.txt").write_text("the third version", encoding="utf-8")
    (folder / "Python-LICENSE.txt").write_text("the licence of Python", encoding="utf-8")
    (folder / "Apache-2.0.txt").write_text("the Apache text", encoding="utf-8")
    (folder / "Python-parts.txt").write_text("the parts of Python", encoding="utf-8")
    (tmp_path / "LICENSE").write_text("the licence", encoding="utf-8")
    (tmp_path / "THIRD_PARTY_NOTICES.txt").write_text("the notices", encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    app.run("help")
    app.help_window.select("License")
    text = app.help_window.pages["License"].plain_text()
    assert (text.index("the notices") < text.index("version 3 (GNU binutils)")
            < text.index("the third version") < text.index("the Apache text")
            < text.index("Python's licence") < text.index("the licence of Python")
            < text.index("the parts of Python"))


def test_without_a_package_only_the_two_files_are_shown(app):
    app.run("help")
    app.help_window.select("License")
    assert "(GNU binutils)" not in app.help_window.pages["License"].plain_text()


def test_a_missing_document_says_so_in_its_place(app, monkeypatch):
    monkeypatch.setattr(helpwindow, "LICENSE_FILE", "no such file.txt")
    app.run("help")
    app.help_window.select("License")
    assert "no such file.txt could not be read" in words(app.help_window.pages["License"])


def test_the_key_stands_on_light_green_over_the_tabs_of_the_arm_tab(app):
    app.run("help")
    help_window = app.help_window
    key = help_window.key
    assert isinstance(key, KeyPage) and KEY_BACKGROUND == "#CCFF99"
    assert key.text.cget("background") == KEY_BACKGROUND
    assert key.text.tag_cget("shaded", "background") == KEY_BACKGROUND
    assert "Operand key for the example lines" in key.plain_text()
    assert str(key.text.cget("yscrollcommand"))
    assert list(help_window.split.panes()) == [str(key), str(help_window.inner["ARM"])]


def test_the_key_is_centred_with_its_table_as_one_block(app):
    app.run("help")
    text = app.help_window.key.text
    assert text.tag_cget(helptext.HEADING, "justify") == "center"
    assert text.tag_cget(helptext.TABLE, "justify") == "center"
    rows = helptext.table_lines(helptext.parse(helptext.operand_key())[1].rows)
    first = text.tag_ranges(helptext.TABLE)[0]
    widths = {len(text.get(f"{first} + {number} lines linestart", f"{first} + {number} lines lineend"))
              for number in range(sum(len(lines) for lines in rows))}
    assert len(widths) == 1


def test_a_page_uses_its_tags(app):
    app.run("help")
    help_window = app.help_window
    help_window.select("Intro")
    text = help_window.pages["Intro"].text
    assert text.tag_ranges(helptext.HEADING) and text.tag_ranges(helptext.CODE)
    assert text.tag_ranges(helptext.BULLET) and text.tag_ranges("inline")
    help_window.select("Directives")
    text = help_window.pages["Directives"].text
    assert text.tag_ranges(helptext.TABLE) and text.tag_ranges("table_heading")
    assert text.tag_ranges("shaded")


def test_pages_cannot_be_changed(app):
    app.run("help")
    app.help_window.select("Intro")
    text = app.help_window.pages["Intro"].text
    before = text.get("1.0", "end")
    text.insert("1.0", "x")
    text.delete("1.0", "end")
    assert text.get("1.0", "end") == before


def test_the_tools_tab_lists_every_tool(app):
    app.run("help")
    help_window = app.help_window
    help_window.select("Tools")
    page = help_window.pages["Tools"]
    assert isinstance(page, ToolsPage)
    names = list(page.list.get(0, "end"))
    assert names[0] == COMMON and names[-1] == MEMORY_MAP
    assert names[1:-1] == [label.replace("&", "") for label in
                           (tool.label for tool in tools.TOOLS)]
    assert "Connect to ARM" in words(page.page)


@pytest.mark.parametrize("tool", tools.TOOLS, ids=lambda tool: tool.command)
def test_a_tool_page_is_the_tools_own_text(app, tool):
    app.run("help")
    help_window = app.help_window
    help_window.select("Tools")
    page = help_window.pages["Tools"]
    page.select(tool.label.replace("&", ""))
    expected = " ".join(tools.window_class(tool.command).HELP.split())
    assert words(page.page) == expected


def test_choosing_in_the_list_shows_the_page(app):
    app.run("help")
    help_window = app.help_window
    help_window.select("Tools")
    page = help_window.pages["Tools"]
    page.list.selection_clear(0, "end")
    page.list.selection_set(len(page.entries) - 1)
    native(page.list)
    page.list.event_generate("<<ListboxSelect>>")
    page.update()
    assert "SP now:" in words(page.page)


def test_escape_closes_the_help(app):
    app.run("help")
    window = app.help_window.window
    press_key(window, "<Escape>")
    assert app.help_window.window is None and not window.winfo_exists()


def test_the_close_button_closes_the_help(app):
    app.run("help")
    app.help_window.close_button.invoke()
    assert app.help_window.window is None


def test_return_closes_the_help_from_a_page(app):
    app.run("help")
    app.help_window.select("Registers")
    press_key(app.help_window.pages["Registers"].text, "<Return>")
    assert app.help_window.window is None


def test_a_page_shows_no_text_cursor(app):
    app.run("help")
    app.help_window.select("Intro")
    assert int(str(app.help_window.pages["Intro"].text.cget("insertwidth"))) == 0


def test_the_page_on_top_asks_for_the_keyboard_focus(app, hidden_windows):
    app.run("help")
    help_window = app.help_window
    assert hidden_windows.focus is help_window.pages["Basic Instructions"].list
    help_window.select("Registers")
    help_window.focus_page()
    assert hidden_windows.focus is help_window.pages["Registers"].text
    help_window.select("Tools")
    help_window.focus_page()
    assert hidden_windows.focus is help_window.pages["Tools"].list


@pytest.mark.parametrize("title, step, after", [
    ("Basic Instructions", 1, "Extended (pseudo) Instructions"),
    ("Registers", 1, "Memory and devices"),
    ("Memory and devices", 1, "Basic Instructions"),
    ("Basic Instructions", -1, "Memory and devices"),
    ("Intro", 1, "IDE"),
    ("Limits", 1, "Intro"),
    ("Intro", -1, "Limits"),
    ("License", 1, "Acknowledgements"),
    ("Acknowledgements", 1, "ARM"),
    ("License", -1, "ARES"),
])
def test_ctrl_tab_goes_round_the_tabs_inside_the_top_tab(app, title, step, after):
    app.run("help")
    help_window = app.help_window
    help_window.select(title)
    sequence = "<Control-Key-Tab>" if step > 0 else "<Control-Shift-Key-Tab>"
    press_key(help_window.pages[title].focus_widget(), sequence)
    assert help_window.current() == after or help_window.top() == after


@pytest.mark.parametrize("sequence, start, after", [
    ("<Control-Key-Next>", "Registers", "ARES"), ("<Control-Key-Prior>", "Registers", "Acknowledgements"),
    ("<Control-Key-Next>", "Acknowledgements", "ARM"), ("<Control-Key-Next>", "Limits", "License")])
def test_ctrl_page_down_goes_round_the_top_tabs(app, sequence, start, after):
    app.run("help")
    help_window = app.help_window
    help_window.select(start)
    press_key(help_window.pages[start].focus_widget(), sequence)
    assert help_window.top() == after


def test_a_top_tab_keeps_the_tab_inside_it(app):
    app.run("help")
    help_window = app.help_window
    help_window.select("Registers")
    press_key(help_window.pages["Registers"].text, "<Control-Key-Next>")
    press_key(help_window.pages["Intro"].text, "<Control-Key-Prior>")
    assert help_window.current() == "Registers"


@pytest.mark.parametrize("where", ["list", "text", "tools", "tool text", "key", "close"])
def test_ctrl_tab_works_at_the_first_press_from_anywhere(app, where):
    app.run("help")
    help_window = app.help_window
    if where in ("tools", "tool text"):
        help_window.select("Tools")
    elif where == "text":
        help_window.select("Registers")
    widget = {"list": lambda: help_window.pages["Basic Instructions"].list,
              "text": lambda: help_window.pages["Registers"].text,
              "tools": lambda: help_window.pages["Tools"].list,
              "tool text": lambda: help_window.pages["Tools"].page.text,
              "key": lambda: help_window.key.text,
              "close": lambda: help_window.close_button}[where]()
    first = help_window.current()
    press_key(widget, "<Control-Key-Tab>")
    assert help_window.current() != first
    press_key(widget, "<Control-Shift-Key-Tab>")
    assert help_window.current() == first


@pytest.mark.parametrize("key", ["<Key-Next>", "<Key-End>"])
def test_the_list_of_tools_scrolls_the_page_beside_it(app, key):
    app.run("help")
    help_window = app.help_window
    help_window.select("Tools")
    page = help_window.pages["Tools"]
    page.select("Dynamic Instruction Counter")
    native(help_window.window)
    lay_out(help_window.window)
    press_key(page.list, key)
    lay_out(help_window.window)
    assert page.page.text.yview()[0] > 0
    assert page.list.get(page.list.curselection()[0]) == "Dynamic Instruction Counter"


@pytest.fixture
def laid_out_page(app):
    """The first page of a Help window, with a size and its lines laid out."""
    app.run("help")
    window = app.help_window.window
    app.help_window.select("Intro")
    native(window)
    lay_out(window)
    return app.help_window.pages["Intro"]


@pytest.mark.parametrize("key", ["<Key-Down>", "<Key-Next>", "<Key-End>"])
def test_the_keys_scroll_a_page(laid_out_page, key):
    text = laid_out_page.text
    assert text.yview()[0] == 0 and text.yview()[1] < 1
    press_key(text, key)
    lay_out(text)
    assert text.yview()[0] > 0


class Key:
    """What a key event tells Page._key."""

    def __init__(self, keysym, char="", state=0):
        self.keysym, self.char, self.state = keysym, char, state


@pytest.mark.parametrize("key", [Key("space", " "), Key("a", "a"), Key("A", "A", 1), Key("Left"),
                                 Key("Right"), Key("BackSpace", "\x08"), Key("Delete", "\x7f")])
def test_a_key_that_types_or_moves_the_cursor_leaves_the_view(laid_out_page, key):
    assert laid_out_page._key(key) == "break"


@pytest.mark.parametrize("key", [Key("c", "\x03", 4), Key("Escape", "\x1b"), Key("Return", "\r"),
                                 Key("Tab", "\t"), Key("Shift_L")])
def test_the_other_keys_go_on_to_their_bindings(laid_out_page, key):
    assert laid_out_page._key(key) is None


def test_a_click_on_the_tab_on_top_leaves_the_focus_in_the_page(app, hidden_windows):
    app.run("help")
    help_window = app.help_window
    hidden_windows.focus = None
    press_key(help_window.tabs, "<<TabClicked>>")
    assert hidden_windows.focus is help_window.pages["Basic Instructions"].list


@pytest.mark.parametrize("room, height", [(5000, helpwindow.SIZE[1]), (500, 500 - 50), (200, 320)])
def test_the_window_opens_no_taller_than_the_work_area(app, monkeypatch, room, height):
    monkeypatch.setattr(helpwindow, "screen_area", lambda *args: (0, 0, 2000, room))
    monkeypatch.setattr(helpwindow, "frame_of", lambda window: (0, 0, 800, 600, 10, 40))
    monkeypatch.setattr(helpwindow, "px", lambda widget, size: size)
    app.run("help")
    assert app.help_window.first_height(app.root) == height


def test_up_and_home_go_back(laid_out_page):
    text = laid_out_page.text
    press_key(text, "<Key-Next>")
    lay_out(text)
    place = text.yview()[0]
    press_key(text, "<Key-Up>")
    lay_out(text)
    assert 0 < text.yview()[0] < place
    press_key(text, "<Key-Home>")
    lay_out(text)
    assert text.yview()[0] == 0


def test_the_help_window_is_not_tied_to_the_main_window(app):
    # It stays beside the main window while the program is edited, in the taskbar and with its
    # icon in its own title bar.
    app.run("help")
    assert not str(app.help_window.window.wm_transient())


def test_at_its_smallest_the_window_shows_all_its_tabs_and_whole_tables(app):
    app.run("help")
    help_window = app.help_window
    width = help_window.window.minsize()[0]
    assert width >= max(book.winfo_reqwidth() for book in help_window.notebooks)
    table = help_window.fonts.code.measure("0") * helptext.TABLE_WIDTH
    assert width >= table + 2 * px(app.root, helpwindow.INSET)


# The instruction lists ----------------------------------------------------------------------

@pytest.fixture
def rows(app):
    """The list of Basic Instructions, with its rows."""
    app.run("help")
    return app.help_window.pages["Basic Instructions"]


def row_index(page, example):
    return next(i for i, (row, group) in enumerate(page.shown) if row.example == example)


def stripes_are_right(page):
    colours = [str(page.list.itemcget(i, "background")) for i in range(page.list.size())]
    return colours == [ROW_SHADE if i % 2 == 0 else WINDOW for i in range(page.list.size())]


def test_the_lists_are_in_the_font_of_programs(app, rows):
    assert isinstance(rows, InstructionList)
    assert str(rows.list.cget("font")) == str(app.help_window.fonts.code)


def test_the_list_shows_every_row_with_its_groups_closed(rows):
    assert rows.list.size() == len(instructions.BASIC)
    assert rows.list.get(row_index(rows, "MOV R1, R2")).startswith("+ MOV R1, R2 ")
    assert rows.list.get(row_index(rows, "CLREX")).startswith("  CLREX ")
    assert all(group is None for row, group in rows.shown)


def test_the_rows_are_sorted_like_the_table(rows):
    assert [row for row, group in rows.shown] == list(instructions.BASIC)


def test_the_rows_alternate_white_and_the_face_colour(rows):
    assert ROW_SHADE == "#EEEEEE" and stripes_are_right(rows)


def test_the_extended_list_is_a_list_too(app):
    app.run("help")
    app.help_window.select("Extended (pseudo) Instructions")
    page = app.help_window.pages["Extended (pseudo) Instructions"]
    assert page.list.size() == len(instructions.EXTENDED)
    assert "LDR R1, =100000" in page.plain_text()


def test_right_opens_a_group_and_left_closes_it(rows):
    index = row_index(rows, "MOV R1, R2")
    size = rows.list.size()
    rows._go_to(index)
    press_key(rows.list, "<Key-Right>")
    group = instructions.variants(rows.rows[index])
    assert rows.list.size() == size + len(group)
    assert rows.list.get(index).startswith("- MOV R1, R2 ")
    assert rows.list.get(index + 1).startswith("    MOVEQ R1, R2 ")
    assert rows.list.get(index + len(group)).startswith("    MOVS R1, R2 ")
    assert stripes_are_right(rows)
    press_key(rows.list, "<Key-Left>")
    assert rows.list.size() == size
    assert rows.list.get(index).startswith("+ MOV R1, R2 ")
    assert stripes_are_right(rows)


def test_right_on_an_open_group_or_a_row_without_one_changes_nothing(rows):
    index = row_index(rows, "MOV R1, R2")
    rows.open_group(index)
    size = rows.list.size()
    rows._go_to(index)
    press_key(rows.list, "<Key-Right>")
    rows._go_to(row_index(rows, "CLREX"))
    press_key(rows.list, "<Key-Right>")
    assert rows.list.size() == size


def test_left_in_a_group_closes_it_and_goes_to_its_row(rows):
    index = row_index(rows, "MOV R1, R2")
    size = rows.list.size()
    rows.open_group(index)
    rows._go_to(index + 3)
    press_key(rows.list, "<Key-Left>")
    assert rows.list.size() == size
    assert rows.active() == index and rows.list.curselection() == (index,)


def test_a_group_of_a_later_row_opens_at_its_own_place(rows):
    rows.open_group(row_index(rows, "ADD R1, R2, R3"))
    index = row_index(rows, "MOV R1, R2")
    rows.open_group(index)
    assert rows.list.get(index + 1).startswith("    MOVEQ R1, R2 ")
    rows.close_group(row_index(rows, "ADD R1, R2, R3"))
    index = row_index(rows, "MOV R1, R2")
    assert rows.list.get(index + 1).startswith("    MOVEQ R1, R2 ")
    assert [row for row, group in rows.shown if group is None] == list(instructions.BASIC)
    assert stripes_are_right(rows)


def test_home_and_end_go_to_the_ends_of_the_list(rows):
    press_key(rows.list, "<Key-End>")
    assert rows.active() == rows.list.size() - 1
    press_key(rows.list, "<Key-Home>")
    assert rows.active() == 0


@pytest.mark.parametrize("key", ["<Key-Right>", "<Key-Left>", "<Key-Prior>", "<Key-Next>",
                                 "<Key-Home>", "<Key-End>"])
def test_the_keys_of_a_list_stop_at_the_list(rows, key):
    # Tk's Listbox class would scroll sideways at Left, Right, Home and End.
    assert "Listbox" not in press_key(rows.list, key)


def test_return_closes_the_help_from_a_list(app, rows):
    press_key(rows.list, "<Return>")
    assert app.help_window.window is None


@pytest.fixture
def mapped_list(mapped_area):
    """The Basic list in a mapped window with its size, as on the screen."""
    from ares.gui.helpwindow import Fonts
    from tkinter import font as tkfont
    inside = mapped_area(780, 340)
    code = tkfont.Font(root=inside, family="Courier New", size=9)
    page = InstructionList(inside, Fonts(inside, code), instructions.BASIC)
    page.pack(fill="both", expand=True)
    page.fill()
    inside.update()
    return page


def click(page, index):
    x, y, width, height = page.list.bbox(index)
    page.list.event_generate("<Button-1>", x=x + 5, y=y + height // 2)
    page.list.event_generate("<ButtonRelease-1>", x=x + 5, y=y + height // 2)
    page.update()


def test_a_row_of_a_list_is_as_high_as_a_line_of_the_editor(mapped_list):
    page = mapped_list
    font = tk.font.Font(root=page, font=page.list.cget("font"))
    line = font.metrics("linespace") + sum(helpwindow.line_spacing(page, font))
    assert abs(page.list.bbox(1)[1] - page.list.bbox(0)[1] - line) <= 2


def test_a_click_on_a_row_opens_and_closes_its_group(mapped_list):
    page = mapped_list
    size = page.list.size()
    click(page, 1)
    assert page.list.size() > size and page.list.get(1).startswith("- ")
    assert page.list.curselection() == (1,)
    click(page, 1)
    assert page.list.size() == size and page.list.get(1).startswith("+ ")


def test_a_click_on_a_row_of_a_group_only_selects_it(mapped_list):
    page = mapped_list
    click(page, 1)
    size = page.list.size()
    click(page, 2)
    assert page.list.size() == size and page.list.curselection() == (2,)


def test_a_drag_from_row_to_row_opens_nothing(mapped_list):
    page = mapped_list
    size = page.list.size()
    x, y, width, height = page.list.bbox(1)
    page.list.event_generate("<Button-1>", x=x + 5, y=y + 2)
    page.list.event_generate("<ButtonRelease-1>", x=x + 5, y=y + 3 * height)
    page.update()
    assert page.list.size() == size


def test_a_click_under_the_last_row_opens_nothing(mapped_area):
    from ares.gui.helpwindow import Fonts
    from tkinter import font as tkfont
    inside = mapped_area(780, 340)
    code = tkfont.Font(root=inside, family="Courier New", size=9)
    page = InstructionList(inside, Fonts(inside, code), instructions.BASIC[:3])
    page.pack(fill="both", expand=True)
    page.fill()
    inside.update()
    y = page.list.winfo_height() - 2
    page.list.event_generate("<Button-1>", x=5, y=y)
    page.list.event_generate("<ButtonRelease-1>", x=5, y=y)
    page.update()
    assert page.list.size() == 3


def test_page_down_goes_a_page_on(mapped_list):
    page = mapped_list
    page._go_to(0)
    page.update()
    press_key(page.list, "<Key-Next>")
    page.update()
    shown = page.list.nearest(page.list.winfo_height()) - page.list.nearest(0)
    assert page.active() == shown > 5
    press_key(page.list, "<Key-Prior>")
    assert page.active() == 0


def test_a_group_opened_at_the_bottom_comes_into_view(mapped_list):
    page = mapped_list
    last = page.list.nearest(page.list.winfo_height())
    index = next(i for i in range(last, 0, -1) if instructions.variants(page.shown[i][0]))
    page.open_group(index)
    page.update()
    count = len(instructions.variants(page.shown[index][0]))
    assert page.list.bbox(index) and page.list.bbox(index + count)


def test_the_bar_under_a_list_shows_only_while_the_rows_are_too_wide(mapped_list):
    page = mapped_list
    page._scrolled_sideways("0.0", "1.0")
    assert not page.sideways.winfo_manager() or not page.sideways.grid_info()
    page._scrolled_sideways("0.0", "0.5")
    assert page.sideways.grid_info()


class MappedHelp(HelpWindow):
    """A Help window in a mapped window: it knows where the keyboard focus goes."""

    inside = None

    def new_window(self, master):
        return self.inside


@pytest.fixture
def mapped_help(mapped_area):
    inside = mapped_area(800, 600)
    MappedHelp.inside = inside
    window = MappedHelp(inside, tk.font.Font(root=inside, family="Courier New", size=9),
                        [], lambda label: label)
    inside.update()
    return window


def focus_of(help_window):
    help_window.window.update()
    return help_window.window.focus_get()


def test_the_list_has_the_real_focus_at_the_start(mapped_help):
    mapped_help.window.focus_force()
    mapped_help.focus_page()
    assert focus_of(mapped_help) is mapped_help.pages["Basic Instructions"].list


@pytest.mark.parametrize("title", ["Directives", "Intro", "Tools", "License", "Acknowledgements"])
def test_the_page_brought_to_the_top_gets_the_real_focus(mapped_help, title):
    mapped_help.window.focus_force()
    mapped_help.select(title)
    mapped_help.window.update()
    assert focus_of(mapped_help) is mapped_help.pages[title].focus_widget()


def test_a_click_on_an_inner_tab_leaves_the_focus_in_the_page(mapped_help):
    mapped_help.window.focus_force()
    book = mapped_help.inner["ARM"]
    book.update()
    x = next(x for x in range(5, book.winfo_width(), 5) if book.identify(x, 8) == "label"
             and book.index(f"@{x},8") == 3)
    book.event_generate("<Button-1>", x=x, y=8)
    book.event_generate("<ButtonRelease-1>", x=x, y=8)
    book.update()
    assert mapped_help.current() == "Syscalls"
    assert focus_of(mapped_help) is mapped_help.pages["Syscalls"].text
    assert mapped_help.pages["Syscalls"].filled


def test_the_key_takes_its_share_of_the_height(mapped_help):
    split = mapped_help.split
    mapped_help.window.update()
    share = split.sashpos(0) / mapped_help.window.winfo_height()
    assert abs(share - helpwindow.KEY_SHARE) < 0.03


def test_ctrl_tab_really_arrives_in_a_list(mapped_help):
    mapped_help.window.focus_force()
    mapped_help.focus_page()
    widget = focus_of(mapped_help)
    widget.event_generate("<Control-Key-Tab>")
    mapped_help.window.update()
    assert mapped_help.current() == "Extended (pseudo) Instructions"
    assert focus_of(mapped_help) is mapped_help.pages["Extended (pseudo) Instructions"].list


def test_a_tool_has_no_help_button(app):
    app.run("tool_bht")
    window = app.tool_windows["tool_bht"]
    assert [button.cget("text") for button in window.buttons] == [
        "Connect to ARM", "Reset", "Close"]


# A line too long to follow ------------------------------------------------------------------

def run_io(app):
    text = app.messages.run_io
    app.messages.select(1)
    native(app.root)
    lay_out(app.root)
    assert text.winfo_width() > 1
    return text


def test_run_io_follows_a_long_line_sideways(app):
    text = run_io(app)
    app.messages.write_output("X" * 2000)
    lay_out(app.root)
    assert text.xview()[1] == 1 and text.xview()[0] > 0


def test_a_very_long_line_is_shown_from_its_start(app):
    text = run_io(app)
    app.messages.write_output("line\n" * 100 + "X" * (LONG_LINE + 1))
    lay_out(app.root)
    assert text.xview()[0] == 0 and text.yview()[1] == 1


def test_a_line_growing_past_the_limit_goes_back_to_its_start(app):
    text = run_io(app)
    app.messages.write_output("X" * 3000)
    lay_out(app.root)
    app.messages.write_output("X" * LONG_LINE)
    lay_out(app.root)
    assert text.xview()[0] == 0


def test_the_next_line_is_followed_again(app):
    text = run_io(app)
    app.messages.write_output("X" * (LONG_LINE + 1) + "\n" + "Y" * 2000)
    lay_out(app.root)
    assert text.xview()[0] > 0


# About --------------------------------------------------------------------------------------

def test_the_about_box_says_what_ares_is(app):
    app.run("about")
    dialog = app.about_dialog
    assert dialog.window.title() == "About ARES"
    assert dialog.lines == (
        f"ARES {__version__}", APP_FULL_NAME, "", *credits.CREDITS, "", about.LICENCE,
        "Toolbar and menu icons drawn for ARES")
    assert "GPL-2.0-or-later" in about.LICENCE and "License tab" in about.LICENCE


def test_the_about_box_has_one_button(app):
    app.run("about")
    window = app.about_dialog.window

    def buttons(widget):
        found = [widget] if widget.winfo_class() == "TButton" else []
        for child in widget.winfo_children():
            found += buttons(child)
        return found
    assert buttons(window) == [app.about_dialog.ok_button]
    assert app.about_dialog.ok_button.cget("text") == "OK"


def test_the_about_box_is_a_message_box_with_ok_in_the_middle_under_the_text(mapped_area,
                                                                             monkeypatch):
    inside = mapped_area(700, 500)
    inside.withdraw = inside.transient = inside.resizable = lambda *args: None
    monkeypatch.setattr(about.tk, "Toplevel", lambda master: inside)
    dialog = about.AboutDialog(inside)
    inside.update()
    ok = dialog.ok_button
    body = ok.master
    middle = ok.winfo_x() + ok.winfo_width() / 2
    assert abs(middle - body.winfo_width() / 2) <= 1
    message = body.winfo_children()[0]
    assert ok.winfo_y() >= message.winfo_y() + message.winfo_height()
    helmet, lines = message.winfo_children()
    assert helmet.winfo_x() + helmet.winfo_width() < lines.winfo_x()
    assert helmet.winfo_y() == lines.winfo_y()
    assert not hasattr(about, "DocumentWindow")


def test_the_about_box_shows_the_helmet_at_twice_its_size(app):
    app.run("about")
    side = 32 * icons.design_factor(app.root, 2)
    assert app.about_dialog.helmet.width() == app.about_dialog.helmet.height() == side
    assert side % 32 == 0


def test_the_about_box_opens_once(app):
    app.run("about")
    dialog = app.about_dialog
    app.run("about")
    assert app.about_dialog is dialog


def test_ok_closes_the_about_box(app):
    app.run("about")
    app.about_dialog.ok_button.invoke()
    assert app.about_dialog.window is None


def test_return_presses_ok_and_escape_closes(app):
    app.run("about")
    press_key(app.about_dialog.window, "<Return>")
    assert app.about_dialog.window is None
    app.run("about")
    press_key(app.about_dialog.window, "<Escape>")
    assert app.about_dialog.window is None


def test_the_documents_are_found_next_to_the_program_or_in_a_package(monkeypatch, tmp_path):
    assert about.document_path("LICENSE") == ROOT / "LICENSE"
    assert about.document_path("LICENSE").is_file()
    assert about.document_path("THIRD_PARTY_NOTICES.txt").is_file()
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert about.document_path("LICENSE") == tmp_path / "LICENSE"


# The splash screen --------------------------------------------------------------------------

@pytest.fixture
def splash_screen(tk_root):
    screen = splash.Splash(tk_root)
    yield screen
    if screen.window.winfo_exists():
        screen.close()


def texts(canvas):
    return [canvas.itemcget(item, "text") for item in canvas.find_all()
            if canvas.type(item) == "text"]


def test_the_splash_shows_the_name_and_the_version(splash_screen):
    assert texts(splash_screen.canvas) == ["ARES", APP_FULL_NAME, f"Version {__version__}"]


def test_the_splash_has_no_title_bar_and_stays_in_front(splash_screen):
    window = splash_screen.window
    assert window.overrideredirect() and window.attributes("-topmost")


def test_the_splash_has_a_navy_panel_and_the_helmet_at_four_times_its_size(splash_screen):
    canvas = splash_screen.canvas
    fills = [canvas.itemcget(item, "fill") for item in canvas.find_all()
             if canvas.type(item) == "rectangle"]
    assert NAVY in fills
    assert splash_screen.helmet.width() == 32 * icons.design_factor(canvas, 4)


def test_everything_on_the_splash_fits_inside_it(splash_screen):
    canvas = splash_screen.canvas
    width, height = int(canvas.cget("width")), int(canvas.cget("height"))
    bar_top = splash_screen.blocks[0][1]
    for item in canvas.find_all():
        if canvas.type(item) in ("text", "image"):
            x0, y0, x1, y1 = canvas.bbox(item)
            assert x0 >= 0 and y0 >= 0 and x1 <= width and y1 <= bar_top


def test_the_bar_is_made_of_separate_blocks(splash_screen):
    blocks = splash_screen.blocks
    assert len(blocks) > 10
    assert all(right < following[0] for (_, _, right, _), following in zip(blocks, blocks[1:]))


def test_the_bar_fills_as_the_start_goes_on(splash_screen):
    count = len(splash_screen.blocks)
    splash_screen.advance(0.5)
    assert splash_screen.filled == round(count / 2)
    splash_screen.advance(0.25)                 # it never goes back
    assert splash_screen.filled == round(count / 2)
    splash_screen.advance(1)
    assert splash_screen.filled == count


def test_the_splash_is_centred(tk_root):
    x, y = splash.centred(tk_root, 100, 50)[1:].split("+")
    assert int(x) == (tk_root.winfo_screenwidth() - 100) // 2
    assert int(y) == (tk_root.winfo_screenheight() - 50) // 2


def test_a_file_that_cannot_be_opened_is_reported_after_the_splash_closed(monkeypatch, tmp_path):
    from ares.gui.app import App
    opened = []
    monkeypatch.setattr(App, "open_paths",
                        lambda self, paths: opened.append((list(paths),
                                                           list(Recorder.made.steps))))
    start_main(monkeypatch, tmp_path, ["missing.s"])
    assert opened[-1][0] == ["missing.s"] and opened[-1][1][-1] == "closed"


class Recorder:
    """A splash screen that writes down what happens to it."""

    made = None

    def __init__(self, root):
        Recorder.made = self
        self.steps = []

    def advance(self, share):
        self.steps.append(share)

    def close(self):
        self.steps.append("closed")


def start_main(monkeypatch, tmp_path, files=()):
    monkeypatch.setattr(start, "Splash", Recorder)
    from ares.gui import app as app_module
    original = app_module.App

    def app_with_settings(root, progress=None):
        return original(root, settings_path=tmp_path / "settings.json", progress=progress)
    monkeypatch.setattr(app_module, "App", app_with_settings)
    monkeypatch.setattr(tk.Tk, "mainloop", lambda self, n=0: self.destroy())
    return start.main(list(files))


def test_the_splash_goes_with_the_start_and_closes_last(monkeypatch, tmp_path):
    assert start_main(monkeypatch, tmp_path) == 0
    steps = Recorder.made.steps
    assert steps[-1] == "closed"
    shares = steps[:-1]
    assert shares == sorted(shares) and shares[-1] == 1 and len(shares) >= 5


def test_a_start_that_fails_closes_the_splash_first(monkeypatch, tmp_path):
    from ares.gui import app as app_module
    from tkinter import messagebox

    def fails(root, **options):
        raise OSError("no")
    shown = []
    monkeypatch.setattr(start, "Splash", Recorder)
    monkeypatch.setattr(app_module, "App", fails)
    monkeypatch.setattr(messagebox, "showerror",
                        lambda *args, **options: shown.append(list(Recorder.made.steps)))
    with pytest.raises(OSError):
        start.main([])
    assert shown and shown[0][-1] == "closed"


def test_the_design_sizes_are_scaled(tk_root, splash_screen):
    assert int(splash_screen.canvas.cget("width")) == px(tk_root, splash.WIDTH)
    assert helpwindow.SIZE[0] > 0


def painted(book):
    """The title of the tab that the strip paints as selected."""
    book.update()
    canvas = book.strip
    fills = [canvas.bbox(item) for item in canvas.find_all() if canvas.type(item) == "polygon"
             and str(canvas.itemcget(item, "fill")).upper() == TAB]
    x0, _, x1, _ = max(fills, key=lambda box: box[2] - box[0])      # not a cut-off corner
    return next(canvas.itemcget(item, "text") for item in canvas.find_all()
                if canvas.type(item) == "text" and x0 <= canvas.coords(item)[0] <= x1)


def test_the_strips_paint_the_tab_on_top(mapped_help):
    window = mapped_help
    window.select("Syscalls")
    assert painted(window.inner["ARM"]) == "Syscalls"
    window.select("License")
    assert painted(window.tabs) == "License"
    window.select("Limits")
    assert painted(window.tabs) == "ARES" and painted(window.inner["ARES"]) == "Limits"
    window._next_tab(1)
    assert painted(window.inner["ARES"]) == "Intro"


def test_ctrl_tab_on_the_top_tabs_goes_round_the_tabs_inside(mapped_help):
    window = mapped_help
    window.tabs.focus_force()
    window.window.update()
    window.tabs.event_generate("<Control-Key-Tab>")
    window.window.update()
    assert window.top() == "ARM" and window.current() == "Extended (pseudo) Instructions"
