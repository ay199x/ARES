# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The build script's pure parts, the icon files, and the workflows that run it on each system."""

import json
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import ROOT

from ares import __version__, toolchain

sys.path.insert(0, str(ROOT / "tools"))
import build  # noqa: E402
import make_icons  # noqa: E402

WORKFLOWS = ROOT / ".github" / "workflows"
TOOLCHAIN = json.loads((ROOT / "tools" / "toolchain.json").read_text(encoding="utf-8"))
ICONS = ("ARES.ico", "ARES.icns")
TAGS = ("windows-x64", "macos-arm64", "macos-x86_64", "linux-x86_64")


def argument_values(arguments, option):
    return [arguments[k + 1] for k, value in enumerate(arguments) if value == option]


def png_size(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


# The icon files ------------------------------------------------------------------------------

def ico_entries(data):
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1)
    entries = []
    for k in range(count):
        width, height, _, _, planes, bits, size, place = struct.unpack(
            "<BBBBHHII", data[6 + 16 * k:22 + 16 * k])
        assert (planes, bits) == (1, 32) and width == height
        entries.append((width or 256, data[place:place + size]))
    return entries


def test_the_ico_file_holds_each_size_of_the_helmet():
    entries = ico_entries(make_icons.ico())
    assert [side for side, _ in entries] == [16, 32, 48, 64, 128, 256]
    for side, data in entries:
        assert png_size(data) == (side, side)


def test_the_small_sizes_come_from_their_own_grid():
    entries = dict(ico_entries(make_icons.ico()))
    assert entries[16] == make_icons.icons.helmet_png(make_icons.icons.HELMET_16, 1)
    assert entries[48] == make_icons.icons.helmet_png(make_icons.icons.HELMET_16, 3)
    assert entries[32] == make_icons.icons.helmet_png(make_icons.icons.HELMET_32, 1)


def icns_entries(data):
    assert data[:4] == b"icns"
    assert struct.unpack(">I", data[4:8])[0] == len(data)
    entries, place = {}, 8
    while place < len(data):
        kind, size = data[place:place + 4], struct.unpack(">I", data[place + 4:place + 8])[0]
        entries[kind] = data[place + 8:place + size]
        place += size
    return entries


def test_the_icns_file_holds_a_picture_of_the_right_size_for_each_type():
    sides = {b"icp4": 16, b"icp5": 32, b"icp6": 64, b"ic07": 128, b"ic08": 256, b"ic09": 512,
             b"ic10": 1024, b"ic11": 32, b"ic12": 64, b"ic13": 256, b"ic14": 512}
    entries = icns_entries(make_icons.icns())
    assert set(entries) == set(sides)
    for kind, side in sides.items():
        assert png_size(entries[kind]) == (side, side)


def test_write_all_makes_both_files(tmp_path):
    made = make_icons.write_all(tmp_path / "icons")
    assert [path.name for path in made] == list(ICONS)
    assert all(path.stat().st_size > 0 for path in made)


# Version information -------------------------------------------------------------------------

def test_the_windows_version_has_four_numbers():
    assert build.version_numbers("1.0") == (1, 0, 0, 0)
    assert build.version_numbers("1.2.3") == (1, 2, 3, 0)


def test_the_version_resource_is_a_valid_expression_with_the_version():
    text = build.version_resource()
    compile(text, "version", "eval")
    assert "ARES 1.0" in text if __version__ == "1.0" else True
    for words in ("ARM Educational Simulator", "The ARES Project", "ARES.exe"):
        assert words in text


def test_pyinstaller_reads_the_version_resource(tmp_path):
    versioninfo = pytest.importorskip("PyInstaller.utils.win32.versioninfo")
    path = tmp_path / "version.txt"
    path.write_text(build.version_resource(), encoding="utf-8")
    info = versioninfo.load_version_info_from_text_file(str(path))
    assert info.ffi.fileVersionMS == 1 << 16 and info.ffi.fileVersionLS == 0


