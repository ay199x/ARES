# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The film of Tools > ARM X-Ray: one instruction on the datapath, step by step, as data.

film() turns a Trace (ares.xray) into the ordered Steps a student watches:
which values travel along which wires, which blocks work and what they say,
which multiplexer takes which input, which write is open or closed, and one
sentence with the real numbers for each step. Nothing here knows a window:
the window only plays the steps by the clock (ares.gui.tools.xray).

The datapath is described here without coordinates. A net is a value that
leaves one output port and reaches one or more input ports, its branches.
Each branch of a net that travels has an outcome: taken (the block uses it),
rejected (a multiplexer chose its other input), closed (it reaches a write
whose enable is 0), or no outcome, when nothing looks at it: that branch
stays gray. A port's value can leave only when the inputs it depends on
have arrived (DEPENDS); the tests check every film against that.

In the real circuit all of this happens within one clock cycle: the film
spreads it out so that it can be read. An LDM, STM, PUSH or POP takes one
cycle for each register: its film is the chain of one film for each pass,
the first at the chosen speed and the others faster (PASS_SHARE).
"""

from dataclasses import dataclass, replace

from . import xray

PARTS = ("Fetch", "Decode", "Execute", "Memory", "Write back", "Next PC")
FETCH, DECODE, EXECUTE, MEMORY, WRITE_BACK, NEXT_PC = PARTS
TAKEN, REJECTED, CLOSED = "taken", "rejected", "closed"
SECONDS = (5, 40)               # the least and most time one instruction may take
DEFAULT_SECONDS = 15
PASS_SHARE = 1 / 3              # each pass after the first takes this share of the chosen time

# The nets: name -> (output port, {branch: input port}). A port is "block.port".
NETS = {
    # Fetch
    "PC": ("PCReg.Q", {"imem": "IMem.A", "add4": "Add4.A"}),
    "Instr": ("IMem.RD", {"split": "Split.In"}),
    "Const4": ("Const4.Out", {"add4": "Add4.B"}),
    "PCPlus4": ("Add4.Out", {"pcmux": "PCMux.0", "add8": "Add8.A", "wd3": "WD3Mux.1"}),
    "PCPlus8": ("Add8.Out", {"r15": "RegFile.R15"}),
    # Decode: the fields of the word
    "Cond": ("Split.Cond", {"control": "Control.Cond"}),
    "Op": ("Split.Op", {"control": "Control.Op"}),
    "Funct": ("Split.Funct", {"control": "Control.Funct"}),
    "Rd": ("Split.Rd", {"control": "Control.Rd", "ra2": "RA2Mux.1", "a3": "A3Mux.0",
                        "a4": "A4Mux.0"}),
    "Rn": ("Split.Rn", {"ra1": "RA1Mux.0", "a3": "A3Mux.2"}),
    "Rm": ("Split.Rm", {"ra2": "RA2Mux.0"}),
    "Rs": ("Split.Rs", {"ra1": "RA1Mux.2", "a4": "A4Mux.1"}),
    "Op2": ("Split.Op2", {"control": "Control.Op2"}),
    "Imm": ("Split.Imm", {"extend": "Extend.Imm"}),
    "Shamt": ("Split.Shamt", {"shifter": "Shifter.Shamt"}),
    "Const15": ("Const15.Out", {"ra1": "RA1Mux.1"}),
    "Const14": ("Const14.Out", {"a3": "A3Mux.1"}),
    "RA1": ("RA1Mux.Out", {"regfile": "RegFile.A1"}),
    "RA2": ("RA2Mux.Out", {"regfile": "RegFile.A2"}),
    "A4": ("A4Mux.Out", {"regfile": "RegFile.A4"}),
    "SrcA": ("RegFile.RD1", {"alu": "ALU.A", "adr": "AdrSrcMux.1"}),
    "RD2": ("RegFile.RD2", {"shifter": "Shifter.In", "store": "StoreMux.0"}),
    "RD4": ("RegFile.RD4", {"store": "StoreMux.1", "alu": "ALU.RD4", "shifter": "Shifter.RD4"}),
    "ExtImm": ("Extend.Out", {"alusrc": "ALUSrcMux.1"}),
    # Execute
    "Shifted": ("Shifter.Out", {"alusrc": "ALUSrcMux.0"}),
    "ShiftC": ("Shifter.Carry", {"control": "Control.ShiftC"}),
    "SrcB": ("ALUSrcMux.Out", {"alu": "ALU.B"}),
    "ALUResult": ("ALU.Result", {"adr": "AdrSrcMux.0", "result": "ResultMux.0",
                                 "wd5": "RegFile.WD5"}),
    "ALUFlags": ("ALU.Flags", {"control": "Control.Flags"}),
    # Memory
    "Address": ("AdrSrcMux.Out", {"dmem": "DMem.A"}),
    "WriteData": ("StoreMux.Out", {"dmem": "DMem.WD"}),
    "ReadData": ("DMem.RD", {"result": "ResultMux.1"}),
    # Write back
    "Result": ("ResultMux.Out", {"wd3": "WD3Mux.0", "pcmux": "PCMux.1"}),
    "A3": ("A3Mux.Out", {"regfile": "RegFile.A3"}),
    "WD3": ("WD3Mux.Out", {"regfile": "RegFile.WD3"}),
    # Next PC
    "PC'": ("PCMux.Out", {"pcreg": "PCReg.D"}),
    # The control signals
    "PCSrc": ("Control.PCSrc", {"pcmux": "PCMux.S"}),
    "MemtoReg": ("Control.MemtoReg", {"result": "ResultMux.S"}),
    "MemWrite": ("Control.MemWrite", {"dmem": "DMem.WE"}),
    # Size: a word, a halfword or a byte; Signed: the load extender inside the data memory
    # copies the sign bit of a halfword or byte read upwards.
    "Size": ("Control.Size", {"dmem": "DMem.Size"}),
    "Signed": ("Control.Signed", {"dmem": "DMem.Signed"}),
    "ALUControl": ("Control.ALUControl", {"alu": "ALU.Control"}),
    "ALUSrc": ("Control.ALUSrc", {"alusrc": "ALUSrcMux.S"}),
    "Shift": ("Control.Shift", {"shifter": "Shifter.Shift"}),
    "StoreSrc": ("Control.StoreSrc", {"store": "StoreMux.S"}),
    "ImmSrc": ("Control.ImmSrc", {"extend": "Extend.ImmSrc"}),
    "RegWrite": ("Control.RegWrite", {"regfile": "RegFile.WE3"}),
    "RegSrc0": ("Control.RegSrc0", {"ra1": "RA1Mux.S"}),
    "RegSrc1": ("Control.RegSrc1", {"ra2": "RA2Mux.S"}),
    "Link": ("Control.Link", {"a3": "A3Mux.S", "wd3": "WD3Mux.S"}),
    "AdrSrc": ("Control.AdrSrc", {"adr": "AdrSrcMux.S"}),
    "BaseWrite": ("Control.BaseWrite", {"regfile": "RegFile.WE5"}),
    "Hold": ("Control.Hold", {"pcreg": "PCReg.Hold"}),
    # The system call: the service's number, and the control unit's call to the system.
    "SvcNum": ("Split.SvcNum", {"system": "System.Number"}),
    "Syscall": ("Control.Syscall", {"system": "System.Call"}),
    # LDM, STM, PUSH and POP: the register list goes to the pass counter in the control unit,
    # which gives each pass its register (for A3 or A4) and its offset (through Extend).
    "List": ("Split.List", {"control": "Control.List"}),
    "PassReg": ("Control.PassReg", {"regfile": "RegFile.PassReg"}),
    "Offset": ("Control.Offset", {"extend": "Extend.Offset"}),
    # MUL and MLA: Mul makes the RA1 multiplexer take Rs and the A3 multiplexer Instr 19:16.
    "Mul": ("Control.Mul", {"ra1": "RA1Mux.Mul", "a3": "A3Mux.Mul"}),
    # A shift by a register: ShiftReg makes the A4 multiplexer take Rs (Instr 11:8); RD4 goes into
    # the shifter, which takes its amount from RD4[7:0] (above).
    "ShiftReg": ("Control.ShiftReg", {"a4": "A4Mux.S"}),
    # ADC, SBC and RSC: the C flag, from the flags register in the control unit, into the adder.
    "CarryIn": ("Control.CarryIn", {"alu": "ALU.CarryIn"}),
}
SIGNALS = ("PCSrc", "MemtoReg", "MemWrite", "Size", "Signed", "ALUControl", "ALUSrc", "Shift",
           "StoreSrc", "ImmSrc", "RegWrite", "RegSrc0", "RegSrc1", "Link", "Syscall", "AdrSrc",
           "BaseWrite", "Hold", "Mul", "ShiftReg")
# What each net carries, for its colour, width and number format.
KINDS = {
    "PC": "pc", "PC'": "pc", "PCPlus4": "pc", "PCPlus8": "pc", "Const4": "constant",
    "Instr": "instr", "Cond": "cond", "Op": "op", "Funct": "funct", "Rn": "rn", "Rd": "rd",
    "Rm": "rm", "Imm": "imm", "Shamt": "shamt", "Const15": "constant", "Const14": "constant",
    "RA1": "rn", "RA2": "rm", "A3": "rd", "SrcA": "rd1", "RD2": "rd2", "RD4": "rd2",
    "ExtImm": "imm", "Shifted": "rd2", "ShiftC": "flags", "SrcB": "rd2", "ALUResult": "alu",
    "ALUFlags": "flags", "WriteData": "rd2", "ReadData": "memory", "Result": "result",
    "WD3": "result", "SvcNum": "imm", "Address": "alu", "List": "rd", "PassReg": "rd",
    "Offset": "imm", "Rs": "rn", "Op2": "op", "A4": "rd", "CarryIn": "flags",
}
KINDS.update((name, "control") for name in SIGNALS)
WIDTHS = {"Cond": 4, "Op": 2, "Funct": 6, "Rn": 4, "Rd": 4, "Rm": 4, "Imm": 24, "Shamt": 7,
          "Const15": 4, "Const14": 4, "RA1": 4, "RA2": 4, "A3": 4, "ShiftC": 1, "ALUFlags": 4,
          "ALUControl": 4, "ImmSrc": 3, "SvcNum": 24, "List": 16, "PassReg": 4, "Rs": 4,
          "Op2": 4, "A4": 4, "CarryIn": 1, "Size": 2}
# The nets that carry a register's number: on the picture they show its four bits, as the table
# of the word shows them (1101, not R13); the sentences and the register file's word name the
# register, and a tip can give both (register_bits()).
REGISTER_NETS = ("Rn", "Rd", "Rm", "Rs", "RA1", "RA2", "A3", "A4", "Const15", "Const14",
                 "PassReg")
MUXES = {                       # multiplexer -> (select signal, its input nets in order)
    "PCMux": ("PCSrc", ("PCPlus4", "Result")),
    "RA1Mux": ("RegSrc0", ("Rn", "Const15", "Rs")),
    "RA2Mux": ("RegSrc1", ("Rm", "Rd")),
    "A3Mux": ("Link", ("Rd", "Const14", "Rn")),
    "A4Mux": ("ShiftReg", ("Rd", "Rs")),
    "WD3Mux": ("Link", ("Result", "PCPlus4")),
    "StoreMux": ("StoreSrc", ("RD2", "RD4")),
    "ALUSrcMux": ("ALUSrc", ("Shifted", "ExtImm")),
    "ResultMux": ("MemtoReg", ("ALUResult", "ReadData")),
    "AdrSrcMux": ("AdrSrc", ("ALUResult", "SrcA")),
}
MUX_OUTPUTS = {"PCMux": "PC'", "RA1Mux": "RA1", "RA2Mux": "RA2", "A3Mux": "A3", "A4Mux": "A4",
               "WD3Mux": "WD3", "StoreMux": "WriteData", "ALUSrcMux": "SrcB",
               "ResultMux": "Result", "AdrSrcMux": "Address"}
# The multiplexers with three inputs: Mul is their second select, beside the first one. Mul 1
# takes input 2 (Rs, Instr 19:16) whatever the first says: the select is the two bits Mul, then
# the first select; their third input and Mul are additions, used only by MUL and MLA.
MUL_SELECT = ("RA1Mux", "A3Mux")
# The A4 multiplexer is an addition too, with ShiftReg its only select: ShiftReg travels only when
# it is 1 (a shift by a register), and Rs comes to its input 1 only then. For an instruction that
# reads A4 otherwise (a store with a register offset, MLA) the multiplexer takes Instr 15:12, as
# A4 did before the addition, with ShiftReg 0 gray: it decides with no select travelling.
SHIFT_SELECT = "A4Mux"
# Output port -> the input ports its value needs. A multiplexer's output needs its select and
# every input that arrives there (film() checks only those that travel). The PC's output and
# the constants need nothing: they are there when the cycle starts.
DEPENDS = {
    "PCReg.Q": (), "Const4.Out": (), "Const15.Out": (), "Const14.Out": (),
    "Control.CarryIn": (),      # the flags register: there when the cycle starts
    "IMem.RD": ("IMem.A",), "Add4.Out": ("Add4.A", "Add4.B"), "Add8.Out": ("Add8.A",),
    "Split.Cond": ("Split.In",), "Split.Op": ("Split.In",), "Split.Funct": ("Split.In",),
    "Split.Rd": ("Split.In",), "Split.Rn": ("Split.In",), "Split.Rm": ("Split.In",),
    "Split.Imm": ("Split.In",), "Split.Shamt": ("Split.In",), "Split.SvcNum": ("Split.In",),
    "Split.List": ("Split.In",), "Split.Rs": ("Split.In",), "Split.Op2": ("Split.In",),
    "RegFile.RD1": ("RegFile.A1",), "RegFile.RD2": ("RegFile.A2",), "RegFile.RD4": ("RegFile.A4",),
    "Extend.Out": ("Extend.Imm", "Extend.ImmSrc"),
    "Shifter.Out": ("Shifter.In", "Shifter.Shift"), "Shifter.Carry": ("Shifter.In", "Shifter.Shift"),
    "ALU.Result": ("ALU.B", "ALU.Control"), "ALU.Flags": ("ALU.B", "ALU.Control"),
    "DMem.RD": ("DMem.A", "DMem.Size", "DMem.Signed"),   # through the load extender
}
for _mux, (_select, _inputs) in MUXES.items():
    DEPENDS[f"{_mux}.Out"] = (f"{_mux}.S",) + tuple(f"{_mux}.{n}" for n in range(len(_inputs)))
for _signal in SIGNALS:
    DEPENDS[f"Control.{_signal}"] = ("Control.Cond", "Control.Op", "Control.Funct")
# The pass counter needs the register list for the register, the offset and the last pass.
for _output in ("PassReg", "Offset", "Hold"):
    DEPENDS[f"Control.{_output}"] = ("Control.Cond", "Control.Op", "Control.Funct",
                                     "Control.List")
BLOCK_NAMES = {
    "PCReg": "PC", "IMem": "Instruction Memory", "Add4": "PCPlus4 adder",
    "Add8": "PCPlus8 adder", "Control": "Control Unit", "RegFile": "Register File",
    "Extend": "Extend", "Shifter": "Shifter", "ALU": "ALU", "DMem": "Data Memory",
    "PCMux": "PC multiplexer", "RA1Mux": "RA1 multiplexer", "RA2Mux": "RA2 multiplexer",
    "A3Mux": "A3 multiplexer", "WD3Mux": "WD3 multiplexer", "StoreMux": "WriteData multiplexer",
    "ALUSrcMux": "SrcB multiplexer", "ResultMux": "Result multiplexer",
    "AdrSrcMux": "AdrSrc multiplexer", "System": "System (ARES)", "A4Mux": "A4 multiplexer",
}
ALU_WORDS = {xray.ALU_ADD: "ADD", xray.ALU_SUB: "SUB", xray.ALU_AND: "AND", xray.ALU_ORR: "ORR",
             xray.ALU_EOR: "EOR", xray.ALU_BIC: "BIC", xray.ALU_RSB: "RSB", xray.ALU_MOV: "MOV",
             xray.ALU_MVN: "MVN", xray.ALU_MUL: "MUL", xray.ALU_MLA: "MLA", xray.ALU_ADC: "ADC",
             xray.ALU_SBC: "SBC", xray.ALU_RSC: "RSC", xray.ALU_MOVT: "MOVT"}
ALU_DOING = {xray.ALU_ADD: "adds", xray.ALU_SUB: "subtracts", xray.ALU_AND: "ANDs",
             xray.ALU_ORR: "ORs", xray.ALU_EOR: "exclusive-ORs", xray.ALU_BIC: "clears bits of",
             xray.ALU_RSB: "subtracts in reverse", xray.ALU_MOV: "passes", xray.ALU_MVN: "inverts",
             xray.ALU_MUL: "multiplies", xray.ALU_MLA: "multiplies and adds",
             xray.ALU_ADC: "adds with carry", xray.ALU_SBC: "subtracts with carry",
             xray.ALU_RSC: "subtracts in reverse with carry", xray.ALU_MOVT: "joins the halves of"}
MULTIPLIER = (xray.ALU_MUL, xray.ALU_MLA)   # the ALUControl codes of the multiplier
IMM_WAYS = {"000": "rotates imm8 right by twice rot", "001": "zero-extends imm12",
            "010": "sign-extends imm24 and multiplies it by 4",
            "011": "passes on the offset of the pass counter",
            "100": "joins imm4 and imm12 into imm16 and zero-extends it",
            "101": "joins imm4H and imm4L into imm8 and zero-extends it"}
SIZE_WORDS = {xray.SIZE_WORD: "word", xray.SIZE_HALF: "halfword", xray.SIZE_BYTE: "byte"}
NO_RN = (0b1101, 0b1111)                    # MOV and MVN: bits 19:16 are no field
NO_RD = (0b1000, 0b1001, 0b1010, 0b1011)    # TST, TEQ, CMP and CMN: bits 15:12 are no field
HALF_NAMES = {(1, 0, 1): "LDRH", (1, 1, 0): "LDRSB", (1, 1, 1): "LDRSH", (0, 0, 1): "STRH"}  # L S H
CMD_NAMES = {0b0000: "AND", 0b0001: "EOR", 0b0010: "SUB", 0b0011: "RSB", 0b0100: "ADD",
             0b0101: "ADC", 0b0110: "SBC", 0b0111: "RSC", 0b1000: "TST", 0b1001: "TEQ",
             0b1010: "CMP", 0b1011: "CMN", 0b1100: "ORR", 0b1101: "MOV", 0b1110: "BIC",
             0b1111: "MVN"}


@dataclass(frozen=True)
class Move:
    """A value that leaves its port and travels to its branches; outcomes holds (branch,
    outcome) for each branch that something looks at."""
    net: str
    text: str
    outcomes: tuple


@dataclass(frozen=True)
class Decision:
    """A multiplexer takes input number taken because its select signal has value; rejected
    holds the inputs that bring a value it does not take (they get a gray cross)."""
    mux: str
    taken: int
    select: str
    value: str
    rejected: tuple = ()


@dataclass(frozen=True)
class Gate:
    """A write whose enable has value: open writes, closed keeps what is there."""
    block: str
    enable: str
    value: str
    open: bool


@dataclass(frozen=True)
class Step:
    """What happens at one moment of the film, all at once, and how long it lasts."""
    part: str
    sentence: str
    moves: tuple = ()
    lights: tuple = ()          # (block, word): the block works and says what it does
    decisions: tuple = ()
    gates: tuple = ()
    fields: tuple = ()          # the fields of the bit display that light
    start: float = 0.0
    duration: float = 0.0


@dataclass(frozen=True)
class Film:
    trace: object
    steps: tuple
    seconds: float
    passes: tuple = ()          # an LDM, STM, PUSH or POP: the Film of each pass, in order
    offset: float = 0.0         # a pass: where its film starts in the whole film

    def part(self, moment, inclusive=False):
        """(the Film of the pass playing at moment, the moment within it); a film of one pass
        gives itself. A moment where one pass ends belongs to the next one, or with inclusive to
        the one that ends (Film.at)."""
        if not self.passes:
            return self, moment
        for number in range(len(self.passes) - 1, -1, -1):
            sub = self.passes[number]
            if moment >= sub.offset - 1e-9:
                if inclusive and number and moment <= sub.offset + 1e-9:
                    before = self.passes[number - 1]
                    return before, before.seconds
                return sub, moment - sub.offset
        return self.passes[0], moment

    def at(self, moment, inclusive=False):
        """(number of the step playing at moment, how far into it, 0 to 1); after the end,
        (len(steps), 1.0). A moment where one step ends and the next begins belongs to the
        next one, or with inclusive to the one that ends (a film that waits there)."""
        for number, step in enumerate(self.steps):
            end = step.start + step.duration
            if moment < end or (inclusive and moment <= end + 1e-9):
                if step.duration <= 0:
                    return number, 1.0
                return number, min(1.0, max(0.0, (moment - step.start) / step.duration))
        return len(self.steps), 1.0

    def used(self):
        """The nets that travel, each once."""
        return [move.net for step in self.steps for move in step.moves]


# Number formats -----------------------------------------------------------------------------

def hex32(value):
    return "?" if value is None else f"0x{value:08X}"


def show(net, value):
    """A net's value as its travelling label shows it."""
    if value is None:
        return "?"
    if isinstance(value, str):
        return value
    if net in REGISTER_NETS:            # a register's number: its four bits
        return f"{value:04b}"
    if net in ("Imm", "SvcNum"):        # 24 bits: too many binary digits to read
        return f"0x{value:06X}"
    width = WIDTHS.get(net, 32)
    if width == 32:
        return hex32(value)
    return f"{value:0{width}b}"


