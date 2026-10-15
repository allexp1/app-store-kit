"""Build the master-canvas HTML for one locale and slot.

The master canvas is N panels wide (N x W by H). Everything is placed on it in campaign units, rendered once,
and sliced at exact pixel boundaries, so anything may cross a panel edge and the seams always match.

Units
  x      panels, measured from the left edge of panel 1 (x = 1.5 is the middle of panel 2)
  y      fraction of the panel height (0 top, 1 bottom)
  w, h   u, where u = min(W, H / 2.17): one phone-shaped panel width. The same layer reads right on an iPhone
         slot (u = W) and an iPad slot (u < W), so one layout serves every slot.
  size   u (font sizes)
Text blocks are the exception: `panel` (1-based) plus x / y / w as fractions of that panel.
"""
from __future__ import annotations

import html
import json
import math
import pathlib
import random
import re

from PIL import Image

from . import devices, fonts
from .spec import ACCENT_STYLES, HEX, screen_path, text_for  # noqa: F401  (ACCENT_STYLES re-exported)

ROLE_DEFAULTS = {
    # size (u), max lines, font, leading, tracking (em)
    "kicker": {"size": 0.034, "max_lines": 1, "font": "mono", "leading": 1.2, "tracking": 0.14, "case": "uppercase"},
    "headline": {"size": 0.112, "max_lines": 3, "font": "display"},
    "sub": {"size": 0.043, "max_lines": 3, "font": "text", "leading": 1.28, "tracking": -0.005},
    "label": {"size": 0.032, "max_lines": 2, "font": "text", "leading": 1.25, "tracking": 0.0},
    "big": {"size": 0.2, "max_lines": 2, "font": "display"},
    "stat": {"size": 0.17, "max_lines": 1, "font": "display", "leading": 1.0, "tracking": -0.03},
    "footnote": {"size": 0.026, "max_lines": 4, "font": "text", "leading": 1.3, "tracking": 0.0},
    "chips": {"size": 0.034, "max_lines": 2, "font": "text", "leading": 2.1, "tracking": 0.0, "weight": 600},
}
CHIP_STYLES = ("glass", "solid", "outline", "sticker")
SERIF_ACCENT = "Instrument Serif"   # the face the `serif` accent style swaps to (loaded when that style is used)
BLOB_RADIUS = "58% 42% 55% 45% / 46% 56% 44% 54%"   # image `mask: blob`: an organic rounded shape
MIN_HEADLINE_U = 0.06   # below this a headline stops reading in a store thumbnail


def unit(W, H):
    return min(W, H / 2.17)


def color(tok, palette, default="#000000"):
    """'accent', 'accent@0.4', '#hex', '#hex@0.5', 'rgba(...)', 'transparent'."""
    if tok is None:
        return default
    tok = str(tok)
    alpha = None
    if "@" in tok:
        tok, a = tok.split("@", 1)
        alpha = float(a)
    c = palette.get(tok, tok)
    if alpha is None or not HEX.match(c):
        return c
    h = c.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def luminance(hexc):
    h = hexc.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


class Ctx:
    def __init__(self, spec, locale, slot_id, W, H, mirror):
        self.spec, self.locale, self.slot, self.W, self.H = spec, locale, slot_id, W, H
        self.N = spec["campaign"]["panels"]
        self.u = unit(W, H)
        self.mirror = mirror
        self.palette = spec["design"]["palette"]
        self.base = pathlib.Path(spec["_base"])
        self.shots = {}

    def X(self, x):  # campaign x (panels) -> canvas px
        return ((self.N - x) if self.mirror else x) * self.W

    def Y(self, y):
        return y * self.H

    def U(self, v):
        return v * self.u

    def rot(self, r):
        rx, ry, rz = (list(r or []) + [0, 0, 0])[:3]
        return (rx, -ry, -rz) if self.mirror else (rx, ry, rz)

    def col(self, tok, default="#000000"):
        return color(tok, self.palette, default)

    def shot(self, sid):
        if sid not in self.shots:
            p, _ = screen_path(self.spec, sid, self.locale, self.slot)
            if p is None or not p.exists():
                raise FileNotFoundError(f"screen {sid!r} for {self.locale}/{self.slot}: {p} not found")
            with Image.open(p) as im:
                self.shots[sid] = (p.resolve().as_uri(), im.width, im.height)
        return self.shots[sid]


