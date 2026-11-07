# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The Tools menu's tools.

TOOLS lists them as the Tools menu shows them, in alphabetical order; Memory
Map follows after a separator (MENU). Each tool lives in a module of this
package that names its window class in WINDOW (an ares.gui.tools.frame
ToolWindow, whose MODEL is its model). A tool whose module does not exist
yet is in the menu, but cannot be chosen. The modules are imported by name,
so a packaged ARES must include them explicitly (hidden imports).
"""

import importlib
import importlib.util
from dataclasses import dataclass


@dataclass(frozen=True)
class Tool:
    command: str        # the command that opens its window (App.run)
    label: str          # the menu's label: "&" before the access letter
    module: str         # the module of this package that holds it


TOOLS = [
    Tool("tool_xray", "&ARM X-Ray", "xray"),
    Tool("tool_bht", "&BHT Simulator", "bht"),
    Tool("tool_bitmap", "B&itmap Display", "bitmap"),
    Tool("tool_cache", "&Data Cache Simulator", "cache"),
    Tool("tool_labsim", "Digital &Lab Sim", "labsim"),
    Tool("tool_counter", "Dynamic Instruction &Counter", "counter"),
    Tool("tool_fpr", "&Floating Point Representation", "fpr"),
    Tool("tool_mmio", "&Keyboard and Display MMIO Simulator", "mmio"),
    Tool("tool_memref", "Memory &Reference Visualization", "memref"),
]
COMMANDS = {tool.command: tool for tool in TOOLS}
# The Tools menu, as the entries of ares.gui.app.MENUS: (command, label, shortcut); None
# is a separator.
MENU = [(tool.command, tool.label, None) for tool in TOOLS] + [
    None, ("memory_map", "&Memory Map", None)]

_found = {}


def available(command):
    """True when command opens a tool that exists (its module is there)."""
    tool = COMMANDS.get(command)
    if tool is None:
        return False
    if command not in _found:
        _found[command] = importlib.util.find_spec(f"{__name__}.{tool.module}") is not None
    return _found[command]


def window_class(command):
    """The window class (a ToolWindow) of the tool that command opens."""
    return importlib.import_module(f"{__name__}.{COMMANDS[command].module}").WINDOW
