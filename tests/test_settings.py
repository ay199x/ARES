# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Per-user settings: defaults, saving, loading and damaged files."""

import json
from dataclasses import asdict

import pytest

from ares import settings as settings_module
from ares.settings import DEFAULT_FONT, Settings, default_path, installed_family


def test_defaults_follow_the_specification():
    s = Settings()
    assert s.require_capitals is True
    assert s.backstep_while_running is False
    assert s.show_labels is False and s.assemble_on_open is False and s.popup_input is False
    assert s.hex_addresses is True and s.hex_values is True
    assert s.font_size == settings_module.DEFAULT_SIZE
    assert s.font_family == settings_module.DEFAULT_FONT
    assert s.show_line_numbers is True and s.tab_spaces is True


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "deep" / "folder" / "settings.json"
    s = Settings(show_labels=True, require_capitals=False, font_family="Courier New",
                 font_size=16, tab_size=8, tab_spaces=False, last_folder="C:/work")
    assert s.save(path)
    assert Settings.load(path) == s
    assert list(tmp_path.joinpath("deep", "folder").iterdir()) == [path]   # no temporary files left


def test_missing_file_gives_defaults(tmp_path):
    assert Settings.load(tmp_path / "none.json") == Settings()


@pytest.mark.parametrize("content", ["", "{", "[1, 2]", "null", "42", "\x00\xff",
                                     pytest.param("[" * 100000, id="RecursionError")])
def test_damaged_file_gives_defaults(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="latin-1")
    assert Settings.load(path) == Settings()


def test_file_with_a_byte_order_mark_is_read(tmp_path):
    # As an editor may save it ("UTF-8 with BOM").
    path = tmp_path / "settings.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"font_size": 16}).encode("utf-8"))
    assert Settings.load(path).font_size == 16


@pytest.mark.parametrize("key, value", [
    ("show_labels", 1), ("show_labels", "yes"), ("font_size", True), ("font_size", 12.5),
    ("font_size", 5), ("font_size", 73), ("tab_size", 0), ("tab_size", 17),
    ("font_family", ""), ("font_family", "   "), ("font_family", 3), ("last_folder", None),
    ("last_folder", "x" * 1001),
])
def test_invalid_values_fall_back_to_their_default(tmp_path, key, value):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({key: value, "show_line_numbers": False}), encoding="utf-8")
    loaded = Settings.load(path)
    assert getattr(loaded, key) == getattr(Settings(), key)
    assert loaded.show_line_numbers is False        # the valid neighbour is kept


def test_unknown_keys_are_ignored_and_gone_after_a_save(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"colour": "red", "split_left": 0.5, "geometry": "900x700+5+5",
                                "maximized": False, "font_size": 14}), encoding="utf-8")
    loaded = Settings.load(path)
    assert loaded.font_size == 14
    assert loaded == Settings(font_size=14)
    loaded.save(path)
    assert set(json.loads(path.read_text())) == set(asdict(Settings()))


@pytest.mark.parametrize("name", ["geometry", "maximized", "split_main", "split_left",
                                  "split_execute", "split_labels"])
def test_the_windows_layout_is_no_setting(name):
    assert name not in asdict(Settings())


def test_restore_defaults_keeps_the_last_folder():
    s = Settings(require_capitals=False, font_size=20, show_line_numbers=False, last_folder="/tmp")
    s.restore_defaults()
    assert s == Settings(last_folder="/tmp")


def test_save_failure_returns_false(tmp_path):
    folder = tmp_path / "settings.json"
    folder.mkdir()                  # a folder where the file should be
    assert Settings().save(folder) is False
    assert list(folder.iterdir()) == []
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert Settings().save(blocker / "settings.json") is False


def test_default_path_per_platform(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_module.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert default_path() == tmp_path / "ARES" / "settings.json"
    monkeypatch.setattr(settings_module.sys, "platform", "darwin")
    assert default_path().parts[-4:] == ("Library", "Application Support", "ARES",
                                         "settings.json")
    monkeypatch.setattr(settings_module.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    assert default_path() == tmp_path / "config" / "ARES" / "settings.json"


def test_the_default_code_font_is_taken_where_it_is_installed():
    assert installed_family(DEFAULT_FONT, {DEFAULT_FONT, "Other"}) == DEFAULT_FONT


def test_without_it_the_closest_installed_family_stands_in(monkeypatch):
    monkeypatch.setattr(settings_module, "CODE_FAMILIES", (DEFAULT_FONT, "Near", "Far"))
    assert installed_family(DEFAULT_FONT, {"Far", "Near"}) == "Near"
    assert installed_family(DEFAULT_FONT, {"Far"}) == "Far"


def test_with_none_of_them_the_name_goes_to_tk_as_it_is(monkeypatch):
    monkeypatch.setattr(settings_module, "CODE_FAMILIES", (DEFAULT_FONT, "Near"))
    assert installed_family(DEFAULT_FONT, {"Other"}) == DEFAULT_FONT


def test_a_font_the_user_chose_is_never_replaced():
    assert installed_family("Chosen", {"Other"}) == "Chosen"


def test_save_where_no_new_file_can_be_made_writes_in_place(tmp_path, monkeypatch):
    # tempfile.mkstemp would try new names without end on Windows there.
    from ares import files
    path = tmp_path / "settings.json"
    Settings().save(path)
    monkeypatch.setattr(files, "_new_file_beside", lambda path, mode: None)
    assert Settings(font_size=20).save(path)
    assert Settings.load(path).font_size == 20