def register_name(number):
    return f"R{number}"


def register_bits(number):
    """A register's number as a tip gives it: its four bits, as the picture shows them, and the
    register they name: "1101 (R13)"."""
    return f"{number:04b} (R{number})"


def fields_of(trace):
    """The fields of the word under the textbook's names: [(name, high bit, low bit, kind)]."""
    word = trace.word
    kind = trace.kind
    head = [("cond", 31, 28, "cond"), ("op", 27, 26, "op")]
    if word & xray.MULTIPLY_MASK == xray.MULTIPLY_BITS and word >> 28 != 0xF:
        # MUL and MLA: Rd is 19:16, which the wire of 19:16 carries (in its colour); Ra (MLA)
        # 15:12, on the wire of 15:12 to A4; bits 15:12 of MUL are no field; op2 tells them.
        ra = ("Ra", 15, 12, "rd") if word >> 21 & 1 else ("", 15, 12, "constant")
        return head + [("I", 25, 25, "funct"), ("cmd", 24, 21, "funct"), ("S", 20, 20, "funct"),
                       ("Rd", 19, 16, "rn"), ra, ("Rs", 11, 8, "rn"), ("op2", 7, 4, "op"),
                       ("Rm", 3, 0, "rm")]
    if kind == xray.NO_OPERATION or (word >> 28 != 0xF and xray.is_nop(word)):
        # NOP: cmd 1001 without S, a hint; bits 19:0 say which hint (0x0F000 is NOP).
        return head + [("funct", 25, 20, "funct"), ("19:0", 19, 0, "constant")]
    if word >> 28 != 0xF and xray.is_move_16(word):
        # MOVW and MOVT: funct 110000 and 110100; imm16 is imm4 (19:16) and imm12 (11:0).
        return head + [("funct", 25, 20, "funct"), ("imm4", 19, 16, "imm"), ("Rd", 15, 12, "rd"),
                       ("imm12", 11, 0, "imm")]
    if word >> 28 != 0xF and xray.is_half(word):
        # LDRH, STRH, LDRSB, LDRSH: P U I W L as LDR's, I (22) for an immediate offset, which is
        # imm4H (11:8) and imm4L (3:0); op2 (7:4) is 1SH1: S signed, H a halfword.
        fields = head + [("0", 25, 25, "funct"), ("P", 24, 24, "funct"), ("U", 23, 23, "funct"),
                         ("I", 22, 22, "funct"), ("W", 21, 21, "funct"), ("L", 20, 20, "funct"),
                         ("Rn", 19, 16, "rn"), ("Rd", 15, 12, "rd")]
        if word >> 22 & 1:
            return fields + [("imm4H", 11, 8, "imm"), ("op2", 7, 4, "op"),
                             ("imm4L", 3, 0, "imm")]
        return fields + [("0000", 11, 8, "constant"), ("op2", 7, 4, "op"), ("Rm", 3, 0, "rm")]
    if kind in (xray.BRANCH_EXCHANGE, xray.BRANCH_LINK_EXCHANGE):
        # op2, bits 7:4, tells BX (0001) from BLX (0011).
        return head + [("funct", 25, 20, "funct"), ("19:8", 19, 8, "constant"),
                       ("op2", 7, 4, "op"), ("Rm", 3, 0, "rm")]
    if kind in (xray.DP_REGISTER, xray.DP_IMMEDIATE) or (word >> 26 & 3 == 0 and not
                                                          kind == xray.BRANCH_EXCHANGE
                                                          and word >> 28 != 0xF
                                                          and word & 0x0E000090 != 0x00000090):
        cmd = word >> 21 & 0xF
        rn = ("", 19, 16, "constant") if cmd in NO_RN else ("Rn", 19, 16, "rn")
        rd = ("", 15, 12, "constant") if cmd in NO_RD else ("Rd", 15, 12, "rd")
        fields = head + [("I", 25, 25, "funct"), ("cmd", 24, 21, "funct"), ("S", 20, 20, "funct"),
                         rn, rd]
        if word >> 25 & 1:
            return fields + [("rot", 11, 8, "imm"), ("imm8", 7, 0, "imm")]
        if word >> 4 & 1:              # shifted by a register: Rs goes to A4, its wire's colour;
            # bit 4, the 1 that tells it, goes only on Op2's wire (7:4), in that wire's colour
            return fields + [("Rs", 11, 8, "rn"), ("0", 7, 7, "shamt"), ("sh", 6, 5, "shamt"),
                             ("1", 4, 4, "op"), ("Rm", 3, 0, "rm")]
        return fields + [("shamt5", 11, 7, "shamt"), ("sh", 6, 5, "shamt"),
                         ("0", 4, 4, "constant"), ("Rm", 3, 0, "rm")]
    if word >> 26 & 3 == 1:
        fields = head + [("I", 25, 25, "funct"), ("P", 24, 24, "funct"), ("U", 23, 23, "funct"),
                         ("B", 22, 22, "funct"), ("W", 21, 21, "funct"), ("L", 20, 20, "funct"),
                         ("Rn", 19, 16, "rn"), ("Rd", 15, 12, "rd")]
        if word >> 25 & 1:
            return fields + [("shamt5", 11, 7, "shamt"), ("sh", 6, 5, "shamt"),
                             (str(word >> 4 & 1), 4, 4, "constant"), ("Rm", 3, 0, "rm")]
        return fields + [("imm12", 11, 0, "imm")]
    if word >> 26 & 3 == 2 and word >> 25 & 1:
        return head + [("1", 25, 25, "funct"), ("L", 24, 24, "funct"), ("imm24", 23, 0, "imm")]
    if word >> 26 & 3 == 2:
        return head + [("0", 25, 25, "funct"), ("P", 24, 24, "funct"), ("U", 23, 23, "funct"),
                       ("S", 22, 22, "funct"), ("W", 21, 21, "funct"), ("L", 20, 20, "funct"),
                       ("Rn", 19, 16, "rn"), ("register list", 15, 0, "rd")]
    if word >> 24 & 0xF == 0xF:
        return head + [("1 1", 25, 24, "funct"), ("imm24", 23, 0, "imm")]
    return [("cond", 31, 28, "cond"), ("27:0", 27, 0, "constant")]