def test_the_bundle_says_its_version_and_keeps_what_was_there():
    plist = build.describe_bundle({"CFBundleIdentifier": "kept"})
    assert plist["CFBundleIdentifier"] == "kept"
    assert plist["CFBundleShortVersionString"] == __version__
    assert plist["NSHighResolutionCapable"] is True


# What goes into a package --------------------------------------------------------------------

@pytest.fixture
def icon_paths(tmp_path):
    return tmp_path / ICONS[0], tmp_path / ICONS[1]


@pytest.mark.parametrize("tag", TAGS)
@pytest.mark.parametrize("kind", ["file", "folder"])
def test_every_package_holds_what_ares_reads(tag, kind, icon_paths, tmp_path):
    arguments = build.pyinstaller_arguments(tag, kind, icon_paths, tmp_path)
    data = [value.rsplit(build.os.pathsep, 1) for value in argument_values(arguments, "--add-data")]
    targets = {source.replace("\\", "/").rsplit("/", 1)[-1]: target for source, target in data}
    assert targets["LICENSE"] == "."
    assert targets["THIRD_PARTY_NOTICES.txt"] == "."
    assert targets["ares.ld"] == "ares/data"
    assert targets["examples"] == "examples"
    assert targets[tmp_path.name] == "licenses"


@pytest.mark.parametrize("tag", TAGS)
def test_the_assembler_and_linker_go_into_the_folder_ares_looks_in(tag, icon_paths, tmp_path):
    arguments = build.pyinstaller_arguments(tag, "folder", icon_paths, tmp_path)
    binaries = [value for value in argument_values(arguments, "--add-binary")
                if value.endswith("toolchain/bin")]
    assert len(binaries) == 2
    suffix = ".exe" if tag == "windows-x64" else ""
    assert "arm-none-eabi-as" + suffix in binaries[0]
    assert "arm-none-eabi-ld" + suffix in binaries[1]
    assert f"vendor" in binaries[0] and tag in binaries[0]


def test_the_tools_are_collected_by_name_and_there_is_no_console(icon_paths, tmp_path):
    arguments = build.pyinstaller_arguments("windows-x64", "file", icon_paths, tmp_path)
    assert argument_values(arguments, "--collect-submodules") == ["ares.gui.tools", "unicorn",
                                                                  "capstone"]
    assert "--windowed" in arguments and "--onefile" in arguments
    assert arguments[-1].endswith("__main__.py")


@pytest.mark.parametrize("name, library", [
    ("unicorn.dll", True), ("libunicorn.2.dylib", True), ("libunicorn.so.2", True),
    ("libcapstone.so", True), ("libcapstone.so.5", True), ("unicorn.lib", False),
    ("libunicorn.a", False), ("__init__.py", False)])
def test_a_library_of_any_system_is_known_by_its_name(name, library):
    assert build.is_library(Path(name)) is library


def engine_site(tmp_path, monkeypatch, names):
    """Engines installed in tmp_path, each with the files called names in its folder lib."""
    for engine in build.ENGINES:
        (tmp_path / engine / "lib").mkdir(parents=True)
        (tmp_path / engine / "__init__.py").write_text("", encoding="utf-8")
        for name in names:
            (tmp_path / engine / "lib" / name).write_text("", encoding="utf-8")
    monkeypatch.setattr(build.importlib.util, "find_spec", lambda name: SimpleNamespace(
        origin=str(tmp_path / name / "__init__.py")))


def test_the_engines_libraries_are_taken_whatever_their_name(tmp_path, monkeypatch, icon_paths):
    engine_site(tmp_path, monkeypatch, ["libunicorn.so.2", "libunicorn.a"])
    assert [(path.name, folder) for path, folder in build.engine_libraries()] == [
        ("libunicorn.so.2", "unicorn/lib"), ("libunicorn.so.2", "capstone/lib")]
    arguments = build.pyinstaller_arguments("linux-x86_64", "folder", icon_paths, tmp_path)
    binaries = argument_values(arguments, "--add-binary")
    assert sum(value.endswith("unicorn/lib") and "libunicorn.so.2" in value
               for value in binaries) == 1


