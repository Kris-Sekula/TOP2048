# toprammer for Windows 10/11 x64, with GAL16V8 / GAL20V8 / GAL22V10 support

This folder is a copy of [**toprammer**](https://github.com/mbuesch/toprammer) (upstream commit `cac51c0`, imported with its full history), Michael Büsch's open-source software for **TOP2049**-family USB universal programmers (USB ID `VID_2471 PID_0853`, also sold as TOP853 / TOP2048), with changes that do three things:

1. **Makes toprammer work on 64-bit Windows 10/11**, using Microsoft's signed WinUSB driver. There are no kernel drivers to install, no test-signing mode, and no libusb.
2. **Adds GAL programming**: GAL16V8 (A/B/D), GAL20V8 (A/B) and GAL22V10, from both the command line and the GUI, using standard JEDEC (`.jed`) fuse files.
3. **Adds bipolar PROM reading** for the Tesla MH74S571 / 74S571 (512 × 4).

It also fixes several GUI annoyances and removes the deprecated `pkg_resources` dependency.

> If you only need the original **TopWin** software running on 64-bit Windows, see the companion project **[TopWD](../TopWD/)** in this repository. It's a drop-in `version.dll` that replaces TopWin's old Jungo WinDriver kernel driver. TopWD and this toprammer fork both use the same WinUSB driver, so they can be used side by side (but not at the same time).

---

## Tested hardware

Programmer: TOP2049-compatible unit, firmware string `top2049 ver1.08`, on Windows 11 x64 with Python 3.14.

| Chip | PES (signature) | Programming | Command line | GUI |
|---|---|---|---|---|
| Lattice GAL16V8A | `00 03 1A A1 …` algorithm 3 | 14.5 V, 40 ms | ✅ Verify OK | ✅ |
| Lattice GAL16V8 (newer part) | `00 05 1A A1 CD A4 …` algorithm 5 | 14.0 V, 40 ms | ✅ Verify OK | ✅ |
| Lattice GAL16V8A-15LP (early) | `01 02 1A A1 …` algorithm 2 | 16.5 V, 10 ms | ✅ Verify OK | ✅ |
| Lattice GAL20V8A/B | `00 03 3A A1 …` algorithm 3 | 14.5 V, 40 ms | ✅ Verify OK | ✅ |
| Lattice GAL22V10 | `00 02 48 A1 …` algorithm 2 | 14.5 V, 40 ms | ✅ Verify OK | ✅ |

The original EPROM support also works on Windows through the new USB backend.

---

## What was changed, and why

### 1. Windows USB: a direct WinUSB backend (`libtoprammer/winusb_direct.py`)

Upstream toprammer reaches the programmer through PyUSB and libusb. On Windows, **libusb never sees the TOP programmer**. Its device descriptor claims **25 USB configurations** (`bNumConfigurations = 25`) but only one exists. libusb tries to read all 25 configuration descriptors, fails, and drops the device. Its debug log shows `found 25 configurations … failed to initialize device`. Windows itself, WinUSB and TopWin only ever use configuration 0, so they're unaffected.

`winusb_direct.py` talks to WinUSB directly through `ctypes`, so it needs no extra Python packages:

- It finds the device with SetupAPI. It prefers the device interface GUID that Zadig/libwdi writes to the registry, and falls back to the generic USB device interface.
- It opens the device with `WinUsb_Initialize` and enumerates the bulk endpoints with `WinUsb_QueryPipe`.
- It handles bulk reads and writes with per-pipe timeouts, plus pipe resets.

`libtoprammer/hardware_access_usb.py` uses this backend automatically on Windows and keeps PyUSB/libusb on Linux and macOS. On Windows you can set `TOPRAMMER_LIBUSB=1` to force the libusb path.

Self-test, which reads the programmer's version string:
```
python -m libtoprammer.winusb_direct
```

### 2. No more `pkg_resources` (`libtoprammer/bitfile.py`, `toprammer-gui`)

Upstream used setuptools' `pkg_resources` to locate FPGA bitfiles and GUI icons. It's deprecated, prints a warning on every run, and was removed in setuptools 81. Both lookups now resolve paths relative to the `libtoprammer` package, with an `importlib.resources` fallback. They work from any working directory.

### 3. GAL support (`libtoprammer/chips/gal.py`)

New chip IDs: **`gal16v8`**, **`gal20v8`**, **`gal22v10`**.

#### How it works
Upstream toprammer needs a dedicated FPGA bitstream for each chip, and those are built with the long-obsolete Xilinx ISE. The GAL support needs **no new bitstream**. It loads toprammer's existing generic `unitest` FPGA configuration, which lets software drive and read every ZIF pin, and does the GAL serial **edit-mode** protocol in Python:

- **Programming voltage:** the TOP2049 VPP driver applies the edit voltage (12 V to read, 14–16.5 V to program) to pin 2.
- **Row address:** set on the RAG0–RAG5 pins. On the 22V10, it's instead shifted serially into SDIN after the data bits.
- **Data:** shifted in on SDIN and out on SDOUT, clocked by SCLK, with /STR as the strobe and P/V selecting program or verify.
- **Programming parameters:** read from the chip's own **PES** (electronic signature). The PES gives the manufacturer, the device type, and the programming voltage and pulse width:
  - **16V8/20V8:** algorithms 0–4 and 5;
  - **22V10:** its own algorithm table and 5;
  - **National parts:** adjusted voltage and erase times.
- **Safety limits:** the programming voltage is hard-capped at 16.5 V, the GAL's absolute maximum. The FPGA never drives the pin that carries VPP, VCC or GND.

The algorithm, row maps, configuration-bit order and PES decoding follow the publicly documented GAL programming method (GALBLAST / ATFblast / GALer / Afterburner).

| | GAL16V8 | GAL20V8 | GAL22V10 |
|---|---|---|---|
| Package / ZIF position | DIP20, pin 1 → ZIF 15 | DIP24, pin 1 → ZIF 13 | DIP24, pin 1 → ZIF 13 |
| Fuses | 2194 | 2706 | 5892 |
| Array | 32 rows × 64 bits | 40 × 64 | 44 × 132 |
| Row addressing | RAG pins | RAG pins | serial, after the data |
| Config | 82-bit ACW, row 60 | 82-bit ACW, row 60 | 20 S0/S1 bits, row 16 |

toprammer works out the ZIF position itself and prints it. Check the layout it shows before inserting the chip.

#### Two things learned on real hardware
- **Clock edge.** Some GAL16V8A parts sample SDIN on the **falling** SCLK edge. Changing SDIN and dropping SCLK in one register write shifted every row by one bit. The read-back matched a "shifted by one" model on all 2194 fuses. SDIN is now held stable across both clock edges, which works with either kind of part.
- **Open-drain SDOUT.** Early **GAL16V8A-15LP** parts have an open-drain SDOUT. Without pull-ups they read all `00`, so the PES looks blank. The ZIF pull-ups are therefore enabled by default; push-pull parts are unaffected.

#### Fuse files
- `--read-fuse` produces a **JEDEC** file, with the PES recorded in an `N` note line.
- `--write-fuse` accepts **JEDEC** files from GALasm, WinCUPL and similar tools, or a raw fuse bitmap.
- The `QF` fuse count is checked, so a file for the wrong device is rejected with a clear message.
- `G1` in a 16V8 or 20V8 file sets the security fuse **after** a successful verify.

A write always runs: read PES → erase → program array, UES and configuration → read back and verify every fuse → (security fuse, if requested).

#### Diagnostics
A failed verify prints:
- the counts of "wrote 1, read 0" and "wrote 0, read 1" mismatches;
- which area they're in (array, UES or config);
- the first 12 mismatching fuses, with row and bit.

It also saves `<chip>_verify_readback.jed`. `-C debug=1` additionally reads back and saves the fuse map after erasing.

#### Chip options (`-C name=value`)

| Option | Meaning |
|---|---|
| `probe=1` | With `-s`: tries 24 combinations of read voltage, strobe length, settle time and pull-ups, and prints the PES for each. This is the first thing to run on an unknown or problem chip. |
| `vpp=16.0` | Overrides the programming voltage from the PES (capped at 16.5 V). |
| `prog_ms=` / `erase_ms=` | Override the pulse widths from the PES. |
| `read_vpp=` | Edit voltage for reading (default 12 V). |
| `clk_delay_us=` | Extra delay per SCLK edge. |
| `read_strobe_us=`, `edit_settle_ms=`, `vcc_settle_ms=` | Read timing. |
| `pullups=0` | Disables the ZIF pull-ups (on by default). |
| `secure=1` / `secure=0` | Forces the security fuse on or off, whatever the file says. |
| `v8ab=1` | Forces the 16V8A/20V8A configuration bit order, for chips with an unreadable PES. |
| `debug=1` | Saves the fuse map after erase, plus the verify read-back. |
| `no_erase=1` | Skips the erase before programming. |

#### Limitations
- **GAL22V10 security fuse:** not supported. The published sources disagree on how to set it. A `G1` file still programs and verifies, then reports clearly that the chip is **not** secured.
- **Atmel ATF16V8 / ATF20V8 / ATF22V10:** detected from their PES and refused. They need a different algorithm.

### 3a. Bipolar PROM reading: MH74S571 / SN74S571 / DM74S571 (`libtoprammer/chips/prom74s571.py`)

Chip ID **`mh74s571`** reads (dumps) 512 × 4 tri-state bipolar PROMs: the Tesla MH74S571 and the TI/National 74S571. It runs at 5 V, through the same generic `unitest` FPGA configuration as the GAL support. The FPGA only drives the address and /CE pins and never the PROM's outputs.

- **Image format:** 512 bytes, one per address, with the 4 data bits in the low nibble. That's the usual format for 4-bit PROM dumps, for example in MAME. A blank PROM reads all 0.
- **Read check:** every read is done twice and compared, so a badly seated chip is reported instead of producing a silently wrong dump. The summary shows non-zero locations, blown fuses and a checksum.
- **Pinout** (TI SN74S571 / Tesla):

  | 1 A6 | 2 A5 | 3 A4 | 4 A3 | 5 A0 | 6 A1 | 7 A2 | 8 GND |
  |---|---|---|---|---|---|---|---|
  | **9 D3** | **10 D2** | **11 D1** | **12 D0** | **13 /CE** | **14 A8** | **15 A7** | **16 VCC** |

  Toprammer places PROM pin 1 at ZIF 17, with VCC on ZIF 32 and GND on ZIF 24.
- **Option `swap_a0_a2=1`:** exchanges A0 and A2. Some pinout transcriptions list pins 5–7 as A2, A1, A0. To be sure, compare a dump of a PROM whose contents are published.
- **Read only.** Blowing the fuses needs VCC raised to about 10.5 V at several hundred mA, and each data pin pulled hard to 0 V (up to about 150 mA). The TOP2049 can't do that: its VCC driver stops at 5 V, it has a single switchable ground, and the data pins are only reachable through FPGA logic outputs. Tesla parts also need a different procedure from National parts. Use a dedicated programmer for writing.

Status: tested against a pin-level 74S571 simulator (`tests/prom74s571_sim_test.py`), not yet on a real chip.

### 4. GUI changes (`toprammer-gui`)

- **GAL fuse view.** The "fuse bits" tab was built for AVR-style chips: it showed one checkbox per bit and refused any data over 32 bytes, so loading a GAL file failed. With a GAL selected, the tab now shows the fuse map as **address ranges and bit values**:
  - one product term per line (`0000-0043 PT0 1111…`);
  - then the configuration fields: XOR/AC1/PTD/SYN/AC0 for the V8 parts, S0/S1 for the 22V10;
  - the **UES decoded as text**;
  - a header with the device, the number of fuses set, the JEDEC checksum and the security flag.

  Other chips keep the original checkbox view.
- **JEDEC load and save.** "Load buffer" and "Save buffer" get a *JEDEC fuse file (\*.jed)* filter when a GAL is selected.
- **Fuse-level verify.** For GALs, "Verify" compares the actual fuses rather than file bytes. A `.jed` from GALasm and the chip's own readout have different headers but are the same fuse map. A mismatch reports something like "*1 of 5892 fuses differ, first at fuse 5*".
- **Verify shows which bytes are wrong.** When a verify of an EPROM, EEPROM, PROM or RAM image fails, the GUI switches to that buffer tab, highlights every differing byte in red (hex and ASCII columns), and moves the cursor to the first one. The console lists the count and the first addresses. Hover over a highlighted byte to get a pop-up with the chip value, the buffer value and their XOR in hex and binary, with the wrong bits marked (e.g. "*Differing bits: D1, D3*"). The same details appear in a line under the hex view for the byte under the mouse, or the byte at the cursor, so clicking or arrowing onto a red byte works too. Editing a byte to match removes its mark; loading new data or a passing verify clears them all.
- **Autorun no longer loops.** The Run button used to start over after the last step with "*Please insert a new chip…*". A new **"Repeat with next chip"** checkbox, unticked by default, controls this:
  - **unticked:** Run does the ticked steps once, with no prompts, and returns to the main window;
  - **ticked:** the original batch behaviour.
- **Load and Save target the right tab.** With the read-only "chip info" tab active (the default), "Load buffer" used to fail with "*cannot load data into the chip info buffer*". Load and Save now pick the chip's data buffer and switch to it:

  | Chip | Buffer |
  |---|---|
  | GAL | fuse bits |
  | EPROM | (E)EPROM memory |
  | Microcontroller | program memory |
  | SRAM | RAM |

  A data tab you've selected yourself is still respected.

### 5. Windows launchers
`toprammer`, `toprammer-gui` and `toprammer-layout` have no `.py` extension on purpose. That's the Unix convention for installed commands: `setup.py` installs them as `scripts`, and the `#!/usr/bin/env python3` line selects the interpreter. On Windows that convention doesn't apply, so two small launchers are included:

- **`toprammer-gui.pyw`**: double-click it to start the GUI with no console window.
- **`toprammer.py`**: `python toprammer.py -c gal16v8 …`, the same as `python toprammer …`.

---

## Installation (Windows 10/11 x64)

1. **Python.** Install **64-bit Python 3.9 or newer** from [python.org](https://www.python.org/). PyQt6 has no 32-bit Windows builds. Check with:
   ```
   python -c "import struct,sys; print(sys.version, struct.calcsize('P')*8, 'bit')"
   ```
2. **Python packages.** PyUSB isn't needed on Windows.
   ```
   python -m pip install PyQt6
   ```
3. **WinUSB driver for the programmer.** Use [Zadig](https://zadig.akeo.ie/):
   1. Plug in the programmer.
   2. Choose **Options → List All Devices**.
   3. Select the device with USB ID **2471 0853**.
   4. Pick **WinUSB**.
   5. Click **Install Driver** (or **Replace Driver**).

   If you also use TopWin with TopWD, it needs the same WinUSB driver, so this step only has to be done once.
4. **toprammer.** Clone this repository. Everything needed is in this `toprammer` folder, and nothing else has to be downloaded:
   ```
   git clone https://github.com/Kris-Sekula/TOP2048.git
   cd TOP2048\toprammer
   ```
   Files changed or added compared with upstream toprammer:
   ```
   toprammer-gui                         (changed)
   toprammer-gui.pyw, toprammer.py       (new: Windows launchers)
   libtoprammer/bitfile.py               (changed)
   libtoprammer/hardware_access_usb.py   (changed)
   libtoprammer/winusb_direct.py         (new)
   libtoprammer/chips/__init__.py        (changed: registers gal.py)
   libtoprammer/chips/gal.py             (new)
   examples/                             (new: GAL test designs)
   tests/gal_sim_test.py, tests/gui_*.py (new: offline tests)
   README.md                             (new: this file)
   ```
   `git log -- toprammer` shows the full upstream history, followed by these changes as separate commits.
5. **Check the connection.** Run this from the `toprammer` folder. TopWin must be closed, because only one program can open the programmer at a time.
   ```
   python -m libtoprammer.winusb_direct
   ```
   The output should end with `Version reply: top2049 ver1.08` (or similar).

**Linux and macOS:** nothing changes. PyUSB/libusb is still used, so follow upstream's instructions, run from this `toprammer` folder. The GAL support and GUI changes work there too.

---

## Usage

### GUI
1. Start the GUI: double-click `toprammer-gui.pyw`, or run `python toprammer-gui`.
2. **Select chip** → `gal16v8` / `gal20v8` / `gal22v10`.
3. **Load buffer** → your `.jed` file. It goes into the "fuse bits" tab automatically.
4. **Run**, with Erase, Write fuses and Verify ticked. For GALs the Erase step is optional, because Write always erases first.

### Command line
```bat
:: read the chip's signature (safe; also shows the programming voltage it will use)
python toprammer -c gal22v10 -s pes.bin

:: if the signature reads as all FF / 00: try a range of read settings
python toprammer -c gal22v10 -s pes.bin -C probe=1

:: program and verify a JEDEC file
python toprammer -c gal22v10 -F design.jed -I bin

:: read a chip to a JEDEC file
python toprammer -c gal22v10 -f readback.jed -O bin

:: erase
python toprammer -c gal22v10 -x

:: dump a MH74S571 / 74S571 bipolar PROM (512 bytes, data in the low nibble)
python toprammer -c mh74s571 -e dump.bin
```

### Example designs (`examples/`)
These are GALasm sources (`.pld`), JEDEC files (`.jed`) and pinouts (`.chp`) for a known-good test of each device. Each one contains AND, NAND, OR, NOR and XOR of A and B, a 2:1 MUX, an inverter and a 3-input majority gate. The 22V10 one adds a 2-bit counter on pin 1's clock with an asynchronous reset, which also exercises the register configuration.

| File | Expected fuse checksum |
|---|---|
| `test16v8.jed` | `431E` |
| `test20v8.jed` | `5070` |
| `test22v10.jed` | `9D01` |

---

## Tests (`tests/`)

Run these from the `toprammer` folder.

These run without a programmer:

```
python tests/gal_sim_test.py .                 # GAL algorithms vs. pin-level GAL simulators
python tests/prom74s571_sim_test.py .          # 74S571 PROM reader vs. a pin-level PROM model
python -I tests/gui_fuse_test.py "%CD%" examples
python -I tests/gui_autorun_test.py "%CD%"
python -I tests/gui_loadtarget_test.py "%CD%"
python -I tests/gui_verify_test.py "%CD%"
```

- **`gal_sim_test.py`** drives `gal.py` through a fake TOP2049 into simulated GAL16V8, GAL20V8 and GAL22V10 chips. Each is simulated twice: once as a chip that samples data on the rising clock edge, once on the falling edge.

  Each run checks the PES read, erase, programming, verify and the JEDEC round trip. The simulator also enforces the safety rules:
  - never program below 14 V;
  - never read at programming voltage;
  - the FPGA never drives the pin carrying VPP, VCC or GND.

  It reproduced the real off-by-one failure before that fix.
- **`gui_*_test.py`** run the real Qt widgets offscreen. They cover the GAL fuse tab and verify, Autorun single-run and repeat, the Load/Save buffer targets, and the highlighted bytes and hover pop-up after a failed verify.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `TOP programmer 2471:0853 not found` | Unplug and replug the programmer. Make sure **TopWin is closed**. Check Device Manager for the device under *Universal Serial Bus devices* with the WinUSB driver. |
| `Cannot open … with WinUSB` | Repeat the Zadig step. |
| `Init: Unexpected status (a)/(b)` at start-up | Harmless. This firmware doesn't answer one status query, so toprammer reads leftover bytes ("top2"). |
| GAL PES all `FF` or `00` | Check the chip's orientation and ZIF position. Run `-C probe=1`. Early 16V8A parts need the pull-ups, which are the default. |
| `Verify FAILED` | Rerun with `-C debug=1` and look at the mismatch summary and the saved `.jed` files. Try `-C clk_delay_us=8`. |
| `does not look like a GAL20V8 … it looks like a GAL22V10` | The wrong chip type is selected for the part in the socket. |
| `JEDEC file is for a device with 5892 fuses, GAL16V8 has 2194` | The `.jed` was assembled for a different device. |

---

## Credits

- **toprammer:** Michael Büsch and contributors. GPL v2+.
- GAL programming method and documentation: **GALBLAST** (Manfred Winterhoff), **ATFblast** (Bruce Abbott), **GALer / GALasm** (Christian Habermann; GALasm by Alessandro Zummo, maintained by David Hovemeyer), **Afterburner** (ole00 and contributors).
- **Zadig / libwdi:** Pete Batard.

## License

Same as toprammer: **GNU GPL version 2 or later**. See `COPYING` in the toprammer source.
