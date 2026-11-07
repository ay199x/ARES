# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Editor colours: spans of CPUlator lines, incremental re-highlighting and its speed."""

import random
import statistics
import time
from tkinter import TclError, font

import pytest

from ares.gui import highlight
from ares.gui.highlight import COLOURS, TAGS, Highlighter, line_spans
from ares.gui.textedit import TrackedText
from ares.tokens import COMMENT, DIRECTIVE, LABEL_DEF, NUMBER, REGISTER, STRING, tokenize

TAG_OF_KIND = {REGISTER: "register", NUMBER: "number", LABEL_DEF: "label",
               DIRECTIVE: "directive", COMMENT: "comment", STRING: "string"}

PROGRAM = """\
.global _start
/* Scan a genome and add up
   the quality scores. */
.macro EXIT
    MOV R7, #1
    SVC #0
.endm
_start:
    LDR SP, =0x3FFFFFF8
    MOV R5, #0              @ R5 = Total Quality Score
    LDR R1, =covid_genome   @ R1 = Main Genome Pointer
scan_loop_unrolled:
    LDRB R2, [R1], #1       // Load char 1
    CMP R2, #'N'
    LDRNEB R3, [R4]
    SUBNE R3, R3, #33       /* Subtract offset */
    ADD R0, R0, R1, LSL #2
    PUSH {R0-R5, LR}
    POP {R0-R5, PC}
    B scan_loop_unrolled
    EXIT
.data
divisors: .word 100000, 10000, 1000, 100, 10, 1, 0
covid_genome: .asciz "ATTAAAGG"
"""

# 24 lines of a CPUlator-style program; {n} keeps the labels apart.
BLOCK = """\
@ ==========================
@ Part {n}: scan and score
@ ==========================
.data
.balign 4
divisors_{n}: .word 100000, 10000, 1000, 100, 10, 1, 0
genome_{n}: .asciz "ATTAAAGGTTTATACCTTCC"
.text
/* Score the genome
   one character at a time. */
part_{n}:
    LDR SP, =0x3FFFFFF8
    MOV R5, #0              @ R5 = Total Quality Score
    LDR R1, =genome_{n}     // R1 = Main Genome Pointer
loop_{n}:
    LDRB R2, [R1], #1       @ Load char
    CMP R2, #'N'            @ Is it 'N'?
    LDRNEB R3, [R4]
    SUBNE R3, R3, #33       /* Subtract offset */
    ADD R0, R0, R1, LSL #2
    PUSH {{R0-R5, LR}}
    BL print_{n}
    POP {{R0-R5, PC}}
    B loop_{n}
"""


