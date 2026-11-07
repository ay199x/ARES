# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Try the packages of dist/ on this computer, after tools/build.py.

usage: python tools/check_package.py

A package takes no script from outside. So a second package is made with the same options, with
tools/package_entry.py as its start: it runs the programs of tests/programs and examples/ with
ARES's own commands, opens every tool, and its report is compared with the expected output.
Then each real package is unpacked and started with hello.s on its command line, assembling it
on opening: it must still be running after some seconds. Pictures of the screen are left in
build/check/pictures. Each run sees a bare environment and settings of its own.
"""

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import build  # noqa: E402

from ares import APP_NAME  # noqa: E402
from ares.console import FINISHED  # noqa: E402
from ares.toolchain import platform_tag  # noqa: E402

PLACE = build.BUILD / "check"
PICTURES = PLACE / "pictures"
ENTRY = ROOT / "tools" / "package_entry.py"
PROGRAMS = ROOT / "tests" / "programs"
EXAMPLES = ROOT / "examples"
RUN_LIMIT = 300                 # seconds for all the programs of a package
ALIVE = 12                      # seconds a real package must keep running
KEYS_EXAMPLE = "keyboard_echo.s"    # reads the keys one by one: no line to type
# Where the mouse goes in the window, at 96 dots per inch: the title File, then Open Example.
MOUSE_STEPS = (("file-menu", 18, 12, True), ("submenu", 60, 69, False))


def example_table():
    """{file: (what is typed, what Run I/O shows)}, the table of tests/test_examples.py."""
    tree = ast.parse((ROOT / "tests" / "test_examples.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "EXPECTED":
            return ast.literal_eval(node.value)
    raise SystemExit("no table of the examples")


def list_of_programs():
    """Each program to run: its name, path, what is typed, and what it must show."""
    programs = []
    for path in sorted(PROGRAMS.glob("*.s")):
        expected = path.with_suffix(".out")
        if expected.is_file():
            typed = path.with_suffix(".in")
            programs.append({
                "name": f"programs/{path.name}", "path": str(path), "keys": False,
                "lines": typed.read_text().splitlines() if typed.is_file() else [],
                "expected": expected.read_text().replace("\r\n", "\n")})
    for name, (typed, shown) in example_table().items():
        programs.append({"name": f"examples/{name}", "path": str(EXAMPLES / name),
                         "keys": name == KEYS_EXAMPLE, "lines": typed.splitlines(),
                         "starts_with": shown})
    return programs


def without_typed_lines(result, entry):
    """What the program itself showed: Run I/O shows the typed lines too."""
    shown = result.get("output", "")
    if not entry["keys"]:
        for start, line in reversed(list(zip(result.get("starts", []), entry["lines"]))):
            shown = shown[:start] + shown[start + len(line) + 1:]
    return shown


def program_problem(entry, result):
    """What is wrong with what a program did; None when all is as expected."""
    if result.get("failed"):
        return result["failed"]
    if not result.get("assembled"):
        return f"not assembled: {result.get('messages')}"
    if result.get("error"):
        return f"ended with: {result['error']}"
    shown = without_typed_lines(result, entry)
    if "expected" in entry:
        return None if shown == entry["expected"] else f"showed {shown!r}"
    good = shown.rstrip() == entry["starts_with"] + FINISHED
    return None if good else f"showed {shown!r}"


def report_problems(report, programs):
    """Every problem a report tells of, as lines."""
    problems = []
    for key in ("failed",):
        if key in report:
            problems.append(report[key])
    if not report.get("done"):
        problems.append("the list was not finished")
    if not report.get("frozen"):
        problems.append("it did not run as a package")
    if report.get("internal errors"):
        problems.append(f"{report['internal errors']} internal errors in ARES Messages")
    missing = set(example_table()) - set(report.get("examples", ()))
    if missing:
        problems.append(f"File > Open Example lacks {sorted(missing)}")
    for entry in programs:
        result = report["programs"].get(entry["name"], {})
        problem = program_problem(entry, result)
        if problem:
            problems.append(f"{entry['name']}: {problem}")
    for name, state in report.get("tools", {}).items():
        if state != "opened":
            problems.append(f"{name}: {state}")
    for name, size in report.get("documents", {}).items():
        if size < 500:
            problems.append(f"{name}: only {size} characters")
    return problems


def bare_environment(folder):
    """The environment of a run: the system's folders only, and settings inside folder."""
    keep = ("SystemRoot", "SystemDrive", "windir", "TEMP", "TMP", "TMPDIR", "USERPROFILE", "USER",
            "USERNAME", "LOGNAME", "DISPLAY", "XAUTHORITY", "LANG")
    env = {key: os.environ[key] for key in keep if key in os.environ}
    home = folder / "home"
    (home / "config").mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        system = os.environ["SystemRoot"]
        env.update(PATH=rf"{system}\System32;{system}", APPDATA=str(home / "config"))
    else:
        env.update(PATH="/usr/bin:/bin", HOME=str(home), XDG_CONFIG_HOME=str(home / "config"))
    return env


