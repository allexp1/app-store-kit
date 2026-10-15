"""Look at the real screenshots and icon: size, light or dark, dominant colours, and the UI blocks (cards,
rows) that a feature-explosion layout may lift out. Measurements only; meaning comes from reading the app."""
from __future__ import annotations

import pathlib

from PIL import Image, ImageFilter, ImageStat


def hexc(rgb):
    return "#%02X%02X%02X" % tuple(int(v) for v in rgb[:3])


def palette(img: Image.Image, n=6):
    small = img.convert("RGB").resize((96, int(96 * img.height / img.width)))
    q = small.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[: n * 3]
    counts = sorted(q.getcolors(), reverse=True)
    out = []
    for cnt, idx in counts:
        rgb = pal[idx * 3: idx * 3 + 3]
        out.append({"hex": hexc(rgb), "share": round(cnt / (small.width * small.height), 3),
                    "chroma": max(rgb) - min(rgb)})
    return out


def ui_blocks(img: Image.Image, min_h=0.045, max_n=4):
    """Horizontal content blocks, separated by rows of nearly uniform colour. Returns fractions [x, y, w, h].

    Skips the status bar (top 6%) and the home indicator / tab bar (bottom 10%); a block must be 4.5–40% of
    the height. A heuristic: check the pick by eye, or set storyboard[].highlights by hand."""
    g = img.convert("L").filter(ImageFilter.GaussianBlur(1))
    w, h = g.size
    step = max(1, h // 700)
    rows = []
    for y in range(0, h, step):
        row = g.crop((int(w * 0.04), y, int(w * 0.96), y + 1))
        rows.append((y, ImageStat.Stat(row).stddev[0]))
    busy = [s > 6 for _, s in rows]
    blocks, start = [], None
    for k, (y, _) in enumerate(rows):
        if busy[k] and start is None:
            start = y
        elif not busy[k] and start is not None:
            blocks.append((start, y))
            start = None
    if start is not None:
        blocks.append((start, h))
    out = []
    for y0, y1 in blocks:
        if y0 < h * 0.06 or y1 > h * 0.9:
            continue
        bh = (y1 - y0) / h
        if min_h <= bh <= 0.4:
            pad = 0.008
            out.append([0.03, round(max(0, y0 / h - pad), 4), 0.94, round(min(1, bh + 2 * pad), 4)])
    out.sort(key=lambda b: -b[3])
    return out[:max_n]


def describe(path: pathlib.Path):
    with Image.open(path) as im:
        im.load()
        rgb = im.convert("RGB")
        lum = ImageStat.Stat(rgb.convert("L")).mean[0] / 255
        return {"file": str(path), "size": list(im.size), "aspect": round(im.height / im.width, 4),
                "mode": im.mode, "alpha": im.mode in ("RGBA", "LA") or "transparency" in im.info,
                "luminance": round(lum, 3), "appearance": "dark" if lum < 0.4 else "light",
                "palette": palette(rgb), "blocks": ui_blocks(rgb)}


def suggest_palette(screens: list[dict], icon: dict | None):
    """A starting palette from the icon (brand) and the screens (UI). The art director refines it."""
    src = (icon or {}).get("palette") or []
    vivid = sorted([c for c in src if c["chroma"] > 60], key=lambda c: -c["share"])
    if not vivid:
        allc = [c for s in screens for c in s["palette"] if c["chroma"] > 60]
        vivid = sorted(allc, key=lambda c: -c["share"])
    accent = vivid[0]["hex"] if vivid else "#FF5A36"
    accent2 = vivid[1]["hex"] if len(vivid) > 1 else "#2D5BFF"
    dark = sum(1 for s in screens if s["appearance"] == "dark") > len(screens) / 2
    return {"bg": "#0F1115" if dark else "#F4F1EA", "bg2": "#1B1F27" if dark else "#E7E1D5",
            "ink": "#F4F2EC" if dark else "#15140F", "muted": "#8B93A1" if dark else "#6B665C",
            "accent": accent, "accent2": accent2, "dark": "#0E0F12", "light": "#FFFFFF"}
