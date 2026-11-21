"""Composition engines: each turns the storyboard + design tokens into background and layers.

They are different composition systems, not colour swaps: where the devices go, how they are lit, how type
and image share the panel, and what ties the panels together all change per engine. Each output is plain
campaign layers, so `campaign.py eject` can write it out for hand tuning.

Every engine follows the same hard rules: every panel shows real UI from its own storyboard screen, the
headline sits wholly inside its panel, and panel 1 carries the strongest message at the largest size.
"""
from __future__ import annotations

import math
import random

from .scene import luminance

ENGINES = {}


# Six axes a set can differ on (studio/diversity.py picks concepts that differ on at least three of them):
#   device       full | cropped | multiple | mixed (device + lifted cards) | ui-only (no frame)
#   composition  centered | panorama | poster | column | grid | collage | strips | cascade | split | annotated
#   background   gradient | flat | photo | texture | pattern | type | blocks | shapes
#   type         sans | serif | display | condensed | rounded | mono
#   color        a palette family from diversity.FAMILIES
#   eye          top-down | bottom-up | sweep | zigzag | rows | margin | radial | cascade | diagonal | focal
AXES = ("device", "composition", "background", "type", "color", "eye")


def engine(name, *, label, pattern, type_preset, mood, needs=None, axes=None, art=None):
    """`axes` places the engine on the six axes above; `art` describes the optional generated artwork the
    engine can use ({role, brief}), written out by `campaign.py art-briefs`."""
    def deco(fn):
        ENGINES[name] = {"fn": fn, "label": label, "pattern": pattern, "type": type_preset, "mood": mood,
                         "needs": needs or [], "axes": dict(axes or {}), "art": art}
        return fn
    return deco


class E:
    """What an engine gets: panel count, storyboard, palette, a seeded RNG, UI blocks per screen."""

    def __init__(self, spec, blocks=None):
        self.spec = spec
        self.N = spec["campaign"]["panels"]
        self.sb = spec["storyboard"]
        self.pal = spec["design"]["palette"]
        self.rng = random.Random(spec["campaign"]["seed"])
        self.blocks = blocks or {}
        self.has_icon = bool((spec.get("app") or {}).get("icon"))
        self.art = {k: v for k, v in (spec.get("artwork") or {}).items()}

    def screen(self, i, k=0):
        p = self.sb[i - 1] if i - 1 < len(self.sb) else {}
        lst = [p.get("screen")] + list(p.get("screens") or [])
        lst = [s for s in lst if s]
        if not lst:
            # fall back to a neighbour's screen so a type-only panel still has something to hold
            allsc = [q.get("screen") for q in self.sb if q.get("screen")]
            return allsc[(i + k) % len(allsc)] if allsc else None
        return lst[k % len(lst)]

    def other_screen(self, i, k=1):
        """A different screen from the storyboard (for second devices)."""
        own = self.screen(i)
        pool = [s for s in ([q.get("screen") for q in self.sb] + [s for q in self.sb for s in (q.get("screens") or [])])
                if s and s != own]
        return pool[(i + k) % len(pool)] if pool else own

    def ink_on(self, bg_token):
        bg = self.pal.get(bg_token, bg_token)
        ink, light = self.pal.get("ink", "#111111"), self.pal.get("light", "#FFFFFF")
        def cr(a, b):
            la, lb = luminance(a), luminance(b)
            return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)
        return "ink" if cr(ink, bg) >= cr(light, bg) else "light"

    def accent_on(self, bg_token, prefer=("accent", "accent2", "light", "ink")):
        """The first accent that reads (>= 3:1) on this background."""
        bg = self.pal.get(bg_token, bg_token)
        def cr(a, b):
            la, lb = luminance(a), luminance(b)
            return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)
        for t in prefer:
            if t in self.pal and cr(self.pal[t], bg) >= 3.0:
                return t
        return self.ink_on(bg_token)

    def is_dark(self, token):
        return luminance(self.pal.get(token, token)) < 0.18

    def cap(self, panel, *, x=0.085, y=0.062, w=0.83, align="start", anchor="top", color="ink", size=None,
            kicker=True, sub=True, z=None, accent="accent", kicker_color=None, gap=None, max_lines=None,
            shadow=None):
        p = self.sb[panel - 1]
        items = []
        if kicker and p.get("kicker"):
            items.append({"role": "kicker", "copy": f"{p['id']}.kicker", "color": kicker_color or accent})
        h = {"role": "headline", "copy": f"{p['id']}.headline"}
        if size:
            h["size"] = size
        if max_lines:
            h["max_lines"] = max_lines
        items.append(h)
        if sub and p.get("sub"):
            items.append({"role": "sub", "copy": f"{p['id']}.sub", "opacity": 0.78})
        L = {"type": "text", "panel": panel, "x": x, "y": y, "w": w, "align": align, "anchor": anchor,
             "color": color, "accent": accent, "items": items}
        if z is not None:
            L["z"] = z
        if gap is not None:
            L["gap"] = gap
        if shadow:
            L["shadow"] = shadow
        return L

    def chips(self, panel, *, x=0.06, y=0.4, w=0.88, align="center", anchor="top", style="glass", fill="accent",
              color="ink", z=None):
        """The panel's feature chips (storyboard `chips:`) as their own block, or None when it has none."""
        p = self.sb[panel - 1]
        if not p.get("chips"):
            return None
        L = {"type": "text", "panel": panel, "x": x, "y": y, "w": w, "align": align, "anchor": anchor,
             "color": color, "chip_style": style, "chip_fill": fill,
             "items": [{"role": "chips", "copy": f"{p['id']}.chips"}]}
        if z is not None:
            L["z"] = z
        return L

    def stat(self, panel, *, x=0.08, y=0.95, w=0.84, align="start", anchor="bottom", color="ink", accent="accent"):
        """A stat callout (storyboard `stat:` + `stat_label:`), or None. The spec refuses a stat without evidence."""
        p = self.sb[panel - 1]
        if not p.get("stat"):
            return None
        items = [{"role": "stat", "copy": f"{p['id']}.stat", "color": accent}]
        if p.get("stat_label"):
            items.append({"role": "label", "copy": f"{p['id']}.stat_label", "opacity": 0.85})
        return {"type": "text", "panel": panel, "x": x, "y": y, "w": w, "align": align, "anchor": anchor,
                "color": color, "items": items, "gap": 0.006}

    def footnote(self, panel, *, color="ink", top=False):
        p = self.sb[panel - 1]
        return {"type": "text", "panel": panel, "x": 0.07, "y": 0.02 if top else 0.988, "w": 0.86,
                "anchor": "top" if top else "bottom", "align": "start", "color": color, "z": 60,
                "items": [{"role": "footnote", "copy": f"{p['id']}.footnote", "opacity": 0.72}]}

    def dev(self, panel, x, y, w=0.78, rotate=(0, 0, 0), k=0, screen=None, **kw):
        sid = screen or self.screen(panel, k)
        d = {"type": "device", "screen": sid, "x": round(x, 4), "y": round(y, 4), "w": w, "rotate": list(rotate)}
        d.update(kw)
        return d

    def cards_for(self, panel, n=2):
        sid = self.screen(panel)
        p = self.sb[panel - 1]
        hl = p.get("highlights") or self.blocks.get(sid) or []
        return sid, hl[:n]

    def crops(self, panel, n=3):
        """n real regions of the panel's screen: the storyboard's highlights, else the detected UI blocks, else
        even horizontal bands below the status bar. Fractions [x, y, w, h] of the screenshot."""
        sid, found = self.cards_for(panel, n)
        found = [list(b) for b in found]
        band = 0.78 / n
        while len(found) < n:
            k = len(found)
            found.append([0.0, round(0.08 + k * band, 4), 1.0, round(min(band, 0.3), 4)])
        return sid, found

    def card(self, panel, crop, x, y, w=0.7, *, screen=None, rotate=(0, 0, 0), radius=0.05, shadow="float",
             z=None, border=None):
        L = {"type": "card", "screen": screen or self.screen(panel), "crop": [round(v, 4) for v in crop],
             "x": round(x, 4), "y": round(y, 4), "w": w, "radius": radius, "rotate": list(rotate), "shadow": shadow}
        if z is not None:
            L["z"] = z
        if border:
            L["border"] = border
        return L

    def motifs(self, panel, n=3):
        """Pictograms that fit this panel's story (studio/motifs.py)."""
        from . import motifs as M
        return M.panel_motifs(self.spec, panel, n)

    def badge(self, glyph, x, y, size=0.16, *, disc="#FFFFFF", fill="accent", fill2="#FFFFFF", rotate=0, z=20,
              ring=None):
        """A glyph on a round disc, like a sticker or a map marker."""
        out = [{"type": "shape", "kind": "circle", "x": x, "y": y, "r": size * 0.62, "fill": disc, "z": z}]
        if ring:
            out.append({"type": "shape", "kind": "ring", "x": x, "y": y, "r": size * 0.72, "stroke": ring,
                        "width": 0.006, "z": z})
        out.append({"type": "shape", "kind": "glyph", "glyph": glyph, "x": x, "y": y, "size": size * 0.72,
                    "rotate": rotate, "fill": fill, "fill2": fill2, "shadow": False, "z": z})
        return out

    def art_of(self, role, k=0):
        """The k-th artwork with this role (cycling), or None."""
        hits = [n for n, a in self.art.items() if a.get("role") == role]
        return hits[k % len(hits)] if hits else None

    def accent_word(self, panel):
        """The headline's **accent** word per locale ({locale: word}), or its first word when none is marked."""
        h = self.sb[panel - 1].get("headline") or {}
        h = h if isinstance(h, dict) else {"*": h}
        out = {}
        for loc, t in h.items():
            t = str(t)
            if "**" in t:
                out[loc] = t.split("**")[1]
            else:
                out[loc] = t.split()[0] if t.split() else t
        return out


