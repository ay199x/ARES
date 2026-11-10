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
SECTIONS = ("## Features", "## Download", "## A first program", "## Documentation",
            "## Building from source", "## Why ARES", "## Credits", "## Acknowledgements",
            "## Licence")
# The words of the two sections that may name other simulators, built here so that this file
# names none of them.
INSPIRATION, ITS_LANGUAGE = "".join(("M", "A", "R", "S")), "".join(("M", "I", "P", "S"))


def section(title):
    """The text of one section of the README, without its heading."""
    begin = README.index(f"## {title}\n") + len(f"## {title}\n")
    end = README.find("\n## ", begin)
    return README[begin:end if end >= 0 else None]


def menu_labels():
    from ares.gui.app import MENUS
    return {menu.replace("&", ""): [entry[1].replace("&", "") for entry in entries if entry]
            for menu, entries in MENUS if entries}


def test_the_helmet_is_at_the_top_and_centred():
    assert README.startswith('<p align="center"><img src="docs/ares-helmet.png"')


def test_the_title_gives_the_name_and_says_what_ares_is():
    assert "\n# ARES: ARM Educational Simulator\n" in README
    words = " ".join(README.split())
    assert "writing, assembling, running and debugging ARMv7 assembly language" in words
    assert "Education Simulator" not in README


def test_the_sections_are_in_their_order():
    places = [README.index(text) for text in ("# ARES: ARM Educational Simulator",
                                              "docs/screenshot.png", *SECTIONS)]
    assert places == sorted(places)
    assert [line for line in README.split("\n") if line.startswith("## ")] == list(SECTIONS)


def test_other_simulators_are_named_only_in_why_ares_and_the_acknowledgements():
    allowed = section("Why ARES") + section("Acknowledgements")
    rest = README.replace(section("Why ARES"), "").replace(section("Acknowledgements"), "")
    for name in (INSPIRATION, ITS_LANGUAGE):
        assert name in allowed
        assert name.lower() not in rest.lower(), name


def test_why_ares_is_the_motivation_and_the_fun_fact_in_three_sentences_at_most():
    text = section("Why ARES").strip()
    assert text == credits.README_LINE.removeprefix("Why ARES: ")
    assert text.count(". ") + 1 <= 3


def test_the_credits_are_those_of_the_help_and_the_about_box_as_a_list():
    first, second = credits.ADVISORS
    # Plain lines, but for the two advisors: one level of bullets, nothing nested.
    assert section("Credits").strip() == "\n".join((
        credits.CREATED_BY, "", credits.ADVISORS_HEADING, f"- {first}", f"- {second}", "",
        credits.FIRST_USED))
    assert section("Credits").strip() == credits.credits_markup()
    assert credits.CREATED_BY.endswith(".") and credits.FIRST_USED.endswith(".")
    assert not any(advisor.endswith(".") for advisor in credits.ADVISORS)


def test_the_acknowledgements_name_the_inspiration_the_engines_and_the_sources():
    text = section("Acknowledgements")
    assert f"Inspired by [{INSPIRATION}](https://" in text
    assert "Compatible with the ARMv7 syntax of [CPUlator](https://cpulator.01xz.net/)" in text
    for name in ("GNU binutils", "Unicorn", "Capstone"):
        assert f"[{name}](https://" in text
    assert "DynARMic" in text and "https://doi.org/" in text and "GLSVLSI 2026" in text
    assert credits.TEXTBOOK.split(",")[0] in text and "ARM Edition" in text


def test_the_licence_says_in_plain_words_that_ares_is_open_source():
    words = " ".join(section("Licence").split())
    assert ("ARES is open source: anyone may use, study, change and share it, and changed versions "
            "that are shared must stay open source too.") in words
    assert "GPL-2.0-or-later" in words and "THIRD_PARTY_NOTICES.txt" in words


def test_the_features_name_the_nine_tools_by_their_menu_labels():
    from ares.gui.tools import TOOLS
    text = " ".join(section("Features").split())
    labels = [tool.label.replace("&", "") for tool in TOOLS]
    assert len(labels) == 9
    for label in labels:
        assert label in text, label


def test_the_menus_and_keys_the_readme_names_exist():
    menus = menu_labels()
    assert "Capitalize Instructions" in menus["Edit"] and "Find/Replace..." in menus["Edit"]
    assert "Open Example" in menus["File"] and "Help" in menus["Help"]
    from ares.gui.app import MENUS
    keys = {entry[0]: entry[2] for _, entries in MENUS if entries for entry in entries if entry}
    assert keys["assemble"] == "F3" and keys["go"] == "F5"
    for words in ("Edit > Capitalize Instructions", "File > Open Example", "Help > Help",
                  "Press F3 to assemble and F5 to run."):
        assert words in README


