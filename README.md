# MPKill8

Disable the physically broken **K8** knob on an Akai MPK Mini MK3 so it is completely ignored:

- no CC77
- no QLINK4 OLED focus
- no MIDI-learn hijacking
- no internal K8 movement event

K1-K7 and the pads continue to use their original firmware paths.

## Install

### macOS — primary workflow

The target unit was identified as:

- USB VID `0x09e8`
- USB PID `0x1049`
- Akai firmware v1.26, updater Region 3

On the Mac with the MPK connected normally over USB:

```bash
git pull
python3 install.py
```

That command:

1. verifies the connected controller is the supported **VID 09E8 / PID 1049** revision;
2. downloads Akai's official **macOS v1.26** updater if it is not already cached;
3. extracts the official `.app`;
4. searches the app bundle for the exact stock Region-3 firmware SHA-256;
5. refuses to patch unless the embedded 128 KiB image matches the verified stock hash;
6. applies the two-byte MPKill8 patch;
7. verifies the exact patched firmware SHA-256;
8. ad-hoc re-signs the modified app locally;
9. launches the patched updater.

When the Akai updater requires firmware-update mode, reconnect the MPK while holding **BANK + PROG SELECT**.

The patched updater is created under:

```
dist/MPKmini3_Updater_v1.26_MPKILL8.app
```

The untouched Akai download remains cached under ignored `vendor/`.

#### Restore stock on macOS

```bash
python3 restore_stock.py
```

That extracts and launches an untouched copy of Akai's official macOS v1.26 updater.

### Windows — optional

A Windows workflow remains available:

```bat
git pull
install.bat
```

and stock recovery:

```bat
restore_stock.bat
```

## Confirmed hardware / firmware target

The user's actual controller enumerates as:

- USB VID: `0x09e8`
- USB PID: `0x1049`

The correct Akai v1.26 firmware image is updater **Region 3**:

- EXE offset: `0x28c144`
- image size: `0x20000` (128 KiB)
- stock SHA-256: `b2a8c30125d8d93fae59b8726140c8887ca806c16808f8cbdb753813e91b7392`

The PID `0x1049` firmware uses ARMv7-M/Thumb-2 and an STM32F1-style peripheral map. The older service manual documents an STM32F070-based revision, so the manual cannot be treated as the CPU definition for this unit.

## Why the preset/SysEx approach was rejected

K8 is program record 8, CC77, display name QLINK4.

A RAM-only test set K8's undocumented mode byte to `2`. During a stress test while moving healthy knobs, the broken K8 generated **1,255 CC77 events**, overwhelmingly value `1`, and the OLED flickered between the intended knob and QLINK4.

Therefore preset configuration cannot make K8 truly dead.

## Firmware path recovered

The firmware scans a 3-bit 74HC4051 mux with selector values 0..7.

The low-level ADC scanner processes three parallel muxed channels:

1. encoder phase A
2. encoder phase B
3. pad pressure

Because the pad mux shares the same selector, globally skipping mux Y4 would also break the pad on Y4. The kill therefore belongs in the **encoder-only** path.

The encoder routine at `0x0800e5d4` loops logical knob indices 0..7.

Its lookup tables map:

```
K1 -> mux 3
K2 -> mux 0
K3 -> mux 1
K4 -> mux 2
K5 -> mux 5
K6 -> mux 7
K7 -> mux 6
K8 -> mux 4
```

The loop head is:

```asm
0800e5e8  ldrb.w r0, [r9]
0800e5ec  cmp     r0, #8
0800e5ee  bge.w   0800e79a
```

## MPKill8 patch

Change one instruction byte:

```
firmware offset 0x0e5ec
08 28    cmp r0,#8
          ↓
07 28    cmp r0,#7
```

Now the encoder routine processes K1-K7 and exits before physical K8.

Akai's firmware checksum is a big-endian 16-bit sum of all bytes before the final two checksum bytes. Recomputing it changes one more byte:

```
0x0e5ec: 08 -> 07
0x1ffff: ff -> fe
```

Those are the **only two bytes** changed in the 128 KiB firmware.

Patched firmware SHA-256:

`b7121c28293201a031200b56058fc5bee1fdbfdf053582d99e1fbea8029f3087`

Full reverse-engineering notes: [docs/FIRMWARE_PATCH.md](docs/FIRMWARE_PATCH.md)

## Build the patched updater

Create the virtual environment if needed:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Download/scan Akai's official v1.26 updater:

```bash
python tools/fetch_updater.py win
```

Confirm the connected controller family on macOS:

```bash
python tools/detect_usb_identity.py
```

For this project it must report:

```
VID 0x09e8, PID 0x1049
```

Build a patched copy of the Windows updater:

```bash
python tools/build_mpkill8_updater.py
```

Outputs are written under ignored `dist/`:

```
dist/MPKmini3_Updater_v1.26_MPKILL8.exe
dist/MPKmini3_Updater_v1.26_MPKILL8_WIN.zip
```

The original Akai ZIP is never modified.

## Recovery / flashing caution

This is a custom firmware flash. Keep the untouched official v1.26 updater available before testing the patched updater.

Akai's documented recovery/update mode is entered by holding **BANK + PROG SELECT** while connecting USB.

The patch is intentionally minimal: one encoder-loop immediate plus the corresponding firmware-checksum byte. Nevertheless, flashing modified firmware always carries some risk.

## Utility commands

List MIDI ports:

```bash
python mpkill8.py ports
```

Inspect a program:

```bash
python mpkill8.py inspect --source 1
```

Sniff MIDI:

```bash
python mpkill8.py sniff --all-ports --seconds 10
```

The old undocumented-mode `probe` remains in the tool for reproducibility, but it is no longer the chosen solution.

## Sources / prior work

- Akai MPK Mini MK3 service schematic/manual
- Akai firmware recovery/update instructions
- Joonas Pihlajamaa's MPK Mini MK3 SysEx reverse engineering
- sysex-controls MK3 implementation
