# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The website in docs/, made by tools/make_site.py: it is up to date, its links and downloads work,
its Help & Info pages say what ARES's Help says, and other names stand only where they may."""

import importlib.util
import json
import re
from html.parser import HTMLParser
from urllib.parse import urldefrag, urlsplit

import pytest
from conftest import ROOT
from PIL import Image

from ares import __version__, credits, helptext
from ares.gui.app import MENUS
from ares.gui.helpwindow import page_blocks, tool_entries
from ares.gui.menubar import access_letter
from ares.syscalls import SERVICES

DOCS = ROOT / "docs"
_spec = importlib.util.spec_from_file_location("make_site", ROOT / "tools" / "make_site.py")
site = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(site)
_build_spec = importlib.util.spec_from_file_location("build_tool", ROOT / "tools" / "build.py")
build_tool = importlib.util.module_from_spec(_build_spec)
_build_spec.loader.exec_module(build_tool)

MAIN = [name for name, *_ in site.MAIN]
HELP = [f"help/{name}" for name, *_ in site.HELP]
PAGES = MAIN + HELP
# The names that only some pages may hold, built here so that this file spells none of them: the
# simulator and the language ARES grew out of, the simulator it is compatible with, the people of
# the credits, and the textbook.
OTHER_NAMES = [word for word in credits.MOTIVATION[0].split()[:4] if word.isupper()]
COMPATIBLE = credits.MOTIVATION[0].split("The closest was ")[1].split(",")[0]
PEOPLE = [credits.CREATED_BY.rstrip(".").split()[-1],
          *(advisor.split(",")[0].split()[-1] for advisor in credits.ADVISORS)]
BOOK = credits.TEXTBOOK.split()[0]
# The captures of ARES the pages show: kept in docs/, not made by the script.
CAPTURES = sorted(path.relative_to(DOCS).as_posix() for folder in ("features", "tools")
                  for path in (DOCS / "images" / folder).glob("*"))
SOURCES = {site.SCREENSHOT, site.HELMET, *CAPTURES}
BLOCKS = {"p", "li", "ul", "ol", "div", "td", "th", "tr", "h1", "h2", "h3", "pre", "section",
          "nav", "header", "br", "table"}


def label_of(text):
    return access_letter(text)[0]


class Page(HTMLParser):
    """What a test needs of an HTML page: its tags with their attributes, its ids, the text of
    its main part, and its title."""

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.tags, self.ids, self.words, self.title = [], set(), [], None
        self._in_main = self._in_title = False
        self.feed(text)
        self.text = " ".join("".join(self.words).split())

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if "id" in attrs:
            self.ids.add(attrs["id"])
        self._in_main |= tag == "main"
        self._in_title |= tag == "title"
        if tag in BLOCKS:
            self.words.append(" ")

    def handle_endtag(self, tag):
        if tag == "main":
            self._in_main = False
        if tag == "title":
            self._in_title = False
        if tag in BLOCKS:
            self.words.append(" ")

    def handle_data(self, data):
        if self._in_title:
            self.title = data
        if self._in_main:
            self.words.append(data)

    def all(self, tag):
        return [attrs for name, attrs in self.tags if name == tag]

    def meta(self, key):
        for attrs in self.all("meta"):
            if key in (attrs.get("name"), attrs.get("property")):
                return attrs.get("content")
        return None


def read(place):
    return (DOCS / place).read_text(encoding="utf-8")


def parsed(place):
    return Page(read(place))


def words(text):
    return " ".join(helptext.plain(text).split())


def in_order(text, parts, where):
    """Every part appears in text, each after the one before."""
    at = 0
    for part in parts:
        found = text.find(part, at)
        assert found >= 0, (where, part)
        at = found + len(part)


def block_words(blocks):
    """The words of blocks as a page shows them, in order; the titles are the page's header."""
    parts = []
    for block in blocks:
        if block.kind == helptext.TABLE:
            parts += [words(cell) for row in block.rows for cell in row if words(cell)]
        elif block.kind != helptext.TITLE:
            parts.append(words(block.text))
    return parts


# The site is made by the script, and is up to date ----------------------------------------------

@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    return out, site.build(out)


def icon_frames(path):
    """{size: pixels} of every picture of an .ico file."""
    frames = {}
    with Image.open(path) as icon:
        for size in sorted(icon.info["sizes"]):
            icon.size = size
            icon.load()
            frames[size] = icon.convert("RGBA").tobytes()
    return frames


