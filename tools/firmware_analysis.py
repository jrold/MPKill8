#!/usr/bin/env python3
"""
Binary-level safety analysis for MPKill8.

This module intentionally does NOT write flashable firmware.  It verifies
structural facts in the exact stock PID 0x1049 / v1.26 image and can build
candidate bytes in memory for tests only.

The first hardware test proved that patching 0x0e5ec was wrong.  The live
QLINK runtime loop is at 0x14912 and its loop bound is at 0x14932.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


IMAGE_SIZE = 0x20000
STOCK_SHA256 = "b2a8c30125d8d93fae59b8726140c8887ca806c16808f8cbdb753813e91b7392"

# Rejected hardware-tested patch.
REJECTED_PATCH_OFFSET = 0x0E5EC

# Live runtime QLINK loop discovered after the failed hardware test.
RUNTIME_FUNCTION_START = 0x14912
RUNTIME_FUNCTION_END = 0x15322
RUNTIME_LOOP_COMPARE = 0x14932

# Runtime QLINK initialization loop.
INIT_FUNCTION_START = 0x1486A
INIT_LOOP_COMPARE = 0x1487E

# Lookup tables used by both initialization/runtime code.
PHASE_A_TABLE = 0x18D4C
PHASE_B_TABLE = 0x18D54
EXPECTED_PHASE_A = bytes([3, 0, 1, 2, 5, 7, 6, 4])
EXPECTED_PHASE_B = bytes([11, 8, 9, 10, 13, 15, 14, 12])

CHECKSUM_OFFSET = 0x1FFFE


@dataclass(frozen=True)
class KnobPathEvidence:
    stock_sha256: str
    rejected_loop_bound: int
    runtime_loop_bound: int
    init_loop_bound: int
    phase_a: tuple[int, ...]
    phase_b: tuple[int, ...]
    runtime_has_record_stride_20: bool
    runtime_has_midi_dispatch: bool
    runtime_has_ui_name_path: bool


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require(image: bytes, offset: int, expected: bytes, label: str) -> None:
    actual = image[offset : offset + len(expected)]
    if actual != expected:
        raise AssertionError(
            f"{label} mismatch at 0x{offset:05x}: "
            f"expected {expected.hex(' ')}, got {actual.hex(' ')}"
        )


def _thumb_cmp_r0_imm8(image: bytes, offset: int) -> int:
    # Thumb-1 CMP R0,#imm8 encodes as 0x28 imm8, little endian bytes imm,0x28.
    if image[offset + 1] != 0x28:
        raise AssertionError(
            f"Expected Thumb CMP r0,#imm8 at 0x{offset:05x}; "
            f"got {image[offset:offset+2].hex(' ')}"
        )
    return image[offset]


def analyze_stock(image: bytes, require_stock_hash: bool = True) -> KnobPathEvidence:
    if len(image) != IMAGE_SIZE:
        raise AssertionError(f"Expected {IMAGE_SIZE} bytes, got {len(image)}")

    digest = sha256(image)
    if require_stock_hash and digest != STOCK_SHA256:
        raise AssertionError(
            f"Wrong stock firmware SHA256: expected {STOCK_SHA256}, got {digest}"
        )

    # Both locations are 8-wide loops in stock, but only the second is tied
    # directly to the 20-byte program records and UI/MIDI dispatch.
    rejected_bound = _thumb_cmp_r0_imm8(image, REJECTED_PATCH_OFFSET)
    runtime_bound = _thumb_cmp_r0_imm8(image, RUNTIME_LOOP_COMPARE)
    init_bound = _thumb_cmp_r0_imm8(image, INIT_LOOP_COMPARE)

    if rejected_bound != 8:
        raise AssertionError("Stock rejected-loop bound is not 8")
    if runtime_bound != 8:
        raise AssertionError("Stock live runtime-loop bound is not 8")
    if init_bound != 8:
        raise AssertionError("Stock init-loop bound is not 8")

    phase_a = image[PHASE_A_TABLE : PHASE_A_TABLE + 8]
    phase_b = image[PHASE_B_TABLE : PHASE_B_TABLE + 8]
    if phase_a != EXPECTED_PHASE_A:
        raise AssertionError(f"Unexpected phase-A table: {phase_a.hex(' ')}")
    if phase_b != EXPECTED_PHASE_B:
        raise AssertionError(f"Unexpected phase-B table: {phase_b.hex(' ')}")

    runtime = image[RUNTIME_FUNCTION_START:RUNTIME_FUNCTION_END]

    # Structural anchors from the exact Thumb code:
    #
    #   movs r0,#0x14
    #   muls r2,r0,r2
    #
    # This occurs when calculating current_program + knob_index*20.
    record_stride_20 = bytes.fromhex("14 20 42 43") in runtime

    # BL to 0x0800cb9a appears in the live routine.  We avoid implementing a
    # Thumb decoder here; these exact call encodings are stable for this exact
    # stock image and are backed by disassembly notes.
    midi_call_encodings = (
        bytes.fromhex("f7 f7 eb fc"),  # 0x080151c0 -> 0x0800cb9a
        bytes.fromhex("f7 f7 c8 fc"),  # 0x08015206 -> 0x0800cb9a
        bytes.fromhex("f7 f7 82 fc"),  # 0x08015292 -> 0x0800cb9a
        bytes.fromhex("f7 f7 5e fc"),  # 0x080152da -> 0x0800cb9a
    )
    runtime_has_midi = all(x in runtime for x in midi_call_encodings)

    # UI path anchor:
    #   index * 20
    #   add current-program base
    #   adds #0x58
    #
    # Program record 0 begins at +0x54, so +0x58 is record +4: name[16].
    # The pointer is then passed into 0x0800fdfc.
    ui_anchor = bytes.fromhex(
        "14 20 42 43 01 eb 02 00 58 30"
    )
    runtime_has_ui = ui_anchor in runtime

    if not record_stride_20:
        raise AssertionError("Live runtime loop does not contain 20-byte record stride")
    if not runtime_has_midi:
        raise AssertionError("Live runtime loop is missing expected MIDI dispatch calls")
    if not runtime_has_ui:
        raise AssertionError("Live runtime loop is missing record-name UI path")

    return KnobPathEvidence(
        stock_sha256=digest,
        rejected_loop_bound=rejected_bound,
        runtime_loop_bound=runtime_bound,
        init_loop_bound=init_bound,
        phase_a=tuple(phase_a),
        phase_b=tuple(phase_b),
        runtime_has_record_stride_20=record_stride_20,
        runtime_has_midi_dispatch=runtime_has_midi,
        runtime_has_ui_name_path=runtime_has_ui,
    )


def firmware_checksum(image: bytes) -> bytes:
    if len(image) != IMAGE_SIZE:
        raise ValueError("wrong image size")
    return (sum(image[:CHECKSUM_OFFSET]) & 0xFFFF).to_bytes(2, "big")


def reconstruct_rejected_hardware_build(stock: bytes) -> bytes:
    """Recreate the known-bad image from the first hardware test."""
    analyze_stock(stock)
    out = bytearray(stock)
    out[REJECTED_PATCH_OFFSET] = 7
    out[CHECKSUM_OFFSET : CHECKSUM_OFFSET + 2] = firmware_checksum(out)
    return bytes(out)


def build_runtime_candidate_in_memory(stock: bytes) -> bytes:
    """
    Build the new candidate in memory only.

    This function exists for automated analysis/testing.  It intentionally has
    no CLI and no updater writer.
    """
    analyze_stock(stock)
    out = bytearray(stock)

    # Crucial regression condition: leave the previously corrupted low-level
    # loop completely stock.
    assert out[REJECTED_PATCH_OFFSET] == 8

    out[RUNTIME_LOOP_COMPARE] = 7
    out[CHECKSUM_OFFSET : CHECKSUM_OFFSET + 2] = firmware_checksum(out)
    return bytes(out)


def model_record_dispatch(loop_bound: int, records: list[dict]) -> list[tuple[int, str]]:
    """
    Minimal behavioral model of the proven record-index relationship.

    Static disassembly proves the live loop's index is also the index used for:
      program_base + index*20 + {mode,cc,min,max,name}
    This model tests the consequence of changing ONLY that loop bound.
    """
    if len(records) != 8:
        raise ValueError("need eight records")
    return [(records[i]["cc"], records[i]["name"]) for i in range(loop_bound)]