def signal_value(trace, net):
    """The value of the control signal net in trace: "0", "1", "01", "X", ..."""
    s = trace.signals
    if net == "RegSrc0":
        return s["RegSrc"][1]
    if net == "RegSrc1":
        return s["RegSrc"][0]
    return s[net]


def present(trace):
    """The fields of the word that this instruction has, as the nets that carry them (of Rn,
    Rd, Rm, Rs, Op2, Imm, Shamt and List): only these travel; the bits of no field stay gray."""
    names = {name for name, *_ in fields_of(trace)}
    if trace.kind == xray.MULTIPLY:     # by place: Rd on the wire of 19:16, Ra on that of 15:12
        return {"Rn", "Rs", "Op2", "Rm"} | ({"Rd"} if "Ra" in names else set())
    have = {net for net in ("Rn", "Rd", "Rm", "Rs") if net in names}
    if "op2" in names:                  # BX and BLX: told apart by bits 7:4
        have.add("Op2")
    if "Rs" in names:                   # a shift by a register: bits 7:4 (0, sh, 1) tell it
        have.add("Op2")
    if names & {"imm8", "imm12", "imm24", "imm4", "imm4H", "imm4L"}:
        have.add("Imm")
    if "shamt5" in names:
        have.add("Shamt")
    if "register list" in names:
        have.add("List")
    return have


