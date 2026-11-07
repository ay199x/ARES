# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The pages of the Help window: their markup, and that what they say is true."""

import re

import pytest

from ares import credits, helptext, instructions
from ares.assembler import assemble
from ares.capitals import offences
from ares.gui import tools
from ares.gui.app import MENUS, SETTINGS_COMMANDS, SETTINGS_MENU
from ares.gui.menubar import access_letter
from ares.helptext import BULLET, CODE, DOCUMENT, HEADING, PARAGRAPH, TABLE, TITLE, Block, parse
from ares.machine import Machine
from ares.program import Program
from ares.syscalls import SERVICES


def label_of(text):
    return access_letter(text)[0]


def all_pages():
    pages = {title: text for title, text in helptext.PAGES.items()}
    pages["Operand key"] = helptext.operand_key()
    pages["Syscalls"] = helptext.system_calls_page()
    pages["Keyboard shortcuts"] = helptext.keyboard_page(MENUS, label_of)
    pages["Tools"] = helptext.TOOLS_INTRO + "\n" + helptext.MEMORY_MAP
    pages["Intro"] = helptext.intro_page()
    pages["Limits"] = helptext.limits_page()
    pages["Acknowledgements"] = helptext.acknowledgements_page()
    pages["License"] = helptext.LICENSE_WORDS
    return pages


def examples():
    """(page title, example) of every program example of the pages."""
    return [(title, block.text) for title, page in all_pages().items()
            for block in parse(page) if block.kind == CODE]


def tables(page):
    return [block.rows for block in parse(page) if block.kind == TABLE]


def test_the_tabs_and_their_pages():
    assert helptext.TABS == (
        ("ARM", ("Basic Instructions", "Extended (pseudo) Instructions", "Directives", "Syscalls",
                 "Registers", "Memory and devices")),
        ("ARES", ("Intro", "IDE", "Debugging", "Settings", "Tools", "Keyboard shortcuts",
                  "Limits")),
        ("License", ()),
        ("Acknowledgements", ()))


def test_every_tab_has_its_page():
    made = {"Basic Instructions", "Extended (pseudo) Instructions", "Tools"}
    titles = {title for top, inside in helptext.TABS for title in inside or (top,)}
    assert titles - made == set(all_pages()) - {"Operand key", "Tools"} | {"License"}


# The markup ---------------------------------------------------------------------------------

def test_parse_makes_the_blocks_of_a_page():
    page = """\
# The title

First line
second line.

## A heading

- one
  more
- two

    code
      indented

    more code

| A | B |
| 1 | two words |
"""
    assert parse(page) == [
        Block(TITLE, "The title"),
        Block(PARAGRAPH, "First line second line."),
        Block(HEADING, "A heading"),
        Block(BULLET, "one more"),
        Block(BULLET, "two"),
        Block(CODE, "code\n  indented\n\nmore code"),
        Block(TABLE, rows=(("A", "B"), ("1", "two words"))),
    ]


def test_spans_mark_the_parts_in_the_font_of_programs():
    assert helptext.spans("Use `MOV R0, #1` here") == [("Use ", False), ("MOV R0, #1", True),
                                                       (" here", False)]
    assert helptext.spans("`B .`") == [("B .", True)]
    assert helptext.plain("a `b` c") == "a b c"


def test_a_table_fits_and_wraps_inside_its_columns():
    rows = (("N", "Text"), ("1", "word " * 30))
    lines = helptext.table_lines(rows, limit=40)
    assert all(len(line) <= 40 for row in lines for line in row)
    assert len(lines[1]) > 1
    assert all(line.startswith(" " * 3) for line in lines[1][1:])


def test_a_column_is_not_narrower_than_its_longest_word():
    assert helptext.column_widths((("a" * 30, "b"), ("x", "y")), limit=10) == [30, 1]


def test_a_table_with_room_keeps_its_cells_on_one_line():
    assert helptext.table_lines((("A", "B"), ("one", "two"))) == [["A    B"], ["one  two"]]


def test_a_tool_text_gets_its_short_lines_as_headings():
    text = "First\nparagraph here.\n\nShort heading\n\nA line: with colon:\n\nEnds with stop.\n"
    assert helptext.tool_page(text) == [Block(PARAGRAPH, "First paragraph here."),
                                        Block(HEADING, "Short heading"),
                                        Block(PARAGRAPH, "A line: with colon:"),
                                        Block(PARAGRAPH, "Ends with stop.")]


