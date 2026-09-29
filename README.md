# MPKill8

Disable the broken **K8** knob on an Akai MPK Mini MK3 so it is completely ignored: no MIDI CC and, ultimately, no OLED reaction.

## Current strategy

There are two paths, in increasing order of invasiveness:

1. **RAM-only undocumented-mode probe** — clone a normal MPK program into the volatile RAM slot and change only K8's mode byte. The documented values are `0 = Absolute` and `1 = Relative`; the tool lets us test undocumented values without touching saved programs or firmware.
2. **Firmware patch** — if the stock firmware treats every nonzero mode as Relative, extract the v1.26 firmware payload, locate the knob scan/event path, and patch K8 out before MIDI/UI dispatch.

The first path is intentionally cheap and reversible. If it works, we get the desired behavior without flashing anything.

## What we know

### Hardware

- MCU: **STM32F070RBT6** (Cortex-M0, 128 KiB flash, 16 KiB SRAM).
- The eight knobs are scanned through a **CD74HC4051** analog multiplexer.
- In the service schematic, K8 is the `P8PHB` input and lands on mux input `Y4`.
- Akai's firmware updater enters update mode by holding **BANK + PROG SELECT** while connecting USB.

### MPK Mini MK3 SysEx

Model ID: `0x49`

| Command | Value |
|---|---:|
| Select program | `0x62` |
| Write program | `0x64` |
| Query program | `0x66` |
| Program reply | `0x67` |

Program `0` is the volatile **RAM** program. Programs `1..8` are saved slots.

Each knob occupies 20 bytes in the program payload:

```
+0x00  mode     (0 = Absolute, 1 = Relative)
+0x01  CC
+0x02  minimum
+0x03  maximum
+0x04  name[16]
```

K8 begins at payload offset **`0xE0`**.

## First experiment

Requirements:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

List ports:

```bash
python mpkill8.py ports
```

Read a saved program and inspect K8:

```bash
python mpkill8.py inspect --source 1
```

Try undocumented mode `2` in the volatile RAM program:

```bash
python mpkill8.py probe --source 1 --mode 2
```

The tool:

1. reads saved Program 1;
2. changes only K8's mode byte;
3. writes the modified copy to Program 0 (RAM);
4. selects RAM;
5. leaves the controller untouched and watches for the broken K8 input to fire spontaneously.

**K8 is physically broken off; do not try to move anything.** Watch the MPK OLED while the controller sits idle. Success means BOTH:

- the tool sees no spontaneous K8 CC messages; and
- K8 never causes a spontaneous popup/value change on the OLED.

The default idle observation is 60 seconds. Because the fault is intermittent, a longer test is better:

```bash
python mpkill8.py probe --source 1 --mode 2 --seconds 300
```

If mode `2` fails, try:

```bash
python mpkill8.py probe --source 1 --mode 127
```

Nothing in `probe` writes Programs 1–8.

## Firmware-updater analysis

Akai currently publishes MPK Mini MK3 updater **v1.26**. Put the downloaded Windows updater ZIP/EXE anywhere outside the repo (or under ignored `vendor/`) and run:

```bash
python tools/scan_updater.py /path/to/MPKmini3_Updater_v1.26_WIN.zip
```

The scanner recursively checks ZIP members and raw files for plausible STM32F070 vector tables. If the updater contains an uncompressed firmware image, this should identify its offset and allow us to carve it out for Ghidra.

## Safety / recovery

- The RAM probe does **not** overwrite your saved programs.
- Selecting a normal program or power-cycling returns to normal configuration.
- Do not flash any patched image until we have extracted and verified the stock v1.26 payload and have a recovery route.

## Sources / prior work

- Akai MPK Mini MK3 service schematic/manual: https://www.manualslib.com/manual/2910998/Akai-Mpk-Mini-Mk3.html?page=34
- Akai firmware recovery/update instructions: https://support.akaipro.com/en/support/solutions/articles/69000798892-akai-pro-mpk-mini-mk3-upgrade-v-error-and-installing-the-firmware
- Joonas Pihlajamaa's MK3 SysEx reverse engineering: https://joonas.fi/2021/02/reverse-engineering-midi-devices-akai-mpk-mini-mk3/
- sysex-controls MK3 implementation: https://github.com/soyersoyer/sysex-controls

## Status

**Phase 1: RAM-only K8 disable probe — implemented.**

If undocumented mode values do not suppress both MIDI and OLED behavior, next step is binary extraction/static analysis of v1.26.


## Physical knob calibration

Do this before probing K8. The program-record names are not a reliable physical label: on the user's factory program, physical K1 reports `QLINK5` while physical K5 reports `QLINK1`.

```bash
python mpkill8.py map --source 1
python mpkill8.py calibrate --source 1
```

Calibration asks you to move physical K1 through K7 one at a time. The broken K8 is never touched. If ghost K8 traffic appears while another knob moves, it is retained as secondary evidence; the knob you intentionally move should dominate the event count.

If all seven good knobs map uniquely, the remaining record is inferred as physical K8 and saved locally in `mapping.json`.

Then run the kill probe:

```bash
python mpkill8.py probe --source 1 --mode 2 --seconds 30
```

During the probe, actively move K1-K7—especially the controls that normally provoke the K8 ghost. Success requires both zero K8 MIDI events and no K8 popup/value activity on the OLED.
