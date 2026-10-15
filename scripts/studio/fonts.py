"""Typography presets and a local cache of open-licence (Google Fonts, SIL OFL / Apache) font files.

Fonts are downloaded once into the cache and referenced by file:// URL, so a render is repeatable and offline
after the first run. Proprietary brand fonts are never downloaded or copied: the campaign points at the
owner's own files (design.type.files) and they are referenced in place.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import urllib.parse
import urllib.request

CACHE = pathlib.Path(os.environ.get("APP_STORE_KIT_CACHE", "~/.cache/app-store-kit")).expanduser() / "fonts"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0 Safari/537.36")  # the CSS API serves woff2 only to a modern browser agent

# Each preset: display face, text face, and how the headline is set. Sizes are in u (see scene.py).
PRESETS = {
    "premium-editorial": {
        "display": {"family": "Instrument Serif", "weights": [400], "italic": True, "weight": 400,
                    "tracking": -0.02, "leading": 0.98, "case": "none", "scale": 1.18},
        "text": {"family": "Geist", "weights": [400, 500, 600], "weight": 500},
        "accent_style": "italic",
        "mood": "magazine restraint: a serif headline with an italic accent word, quiet sans for the rest",
    },
    "bold-geometric": {
        "display": {"family": "Unbounded", "weights": [700, 800], "weight": 800,
                    "tracking": -0.03, "leading": 1.0, "case": "none", "scale": 0.86},
        "text": {"family": "Manrope", "weights": [500, 700], "weight": 600},
        "accent_style": "color",
        "mood": "confident, wide geometric display; works for utility and finance",
    },
    "modern-tech": {
        "display": {"family": "Geist", "weights": [600, 700, 800], "weight": 700,
                    "tracking": -0.045, "leading": 1.0, "case": "none", "scale": 1.0},
        "text": {"family": "Geist", "weights": [400, 500], "weight": 500},
        "mono": {"family": "Geist Mono", "weights": [500]},
        "accent_style": "color",
        "mood": "precise neo-grotesk, tight tracking, mono kickers",
    },
    "friendly-consumer": {
        "display": {"family": "Bricolage Grotesque", "weights": [700, 800], "weight": 800,
                    "tracking": -0.035, "leading": 1.0, "case": "none", "scale": 1.0},
        "text": {"family": "DM Sans", "weights": [500, 700], "weight": 500},
        "accent_style": "marker",
        "mood": "warm, characterful grotesque with a highlighter accent",
    },
    "luxury-minimal": {
        "display": {"family": "Cormorant Garamond", "weights": [500, 600], "italic": True, "weight": 500,
                    "tracking": -0.01, "leading": 1.0, "case": "none", "scale": 1.2},
        "text": {"family": "Jost", "weights": [400, 500], "weight": 400, "tracking": 0.18, "case": "uppercase"},
        "accent_style": "italic",
        "mood": "high-contrast serif, spaced small caps, a lot of air",
    },
    "dynamic-sport": {
        "display": {"family": "Anton", "weights": [400], "weight": 400,
                    "tracking": 0.0, "leading": 0.92, "case": "uppercase", "scale": 1.12, "skew": -8},
        "text": {"family": "Barlow", "weights": [500, 700], "weight": 600},
        "accent_style": "color",
        "mood": "condensed, slanted, loud; cinematic sport-ad energy",
    },
    "playful-illustration": {
        "display": {"family": "Fredoka", "weights": [600, 700], "weight": 700,
                    "tracking": -0.01, "leading": 1.02, "case": "none", "scale": 1.0},
        "text": {"family": "Nunito", "weights": [600, 700], "weight": 600},
        "accent_style": "color",
        "mood": "rounded, friendly, pairs with flat illustration",
    },
}

# Faces that cover a script the preset faces may not. Listed after the preset face in the CSS stack, so the
# browser uses them glyph by glyph only where the preset face has no glyph.
SCRIPT_FALLBACK = {
    "hebrew": {"serif": "Frank Ruhl Libre", "sans": "Heebo"},
    "arabic": {"serif": "Noto Naskh Arabic", "sans": "Cairo"},
    "cyrillic": {"serif": "Playfair Display", "sans": "Manrope"},
    "greek": {"serif": "Noto Serif", "sans": "Noto Sans"},
    "thai": {"serif": "Noto Serif Thai", "sans": "Noto Sans Thai"},
    "devanagari": {"serif": "Noto Serif Devanagari", "sans": "Noto Sans Devanagari"},
    "japanese": {"serif": "Noto Serif JP", "sans": "Noto Sans JP"},
    "korean": {"serif": "Noto Serif KR", "sans": "Noto Sans KR"},
    "chinese-simplified": {"serif": "Noto Serif SC", "sans": "Noto Sans SC"},
    "chinese-traditional": {"serif": "Noto Serif TC", "sans": "Noto Sans TC"},
}
SERIF_FACES = {"Instrument Serif", "Cormorant Garamond", "Playfair Display", "Frank Ruhl Libre", "Fraunces"}

RTL_LANGS = {"he", "iw", "ar", "fa", "ur"}


def lang(locale: str) -> str:
    return re.split(r"[-_]", locale)[0].lower()


def is_rtl(locale: str) -> bool:
    return lang(locale) in RTL_LANGS


def scripts_in(text: str, locale: str = "") -> set[str]:
    out = set()
    for ch in text:
        o = ord(ch)
        if 0x0590 <= o <= 0x05FF:
            out.add("hebrew")
        elif 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F:
            out.add("arabic")
        elif 0x0400 <= o <= 0x04FF:
            out.add("cyrillic")
        elif 0x0370 <= o <= 0x03FF:
            out.add("greek")
        elif 0x0E00 <= o <= 0x0E7F:
            out.add("thai")
        elif 0x0900 <= o <= 0x097F:
            out.add("devanagari")
        elif 0xAC00 <= o <= 0xD7AF:
            out.add("korean")
        elif 0x3040 <= o <= 0x30FF:
            out.add("japanese")
        elif 0x4E00 <= o <= 0x9FFF:
            l = locale.lower()
            out.add("japanese" if l.startswith("ja") else
                    "chinese-traditional" if ("hant" in l or l.endswith(("tw", "hk"))) else "chinese-simplified")
    return out


def stack(face: str, scripts: set[str], generic: str = "sans-serif") -> list[str]:
    kind = "serif" if face in SERIF_FACES else "sans"
    fams = [face]
    for s in sorted(scripts):
        fb = SCRIPT_FALLBACK.get(s, {}).get(kind)
        if fb and fb not in fams:
            fams.append(fb)
    return fams


def css_stack(fams: list[str], generic: str) -> str:
    return ", ".join([f"'{f}'" for f in fams] + [generic])


def _css_url(family: str, weights, italic: bool) -> str:
    ws = sorted(set(int(w) for w in weights)) or [400]
    if italic:
        axis = "ital,wght@" + ";".join([f"0,{w}" for w in ws] + [f"1,{w}" for w in ws])
    else:
        axis = "wght@" + ";".join(str(w) for w in ws)
    return ("https://fonts.googleapis.com/css2?family=" + urllib.parse.quote_plus(family) + ":" + axis
            + "&display=block")


def _fetch(url: str, timeout=20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed https hosts)
        return r.read()


def ensure_family(family: str, weights=(400,), italic=False, offline=False) -> tuple[str | None, str]:
    """Return (css with file:// sources, status). status: cached | downloaded | missing (reason)."""
    url = _css_url(family, weights, italic)
    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    d = CACHE / re.sub(r"[^A-Za-z0-9]+", "-", family) / key
    css_p = d / "font.css"
    if css_p.exists():
        return css_p.read_text(), "cached"
    if offline or os.environ.get("APP_STORE_KIT_OFFLINE"):
        return None, "missing (offline, not in cache)"
    try:
        css = _fetch(url).decode()
    except Exception as e:  # network, 400 for an unknown family
        return None, f"missing ({type(e).__name__}: {e})"
    d.mkdir(parents=True, exist_ok=True)

    def grab(m):
        src = m.group(1)
        if not src.startswith("https://fonts.gstatic.com/"):
            return m.group(0)
        f = d / (hashlib.sha256(src.encode()).hexdigest()[:16] + pathlib.Path(urllib.parse.urlparse(src).path).suffix)
        if not f.exists():
            f.write_bytes(_fetch(src))
        return f"url({f.as_uri()})"

    css = re.sub(r"url\((https://[^)]+)\)", grab, css)
    css_p.write_text(css)
    return css, "downloaded"


def subsets(css: str) -> set[str]:
    return set(re.findall(r"/\*\s*([a-z-]+)\s*\*/", css or ""))


def brand_face_css(files: list[dict], base: pathlib.Path) -> tuple[str, list[str]]:
    """@font-face rules for the owner's font files, referenced in place (never copied). Returns css, errors."""
    out, errs = [], []
    for f in files or []:
        p = (base / f["src"]).expanduser()
        if not p.exists():
            errs.append(f"brand font {f.get('family')}: {p} not found")
            continue
        out.append("@font-face{font-family:'%s';src:url(%s);font-weight:%s;font-style:%s;font-display:block}"
                   % (f["family"], p.resolve().as_uri(), f.get("weight", 400), f.get("style", "normal")))
    return "\n".join(out), errs


def resolve(type_cfg: dict, scripts: set[str], base: pathlib.Path, offline=False):
    """Pick the faces for a campaign and load them. Returns (info, css, notes)."""
    preset_name = type_cfg.get("preset", "modern-tech")
    if preset_name not in PRESETS:
        raise ValueError(f"unknown type preset {preset_name!r}; one of {', '.join(PRESETS)}")
    p = PRESETS[preset_name]
    disp = {**p["display"], **(type_cfg.get("display") or {})}
    text = {**p["text"], **(type_cfg.get("text") or {})}
    mono = {**(p.get("mono") or {"family": text["family"], "weights": [500]}), **(type_cfg.get("mono") or {})}
    css_parts, notes = [], []
    brand_css, errs = brand_face_css(type_cfg.get("files"), base)
    notes += [("error", e) for e in errs]
    brand_fams = {f["family"] for f in type_cfg.get("files") or []}
    loaded = {}
    wanted = [(disp["family"], disp.get("weights", [disp.get("weight", 400)]), disp.get("italic", False)),
              (text["family"], text.get("weights", [text.get("weight", 400)]), False),
              (mono["family"], mono.get("weights", [500]), False)]
    for s in sorted(scripts):
        for kind in ("serif", "sans"):
            fb = SCRIPT_FALLBACK.get(s, {}).get(kind)
            if fb:
                wanted.append((fb, [400, 700], False))
    seen = set()
    for fam, ws, it in wanted:
        if fam in seen or fam in brand_fams:
            continue
        seen.add(fam)
        css, status = ensure_family(fam, ws, it, offline)
        loaded[fam] = subsets(css) if css else None
        if css:
            css_parts.append(css)
        else:
            notes.append(("warn", f"font {fam}: {status}; the browser substitutes a system face"))
    info = {"preset": preset_name, "display": disp, "text": text, "mono": mono, "subsets": loaded,
            "accent_style": type_cfg.get("accent_style", p.get("accent_style", "color"))}
    return info, brand_css + "\n" + "\n".join(css_parts), notes