def test_an_engine_without_its_library_stops_the_build(tmp_path, monkeypatch):
    engine_site(tmp_path, monkeypatch, ["libunicorn.a"])
    with pytest.raises(SystemExit, match="no library"):
        build.engine_libraries()


def test_the_build_finds_the_engines_on_this_computer():
    found = {folder for _, folder in build.engine_libraries()}
    assert found == {"unicorn/lib", "capstone/lib"}


def test_a_package_without_an_engines_library_is_refused(tmp_path):
    (tmp_path / "unicorn" / "lib").mkdir(parents=True)
    with pytest.raises(SystemExit, match="no library of unicorn"):
        build.check_contents(tmp_path, "linux-x86_64")


def test_each_system_gets_its_own_icon(icon_paths, tmp_path):
    for tag, icon in (("windows-x64", icon_paths[0]), ("macos-arm64", icon_paths[1])):
        arguments = build.pyinstaller_arguments(tag, "folder", icon_paths, tmp_path)
        assert argument_values(arguments, "--icon") == [str(icon)]
    arguments = build.pyinstaller_arguments("linux-x86_64", "folder", icon_paths, tmp_path)
    assert argument_values(arguments, "--icon") == []


def test_only_windows_has_a_version_resource(icon_paths, tmp_path):
    for tag in TAGS:
        arguments = build.pyinstaller_arguments(tag, "folder", icon_paths, tmp_path)
        assert ("--version-file" in arguments) == (tag == "windows-x64")


def test_what_ares_never_uses_is_left_out_of_a_package():
    recipe = "a = Analysis(['x'])\npyz = PYZ(a.pure)\nexe = EXE(pyz)\n"
    changed = build.leave_files_out(recipe)
    assert changed.index("Analysis") < changed.index("a.datas =") < changed.index("pyz = PYZ(")
    names = ("_tcl_data\\tzdata\\Europe\\Paris", "_tcl_data/msgs/de.msg", "_tcl_data/init.tcl",
             "_tcl_data/encoding/utf-8.enc", "_tk_data/tk.tcl", "_tk_data/msgs/de.msg")
    analysis = SimpleNamespace(datas=[(name, "x", "DATA") for name in names])
    line = changed[changed.index("a.datas ="):changed.index("pyz = PYZ(")]
    exec(line, {"a": analysis})
    assert [item[0] for item in analysis.datas] == list(names[2:])


PYTHON_TEXT = "A. HISTORY OF THE SOFTWARE\n\nPYTHON SOFTWARE FOUNDATION LICENSE VERSION 2\n"
OTHER_TEXT = "End User License Agreement - Miniconda\n"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_python_s_licence_comes_from_beside_the_standard_library_on_a_python_org_mac(tmp_path):
    base = tmp_path / "Python.framework" / "Versions" / "3.12"
    stdlib = base / "lib" / "python3.12"
    wanted = write(stdlib / "LICENSE.txt", PYTHON_TEXT)
    assert build.python_licence(base, stdlib, "python3.12") == wanted


def test_miniconda_s_own_licence_beside_its_python_is_passed_over(tmp_path):
    base = tmp_path / "miniconda3"
    stdlib = base / "lib" / "python3.12"
    write(base / "LICENSE.txt", OTHER_TEXT)
    wanted = write(stdlib / "LICENSE.txt", PYTHON_TEXT)
    assert build.python_licence(base, stdlib, "python3.12") == wanted


def test_the_standard_library_s_copy_is_preferred_to_the_one_at_the_base(tmp_path):
    base = tmp_path / "python"
    stdlib = base / "lib" / "python3.12"
    write(base / "LICENSE.txt", PYTHON_TEXT)
    wanted = write(stdlib / "LICENSE.txt", PYTHON_TEXT)
    assert build.python_licence(base, stdlib, "python3.12") == wanted


def test_on_windows_python_s_licence_lies_at_the_base_of_the_installation(tmp_path):
    base = tmp_path / "Python311"
    stdlib = base / "Lib"
    stdlib.mkdir(parents=True)
    wanted = write(base / "LICENSE.txt", PYTHON_TEXT)
    assert build.python_licence(base, stdlib, "python3.11") == wanted


