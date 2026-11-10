# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Build the packages of ARES for this computer, in dist/.

usage: python tools/build.py [--quick] [--skip-tests] [--only file|folder]

  Windows   ARES.exe (one file) and ARES-windows.zip (a folder)
  macOS     ARES-macos-arm64.zip or ARES-macos-x86_64.zip (ARES.app)
  Linux     ARES-linux-x86_64.tar.gz (a folder with the program ARES)

It fetches the GNU assembler and linker if needed, runs the tests, makes the icons and runs
PyInstaller. Each package holds the assembler and linker, LICENSE, THIRD_PARTY_NOTICES.txt, the
licence texts that go with the bundled programs and the example programs. --only chooses one of
the two Windows packages. --quick leaves out the tests and, on Windows, the single file: a first
try of a build, to be followed by tools/check_package.py.
"""

import argparse
import importlib.util
import os
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import sysconfig
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import fetch_toolchain  # noqa: E402
import make_icons  # noqa: E402

from ares import APP_FULL_NAME, APP_NAME, __version__  # noqa: E402
from ares.toolchain import ASSEMBLER, LINKER, platform_tag  # noqa: E402

BUILD = ROOT / "build"
DIST = ROOT / "dist"
ENTRY = ROOT / "ares" / "__main__.py"
LICENCES = ROOT / "tools" / "licenses"
COPYRIGHT = "Copyright (c) 2026 The ARES Project"
BUNDLE_ID = "org.aresproject.ares"
SIZE_TARGET = 80 * 1000 * 1000              # bytes, for each package
# Tcl's time zones and the languages of its dates, three quarters of a package's files: ARES never
# formats a date, and ARES.exe would unpack them at every start.
LEFT_OUT = ("_tcl_data/tzdata/", "_tcl_data/msgs/")
# Nothing of these is used by the running program.
EXCLUDED = ("PIL", "pytest", "_pytest", "xdist", "execnet", "pip", "setuptools", "pkg_resources",
            "numpy", "lib2to3", "pydoc_data", "tkinter.test", "test", "ssl", "_ssl", "_hashlib",
            "readline", "curses", "_curses")
# Imported by name at run time, so PyInstaller does not see them: the tools, when the Tools menu
# opens them, and each engine's parts, such as Unicorn's for the ARM processor.
TOOLS_PACKAGE = "ares.gui.tools"
ENGINES = ("unicorn", "capstone")           # each loads its own library, from its folder lib
# System libraries on macOS; anything else the bundled tools needed would be missing on another Mac.
SYSTEM_LIBRARIES = ("/usr/lib/", "/System/Library/")
LINUX_LIBRARY = "libzstd.so.1"
VIRTUAL_SCREEN = "-screen 0 1920x1200x24 -dpi 96"
OWN_LIBRARIES = ("libpython",)              # Python's own, under its licence in the notices
# In a Windows program's header: where the optional header's flags lie, and the flag of Control Flow
# Guard, which PyInstaller's starter has and python.exe has not.
PE_POINTER = 0x3C
PE_FLAGS = 24 + 70
GUARD_FLAG = 0x4000
ARCHIVES = {"windows-x64": "ARES-windows.zip", "macos-arm64": "ARES-macos-arm64.zip",
            "macos-x86_64": "ARES-macos-x86_64.zip", "linux-x86_64": "ARES-linux-x86_64.tar.gz"}


def version_numbers(version=__version__):
    """The four numbers of a Windows version resource: 1.0 gives (1, 0, 0, 0)."""
    numbers = [int(part) for part in version.split(".")]
    return tuple((numbers + [0, 0, 0, 0])[:4])


def version_resource(version=__version__):
    """The text of the version information of ARES.exe, as PyInstaller reads it."""
    numbers = version_numbers(version)
    strings = {"CompanyName": "The ARES Project", "FileDescription": APP_FULL_NAME,
               "FileVersion": version, "InternalName": APP_NAME, "LegalCopyright": COPYRIGHT,
               "OriginalFilename": f"{APP_NAME}.exe", "ProductName": f"{APP_NAME} {version}",
               "ProductVersion": version}
    lines = ",\n".join(f"          StringStruct({key!r}, {value!r})"
                       for key, value in strings.items())
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
{lines}
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def tool_names(tag):
    """The file names of the assembler and the linker on the system called tag."""
    suffix = ".exe" if tag == "windows-x64" else ""
    return [name + suffix for name in (ASSEMBLER, LINKER)]


PYTHON_LICENCE_MARK = "PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2"


def python_licence(base=None, stdlib=None, version=None):
    """The licence text of the Python that builds ARES.

    The copy beside the standard library comes first: a distribution such as Miniconda keeps a
    LICENSE.txt of its own at the base of the installation. A file counts only if it is Python's.
    """
    base = Path(base or sys.base_prefix)
    stdlib = Path(stdlib or sysconfig.get_path("stdlib"))
    version = version or f"python{sys.version_info.major}.{sys.version_info.minor}"
    places = []
    for place in (stdlib / "LICENSE.txt", base / "LICENSE.txt",
                  base / "lib" / version / "LICENSE.txt", base / "Lib" / "LICENSE.txt"):
        if place not in places:
            places.append(place)
    for place in places:
        if place.is_file() and PYTHON_LICENCE_MARK in place.read_text(encoding="utf-8",
                                                                       errors="replace"):
            return place
    looked = "\n  ".join(str(place) for place in places)
    raise SystemExit(f"Python's licence was not found: no file containing \"{PYTHON_LICENCE_MARK}\" "
                     f"in any of these places:\n  {looked}")


def licence_files():
    """Each licence text that goes with a package: (source, name inside the licenses folder)."""
    return [(LICENCES / "GPL-3.0.txt", "GPL-3.0.txt"), (LICENCES / "Apache-2.0.txt", "Apache-2.0.txt"),
            (python_licence(), "Python-LICENSE.txt"),
            (LICENCES / "Python-parts.txt", "Python-parts.txt")]


def is_library(path):
    """True for a shared library of any system: unicorn.dll, libunicorn.2.dylib, libunicorn.so.2."""
    return path.suffix in (".dll", ".dylib") or ".so" in path.suffixes


def engine_libraries():
    """Each library the engines load: (path, its folder inside a package). They find it by a path
    worked out at run time, so PyInstaller cannot, and its patterns miss names such as
    libunicorn.so.2."""
    found = []
    for name in ENGINES:
        folder = Path(importlib.util.find_spec(name).origin).parent / "lib"
        libraries = [path for path in sorted(folder.iterdir()) if is_library(path)]
        if not libraries:
            raise SystemExit(f"no library in {folder}")
        found += [(path, f"{name}/lib") for path in libraries]
    return found


def data_arguments(licences):
    """PyInstaller's arguments for the files that are not programs; licences is a folder."""
    pairs = [(ROOT / "LICENSE", "."), (ROOT / "THIRD_PARTY_NOTICES.txt", "."),
             (ROOT / "ares" / "data" / "ares.ld", "ares/data"), (ROOT / "examples", "examples"),
             (licences, "licenses")]
    arguments = []
    for source, target in pairs:
        arguments += ["--add-data", f"{source}{os.pathsep}{target}"]
    return arguments