def test_the_site_builds_and_docs_holds_what_the_script_makes(fresh):
    out, written = fresh
    assert {*PAGES, "style.css", ".nojekyll", "favicon.ico", "images/preview.png"} <= set(written)
    stale = []
    for place in written:
        made, kept = out / place, DOCS / place
        if not kept.is_file():
            stale.append(place)
        elif place.endswith(".png"):
            with Image.open(made) as a, Image.open(kept) as b:
                if a.size != b.size or a.convert("RGBA").tobytes() != b.convert("RGBA").tobytes():
                    stale.append(place)
        elif place.endswith(".ico"):
            if icon_frames(made) != icon_frames(kept):
                stale.append(place)
        elif made.read_bytes() != kept.read_bytes():
            stale.append(place)
    assert not stale, f"docs/ is out of date, run python tools/make_site.py: {stale}"


def test_docs_holds_nothing_but_the_site_and_the_pictures_its_pages_show(fresh):
    _, written = fresh
    kept = {path.relative_to(DOCS).as_posix() for path in DOCS.rglob("*") if path.is_file()}
    assert kept == set(written) | SOURCES
    shown = " ".join(read(place) for place in PAGES)
    for capture in CAPTURES:
        assert capture in shown, f"no page shows {capture}"
    for gone in ("examples.html", "tools.html", "downloads.html", "help.html"):
        assert not (DOCS / gone).exists()


def test_the_favicon_holds_the_helmet_at_three_sizes():
    assert sorted(icon_frames(DOCS / "favicon.ico")) == [(16, 16), (32, 32), (48, 48)]


def test_the_release_is_this_version_with_its_month():
    assert site.RELEASE == __version__
    assert site.RELEASE_MONTH.split()[0][:3] == site.RELEASE_SHORT[:3]


# Every page -------------------------------------------------------------------------------------

@pytest.mark.parametrize("place", MAIN)
def test_a_main_page_has_the_helmet_and_the_six_buttons_in_order(place):
    text = read(place)
    page = Page(text)
    nav = text.split('<nav class="left"')[1].split("</nav>")[0]
    assert f'src="{site.HELMET}"' in nav
    labels = re.findall(r'class="button" href="[^"]+"[^>]*>([^<]+)</a>', nav)
    assert labels == ["Home", "Features", "Download", "License", "Papers", "Help &amp; Info"]
    assert re.findall(r'href="([^"]+)" aria-current="page"', nav) == [place]
    assert 'href="help/intro.html"' in nav
    assert "<img" not in nav.split('<ul class="buttons">')[1]       # buttons drawn with CSS
    assert page.all("main") and len(page.all("h1")) <= 1


@pytest.mark.parametrize("place", HELP)
def test_a_help_page_has_the_row_of_links_the_release_and_its_title(place):
    text = read(place)
    row = text.split('<nav class="links"')[1].split("</nav>")[0]
    labels = re.findall(r"<i>([^<]+)</i>", row)
    assert labels == ["Intro", "Settings", "Syscalls", "IDE", "Debugging", "Tools",
                      "Keyboard shortcuts", "History", "Limitations", "Acknowledgements",
                      "ARES&nbsp;home"]
    assert 'href="../index.html"' in row
    header = text.split('<header class="title">')[1].split("</header>")[0]
    head_text = " ".join(re.sub(r"<[^>]+>", " ", header).split())
    heading = next(entry[2] for entry in site.HELP if f"help/{entry[0]}" == place)
    assert head_text == (f"ARES - ARM Educational Simulator Release {site.RELEASE} "
                         f"{site.RELEASE_MONTH} {heading}")
    assert f"<h1>{heading}</h1>" in header


@pytest.mark.parametrize("place", PAGES)
def test_every_page_has_a_title_a_description_and_a_link_preview(place):
    page = parsed(place)
    assert page.title and "ARES" in page.title
    assert page.all("html")[0].get("lang") == "en"
    assert page.meta("viewport") == "width=device-width, initial-scale=1"
    description = page.meta("description")
    assert description and 50 <= len(description) <= 200
    assert page.meta("og:title") == page.title
    assert page.meta("og:description") == description
    assert page.meta("og:image") == site.SITE + "images/preview.png"
    assert page.meta("og:url").startswith(site.SITE)
    assert {"icon", "apple-touch-icon", "stylesheet", "canonical"} <= {
        attrs.get("rel") for attrs in page.all("link")}