def test_the_build_stops_when_no_licence_file_is_python_s(tmp_path):
    base = tmp_path / "miniconda3"
    stdlib = base / "lib" / "python3.12"
    stdlib.mkdir(parents=True)
    write(base / "LICENSE.txt", OTHER_TEXT)
    with pytest.raises(SystemExit) as stop:
        build.python_licence(base, stdlib, "python3.12")
    message = str(stop.value)
    assert "PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2" in message
    assert str(base / "LICENSE.txt") in message and str(stdlib / "LICENSE.txt") in message


def test_the_python_that_builds_here_has_its_licence_found():
    found = build.python_licence()
    assert "PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2" in found.read_text(encoding="utf-8")


def test_the_licence_texts_of_a_package_exist():
    sources = build.licence_files()
    assert [name for _, name in sources] == ["GPL-3.0.txt", "Apache-2.0.txt", "Python-LICENSE.txt",
                                             "Python-parts.txt"]
    gpl = sources[0][0].read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in gpl and "Version 3, 29 June 2007" in gpl
    apache = sources[1][0].read_text(encoding="utf-8")
    assert "Version 2.0, January 2004" in apache and "END OF TERMS AND CONDITIONS" in apache
    assert "PYTHON SOFTWARE FOUNDATION LICENSE" in sources[2][0].read_text(encoding="utf-8")
    parts = sources[3][0].read_text(encoding="utf-8")
    assert all(name in parts for name in ("Mersenne Twister", "expat", "zlib", "libmpdec"))


def test_user_files_lie_beside_the_program(tmp_path):
    licences = tmp_path / "licenses"
    licences.mkdir()
    (licences / "GPL-3.0.txt").write_text("text", encoding="utf-8")
    folder = tmp_path / "ARES"
    folder.mkdir()
    build.add_user_files(folder, licences)
    assert (folder / "LICENSE").is_file() and (folder / "THIRD_PARTY_NOTICES.txt").is_file()
    assert (folder / "licenses" / "GPL-3.0.txt").is_file()
    assert sorted(path.name for path in (folder / "examples").iterdir()) == sorted(
        path.name for path in (ROOT / "examples").iterdir())


def test_a_zip_has_the_folder_at_its_top(tmp_path):
    folder = tmp_path / "ARES"
    (folder / "_internal").mkdir(parents=True)
    (folder / "_internal" / "a.txt").write_text("a", encoding="utf-8")
    target = tmp_path / "out.zip"
    build.zip_folder(folder, target)
    with build.zipfile.ZipFile(target) as archive:
        assert archive.namelist() == ["ARES/_internal/a.txt"]


def windows_header(flags):
    """The start of a Windows program whose optional header's flags are flags."""
    header = bytearray(1024)
    struct.pack_into("<I", header, build.PE_POINTER, 0x100)
    struct.pack_into("<H", header, 0x100 + build.PE_FLAGS, flags)
    return bytes(header)


def test_control_flow_guard_is_turned_off_and_nothing_else():
    changed = build.without_guard(windows_header(0xC160))
    assert changed == windows_header(0x8160)
    assert build.without_guard(windows_header(0x8160)) == windows_header(0x8160)


def test_pyinstallers_starter_is_found_with_the_guard_python_runs_without():
    """Why the flag is cleared; if a new PyInstaller drops the guard, the step can go too."""
    python = Path(sys.base_prefix) / "python.exe"
    if sys.platform != "win32" or not python.is_file():
        pytest.skip("Windows only")
    header = python.read_bytes()[:4096]
    assert build.without_guard(header) == header


def test_a_quick_build_leaves_out_the_tests_and_the_single_file():
    args = build.options(["--quick"])
    assert args.skip_tests and args.only == "folder"
    assert build.options(["--quick", "--only", "file"]).only == "file"


def test_a_full_build_is_the_default():
    args = build.options([])
    assert not args.skip_tests and args.only is None


def test_a_library_under_a_licence_ares_cannot_carry_stays_out():
    assert {"readline", "curses"} <= set(build.EXCLUDED)