def settings_file(env):
    """Where ARES run in env keeps its settings."""
    if sys.platform == "win32":
        return Path(env["APPDATA"]) / "ARES" / "settings.json"
    if sys.platform == "darwin":
        return Path(env["HOME"]) / "Library" / "Application Support" / "ARES" / "settings.json"
    return Path(env["XDG_CONFIG_HOME"]) / "ARES" / "settings.json"


def picture(name):
    """A picture of the screen, if this system gives one."""
    try:
        from PIL import ImageGrab
        PICTURES.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab().save(PICTURES / f"{name}.png")
    except Exception as e:
        print(f"  no picture {name}: {e}")


def stop(process):
    """End a running package, with what it started."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True,
                       check=False)
    else:
        process.terminate()
    try:
        process.wait(10)
    except subprocess.TimeoutExpired:
        process.kill()


def program_of(folder, tag):
    """The program inside the folder that holds a built package."""
    if tag.startswith("macos"):
        return folder / f"{APP_NAME}.app" / "Contents" / "MacOS" / APP_NAME
    return folder / APP_NAME / (f"{APP_NAME}.exe" if tag == "windows-x64" else APP_NAME)


def make_check_packages(tag):
    """The packages with the list's start; the paths of their programs."""
    icons = (build.BUILD / "icons" / "ARES.ico", build.BUILD / "icons" / "ARES.icns")
    made = {}
    for kind in ("file", "folder") if tag == "windows-x64" else ("folder",):
        place = PLACE / kind
        place.mkdir(parents=True, exist_ok=True)
        (place / "version.txt").write_text(build.version_resource(), encoding="utf-8")
        build.run_pyinstaller(build.pyinstaller_arguments(
            tag, kind, icons, build.BUILD / "licenses", place, ENTRY), place)
        if kind == "file":
            program = place / "dist" / f"{APP_NAME}.exe"
        else:
            program = program_of(place / "dist", tag)
        if tag == "windows-x64":
            build.turn_guard_off(program)
        made[kind] = program
    return made


def run_list(name, program):
    """Run the programs through a package; the problems found."""
    programs = list_of_programs()
    work = Path(tempfile.mkdtemp(prefix="ares-list-"))
    env = bare_environment(work)
    report_file = PLACE / f"{name}-report.json"
    report_file.unlink(missing_ok=True)
    list_file = work / "list.json"
    list_file.write_text(json.dumps({"programs": programs, "report": str(report_file)}),
                         encoding="utf-8")
    env["ARES_CHECK_LIST"] = str(list_file)
    begin = time.perf_counter()
    process = subprocess.Popen([str(program)], env=env, cwd=work)
    try:
        process.wait(RUN_LIMIT)
    except subprocess.TimeoutExpired:
        picture(f"{name}-stuck")
        stop(process)
        return [f"{name}: still running after {RUN_LIMIT} s"]
    print(f"{name}: {time.perf_counter() - begin:.1f} s, exit code {process.returncode}")
    if not report_file.is_file():
        return [f"{name}: no report, exit code {process.returncode}"]
    if process.returncode != 0:
        return [f"{name}: exit code {process.returncode}"]
    report = json.loads(report_file.read_text(encoding="utf-8"))
    problems = report_problems(report, programs)
    good = len(programs) - sum(1 for line in problems if line.startswith(("programs/", "examples/")))
    print(f"  {good} of {len(programs)} programs as expected; {len(report['tools'])} tools; "
          f"toolchain {report.get('toolchain')}")
    return [f"{name}: {line}" for line in problems]


