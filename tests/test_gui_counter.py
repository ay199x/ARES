# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Tools > Dynamic Instruction Counter: one window laid out as DynARMic's page, Instruction
Categories and Encoding Formats side by side, filled by one connection."""

import json
from types import SimpleNamespace
from tkinter import font as tkfont

import pytest
from conftest import PROGRAMS, ROOT, lay_out
from test_gui_assemble import assemble
from test_gui_run import go_to_end, loaded
from test_responsiveness import pictures
from test_style import make_root  # noqa: F401  (a fixture: a root at a display scale)

from ares.classify import CLASSES, FORMATS
from ares.gui import style, tools
from ares.gui.tools.counter import (CATEGORY_PANEL, FIELD_SIZE, FORMAT_PANEL, HELP, CounterWindow,
                                    ShareBar)
from ares.gui.tools.frame import BAR_HEIGHT, BAR_WIDTH, PercentBar, paragraphs
from ares.gui.widgets import px

TITLE = "Dynamic Instruction Counter"
DIGITS = 11                     # a count's field has room for this many digits
FACT = json.loads((ROOT / "tests" / "data" / "dynarmic" / "fact.json").read_text())
NO_CYCLES = ("cycle", "cpi", "clock rate", "run time")


def counter(app):
    """Open the Dynamic Instruction Counter (or bring it to the front); returns its window."""
    app.run("tool_counter")
    return app.tool_windows["tool_counter"]


def connected(app):
    window = counter(app)
    window.connect_button.invoke()
    assert window.model.connected
    return window


def panel_shown(panel, names):
    """(total, {item: count}, {item: percentage}) as a panel shows them."""
    counts = {name: int(box.shown) for name, box in zip(names, panel.counts)}
    shares = {name: bar.shown[0] for name, bar in zip(names, panel.bars)}
    return int(panel.total.shown), counts, shares


def shown(window):
    """What the two panels show: Instruction Categories, then Encoding Formats."""
    return panel_shown(window.categories, CLASSES), panel_shown(window.formats, FORMATS)


def items(canvas):
    """{kind: [(coordinates, fill)]} of the items on a canvas, in drawing order."""
    found = {}
    for item in canvas.find_all():
        kind = canvas.type(item)
        found.setdefault(kind, []).append(([round(v) for v in canvas.coords(item)],
                                           canvas.itemcget(item, "fill")))
    return found


# The window ----------------------------------------------------------------------------------

def test_one_entry_in_the_tools_menu(app, hidden_windows):
    """The counting tools are one tool: Dynamic Instruction Counter, its C underlined."""
    labels = [tool.label for tool in tools.TOOLS]
    assert "Dynamic Instruction &Counter" in labels
    assert not any("Statistics" in label for label in labels)
    assert [tool.command for tool in tools.TOOLS].count("tool_counter") == 1
    menu, index = app._menu_items["tool_counter"]
    assert menu.entrycget(index, "label") == TITLE
    assert menu.entrycget(index, "underline") == TITLE.index("Counter")
    assert "tool_statistics" not in app._menu_items
    menu.invoke(index)
    window = app.tool_windows["tool_counter"]
    assert isinstance(window, CounterWindow) and hidden_windows.shows(window.window)
    assert window.window.title() == TITLE
    zeros = (0, dict.fromkeys(CLASSES, 0), dict.fromkeys(CLASSES, "0.0%"))
    assert shown(window) == (zeros, (0, dict.fromkeys(FORMATS, 0), dict.fromkeys(FORMATS,
                                                                                    "0.0%")))


@pytest.mark.parametrize("side", ["categories", "formats"])
def test_each_panel_is_a_group_box_with_dynarmics_labels(app, side):
    window = counter(app)
    panel = getattr(window, side)
    title, labels = CATEGORY_PANEL if side == "categories" else FORMAT_PANEL
    assert panel.box.winfo_class() == "TLabelframe"
    assert panel.box.cget("text") == title and str(panel.box.cget("labelanchor")) == "n"
    assert [label.cget("text") for label in panel.labels] == ["Total:", *labels]
    for label in panel.labels:          # the window's own colours: none of their own
        assert str(label.cget("foreground")) == "" and str(label.cget("font")) == ""
    assert len(panel.counts) == len(panel.bars) == len(labels)
    assert all(isinstance(bar, PercentBar) for bar in panel.bars)


def test_dynarmics_labels_in_its_order():
    """Verbatim from DynARMic's page, in the order of ares.classify's counts."""
    assert CATEGORY_PANEL == ("Instruction Categories", (
        "ALU:", "Branch:", "Memory (Byte Access):", "Memory (Reg-to-Reg):",
        "Conditional Load & Others:"))
    assert CLASSES == ("alu", "branch", "memory", "reg_transfer", "cond_load_other")
    assert FORMAT_PANEL == ("Encoding Formats", (
        "Data Processing (Register):", "Data Processing (Immediate):", "Load/Store (Immediate):",
        "Load/Store (Register):", "Branch:", "Multiply:", "Load/Store Multiple:",
        "Supervisor Call & Others:"))
    assert FORMATS == ("fmt_dp_reg", "fmt_dp_imm", "fmt_ls_imm", "fmt_ls_reg", "fmt_branch",
                       "fmt_mul", "fmt_lsm", "fmt_svc")


def place(widget):
    info = widget.grid_info()
    return int(info["row"]), int(info["column"]), int(info.get("columnspan", 1))


def padding(widget, side):
    """(before, after) of a widget's grid padding: side is "padx" or "pady"."""
    value = widget.grid_info()[side]
    values = value if isinstance(value, tuple) else str(value).split()
    numbers = tuple(int(v) for v in values)
    return numbers * 2 if len(numbers) == 1 else numbers