def test_the_titles_and_descriptions_differ_from_page_to_page():
    pages = [parsed(place) for place in PAGES]
    assert len({page.title for page in pages}) == len(pages)
    assert len({page.meta("description") for page in pages}) == len(pages)


@pytest.mark.parametrize("place", PAGES)
def test_every_picture_has_its_words_and_its_size(place):
    for attrs in parsed(place).all("img"):
        assert len(attrs.get("alt", "")) >= 15, attrs
        source = (DOCS / place).parent / attrs["src"]
        with Image.open(source) as image:
            assert (attrs["width"], attrs["height"]) == (str(image.width), str(image.height))


@pytest.mark.parametrize("place", PAGES)
def test_no_page_runs_a_script_or_loads_from_elsewhere(place):
    text = read(place)
    page = Page(text)
    assert not page.all("script") and not page.all("iframe")
    assert "<script" not in text.lower() and "javascript:" not in text.lower()
    assert not re.search(r"\son[a-z]+=", text)
    for attrs in page.all("link"):
        if attrs.get("rel") in ("stylesheet", "icon", "apple-touch-icon", "preload"):
            assert not urlsplit(attrs["href"]).scheme, attrs
    for attrs in page.all("img"):
        assert not urlsplit(attrs["src"]).scheme, attrs


def test_the_style_loads_nothing_from_elsewhere_and_draws_the_buttons():
    style = read("style.css")
    assert "@import" not in style and "url(" not in style and "@font-face" not in style
    assert ".button {" in style and "border-bottom: 4px solid" in style


def test_github_pages_takes_the_folder_as_it_is():
    assert (DOCS / ".nojekyll").is_file()


def links():
    """(page, link) of every link and picture of the site."""
    found = []
    for place in PAGES:
        for tag, attrs in parsed(place).tags:
            for key in ("href", "src"):
                if key in attrs and not (tag == "link" and attrs.get("rel") == "canonical"):
                    found.append((place, attrs[key]))
    return found


def test_every_link_inside_the_site_leads_to_a_page_and_its_place():
    checked = 0
    for place, link in links():
        if urlsplit(link).scheme:
            continue
        target, anchor = urldefrag(link)
        path = ((DOCS / place).parent / target).resolve() if target else DOCS / place
        assert path.is_file(), (place, link)
        assert DOCS.resolve() in path.resolve().parents, (place, link)
        if anchor:
            assert anchor in Page(path.read_text(encoding="utf-8")).ids, (place, link)
        checked += 1
    assert checked > 150


def test_links_out_of_the_site_are_secure_and_files_of_the_repository_are_real():
    for place, link in links():
        if urlsplit(link).scheme:
            assert urlsplit(link).scheme == "https", (place, link)
        if link.startswith(site.SOURCE_FILE):
            assert (ROOT / link.removeprefix(site.SOURCE_FILE)).is_file(), (place, link)
        if link.startswith("https://github.com/"):
            assert link.startswith(site.REPOSITORY), (place, link)


def test_the_site_publishes_no_release_checksums():
    """No checksum file was published with the release, so the site offers none."""
    for place in PAGES:
        assert not re.search(r"checksum|sha-?256|SHA256SUMS", read(place), re.IGNORECASE), place


def credits_html():
    """The credits as a page shows them: lines, and the advisors as one list of bullets."""
    advisors = "\n".join(f"<li>{site.esc(advisor)}</li>" for advisor in credits.ADVISORS)
    return (f"<p>{site.esc(credits.CREATED_BY)}</p>\n<p>{site.esc(credits.ADVISORS_HEADING)}</p>\n"
            f"<ul>\n{advisors}\n</ul>\n<p>{site.esc(credits.FIRST_USED)}</p>")


def test_the_help_pages_show_the_credits_with_the_advisors_alone_as_bullets():
    for place in ("help/intro.html", "help/acknowledgements.html"):
        text = read(place)
        assert f"<h2>Credits</h2>\n{credits_html()}\n" in text
        assert text.count("<ul>") == text.count("</ul>")
        assert "<ul>\n<li>" + site.esc(credits.CREATED_BY) not in text


def test_the_site_holds_no_address_and_no_local_path():
    for place in [*PAGES, "style.css"]:
        text = read(place)
        assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text), place
        assert not re.search(r"[A-Za-z]:\\|/Users/|/home/", text), place


