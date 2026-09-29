#!/usr/bin/env python3
"""
Cleanly identify the four embedded MPK Mini MK3 firmware images.

Prints only metadata from the four known 128 KiB firmware roots in the
official v1.26 Windows updater. No binary string dump.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import struct
import zipfile
from pathlib import Path


ROOT_OFFSETS = [0x24C144, 0x26C144, 0x28C144, 0x2AC144]
FLASH_SIZE = 0x20000

VID_ADDR = 0x1FFF0
PID_ADDR = 0x1FFF2
VER_ADDR = 0x1FFF6
VER_LEN = 2
CHECKSUM_ADDR = 0x1FFFE


def u16le(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def get_exe(zip_path: Path) -> tuple[str, bytes]:
    raw = zip_path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        exes = [n for n in zf.namelist() if n.lower().endswith(".exe")]
        if not exes:
            raise SystemExit("No updater .exe found in ZIP")
        name = exes[0]
        return name, zf.read(name)


def version_interpretations(raw: bytes) -> str:
    if len(raw) != 2:
        return raw.hex()

    a, b = raw
    le = int.from_bytes(raw, "little")
    be = int.from_bytes(raw, "big")

    guesses = [
        f"raw={raw.hex(' ')}",
        f"bytes-decimal={a}.{b}",
        f"u16le=0x{le:04x}",
        f"u16be=0x{be:04x}",
    ]

    # Common packed-BCD interpretation, if both nibbles are decimal.
    if all(((x >> 4) <= 9 and (x & 0xF) <= 9) for x in raw):
        guesses.append(
            f"BCD={((a >> 4) * 10 + (a & 0xF))}."
            f"{((b >> 4) * 10 + (b & 0xF)):02d}"
        )

    return ", ".join(guesses)


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
    print(f"Updater: {exe_name}")
    print()

    regions = []
    for idx, off in enumerate(ROOT_OFFSETS, 1):
        block = exe[off : off + FLASH_SIZE]
        if len(block) != FLASH_SIZE:
            raise SystemExit(f"Region {idx} is truncated")

        sp, reset = struct.unpack_from("<II", block, 0)
        vid = u16le(block, VID_ADDR)
        pid = u16le(block, PID_ADDR)
        ver_raw = block[VER_ADDR : VER_ADDR + VER_LEN]
        checksum = u16le(block, CHECKSUM_ADDR)

        regions.append(
            {
                "idx": idx,
                "off": off,
                "sha": hashlib.sha256(block).hexdigest(),
                "sp": sp,
                "reset": reset,
                "vid": vid,
                "pid": pid,
                "ver_raw": ver_raw,
                "checksum": checksum,
            }
        )

    for r in regions:
        print(f"Region {r['idx']} @ EXE 0x{r['off']:06x}")
        print(f"  SHA256   {r['sha']}")
        print(f"  SP       0x{r['sp']:08x}")
        print(f"  reset    0x{r['reset']:08x}")
        print(f"  VID      0x{r['vid']:04x}")
        print(f"  PID      0x{r['pid']:04x}")
        print(f"  version  {version_interpretations(r['ver_raw'])}")
        print(f"  checksum 0x{r['checksum']:04x}")
        print()

    print("Expected updater descriptor for MPK mini 3:")
    print("  VID 0x09e8")
    print("  PID 0x0049")
    print("  image size 0x20000")
    print()
    print(
        "The two regions whose version bytes represent 1.26 are the current "
        "firmware images. Differences in VID/PID or startup/vector layout can "
        "then identify the hardware family."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
