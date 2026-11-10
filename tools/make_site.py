# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Make the website of ARES in docs/ from ARES's own sources, so that it says what the program does.

Six main pages share a column of buttons: Home, Features, Download, License, Papers and Help & Info.
The Help & Info pages, in help/, share a row of links and are made from the blocks of ARES's own Help
window (ares.helptext, the tools' help texts), so they stay in step with the program. The pictures
in docs/images/features/ and docs/images/tools/ are captures of ARES, kept in docs/ as they are;
this script makes the favicon, the icons and the link preview. Run it again after any change to its
sources, and commit what it writes:

usage: python tools/make_site.py [--out FOLDER]

It needs Pillow (requirements-dev.txt). GitHub Pages publishes docs/ of the main branch.
"""

import argparse
import html
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from ares import APP_FULL_NAME, APP_NAME, credits, helptext  # noqa: E402
from ares.gui import icons  # noqa: E402
from ares.gui.app import MENUS  # noqa: E402
from ares.gui.helpwindow import page_blocks, tool_entries  # noqa: E402
from ares.gui.menubar import access_letter  # noqa: E402

DOCS = ROOT / "docs"
SITE = "https://ay199x.github.io/ARES/"
REPOSITORY = "https://github.com/ay199x/ARES"
RELEASES = REPOSITORY + "/releases"
DOWNLOAD = RELEASES + "/latest/download/"
SOURCE_FILE = REPOSITORY + "/blob/main/"
SAMPLE = "sorting.s"                    # the sample program of Home and Download, in examples/
DYNARMIC = "https://doi.org/10.1145/3787109.3815320"

# The release the pages offer: its version and month, and its packages, in the order of the
# Download page: (system, file, its size in bytes when it is on the release, else None).
RELEASE = "1.0"
RELEASE_MONTH = "November 2026"
RELEASE_SHORT = "Nov. 2026"
PACKAGES = (
    ("Windows, one file", "ARES.exe", 15580334),
    ("Windows, a folder", "ARES-windows.zip", 15461752),
    ("macOS, Apple Silicon", "ARES-macos-arm64.zip", 17093790),
    ("macOS, Intel", "ARES-macos-x86_64.zip", None),
    ("Linux", "ARES-linux-x86_64.tar.gz", None),
)
RELEASED = tuple(name for _, name, release in PACKAGES if release)

HELMET = "ares-helmet.png"              # the README's helmet, the 32 grid at 4x (128 pixels)
SCREENSHOT = "screenshot.png"           # the README's picture of the window
PREVIEW_SIZE = (1200, 630)
PREVIEW_ALT = "The helmet of Ares beside the ARES window"

# The colours: ARES's light grays and blues (ares.gui.style), laid out as the pages of old
# simulators' sites were.
FACE, TAB, TAB_BORDER, TITLE, NAVY = "#EEEEEE", "#C8DDF2", "#6382BF", "#B8CFE5", "#24406F"

# The main pages: (file, button, title, description).
MAIN = (
    ("index.html", "Home", f"{APP_NAME} - {APP_FULL_NAME}",
     "ARES, the ARM Educational Simulator: an IDE for ARMv7 assembly language programming, "
     "for teaching. Free and open source, for Windows and macOS."),
    ("features.html", "Features", "ARES Features",
     "The features of ARES: an editor, run, step and backstep, breakpoints, editable registers "
     "and memory, system calls, the DE1-SoC's devices and teaching tools."),
    ("download.html", "Download", "Download ARES",
     "Download ARES 1.0 for Windows or macOS: the packages, how to run each, the requirements "
     "and the source code."),
    ("license.html", "License", "ARES License",
     "ARES is open-source software under the GNU General Public License, version 2 or later."),
    ("papers.html", "Papers", "ARES Papers",
     "Who developed ARES, and the published work it builds on: the DynARMic paper of "
     "GLSVLSI '26."),
)
# The Help & Info pages: (file, link, heading, description). help/intro.html is the button's.
HELP = (
    ("intro.html", "Intro", "Introduction",
     "An introduction to ARES: what it is, why it was made, and a first program."),
    ("settings.html", "Settings", "Settings",
     "The settings of ARES, in its Settings menu, and what each one does."),
    ("syscalls.html", "Syscalls", "System calls",
     "The system calls of ARES: SVC #N, the full table of services, their arguments and results."),
    ("ide.html", "IDE", "The window and the editor",
     "The ARES window and its editor: files, editing, assembling and the capital-letters rule."),
    ("debugging.html", "Debugging", "Debugging",
     "Debugging in ARES: run, step, backstep, breakpoints, memory, and how a program ends."),
    ("tools.html", "Tools", "Tools",
     "The teaching tools of ARES, the ARM X-Ray first, each with what it shows and how to use it."),
    ("shortcuts.html", "Keyboard shortcuts", "Keyboard shortcuts",
     "The keyboard shortcuts of ARES: its commands, menus, register tables and Help window."),
    ("history.html", "History", "Release history",
     "The release history of ARES: what release 1.0 contains."),
    ("limits.html", "Limitations", "Limitations",
     "What ARES does not do, and the instructions its lists leave out."),
    ("acknowledgements.html", "Acknowledgements", "Acknowledgements",
     "The credits of ARES, and the programs, papers and textbook it is built on."),
)
# The Help window's tab of each Help & Info page made from it.
HELP_TABS = {"intro.html": "Intro", "settings.html": "Settings", "syscalls.html": "Syscalls",
             "ide.html": "IDE", "debugging.html": "Debugging",
             "shortcuts.html": "Keyboard shortcuts", "limits.html": "Limits",
             "acknowledgements.html": "Acknowledgements"}
# The capture of each tool, in docs/images/tools/.
TOOL_PICTURES = {"ARM X-Ray": "xray", "BHT Simulator": "bht", "Bitmap Display": "bitmap",
                 "Data Cache Simulator": "cache", "Digital Lab Sim": "labsim",
                 "Dynamic Instruction Counter": "counter",
                 "Floating Point Representation": "fpr",
                 "Keyboard and Display MMIO Simulator": "mmio",
                 "Memory Reference Visualization": "memref"}

esc = html.escape


def label_of(text):
    return access_letter(text)[0]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# Text -------------------------------------------------------------------------------------------

def help_words(text):
    """A Help text as HTML: its parts in backquotes in the font of programs."""
    return "".join(f"<code>{esc(part)}</code>" if code else esc(part)
                   for part, code in helptext.spans(text))


def markdown_words(text):
    """The inline Markdown of README.md as HTML: `code`, **bold**, *italic* and [links](url)."""
    out = []
    for i, part in enumerate(text.split("`")):
        if i % 2:
            out.append(f"<code>{esc(part)}</code>")
            continue
        part = esc(part, quote=False)
        part = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", part)
        part = re.sub(r"\*(.+?)\*", r"<i>\1</i>", part)
        part = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                      lambda m: f'<a href="{esc(html.unescape(m.group(2)))}">{m.group(1)}</a>',
                      part)
        out.append(part)
    return "".join(out)


class Readme:
    """The parts of README.md that the pages show."""

    def __init__(self, text):
        self.text = text

    def section(self, title):
        begin = self.text.index(f"\n## {title}\n") + len(f"\n## {title}\n")
        end = self.text.find("\n## ", begin)
        return self.text[begin:end if end >= 0 else None].strip("\n")

    def bullets(self, title):
        items = []
        for line in self.section(title).split("\n"):
            if line.startswith("- "):
                items.append(line[2:].strip())
            elif line.startswith("  ") and items and line.strip():
                items[-1] += " " + line.strip()
        return items

    def packages(self):
        """The download table: {file: what it is for}."""
        rows = {}
        for line in self.section("Download").split("\n"):
            match = re.match(r"\| `([^`]+)` \| (.+?) \|$", line)
            if match:
                rows[match.group(1)] = match.group(2)
        return rows

    def first_start(self):
        """The first-start notes: {system: the note, without its system's name}."""
        notes = {}
        for item in self.bullets("Download"):
            match = re.match(r"\*\*(\w+):\*\* (.+)", item)
            if match:
                notes[match.group(1)] = match.group(2)
        return notes

    def program(self, title):
        return self.section(title).split("```")[1].strip("\n")


def readme():
    return Readme((ROOT / "README.md").read_text(encoding="utf-8"))


def size_text(size):
    return f"{size / 1024 / 1024:.1f} MB"


# Pieces of pages --------------------------------------------------------------------------------

def head(title, description, url, root=""):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{url}">
<link rel="icon" href="{root}favicon.ico" sizes="16x16 32x32 48x48">
<link rel="icon" type="image/png" sizes="192x192" href="{root}images/icon-192.png">
<link rel="apple-touch-icon" href="{root}images/apple-touch-icon.png">
<link rel="stylesheet" href="{root}style.css">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{APP_NAME}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE}images/preview.png">
<meta property="og:image:width" content="{PREVIEW_SIZE[0]}">
<meta property="og:image:height" content="{PREVIEW_SIZE[1]}">
<meta property="og:image:alt" content="{PREVIEW_ALT}">
<meta name="twitter:card" content="summary_large_image">
</head>
"""


def main_page(name, body):
    """A main page: the helmet and the column of buttons at the left, the content at the right."""
    _, button, title, description = next(page for page in MAIN if page[0] == name)
    buttons = []
    for target, label, *_ in MAIN:
        here = ' aria-current="page"' if target == name else ""
        buttons.append(f'<li><a class="button" href="{target}"{here}>{label}</a></li>')
    buttons.append('<li><a class="button" href="help/intro.html">Help &amp; Info</a></li>')
    url = SITE + ("" if name == "index.html" else name)
    return head(title, description, url) + f"""<body class="main">
<div class="page">
<div class="masthead"></div>
<div class="columns">
<nav class="left" aria-label="Site">
<img class="helmet" src="{HELMET}" width="128" height="128" alt="The helmet of Ares, the icon of ARES">
<ul class="buttons">
{chr(10).join(buttons)}
</ul>
</nav>
<main class="content">
{body}
</main>
</div>
<p class="footer">Copyright (c) 2026 The ARES Project</p>
</div>
</body>
</html>
"""


def help_page(name, body):
    """A Help & Info page: the row of links, the name, the release and its month, the title."""
    _, link, heading, description = next(page for page in HELP if page[0] == name)
    links = []
    for target, label, *_ in HELP:
        here = ' aria-current="page"' if target == name else ""
        links.append(f'<a href="{target}"{here}><i>{esc(label)}</i></a>')
    links.append('<a class="home" href="../index.html"><i>ARES&nbsp;home</i></a>')
    return head(f"ARES Help - {heading}", description, f"{SITE}help/{name}", "../") + f"""\
<body class="help">
<nav class="links" aria-label="Help &amp; Info">
{chr(10).join(links)}
</nav>
<header class="title">
<p class="name">{APP_NAME} - {APP_FULL_NAME}</p>
<p>Release {RELEASE}</p>
<p>{RELEASE_MONTH}</p>
<h1>{esc(heading)}</h1>
</header>
<main>
{body}
</main>
</body>
</html>
"""


def section(ident, body):
    """A part of a page: its opening tag alone on its line, so that a line search can tell which
    part a line is in (the cleanliness check does)."""
    return f'<section id="{ident}">\n{body}\n</section>'


def picture(source, alt, root="", css=""):
    """An img with its size, read from the file in docs/."""
    with Image.open(DOCS / source) as image:
        width, height = image.size
    kind = f' class="{css}"' if css else ""
    return (f'<img{kind} src="{root}{source}" width="{width}" height="{height}" '
            f'alt="{esc(alt)}">')


def code(text):
    return f"<pre>{esc(text)}</pre>"


def blocks_html(blocks):
    """Blocks of the Help as HTML; headings are h2, as a Help page's parts."""
    out, bullets = [], []

    def flush():
        if bullets:
            out.append("<ul>\n" + "\n".join(bullets) + "\n</ul>")
            bullets.clear()

    for block in blocks:
        if block.kind != helptext.BULLET:
            flush()
        if block.kind == helptext.TITLE:
            continue                    # the page's header says the name and the version
        if block.kind == helptext.HEADING:
            out.append(f"<h2>{help_words(block.text)}</h2>")
        elif block.kind == helptext.PARAGRAPH:
            out.append(f"<p>{help_words(block.text)}</p>")
        elif block.kind == helptext.BULLET:
            bullets.append(f"<li>{help_words(block.text)}</li>")
        elif block.kind == helptext.CODE:
            out.append(code(block.text))
        elif block.kind == helptext.TABLE:
            out.append(table_html(block.rows))
        else:
            raise ValueError(f"unknown block {block.kind}")
    flush()
    return "\n".join(out)


def table_html(rows):
    head_row = "".join(f"<th>{help_words(cell)}</th>" for cell in rows[0])
    body = "\n".join("<tr>" + "".join(f"<td>{help_words(cell)}</td>" for cell in row) + "</tr>"
                     for row in rows[1:])
    return f'<div class="table"><table>\n<tr>{head_row}</tr>\n{body}\n</table></div>'


def heading():
    """The heading of Home and Papers: the name, then what ARES is."""
    return (f"<h1>{APP_NAME} <small>({APP_FULL_NAME})</small></h1>\n"
            f'<p class="subtitle">An IDE for ARMv7 Assembly Language Programming</p>')


def sample_line():
    return (f'<i>A sample program to try in ARES, one of its examples:</i> '
            f'<a href="{SOURCE_FILE}examples/{SAMPLE}">{SAMPLE}</a>')


# The main pages ---------------------------------------------------------------------------------

OVERVIEW = (
    "A window you work with the mouse, with an editor built in",
    "The GNU assembler and linker included: nothing else to install",
    "Registers you edit in place, like the cells of a spreadsheet, and a view of memory",
    "Values shown in hexadecimal or in decimal",
    "Floating-point registers, and a bit-by-bit view of 32-bit floating-point numbers",
    "Runs at a speed you choose, one instruction at a time, and backwards",
    "System calls for text and number input and output, files and dialogs",
    "Teaching tools in their own windows, such as the ARM X-Ray datapath animation and a data "
    "cache simulator",
)


HOME_INTRO = ("<p>ARES is a lightweight interactive development environment (IDE) for "
              "programming in ARMv7 assembly language, intended for students and teachers of "
              "computer organization. It assembles programs written for CPUlator's ARMv7 DE1-SoC "
              "system with the same GNU assembler, once their instructions and registers are in "
              "capitals (Edit &gt; Capitalize Instructions does that), and simulates the DE1-SoC "
              "computer they run on, with its JTAG UART, LEDs, switches and seven-segment "
              "displays.</p>")


def home():
    overview = "\n".join(f"<li>{esc(item)}</li>" for item in OVERVIEW)
    intro = section("intro", HOME_INTRO)
    body = f"""{heading()}
{intro}
<p class="download"><a href="download.html">Download ARES {RELEASE} software!</a> \
({RELEASE_SHORT})</p>
<ul>
<li>{sample_line()}</li>
</ul>
<p><a href="features.html">ARES features overview:</a></p>
<ul>
{overview}
</ul>"""
    return main_page("index.html", body)


def features():
    pictures = {name: picture(f"images/features/{name}.png", alt) for name, alt in (
        ("run-step-backstep", "The Go, Step and Backstep buttons of the toolbar"),
        ("breakpoints", "The Bkpt column of check boxes beside the instructions of the Text "
                        "Segment"),
        ("run-speed", "The Run speed slider, at its maximum: no interaction"),
        ("xray", "The ARM X-Ray window: the single-cycle datapath with the paths in use in "
                 "dark blue"),
        ("tools-menu", "The Tools menu: ARM X-Ray, BHT Simulator, Bitmap Display, Data Cache "
                       "Simulator, Digital Lab Sim, Dynamic Instruction Counter, Floating Point "
                       "Representation, Keyboard and Display MMIO Simulator, Memory Reference "
                       "Visualization and Memory Map"))}
    items = (
        "A window you work with the mouse, with an editor built in. These three buttons of the "
        "toolbar run the program, step one instruction, and step one instruction back.<br>"
        + pictures["run-step-backstep"],
        "Integrated editor, featuring multiple file-editing tabs, syntax colouring, find and "
        "replace, and line numbers. Errors from the assembler point to their lines.",
        "Breakpoints: a click on the check box beside an instruction sets or clears one<br>"
        + pictures["breakpoints"],
        "Registers you edit in place, like the cells of a spreadsheet; memory shown in "
        "hexadecimal, decimal or ASCII",
        "Values shown in hexadecimal or in decimal",
        "Floating point registers S0 to S31 and D0 to D31, in the Coproc 10 and Coproc 11 tabs, "
        "with FPSCR",
        "A run speed you choose, up to full speed " + pictures["run-speed"],
        "Backstep: one instruction undone at a time",
        "System calls (<code>SVC #N</code>) for text and number input and output, files, dialogs, "
        "random numbers and time",
        "The DE1-SoC computer's JTAG UART, and with the Digital Lab Sim its red LEDs, slide "
        "switches, push buttons and seven-segment displays",
        "\"Tools\" for watching a program run, each in its own window, from the Tools menu. The "
        "ARM X-Ray animates each instruction on a single-cycle ARM datapath.<br>"
        + f'<span class="pair">{pictures["tools-menu"]} {pictures["xray"]}</span>',
        "A built-in Help that lists every instruction, pseudo-instruction and system call and "
        "explains the directives, and example programs under File &gt; Open Example",
    )
    body = ('<h1>ARES Features</h1>\n<p>What ARES does, in short:</p>\n<ul class="features">\n'
            + "\n".join(f"<li>{item}</li>" for item in items) + "\n</ul>")
    return main_page("features.html", body)


def download():
    text = readme()
    table, notes = text.packages(), text.first_start()
    rows = []
    for system, name, release in PACKAGES:
        if release:
            rows.append(f'<tr><td><a class="button wide" href="{DOWNLOAD}{name}">Download '
                        f'{esc(name)}</a></td><td>{esc(system)}: {markdown_words(table[name])}, '
                        f'{size_text(release)}</td></tr>')
        else:
            rows.append(f"<tr><td><code>{esc(name)}</code></td><td>{esc(system)}: coming soon"
                        f"</td></tr>")
    options = (
        ("Option A: Windows, one file.",
         f"Put <code>ARES.exe</code> anywhere, the desktop for one, and double-click it. The "
         f"first time, {markdown_words(notes['Windows'])}"),
        ("Option B: Windows, a folder.",
         "Unzip <code>ARES-windows.zip</code> where you like, then double-click "
         "<code>ARES.exe</code> in the folder; the example programs are beside it. The first "
         "time, Windows asks as it does for the one file."),
        ("Option C: macOS, Apple Silicon.",
         f"{markdown_words(notes['macOS'][0].upper() + notes['macOS'][1:])}"),
        ("Option D: from the source code, with Python.",
         "Install Python 3.11 or newer. In a copy of the source code run these commands, then "
         "run ARES with the command <b><code>.venv/bin/python -m ares</code></b>. On Windows "
         "write <code>py</code> for <code>python3</code> and <code>.venv\\Scripts\\python</code> "
         f'for <code>.venv/bin/python</code>. <a href="{REPOSITORY}#building-from-source">'
         "Building from source</a> also makes the packages."),
    )
    commands = code(text.program("Building from source").replace("tools/build.py",
                                                                 "tools/fetch_toolchain.py"))
    body = f"""<h1>Download ARES <span class="version">V{RELEASE}, {RELEASE_SHORT}</span></h1>
<table class="packages">
{chr(10).join(rows)}
</table>
{"".join(f'<p class="option"><b><i>{label}</i></b> <i>{words}</i></p>{chr(10)}'
         for label, words in options)}{commands}
<p><b><i>ARES runs on Windows 10 or 11 (64-bit) and on macOS 12 or newer on Apple Silicon. The \
GNU assembler and linker come with it: nothing else needs to be installed.</i></b> From the \
source code it needs Python 3.11 or newer (on Linux 3.12 or newer, with <code>python3-tk</code>).</p>
<p><a href="{RELEASES}">All releases</a>, with the source code of the GNU assembler and linker and \
of Unicorn that ARES includes.</p>
<p>{sample_line()}</p>"""
    assert "tools/fetch_toolchain.py" in body           # the README's commands, run from source
    return main_page("download.html", body)


def license_page():
    words = helptext.parse(helptext.LICENSE_WORDS)[:2]
    plain = "\n".join(f"<p>{help_words(block.text)}</p>" for block in words)
    body = f"""<h1>ARES License</h1>
<p>ARES is open-source software, made for the teaching community: instructors and students are \
welcome to use it in any course.</p>
<p>Each source code file contains the license statement:</p>
{code("# SPDX-License-Identifier: GPL-2.0-or-later" + chr(10) + "# Copyright (c) 2026 The ARES Project")}
<p>In plain words:</p>
{plain}
<p>The full licence: <a href="{SOURCE_FILE}LICENSE">LICENSE</a>. The components ARES includes, \
their licences and where their source code is published: \
<a href="{SOURCE_FILE}THIRD_PARTY_NOTICES.txt">THIRD_PARTY_NOTICES.txt</a>.</p>"""
    return main_page("license.html", body)


def papers():
    team = section("credits", blocks_html(helptext.parse(credits.credits_markup())))
    body = f"""{heading()}
{team}
<p>GLSVLSI '26 paper, <a href="{DYNARMIC}"><i>"DynARMic: A Dynamic ARM Instruction Counting \
Tool."</i></a> GLSVLSI '26, pages 365-366. The basis of ARES's Dynamic Instruction Counter.</p>"""
    return main_page("papers.html", body)


# The Help & Info pages --------------------------------------------------------------------------

def help_blocks(name):
    """The blocks of the Help window's tab of a Help & Info page."""
    return page_blocks(HELP_TABS[name], MENUS, label_of)


def help_from_program(name):
    return help_page(name, blocks_html(help_blocks(name)))


def tool_order():
    """The Tools tab's entries, the ARM X-Ray first after what every tool has."""
    entries = tool_entries()
    xray = next(entry for entry in entries if entry[0] == "ARM X-Ray")
    entries.remove(xray)
    entries.insert(1, xray)
    return entries


def tools_help():
    (common, make_common), *tools = tool_order()
    blocks = make_common()              # a paragraph, then its own heading: what every tool has
    names = [common] + [name for name, _ in tools]
    contents = " &nbsp; ".join(f'<a href="#{slug(name)}">{esc(name)}</a>' for name in names)
    parts = [blocks_html(blocks[:1]), f'<p class="contents">{contents}</p>',
             blocks_html(blocks[1:]).replace("<h2>", f'<h2 id="{slug(common)}">', 1)]
    for name, make in tools:
        image = TOOL_PICTURES.get(name)
        shot = (picture(f"images/tools/{image}.png", f"The {name} window", "../", "tool")
                if image else "")
        inner = blocks_html(make()).replace("<h2>", "<h3>").replace("</h2>", "</h3>")
        parts.append(f'<h2 id="{slug(name)}">{esc(name)}</h2>\n{shot}\n{inner}')
    return help_page("tools.html", "\n".join(parts))


def history():
    toolchain = json.loads((ROOT / "tools" / "toolchain.json").read_text(encoding="utf-8"))
    versions = dict(line.split("==") for line in
                    (ROOT / "requirements.txt").read_text(encoding="utf-8").split("\n")
                    if "==" in line)
    packages = ", ".join(f"<code>{name}</code>" for name in RELEASED)
    body = f"""<p>ARES {RELEASE} was released in {RELEASE_MONTH}. It is the first release. \
{esc(credits.FIRST_USED)} It contains:</p>
<ul>
<li>The editor, with several open files, syntax colours, find and replace, and the \
capital-letters rule (Edit &gt; Capitalize Instructions).</li>
<li>The GNU assembler and linker of the {esc(toolchain["name"])} \
{esc(toolchain["version"])}, the processor and memory of Unicorn {versions["unicorn"]}, and the \
disassembler Capstone {versions["capstone"]}.</li>
<li>Run, step, backstep, pause, stop and reset, breakpoints, a run speed, and the registers, \
floating-point registers, memory and labels.</li>
<li>The system calls of the Syscalls page, and the DE1-SoC computer's JTAG UART.</li>
<li>Nine tools: {esc(", ".join(name for name, _ in tool_entries() if name in TOOL_PICTURES))}; \
and the Memory Map.</li>
<li>The Help, with every instruction, pseudo-instruction and system call, the directives, and \
example programs under File &gt; Open Example.</li>
<li>Packages on GitHub: {packages}.</li>
</ul>"""
    return help_page("history.html", body)


def acknowledgements():
    links = "\n".join(f"<li>{markdown_words(item)}</li>"
                      for item in readme().bullets("Acknowledgements"))
    return help_page("acknowledgements.html",
                     blocks_html(help_blocks("acknowledgements.html"))
                     + f"\n<h2>Links</h2>\n<ul>\n{links}\n</ul>")


# Style ------------------------------------------------------------------------------------------

STYLE = f"""/* The main pages: a page in the middle, the helmet and a column of buttons at its left. */
body {{ margin: 0; color: #000000; }}
body.main {{ background: {TITLE}; font: 14px/1.4 Arial, Helvetica, sans-serif; }}
.page {{ max-width: 766px; margin: 0 auto; background: #FFFFFF; padding: 0 10px 12px; }}
.masthead {{ height: 29px; background: {NAVY}; }}
.columns {{ display: flex; margin-top: 10px; }}
.left {{ flex: none; width: 179px; background: {FACE}; padding: 10px 0 40px; }}
.left .helmet {{ display: block; margin: 0 0 0 10px; image-rendering: pixelated; }}
.buttons {{ list-style: none; margin: 28px 0 0; padding: 0 0 0 35px; }}
.buttons li {{ margin: 0 0 4px; }}
.button {{ display: inline-block; box-sizing: border-box; min-width: 100px; padding: 1px 6px 0;
  text-align: center; font: 16px/20px Calibri, Arial, Helvetica, sans-serif; color: #000000;
  text-decoration: none; background: {TAB}; border: 1px solid {TAB_BORDER};
  border-bottom: 4px solid {NAVY}; }}
.button:hover {{ background: #E3EEF9; }}
.button:active {{ border-bottom-width: 2px; margin-top: 2px; }}
.button[aria-current] {{ background: #FFFFFF; font-weight: bold; }}
.button.wide {{ min-width: 220px; font-size: 15px; }}
:focus-visible {{ outline: 2px dotted #000000; outline-offset: 2px; }}
.content {{ flex: 1; min-width: 0; padding: 4px 4px 0 14px; }}
.content h1 {{ font-style: italic; font-size: 24px; margin: 22px 0 6px; }}
.content h1 small {{ font-size: 18px; }}
.content h1 .version {{ font-style: normal; font-size: 22px; margin-left: 6px; }}
.subtitle {{ font-style: italic; font-size: 18px; margin: 0 0 14px; }}
.download {{ font-weight: bold; }}
.download a {{ font-size: 18px; font-style: italic; }}
.content li {{ margin: 4px 0; }}
.features img {{ vertical-align: middle; margin: 4px 6px 4px 0; border: 1px solid #C8C8C8;
  box-sizing: border-box; }}
.option {{ margin: 8px 0; }}
.pair {{ display: flex; gap: 8px; align-items: flex-start; margin-top: 4px; }}
.pair img {{ max-width: calc(50% - 4px); margin: 0; }}
.packages td {{ padding: 4px 8px 4px 0; vertical-align: middle; }}
.footer {{ text-align: right; color: #444444; font-size: 12px; margin: 10px 4px 0; }}
pre {{ font: 13px/1.35 Consolas, "Courier New", monospace; background: #F4F4F4;
  border: 1px solid #CCCCCC; padding: 6px 8px; overflow-x: auto; }}
code {{ font-family: Consolas, "Courier New", monospace; }}
.table {{ overflow-x: auto; }}
img {{ max-width: 100%; height: auto; }}

/* The Help & Info pages: plain text, a row of links at the top. */
body.help {{ max-width: 60em; margin: 0 auto; padding: 8px 14px 30px;
  font: 16px/1.4 "Times New Roman", Times, serif; background: #FFFFFF; }}
.links {{ text-align: center; font-weight: bold; font-size: 1.17em; line-height: 1.6; }}
.links a {{ margin: 0 0.45em; white-space: nowrap; }}
.links a.home {{ margin-left: 1.6em; }}
.title {{ text-align: center; font-weight: bold; }}
.title p {{ margin: 0.9em 0; }}
.title .name {{ font-size: 1.17em; }}
.title h1 {{ font-size: 1em; margin: 0.9em 0 1.2em; }}
body.help h2 {{ font-size: 1.1em; margin: 1.4em 0 0.5em; }}
body.help table {{ border-collapse: collapse; margin: 0.5em 0; }}
body.help th, body.help td {{ border: 1px solid #999999; padding: 2px 6px; text-align: left;
  vertical-align: top; }}
body.help th {{ background: {TAB}; }}
.tool {{ display: block; width: auto; max-width: min(100%, 600px); border: 1px solid #999999;
  margin: 0.5em 0; box-sizing: border-box; }}
body.help h3 {{ font-size: 1em; margin: 1.2em 0 0.4em; }}
.contents {{ text-align: center; }}

/* A phone: the buttons in a row under the helmet. */
@media (max-width: 600px) {{
  .page {{ padding: 0 6px 10px; }}
  .columns {{ flex-direction: column; }}
  .left {{ width: auto; display: flex; align-items: center; gap: 10px; padding: 8px; }}
  .left .helmet {{ width: 64px; height: 64px; margin: 0; }}
  .buttons {{ display: flex; flex-wrap: wrap; gap: 4px; margin: 0; padding: 0; }}
  .buttons li {{ margin: 0; }}
  .button {{ min-width: 0; font-size: 15px; }}
  .content {{ padding: 4px 2px 0; }}
  .button.wide {{ min-width: 0; }}
}}
"""


# Pictures ---------------------------------------------------------------------------------------

def helmet(grid, factor, square=None):
    return Image.open(io.BytesIO(icons.helmet_png(grid, factor, square))).convert("RGBA")


def preview():
    """The link preview: the helmet beside the window, on the light blue of a selected tab."""
    image = Image.new("RGB", PREVIEW_SIZE, TAB)
    image.paste(Image.new("RGB", (PREVIEW_SIZE[0], 10), TAB_BORDER), (0, PREVIEW_SIZE[1] - 10))
    big = helmet(icons.HELMET_32, 7)
    image.paste(big, (56, (PREVIEW_SIZE[1] - big.height) // 2), big)
    with Image.open(DOCS / SCREENSHOT) as source:
        shot = source.convert("RGB")
    width = 820
    shot = shot.resize((width, round(width * shot.height / shot.width)), Image.LANCZOS)
    left, top = PREVIEW_SIZE[0] - width - 44, (PREVIEW_SIZE[1] - shot.height) // 2
    frame = Image.new("RGB", (shot.width + 4, shot.height + 4), "#000000")
    frame.paste(Image.new("RGB", (shot.width + 2, shot.height + 2), "#FFFFFF"), (0, 0))
    frame.paste(Image.new("RGB", (shot.width + 1, shot.height + 1), "#8E8E8E"), (1, 1))
    frame.paste(shot, (2, 2))
    image.paste(frame, (left - 2, top - 2))
    return image


def pictures():
    """{place under the site: image} of every picture the script makes."""
    touch = Image.new("RGBA", (180, 180), TAB)
    big = helmet(icons.HELMET_32, 5)
    touch.alpha_composite(big, ((180 - big.width) // 2, (180 - big.height) // 2))
    return {"images/preview.png": preview(), "images/apple-touch-icon.png": touch,
            "images/icon-192.png": helmet(icons.HELMET_32, 6)}


def favicon():
    """favicon.ico: the helmet at 16, 32 and 48 pixels, each from its own grid, not scaled."""
    sizes = {16: helmet(icons.HELMET_16, 1), 32: helmet(icons.HELMET_32, 1),
             48: helmet(icons.HELMET_16, 3)}
    data = io.BytesIO()
    sizes[48].save(data, format="ICO", sizes=[(16, 16), (32, 32), (48, 48)],
                   append_images=[sizes[16], sizes[32]])
    return data.getvalue()


# The site ---------------------------------------------------------------------------------------

def texts():
    """{place under the site: text} of every page and the style."""
    made = {"index.html": home(), "features.html": features(), "download.html": download(),
            "license.html": license_page(), "papers.html": papers(), "style.css": STYLE,
            ".nojekyll": ""}
    for name in HELP_TABS:
        made[f"help/{name}"] = (acknowledgements() if name == "acknowledgements.html"
                                else help_from_program(name))
    made["help/tools.html"] = tools_help()
    made["help/history.html"] = history()
    return made


def build(out):
    """Write the site into the folder out; return the places of the files written."""
    written = []
    for place, text in texts().items():
        target = out / place
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as file:
            file.write(text)
        written.append(place)
    for place, image in pictures().items():
        target = out / place
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, format="PNG", optimize=True)
        written.append(place)
    (out / "favicon.ico").write_bytes(favicon())
    written.append("favicon.ico")
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description="Make the website of ARES.")
    parser.add_argument("--out", type=Path, default=DOCS, help="the folder to write (docs)")
    args = parser.parse_args(argv)
    written = build(args.out)
    print(f"{len(written)} files written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
