# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The start of the package that tools/check_package.py makes: ARES, working through a list.

It starts as ARES does, then assembles and runs each program of the list named by
ARES_CHECK_LIST with ARES's own commands, typing what the program asks for. It opens every tool,
plays a film of ARM X-Ray and opens the window inside a block, runs the Pipeline Simulator's
tour, shows one of ARES's message boxes, reads the documents, writes what it saw to the report
file of the list, and closes.
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


def example(name):
    from ares.examples import example_programs
    return next(path for path in example_programs() if path.name == name)


def assembled(app, name):
    """Steps that open an example and assemble it; its tab."""
    tab = app.open_path(example(name))
    app.run("assemble")
    yield from until(lambda: not app.assembling, 30)
    if app.runner is None:
        raise RuntimeError(f"{name} did not assemble")
    return tab


def xray_film(app):
    """ARM X-Ray: Step plays the film of LDR SP, =stack; Skip to end shows its end, where the
    panel tells what it did; the window inside the ALU opens and closes."""
    tab = yield from assembled(app, "xray_tour.s")
    app.open_tool("tool_xray")
    tool = app.tool_windows["tool_xray"]
    tool.connect_button.invoke()
    app.run("step")
    yield from until(lambda: tool.film is not None and tool.film.steps, 20)
    for _ in range(10):             # some pictures of the film, by its own clock
        app.root.update()
        yield
    tool.skip()
    yield
    if app.machine.reg(13) == 0 or "SP" not in tool.panel_text():
        raise RuntimeError(f"the film's end does not show SP: {tool.panel_text()!r}")
    inside = tool.open_inside("ALU")
    app.root.update()
    if inside is None or inside.window is None:
        raise RuntimeError("the window inside the ALU did not open")
    inside.close()
    tool.close()
    app.close_tab(tab)


def pipeline_tour(app):
    """The Pipeline Simulator: pipeline_tour.s run with forwarding and 2-bit prediction gives
    the cycles and CPI its walk in the help says."""
    from ares.gui.tools.pipeline import TOUR, TOUR_SETTINGS, two_places
    from ares.runner import State
    tab = yield from assembled(app, "pipeline_tour.s")
    app.open_tool("tool_pipeline")
    tool = app.tool_windows["tool_pipeline"]
    tool.connect_button.invoke()
    tool.confirm(TOUR_SETTINGS[2])
    app.run("go")
    yield from until(lambda: app.runner.state is State.FINISHED, 60)
    tool.refresh()
    app.root.update()
    totals = tool.model.totals
    shown = (f"{totals.cycles} cycles, CPI {two_places(totals.cycles, totals.instructions)}, "
             f"steady-state CPI {two_places(totals.cycles - 4, totals.instructions)}")
    if shown != TOUR[2]:
        raise RuntimeError(f"the pipeline shows {shown!r}, not {TOUR[2]!r}")
    tool.close()
    app.close_tab(tab)


def message_box(app):
    """One of ARES's own message boxes: drawn with its sign and button, then answered."""
    from ares.gui import msgbox
    box = msgbox.MessageBox(app.root, msgbox.INFORMATION, "ARES", "A message box of ARES.")
    try:
        yield from until(lambda: bool(box.window.winfo_ismapped()), 15)
    except TimeoutError:
        raise RuntimeError("the message box is not shown") from None
    if box.sign_image is None or not box.buttons:
        raise RuntimeError("the message box has no sign or no button")
    box.press(msgbox.OK)
    if box.answer != msgbox.OK or box.window is not None:
        raise RuntimeError("the message box did not close with OK")


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
    for name, part in (("ARM X-Ray", xray_film), ("Pipeline Simulator", pipeline_tour),
                       ("message box", message_box)):
        try:
            yield from part(app)
            report["working"][name] = "ok"
        except Exception:
            report["working"][name] = traceback.format_exc()
        save()
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
    report = {"programs": {}, "tools": {}, "working": {}}

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
