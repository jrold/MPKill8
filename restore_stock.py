#!/usr/bin/env python3
"""Download/extract and launch Akai's untouched macOS v1.26 updater."""

from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


AKAI_MAC_URL = (
    "https://cdn.inmusicbrands.com/akai/mpk3mini/1_26/"
    "MPKmini3_Updater_v1.26.app.zip"
)

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor"
DIST = ROOT / "dist"
ZIP_PATH = VENDOR / "MPKmini3_Updater_v1.26.app.zip"
WORK = DIST / "_stock_mac_updater"


def main() -> int:
    if sys.platform != "darwin":
        print("restore_stock.py is the macOS recovery launcher.")
        return 2

    VENDOR.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)

    if not ZIP_PATH.is_file() or ZIP_PATH.stat().st_size < 100_000:
        print("Downloading official Akai macOS v1.26 updater...")
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
        tmp.replace(ZIP_PATH)

    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)

    subprocess.run(
        ["/usr/bin/ditto", "-x", "-k", str(ZIP_PATH), str(WORK)],
        check=True,
    )

    apps = sorted(WORK.rglob("*.app"))
    if not apps:
        print("No updater app found.")
        return 1

    app = next(
        (p for p in apps if "mpk" in p.name.lower() and "updat" in p.name.lower()),
        apps[0],
    )

    print(f"Launching untouched official updater: {app}")

    # Prefer normal LaunchServices for the untouched vendor app.
    opened = subprocess.run(["/usr/bin/open", str(app)], check=False)
    if opened.returncode == 0:
        return 0

    # Fallback for Apple Silicon / Rosetta environments.
    import plistlib
    info_plist = app / "Contents" / "Info.plist"
    with info_plist.open("rb") as fh:
        info = plistlib.load(fh)
    exe_name = info.get("CFBundleExecutable")
    if not exe_name:
        print("CFBundleExecutable missing from stock updater Info.plist")
        return 1
    exe = app / "Contents" / "MacOS" / exe_name
    if not exe.is_file():
        print(f"Stock updater executable not found: {exe}")
        return 1

    file_out = subprocess.check_output(["/usr/bin/file", str(exe)], text=True)
    cmd = [str(exe)]
    if "x86_64" in file_out:
        cmd = ["/usr/bin/arch", "-x86_64", str(exe)]

    print(f"Launching stock updater executable directly: {exe}")
    subprocess.Popen(cmd, cwd=str(exe.parent), start_new_session=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