def pyinstaller_arguments(tag, kind, icons, licences, place=None, entry=ENTRY):
    """PyInstaller's command line for one package; kind is "file" or "folder"."""
    place = place or BUILD / kind
    arguments = ["--noupx", "--windowed", "--name", APP_NAME,
                 "--onefile" if kind == "file" else "--onedir",
                 "--specpath", str(place), "--paths", str(ROOT)]
    for name in (TOOLS_PACKAGE, *ENGINES):
        arguments += ["--collect-submodules", name]
    for name in tool_names(tag):
        path = ROOT / "vendor" / tag / "bin" / name
        arguments += ["--add-binary", f"{path}{os.pathsep}toolchain/bin"]
    for path, folder in engine_libraries():
        arguments += ["--add-binary", f"{path}{os.pathsep}{folder}"]
    arguments += data_arguments(licences)
    for name in EXCLUDED:
        arguments += ["--exclude-module", name]
    if tag == "windows-x64":
        arguments += ["--icon", str(icons[0]), "--version-file", str(place / "version.txt")]
    elif tag.startswith("macos"):
        arguments += ["--icon", str(icons[1]), "--osx-bundle-identifier", BUNDLE_ID]
    return arguments + [str(entry)]


def foreign_libraries(listing):
    """The libraries in the output of otool -L that a Mac without them would not have."""
    found = []
    for line in listing.splitlines()[1:]:
        match = re.match(r"\s*(\S+) \(", line)
        if match and not match.group(1).startswith(SYSTEM_LIBRARIES):
            found.append(match.group(1))
    return found


def without_guard(header):
    """The first bytes of a Windows program, with Control Flow Guard turned off.

    Unicorn runs code it generates: under the guard the whole process ends with 0xC0000409 as soon
    as a program is loaded. python.exe, which ARES runs under otherwise, has no guard either.
    """
    place = struct.unpack_from("<I", header, PE_POINTER)[0] + PE_FLAGS
    flags = struct.unpack_from("<H", header, place)[0]
    return header[:place] + struct.pack("<H", flags & ~GUARD_FLAG) + header[place + 2:]


