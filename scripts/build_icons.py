#!/usr/bin/env python3
"""Export the source SVG to home-screen icons. Requires requirements-dev.txt."""
from __future__ import annotations

import argparse
from pathlib import Path
import struct

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "app" / "static" / "icons"
SIZES = {"icon-192.png": 192, "icon-512.png": 512,
         "icon-maskable-512.png": 512, "apple-touch-icon.png": 180, "favicon-32.png": 32}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", help="Optional Chrome/Chromium executable")
    args = parser.parse_args()
    svg = (ICONS / "icon.svg").read_text(encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.browser, headless=True)
        page = browser.new_page(device_scale_factor=1)
        for name, size in SIZES.items():
            page.set_viewport_size({"width": size, "height": size})
            page.set_content('<style>html,body{margin:0}svg{display:block;width:100vw;height:100vh}</style>' + svg)
            page.screenshot(path=str(ICONS / name), animations="disabled")
        browser.close()
    # Standard ICO header containing the 32px PNG for older favicon clients.
    png = (ICONS / "favicon-32.png").read_bytes()
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 32, 32, 0, 0, 1, 32, len(png), 22)
    (ICONS / "favicon.ico").write_bytes(header + entry + png)
    print("Exported iPhone, Android, maskable and browser icons.")


if __name__ == "__main__":
    main()
