#!/usr/bin/env python3
"""
Identify the connected Akai MPK Mini MK3 USB PID on macOS.

This decides which v1.26 firmware family in Akai's updater matches the
physical device:
  PID 0x0049 -> updater Region 1 (v1.26)
  PID 0x1049 -> updater Region 3 (v1.26)
"""

from __future__ import annotations

import plistlib
import re
import subprocess
import sys


AKAI_VID = 0x09E8


def parse_hexish(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip().lower()
    # system_profiler commonly emits strings like:
    #   "0x09e8  (AKAI professional M.I. Corp.)"
    # so extract the first hex token rather than parsing the whole field.
    m = re.search(r"0x([0-9a-f]+)", s)
    if m:
        return int(m.group(1), 16)
    try:
        return int(s, 0)
    except ValueError:
        return None


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)



def detect_with_ioreg():
    """Fallback USB scan using IORegistry when system_profiler is unhelpful."""
    try:
        raw = subprocess.check_output(
            ["ioreg", "-p", "IOUSB", "-l", "-w", "0"],
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
    except Exception:
        return []

    matches = []
    current_name = None
    current_vid = None
    current_pid = None

    for line in raw.splitlines():
        stripped = line.strip()

        # Device tree line, e.g. '+-o MPK mini 3@...'
        m_name = re.search(r"\+-o\s+(.+?)(?:@|\s{2,}|$)", stripped)
        if m_name:
            if current_name is not None and (
                current_vid == AKAI_VID
                or "mpk mini" in current_name.lower()
                or "akai" in current_name.lower()
            ):
                matches.append((current_name, current_vid, current_pid, {}))
            current_name = m_name.group(1).strip()
            current_vid = None
            current_pid = None
            continue

        m_vid = re.search(r'"idVendor"\s*=\s*(\d+)', stripped)
        if m_vid:
            current_vid = int(m_vid.group(1))
            continue

        m_pid = re.search(r'"idProduct"\s*=\s*(\d+)', stripped)
        if m_pid:
            current_pid = int(m_pid.group(1))
            continue

    if current_name is not None and (
        current_vid == AKAI_VID
        or "mpk mini" in current_name.lower()
        or "akai" in current_name.lower()
    ):
        matches.append((current_name, current_vid, current_pid, {}))

    return matches

def main() -> int:
    if sys.platform != "darwin":
        print("This helper currently targets macOS.")
        return 2

    try:
        raw = subprocess.check_output(
            ["system_profiler", "SPUSBDataType", "-xml"],
            stderr=subprocess.STDOUT,
        )
        plist = plistlib.loads(raw)
    except Exception as exc:
        print(f"Could not query macOS USB devices: {exc}")
        return 2

    matches = []
    for item in walk(plist):
        name = str(item.get("_name", ""))
        vid = parse_hexish(item.get("vendor_id"))
        pid = parse_hexish(item.get("product_id"))

        # Prefer the known Akai VID, but retain name matches in case macOS
        # omits/changes one of the descriptor fields.
        if vid == AKAI_VID or "mpk mini" in name.lower() or "akai" in name.lower():
            matches.append((name, vid, pid, item))

    if not matches:
        matches = detect_with_ioreg()

    if not matches:
        print("No Akai/MPK USB device found via system_profiler or ioreg.")
        print()
        print("Raw USB devices containing 'AKAI' or 'MPK' may still be useful.")
        print("Run this and paste the output:")
        print("  system_profiler SPUSBDataType | grep -i -A 12 -B 2 -E 'akai|mpk'")
        return 1

    print("Matching USB devices:")
    for name, vid, pid, _ in matches:
        vid_s = f"0x{vid:04x}" if vid is not None else "unknown"
        pid_s = f"0x{pid:04x}" if pid is not None else "unknown"
        print(f"  {name or '(unnamed)'}: VID {vid_s}, PID {pid_s}")

    pids = {pid for _, vid, pid, _ in matches if vid == AKAI_VID and pid is not None}

    print()
    if 0x0049 in pids:
        print("MATCH: PID 0x0049")
        print("Use updater Region 1 for v1.26.")
        print("SHA256: 2c006142134bcc66116f25f04c091f4c62e2b97984beecfdbffc8a93db602a19")
        return 0

    if 0x1049 in pids:
        print("MATCH: PID 0x1049")
        print("Use updater Region 3 for v1.26.")
        print("SHA256: b2a8c30125d8d93fae59b8726140c8887ca806c16808f8cbdb753813e91b7392")
        return 0

    print("Akai VID found, but PID is neither 0x0049 nor 0x1049.")
    print("Paste the output above before proceeding.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