def turn_guard_off(path):
    """Change the program at path as without_guard() says, and its header's checksum with it."""
    from PyInstaller.utils.win32 import winutils
    with open(path, "r+b") as f:
        header = f.read(4096)
        f.seek(0)
        f.write(without_guard(header))
    winutils.update_exe_pe_checksum(str(path))


def test_commands(system=sys.platform):
    """The commands of the whole test suite; the tests that measure time run alone, after the
    others. On Linux they map their windows on a virtual display, one test at a time."""
    pytest = [sys.executable, "-m", "pytest", "-q"]
    if system.startswith("linux"):
        display = ["xvfb-run", "-a", "-s", VIRTUAL_SCREEN]
        return [[*display, *pytest, "-m", "not serial"], [*display, *pytest, "-m", "serial"]]
    return [[*pytest, "-n", "auto", "-m", "not serial"], [*pytest, "-m", "serial"]]


def run_tests():
    env = dict(os.environ)
    if sys.platform.startswith("linux"):
        if shutil.which("xvfb-run") is None:
            raise SystemExit("the tests need xvfb-run; install xvfb, or use --skip-tests")
        env["ARES_VIRTUAL_DISPLAY"] = "1"
    for command in test_commands():
        subprocess.run(command, cwd=ROOT, env=env, check=True)


def leave_files_out(recipe):
    """PyInstaller's recipe for a package, as the text recipe, without the files of LEFT_OUT."""
    line = ("a.datas = [item for item in a.datas\n"
            f"           if not item[0].replace(chr(92), '/').startswith({LEFT_OUT!r})]\n")
    return recipe.replace("pyz = PYZ(", line + "pyz = PYZ(", 1)


def run_pyinstaller(arguments, place):
    """Build a package in the folder place: PyInstaller writes its recipe for the arguments, the
    recipe is changed, and PyInstaller carries it out."""
    subprocess.run([sys.executable, "-m", "PyInstaller.utils.cliutils.makespec", *arguments],
                   cwd=ROOT, check=True)
    recipe = place / f"{APP_NAME}.spec"
    recipe.write_text(leave_files_out(recipe.read_text(encoding="utf-8")), encoding="utf-8")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(place / "dist"), "--workpath", str(place / "work"),
                    str(recipe)], cwd=ROOT, check=True)


def add_user_files(folder, licences):
    """Put what users look for at the top of a folder package, beside the program."""
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.txt"):
        shutil.copy2(ROOT / name, folder / name)
    shutil.copytree(ROOT / "examples", folder / "examples")
    shutil.copytree(licences, folder / "licenses")


def check_contents(contents, tag):
    """A package's folder of files holds the engines' libraries, and the bundled assembler and
    linker start and need nothing from outside the system."""
    contents = Path(contents)
    for name in ENGINES:
        folder = contents / name / "lib"
        if not (folder.is_dir() and any(is_library(path) for path in folder.iterdir())):
            raise SystemExit(f"no library of {name} in {folder}")
    for name in tool_names(tag):
        path = contents / "toolchain" / "bin" / name
        result = subprocess.run([str(path), "--version"], capture_output=True, text=True,
                                timeout=60)
        if result.returncode != 0:
            raise SystemExit(f"{path} does not start:\n{result.stderr}")
        print(f"  {result.stdout.splitlines()[0]}")
        if tag.startswith("macos"):
            listing = subprocess.run(["otool", "-L", str(path)], capture_output=True, text=True,
                                     check=True).stdout
            foreign = foreign_libraries(listing)
            if foreign:
                raise SystemExit(f"{path} needs {', '.join(foreign)}")


def report(path):
    size = path.stat().st_size
    print(f"{path}: {size / 1e6:.1f} MB")
    if size > SIZE_TARGET:
        print(f"  larger than the target of {SIZE_TARGET / 1e6:.0f} MB")


def zip_folder(folder, target):
    """Pack folder into the zip file target, with the folder's own name at the top."""
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(folder.parent))


def build_windows(tag, only, icons, licences):
    if only != "folder":
        place = BUILD / "file"
        place.mkdir(parents=True, exist_ok=True)
        (place / "version.txt").write_text(version_resource(), encoding="utf-8")
        run_pyinstaller(pyinstaller_arguments(tag, "file", icons, licences), place)
        target = DIST / f"{APP_NAME}.exe"
        shutil.copy2(place / "dist" / target.name, target)
        turn_guard_off(target)
        report(target)
    if only != "file":
        place = BUILD / "folder"
        place.mkdir(parents=True, exist_ok=True)
        (place / "version.txt").write_text(version_resource(), encoding="utf-8")
        run_pyinstaller(pyinstaller_arguments(tag, "folder", icons, licences), place)
        folder = place / "dist" / APP_NAME
        turn_guard_off(folder / f"{APP_NAME}.exe")
        check_contents(folder / "_internal", tag)
        add_user_files(folder, licences)
        target = DIST / ARCHIVES[tag]
        zip_folder(folder, target)
        report(target)


