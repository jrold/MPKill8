#!/usr/bin/env python3
"""
Build an MPKill8-patched copy of Akai's official MPK Mini MK3 v1.26 updater.

Confirmed target hardware:
  USB VID 0x09e8
  USB PID 0x1049

Confirmed stock firmware image:
  updater Region 3
  EXE offset 0x28c144
  size 0x20000
  SHA-256 b2a8c30125d8d93fae59b8726140c8887ca806c16808f8cbdb753813e91b7392

Patch:
  firmware offset 0x0e5ec
  08 28   cmp r0,#8
  07 28   cmp r0,#7

This prevents logical knob index 7 (physical K8) from entering the encoder
movement/event path while leaving the low-level mux/ADC scan intact. That is
important because mux Y4 is also used by a pad on the parallel pad mux.

The Akai firmware checksum is the 16-bit sum of bytes [0:0x1fffe], stored
big-endian at 0x1fffe. The stock image stores e2 ff; the patched image stores
e2 fe.

The script never modifies the official input ZIP. It writes patched artifacts
under dist/, which is ignored by .gitignore.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import shutil
import zipfile
from pathlib import Path


REGION_OFFSET = 0x28C144
REGION_SIZE = 0x20000
PATCH_OFFSET = 0x0E5EC
CHECKSUM_OFFSET = 0x1FFFE

ORIGINAL_INSN = bytes.fromhex("08 28")
PATCHED_INSN = bytes.fromhex("07 28")

ORIGINAL_SHA256 = "b2a8c30125d8d93fae59b8726140c8887ca806c16808f8cbdb753813e91b7392"
PATCHED_SHA256 = "b7121c28293201a031200b56058fc5bee1fdbfdf053582d99e1fbea8029f3087"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def firmware_checksum(image: bytes) -> bytes:
    if len(image) != REGION_SIZE:
        raise ValueError(f"firmware image must be {REGION_SIZE} bytes")
    value = sum(image[:CHECKSUM_OFFSET]) & 0xFFFF
    return value.to_bytes(2, "big")


def patch_region(stock: bytes) -> bytes:
    if len(stock) != REGION_SIZE:
        raise RuntimeError(f"Region 3 size mismatch: {len(stock)}")

    actual_sha = sha256(stock)
    if actual_sha != ORIGINAL_SHA256:
        raise RuntimeError(
            "Region 3 hash mismatch; refusing to patch.\n"
            f"Expected: {ORIGINAL_SHA256}\n"
            f"Actual:   {actual_sha}"
        )

    if stock[PATCH_OFFSET:PATCH_OFFSET + 2] != ORIGINAL_INSN:
        raise RuntimeError(
            "Expected encoder-loop instruction not found at 0x0e5ec; "
            "refusing to patch."
        )

    expected_stock_checksum = firmware_checksum(stock)
    actual_stock_checksum = stock[CHECKSUM_OFFSET:CHECKSUM_OFFSET + 2]
    if actual_stock_checksum != expected_stock_checksum:
        raise RuntimeError(
            "Stock firmware checksum mismatch; refusing to patch.\n"
            f"Expected from data: {expected_stock_checksum.hex(' ')}\n"
            f"Stored:             {actual_stock_checksum.hex(' ')}"
        )

    out = bytearray(stock)
    out[PATCH_OFFSET:PATCH_OFFSET + 2] = PATCHED_INSN
    out[CHECKSUM_OFFSET:CHECKSUM_OFFSET + 2] = firmware_checksum(out)

    patched = bytes(out)
    actual_patched_sha = sha256(patched)
    if actual_patched_sha != PATCHED_SHA256:
        raise RuntimeError(
            "Patched image hash does not match known-good static build.\n"
            f"Expected: {PATCHED_SHA256}\n"
            f"Actual:   {actual_patched_sha}"
        )

    return patched


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "input_zip",
        type=Path,
        nargs="?",
        default=Path("vendor/MPKmini3_Updater_v1.26_WIN.zip"),
    )
    ap.add_argument(
        "--dist",
        type=Path,
        default=Path("dist"),
    )
    args = ap.parse_args()

    if not args.input_zip.is_file():
        raise SystemExit(f"Updater ZIP not found: {args.input_zip}")

    args.dist.mkdir(parents=True, exist_ok=True)

    raw_zip = args.input_zip.read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw_zip), "r") as zin:
        exe_names = [n for n in zin.namelist() if n.lower().endswith(".exe")]
        if len(exe_names) != 1:
            raise SystemExit(f"Expected exactly one updater EXE; found {exe_names}")

        exe_name = exe_names[0]
        stock_exe = bytearray(zin.read(exe_name))

        end = REGION_OFFSET + REGION_SIZE
        if len(stock_exe) < end:
            raise SystemExit("Updater EXE is too small for expected Region 3")

        stock_region = bytes(stock_exe[REGION_OFFSET:end])
        patched_region = patch_region(stock_region)
        stock_exe[REGION_OFFSET:end] = patched_region

        out_exe = args.dist / "MPKmini3_Updater_v1.26_MPKILL8.exe"
        out_exe.write_bytes(stock_exe)

        out_zip = args.dist / "MPKmini3_Updater_v1.26_MPKILL8_WIN.zip"
        with zipfile.ZipFile(out_zip, "w") as zout:
            for info in zin.infolist():
                payload = bytes(stock_exe) if info.filename == exe_name else zin.read(info.filename)
                zout.writestr(info, payload)

    # Verify the only firmware-byte changes are the instruction immediate and
    # checksum byte.
    diffs = [
        i for i, (a, b) in enumerate(zip(stock_region, patched_region))
        if a != b
    ]
    expected_diffs = [PATCH_OFFSET, CHECKSUM_OFFSET + 1]
    if diffs != expected_diffs:
        raise SystemExit(
            f"Unexpected firmware diff offsets: {[hex(x) for x in diffs]}"
        )

    print("MPKill8 updater built successfully.")
    print()
    print(f"Target:       VID 0x09e8 / PID 0x1049")
    print(f"Firmware:     v1.26 Region 3")
    print(f"Stock SHA256: {ORIGINAL_SHA256}")
    print(f"Patch SHA256: {PATCHED_SHA256}")
    print()
    print("Firmware changes:")
    print("  0x0e5ec: 08 -> 07   (encoder loop: 8 knobs -> 7 knobs)")
    print("  0x1ffff: ff -> fe   (recomputed Akai firmware checksum)")
    print()
    print(f"Patched EXE:  {out_exe}")
    print(f"Patched ZIP:  {out_zip}")
    print()
    print(
        "The modified EXE will no longer have a valid original publisher "
        "signature, if the stock updater was Authenticode-signed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
