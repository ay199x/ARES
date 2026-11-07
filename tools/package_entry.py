# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The start of the package that tools/check_package.py makes: ARES, working through a list.

It starts as ARES does, then assembles and runs each program of the list named by
ARES_CHECK_LIST with ARES's own commands, typing what the program asks for. It opens every tool
and reads the documents, writes what it saw to the report file of the list, and closes.
"""

import gc
import json
import os
import sys
import time
import tkinter
import traceback

from ares.gui.start import main

STEP = 5                        # milliseconds between steps, so the window keeps working
DOCUMENTS = ("LICENSE", "THIRD_PARTY_NOTICES.txt", "licenses/GPL-3.0.txt",
             "licenses/Apache-2.0.txt", "licenses/Python-LICENSE.txt",
             "licenses/Python-parts.txt")


def until(done, limit):
    """Steps of a script: wait until done(), for at most limit seconds."""
    deadline = time.monotonic() + limit
    while not done():
        if time.monotonic() > deadline:
            raise TimeoutError("waited too long")
        yield


def find_app():
    """The application object, once the window exists."""
    module = sys.modules.get("ares.gui.app")
    if module is None:
        return None
    for item in gc.get_objects():
        if isinstance(item, module.App) and getattr(item, "editor", None) is not None:
            return item
    return None


def run_program(app, entry, result):
    """Steps that assemble and run one program of the list; what it showed goes into result."""
    from ares.runner import State
    messages = app.messages
    messages.clear(messages.run_io)
    tab = app.open_path(entry["path"])
    app.run("assemble")
    yield from until(lambda: not app.assembling, 30)
    result["assembled"] = app.runner is not None
    if app.runner is None:
        result["messages"] = messages.messages.get("1.0", "end-1c")
        app.close_tab(tab)
        return
    start = time.perf_counter()
    app.run("go")
    for line in entry["lines"]:
        if entry["keys"]:
            yield from until(lambda: messages.keys_wanted, 20)
        else:
            yield from until(lambda: messages.run_io.typing, 20)
        result.setdefault("starts", []).append(len(messages.run_io.get("1.0", "end-1c")))
        messages.paste(line + "\n")
    yield from until(lambda: app.runner.state is State.FINISHED, 60)
    result["seconds"] = round(time.perf_counter() - start, 3)
    result["output"] = messages.run_io.get("1.0", "end-1c")
    result["error"] = str(app.machine.error) if app.machine.error else None
    app.close_tab(tab)


def script(wanted, report, save):
    """All the steps."""
    box = []

    def found():
        box[:] = [find_app()]
        return box[0] is not None
    yield from until(found, 60)
    app = box[0]
    yield from until(lambda: str(app.root.state()) != "withdrawn", 30)
    from ares import toolchain
    from ares.examples import example_programs
    from ares.gui import tools
    from ares.gui.about import read_document
    report["frozen"] = bool(getattr(sys, "frozen", False))
    report["toolchain"] = str(toolchain.toolchain_dir())
    report["examples"] = [path.name for path in example_programs()]
    for entry in wanted["programs"]:
        result = report["programs"].setdefault(entry["name"], {})
        try:
            yield from run_program(app, entry, result)
        except Exception:
            result["failed"] = traceback.format_exc()
        save()
        yield
    for name in tools.COMMANDS:
        try:
            app.open_tool(name)
            app.root.update()
            app.tool_windows[name].close()
            report["tools"][name] = "opened"
        except Exception:
            report["tools"][name] = traceback.format_exc()
        yield
    report["documents"] = {name: len(read_document(name)) for name in DOCUMENTS}
    # An error in a Tk callback goes to ARES Messages, not to the code above.
    report["internal errors"] = app.messages.messages.get("1.0", "end").count("Internal error")
    report["done"] = True
    save()
    app.root.after(200, app.root.destroy)


def check_on(root):
    """Go through the list of ARES_CHECK_LIST once root, the main window, is running."""
    with open(os.environ["ARES_CHECK_LIST"], encoding="utf-8") as f:
        wanted = json.load(f)
    report = {"programs": {}, "tools": {}}

    def save():
        with open(wanted["report"], "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1)

    steps = script(wanted, report, save)

    def step():
        try:
            next(steps)
        except StopIteration:
            return
        except BaseException:
            report["failed"] = traceback.format_exc()
            save()
            root.after(200, root.destroy)
            return
        root.after(STEP, step)

    root.after(50, step)


original_start = tkinter.Tk.__init__


def start_and_check(self, *args, **options):
    original_start(self, *args, **options)
    check_on(self)


tkinter.Tk.__init__ = start_and_check

if __name__ == "__main__":
    sys.exit(main())
