#!/usr/bin/env python3
"""
Extract and verify the exact stock firmware image for the user's MPK Mini MK3.

Confirmed hardware identity:
  USB VID 0x09e8
  USB PID 0x1049

Correct updater image:
  Region 3
  EXE offset 0x28c144
  length 0x20000 (128 KiB)
  firmware v1.26
  SHA-256 b2a8c30125d8d93fae59b8726140c8887ca806c16808f8cbdb753813e91b7392

The output is intentionally written under dumps/ and should NOT be committed
to the public repository.
"""

from __future__ import annotations

import hashlib
import io
import sys
import zipfile
from pathlib import Path


ZIP = Path("vendor/MPKmini3_Updater_v1.26_WIN.zip")
OUT = Path("dumps/MPKmini3_PID1049_v1.26.bin")
OFFSET = 0x28C144
SIZE = 0x20000
EXPECTED_SHA256 = "b2a8c30125d8d93fae59b8726140c8887ca806c16808f8cbdb753813e91b7392"


def main() -> int:
    if not ZIP.is_file():
        print(f"Missing {ZIP}")
        print("Run: python tools/fetch_updater.py win")
        return 1

    with zipfile.ZipFile(io.BytesIO(ZIP.read_bytes())) as zf:
        exes = [n for n in zf.namelist() if n.lower().endswith(".exe")]
        if not exes:
            print("No updater EXE found in ZIP")
            return 1
        exe_name = exes[0]
        exe = zf.read(exe_name)

    image = exe[OFFSET:OFFSET + SIZE]
    if len(image) != SIZE:
        print(f"Extraction failed: expected {SIZE} bytes, got {len(image)}")
        return 1

    sha = hashlib.sha256(image).hexdigest()
    if sha != EXPECTED_SHA256:
        print("HASH MISMATCH — refusing to write output")
        print(f"Expected: {EXPECTED_SHA256}")
        print(f"Actual:   {sha}")
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(image)

    print("OK: exact PID 0x1049 / v1.26 firmware extracted")
    print(f"File:   {OUT}")
    print(f"Size:   {len(image)} bytes")
    print(f"SHA256: {sha}")
    print()
    print("Attach that .bin file to the ChatGPT conversation for disassembly/patching.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