def unpacked(tag, work):
    """Unpack the packages of dist/ into work, as a user would; {name: program}."""
    archive = build.DIST / build.ARCHIVES[tag]
    if tag == "windows-x64":
        with zipfile.ZipFile(archive) as packed:
            packed.extractall(work)
        one_file = work / "single"
        one_file.mkdir()
        shutil.copy2(build.DIST / f"{APP_NAME}.exe", one_file)
        return {"file": one_file / f"{APP_NAME}.exe", "folder": program_of(work, tag)}
    if tag.startswith("macos"):
        subprocess.run(["ditto", "-x", "-k", str(archive), str(work)], check=True)
        return {"app": program_of(work, tag)}
    with tarfile.open(archive) as packed:
        packed.extractall(work)
    return {"folder": program_of(work, tag)}


def xdotool(*arguments):
    """The output of xdotool, which gives a real package real mouse and key events."""
    return subprocess.run(["xdotool", *map(str, arguments)], capture_output=True, text=True,
                          check=True, timeout=30).stdout


def has_window(title):
    """Whether a window with title in its title is on the screen; None where nothing can tell."""
    if sys.platform == "win32":
        import ctypes
        titles = []
        user32 = ctypes.windll.user32
        kind = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def visit(window, _):
            text = ctypes.create_unicode_buffer(300)
            user32.GetWindowTextW(ctypes.c_void_p(window), text, 300)
            titles.append(text.value)
            return True
        user32.EnumWindows(kind(visit), None)
        return any(title in text for text in titles)
    if shutil.which("xdotool"):
        found = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", title],
                               capture_output=True, text=True, timeout=30, check=False)
        return bool(found.stdout.strip())
    return None


def try_the_mouse(name):
    """With a window manager on the display: open File and its submenu with the mouse, leave
    them with Escape, and run the program with F5. The pictures tell how it went."""
    window = xdotool("search", "--onlyvisible", "--name", "hello.s").split()[-1]
    xdotool("windowactivate", "--sync", window)
    for picture_name, x, y, press in MOUSE_STEPS:
        xdotool("mousemove", "--window", window, x, y)
        if press:
            xdotool("click", 1)
        time.sleep(1)
        picture(f"{name}-{picture_name}")
    xdotool("key", "Escape", "Escape", "Escape")
    time.sleep(0.5)
    xdotool("key", "F5")
    time.sleep(2)
    picture(f"{name}-ran")


def start_real(name, program):
    """Start a real package with hello.s; the problems found."""
    work = Path(tempfile.mkdtemp(prefix="ares-start-"))
    env = bare_environment(work)
    settings = settings_file(env)
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text('{"assemble_on_open": true}', encoding="utf-8")
    process = subprocess.Popen([str(program), str(EXAMPLES / "hello.s")], env=env, cwd=work)
    problems = []
    try:
        time.sleep(ALIVE)
        picture(f"{name}-real")
        ended = process.poll()
        if ended is not None:
            return [f"{name}: the real package ended by itself, exit code {ended}"]
        if has_window("hello.s") is False:
            problems.append(f"{name}: the real package shows no window for hello.s")
        elif shutil.which("xdotool"):
            try_the_mouse(name)
    except (subprocess.SubprocessError, OSError) as e:
        problems.append(f"{name}: {e}")
    finally:
        ended = process.poll()
        stop(process)
    if ended is not None:
        problems.append(f"{name}: the real package ended by itself, exit code {ended}")
    print(f"{name}: the real package ran for {ALIVE} s with hello.s assembled on opening")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description="Try the packages of dist/ on this computer.")
    parser.parse_args(argv)
    tag = platform_tag()
    PLACE.mkdir(parents=True, exist_ok=True)
    problems = []
    for kind, program in make_check_packages(tag).items():
        problems += run_list(f"list-{kind}", program)
    work = Path(tempfile.mkdtemp(prefix="ares-unpacked-"))
    for name, program in unpacked(tag, work).items():
        problems += start_real(name, program)
    for line in problems:
        print("PROBLEM:", line)
    print("packages as expected" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
