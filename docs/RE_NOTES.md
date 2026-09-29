# Reverse-engineering notes

## Goal

K8 must be **absent from behavior**, not merely mapped to a harmless CC:

- no MIDI output caused by K8;
- no OLED parameter popup/update caused by K8;
- no effect on the other seven knobs or normal MPK behavior.

## Device

Akai MPK Mini MK3.

### MCU

Service documentation identifies:

- STM32F070RBT6
- Cortex-M0
- 128 KiB flash
- 16 KiB SRAM
- LQFP64

### Knob hardware

The schematic shows eight knob signals (`P1PHB..P8PHB`) feeding a CD74HC4051 8:1 analog multiplexer.

K8 is:

```
P8PHB -> 74HC4051 Y4
```

The mux select lines are `ADDR0..ADDR2`; its common output is `VR-OUT2`.

This matters because K8 is not a quadrature encoder with two digital edges. The firmware is scanning an analog mux channel and deciding whether the resulting control value changed.

## Program SysEx

Confirmed by independent reverse engineering and the open-source `sysex-controls` implementation.

Manufacturer:

```
0x47  Akai
```

Model:

```
0x49  MPK Mini MK3
```

Host -> device uses device byte `0x7f`.

### Query program

```
F0 47 7F 49 66 00 01 PP F7
```

### Program response

```
F0 47 ?? 49 67 LL LL PP <payload> F7
```

### Write program

```
F0 47 7F 49 64 LL LL PP <payload> F7
```

Length is 14-bit (`MSB << 7 | LSB`) and includes the program-id byte.

### Select program

```
F0 47 7F 49 62 00 01 PP F7
```

### Program IDs

- `0`: volatile RAM program
- `1..8`: stored programs

## K8 program record

Knob records are 20 bytes each.

| Knob | Payload offset |
|---|---:|
| K1 | `0x54` |
| K2 | `0x68` |
| K3 | `0x7c` |
| K4 | `0x90` |
| K5 | `0xa4` |
| K6 | `0xb8` |
| K7 | `0xcc` |
| **K8** | **`0xe0`** |

Record layout:

```
+0  mode       0 Absolute, 1 Relative
+1  CC
+2  min
+3  max
+4  name[16]
```

There is no documented/program-editor OFF value.

## Phase 1 hypothesis

Test undocumented values (`2`, `127`, etc.) in K8's mode byte in Program 0 only.

Possible firmware implementations:

### Best case

```c
switch (mode) {
case 0:
    handle_absolute();
    break;
case 1:
    handle_relative();
    break;
}
```

An unknown mode can fall through and suppress the entire K8 event path, potentially including OLED UI.

### Less useful case

```c
if (mode == 0)
    handle_absolute();
else
    handle_relative();
```

Then every nonzero value behaves as Relative and we need a firmware patch.

The RAM read-back in `mpkill8.py probe` also tells us whether firmware validates/normalizes the mode before use.

## Phase 2: firmware extraction

Official updater as of 2026-09-29: **v1.26**.

Windows package:

```
https://cdn.inmusicbrands.com/akai/mpk3mini/1_26/MPKmini3_Updater_v1.26_WIN.zip
```

Run:

```bash
python tools/scan_updater.py MPKmini3_Updater_v1.26_WIN.zip --extract-dir dumps
```

The scanner looks for a Cortex-M vector table whose initial MSP is in the STM32F070RB's 16 KiB SRAM and whose reset/exception handlers point into the device's 128 KiB flash.

If no raw image is found, likely next approaches:

1. inspect PE resources and embedded compressed blobs;
2. trace updater file/resource access;
3. capture updater USB traffic in update mode;
4. identify update transport/checksum;
5. reconstruct the payload from USB transfers.

## Phase 3: static patch

Once stock firmware is available, load it in Ghidra at:

```
0x08000000
```

Likely search anchors:

- GPIO writes for the three mux address lines;
- ADC conversion/read loop;
- loop count / channel index of eight;
- control-change dispatch;
- OLED control-name rendering;
- references to the eight 20-byte program records.

Preferred patch location is **before both UI and MIDI dispatch**, ideally directly after K8's ADC scan/debounce step.

Conceptual patch:

```c
if (knob_index == 7)
    continue;
```

That preserves all normal behavior while making K8 physically irrelevant.

## Sources

- Akai service schematic/manual:
  https://www.manualslib.com/manual/2910998/Akai-Mpk-Mini-Mk3.html?page=34
- Akai firmware update/recovery:
  https://support.akaipro.com/en/support/solutions/articles/69000798892-akai-pro-mpk-mini-mk3-upgrade-v-error-and-installing-the-firmware
- Joonas Pihlajamaa MK3 SysEx RE:
  https://joonas.fi/2021/02/reverse-engineering-midi-devices-akai-mpk-mini-mk3/
- sysex-controls:
  https://github.com/soyersoyer/sysex-controls