def jitter(e, a, spread):
    return a + e.rng.uniform(-spread, spread)


# ---------------------------------------------------------------- 1. panoramic flow
@engine("panoramic-flow", label="Panoramic flow", pattern="panoramic storytelling + devices crossing panels",
        type_preset="friendly-consumer",
        mood="one continuous scene: a brand-colour wave runs through every panel and paired phones meet across the seams")
def panoramic_flow(e: E):
    """Panels work in pairs: the two phones of a pair lean toward their shared seam and overlap across it.
    Pairs alternate text-on-top (phones low, bleeding off the bottom) and text-on-the-wave (phones high)."""
    N = e.N
    layers = [
        {"type": "shape", "kind": "wave", "y": 0.7, "amp": 0.05, "cycles": max(1.0, N / 2.4), "fill": "accent",
         "phase": 0.6},
        {"type": "shape", "kind": "wave", "y": 0.79, "amp": 0.035, "cycles": max(1.0, N / 3.1),
         "fill": "accent2@0.92", "phase": 2.1},
    ]
    for i in range(1, N + 1):
        c = i - 0.5
        q = (i - 1) // 2
        left = i % 2 == 1
        alone = left and i == N
        top = q % 2 == 0
        w = 0.8 if i == 1 else 0.72
        lean = 0 if alone else (0.19 if left else -0.19)
        ry = 0 if alone else (-17 if left else 17)
        rz = 0 if alone else (5 if left else -5)
        align = "center" if alone else ("start" if left else "end")
        if top:
            layers.append(e.cap(i, y=0.062, size=0.13 if i == 1 else None, color=e.ink_on("bg"), align=align,
                                accent=e.accent_on("bg")))
            layers.append(e.dev(i, c + lean, 0.33 + w / 2, w, (5, ry, rz), shadow="float", z=10 + i))
        else:
            # the lower wave (accent2) is what sits behind bottom text
            layers.append(e.cap(i, y=0.955, anchor="bottom", color=e.ink_on("accent2"), align=align,
                                accent=e.accent_on("accent2", ("accent", "dark", "ink"))))
            layers.append(e.dev(i, c + lean, 0.035 + w / 2 - 0.03, w, (-5, ry, -rz), shadow="float", z=10 + i))
    return {"background": [{"type": "linear", "angle": 100, "stops": [["bg", 0], ["bg2", 1]]}], "layers": layers}


# ---------------------------------------------------------------- 2. floating 3D
@engine("floating-3d", label="Floating 3D", pattern="floating devices with depth, light and shadow",
        type_preset="modern-tech",
        mood="studio product shots: phones hang in a lit space at three-quarter angles, a second phone gives depth")
def floating_3d(e: E):
    N = e.N
    layers, bgs = [], [{"type": "linear", "angle": 180, "stops": [["bg", 0], ["bg2", 1]]}]
    for i in range(1, N + 1):
        c = i - 0.5
        side = -1 if i % 2 else 1
        bgs.append({"type": "radial", "x": c + 0.18 * side, "y": 0.58, "r": 0.9, "color": "light@0.55"})
        layers.append({"type": "glow", "x": c - 0.2 * side, "y": 0.7, "r": 0.55, "color": "accent@0.35", "opacity": 0.7})
        if i == 1:
            layers.append(e.cap(1, y=0.06, align="center", x=0.07, w=0.86, size=0.12, color=e.ink_on("bg")))
            layers.append(e.dev(1, c - 0.2, 0.66, 0.66, (10, 26, 6), screen=e.other_screen(1), shadow="float",
                                opacity=1))
            layers.append(e.dev(1, c + 0.13, 0.62, 0.78, (8, -24, -8), shadow="float"))
            continue
        layers.append(e.cap(i, y=0.06, align="center", x=0.07, w=0.86, color=e.ink_on("bg")))
        layers.append(e.dev(i, c + 0.04 * side, 0.63, 0.8, (9, 24 * side, 7 * side), shadow="float"))
    return {"background": bgs, "layers": layers}


# ---------------------------------------------------------------- 3. editorial
@engine("editorial", label="Editorial", pattern="magazine grid, oversized serif headline, cropped flat device",
        type_preset="premium-editorial",
        mood="a printed magazine: big serif headline set left, numbered kickers, a hairline grid, one inverted spread")
def editorial(e: E):
    N = e.N
    layers, bgs = [], [{"type": "solid", "color": "bg"}]
    inv = 4 if N >= 5 else None
    for i in range(1, N + 1):
        c = i - 0.5
        dark = i == inv
        if dark:
            bgs.append({"type": "panel", "panel": i, "color": "dark"})
        ink = "light" if dark else "ink"
        num = {"role": "kicker", "text": f"{i:02d}", "color": "accent", "font": "mono"}
        cap = e.cap(i, y=0.07, x=0.09, w=0.82, size=0.15 if i == 1 else 0.125, color=ink, sub=True)
        cap["items"].insert(0, num)
        layers.append(cap)
        layers.append({"type": "shape", "kind": "rect", "x": c, "y": 0.052, "w": 0.82, "h": 0.0018,
                       "fill": "light@0.5" if dark else "ink@0.35"})
        right = i % 2 == 1
        layers.append(e.dev(i, c + (0.13 if right else -0.13), 0.9, 0.8, (0, 0, 0), shadow="soft", glare=0.04))
    return {"background": bgs, "layers": layers}


# ---------------------------------------------------------------- 4. typographic hero
@engine("typographic-hero", label="Typographic hero", pattern="type as the image; giant outlined name across all panels",
        type_preset="bold-geometric",
        mood="the words are the picture: very large headlines, the app name runs behind every panel in outline")
def typographic_hero(e: E):
    N = e.N
    name = (e.spec.get("app") or {}).get("name", "")
    layers = []
    if name:
        layers.append({"type": "display", "text": (name + "  ") * 2, "x": N / 2, "y": 0.5, "size": 1.25,
                       "outline": 0.004, "color": "ink@0.16", "z": 1})
    for i in range(1, N + 1):
        c = i - 0.5
        layers.append(e.cap(i, y=0.055, x=0.07, w=0.86, size=0.155 if i == 1 else 0.14, color="ink", sub=False,
                            kicker=True, max_lines=4))
        layers.append(e.dev(i, c + (0.14 if i % 2 else -0.14), 0.79, 0.74, (0, 0, -6 if i % 2 else 6),
                            shadow="soft"))
    return {"background": [{"type": "solid", "color": "bg"},
                           {"type": "linear", "angle": 90, "stops": [["accent@0.0", 0], ["accent@0.10", 0.5],
                                                                     ["accent@0.0", 1]]}],
            "layers": layers}


# ---------------------------------------------------------------- 5. feature explosion
@engine("feature-explosion", label="Feature explosion", pattern="real UI pieces lifted out of the phone",
        type_preset="modern-tech",
        mood="exploded view: the screen's own cards float out of the phone in 3D, each a real piece of the UI")
def feature_explosion(e: E):
    N = e.N
    layers, bgs = [], [{"type": "linear", "angle": 160, "stops": [["bg", 0], ["bg2", 1]]}]
    for i in range(1, N + 1):
        c = i - 0.5
        side = 1 if i % 2 else -1
        layers.append(e.cap(i, y=0.06, x=0.08, w=0.84, align="center", size=0.12 if i == 1 else None,
                            color=e.ink_on("bg")))
        layers.append({"type": "glow", "x": c, "y": 0.66, "r": 0.6, "color": "accent@0.4"})
        layers.append(e.dev(i, c - 0.07 * side, 0.67, 0.68, (6, 14 * side, 3 * side), shadow="soft"))
        sid, blocks = e.cards_for(i, 2)
        for k, b in enumerate(blocks):
            cy = 0.53 + 0.2 * k
            layers.append({"type": "card", "screen": sid, "crop": b, "x": c + (0.17 + 0.05 * k) * side,
                           "y": cy, "w": 0.6, "radius": 0.05, "rotate": [4, -10 * side, -3 * side],
                           "shadow": "float", "z": 20 + k})
    return {"background": bgs, "layers": layers}


