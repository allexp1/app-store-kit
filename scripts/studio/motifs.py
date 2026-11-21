"""Pictograms that fit the app: read the campaign's own words and pick glyphs for each panel.

A medication panel gets capsules and a blister pack, a landing panel a plane and a pin, a sleep panel the moon.
The words read are the panel's headline and sub (primary locale), its screen id, the app name and description,
and `design.motifs` (the owner's list, always first in the app-wide set). Glyph drawings live in scene.GLYPHS.
"""
from __future__ import annotations

import re

# glyph -> words that call for it (lower case; matched as word starts, so "medic" finds "medication")
LEXICON = {
    "plane": ["fly", "flight", "flies", "takeoff", "take off", "airport", "jet", "plane", "land", "board", "travel",
              "trip"],
    "globe": ["world", "zone", "time zone", "international", "abroad", "global", "every clock", "cities", "country"],
    "ticket": ["trip", "boarding", "ticket", "journey", "before you fly", "itinerary", "booking"],
    "suitcase": ["pack", "luggage", "suitcase", "trip", "travel", "holiday", "vacation"],
    "passport": ["abroad", "border", "passport", "visa", "country"],
    "capsule": ["medic", "dose", "pill", "drug", "prescription", "vitamin", "metformin", "tablet", "pharma"],
    "blister": ["medic", "dose", "pill", "take it", "tablet", "health", "supply"],
    "clock": ["time", "clock", "hour", "minute", "schedule", "later", "o'clock", "on the clock", "timer"],
    "bell": ["alarm", "ring", "remind", "notif", "wake", "snooze", "alert"],
    "moon": ["sleep", "night", "nap", "jet lag", "bed", "dark", "silent", "focus"],
    "sun": ["morning", "wake", "light", "day", "sunrise", "sky"],
    "house": ["home"],
    "pin": ["here", "location", "place", "arriv", "land", "city", "where", "map"],
    "heart": ["health", "care", "wellbeing", "heart", "wellness"],
    "drop": ["water", "hydrat", "blood", "drink"],
    "cloud": ["weather", "cloud", "sky", "rain"],
    "star": ["favourite", "favorite", "best", "star"],
}

FALLBACK = ["star", "cloud"]


def _words(text):
    return " " + re.sub(r"[^a-z' ]+", " ", str(text or "").lower().replace("*", "")) + " "


def score(text: str) -> dict:
    """{glyph: hits} for one piece of text."""
    t = _words(text)
    out = {}
    for g, words in LEXICON.items():
        n = sum(1 for w in words if f" {w}" in t)
        if n:
            out[g] = n
    return out


def _primary(value, spec):
    if isinstance(value, dict):
        prim = (spec.get("campaign") or {}).get("primary_locale")
        return value.get(prim) or value.get("*") or next(iter(value.values()), "")
    return value or ""


def app_motifs(spec: dict, n: int = 6) -> list:
    """The app-wide set: the owner's `design.motifs` first, then what the whole campaign talks about most."""
    own = [g for g in ((spec.get("design") or {}).get("motifs") or []) if g in LEXICON]
    app = spec.get("app") or {}
    text = " ".join([str(app.get("name", "")), str(app.get("description", "")), str(app.get("category", ""))]
                    + [f"{_primary(p.get('headline'), spec)} {_primary(p.get('sub'), spec)} {p.get('screen', '')}"
                       for p in spec.get("storyboard") or []])
    ranked = sorted(score(text).items(), key=lambda kv: -kv[1])
    out = list(own)
    for g, _ in ranked:
        if g not in out:
            out.append(g)
    for g in FALLBACK:
        if g not in out:
            out.append(g)
    return out[:max(n, len(own))]


def panel_motifs(spec: dict, panel: int, n: int = 3) -> list:
    """The n glyphs that fit this panel best: its own words first, then the app-wide set."""
    p = (spec.get("storyboard") or [])[panel - 1]
    tally = {}
    for text, weight in ((_primary(p.get("headline"), spec), 3), (_primary(p.get("sub"), spec), 2),
                         (f"{p.get('screen', '')} {p.get('id', '')}".replace("-", " "), 1)):
        for g, k in score(text).items():
            tally[g] = tally.get(g, 0) + k * weight
    own = [g for g, _ in sorted(tally.items(), key=lambda kv: -kv[1])]
    out = []
    for g in own + app_motifs(spec):
        if g not in out:
            out.append(g)
    return out[:n]
