#!/usr/bin/env python3
"""Lint App Store product-page metadata (kit/metadata.<locale>.yaml) against Apple's limits and rules.

Usage:
  lint_metadata.py KIT_DIR                     lints every KIT_DIR/metadata.*.yaml with KIT_DIR/facts.yaml
  lint_metadata.py FILE.yaml [...] [--facts F] [--rules R] [--strict]

metadata.<locale>.yaml keys: name, subtitle, promotional_text, description, keywords (string "a,b,c"
or list), whats_new, support_url, marketing_url, privacy_policy_url, category {primary, secondary},
copyright, review_notes, review_notes_file, iap [{product_id, display_name, description}].

facts.yaml keys used here (all optional): company, first_version (bool), has_iap (bool),
has_ads (bool), kids_category (bool), claims [phrases the app can back up], competitors [names].
Review checks also read app.version/version, has_subscription, monetization.iap[].type.
Optional review facts: has_login/sign_in_required (bool), review.hardware (required hardware,
bool or description), review.external_services (list or bool), third_party_ai,
payment_services, auth_services (list or bool). These declarations only enable warnings;
completeness is judged heuristically from the resolved notes, never from private.yaml.
The CLI resolves notes beside each metadata file with connect_guide.review_notes_text;
callers of lint() can pass kit=KIT_DIR for the same file resolution.

Errors are Apple limits or App Review rules; warnings are ASO hygiene or things a human must judge.
Exit 1 on any error (or any warning with --strict).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

import yaml

from connect_guide import review_notes_text

HERE = pathlib.Path(__file__).resolve().parent

CATEGORIES = {c.lower() for c in [
    "Books", "Business", "Developer Tools", "Education", "Entertainment", "Finance", "Food & Drink",
    "Games", "Graphics & Design", "Health & Fitness", "Kids", "Lifestyle", "Magazines & Newspapers",
    "Medical", "Music", "Navigation", "News", "Photo & Video", "Productivity", "Reference", "Shopping",
    "Social Networking", "Sports", "Stickers", "Travel", "Utilities", "Weather"]}
APPLE_MARKS = ["apple", "iphone", "ipad", "ipod", "macbook", "macos", "ipados", "siri", "icloud",
               "app store", "apple watch", "apple tv", "facetime", "imessage", "airdrop", "airpods", "vision pro"]
OTHER_PLATFORMS = re.compile(r"\b(android|google play|play store|galaxy store|windows phone|huawei appgallery|"
                             r"appgallery|amazon appstore|f-droid)\b", re.I)
MISTYPED_MARKS = [
    (re.compile(r"\bAppStore\b|\bApp store\b|\bapp Store\b|\bAPP STORE\b"), "write 'App Store' (capital A and S, two words)"),
    (re.compile(r"\b(Apple|iTunes|iPhone|iPad) App Store\b"), "say 'the App Store', no other descriptors"),
    (re.compile(r"\b(?!iPhone\b)[iI][pP][hH][oO][nN][eE]\b"), "write 'iPhone'"),
    (re.compile(r"\b(?!iPad\b)[iI][pP][aA][dD]\b"), "write 'iPad'"),
    (re.compile(r"\bIOS\b|\bIos\b"), "Apple's marketing guidelines say avoid naming iOS in marketing copy"),
    (re.compile(r"\b(iPhones|iPads)\b"), "Apple product names are always singular"),
]
PRICE = re.compile(r"([$€£¥₹₩]\s?\d)|(\d+(?:[.,]\d{1,2})?\s?(?:USD|EUR|GBP|JPY|dollars?|euros?|pounds?)\b)"
                   r"|(\b(?:USD|EUR|GBP)\s?\d)", re.I)
PLACEHOLDER = re.compile(r"\b(lorem|ipsum|todo|tbd|fixme|placeholder|xxx+|coming soon)\b|\[[A-Z _]+\]", re.I)
CLAIM = re.compile(r"\b(best|#1|no\.? ?1|number one|fastest|first|only|leading|most popular|award[- ]winning|"
                   r"guaranteed|world'?s|\d+\s?%|\d+x faster|millions?|\d[\d,.]*\+?\s?(?:users|downloads|reviews))\b", re.I)
KIDS = re.compile(r"\bfor (kids|children)\b", re.I)
HTML = re.compile(r"</?[a-z][^>]*>", re.I)
TEXT_FIELDS = ["name", "subtitle", "promotional_text", "description", "whats_new"]


class Findings:
    def __init__(self, scope):
        self.scope, self.errors, self.warnings = scope, [], []

    def e(self, msg):
        self.errors.append(msg)

    def w(self, msg):
        self.warnings.append(msg)


def measure(value: str, unit: str) -> int:
    return len(value.encode("utf-8")) if unit == "bytes" else len(value)


def keyword_terms(raw):
    if isinstance(raw, list):
        return [str(t) for t in raw], ",".join(str(t) for t in raw)
    raw = str(raw or "")
    return raw.split(","), raw


def words(text):
    return {w for w in re.findall(r"[\w']+", (text or "").lower()) if len(w) > 1}


REVIEW_HELP = "https://developer.apple.com/help/app-review/before-submitting-for-review/complete-review"


def lint_review_notes(notes, meta, facts, f):
    def has(pattern):
        return re.search(pattern, notes, re.I) is not None

    def warn(message):
        f.w(f"MD-14: review notes {message} (2.1 / Before You Submit; {REVIEW_HELP})")

    n = measure(notes, "bytes")
    if n > 4000:
        f.e(f"MD-14: review_notes is {n} bytes, limit 4000 (2.1; {REVIEW_HELP})")
    if not has(r"\b(?:iPhone|iPad|MacBook|Apple Watch|Vision Pro)\b|\b(?:iOS|iPadOS|macOS|watchOS|tvOS|visionOS)\s+\d+"):
        warn("may be missing devices and OS versions tested")
    if not has(r"\b(?:regions?|regional|countries|country|storefronts?)\b"):
        warn("may be missing a statement on regional differences")
    version = meta.get("version") or (facts.get("app") or {}).get("version") or facts.get("version")
    parts = re.findall(r"\d+", str(version or ""))
    update = facts.get("first_version") is False or meta.get("first_version") is False or bool(meta.get("whats_new"))
    update = update or bool(parts and tuple(map(int, (parts + ["0", "0"])[:3])) > (1, 0, 0))
    if update and not has(r"\b(?:new|added|changed|updated|improved|fixed|removed|changes|what.s new)\b"):
        warn("may be missing what changed in this update")
    elif update and has(r"\b(?:new|added|introduc\w*)\b") and not has(
            r"\b(?:tap|open|navigate|select|visit|go to|find|screen|tab|menu|settings)\b"):
        warn("may be missing where to find what changed (new features need a path)")
    products = (facts.get("monetization") or {}).get("iap") or []
    subscriptions = facts.get("has_subscription") or any(
        re.sub(r"[^a-z]", "", str(p.get("type", "")).lower()) in
        ("autorenewable", "autorenewablesubscription", "subscription") for p in products)
    if subscriptions and not (has(r"\bexpired\b") and has(r"\bsubscription\b")
                              and has(r"\b(?:demo|test)\s+account\b")):
        warn("may be missing an expired-subscription demo account")
    if (facts.get("has_login") or facts.get("sign_in_required")) and not has(
            r"\b(?:demo\s+(?:account|mode)|credentials?|username|password)\b"):
        warn("may be missing demo account credentials or demo mode instructions")
    review = facts.get("review") or {}
    if review.get("hardware") and not has(r"\bvideo\b"):
        warn("may be missing a video of required hardware")
    if (review.get("external_services") or facts.get("third_party_ai") or facts.get("payment_services")
            or facts.get("auth_services")) and not has(
            r"\b(?:external|third[- ]party)\s+(?:services?|platforms?|tools?|AI|authentication|payments?)\b|"
            r"\b(?:AI|authentication|auth|payment)\s+(?:services?|providers?|processors?)\b"):
        warn("may be missing external services used for core functionality")


def lint(meta: dict, facts: dict, rules: dict, scope="metadata", kit=None, seen_notes=None) -> Findings:
    f = Findings(scope)
    lim = rules["text_limits"]
    facts = facts or {}

    notes = review_notes_text(pathlib.Path(kit), meta) if kit is not None else str(meta.get("review_notes") or "").strip()
    # Review notes are one text per app: lint them once per distinct text (seen_notes).
    if seen_notes is None or notes not in seen_notes:
        if notes:
            lint_review_notes(notes, meta, facts, f)
        else:
            f.w(f"MD-14: no review notes: say what the app does, devices tested, regional differences and how "
                f"to reach every feature (2.1 / Before You Submit; {REVIEW_HELP})")
        if seen_notes is not None:
            seen_notes.add(notes)

    # ---- limits -------------------------------------------------------------------------------
    for key in ["name", "subtitle", "promotional_text", "description", "whats_new"]:
        val = meta.get(key)
        rule = lim.get(key)
        if rule is None:
            continue
        if val is None or str(val).strip() == "":
            if key in ("name", "description"):
                f.e(f"{key} is required")
            elif key == "whats_new" and facts.get("first_version") is False:
                f.e("whats_new is required for every version after the first (2.3.12)")
            continue
        val = str(val)
        n = measure(val, rule["unit"])
        if n > rule["max"]:
            f.e(f"{key} is {n} {rule['unit']}, limit {rule['max']} (over by {n - rule['max']})")
        if rule.get("min") and n < rule["min"]:
            f.e(f"{key} is {n} {rule['unit']}, minimum {rule['min']}")
    if meta.get("whats_new") and facts.get("first_version"):
        f.w("whats_new is not shown for a first version; App Store Connect ignores it")

    # ---- keywords -----------------------------------------------------------------------------
    terms, raw = keyword_terms(meta.get("keywords"))
    if not raw.strip():
        f.e("keywords are required")
    else:
        n = measure(raw, "bytes")
        if n > lim["keywords"]["max"]:
            f.e(f"keywords are {n} bytes, limit {lim['keywords']['max']} (over by {n - lim['keywords']['max']})")
        if re.search(r",\s", raw) or re.search(r"\s,", raw):
            f.w("spaces around commas in keywords waste bytes; separate terms with ',' only")
        clean = [t.strip().lower() for t in terms]
        if "" in clean:
            f.w("empty keyword term (doubled or trailing comma)")
        clean = [t for t in clean if t]
        minc = lim["keywords"].get("min_term_chars", 3)
        for t in clean:
            if len(t) < minc:
                f.e(f"keyword '{t}' is shorter than {minc} characters (App Store Connect rejects it)")
        seen = set()
        for t in clean:
            if t in seen:
                f.w(f"duplicate keyword '{t}'")
            seen.add(t)
        title_words = words(meta.get("name")) | words(meta.get("subtitle"))
        if facts.get("company"):
            title_words |= words(facts["company"])
        for t in clean:
            dup = [w for w in re.findall(r"[\w']+", t) if w in title_words]
            if dup:
                f.w(f"keyword '{t}' repeats {', '.join(dup)} from the name/subtitle/company; those are already indexed")
            if re.search(r"\bapps?\b", t):
                f.w(f"keyword '{t}': Apple says don't use the word 'app'")
            if t in CATEGORIES:
                f.w(f"keyword '{t}' is a category name; Apple says avoid it")
            if re.search(r"[#@]", t):
                f.w(f"keyword '{t}' has # or @")
            if t == "free" or re.search(r"\bfree\b", t):
                f.w(f"keyword '{t}': 'free' is pricing information (2.3.7)")
            for mark in APPLE_MARKS:
                if re.search(rf"\b{re.escape(mark)}\b", t):
                    f.e(f"keyword '{t}' contains the Apple trademark '{mark}' (2.3.7, 5.2.1)")
        for t in clean:
            for suf in ("s", "es"):
                if t.endswith(suf) and t[: -len(suf)] in seen:
                    f.w(f"keyword '{t}' is a plural of '{t[: -len(suf)]}'; Apple matches both, drop one")
                    break
        for comp in facts.get("competitors", []) or []:
            for t in clean:
                if comp.lower() in t:
                    f.e(f"keyword '{t}' names a competitor ({comp}) (2.3.7)")

    # ---- text content -------------------------------------------------------------------------
    texts = {k: str(meta.get(k) or "") for k in TEXT_FIELDS}
    texts["keywords"] = raw
    for k, txt in texts.items():
        if not txt:
            continue
        if PLACEHOLDER.search(txt):
            f.e(f"{k}: placeholder text '{PLACEHOLDER.search(txt).group(0)}' (2.1)")
        if PRICE.search(txt):
            f.e(f"{k}: price '{PRICE.search(txt).group(0).strip()}' in metadata (2.3.7; prices differ by storefront)")
        if OTHER_PLATFORMS.search(txt):
            f.e(f"{k}: names another platform or store '{OTHER_PLATFORMS.search(txt).group(0)}' (2.3.10)")
        for rx, why in MISTYPED_MARKS:
            m = rx.search(txt)
            if m:
                f.w(f"{k}: '{m.group(0)}': {why}")
        if KIDS.search(txt) and not facts.get("kids_category"):
            f.e(f"{k}: '{KIDS.search(txt).group(0)}' is reserved for the Kids Category (2.3.8)")
        for comp in facts.get("competitors", []) or []:
            if comp.lower() in txt.lower():
                f.e(f"{k}: names a competitor '{comp}' (2.3.7, 5.2.1)")
        if k != "keywords" and HTML.search(txt):
            f.e(f"{k}: HTML is not supported, plain text only")
    for k in ("name", "subtitle"):
        t = texts.get(k, "")
        for mark in ("app store", "apple"):
            if re.search(rf"\b{mark}\b", t, re.I):
                f.e(f"{k}: contains Apple trademark '{mark}' (5.2.1)")

    # free + IAP disclosure
    if facts.get("has_iap") or facts.get("has_subscription"):
        allt = " ".join(texts[k] for k in TEXT_FIELDS)
        if re.search(r"\bfree\b", allt, re.I) and not re.search(
                r"in-app purchase|subscription|upgrade|unlock|premium|\bpro\b|optional purchase", allt, re.I):
            f.w("text says 'free' but never mentions the in-app purchase; disclose what costs extra (2.3.2)")
    if facts.get("has_iap") and meta.get("description") and not re.search(
            r"in-app purchase|subscription|upgrade|unlock|premium|\bpro\b", str(meta["description"]), re.I):
        f.w("description does not mention the paid tier; 2.3.2 wants extra-cost items made clear")

    # claims not backed by facts
    backed = [c.lower() for c in facts.get("claims", []) or []]
    for k in ("subtitle", "promotional_text", "description"):
        for sent in re.split(r"(?<=[.!?\n])\s+", texts.get(k, "")):
            for m in CLAIM.finditer(sent):
                if not any(b in sent.lower() for b in backed):
                    f.w(f"{k}: claim '{m.group(0)}' in \"{sent.strip()[:80]}\" is not backed by facts.yaml claims")
                    break

    # description shape
    desc = texts["description"]
    if desc:
        first = re.split(r"(?<=[.!?])\s|\n", desc.strip(), maxsplit=1)[0]
        if len(first) > 170:
            f.w(f"description's first sentence is {len(first)} chars; it is what shows before 'more'")

    # ---- URLs, copyright, category ------------------------------------------------------------
    for k in ("support_url", "privacy_policy_url", "marketing_url"):
        u = meta.get(k)
        if not u:
            if k != "marketing_url":
                f.e(f"{k} is required")
            continue
        if not re.match(r"^https?://[^\s/]+\.[^\s]+$", str(u)):
            f.e(f"{k} '{u}' must be a full URL including the protocol")
        elif str(u).startswith("http://"):
            f.w(f"{k} uses http://; prefer https://")
    c = str(meta.get("copyright") or "")
    if not c:
        f.e("copyright is required (e.g. '2026 Example, Inc.')")
    else:
        if c.strip().startswith(("©", "(c)", "Copyright")):
            f.w("copyright: App Store Connect adds © itself; start with the year")
        if not re.match(r"^\s*(©\s*)?\d{4}\b", c):
            f.w("copyright should start with the year")
    cat = meta.get("category") or {}
    prim = cat.get("primary") if isinstance(cat, dict) else cat
    if not prim:
        f.e("category.primary is required")
    elif str(prim).lower() not in CATEGORIES:
        f.w(f"category '{prim}' is not in the known App Store category list")

    # ---- in-app purchases ----------------------------------------------------------------------
    for item in meta.get("iap", []) or []:
        pid = item.get("product_id", "?")
        for key, rk in (("display_name", "iap_display_name"), ("description", "iap_description")):
            val = str(item.get(key) or "")
            rule = lim[rk]
            if not val:
                f.e(f"iap {pid}: {key} is required")
                continue
            if len(val) > rule["max"]:
                f.e(f"iap {pid}: {key} is {len(val)} chars, limit {rule['max']}")
            if rule.get("min") and len(val) < rule["min"]:
                f.e(f"iap {pid}: {key} is {len(val)} chars, minimum {rule['min']}")
            if PRICE.search(val):
                f.e(f"iap {pid}: {key} contains a price")
    return f


def load_yaml(p):
    return yaml.safe_load(pathlib.Path(p).read_text()) or {}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--facts")
    ap.add_argument("--rules")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    files, facts_path, rules_path = [], a.facts, a.rules
    for p in map(pathlib.Path, a.paths):
        if p.is_dir():
            files += sorted(p.glob("metadata.*.yaml"))
            facts_path = facts_path or (p / "facts.yaml" if (p / "facts.yaml").exists() else None)
            rules_path = rules_path or (p / "rules.json" if (p / "rules.json").exists() else None)
        else:
            files.append(p)
    rules = json.loads(pathlib.Path(rules_path or HERE / "rules.json").read_text())
    facts = load_yaml(facts_path) if facts_path else {}
    if not files:
        print("no metadata.*.yaml files found", file=sys.stderr)
        return 2
    total_e = total_w = 0
    out = []
    seen_notes = set()
    for p in files:
        f = lint(load_yaml(p), facts, rules, p.name, kit=p.parent, seen_notes=seen_notes)
        total_e += len(f.errors); total_w += len(f.warnings)
        out.append({"file": str(p), "errors": f.errors, "warnings": f.warnings})
        if not a.json:
            print(("PASS " if not f.errors else "FAIL ") + str(p)
                  + "".join(f"\n    error: {e}" for e in f.errors) + "".join(f"\n    warn:  {w}" for w in f.warnings))
    if a.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"\n{total_e} error(s), {total_w} warning(s)" + ("" if facts_path else "  (no facts.yaml: claim checks see no backing)"))
    return 1 if total_e or (a.strict and total_w) else 0


if __name__ == "__main__":
    sys.exit(main())
