"""Composition engines: each turns the storyboard + design tokens into background and layers.

They are different composition systems, not colour swaps: where the devices go, how they are lit, how type
and image share the panel, and what ties the panels together all change per engine. Each output is plain
campaign layers, so `campaign.py eject` can write it out for hand tuning.

Every engine follows the same hard rules: every panel shows real UI from its own storyboard screen, the
headline sits wholly inside its panel, and panel 1 carries the strongest message at the largest size.
"""
from __future__ import annotations

import random

from .scene import luminance

ENGINES = {}


def engine(name, *, label, pattern, type_preset, mood, needs=None):
    def deco(fn):
        ENGINES[name] = {"fn": fn, "label": label, "pattern": pattern, "type": type_preset, "mood": mood,
                         "needs": needs or []}
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