def funct_bits(trace):
    """The bits of the funct fields that the instruction has, as one binary text: six for data
    processing, memory and BX, two (1 and L) for a branch and an SVC."""
    word = trace.word
    return "".join(f"{word >> low & (1 << high - low + 1) - 1:0{high - low + 1}b}"
                   for _, high, low, kind in fields_of(trace) if kind == "funct")


def immediate(trace):
    """The value and the hex digits of the instruction's immediate field: imm24 for a branch,
    imm16 (imm4 and imm12) for MOVW and MOVT, imm8 (imm4H and imm4L) for a halfword transfer, rot
    and imm8 or imm12 (12 bits) for the others."""
    names = {name for name, *_ in fields_of(trace)}
    if "imm24" in names:
        return trace.word & 0xFFFFFF, 6
    if "imm4" in names:
        return xray.extend(trace.word, "100"), 4
    if "imm4H" in names:
        return xray.extend(trace.word, "101"), 2
    return trace.word & 0xFFF, 3


def field_parts(trace):
    """The fields of the word as the film's sentence names them, in the order of fields_of():
    the funct bits together, register numbers as R0 to R15, long immediates in hexadecimal."""
    word = trace.word
    parts, funct = [], ""
    for name, high, low, kind in fields_of(trace):
        width = high - low + 1
        value = word >> low & (1 << width) - 1
        if kind == "funct":
            funct += f"{value:0{width}b}"
            continue
        if funct:
            parts.append(f"funct {funct}")
            funct = ""
        if kind == "constant" or name in ("0", "1"):
            continue                    # bits that are always the same
        if name in ("Rn", "Rd", "Rm", "Rs", "Ra"):
            parts.append(f"{name} R{value}")
        elif kind == "imm" and width > 8:
            parts.append(f"{name} 0x{value:0{(width + 3) // 4}X}")
        else:
            parts.append(f"{name} {value:0{width}b}")
    if funct:
        parts.append(f"funct {funct}")
    return parts


# What a service can wait for: (the system's word, the end of the sentence).
WAITS = {
    "input": ("waits for input", "it waits for input; type a line in Run I/O."),
    "popup": ("waits for input", "it waits for input; type it in the input dialog."),
    "dialog": ("waits for an answer", "it waits for an answer in the dialog window."),
}


# The film -----------------------------------------------------------------------------------

def film(trace, seconds=DEFAULT_SECONDS, lengths=None, next_text="", service="",
         waiting="", error=""):
    """The Film of trace, an instruction inside the datapath, lasting seconds; lengths gives
    each net's longest branch in pixels of the picture (all equal when None), so that a label
    moves at about the same speed on a short wire as on a long one; next_text names the
    instruction that runs next, for the last sentence. For an SVC, service says what the
    system did (for its box and its sentence), and waiting what it waits for (WAITS), or
    "error" when the service failed with the message error: then the film ends at the system,
    the PC staying. An instruction outside the datapath has no film: its picture stays gray."""
    if trace is None or trace.note or not trace.signals:
        return Film(trace, (), float(seconds))
    if trace.passes:
        return _chain(trace, seconds, lengths or {}, next_text)
    builder = _Builder(trace, next_text)
    if trace.kind == xray.SYSTEM_CALL:
        steps = builder.system_steps(service, WAITS["input"] if waiting is True else
                                     WAITS.get(waiting), error)
    elif trace.kind == xray.NO_OPERATION:
        steps = builder.nop_steps()
    else:
        steps = [step for step in builder.steps() if step is not None]
    return Film(trace, _timed(steps, seconds, lengths or {}), float(seconds))


def _chain(trace, seconds, lengths, next_text):
    """The film of an LDM, STM, PUSH or POP: one film for each pass, one after the other, the
    first lasting seconds and each other PASS_SHARE of it; each sentence says which pass plays."""
    subs, steps, start = [], [], 0.0
    count = len(trace.passes)
    for number, part in enumerate(trace.passes, 1):
        time = float(seconds) if number == 1 else seconds * PASS_SHARE
        made = [step for step in _Builder(part, next_text if number == count else "").steps()
                if step is not None]
        if count > 1:
            made = [replace(step, sentence=f"Pass {number} of {count}: {step.sentence}")
                    for step in made]
        timed = _timed(made, time, lengths)
        subs.append(Film(part, timed, time, offset=start))
        steps += [replace(step, start=step.start + start) for step in timed]
        start += time
    return Film(trace, tuple(steps), start, tuple(subs))


def _timed(steps, seconds, lengths):
    """steps with their start and duration: each step's share of seconds grows with the
    length of its longest move, and is never shorter than the time to read its sentence."""
    weights = []
    for step in steps:
        longest = max((lengths.get(move.net, 200) for move in step.moves), default=0)
        travel = 0.8 + longest / 400 if step.moves else 0.8
        reading = 0.55 + len(step.sentence) / 75      # time to read its sentence
        weights.append(max(travel, reading))
    total = sum(weights)
    timed, start = [], 0.0
    for step, weight in zip(steps, weights):
        duration = seconds * weight / total
        timed.append(replace(step, start=start, duration=duration))
        start += duration
    last = timed[-1]
    timed[-1] = replace(last, duration=seconds - last.start)    # exactly seconds in all
    return tuple(timed)


