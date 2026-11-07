# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Where ARES finds the GNU assembler and linker."""

import sys
from pathlib import Path

import pytest

from ares import toolchain


def test_the_environment_variable_names_the_folder(monkeypatch, tmp_path):
    monkeypatch.setenv(toolchain.TOOLCHAIN_VARIABLE, str(tmp_path))
    assert toolchain.toolchain_dir() == tmp_path


def test_the_variable_comes_before_a_packaged_folder(monkeypatch, tmp_path):
    monkeypatch.setenv(toolchain.TOOLCHAIN_VARIABLE, str(tmp_path))
    monkeypatch.setattr(sys, "_MEIPASS", "bundle", raising=False)
    assert toolchain.toolchain_dir() == tmp_path


@pytest.mark.parametrize("value", [None, ""])
def test_without_it_the_project_folder_is_used(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(toolchain.TOOLCHAIN_VARIABLE, raising=False)
    else:
        monkeypatch.setenv(toolchain.TOOLCHAIN_VARIABLE, value)
    assert toolchain.toolchain_dir() == (toolchain.PROJECT_ROOT / "vendor"
                                         / toolchain.platform_tag())


def test_a_packaged_ares_uses_its_own_folder(monkeypatch):
    monkeypatch.delenv(toolchain.TOOLCHAIN_VARIABLE, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "bundle", raising=False)
    assert toolchain.toolchain_dir() == Path("bundle") / "toolchain"


def test_a_missing_tool_names_the_folder_it_looked_in(monkeypatch, tmp_path):
    monkeypatch.setenv(toolchain.TOOLCHAIN_VARIABLE, str(tmp_path))
    with pytest.raises(toolchain.ToolchainMissingError, match="not found in"):
        toolchain.tool_path(toolchain.ASSEMBLER)