def _bg(ctx, B):
    t = B["type"]
    MW, H = ctx.N * ctx.W, ctx.H
    op = B.get("opacity", 1)
    blend = f"mix-blend-mode:{B['blend']};" if B.get("blend") else ""
    if t == "solid":
        css = f"background:{ctx.col(B['color'])}"
        box = (0, 0, MW, H)
    elif t == "linear":
        ang = float(B.get("angle", 90))
        if ctx.mirror:
            ang = (360 - ang) % 360
        stops = ",".join(f"{ctx.col(c)} {p * 100 if p <= 1 else p:.1f}%" for c, p in B["stops"])
        css = f"background:linear-gradient({ang}deg,{stops})"
        box = (0, 0, MW, H)
    elif t == "radial":
        cx, cy = ctx.X(B["x"]), ctx.Y(B["y"])
        rx = ctx.U(B.get("r", 1.0))
        ry = ctx.U(B.get("ry", B.get("r", 1.0)))
        c = ctx.col(B["color"])
        css = (f"background:radial-gradient({rx:.0f}px {ry:.0f}px at {cx:.0f}px {cy:.0f}px,{c} 0%,"
               f"{ctx.col(B.get('to', 'transparent'))} {B.get('falloff', 1.0) * 100:.0f}%)")
        box = (0, 0, MW, H)
    elif t == "conic":
        cx, cy = ctx.X(B["x"]), ctx.Y(B["y"])
        stops = ",".join(f"{ctx.col(c)} {p * 100:.1f}%" for c, p in B["stops"])
        css = f"background:conic-gradient(from {B.get('from', 0)}deg at {cx:.0f}px {cy:.0f}px,{stops})"
        box = (0, 0, MW, H)
    elif t == "panel":
        p = int(B["panel"])
        left = ctx.X(p - 1) if not ctx.mirror else ctx.X(p)
        fill = ctx.col(B["color"]) if "color" in B else (
            "linear-gradient({}deg,{})".format(B.get("angle", 180),
                                               ",".join(f"{ctx.col(c)} {q * 100:.1f}%" for c, q in B["stops"])))
        css = f"background:{fill}"
        box = (left, 0, ctx.W, H)
    elif t == "image":
        a = ctx.spec["artwork"][B["art"]]
        uri = (ctx.base / a["file"]).resolve().as_uri()
        css = f"background:url('{uri}') center/{B.get('fit', 'cover')} no-repeat"
        box = (0, 0, MW, H)
    else:
        raise ValueError(f"background type {t}")
    x, y, w, h = box
    return (f'<div class="bg" style="left:{x:.0f}px;top:{y:.0f}px;width:{w:.0f}px;height:{h:.0f}px;'
            f'opacity:{op};{blend}{css}"></div>')


def _smooth_closed(pts):
    """Catmull-Rom through closed points -> cubic Bezier path."""
    n = len(pts)
    d = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
    for i in range(n):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d += f" C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}"
    return d + " Z"


