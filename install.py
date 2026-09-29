#!/usr/bin/env python3
"""
MPKill8 one-command installer for macOS.

Workflow:
  1. Confirm the connected MPK Mini 3 is the supported VID/PID family.
  2. Download Akai's official macOS v1.26 updater (cached under vendor/).
  3. Extract the .app using macOS 'ditto'.
  4. Locate the exact stock PID 0x1049 / v1.26 firmware image by SHA-256.
  5. Patch only the verified 128 KiB firmware region:
       0x0e5ec: 08 -> 07   (encoder loop K1-K8 -> K1-K7)
       0x1ffff: ff -> fe   (Akai firmware checksum)
  6. Verify the exact patched firmware SHA-256.
  7. Ad-hoc re-sign the modified .app.
  8. Launch it.

The official Akai updater archive is never modified in place.
"""

from __future__ import annotations

import hashlib
import os
import plistlib
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


AKAI_MAC_URL = (
    "https://cdn.inmusicbrands.com/akai/mpk3mini/1_26/"
    "MPKmini3_Updater_v1.26.app.zip"
)

AKAI_VID = 0x09E8
TARGET_PID = 0x1049

REGION_SIZE = 0x20000
PATCH_OFFSET = 0x0E5EC
CHECKSUM_OFFSET = 0x1FFFF

STOCK_SHA256 = (
    "b2a8c30125d8d93fae59b8726140c8887ca806c16808f8cbdb753813e91b7392"
)
PATCHED_SHA256 = (
    "b7121c28293201a031200b56058fc5bee1fdbfdf053582d99e1fbea8029f3087"
)

