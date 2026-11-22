# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""The look of the ARM X-Ray: the fills of its blocks, the colours of its values and of its
strip, for its picture and for the windows inside its blocks.

A block the instruction does not use stays pale; one it uses waits in a calm blue until its
inputs have arrived, lights while it works and keeps a lighter tint once it is done
(fill_of()). With no instruction shown, every block rests in the calm blue.

A value keeps its colour wherever it goes (net_colours()). What comes from a field of the
word keeps the field's colour through the blocks it passes: Rn's number, the value read for
it and SrcA; the second register's number, its value, the shifter's output and the data to
store; the immediate and ExtImm; Rd and A3. After a multiplexer a wire has the colour of the
input taken. New values have colours of their own: the PC and its sums; the ALU's result,
with the address and the result written back; the data read from memory. The register file
gives PCPlus8 for R15, so a value read for R15 has the PC's colour. A value lights on a band
of its own colour as it travels and arrives, then stays readable on a tint of it (band(),
rest()); what the instruction changes, the register written, the memory word, the flags and
the PC (WRITES), rests on the green of the changed rows of the Registers pane.

The instruction table under the picture is the key: each field's cells take the colour of
the field's value on the picture (VALUES by the kinds of ares.xray_film.fields_of()).

Every text and line colour here keeps a contrast of at least 3 to 1 (contrast(), the WCAG
ratio) on the fills it lies on: IDLE, the gray of unused parts, only on white and PALE.
"""

from ... import xray
from ...xray_film import KINDS, MUX_OUTPUTS, MUXES, PARTS, SIGNALS, signal_value
from ..registers import CHANGED
from .pipeline import COLOURS as PIPELINE_COLOURS

# The fills of a block: not used by the instruction, used and waiting for its inputs, at work,
# and done.
UNUSED_FILL = "#F3F6FA"
WAITING_FILL = "#DCE8F6"
WORKING_FILL = "#FFE58A"
DONE_FILL = "#FFF4C7"
FILLS = {"unused": UNUSED_FILL, "waiting": WAITING_FILL, "working": WORKING_FILL,
         "done": DONE_FILL}
WHITE = "#FFFFFF"               # the picture's background

# Texts and lines.
INK = "#202020"                 # words, outlines and values that are in use
IDLE = "#8E8E8E"                # what the instruction does not use: on WHITE or UNUSED_FILL only
DIM = "#6E6E6E"                 # a part not in use that lies on a fill other than those two
ON = "#D00000"                  # a control signal that is 1
OFF = "#6E6E6E"                 # one that is 0; also X, dashed
MARK = "#6E6E6E"                # the cross of a rejected input, the bar of a closed write

# CHANGED, imported above, is the green of the changed rows of the Registers pane: what the
# instruction changes rests on it. What it changes, as (net, branch) arriving at an open write:
# the register written, the base written, the memory word, the flags and the PC.
WRITES = frozenset({("WD3", "regfile"), ("ALUResult", "wd5"), ("WriteData", "dmem"),
                    ("ALUFlags", "control"), ("PC'", "pcreg")})

# The strip's parts take the colours of the Pipeline Simulator's stages; Next PC has its own.
NEXT_PC = "#F4CCCC"
STAGES = dict(zip(PARTS, (PIPELINE_COLOURS["IF"], PIPELINE_COLOURS["ID"],
                          PIPELINE_COLOURS["EX"], PIPELINE_COLOURS["MEM"],
                          PIPELINE_COLOURS["WB"], NEXT_PC)))

# The colours of the values, by class. The classes of the fields are the kinds of
# ares.xray_film.fields_of(); op and funct, which the decoders read together, share a colour,
# and so do the flags and the constants. Each has a contrast of at least 4.5 to 1 on white.
VALUES = {
    "pc": "#8A5A00", "instr": "#4B0082", "cond": "#B0006A", "op": "#7B3FB5",
    "funct": "#7B3FB5", "rn": "#007A33", "rd": "#0047AB", "rm": "#007C80", "imm": "#C25400",
    "shamt": "#5F6B00", "alu": "#8B1A1A", "memory": "#4466FF", "flags": "#455A64",
    "constant": "#455A64",
}
# Each net's class as it leaves its source when nothing follows another (ares.xray_film.KINDS):
# the nets below take another's class for an instruction (net_colours()); these are their
# classes without one.
FOLLOWING = {"RA1": "rn", "RA2": "rm", "A3": "rd", "A4": "rd", "SrcA": "rn", "RD2": "rm",
             "RD4": "rd", "Shifted": "rm", "SrcB": "rm", "WriteData": "rd", "Address": "alu",
             "Result": "alu", "WD3": "alu", "PC'": "pc"}
CLASSES = {**{net: kind for net, kind in KINDS.items() if net not in SIGNALS}, **FOLLOWING}
# A register's value read takes the class of its number: (value, number).
READS = (("SrcA", "RA1"), ("RD2", "RA2"), ("RD4", "A4"))
TINT = 0.18                     # how much of its colour the tint of a resting value takes


# Contrast ----------------------------------------------------------------------------------

def luminance(colour):
    """The relative luminance of a colour "#RRGGBB" (WCAG 2)."""
    def linear(channel):
        c = channel / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (linear(int(colour[i:i + 2], 16)) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(one, other):
    """The contrast ratio of two colours, from 1 to 21 (WCAG 2)."""
    light, dark = sorted((luminance(one), luminance(other)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def tint(colour, share=TINT):
    """colour mixed with white, share of it."""
    return "#" + "".join(f"{round(255 - (255 - int(colour[i:i + 2], 16)) * share):02X}"
                         for i in (1, 3, 5))


def ink_on(fill):
    """The text colour that reads best on fill: white or INK."""
    return WHITE if contrast(WHITE, fill) >= contrast(INK, fill) else INK


# Blocks and values ---------------------------------------------------------------------------

def fill_of(state, used=True):
    """A block's fill: state is "idle" before the block's first step of the film, "working"
    during a step in which it works and "done" after it (as ares.gui.tools.xray_inside.phase()
    gives them); a block the instruction does not use (used False) stays pale."""
    if not used:
        return UNUSED_FILL
    return {"working": WORKING_FILL, "done": DONE_FILL}.get(state, WAITING_FILL)


def band(colour):
    """(fill, text) of a value that travels or has just arrived: a band of its colour."""
    return colour, ink_on(colour)


def rest(colour, changed=False):
    """(fill, text) of a value that has arrived and stays: a tint of its colour, or the green
    of a change."""
    return (CHANGED if changed else tint(colour)), INK


def signal_colour(value):
    """A control signal's colour: red for 1 (any bit), gray for 0, gray dashed for X."""
    if value is None or "X" in value or "1" not in value:
        return OFF
    return ON


