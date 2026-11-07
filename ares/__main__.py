# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Start the ARES window: python -m ares [file.s ...]"""

import sys

from ares.gui.start import main

if __name__ == "__main__":
    sys.exit(main())
