# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The system's title bars: ARES's own icon; the bars themselves stay light, with dark text."""

import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import pump
from test_icons import pixels

from ares.gui import icons, titlebar, widgets


def system(platform, build=None):
    """A stand-in for the sys module: the platform, and on Windows its build."""
    if build is None:
        return SimpleNamespace(platform=platform)
    return SimpleNamespace(platform=platform,
                           getwindowsversion=lambda: SimpleNamespace(build=build))


def shown(window):
    """The window is mapped, as on the screen; hidden windows never are.

    Tk gives a window its frame at the first idle time after it is made
    (a hidden one too), before it can be mapped.
    """
    pump(window)
    window.winfo_id()
    window.event_generate("<Map>")


def test_ares_leaves_the_colours_of_the_title_bars_to_the_system(make_app):
    app = make_app()
    assert not hasattr(app, "title_bars")
    assert not hasattr(titlebar, "start") and not hasattr(titlebar, "TitleBars")
    assert "Dwm" not in Path(titlebar.__file__).read_text(encoding="utf-8")


@pytest.fixture
def iconphoto(monkeypatch):
    """The calls of iconphoto on any window: [(window, default, pictures)]; Tk is not called."""
    calls = []
    monkeypatch.setattr(tk.Wm, "iconphoto",
                        lambda self, default, *pictures: calls.append((self, default, pictures)))
    return calls


def test_the_icon_is_set_at_start_up_in_all_its_sizes(make_app, iconphoto):
    app = make_app()
    assert [(window, default) for window, default, pictures in iconphoto] == [(app.root, True)]
    pictures = iconphoto[0][2]
    assert list(pictures) == app.window_images
    assert [picture.width() for picture in pictures] == [16, 32, 48, 64, 128]
    assert [picture.height() for picture in pictures] == [16, 32, 48, 64, 128]
    for picture, size in zip(pictures, sorted(icons.WINDOW_PICTURES)):
        expected = pixels(icons.helmet_png(*icons.WINDOW_PICTURES[size]))
        assert [[None if picture.transparency_get(x, y) else picture.get(x, y)
                 for x in range(picture.width())] for y in range(picture.height())] == expected


@pytest.mark.parametrize("platform, expected", [
    ("win32", [True, True, False]),     # Windows: again once the window is shown
    ("linux", [True])])
def test_the_icon_is_given_again_once_the_window_is_shown(make_app, iconphoto, monkeypatch,
                                                         platform, expected):
    monkeypatch.setattr(titlebar, "sys", system(platform, 19045 if platform == "win32" else None))
    exact = []
    monkeypatch.setattr(titlebar, "exact_icons", exact.append)
    app = make_app()
    made = set(app.root.image_names())
    for _ in range(2):                  # shown, minimized and shown again
        shown(app.root)
    assert [default for window, default, pictures in iconphoto] == expected
    assert all(window is app.root and list(pictures) == app.window_images
               for window, default, pictures in iconphoto)
    assert set(app.root.image_names()) == made         # no picture is made after start-up
    assert exact == ([app.root] if platform == "win32" else [])     # and only once


class FakeUser32:
    """What exact_icons() asks of Windows, with 36 and 72 pixels for the display's icons."""

    def __init__(self):
        self.made = []                  # (size, the picture's bytes)
        self.sent = []                  # (frame, message, which, handle)
        self.classes = []               # (frame, index, handle)

    def GetSystemMetrics(self, metric):
        return {titlebar.SM_CXSMICON: 36, titlebar.SM_CXICON: 72}[metric]

    def CreateIconFromResourceEx(self, data, length, icon, version, width, height, flags):
        assert (length, icon, version, width) == (len(data), True, titlebar.ICON_VERSION, height)
        self.made.append((width, data))
        return 1000 + width

    def SendMessageW(self, frame, message, which, handle):
        self.sent.append((frame, message, which, handle))

    def SetClassLongPtrW(self, frame, index, handle):
        self.classes.append((frame, index, handle))


def test_windows_gets_the_helmet_at_exactly_the_sizes_it_draws(make_app, monkeypatch):
    user32 = FakeUser32()
    monkeypatch.setattr(titlebar, "_user32", lambda: user32)
    app = make_app()
    titlebar.exact_icons(app.root)
    frame = int(app.root.tk.call("wm", "frame", app.root), 16)
    assert user32.made == [(36, icons.window_png(36)), (72, icons.window_png(72))]
    assert user32.sent == [(frame, titlebar.WM_SETICON, titlebar.ICON_SMALL, 1036),
                           (frame, titlebar.WM_SETICON, titlebar.ICON_BIG, 1072)]
    assert user32.classes == [(frame, titlebar.GCLP_HICONSM, 1036), (frame, titlebar.GCLP_HICON, 1072)]


def test_a_refused_icon_leaves_the_windows_as_they_are(make_app, monkeypatch):
    user32 = FakeUser32()
    user32.CreateIconFromResourceEx = lambda *args: None
    monkeypatch.setattr(titlebar, "_user32", lambda: user32)
    titlebar.exact_icons(make_app().root)
    assert user32.sent == [] and user32.classes == []


def test_without_user32_nothing_happens(make_app, monkeypatch):
    monkeypatch.setattr(titlebar, "_user32", lambda: None)
    titlebar.exact_icons(make_app().root)


def test_macos_keeps_the_application_icon(make_app, iconphoto, monkeypatch):
    monkeypatch.setattr(titlebar, "sys", system("darwin"))
    monkeypatch.setattr(titlebar, "is_aqua", lambda widget: True)
    app = make_app()
    shown(app.root)
    assert iconphoto == []
