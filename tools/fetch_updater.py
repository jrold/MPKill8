#!/usr/bin/env python3
"""
Download the official Akai MPK Mini MK3 v1.26 updater and immediately scan it.

Akai's current support article links to these official CDN endpoints:
  Win: https://cdn.inmusicbrands.com/akai/mpk3mini/1_26/MPKmini3_Updater_v1.26_WIN.zip
  Mac: https://cdn.inmusicbrands.com/akai/mpk3mini/1_26/MPKmini3_Updater_v1.26.app.zip

Run on the user's normal machine; this environment may block binary downloads.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import urllib.request
from pathlib import Path


URLS = {
    "win": "https://cdn.inmusicbrands.com/akai/mpk3mini/1_26/MPKmini3_Updater_v1.26_WIN.zip",
    "mac": "https://cdn.inmusicbrands.com/akai/mpk3mini/1_26/MPKmini3_Updater_v1.26.app.zip",
}

DEFAULT_NAMES = {
    "win": "MPKmini3_Updater_v1.26_WIN.zip",
    "mac": "MPKmini3_Updater_v1.26.app.zip",
}


def download(url: str, out: Path) -> None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 MPKill8/1.0",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        final_url = resp.geturl()
        content_type = resp.headers.get("Content-Type", "")
        disposition = resp.headers.get("Content-Disposition", "")
        data = resp.read()

    if len(data) < 100_000:
        preview = data[:200].decode("utf-8", errors="replace")
        raise RuntimeError(
            f"download is suspiciously small ({len(data)} bytes). "
            f"Content-Type={content_type!r}; preview={preview!r}"
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()

    print(f"Downloaded {len(data):,} bytes")
    print(f"Final URL: {final_url}")
    print(f"Content-Type: {content_type}")
    if disposition:
        print(f"Content-Disposition: {disposition}")
    print(f"SHA-256: {sha}")
    print(f"Saved: {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("platform", choices=("win", "mac"))
    ap.add_argument("--output", type=Path)
    ap.add_argument(
        "--no-scan",
        action="store_true",
        help="download only; do not invoke scan_updater.py",
    )
    args = ap.parse_args()

    out = args.output or Path("vendor") / DEFAULT_NAMES[args.platform]
    download(URLS[args.platform], out)

    if not args.no_scan:
        scan = Path(__file__).with_name("scan_updater.py")
        extract_dir = Path("dumps") / args.platform
        print("\nScanning for STM32 firmware payloads...")
        return subprocess.call(
            [sys.executable, str(scan), str(out), "--extract-dir", str(extract_dir)]
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
