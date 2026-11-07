# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""How tools/check_package.py judges what a package did. Packages themselves run in the workflows."""

import sys

import pytest
from conftest import ROOT

sys.path.insert(0, str(ROOT / "tools"))
import check_package as check  # noqa: E402

END = "\n-- program is finished running --\n"
OUT = {"name": "programs/a.s", "keys": False, "lines": [], "expected": "42" + END}
TYPED = {"name": "programs/b.s", "keys": False, "lines": ["40", "2"], "expected": "42" + END}
EXAMPLE = {"name": "examples/c.s", "keys": False, "lines": [], "starts_with": "Sum: 3\n"}
KEYS = {"name": "examples/d.s", "keys": True, "lines": ["Abc1"], "starts_with": "ABC1\n"}


def good(output, **more):
    return {"assembled": True, "output": output, "error": None, **more}


def test_exact_output_passes():
    assert check.program_problem(OUT, good("42" + END)) is None


def test_other_output_is_shown():
    assert "41" in check.program_problem(OUT, good("41" + END))


def test_typed_lines_are_taken_out_by_where_they_were_typed():
    # "2" also ends the line "42": only the place tells which one was typed.
    assert check.program_problem(TYPED, good("40\n2\n42" + END, starts=[0, 3])) is None


def test_an_example_shows_its_start_and_then_the_end_of_the_program():
    assert check.program_problem(EXAMPLE, good("Sum: 3" + END)) is None
    assert check.program_problem(EXAMPLE, good("Sum: 3\n")) is not None
    assert check.program_problem(EXAMPLE, good("Sum: 3\nmore" + END)) is not None
    dropped = "Sum: 3\n-- program is finished running (dropped off bottom) --\n"
    assert check.program_problem(EXAMPLE, good(dropped)) is not None


def test_keys_are_not_lines():
    assert check.program_problem(KEYS, good("ABC1" + END)) is None


@pytest.mark.parametrize("result, word", [
    ({"failed": "a traceback"}, "traceback"), ({"assembled": False, "messages": "no"}, "no"),
    ({"assembled": True, "error": "a fault"}, "fault")])
def test_a_program_that_did_not_run_says_why(result, word):
    assert word in check.program_problem(OUT, result)


def test_a_report_lists_all_its_problems():
    report = {"programs": {"programs/a.s": good("42" + END)}, "tools": {"tool_x": "a traceback"},
              "documents": {"LICENSE": 3}, "internal errors": 2, "examples": ["hello.s"]}
    problems = check.report_problems(report, [OUT])
    assert problems[:3] == ["the list was not finished", "it did not run as a package",
                            "2 internal errors in ARES Messages"]
    assert problems[3].startswith("File > Open Example lacks ")
    assert problems[4:] == ["tool_x: a traceback", "LICENSE: only 3 characters"]


def test_a_good_report_has_no_problems():
    report = {"programs": {"programs/a.s": good("42" + END)}, "tools": {"tool_x": "opened"},
              "documents": {"LICENSE": 5000}, "internal errors": 0, "frozen": True, "done": True,
              "examples": list(check.example_table())}
    assert check.report_problems(report, [OUT]) == []


def test_the_list_holds_every_program_with_an_output_and_every_example():
    names = [entry["name"] for entry in check.list_of_programs()]
    assert "programs/read_sum.s" in names and "examples/xray_tour.s" in names
    assert len(names) == len(set(names))
    assert sum(name.startswith("examples/") for name in names) == len(
        list((ROOT / "examples").glob("*.s")))


def test_what_a_program_reads_is_typed_for_it():
    entries = {entry["name"]: entry for entry in check.list_of_programs()}
    assert entries["programs/read_sum.s"]["lines"]
    assert entries["examples/strings.s"]["lines"] == ["ARM", "3"]
    assert entries["examples/keyboard_echo.s"]["keys"] is True


@pytest.mark.parametrize("tag, parts", [
    ("windows-x64", ("ARES", "ARES.exe")), ("linux-x86_64", ("ARES", "ARES")),
    ("macos-arm64", ("ARES.app", "Contents", "MacOS", "ARES"))])
def test_the_program_of_a_package_is_found(tag, parts, tmp_path):
    assert check.program_of(tmp_path, tag).parts[-len(parts):] == parts