# ---------------------------------------------------------------- 6. cinematic
@engine("cinematic", label="Cinematic", pattern="dark stage, rim light, dramatic close angles across the seams",
        type_preset="modern-tech",
        mood="a film still: near-black stage, coloured rim light, big phones at hard angles bleeding off the edges")
def cinematic(e: E):
    N = e.N
    layers = []
    bgs = [{"type": "solid", "color": "dark"}]
    acc = e.accent_on("dark", ("accent2", "accent", "light"))
    for i in range(1, N + 1):
        c = i - 0.5
        side = 1 if i % 2 else -1
        bgs.append({"type": "radial", "x": c + 0.3 * side, "y": 0.36, "r": 1.0, "color": "accent@0.5"})
        bgs.append({"type": "radial", "x": c - 0.4 * side, "y": 0.98, "r": 0.8, "color": "accent2@0.3"})
        layers.append(e.cap(i, y=0.952, anchor="bottom", x=0.08, w=0.84, color="light",
                            size=0.125 if i == 1 else 0.105, accent=acc, kicker_color=acc))
        w = 0.9 if i == 1 else 0.84
        layers.append(e.dev(i, c + 0.1 * side, w / 2 - 0.1, w, (14, -30 * side, -12 * side),
                            shadow={"style": "long", "strength": 1.6}, glare=0.14, finish="graphite"))
    return {"background": bgs, "layers": layers}


# ---------------------------------------------------------------- 7. minimal premium
@engine("minimal-premium", label="Minimal premium", pattern="restraint: precise type, air, one refined device",
        type_preset="luxury-minimal",
        mood="quiet luxury: a single upright phone at a different height each time, spaced small caps, nothing extra")
def minimal_premium(e: E):
    N = e.N
    layers = []
    for i in range(1, N + 1):
        c = i - 0.5
        hi = i % 2 == 0
        if i == 1 and e.has_icon:
            layers.append({"type": "icon", "x": c, "y": 0.07, "w": 0.13})
        layers.append(e.cap(i, y=0.13 if i == 1 and e.has_icon else 0.075, x=0.1, w=0.8, align="center",
                            size=0.1, color="ink", kicker=True, kicker_color="muted"))
        layers.append(e.dev(i, c, 0.68 if not hi else 0.72, 0.66, (0, 0, 0), shadow={"style": "soft", "strength": 0.7},
                            glare=0.05, finish="silver"))
    return {"background": [{"type": "linear", "angle": 180, "stops": [["bg", 0], ["bg", 0.55], ["bg2", 1]]}],
            "layers": layers}


# ---------------------------------------------------------------- 8. device cluster
@engine("device-cluster", label="Device cluster", pattern="several phones per panel at different depths",
        type_preset="modern-tech",
        mood="a busy, confident product spread: two or three phones overlap per panel and hand off to the next")
def device_cluster(e: E):
    N = e.N
    layers = []
    for i in range(1, N + 1):
        c = i - 0.5
        layers.append(e.cap(i, y=0.06, x=0.08, w=0.84, color=e.ink_on("bg"), size=0.12 if i == 1 else None))
        layers.append(e.dev(i, c - 0.24, 0.66, 0.6, (6, 22, 10), screen=e.other_screen(i, 1), shadow="soft"))
        layers.append(e.dev(i, c + 0.28, 0.72, 0.6, (6, -22, -10), screen=e.other_screen(i, 2), shadow="soft"))
        layers.append(e.dev(i, c + 0.02, 0.69, 0.74, (4, 0, 0), shadow="float"))
    return {"background": [{"type": "linear", "angle": 135, "stops": [["bg", 0], ["bg2", 1]]},
                           {"type": "radial", "x": 1.5, "y": 0.2, "r": 2.5, "color": "accent@0.12"}],
            "layers": layers}


# ---------------------------------------------------------------- 9. immersive
@engine("immersive", label="Immersive", pattern="one panoramic photograph behind floating UI",
        type_preset="premium-editorial", needs=["artwork with role: scene (a wide photo or generated scene)"],
        mood="the place the app is for: one wide photograph across all panels, phones float in it")
def immersive(e: E):
    N = e.N
    scene = next((k for k, a in e.art.items() if a.get("role") == "scene"), None)
    bgs = []
    if scene:
        bgs.append({"type": "image", "art": scene, "fit": "cover"})
    else:
        bgs += [{"type": "linear", "angle": 180, "stops": [["accent2", 0], ["accent", 0.62], ["bg2", 1]]}]
    bgs.append({"type": "linear", "angle": 180, "stops": [["dark@0.55", 0], ["dark@0.0", 0.38], ["dark@0.0", 0.7],
                                                         ["dark@0.45", 1]]})
    layers = []
    if not scene:
        for k in range(N * 2):
            layers.append({"type": "shape", "kind": "blob", "x": 0.3 + k * N / (N * 2), "y": 0.55 + 0.25 * (k % 2),
                           "r": 0.7, "fill": "light@0.22" if k % 2 else "accent2@0.35", "blur": 0.12})
    for i in range(1, N + 1):
        c = i - 0.5
        layers.append(e.cap(i, y=0.062, x=0.08, w=0.84, color="light", size=0.13 if i == 1 else None,
                            shadow="0 2px 30px rgba(0,0,0,.35)"))
        layers.append(e.dev(i, c + (0.08 if i % 2 else -0.08), 0.66, 0.78, (6, -14 if i % 2 else 14, 0),
                            shadow={"style": "float", "strength": 1.3}))
    return {"background": bgs, "layers": layers}


# ---------------------------------------------------------------- 10. illustrated
@engine("illustrated", label="Illustrated", pattern="flat geometric illustration crossing the seams",
        type_preset="playful-illustration",
        mood="a picture book: big flat shapes in the brand colours run across panels, phones sit on them")
def illustrated(e: E):
    N = e.N
    layers = []
    for k in range(N + 1):
        layers.append({"type": "shape", "kind": "circle", "x": k + 0.0, "y": 0.62 + 0.12 * ((k % 3) - 1),
                       "r": 0.55 + 0.1 * (k % 2), "fill": ["accent", "accent2", "bg2"][k % 3]})
    layers.append({"type": "shape", "kind": "path", "points": [[0.1 + j * 0.5, 0.9 - 0.08 * ((j % 2))]
                                                                for j in range(2 * N)],
                   "stroke": "ink@0.6", "width": 0.006, "dash": 0.02, "gap": 0.022})
    layers.append({"type": "shape", "kind": "dots", "x": 0.1, "y": 0.2, "w": N * 1.1, "h": 0.7, "gap": 0.05,
                   "r": 0.004, "fill": "ink@0.12"})
    for i in range(1, N + 1):
        c = i - 0.5
        layers.append(e.cap(i, y=0.06, x=0.08, w=0.84, color="ink", size=0.12 if i == 1 else None))
        layers.append(e.dev(i, c, 0.68, 0.72, (0, 0, -5 if i % 2 else 5), shadow="contact"))
    return {"background": [{"type": "solid", "color": "bg"}], "layers": layers}


# ---------------------------------------------------------------- 11. big type
@engine("big-type", label="Big type", pattern="colour-block panels, oversized headlines, a phone crossing the first seam",
        type_preset="friendly-consumer",
        mood="loud and friendly: each panel a saturated colour block, the first headline fills the panel, one phone "
             "straddles the first seam")
def big_type(e: E):
    N = e.N
    seq = ["accent", "accent"] + ["accent2", "dark", "accent"] * 4
    bgs = [{"type": "solid", "color": "accent"}]
    layers = []
    for i in range(1, N + 1):
        c = i - 0.5
        col = seq[i - 1]
        bgs.append({"type": "panel", "panel": i, "color": col})
        ink = e.ink_on(col)
        acc = e.accent_on(col, ("light", "accent2", "accent", "ink") if ink == "light" else ("ink", "dark"))
        if i == 1:
            cap = e.cap(1, y=0.05, x=0.07, w=0.88, size=0.18, max_lines=4, color=ink, accent=acc,
                        kicker=False, sub=True)
            cap["accent_style"] = "color"
            layers.append(cap)
            seam = 1.0 if N > 1 else 0.62
            layers.append(e.dev(1, seam, 0.9, 0.8, (0, 0, -8), shadow="float", z=12))
            continue
        if i == 2:
            cap = e.cap(2, y=0.06, x=0.12, w=0.82, align="end", color=ink, accent=acc, size=0.13)
            cap["accent_style"] = "color"
            layers.append(cap)
            layers.append(e.dev(2, c + 0.2, 0.9, 0.66, (0, 0, 7), shadow="soft", z=11))
            continue
        cap = e.cap(i, y=0.06, x=0.07, w=0.86, align="center", color=ink, accent=acc, size=0.13)
        cap["accent_style"] = "color"
        layers.append(cap)
        layers.append(e.dev(i, c, 0.76, 0.78, (0, 0, 0), shadow="float"))
    return {"background": bgs, "layers": layers}


