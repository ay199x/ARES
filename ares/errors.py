# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Errors that stop a running program."""


class RuntimeFault(Exception):
    """The program did something that stops the run, e.g. a bad memory access."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message