def test_the_example_is_in_the_house_style_and_runs(run):
    source = re.search(r"```\n( +\.data\n.*?)```", README, re.S)[1]
    assert offences(source) == []
    assert 8 <= len(source.strip().split("\n")) <= 12
    assert run(source).console.text.startswith("Hello, world!\n")


def test_the_example_assembles_without_a_message(tmp_path):
    source = re.search(r"```\n( +\.data\n.*?)```", README, re.S)[1]
    assert assemble(source, tmp_path).messages == []


def test_the_files_of_the_release_are_in_the_table():
    rows = [line for line in section("Download").split("\n") if line.startswith("| `")]
    assert rows == [
        "| `ARES.exe` | Windows 10 or 11, 64-bit: one file to run |",
        "| `ARES-windows.zip` | the same as a folder, with the example programs beside it |",
        "| `ARES-macos-arm64.zip` | macOS 12 or newer, Apple Silicon |"]
    for name in ("ARES-macos-x86_64.zip", "ARES-linux-x86_64.tar.gz"):
        assert name not in README
    assert "Packages for Linux and for Intel Macs will follow" in README
    assert re.search(r"\[Releases page\]\(https://github\.com/[^/]+/ARES/releases/latest\)",
                     section("Download"))


def test_the_first_start_of_each_system_is_explained():
    words = " ".join(section("Download").split())
    assert "More info > Run anyway" in words
    assert "**Open Anyway** in **System Settings > Privacy & Security**" in words
    assert "on macOS 12: **System Preferences > Security & Privacy**" in words


def test_building_takes_one_command():
    text = section("Building from source")
    assert "tools/build.py" in text and "requirements-dev.txt" in text
    assert "tools/fetch_toolchain.py" in text and "-m ares" in text


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


def test_the_notices_cover_the_libraries_of_the_macos_package_with_their_licences():
    for library, licence in (("zlib 1.2.13", "Licence of zlib"), ("bzip2 1.0.8", "Licence of bzip2"),
                             ("Expat 2.6.2", "Licence of Expat"), ("libffi 3.4", "Licence of libffi"),
                             ("liblzma of XZ Utils 5.4.6", "Licence of liblzma (XZ Utils)")):
        assert library in NOTICES and licence in NOTICES, library
    for file in ("libz.1.dylib", "libbz2.dylib", "libexpat.1.dylib", "libffi.8.dylib",
                 "liblzma.5.dylib"):
        assert file in NOTICES, file
    assert "Permission is granted to anyone to use this software" in NOTICES        # zlib
    assert "The name of the author may not be used to endorse" in NOTICES          # bzip2
    assert "Thai Open Source Software Center Ltd" in NOTICES                       # Expat
    assert "libffi - Copyright (c) 1996-2022" in NOTICES                           # libffi
    assert "liblzma is in the public domain." in NOTICES
    assert "Tcl/Tk 8.6.14" in NOTICES and "Python 3.12" in NOTICES


def test_the_notices_give_the_exact_source_of_the_assembler():
    toolchain = json.loads((ROOT / "tools" / "toolchain.json").read_text(encoding="utf-8"))
    assert toolchain["source"]["url"] in NOTICES
    assert toolchain["version"] in NOTICES


def test_no_public_text_offers_release_checksums():
    """No checksum file was published with a release."""
    for text in (README, NOTICES):
        assert not re.search(r"checksum|sha-?256|SHA256SUMS", text, re.IGNORECASE)


def test_the_notices_give_the_exact_source_of_unicorn():
    toolchain = json.loads((ROOT / "tools" / "toolchain.json").read_text(encoding="utf-8"))
    pins = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert toolchain["engine_source"]["url"] in NOTICES
    version = re.search(r"^unicorn==(\S+)$", pins, re.M)[1]
    assert toolchain["engine_source"]["url"].endswith(f"unicorn-{version}.tar.gz")


def test_the_notices_give_the_versions_in_use():
    pins = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    for name, shown in (("unicorn", "Unicorn"), ("capstone", "Capstone"),
                        ("pyelftools", "pyelftools")):
        version = re.search(rf"^{name}==(\S+)$", pins, re.M)[1]
        assert f"{shown} {version}" in NOTICES
