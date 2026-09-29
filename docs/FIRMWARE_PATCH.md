# Firmware patch: physical K8 kill

## Confirmed target

The user's physical MPK Mini MK3 enumerates as:

- USB VID: `0x09e8`
- USB PID: `0x1049`

That selects updater **Region 3**, v1.26:

- EXE offset: `0x28c144`
- length: `0x20000`
- SHA-256: `b2a8c30125d8d93fae59b8726140c8887ca806c16808f8cbdb753813e91b7392`

The PID `0x1049` firmware uses ARMv7-M/Thumb-2 instructions and an STM32F1-style peripheral map (GPIOA `0x40010800`, GPIOB `0x40010c00`, ADC1 `0x40012400`, RCC `0x40021000`). This is not the Cortex-M0 instruction set used by the older service-manual STM32F070 design.

## Scan path recovered

### Mux selector

Function `0x0801213e` accepts selector values 0..7 and drives GPIOB bits 0,1,2.

This is the 3-bit address for the parallel 74HC4051 muxes.

### ADC scan

Function `0x08011f42` rotates the mux selector modulo 8 and processes five ADC conversions. The first three are arrays of eight mux slots:

1. encoder phase A
2. encoder phase B
3. pad pressure

Therefore globally skipping mux Y4 would be wrong: it would also suppress the pad occupying Y4 on the pad mux.

### Encoder logical-to-mux map

The encoder routine uses two lookup tables:

```
phase A: 03 00 01 02 05 07 06 04
phase B: 0b 08 09 0a 0d 0f 0e 0c
```

Subtracting 8 from the phase-B indices yields the identical mux mapping:

```
logical knob 0..7 -> mux channel
K1 -> 3
K2 -> 0
K3 -> 1
K4 -> 2
K5 -> 5
K6 -> 7
K7 -> 6
K8 -> 4
```

That matches the service schematic's 4051 wiring, where P8PHA/P8PHB are on Y4.

## Encoder event routine

Function `0x0800e5d4` loops logical knob indices 0..7. For each knob it:

1. retrieves filtered phase A/B values;
2. compares against previous phase values;
3. computes movement/direction;
4. updates the knob's 0..127 state;
5. emits the control event via `0x0800cb9a` with the logical knob index.

The loop head is:

```asm
0800e5e8  ldrb.w r0, [r9]
0800e5ec  cmp     r0, #8
0800e5ee  bge.w   0800e79a
```

Physical K8 is logical index 7.

## Patch

Change:

```
file offset 0x0e5ec
08 28    cmp r0,#8
```

to:

```
07 28    cmp r0,#7
```

The routine now processes indices 0..6 and exits before K8.

This is deliberately downstream of the shared mux/ADC scanner but upstream of K8 movement/event generation. It preserves the pad sharing mux Y4 while preventing K8 from generating the event that drives MIDI, MIDI learn, and OLED focus.

## Firmware checksum

The final two bytes of the 128 KiB image are a big-endian 16-bit byte sum of offsets `0x00000..0x1fffd`.

Stock:

```
sum = 0xe2ff
stored at 0x1fffe = e2 ff
```

After the one-byte logic patch:

```
sum = 0xe2fe
stored at 0x1fffe = e2 fe
```

Only two bytes in the complete firmware image change:

```
0x0e5ec: 08 -> 07
0x1ffff: ff -> fe
```

Patched firmware SHA-256:

`b7121c28293201a031200b56058fc5bee1fdbfdf053582d99e1fbea8029f3087`

## Building a patched updater

Do not commit Akai firmware/updater binaries.

With the official v1.26 Windows updater already under `vendor/`:

```bash
python tools/build_mpkill8_updater.py
```

This verifies the exact stock Region 3 hash, applies the two-byte firmware delta, recalculates/verifies the firmware checksum, and writes a new updater under ignored `dist/`.

The official ZIP is never modified in place.
