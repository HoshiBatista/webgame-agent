"""Rasterize the existing brand SVG for Safari and legacy favicon clients."""

import os
import struct
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "web/public"
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".data/native-validator/browsers"))


def main():
    svg = (PUBLIC / "assets/beeline-logo.svg").read_text()
    pngs = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.route("**/*", lambda route: route.abort())
        for size in (16, 32, 48, 180):
            page.set_viewport_size({"width": size, "height": size})
            style = (
                "body{background:#f7f5ef;display:grid;place-items:center}"
                "svg{width:140px;height:140px}"
                if size == 180 else "svg{width:100vw;height:100vh}"
            )
            page.set_content(f"<style>html,body{{margin:0;width:100%;height:100%}}{style}</style>{svg}")
            path = PUBLIC / (
                "apple-touch-icon.png" if size == 180 else f"assets/favicon-{size}x{size}.png"
            )
            png = page.screenshot(path=str(path), omit_background=size != 180)
            if size != 180:
                pngs.append((size, png))
        browser.close()
    # Each ICO entry retains its original PNG pixels without resampling the vector render.
    offset = 6 + 16 * len(pngs)
    entries = []
    for size, png in pngs:
        entries.append(struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(png), offset))
        offset += len(png)
    (PUBLIC / "favicon.ico").write_bytes(
        struct.pack("<HHH", 0, 1, len(pngs)) + b"".join(entries) + b"".join(png for _, png in pngs)
    )
    print("Created PNG icons (16/32/48/180px) and multi-size ICO.")


if __name__ == "__main__":
    main()
