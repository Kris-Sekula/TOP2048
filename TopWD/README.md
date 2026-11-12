# TopWD — TopWin for the TOP2049 programmer on 64-bit Windows

Lets you use **TopWin** with the **TOP2049** USB universal programmer (USB ID `VID_2471 & PID_0853`) on **64-bit Windows 10/11**. Other TOP-series models (TOP853, TOP2004) also use TopWin and may work too, but they're untested and may have different USB IDs. You don't need the original Jungo **WinDriver** kernel driver (`windrvr6.sys`), test-signing mode or any changes to Secure Boot.

TopWD is a small 32-bit DLL that you drop next to `TopWinEn.exe`. It **replaces the WinDriver 6.03 kernel driver in user mode** and sends the USB traffic through Microsoft's built-in, signed **WinUSB** driver.

> Tested with TopWinEn 3.x on Windows 11 x64.
>
> Prefer open-source software? The [`toprammer`](../toprammer/) folder of this repository has toprammer with Windows WinUSB support and GAL16V8/20V8/22V10 programming. It uses the same WinUSB driver, so TopWD and toprammer can share one Zadig install (close one before starting the other). The programmer is detected, the self-test passes, and EPROMs program and verify correctly.

---

## Why it's needed

TopWin was written around 2004. It talks to the programmer through Jungo WinDriver 6.03, and the driver in the installer is a 32-bit (x86) kernel driver. 64-bit Windows can only load 64-bit kernel drivers, so:

- the driver install fails, and
- TopWin reports that the programmer isn't connected.

Editing the INF file or switching on test-signing mode doesn't help, because the driver binary itself can't run on x64.

## How it works

TopWinEn.exe has WinDriver 6.03's user-mode library built into it. That library uses the kernel driver only for these calls:

```
CreateFileA("\\.\WINDRVR6")  +  DeviceIoControl(0x9538xxxx, ...)
```

The kernel driver adds no logic of its own for the programmer; it just passes USB requests through. TopWD takes its place:

1. **Loads in place of `version.dll`.** TopWin imports `version.dll`, and Windows loads a DLL with that name from the application folder first. TopWD passes every real `version.dll` call through to the system copy.
2. **Patches TopWin's import table** for `CreateFileA`, `DeviceIoControl` and `CloseHandle`.
3. **Answers the WinDriver requests itself** (version check, license, plug-and-play events, device descriptors, set interface, USB transfers, pipe reset/abort and so on).
4. **Does the actual USB I/O through WinUSB.**

`TopWinEn.exe` is **not modified**.

```
TopWinEn.exe ──(WinDriver 6.03 user lib)──► CreateFile/DeviceIoControl
                                               │  (hooked)
                                               ▼
                                         TopWD (version.dll)
                                               │
                                               ▼
                                      WinUSB (Microsoft, signed)
                                               │
                                               ▼
                                     TOP programmer (2471:0853)
```

---

## Installation