def debian_package(listing):
    """The first package in a line of dpkg -S: libx11-6:amd64: /usr/lib/.../libX11.so.6."""
    return listing.split(":", 1)[0].split(",")[0].strip()


def copy_system_licences(contents, target):
    """Put the licence of each system library in the folder contents into the folder target, as
    <package>.txt. The build stops if one is missing, where dpkg can tell; elsewhere the person
    who builds has to add them."""
    if shutil.which("dpkg") is None:
        print("  no dpkg here: add the licences of the libraries in the package yourself")
        return
    for library in sorted(contents.glob("lib*.so*")):
        if library.name.startswith(OWN_LIBRARIES):
            continue
        found = subprocess.run(["dpkg", "-S", f"*/{library.name}"], capture_output=True, text=True,
                               check=False)
        if found.returncode != 0 or not found.stdout:
            raise SystemExit(f"no system package has {library.name}")
        package = debian_package(found.stdout.splitlines()[0])
        licence = Path("/usr/share/doc") / package / "copyright"
        if not licence.is_file():
            raise SystemExit(f"no licence of {package}, for {library.name}")
        shutil.copy2(licence, target / f"{package}.txt")


def build_linux(tag, icons, licences):
    (BUILD / "folder").mkdir(parents=True, exist_ok=True)
    run_pyinstaller(pyinstaller_arguments(tag, "folder", icons, licences), BUILD / "folder")
    folder = BUILD / "folder" / "dist" / APP_NAME
    # The tools need this library, and find it where ARES's start-up points LD_LIBRARY_PATH.
    if not (folder / "_internal" / LINUX_LIBRARY).is_file():
        raise SystemExit(f"{LINUX_LIBRARY} is not in the package")
    check_contents(folder / "_internal", tag)
    add_user_files(folder, licences)
    copy_system_licences(folder / "_internal", folder / "licenses")
    target = DIST / ARCHIVES[tag]
    with tarfile.open(target, "w:gz") as archive:
        archive.add(folder, arcname=APP_NAME)
    report(target)


def describe_bundle(plist):
    """The entries of the Info.plist of ARES.app that PyInstaller's command line cannot set."""
    plist.update({"CFBundleName": APP_NAME, "CFBundleDisplayName": APP_NAME,
                  "CFBundleShortVersionString": __version__, "CFBundleVersion": __version__,
                  "NSHumanReadableCopyright": COPYRIGHT, "NSHighResolutionCapable": True})
    return plist


def build_macos(tag, icons, licences):
    (BUILD / "folder").mkdir(parents=True, exist_ok=True)
    run_pyinstaller(pyinstaller_arguments(tag, "folder", icons, licences), BUILD / "folder")
    app = BUILD / "folder" / "dist" / f"{APP_NAME}.app"
    check_contents(app / "Contents" / "Frameworks", tag)
    info = app / "Contents" / "Info.plist"
    with open(info, "rb") as f:
        plist = plistlib.load(f)
    with open(info, "wb") as f:
        plistlib.dump(describe_bundle(plist), f)
    # Ad hoc: Apple Silicon starts nothing unsigned, and the edit above broke the first signature.
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    target = DIST / ARCHIVES[tag]
    subprocess.run(["ditto", "-c", "-k", "--keepParent", str(app), str(target)], check=True)
    report(target)


def options(argv=None):
    """The command line's options."""
    parser = argparse.ArgumentParser(description="Build the packages of ARES for this computer.")
    parser.add_argument("--quick", action="store_true",
                        help="no tests and, on Windows, only the folder package")
    parser.add_argument("--skip-tests", action="store_true", help="do not run the tests first")
    parser.add_argument("--only", choices=("file", "folder"),
                        help="on Windows, build only the one-file or the folder package")
    args = parser.parse_args(argv)
    if args.quick:
        args.skip_tests = True
        args.only = args.only or "folder"
    return args


def main(argv=None):
    args = options(argv)

    tag = platform_tag()
    fetch_toolchain.main(["--platform", tag])
    if not args.skip_tests:
        run_tests()
    DIST.mkdir(exist_ok=True)
    icons = make_icons.write_all(BUILD / "icons")
    licences = BUILD / "licenses"
    shutil.rmtree(licences, ignore_errors=True)
    licences.mkdir(parents=True)
    for source, name in licence_files():
        shutil.copy2(source, licences / name)
    if tag == "windows-x64":
        build_windows(tag, args.only, icons, licences)
    elif tag.startswith("macos"):
        build_macos(tag, icons, licences)
    else:
        build_linux(tag, icons, licences)
    return 0


if __name__ == "__main__":
    sys.exit(main())
