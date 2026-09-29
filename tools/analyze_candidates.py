#!/usr/bin/env python3
"""
Analyze scan_updater.py candidate carvings.

The scanner carves 128 KiB starting at every plausible Cortex-M vector table.
That means candidates can overlap when a larger updater resource contains
multiple vector tables. This tool reconstructs those overlap relationships and
prints useful metadata for each vector table.
"""

from __future__ import annotations

import argparse
import math
import re
import struct
from pathlib import Path


FLASH_BASE = 0x08000000
FLASH_SIZE = 128 * 1024
SRAM_BASE = 0x20000000
SRAM_END = SRAM_BASE + 16 * 1024

OFFSET_RE = re.compile(r"\.candidate(\d+)\.0x([0-9a-fA-F]+)\.bin$")


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def shannon(data: bytes) -> float:
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in counts if c)


def ascii_strings(data: bytes, minimum: int = 5) -> list[str]:
    out = []
    cur = bytearray()
    for b in data:
        if 32 <= b <= 126:
            cur.append(b)
        else:
            if len(cur) >= minimum:
                out.append(cur.decode("ascii", errors="replace"))
            cur.clear()
    if len(cur) >= minimum:
        out.append(cur.decode("ascii", errors="replace"))
    return out


def interesting_strings(data: bytes) -> list[str]:
    strings = ascii_strings(data)
    needles = (
        "akai", "mpk", "mini", "version", "firmware", "boot",
        "usb", "midi", "qlink", "encoder", "update", "stm32",
    )
    hits = []
    for s in strings:
        low = s.lower()
        if any(n in low for n in needles):
            hits.append(s)
    return hits[:40]


def vector_summary(data: bytes) -> dict:
    if len(data) < 0x100:
        return {}
    sp = u32(data, 0)
    reset = u32(data, 4)
    vectors = [u32(data, i * 4) for i in range(1, 48)]
    flash_handlers = [
        v for v in vectors
        if v & 1 and FLASH_BASE <= (v & ~1) < FLASH_BASE + FLASH_SIZE
    ]
    nonzero = [v for v in vectors if v]
    return {
        "sp": sp,
        "reset": reset,
        "reset_offset": (reset & ~1) - FLASH_BASE
            if FLASH_BASE <= (reset & ~1) < FLASH_BASE + FLASH_SIZE else None,
        "nonzero_vectors": len(nonzero),
        "flash_vectors": len(flash_handlers),
    }


def parse(path: Path):
    m = OFFSET_RE.search(path.name)
    if not m:
        raise ValueError(f"cannot parse candidate offset from {path.name}")
    return {
        "path": path,
        "candidate": int(m.group(1)),
        "offset": int(m.group(2), 16),
        "data": path.read_bytes(),
    }


def overlap_equal(a, b) -> tuple[int, int]:
    """Return equal bytes / overlap bytes using original EXE offsets."""
    a0, a1 = a["offset"], a["offset"] + len(a["data"])
    b0, b1 = b["offset"], b["offset"] + len(b["data"])
    lo, hi = max(a0, b0), min(a1, b1)
    if hi <= lo:
        return 0, 0
    aa = a["data"][lo - a0 : hi - a0]
    bb = b["data"][lo - b0 : hi - b0]
    eq = sum(x == y for x, y in zip(aa, bb))
    return eq, len(aa)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("directory", type=Path, nargs="?", default=Path("dumps/win"))
    args = ap.parse_args()

    files = sorted(args.directory.glob("*.bin"))
    if not files:
        raise SystemExit(f"no .bin files found in {args.directory}")

    items = sorted((parse(p) for p in files), key=lambda x: x["offset"])

    print("CANDIDATES")
    print("==========")
    for item in items:
        d = item["data"]
        v = vector_summary(d)
        ff = d.count(0xFF) / len(d) * 100
        zero = d.count(0x00) / len(d) * 100
        print(
            f"#{item['candidate']:>2}  off=0x{item['offset']:06x}  "
            f"size={len(d):6}  SP=0x{v.get('sp',0):08x}  "
            f"reset=0x{v.get('reset',0):08x}  "
            f"reset_off={v.get('reset_offset')}  "
            f"vectors={v.get('flash_vectors',0)}/{v.get('nonzero_vectors',0)}  "
            f"entropy={shannon(d):.2f}  FF={ff:.1f}%  00={zero:.1f}%"
        )
        hits = interesting_strings(d)
        if hits:
            print("     strings:", " | ".join(repr(x) for x in hits[:12]))

    print("\nOVERLAPS")
    print("========")
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            eq, n = overlap_equal(a, b)
            if not n:
                continue
            pct = 100.0 * eq / n
            print(
                f"#{a['candidate']} @0x{a['offset']:x} <-> "
                f"#{b['candidate']} @0x{b['offset']:x}: "
                f"overlap=0x{n:x} ({n} bytes), identical={pct:.3f}%"
            )

    # Anchor each region at the first not-yet-assigned vector table and
    # include only vector tables that begin within that exact 128 KiB span.
    # Do NOT use transitive overlap between carved files: each carve is itself
    # 128 KiB and can extend into the next resource.
    print("\nDISTINCT 128 KiB REGIONS")
    print("========================")
    groups = []
    i = 0
    while i < len(items):
        root = items[i]
        boundary = root["offset"] + FLASH_SIZE
        group = [root]
        i += 1
        while i < len(items) and items[i]["offset"] < boundary:
            group.append(items[i])
            i += 1
        groups.append(group)

    for gi, group in enumerate(groups, 1):
        root = group[0]
        boundary = root["offset"] + FLASH_SIZE
        print(
            f"Region {gi}: root candidate #{root['candidate']} "
            f"at EXE offset 0x{root['offset']:x} "
            f"(window ends 0x{boundary:x})"
        )
        for item in group:
            rel = item["offset"] - root["offset"]
            print(
                f"  candidate #{item['candidate']}: +0x{rel:x} "
                f"(vector table inside this 128 KiB region)"
            )

    print(
        "\nNOTE: candidates with byte-for-byte identical overlap are not "
        "independent firmware images; they are different vector-table entry "
        "points carved from the same updater resource."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
