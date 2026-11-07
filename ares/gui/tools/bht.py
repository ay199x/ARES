# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Tools > BHT Simulator: branch prediction with a branch history table.

The table has 8, 16 or 32 entries. Each conditional branch the program
executes (B with a condition other than AL, such as BNE or BGT; not BL, BX
or other instructions that change PC) uses the entry its address selects:
the address divided by 4, modulo the number of entries. The entry predicts
taken or not taken, remembers the last one or two outcomes (its history
bits) and counts how often its prediction was right. A branch is taken when
its condition holds for the flags it finds as it runs.

Only the addresses of the program's conditional branches are hooked
(ares.observers): a connected simulator costs Python time per conditional
branch executed, never per instruction.
"""

import tkinter as tk
from collections import deque
from dataclasses import dataclass
from itertools import islice
from tkinter import ttk

from ...disasm import basic
from ...machine import condition_passed
from ...runner import State
from .. import style
from ..execute import CURRENT, FAILED
from ..registers import CHANGED
from ..table import Column, Row, Table, column_width
from ..widgets import HidingBars, ReadOnlyText, px, tab_moves_on
from .frame import ToolModel, ToolWindow

ENTRIES = (8, 16, 32)           # the choices for the number of entries
HISTORY_BITS = (1, 2)           # and for the outcomes each entry remembers
DEFAULTS = (16, 1, False)       # entries, history bits, initial prediction (not taken)
PREDICTIONS = ("Not taken", "Taken")    # a prediction as the table shows it, by taken
OUTCOMES = ("not taken", "taken")       # the same in the log
LOG_LIMIT = 1000                # branches the log keeps, the newest

# For each condition code (EQ ... AL), whether it holds for each value of the
# flags N, Z, C and V (CPSR bits 31-28).
HOLDS = tuple(tuple(bool(condition_passed(cond, flags << 28)) for flags in range(16))
              for cond in range(16))

# The coloured row: the entry of the branch that runs next (light yellow, as the
# Text Segment's next instruction), else that of the last branch executed: green
# when its prediction was right (as changed registers), light red when it was wrong.
NEXT_COLOUR, RIGHT_COLOUR, WRONG_COLOUR = CURRENT, CHANGED, FAILED

FIELDS = ("Instruction", "Address", "Index", "Branches", "Accuracy")    # at the left
FIELD_WIDTH = 16                # characters of a field
VISIBLE_ROWS = 16               # rows of the table on the screen
LOG_LINES = 6                   # lines of the log on the screen
LOG_CHARS = 80                  # characters of a log line on the screen

HELP = """\
The BHT Simulator shows how a branch history table predicts the conditional branches of
the program: whether each one will branch (taken) or go on with the next instruction (not
taken), and how often the predictions are right.

Click Connect to ARM, then run the program (Go, Step). The table follows the program, also
while it runs at full speed. Disconnect from ARM stops the observing; the table stays.
Close closes the tool and stops the observing.

The conditional branches are the B instructions with a condition: BEQ, BNE, BCS (BHS),
BCC (BLO), BMI, BPL, BVS, BVC, BHI, BLS, BGE, BLT, BGT and BLE. B without a condition
(or with AL) always branches and is not predicted, nor are BL, BX and the other
instructions that change PC. A branch is taken when its condition holds for the flags N,
Z, C and V as the branch runs: BNE after CMP R0, #3 is taken when R0 is not 3.

Number of entries (8, 16 or 32): the rows of the table. A branch uses the entry of its
address divided by 4, modulo the number of entries: with 16 entries the branch at
0x0000001c uses entry 7, and so does the branch at 0x0000005c. Branches that share an
entry disturb each other's predictions.

History bits (1 or 2): how many of its last outcomes an entry remembers. With 1 bit the
entry predicts what its last branch did. With 2 bits its prediction changes only after
two wrong predictions in a row, so a loop that ends now and then stays predicted taken.