# ---------------------------------------------------------------- 12. before / after
@engine("before-after", label="Before / after", pattern="a two-panel contrast story, then proof panels with stat callouts",
        type_preset="premium-editorial",
        mood="a story told in contrast: a dim 'before' panel meets a bright 'after' across one phone, then calm "
             "proof panels pair a small phone with a sourced number")
def before_after(e: E):
    N = e.N
    bgs = [{"type": "solid", "color": "bg"}]
    layers = []
    for i in range(1, N + 1):
        c = i - 0.5
        if i == 1:
            bgs.append({"type": "panel", "panel": 1, "color": "dark"})
            layers.append({"type": "glow", "x": 0.9, "y": 0.75, "r": 0.7, "color": "accent2@0.35"})
            layers.append(e.cap(1, y=0.06, x=0.09, w=0.82, size=0.16, color="light",
                                accent=e.accent_on("dark", ("accent2", "accent", "light"))))
            if N == 1:
                layers.append(e.dev(1, 0.62, 0.74, 0.76, (0, -12, 0), shadow="float"))
            continue
        if i == 2:
            layers.append({"type": "glow", "x": 1.35, "y": 0.4, "r": 0.8, "color": "accent@0.35"})
            layers.append(e.cap(2, y=0.06, x=0.09, w=0.82, align="end", size=0.16, color=e.ink_on("bg"),
                                accent=e.accent_on("bg")))
            layers.append(e.dev(2, 1.02, 0.76, 0.82, (0, -14, -4), shadow="float", z=12))
            continue
        dark = i % 2 == 0
        col = "dark" if dark else "bg"
        if dark:
            bgs.append({"type": "panel", "panel": i, "color": "dark"})
        ink = e.ink_on(col)
        layers.append(e.cap(i, y=0.06, x=0.08, w=0.84, align="center", color=ink, accent=e.accent_on(col)))
        st = e.stat(i, x=0.55, y=0.9, w=0.4, color=ink, accent=e.accent_on(col, ("accent", "accent2", "light", "ink")))
        if st:
            layers.append(e.dev(i, c - 0.24, 0.73, 0.4, (0, 0, 0), shadow="soft"))
            layers.append(st)
        else:
            layers.append(e.dev(i, c, 0.72, 0.78, (0, 0, 0), shadow="float"))
    return {"background": bgs, "layers": layers}


# ---------------------------------------------------------------- 13. glass
@engine("glass", label="Glass", pattern="frosted light panels, feature chips, floating UI cards, a serif accent word",
        type_preset="modern-tech",
        mood="soft and current: pale gradient light, glass chips under the headline, a real UI card floating off "
             "the phone, one word set in italic serif")
def glass(e: E):
    N = e.N
    bgs = [{"type": "linear", "angle": 165, "stops": [["bg", 0], ["bg2", 1]]}]
    layers = []
    for i in range(1, N + 1):
        c = i - 0.5
        side = 1 if i % 2 else -1
        layers.append({"type": "glow", "x": c + 0.3 * side, "y": 0.35, "r": 0.75, "color": "accent@0.30"})
        layers.append({"type": "glow", "x": c - 0.35 * side, "y": 0.85, "r": 0.7, "color": "accent2@0.25"})
        cap = e.cap(i, y=0.065, x=0.07, w=0.86, align="center", size=0.125 if i == 1 else 0.11,
                    color=e.ink_on("bg"), accent=e.accent_on("bg"))
        cap["accent_style"] = "serif"
        if e.sb[i - 1].get("chips"):
            cap["items"].append({"role": "chips", "copy": f"{e.sb[i - 1]['id']}.chips"})
            cap["chip_style"] = "glass"
        layers.append(cap)
        layers.append(e.dev(i, c - 0.05 * side, 0.74, 0.74, (4, 10 * side, 2 * side), shadow="soft", glare=0.06))
        sid, blocks = e.cards_for(i, 1)
        for b in blocks:
            layers.append({"type": "card", "screen": sid, "crop": b, "x": c + 0.2 * side, "y": 0.66, "w": 0.6,
                           "radius": 0.06, "rotate": [0, 0, 0], "shadow": "float", "border": "light@0.9",
                           "z": 20})
    return {"background": bgs, "layers": layers}


# ---------------------------------------------------------------- 14. sticker pop
@engine("sticker-pop", label="Sticker pop", pattern="headline words in gradient pills, tilted feature stickers, a big phone",
        type_preset="friendly-consumer",
        mood="playful and warm: a sky gradient, the key word set in a bright pill, feature stickers stuck at angles "
             "around a big phone")
def sticker_pop(e: E):
    N = e.N
    bgs = [{"type": "linear", "angle": 180, "stops": [["accent2", 0], ["bg2", 0.62], ["bg", 1]]}]
    layers = []
    for i in range(1, N + 1):
        c = i - 0.5
        ink = e.ink_on("accent2")
        cap = e.cap(i, y=0.055, x=0.07, w=0.86, align="center", size=0.135 if i == 1 else 0.12, color=ink,
                    sub=False, kicker=False, accent="accent")
        cap["accent_style"] = "pill"
        layers.append(cap)
        ch = e.chips(i, y=0.37, style="sticker", fill="accent", color="ink", z=55)
        if ch:
            layers.append(ch)
        layers.append({"type": "shape", "kind": "circle", "x": c + (0.3 if i % 2 else -0.3), "y": 0.58,
                       "r": 0.28, "fill": "accent@0.35", "blur": 0.06})
        layers.append(e.dev(i, c, 0.8, 0.82, (0, 0, 3 if i % 2 else -3), shadow="float", finish="graphite"))
    return {"background": bgs, "layers": layers}


# ================================================================ structures without a phone frame, or beyond
# "headline on top, one phone below". Added 2026-11 from a trend study (references/screenshot-trends.md): strong
# current sets change structure from panel to panel and make a real piece of the UI the image.

# ---------------------------------------------------------------- 15. interface monument
@engine("interface-monument", label="Interface monument", pattern="no phone: one real region of the screen, huge",
        type_preset="bold-geometric",
        mood="the product is the poster: a real crop of the screen fills most of the panel, edge to edge on odd "
             "panels and inset on even ones, one short headline",
        axes={"device": "ui-only", "composition": "poster", "background": "flat", "type": "display",
              "color": "mono", "eye": "focal"})
def interface_monument(e: E):
    N = e.N
    layers = []
    for i in range(1, N + 1):
        c = i - 0.5
        bleed = i % 2 == 1
        top = i % 4 in (1, 2)
        crop = [0.0, 0.06, 1.0, 0.52] if top else [0.0, 0.34, 1.0, 0.52]
        w = 1.0 if bleed else 0.86
        h = w * 0.52 * 2.17  # in u; one u is the panel width on a phone
        y = 1.0 - h / 2.17 / 2 + (0.0 if bleed else -0.05)
        layers.append(e.cap(i, y=0.06, x=0.08, w=0.84, size=0.135 if i == 1 else 0.115, color=e.ink_on("bg"),
                            accent=e.accent_on("bg"), sub=True))
        layers.append(e.card(i, crop, c, y, w, radius=0 if bleed else 0.05, shadow="none" if bleed else "soft",
                             border=None if bleed else "ink@0.08"))
    return {"background": [{"type": "solid", "color": "bg"}], "layers": layers}


# ---------------------------------------------------------------- 16. specimen sheet
@engine("specimen-sheet", label="Specimen sheet", pattern="a ruled grid of real UI exhibits with mono labels",
        type_preset="modern-tech",
        mood="a type specimen for an interface: one large exhibit and two details in a hairline grid, numbered "
             "like plates in a catalogue",
        axes={"device": "ui-only", "composition": "grid", "background": "pattern", "type": "mono",
              "color": "cool", "eye": "rows"})
def specimen_sheet(e: E):
    N = e.N
    layers = [{"type": "shape", "kind": "dots", "x": 0, "y": 0, "w": N * 3.0, "h": 2.2, "gap": 0.03,
               "r": 0.0016, "fill": "ink@0.18"}]
    for i in range(1, N + 1):
        c = i - 0.5
        cap = e.cap(i, y=0.055, x=0.08, w=0.84, size=0.12 if i == 1 else 0.105, color="ink", sub=False)
        cap["items"].insert(0, {"role": "kicker", "text": f"PL. {i:02d}", "color": "accent", "font": "mono"})
        layers.append(cap)
        sid, crops = e.crops(i, 3)
        big = [0.0, 0.07, 1.0, 0.42]
        layers.append(e.card(i, big, c, 0.265 + 0.84 * 0.42 / 2, 0.84, screen=sid,
                             radius=0.03, shadow="contact", border="ink@0.25"))
        for k, b in enumerate(crops[:2]):
            x = c + (-0.215 if k == 0 else 0.215)
            bw = 0.4
            bh = min(bw * (b[3] / max(b[2], 0.01)) * 2.17, 0.5)  # in u, capped so tall blocks stay in the row
            crop = b if bw * (b[3] / max(b[2], 0.01)) * 2.17 <= 0.5 else [b[0], b[1], b[2], b[2] * 0.5 / 2.17 / bw]
            layers.append(e.card(i, crop, x, 0.74 + bh / 2.17 / 2, bw, screen=sid, radius=0.03, shadow="contact",
                                 border="ink@0.25"))
            layers.append({"type": "text", "panel": i, "x": 0.08 if k == 0 else 0.515, "y": 0.715, "w": 0.4,
                           "align": "start", "anchor": "bottom", "color": "muted",
                           "items": [{"role": "kicker", "text": f"{i:02d}.{k + 1}", "font": "mono"}]})
        layers.append({"type": "shape", "kind": "rect", "x": c, "y": 0.69, "w": 0.86, "h": 0.002, "fill": "ink@0.3"})
    return {"background": [{"type": "solid", "color": "bg"}], "layers": layers}