def taken_inputs(trace):
    """multiplexer -> the number of the input it takes for trace's instruction (a pass of it):
    its select's value, an X filled as 0 as in the circuit drawn; Mul 1 takes the third input
    of the RA1 and A3 multiplexers."""
    signals = trace.signals
    filled = {name: xray.filled(value) for name, value in signals.items()}
    taken = {mux: int(filled[select][-1]) for mux, (select, _) in MUXES.items()
             if select in filled}
    if "RegSrc" in filled:
        taken["RA1Mux"], taken["RA2Mux"] = int(filled["RegSrc"][1]), int(filled["RegSrc"][0])
    if signals.get("Mul") == "1":
        taken["RA1Mux"] = taken["A3Mux"] = 2
    return taken


_classes = []                   # [(trace, its classes)]: the last ones worked out


def classes_of(trace):
    """net -> its class for trace's instruction (a pass of it), CLASSES without one: a
    multiplexer's output takes the class of the input taken, a register's value read the class
    of its number (the PC's for R15), RD4 in a pass of LDM, STM, PUSH or POP PassReg's, and the
    shifter's output the class of its input."""
    if trace is None or not trace.signals:
        return dict(CLASSES)
    for known, found in _classes:
        if known is trace:
            return dict(found)
    found = dict(CLASSES)
    taken = taken_inputs(trace)
    values = trace.values
    outputs = {output: mux for mux, output in MUX_OUTPUTS.items()}

    def through(net):
        mux = outputs[net]
        number = taken.get(mux)
        if number is not None:
            found[net] = found[MUXES[mux][1][number]]
    for net in ("RA1", "RA2", "A3", "A4"):
        through(net)
    for value, number in READS:
        if value == "RD4" and trace.kind in xray.MULTIPLE:  # a pass reads PassReg's register
            number = "PassReg"
        found[value] = "pc" if values.get(number) == xray.PC_NUMBER else found[number]
    found["Shifted"] = found["RD2"]
    for net in ("SrcB", "WriteData", "Address", "Result", "WD3", "PC'"):
        through(net)
    _classes[:] = [(trace, found)] + _classes[:7]
    return dict(found)


def net_colours(trace):
    """net -> its colour for trace's instruction (a pass of it; None: no instruction): its
    class's (classes_of()), and for a control signal red or gray by its value."""
    colours = {net: VALUES[kind] for net, kind in classes_of(trace).items()}
    if trace is not None and trace.signals:
        colours.update((net, signal_colour(signal_value(trace, net))) for net in SIGNALS)
    else:
        colours.update(dict.fromkeys(SIGNALS, OFF))
    return colours


def net_colour(net, trace=None, value=None):
    """One net's colour for trace's instruction (net_colours()); a control signal's by value
    when it is given."""
    if net in SIGNALS and value is not None:
        return signal_colour(value)
    return net_colours(trace).get(net, VALUES["constant"])


def field_colour(kind):
    """The colour of a field of the word by its kind (ares.xray_film.fields_of()): the colour of
    its value on the picture; INK for bits that the kind of instruction fixes ("constant")."""
    return INK if kind == "constant" else VALUES.get(kind, INK)