# First 8 bytes of the confirmed PID 0x1049 / v1.26 image:
#   SP    = 0x20002748
#   Reset = 0x0800436d
FIRMWARE_SIGNATURE = bytes.fromhex("48 27 00 20 6d 43 00 08")

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor"
DIST = ROOT / "dist"
ZIP_PATH = VENDOR / "MPKmini3_Updater_v1.26.app.zip"
WORK = DIST / "_mac_updater_extract"
PATCHED_APP = DIST / "MPKmini3_Updater_v1.26_MPKILL8.app"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_hexish(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip().lower()
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


def detect_target_usb() -> tuple[str, int, int] | None:
    # First try system_profiler.
    try:
        raw = subprocess.check_output(
            ["system_profiler", "SPUSBDataType", "-xml"],
            stderr=subprocess.STDOUT,
        )
        plist = plistlib.loads(raw)

        for item in walk(plist):
            name = str(item.get("_name", ""))
            vid = parse_hexish(item.get("vendor_id"))
            pid = parse_hexish(item.get("product_id"))
            if vid == AKAI_VID and pid == TARGET_PID:
                return name or "MPK mini 3", vid, pid
    except Exception:
        pass

    # Fallback: this is the path that successfully detected the user's MPK
    # on macOS when system_profiler did not expose it reliably.
    try:
        raw = subprocess.check_output(
            ["ioreg", "-p", "IOUSB", "-l", "-w", "0"],
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
    except Exception:
        return None

    current_name = None
    current_vid = None
    current_pid = None

    def maybe_match():
        if current_vid == AKAI_VID and current_pid == TARGET_PID:
            return current_name or "MPK mini 3", current_vid, current_pid
        return None

    for line in raw.splitlines():
        stripped = line.strip()

        m_name = re.search(r"\+-o\s+(.+?)(?:@|\s{2,}|$)", stripped)
        if m_name:
            found = maybe_match()
            if found:
                return found
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

    return maybe_match()


def download_if_needed() -> None:
    VENDOR.mkdir(parents=True, exist_ok=True)

    if ZIP_PATH.is_file() and ZIP_PATH.stat().st_size > 100_000:
        print(f"Using cached official Akai updater: {ZIP_PATH}")
        return

    print("Downloading official Akai MPK Mini 3 macOS v1.26 updater...")
    req = urllib.request.Request(
        AKAI_MAC_URL,
        headers={"User-Agent": "Mozilla/5.0 MPKill8/1.0"},
    )
    tmp = ZIP_PATH.with_suffix(".download")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
            shutil.copyfileobj(resp, out)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    if tmp.stat().st_size < 100_000:
        size = tmp.stat().st_size
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Akai updater download is suspiciously small: {size} bytes")

    tmp.replace(ZIP_PATH)
    print(f"Downloaded: {ZIP_PATH}")


def extract_app() -> Path:
    DIST.mkdir(parents=True, exist_ok=True)

    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)

    # ditto preserves the app bundle's permissions/metadata better than Python
    # zipfile extraction on macOS.
    subprocess.run(
        ["/usr/bin/ditto", "-x", "-k", str(ZIP_PATH), str(WORK)],
        check=True,
    )

    apps = sorted(WORK.rglob("*.app"))
    if not apps:
        raise RuntimeError("No .app bundle found in Akai macOS updater archive.")

    # Prefer the updater-looking bundle if more than one is present.
    app = next(
        (p for p in apps if "mpk" in p.name.lower() and "updat" in p.name.lower()),
        apps[0],
    )

    if PATCHED_APP.exists():
        shutil.rmtree(PATCHED_APP)

    subprocess.run(
        ["/usr/bin/ditto", str(app), str(PATCHED_APP)],
        check=True,
    )
    return PATCHED_APP


def locate_stock_firmware(app: Path) -> tuple[Path, int, bytes]:
    matches: list[tuple[Path, int, bytes]] = []

    for path in app.rglob("*"):
        if not path.is_file():
            continue

        try:
            if path.stat().st_size < REGION_SIZE:
                continue
            data = path.read_bytes()
        except (OSError, PermissionError):
            continue

        start = 0
        while True:
            idx = data.find(FIRMWARE_SIGNATURE, start)
            if idx < 0:
                break
            start = idx + 1

            end = idx + REGION_SIZE
            if end > len(data):
                continue

            region = data[idx:end]
            if sha256(region) == STOCK_SHA256:
                matches.append((path, idx, region))

    if not matches:
        raise RuntimeError(
            "Could not find the exact verified PID 0x1049 / v1.26 firmware "
            "inside Akai's macOS updater. Refusing to patch."
        )

    if len(matches) != 1:
        locations = "\n".join(f"  {p} @ 0x{o:x}" for p, o, _ in matches)
        raise RuntimeError(
            "Found the verified firmware more than once; refusing to guess:\n"
            + locations
        )

    return matches[0]


def patch_firmware(container_file: Path, base: int, stock_region: bytes) -> None:
    if stock_region[PATCH_OFFSET] != 0x08:
        raise RuntimeError(
            f"Expected stock byte 08 at firmware 0x{PATCH_OFFSET:x}; "
            f"found {stock_region[PATCH_OFFSET]:02x}."
        )
    if stock_region[CHECKSUM_OFFSET] != 0xFF:
        raise RuntimeError(
            f"Expected stock checksum byte FF at firmware 0x{CHECKSUM_OFFSET:x}; "
            f"found {stock_region[CHECKSUM_OFFSET]:02x}."
        )

    patched_region = bytearray(stock_region)
    patched_region[PATCH_OFFSET] = 0x07
    patched_region[CHECKSUM_OFFSET] = 0xFE
    patched_region = bytes(patched_region)

    actual = sha256(patched_region)
    if actual != PATCHED_SHA256:
        raise RuntimeError(
            "Patched firmware hash verification failed.\n"
            f"Expected: {PATCHED_SHA256}\n"
            f"Actual:   {actual}"
        )

    blob = bytearray(container_file.read_bytes())
    blob[base : base + REGION_SIZE] = patched_region
    container_file.write_bytes(blob)

    # Read it back from disk and verify the exact embedded region.
    reread = container_file.read_bytes()[base : base + REGION_SIZE]
    if sha256(reread) != PATCHED_SHA256:
        raise RuntimeError("Patched firmware failed read-back verification.")


def resign_and_launch(app: Path) -> None:
    print("Ad-hoc signing patched updater app...")
    subprocess.run(
        ["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(app)],
        check=True,
    )

    # urllib does not normally add quarantine, but clear it recursively if
    # present so the locally modified app is not blocked solely by quarantine.
    subprocess.run(
        ["/usr/bin/xattr", "-dr", "com.apple.quarantine", str(app)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    subprocess.run(
        ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
        check=True,
    )

    print()
    print("PATCH VERIFIED")
    print(f"  Stock firmware:   {STOCK_SHA256}")
    print(f"  Patched firmware: {PATCHED_SHA256}")
    print()
    print("Firmware changes:")
    print("  0x0E5EC: 08 -> 07   (encoder loop processes K1-K7 only)")
    print("  0x1FFFF: FF -> FE   (firmware checksum)")
    print()
    print(f"Patched updater: {app}")
    print()
    print("Launching patched Akai updater...")
    print(
        "When the updater requires firmware-update mode, reconnect the MPK "
        "while holding BANK + PROG SELECT."
    )
    print()

    opened = subprocess.run(
        ["/usr/bin/open", str(app)],
        check=False,
    )
    if opened.returncode == 0:
        return

    print()
    print("macOS LaunchServices refused the modified app wrapper.")
    print("Launching the updater executable directly instead...")

    info_plist = app / "Contents" / "Info.plist"
    if not info_plist.is_file():
        raise RuntimeError(f"Missing Info.plist: {info_plist}")

    with info_plist.open("rb") as fh:
        info = plistlib.load(fh)

    exe_name = info.get("CFBundleExecutable")
    if not exe_name:
        raise RuntimeError("CFBundleExecutable is missing from Info.plist.")

    executable = app / "Contents" / "MacOS" / exe_name
    if not executable.is_file():
        raise RuntimeError(f"Updater executable not found: {executable}")

    executable.chmod(executable.stat().st_mode | 0o111)

    print(f"Executable: {executable}")
    subprocess.Popen(
        [str(executable)],
        cwd=str(executable.parent),
        start_new_session=True,
    )


def main() -> int:
    if sys.platform != "darwin":
        print("This installer is for macOS.")
        print("Use the Windows install.bat only on Windows.")
        return 2

    print()
    print("MPKill8 macOS installer")
    print("=======================")
    print()

    device = detect_target_usb()
    if device is None:
        print(
            "No supported normal-mode MPK Mini 3 was detected "
            "(required VID 09E8 / PID 1049)."
        )
        print("Connect the MPK normally over USB, then run this command again.")
        return 2

    name, vid, pid = device
    print(f"Found supported controller: {name}")
    print(f"  VID 0x{vid:04x}, PID 0x{pid:04x}")
    print()

    try:
        download_if_needed()
        app = extract_app()
        container_file, base, stock_region = locate_stock_firmware(app)

        print("Found exact verified stock firmware:")
        print(f"  file:   {container_file.relative_to(ROOT)}")
        print(f"  offset: 0x{base:x}")
        print(f"  SHA256: {sha256(stock_region)}")
        print()

        patch_firmware(container_file, base, stock_region)
        resign_and_launch(app)
    except Exception as exc:
        print()
        print(f"MPKill8 installer failed: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
