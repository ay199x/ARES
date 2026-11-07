# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Go, Step, Backstep, Pause, Stop and Reset for a loaded program.

The window calls run_slice() again and again (between screen updates) while
the state is RUNNING or WAITING; run() does the same in a loop for the
command-line runner and the tests. Pause and Stop may also be called from
another thread: they take effect between slices, so within one slice
(about 30 ms).
"""

import enum
import time

from .machine import DIALOG, INPUT, SLEEP


class State(enum.Enum):
    READY = "ready"             # loaded or Reset, nothing executed yet
    RUNNING = "running"         # Go: running in time slices
    PAUSED = "paused"           # after Pause, Step, Backstep or at a breakpoint
    WAITING = "waiting"         # for a typed line or a dialog answer
    FINISHED = "finished"       # ended, stopped by a runtime error, or Stop


CAN_START = (State.READY, State.PAUSED)


class Runner:
    """Controls one Machine.

    dialogs(request) answers dialog services at once (command-line runner,
    tests); without it the window shows the dialog and calls answer().
    input_source(request) returns more typed input for machine.console (empty
    if it fed the console itself), or None at the end of the input; without
    it the window feeds machine.console.
    """

    def __init__(self, machine, dialogs=None, input_source=None,
                 record_while_running=False):
        self.machine = machine
        self.dialogs = dialogs
        self.input_source = input_source
        self.record_while_running = record_while_running
        self.state = State.READY
        self.stopped_by_user = False
        self._slow = False              # Go one recorded instruction per slice
        self._step_waits = False        # the request came from Step, not Go
        self._pause = self._stop = False
        self._busy = False

    # Commands -----------------------------------------------------------

    def go(self, slow=False):
        """Start or continue running; slow runs one instruction per run_slice()."""
        if self.state in CAN_START:
            self._pause = False
            self._slow = slow
            self.machine.resume_here()
            self.state = State.RUNNING

    def set_slow(self, slow):
        """Go on at full speed, or with one recorded instruction per run_slice() (slow)."""
        self._slow = slow

    def step(self):
        """Execute one instruction (answering a dialog or reading input if it can)."""
        if self.state in CAN_START:
            self._step()
            self._resolve_waiting()
        return self.state

    def backstep(self):
        """Undo the last recorded instruction; False when nothing can be undone."""
        if self.state is State.RUNNING or not self.machine.backstep():
            return False
        self.state = State.PAUSED
        self.stopped_by_user = self._step_waits = False
        return True

    def pause(self):
        """Pause a run (from any thread)."""
        self._pause = True
        if not self._busy:
            self._apply_flags()

    def stop(self):
        """End the run; only Reset (or Backstep) can bring the program back."""
        self._stop = True
        if not self._busy:
            self._apply_flags()

    def reset(self):
        """Reload the program and its initial state; breakpoints stay."""
        self.machine.reset()
        self.state = State.READY
        self.stopped_by_user = self._step_waits = False
        self._pause = self._stop = False

    def answer(self, value):
        """Answer the dialog the program waits for."""
        self.machine.answer(value)

    def set_breakpoint(self, address, on=True):
        self.machine.set_breakpoint(address, on)

    def toggle_breakpoint(self, address):
        self.set_breakpoint(address, address not in self.machine.breakpoints)

    @property
    def request(self):
        """What the program waits for (machine.Request), or None."""
        return self.machine.request if self.state is State.WAITING else None

    def sleep_remaining(self):
        """Seconds until a sleeping program goes on (0 when it is not asleep)."""
        request = self.machine.request
        if self.state is State.RUNNING and request is not None and request.kind == SLEEP:
            return max(0.0, request.until - time.perf_counter())
        return 0.0

    # Running ------------------------------------------------------------

    def run_slice(self):
        """Advance the program by one time slice (or one slow instruction)."""
        self._busy = True
        try:
            self._apply_flags()
            if self.state is State.WAITING:
                self._resolve_waiting()
            elif self.state is State.RUNNING:
                self._run_once()
        finally:
            self._busy = False
        self._apply_flags()
        return self.state

    def run(self, time_limit=None):
        """Go and keep running until the program finishes, pauses or needs help.

        Returns the state: FINISHED, PAUSED (Pause, breakpoint, time_limit
        reached) or WAITING (input or a dialog nobody here can answer).
        """
        self.go()
        deadline = None if time_limit is None else time.monotonic() + time_limit
        while self.state in (State.RUNNING, State.WAITING):
            if self.state is State.WAITING and not self._can_resolve():
                break
            self.run_slice()
            delay = self.sleep_remaining()
            if delay:
                time.sleep(min(delay, 0.01))
            if deadline is not None and time.monotonic() > deadline:
                self.pause()
        return self.state

    def _run_once(self):
        machine = self.machine
        if not self._slow:
            machine.run_slice(record=self.record_while_running)
            self._update(stepping=False)
        elif not machine.request_done():
            self._update(stepping=False)    # a sleep runs out first, as in a fast Go
        elif machine.breakpoint_here():
            machine.at_breakpoint = True
            self.state = State.PAUSED
        else:
            machine.step()
            self._update(stepping=False)

    def _step(self):
        self._skip_sleep()
        self.machine.step()
        self._skip_sleep()
        self._update(stepping=True)

    def _skip_sleep(self):
        """Step does not wait for a sleep, neither a pending one nor its own."""
        request = self.machine.request
        if request is not None and request.kind == SLEEP:
            self.machine.request = None

    def _update(self, stepping):
        machine = self.machine
        if machine.stop_reason is not None:
            self.state = State.FINISHED
        elif machine.request is not None and machine.request.kind != SLEEP:
            self.state = State.WAITING
            self._step_waits = stepping
        elif stepping or machine.at_breakpoint:
            self.state = State.PAUSED
        else:
            self.state = State.RUNNING

    def _can_resolve(self):
        """True when the pending request can be answered without the window."""
        machine, request = self.machine, self.machine.request
        if request is None or machine.request_done():
            return True
        if request.kind == INPUT:
            return self.input_source is not None
        return request.kind == DIALOG and self.dialogs is not None

    def _resolve_waiting(self):
        """Answer the request if possible, then continue the Go or the Step."""
        machine = self.machine
        while self.state is State.WAITING:
            request = machine.request
            if request is not None and not machine.request_done():
                if request.kind == INPUT and self.input_source is not None:
                    line = self.input_source(request)
                    if line is None:
                        machine.console.close_input()
                    else:
                        machine.console.feed(line)
                elif request.kind == DIALOG and self.dialogs is not None:
                    machine.answer(self.dialogs(request))
                if not machine.request_done():
                    return
            if self._step_waits:
                self._step()
            else:
                self.state = State.RUNNING
                return

    def _apply_flags(self):
        if self._stop:
            self._stop = self._pause = False
            if self.state is not State.FINISHED:
                self.state = State.FINISHED
                self.stopped_by_user = True
                self.machine.close_files()
        elif self._pause:
            self._pause = False
            if self.state in (State.RUNNING, State.WAITING):
                self.state = State.PAUSED