def _smooth_open(pts):
    d = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
    for i in range(len(pts) - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < len(pts) else p2
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d += f" C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}"
    return d


def _fill(ctx, S, defs, key):
    """A fill: token/hex, or {linear: [[c, p]...], angle} -> gradient def id."""
    f = S.get("fill", "accent")
    if isinstance(f, dict) and "stops" in f:
        gid = f"g{key}"
        a = math.radians(f.get("angle", 90) - 90)
        x2, y2 = 0.5 + 0.5 * math.cos(a), 0.5 + 0.5 * math.sin(a)
        stops = "".join(f'<stop offset="{p}" stop-color="{ctx.col(c)}"/>' for c, p in f["stops"])
        defs.append(f'<linearGradient id="{gid}" x1="{1 - x2:.3f}" y1="{1 - y2:.3f}" x2="{x2:.3f}" y2="{y2:.3f}">'
                    f'{stops}</linearGradient>')
        return f"url(#{gid})"
    return ctx.col(f)


def _shape(ctx, S, key, defs):
    """One SVG element in logical (unmirrored) canvas coordinates; the whole SVG is mirrored for RTL."""
    k = S["kind"]
    X = lambda x: x * ctx.W  # noqa: E731  logical
    Y, U = ctx.Y, ctx.U
    op = S.get("opacity", 1)
    rng = random.Random(f"{ctx.spec['campaign']['seed']}-{key}")
    blur = f' filter="url(#blur{key})"' if S.get("blur") else ""
    if S.get("blur"):
        defs.append(f'<filter id="blur{key}" x="-50%" y="-50%" width="200%" height="200%">'
                    f'<feGaussianBlur stdDeviation="{U(S["blur"]):.1f}"/></filter>')
    if k == "blob":
        cx, cy, r = X(S["x"]), Y(S["y"]), U(S.get("r", 0.6))
        n, wob = int(S.get("points", 7)), float(S.get("wobble", 0.22))
        pts = []
        for i in range(n):
            a = 2 * math.pi * i / n + rng.uniform(-0.2, 0.2)
            rr = r * (1 + rng.uniform(-wob, wob))
            pts.append((cx + rr * math.cos(a) * S.get("sx", 1), cy + rr * math.sin(a) * S.get("sy", 1)))
        return f'<path d="{_smooth_closed(pts)}" fill="{_fill(ctx, S, defs, key)}" opacity="{op}"{blur}/>'
    if k == "wave":
        # a band across the whole canvas: centre line y, amplitude, cycles, thickness; ties the panels together
        MW = ctx.N * ctx.W
        y0, amp, cyc = Y(S.get("y", 0.7)), Y(S.get("amp", 0.06)), float(S.get("cycles", ctx.N / 2))
        th = Y(S.get("thickness", 0.25))
        ph = S.get("phase", rng.uniform(0, math.tau))
        steps = max(24, ctx.N * 12)
        top = [(MW * i / steps, y0 + amp * math.sin(ph + math.tau * cyc * i / steps)) for i in range(steps + 1)]
        if S.get("to_bottom", True):
            d = _smooth_open(top) + f" L{MW:.0f},{ctx.H:.0f} L0,{ctx.H:.0f} Z"
        else:
            bot = [(x, y + th + amp * 0.35 * math.sin(ph * 1.7 + math.tau * cyc * 1.3 * i / steps))
                   for i, (x, y) in enumerate(top)][::-1]
            d = _smooth_open(top) + " L" + _smooth_open(bot)[1:] + " Z"
        return f'<path d="{d}" fill="{_fill(ctx, S, defs, key)}" opacity="{op}"{blur}/>'
    if k == "ring":
        cx, cy, r = X(S["x"]), Y(S["y"]), U(S.get("r", 0.5))
        return (f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="none" stroke="{ctx.col(S.get("stroke", "accent"))}" '
                f'stroke-width="{U(S.get("width", 0.01)):.1f}" opacity="{op}"'
                + (f' stroke-dasharray="{U(S["dash"]):.1f} {U(S["dash"]):.1f}"' if S.get("dash") else "") + f"{blur}/>")
    if k == "circle":
        cx, cy, r = X(S["x"]), Y(S["y"]), U(S.get("r", 0.5))
        return f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{_fill(ctx, S, defs, key)}" opacity="{op}"{blur}/>'
    if k == "path":
        pts = [(X(x), Y(y)) for x, y in S["points"]]
        dash = f' stroke-dasharray="{U(S["dash"]):.1f} {U(S.get("gap", S["dash"])):.1f}"' if S.get("dash") else ""
        return (f'<path d="{_smooth_open(pts)}" fill="none" stroke="{ctx.col(S.get("stroke", "ink"))}" '
                f'stroke-width="{U(S.get("width", 0.008)):.1f}" stroke-linecap="round" opacity="{op}"{dash}{blur}/>')
    if k == "rect":
        x, y, w, h = X(S["x"]), Y(S["y"]), U(S["w"]), U(S["h"])
        rot = S.get("rotate", 0)
        return (f'<rect x="{x - w / 2:.1f}" y="{y - h / 2:.1f}" width="{w:.1f}" height="{h:.1f}" '
                f'rx="{U(S.get("radius", 0)):.1f}" fill="{_fill(ctx, S, defs, key)}" opacity="{op}" '
                f'transform="rotate({rot} {x:.1f} {y:.1f})"{blur}/>')
    if k == "dots":
        x0, y0, w, h = X(S["x"]), Y(S["y"]), U(S["w"]), U(S["h"])
        gap, r = U(S.get("gap", 0.04)), U(S.get("r", 0.005))
        pid = f"dots{key}"
        defs.append(f'<pattern id="{pid}" width="{gap:.1f}" height="{gap:.1f}" patternUnits="userSpaceOnUse">'
                    f'<circle cx="{gap / 2:.1f}" cy="{gap / 2:.1f}" r="{r:.1f}" fill="{ctx.col(S.get("fill", "ink"))}"/></pattern>')
        return f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h:.1f}" fill="url(#{pid})" opacity="{op}"/>'
    if k == "arc":
        cx, cy, r = X(S["x"]), Y(S["y"]), U(S.get("r", 0.6))
        a0, a1 = math.radians(S.get("from", 200)), math.radians(S.get("to", 340))
        p0 = (cx + r * math.cos(a0), cy + r * math.sin(a0))
        p1 = (cx + r * math.cos(a1), cy + r * math.sin(a1))
        large = 1 if (S.get("to", 340) - S.get("from", 200)) % 360 > 180 else 0
        return (f'<path d="M{p0[0]:.1f},{p0[1]:.1f} A{r:.1f},{r:.1f} 0 {large} 1 {p1[0]:.1f},{p1[1]:.1f}" fill="none" '
                f'stroke="{ctx.col(S.get("stroke", "accent"))}" stroke-width="{U(S.get("width", 0.02)):.1f}" '
                f'stroke-linecap="round" opacity="{op}"{blur}/>')
    raise ValueError(f"shape kind {k!r}")


def _on(ctx, tok):
    """ink or light, whichever reads better on this colour token (for text inside a pill or chip)."""
    c = ctx.col(str(tok).split("@")[0])
    if not HEX.match(c):
        return ctx.col("light")
    ink, light = ctx.col("ink"), ctx.col("light")
    lc = luminance(c)
    cr = lambda a: (max(luminance(a), lc) + 0.05) / (min(luminance(a), lc) + 0.05)  # noqa: E731
    return ink if cr(ink) >= cr(light) else light


def _chips(items):
    return "".join(f'<span class="chip">{html.escape(str(x))}</span>' for x in items if str(x).strip())


def _richtext(text, accent_style):
    """**word** marks the accent; newlines are kept as line breaks."""
    out = []
    for i, part in enumerate(re.split(r"\*\*", text)):
        esc = html.escape(part).replace("\n", "<br>")
        out.append(f'<span class="acc acc-{accent_style}">{esc}</span>' if i % 2 else esc)
    return "".join(out)


def _font_css(info, which, scripts):
    f = info[which] if which in info else info["text"]
    fam = fonts.stack(f["family"], scripts)
    generic = "serif" if f["family"] in fonts.SERIF_FACES else "sans-serif"
    return fonts.css_stack(fam, generic), f


def _text_block(ctx, L, idx, finfo, fit):
    loc, prim = ctx.locale, ctx.spec["campaign"]["primary_locale"]
    sb = {p["id"]: p for p in ctx.spec["storyboard"]}
    p = int(L["panel"])
    rtl = fonts.is_rtl(loc)
    lp = (ctx.N + 1 - p) if ctx.mirror else p
    W, H = ctx.W, ctx.H
    x, w = L.get("x", 0.08), L.get("w", 0.84)
    if ctx.mirror:
        x = 1 - x - w
    left = (lp - 1) * W + x * W
    align = L.get("align", "start")
    if align in ("left", "right"):
        align = {"left": "start", "right": "end"}[align]
        if ctx.mirror:
            align = {"start": "end", "end": "start"}[align]
    anchor = L.get("anchor", "top")
    items = L.get("items") or [{"role": L.get("role", "headline"), "copy": L.get("copy"), "text": L.get("text")}]
    rows, meta = [], []
    for j, it in enumerate(items):
        role = it.get("role", "headline")
        rd = {**ROLE_DEFAULTS.get(role, ROLE_DEFAULTS["sub"]), **{k: v for k, v in it.items() if k not in ("copy", "text")}}
        if it.get("text") is not None:
            t, _ = text_for(it["text"], loc, prim)
        else:
            ref = it.get("copy") or ""
            pid, _, field = ref.partition(".")
            t, _ = text_for(sb.get(pid, {}).get(field or role), loc, prim)
        chips = None
        if isinstance(t, list):
            chips = [str(x) for x in t if str(x).strip()]
            t = " · ".join(chips)
        if not t:
            continue
        scripts = fonts.scripts_in(t, loc)
        stack, f = _font_css(finfo, rd.get("font", "text"), scripts)
        tid = f"t{idx}-{j}"
        size_u = rd["size"] * (finfo["display"].get("scale", 1.0) if rd.get("font") == "display" else 1.0)
        fs = fit.get(tid, ctx.U(size_u))
        lead = rd.get("leading", f.get("leading", 1.05))
        track = rd.get("tracking", f.get("tracking", 0))
        case = rd.get("case", f.get("case", "none"))
        weight = rd.get("weight", f.get("weight", 400))
        colr = ctx.col(it.get("color", L.get("color", "ink")))
        skew = f.get("skew", 0) if rd.get("font") == "display" else 0
        style = (f"font-family:{stack};font-size:{fs:.2f}px;line-height:{lead};letter-spacing:{track}em;"
                 f"font-weight:{weight};text-transform:{case};color:{colr};"
                 + (f"transform:skewX({skew}deg);" if skew else "")
                 + (f"text-shadow:{it.get('shadow') or L.get('shadow')};" if (it.get('shadow') or L.get('shadow')) else "")
                 + (f"opacity:{it['opacity']};" if "opacity" in it else ""))
        acc_tok = it.get("accent", L.get("accent", "accent"))
        acc_col = ctx.col(acc_tok)
        acc_style = it.get("accent_style", L.get("accent_style", finfo["accent_style"]))
        chip_tok = it.get("chip_fill", L.get("chip_fill", acc_tok))
        style += (f"--acc2:{ctx.col(it.get('accent2', L.get('accent2', 'accent2')))};--on-acc:{_on(ctx, acc_tok)};"
                  f"--chip:{ctx.col(chip_tok)};--on-chip:{_on(ctx, chip_tok)};")
        if role == "footnote":
            # small print over a phone or a busy scene: give it its own quiet backing so it stays readable
            base = ctx.col(str(it.get("color", L.get("color", "ink"))).split("@")[0])
            back = "dark@0.72" if HEX.match(base) and luminance(base) > 0.4 else "light@0.82"
            style += (f"background:{ctx.col(back)};padding:.45em .75em;border-radius:.7em;"
                      f"align-self:flex-start;")
        body = _chips(chips) if chips is not None else _richtext(t, acc_style)
        extra = f" chips-{L.get('chip_style', 'glass')}" if chips is not None else ""
        rows.append(f'<div class="t t-{role}{extra}" data-tid="{tid}" data-fit="1" data-size="{fs:.2f}" '
                    f'data-min="{ctx.U(rd.get("min", MIN_HEADLINE_U if role == "headline" else 0.026)):.2f}" '
                    f'data-max-lines="{rd["max_lines"]}" data-lh="{lead}" data-role="{role}" '
                    f'data-family="{html.escape(f["family"], quote=True)}" data-weight="{weight}" '
                    f'style="{style}--acc:{acc_col}">{body}</div>')
        meta.append({"tid": tid, "role": role, "text": t, "panel": p, "family": f["family"], "scripts": sorted(scripts)})
    if not rows:
        return "", []
    top = ctx.Y(L.get("y", 0.06))
    pos = f"top:{top:.1f}px;" if anchor == "top" else f"bottom:{ctx.H - top:.1f}px;"
    gap = ctx.U(L.get("gap", 0.022))
    z = f"z-index:{L['z']};" if "z" in L else "z-index:50;"
    block = (f'<div class="tx" data-id="text{idx}" data-kind="text" data-panel="{p}" '
             f'dir="{"rtl" if rtl else "ltr"}" lang="{html.escape(loc)}" '
             f'style="left:{left:.1f}px;width:{w * W:.1f}px;{pos}gap:{gap:.1f}px;text-align:{align};{z}">'
             + "".join(rows) + "</div>")
    return block, meta


def build(spec, locale, slot_id, W, H, layout, finfo, font_css, fit=None, mirror=False, hide_text=False,
          measure=True, slices=None):
    """layout = {'background': [...], 'layers': [...]} with every value already resolved."""
    fit = fit or {}
    ctx = Ctx(spec, locale, slot_id, W, H, mirror)
    MW = ctx.N * W
    d = spec["design"]
    dev = d["device"]
    parts, texts, elements = [], [], []
    for B in layout.get("background") or []:
        parts.append(_bg(ctx, B))
    defs, svg_low, svg_high = [], [], []
    for i, L in enumerate(layout.get("layers") or []):
        t = L["type"]
        z = L.get("z")
        if t == "shape":
            (svg_high if (z or 0) >= 10 else svg_low).append(_shape(ctx, L, f"{i}", defs))
        elif t == "glow":
            cx, cy, r = ctx.X(L["x"]), ctx.Y(L["y"]), ctx.U(L.get("r", 0.8))
            parts.append(f'<div class="glow" style="left:{cx - r:.0f}px;top:{cy - r:.0f}px;width:{2 * r:.0f}px;'
                         f'height:{2 * r:.0f}px;background:radial-gradient(closest-side,{ctx.col(L.get("color", "accent"))},'
                         f'transparent);opacity:{L.get("opacity", 0.6)};{"z-index:%s;" % z if z is not None else ""}'
                         f'{"mix-blend-mode:%s;" % L["blend"] if L.get("blend") else ""}"></div>')
        elif t == "device":
            uri, sw, sh = ctx.shot(L["screen"])
            model = L.get("model", dev["model"] if not slot_id.startswith("ipad") else "ipad")
            parts.append(devices.device_html(
                did=f"dev{i}", screen_uri=uri, aspect=sh / sw, cx=ctx.X(L["x"]), cy=ctx.Y(L["y"]),
                width=ctx.U(L.get("w", 0.78)), model=model, finish=L.get("finish", dev["finish"]),
                rotate=ctx.rot(L.get("rotate")), focal=L.get("focal", dev["focal"]),
                shadow=L.get("shadow", dev["shadow"]), glare=L.get("glare", dev["glare"]),
                island=L.get("island"), light=(360 - dev["light"]) % 360 if mirror else dev["light"],
                z=z, opacity=L.get("opacity", 1), slices=slices))
            elements.append({"id": f"dev{i}", "kind": "device", "screen": L["screen"]})
        elif t == "card":
            uri, sw, sh = ctx.shot(L["screen"])
            crop = L["crop"]
            if all(0 <= v <= 1 for v in crop):
                crop = [crop[0] * sw, crop[1] * sh, crop[2] * sw, crop[3] * sh]
            parts.append(devices.card_html(
                cid=f"card{i}", screen_uri=uri, shot_w=sw, shot_h=sh, crop=crop, cx=ctx.X(L["x"]),
                cy=ctx.Y(L["y"]), width=ctx.U(L.get("w", 0.6)), radius=L.get("radius", 0.06),
                rotate=ctx.rot(L.get("rotate")), shadow=L.get("shadow", "float"), z=z,
                light=(360 - dev["light"]) % 360 if mirror else dev["light"], border=L.get("border"),
                lift=L.get("lift", 0)))
            elements.append({"id": f"card{i}", "kind": "card", "screen": L["screen"]})
        elif t == "image":
            a = spec["artwork"][L["art"]]
            p = (ctx.base / a["file"]).resolve()
            with Image.open(p) as im:
                iw, ih = im.size
            w = ctx.U(L.get("w", 1.0))
            h = ctx.U(L["h"]) if "h" in L else w * ih / iw
            rot = L.get("rotate", 0) * (-1 if mirror else 1)
            flip = "scaleX(-1)" if (mirror and L.get("mirror_art")) else ""
            parts.append(f'<img class="art" data-id="img{i}" data-kind="image" src="{p.as_uri()}" alt="" '
                         f'style="left:{ctx.X(L["x"]) - w / 2:.1f}px;top:{ctx.Y(L["y"]) - h / 2:.1f}px;width:{w:.1f}px;'
                         f'height:{h:.1f}px;object-fit:{L.get("fit", "cover")};opacity:{L.get("opacity", 1)};'
                         f'transform:rotate({rot}deg) {flip};border-radius:{BLOB_RADIUS if L.get("mask") == "blob" else "%.1fpx" % ctx.U(L.get("radius", 0))};'
                         f'{"z-index:%s;" % z if z is not None else ""}'
                         f'{"mix-blend-mode:%s;" % L["blend"] if L.get("blend") else ""}'
                         f'{"filter:drop-shadow(0 %.0fpx %.0fpx rgba(0,0,0,.3));" % (h * .03, h * .05) if L.get("shadow") else ""}">')
            elements.append({"id": f"img{i}", "kind": "image", "art": L["art"]})
        elif t == "icon":
            icon = (spec.get("app") or {}).get("icon")
            if not icon:
                continue
            p = (ctx.base / icon).resolve()
            w = ctx.U(L.get("w", 0.2))
            parts.append(f'<img class="art" data-id="icon{i}" data-kind="icon" src="{p.as_uri()}" alt="" '
                         f'style="left:{ctx.X(L["x"]) - w / 2:.1f}px;top:{ctx.Y(L["y"]) - w / 2:.1f}px;width:{w:.1f}px;'
                         f'height:{w:.1f}px;border-radius:{w * 0.225:.1f}px;z-index:{z or 40};'
                         f'filter:drop-shadow(0 {w * .06:.0f}px {w * .12:.0f}px rgba(0,0,0,.28))">')
        elif t == "display":
            # decorative giant type on the canvas (may cross panels); never carries the message alone
            txt, _ = text_for(L.get("text"), locale, spec["campaign"]["primary_locale"])
            if not txt:
                continue
            scripts = fonts.scripts_in(txt, locale)
            stack, f = _font_css(finfo, L.get("font", "display"), scripts)
            size = ctx.U(L.get("size", 0.6))
            stroke = L.get("outline")
            fillc = "transparent" if stroke else ctx.col(L.get("color", "ink"))
            ws = f"-webkit-text-stroke:{ctx.U(stroke):.1f}px {ctx.col(L.get('color', 'ink'))};" if stroke else ""
            anchor_x = ctx.X(L["x"])
            parts.append(f'<div class="disp" data-id="disp{i}" data-kind="display" '
                         f'style="left:{anchor_x:.0f}px;top:{ctx.Y(L["y"]):.0f}px;font-family:{stack};font-size:{size:.0f}px;'
                         f'font-weight:{L.get("weight", f.get("weight", 700))};letter-spacing:{L.get("tracking", -0.04)}em;'
                         f'color:{fillc};{ws}opacity:{L.get("opacity", 1)};text-transform:{L.get("case", f.get("case", "none"))};'
                         f'transform:translate(-50%,-50%) rotate({L.get("rotate", 0) * (-1 if mirror else 1)}deg);'
                         f'{"z-index:%s;" % z if z is not None else ""}">{html.escape(txt)}</div>')
        elif t == "text":
            block, meta = _text_block(ctx, L, i, finfo, fit)
            if block:
                parts.append(block)
                texts += meta
    mir = ' style="transform:scaleX(-1)"' if mirror else ""
    svg_open = (f'<svg class="shapes" width="{MW}" height="{H}" viewBox="0 0 {MW} {H}" '
                f'xmlns="http://www.w3.org/2000/svg"{mir}>')
    low = f'{svg_open}<defs>{"".join(defs)}</defs>{"".join(svg_low)}</svg>' if svg_low else ""
    hi_open = svg_open.replace('class="shapes"', 'class="shapes hi" style="z-index:30"', 1)
    if mirror:
        hi_open = hi_open.replace('style="z-index:30" style="transform:scaleX(-1)"',
                                  'style="z-index:30;transform:scaleX(-1)"')
    high = f'{hi_open}<defs>{"".join(defs)}</defs>{"".join(svg_high)}</svg>' if svg_high else ""
    grain = ""
    if d.get("grain"):
        seed = spec["campaign"]["seed"]
        noise = ("data:image/svg+xml;utf8," + html.escape(
            f"<svg xmlns='http://www.w3.org/2000/svg' width='512' height='512'><filter id='n'><feTurbulence "
            f"type='fractalNoise' baseFrequency='0.9' numOctaves='2' seed='{seed}' stitchTiles='stitch'/>"
            f"<feColorMatrix values='0 0 0 0 0.5 0 0 0 0 0.5 0 0 0 0 0.5 0 0 0 1.4 -0.2'/></filter>"
            f"<rect width='512' height='512' filter='url(#n)'/></svg>", quote=True).replace("#", "%23"))
        grain = (f'<div class="grain" style="background-image:url(&quot;{noise}&quot;);'
                 f'opacity:{float(d["grain"]):.3f}"></div>')
    n_bg = len(layout.get("background") or [])
    body = "".join(parts[:n_bg]) + low + "".join(parts[n_bg:]) + high + grain
    css = (font_css + "\n" + devices.DEVICE_CSS + f"""
html,body{{margin:0;padding:0;background:{ctx.col('bg')}}}
.canvas{{position:relative;width:{MW}px;height:{H}px;overflow:hidden;isolation:isolate}}
.bg,.glow,.art,.disp,.tx,.grain,.shapes{{position:absolute}}
.shapes{{left:0;top:0;pointer-events:none}}
.grain{{inset:0;mix-blend-mode:overlay;z-index:90;pointer-events:none;background-size:512px 512px}}
.disp{{white-space:nowrap;line-height:.9}}
.tx{{display:flex;flex-direction:column}}
.t{{margin:0;text-wrap:balance;overflow-wrap:normal;word-break:normal;-webkit-font-smoothing:antialiased}}
.t[lang|=ja],.tx[lang|=ja] .t{{line-break:strict}}
.tx[lang|=ko] .t{{word-break:keep-all}}
.acc-color{{color:var(--acc)}}
.acc-italic{{font-style:italic;color:var(--acc)}}
.acc-marker{{--mk:color-mix(in srgb,var(--acc) 55%,transparent);
  background:linear-gradient(transparent 58%,var(--mk) 58%,var(--mk) 92%,transparent 92%);
  padding:0 .06em;-webkit-box-decoration-break:clone;box-decoration-break:clone}}
.acc-pill{{background:linear-gradient(100deg,var(--acc),color-mix(in srgb,var(--acc) 62%,var(--acc2)));
  color:var(--on-acc);padding:.02em .3em .08em;border-radius:.42em;
  -webkit-box-decoration-break:clone;box-decoration-break:clone}}
.acc-circle,.acc-underline,.acc-box{{position:relative;display:inline-block}}
.acc-circle::after{{content:"";position:absolute;inset:-.1em -.22em -.06em -.2em;border:.055em solid var(--acc);
  border-radius:50%;transform:rotate(-4deg);pointer-events:none}}
.acc-underline::after{{content:"";position:absolute;left:-.04em;right:-.04em;bottom:-.1em;height:.22em;
  border-bottom:.06em solid var(--acc);border-radius:0 0 50% 50% / 0 0 100% 100%;pointer-events:none}}
.acc-box{{outline:.035em solid var(--acc);outline-offset:.04em}}
.acc-box::before,.acc-box::after{{content:"";position:absolute;width:.13em;height:.13em;background:var(--acc)}}
.acc-box::before{{left:-.105em;top:-.105em}}
.acc-box::after{{right:-.105em;bottom:-.105em}}
.acc-serif{{font-family:'{SERIF_ACCENT}',serif;font-style:italic;font-weight:400;letter-spacing:-.01em}}
.acc-gradient{{background:linear-gradient(100deg,var(--acc),var(--acc2));-webkit-background-clip:text;
  background-clip:text;color:transparent;-webkit-box-decoration-break:clone;box-decoration-break:clone}}
.t-chips{{display:flex;flex-wrap:wrap;gap:.45em .4em;line-height:1.2}}
.tx[style*="text-align:center"] .t-chips{{justify-content:center}}
.tx[style*="text-align:end"] .t-chips{{justify-content:flex-end}}
.chip{{display:inline-block;padding:.42em .95em;border-radius:999px;white-space:nowrap}}
.chips-glass .chip{{background:rgba(255,255,255,.62);border:.06em solid rgba(255,255,255,.85);
  box-shadow:0 .25em .9em rgba(20,20,40,.10)}}
.chips-solid .chip{{background:var(--chip);color:var(--on-chip)}}
.chips-outline .chip{{border:.08em solid var(--chip)}}
.chips-sticker .chip{{background:var(--chip);color:var(--on-chip);box-shadow:0 .2em .6em rgba(0,0,0,.18);
  border:.12em solid #fff}}
.chips-sticker .chip:nth-child(odd){{transform:rotate(-5deg)}}
.chips-sticker .chip:nth-child(even){{transform:rotate(4deg)}}
{'.tx{visibility:hidden}' if hide_text else ''}
""")
    script = MEASURE_JS if measure else ""
    page = (f'<!doctype html><html lang="{html.escape(locale)}"><head><meta charset="utf-8">'
            f'<style>{css}</style></head><body><div class="canvas" id="canvas">{body}</div>'
            f'<pre id="__m" style="display:none"></pre>{script}</body></html>')
    return page, {"texts": texts, "elements": elements, "W": W, "H": H, "N": ctx.N, "u": ctx.u, "mirror": mirror}


MEASURE_JS = r"""<script>
(async () => {
  const out = {texts: [], els: [], fonts: {}, ok: true};
  try {
    await document.fonts.ready;
    const fams = new Set();
    for (const el of document.querySelectorAll('[data-fit]')) {
      const max = +el.dataset.maxLines, min = +el.dataset.min, lh = +el.dataset.lh;
      let fs = +el.dataset.size, steps = 0;
      const lines = () => Math.round(el.getBoundingClientRect().height / (fs * lh));
      const over = () => el.scrollWidth > el.clientWidth + 1;
      while ((lines() > max || over()) && fs > min && steps < 80) {
        fs = Math.max(min, fs * 0.965); el.style.fontSize = fs + 'px'; steps++;
      }
      const range = document.createRange(); range.selectNodeContents(el);
      const r = range.getBoundingClientRect();
      const fam = el.dataset.family; fams.add(fam);
      out.texts.push({tid: el.dataset.tid, role: el.dataset.role, fs: fs, lines: lines(), overflow: over(),
        min_hit: fs <= min + 0.01 && (lines() > max || over()),
        rect: [r.left, r.top, r.width, r.height],
        font_ok: document.fonts.check(`${el.dataset.weight} ${Math.round(fs)}px "${fam}"`, el.textContent),
        panel: +el.parentElement.dataset.panel});
    }
    for (const el of document.querySelectorAll('[data-kind]')) {
      if (el.dataset.kind === 'text') continue;
      const tgt = el.querySelector('.dv-screen,.dv-front,.cd-body') || el;
      const r = tgt.getBoundingClientRect(), o = el.getBoundingClientRect();
      out.els.push({id: el.dataset.id, kind: el.dataset.kind, rect: [r.left, r.top, r.width, r.height],
        outer: [o.left, o.top, o.width, o.height]});
    }
    for (const f of fams) out.fonts[f] = [...document.fonts].some(ff => ff.family.replace(/['"]/g,'') === f && ff.status === 'loaded');
    const imgs = [...document.images];
    out.images_broken = imgs.filter(i => !i.complete || i.naturalWidth === 0).map(i => i.src.slice(0, 200));
  } catch (e) { out.ok = false; out.error = String(e); }
  document.getElementById('__m').textContent = JSON.stringify(out);
})();
</script>"""


def parse_measure(dom: str) -> dict:
    m = re.search(r'<pre id="__m"[^>]*>(.*?)</pre>', dom, re.S)
    if not m or not m.group(1).strip():
        raise RuntimeError("the measuring pass returned nothing (did the page load?)")
    return json.loads(html.unescape(m.group(1)))
