#!/usr/bin/env python3
"""
Find plausible STM32F070 firmware images embedded in Akai updater files.

This is intentionally a heuristic scanner. It looks for Cortex-M vector tables:
  - initial MSP inside the STM32F070RB SRAM range
  - odd Thumb reset handler inside the 128 KiB flash range
  - several additional exception vectors that are zero or plausible Thumb
    addresses inside flash

It scans ordinary files, recursively expands ZIP members, and probes common
compression streams (zlib/gzip/bzip2/xz) for embedded firmware payloads.
"""

from __future__ import annotations

import argparse
import bz2
import gzip
import hashlib
import io
import lzma
import struct
import sys
import zlib
import zipfile
from dataclasses import dataclass
from pathlib import Path


FLASH_BASE = 0x08000000
FLASH_SIZE = 128 * 1024
FLASH_END = FLASH_BASE + FLASH_SIZE

SRAM_BASE = 0x20000000
SRAM_SIZE = 16 * 1024
SRAM_END = SRAM_BASE + SRAM_SIZE


@dataclass(frozen=True)
class Candidate:
    offset: int
    initial_sp: int
    reset: int
    plausible_vectors: int


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def plausible_handler(value: int) -> bool:
    if value == 0:
        return True
    return (
        value & 1 == 1
        and FLASH_BASE <= (value & ~1) < FLASH_END
    )


def score_vector_table(data: bytes, offset: int) -> Candidate | None:
    if offset + 16 * 4 > len(data):
        return None

    initial_sp = u32(data, offset)
    reset = u32(data, offset + 4)

    if not (SRAM_BASE < initial_sp <= SRAM_END):
        return None

    if not (
        reset & 1 == 1
        and FLASH_BASE <= (reset & ~1) < FLASH_END
    ):
        return None

    vectors = [u32(data, offset + i * 4) for i in range(1, 16)]
    plausible = sum(plausible_handler(v) for v in vectors)

    # Reset + a healthy number of Cortex exception vectors should look sane.
    if plausible < 10:
        return None

    return Candidate(
        offset=offset,
        initial_sp=initial_sp,
        reset=reset,
        plausible_vectors=plausible,
    )


def scan(data: bytes) -> list[Candidate]:
    candidates: list[Candidate] = []

    # Vector tables are word-aligned.
    for offset in range(0, max(0, len(data) - 64), 4):
        candidate = score_vector_table(data, offset)
        if candidate is not None:
            candidates.append(candidate)

    # Collapse adjacent hits that are likely the same image / copied table.
    unique: list[Candidate] = []
    for c in candidates:
        if unique and c.offset - unique[-1].offset < 64:
            if c.plausible_vectors > unique[-1].plausible_vectors:
                unique[-1] = c
            continue
        unique.append(c)
    return unique


def printable_context(data: bytes, offset: int, radius: int = 48) -> str:
    lo = max(0, offset - radius)
    hi = min(len(data), offset + radius)
    out = []
    for b in data[lo:hi]:
        out.append(chr(b) if 32 <= b < 127 else ".")
    return "".join(out)


def extract_candidate(
    data: bytes,
    candidate: Candidate,
    label: str,
    output_dir: Path,
    index: int,
) -> None:
    available = len(data) - candidate.offset
    length = min(FLASH_SIZE, available)
    image = data[candidate.offset : candidate.offset + length]
    digest = hashlib.sha256(image).hexdigest()

    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in label)
    out = output_dir / f"{safe}.candidate{index}.0x{candidate.offset:x}.bin"
    out.write_bytes(image)

    print(
        f"    extracted {length} bytes -> {out} "
        f"(sha256 {digest})"
    )


def scan_blob(
    data: bytes,
    label: str,
    extract_dir: Path | None,
) -> int:
    found = scan(data)
    print(f"\n[{label}] {len(data)} bytes")

    if not found:
        print("  no plausible raw STM32F070 vector table found")
        return 0

    for i, c in enumerate(found, 1):
        print(
            f"  candidate {i}: file offset 0x{c.offset:x}, "
            f"MSP=0x{c.initial_sp:08x}, reset=0x{c.reset:08x}, "
            f"plausible vectors={c.plausible_vectors}/15"
        )
        print(f"    context: {printable_context(data, c.offset)}")
        if extract_dir is not None:
            extract_candidate(data, c, label, extract_dir, i)

    return len(found)


def decompress_common_streams(data: bytes, label: str):
    """Yield plausible decompressed children from common embedded stream types."""
    seen = set()

    signatures = [
        (b"\x1f\x8b", "gzip", lambda b: gzip.decompress(b)),
        (b"BZh", "bzip2", lambda b: bz2.decompress(b)),
        (b"\xfd7zXZ\x00", "xz", lambda b: lzma.decompress(b)),
    ]

    # zlib has several common two-byte headers.
    for sig in (b"\x78\x01", b"\x78\x5e", b"\x78\x9c", b"\x78\xda"):
        signatures.append((sig, "zlib", lambda b: zlib.decompress(b)))

    for sig, kind, decoder in signatures:
        start = 0
        while True:
            off = data.find(sig, start)
            if off < 0:
                break
            start = off + 1
            key = (kind, off)
            if key in seen:
                continue
            seen.add(key)
            try:
                child = decoder(data[off:])
            except Exception:
                continue
            if len(child) < 64:
                continue
            yield f"{label}::{kind}@0x{off:x}", child


def iter_blob_tree(label: str, data: bytes, depth: int = 0, seen_hashes=None):
    if seen_hashes is None:
        seen_hashes = set()
    if depth > 5:
        return

    digest = hashlib.sha256(data).digest()
    if digest in seen_hashes:
        return
    seen_hashes.add(digest)

    yield label, data

    bio = io.BytesIO(data)
    if zipfile.is_zipfile(bio):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                try:
                    member = zf.read(info)
                except Exception as exc:
                    print(
                        f"warning: cannot read ZIP member {info.filename}: {exc}",
                        file=sys.stderr,
                    )
                    continue
                yield from iter_blob_tree(
                    f"{label}::{info.filename}",
                    member,
                    depth + 1,
                    seen_hashes,
                )

    for child_label, child in decompress_common_streams(data, label):
        yield from iter_blob_tree(child_label, child, depth + 1, seen_hashes)


def iter_inputs(path: Path):
    raw = path.read_bytes()
    yield from iter_blob_tree(path.name, raw)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan Akai updater files for raw STM32F070 firmware images"
    )
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "--extract-dir",
        type=Path,
        help="Carve candidate images into this directory",
    )
    args = parser.parse_args()

    if not args.input.is_file():
        parser.error(f"not a file: {args.input}")

    if args.extract_dir is not None:
        args.extract_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for label, data in iter_inputs(args.input):
        total += scan_blob(data, label, args.extract_dir)

    print(f"\nTotal plausible vector-table candidates: {total}")
    if total == 0:
        print(
            "No raw/decompressed STM32 vector table was found. "
            "Next step is PE/resource inspection or runtime USB-traffic analysis."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