# Every page ---------------------------------------------------------------------------------

@pytest.mark.parametrize("title", list(all_pages()))
def test_a_page_has_no_markup_left_over(title):
    for block in parse(all_pages()[title]):
        assert block.text.count("`") % 2 == 0 or block.kind == CODE, block.text
        assert "{" not in block.text or block.kind == CODE or "{R" in block.text \
            or "{..." in block.text, block.text
        assert not block.text.startswith(("#", "|")), block.text


@pytest.mark.parametrize("title", list(all_pages()))
def test_tables_fit_their_room_and_have_full_rows(title):
    for rows in tables(all_pages()[title]):
        assert {len(row) for row in rows} == {len(rows[0])}, rows[0]
        assert all(len(line) <= helptext.TABLE_WIDTH
                   for row in helptext.table_lines(rows) for line in row)


# Examples -----------------------------------------------------------------------------------

@pytest.mark.parametrize("title, example", examples())
def test_every_example_assembles_in_capitals(title, example, tmp_path):
    assert offences(example) == []
    result = assemble(example, tmp_path)
    assert result.ok, [message.format() for message in result.messages]
    assert result.messages == [], [message.format() for message in result.messages]


@pytest.mark.parametrize("title, example", examples())
def test_every_example_has_its_data_first(title, example):
    assert ".text" in example and ".global _start" in example
    if ".data" in example:
        assert example.index(".data") < example.index(".global _start")
    assert example.index(".global _start") < example.index(".text")


@pytest.mark.parametrize("title, example", examples())
def test_every_example_runs_to_its_end(title, example, tmp_path):
    result = assemble(example, tmp_path)
    machine = Machine(Program(result.elf_path))
    assert machine.run(time_limit=5) is not None


def run_example(example, tmp_path):
    machine = Machine(Program(assemble(example, tmp_path).elf_path))
    machine.run(time_limit=5)
    return machine


def test_the_first_program_prints_hello(tmp_path):
    example = next(text for title, text in examples() if title == "Intro")
    assert run_example(example, tmp_path).console.text.startswith("Hello, world!\n--")


def test_the_jtag_example_prints(tmp_path):
    example = next(text for title, text in examples() if "0xFF201000" in text)
    assert run_example(example, tmp_path).console.text.startswith("Hi\n")


def test_the_first_push_stores_at_the_top_as_the_page_says(tmp_path):
    example = next(text for title, text in examples() if "PUSH" in text)
    machine = run_example(example, tmp_path)
    assert machine.reg(1) == 7 and machine.reg(13) == 0
    assert machine.read_memory(0xFFFFFFFC, 4) == (7).to_bytes(4, "little")


FRAME = """\
        .data
table:  .word   0, 0, 0, 0
        .global _start
        .text
_start: LDR     R1, =table
        {line}
loop:   NOP
done:   NOP
function:
        BX      LR
"""


def example_cells():
    """Every cell of an Example column of the operand key."""
    cells = []
    for rows in tables(helptext.operand_key()):
        if rows[0][-1] == "Example":
            cells += [helptext.plain(row[-1]) for row in rows[1:]]
    return cells


@pytest.mark.parametrize("line", example_cells())
def test_the_instructions_in_the_tables_assemble(line, tmp_path):
    source = FRAME.format(line=line)
    assert offences(source) == []
    result = assemble(source, tmp_path)
    assert result.ok, [message.format() for message in result.messages]


def directive_cells():
    cells = []
    for rows in tables(helptext.DIRECTIVES):
        if rows[0][-1] == "Example":
            cells += [helptext.plain(row[-1]) for row in rows[1:]]
    return cells


@pytest.mark.parametrize("line", directive_cells())
def test_the_directives_in_the_tables_assemble(line, tmp_path):
    source = f"        .data\n        {line}\n        .global _start\n        .text\n_start: NOP\n"
    assert assemble(source, tmp_path).ok


def test_the_directives_page_has_the_specified_directives():
    for name in (".global", ".text", ".data", ".word", ".hword", ".byte", ".ascii", ".asciz",
                 ".space", ".align", ".balign", ".equ", ".ltorg"):
        assert re.search(rf"^\| {re.escape(name)} \|", helptext.DIRECTIVES, re.M), name