def test_the_package_of_a_system_library_is_read_from_dpkg():
    line = "libx11-6:amd64: /usr/lib/x86_64-linux-gnu/libX11.so.6"
    assert build.debian_package(line) == "libx11-6"
    assert build.debian_package("liba, libb: /usr/lib/liba.so.1") == "liba"


def test_the_tests_of_the_build_run_as_the_workflows_run_them():
    linux = build.test_commands("linux")
    assert all(command[0] == "xvfb-run" for command in linux)
    assert not any("auto" in command for command in linux)
    assert "auto" in build.test_commands("win32")[0]
    assert build.VIRTUAL_SCREEN in (WORKFLOWS / "tests.yml").read_text(encoding="utf-8")


def test_a_release_takes_only_the_packages():
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert "name: package-${{ matrix.tag }}" in text and "pattern: package-*" in text


def test_a_library_outside_the_system_is_found():
    listing = """bin/arm-none-eabi-as:
\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 1.0.0)
\t/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation (compatibility version 1.0)
\t/opt/local/lib/libz.1.dylib (compatibility version 1.0.0, current version 1.3.0)
"""
    assert build.foreign_libraries(listing) == ["/opt/local/lib/libz.1.dylib"]


# Each system ---------------------------------------------------------------------------------

@pytest.mark.parametrize("system, machine, tag", [
    ("Windows", "AMD64", "windows-x64"), ("Darwin", "arm64", "macos-arm64"),
    ("Darwin", "x86_64", "macos-x86_64"), ("Linux", "x86_64", "linux-x86_64")])
def test_each_system_has_its_toolchain_and_its_archive(system, machine, tag):
    assert toolchain.platform_tag(system, machine) == tag
    entry = TOOLCHAIN["platforms"][tag]
    assert TOOLCHAIN["version"].lower() in entry["url"].lower()
    assert len(entry["sha256"]) == 64 and entry["size"] > 0
    assert [name.rsplit("/", 1)[1] for name in entry["files"]] == build.tool_names(tag)
    assert tag in build.ARCHIVES


def test_a_system_without_a_toolchain_is_refused():
    with pytest.raises(toolchain.ToolchainMissingError):
        toolchain.platform_tag("Linux", "aarch64")


# The workflows -------------------------------------------------------------------------------

def test_the_tests_run_on_every_system():
    text = (WORKFLOWS / "tests.yml").read_text(encoding="utf-8")
    for tag in TAGS:
        assert f"tag: {tag}" in text
    assert '-n auto --max-worker-restart=1000 -m "not serial"' in text
    assert "pytest -q -m serial" in text
    assert 'python -m pytest -q -m "not serial"' in text        # one display: one test at a time


def test_the_release_builds_all_five_packages():
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    for name in ("ARES.exe", *build.ARCHIVES.values()):
        assert f"dist/{name}" in text
    assert "tools/build.py" in text


def test_a_check_package_has_its_own_folder_and_start(icon_paths, tmp_path):
    arguments = build.pyinstaller_arguments("linux-x86_64", "folder", icon_paths, tmp_path,
                                            tmp_path / "check", tmp_path / "start.py")
    assert arguments[-1] == str(tmp_path / "start.py")
    assert argument_values(arguments, "--specpath") == [str(tmp_path / "check")]


def test_a_release_carries_the_source_of_the_gnu_tools_and_of_unicorn():
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    for key in ("source", "engine_source"):
        assert key in text and key in TOOLCHAIN
    assert "sha256sum --check" in text


def test_only_a_run_started_by_hand_on_a_tag_publishes():
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert "inputs.publish && startsWith(github.ref, 'refs/tags/v')" in text
    assert "needs: [tests, build]" in text


@pytest.mark.parametrize("name", ["tests.yml", "release.yml"])
def test_a_workflow_runs_only_when_started_by_hand(name):
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    triggers = text[text.index("on:\n"):text.index("permissions:")]
    assert "workflow_dispatch:" in triggers
    assert "push:" not in triggers and "pull_request:" not in triggers and "schedule:" not in triggers


def test_the_packages_are_tried_where_they_are_built():
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert text.count("python tools/check_package.py") == 2 and "xvfb-run" in text
