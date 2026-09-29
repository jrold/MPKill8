# Firmware patch status

## DO NOT FLASH THE FIRST MPKill8 BUILD

The first hardware test failed.

Observed on the real PID `0x1049` MPK Mini MK3:

- physical K8 still generated the same ghost activity;
- normal QLINK behavior was also altered.

The old patch changed firmware offset `0x0e5ec` from `cmp r0,#8` to
`cmp r0,#7`. That patch is now **rejected and permanently disabled**.

## What the failure proved

Re-analysis of the exact stock v1.26 image
(`b2a8c30125d8a59...e91b7392`) found two separate eight-control loops.

### Rejected loop

- function starts near `0x0800e5d4`
- loop bound at firmware offset `0x0e5ec`
- first hardware build changed this loop
- this loop is **not** the live QLINK program-record dispatch loop

Reconstructing the exact failed image proves the true runtime QLINK loop still
has a bound of eight.

### Live QLINK runtime loop

The live routine starts at `0x08014912`.

Its loop bound is at firmware offset:

`0x14932`

The routine is tied directly to the known MPK program format:

- it uses a stride of `0x14` / **20 bytes** per knob record;
- it reads record fields corresponding to mode / CC / min / max;
- its MIDI path calls the internal control-event dispatcher using the CC read
  from the selected program record;
- its UI path calculates `program_base + index*20 + 0x58`.
  The first knob record starts at `+0x54`, so `+0x58` is exactly
  **record + 4 = name[16]**.

This is the first routine found that directly joins all three pieces:

1. raw knob index,
2. the known 20-byte SysEx knob record,
3. both MIDI and OLED/UI dispatch.

## Safety gate

No replacement firmware is approved yet.

`tools/firmware_analysis.py` performs binary-level structural checks against
the exact stock image.  The regression suite also reconstructs the failed
hardware build and asserts that it left the true runtime loop at eight.

A future candidate must satisfy all of these before any installer is enabled:

1. the rejected `0x0e5ec` loop remains byte-for-byte stock;
2. K1-K7 retain the original program-record/MIDI/UI path;
3. record 8 / K8 cannot enter the live dispatch path;
4. only the intended code byte(s) and firmware checksum may differ;
5. exact-stock integration tests pass against the known v1.26 SHA-256;
6. the custom installer remains disabled until those checks are reviewed.

The first failed firmware must not be redistributed or flashed again.