# The main pages ---------------------------------------------------------------------------------

def test_home_says_what_ares_is_and_links_the_download_the_sample_and_the_features():
    text = read("index.html")
    page = Page(text)
    assert "ARES (ARM Educational Simulator)" in page.text
    assert "An IDE for ARMv7 Assembly Language Programming" in page.text
    assert "DE1-SoC" in text.split('<section id="intro">')[1].split("</section>")[0]
    assert re.search(rf'href="download.html">Download ARES {site.RELEASE} software!</a> '
                     rf'\({re.escape(site.RELEASE_SHORT)}\)', text)
    assert f'href="{site.SOURCE_FILE}examples/{site.SAMPLE}"' in text
    assert 'href="features.html">ARES features overview:' in text
    assert text.count("<li>") >= len(site.OVERVIEW)


def test_features_shows_its_pictures_where_its_bullets_say():
    text = read("features.html")
    for name in ("run-step-backstep", "breakpoints", "run-speed", "xray", "tools-menu"):
        assert f"images/features/{name}.png" in text
    page = Page(text)
    for words_ in ("run the program, step one instruction, and step one instruction back",
                   "check box", "run speed", "Tools menu", "editor"):
        assert words_ in page.text


def test_every_download_names_a_file_of_the_release_once():
    names = [link.removeprefix(site.DOWNLOAD) for _, link in links()
             if link.startswith(site.DOWNLOAD)]
    assert sorted(names) == sorted(site.RELEASED)


def test_the_release_files_are_the_readmes_and_the_packages_the_build_makes():
    assert set(site.readme().packages()) == set(site.RELEASED)
    assert {name for _, name, _ in site.PACKAGES} == {"ARES.exe", *build_tool.ARCHIVES.values()}


def test_download_has_each_package_its_options_and_requirements():
    text = read("download.html")
    page = Page(text)
    notes = site.readme().first_start()
    for system, name, release in site.PACKAGES:
        if release:
            assert site.size_text(release) in page.text
        else:
            assert f"{name} {system}: coming soon" in page.text
    for option in ("Option A: Windows, one file.", "Option B: Windows, a folder.",
                   "Option C: macOS, Apple Silicon.", "Option D: from the source code, with "
                   "Python."):
        assert option in page.text
    for note in notes.values():
        bare = re.sub(r"\*\*([^*]+)\*\*", r"\1", note)
        assert bare[1:] in page.text
    assert f"V{site.RELEASE}, {site.RELEASE_SHORT}" in page.text
    assert any(link == site.RELEASES for _, link in links())
    assert "python -m ares" in page.text and "tools/fetch_toolchain.py" in page.text


def test_license_shows_the_statement_every_source_file_carries():
    text = parsed("license.html").text
    statement = (ROOT / "tools" / "make_site.py").read_text(encoding="utf-8").split("\n")[:2]
    assert " ".join(statement) in text
    for block in helptext.parse(helptext.LICENSE_WORDS)[:2]:
        assert words(block.text) in text
    hrefs = {attrs.get("href") for attrs in parsed("license.html").all("a")}
    assert {site.SOURCE_FILE + "LICENSE", site.SOURCE_FILE + "THIRD_PARTY_NOTICES.txt"} <= hrefs


def test_papers_shows_the_credits_then_the_published_paper_as_a_paragraph():
    text = read("papers.html")
    team = text.split('<section id="credits">')[1].split("</section>")[0]
    assert team.strip() == credits_html()
    after = text.split("</section>", 1)[1]
    paper = Page("<main>" + after).text
    assert paper.startswith('GLSVLSI \'26 paper, "DynARMic: A Dynamic ARM Instruction Counting '
                            'Tool." GLSVLSI \'26, pages 365-366. The basis of ARES\'s Dynamic '
                            "Instruction Counter.")
    assert after.lstrip().startswith("<p>GLSVLSI") and "<li>" not in after
    assert any(link == site.DYNARMIC for place, link in links() if place == "papers.html")


# The Help & Info pages --------------------------------------------------------------------------

@pytest.mark.parametrize("name,tab", list(site.HELP_TABS.items()))
def test_a_help_page_says_what_the_help_window_says(name, tab):
    page = parsed(f"help/{name}")
    in_order(page.text, block_words(page_blocks(tab, MENUS, label_of)), tab)