# ---------------------------------------------------------------- 17. field journal
@engine("field-journal", label="Field journal", pattern="paper, a margin column of notes, a phone on the page",
        type_preset="premium-editorial",
        mood="a working notebook: the headline set like a chapter title, the explanation in a ruled margin, a "
             "dashed hand line from the note to the phone",
        axes={"device": "full", "composition": "column", "background": "texture", "type": "serif",
              "color": "paper", "eye": "margin"},
        art={"role": "texture", "brief": "an almost plain sheet of warm, uncoated paper seen flat and evenly lit: "
             "fine fibres, a faint deckle tooth, two or three soft pencil smudges near the edges; no writing, "
             "no lines, no objects"})
def field_journal(e: E):
    N = e.N
    tex = e.art_of("texture")
    bgs = [{"type": "solid", "color": "bg"}]
    if tex:
        bgs.append({"type": "image", "art": tex, "fit": "cover", "opacity": 0.9})
    layers = [{"type": "shape", "kind": "dots", "x": 0, "y": 0, "w": N * 3.0, "h": 2.2, "gap": 0.012,
               "r": 0.0012, "fill": "ink@0.06"}]
    for i in range(1, N + 1):
        c = i - 0.5
        right = i % 2 == 1  # the phone's side; the margin is opposite
        mx = 0.06 if right else 0.6
        cap = e.cap(i, y=0.06, x=0.07, w=0.86, size=0.12 if i == 1 else 0.1, color="ink", sub=False)
        cap["items"].insert(0, {"role": "kicker", "text": f"No. {i}", "color": "accent", "font": "mono"})
        layers.append(cap)
        if e.sb[i - 1].get("sub"):
            layers.append({"type": "text", "panel": i, "x": mx, "y": 0.42, "w": 0.34, "align": "start",
                           "anchor": "top", "color": "ink",
                           "items": [{"role": "sub", "copy": f"{e.sb[i - 1]['id']}.sub", "opacity": 0.85, "max_lines": 7}]})
        rule_x = (i - 1) + (0.42 if right else 0.58)
        layers.append({"type": "shape", "kind": "rect", "x": rule_x, "y": 0.6, "w": 0.002, "h": 0.8,
                       "fill": "accent@0.5"})
        px = c + (0.2 if right else -0.2)
        layers.append(e.dev(i, px, 0.66, 0.56, (0, 0, 2 if right else -2), shadow="contact", finish="silver"))
        nx = (i - 1) + (mx + 0.2)
        layers.append({"type": "shape", "kind": "path", "points": [[nx, 0.39], [(nx + px) / 2, 0.34],
                                                                  [px + (-0.12 if right else 0.12), 0.38]],
                       "stroke": "accent", "width": 0.005, "dash": 0.014, "gap": 0.012})
    return {"background": bgs, "layers": layers}


# ---------------------------------------------------------------- 18. type weave
@engine("type-weave", label="Type weave", pattern="the accent word, giant, woven behind a large cropped phone",
        type_preset="dynamic-sport",
        mood="a sports poster: duotone panels, the headline's key word set enormous across the middle, the phone "
             "rising from the bottom edge over it",
        axes={"device": "cropped", "composition": "poster", "background": "type", "type": "condensed",
              "color": "duotone", "eye": "zigzag"})
def type_weave(e: E):
    N = e.N
    bgs = [{"type": "solid", "color": "bg"}]
    layers = []
    for i in range(1, N + 1):
        c = i - 0.5
        col = "bg" if i % 2 else "bg2"
        bgs.append({"type": "panel", "panel": i, "color": col})
        ink = e.ink_on(col)
        word = e.accent_word(i)
        # size so the longest locale's word fits the panel: CJK glyphs are about a full em, Latin about half
        # a long accent phrase keeps only its longest word, so the giant type never runs into the next panel
        word = {k: (max(w.split(), key=len) if len(w) > 9 and " " in w else w) for k, w in word.items()}
        width = max((sum(1.0 if ord(ch) > 0x2E7F else 0.56 for ch in w) for w in word.values()), default=4)
        size = max(0.08, min(0.62, 0.9 / max(width, 1)))
        if word:
            layers.append({"type": "display", "text": word, "x": c, "y": 0.47, "size": size, "color": f"{ink}@0.22",
                           "tracking": -0.02, "z": 1})
        cap = e.cap(i, y=0.055, x=0.08, w=0.84, size=0.145 if i == 1 else 0.125, color=ink, sub=False,
                    accent=e.accent_on(col, ("accent", "light", "ink") if ink == "light" else ("accent2", "dark")))
        cap["accent_style"] = "color"
        layers.append(cap)
        layers.append(e.dev(i, c + (0.06 if i % 2 else -0.06), 0.97, 0.9, (0, 0, 4 if i % 2 else -4),
                            shadow="float", z=10))
    return {"background": bgs, "layers": layers}


# ---------------------------------------------------------------- 19. screen strips
@engine("screen-strips", label="Screen strips", pattern="the screen as three readable strips with numbered beats",
        type_preset="friendly-consumer",
        mood="a comic strip: three real bands of the interface (or three screens of one task) stacked with big "
             "numbers in a rail, each panel its own vivid colour",
        axes={"device": "ui-only", "composition": "strips", "background": "blocks", "type": "rounded",
              "color": "vivid", "eye": "rows"})
def screen_strips(e: E):
    N = e.N
    seq = ["accent", "accent2", "bg2"]
    bgs = [{"type": "solid", "color": "bg"}]
    layers = []
    for i in range(1, N + 1):
        c = i - 0.5
        col = seq[(i - 1) % 3]
        bgs.append({"type": "panel", "panel": i, "color": col})
        ink = e.ink_on(col)
        layers.append(e.cap(i, y=0.05, x=0.08, w=0.84, size=0.125 if i == 1 else 0.11, color=ink,
                            accent=e.accent_on(col, ("light", "ink", "dark") if ink == "light" else ("dark", "ink")),
                            sub=False))
        p = e.sb[i - 1]
        own = [s for s in [p.get("screen")] + list(p.get("screens") or []) if s]
        sid, bands = e.crops(i, 3)
        for k in range(3):
            if len(own) >= 3:
                scr, crop = own[k], [0.0, 0.12, 1.0, 0.24]   # three screens of one task: the same band of each
            else:
                scr, crop = sid, bands[k]
            bw = 0.74
            bh = bw * crop[3] / max(crop[2], 0.01) * 2.17
            if bh > 0.42:   # keep three bands inside the panel
                crop = [crop[0], crop[1], crop[2], crop[2] * 0.42 / 2.17 / bw]
            y = 0.33 + 0.215 * k
            layers.append(e.card(i, crop, c + 0.09, y, bw, screen=scr, radius=0.05, shadow="soft",
                                 rotate=(0, 0, (-1.5, 1, -0.5)[k])))
            layers.append({"type": "text", "panel": i, "x": 0.03, "y": y, "w": 0.16, "align": "center",
                           "anchor": "center", "color": ink,
                           "items": [{"role": "label", "text": str(k + 1), "size": 0.12, "font": "display"}]})
    return {"background": bgs, "layers": layers}


# ---------------------------------------------------------------- 20. card cascade
@engine("card-cascade", label="Card cascade", pattern="real UI cards tumbling down the panel, the full screen next door",
        type_preset="playful-illustration",
        mood="a soft pastel cascade: the screen's own cards fall diagonally down odd panels; even panels show the "
             "whole screen they came from, so every card has its context",
        axes={"device": "mixed", "composition": "cascade", "background": "pattern", "type": "rounded",
              "color": "pastel", "eye": "cascade"},
        art={"role": "pattern", "brief": "a seamless, very low-contrast repeating motif drawn from the app's "
             "subject (simple line icons of the subject, not UI), two tones of one pastel, lots of empty space"})
