# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""What the connected tools observe of a running program.

Each Machine has one Observers. The tools ask it for what they need:
counts of the basic blocks executed (instruction counting), the memory
accesses (in an address range, if they like) or the instructions at given
addresses. Nothing is installed in the emulator while no tool asks for
anything, so a program then runs exactly as fast as without tools. Python
runs once per basic block, per memory access or per watched instruction,
never for every instruction.

What the program writes to the JTAG UART is reported by the JTAG UART
itself, to the tools that watch it (watch_jtag()): no hook is needed.

The hooks are added to the emulator at once and again to the new emulator of
each Reset. Unicorn translates code into blocks once and runs them again
and again: a block or code hook is called only by code translated after it
was added, so adding or removing one drops the translated code. Memory hooks
take effect at once; their code is dropped the same way, which costs little.

The hooks go to Unicorn through ctypes without the binding's wrappers when
the binding allows it: a call then costs about half (0.5 instead of 0.9
microseconds for a block, measured).
"""

import ctypes

from unicorn import (UC_ERR_OK, UC_HOOK_BLOCK, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE,
                     UcError)
from unicorn.arm_const import UC_ARM_REG_CPSR

from .program import INSTRUCTION_SIZE

try:                # Unicorn's own ctypes types, so a hook calls Python only once
    from unicorn.unicorn_py3 import unicorn as _binding
    _DIRECT = (_binding.uclib.uc_hook_add, _binding.uc_hook_h, _binding.HOOK_CODE_CFUNC,
               _binding.HOOK_MEM_ACCESS_CFUNC)
except (ImportError, AttributeError):
    _DIRECT = None

_REG_READ = None    # uc_reg_read without argument types, so ctypes converts nothing
if _DIRECT is not None:
    try:
        _REG_READ = ctypes.CDLL(_binding.uclib._name, handle=_binding.uclib._handle).uc_reg_read
    except (AttributeError, OSError):
        pass

_MEMORY = UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE
_VALUE = (1 << 64) - 1          # a memory access's value, unsigned


def add_hook(uc, kind, callback, begin=1, end=0):
    """Add a hook to the emulator uc and return its handle (for uc.hook_del()).

    callback gets Unicorn's own arguments: (handle, address, size, key) for
    a block or code hook, (handle, access, address, size, value, key) for a
    memory hook; handle and key mean nothing here. begin and end limit the
    hook to those addresses (both included); begin > end means all.
    """
    if _DIRECT is None or not hasattr(uc, "_uch") or not hasattr(uc, "_callbacks"):
        if kind & _MEMORY:
            def call(uc, access, address, size, value, data):
                callback(None, access, address, size, value, None)
        else:
            def call(uc, address, size, data):
                callback(None, address, size, None)
        return uc.hook_add(kind, call, begin=begin, end=end)
    hook_add, handle_type, code_type, memory_type = _DIRECT
    function = (memory_type if kind & _MEMORY else code_type)(callback)
    handle = handle_type()
    status = hook_add(uc._uch, ctypes.byref(handle), kind, function, None,
                      ctypes.c_uint64(begin), ctypes.c_uint64(end))
    if status != UC_ERR_OK:
        raise UcError(status)
    uc._callbacks[handle.value] = function      # kept alive; uc.hook_del() lets it go
    return handle.value


class BlockCounts:
    """How often each stretch of instructions ran, counted per basic block.

    runs maps (address, size in bytes) to a count. The block hook adds 1 for
    each block the emulator enters. When a run of the emulator stops inside
    the last block it entered (a breakpoint, Pause between slices, the end
    of a chunk or of a step, a system call that waits and will run again, a
    runtime error, ``B .`` or a WFE or YIELD), the instructions from the stop
    to the end of the block did not complete: stopped() takes 1 off for that
    stretch. A WFE or YIELD that the machine steps over adds 1 for itself.
    So the instructions that completed are the sum of count * size / 4,
    each counted once even when a run stopped on it first, and the count of
    each instruction only grows (a stretch taken off is the rest of a block
    added before). Each tool keeps its own copy of runs to see what is new.
    The sizes are those of ARM code (4 bytes an instruction): Thumb code,
    which a program can switch to, is not counted right.
    """

    def __init__(self):
        self.runs = {}
        self.last = None            # the block entered last in the current run
        runs = self.runs

        def entered(handle, address, size, key):
            block = address, size
            runs[block] = runs.get(block, 0) + 1
            self.last = block
        self.hook = entered

    def stopped(self, address):
        """A run of the emulator ended with the next instruction at address."""
        last, self.last = self.last, None
        if last is not None:
            start, size = last
            if start <= address < start + size:
                self._add(address, start + size - address, -1)

    def stepped_over(self, address):
        """The machine stepped over the instruction at address without the emulator."""
        self._add(address, INSTRUCTION_SIZE, 1)

    def _add(self, address, size, count):
        key = address, size
        self.runs[key] = self.runs.get(key, 0) + count

    def instructions(self):
        """The number of instructions completed so far."""
        return sum(count * (size // INSTRUCTION_SIZE) for (_, size), count in self.runs.items())


class _Hook:
    """A hook a tool asked for: kind, its callback with Unicorn's arguments, and range."""

    def __init__(self, client, kind, callback, begin, end):
        self.client, self.kind, self.callback = client, kind, callback
        self.begin, self.end = begin, end
        self.handle = None