def test_the_layout_two_panels_side_by_side(app):
    """Two group boxes side by side, each with Total: and a field but no bar, a gap, then a
    row per item: label, field, bar."""
    window = counter(app)
    left, right = window.categories.box, window.formats.box
    assert left.master is right.master
    assert left.pack_info()["side"] == right.pack_info()["side"] == "left"
    assert right.pack_info()["padx"] == (px(right, 5), 0) or \
        str(right.pack_info()["padx"]) == f"{px(right, 5)} 0"
    for panel in (window.categories, window.formats):
        box = panel.box
        assert panel.total.canvas.master is box
        assert place(panel.labels[0]) == (0, 0, 1)
        assert place(panel.total.canvas) == (0, 1, 1)
        for row, (label, count, bar) in enumerate(zip(panel.labels[1:], panel.counts,
                                                      panel.bars), start=1):
            assert [place(part) for part in (label, count.canvas, bar.canvas)] == [
                (row, 0, 1), (row, 1, 1), (row, 2, 1)]
        # 20 under Total:, 6 between the other rows, 6 from a field to its bar.
        tops = [0, px(box, 20)] + [px(box, 6)] * (len(panel.labels) - 2)
        assert [padding(label, "pady") for label in panel.labels] == [(top, 0) for top in tops]
        for label, count, bar in zip(panel.labels[1:], panel.counts, panel.bars):
            assert padding(count.canvas, "pady") == padding(bar.canvas, "pady") \
                == padding(label, "pady")
            assert padding(bar.canvas, "padx") == (px(box, 6), 0)
    assert len(window.categories.bars) == 5 and len(window.formats.bars) == 8


def test_the_panels_line_up(app):
    """In each panel the fields and the bars stand under each other, and a row's label, field
    and bar are centred on one line; the rows of both panels line up."""
    window = counter(app)
    assert lay_out(window.window)
    left, right = window.categories, window.formats
    for panel in (left, right):
        assert len({box.canvas.winfo_x() for box in (panel.total, *panel.counts)}) == 1
        assert len({bar.canvas.winfo_x() for bar in panel.bars}) == 1
        for label, box, bar in zip(panel.labels[1:], panel.counts, panel.bars):
            middles = [part.winfo_y() + part.winfo_height() // 2
                       for part in (box.canvas, bar.canvas, label)]
            assert max(middles) - min(middles) <= px(label, 2)
    for row in range(5):                                # the rows of both panels line up
        assert left.bars[row].canvas.winfo_y() == right.bars[row].canvas.winfo_y()


