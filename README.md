<img src="docs/ares-helmet.png" alt="The helmet of Ares" width="128">

# ARES

ARES, the ARM Educational Simulator, is a desktop program for writing, assembling, running and
debugging assembly language programs. It supports the ARMv7 instruction set, and programs written
for CPUlator's ARMv7 DE1-SoC system assemble in it, with their instructions and registers in
capitals (Edit > Capitalize Instructions does that).

Why ARES: MARS made MIPS assembly easy to learn, but ARM had nothing like it, and the closest, CPUlator, is hard for beginners. ARES is an easy simulator for ARMv7 that university labs can use. Ares is the Greek name of the god the Romans called Mars, so ARES and MARS mean the same thing in two languages.

![The ARES window](docs/screenshot.png)

## Download

Get the latest version from this repository's Releases page:

| File | System |
|---|---|
| `ARES.exe` | Windows 10 or 11, 64-bit: one file to run |
| `ARES-windows.zip` | the same as a folder, if antivirus software dislikes the single file |

Packages for macOS and Linux will follow on the same page.

The first time you start it, ARES is not signed, so your system asks:

- **Windows:** in the SmartScreen message, choose **More info > Run anyway**.
- **macOS 14 or older:** right-click the app and choose **Open**.
- **macOS 15 or newer:** open it once, then choose **Open Anyway** in **System Settings > Privacy & Security**.
- **Linux:** unpack the archive and run `ARES/ARES`; nothing else is needed.

## A first program

```
        .data
hello:  .asciz  "Hello, world!\n"

        .global _start
        .text
_start: LDR     R0, =hello      @ R0 = the address of the text
        SVC     #4              @ print the string
        SVC     #10             @ end the program
```

Press F3 to assemble and F5 to run. Help > Help explains the rest, and File > Open Example has more
programs.

## Build it yourself

With Python 3.11 or newer (on Linux 3.12 or newer, with `python3-tk` and `xvfb` for the tests), on the
system you build for:

```
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python tools/build.py
```

On Windows write `py` for `python3` and `.venv\Scripts\python` for `.venv/bin/python`. `tools/build.py`
fetches the GNU assembler and linker, runs the tests and leaves the packages in `dist`. To run ARES
without building it: `.venv/bin/python tools/fetch_toolchain.py`, then `.venv/bin/python -m ares`.

## Credits

Created by Ayush Shashikant Pindoria.

Advisors:

1. Ronald F. DeMara, Ph.D., P.E., Pegasus Professor, Department of Electrical and Computer Engineering, University of Central Florida; Fellow of IEEE and AAAS.
2. Paul Amoruso, Ph.D., Assistant Professor of Computer Engineering, Florida Polytechnic University.

First used in the EEL 3801 Computer Organization labs at the University of Central Florida.

## Licence

ARES is open source: anyone may use, study, change and share it, and changed versions that are
shared must stay open source too. It is licensed under GPL-2.0-or-later (see `LICENSE`). `THIRD_PARTY_NOTICES.txt` lists the
components it includes, their licences and where their source code is published.

Acknowledgements: inspired by MARS and its tools; compatible with CPUlator's ARMv7 syntax; built on GNU binutils, Unicorn and Capstone; Dynamic Instruction Counter tool based on DynARMic.