def test_the_tools_page_has_every_tool_the_x_ray_first_with_its_picture():
    text = read("help/tools.html")
    page = Page(text)
    entries = tool_entries()
    order = [name for name, _ in site.tool_order()]
    assert order[1] == "ARM X-Ray" and sorted(order) == sorted(name for name, _ in entries)
    in_order(page.text, block_words(site.tool_order()[0][1]()), order[0])
    for name, make in site.tool_order()[1:]:
        start = text.rindex("<h2", 0, text.index(f'id="{site.slug(name)}"'))
        part = Page("<main>" + text[start:] + "</main>").text
        assert part.startswith(f"{name} "), name
        in_order(part, block_words(make()), name)
    places = [text.index(f'id="{site.slug(name)}"') for name in order]
    assert places == sorted(places)
    for name, image in site.TOOL_PICTURES.items():
        assert f"images/tools/{image}.png" in text
    assert "Choose one on the left" not in page.text


def test_the_syscalls_page_has_every_service():
    page = parsed("help/syscalls.html")
    for number in sorted(SERVICES):
        service = SERVICES[number]
        in_order(page.text, [str(number), service.name], service.name)


def test_the_shortcuts_page_has_every_shortcut_of_the_menus():
    text = parsed("help/shortcuts.html").text
    for _, entries in MENUS:
        for entry in entries or ():
            if entry and entry[2]:
                assert entry[2] in text


def test_the_history_says_what_release_one_contains():
    text = parsed("help/history.html").text
    toolchain = json.loads((ROOT / "tools" / "toolchain.json").read_text(encoding="utf-8"))
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert f"ARES {site.RELEASE} was released in {site.RELEASE_MONTH}" in text
    assert toolchain["version"] in text
    for name in ("unicorn", "capstone"):
        version = re.search(rf"{name}==(\S+)", requirements).group(1)
        assert version in text
    for package in site.RELEASED:
        assert package in text


def test_the_acknowledgements_link_the_paper_and_name_the_textbook():
    text = read("help/acknowledgements.html")
    assert f'href="{site.DYNARMIC}"' in text
    assert credits.TEXTBOOK.split(",")[0] in text
    assert f">{OTHER_NAMES[0]}</a>" in text


# Names: only where they may stand ---------------------------------------------------------------

def outside(text, allowed):
    """The lines of a page outside its sections called by a name in allowed."""
    current, lines = None, []
    for line in text.split("\n"):
        match = re.match(r'<section id="([^"]+)"', line)
        if match:
            current = match.group(1)
        if current not in allowed:
            lines.append(line)
        if line.startswith("</section>"):
            current = None
    return "\n".join(lines)


# {page: sections where the names may stand, or None for the whole page}
OTHER_ALLOWED = {"index.html": {"intro"}, "help/intro.html": None,
                 "help/acknowledgements.html": None}
COMPATIBLE_ALLOWED = {**OTHER_ALLOWED, "help/ide.html": None, "help/tools.html": None}
PEOPLE_ALLOWED = {"papers.html": {"credits"}, "help/intro.html": None,
                  "help/acknowledgements.html": None}
BOOK_ALLOWED = {"help/acknowledgements.html": None, "help/tools.html": None}


@pytest.mark.parametrize("place", PAGES)
def test_names_stand_only_on_the_pages_that_may_hold_them(place):
    text = read(place)
    for names, allowed in ((OTHER_NAMES, OTHER_ALLOWED), ([COMPATIBLE], COMPATIBLE_ALLOWED),
                           (PEOPLE, PEOPLE_ALLOWED), ([BOOK], BOOK_ALLOWED)):
        if place in allowed and allowed[place] is None:
            continue
        rest = outside(text, allowed.get(place) or set())
        for name in names:
            assert not re.search(rf"\b{name}\b", rest, re.IGNORECASE), (place, name)


def test_the_names_do_stand_where_they_belong():
    assert COMPATIBLE in read("index.html") and OTHER_NAMES[0] in read("help/intro.html")
    assert all(name in read("papers.html") for name in PEOPLE)
    assert BOOK in read("help/acknowledgements.html")


def test_the_readme_links_to_the_website():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    shown = site.SITE.removeprefix("https://").rstrip("/")
    assert f"**Website:** [{shown}]({site.SITE})" in text
    for link in re.findall(rf"\]\({re.escape(site.SITE)}([^)]*)\)", text):
        assert (DOCS / (link or "index.html")).is_file(), link
