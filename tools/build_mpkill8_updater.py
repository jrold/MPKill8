#!/usr/bin/env python3
"""
DISABLED: known-bad MPKill8 firmware builder.

The first hardware test on 2026-09-29 proved the old patch at firmware
offset 0x0e5ec does NOT disable K8 and alters normal QLINK behavior.

Do not re-enable this builder.  A replacement firmware must pass the
binary-level regression suite and hardware review before any installer is
made available.
"""

from __future__ import annotations

KNOWN_BAD_PATCH_DISABLED = True


def patch_region(*_args, **_kwargs):
    raise RuntimeError(
        "KNOWN-BAD PATCH DISABLED: 0x0e5ec was the wrong 8-control loop. "
        "Restore stock firmware and use tools/firmware_analysis.py for analysis only."
    )


def main() -> int:
    print("MPKill8 firmware build is DISABLED.")
    print("Reason: first hardware test proved patch 0x0e5ec was the wrong loop.")
    print("Restore stock firmware; no replacement firmware has been approved.")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