def test_every_condition_code_is_listed():
    codes = {row[0] for rows in tables(helptext.operand_key()) if rows[0][0] == "Code"
             for row in rows[1:]}
    assert codes == {"EQ", "NE", "CS", "HS", "CC", "LO", "MI", "PL", "VS", "VC", "HI", "LS", "GE",
                     "LT", "GT", "LE", "AL"}


# Pages made from the program's own tables ---------------------------------------------------

def test_the_system_calls_are_the_programs():
    rows = tables(helptext.system_calls_page())[0]
    assert rows[0] == ("N", "Service", "Arguments", "Result")
    assert [int(row[0]) for row in rows[1:]] == sorted(SERVICES)
    for row in rows[1:]:
        service = SERVICES[int(row[0])]
        assert row[1:] == (service.name, service.arguments or "-", service.result or "-")


def test_the_shortcuts_are_the_menus():
    rows = tables(helptext.keyboard_page(MENUS, label_of))[0]
    expected = {entry[2]: (label_of(title), label_of(entry[1]))
                for title, entries in MENUS for entry in entries or () if entry and entry[2]}
    assert {row[0]: tuple(row[1].split(" > ")) for row in rows[1:]} == expected
    assert "Ctrl+N" in expected and "F5" in expected


# What the pages explain ---------------------------------------------------------------------

def test_the_registers_page_explains_the_shared_storage_and_fpscr():
    words = " ".join(block.text for block in parse(helptext.REGISTERS))
    assert "S2 and S3 are the two halves of D1" in words
    assert "D16 to D31 have no S registers" in words
    assert "FPSCR" in words and "rounding mode" in words


def test_the_devices_page_says_why_sp_starts_at_zero():
    words = " ".join(block.text for block in parse(helptext.PAGES["Memory and devices"]))
    assert "SP starts at 0x00000000" in words
    assert "stores at 0xfffffffc" in words


def test_the_counters_page_names_dynarmic_and_no_person():
    text = tools.window_class("tool_counter").HELP
    assert "DynARMic (GLSVLSI 2026)" in " ".join(text.split())
    assert "Instruction Categories" in text and "Encoding Formats" in text


@pytest.mark.parametrize("tool", tools.TOOLS, ids=lambda tool: tool.command)
def test_every_tool_has_a_page_without_a_help_button(tool):
    text = tools.window_class(tool.command).HELP
    blocks = helptext.tool_page(text)
    assert len(blocks) > 2
    assert "Help button" not in " ".join(block.text for block in blocks)


# What the pages of ARES say ----------------------------------------------------------------

def blocks_of(title):
    return parse(all_pages()[title])


def words_of(title):
    """All the words of a page, those of its tables too."""
    return " ".join([block.text for block in blocks_of(title)]
                    + [cell for block in blocks_of(title) for row in block.rows for cell in row])


def test_the_intro_starts_with_the_name_the_version_and_the_story():
    blocks = blocks_of("Intro")
    assert blocks[0] == Block(TITLE, "ARES - ARM Educational Simulator")
    assert blocks[1] == Block(TITLE, "Version 1.0")
    texts = [block.text for block in blocks]
    count = len(credits.MOTIVATION)
    assert tuple(texts[2:2 + count]) == credits.MOTIVATION
    assert texts[2 + count] == credits.FUN_FACT
    assert blocks[3 + count] == Block(HEADING, "Credits")
    assert tuple(texts[4 + count:4 + count + len(credits.CREDITS)]) == credits.CREDITS


def test_the_intro_goes_on_with_the_first_program():
    words = words_of("Intro")
    assert "ARM Educational Simulator" in words
    assert "supports the ARMv7 instruction set" in words
    assert any(block.kind == CODE for block in blocks_of("Intro"))


def test_the_acknowledgements_have_the_credits_the_engines_and_the_book():
    words = words_of("Acknowledgements")
    for credit in credits.CREDITS:
        assert credit in words
    for name in ("GNU binutils", "Unicorn", "Capstone", "pyelftools", "Python", "Tcl/Tk",
                 "DynARMic (GLSVLSI 2026)", credits.TEXTBOOK):
        assert name in words


# The names of the program and the language that ARES grew out of, as the credits spell them.
OTHER_NAMES = [word for word in credits.MOTIVATION[0].split()[:4] if word.isupper()]


