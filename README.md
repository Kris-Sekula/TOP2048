# TOP2049

Software for the **TOP2049** USB universal programmer (USB ID `VID_2471 PID_0853`)
on modern 64-bit Windows. Everything here was tested with a TOP2049. Other TOP-series
models may use different USB IDs, and they're untested.

| Folder | Contents |
|---|---|
| [`toprammer/`](toprammer/) | [toprammer](https://github.com/mbuesch/toprammer), the open-source programmer software by Michael Büsch, with a direct WinUSB backend for Windows 10/11 x64, support for more chips (GAL16V8 / GAL20V8 / GAL22V10 programming, Tesla MH74S571 PROM reading, Intel 8755 / 8755A / 8355 ROM reading and I/O port test, TMS4044 / 2147 4K × 1 SRAM test), and GUI improvements such as highlighted verify mismatches. See [`toprammer/README.md`](toprammer/README.md). |
| [`TopWD/`](TopWD/) | **TopWD**: a drop-in `version.dll` that lets the original **TopWin** software run on 64-bit Windows 10/11 without the old Jungo `windrvr6.sys` kernel driver. It emulates WinDriver 6.03 in user mode over WinUSB. See [`TopWD/README.md`](TopWD/README.md); the prebuilt DLL is on the [Releases](https://github.com/Kris-Sekula/TOP2049/releases) page. |

The programmer needs Microsoft's WinUSB driver, which you install with [Zadig](https://zadig.akeo.ie/).
Both folders use the same driver, so it only has to be installed once. See the installation section of either README.

Licences: toprammer is GNU GPL v2 or later ([`toprammer/COPYING`](toprammer/COPYING)); TopWD is MIT ([`TopWD/LICENSE`](TopWD/LICENSE)).
