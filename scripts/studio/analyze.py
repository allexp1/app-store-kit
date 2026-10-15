"""Look at the real screenshots and icon: size, light or dark, dominant colours, and the UI blocks (cards,
rows) that a feature-explosion layout may lift out. Measurements only; meaning comes from reading the app."""
from __future__ import annotations

import colorsys
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


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a, b, t):
    """a moved a fraction t of the way to b (both "#RRGGBB")."""
    return hexc([x + (y - x) * t for x, y in zip(_rgb(a), _rgb(b))])


def _hue(h):
    r, g, b = (v / 255 for v in _rgb(h))
    return colorsys.rgb_to_hls(r, g, b)[0] * 360


def _hue_gap(a, b):
    d = abs(_hue(a) - _hue(b)) % 360
    return min(d, 360 - d)


def _lum(h):
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


FALLBACK = {"light": {"bg": "#F4F1EA", "bg2": "#E7E1D5", "ink": "#15140F", "muted": "#6B665C"},
            "dark": {"bg": "#0F1115", "bg2": "#1B1F27", "ink": "#F4F2EC", "muted": "#8B93A1"}}


def suggest_palette(screens: list[dict], icon: dict | None, sources: dict | None = None):
    """A starting palette from the icon (brand) and the screens (UI). The art director refines it.

    bg/bg2 are tints of the brand hue: the app's own most-shared pale (or deep) colour within 20° of the accent,
    else the accent mixed toward white (light apps) or black (dark apps). ink is the accent pushed toward black
    (white) until it reaches 7:1 on bg. The fixed cream / charcoal is only the fallback when no colour in the
    icon or screens reaches chroma 60. `sources`, when given, is filled with where each colour came from."""
    sources = {} if sources is None else sources
    src = (icon or {}).get("palette") or []
    vivid = sorted([c for c in src if c["chroma"] > 60], key=lambda c: -c["share"])
    origin = "icon"
    if not vivid:
        allc = [c for s in screens for c in s["palette"] if c["chroma"] > 60]
        vivid = sorted(allc, key=lambda c: -c["share"])
        origin = "screens"
    dark = sum(1 for s in screens if s["appearance"] == "dark") > len(screens) / 2
    mode = "dark" if dark else "light"
    if not vivid:
        sources.update({k: f"fallback {mode} neutral (no colour reaches chroma 60)"
                        for k in ("bg", "bg2", "ink", "muted", "accent", "accent2")})
        return {**FALLBACK[mode], "accent": "#FF5A36", "accent2": "#2D5BFF", "dark": "#0E0F12", "light": "#FFFFFF"}
    accent = vivid[0]["hex"]
    accent2 = next((c["hex"] for c in vivid[1:] if _hue_gap(c["hex"], accent) > 25), None)
    sources["accent"] = f"most-shared vivid colour of the {origin}"
    sources["accent2"] = (f"next vivid colour of the {origin} with another hue" if accent2
                          else "accent mixed 35% toward black (no second hue in the app)")
    accent2 = accent2 or _mix(accent, "#000000", 0.35)
    target = "#000000" if dark else "#FFFFFF"
    pale = [c for s in screens + ([icon] if icon else []) for c in s["palette"]
            if c["chroma"] <= 40 and c["chroma"] >= 4 and _hue_gap(c["hex"], accent) <= 20
            and ((_lum(c["hex"]) < 0.05) if dark else (_lum(c["hex"]) > 0.6))]
    if pale:
        best = max(pale, key=lambda c: c["share"])
        bg = best["hex"]
        bg2 = _mix(bg, accent, 0.10)
        sources["bg"] = "the app's most-shared low-chroma tint of the accent hue"
        sources["bg2"] = "bg moved 10% toward the accent"
    else:
        bg = _mix(accent, target, 0.86 if dark else 0.90)
        bg2 = _mix(accent, target, 0.76 if dark else 0.80)
        sources["bg"] = f"accent mixed {'86% toward black' if dark else '90% toward white'}"
        sources["bg2"] = f"accent mixed {'76% toward black' if dark else '80% toward white'}"
    away = "#FFFFFF" if dark else "#000000"
    t = 0.75
    ink = _mix(accent, away, t)
    while contrast(ink, bg) < 7 and t < 1:
        t = min(1.0, t + 0.03)
        ink = _mix(accent, away, t)
    sources["ink"] = f"accent mixed {round(t * 100)}% toward {'white' if dark else 'black'} ({contrast(ink, bg):.1f}:1 on bg)"
    muted = _mix(ink, bg, 0.42)
    sources["muted"] = "ink mixed 42% toward bg"
    return {"bg": bg, "bg2": bg2, "ink": ink, "muted": muted, "accent": accent, "accent2": accent2,
            "dark": "#0E0F12", "light": "#FFFFFF"}
