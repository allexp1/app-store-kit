"""Pick concept directions that really differ, and give each its own palette family and type preset.

Six concepts from one layout family read as one idea in six colours. The picker scores every engine on six
axes (engines.AXES) and searches every combination for the set whose closest pair still differs the most:

  - any two concepts differ on at least `min_axes` axes (default 3),
  - and on at least two of the structural ones (device, composition, background, eye), so a palette and a font
    change cannot pass for a new layout,
  - no two share a palette family or a type preset,
  - at least one keeps the brand's own palette,
  - engines that need artwork the campaign does not have are left out.

Ties break on the total distance, then on a seeded order, so the same campaign always gets the same six and a
different `campaign.seed` explores a different six.
"""
from __future__ import annotations

import colorsys
import itertools
import random

from .engines import AXES, ENGINES

STRUCTURAL = ("device", "composition", "background", "eye")

# Palette families. "brand" keeps the campaign palette as it is; the others derive from the brand accent, so every
# direction still carries the app's colour on its key word.
FAMILIES = ("brand", "sky", "dark", "paper", "mono", "cool", "duotone", "vivid", "pastel", "natural")

# Type presets an axis value can wear, in order of preference.
TYPE_FOR = {
    "sans": ["modern-tech", "bold-geometric"],
    "serif": ["premium-editorial", "luxury-minimal"],
    "display": ["bold-geometric", "dynamic-sport"],
    "condensed": ["dynamic-sport", "bold-geometric"],
    "rounded": ["friendly-consumer", "playful-illustration"],
    "mono": ["modern-tech"],
}


# ---------------------------------------------------------------- colour helpers
def _rgb(h):
    h = h.lstrip("#")[:6]
    if len(h) == 3:   # shorthand #f50 -> #ff5500, as the spec validator and the renderer accept
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _hex(rgb):
    return "#" + "".join(f"{round(max(0, min(1, c)) * 255):02X}" for c in rgb)


def _hls(h):
    return colorsys.rgb_to_hls(*_rgb(h))


def _from_hls(hh, ll, ss):
    return _hex(colorsys.hls_to_rgb(hh % 1.0, max(0, min(1, ll)), max(0, min(1, ss))))


def family_palette(base: dict, family: str) -> dict:
    """A full palette (bg bg2 ink muted accent accent2 dark light) for a family, from the brand palette."""
    if family in ("brand", "sky"):   # sky: the engine paints its own day-to-night sky over the brand palette
        return dict(base)
    acc = base.get("accent", "#5856D6")
    h, l, s = _hls(acc)
    deep = _from_hls(h, 0.28, min(0.75, s))
    if family == "dark":
        return {"bg": _from_hls(h, 0.07, 0.35), "bg2": _from_hls(h, 0.13, 0.4), "ink": "#FFFFFF",
                "muted": _from_hls(h, 0.75, 0.25), "accent": _from_hls(h, max(l, 0.62), s),
                "accent2": _from_hls(h + 0.08, 0.7, 0.9), "dark": _from_hls(h, 0.05, 0.3), "light": "#FFFFFF"}
    if family == "paper":
        return {"bg": "#F3EDE2", "bg2": "#E7DDCC", "ink": "#2B241B", "muted": "#6F6352", "accent": deep,
                "accent2": "#A4532F", "dark": "#2B241B", "light": "#FFFCF6"}
    if family == "mono":
        return {"bg": "#F4F4F3", "bg2": "#E4E4E2", "ink": "#121212", "muted": "#5C5C5A", "accent": deep,
                "accent2": "#121212", "dark": "#121212", "light": "#FFFFFF"}
    if family == "cool":
        return {"bg": "#EDF1F5", "bg2": "#DCE3EA", "ink": "#16202B", "muted": "#566271", "accent": deep,
                "accent2": "#2F6F8F", "dark": "#16202B", "light": "#FFFFFF"}
    if family == "duotone":
        return {"bg": _from_hls(h, 0.42, min(0.85, s + 0.1)), "bg2": _from_hls(h + 0.5, 0.55, 0.85),
                "ink": "#FFFFFF", "muted": "#FFFFFF", "accent": _from_hls(h + 0.5, 0.7, 0.95),
                "accent2": _from_hls(h, 0.2, 0.8), "dark": _from_hls(h, 0.12, 0.6), "light": "#FFFFFF"}
    if family == "vivid":
        return {"bg": "#FFFFFF", "bg2": _from_hls(h + 0.33, 0.62, 0.85), "ink": "#141414", "muted": "#4A4A4A",
                "accent": _from_hls(h, 0.5, min(0.95, s + 0.15)), "accent2": _from_hls(h + 0.62, 0.52, 0.9),
                "dark": "#141414", "light": "#FFFFFF"}
    if family == "pastel":
        return {"bg": _from_hls(h, 0.95, 0.6), "bg2": _from_hls(h + 0.1, 0.88, 0.55), "ink": _from_hls(h, 0.16, 0.5),
                "muted": _from_hls(h, 0.4, 0.2), "accent": _from_hls(h, 0.48, s), "accent2": _from_hls(h + 0.1, 0.6, 0.7),
                "dark": _from_hls(h, 0.16, 0.5), "light": "#FFFFFF"}
    if family == "natural":
        return {"bg": "#E9E5DB", "bg2": "#D5D0C1", "ink": "#22261F", "muted": "#5D6354", "accent": "#9C4F2E",
                "accent2": "#6E7F5C", "dark": "#22261F", "light": "#FBFAF6"}
    raise ValueError(f"unknown palette family {family!r}; one of {', '.join(FAMILIES)}")


