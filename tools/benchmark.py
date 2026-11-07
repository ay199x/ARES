# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Speed benchmark: run tests/programs/loop10m.s (10,000,000 instructions).

Usage: python tools/benchmark.py [--repeat N] [--tool NAME]

--tool connects the model of a tool of the Tools menu (its module in
ares/gui/tools, for example counter) during each run, as its window would.
"""

import argparse
import importlib
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ares.assembler import assemble  # noqa: E402
from ares.gui import tools  # noqa: E402
from ares.machine import Machine, StopReason  # noqa: E402
from ares.program import Program  # noqa: E402

BENCHMARK = ROOT / "tests" / "programs" / "loop10m.s"
INSTRUCTIONS = 10_000_000


def tool_names():
    """The modules of the tools that exist, which --tool takes."""
    return [tool.module for tool in tools.TOOLS if tools.available(tool.command)]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Measure full-speed run time.")
    parser.add_argument("--repeat", type=int, default=5, help="number of runs")
    parser.add_argument("--tool", choices=tool_names(),
                        help="connect this tool's model during the runs")
    args = parser.parse_args(argv)
    window = None
    if args.tool:
        window = importlib.import_module(f"ares.gui.tools.{args.tool}").WINDOW

    with tempfile.TemporaryDirectory(prefix="ares-") as work:
        start = time.perf_counter()
        result = assemble(BENCHMARK.read_text(encoding="utf-8"), work)
        assemble_time = time.perf_counter() - start
        if not result.ok:
            for message in result.messages:
                print(message.format(), file=sys.stderr)
            return 1
        program = Program(result.elf_path)

    times = []
    for _ in range(args.repeat):
        machine = Machine(program)
        model = None
        if window is not None:
            model = window.MODEL()
            model.connect(machine)
        start = time.perf_counter()
        reason = machine.run()
        if model is not None:
            model.update()
        times.append(time.perf_counter() - start)
        if reason is not StopReason.EXIT:
            print(f"unexpected stop: {reason}", file=sys.stderr)
            return 1

    best = min(times)
    connected = f" with the {window.NAME} connected" if window is not None else ""
    print(f"assemble and link: {assemble_time * 1000:.0f} ms")
    print(f"run {INSTRUCTIONS:,} instructions{connected}: best {best:.3f} s, "
          f"median {statistics.median(times):.3f} s over {args.repeat} runs "
          f"({INSTRUCTIONS / best / 1e6:.0f} million instructions per second)")
    if model is not None and hasattr(model, "total"):
        print(f"the tool counted {model.total:,} instructions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