1. **Install TopWin** with the original installer. Ignore or cancel any errors from its driver install step.
2. **Install WinUSB for the programmer** with [Zadig](https://zadig.akeo.ie/):
   - Plug in the programmer.
   - Choose **Options → List All Devices**.
   - Select the device with USB ID **2471 0853**. It may show as "TOP Programmer" or as an unknown device.
   - Set the driver to **WinUSB**, then click **Install Driver** (or **Replace Driver**).
3. **Copy `version.dll`** from the [Releases](https://github.com/Kris-Sekula/TOP2049/releases) page into the TopWin folder, next to `TopWinEn.exe`.
4. **Start `TopWinEn.exe`** as usual.

Don't run `LoadDrv.exe` ("Reload USB driver"), because it tries to install the old driver. To uninstall TopWD, delete `version.dll` from the TopWin folder.

### Windows Security / antivirus may delete `version.dll`

Windows Security (Microsoft Defender) or other antivirus software may quarantine or delete `version.dll` without telling you. Sometimes this happens right after you copy it into the folder; sometimes it happens the first time TopWin loads it. Security software is suspicious of this kind of DLL for two reasons:

- A DLL named after a system DLL that sits in an application folder is a classic **"DLL hijacking"** pattern, which malware uses too.
- TopWD **patches the import table** of the program that loads it, which antivirus heuristics also watch for.

The DLL does nothing beyond what this README and the source describe. The full source is in this repository, so you can check it and build it yourself.

If TopWin says the programmer isn't connected again and there's no `TopWD.log`, check whether the DLL was removed:

1. Open **Windows Security → Virus & threat protection → Protection history**.
2. If `version.dll` is listed as quarantined or removed, choose **Actions → Restore** (or **Allow on device**).
3. To stop it happening again, add an exclusion for the TopWin folder: **Virus & threat protection → Manage settings → Exclusions → Add or remove exclusions → Add an exclusion → Folder**, then select the TopWin folder, for example `C:\Top\topwinen3`.
4. Copy `version.dll` back into the folder if it isn't there any more.

Building the DLL yourself from source (see [Building from source](#building-from-source)) produces a different file, which antivirus software may treat differently from the release build.

---

## Configuration (optional)

You set these as environment variables before starting TopWin. For example, from a command prompt:

```bat
set TOPWD_LOG=1
"C:\Top\TopWinEn.exe"
```

| Variable | Default | Meaning |
|---|---|---|
| `TOPWD_CHUNK` | `4096` | Largest number of bytes sent to WinUSB in one call. Large transfers are split into pieces of this size and each piece gets TopWin's timeout (see below). `0` turns splitting off. |
| `TOPWD_PACE_US` | `1000` | Minimum gap between USB transfers, in microseconds. This matches the timing of the old USB 1.1 host controllers. `0` turns it off. |
| `TOPWD_LOG` | off | Logs every USB transfer with a hex dump. It's slow, so use it only when debugging. |
| `TOPWD_GHOSTING` | off | Set to `1` to keep Windows' normal "Not Responding" window handling (see below). |
| `TOPWD_SIM` | off | Pretends a programmer is connected, for testing without hardware. |

---

## Troubleshooting

TopWD writes **`TopWD.log`** next to `TopWinEn.exe`. If that folder can't be written to, the log goes to `%TEMP%\TopWD.log` instead. The log is overwritten every time TopWin starts, so copy it straight after a failure.

| Symptom | Cause / fix |
|---|---|
| No `TopWD.log` is created / the programmer suddenly stops being detected | `version.dll` isn't next to `TopWinEn.exe`, or Windows Security / antivirus removed it. Check **Protection history**; see [Windows Security / antivirus may delete version.dll](#windows-security--antivirus-may-delete-versiondll). |
| Log says `WinUsb_Initialize failed` or `could not open the programmer` | WinUSB isn't installed for the device. Repeat the Zadig step. This can also happen after a Windows Update. |
| Log shows `write ep02 failed … err 121 (timeout)` | Try a smaller piece size: `set TOPWD_CHUNK=2048`. |
| Self-test reports `Error! Number …` | Make sure the ZIF socket is empty during the self-test. |

When a transfer fails, or the device disappears, TopWD always writes the **last 48 USB transfers** to the log: direction, size, bytes moved, time taken, timeout and Windows error code. Include that section when you report a problem.

### Decoding TopWin's self-test error number

TopWin shows self-test errors as `Error! Number <n>`, where `n = r + (r << 16) + (test << 8) + detail`. Here `r` is a random number from 0 to 99, added to make the number look obscure. Convert `n` to hex as `0xRRTTxx`:

- `RR` is `r`
- `TT` is the test number
- `detail` is `xx − r`

For example, `1968188 = 0x1E083C` gives `r = 0x1E`, test `8` (pin-driver test) and detail `0x3C − 0x1E = 30` (socket pin 30).

---

## Problems found along the way

**1. Programming failed at the same address every time** (`000384: Error! (file=0b, chip=ff)`)
TopWin writes each block as one bulk write of about 10 KB with a **1 s timeout**. The programmer only accepts data as fast as it burns the chip, roughly 9 KB/s, so the whole write takes longer than 1 s. On XP, WinDriver split large transfers into 4 KB pieces and applied the timeout to each piece, so it never ran out. WinUSB applies the timeout to the whole transfer. TopWD now splits transfers the same way (`TOPWD_CHUNK`).

**2. Progress bar froze at about 30%**
TopWin programs on its window (GUI) thread and redraws the progress bar directly. After 5 s without reading its message queue, Windows swaps in a frozen "ghost" copy of the window. TopWD calls `DisableProcessWindowsGhosting()` for TopWin's process.

**3. False "device removed" in the middle of a job**
TopWD checks for plugging and unplugging every second. It now skips that check while USB transfers are running, and needs to miss the device three scans in a row before treating it as unplugged.

---

## Building from source

TopWin is a **32-bit** program, so TopWD must be built as a **32-bit (x86) DLL**. A 64-bit build won't load into TopWin. TopWD is a single C file with no third-party dependencies, and builds with **MinGW-w64** (GCC). It only links against Windows' own libraries: `setupapi`, `ole32` and `advapi32`. `winusb.dll` is loaded at run time.

### Source files

| File | Contents |
|---|---|
| `topwd.c` | WinDriver IOCTL handling, WinUSB code, plug/unplug detection, `version.dll` pass-through, import hooks, diagnostics |
| `windrvr6_compat.h` | WinDriver 6.03 structure layouts and IOCTL codes, as found in TopWinEn.exe, with compile-time size and offset checks |
| `build.sh` | Build script. The compiler and strip tool can be overridden with `CC` and `STRIP`. |

### Option A: Windows with MSYS2

1. Install [MSYS2](https://www.msys2.org/).
2. From the Start menu, open the **"MSYS2 MINGW32"** shell. It must be MINGW32, not UCRT64, CLANG64 or MINGW64, because those build 64-bit binaries.
3. Install the 32-bit toolchain:
   ```sh
   pacman -S --needed mingw-w64-i686-gcc git
   ```
4. Get the source and build:
   ```sh
   git clone https://github.com/Kris-Sekula/TOP2049.git
   cd TOP2049/TopWD
   CC=gcc STRIP=strip ./build.sh
   ```
   In the MINGW32 shell, `gcc` is already the 32-bit compiler, which is why `CC=gcc` is set.

### Option B: Linux or WSL (cross-compiling)

Debian/Ubuntu:

```sh
sudo apt install gcc-mingw-w64-i686 git
git clone https://github.com/Kris-Sekula/TOP2049.git
cd TOP2049/TopWD
./build.sh
```

Fedora: `sudo dnf install mingw32-gcc`. Arch: `sudo pacman -S mingw-w64-gcc`. Then run `./build.sh`.

### Building without the script

```sh
i686-w64-mingw32-gcc -O2 -Wall -Wno-unused-function -shared -static-libgcc \
    -o version.dll topwd.c \
    -Wl,--kill-at -Wl,--enable-stdcall-fixup \
    -lsetupapi -lole32 -ladvapi32
i686-w64-mingw32-strip version.dll
```

What the less obvious options do:

- **`-shared`** builds a DLL.
- **`-static-libgcc`** builds the GCC runtime into the DLL, so you don't need to copy `libgcc_s_dw2-1.dll` alongside it.
- **`-Wl,--kill-at`** exports plain names (`GetFileVersionInfoA`) instead of decorated stdcall names (`GetFileVersionInfoA@16`). Without it, TopWin can't find the functions it imports and won't start.
- **`-lsetupapi -lole32 -ladvapi32`** link the libraries used for finding devices (SetupAPI), reading the WinUSB interface GUID that Zadig writes, and accessing the registry.

### Checking the build

The result must be a 32-bit DLL called exactly `version.dll`:

```sh
file version.dll
# version.dll: PE32 executable (DLL) ... Intel 80386 ...   <- PE32 / 80386 = 32-bit (correct)
#                PE32+ ... x86-64                           <- 64-bit (wrong toolchain)
```

It must export all 17 `version.dll` functions under their plain names:

```sh
i686-w64-mingw32-objdump -p version.dll | sed -n '/Ordinal\/Name Pointer/,/^$/p'
#   GetFileVersionInfoA, GetFileVersionInfoByHandle, GetFileVersionInfoExA/W,
#   GetFileVersionInfoSizeA/W, GetFileVersionInfoSizeExA/W, GetFileVersionInfoW,
#   VerFindFileA/W, VerInstallFileA/W, VerLanguageNameA/W, VerQueryValueA/W
```

If the names end in `@4`, `@16` and so on, the `--kill-at` option was left out.

### Testing without a programmer

The simulation mode adds a fake programmer, so you can check that TopWin loads the DLL and reaches the "device attached" stage:

```bat
set TOPWD_SIM=1
set TOPWD_LOG=1
"C:\Top\TopWinEn.exe"
```

`TopWD.log` should show `EVENT_REGISTER`, `EVENT_PULL -> INSERT`, `GET_DEVICE_DATA` and `SET_INTERFACE`, followed by TopWin's first commands to the programmer. The fake device replies with zeros, so TopWin will then report that it can't talk to the programmer. That's expected.

The same test also works on Linux under Wine. Wine's own `version.dll` has to be overridden with `WINEDLLOVERRIDES="version=n,b"`:

```sh
TOPWD_SIM=1 TOPWD_LOG=1 WINEDLLOVERRIDES="version=n,b" wine TopWinEn.exe
```

### Notes

- **Microsoft Visual C++** hasn't been tested. It would need a `.def` file to export the plain names that `--kill-at` gives with MinGW, and must target x86 (Win32).
- A DLL you build yourself is a different file from the release build, so Windows Security may treat it differently. See [Windows Security / antivirus may delete version.dll](#windows-security--antivirus-may-delete-versiondll).
- The version number is `TOPWD_VERSION` near the top of `topwd.c`. It's written to the first line of `TopWD.log`.

---

## Technical reference

IOCTL code = `CTL_CODE(0x9538, func, METHOD_NEITHER, FILE_ANY_ACCESS)`. The 4-byte output buffer receives the WinDriver status code.

| Func | Name | TopWD's handling |
|---|---|---|
| `0x910` | `VERSION` | Returns **603**. TopWin requires exactly 603. |
| `0x952` | `LICENSE` | Accepted. |
| `0x964` | `DEBUG_ADD` | Ignored. With `TOPWD_LOG` set, the message is logged. |
| `0x986` | `EVENT_REGISTER` (v6) | Registers a match table and immediately reports any programmer already plugged in. |
| `0x91e` / `0x91f` / `0x94b` | `INT_ENABLE` / `INT_DISABLE` / `INT_WAIT` | WinDriver's plug-and-play event thread. `INT_WAIT` blocks until an event or until it's disabled. |
| `0x988` / `0x989` / `0x987` | `EVENT_PULL` / `EVENT_SEND` / `EVENT_UNREGISTER` | Insert/remove events, with `dwUniqueID` identifying the device. |
| `0x980` | `USB_GET_DEVICE_DATA` (v6) | Builds the `WDU_DEVICE` descriptor tree in the caller's buffer, from WinUSB descriptors. |
| `0x981` | `USB_SET_INTERFACE` | `WinUsb_SetCurrentAlternateSetting` |
| `0x983` | `USB_TRANSFER` | Control transfers (pipe 0) and bulk/interrupt transfers. Bulk is split into pieces of `TOPWD_CHUNK` bytes. |
| `0x982` / `0x985` | `USB_RESET_PIPE` / `USB_HALT_TRANSFER` | `WinUsb_ResetPipe` / `WinUsb_AbortPipe` |
| `0x98a` / `0x98b` | `USB_WAKEUP` / `USB_RESET_DEVICE` | No-op. |

The programmer is USB 1.0 / full speed, with one interface. TopWin uses bulk endpoint `0x02` (OUT) and `0x82` (IN), with a 64-byte maximum packet size.

---

## Credits

- WinDriver structure layouts were checked against **usb-driver / libusb-driver** by Michael Gernoth, a Linux user-space replacement for windrvr6 used with Xilinx tools.
- [Zadig](https://zadig.akeo.ie/) / libwdi by Pete Batard, for installing WinUSB.
- [Toprammer](https://bues.ch/h/toprammer) by Michael Büsch, open-source TOP2049 software and protocol documentation.

## Disclaimer

This is an independent project and isn't affiliated with Jungo or with the maker of the TOP programmers or TopWin. This repository doesn't include TopWin, WinDriver or any of their binaries; you need your own copy of TopWin. Use at your own risk.

## Version history

| Version | Change |
|---|---|
| 1.0 | WinDriver 6.03 emulation over WinUSB, `version.dll` proxy, plug-and-play events. |
| 1.1 | Window ghosting disabled; no bus scanning during transfers; device removal needs 3 missed scans; always-on transfer history in the log. |
| 1.2 | Optional pacing between USB transfers (`TOPWD_PACE_US`). |
| 1.3 | Large bulk transfers split into 4 KB pieces with a per-piece timeout, as WinDriver did on XP. This fixed programming stopping at the same address. |

## License

MIT. See [LICENSE](LICENSE).