# ---------------------------------------------------------------- the picker
def distance(a: str, b: str) -> tuple:
    """(axes that differ, structural axes that differ) between two engines."""
    A, B = ENGINES[a]["axes"], ENGINES[b]["axes"]
    return (sum(A.get(k) != B.get(k) for k in AXES), sum(A.get(k) != B.get(k) for k in STRUCTURAL))


def available(spec: dict) -> list:
    """Engines this campaign can render well: an engine that needs artwork is left out until the art exists."""
    roles = {a.get("role") for a in (spec.get("artwork") or {}).values()}
    out = []
    for name, meta in ENGINES.items():
        if meta["needs"] and "scene" not in roles:
            continue
        art = meta.get("art")
        if art and art.get("role") == "photo" and "photo" not in roles:
            continue
        out.append(name)
    return out


def _types_for(names) -> dict | None:
    """Distinct type presets for the chosen engines (the engine's own first), or None when impossible."""
    prefs = [[ENGINES[n]["type"]] + [t for t in TYPE_FOR.get(ENGINES[n]["axes"].get("type"), [])
                                     if t != ENGINES[n]["type"]] for n in names]
    def go(i, used):
        if i == len(names):
            return {}
        for t in prefs[i]:
            if t not in used:
                rest = go(i + 1, used | {t})
                if rest is not None:
                    return {names[i]: t, **rest}
        return None
    return go(0, frozenset())


def pick(spec: dict, n: int = 6, *, min_axes: int = 3, keep: list | None = None, pool: list | None = None) -> list:
    """The n most different engines for this campaign (see module doc). `keep` forces engines into the set."""
    pool = list(pool or available(spec))
    keep = [k for k in (keep or []) if k in ENGINES]
    for k in keep:
        if k not in pool:
            pool.append(k)
    rng = random.Random(f"diversity-{(spec.get('campaign') or {}).get('seed', 7)}")
    rng.shuffle(pool)
    n = min(n, len(pool))
    best, best_key = None, None
    rest = [p for p in pool if p not in keep]
    for combo in itertools.combinations(rest, n - len(keep)):
        names = keep + list(combo)
        fams = [ENGINES[x]["axes"]["color"] for x in names]
        if len(set(fams)) < len(fams) or not {"brand", "sky"} & set(fams):
            continue
        mins, total, ok = 99, 0, True
        for a, b in itertools.combinations(names, 2):
            d, ds = distance(a, b)
            if d < min_axes or ds < 2:
                ok = False
                break
            mins, total = min(mins, d), total + d
        if not ok:
            continue
        key = (mins, total)
        if best_key is None or key > best_key:
            types = _types_for(names)
            if types is None:
                continue
            best, best_key = names, key
    if best is None:
        raise ValueError(f"no set of {n} engines differs on {min_axes}+ axes; lower min_axes or the count")
    return best


def concepts(spec: dict, n: int = 6, *, brand_only: bool = False, keep: list | None = None) -> list:
    """Concept entries for `campaign.py concepts`: {engine, family, type, palette, name, rationale}."""
    names = pick(spec, n, keep=keep)
    types = _types_for(names) or {k: ENGINES[k]["type"] for k in names}
    base = (spec.get("design") or {}).get("palette") or {}
    out = []
    for k in names:
        meta = ENGINES[k]
        fam = "brand" if brand_only else meta["axes"]["color"]
        ax = meta["axes"]
        out.append({"engine": k, "family": fam, "type": types[k], "palette": family_palette(base, fam),
                    "rationale": f"{ax['device']} device · {ax['composition']} · {ax['background']} ground · "
                                 f"{fam} palette · eye path {ax['eye']}"})
    return out
