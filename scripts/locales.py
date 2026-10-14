#!/usr/bin/env python3
"""The App Store's 50 metadata locales, and a kit's language coverage.

Usage:
  locales.py list                              table of the 50 App Store Connect locale codes
  locales.py check KIT [--project DIR]         per kit locale: valid code, metadata file, screenshots, app translated
  locales.py scaffold KIT LOCALE [LOCALE ...]  metadata.<locale>.yaml skeletons + add the locales to facts.yaml

Codes are the exact App Store Connect API codes (references/localization-and-updates.md §1), which are not always
BCP-47: ar-SA (not ar), de-DE (not de), no (not nb), the Indic codes carry -IN, Urdu is ur-PK.

KIT/facts.yaml `locales: [en-US, de-DE, ja]` lists the store languages, primary first. Without it the kit's
metadata.<locale>.yaml files are the list (the connect.yaml `locale:` first, else en-US, else alphabetical).

check reads the app's own translations from *.xcstrings (entries with a value for that language / translatable
entries) or, without String Catalogs, from <lang>.lproj folders under --project (default: the kit's parent folder).
A store language the app lacks is a warning: the product page would promise a language the app doesn't speak.
Exit 1 when a kit locale is not one of the 50 codes.

scaffold never overwrites a file. It copies the primary's keys with the text fields emptied; URLs, category,
copyright and IAP product ids are kept (they rarely change per language).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

import yaml

# (code, English name, native name, rtl, script note, app-side codes in .xcstrings/.lproj, best match first)
# Script note: "latin" 1 byte per plain letter (accents 2), "2-byte" Greek/Cyrillic/Hebrew/Arabic,
# "3-byte" CJK, Thai and Indic scripts. Keywords are 100 BYTES, so a 3-byte script fits about 33 characters.
_TABLE = [
    ("ar-SA", "Arabic", "العربية", True, "2-byte", ["ar"]),
    ("bn-BD", "Bengali (Bangla)", "বাংলা", False, "3-byte", ["bn", "bn-BD"]),
    ("ca", "Catalan", "Català", False, "latin", ["ca"]),
    ("zh-Hans", "Chinese (Simplified)", "简体中文", False, "3-byte cjk", ["zh-Hans", "zh-CN", "zh"]),
    ("zh-Hant", "Chinese (Traditional)", "繁體中文", False, "3-byte cjk", ["zh-Hant", "zh-TW", "zh-HK"]),
    ("hr", "Croatian", "Hrvatski", False, "latin", ["hr"]),
    ("cs", "Czech", "Čeština", False, "latin", ["cs"]),
    ("da", "Danish", "Dansk", False, "latin", ["da"]),
    ("nl-NL", "Dutch", "Nederlands", False, "latin", ["nl", "nl-NL"]),
    ("en-AU", "English (Australia)", "English (Australia)", False, "latin", ["en-AU", "en-GB", "en"]),
    ("en-CA", "English (Canada)", "English (Canada)", False, "latin", ["en-CA", "en"]),
    ("en-GB", "English (U.K.)", "English (U.K.)", False, "latin", ["en-GB", "en"]),
    ("en-US", "English (U.S.)", "English (U.S.)", False, "latin", ["en", "en-US"]),
    ("fi", "Finnish", "Suomi", False, "latin", ["fi"]),
    ("fr-FR", "French", "Français", False, "latin", ["fr", "fr-FR"]),
    ("fr-CA", "French (Canada)", "Français (Canada)", False, "latin", ["fr-CA", "fr"]),
    ("de-DE", "German", "Deutsch", False, "latin", ["de", "de-DE"]),
    ("el", "Greek", "Ελληνικά", False, "2-byte", ["el"]),
    ("gu-IN", "Gujarati", "ગુજરાતી", False, "3-byte", ["gu", "gu-IN"]),
    ("he", "Hebrew", "עברית", True, "2-byte", ["he", "iw"]),
    ("hi", "Hindi", "हिन्दी", False, "3-byte", ["hi"]),
    ("hu", "Hungarian", "Magyar", False, "latin", ["hu"]),
    ("id", "Indonesian", "Bahasa Indonesia", False, "latin", ["id", "in"]),
    ("it", "Italian", "Italiano", False, "latin", ["it"]),
    ("ja", "Japanese", "日本語", False, "3-byte cjk", ["ja"]),
    ("kn-IN", "Kannada", "ಕನ್ನಡ", False, "3-byte", ["kn", "kn-IN"]),
    ("ko", "Korean", "한국어", False, "3-byte cjk", ["ko"]),
    ("ms", "Malay", "Bahasa Melayu", False, "latin", ["ms"]),
    ("ml-IN", "Malayalam", "മലയാളം", False, "3-byte", ["ml", "ml-IN"]),
    ("mr-IN", "Marathi", "मराठी", False, "3-byte", ["mr", "mr-IN"]),
    ("no", "Norwegian", "Norsk", False, "latin", ["nb", "no", "nn"]),
    ("or-IN", "Oriya (Odia)", "ଓଡ଼ିଆ", False, "3-byte", ["or", "or-IN"]),
    ("pl", "Polish", "Polski", False, "latin", ["pl"]),
    ("pt-BR", "Portuguese (Brazil)", "Português (Brasil)", False, "latin", ["pt-BR", "pt"]),
    ("pt-PT", "Portuguese (Portugal)", "Português (Portugal)", False, "latin", ["pt-PT", "pt"]),
    ("pa-IN", "Punjabi", "ਪੰਜਾਬੀ", False, "3-byte", ["pa", "pa-IN"]),
    ("ro", "Romanian", "Română", False, "latin", ["ro"]),
    ("ru", "Russian", "Русский", False, "2-byte", ["ru"]),
    ("sk", "Slovak", "Slovenčina", False, "latin", ["sk"]),
    ("sl-SI", "Slovenian", "Slovenščina", False, "latin", ["sl", "sl-SI"]),
    ("es-MX", "Spanish (Mexico)", "Español (México)", False, "latin", ["es-MX", "es-419", "es"]),
    ("es-ES", "Spanish (Spain)", "Español (España)", False, "latin", ["es", "es-ES"]),
    ("sv", "Swedish", "Svenska", False, "latin", ["sv"]),
    ("ta-IN", "Tamil", "தமிழ்", False, "3-byte", ["ta", "ta-IN"]),
    ("te-IN", "Telugu", "తెలుగు", False, "3-byte", ["te", "te-IN"]),
    ("th", "Thai", "ไทย", False, "3-byte", ["th"]),
    ("tr", "Turkish", "Türkçe", False, "latin", ["tr"]),
    ("uk", "Ukrainian", "Українська", False, "2-byte", ["uk"]),
    ("ur-PK", "Urdu", "اردو", True, "2-byte", ["ur", "ur-PK"]),
    ("vi", "Vietnamese", "Tiếng Việt", False, "latin", ["vi"]),
]
LOCALES = {c: {"code": c, "name": n, "native": nat, "rtl": rtl, "script": s, "app_codes": app}
           for c, n, nat, rtl, s, app in _TABLE}
assert len(LOCALES) == 50

# Common mistakes → the right App Store Connect code (used for hints only, never applied silently).
HINTS = {"ar": "ar-SA", "de": "de-DE", "nb": "no", "nn": "no", "nl": "nl-NL", "fr": "fr-FR", "es": "es-ES",
         "pt": "pt-BR or pt-PT", "en": "en-US", "zh": "zh-Hans", "zh-CN": "zh-Hans", "zh-TW": "zh-Hant",
         "iw": "he", "in": "id", "bn": "bn-BD", "ur": "ur-PK", "sl": "sl-SI", "kn": "kn-IN", "ml": "ml-IN",
         "mr": "mr-IN", "or": "or-IN", "pa": "pa-IN", "ta": "ta-IN", "te": "te-IN", "gu": "gu-IN",
         "ja-JP": "ja", "ko-KR": "ko", "it-IT": "it", "sv-SE": "sv", "ru-RU": "ru"}

# Fields Claude writes per language; everything else is copied from the primary by scaffold.
KEEP_FIELDS = {"support_url", "marketing_url", "privacy_policy_url", "category", "copyright", "product_id"}
SKIP_DIRS = {"DerivedData", "build", ".build", "Pods", "Carthage", "node_modules", ".git"}


def is_valid(code: str) -> bool:
    return code in LOCALES


def hint(code: str) -> str:
    h = HINTS.get(code)
    return f" (did you mean {h}?)" if h else ""


# ---- kit --------------------------------------------------------------------------------------------

def load_yaml(p: pathlib.Path):
    return (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}


def metadata_locales(kit: pathlib.Path) -> list[str]:
    return sorted(p.name[len("metadata."):-len(".yaml")] for p in kit.glob("metadata.*.yaml"))


def kit_locales(kit: pathlib.Path) -> list[str]:
    """facts.yaml locales (primary first); else the metadata files with the primary moved to the front."""
    facts = load_yaml(kit / "facts.yaml")
    locs = facts.get("locales") if isinstance(facts, dict) else None
    if locs:
        return [str(x) for x in (locs if isinstance(locs, list) else [locs])]
    found = metadata_locales(kit)
    primary = str(load_yaml(kit / "connect.yaml").get("locale") or "") or ("en-US" if "en-US" in found else "")
    if primary in found:
        found.remove(primary)
        found.insert(0, primary)
    return found


# ---- the app's own languages ------------------------------------------------------------------------

def _walk(root: pathlib.Path, pattern: str):
    for p in root.rglob(pattern):
        if not SKIP_DIRS.intersection(p.relative_to(root).parts[:-1]):
            yield p


def _has_value(loc: dict) -> bool:
    if not isinstance(loc, dict):
        return False
    unit = loc.get("stringUnit")
    if isinstance(unit, dict) and str(unit.get("value") or "").strip():
        return True
    return bool(loc.get("variations") or loc.get("substitutions"))


def app_coverage(project: pathlib.Path) -> dict:
    """{'source': lang, 'total': n, 'langs': {lang: translated}, 'lproj': set, 'catalogs': [paths]}."""
    out = {"source": None, "total": 0, "langs": {}, "lproj": set(), "catalogs": []}
    if not project or not project.is_dir():
        return out
    for cat in _walk(project, "*.xcstrings"):
        try:
            data = json.loads(cat.read_text())
        except (OSError, ValueError):
            continue
        out["catalogs"].append(cat)
        src = data.get("sourceLanguage", "en")
        out["source"] = out["source"] or src
        for key, entry in (data.get("strings") or {}).items():
            entry = entry or {}
            if entry.get("shouldTranslate") is False or not str(key).strip():
                continue
            out["total"] += 1
            locs = entry.get("localizations") or {}
            langs = {lang for lang, loc in locs.items() if _has_value(loc)} | {src}
            for lang in langs:
                out["langs"][lang] = out["langs"].get(lang, 0) + 1
    for d in _walk(project, "*.lproj"):
        if d.is_dir() and d.stem != "Base":
            out["lproj"].add(d.stem)
    return out


def app_status(code: str, cov: dict) -> tuple[bool | None, str]:
    """(supported?, text). None when the project has no language data at all."""
    candidates = LOCALES[code]["app_codes"] if code in LOCALES else [code]
    if cov["total"]:
        best = max(((cov["langs"].get(c, 0), c) for c in candidates), default=(0, ""))
        n, lang = best
        if n == 0:
            return False, f"no ({'/'.join(candidates)} 0/{cov['total']})"
        pct = 100 * n // cov["total"]
        return True, f"{lang} {n}/{cov['total']} ({pct}%)" + (" partial" if pct < 90 else "")
    if cov["lproj"]:
        hit = next((c for c in candidates if c in cov["lproj"]), None)
        return (True, f"{hit}.lproj") if hit else (False, "no .lproj")
    return None, "unknown (no .xcstrings or .lproj found)"


# ---- commands ---------------------------------------------------------------------------------------

def cmd_list(_a) -> int:
    print(f"{'code':8} {'language':24} {'native':22} {'rtl':4} {'script':11} app codes")
    for loc in LOCALES.values():
        print(f"{loc['code']:8} {loc['name']:24} {loc['native']:22} {'yes' if loc['rtl'] else '':4} "
              f"{loc['script']:11} {', '.join(loc['app_codes'])}")
    print("\nKeywords are 100 bytes: 2-byte scripts fit ~50 characters, 3-byte (CJK, Thai, Indic) ~33.")
    return 0


def cmd_check(a) -> int:
    kit = pathlib.Path(a.kit)
    project = pathlib.Path(a.project) if a.project else kit.resolve().parent
    locs = kit_locales(kit)
    if not locs:
        print("no locales: add `locales: [en-US, ...]` to facts.yaml or write metadata.<locale>.yaml", file=sys.stderr)
        return 2
    cov = app_coverage(project)
    rows, invalid, warns = [], [], []
    for i, code in enumerate(locs):
        valid = is_valid(code)
        if not valid:
            invalid.append(code)
        meta = (kit / f"metadata.{code}.yaml").exists()
        shots_dir = kit / "screenshots" / code
        shots = shots_dir.is_dir() and any(p.suffix.lower() in (".png", ".jpg", ".jpeg")
                                           for p in shots_dir.rglob("*"))
        shot_txt = "own" if shots else ("MISSING (primary)" if i == 0 else "uses primary screenshots")
        ok, app_txt = app_status(code, cov)
        if ok is False:
            warns.append(f"{code}: the app itself is not translated; the product page would promise a language "
                         "the app lacks (translate the app, or drop the locale)")
        if valid and LOCALES[code]["rtl"] and shots:
            warns.append(f"{code}: right-to-left; check the screenshots show the mirrored UI and right-aligned captions")
        rows.append((code + (" *" if i == 0 else ""), "yes" if valid else "NO" + hint(code),
                     "yes" if meta else "MISSING", shot_txt, app_txt))
    head = ("locale", "valid", "metadata", "screenshots", "app translated")
    widths = [max(len(str(r[k])) for r in rows + [head]) for k in range(len(head))]
    for r in [head] + rows:
        print("  ".join(str(v).ljust(w) for v, w in zip(r, widths)).rstrip())
    print("\n* primary locale")
    if cov["catalogs"]:
        print(f"app languages from {len(cov['catalogs'])} String Catalog(s), {cov['total']} translatable entries")
    for w in warns:
        print(f"warn: {w}")
    for code in invalid:
        print(f"error: '{code}' is not an App Store Connect locale code{hint(code)}; see `locales.py list`")
    return 1 if invalid else 0


def _blank(value, key=None):
    if key in KEEP_FIELDS:
        return value
    if isinstance(value, dict):
        return {k: _blank(v, k) for k, v in value.items()}
    if isinstance(value, list):
        if all(not isinstance(v, (dict, list)) for v in value):
            return []
        return [_blank(v) for v in value]
    if isinstance(value, str):
        return ""
    return value


HEADER = """\
# {name} ({code}) product page. Skeleton from locales.py scaffold on the primary ({primary}).
# Claude ADAPTS each field for {name}-speaking customers (not a literal translation), following
# references/copy.md: name 30, subtitle 30, promotional_text 170, description 4000, whats_new 4000 characters.
# keywords: researched for this language and market (what people here type), 100 BYTES ({script}),
# comma-separated with no spaces, no words already in the name or subtitle.
# URLs, category, copyright and IAP product ids are copied from the primary.{rtl}
# Lint: python3 ~/.claude/skills/app-store-kit/scripts/lint_metadata.py KIT
"""


def add_to_facts(facts_path: pathlib.Path, new: list[str], primary: str) -> list[str]:
    """Add locales to facts.yaml `locales:` editing the text minimally (comments survive). Returns added codes."""
    text = facts_path.read_text() if facts_path.exists() else ""
    lines = text.splitlines(keepends=True)
    idx = next((i for i, ln in enumerate(lines) if re.match(r"^locales\s*:", ln)), None)
    if idx is None:
        codes = list(dict.fromkeys(c for c in [primary] + new if c))
        if text and not text.endswith("\n"):
            text += "\n"
        text += f"\nlocales: [{', '.join(codes)}]   # store languages, primary first (locales.py)\n"
        facts_path.write_text(text)
        return [c for c in codes if c != primary]
    m = re.match(r"^locales\s*:\s*\[(?P<items>[^\]]*)\](?P<rest>.*)$", lines[idx].rstrip("\n"))
    if m:  # flow list on one line
        current = [x.strip().strip("'\"") for x in m.group("items").split(",") if x.strip()]
        added = [c for c in dict.fromkeys(new) if c not in current]
        if added:
            lines[idx] = f"locales: [{', '.join(current + added)}]{m.group('rest')}\n"
    else:  # block list (or empty value) on the following lines
        j, current, indent = idx + 1, [], "  "
        last_item = idx
        while j < len(lines):
            ln = lines[j]
            im = re.match(r"^(\s*)-\s*['\"]?([^'\"#\s]+)", ln)
            if im:
                current.append(im.group(2))
                indent, last_item = im.group(1), j
            elif ln.strip() and not ln.lstrip().startswith("#"):
                break
            j += 1
        added = [c for c in dict.fromkeys(new) if c not in current]
        lines[last_item + 1:last_item + 1] = [f"{indent}- {c}\n" for c in added]
    facts_path.write_text("".join(lines))
    return added


def cmd_scaffold(a) -> int:
    kit = pathlib.Path(a.kit)
    bad = [c for c in a.locales if not is_valid(c)]
    if bad:
        for c in bad:
            print(f"error: '{c}' is not an App Store Connect locale code{hint(c)}", file=sys.stderr)
        return 1
    locs = kit_locales(kit)
    primary = locs[0] if locs else None
    src = kit / f"metadata.{primary}.yaml" if primary else None
    if not src or not src.exists():
        print("error: no primary metadata.<locale>.yaml to copy the structure from", file=sys.stderr)
        return 2
    base = yaml.safe_load(src.read_text()) or {}
    for code in a.locales:
        dest = kit / f"metadata.{code}.yaml"
        if dest.exists():
            print(f"kept    {dest.name} (exists, not overwritten)")
            continue
        loc = LOCALES[code]
        rtl = "\n# Right-to-left language: screenshots need the mirrored UI and right-aligned captions." \
            if loc["rtl"] else ""
        body = yaml.safe_dump(_blank(base), allow_unicode=True, sort_keys=False, width=110)
        dest.write_text(HEADER.format(name=loc["name"], code=code, primary=primary, script=loc["script"], rtl=rtl)
                        + "\n" + body)
        print(f"created {dest.name}")
    added = add_to_facts(kit / "facts.yaml", [c for c in a.locales if c != primary], primary)
    if added:
        print(f"facts.yaml locales += {', '.join(added)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    c = sub.add_parser("check")
    c.add_argument("kit")
    c.add_argument("--project", help="app source folder to scan for .xcstrings/.lproj (default: KIT/..)")
    s = sub.add_parser("scaffold")
    s.add_argument("kit")
    s.add_argument("locales", nargs="+")
    a = ap.parse_args(argv)
    return {"list": cmd_list, "check": cmd_check, "scaffold": cmd_scaffold}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