class _Builder:
    """The steps of one instruction, in the order of the datapath (see film()). Only what the
    instruction has travels: the values of Trace.values (None: nothing goes there), the fields
    of the word it has (present()); a multiplexer that an X steers decides nothing."""

    def __init__(self, trace, next_text=""):
        self.trace = trace
        self.next_text = next_text
        self.s = s = trace.signals
        self.f = {name: xray.filled(value) for name, value in s.items()}
        self.v = v = trace.values
        self.word = trace.word
        self.executes = s["CondEx"] == "1"
        self.fields = present(trace)
        self.uses_a = v.get("RA1") is not None
        self.memory = s["MemW"] == "1" or s["MemtoReg"] == "1"
        self.load = s["MemtoReg"] == "1" and v.get("ReadData") is not None
        self.register_write = v.get("A3") is not None
        self.multiple = trace.kind in xray.MULTIPLE
        self.base_write = v.get("WD5") is not None
        self.reads_15 = xray.PC_NUMBER in (v.get("RA1"), v.get("RA2"), v.get("A4"))
        self.mul = s.get("Mul") == "1"  # MUL and MLA: the third inputs of RA1 and A3
        self.shift_reg = s.get("ShiftReg") == "1"   # a shift by a register: A4 takes Rs
        self.taken = {mux: int(self.f[select][-1]) for mux, (select, _) in MUXES.items()
                      if select in self.f}
        self.taken["RA1Mux"] = int(self.f["RegSrc"][1])
        self.taken["RA2Mux"] = int(self.f["RegSrc"][0])
        if self.mul:
            self.taken.update(dict.fromkeys(MUL_SELECT, 2))
        self.arrives = self._arrivals()

    def _arrivals(self):
        """multiplexer -> the input nets that bring it a value; a multiplexer that an X
        steers, or that nothing reaches, is not there."""
        v, s, fields = self.v, self.s, self.fields

        def has(net):
            return v.get(net) is not None

        def real(select):
            return "X" not in self.signal(select)

        # The third inputs of RA1 and A3 are additions: something comes there only with Mul 1.
        third = self.mul
        arrives = {"PCMux": {"PCPlus4"} | ({"Result"} if has("Result") else set())}
        if self.uses_a and real("RegSrc0"):
            arrives["RA1Mux"] = {"Const15"} | {net for net, comes in (("Rn", True), ("Rs", third))
                                               if comes and net in fields}
        if has("RA2") and real("RegSrc1"):
            arrives["RA2Mux"] = {net for net in ("Rm", "Rd") if net in fields}
        if self.register_write and not self.multiple:   # a pass's register comes as PassReg
            arrives["A3Mux"] = {"Const14"} | {net for net, comes in (("Rd", True), ("Rn", third))
                                              if comes and net in fields}
        if has("A4") and not self.multiple:
            # Rs, the second input, is an addition: it comes only with ShiftReg 1.
            arrives["A4Mux"] = {net for net, comes in (("Rd", True), ("Rs", self.shift_reg))
                                if comes and net in fields}
        if self.register_write:
            arrives["WD3Mux"] = {"PCPlus4"} | ({"Result"} if has("Result") else set())
        if self.memory and real("AdrSrc"):
            arrives["AdrSrcMux"] = {net for net in ("ALUResult", "SrcA") if has(net)}
        if s["MemW"] == "1" and real("StoreSrc"):
            arrives["StoreMux"] = {net for net in ("RD2", "RD4") if has(net)}
        if real("ALUSrc"):
            arrives["ALUSrcMux"] = {net for net in ("Shifted", "ExtImm") if has(net)}
        if real("MemtoReg"):
            arrives["ResultMux"] = {"ALUResult"} | ({"ReadData"} if has("ReadData") else set())
        return arrives

    # helpers

    def move(self, net, **outcomes):
        """A Move of net with its value from Trace.values (control signals: their values)."""
        outcomes = tuple((branch, outcome) for branch, outcome in outcomes.items() if outcome)
        if net in SIGNALS:
            text = self.signal(net)
        elif net == "Const4":
            text = "4"
        elif net == "Const15":
            text = show(net, xray.PC_NUMBER)
        elif net == "Const14":
            text = show(net, xray.LINK_REGISTER)
        elif net == "Imm":
            value, digits = immediate(self.trace)
            text = f"0x{value:0{digits}X}"
        elif net == "Funct":
            text = funct_bits(self.trace)       # only the bits of its funct fields
        else:
            text = show(net, self._value(net))
        return Move(net, text, outcomes)

    def _value(self, net):
        v, word = self.v, self.word
        fields = {"Cond": word >> 28, "Op": word >> 26 & 3, "Funct": word >> 20 & 0x3F,
                  "Rn": word >> 16 & 0xF, "Rd": word >> 12 & 0xF, "Rm": word & 0xF,
                  "Rs": word >> 8 & 0xF, "Shamt": word >> 5 & 0x7F, "Op2": word >> 4 & 0xF}
        if net in fields:
            return fields[net]
        if net == "ShiftC":
            return v["ShiftCarry"]
        return v.get(net)

    def signal(self, net):
        return signal_value(self.trace, net)

    def used(self, block):
        """True when this instruction uses block: a multiplexer that decides, a block that
        works. A control signal goes only to the parts it uses: one that steers only gray
        parts stays gray, with no value beside it."""
        if self.trace.kind == xray.SYSTEM_CALL:
            return block in ("System", "PCMux")     # the system performs the service
        if self.trace.kind == xray.NO_OPERATION:
            return block == "PCMux"     # nothing is written: only the PC goes on
        if block in MUXES:              # it decides when its output travels
            output = MUX_OUTPUTS[block]
            return block in self.arrives and (output == "PC'" or self.v.get(output) is not None)
        if block == "Shifter":
            return self.v.get("RD2") is not None
        if block == "Extend":
            return self.v.get("ExtImm") is not None
        if block == "DMem":
            return self.memory
        if block == "System":
            return False
        return True                     # the register file, the ALU

    def travelling(self, net):
        """The branches of the control signal net that reach a part this instruction uses."""
        return [branch for branch, port in NETS[net][1].items() if self.port_used(port)]

    def port_used(self, port):
        """True when this instruction uses the part behind the input port: the base write port
        (WE5) only when it writes its base, the PC's Hold only in a pass of LDM, STM, PUSH or
        POP, the AdrSrc multiplexer only in a load or store (used()), the Mul select of the RA1
        and A3 multiplexers only in MUL and MLA (Mul travels only when it is 1), the load
        extender in the data memory (Signed) only in a load; else its block's use."""
        if port == "RegFile.WE5":
            return self.base_write
        if port == "PCReg.Hold":
            return self.multiple
        if port.endswith(".Mul"):
            return self.mul and self.used(port.split(".")[0])
        if port == f"{SHIFT_SELECT}.S":  # ShiftReg travels only when it is 1
            return self.shift_reg and self.used(SHIFT_SELECT)
        if port == "DMem.Signed":       # the load extender works on what a load reads
            return self.s["MemtoReg"] == "1" and self.used("DMem")
        return self.used(port.split(".")[0])

    def outcome(self, mux, net):
        """The outcome of net's branch into mux: taken or rejected, None when net brings it
        nothing (or an X steers it)."""
        if net not in self.arrives.get(mux, ()):
            return None
        select, inputs = MUXES[mux]
        return TAKEN if inputs.index(net) == self.taken[mux] else REJECTED

    mux_outcome = outcome

    def decision(self, mux):
        """The Decision of mux, or None when it decides nothing: an X steers it, or nothing
        comes in on the input it takes."""
        arrives = self.arrives.get(mux)
        select, inputs = MUXES[mux]
        taken = self.taken.get(mux)
        if not arrives or inputs[taken] not in arrives:
            return None
        rejected = tuple(number for number, net in enumerate(inputs)
                         if number != taken and net in arrives)
        if mux in MUL_SELECT and self.mul:  # the two bits Mul and the first select: 10, input 2
            return Decision(mux, taken, f"Mul, {select}", "1" + self.signal(select), rejected)
        return Decision(mux, taken, select, self.signal(select), rejected)

    def decisions(self, *muxes):
        return tuple(d for d in (self.decision(mux) for mux in muxes) if d is not None)

    def said(self, value):
        """A signal's value in a sentence (an X stays an X)."""
        return value

    # the steps, in order

    def steps(self):
        return (self.pc(), self.fetch(), self.split(), self.control(), self.signals(),
                self.choose_registers(), self.read_registers(), self.extend(), self.shifter(),
                self.alu_source(), self.carry(), self.alu(), self.address(), self.store_data(),
                self.data_memory(), self.result(), self.write_register(), self.write_flags(),
                self.next_pc(), self.pc_write())

    def pc(self):
        pc = hex32(self.v["PC"])
        return Step(FETCH, f"The PC holds {pc}, the address of this instruction: it goes to the "
                           "instruction memory and to the adder.",
                    moves=(self.move("PC", imem=TAKEN, add4=TAKEN),
                           self.move("Const4", add4=TAKEN)),
                    lights=(("PCReg", pc),))

    def fetch(self):
        v = self.v
        moves = [self.move("Instr", split=TAKEN),
                 self.move("PCPlus4", pcmux=self.outcome("PCMux", "PCPlus4"),
                           add8=TAKEN if self.reads_15 else None,
                           wd3=self.outcome("WD3Mux", "PCPlus4"))]
        return Step(FETCH, f"The instruction memory reads the word at {hex32(v['PC'])}: "
                           f"{hex32(v['Instr'])}. The adder makes PCPlus4 = {hex32(v['PCPlus4'])}.",
                    moves=tuple(moves), lights=(("IMem", "READ"), ("Add4", "+4")))

    def split(self):
        fields = self.fields
        moves = [self.move("Cond", control=TAKEN), self.move("Op", control=TAKEN),
                 self.move("Funct", control=TAKEN)]
        if "Op2" in fields:             # MUL and MLA: 1001 in bits 7:4 tells them from DP
            moves.append(self.move("Op2", control=TAKEN))
        if "Rd" in fields:
            moves.append(self.move("Rd", control=TAKEN, ra2=self.outcome("RA2Mux", "Rd"),
                                   a3=self.outcome("A3Mux", "Rd"),
                                   a4=self.outcome("A4Mux", "Rd")))
        if "Rs" in fields:              # MUL and MLA: to RA1; a shift by a register: to A4
            moves.append(self.move("Rs", ra1=self.outcome("RA1Mux", "Rs"),
                                   a4=self.outcome("A4Mux", "Rs")))
        if "Rm" in fields:
            moves.append(self.move("Rm", ra2=self.outcome("RA2Mux", "Rm")))
        if "Imm" in fields and self.v.get("ExtImm") is not None:
            moves.append(self.move("Imm", extend=TAKEN))
        if "List" in fields:
            moves.append(self.move("List", control=TAKEN))
        if self.uses_a:
            if "Rn" in fields:
                moves.append(self.move("Rn", ra1=self.outcome("RA1Mux", "Rn"),
                                       a3=self.outcome("A3Mux", "Rn")))
            moves.append(self.move("Const15", ra1=self.outcome("RA1Mux", "Const15")))
        if self.f["Shift"] == "1" or self.shift_reg:    # by a register: the kind, bits 6:5
            moves.append(self.move("Shamt", shifter=TAKEN))
        if self.register_write:
            moves.append(self.move("Const14", a3=self.outcome("A3Mux", "Const14")))
        parts = field_parts(self.trace)
        fields_lit = ("cond", "op", "funct", "rn", "rd", "src2", "imm24")
        return Step(DECODE, "The word splits into its fields: " + ", ".join(parts) + ".",
                    moves=tuple(move for move in moves if move.outcomes), fields=fields_lit)

    def control(self):
        trace = self.trace
        word = self.word
        name = _class_word(trace)
        cond = word >> 28
        check = trace.condition
        if cond == 0xE:
            said = "AL: it always runs."
        elif self.multiple:             # a pass: its line also names the pass (keep it short)
            said = check.replace(", executes", ", CondEx 1.").replace(
                ", does not execute", ", CondEx 0: nothing is written.")
        elif self.executes:
            said = check.replace(", executes", ": the condition holds, it runs (CondEx 1).")
        else:
            said = check.replace(", does not execute",
                                 ": the condition fails (CondEx 0): nothing will be written.")
        if self.multiple:
            v = self.v
            return Step(DECODE, f"The control unit decodes {name}; its pass counter takes "
                                f"R{v['PassReg']} and the offset 0x{v['Offset']:X}. {said}",
                        lights=(("Control", _short(trace)),))
        if "Op2" in self.fields:        # op and funct alone are those of AND or EOR
            return Step(DECODE, f"The control unit decodes op {word >> 26 & 3:02b}, funct "
                                f"{funct_bits(trace)} and op2 {word >> 4 & 0xF:04b}: {name}. "
                                f"{said}",
                        lights=(("Control", _short(trace)),))
        return Step(DECODE, f"The control unit decodes op {word >> 26 & 3:02b} and funct "
                            f"{funct_bits(trace)}: {name}. {said}",
                    lights=(("Control", _short(trace)),))

    def signals(self):
        s = self.s
        moves = []
        for net in SIGNALS:
            branches = self.travelling(net)
            if branches:
                moves.append(self.move(net, **{branch: TAKEN for branch in branches}))
        named = ("RegSrc1", "RegSrc0", "Mul", "ShiftReg", "ImmSrc", "ALUSrc", "ALUControl",
                 "AdrSrc", "MemWrite", "MemtoReg", "Size", "Signed", "RegWrite", "BaseWrite",
                 "Hold", "PCSrc")
        if self.multiple:               # the line names the pass too: the main ones only
            named = ("ImmSrc", "ALUControl", "AdrSrc", "MemWrite", "MemtoReg", "RegWrite",
                     "BaseWrite", "Hold", "PCSrc")
        listed = ", ".join(f"{net} {self.signal(net)}" for net in named if self.travelling(net))
        del s
        sentence = f"The control unit sends: {listed}."
        if self.multiple:
            v = self.v
            moves += [self.move("PassReg", regfile=TAKEN), self.move("Offset", extend=TAKEN)]
            sentence = (f"The control unit sends: {listed}; PassReg R{v['PassReg']}, Offset "
                        f"0x{v['Offset']:X}.")
        return Step(DECODE, sentence, moves=tuple(moves))

    def choose_registers(self):
        v = self.v
        moves, words = [], []
        if self.uses_a:
            moves.append(self.move("RA1", regfile=TAKEN))
            words.append(f"RA1 takes {_number(self, 'RA1Mux')}")
        if v.get("RA2") is not None:
            moves.append(self.move("RA2", regfile=TAKEN))
            words.append(f"RA2 takes {_number(self, 'RA2Mux')}")
        a4 = v.get("A4") is not None and not self.multiple  # a pass: A4 comes as PassReg
        if a4:
            moves.append(self.move("A4", regfile=TAKEN))
            words.append(f"A4 takes {_number(self, 'A4Mux')}")
        if not moves:
            return None                 # it reads no register
        if self.reads_15:
            moves.append(self.move("PCPlus8", r15=TAKEN))
            words.append(f"R15 reads as PCPlus8 = {hex32(v['PCPlus8'])}")
        who = "Mul and RegSrc choose" if self.mul else \
            "RegSrc and ShiftReg choose" if self.shift_reg else "RegSrc chooses"
        if self.s["ALUControl"] == xray.ALU_MOVT:   # no RegSrc decides; A4 takes Instr 15:12
            return Step(DECODE, f"MOVT keeps the low half of its Rd: A4 takes "
                                f"{_number(self, 'A4Mux')}, Instr 15:12.",
                        moves=tuple(moves), decisions=self.decisions("A4Mux"))
        return Step(DECODE, f"{who} the registers to read: " + "; ".join(words) + ".",
                    moves=tuple(moves), decisions=self.decisions("RA1Mux", "RA2Mux", "A4Mux"),
                    lights=(("Add8", "+4"),) if self.reads_15 else ())

    def read_registers(self):
        v = self.v
        moves, reads, numbers = [], [], []
        if self.uses_a:
            moves.append(self.move("SrcA", alu=TAKEN, adr=self.outcome("AdrSrcMux", "SrcA")))
            reads.append(f"R{v['RA1']} = {hex32(v['SrcA'])} on RD1")
            numbers.append(f"R{v['RA1']}")
        if v.get("RD2") is not None:
            moves.append(self.move("RD2", shifter=TAKEN, store=self.outcome("StoreMux", "RD2")))
            reads.append(f"R{v['RA2']} = {hex32(v['RD2'])} on RD2")
            numbers.append(f"R{v['RA2']}")
        if v.get("RD4") is not None:     # to the store, the ALU (MLA, MOVT) or the shifter
            into_alu = self.s["ALUControl"] in (xray.ALU_MLA, xray.ALU_MOVT)
            moves.append(self.move("RD4", store=self.outcome("StoreMux", "RD4"),
                                   alu=TAKEN if into_alu else None,
                                   shifter=TAKEN if self.shift_reg else None))
            reads.append(f"R{v['A4']} = {hex32(v['RD4'])} on RD4")
            numbers.append(f"R{v['A4']}")
        if not moves:
            return None
        return Step(DECODE, "The register file reads " + ", ".join(reads) + ".",
                    moves=tuple(moves), lights=(("RegFile", "READ " + ", ".join(numbers)),))

    def extend(self):
        v = self.v
        if v.get("ExtImm") is None:
            return None                 # ImmSrc is X: Extend is not used
        imm_src = self.s["ImmSrc"]
        return Step(DECODE, f"ImmSrc is {imm_src}: Extend {IMM_WAYS[imm_src]}: ExtImm = "
                            f"{hex32(v['ExtImm'])}.",
                    moves=(self.move("ExtImm", alusrc=self.outcome("ALUSrcMux", "ExtImm")),),
                    lights=(("Extend", _extend_word(imm_src)),))

    def shifter(self):
        v = self.v
        if v.get("Shifted") is None:
            return None                 # no register comes to the shifter
        moves = [self.move("Shifted", alusrc=self.outcome("ALUSrcMux", "Shifted"))]
        if self.s["ShiftC"] == "1" and self.s["Shift"] == "1":
            moves.append(self.move("ShiftC", control=TAKEN))
        if self.shift_reg:              # the amount: RD4[7:0], from the register Rs; Shift is 1
            text = xray.shift_text(self.word)
            amount = v["RD4"] & 0xFF
            sentence = (f"ShiftReg 1: the shifter shifts {hex32(v['RD2'])} by R{v['A4']}[7:0] = "
                        f"{amount} ({text}): {hex32(v['Shifted'])}"
                        + (", unchanged: an amount of 0 leaves it and C as they are."
                           if amount == 0 else "."))
            word = text
        elif self.f["Shift"] == "1":
            text = xray.shift_text(self.word)
            sentence = (f"The shifter shifts {hex32(v['RD2'])} ({text}): "
                        f"{hex32(v['Shifted'])}.")
            word = text
        else:
            sentence = f"Shift is 0: the shifter passes RD2 = {hex32(v['RD2'])} on unchanged."
            word = "no shift"
        return Step(EXECUTE, sentence, moves=tuple(moves), lights=(("Shifter", word),))

    def alu_source(self):
        v = self.v
        names = {"ExtImm": "ExtImm", "Shifted": "the shifter's output"}
        inputs = MUXES["ALUSrcMux"][1]
        chosen = inputs[self.taken["ALUSrcMux"]]
        decisions = self.decisions("ALUSrcMux")
        sentence = (f"ALUSrc is {self.s['ALUSrc']}: the multiplexer takes {names[chosen]}, "
                    f"{hex32(v[chosen])}, as SrcB")
        if decisions and decisions[0].rejected:
            sentence += f"; {names[inputs[decisions[0].rejected[0]]]} is rejected"
        return Step(EXECUTE, sentence + ".", moves=(self.move("SrcB", alu=TAKEN),),
                    decisions=decisions)

    def carry(self):
        """ADC, SBC and RSC: CarryIn brings the C flag from the flags register to the adder."""
        carry = self.v.get("CarryIn")
        if carry is None:
            return None
        name = ALU_WORDS[self.s["ALUControl"]]
        return Step(EXECUTE, f"CarryIn brings the C flag, {carry}, from the flags register to the "
                             f"ALU's adder: {name} takes it as its carry in.",
                    moves=(self.move("CarryIn", alu=TAKEN),))

    def alu(self):
        v, s = self.v, self.s
        control = s["ALUControl"]
        word = ALU_WORDS[control]
        b, result = hex32(v["SrcB"]), hex32(v["ALUResult"])
        doing = ALU_DOING[control]
        carry = v.get("CarryIn")
        if control in MULTIPLIER:       # the whole multiplication, in the ALU's line
            added = f" + {hex32(v['RD4'])}" if control == xray.ALU_MLA else ""
            sentence = (f"ALUControl {control}: the multiplier: {hex32(v['SrcA'])} x {b}{added} = "
                        f"{result}")
        elif control == xray.ALU_MOVT:  # the two halves, in the ALU's line
            high, low = v["SrcB"] & 0xFFFF, v["RD4"] & 0xFFFF
            sentence = (f"ALUControl {control}: MOVT: R{v['A4']} = 0x{high:04X} : 0x{low:04X}, the "
                        f"new high half from SrcB and the old low half from RD4: {result}")
        elif control == xray.ALU_ADC:
            sentence = (f"ALUControl {control}: the ALU adds {hex32(v['SrcA'])}, {b} and the carry "
                        f"{carry}: {result}")
        elif control == xray.ALU_SBC:
            sentence = (f"ALUControl {control}: the ALU subtracts {b} and NOT C from "
                        f"{hex32(v['SrcA'])} (C = {carry}): {result}")
        elif control == xray.ALU_RSC:
            sentence = (f"ALUControl {control}: the ALU subtracts {hex32(v['SrcA'])} and NOT C "
                        f"from {b} (C = {carry}): {result}")
        elif not self.uses_a:
            sentence = f"ALUControl {control}: the ALU {doing} SrcB {b}: {result}"
        elif control == xray.ALU_RSB:
            sentence = f"ALUControl {control}: the ALU subtracts {hex32(v['SrcA'])} from {b}: {result}"
        elif control == xray.ALU_SUB:
            sentence = f"ALUControl {control}: the ALU subtracts {b} from {hex32(v['SrcA'])}: {result}"
        else:
            sentence = f"ALUControl {control}: the ALU {doing} {hex32(v['SrcA'])} and {b}: {result}"
        if self.memory and self.s["AdrSrc"] == "1":
            sentence += ", the new base"
        elif self.memory:
            sentence += ", the address" + (" and the new base" if self.base_write else "")
        elif self.s["Branch"] == "1" and self.trace.kind != xray.BRANCH_EXCHANGE:
            sentence += ", the branch target"
        flag_write = s["FlagW"]
        if flag_write != "00":
            sentence += f"; its flags NZCV are {xray.flag_text(v['ALUFlags'])}"
        base = None
        if self.base_write:             # to the base write port: closed when nothing is written
            base = TAKEN if s["BaseWrite"] == "1" else CLOSED
        moves = (self.move("ALUResult", adr=self.outcome("AdrSrcMux", "ALUResult"),
                           result=self.outcome("ResultMux", "ALUResult"), wd5=base),
                 self.move("ALUFlags", control=TAKEN if s["FlagWrite"] != "00" else CLOSED))
        return Step(EXECUTE, sentence + ".", moves=moves, lights=(("ALU", word),))

    def address(self):
        """AdrSrc chooses the data memory's address: ALUResult, or for post-indexing RD1, the
        base as it was before this access."""
        if not self.memory:
            return None
        v = self.v
        decisions = self.decisions("AdrSrcMux")
        if self.taken["AdrSrcMux"]:
            said = (f"AdrSrc is 1: the address is RD1 = {hex32(v['SrcA'])}, the base before this "
                    f"access; ALUResult is rejected")
        else:
            said = f"AdrSrc is 0: the address is ALUResult = {hex32(v['ALUResult'])}"
            if decisions and decisions[0].rejected:
                said += "; RD1 is rejected"
        return Step(MEMORY, said + ".", moves=(self.move("Address", dmem=TAKEN),),
                    decisions=decisions)

    def store_data(self):
        if self.s["MemW"] != "1":
            return None
        v = self.v
        inputs = MUXES["StoreMux"][1]
        chosen = inputs[self.taken["StoreMux"]]
        decisions = self.decisions("StoreMux")
        outcome = TAKEN if self.s["MemWrite"] == "1" else CLOSED
        sentence = f"StoreSrc is {self.s['StoreSrc']}: WriteData takes {chosen} = {hex32(v[chosen])}"
        if decisions and decisions[0].rejected:
            sentence += f"; {inputs[decisions[0].rejected[0]]} is rejected"
        return Step(MEMORY, sentence + ".", moves=(self.move("WriteData", dmem=outcome),),
                    decisions=decisions)

    def data_memory(self):
        v, s = self.v, self.s
        write = s["MemWrite"] == "1"
        gate = Gate("DMem", "MemWrite", s["MemWrite"], write)
        size = SIZE_WORDS[s["Size"]]
        if not self.memory:             # MemWrite steers only a gray block: no mark
            return Step(MEMORY, "MemWrite is 0: the data memory writes nothing, and nothing "
                                "reads it.")
        address = hex32(v["Address"])
        count = xray.SIZES[s["Size"]]
        if write:
            data = v["WriteData"] & (1 << 8 * count) - 1
            return Step(MEMORY, f"MemWrite is 1: the data memory writes the {size} "
                                f"0x{data:0{2 * count}X} at {address}.", gates=(gate,),
                        lights=(("DMem", memory_word("WRITE", s)),))
        if not self.executes:
            return Step(MEMORY, "MemWrite is 0, and the condition failed: the data memory "
                                "neither writes nor reads.", gates=(gate,))
        word = memory_word("READ", s)
        if self.load:
            read = v["ReadData"]
            said = (f"MemWrite is 0: nothing is written. The data memory reads the {size} at "
                    f"{address}")
            if count < 4:               # the load extender widens it to 32 bits
                raw, top = read & (1 << 8 * count) - 1, 8 * count
                if s["Signed"] == "1":
                    said += (f": 0x{raw:0{2 * count}X}; its load extender copies the sign bit, "
                             f"{raw >> top - 1}, into bits 31:{top}: ReadData = {hex32(read)}.")
                else:
                    said += (f": 0x{raw:0{2 * count}X}; its load extender fills bits 31:{top} "
                             f"with zeros: ReadData = {hex32(read)}.")
            else:
                said += f": {hex32(read)}."
            return Step(MEMORY, said,
                        moves=(self.move("ReadData",
                                         result=self.outcome("ResultMux", "ReadData")),),
                        gates=(gate,), lights=(("DMem", word),))
        return Step(MEMORY, f"MemWrite is 0: nothing is written. What the data memory reads at "
                            f"{address} cannot be known before the program reads it.",
                    gates=(gate,), lights=(("DMem", word),))

    def result(self):
        v, s = self.v, self.s
        if v.get("Result") is None:
            return None                 # MemtoReg is X: the Result multiplexer is not used
        outcomes = {"pcmux": self.outcome("PCMux", "Result"),
                    "wd3": self.outcome("WD3Mux", "Result")}
        if self.taken["ResultMux"]:
            said = f"Result takes ReadData = {hex32(v['ReadData'])}; ALUResult is rejected"
        else:
            said = f"Result takes ALUResult = {hex32(v['ALUResult'])}"
        return Step(WRITE_BACK, f"MemtoReg is {s['MemtoReg']}: {said}.",
                    moves=(self.move("Result", **outcomes),),
                    decisions=self.decisions("ResultMux"))

    def write_register(self):
        v, s = self.v, self.s
        writes = s["RegWrite"] == "1"
        gate = Gate("RegFile", "RegWrite", s["RegWrite"], writes)
        base, base_said, written = self._base()
        if not self.register_write:
            if s["NoWrite"] == "1":
                what = (f"{CMD_NAMES[self.word >> 21 & 0xF]} only sets the flags; no register is "
                        "written")
            elif self.trace.kind in xray.STORES:
                what = "a store writes no register"
            else:
                what = "a branch writes no register"
            lights = (("RegFile", "WRITE " + written),) if written else ()
            return Step(WRITE_BACK, f"RegWrite is 0: {what}{base_said}.",
                        gates=(gate,) + base, lights=lights)
        outcome = TAKEN if writes else CLOSED
        a3, wd3 = v["A3"], v["WD3"]
        target = f"R{a3}"
        source = " (from PassReg)" if self.multiple else " (Instr 19:16: Mul is 1)" if self.mul \
            else ""
        if writes:
            sentence = f"RegWrite is 1: {target}{source} takes {hex32(wd3)}"
            if a3 == xray.PC_NUMBER:
                sentence += " (R15 is the PC: the PC takes it, below)"
            names = [target] + ([written] if written else [])
            lights = (("RegFile", "WRITE " + ", ".join(names)),)
        else:
            sentence = f"RegWrite is 0: the condition failed, so {target} keeps its value"
            lights = ()
        moves = [] if self.multiple else [self.move("A3", regfile=outcome)]
        if wd3 is not None:
            moves.append(self.move("WD3", regfile=outcome))
        return Step(WRITE_BACK, sentence + base_said + ".", moves=tuple(moves),
                    decisions=self.decisions("A3Mux", "WD3Mux"), gates=(gate,) + base,
                    lights=lights)

    def _base(self):
        """The base write port: (its gate, as a tuple, the words that say what it does, the base
        it writes or ""); nothing when the instruction does not write the base."""
        if not self.base_write:
            return (), "", ""
        v, s = self.v, self.s
        writes = s["BaseWrite"] == "1"
        gate = Gate("Base", "BaseWrite", s["BaseWrite"], writes)
        base = f"R{v['A5']}"
        if writes:
            said = f"; BaseWrite is 1: the base {base} takes WD5 = {hex32(v['WD5'])}"
            return (gate,), said, base
        return (gate,), f"; BaseWrite is 0: the base {base} keeps its value", ""

    def write_flags(self):
        trace, s = self.trace, self.s
        flag_write = s["FlagWrite"]
        gate = Gate("Control", "FlagWrite", flag_write, flag_write != "00")
        old, new = xray.flag_text(trace.flags), xray.flag_text(trace.new_flags)
        if flag_write == "00":
            if s["FlagW"] != "00":
                said = f"FlagWrite is 00: the condition failed, so the flags stay NZCV {old}."
            else:
                said = f"FlagWrite is 00: the flags stay NZCV {old}."
        elif flag_write == "10":
            said = f"FlagWrite is 10: N and Z are written (C too, from the shifter): NZCV {old} -> {new}." \
                if s["ShiftC"] == "1" else f"FlagWrite is 10: N and Z are written: NZCV {old} -> {new}."
        else:
            said = f"FlagWrite is 11: all four flags are written: NZCV {old} -> {new}."
        return Step(WRITE_BACK, said, gates=(gate,))

    def next_pc(self):
        v, s = self.v, self.s
        result = "; Result is rejected" if "Result" in self.arrives["PCMux"] else ""
        if self.taken["PCMux"]:
            said = f"PCSrc is 1: PC' takes Result = {hex32(v['Result'])}; PCPlus4 is rejected."
        elif s["PCS"] == "1" and not self.executes:
            said = (f"PCSrc is 0 because the condition failed: PC' takes PCPlus4 = "
                    f"{hex32(v['PCPlus4'])}{result}.")
        else:
            said = f"PCSrc is 0: PC' takes PCPlus4 = {hex32(v['PCPlus4'])}{result}."
        held = self.s.get("Hold") == "1"
        return Step(NEXT_PC, said, moves=(self.move("PC'", pcreg=CLOSED if held else TAKEN),),
                    decisions=self.decisions("PCMux"))

    # A system call ------------------------------------------------------------------------

    def system_steps(self, service, waiting, error=""):
        """The film of an SVC: fetched and decoded as any instruction, then the control unit
        calls the system, which performs the service; then the PC goes on. waiting, from WAITS,
        is what the service waits for (the film ends at the system), or None; error says why
        the service failed (the program stops there)."""
        word = self.word
        number = word & 0xFFFFFF
        steps = [self.pc()]
        fetch = self.fetch()
        steps.append(replace(fetch, moves=(self.move("Instr", split=TAKEN),
                                           self.move("PCPlus4", pcmux=TAKEN))))
        steps.append(Step(DECODE, "The word splits into its fields: "
                                  + ", ".join(field_parts(self.trace))
                                  + ", the number of the service.",
                          moves=(self.move("Cond", control=TAKEN), self.move("Op", control=TAKEN),
                                 self.move("Funct", control=TAKEN), self.move("Rd", control=TAKEN),
                                 self.move("SvcNum", system=TAKEN)),
                          fields=("cond", "op", "funct", "imm24")))
        steps.append(self.control())
        if self.executes:
            said = ("The control signals leave the control unit: Syscall 1 calls the system; "
                    "RegWrite 0 and MemWrite 0: the datapath writes no register and no memory.")
        else:
            said = ("The control signals leave the control unit; the condition failed, so "
                    "Syscall, RegWrite and MemWrite are 0.")
        signals = self.signals()
        if waiting or error:            # the film stops at the system: no PC multiplexer
            signals = replace(signals, moves=tuple(m for m in signals.moves if m.net != "PCSrc"))
        steps.append(replace(signals, sentence=said))
        said = service or f"SVC #{number}"
        if not self.executes:
            sentence = "The condition failed: the system does nothing, and the PC goes on."
            word_shown = f"SVC #{number}\nnot called"
        elif error:
            sentence = (f"Syscall is 1, so the control unit hands the call to the system, but the "
                        f"service fails: {error}. The program stops here.")
            word_shown = f"{said}\nfails"
        elif waiting:
            word, sentence = waiting
            sentence = (f"Syscall is 1, so the control unit hands the call to the system. {said}: "
                        f"{sentence}")
            word_shown = f"{said}\n{word}"
        else:
            sentence = (f"Syscall is 1, so the control unit hands the call to the system, and "
                        f"ARES performs it. {said}.")
            word_shown = said
        steps.append(Step(EXECUTE, sentence, lights=(("System", word_shown),)))
        if (waiting or error) and self.executes:
            return steps
        next_pc = self.next_pc()
        steps.append(replace(next_pc, sentence=f"PCSrc is 0: PC' takes PCPlus4 = "
                                               f"{hex32(self.v['PCPlus4'])}."))
        steps.append(self.pc_write())
        return steps

    # A NOP --------------------------------------------------------------------------------

    def nop_steps(self):
        """The film of a NOP: fetched and decoded as any instruction; its row of the Main Decoder
        writes nothing, so no other part works, and the PC goes on."""
        steps = [self.pc()]
        fetch = self.fetch()
        steps.append(replace(fetch, moves=(self.move("Instr", split=TAKEN),
                                           self.move("PCPlus4", pcmux=TAKEN))))
        steps.append(Step(DECODE, "The word splits into its fields: "
                                  + ", ".join(field_parts(self.trace))
                                  + "; bits 19:0 say which hint.",
                          moves=(self.move("Cond", control=TAKEN), self.move("Op", control=TAKEN),
                                 self.move("Funct", control=TAKEN)),
                          fields=("cond", "op", "funct")))
        steps.append(self.control())
        signals = self.signals()
        steps.append(replace(signals, sentence="The control unit sends: PCSrc 0; RegWrite, "
                                               "MemWrite and FlagWrite are 0."))
        steps.append(Step(WRITE_BACK, "NOP: nothing is written. No register is read, and the "
                                      "ALU and the memory do nothing."))
        steps.append(self.next_pc())
        steps.append(self.pc_write())
        return steps

    def pc_write(self):
        if self.s.get("Hold") == "1":   # an LDM or STM before its last pass
            pc = hex32(self.v["PC"])
            return Step(NEXT_PC, f"Hold is 1: at the clock edge the pass counter keeps the PC at "
                                 f"{pc}, so pass {self.trace.number + 1} runs the same "
                                 f"instruction.",
                        gates=(Gate("PCReg", "Hold", "1", False),), lights=(("PCReg", pc),))
        new = self.v["PC'"]
        text = hex32(new)
        there = f": the next instruction is {self.next_text}." if self.next_text else \
            ": the next instruction is there."
        said = f"At the clock edge the PC takes {text}{there}"
        if self.trace.to_thumb:
            said += " " + xray.NOTE_TO_THUMB
        return Step(NEXT_PC, said, lights=(("PCReg", text),))