def test_a_count_s_field(app):
    """A sunken white field, with the number at its left in the fields' font, and room for
    11 digits."""
    window = counter(app)
    box = window.formats.counts[0]
    five = px(app.root, 5)
    width, height = (px(app.root, side) for side in FIELD_SIZE)
    canvas = box.canvas
    assert (int(canvas.cget("width")), int(canvas.cget("height"))) == (width, height)
    assert canvas.cget("background") == style.WINDOW
    assert not int(canvas.cget("highlightthickness")) and not int(canvas.cget("takefocus"))
    drawn = [fill for _, fill in items(canvas)["rectangle"]]
    assert drawn[0] == style.WINDOW
    assert {style.SHADOW, style.DARK_SHADOW, style.HIGHLIGHT, style.LIGHT} <= set(drawn)
    assert canvas.coords(box.text) == [five, height // 2]
    assert canvas.itemcget(box.text, "anchor") == "w"               # numbers at the left
    assert canvas.itemcget(box.text, "fill") == style.TEXT
    assert canvas.itemcget(box.text, "font") == "TkTextFont"
    assert canvas.itemcget(box.text, "text") == box.shown == "0"
    box.set(12345678901)
    assert canvas.itemcget(box.text, "text") == box.shown == "12345678901"
    x0, _, x1, _ = canvas.bbox(box.text)
    assert x1 <= width                                              # 11 digits fit


def test_a_bar_is_a_block_percentage_bar(app):
    """A Windows 98 percentage bar, the percentage across its middle."""
    window = counter(app)
    bar = window.categories.bars[0]
    assert isinstance(bar, ShareBar) and isinstance(bar, PercentBar)
    canvas = bar.canvas
    assert (int(canvas.cget("width")), int(canvas.cget("height"))) == (
        px(app.root, BAR_WIDTH), px(app.root, BAR_HEIGHT))
    assert not int(canvas.cget("takefocus"))
    assert canvas.itemcget(bar.text, "anchor") == "center"
    assert canvas.itemcget(bar.text, "fill") == style.TEXT
    assert bar.shown == ("0.0%", 0) and canvas.itemcget(bar.text, "text") == "0.0%"
    assert not bar.cover.winfo_manager()                            # no block yet


@pytest.mark.parametrize("part, whole, text", [
    (1, 4, "25.0%"), (2, 3, "66.7%"), (1, 16, "6.3%"), (23, 80, "28.7%"), (3, 3, "100.0%"),
])
def test_a_bar_fills_the_percentage_it_shows(app, part, whole, text):
    """Its blocks reach as far as the rounded percentage of its room (23 of 80 is shown as
    28.7 %, as DynARMic's page shows it, and filled so)."""
    bar = counter(app).categories.bars[0]
    bar.set(part, whole)
    tenths = int(text[:-1].replace(".", ""))
    filled = int(tenths * bar.room / 1000 + 0.5)
    assert bar.shown == (text, filled) and bar.canvas.itemcget(bar.text, "text") == text
    assert int(bar.cover.place_info()["width"]) == filled
    bar.set(0, whole)
    assert bar.shown == ("0.0%", 0) and not bar.cover.winfo_manager()


# What it counts ------------------------------------------------------------------------------

def fact_shown():
    """What the panels show after fact.s: DynARMic's counts and the page's percentages."""
    return ((48, FACT["classes"], {"alu": "52.1%", "branch": "20.8%", "memory": "0.0%",
                                   "reg_transfer": "20.8%", "cond_load_other": "6.3%"}),
            (48, FACT["formats"], {"fmt_dp_reg": "10.4%", "fmt_dp_imm": "33.3%",
                                   "fmt_ls_imm": "0.0%", "fmt_ls_reg": "0.0%",
                                   "fmt_branch": "20.8%", "fmt_mul": "8.3%", "fmt_lsm": "20.8%",
                                   "fmt_svc": "6.3%"}))


def test_one_connection_fills_both_panels(app, tmp_path):
    loaded(app, tmp_path, (PROGRAMS / "fact.s").read_text(), "fact.s")
    hooks = len(app.machine.uc._callbacks)
    window = connected(app)
    assert len(app.machine.uc._callbacks) == hooks + 1             # one block hook
    assert app.machine.observers._counting == [window.model]
    go_to_end(app)
    assert FACT["instructions"] == 48
    assert shown(window) == fact_shown()


def test_the_panels_follow_step_backstep_reset_and_assemble(app, tmp_path):
    loaded(app, tmp_path, (PROGRAMS / "fact.s").read_text(), "fact.s")
    window = connected(app)
    for steps in (1, 2, 3):
        app.run("step")
        categories, formats = shown(window)
        assert categories[0] == formats[0] == steps
        assert sum(categories[1].values()) == sum(formats[1].values()) == steps
    app.run("backstep")                         # undone, but executed: the counts stay
    assert shown(window)[0][0] == 3
    app.run("reset")                            # Reset, F12: the counts go on
    go_to_end(app)
    assert shown(window)[0][0] == shown(window)[1][0] == 3 + 48
    assemble(app)                               # a new program: still connected, counting
    assert window.model.connected and window.model.machine is app.machine
    go_to_end(app)
    assert shown(window)[1][0] == 3 + 2 * 48
    window.reset_button.invoke()                # only the tool's Reset sets them to 0
    zeros = [(0, dict.fromkeys(names, 0), dict.fromkeys(names, "0.0%"))
             for names in (CLASSES, FORMATS)]
    assert list(shown(window)) == zeros and window.model.connected
    app.run("reset")
    go_to_end(app)
    assert shown(window) == fact_shown()


def test_the_help_text():
    """Kept in the tool's module for the Help window."""
    text = paragraphs(HELP)
    assert "DynARMic (GLSVLSI 2026), a dynamic ARM instruction counting tool" in text
    for title, labels in (CATEGORY_PANEL, FORMAT_PANEL):
        assert title in text
        for label in labels:
            assert label in text, label


def texts(widget):
    """Every text the window shows: its widgets' and its canvases' items'."""
    found = [str(widget.cget("text"))] if "text" in widget.keys() else []
    if widget.winfo_class() == "Canvas":
        found += [widget.itemcget(item, "text") for item in widget.find_all()
                  if widget.type(item) == "text"]
    for child in widget.winfo_children():
        found += texts(child)
    return found


def test_no_cycles_are_shown(app, tmp_path):
    loaded(app, tmp_path, (PROGRAMS / "fact.s").read_text(), "fact.s")
    window = connected(app)
    go_to_end(app)
    shown_texts = " ".join(texts(window.window)).lower()
    assert "Encoding Formats".lower() in shown_texts and "52.1%" in shown_texts
    for words in NO_CYCLES:
        assert words not in shown_texts, words


def test_no_pictures_are_made_for_the_counter(app, tmp_path):
    made = pictures(app.root)
    loaded(app, tmp_path, (PROGRAMS / "fact.s").read_text(), "fact.s")
    window = connected(app)
    app.run("step")
    go_to_end(app)
    window.reset_button.invoke()
    window.close()
    assert pictures(app.root) == made


def test_refreshing_redraws_only_what_changed(app, tmp_path):
    loaded(app, tmp_path, ".global _start\n_start: MOV R0, #1\n        MOV R1, #2\n"
                          "        SVC #10\n")
    window = connected(app)
    app.run("step")                             # MOV: ALU, Data Processing (Immediate)
    changed = []
    for panel in (window.categories, window.formats):
        for part in (panel.total, *panel.counts, *panel.bars):
            canvas = part.canvas
            for name in ("itemconfigure", "coords"):
                original = getattr(canvas, name)

                def note(item, *args, original=original, **options):
                    changed.append(item)
                    return original(item, *args, **options)
                setattr(canvas, name, note)
    app.run("step")                             # another of the same: the shares stay 100 %
    assert len(changed) == 2 * 2                # each panel's total and one count
    app.run("reset")                            # nothing ran: nothing to draw again
    assert len(changed) == 2 * 2


# At 100 % and 225 % --------------------------------------------------------------------------

@pytest.mark.parametrize("scale", [1.0, 2.25])
def test_the_window_is_in_proportion_at_each_scale(make_root, scale):
    """Every size scales with the display, and the texts fit in the fields and bars."""
    root = make_root(scale)
    style.apply(root)
    window = CounterWindow(SimpleNamespace(root=root, machine=None))
    assert lay_out(window.window)
    one = px(root, 1)
    assert one == (2 if scale == 2.25 else 1)
    for panel in (window.categories, window.formats):
        for bar in panel.bars:
            bar.set(1, 1)
            x0, y0, x1, y1 = bar.canvas.bbox(bar.text)
            assert int(bar.canvas.cget("width")) == px(root, BAR_WIDTH) and x1 - x0 < bar.room
            assert y1 - y0 <= int(bar.canvas.cget("height"))
        for box in (panel.total, *panel.counts):
            box.set(10 ** (DIGITS - 1))
            x0, _, x1, _ = box.canvas.bbox(box.text)
            assert x1 <= int(box.canvas.cget("width")) - one
    top = window.window
    width, height = top.winfo_reqwidth(), top.winfo_reqheight()
    assert width < px(root, 1000) and height < px(root, 400)          # compact
    window.close()