class Observers:
    """The hooks the connected tools ask for, on the emulator of one machine.

    The machine calls install() for each new emulator, stopped() after each
    run of it, stepped_over() for a WFE or YIELD it steps over, and
    keep_last() after adding a hook that stops runs. A client is whatever
    stands for a tool (its model); forget(client) removes everything it
    asked for.

    The machine's JTAG UART calls the callbacks in jtag (watch_jtag()).
    """

    def __init__(self):
        self.uc = None
        self.blocks = None          # the BlockCounts, while a tool counts
        self._counting = []         # the clients that count
        self._block_handle = None
        self._hooks = []            # _Hook, in the order they were asked for
        self.jtag = []              # (client, callback) of the tools that watch the JTAG UART

    # Asking ---------------------------------------------------------------

    def count_blocks(self, client):
        """Count the basic blocks executed from now on, for client; returns the BlockCounts.

        Every tool that counts shares the same counts (and the same hook).
        """
        if client not in self._counting:
            self._counting.append(client)
        if self.blocks is None:
            self.blocks = BlockCounts()
            if self.uc is not None:
                self._block_handle = add_hook(self.uc, UC_HOOK_BLOCK, self.blocks.hook)
                self.uc.ctl_flush_tb()
        return self.blocks

    def watch_memory(self, client, callback, reads=True, writes=True, begin=0, end=0xFFFFFFFF,
                     raw=False):
        """Call callback(access, address, size, value) for every read or write the
        program makes in begin..end (both included).

        access is UC_MEM_READ or UC_MEM_WRITE; value is the value written (0
        for a read), unsigned. The callback must be quick and must not stop
        the run; an error it raises ends the run (see _failed()). With raw,
        callback gets Unicorn's own arguments (see add_hook()): a Python call
        less for each access. A raw callback must not raise (nothing could
        end the run for it) and gets an 8-byte value signed.
        """
        kind = (UC_HOOK_MEM_READ if reads else 0) | (UC_HOOK_MEM_WRITE if writes else 0)

        def accessed(handle, access, address, size, value, key):
            try:
                # Unicorn passes the value signed: an 8-byte one can be below 0.
                callback(access, address, size, value & _VALUE)
            except BaseException as error:
                self._failed(error)
        self._add(_Hook(client, kind, callback if raw else accessed, begin, end))

    def count_accesses(self, client, counts, begin, end, shift=0):
        """Count the reads and writes the program makes in begin..end (both included), for
        client: counts[(address - begin) >> shift] grows by 1 for each that starts at
        address. An access that reaches into the next words, one of 8 bytes (VLDR D0, a
        NEON VLD1) or an unaligned one (LDR R0, [R1, #2]), counts once more for each of
        them, at the word's address if that is in begin..end too.

        counts starts every key at 0 (a collections.defaultdict(int)); the
        client takes the counts out of it. A count costs one Python call, about
        half a watch_memory() call.
        """
        def accessed(handle, access, address, size, value, key):
            counts[(address - begin) >> shift] += 1
            if (address & 3) + size > 4:        # it reaches into the next words too
                for word in range((address | 3) + 1, min(address + size, end + 1), 4):
                    counts[(word - begin) >> shift] += 1
        self._add(_Hook(client, _MEMORY, accessed, begin, end))

    def watch_code(self, client, addresses, callback, flags=False):
        """Call callback(address) each time the instruction at one of addresses is about to run.

        The hooks come after the machine's own stops (breakpoints, ``B .``,
        WFE and YIELD), so an instruction a run stops at is reported when it
        runs, not when the run stops there. An error the callback raises ends
        the run (see _failed()).

        With flags, callback(address, flags) also gets the condition flags N,
        Z, C and V the instruction finds (CPSR bits 31-28, 0 to 15). They are
        read through ctypes without the binding's wrappers: about 0.6 instead
        of 4 microseconds (measured), for hooks that run millions of times.
        """
        if not flags:
            def reached(handle, address, size, key):
                try:
                    callback(address)
                except BaseException as error:
                    self._failed(error)
        elif _REG_READ is not None:
            number, value = ctypes.c_int(UC_ARM_REG_CPSR), ctypes.c_uint32()
            where = ctypes.byref(value)

            def reached(handle, address, size, key):
                try:
                    _REG_READ(self.uc._uch, number, where)
                    callback(address, value.value >> 28)
                except BaseException as error:
                    self._failed(error)
        else:
            def reached(handle, address, size, key):
                try:
                    callback(address, self.uc.reg_read(UC_ARM_REG_CPSR) >> 28)
                except BaseException as error:
                    self._failed(error)
        for address in sorted(set(addresses)):
            self._add(_Hook(client, UC_HOOK_CODE, reached, address, address))

    def watch_jtag(self, client, callback):
        """Call callback(value) for each value the program stores to the JTAG UART's data
        register: its low byte is the character Run I/O shows; a word keeps its other bits.

        The JTAG UART calls it as it outputs the character, so no hook is added:
        it costs nothing for a program that does not use the JTAG UART. An error
        it raises ends the run (Unicorn's binding stops it and raises the error).
        """
        self.jtag.append((client, callback))

    def forget(self, client):
        """Remove everything client asked for."""
        if client in self._counting:
            self._counting.remove(client)
            if not self._counting:
                if self.uc is not None and self._block_handle is not None:
                    self.uc.hook_del(self._block_handle)
                self.blocks = self._block_handle = None
                self._flush()
        mine = [hook for hook in self._hooks if hook.client == client]
        if mine:
            self._hooks = [hook for hook in self._hooks if hook.client != client]
            if self.uc is not None:
                for hook in mine:
                    self.uc.hook_del(hook.handle)
            self._flush()
        self.jtag = [(watcher, callback) for watcher, callback in self.jtag if watcher != client]

    @property
    def active(self):
        """True while some tool observes the program."""
        return bool(self._counting or self._hooks or self.jtag)

    @property
    def watches_memory(self):
        """True while some tool watches memory accesses (each one calls Python)."""
        return any(hook.kind & _MEMORY for hook in self._hooks)

    def _add(self, hook):
        self._hooks.append(hook)
        if self.uc is not None:
            hook.handle = add_hook(self.uc, hook.kind, hook.callback, hook.begin, hook.end)
            self._flush()

    def _flush(self):
        if self.uc is not None:
            self.uc.ctl_flush_tb()

    def _failed(self, error):
        """A tool's callback raised error: stop the run, which then raises error, as
        Unicorn's binding does for the hooks it calls itself. A hook added without the
        binding's wrapper would only print the error, and the run would go on."""
        if getattr(self.uc, "_hook_exception", None) is None:
            self.uc._hook_exception = error
        self.uc.emu_stop()

    # Called by the machine ------------------------------------------------

    def install(self, uc):
        """Add every hook asked for to uc, a new emulator (Reset makes one)."""
        self.uc = uc
        self._block_handle = None
        if self.blocks is not None:
            self.blocks.last = None
            self._block_handle = add_hook(uc, UC_HOOK_BLOCK, self.blocks.hook)
        for hook in self._hooks:
            hook.handle = add_hook(uc, hook.kind, hook.callback, hook.begin, hook.end)

    def stopped(self, address):
        """A run of the emulator ended, with the next instruction at address (see BlockCounts)."""
        if self.blocks is not None:
            self.blocks.stopped(address)

    def stepped_over(self, address):
        """The machine stepped over the WFE or YIELD at address (it completed)."""
        if self.blocks is not None:
            self.blocks.stepped_over(address)

    def keep_last(self):
        """Move the code hooks after a hook the machine just added: Unicorn calls the hooks
        of an instruction in the order they were added, and stops calling them once one
        stopped the run."""
        code = [hook for hook in self._hooks if hook.kind == UC_HOOK_CODE]
        if self.uc is None or not code:
            return
        for hook in code:
            self.uc.hook_del(hook.handle)
            hook.handle = add_hook(self.uc, hook.kind, hook.callback, hook.begin, hook.end)
