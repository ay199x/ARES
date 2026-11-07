# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (c) 2026 The ARES Project
"""Who made ARES and why: the words the About box, the Help window and README.md share."""

CREATED_BY = "Created by Ayush Shashikant Pindoria."
ADVISORS_HEADING = "Advisors:"
ADVISORS = (
    "Ronald F. DeMara, Ph.D., P.E., Pegasus Professor, Department of Electrical and Computer "
    "Engineering, University of Central Florida; Fellow of IEEE and AAAS.",
    "Paul Amoruso, Ph.D., Assistant Professor of Computer Engineering, Florida Polytechnic "
    "University.",
)
FIRST_USED = ("First used in the EEL 3801 Computer Organization labs at the University of Central "
              "Florida.")
CREDITS = (CREATED_BY, ADVISORS_HEADING, *ADVISORS, FIRST_USED)
TEXTBOOK = "Harris and Harris, Digital Design and Computer Architecture: ARM Edition."

# The paragraphs of the start of the Help's Intro page.
MOTIVATION = (
    "MARS made MIPS assembly easy to learn, with an editor, a debugger and tools in one program, "
    "but ARM had nothing like it. The closest was CPUlator, which beginners in assembly language "
    "find hard to learn.",
    "So ARES was built: an easy simulator for ARMv7 that university labs can use. Its first "
    "version is used in the EEL 3801 labs at UCF.",
)
FUN_FACT = ("Fun fact: ARES stands for ARM Educational Simulator, and Ares is the Greek name of "
            "the god of war whom the Romans called Mars, so ARES and MARS mean the same thing in "
            "two languages.")
# The same, shortened, as one line of README.md.
README_LINE = ("Why ARES: MARS made MIPS assembly easy to learn, but ARM had nothing like it, and "
               "the closest, CPUlator, is hard for beginners. ARES is an easy simulator for ARMv7 "
               "that university labs can use. Ares is the Greek name of the god the Romans called "
               "Mars, so ARES and MARS mean the same thing in two languages.")