Initial prediction (Not taken or Taken): the prediction of every entry at the start. Its
history starts as if its branches had always done that.

Choosing another value in one of these lists starts the table again, as Reset does.

The table: Index, the entry's number; History, the outcomes it remembers, the oldest
first (T taken, NT not taken); Prediction, what it predicts for its next branch; Correct
and Incorrect, how many of its predictions were right and wrong; Accuracy, the share of
right ones.

At the left: Instruction, Address and Index of the branch whose entry is coloured. While
the program waits before a conditional branch (after Step, Pause or at a breakpoint), its
entry is light yellow, and its Prediction is the one about to be checked. Otherwise the
entry of the last branch executed is coloured: green when its prediction was right, light
red when it was wrong. Branches and Accuracy are for all the branches executed.

The log has a line for each branch executed, with its entry, the prediction and what the
branch did. It keeps the last 1,000 lines. While the program runs at full speed the table
follows it and the log waits: it gets the newest lines when the run stops (Pause, a
breakpoint, the end).

A branch counts once, when it runs. A breakpoint, Pause or Step that stops before it does
not count it; it counts when the program goes on. A branch to itself whose condition
holds (BEQ . for example) ends the program, as B . does, and does not count.

The table keeps what it has learned when the program is assembled again, reset (Reset,
F12) or stepped back (Backstep undoes the instruction, but the branch was executed): only
the tool's Reset and the lists above start it again. The tool stays connected when the
program is assembled again or its file is closed.