def test_the_credits_alone_may_name_what_ares_grew_out_of():
    assert len(OTHER_NAMES) == 2
    for title in all_pages():
        words = words_of(title)
        if title == "Intro":
            for text in (*credits.MOTIVATION, credits.FUN_FACT):
                words = words.replace(text, "")
        for name in OTHER_NAMES:
            assert not re.search(rf"\b{name}\b", words, re.IGNORECASE), (title, name)


def surnames():
    return [credits.CREATED_BY.rstrip(".").split()[-1],
            *(advisor.split(",")[0].split()[-1] for advisor in credits.ADVISORS)]


def test_the_two_advisors_stand_under_one_heading_in_order():
    assert credits.CREDITS[1:4] == ("Advisors:", *credits.ADVISORS)
    assert "Pegasus Professor" in credits.ADVISORS[0]
    assert "Florida Polytechnic University" in credits.ADVISORS[1]
    assert not any(line.startswith("Advisor:") for line in credits.CREDITS)


def test_people_are_named_on_the_two_pages_of_the_credits_only():
    assert all(name[0].isupper() for name in surnames())
    for title in all_pages():
        for name in surnames():
            assert (name in words_of(title)) == (title in ("Intro", "Acknowledgements")), title


def test_the_book_is_named_on_the_acknowledgements_only():
    name = credits.TEXTBOOK.split()[0]
    assert [title for title in all_pages() if name in words_of(title)] == ["Acknowledgements"]


def test_the_license_page_can_end_with_more_texts():
    blocks = helptext.license_blocks("the licence", "the notices", [("Another", "its text")])
    assert blocks[-2:] == [Block(HEADING, "Another"), Block(DOCUMENT, "its text")]


def test_the_license_page_says_it_in_plain_words_first():
    blocks = helptext.license_blocks("the licence", "the notices")
    assert blocks[0].kind == PARAGRAPH and "open source" in blocks[0].text
    assert "use it, study how it works, change it and share it" in blocks[0].text
    assert "must stay open source too" in " ".join(blocks[0].text.split())
    words = " ".join(block.text for block in blocks)
    assert "GPL-2.0-or-later" in words and "Unicorn" in words and "MIT" in words
    assert blocks[-3:] == [Block(DOCUMENT, "the licence"), Block(HEADING, "Third-party notices"),
                           Block(DOCUMENT, "the notices")]


def test_the_settings_page_has_every_setting_of_the_menu():
    words = words_of("Settings")
    for name, label in SETTINGS_MENU + [entry[:2] for entry in SETTINGS_COMMANDS]:
        assert label_of(label).rstrip(".") in words, label


def test_the_debugging_page_has_the_commands_of_the_run_menu():
    words = words_of("Debugging")
    for key in ("F7", "F8", "F9", "F11", "F12", "Ctrl+K", "Ctrl+T"):
        assert key in words, key


def test_the_ide_page_has_the_menus_of_the_editor():
    words = words_of("IDE")
    for name in ("File > New", "File > Open", "File > Exit", "Edit > Find/Replace",
                 "Edit > Capitalize Instructions", "File > Dump Memory", "Run > Assemble"):
        assert name in words, name


def test_the_limits_name_what_ares_does_not_do():
    words = words_of("Limits")
    for phrase in ("no interrupts and no timers", "no memory management unit", "Thumb",
                   "no divide instruction", "2,000 steps", "play no sound", "no cycles"):
        assert phrase in words, phrase


def test_the_limits_name_every_mnemonic_left_out_of_the_lists():
    words = words_of("Limits")
    for names, why in instructions.LEFT_OUT:
        assert why in words
        for name in names:
            assert re.search(rf"\b{name}\b", words), name
    for form, why in instructions.FORMS_LEFT_OUT:
        assert form in words


def test_the_key_explains_the_operands_of_the_example_lines():
    cells = [row[0] for rows in tables(helptext.operand_key()) for row in rows]
    for operand in ("label", "R1", "S1", "D1", "Q0", "#100", "LSL #2", "{R2, R3}"):
        assert any(operand in cell for cell in cells), operand


def test_the_help_says_the_layout_is_not_kept():
    ide = " ".join(helptext.IDE.split())
    settings = " ".join(helptext.SETTINGS.split())
    assert "every start opens maximized, with the default layout" in ide
    assert "The window's size and dividers are not kept." in settings
    assert "remembers" not in ide
