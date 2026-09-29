#!/usr/bin/env python3
"""
Inspect the MPK Mini MK3 v1.26 Windows updater layout.

This tool extracts the updater EXE from the official ZIP, prints the embedded
UpdaterInfo XML, and analyzes the four consecutive 128 KiB firmware regions
identified by scan_updater.py.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import struct
import zipfile
from pathlib import Path


ROOT_OFFSETS = [0x24C144, 0x26C144, 0x28C144, 0x2AC144]
FLASH_SIZE = 0x20000
FLASH_BASE = 0x08000000


def ascii_strings(data: bytes, minimum: int = 4) -> list[tuple[int, str]]:
    out = []
    start = None
    buf = bytearray()
    for i, b in enumerate(data):
        if 32 <= b <= 126:
            if start is None:
                start = i
            buf.append(b)
        else:
            if start is not None and len(buf) >= minimum:
                out.append((start, buf.decode("ascii", errors="replace")))
            start = None
            buf.clear()
    if start is not None and len(buf) >= minimum:
        out.append((start, buf.decode("ascii", errors="replace")))
    return out


def get_exe(zip_path: Path) -> tuple[str, bytes]:
    raw = zip_path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        exe_names = [n for n in zf.namelist() if n.lower().endswith(".exe")]
        if not exe_names:
            raise SystemExit("No .exe found in updater ZIP")
        if len(exe_names) > 1:
            print("Multiple EXEs found; using:", exe_names[0])
        name = exe_names[0]
        return name, zf.read(name)


def extract_xml(exe: bytes) -> str | None:
    starts = [
        exe.find(b"<?xml"),
        exe.find(b"<UpdaterInfo"),
    ]
    starts = [x for x in starts if x >= 0]
    if not starts:
        return None

    start = min(starts)
    end_tag = b"</UpdaterInfo>"
    end = exe.find(end_tag, start)
    if end < 0:
        # Try UTF-16LE form.
        marker = "<UpdaterInfo".encode("utf-16le")
        ustart = exe.find(marker)
        if ustart >= 0:
            uend_tag = "</UpdaterInfo>".encode("utf-16le")
            uend = exe.find(uend_tag, ustart)
            if uend >= 0:
                uend += len(uend_tag)
                return exe[ustart:uend].decode("utf-16le", errors="replace")
        return None

    end += len(end_tag)
    return exe[start:end].decode("utf-8", errors="replace")


def vector_info(block: bytes) -> tuple[int, int]:
    sp, reset = struct.unpack_from("<II", block, 0)
    return sp, reset


def interesting_region_strings(block: bytes) -> list[tuple[int, str]]:
    hits = []
    versionish = re.compile(
        r"(?:\b(?:v|ver(?:sion)?)[ ._-]*\d|\b\d+\.\d+(?:\.\d+)?\b)",
        re.IGNORECASE,
    )
    needles = (
        "mpk", "mini", "qlink", "akai", "firm", "boot", "midi",
        "usb", "update", "version", "copyright"
    )

    for off, s in ascii_strings(block, 4):
        low = s.lower()
        if any(n in low for n in needles) or versionish.search(s):
            hits.append((off, s))
    return hits[:80]


def byte_diff(a: bytes, b: bytes) -> tuple[int, int | None, int | None]:
    diffs = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    if not diffs:
        return 0, None, None
    return len(diffs), diffs[0], diffs[-1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "zip",
        type=Path,
        nargs="?",
        default=Path("vendor/MPKmini3_Updater_v1.26_WIN.zip"),
    )
    args = ap.parse_args()

    exe_name, exe = get_exe(args.zip)
    print(f"EXE: {exe_name}")
    print(f"EXE size: {len(exe):,} bytes")
    print(f"EXE SHA-256: {hashlib.sha256(exe).hexdigest()}")

    print("\nUPDATER XML")
    print("===========")
    xml = extract_xml(exe)
    if xml:
        print(xml)
    else:
        print("No complete UpdaterInfo XML block found.")

    print("\nFOUR ROOT REGIONS")
    print("=================")
    regions = []
    for idx, off in enumerate(ROOT_OFFSETS, 1):
        block = exe[off:off + FLASH_SIZE]
        if len(block) != FLASH_SIZE:
            print(f"Region {idx}: truncated at EXE offset 0x{off:x}")
            continue
        regions.append((idx, off, block))
        sp, reset = vector_info(block)
        print(
            f"Region {idx}: EXE 0x{off:x}..0x{off+FLASH_SIZE:x}  "
            f"SP=0x{sp:08x} reset=0x{reset:08x} "
            f"sha256={hashlib.sha256(block).hexdigest()}"
        )
        hits = interesting_region_strings(block)
        if hits:
            for soff, s in hits[:30]:
                print(f"  +0x{soff:05x}: {s!r}")
        else:
            print("  (no interesting/version strings)")

    print("\nPAIRWISE ROOT DIFFS")
    print("===================")
    for i in range(len(regions)):
        for j in range(i + 1, len(regions)):
            ia, _, a = regions[i]
            ib, _, b = regions[j]
            count, first, last = byte_diff(a, b)
            if first is None:
                print(f"Region {ia} vs {ib}: identical")
            else:
                print(
                    f"Region {ia} vs {ib}: {count:,} differing bytes; "
                    f"first +0x{first:x}, last +0x{last:x}"
                )

    print("\nXML/RESOURCE STRINGS AFTER REGION 4")
    print("===================================")
    tail_start = ROOT_OFFSETS[-1] + FLASH_SIZE
    tail = exe[tail_start:tail_start + 0x20000]
    for off, s in ascii_strings(tail, 5):
        low = s.lower()
        if (
            "updater" in low or "version" in low or "firm" in low or
            "hardware" in low or "product" in low or "mpk" in low
        ):
            print(f"EXE +0x{tail_start + off:x}: {s!r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