def card_cascade(e: E):
    N = e.N
    pat = e.art_of("pattern")
    bgs = [{"type": "linear", "angle": 170, "stops": [["bg", 0], ["bg2", 1]]}]
    if pat:
        bgs.append({"type": "image", "art": pat, "fit": "cover", "opacity": 0.35})
    layers = [] if pat else [{"type": "shape", "kind": "dots", "x": 0, "y": 0, "w": N * 3.0, "h": 2.2,
                              "gap": 0.06, "r": 0.006, "fill": "accent@0.12"}]
    for i in range(1, N + 1):
        c = i - 0.5
        layers.append(e.cap(i, y=0.055, x=0.08, w=0.84, size=0.125 if i == 1 else 0.11, color=e.ink_on("bg"),
                            accent=e.accent_on("bg"), sub=False))
        if i % 2 == 1 or N == 1:
            sid, crops = e.crops(i, 3)
            for k, b in enumerate(crops):
                bw = 0.78
                if bw * b[3] / max(b[2], 0.01) * 2.17 > 0.5:
                    b = [b[0], b[1], b[2], b[2] * 0.5 / 2.17 / bw]
                layers.append(e.card(i, b, c + (-0.06, 0.05, -0.02)[k], 0.4 + 0.2 * k, bw, screen=sid,
                                     rotate=(0, 0, (-3, 2.5, -1)[k]), radius=0.06, shadow="float", z=20 + k))
        else:
            layers.append(e.dev(i, c, 0.72, 0.74, (0, 0, 0), shadow="soft", finish="white"))
    return {"background": bgs, "layers": layers}


# ---------------------------------------------------------------- 21. annotated zoom
@engine("annotated-zoom", label="Annotated zoom", pattern="a phone and a magnified detail joined by a leader line",
        type_preset="modern-tech",
        mood="an engineering drawing: dark ground with a fine grid, the phone set right, one real detail pulled "
             "out large with a numbered leader line back to where it lives on the screen",
        axes={"device": "mixed", "composition": "annotated", "background": "pattern", "type": "mono",
              "color": "dark", "eye": "radial"})
def annotated_zoom(e: E):
    N = e.N
    acc = e.accent_on("dark", ("accent2", "accent", "light"))
    layers = [{"type": "shape", "kind": "dots", "x": 0, "y": 0, "w": N * 3.0, "h": 2.2, "gap": 0.04,
               "r": 0.0022, "fill": "light@0.16"}]
    for i in range(1, N + 1):
        c = i - 0.5
        right = i % 2 == 1
        cap = e.cap(i, y=0.055, x=0.08, w=0.84, size=0.12 if i == 1 else 0.105, color="light", accent=acc,
                    kicker_color=acc, sub=False)
        cap["items"].insert(0, {"role": "kicker", "text": f"FIG. {i}", "color": acc, "font": "mono"})
        layers.append(cap)
        dw, dx, dy = 0.62, c + (0.15 if right else -0.15), 0.64
        layers.append(e.dev(i, dx, dy, dw, (0, 0, 0), shadow={"style": "soft", "strength": 0.6}, finish="graphite"))
        sid, crops = e.crops(i, 1)
        b = crops[0]
        bw = 0.56
        if bw * b[3] / max(b[2], 0.01) * 2.17 > 0.45:
            b = [b[0], b[1], b[2], b[2] * 0.45 / 2.17 / bw]
        cx, cy = c + (-0.19 if right else 0.19), 0.86
        # where the detail sits on the phone: screen fraction -> panel coordinates (screen ~ 0.92 of the width)
        sx = dx + (b[0] + b[2] / 2 - 0.5) * dw * 0.92
        sy = dy + (b[1] + b[3] / 2 - 0.5) * dw * 0.92 * 2.17 / 2.17
        layers.append({"type": "shape", "kind": "ring", "x": sx, "y": sy, "r": 0.05, "stroke": acc, "width": 0.006,
                       "z": 30})
        layers.append({"type": "shape", "kind": "path", "points": [[sx, sy + 0.03], [(sx + cx) / 2, (sy + cy) / 2 + 0.02],
                                                                  [cx, cy - 0.06]],
                       "stroke": acc, "width": 0.004, "z": 30})
        layers.append(e.card(i, b, cx, cy, bw, screen=sid, radius=0.04, shadow="float", border=f"{acc}@0.9", z=40))
    return {"background": [{"type": "solid", "color": "dark"},
                           {"type": "radial", "x": N / 2, "y": 0.3, "r": N * 0.8, "color": "accent@0.18"}],
            "layers": layers}


# ---------------------------------------------------------------- 22. contact sheet
@engine("contact-sheet", label="Contact sheet", pattern="a photo collage with the real screen as the largest frame",
        type_preset="luxury-minimal",
        mood="a photographer's contact sheet: two small frames of the world the app is for, one large frame of the "
             "app itself, the cells hopping diagonally from panel to panel",
        axes={"device": "ui-only", "composition": "collage", "background": "photo", "type": "serif",
              "color": "natural", "eye": "diagonal"},
        art={"role": "photo", "brief": "an original, documentary-style photograph of the situation the app is used "
             "in, natural light, muted colour, shallow depth of field; no people's faces, no phones or other "
             "devices, no screens, no readable signs, logos or text"})
def contact_sheet(e: E):
    N = e.N
    layers = []
    for i in range(1, N + 1):
        c = i - 0.5
        flip = i % 2 == 0
        layers.append(e.cap(i, y=0.05, x=0.08, w=0.84, size=0.12 if i == 1 else 0.105, color="ink", sub=False))
        cells = [(c + (0.22 if flip else -0.2), 0.335, 0.48, 0.26), (c + (-0.25 if flip else 0.27), 0.335, 0.38, 0.26)]
        for k, (x, y, w, h) in enumerate(cells):
            art = e.art_of("photo", 2 * (i - 1) + k)
            if art:
                layers.append({"type": "image", "art": art, "x": x, "y": y, "w": w, "h": h * 2.17, "fit": "cover",
                               "radius": 0.012})
            else:
                layers.append({"type": "shape", "kind": "rect", "x": x, "y": y, "w": w, "h": h * 2.17,
                               "radius": 0.012, "fill": {"stops": [["bg2", 0], ["accent@0.35", 1]], "angle": 160}})
        layers.append(e.card(i, [0.0, 0.07, 1.0, 0.46], c + (-0.03 if flip else 0.03), 0.735, 0.88, radius=0.012,
                             shadow="contact", border="light"))
    return {"background": [{"type": "solid", "color": "bg"}], "layers": layers}


# ---------------------------------------------------------------- 23. flight path
SKY = [("#FFC9A3", 0.0), ("#BFD9F6", 0.22), ("#8EB6EE", 0.42), ("#9C86E0", 0.62), ("#3A2F86", 0.8), ("#14123A", 1.0)]


def _sky_at(t):
    for (c0, p0), (c1, p1) in zip(SKY, SKY[1:]):
        if t <= p1:
            k = (t - p0) / max(p1 - p0, 1e-6)
            a = [int(c0[i:i + 2], 16) for i in (1, 3, 5)]
            b = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
            return "#" + "".join(f"{round(x + (y - x) * k):02X}" for x, y in zip(a, b))
    return SKY[-1][0]


@engine("flight-path", label="Flight path", pattern="one route and one plane across the whole set, dawn to night",
        type_preset="friendly-consumer",
        mood="a journey: the sky turns from dawn to night across the panels, a dashed route runs through all of "
             "them, the plane crosses from the first screen into the second, and the app's own motifs (pills, "
             "clocks) sit along the way like waypoints",
        axes={"device": "full", "composition": "journey", "background": "sky", "type": "rounded",
              "color": "sky", "eye": "route"})