def memory_word(action, signals):
    """What the data memory says it does: READ or WRITE, with the size when it is not a word, and
    for a signed load SIGNED on a second line, where the block is narrow: READ HALF, READ BYTE and
    SIGNED."""
    size = signals["Size"]
    if size == xray.SIZE_WORD:
        return action
    word = f"{action} {'HALF' if size == xray.SIZE_HALF else 'BYTE'}"
    return word + "\nSIGNED" if signals.get("Signed") == "1" else word


def _number(builder, mux):
    """What a register-number multiplexer took, for a sentence: "R1 (Rn)"; MLA's Ra comes on the
    wire of Instr 15:12, which is Rd's."""
    select, inputs = MUXES[mux]
    net = inputs[builder.taken[mux]]
    value = builder.v[MUX_OUTPUTS[mux]]
    if net == "Rd" and mux == "A4Mux" and builder.trace.kind == xray.MULTIPLY:
        net = "Ra"
    return f"R{value} ({net.replace('Const', '')})"


def _class_word(trace):
    word = trace.word
    kind = trace.kind
    if kind in (xray.DP_REGISTER, xray.DP_IMMEDIATE):
        name = CMD_NAMES[word >> 21 & 0xF]
        what = "an immediate operand" if kind == xray.DP_IMMEDIATE else "a register operand"
        if xray.shifted_by_register(word):
            what = "a register shifted by a register"
        s = "S" if word >> 20 & 1 and name not in ("CMP", "CMN", "TST", "TEQ") else ""
        return f"{name}{s}, data processing with {what}"
    if kind in (xray.LOAD_IMMEDIATE, xray.LOAD_REGISTER):
        size = "LDRB" if word >> 22 & 1 else "LDR"
        offset = "an immediate" if kind == xray.LOAD_IMMEDIATE else "a register"
        return f"{size}, a load with {offset} offset{_indexing(word)}"
    if kind in (xray.STORE_IMMEDIATE, xray.STORE_REGISTER):
        size = "STRB" if word >> 22 & 1 else "STR"
        offset = "an immediate" if kind == xray.STORE_IMMEDIATE else "a register"
        return f"{size}, a store with {offset} offset{_indexing(word)}"
    if kind in xray.HALVES:             # 1SH1 in bits 7:4: S signed, H a halfword (else a byte)
        name = HALF_NAMES[word >> 20 & 1, word >> 6 & 1, word >> 5 & 1]
        what = {"LDRH": "a halfword", "LDRSB": "a signed byte", "LDRSH": "a signed halfword",
                "STRH": "a halfword"}[name]
        doing = "a load of" if word >> 20 & 1 else "a store of"
        offset = "an immediate" if word >> 22 & 1 else "a register"
        return f"{name}, {doing} {what} with {offset} offset{_indexing(word)}"
    if kind == xray.MOVE_16:
        if word >> 22 & 1:
            return "MOVT, a move of a 16-bit immediate into the high half"
        return "MOVW, a move of a 16-bit immediate"
    if kind == xray.BRANCH:
        return "B, a branch"
    if kind == xray.BRANCH_LINK:
        return "BL, a branch with link"
    if kind == xray.SYSTEM_CALL:
        return "SVC, a call to the system"
    if kind in xray.MULTIPLE:
        what = "a load" if kind == xray.LOAD_MULTIPLE else "a store"
        return f"{_short(trace)}, {what} multiple"
    if kind == xray.MULTIPLY:
        s = "S" if word >> 20 & 1 else ""
        return f"MLA{s}, a multiply-accumulate" if word >> 21 & 1 else f"MUL{s}, a multiply"
    if kind == xray.NO_OPERATION:
        return "NOP, a hint that does nothing"
    if kind == xray.BRANCH_LINK_EXCHANGE:
        return "BLX, a branch with link to the address in a register"
    return "BX, a branch to the address in a register"


def _indexing(word):
    """How a load or store moves its base, for the control unit's sentence."""
    if not word >> 24 & 1:
        return ", post-indexed"
    if word >> 21 & 1:
        return ", with write-back"
    return ""


def _short(trace):
    """The control unit's word: the instruction's name."""
    return trace.text.split()[0] if trace.text else ""


def _extend_word(imm_src):
    return {"000": "ROTATE imm8", "001": "ZERO-EXTEND imm12", "010": "SIGN-EXT imm24 x4",
            "011": "PASS OFFSET", "100": "JOIN imm4:imm12", "101": "JOIN imm4H:imm4L"}[imm_src]
