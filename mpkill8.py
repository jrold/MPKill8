#!/usr/bin/env python3
"""
MPKill8 - Akai MPK Mini MK3 K8 experiments.

The primary experiment is deliberately non-destructive:
read a saved program, patch only K8's mode byte, write the modified
copy to the volatile RAM program (program 0), and select RAM.

Requires:
    pip install mido python-rtmidi
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import mido


AKAI_MANUFACTURER = 0x47
HOST_TO_DEVICE = 0x7F
MPK_MINI_MK3 = 0x49

CMD_SELECT = 0x62
CMD_WRITE = 0x64
CMD_QUERY = 0x66
CMD_REPLY = 0x67

PROGRAM_RAM = 0

KNOB_OFFSETS = tuple(0x54 + (i * 0x14) for i in range(8))
K8_OFFSET = KNOB_OFFSETS[7]  # program record 8; physical mapping calibrated separately
KNOB_RECORD_SIZE = 20
KNOB_MODE = 0
KNOB_CC = 1
KNOB_MIN = 2
KNOB_MAX = 3
KNOB_NAME = 4
KNOB_NAME_LEN = 16

DEFAULT_PORT_HINTS = ("mpk mini 3", "mpk mini")


class MPKError(RuntimeError):
    pass


@dataclass
class KnobRecord:
    mode: int
    cc: int
    minimum: int
    maximum: int
    name: str


def decode_knob(payload: bytes, offset: int = K8_OFFSET) -> KnobRecord:
    end = offset + KNOB_RECORD_SIZE
    if len(payload) < end:
        raise MPKError(
            f"Program payload is only {len(payload)} bytes; "
            f"K8 requires at least {end} bytes."
        )

    raw_name = payload[offset + KNOB_NAME : offset + KNOB_NAME + KNOB_NAME_LEN]
    name = raw_name.split(b"\x00", 1)[0].decode("ascii", errors="replace")

    return KnobRecord(
        mode=payload[offset + KNOB_MODE],
        cc=payload[offset + KNOB_CC],
        minimum=payload[offset + KNOB_MIN],
        maximum=payload[offset + KNOB_MAX],
        name=name,
    )


def decode_all_knobs(payload: bytes) -> list[KnobRecord]:
    return [decode_knob(payload, offset) for offset in KNOB_OFFSETS]


def patch_record_mode(payload: bytes, record: int, mode: int) -> bytes:
    if not 1 <= record <= 8:
        raise ValueError("Knob record must be 1..8.")
    if not 0 <= mode <= 0x7F:
        raise ValueError("SysEx data bytes must be in the range 0..127.")

    offset = KNOB_OFFSETS[record - 1]
    if len(payload) < offset + KNOB_RECORD_SIZE:
        raise MPKError(f"Program payload is too short to contain knob record {record}.")

    patched = bytearray(payload)
    patched[offset + KNOB_MODE] = mode
    return bytes(patched)


def patch_k8_mode(payload: bytes, mode: int) -> bytes:
    # Backward-compatible helper: program record 8 only.
    return patch_record_mode(payload, 8, mode)


def make_query(program: int) -> mido.Message:
    return mido.Message(
        "sysex",
        data=[
            AKAI_MANUFACTURER,
            HOST_TO_DEVICE,
            MPK_MINI_MK3,
            CMD_QUERY,
            0x00,
            0x01,
            program,
        ],
    )


def make_write(program: int, payload: bytes) -> mido.Message:
    if any(b > 0x7F for b in payload):
        raise MPKError("Program payload contains a byte > 0x7F; refusing SysEx write.")

    wire_size = len(payload) + 1  # Akai length includes program-id byte.
    return mido.Message(
        "sysex",
        data=[
            AKAI_MANUFACTURER,
            HOST_TO_DEVICE,
            MPK_MINI_MK3,
            CMD_WRITE,
            (wire_size >> 7) & 0x7F,
            wire_size & 0x7F,
            program,
            *payload,
        ],
    )


def make_select(program: int) -> mido.Message:
    return mido.Message(
        "sysex",
        data=[
            AKAI_MANUFACTURER,
            HOST_TO_DEVICE,
            MPK_MINI_MK3,
            CMD_SELECT,
            0x00,
            0x01,
            program,
        ],
    )


def parse_program_reply(msg: mido.Message, expected_program: int) -> bytes | None:
    if msg.type != "sysex":
        return None

    d = list(msg.data)
    if len(d) < 7:
        return None

    # Byte 1 is usually 0x00 in device->host replies, but existing
    # reverse-engineered implementations intentionally do not depend on it.
    if not (
        d[0] == AKAI_MANUFACTURER
        and d[2] == MPK_MINI_MK3
        and d[3] == CMD_REPLY
        and d[6] == expected_program
    ):
        return None

    declared = ((d[4] & 0x7F) << 7) | (d[5] & 0x7F)
    payload = bytes(d[7:])

    # Akai counts the program-id byte in the length.
    if declared not in (len(payload), len(payload) + 1):
        print(
            f"warning: reply declared {declared} bytes but payload is "
            f"{len(payload)} bytes",
            file=sys.stderr,
        )

    return payload


def choose_port(names: list[str], explicit: str | None, direction: str) -> str:
    if explicit:
        if explicit not in names:
            raise MPKError(
                f"{direction} port {explicit!r} was not found. "
                f"Run 'python mpkill8.py ports'."
            )
        return explicit

    lowered = [(name, name.lower()) for name in names]
    for hint in DEFAULT_PORT_HINTS:
        hits = [name for name, low in lowered if hint in low]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            # Prefer a plain MIDI port over DAW/remote ports where possible.
            midi_hits = [
                name
                for name in hits
                if "daw" not in name.lower() and "remote" not in name.lower()
            ]
            if len(midi_hits) == 1:
                return midi_hits[0]
            raise MPKError(
                f"Multiple possible MPK {direction} ports found:\n  "
                + "\n  ".join(hits)
                + f"\nUse --{direction}-port with the exact name."
            )

    raise MPKError(
        f"No MPK Mini MK3 {direction} port found. "
        "Run 'python mpkill8.py ports'."
    )


class MPKClient:
    def __init__(self, input_name: str, output_name: str):
        self.messages: queue.Queue[mido.Message] = queue.Queue()
        self.input = mido.open_input(input_name, callback=self.messages.put)
        self.output = mido.open_output(output_name)

    def close(self) -> None:
        self.input.close()
        self.output.close()

    def __enter__(self) -> "MPKClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def clear_queue(self) -> None:
        while True:
            try:
                self.messages.get_nowait()
            except queue.Empty:
                return

    def read_program(self, program: int, timeout: float = 1.5) -> bytes:
        self.clear_queue()
        self.output.send(make_query(program))

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                msg = self.messages.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue
            payload = parse_program_reply(msg, program)
            if payload is not None:
                return payload

        raise MPKError(f"Timed out reading MPK program {program}.")

    def write_program(self, program: int, payload: bytes) -> None:
        self.output.send(make_write(program, payload))

    def select_program(self, program: int) -> None:
        self.output.send(make_select(program))


def open_client(args: argparse.Namespace) -> MPKClient:
    inputs = mido.get_input_names()
    outputs = mido.get_output_names()
    input_name = choose_port(inputs, args.input_port, "input")
    output_name = choose_port(outputs, args.output_port, "output")

    print(f"Input : {input_name}")
    print(f"Output: {output_name}")
    return MPKClient(input_name, output_name)


def print_k8(record: KnobRecord, prefix: str = "K8") -> None:
    mode_name = {0: "Absolute", 1: "Relative"}.get(record.mode, "UNDOCUMENTED")
    print(
        f"{prefix}: mode={record.mode} ({mode_name}), CC={record.cc}, "
        f"min={record.minimum}, max={record.maximum}, name={record.name!r}"
    )


def print_knob_table(payload: bytes) -> None:
    print("Record  Offset  Mode  CC   Name")
    print("------  ------  ----  ---  ----------------")
    for i, (offset, knob) in enumerate(zip(KNOB_OFFSETS, decode_all_knobs(payload)), 1):
        mode_name = {0: "ABS", 1: "REL"}.get(knob.mode, str(knob.mode))
        print(f"{i:>6}  0x{offset:04X}  {mode_name:>4}  {knob.cc:>3}  {knob.name}")


def collect_cc_counts(mpk: "MPKClient", seconds: float) -> Counter[int]:
    mpk.clear_queue()
    deadline = time.monotonic() + seconds
    counts: Counter[int] = Counter()
    while time.monotonic() < deadline:
        try:
            msg = mpk.messages.get(timeout=0.05)
        except queue.Empty:
            continue
        if msg.type == "control_change":
            counts[msg.control] += 1
    return counts


def resolve_target_record(args: argparse.Namespace) -> int:
    if getattr(args, "record", None):
        return args.record

    mapping_path = Path(getattr(args, "mapping", "mapping.json"))
    if mapping_path.is_file():
        data = json.loads(mapping_path.read_text())
        record = int(data["physical_to_record"]["K8"])
        if 1 <= record <= 8:
            print(f"Using physical K8 -> program record {record} from {mapping_path}")
            return record

    raise MPKError(
        "Physical K8 has not been calibrated. Run 'python mpkill8.py calibrate "
        "--source 1' first, or pass --record N explicitly."
    )


def cmd_ports(_args: argparse.Namespace) -> int:
    print("MIDI inputs:")
    for name in mido.get_input_names():
        print(f"  {name}")
    print("\nMIDI outputs:")
    for name in mido.get_output_names():
        print(f"  {name}")
    return 0


def cmd_sniff(args: argparse.Namespace) -> int:
    names = mido.get_input_names()
    if not names:
        raise MPKError("No MIDI input ports found.")

    if args.all_ports:
        selected = names
    else:
        selected = [choose_port(names, args.input_port, "input")]

    print("Listening on:")
    for name in selected:
        print(f"  {name}")
    print(
        f"\nMove knobs / press pads / keys for {args.seconds:.1f} seconds. "
        "Printing EVERY incoming MIDI message..."
    )

    q: queue.Queue[tuple[str, mido.Message]] = queue.Queue()
    ports = []

    try:
        for name in selected:
            ports.append(
                mido.open_input(
                    name,
                    callback=lambda msg, port_name=name: q.put((port_name, msg)),
                )
            )

        deadline = time.monotonic() + args.seconds
        count = 0
        while time.monotonic() < deadline:
            try:
                port_name, msg = q.get(timeout=0.1)
            except queue.Empty:
                continue
            count += 1
            print(f"[{port_name}] {msg}")

        print(f"\nTotal incoming messages: {count}")
        if count == 0:
            print(
                "No performance MIDI reached the opened CoreMIDI input(s). "
                "That means the SysEx/config path is not enough for calibration; "
                "we need to identify the performance endpoint before mapping knobs."
            )
    finally:
        for port in ports:
            port.close()

    return 0


def cmd_map(args: argparse.Namespace) -> int:
    with open_client(args) as mpk:
        payload = mpk.read_program(args.source)
        print(f"Program {args.source}: {len(payload)} payload bytes\n")
        print_knob_table(payload)
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    with open_client(args) as mpk:
        payload = mpk.read_program(args.source)
        records = decode_all_knobs(payload)

        cc_to_records: dict[int, list[int]] = {}
        for i, knob in enumerate(records, 1):
            cc_to_records.setdefault(knob.cc, []).append(i)

        print(f"Program {args.source} knob records:\n")
        print_knob_table(payload)
        print(
            "\nWe will identify the seven surviving PHYSICAL knobs. "
            "K8 is broken off and is NEVER touched. If its ghost input fires "
            "while another knob moves, that is useful evidence and should appear "
            "as a secondary CC."
        )

        mpk.select_program(args.source)
        time.sleep(0.15)

        physical_to_record: dict[str, int] = {}
        details: dict[str, object] = {}

        for physical in range(1, 8):
            input(
                f"\nPhysical K{physical}: press Enter, then immediately move ONLY "
                f"K{physical} back and forth continuously for {args.seconds:.1f}s..."
            )
            counts = collect_cc_counts(mpk, args.seconds)
            known = {cc: count for cc, count in counts.items() if cc in cc_to_records}

            if not known:
                print("  No knob-record CC traffic detected.")
                details[f"K{physical}"] = {"counts": dict(counts), "record": None}
                continue

            ordered = sorted(known.items(), key=lambda item: item[1], reverse=True)
            print("  observed:", ", ".join(f"CC{cc} x{count}" for cc, count in ordered))

            best_cc, _ = ordered[0]
            candidates = cc_to_records[best_cc]
            if len(candidates) != 1:
                print(f"  CC{best_cc} is shared by records {candidates}; cannot map uniquely.")
                details[f"K{physical}"] = {"counts": dict(counts), "record": None}
                continue

            record = candidates[0]
            physical_to_record[f"K{physical}"] = record
            details[f"K{physical}"] = {
                "counts": dict(counts),
                "record": record,
                "cc": best_cc,
                "name": records[record - 1].name,
            }
            print(
                f"  => physical K{physical} = program record {record} "
                f"(CC{best_cc}, name={records[record - 1].name!r})"
            )

        used = set(physical_to_record.values())
        remaining = [r for r in range(1, 9) if r not in used]

        print("\n--- inferred physical mapping ---")
        for physical in range(1, 8):
            record = physical_to_record.get(f"K{physical}")
            print(f"K{physical}: record {record if record else '?'}")

        if len(physical_to_record) == 7 and len(remaining) == 1:
            k8_record = remaining[0]
            physical_to_record["K8"] = k8_record
            k8 = records[k8_record - 1]
            print(
                f"K8: record {k8_record} (remaining record; "
                f"CC{k8.cc}, name={k8.name!r})"
            )

            output = {
                "source_program": args.source,
                "physical_to_record": physical_to_record,
                "records": {
                    str(i): {
                        "offset": KNOB_OFFSETS[i - 1],
                        "cc": knob.cc,
                        "name": knob.name,
                        "mode": knob.mode,
                    }
                    for i, knob in enumerate(records, 1)
                },
                "calibration": details,
            }
            Path(args.output).write_text(json.dumps(output, indent=2) + "\n")
            print(f"\nSaved mapping to {args.output}")
            return 0

        print(
            f"\nCalibration inconclusive. Used records={sorted(used)}, "
            f"remaining={remaining}. No mapping file written."
        )
        return 2


def cmd_inspect(args: argparse.Namespace) -> int:
    with open_client(args) as mpk:
        payload = mpk.read_program(args.source)
        print(f"Program {args.source}: {len(payload)} payload bytes")
        print_k8(decode_knob(payload))
    return 0


def cmd_dump(args: argparse.Namespace) -> int:
    with open_client(args) as mpk:
        payload = mpk.read_program(args.source)
        out = Path(args.output)
        out.write_bytes(payload)
        print(f"Wrote {len(payload)} bytes from Program {args.source} to {out}")
        print_k8(decode_knob(payload))
    return 0


def cmd_select(args: argparse.Namespace) -> int:
    with open_client(args) as mpk:
        mpk.select_program(args.program)
        print(f"Selected Program {args.program}.")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    if args.source == PROGRAM_RAM:
        raise MPKError("Use a saved source program (1..8), not RAM program 0.")

    target_record = resolve_target_record(args)
    target_offset = KNOB_OFFSETS[target_record - 1]

    with open_client(args) as mpk:
        original = mpk.read_program(args.source)
        original_k8 = decode_knob(original, target_offset)
        print(f"Read saved Program {args.source} ({len(original)} bytes).")
        print_k8(original_k8, f"Physical K8 / record {target_record}")

        patched = patch_record_mode(original, target_record, args.mode)
        print(
            f"\nWriting a VOLATILE copy to RAM Program 0 with only physical K8 "
            f"(record {target_record}, offset 0x{target_offset:04X}) mode changed: "
            f"{original_k8.mode} -> {args.mode}"
        )
        mpk.write_program(PROGRAM_RAM, patched)
        time.sleep(0.15)

        # Read back RAM before selecting it. If the device normalizes/rejects
        # the undocumented value, this tells us immediately.
        try:
            readback = mpk.read_program(PROGRAM_RAM)
            readback_k8 = decode_knob(readback, target_offset)
            print_k8(readback_k8, f"RAM readback physical K8 / record {target_record}")
            if readback_k8.mode != args.mode:
                print(
                    f"\nDevice did not retain mode {args.mode}; "
                    f"it read back as {readback_k8.mode}. "
                    "This candidate cannot be an undocumented OFF mode."
                )
                return 2
        except MPKError as exc:
            print(f"warning: could not verify RAM readback: {exc}", file=sys.stderr)

        mpk.select_program(PROGRAM_RAM)
        time.sleep(0.15)

        print(
            "\nRAM program is active. This has NOT overwritten Programs 1-8."
        )
        print(
            "SUCCESS CRITERIA: moving the surviving knobs must NOT provoke the "
            "broken K8 input: no K8 CC and no K8 popup/activity on the OLED."
        )
        input(
            f"\nWatch the OLED. Press Enter, then exercise K1-K7 (especially the "
            f"ones that normally provoke the ghost) for {args.seconds:.1f} seconds. "
            "Do not touch the broken K8 position..."
        )

        mpk.clear_queue()
        deadline = time.monotonic() + args.seconds
        matching_cc = []
        all_cc = []

        while time.monotonic() < deadline:
            try:
                msg = mpk.messages.get(timeout=0.05)
            except queue.Empty:
                continue
            if msg.type == "control_change":
                all_cc.append(msg)
                if msg.control == original_k8.cc:
                    matching_cc.append(msg)

        print("\n--- MIDI result ---")
        if matching_cc:
            values = [m.value for m in matching_cc]
            print(
                f"FAIL for MIDI: saw {len(matching_cc)} messages on K8's "
                f"configured CC {original_k8.cc}. "
                f"Values: {values[:24]}"
                + (" ..." if len(values) > 24 else "")
            )
        else:
            print(
                f"PASS for MIDI: saw zero messages on K8's configured "
                f"CC {original_k8.cc} during the test window."
            )

        if all_cc and not matching_cc:
            summary = ", ".join(
                f"CC{m.control}={m.value}" for m in all_cc[:12]
            )
            print(f"Other CC traffic observed: {summary}")

        print(
            "\nOLED result cannot be measured over MIDI: "
            "if you exercised the good knobs and physical K8 never popped up or "
            "changed anything on the OLED, this mode is a candidate for the actual kill."
        )
        print(
            f"RAM remains selected for further physical testing. "
            f"Restore with: python mpkill8.py select --program {args.source}"
        )

        return 1 if matching_cc else 0


def add_port_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input-port", help="Exact MIDI input port name")
    parser.add_argument("--output-port", help="Exact MIDI output port name")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Akai MPK Mini MK3 K8 reverse-engineering tools"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ports", help="List MIDI ports")
    p.set_defaults(func=cmd_ports)

    p = sub.add_parser("sniff", help="Print every incoming MIDI message")
    p.add_argument("--seconds", type=float, default=10.0)
    p.add_argument("--input-port", help="Exact MIDI input port name")
    p.add_argument(
        "--all-ports",
        action="store_true",
        help="Listen on every available MIDI input port",
    )
    p.set_defaults(func=cmd_sniff)

    p = sub.add_parser("map", help="Show all eight program knob records")
    p.add_argument("--source", type=int, default=1, choices=range(0, 9))
    add_port_args(p)
    p.set_defaults(func=cmd_map)

    p = sub.add_parser(
        "calibrate",
        help="Learn physical K1-K7 mapping and infer broken physical K8",
    )
    p.add_argument("--source", type=int, default=1, choices=range(1, 9))
    p.add_argument(
        "--seconds",
        type=float,
        default=2.5,
        help="Movement window for each surviving knob (default: 2.5 seconds)",
    )
    p.add_argument("--output", default="mapping.json")
    add_port_args(p)
    p.set_defaults(func=cmd_calibrate)

    p = sub.add_parser("inspect", help="Read a program and show program record 8 settings")
    p.add_argument("--source", type=int, default=1, choices=range(0, 9))
    add_port_args(p)
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("dump", help="Dump raw program payload to a file")
    p.add_argument("--source", type=int, default=1, choices=range(0, 9))
    p.add_argument("--output", default="program.bin")
    add_port_args(p)
    p.set_defaults(func=cmd_dump)

    p = sub.add_parser("select", help="Select RAM (0) or saved Program 1..8")
    p.add_argument("--program", type=int, required=True, choices=range(0, 9))
    add_port_args(p)
    p.set_defaults(func=cmd_select)

    p = sub.add_parser(
        "probe",
        help="Clone a saved program to RAM and test an undocumented K8 mode",
    )
    p.add_argument("--source", type=int, default=1, choices=range(1, 9))
    p.add_argument(
        "--mode",
        type=lambda s: int(s, 0),
        required=True,
        help="K8 mode byte to test, e.g. 2 or 0x7f",
    )
    p.add_argument(
        "--seconds",
        type=float,
        default=30.0,
        help="Stress window while moving K1-K7 to provoke ghost K8 (default: 30 seconds)",
    )
    p.add_argument(
        "--mapping",
        default="mapping.json",
        help="Calibration file used to resolve physical K8 (default: mapping.json)",
    )
    p.add_argument(
        "--record",
        type=int,
        choices=range(1, 9),
        help="Explicit program record for physical K8; bypasses mapping file",
    )
    add_port_args(p)
    p.set_defaults(func=cmd_probe)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        return args.func(args)
    except (MPKError, OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
