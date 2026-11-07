# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The layout at the start, which is always the default one, and how far a drag can take a divider.

The windows are hidden and get their sizes through real <Configure> events. A divided window
passes through small sizes on its way to its real one; a divider placed then would stay there.
"""

import json

import pytest
from conftest import fixed_screen, lay_out

from ares.gui import app as app_module
from ares.gui import bumps
from ares.gui.app import LEAST_HEIGHTS, LEAST_WIDTHS
from ares.gui.execute import LEAST_LABELS, LEAST_SEGMENT
from ares.gui.widgets import px
from ares.settings import Settings

MAIN, LEFT = 0.732, 0.771               # the default proportions
# What an older ARES kept in the settings file.
OLD_LAYOUT = {"geometry": "1000x700+50+60", "maximized": False, "split_main": 0.6,
              "split_left": 0.5, "split_execute": 0.3, "split_labels": 0.6}


@pytest.fixture
def start(make_app, tmp_path, monkeypatch):
    """start(entries=None): ARES laid out, with those entries in its settings file."""
    fixed_screen(monkeypatch)

    def start_with(entries=None):
        if entries is not None:
            (tmp_path / "settings.json").write_text(json.dumps(entries), encoding="utf-8")
        app = make_app()
        assert lay_out(app.root)
        return app
    return start_with


def shares(app):
    """Where the dividers are, as shares of their windows."""
    return (app.main_split.sashpos(0) / app.main_split.winfo_width(),
            app.left_split.sashpos(0) / app.left_split.winfo_height())


def near(values, wanted):
    return all(abs(value - share) < 0.01 for value, share in zip(values, wanted))


class Sizes:
    """What the divided windows say their sizes are, for an order of events a test sets up."""

    def __init__(self, app, monkeypatch):
        self.app = app
        self.main_height, self.left_height = 1827, 1
        self.sashes = {}
        monkeypatch.setattr(app.main_split, "winfo_width", lambda: 3836)
        monkeypatch.setattr(app.main_split, "winfo_height", lambda: self.main_height)
        monkeypatch.setattr(app.left_split, "winfo_height", lambda: self.left_height)
        for paned in (app.main_split, app.left_split):
            monkeypatch.setattr(paned, "sashpos", lambda index, position=None, paned=paned:
                                self.sashes.setdefault(paned, position) if position is not None
                                else self.sashes.get(paned, 0))

    def configure(self, height):
        """The left part reaches height: its <Configure>, as on the real start."""
        self.left_height = height
        self.app.left_split.winfo_id()
        self.app.left_split.event_generate("<Configure>", width=2876, height=height)


def test_a_passing_small_size_places_no_divider(start, monkeypatch):
    """The order of events of the real start: 22 pixels high first, then the real height."""
    app = start()
    app._splits_pending = True
    sizes = Sizes(app, monkeypatch)
    sizes.configure(22)
    assert app._splits_pending and sizes.sashes == {}
    real = 1827 - 2 * px(app.root, 1)
    sizes.configure(real)
    assert not app._splits_pending
    assert sizes.sashes[app.left_split] == round(real * LEFT)
    assert sizes.sashes[app.main_split] == round(3836 * MAIN)


def test_a_fresh_start_gives_the_default_proportions(start):
    app = start()
    assert near(shares(app), (MAIN, LEFT))
    assert app.views.winfo_height() > 3 * app.messages.winfo_height()
    assert app.side.winfo_width() < app.left_part.winfo_width() / 2


def test_every_start_is_maximized(start, hidden_windows):
    assert start(OLD_LAYOUT).root in hidden_windows.zoomed


def test_the_window_under_the_maximized_one_has_the_default_size(start):
    app = start(OLD_LAYOUT)
    width, height = app.root.winfo_screenwidth(), app.root.winfo_screenheight()
    assert app.root.geometry() == f"{int(width * 0.958)}x{int(height * 0.894)}+0+0"


@pytest.mark.parametrize("entries", [OLD_LAYOUT, {"split_left": 0.05}, {"split_main": 0.95}], ids=str)
def test_layout_entries_in_the_settings_file_are_ignored(start, entries):
    assert near(shares(start(entries)), (MAIN, LEFT))


def test_layout_entries_go_the_next_time_the_file_is_saved(start, tmp_path):
    app = start({**OLD_LAYOUT, "font_size": 14, "hex_values": False})
    app.cmd_exit()
    data = json.loads((tmp_path / "settings.json").read_text())
    assert not set(OLD_LAYOUT) & set(data)
    assert data["font_size"] == 14 and data["hex_values"] is False


def test_a_changed_layout_is_not_restored_after_a_restart(start, hidden_windows):
    app = start()
    app.root.geometry("1200x800+40+50")
    assert lay_out(app.root)
    app.main_split.sashpos(0, 500)
    app.left_split.sashpos(0, 200)
    assert lay_out(app.root)
    assert app.main_split.sashpos(0) == 500 and app.left_split.sashpos(0) == 200    # while it runs
    app.cmd_exit()
    again = start()
    assert near(shares(again), (MAIN, LEFT)) and again.root in hidden_windows.zoomed
    assert again.root.geometry() != "1200x800+40+50"


def test_changed_execute_dividers_are_not_restored_after_a_restart(make_app, tmp_path, monkeypatch):
    (tmp_path / "settings.json").write_text(json.dumps({"show_labels": True}), encoding="utf-8")
    app = make_app()
    segments = FakeSash(monkeypatch, app.execute.segments, 1000, 0)
    labels = FakeSash(monkeypatch, app.execute, 2000, 0)
    monkeypatch.setattr(app.execute, "winfo_height", lambda: 1000)
    app.execute.place_dividers()
    assert (segments.at, labels.at) == (500, 1500)
    segments.at, labels.at = 700, 1000
    app.cmd_exit()
    again = make_app()
    segments = FakeSash(monkeypatch, again.execute.segments, 1000, 0)
    labels = FakeSash(monkeypatch, again.execute, 2000, 0)
    monkeypatch.setattr(again.execute, "winfo_height", lambda: 1000)
    again.execute.place_dividers()
    assert (segments.at, labels.at) == (500, 1500)


def test_the_labels_divider_is_kept_while_ares_runs(make_app, tmp_path, monkeypatch):
    (tmp_path / "settings.json").write_text(json.dumps({"show_labels": True}), encoding="utf-8")
    app = make_app()
    labels = FakeSash(monkeypatch, app.execute, 2000, 0)
    app.execute.place_dividers()
    labels.at = 1200
    for on in (False, True):
        app.setting_vars["show_labels"].set(on)
        app._setting_toggled("show_labels")
    assert labels.at == 1200


def test_the_other_settings_are_still_saved(start, tmp_path):
    app = start()
    app.settings.font_size, app.settings.hex_values = 14, False
    app.settings.show_labels, app.settings.tab_size = True, 8
    app.settings.last_folder = "C:/work"
    app.cmd_exit()
    saved = Settings.load(tmp_path / "settings.json")
    assert (saved.font_size, saved.hex_values, saved.show_labels, saved.tab_size,
            saved.last_folder) == (14, False, True, 8, "C:/work")


@pytest.mark.parametrize("position, wanted", [(-50, 100), (0, 100), (150, 150), (295, 200),
                                              (9000, 200)])
def test_a_position_is_kept_between_the_minimums(position, wanted):
    assert bumps.clamped(position, 300, 10, (100, 90)) == wanted


def test_a_window_too_small_for_both_minimums_shares_what_there_is():
    assert bumps.clamped(0, 110, 10, (100, 100)) == 50
    assert bumps.clamped(999, 110, 10, (100, 100)) == 50


class FakeSash:
    """A paned window's size and first divider; a hidden window has no real sash."""

    def __init__(self, monkeypatch, paned, length, at):
        self.at = at
        monkeypatch.setattr(paned, "winfo_width", lambda: length)
        monkeypatch.setattr(paned, "winfo_height", lambda: length)
        monkeypatch.setattr(paned, "sashpos", self.sashpos)

    def sashpos(self, index, position=None):
        if position is not None:
            self.at = position
        return self.at


