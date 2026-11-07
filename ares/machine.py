# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The simulated DE1-SoC computer: ARMv7 CPU, memory map and JTAG UART.

Full-speed runs execute inside Unicorn without any per-instruction Python
code. Python is called only for system calls (SVC), DE1-SoC device accesses,
the first access to each DDR3 page, breakpoint addresses and the addresses of
``B .`` instructions, and for what connected tools observe (ares.observers).
Recording history for Backstep adds hooks on every instruction and memory
write, so it is used only for Step and when asked for.
"""

import enum
import struct
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from unicorn import (UC_ARCH_ARM, UC_HOOK_CODE, UC_HOOK_INTR, UC_HOOK_MEM_FETCH_PROT,
                     UC_HOOK_MEM_UNMAPPED, UC_HOOK_MEM_WRITE, UC_MEM_FETCH_PROT,
                     UC_MEM_FETCH_UNMAPPED, UC_MODE_ARM, Uc, UcError)
from unicorn import arm_const as arm
from unicorn import unicorn_const as ucc

from . import syscalls
from .console import FINISHED, FINISHED_DROPPED, FINISHED_ERROR, Console
from .errors import RuntimeFault
from .observers import Observers
from .program import INSTRUCTION_SIZE

# Memory map
DDR_BASE = 0x00000000
DDR_END = 0x40000000            # 1 GB of DDR3 memory
DDR_PAGE = 0x100000             # DDR3 is mapped 1 MB at a time, on first access
DEVICES_BASE = 0xFF200000       # DE1-SoC devices: the JTAG UART, and the board while connected
DEVICES_SIZE = 0x10000
JTAG_UART = 0xFF201000          # data register; control register at +4
JTAG_UART_SIZE = 8
ONCHIP_BASE = 0xFFFF0000
ONCHIP_SIZE = 0x10000

JTAG_RVALID = 1 << 15
JTAG_WSPACE = 64                # output space reported in control bits 31-16

# Initial state
INITIAL_SP = 0x00000000         # as in CPUlator: the first push stores at 0xFFFFFFFC (on-chip)
INITIAL_CPSR = 0x000001D3       # Supervisor mode, IRQ and FIQ masked
CPACR_CP10_CP11 = 0xF << 20     # full access to the VFP/NEON coprocessors
FPEXC_EN = 1 << 30

SLICE_MS = 30
CHUNK = 10_000                  # instructions per Unicorn call (a few ms at most)
MEMORY_CHUNK = 1_000            # the same while a tool watches memory accesses
RECORD_CHUNK = 500              # the same while recording every instruction
NO_END = 0xFFFFFFFF             # an address no ARM instruction can have
HISTORY_LIMIT = 2000            # instructions Backstep can undo

EXCP_SWI = 2
EXCP_SMC = 13
_EXCEPTIONS = {
    1: "undefined instruction",
    3: "instruction fetch abort",
    4: "data abort",
    7: "breakpoint instruction (BKPT)",
    EXCP_SMC: "secure monitor call (SMC) is not supported",
}
_UC_ERRORS = {
    ucc.UC_ERR_INSN_INVALID: "undefined instruction",
    ucc.UC_ERR_READ_UNALIGNED: "unaligned memory read",
    ucc.UC_ERR_WRITE_UNALIGNED: "unaligned memory write",
    ucc.UC_ERR_FETCH_UNALIGNED: "unaligned instruction address",
    ucc.UC_ERR_EXCEPTION: "unhandled processor exception",
}

REGISTERS = [getattr(arm, f"UC_ARM_REG_R{i}") for i in range(13)] + [
    arm.UC_ARM_REG_SP, arm.UC_ARM_REG_LR, arm.UC_ARM_REG_PC]
SP, LR, PC = 13, 14, 15
# Saved for Backstep. CPSR comes first: restoring it may switch the register bank,
# and with it the SPSR, SP and LR that follow.
SNAPSHOT_REGISTERS = [arm.UC_ARM_REG_CPSR, arm.UC_ARM_REG_SPSR] + REGISTERS + [
    arm.UC_ARM_REG_FPSCR, arm.UC_ARM_REG_FPEXC] + [
    getattr(arm, f"UC_ARM_REG_D{i}") for i in range(32)]
SNAPSHOT_PC = SNAPSHOT_REGISTERS.index(arm.UC_ARM_REG_PC)
SINGLES = [getattr(arm, f"UC_ARM_REG_S{i}") for i in range(32)]
DOUBLES = [getattr(arm, f"UC_ARM_REG_D{i}") for i in range(32)]   # S2n is the low half of Dn

# What a system call can wait for (Request.kind)
INPUT = "input"                 # a typed line (Enter) in Run I/O
DIALOG = "dialog"               # an answer from a dialog window
SLEEP = "sleep"                 # some time to pass


class StopReason(enum.Enum):
    EXIT = "exit"
    SELF_BRANCH = "branch to itself"
    DROPPED_OFF = "dropped off bottom"
    ERROR = "runtime error"


@dataclass
class Request:
    """Something a system call needs before the program can go on."""
    kind: str                   # INPUT, DIALOG or SLEEP
    service: int
    dialog: str = ""            # DIALOG: which dialog (syscalls.CONFIRM ...)
    message: str = ""           # DIALOG: the message to show
    value: object = None        # DIALOG: extra value (message type, number, text)
    until: float = 0.0          # SLEEP: time.perf_counter() when the sleep ends


@dataclass
class Change:
    """Everything needed to undo one executed instruction."""
    registers: tuple
    heap: int
    number: int                 # the machine's changes are numbered from 1, in order
    writes: list = field(default_factory=list)     # (address, old bytes), in order


class _Wait(Exception):
    """A system call has to wait; its SVC instruction runs again afterwards."""

    def __init__(self, request):
        super().__init__(request.kind)
        self.request = request


_NO_ANSWER = object()


def condition_passed(cond, cpsr):
    """True when ARM condition code cond holds for the flags in cpsr."""
    n, z, c, v = (cpsr >> 31) & 1, (cpsr >> 30) & 1, (cpsr >> 29) & 1, (cpsr >> 28) & 1
    return (z, not z, c, not c, n, not n, v, not v,
            c and not z, not c or z, n == v, n != v,
            not z and n == v, z or n != v, True, True)[cond]


class Machine:
    """One program loaded into a fresh DE1-SoC computer.

    base_dir is the folder that file names given to the file services are
    relative to (normally the folder of the source file).
    """

    def __init__(self, program, console=None, base_dir=None):
        self.program = program
        self.console = console if console is not None else Console()
        self.base_dir = Path(base_dir) if base_dir is not None else Path.cwd()
        self._breakpoints = {}          # address -> Unicorn hook handle
        self._changes = 0               # changes recorded for Backstep so far
        self.services = None
        self.observers = Observers()    # what connected tools observe; kept across Reset
        # The DE1-SoC's LEDs, displays, switches and keys (ares.devices.Board) while the
        # Digital Lab Sim is connected, else None: not simulated. Kept across Reset.
        self.board = None
        self.reset()

    # Set-up -------------------------------------------------------------

    def reset(self):
        """Reload the program and return to the initial state.

        Breakpoints stay set; the history for Backstep is cleared.
        """
        if self.services is not None:
            self.services.close()
        self._release_memory()
        self.services = syscalls.ServiceState()
        self.stop_reason = None
        self.error = None
        self.error_address = None       # where the runtime error happened (PC may change since)
        self.no_code = False            # the runtime error was a fetch of nothing there
        self.backsteps = 0              # instructions undone since the last Reset
        self.exit_value = None
        self.request = None             # what the program waits for, if anything
        self.at_breakpoint = False      # the last run stopped at a breakpoint
        self.history = deque()          # at most HISTORY_LIMIT changes
        end = max((s.end for s in self.program.sections), default=0)
        self.heap_start = (end + 3) & ~3    # the first word after the program
        self.heap = self.heap_start     # next address the heap service hands out
        self._answer = _NO_ANSWER
        self._resume_at = None
        self._deadline = float("inf")  # when the current slice should end
        self._at_hint = False           # stopped before WFE or YIELD
        self._recording = False
        self._write_hook = self._instruction_hook = None
        self._ddr_pages = set()
        self.warnings = []              # run-time warnings for the messages pane
        self._warnings_taken = 0
        self._warned_devices = set()

        uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        uc.ctl_set_cpu_model(arm.UC_CPU_ARM_CORTEX_A9)
        self.uc = uc
        uc.mem_map(ONCHIP_BASE, ONCHIP_SIZE)
        uc.mmio_map(DEVICES_BASE, DEVICES_SIZE,
                    self._device_read, None, self._device_write, None)
        for section in self.program.sections:
            self._map_ddr(section.address, section.size)
            if section.data:
                uc.mem_write(section.address, section.data)
        self._set_initial_state()

        uc.hook_add(UC_HOOK_INTR, self._on_interrupt)
        # The devices cannot be executed: an instruction fetched there is no program code.
        uc.hook_add(UC_HOOK_MEM_UNMAPPED | UC_HOOK_MEM_FETCH_PROT, self._on_unmapped)
        for address, cond in self.program.self_branches:
            uc.hook_add(UC_HOOK_CODE, self._on_self_branch, cond, begin=address, end=address)
        for address in self.program.wait_hints:
            uc.hook_add(UC_HOOK_CODE, self._on_wait_hint, begin=address, end=address)
        self.observers.install(uc)
        addresses, self._breakpoints = list(self._breakpoints), {}
        for address in addresses:
            self.set_breakpoint(address)

    def close(self):
        """Close the program's files and give back the emulator's memory (the machine is done)."""
        self.services.close()
        self._release_memory()

    def _release_memory(self):
        """Unmap the old emulator's memory at once.

        Its hooks make the emulator and this machine refer to each other, so
        Python would free that memory only at its next full collection.
        """
        uc = getattr(self, "uc", None)
        if uc is not None:
            for begin, end, _ in list(uc.mem_regions()):
                uc.mem_unmap(begin, end - begin + 1)

    def _set_initial_state(self):
        uc = self.uc
        uc.reg_write(arm.UC_ARM_REG_CPSR, INITIAL_CPSR)
        for reg in REGISTERS[:PC]:
            uc.reg_write(reg, 0)
        uc.reg_write(arm.UC_ARM_REG_SP, INITIAL_SP)
        uc.reg_write(arm.UC_ARM_REG_C1_C0_2,
                     uc.reg_read(arm.UC_ARM_REG_C1_C0_2) | CPACR_CP10_CP11)
        uc.reg_write(arm.UC_ARM_REG_FPEXC, FPEXC_EN)
        uc.reg_write(arm.UC_ARM_REG_PC, self.program.entry)

    def _map_ddr(self, address, size):
        first = address // DDR_PAGE
        last = (address + max(size, 1) - 1) // DDR_PAGE
        for page in range(first, last + 1):
            if page not in self._ddr_pages:
                self.uc.mem_map(page * DDR_PAGE, DDR_PAGE)
                self._ddr_pages.add(page)

    # Registers ----------------------------------------------------------

    def reg(self, n):
        """Value of register Rn (13 = SP, 14 = LR, 15 = PC)."""
        return self.uc.reg_read(REGISTERS[n])

    def set_reg(self, n, value):
        self.uc.reg_write(REGISTERS[n], value & 0xFFFFFFFF)

    def set_flag(self, bit, value):
        """Set (value 1) or clear (0) a bit of CPSR, such as a condition flag (N is bit 31)."""
        cpsr = self.cpsr
        self.uc.reg_write(arm.UC_ARM_REG_CPSR, cpsr | 1 << bit if value else cpsr & ~(1 << bit))

    @property
    def pc(self):
        return self.uc.reg_read(arm.UC_ARM_REG_PC)

    @property
    def cpsr(self):
        return self.uc.reg_read(arm.UC_ARM_REG_CPSR)

    @property
    def spsr(self):
        """The SPSR of the current mode (User and System modes have none: then 0)."""
        return self.uc.reg_read(arm.UC_ARM_REG_SPSR)

    def set_spsr_flag(self, bit, value):
        """Set (value 1) or clear (0) a bit of the current mode's SPSR."""
        spsr = self.spsr
        self.uc.reg_write(arm.UC_ARM_REG_SPSR, spsr | 1 << bit if value else spsr & ~(1 << bit))

    def vfp(self):
        """The bits of D0 to D31 (S0 to S31 are the halves of D0 to D15) and FPSCR."""
        values = self.uc.reg_read_batch(DOUBLES + [arm.UC_ARM_REG_FPSCR])
        return list(values[:-1]), values[-1]

    def single(self, n):
        """The bits of register Sn."""
        return self.uc.reg_read(SINGLES[n]) & 0xFFFFFFFF

    def set_single(self, n, bits):
        self.uc.reg_write(SINGLES[n], bits & 0xFFFFFFFF)

    def double(self, n):
        """The bits of register Dn."""
        return self.uc.reg_read(DOUBLES[n]) & 0xFFFFFFFFFFFFFFFF

    def set_double(self, n, bits):
        self.uc.reg_write(DOUBLES[n], bits & 0xFFFFFFFFFFFFFFFF)

    def set_fpscr_flag(self, bit, value):
        """Set (value 1) or clear (0) a bit of FPSCR, such as its N flag (bit 31)."""
        fpscr = self.uc.reg_read(arm.UC_ARM_REG_FPSCR)
        self.uc.reg_write(arm.UC_ARM_REG_FPSCR, fpscr | 1 << bit if value else fpscr & ~(1 << bit))

    # Memory as the program sees it -------------------------------------

    def read_memory(self, address, size):
        """Read memory; DDR3 pages never touched read as zeros."""
        self.check_range(address, size)     # before building a huge result
        out = bytearray()
        while size > 0:
            address &= 0xFFFFFFFF
            if address < DDR_END:
                page = address // DDR_PAGE
                chunk = min(size, (page + 1) * DDR_PAGE - address)
                if page in self._ddr_pages:
                    out += self.uc.mem_read(address, chunk)
                else:
                    out += bytes(chunk)
            elif address >= ONCHIP_BASE:
                chunk = min(size, 0x100000000 - address)
                out += self.uc.mem_read(address, chunk)
            else:
                raise RuntimeFault(f"memory access out of range at 0x{address:08x}")
            address += chunk
            size -= chunk
        return bytes(out)

    @staticmethod
    def check_range(address, size):
        """Raise RuntimeFault unless [address, address + size) is DDR3 or on-chip memory.

        Addresses wrap from 0xFFFFFFFF to 0, as the CPU's do.
        """
        if size <= 0:
            return
        address &= 0xFFFFFFFF
        if DDR_END <= address < ONCHIP_BASE:
            bad = address
        elif address < DDR_END:
            bad = DDR_END if address + size > DDR_END else None
        else:
            bad = DDR_END if address + size - 0x100000000 > DDR_END else None
        if bad is not None:
            raise RuntimeFault(f"memory access out of range at 0x{bad:08x}")

    def read_cstring(self, address, chunk=256):
        """Bytes of the zero-terminated string at address (without the zero)."""
        out = bytearray()
        while True:
            data = self.read_memory(address, chunk - address % chunk)
            end = data.find(0)
            if end >= 0:
                return bytes(out + data[:end])
            out += data
            address = (address + len(data)) & 0xFFFFFFFF

    def peek_words(self, address, count):
        """count words from address as a memory table shows them; None where there is no memory.

        Unlike the program's own reads, this takes no typed character from the
        JTAG UART and warns about no device.
        """
        try:
            return list(struct.unpack(f"<{count}I", self.read_memory(address, 4 * count)))
        except RuntimeFault:            # not all of it is memory: word by word
            return [self._peek_word((address + 4 * k) & 0xFFFFFFFF) for k in range(count)]

    def _peek_word(self, address):
        if DEVICES_BASE <= address < DEVICES_BASE + DEVICES_SIZE:
            if address == JTAG_UART:
                ch = self.console.peek_byte()
                return 0 if ch is None else (
                    (min(self.console.pending() - 1, 0xFFFF) << 16) | JTAG_RVALID | ch)
            if self.board is not None and address in self.board:
                return self.board.read(address, 4)
            return JTAG_WSPACE << 16 if address == JTAG_UART + 4 else 0
        try:
            return struct.unpack("<I", self.read_memory(address, 4))[0]
        except RuntimeFault:
            return None

    def write_memory(self, address, data):
        """Write bytes for a system call (recorded for Backstep).

        Addresses wrap from 0xFFFFFFFF to 0, as the CPU's do.
        """
        if not data:
            return
        address &= 0xFFFFFFFF
        self.check_range(address, len(data))
        if self._recording and self.history:
            self.history[-1].writes.append((address, self.read_memory(address, len(data))))
        first = min(len(data), 0x100000000 - address)
        for start, part in ((address, data[:first]), (0, data[first:])):
            if part:
                if start < DDR_END:
                    self._map_ddr(start, len(part))
                self.uc.mem_write(start, bytes(part))

    # Running ------------------------------------------------------------

    def run_slice(self, timeout_ms=SLICE_MS, record=False):
        """Run at full speed for about timeout_ms.

        With record, every instruction is recorded for Backstep (much slower).
        Returns the StopReason once the program has stopped, None while it
        can go on; then ``request`` tells what it waits for, and
        ``at_breakpoint`` whether it stopped at a breakpoint.
        """
        return self._execute(timeout_ms / 1000, None, record)

    def step(self):
        """Execute the instruction at PC (even on a breakpoint), recorded for Backstep."""
        self.resume_here()
        return self._execute(0.0, 1, True)

    def run(self, time_limit=None):
        """Go: run until the program stops (or time_limit seconds pass).

        Returns the StopReason, or None when the time is up, a breakpoint was
        reached, or the program waits for input or a dialog answer.
        """
        self.resume_here()
        deadline = None if time_limit is None else time.monotonic() + time_limit
        while self.run_slice() is None:
            request = self.request
            if self.at_breakpoint or (request is not None and request.kind != SLEEP):
                return None
            if request is not None:
                time.sleep(max(0.0, min(0.01, request.until - time.perf_counter())))
            if deadline is not None and time.monotonic() > deadline:
                return None
        return self.stop_reason

    def resume_here(self):
        """Go or Step starts here: a breakpoint at PC does not stop it."""
        self._resume_at = self.pc if self.pc in self._breakpoints else None
        self.at_breakpoint = False

    def breakpoint_here(self):
        """True when a run arriving at PC should stop at its breakpoint."""
        return self.pc in self._breakpoints and self.pc != self._resume_at

    def ends_here(self):
        """True when the program ends at PC without running another instruction.

        PC is past its last instruction, or at a ``B .`` whose condition passes.
        """
        pc, cpsr = self.pc, self.cpsr
        return pc == self.program.end_address or any(
            address == pc and condition_passed(cond, cpsr)
            for address, cond in self.program.self_branches)

    def _execute(self, seconds, count, record):
        """Run counted chunks of instructions until seconds have passed.

        Unicorn's own timeout is not used: it can stop the CPU inside a device
        access, after which Unicorn runs that instruction again, so a JTAG UART
        character would be printed twice or a typed one lost. Counted chunks
        always stop between instructions.
        """
        if self.stop_reason is not None:
            return self.stop_reason
        if not self.request_done():
            return None
        self.at_breakpoint = False
        end = self.program.end_address
        if self.pc == end:
            self._finish(StopReason.DROPPED_OFF)
            return self.stop_reason
        until = NO_END if end is None else end
        # A tool that watches memory has Python called for each access, up to 16 for one
        # instruction (LDM, VLDM): shorter chunks keep the slice, and what the tool then
        # does with its accesses, short.
        chunk = count or (RECORD_CHUNK if record else
                          MEMORY_CHUNK if self.observers.watches_memory else CHUNK)
        if record:
            self._start_recording(every_instruction=count != 1)
        else:
            self.history.clear()        # unrecorded instructions make it stale
        deadline = time.perf_counter() + seconds
        # System calls and recording cost Python time per instruction, so a
        # chunk may take long; their hooks also end the slice at the deadline.
        self._deadline = float("inf") if count else deadline
        try:
            while self.pc != end:
                pc = self.pc
                try:
                    self.uc.emu_start(pc | 1 if self.cpsr & 0x20 else pc, until, count=chunk)
                except UcError as e:
                    if self.stop_reason is None:
                        self._fail(self.pc, _UC_ERRORS.get(e.errno, str(e)))
                if self.observers.blocks is not None:
                    # The instruction that failed did not complete, whatever PC is now.
                    self.observers.stopped(self.error_address if self.stop_reason
                                           is StopReason.ERROR else self.pc)
                if self._at_hint:
                    self._skip_wait_hint(record)
                if self.pc != self._resume_at:
                    self._resume_at = None
                if record:
                    self._drop_unfinished_change()
                if (count or self.stop_reason is not None or self.request is not None
                        or self.at_breakpoint or time.perf_counter() >= deadline):
                    break
        finally:
            if record:
                self._stop_recording()
        if self.stop_reason is None and self.request is None and self.pc == end:
            self._finish(StopReason.DROPPED_OFF)
        if self.stop_reason is StopReason.ERROR:
            self.uc.reg_write(arm.UC_ARM_REG_PC, self.error_address)
        return self.stop_reason

    def take_warnings(self):
        """Warnings added since the previous call."""
        new = self.warnings[self._warnings_taken:]
        self._warnings_taken = len(self.warnings)
        return new

    def close_files(self):
        """Close the files the program opened (the run was stopped)."""
        self.services.close()

    def exit(self, value=None):
        """End the program normally (used by the exit services)."""
        self.exit_value = value
        self._finish(StopReason.EXIT)

    def _finish(self, reason):
        if self.stop_reason is None:
            self.stop_reason = reason
            self.services.close()
            self.console.end_line(
                FINISHED_DROPPED if reason is StopReason.DROPPED_OFF else FINISHED)

    def _fail(self, address, message):
        """Stop with a runtime error for the instruction at address."""
        if self.stop_reason is not None:
            return
        line = self.program.line_at(address)
        where = (f"at line {line} (address 0x{address:08x})" if line
                 else f"at address 0x{address:08x}")
        self.error = f"Runtime error {where}: {message}"
        self.error_address = address
        self.stop_reason = StopReason.ERROR
        self.services.close()
        self.console.end_line(self.error)
        self.console.end_line(FINISHED_ERROR)       # the run is over, as after a normal end

    # Breakpoints --------------------------------------------------------

    @property
    def breakpoints(self):
        return set(self._breakpoints)

    def set_breakpoint(self, address, on=True):
        """Stop before the instruction at address (or no longer stop there)."""
        if on and address not in self._breakpoints:
            self._breakpoints[address] = self.uc.hook_add(
                UC_HOOK_CODE, self._on_breakpoint, begin=address, end=address)
            # Code Unicorn translated before has no call to the new hook.
            self.uc.ctl_remove_cache(address, address + INSTRUCTION_SIZE)
            self.observers.keep_last()
        elif not on and address in self._breakpoints:
            self.uc.hook_del(self._breakpoints.pop(address))

    def clear_breakpoints(self):
        for address in list(self._breakpoints):
            self.set_breakpoint(address, False)

    # Waiting for input, dialogs and time -------------------------------

    def input_line(self, service):
        """The next typed line, for a read service; waits until Enter is typed.

        Returns b"" when standard input has ended (command-line runner).
        """
        line = self.console.read_line()
        if line is None:
            raise _Wait(Request(INPUT, service))
        return line

    def input_bytes(self, service, count):
        """Up to count typed bytes of the current line (waits like input_line)."""
        data = self.console.read_bytes(count)
        if data is None:
            raise _Wait(Request(INPUT, service))
        return data

    def dialog(self, service, kind, message, value=None):
        """The answer of a dialog window; waits until answer() is called."""
        if self._answer is _NO_ANSWER:
            raise _Wait(Request(DIALOG, service, kind, message, value))
        answer, self._answer = self._answer, _NO_ANSWER
        return answer

    def drop_request(self):
        """Forget what the program waited for: its registers were changed, so the
        system call (if PC is still on it) asks again when it runs."""
        self.request = None
        self._answer = _NO_ANSWER

    def answer(self, value):
        """Answer the dialog the program waits for (see request)."""
        if self.request is not None and self.request.kind == DIALOG:
            self._answer = value

    def sleep(self, service, milliseconds):
        """Let time pass before the next instruction runs."""
        self.request = Request(SLEEP, service,
                               until=time.perf_counter() + max(milliseconds, 0) / 1000)

    def request_done(self):
        """True when nothing is pending any more (clears a satisfied request)."""
        request = self.request
        if request is None:
            return True
        if request.kind == INPUT:
            done = self.console.has_line()
        elif request.kind == DIALOG:
            done = self._answer is not _NO_ANSWER
        else:
            done = time.perf_counter() >= request.until
        if done:
            self.request = None
        return done

    # Backstep -----------------------------------------------------------

    def backstep(self):
        """Undo the last recorded instruction; False when there is none."""
        if not self.history:
            return False
        change = self.history[-1]
        self._restore(change)
        self.history.pop()
        self.backsteps += 1
        self.uc.reg_write_batch(list(zip(SNAPSHOT_REGISTERS, change.registers)))
        self.heap = change.heap
        self.stop_reason = self.error = self.error_address = self.request = None
        self.no_code = False
        self.at_breakpoint = False
        self._answer = _NO_ANSWER
        return True

    def _new_change(self):
        self._changes += 1
        return Change(self.uc.reg_read_batch(SNAPSHOT_REGISTERS), self.heap, self._changes)

    def _restore(self, change):
        """Put back the memory the writes of a change replaced.

        A write can wrap from 0xFFFFFFFF to 0, as the CPU's addresses do;
        Unicorn's own memory writes do not wrap. The board's registers go back
        to the board, while it is connected.
        """
        for address, old in reversed(change.writes):
            if DEVICES_BASE <= address < DEVICES_BASE + DEVICES_SIZE:
                if self.board is not None:
                    self.board.put_back(address, old)
                continue
            first = min(len(old), 0x100000000 - address)
            self.uc.mem_write(address, old[:first])
            if first < len(old):
                self.uc.mem_write(0, old[first:])

    def _start_recording(self, every_instruction):
        self._recording = True
        self._write_hook = self.uc.hook_add(UC_HOOK_MEM_WRITE, self._on_write)
        if every_instruction:
            self._instruction_hook = self.uc.hook_add(UC_HOOK_CODE, self._on_instruction)
            self.uc.ctl_flush_tb()      # code translated before would not call the hook
            self.observers.keep_last()
        else:
            self.history.append(self._new_change())

    def _stop_recording(self):
        self.uc.hook_del(self._write_hook)
        if self._instruction_hook is not None:
            self.uc.hook_del(self._instruction_hook)
        self._write_hook = self._instruction_hook = None
        self._recording = False

    def _drop_unfinished_change(self):
        """Forget the last change if its instruction did not complete.

        That happens when the run stopped before the instruction (breakpoint,
        ``B .``), when its SVC has to wait and will run again, and when the
        instruction itself failed. Any memory it wrote is restored.
        """
        if not self.history:
            return
        change = self.history[-1]
        if self.stop_reason is StopReason.ERROR:
            unfinished = change.registers[SNAPSHOT_PC] == self.error_address
        else:
            unfinished = change.registers == self.uc.reg_read_batch(SNAPSHOT_REGISTERS)
        if unfinished:
            self._restore(change)
            self.history.pop()
        while len(self.history) > HISTORY_LIMIT:    # trimmed only now, so a dropped
            self.history.popleft()                  # change never costs an old one

    # Hooks (called by Unicorn) -----------------------------------------

    def _on_interrupt(self, uc, intno, user_data):
        pc = uc.reg_read(arm.UC_ARM_REG_PC)
        if intno == EXCP_SWI:
            address = pc - 4
            word = struct.unpack("<I", uc.mem_read(address, 4))[0]
            try:
                syscalls.call(self, word & 0x00FFFFFF)
            except _Wait as wait:
                self.request = wait.request
                uc.reg_write(arm.UC_ARM_REG_PC, address)
                if address in self._breakpoints:
                    self._resume_at = address   # running the SVC again is no new hit
            except RuntimeFault as fault:
                self._fail(address, fault.message)
        else:
            # SMC, like SVC, is reported with PC already after the instruction.
            self._fail(pc - 4 if intno == EXCP_SMC else pc,
                       _EXCEPTIONS.get(intno, f"processor exception {intno}"))
        # The SVC has completed here, so stopping for the deadline is clean.
        if (self.stop_reason is not None or self.request is not None
                or time.perf_counter() >= self._deadline):
            uc.emu_stop()

    def _on_unmapped(self, uc, access, address, size, value, user_data):
        """An access to memory that is not there (DDR3 is mapped on the first access),
        or an instruction fetched from the DE1-SoC devices."""
        if access in (UC_MEM_FETCH_UNMAPPED, UC_MEM_FETCH_PROT):
            self.no_code = True
            self._fail(address, f"no program code at 0x{address:08x}")
            return False
        if address + size <= DDR_END:
            self._map_ddr(address, size)
            return True
        self._fail(uc.reg_read(arm.UC_ARM_REG_PC),
                   f"memory access out of range at 0x{address:08x}")
        return False

    def _on_self_branch(self, uc, address, size, cond):
        if address in self._breakpoints and address != self._resume_at:
            return                      # _on_breakpoint pauses here first
        if condition_passed(cond, uc.reg_read(arm.UC_ARM_REG_CPSR)):
            self._finish(StopReason.SELF_BRANCH)
            uc.emu_stop()

    def _on_wait_hint(self, uc, address, size, user_data):
        """WFE or YIELD: stop before it; _execute steps over it (a hint does nothing here)."""
        if address in self._breakpoints and address != self._resume_at:
            return                      # _on_breakpoint pauses here first
        self._at_hint = True
        uc.emu_stop()

    def _skip_wait_hint(self, record):
        self._at_hint = False
        if record and (not self.history or
                       self.history[-1].registers[SNAPSHOT_PC] != self.pc):
            self.history.append(self._new_change())
        self.observers.stepped_over(self.pc)
        self.uc.reg_write(arm.UC_ARM_REG_PC, self.pc + INSTRUCTION_SIZE)

    def _on_breakpoint(self, uc, address, size, user_data):
        if address == self._resume_at:
            self._resume_at = None      # the run starts here: execute it
            return
        self.at_breakpoint = True
        uc.emu_stop()

    def _on_instruction(self, uc, address, size, user_data):
        if time.perf_counter() >= self._deadline:
            uc.emu_stop()               # before this instruction runs
            return
        self.history.append(self._new_change())

    def _on_write(self, uc, access, address, size, value, user_data):
        if not self.history:
            return
        if DEVICES_BASE <= address < DEVICES_BASE + DEVICES_SIZE:
            # Unicorn calls this before the device's write: the board still has the old bytes.
            kept = None if self.board is None else self.board.before_write(address, size)
            if kept is not None:
                self.history[-1].writes.append(kept)
            return
        try:
            old = self.read_memory(address, size)
        except RuntimeFault:
            return                      # the write itself will fail
        self.history[-1].writes.append((address, old))

    def _device_read(self, uc, offset, size, user_data):
        address = DEVICES_BASE + offset
        if JTAG_UART <= address < JTAG_UART + JTAG_UART_SIZE:
            return self._jtag_read(address - JTAG_UART, size)
        if self.board is not None and address in self.board:
            return self.board.read(address, size)
        self._warn_device(address)
        return 0

    def _device_write(self, uc, offset, size, value, user_data):
        address = DEVICES_BASE + offset
        if JTAG_UART <= address < JTAG_UART + JTAG_UART_SIZE:
            self._jtag_write(address - JTAG_UART, value)
        elif self.board is not None and address in self.board:
            self.board.write(address, size, value)
        else:
            self._warn_device(address)

    def _warn_device(self, address):
        """A device ARES does not simulate: warn once per address and run."""
        if address not in self._warned_devices:
            self._warned_devices.add(address)
            self.warnings.append(f"Warning: DE1-SoC device at 0x{address:08x} is not "
                                 f"simulated: writes are ignored, reads return 0")

    def _jtag_read(self, offset, size):
        if offset < 4:
            ch = self.console.read_byte()
            value = 0 if ch is None else (
                (min(self.console.pending(), 0xFFFF) << 16) | JTAG_RVALID | ch)
        else:
            value = JTAG_WSPACE << 16
        return (value >> (8 * (offset & 3))) & ((1 << (8 * size)) - 1)

    def _jtag_write(self, offset, value):
        if offset == 0:
            self.console.write_bytes(bytes([value & 0xFF]))
            for _, callback in self.observers.jtag:     # connected tools (ares.observers)
                callback(value)