def flight_path(e: E):
    N = e.N
    motifs = (e.spec.get("design") or {}).get("motifs") or ["clock", "star"]
    rng = random.Random(f"flight-{e.spec['campaign'].get('seed', 7)}")
    bgs = [{"type": "linear", "angle": 90, "stops": [[c, p] for c, p in SKY]}]
    layers = []
    # the route: a gentle wave through every panel just under the headlines
    def ry(x):
        return 0.335 + 0.035 * math.sin(x * 2.1 + 0.6)
    pts = [[x / 4, ry(x / 4)] for x in range(0, N * 4 + 1)]
    plane_x = 1.0 if N > 1 else 0.7
    behind = [p for p in pts if p[0] <= plane_x - 0.12]
    ahead = [p for p in pts if p[0] >= plane_x + 0.12]
    if len(behind) > 1:
        layers.append({"type": "shape", "kind": "path", "points": behind, "stroke": "#FFFFFF@0.85", "width": 0.012})
    if len(ahead) > 1:
        layers.append({"type": "shape", "kind": "path", "points": ahead, "stroke": "#FFFFFF@0.75", "width": 0.007,
                       "dash": 0.018, "gap": 0.022})
    slope = (ry(plane_x + 0.01) - ry(plane_x - 0.01)) / 0.02 * 2.17  # y is a fraction of H, x of W
    ang = math.degrees(math.atan(slope))
    layers.append({"type": "shape", "kind": "glyph", "glyph": "plane", "x": plane_x, "y": ry(plane_x),
                   "size": 0.36, "rotate": ang - 8, "fill": "#FFFFFF", "fill2": "accent", "z": 30})
    if N > 2:   # a second, smaller plane coming in to land on the last panel
        lx = N - 0.3
        layers.append({"type": "shape", "kind": "glyph", "glyph": "plane", "x": lx, "y": ry(lx) + 0.02,
                       "size": 0.12, "rotate": 14, "fill": "#FFFFFF", "fill2": "accent", "z": 30})
    for i in range(1, N + 1):
        c = i - 0.5
        t = (i - 0.5) / N
        sky = _sky_at(t)
        dark = luminance(sky) < 0.3
        ink = "#FFFFFF" if dark else "dark"
        acc = "#C9C7FF" if dark else "accent"
        cap = e.cap(i, y=0.05, x=0.08, w=0.84, size=0.13 if i == 1 else 0.115, color=ink, accent=acc, sub=True)
        cap["accent_style"] = "color"
        layers.append(cap)
        # waypoint on the route at the panel's centre
        layers.append({"type": "shape", "kind": "circle", "x": c, "y": ry(c), "r": 0.022, "fill": "#FFFFFF"})
        layers.append({"type": "shape", "kind": "circle", "x": c, "y": ry(c), "r": 0.011, "fill": "accent"})
        if t < 0.6:   # clouds by day
            for k in range(2):
                layers.append({"type": "shape", "kind": "blob", "x": c + rng.uniform(-0.45, 0.45),
                               "y": rng.uniform(0.42, 0.95), "r": rng.uniform(0.12, 0.2), "sy": 0.45,
                               "fill": "#FFFFFF@0.55", "blur": 0.01})
        else:         # stars by night
            for k in range(5):
                layers.append({"type": "shape", "kind": "glyph", "glyph": "star", "x": c + rng.uniform(-0.45, 0.45),
                               "y": rng.uniform(0.3, 0.98), "size": rng.uniform(0.025, 0.05), "fill": "#FFFFFF@0.8",
                               "shadow": False})
        panel_m = [m for m in e.motifs(i, 3) if m != "plane"] or motifs
        tilt = (-3, 3)[i % 2]
        layers.append(e.dev(i, c + (0.03 if i % 2 else -0.03), 0.72, 0.64, (0, 0, tilt), shadow="float", z=10))
        # two motifs beside the phone, tumbling a little, over it at the edge so they feel alive
        for k, side in enumerate((-1, 1)):
            g = panel_m[k % len(panel_m)]
            layers.append({"type": "shape", "kind": "glyph", "glyph": g, "x": c + side * rng.uniform(0.38, 0.43),
                           "y": rng.uniform(0.5, 0.88), "size": rng.uniform(0.2, 0.26),
                           "rotate": rng.uniform(-40, 40), "z": 20,
                           "fill": "#FFFFFF" if g == "clock" else "accent",
                           "fill2": "accent" if g == "clock" else "#FFFFFF"})
    return {"background": bgs, "layers": layers}


# ---------------------------------------------------------------- 24. boarding pass
@engine("boarding-pass", label="Boarding pass", pattern="each panel a boarding pass: headline on the ticket, phone from the stub",
        type_preset="modern-tech",
        mood="the trip as paperwork: a cream ticket with notches and a perforated stub on a deep brand ground, "
             "mono panel numbers like seat rows, the panel's own pictogram in the stub, the phone rising out of it",
        axes={"device": "cropped", "composition": "ticket", "background": "objects", "type": "mono",
              "color": "brand", "eye": "top-down"})
def boarding_pass(e: E):
    N = e.N
    bgs = [{"type": "solid", "color": "bg"}]
    layers = [{"type": "shape", "kind": "dots", "x": 0, "y": 0, "w": N * 3.0, "h": 2.2, "gap": 0.05, "r": 0.003,
               "fill": "light@0.12"}]
    paper = "#FBF7EE"
    for i in range(1, N + 1):
        c = i - 0.5
        col = "bg" if i % 2 else "bg2"
        bgs.append({"type": "panel", "panel": i, "color": col})
        # the ticket: a rounded card with two notches and a dashed tear line above the stub
        tw, th, ty = 0.88, 0.8, 0.235
        tear = ty + th / 2.17 / 2 - 0.035
        layers.append({"type": "shape", "kind": "rect", "x": c, "y": ty, "w": tw, "h": th, "radius": 0.04,
                       "fill": paper, "rotate": (-1.2, 1.2)[i % 2]})
        for side in (-1, 1):
            layers.append({"type": "shape", "kind": "circle", "x": c + side * tw / 2, "y": tear, "r": 0.035,
                           "fill": col})
        layers.append({"type": "shape", "kind": "path", "points": [[c - tw / 2 + 0.05, tear],
                                                                  [c + tw / 2 - 0.05, tear]],
                       "stroke": "muted@0.6", "width": 0.004, "dash": 0.012, "gap": 0.01})
        cap = e.cap(i, y=0.075, x=0.11, w=0.62, size=0.11 if i == 1 else 0.095, color="#1B1830", accent="accent",
                    sub=False)
        cap["accent_style"] = "color"
        cap["items"].insert(0, {"role": "kicker", "text": f"{i:02d} / {N:02d}", "color": "muted", "font": "mono"})
        layers.append(cap)
        m = e.motifs(i, 1)[0]
        layers.append({"type": "shape", "kind": "glyph", "glyph": m, "x": c + 0.3, "y": 0.135, "size": 0.2,
                       "fill": "accent", "fill2": paper, "shadow": False})
        layers.append(e.dev(i, c, 0.83, 0.8, (0, 0, 0), shadow="float", z=10))
        for k, g in enumerate(e.motifs(i, 3)[1:3]):   # the stub: two small pictograms like a fare class
            layers.append({"type": "shape", "kind": "glyph", "glyph": g, "x": c - 0.3 + 0.13 * k, "y": tear + 0.025,
                           "size": 0.1, "fill": "muted", "fill2": paper, "shadow": False, "z": 20})
    return {"background": bgs, "layers": layers}


# ---------------------------------------------------------------- 25. orbit
@engine("orbit", label="Orbit", pattern="the phone at the centre of rings that run through every panel, motifs as satellites",
        type_preset="bold-geometric",
        mood="a night sky of time zones: concentric dashed rings centred on each phone overlap the neighbours so the "
             "set reads as one system, the panel's pictograms sit on the rings as glowing markers",
        axes={"device": "full", "composition": "orbit", "background": "rings", "type": "display",
              "color": "dark", "eye": "radial"})
def orbit(e: E):
    N = e.N
    layers = [{"type": "shape", "kind": "dots", "x": 0, "y": 0, "w": N * 3.0, "h": 2.2, "gap": 0.07, "r": 0.003,
               "fill": "light@0.25"}]
    for i in range(1, N + 1):
        c = i - 0.5
        cy = 0.66
        for k, r in enumerate((0.48, 0.72, 0.98)):
            layers.append({"type": "shape", "kind": "ring", "x": c, "y": cy, "r": r, "stroke": "accent@0.55",
                           "width": 0.004 if k else 0.006, "dash": 0.012 if k else 0, "opacity": 0.9 - 0.2 * k})
        layers.append({"type": "glow", "x": c, "y": cy, "r": 0.7, "color": "accent", "opacity": 0.45})
        cap = e.cap(i, y=0.05, x=0.08, w=0.84, size=0.125 if i == 1 else 0.11, color="#FFFFFF", accent="#C9C7FF",
                    sub=True)
        cap["accent_style"] = "color"
        layers.append(cap)
        layers.append(e.dev(i, c, cy + 0.02, 0.6, (0, 0, 0), shadow="soft", z=10))
        for k, (g, ang) in enumerate(zip(e.motifs(i, 2), (200, 335))):
            r = 0.72
            a = math.radians(ang)
            x, y = c + r * math.cos(a), cy + r * math.sin(a) / 2.17
            layers += e.badge(g, x, y, 0.22, disc="#FFFFFF", fill="accent", fill2="#FFFFFF", z=20,
                              ring="accent@0.6")
    return {"background": [{"type": "solid", "color": "#0D0B26"},
                           {"type": "radial", "x": N / 2, "y": 0.2, "r": N * 0.9, "color": "accent@0.22"}],
            "layers": layers}


# ---------------------------------------------------------------- 26. travel stickers
@engine("travel-stickers", label="Travel stickers", pattern="a scrapbook page: taped phone, stickers and passport stamps",
        type_preset="playful-illustration",
        mood="a travel diary: kraft-paper ground, the phone taped on at a slight angle, the panel's pictograms as "
             "die-cut stickers with white borders and dashed passport-stamp rings, a hand-drawn arrow to the screen",
        axes={"device": "full", "composition": "scrapbook", "background": "kraft", "type": "rounded",
              "color": "natural", "eye": "zigzag"})