def long_program(lines=2000):
    blocks = (BLOCK.format(n=n) for n in range(lines // 24 + 1))
    return "\n".join("".join(blocks).split("\n")[:lines])


def expected_ranges(source):
    """The tag ranges a full tokenize() of source gives, joined where they touch as in Tk."""
    ranges = {tag: [] for tag in TAGS}
    for number, tokens in enumerate(tokenize(source), 1):
        for token in tokens:
            if token.kind in TAG_OF_KIND:
                indices = ranges[TAG_OF_KIND[token.kind]]
                start, end = f"{number}.{token.start}", f"{number}.{token.end}"
                if indices and indices[-1] == start:
                    indices[-1] = end
                else:
                    indices += [start, end]
    return ranges


def tag_ranges(text):
    return {tag: [str(index) for index in text.tag_ranges(tag)] for tag in TAGS}


def assert_tags_right(text):
    assert tag_ranges(text) == expected_ranges(text.get("1.0", "end-1c"))


@pytest.fixture(autouse=True)
def callback_errors(tk_root):
    """Fail the test on an exception inside a Tk callback, which Tk would only print."""
    errors = []
    tk_root.report_callback_exception = lambda *exc_info: errors.append(exc_info)
    yield
    del tk_root.report_callback_exception
    if errors:
        raise errors[0][1]


@pytest.fixture
def bold_font(tk_root):
    return font.Font(root=tk_root, family="Courier", size=10, weight="bold")


@pytest.fixture
def make_editor(tk_root, bold_font):
    """make_editor(source) -> (TrackedText holding source, its Highlighter)."""
    widgets = []

    def make(source=""):
        text = TrackedText(tk_root, undo=True)
        widgets.append(text)
        text.insert("1.0", source)
        text.edit_reset()
        return text, Highlighter(text, bold_font)

    yield make
    for widget in widgets:
        widget.destroy()


# Spans of single lines -----------------------------------------------------

@pytest.mark.parametrize("line, spans", [
    ("    LDR SP, =0x3FFFFFF8", [("register", 8, 10), ("number", 12, 23)]),
    ("    MOV R5, #0          @ R5 = Total Quality Score",
     [("register", 8, 10), ("number", 12, 14), ("comment", 24, 50)]),
    ("    CMP R2, #'N'", [("register", 8, 10), ("number", 12, 13)]),
    ("    LDRNEB R3, [R4]", [("register", 11, 13), ("register", 16, 18)]),
    ("_start:", [("label", 0, 7)]),
    ("scan_loop_unrolled:", [("label", 0, 19)]),
    (".global _start", [("directive", 0, 7)]),
    ("divisors: .word 100000, 10000, 1000, 100, 10, 1, 0",
     [("label", 0, 9), ("directive", 10, 15), ("number", 16, 22), ("number", 24, 29),
      ("number", 31, 35), ("number", 37, 40), ("number", 42, 44), ("number", 46, 47),
      ("number", 49, 50)]),
    ('covid_genome: .asciz "ATTAAAGG"',
     [("label", 0, 13), ("directive", 14, 20), ("string", 21, 31)]),
    ("    POP {R0-R5, PC}", [("register", 9, 11), ("register", 12, 14), ("register", 16, 18)]),
    ("    B div_loop", []),
    ("    STRB R0, [R1]", [("register", 9, 11), ("register", 14, 16)]),
    ("    ADD R0, R0, R1, LSL #2",
     [("register", 8, 10), ("register", 12, 14), ("register", 16, 18), ("number", 24, 26)]),
    ("    MRS R0, CPSR", [("register", 8, 10), ("register", 12, 16)]),
    ("    VADD.F32 S0, S1, D0",
     [("register", 13, 15), ("register", 17, 19), ("register", 21, 23)]),
    ("// comment", [("comment", 0, 10)]),
    ("/* block */ MOV R0, #1", [("comment", 0, 11), ("register", 16, 18), ("number", 20, 22)]),
])
def test_spans_of_cpulator_lines(line, spans):
    assert line_spans(line) == (spans, False)


def test_spans_across_a_block_comment():
    spans, state = line_spans("    MOV R0, #1  /* open")
    assert spans == [("register", 8, 10), ("number", 12, 14), ("comment", 16, 23)]
    assert state
    spans, state = line_spans("    still open", state)
    assert spans == [("comment", 4, 14)] and state
    spans, state = line_spans("closed */ , R1", state)
    assert spans == [("comment", 0, 9), ("register", 12, 14)] and state is False


def test_spans_of_a_macro_call():
    """Operands of a macro call are expressions, even when the macro is called MOV."""
    assert line_spans("    MOV R0, R1", False, frozenset({"MOV"})) == ([], False)


# The widget ------------------------------------------------------------------

def test_tags_match_a_full_tokenize(make_editor, bold_font):
    text, _ = make_editor(PROGRAM)
    assert_tags_right(text)
    assert tag_ranges(text)["label"] == ["8.0", "8.7", "12.0", "12.19", "23.0", "23.9",
                                         "24.0", "24.13"]
    for tag, colour in COLOURS.items():
        assert str(text.tag_cget(tag, "foreground")) == colour
    assert str(text.tag_cget("label", "font")) == str(bold_font)


def test_highlight_all_colours_again(make_editor):
    text, highlighter = make_editor(PROGRAM)
    for tag in TAGS:
        text.tag_remove(tag, "1.0", "end")
    text.tag_add("comment", "9.0", "11.0")
    highlighter.highlight_all()
    assert_tags_right(text)


def test_inserted_and_deleted_text_is_coloured(make_editor):
    text, _ = make_editor()
    text.insert("1.0", PROGRAM)
    assert_tags_right(text)
    text.insert("10.0", "extra:\n    MOV R9, #9 @ new\n")
    assert_tags_right(text)
    text.delete("5.2", "14.4")
    assert_tags_right(text)
    text.delete("1.0", "end")
    assert tag_ranges(text) == {tag: [] for tag in TAGS}


def test_block_comment_opened_and_closed_while_typing(make_editor):
    lines = ["_start:", "    MOV R0, #1", "    ADD R1, R0, R0  @ twice",
             "values: .word 1, 2", '    .asciz "x"', "    B _start"]
    text, _ = make_editor("\n".join(lines))
    text.insert("2.0", "/")
    text.insert("2.1", "*")
    commented = ["2.0", "2.16", "3.4", "3.27", "4.0", "4.18", "5.4", "5.14", "6.4", "6.12"]
    assert tag_ranges(text) == {**{tag: [] for tag in TAGS}, "label": ["1.0", "1.7"],
                                "comment": commented}
    text.insert("4.0", "*")
    assert tag_ranges(text)["comment"] == commented[:5] + ["4.19"] + commented[6:]
    text.insert("4.1", "/")
    assert tag_ranges(text)["comment"] == commented[:4] + ["4.0", "4.2"]
    assert tag_ranges(text)["label"] == ["1.0", "1.7", "4.2", "4.9"]
    assert_tags_right(text)


def test_only_lines_whose_start_state_changed_are_tokenized_again(make_editor, monkeypatch):
    lines = [f"    MOV R{n % 13}, #{n}" for n in range(1, 41)]
    lines[29] = "/* note 30"
    lines[33] = "   end 34 */"
    text, _ = make_editor("\n".join(lines))
    seen = []

    def recording_line_spans(line, *args):
        seen.append(line)
        return line_spans(line, *args)

    def tokenized():
        """Numbers of the lines tokenized since the last call (every line is different)."""
        current = text.get("1.0", "end-1c").split("\n")
        numbers = [current.index(line) + 1 for line in seen]
        seen.clear()
        return numbers

    monkeypatch.setattr(highlight, "line_spans", recording_line_spans)
    text.insert("10.4", "X")
    assert tokenized() == [10]
    text.insert("5.0", "/*")
    assert tokenized() == list(range(5, 31))    # lines 31-34 were inside a comment already
    assert_tags_right(text)
    text.insert("12.end", "*/")
    assert tokenized() == list(range(12, 31))
    assert_tags_right(text)
    text.delete("5.0", "5.2")
    assert tokenized() == list(range(5, 13))
    assert_tags_right(text)


def test_macro_definitions(make_editor):
    """A macro called MOV turns later MOV lines into macro calls, without registers."""
    text, _ = make_editor("    MOV R0, R1\n.macro mov a, b\n.endm\n    MOV R2, R3\n"
                          "    ADD R4, R5, R6")
    assert tag_ranges(text)["register"] == ["1.8", "1.10", "1.12", "1.14", "5.8", "5.10",
                                            "5.12", "5.14", "5.16", "5.18"]
    text.delete("2.0", "3.0")
    assert tag_ranges(text)["register"][4:8] == ["3.8", "3.10", "3.12", "3.14"]
    assert_tags_right(text)
    text.insert("1.0", ".MACRO Mov x\n")
    assert tag_ranges(text)["register"] == ["5.8", "5.10", "5.12", "5.14", "5.16", "5.18"]
    assert_tags_right(text)
    text.insert("1.0", "/* ")
    text.insert("1.end", " */")
    assert len(tag_ranges(text)["register"]) == 14
    assert_tags_right(text)
    text.insert("1.0", "/*\n")
    assert_tags_right(text)
    text.delete("1.0", "2.0")
    assert_tags_right(text)


def test_undo_and_redo_leave_the_tags_of_a_fresh_highlight(make_editor):
    text, _ = make_editor(PROGRAM)
    edits = [lambda: text.insert("8.0", "/* "),         # a comment up to line 16
             lambda: text.delete("5.0", "9.0"),
             lambda: text.insert("end", "\n.macro LDR a\n.endm\n    LDR R0, R1"),
             lambda: text.replace("2.0", "3.2", "    ADD R1, R2, #3\n*/"),
             lambda: text.delete("1.0", "end")]

    def assert_fresh():
        fresh, _ = make_editor(text.get("1.0", "end-1c"))
        assert tag_ranges(text) == tag_ranges(fresh)

    for edit in edits:
        edit()
        text.edit_separator()
        assert_fresh()
    for _ in edits:
        text.edit_undo()
        assert_fresh()
    assert text.get("1.0", "end-1c") == PROGRAM
    for _ in edits:
        text.edit_redo()
        assert_fresh()


def test_abbreviated_and_failing_commands_keep_the_tags_right(make_editor):
    """Tk accepts abbreviated subcommands, and a malformed tag list changes nothing."""
    text, _ = make_editor("    MOV R0, #1\n    ADD R1, R2, R3")
    path = str(text)
    text.tk.call(path, "ins", "1.0", "/* open\n")
    assert_tags_right(text)
    with pytest.raises(TclError):
        text.tk.call(path, "insert", "1.0", "@ note\n", "{bad")
    text.tk.call(path, "r", "2.0", "2.end", "    MOV R2, #2 */")
    assert_tags_right(text)
    text.tk.call(path, "del", "1.0", "2.0")
    text.insert("end", " @ typed at the end")
    assert_tags_right(text)
    assert text.line_count() == 2


def test_random_edits_keep_the_tags_right(make_editor):
    pieces = ["X", " ", "\n", "/*", "*/", "@", "//", '"', "'", "#1", ", R2", ":", ";",
              "\\", ".macro MOV a\n", ".endm\n", "    MOV R0, R1\n", "label: .word 1, 2\n",
              "/* a\n b */", 'x: .asciz "s @ /*"\n', "\n\n"]
    rng = random.Random(2026)
    text, _ = make_editor(PROGRAM)
    for _ in range(300):
        line = rng.randint(1, text.line_count())
        where = f"{line}.{rng.randint(0, len(text.get(f'{line}.0', f'{line}.end')))}"
        choice = rng.random()
        if choice < 0.5:
            text.insert(where, rng.choice(pieces))
        elif choice < 0.65:
            text.delete(f"{where}-1c")          # what BackSpace does
        elif choice < 0.9:
            text.delete(where, f"{where}+{rng.randint(1, 40)}c")
        elif text.edit("canundo"):
            text.edit_undo()
        assert_tags_right(text)


def test_characters_beyond_the_basic_plane(make_editor):
    """Tk 8.6 counts such a character as two columns; the colours still cover whole tokens."""
    smile = "\U0001F600"
    text, _ = make_editor(f"    MOV R0, #1  @ {smile} ok\ns: .asciz \"{smile}\" @ {smile}")

    def coloured(tag):
        indices = text.tag_ranges(tag)
        return [text.get(start, end) for start, end in zip(indices[::2], indices[1::2])]

    assert coloured("comment") == [f"@ {smile} ok", f"@ {smile}"]
    assert coloured("string") == [f'"{smile}"']
    assert coloured("register") == ["R0"]
    assert coloured("label") == ["s:"]


def test_selection_stays_above_the_colours(tk_root, bold_font):
    text = TrackedText(tk_root)
    try:
        text.tag_configure("before_one")
        text.tag_configure("before_two")
        Highlighter(text, bold_font)
        names = list(text.tag_names())          # lowest priority first
        assert all(names.index("sel") > names.index(tag) for tag in TAGS)
        assert names.index("before_one") < names.index("before_two")
    finally:
        text.destroy()


def test_bold_font_for_labels_can_change(tk_root, make_editor, bold_font):
    text, highlighter = make_editor("_start:")
    assert str(text.tag_cget("label", "font")) == str(bold_font)
    larger = font.Font(root=tk_root, family="Courier", size=14, weight="bold")
    highlighter.set_bold_font(larger)
    assert str(text.tag_cget("label", "font")) == str(larger)


# Speed ---------------------------------------------------------------------------

@pytest.mark.serial
def test_typing_in_a_2000_line_program_is_fast(make_editor):
    text, _ = make_editor(long_program())
    assert text.line_count() == 2000
    times = []
    for _ in range(20):
        start = time.perf_counter()
        text.insert("1000.4", "X")
        times.append(time.perf_counter() - start)
    median = statistics.median(times)
    assert median < 0.005, f"{median * 1000:.2f} ms"
    assert_tags_right(text)


@pytest.mark.serial
def test_highlight_all_of_2000_lines_is_fast(make_editor):
    text, highlighter = make_editor(long_program())
    times = []
    for _ in range(3):
        start = time.perf_counter()
        highlighter.highlight_all()
        times.append(time.perf_counter() - start)
    median = statistics.median(times)
    assert median < 0.3, f"{median * 1000:.0f} ms"
    assert_tags_right(text)
