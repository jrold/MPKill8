# K8 kill target

## What the hardware tells us

The MPK Mini MK3 service schematic makes the knob scan architecture unusually clear.

The eight endless knobs are represented as two phase signals per control:

- K1: P1PHA / P1PHB
- ...
- **K8: P8PHA / P8PHB**

Those sixteen phase signals are split across two CD74HC4051 8:1 analog multiplexers:

- IC5 -> phase A -> `VR-OUT1` -> STM32 `PA0`
- IC6 -> phase B -> `VR-OUT2` -> STM32 `PA1`

For **K8**, both muxes use input **Y4**:

```
P8PHA -> IC5 Y4 -> VR-OUT1 -> PA0
P8PHB -> IC6 Y4 -> VR-OUT2 -> PA1
```

Both multiplexers share `ADDR0`, `ADDR1`, and `ADDR2`.

For a standard 74HC4051, Y4 corresponds to select value 4 (binary 100):

```
ADDR2 = 1
ADDR1 = 0
ADDR0 = 0
```

This is the best firmware kill point.

## Desired firmware modification

Do NOT filter CC77 after MIDI generation. Do NOT suppress only the OLED renderer.

Instead, discard mux sample index 4 / physical knob K8 before quadrature decoding or high-level control-event dispatch.

Conceptually:

```c
for (mux_index = 0; mux_index < 8; ++mux_index) {
    select_mux(mux_index);

    phase_a = read_pa0();
    phase_b = read_pa1();

    if (mux_index == 4) {
        // Physical K8. Broken encoder. Deliberately disabled.
        continue;
    }

    update_encoder(mux_index, phase_a, phase_b);
}
```

Depending on firmware organization, logical knob numbering may be remapped after the mux scan. The patch should therefore key off the **mux scan channel**, not the QLINK name or CC number.

## Why this satisfies the requirement

Dropping the input before encoder decoding means K8 can never create:

- CC77
- relative CC increments
- a QLINK4 OLED focus event
- a MIDI-learn candidate
- an internal encoder-change event

K1-K7 continue to use the exact original firmware path.

## Hardware fallback

If firmware flashing proves impractical, the same architecture gives a guaranteed board-level repair: electrically immobilize both `P8PHA` and `P8PHB` at the same stable state so the quadrature decoder can never observe an edge.

Do not blindly short these nets until the encoder common/reference on the actual board has been verified with a meter; the schematic should be followed and the resting state of a working encoder measured first.

## Sources

- MPK Mini MK3 service schematic, CPU + mux sheet (page 34)
- MPK Mini MK3 service schematic, encoder sheet (page 35)