def travel_stickers(e: E):
    N = e.N
    rng = random.Random(f"stickers-{e.spec['campaign'].get('seed', 7)}")
    layers = [{"type": "shape", "kind": "dots", "x": 0, "y": 0, "w": N * 3.0, "h": 2.2, "gap": 0.018, "r": 0.0015,
               "fill": "ink@0.07"}]
    for i in range(1, N + 1):
        c = i - 0.5
        left = i % 2 == 1
        cap = e.cap(i, y=0.055, x=0.08, w=0.84, size=0.125 if i == 1 else 0.11, color="ink", accent="accent",
                    sub=False)
        cap["accent_style"] = "color"
        layers.append(cap)
        tilt = (-4, 4)[i % 2]
        px = c + (0.06 if left else -0.06)
        layers.append(e.dev(i, px, 0.7, 0.66, (0, 0, tilt), shadow="contact", finish="white", z=10))
        for side in (-1, 1):   # tape over the top corners
            layers.append({"type": "shape", "kind": "rect", "x": px + side * 0.22, "y": 0.385, "w": 0.2, "h": 0.06,
                           "rotate": side * 35 + tilt, "fill": "#F1E6C8@0.85", "z": 15})
        gs = e.motifs(i, 3)
        sx = c + (-0.33 if left else 0.33)
        layers.append({"type": "shape", "kind": "ring", "x": sx, "y": 0.5, "r": 0.17, "stroke": "accent2@0.8",
                       "width": 0.008, "dash": 0.012, "z": 20})
        layers.append({"type": "shape", "kind": "ring", "x": sx, "y": 0.5, "r": 0.135, "stroke": "accent2@0.8",
                       "width": 0.005, "z": 20})
        layers.append({"type": "shape", "kind": "glyph", "glyph": gs[0], "x": sx, "y": 0.5, "size": 0.15,
                       "rotate": rng.uniform(-20, 20), "fill": "accent2", "fill2": "#F4ECDD", "shadow": False, "z": 20})
        for k, g in enumerate(gs[1:3]):
            x = c + (0.36 if left else -0.36) * (1 if k == 0 else 0.9)
            y = (0.72, 0.9)[k]
            layers += e.badge(g, x, y, 0.27, disc="#FFFFFF", fill="accent", fill2="#FFFFFF",
                              rotate=rng.uniform(-25, 25), z=25)
        ax = c + (-0.3 if left else 0.3)
        layers.append({"type": "shape", "kind": "path", "points": [[ax, 0.6], [ax + (0.02 if left else -0.02), 0.66],
                                                                  [px + (-0.2 if left else 0.2), 0.7]],
                       "stroke": "ink@0.7", "width": 0.005, "z": 25})
    return {"background": [{"type": "solid", "color": "bg"}], "layers": layers}


# ---------------------------------------------------------------- 27. breakout
@engine("breakout", label="Breakout", pattern="a real card bursts out of the phone, colour shifts panel to panel, mosaic closer",
        type_preset="bold-geometric",
        mood="the advert that points: each panel a new saturated colour from one family, the key card of the screen "
             "scaled past both edges of the phone with a deep shadow, one pictogram sticker on it, and a closing "
             "panel that is a mosaic of the screens",
        axes={"device": "mixed", "composition": "breakout", "background": "colour-shift", "type": "display",
              "color": "vivid", "eye": "focal"})
def breakout(e: E):
    N = e.N
    from .diversity import _from_hls, _hls
    h, l, sat = _hls(e.spec["design"]["palette"].get("accent", "#5856D6"))
    bgs = [{"type": "solid", "color": "bg"}]
    layers = []
    for i in range(1, N + 1):
        c = i - 0.5
        col = _from_hls(h + 0.06 * ((i - 1) % 4) - 0.06, 0.5 if i % 2 else 0.38, min(0.9, sat + 0.1))
        bgs.append({"type": "panel", "panel": i, "color": col})
        cap = e.cap(i, y=0.05, x=0.08, w=0.84, size=0.135 if i == 1 else 0.12, color="#FFFFFF", accent="#FFE07A",
                    sub=False)
        cap["accent_style"] = "color"
        layers.append(cap)
        if i == N and N >= 4:   # the closer: a mosaic of the other screens
            others = []
            for p in e.sb:
                if p.get("screen") and p["screen"] not in others:
                    others.append(p["screen"])
            for k, scr in enumerate(others[:4]):
                x = c + (-0.22 if k % 2 == 0 else 0.22)
                y = 0.47 + (k // 2) * 0.33
                layers.append(e.card(i, [0.0, 0.0, 1.0, 0.62], x, y, 0.4, screen=scr, radius=0.06, shadow="float",
                                     rotate=(0, 0, (-3, 2, 2, -3)[k])))
            continue
        layers.append(e.dev(i, c, 0.72, 0.68, (0, 0, 0), shadow="float", z=10))
        sid, crops = e.crops(i, 1)
        b = crops[0]
        bw = 0.94
        if bw * b[3] / max(b[2], 0.01) * 2.17 > 0.36:
            b = [b[0], b[1], b[2], b[2] * 0.36 / 2.17 / bw]
        layers.append(e.card(i, b, c, 0.62, bw, screen=sid, radius=0.05, shadow="float", z=25))
        g = e.motifs(i, 1)[0]
        layers += e.badge(g, c + 0.36, 0.53, 0.18, disc="#FFE07A", fill="#1B1830", fill2="#FFE07A", rotate=12, z=40)
    return {"background": bgs, "layers": layers}


# The first fourteen engines on the six axes (the newer ones declare theirs in @engine).
for _name, _ax in {
    "panoramic-flow": ("full", "panorama", "shapes", "rounded", "brand", "sweep"),
    "floating-3d": ("multiple", "centered", "gradient", "sans", "brand", "top-down"),
    "editorial": ("cropped", "column", "flat", "serif", "paper", "top-down"),
    "typographic-hero": ("cropped", "poster", "type", "display", "brand", "zigzag"),
    "feature-explosion": ("mixed", "centered", "gradient", "sans", "brand", "radial"),
    "cinematic": ("cropped", "centered", "gradient", "sans", "dark", "bottom-up"),
    "minimal-premium": ("full", "centered", "gradient", "serif", "mono", "top-down"),
    "device-cluster": ("multiple", "centered", "gradient", "sans", "brand", "top-down"),
    "immersive": ("full", "panorama", "photo", "serif", "natural", "sweep"),
    "illustrated": ("full", "panorama", "shapes", "rounded", "vivid", "sweep"),
    "big-type": ("full", "split", "blocks", "display", "vivid", "diagonal"),
    "before-after": ("full", "split", "blocks", "serif", "duotone", "zigzag"),
    "glass": ("mixed", "centered", "gradient", "sans", "pastel", "top-down"),
    "sticker-pop": ("full", "centered", "gradient", "rounded", "vivid", "top-down"),
}.items():
    ENGINES[_name]["axes"] = dict(zip(AXES, _ax))
ENGINES["immersive"]["art"] = {"role": "scene", "brief": "one wide, calm photograph or painting of the place or "
                               "moment the app is for, with large quiet areas at the top and centre for headlines "
                               "and phones; no people's faces, devices, screens, text or logos"}

# Fallback when the picker is not used (`concepts --engines` and older callers).
DEFAULT_SIX = ["panoramic-flow", "floating-3d", "editorial", "typographic-hero", "feature-explosion", "cinematic"]


def generate(spec, name, blocks=None):
    if name not in ENGINES:
        raise ValueError(f"unknown engine {name!r}; one of {', '.join(ENGINES)}")
    e = E(spec, blocks)
    return complete(e, ENGINES[name]["fn"](e))


def complete(e: E, out):
    """Place what the storyboard asks for that the engine left out: chips and a stat join the panel's caption
    block (so they move with it and never collide with it), a footnote goes to the free edge of the panel."""
    layers = out["layers"]
    for i in range(1, e.N + 1):
        p = e.sb[i - 1] if i - 1 < len(e.sb) else {}
        pid = p.get("id")
        texts = [L for L in layers if L.get("type") == "text" and L.get("panel") == i]
        copies = {it.get("copy") for L in texts for it in L.get("items") or []}
        main = next((L for L in texts if any(it.get("role") == "headline" for it in L.get("items") or [])), None)
        if main and p.get("chips") and f"{pid}.chips" not in copies:
            main["items"].append({"role": "chips", "copy": f"{pid}.chips"})
            main.setdefault("chip_style", "solid")
        if main and p.get("stat") and f"{pid}.stat" not in copies:
            k = next(j for j, it in enumerate(main["items"]) if it.get("role") == "headline") + 1
            main["items"][k:k] = [{"role": "stat", "copy": f"{pid}.stat", "color": main.get("accent", "accent")}] + (
                [{"role": "label", "copy": f"{pid}.stat_label"}] if p.get("stat_label") else [])
        if p.get("footnote") and f"{pid}.footnote" not in copies:
            bottom = bool(main and main.get("anchor") == "bottom")
            layers.append(e.footnote(i, color=(main or {}).get("color", "ink"), top=bottom))
    return out
