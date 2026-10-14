#!/usr/bin/env python3
"""Render a header / search-results creative asset from HTML, and a preview with Apple's safe areas drawn on it.

Usage:
  render_creative.py HTML --out KIT/creative/<locale>/universal.png [--kind universal|header|search]
                     [--set NAME=FILE ...] [--guides PREVIEW.jpg] [--renderer auto|playwright|chrome]

HTML is a page whose first element has class "frame" and the asset's exact size (templates/creative-universal.html
is a starting point). {{NAME}} placeholders are filled with --set NAME=FILE as data URIs, or NAME=#hex / text.
The PNG comes out RGB with no alpha, which Apple requires. --guides writes a small JPEG with the art safe areas
from Apple's Figma template (apple-specs.md › Creative assets): yellow = this asset's safe area; on a universal
asset, cyan = the header (21:9) and search (3:2) crops and magenta = their safe areas.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile

from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render  # noqa: E402

# Frame size and "Art Safe Area" (x0, y0, x1, y1), read from Apple's creative assets Figma template
# (developer.apple.com/go/?id=figma-creative-assets-templates, file dated 2026-08-05).
FRAMES = {
    "universal": ((5244, 2950), (1921, 660, 3323, 1622)),
    "search": ((3840, 2560), (836, 765, 3004, 1795)),
    "header": ((3840, 1646), (1097, 493, 2743, 1154)),
}


def crops_on_universal():
    """Where the header (21:9) and search-results (3:2) crops and their safe areas fall on a universal asset,
    assuming a centred crop scaled to the full width or height (UNCONFIRMED: check with App Store Connect's
    Preview button)."""
    (W, H), _ = FRAMES["universal"]
    out = []
    for kind in ("header", "search"):
        (w, h), (x0, y0, x1, y1) = FRAMES[kind]
        k = min(W / w, H / h)
        cw, ch = w * k, h * k
        ox, oy = (W - cw) / 2, (H - ch) / 2
        out.append(((ox, oy, ox + cw, oy + ch), (ox + x0 * k, oy + y0 * k, ox + x1 * k, oy + y1 * k)))
    return out


def guides(png, kind, out):
    im = Image.open(png).convert("RGB")
    d = ImageDraw.Draw(im)
    lw = max(4, im.width // 500)
    d.rectangle(FRAMES[kind][1], outline=(255, 214, 0), width=lw)
    if kind == "universal":
        for crop, safe in crops_on_universal():
            d.rectangle(crop, outline=(0, 200, 255), width=lw)
            d.rectangle(safe, outline=(255, 0, 255), width=lw)
    im.thumbnail((1600, 1600))
    im.save(out, quality=88)


def values(pairs):
    out = {}
    for p in pairs or []:
        k, _, v = p.partition("=")
        f = pathlib.Path(v).expanduser()
        out[k] = render.data_uri(f) if f.is_file() else v
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("html")
    ap.add_argument("--out", required=True)
    ap.add_argument("--kind", default="universal", choices=sorted(FRAMES))
    ap.add_argument("--set", action="append", metavar="NAME=FILE")
    ap.add_argument("--guides")
    ap.add_argument("--renderer", default="auto", choices=["auto", "playwright", "chrome"])
    a = ap.parse_args(argv)
    (w, h), _ = FRAMES[a.kind]
    src = render.fill(pathlib.Path(a.html).read_text(), values(a.set))
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        page = pathlib.Path(tmp) / "creative.html"
        page.write_text(src)
        kind, chrome = render.pick_renderer(a.renderer)
        if kind == "playwright":
            render.shoot_playwright(page, out, w, h)
        else:
            render.shoot_chrome(page, out, w, h, chrome)
    render.finish_png(out, w, h)
    print(f"wrote {out} ({w}x{h}, RGB)")
    if a.guides:
        guides(out, a.kind, a.guides)
        print(f"wrote {a.guides} (safe areas drawn)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
