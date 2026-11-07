# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""README.md, the helmet picture it shows, and THIRD_PARTY_NOTICES.txt."""

import json
import re
import subprocess
import sys

from conftest import ROOT

from ares import credits
from ares.assembler import assemble
from ares.capitals import offences

README = (ROOT / "README.md").read_text(encoding="utf-8")
NOTICES = (ROOT / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")
# The simulator it names is left out here: only the README's own line may name it.
ACKNOWLEDGEMENTS = re.compile(
    r"Acknowledgements: inspired by [A-Z]{4} and its tools; compatible with CPUlator's ARMv7 "
    r"syntax; built on GNU binutils, Unicorn and Capstone; Dynamic Instruction Counter tool "
    r"based on DynARMic\.")


def test_the_helmet_is_at_the_top():
    assert README.startswith('<img src="docs/ares-helmet.png"')


def test_the_readme_gives_the_name_and_the_instruction_set():
    assert "ARM Educational Simulator" in README
    assert "supports the ARMv7 instruction set" in " ".join(README.split())
    assert "Education Simulator" not in README


def test_the_sections_are_in_their_order():
    places = [README.index(text) for text in (
        "ARM Educational Simulator", "Why ARES:", "docs/screenshot.png", "## Download", "SmartScreen",
        "right-click", "Open Anyway", "## A first program", "## Build it yourself", "## Credits",
        "## Licence",
        "GPL-2.0-or-later", "THIRD_PARTY_NOTICES.txt", "Acknowledgements:")]
    assert places == sorted(places)


def test_the_readme_fits_about_one_printed_page():
    assert len(README.split("\n")) <= 90
    assert len(README.split()) <= 560


def test_the_credits_are_those_of_the_help_and_the_about_box():
    for line in (*credits.CREDITS, credits.README_LINE):
        assert line in README


def test_the_advisors_are_a_numbered_list_under_their_heading():
    first, second = credits.ADVISORS
    assert f"Advisors:\n\n1. {first}\n2. {second}\n" in README


def test_the_why_is_one_line_of_three_sentences_at_most():
    line = next(text for text in README.split("\n") if text.startswith("Why ARES:"))
    assert line == credits.README_LINE and line.count(". ") + 1 <= 3


def test_the_licence_says_in_plain_words_that_ares_is_open_source():
    words = " ".join(README.split())
    assert ("ARES is open source: anyone may use, study, change and share it, and changed versions "
            "that are shared must stay open source too.") in words


def test_the_acknowledgements_line_has_its_words_and_ends_the_file():
    assert ACKNOWLEDGEMENTS.fullmatch(README.rstrip().split("\n")[-1])


def test_the_example_is_in_the_house_style_and_runs(run):
    source = re.search(r"```\n( +\.data\n.*?)```", README, re.S)[1]
    assert offences(source) == []
    assert 8 <= len(source.strip().split("\n")) <= 12
    assert run(source).console.text.startswith("Hello, world!\n")


def test_the_example_assembles_without_a_message(tmp_path):
    source = re.search(r"```\n( +\.data\n.*?)```", README, re.S)[1]
    assert assemble(source, tmp_path).messages == []


def test_the_files_of_a_release_are_named():
    for name in ("ARES.exe", "ARES-windows.zip"):
        assert name in README
    for name in ("ARES-macos-arm64.zip", "ARES-macos-x86_64.zip", "ARES-linux-x86_64.tar.gz"):
        assert name not in README
    assert "Packages for macOS and Linux will follow" in README


def test_the_first_start_of_each_system_is_explained():
    words = " ".join(README.split())
    assert "More info > Run anyway" in words
    assert "System Settings > Privacy & Security" in words and "Open Anyway" in words
    assert "ARES/ARES" in words


def test_building_takes_one_command():
    assert "tools/build.py" in README and "requirements-dev.txt" in README


def test_the_helmet_picture_is_made_by_the_script():
    assert (ROOT / "tools" / "make_helmet_png.py").is_file()
    script = f"""
import sys
sys.path.insert(0, {str(ROOT / "tools")!r})
import make_helmet_png
sys.stdout.buffer.write(make_helmet_png.picture())
"""
    made = subprocess.run([sys.executable, "-c", script], capture_output=True, check=True,
                          cwd=ROOT).stdout
    assert made == (ROOT / "docs" / "ares-helmet.png").read_bytes()


def test_the_helmet_picture_is_the_32_grid_at_four_times_its_size():
    data = (ROOT / "docs" / "ares-helmet.png").read_bytes()
    assert int.from_bytes(data[16:20], "big") == int.from_bytes(data[20:24], "big") == 128


def test_the_notices_list_every_bundled_component():
    for name in ("GNU binutils", "Unicorn", "Capstone", "pyelftools", "Python", "Tcl/Tk",
                 "PyInstaller bootloader", "Zstandard", "VCRUNTIME140.dll"):
        assert name in NOTICES, name
    assert "ARM Educational Simulator" in NOTICES


def test_the_notices_carry_the_licence_texts_a_binary_must_carry():
    assert "Licence of Capstone" in NOTICES and "Redistribution and use in source" in NOTICES
    assert "Licence of Tcl/Tk" in NOTICES and "copyrighted by the Regents" in NOTICES
    assert "come from LLVM" in NOTICES and "University of Illinois/NCSA" in NOTICES
    assert "Licence of Zstandard" in NOTICES and "BSD License" in NOTICES
    assert "Licence of Construct" in NOTICES and "Tomer Filiba" in NOTICES


def test_the_notices_name_what_starts_a_package_and_the_software_inside_python():
    assert "PyInstaller run-time hooks" in NOTICES and "licenses/Apache-2.0.txt" in NOTICES
    assert "licenses/Python-parts.txt" in NOTICES
    assert "Additional Conditions for this Windows binary build" in " ".join(NOTICES.split())


def test_the_notices_give_the_exact_source_of_the_assembler():
    toolchain = json.loads((ROOT / "tools" / "toolchain.json").read_text(encoding="utf-8"))
    assert toolchain["source"]["url"] in NOTICES
    assert toolchain["source"]["sha256"] in NOTICES
    assert toolchain["version"] in NOTICES


def test_the_notices_give_the_exact_source_of_unicorn():
    toolchain = json.loads((ROOT / "tools" / "toolchain.json").read_text(encoding="utf-8"))
    pins = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert toolchain["engine_source"]["url"] in NOTICES
    assert toolchain["engine_source"]["sha256"] in NOTICES
    version = re.search(r"^unicorn==(\S+)$", pins, re.M)[1]
    assert toolchain["engine_source"]["url"].endswith(f"unicorn-{version}.tar.gz")


def test_the_notices_give_the_versions_in_use():
    pins = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    for name, shown in (("unicorn", "Unicorn"), ("capstone", "Capstone"),
                        ("pyelftools", "pyelftools")):
        version = re.search(rf"^{name}==(\S+)$", pins, re.M)[1]
        assert f"{shown} {version}" in NOTICES