@pytest.mark.parametrize("index, least", [(0, LEAST_WIDTHS), (1, LEAST_HEIGHTS)])
def test_dragging_a_divider_stops_at_the_minimums(app, monkeypatch, index, least):
    divider = app.dividers[index]
    first, second = (px(app.root, size) for size in least)
    sash = FakeSash(monkeypatch, divider.paned, 2000, 1000)
    divider.canvas.winfo_id()
    for delta, wanted in ((-5000, first), (9000, 2000 - px(app.root, app_module.SASH) - second)):
        divider.canvas.event_generate("<ButtonPress-1>", x=4, y=4)
        divider.canvas.event_generate("<B1-Motion>", x=4 + delta, y=4 + delta)
        divider.canvas.event_generate("<ButtonRelease-1>", x=4, y=4)
        assert sash.at == wanted


def test_dragging_the_execute_tabs_dividers_stops_at_their_minimums(app, monkeypatch):
    segments = app.execute.segments
    sash = FakeSash(monkeypatch, segments, 800, 2)
    bumps.keep_panes_now(segments)
    assert sash.at == px(app.root, LEAST_SEGMENT)
    sash.at = 799
    bumps.keep_panes_now(segments)
    assert sash.at == 800 - px(app.root, 3) - px(app.root, LEAST_SEGMENT)


def test_the_drag_of_tks_own_sash_runs_the_limit_after_tks_binding(app):
    tags = app.execute.segments.bindtags()
    assert tags.index("TPanedwindow") < tags.index(bumps.limit_tag(app.execute.segments))
    assert LEAST_LABELS