While the tool is connected a run takes longer: ARES looks at each conditional branch as
it runs, and each conditional branch in the program makes every instruction a little
slower. A loop of 10,000,000 instructions that runs BNE 2,000,000 times takes a few
seconds instead of a tenth of a second.
"""


def is_conditional_branch(word):
    """True for an ARM B instruction with a condition other than AL (BEQ ... BLE)."""
    return (word >> 24) & 0xF == 0xA and word >> 28 < 0xE


@dataclass(frozen=True)
class Branch:
    """A conditional branch of the program."""
    address: int
    text: str           # as the Text Segment's Basic column shows it
    holds: tuple        # whether it is taken, for each value of the flags N, Z, C and V


def transitions(bits):
    """For each key of an entry with bits history bits, its next state (see BHTModel).

    The outcome goes into the history and the oldest one out. A wrong
    prediction changes once every outcome the history holds disagrees with
    it: with one history bit after one wrong prediction, with two after two
    in a row.
    """
    every = (1 << bits) - 1                 # a history of taken outcomes only
    following = []
    for key in range(4 << bits):
        history, prediction, taken = key >> 2, key >> 1 & 1, key & 1
        history = (history << 1 | taken) & every
        if prediction != taken and history == (every if taken else 0):
            prediction = taken
        following.append(history << 1 | prediction)
    return tuple(following)


def outcome(key):
    """(predicted, taken) of a key: the prediction is bit 1, the outcome bit 0."""
    return bool(key & 2), bool(key & 1)


RIGHT = tuple(key >> 1 & 1 == key & 1 for key in range(16))     # by key: was it right?


def accuracy(correct, incorrect):
    """The share of right predictions as the window shows it ("" before any), rounded half
    up as by hand (29 of 32 is 90.63%; Python's own rounding would show 90.62%)."""
    total = correct + incorrect
    if not total:
        return ""
    hundredths = (20000 * correct + total) // (2 * total)       # of a per cent
    return f"{hundredths // 100}.{hundredths % 100:02d}%"


def log_line(event):
    """The log's line for a branch executed: event is (branch, index, key)."""
    branch, index, key = event
    predicted, taken = outcome(key)
    return (f"{branch.text} at 0x{branch.address:08x}, index {index}: predicted "
            f"{OUTCOMES[predicted]}, was {OUTCOMES[taken]} "
            f"({'correct' if predicted == taken else 'incorrect'})")


class BHTModel(ToolModel):
    """The branch history table, and the log of the branches executed.

    Each entry is in a state: its history (the outcomes it remembers, 1 for
    taken, the newest in bit 0) shifted left by one, with its prediction in
    bit 0. A branch that uses the entry makes a key: the state shifted left
    by one, with the branch's outcome in bit 0. transitions() gives the
    entry's next state for each key, and RIGHT whether its prediction was
    right. counts holds how many predictions of each entry were wrong and
    right; the log holds (branch, index, key) for each branch executed, the
    newest last.

    The table keeps learning across Assemble, Reset and Backstep: only reset()
    and configure() start it again.
    """

    def __init__(self):
        super().__init__()
        self.entries, self.history_bits, self.initial = DEFAULTS
        self._branches = {}             # address -> Branch, of the program observed
        self.reset()

    def configure(self, entries, history_bits, initial):
        """New settings (initial: True predicts taken); the table starts again."""
        self.entries, self.history_bits, self.initial = entries, history_bits, initial
        self.reset()

    def reset(self):
        """Every entry back to its initial prediction and history, nothing counted, no log."""
        history = (1 << self.history_bits) - 1 if self.initial else 0
        self.states = [history << 1 | self.initial] * self.entries
        self.counts = [[0, 0] for _ in range(self.entries)]
        self.log = deque(maxlen=LOG_LIMIT)
        self._following = transitions(self.history_bits)
        self._find_entries()
        self._updated = 0

    @property
    def executed(self):
        """The branches executed since the table started."""
        return sum(wrong + right for wrong, right in self.counts)

    def index(self, address):
        """The entry the branch at address uses."""
        return (address >> 2) % self.entries

    def prediction(self, index):
        """True when the entry predicts taken."""
        return bool(self.states[index] & 1)

    def history(self, index):
        """An entry's history as the table shows it: T or NT for each outcome, the oldest first."""
        history = self.states[index] >> 1
        return ", ".join("T" if history >> k & 1 else "NT"
                         for k in reversed(range(self.history_bits)))

    def next_branch(self):
        """The conditional branch the program runs next, or None (also once it has ended)."""
        machine = self.machine
        if machine is None or machine.stop_reason is not None:
            return None
        return self._branches.get(machine.pc)

    def attach(self, machine):
        program = machine.program
        for address in program.code_addresses():
            word = program.read_word(address)
            if word is not None and is_conditional_branch(word):
                self._branches[address] = Branch(address, basic(word, address), HOLDS[word >> 28])
        self._find_entries()
        if self._branches:
            machine.observers.watch_code(self, self._branches, self._ran, flags=True)

    def detach(self, machine):
        machine.observers.forget(self)
        self._branches = {}
        self._find_entries()

    def _find_entries(self):
        """Note the entry each branch of the program uses, for _ran()."""
        self._watched = {address: (branch, self.index(address))
                         for address, branch in self._branches.items()}

    def update(self):
        """True when branches were executed since the last update."""
        executed = self.executed
        changed, self._updated = executed != self._updated, executed
        return changed

    def _ran(self, address, flags):
        """The conditional branch at address runs now and finds the flags N, Z, C and V:
        its entry's prediction is checked against what it does, and the entry learns."""
        branch, index = self._watched[address]
        key = self.states[index] << 1 | branch.holds[flags]
        self.states[index] = self._following[key]
        self.counts[index][RIGHT[key]] += 1
        self.log.append((branch, index, key))


class BHTWindow(ToolWindow):
    """Tools > BHT Simulator."""

    NAME = "BHT Simulator"
    HEADING = "Predicting branches with a branch history table"
    HELP = HELP
    MODEL = BHTModel

    def build(self, body):
        gap = px(body, 6)
        font = self.app.pane_font
        model = self.model
        self._focus = None              # (branch, index, colour) shown, see _focused()
        self._logged = (None, 0)        # the model's log as shown, and its branches then

        choices = ttk.Frame(body)
        choices.grid(row=0, column=0, columnspan=2, pady=(0, 2 * gap))
        self.lists = []
        for column, (label, values, value) in enumerate((
                ("Number of entries:", [str(n) for n in ENTRIES], str(model.entries)),
                ("History bits:", [str(n) for n in HISTORY_BITS], str(model.history_bits)),
                ("Initial prediction:", list(PREDICTIONS), PREDICTIONS[model.initial]))):
            ttk.Label(choices, text=label).grid(row=0, column=2 * column,
                                                padx=(2 * gap if column else 0, gap))
            chooser = ttk.Combobox(choices, values=values, state="readonly",
                                   width=max(map(len, values)) + 1)
            chooser.set(value)
            chooser.grid(row=0, column=2 * column + 1)
            chooser.bind("<<ComboboxSelected>>", self._chosen)
            self.lists.append(chooser)

        fields = ttk.Frame(body)
        fields.grid(row=1, column=0, sticky="n", padx=(0, 2 * gap))
        self.fields = {}
        for row, label in enumerate(FIELDS):
            ttk.Label(fields, text=label).grid(row=2 * row, column=0,
                                               pady=(2 * gap if label == "Branches" else 0, 0))
            variable = self.fields[label] = tk.StringVar(master=body)
            ttk.Entry(fields, textvariable=variable, state="readonly", width=FIELD_WIDTH,
                      justify="center", takefocus=False).grid(row=2 * row + 1, column=0,
                                                              pady=(0, gap))

        holder = tk.Frame(body)             # the table, as large as VISIBLE_ROWS rows need
        holder.grid(row=1, column=1, sticky="nsew")
        self.table = table = Table(holder, [
            _column(body, font, "index", "Index", 5, "center"),
            _column(body, font, "history", "History", 6, "center"),
            _column(body, font, "prediction", "Prediction", 9, "center"),
            _column(body, font, "correct", "Correct", 10, "center"),
            _column(body, font, "incorrect", "Incorrect", 10, "center"),
            _column(body, font, "accuracy", "Accuracy", 7, "center")], font, stripes=False)
        table.pack(fill="both", expand=True)
        border = 2 * table.winfo_pixels(table.cget("borderwidth"))
        holder.configure(width=sum(column.width for column in table.columns) + border
                         + table.vscroll.winfo_reqwidth(),
                         height=int(table.header.cget("height")) + border
                         + VISIBLE_ROWS * table.row_height)
        holder.pack_propagate(False)
        table.set_rows(model.entries, self._row)
        # Return presses the framed button here too; the table would keep it for its rows.
        for key in ("<Return>", "<KP_Enter>"):
            table.body.bind(key, self._return)

        ttk.Label(body, text="Log").grid(row=2, column=0, columnspan=2, sticky="w",
                                         pady=(2 * gap, 0))
        page = style.sunken(tk.Frame(body))     # the log and its scroll bars
        page.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.log = text = _Log(page, font=font, wrap="none", height=LOG_LINES,
                               background=style.WINDOW, foreground=style.TEXT, borderwidth=0,
                               highlightthickness=0, padx=px(body, 4), pady=px(body, 2))
        tab_moves_on(text)
        yscroll = ttk.Scrollbar(page, orient="vertical", command=text.yview)
        xscroll = ttk.Scrollbar(page, orient="horizontal", command=text.xview)
        text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)
        ring = page.winfo_pixels(page.cget("borderwidth"))
        page.configure(width=LOG_CHARS * font.measure("0") + yscroll.winfo_reqwidth()
                       + 2 * (ring + text.winfo_pixels(text.cget("padx"))),
                       height=LOG_LINES * font.metrics("linespace")
                       + 2 * (ring + text.winfo_pixels(text.cget("pady"))))
        page.grid_propagate(False)
        self.bars = HidingBars(text, yscroll, xscroll)
        body.columnconfigure(1, weight=1)       # the table takes the width the log needs

    # What the window shows --------------------------------------------------------

    def refresh(self):
        """Show what the program did since the last refresh, and the entry now coloured:
        show() changes only what changed."""
        self.model.update()
        self.show()

    def show(self):
        model = self.model
        racing = self._racing()
        self._focus = self._focused(racing)
        self.table.refresh()
        if self._focus is None:
            texts = ("", "", "")
        else:
            branch, index, _ = self._focus
            texts = (branch.text, f"0x{branch.address:08x}", str(index))
        executed = model.executed
        correct = sum(counts[1] for counts in model.counts)
        texts += (str(executed), accuracy(correct, executed - correct))
        for label, text in zip(FIELDS, texts):
            if self.fields[label].get() != text:
                self.fields[label].set(text)
        if not racing:
            self._show_log(executed)

    def _racing(self):
        """True while the program runs at full speed: the main window shows no next
        instruction then, and the log waits until the run stops (the newest lines would
        follow each other too fast to be read)."""
        runner = self.app.runner
        return (runner is not None and runner.state is State.RUNNING
                and self.app.run_speed is None)

    def _focused(self, racing):
        """(branch, index, colour) of the branch the fields and the coloured row are about,
        or None: the conditional branch that runs next while the main window shows the
        next instruction (not while racing, nor once the program has ended), else the
        last one executed."""
        model, runner = self.model, self.app.runner
        if runner is not None and runner.state is not State.FINISHED and not racing:
            upcoming = model.next_branch()
            if upcoming is not None:
                return upcoming, model.index(upcoming.address), NEXT_COLOUR
        if model.log:
            branch, index, key = model.log[-1]
            return branch, index, RIGHT_COLOUR if RIGHT[key] else WRONG_COLOUR
        return None

    def _row(self, index):
        """The table's row of an entry, in the colour of the focus when it is its entry."""
        model, focus = self.model, self._focus
        incorrect, correct = model.counts[index]
        return Row((str(index), model.history(index), PREDICTIONS[model.prediction(index)],
                    str(correct), str(incorrect), accuracy(correct, incorrect)),
                   focus[2] if focus is not None and focus[1] == index else "")

    def _show_log(self, executed):
        """Add the lines of the branches executed since the last time (at most LOG_LIMIT)."""
        log, text = self.model.log, self.log
        shown, before = self._logged
        self._logged = (log, executed)
        if shown is not log:            # a new table: its log starts empty
            text.clear()
            before = 0
        new = min(executed - before, len(log))
        if new > 0:
            if new == LOG_LIMIT:
                text.clear()
            text.write("".join(log_line(event) + "\n"
                               for event in islice(log, len(log) - new, None)))
            text.keep_last(LOG_LIMIT)
            text.see_end()
        if new > 0 or shown is not log:
            self.bars.schedule()

    # Choosing the settings --------------------------------------------------------

    def _chosen(self, event=None):
        """A value was chosen in one of the lists: other settings start the table again."""
        entries, bits, initial = (chooser.get() for chooser in self.lists)
        settings = (int(entries), int(bits), initial == PREDICTIONS[True])
        model = self.model
        if settings == (model.entries, model.history_bits, model.initial):
            return
        model.configure(*settings)
        self.table.set_rows(model.entries, self._row)
        self.show()


def _column(widget, font, column_id, heading, chars, anchor):
    """A column of the table, wide enough for chars characters; all share the spare width."""
    return Column(column_id, heading, column_width(widget, font, chars, heading), anchor,
                  stretch=True)


class _Log(ReadOnlyText):
    """The log's text, which keeps only its newest lines."""

    def keep_last(self, lines):
        """Drop the oldest lines beyond the given number."""
        extra = int(self.index("end-1c").split(".")[0]) - 1 - lines
        if extra > 0:
            self.tk.call(self._original, "delete", "1.0", f"{extra + 1}.0")


WINDOW = BHTWindow
