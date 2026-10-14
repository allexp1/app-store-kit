#!/usr/bin/env python3
"""Write the App Store Connect guide: every text and answer to type, field by field, in the order the forms ask.

Usage:
  connect_guide.py KIT [--locale en-US] [--rules RULES.json] [--no-private] [--check] [--init-progress]

Reads   KIT/facts.yaml, KIT/metadata.<locale>.yaml, KIT/review-notes.md, KIT/privacy-labels.md (or privacy.yaml),
        KIT/connect.yaml (answers that aren't product-page metadata), KIT/private.yaml (optional, personal data),
        KIT/screenshots/<locale>/<slot>/*.
Writes  KIT/CONNECT-GUIDE.md and KIT/connect-guide.html. These never contain private.yaml values: they show
        placeholders such as "your phone number", so they are safe to commit.
        KIT/connect-guide.private.html, only when private.yaml exists (and --no-private isn't given). It has the
        private values filled in. Gitignore it together with private.yaml.

Progress  KIT/connect-progress.yaml (optional) is the record of what is done in App Store Connect:
        steps:
          <step key>:                     # the key is in the guide (MD comment, HTML data-step)
            status: todo | done-by-owner | done-by-claude | skipped
            date: 2026-10-14
            live: {<field label>: <value seen on the live page>}
            note: <mismatch or anything worth keeping>
        Done steps are ticked in both outputs and say who did them. A step whose live values differ from what the
        kit says now is marked "needs update" with old → new. Ticks made in the HTML page itself stay in that
        browser; the YAML is the record. Values that match private.yaml are masked in the public outputs.
  --check          also list the steps that need update; exit 1 when any do.
  --init-progress  add every step missing from connect-progress.yaml as todo (creates the file); keeps entries.

Field names and limits follow references/app-store-connect-fields.md (Apple, read 2026-10-14; live-page
corrections in its "Live-page corrections" section).
Exit 1 when a text is over its limit or a required input is missing (and, with --check, when a step needs update).
"""
from __future__ import annotations

import argparse
import html
import json
import pathlib
import re
import subprocess
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
HAND = "✋"
STOP = "🛑"

# Limits not in rules.json (App Store Connect Help, In-App Purchase information).
EXTRA_LIMITS = {
    "iap_reference_name": {"max": 64, "unit": "chars"},
    "iap_product_id": {"max": 100, "unit": "chars"},
    "iap_review_notes": {"max": 4000, "unit": "chars"},
}

# Age-rating questionnaire, in Apple's section order (Help: Age ratings values and definitions; API:
# AgeRatingDeclaration). kind "yn" = Yes/No, "freq" = None/Infrequent/Frequent.
AGE_RATING = [
    ("In-app controls", [
        ("parentalControls", "Parental Controls", "yn"),
        ("ageAssurance", "Age Assurance", "yn")]),
    ("Capabilities", [
        ("unrestrictedWebAccess", "Unrestricted Web Access", "yn"),
        ("userGeneratedContent", "User-Generated Content", "yn"),
        ("socialMedia", "Social Media", "yn"),
        ("socialMediaAgeRestricted", "Social Media Disabled for Users Under 13", "yn"),
        ("messagingAndChat", "Messaging and Chat", "yn"),
        ("advertising", "Advertising", "yn")]),
    ("Mature themes", [
        ("profanityOrCrudeHumor", "Profanity or Crude Humor", "freq"),
        ("horrorOrFearThemes", "Horror/Fear Themes", "freq"),
        ("alcoholTobaccoOrDrugUseOrReferences", "Alcohol, Tobacco, or Drug Use or References", "freq")]),
    ("Medical or wellness", [
        ("medicalOrTreatmentInformation", "Medical or Treatment Information", "freq"),
        ("healthOrWellnessTopics", "Health or Wellness Topics", "yn")]),
    ("Sexuality or nudity", [
        ("matureOrSuggestiveThemes", "Mature or Suggestive Themes", "freq"),
        ("sexualContentOrNudity", "Sexual Content or Nudity", "freq"),
        ("sexualContentGraphicAndNudity", "Graphic Sexual Content and Nudity", "freq")]),
    ("Violence", [
        ("violenceCartoonOrFantasy", "Cartoon or Fantasy Violence", "freq"),
        ("violenceRealistic", "Realistic Violence", "freq"),
        ("violenceRealisticProlongedGraphicOrSadistic", "Prolonged Graphic or Sadistic Realistic Violence", "freq"),
        ("gunsOrOtherWeapons", "Guns or Other Weapons", "freq")]),
    ("Chance-based activities", [
        ("gamblingSimulated", "Simulated Gambling", "freq"),
        ("contests", "Contests", "freq"),
        ("gambling", "Gambling", "yn"),
        ("lootBox", "Loot Boxes", "yn")]),
]
ACCESSIBILITY = ["VoiceOver", "Voice Control", "Larger Text", "Dark Interface", "Differentiate Without Color Alone",
                 "Sufficient Contrast", "Reduced Motion", "Captions", "Audio Descriptions"]
RELEASE = {
    "manual": "Manually release this version",
    "automatic": "Automatically release this version",
    "scheduled": "Automatically release this version after App Review, no earlier than",
}
PROGRESS_FILE = "connect-progress.yaml"
STATUSES = ("todo", "done-by-owner", "done-by-claude", "skipped")
WHO = {"done-by-owner": "done by owner", "done-by-claude": "done by Claude", "skipped": "skipped"}
MASK = "[private]"
LANGUAGES = {"en-US": "English (U.S.)", "en-GB": "English (U.K.)", "de-DE": "German", "fr-FR": "French",
             "es-ES": "Spanish (Spain)", "es-MX": "Spanish (Mexico)", "it": "Italian", "ja": "Japanese",
             "ko": "Korean", "pt-BR": "Portuguese (Brazil)", "nl-NL": "Dutch", "he": "Hebrew", "ru": "Russian",
             "zh-Hans": "Chinese (Simplified)", "zh-Hant": "Chinese (Traditional)"}


# ---------------------------------------------------------------------------------------------------- model
class Field:
    """One thing to type or pick. kind: copy (type exactly this text), choose (pick this option), info."""

    def __init__(self, label, value, kind="copy", limit=None, judgement=False, why=None, private_key=None,
                 placeholder=None, note=None, live_ok=None):
        self.label, self.value, self.kind, self.limit = label, value, kind, limit
        self.judgement, self.why, self.note = judgement, why, note
        self.private_key, self.placeholder = private_key, placeholder
        self.live_ok = [norm(x) for x in (live_ok or [])]  # live readings that also count as matching

    def matches(self, live, private=None):
        """Does a value read on the live page still agree with what the kit says now?
        copy: exact text (whitespace-normalised). choose: equal, one starts with the other
        ("United States" / "United States (USD)"), or listed in live_ok. None = can't tell (private, no value)."""
        if self.private_key and not (private or {}).get(self.private_key):
            return None
        want, got = norm(self.text(private)), norm(live)
        if self.private_key and len(re.sub(r"\D", "", want)) >= 6:  # phone: separators don't matter
            return re.sub(r"\D", "", want) == re.sub(r"\D", "", got)
        if self.kind == "copy":
            return want == got
        if got in self.live_ok:
            return True
        want, got = loose(want), loose(got)
        return want == got or (bool(want) and bool(got) and (want.startswith(got) or got.startswith(want)))

    def text(self, private=None):
        if self.private_key:
            v = (private or {}).get(self.private_key)
            return str(v) if v else self.placeholder
        return "" if self.value is None else str(self.value)

    def count(self):
        if not self.limit or self.private_key:
            return None
        t = self.text()
        n = len(t.encode("utf-8")) if self.limit["unit"] == "bytes" else len(t)
        return n, self.limit["max"], self.limit["unit"], self.limit.get("min")

    def over(self):
        c = self.count()
        return bool(c and (c[0] > c[1] or (c[3] and c[0] < c[3])))


class Step:
    def __init__(self, title, fields=None, approval=False, note=None, where=None, key=None, guide_only=False,
                 after_launch=False):
        self.title, self.fields, self.approval, self.note, self.where = title, fields or [], approval, note, where
        self.after_launch = after_launch  # Apple allows it only once a version is live (growth: pages, tests)
        self.guide_only = guide_only  # agreements, tax, banking, ID: the owner does these; autopilot never does
        self.key = key  # stable progress key; build() fills it in as "<section key>/<slug of title>" when None
        self.status, self.date, self.live, self.progress_note, self.changes = "todo", None, {}, None, []


class Section:
    def __init__(self, title, where, steps, intro=None, key=None):
        self.title, self.where, self.steps, self.intro, self.key = title, where, steps, intro, key


def norm(v):
    return re.sub(r"\s+", " ", "" if v is None else str(v)).strip().casefold()


def loose(v):
    """For pick-from-a-menu answers: drop the trailing "selected" the live page adds."""
    return re.sub(r"\s+selected$", "", v).strip()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# ---------------------------------------------------------------------------------------------------- inputs
def load_yaml(p):
    p = pathlib.Path(p)
    return (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}


def answer(v):
    """connect.yaml answers are a scalar or {answer, why, judgement}. Returns (answer, why, judgement)."""
    if isinstance(v, dict):
        return v.get("answer"), v.get("why"), bool(v.get("judgement"))
    return v, None, False


def yes_no(v):
    if isinstance(v, bool):
        return "Yes" if v else "No"
    return str(v)


def review_notes_text(kit, meta):
    p = kit / (meta.get("review_notes_file") or "review-notes.md")
    if p.exists():
        lines = p.read_text().splitlines()
        marks = [i for i, ln in enumerate(lines) if ln.strip() == "---"]
        if len(marks) >= 2:
            return "\n".join(lines[marks[0] + 1:marks[1]]).strip()
        return p.read_text().strip()
    return str(meta.get("review_notes") or "").strip()


def _cell(s):
    return re.sub(r"\*\*|`", "", s).strip()


def privacy_rows(kit):
    """Rows from privacy.yaml (preferred) or the 'Data types' table in privacy-labels.md."""
    py = load_yaml(kit / "privacy.yaml")
    if py.get("data_types") or py.get("rows"):
        out = []
        for r in py.get("data_types") or py.get("rows"):
            out.append({"category": r.get("category", ""), "type": r.get("type") or r.get("data_type"),
                        "purposes": r.get("purposes", []), "linked": yes_no(r.get("linked")),
                        "tracking": yes_no(r.get("tracking")),
                        "linked_why": r.get("linked_why") or (r.get("why") if r.get("judgement") else None),
                        "tracking_why": r.get("tracking_why") or (r.get("why") if r.get("judgement") else None)})
        return py.get("collects", True), out
    p = kit / "privacy-labels.md"
    if not p.exists():
        return None, []
    rows, header = [], None
    for ln in p.read_text().splitlines():
        if not ln.startswith("|"):
            if header and rows:
                break
            header = None if not rows else header
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if header is None:
            low = [c.lower() for c in cells]
            if any("data type" in c for c in low) and any("purpose" in c for c in low):
                header = low
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        rec = dict(zip(header, cells))
        dt = _cell(rec.get(next(k for k in header if "data type" in k), ""))
        cat, _, typ = dt.partition("›")
        linked_raw = _cell(rec.get(next((k for k in header if "linked" in k), ""), ""))
        track_raw = _cell(rec.get(next((k for k in header if "tracking" in k), ""), ""))
        purposes = [x.strip() for x in _cell(rec.get(next(k for k in header if "purpose" in k), "")).split(",")]

        def first(raw):
            m = re.match(r"(yes|no)\b", raw, re.I)
            return m.group(1).capitalize() if m else raw

        def doubt(raw):
            if re.search(r"conflict|per the|unless|\?", raw, re.I):
                return f'privacy-labels.md says "{raw}". Read its conflicts section, then decide.'
            return None

        rows.append({"category": cat.strip(), "type": (typ or cat).strip(), "purposes": [x for x in purposes if x],
                     "linked": first(linked_raw), "tracking": first(track_raw),
                     "linked_why": doubt(linked_raw), "tracking_why": doubt(track_raw)})
    collects = True
    m = re.search(r"collect data from this app\?\"?\s*→\s*\*\*(yes|no)\*\*", p.read_text(), re.I)
    if m:
        collects = m.group(1).lower() == "yes"
    return collects, rows


def creative_files(kit, locale):
    """[(tab, file name)] for KIT/creative/<locale>/: universal fills both tabs, header/search override one."""
    root = kit / "creative" / locale
    if not root.is_dir():
        return []
    names = {f.stem.lower(): f.name for f in sorted(root.iterdir())
             if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".mp4", ".mov", ".m4v")}
    out = []
    for tab, own in (("Header", "header"), ("Search Results", "search")):
        name = names.get(own) or names.get("universal")
        if name:
            out.append((tab, name))
    return out


def screenshot_sets(kit, locale, rules):
    base = kit / "screenshots" / locale
    labels = {k: v.get("label", k) for k, v in (rules.get("screenshots", {}).get("slots") or {}).items()}
    out = []
    if base.is_dir():
        slots = [p for p in base.iterdir() if p.is_dir()]
        for slot in sorted(slots, key=lambda p: (not p.name.startswith("iphone"), p.name)):
            files = sorted(f.name for f in slot.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg"))
            if files:
                out.append((labels.get(slot.name, slot.name), slot.relative_to(kit).as_posix(), files))
    return out


# ---------------------------------------------------------------------------------------------------- build
def build(kit: pathlib.Path, locale: str | None, rules: dict, private=None):
    facts, conn = load_yaml(kit / "facts.yaml"), load_yaml(kit / "connect.yaml")
    problems = []
    metas = sorted(kit.glob("metadata.*.yaml"))
    locale = locale or conn.get("locale") or ("en-US" if (kit / "metadata.en-US.yaml").exists()
                                              else (metas[0].name.split(".")[1] if metas else None))
    meta = load_yaml(kit / f"metadata.{locale}.yaml")
    if not meta:
        problems.append(f"metadata.{locale}.yaml is missing")
    if not conn:
        problems.append("connect.yaml is missing: the guide falls back to '✋ decide' for every answer")
    app = facts.get("app", {})
    lim = dict(rules.get("text_limits", {}))
    lim.update(EXTRA_LIMITS)
    app_name = meta.get("name") or app.get("name") or "the app"

    def ask(label, key_path, default=None, why=None):
        """A field from connect.yaml; missing → a ✋ field asking the owner."""
        node = conn
        for k in key_path.split("."):
            node = node.get(k) if isinstance(node, dict) else None
        if node is None:
            if default is not None:
                return Field(label, default, "choose", why=why)
            return Field(label, "decide (not in connect.yaml)", "choose", judgement=True,
                         why=why or f"add `{key_path}` to connect.yaml")
        a, w, j = answer(node)
        return Field(label, yes_no(a), "choose", judgement=j, why=w or why)

    sections = []

    # 0. Business ------------------------------------------------------------------------------------------
    dsa_a, dsa_why, _ = answer(conn.get("dsa"))
    dsa_text = {True: "This is a trader account.", False: "This is not a trader account."}.get(dsa_a, dsa_a)
    sections.append(Section("Before you start: agreements, tax, banking, EU trader status",
                            "App Store Connect › Business", [
        Step("Accept the updated Apple Developer Program License Agreement", [
            Field("Apple Developer Program License Agreement Updated (banner on the Apps list)",
                  "Review and accept it (the Account Holder only)", "choose",
                  note="App Store Connect blocks submitting until the Account Holder accepts it.")],
             where="Apps list banner, or developer.apple.com › Account", guide_only=True),
        Step("Sign the latest agreements", [
            Field("Paid Apps Agreement", "Read and accept it (the Account Holder only)", "choose",
                  note="Needed for a price or an in-app purchase; without it the app can only be free.")],
             guide_only=True),
        Step("Tax and banking", [
            Field("Tax forms and bank account", "Fill in the forms Apple shows for your country", "choose",
                  judgement=True, why="Your own legal and tax details; nobody else can answer them.")],
             guide_only=True),
        Step("EU Digital Services Act: trader status", [
            Field("Digital Services Act › Complete Compliance Requirements",
                  dsa_text or "decide: trader or not a trader", "choose", judgement=True, why=dsa_why)],
             where="Business › Agreements › Compliance", guide_only=True),
    ], key="business"))

    # 1. New App ------------------------------------------------------------------------------------------
    plats = conn.get("platforms") or ["iOS"]
    lang = conn.get("primary_language") or LANGUAGES.get(locale, locale)
    ua = conn.get("user_access", "Full Access")
    sections.append(Section("Create the app record (New App)", "Apps › + (top left) › New App", [
        Step("Fill in the New App dialog", [
            Field("Platforms", ", ".join(plats), "choose"),
            Field("Name", meta.get("name"), limit=lim.get("name")),
            Field("Primary Language", lang, "choose"),
            Field("Bundle ID", app.get("bundle_id"), "choose", note="Pick it from the menu."),
            Field("SKU", conn.get("sku") or "decide a short internal code", "copy" if conn.get("sku") else "choose",
                  judgement=not conn.get("sku"), note="Never shown to customers and can't be changed later."),
            Field("User Access", ua, "choose"),
        ], note="Then press Create.")], key="new-app"))

    # 2. App Information ----------------------------------------------------------------------------------
    cat = meta.get("category") or facts.get("category") or {}
    cr = conn.get("content_rights")
    cr_a, cr_why, cr_j = answer(cr)
    cr_text = {"uses_third_party": "Yes, it contains, shows, or accesses third-party content, and I have the necessary rights",
               "none": "No, it does not contain, show, or access third-party content"}.get(cr_a, cr_a)
    info_steps = [
        Step("Name, subtitle and category", [
            Field("Name", meta.get("name"), limit=lim.get("name")),
            Field("Subtitle", meta.get("subtitle"), limit=lim.get("subtitle")),
            Field("Category › Primary", cat.get("primary"), "choose"),
            Field("Category › Secondary", cat.get("secondary") or "None", "choose"),
        ]),
        Step("Content Rights", [Field("Content Rights", cr_text or "decide", "choose",
                                      judgement=cr_j or cr_a is None, why=cr_why)]),
    ]
    ar = conn.get("age_rating", {})
    ar_fields = []
    for sec_name, items in AGE_RATING:
        for key, label, kind in items:
            if key in ar:
                a, w, j = answer(ar[key])
                ar_fields.append(Field(f"{sec_name} › {label}", yes_no(a), "choose", judgement=j, why=w))
            else:
                ar_fields.append(Field(f"{sec_name} › {label}", "decide", "choose", judgement=True,
                                       why=f"add age_rating.{key} to connect.yaml"))
    ov_a, ov_why, ov_j = answer(ar.get("override", "Not Applicable"))
    ar_fields.append(Field("Additional Information › Age Categories and Override", ov_a, "choose",
                           judgement=ov_j, why=ov_why))
    if ar.get("expected_rating"):
        ar_fields.append(Field("Calculated rating you should see", ar["expected_rating"], "info",
                               note="If App Store Connect shows something else, an answer above differs."))
    info_steps.append(Step("Age Rating (Set Up Age Ratings)", ar_fields,
                           note="Tick the in-app controls and capabilities that apply, then answer each section. "
                                "Apple works out the rating from these answers. The exact question wording on the "
                                "form may differ slightly; the item names match Apple's."))
    lic = conn.get("license_agreement", "Apple's standard license agreement (leave as is)")
    info_steps.append(Step("License Agreement", [Field("License Agreement", lic, "choose")]))
    if conn.get("dsa") is not None:
        info_steps.append(Step("App Store Regulations and Permits › Digital Services Act", [
            Field("Trader status for this app", dsa_text or "decide", "choose", judgement=True,
                  why="Same answer as in Business; shown again per app.")]))
    dg = conn.get("digital_goods")
    if dg:
        a, w, j = answer(dg)
        info_steps.append(Step("Digital Goods and Services (only if App Store Connect shows it)", [
            Field("Can customers consume digital goods and services in this app?", yes_no(a), "choose",
                  judgement=j, why=w)]))
    sections.append(Section("App Information", f"Apps › {app_name} › General › App Information", info_steps,
                            key="app-information"))

    # 3. Pricing and Availability -------------------------------------------------------------------------
    pr, av = conn.get("pricing", {}), conn.get("availability", {})
    countries = av.get("countries", "all")
    av_text = "All Countries or Regions" if str(countries).lower() == "all" else \
        "Specific Countries or Regions: " + ", ".join(countries if isinstance(countries, list) else [countries])
    pa = [Field("Price Schedule › Base Country or Region", pr.get("base_country", "United States"), "choose"),
          Field("Price Schedule › Price", pr.get("price", "Free"), "choose"),
          Field("App Availability › Set Up Availability", av_text, "choose")]
    if "mac" in av:
        a, w, j = answer(av["mac"])
        pa.append(Field("iPhone and iPad Apps on Apple Silicon Mac › Make this app available", yes_no(a),
                        "choose", judgement=j, why=w))
    if "vision_pro" in av:
        a, w, j = answer(av["vision_pro"])
        pa.append(Field("Apple Vision Pro › Make this app available on Apple Vision Pro", yes_no(a), "choose",
                        judgement=j, why=w))
    pa.append(Field("Tax Category", pr.get("tax_category", "App Store software"), "choose"))
    sections.append(Section("Pricing and Availability",
                            f"Apps › {app_name} › Monetization › Pricing and Availability", [Step("Price and countries", pa)],
                            key="pricing"))

    # 4. In-App Purchases ---------------------------------------------------------------------------------
    f_iaps = {i.get("product_id"): i for i in (facts.get("monetization", {}).get("iap") or [])}
    m_iaps = {i.get("product_id"): i for i in (meta.get("iap") or [])}
    c_iaps = {i.get("product_id"): i for i in (conn.get("iap") or [])}
    iap_steps = []
    for pid in list(dict.fromkeys([*f_iaps, *m_iaps, *c_iaps])):
        f, m, c = f_iaps.get(pid, {}), m_iaps.get(pid, {}), c_iaps.get(pid, {})
        fam = c.get("family_sharing", f.get("family_shareable"))
        fa, fw, fj = answer(fam)
        name = m.get("display_name") or f.get("display_name") or pid
        iap_steps += [
            Step(f"{name}: create it", [
                Field("Type", c.get("type") or f.get("type") or "decide", "choose"),
                Field("Reference Name", c.get("reference_name") or f.get("reference_name") or name,
                      limit=lim["iap_reference_name"]),
                Field("Product ID", pid, limit=lim["iap_product_id"], note="Must match the app exactly; never editable."),
            ], note="Press Create."),
            Step(f"{name}: top of the page", [
                Field("Family Sharing", "Turn On" if fa in (True, "Yes", "yes", "on") else "Leave off (don't click Turn On)",
                      "choose", judgement=fj, why=fw or "Once turned on it can never be turned off.",
                      live_ok=["On", "Turned on"] if fa in (True, "Yes", "yes", "on") else ["Off", "Not turned on"]),
                Field("Availability", c.get("availability", "All countries or regions selected"), "choose"),
                Field("Price Schedule › + (Base Country or Region)", c.get("base_country", pr.get("base_country", "United States (USD)")), "choose"),
                Field("Price Schedule › Price", c.get("price") or f.get("price"), "choose",
                      note="Then check Current Price shows it."),
            ], note="Leave Offer Codes alone."),
            Step(f"{name}: Display Name and Description (scroll down, press Add)", [
                Field("Language", lang, "choose"),
                Field("Display Name", m.get("display_name"), limit=lim.get("iap_display_name")),
                Field("Description", m.get("description"), limit=lim.get("iap_description")),
            ]),
            Step(f"{name}: Image (Optional), Tax Category, Review Information", [
                Field("Image (Optional)", c.get("promo_image", "skip: only needed for offer codes or App Store promotion"), "choose"),
                Field("Tax Category", c.get("tax_category", "leave as Match to parent app"), "choose"),
                Field("Review Information › Screenshot", c.get("review_screenshot", "a screenshot of where the purchase appears"),
                      "choose", note="Choose File; it can be replaced but not removed."),
                Field("Review Information › Review Notes (Optional)", c.get("review_notes", ""), limit=lim["iap_review_notes"])
                if c.get("review_notes") else Field("Review Information › Review Notes (Optional)", "leave empty; the app's review notes cover it", "choose"),
            ], note="Press Save at the top. Don't press Add for Review: the first purchase is added on the app's version page and goes to Apple with the app."),
        ]
    if iap_steps:
        sections.append(Section("In-App Purchases", f"Apps › {app_name} › Monetization › In-App Purchases › +",
                                iap_steps, intro="The first purchase goes to App Review together with the app version.",
                                key="iap"))

    # 5. App Privacy --------------------------------------------------------------------------------------
    collects, rows = privacy_rows(kit)
    pv = conn.get("privacy", {})
    p_steps = [Step("Privacy Policy › Edit", [
        Field("Privacy Policy URL", meta.get("privacy_policy_url") or facts.get("urls", {}).get("privacy_policy")),
        Field("User Privacy Choices URL", pv.get("user_choices_url"), "copy") if pv.get("user_choices_url")
        else Field("User Privacy Choices URL", "leave empty (optional)", "choose")])]
    if collects is None:
        p_steps.append(Step("Data collection", [Field("Do you or your third-party partners collect data?", "decide",
                                                       "choose", judgement=True, why="no privacy-labels.md or privacy.yaml")]))
    else:
        p_steps.append(Step("Get Started › data collection", [
            Field("Collect data?", "Yes, we collect data from this app" if collects else
                  "No, we do not collect data from this app", "choose")]))
        if collects and rows:
            p_steps.append(Step("Tick these data types, then Save",
                                [Field(r["category"] or "Data type", r["type"], "choose") for r in rows]))
            for r in rows:
                p_steps.append(Step(f"Data type: {r['type']}", [
                    Field("Purposes (tick each)", ", ".join(r["purposes"]), "choose"),
                    Field("Linked to the user's identity?", r["linked"], "choose", judgement=bool(r["linked_why"]),
                          why=r["linked_why"]),
                    Field("Used for tracking?", r["tracking"], "choose", judgement=bool(r["tracking_why"]),
                          why=r["tracking_why"]),
                ]))
    p_steps.append(Step("Publish", [Field("Product Page Preview", "check it, then press Publish and confirm", "choose")]))
    sections.append(Section("App Privacy", f"Apps › {app_name} › App Privacy", p_steps,
                            intro="Answers drafted in privacy-labels.md. Check them against Xcode's privacy report first.",
                            key="privacy"))

    # 6. Accessibility ------------------------------------------------------------------------------------
    acc = conn.get("accessibility", {})
    a_steps = []
    for dev, feats in (acc.get("devices") or {}).items():
        fl = []
        for feat in ACCESSIBILITY:
            if feat in (feats or {}):
                a, w, j = answer(feats[feat])
                fl.append(Field(feat, yes_no(a), "choose", judgement=j, why=w))
        any_yes = any(f.value == "Yes" for f in fl)
        fl.insert(0, Field("Does the app support any of these features?", "Yes" if any_yes else "No", "choose"))
        a_steps.append(Step(f"Add {dev} Support", fl, note="Then Next, and Publish once a version is live."))
    if acc.get("url"):
        a_steps.append(Step("Accessibility URL", [Field("Accessibility URL", acc["url"])]))
    if a_steps:
        sections.append(Section("App Accessibility (Accessibility Nutrition Labels)",
                                f"Apps › {app_name} › App Accessibility › Get Started", a_steps,
                                intro=acc.get("intro") or "Optional for now. A first version can only save these as a "
                                      "draft: Apple publishes them once a version is live.", key="accessibility"))

    # 7. Build upload -------------------------------------------------------------------------------------
    ver = conn.get("version", {})
    enc = ver.get("export_compliance", {})
    enc_a, enc_why, enc_j = answer(enc.get("uses_non_exempt_encryption", enc) if isinstance(enc, dict) else enc)
    if enc_a is None and "encryption_exempt" in app:
        enc_a = not app["encryption_exempt"]
    sections.append(Section("Upload the build", "Xcode › Product › Archive › Distribute App › App Store Connect", [
        Step(f"Archive and upload version {app.get('version', '?')} ({app.get('build', '?')})", [
            Field("Version and build", f"{app.get('version', '?')} ({app.get('build', '?')})", "info")],
             approval=True, note="Uploading sends this build to Apple. Do it only when you have decided to.",
             key="build/upload"),
        Step("Export compliance (encryption)", [
            Field("Uses non-exempt encryption?", yes_no(enc_a) if enc_a is not None else "decide", "choose",
                  judgement=enc_j or enc_a is None, why=enc_why)],
             note="With ITSAppUsesNonExemptEncryption set to NO in Info.plist, App Store Connect asks nothing."
             if enc_a is False else None),
    ], key="build"))

    # 8. TestFlight ---------------------------------------------------------------------------------------
    tf = conn.get("testflight", {})
    if tf:
        rc = conn.get("review_contact", {})
        tfs = [Field("Beta App Description", tf.get("beta_description")),
               Field("Feedback Email", tf.get("feedback_email") or rc.get("email"))]
        if tf.get("what_to_test"):
            tfs.append(Field("What to Test (on the build)", tf["what_to_test"]))
        sections.append(Section("TestFlight test information (only for outside testers)",
                                f"Apps › {app_name} › TestFlight › Additional › Test Information",
                                [Step("Test Information", tfs)], key="testflight"))

    # 9. Version page ------------------------------------------------------------------------------------
    v_steps = []
    sets = screenshot_sets(kit, locale, rules)
    v_steps.append(Step("App Previews and Screenshots", [
        Field(f"{label} tab", f"{len(files)} files from {folder}/, in this order: {', '.join(files)}", "choose")
        for label, folder, files in sets] or [Field("Screenshots", "none found in screenshots/", "choose", judgement=True)]))
    creative = creative_files(kit, locale)
    if creative:
        v_steps.append(Step("Header and Search Results", [
            Field(f"{tab} tab › Upload", f"creative/{locale}/{name}", "choose") for tab, name in creative],
            note="Shown on iOS and iPadOS 27 and later. Check it with the Preview button before Save."))
    v_steps.append(Step("Product page text", [
        Field("Promotional Text", meta.get("promotional_text"), limit=lim.get("promotional_text")),
        Field("Description", meta.get("description"), limit=lim.get("description")),
        Field("Keywords", meta.get("keywords") if isinstance(meta.get("keywords"), str)
              else ",".join(meta.get("keywords") or []), limit=lim.get("keywords")),
        Field("Support URL", meta.get("support_url")),
        Field("Marketing URL", meta.get("marketing_url")) if meta.get("marketing_url") else
        Field("Marketing URL", "leave empty (optional)", "choose"),
        Field("Version", app.get("version"),
              note="Must equal the build's CFBundleShortVersionString. A record made earlier can still carry an "
                   "old version string and old text: replace every field with the kit's."),
        Field("Copyright", meta.get("copyright") or facts.get("copyright")),
    ] + ([Field("What's New in This Version", meta.get("whats_new"), limit=lim.get("whats_new"))]
         if meta.get("whats_new") and not facts.get("first_version") else [])))
    v_steps.append(Step("Build", [Field("Build › +", f"{app.get('version', '?')} ({app.get('build', '?')})", "choose",
                                        note="If an older build is selected, remove it from the version with the "
                                             "build's − and add this one.")]))
    if iap_steps:
        # Live 2026-10-14: the version page has no In-App Purchases section; the first purchase goes into the same
        # draft submission from its own page ("Add for Review"), then the version's Add for Review.
        v_steps.append(Step("In-App Purchases", [
            Field("In-App Purchases › <purchase> › Add for Review", ", ".join(
                m.get("display_name", pid) for pid, m in {**{k: {} for k in f_iaps}, **m_iaps}.items()), "choose",
                note="The purchase page says \"Your first non-consumable in-app purchase must be submitted with a new "
                     "app version\". Its Add for Review puts it in the same draft as the version; nothing goes to "
                     "Apple until Submit for Review.")], approval=True))
    rc = conn.get("review_contact", {})
    sign_in = conn.get("sign_in_required", False)
    si_a, si_why, si_j = answer(sign_in)
    review = [Field("Sign-in required", yes_no(si_a), "choose", judgement=si_j, why=si_why)]
    if si_a in (True, "Yes"):
        review += [Field("User name", None, private_key="demo_user", placeholder="your demo account user name"),
                   Field("Password", None, private_key="demo_password", placeholder="your demo account password")]
    review += [
        Field("Contact › First name", rc.get("first_name")),
        Field("Contact › Last name", rc.get("last_name")),
        Field("Contact › Phone number", None, private_key="phone", placeholder="your phone number",
              note="International format: + and the country code."),
        Field("Contact › Email", rc.get("email")),
        Field("Notes", review_notes_text(kit, meta), limit=lim.get("review_notes")),
    ]
    if conn.get("review_attachment"):
        review.append(Field("Attachment", conn["review_attachment"], "choose"))
    v_steps.append(Step("App Review Information", review))
    rel_a, rel_why, rel_j = answer(ver.get("release", "manual"))
    v_steps.append(Step("App Store Version Release", [
        Field("Release option", RELEASE.get(str(rel_a), rel_a), "choose", judgement=rel_j, why=rel_why,
              note="The live page starts with \"Automatically release this version\" selected: check the radio.")]))
    if facts.get("first_version"):
        v_steps.append(Step("Phased release and rating reset", [
            Field("Phased Release for Automatic Updates", "not shown for a first version", "info"),
            Field("Reset Overview Rating", "not shown for a first version", "info")]))
    else:
        ph_a, ph_why, ph_j = answer(ver.get("phased_release", False))
        rr_a, rr_why, rr_j = answer(ver.get("reset_ratings", False))
        v_steps.append(Step("Phased release and rating reset", [
            Field("Phased Release for Automatic Updates",
                  "Release update over 7-day period using phased release" if ph_a in (True, "Yes")
                  else "Release update to all users immediately", "choose", judgement=ph_j, why=ph_why),
            Field("Reset Overview Rating", yes_no(rr_a), "choose", judgement=rr_j, why=rr_why)]))
    idfa = ver.get("idfa")
    if idfa is not None:
        a, w, j = answer(idfa)
        v_steps.append(Step("Advertising identifier (IDFA)", [
            Field("Uses the advertising identifier", yes_no(a), "info", judgement=j, why=w,
                  note="App Store Connect no longer asks this on the version page. It is declared in App Privacy "
                       "(Device ID, used for tracking) and by the app's tracking prompt.")]))
    v_steps.append(Step("Save", [Field("Save", "press Save (top right)", "choose")]))
    ver_label = f"iOS App › {app.get('version', '1.0')}"
    sections.append(Section("The version page", f"Apps › {app_name} › {ver_label}", v_steps, key="version",
                            intro="The page heading reads \"iOS App Version <version>\"; the texts sit under "
                                  "Product Page Information (pick the language at the top right). The Header and "
                                  "Search Results tab next to App Previews and Screenshots is optional."))

    # 10–11. Submit, release ------------------------------------------------------------------------------
    sections.append(Section("Submit for review", f"Apps › {app_name} › {ver_label}", [
        Step("Add for Review, then Submit for Review", [
            Field("Add for Review", "press it, then open Draft Submissions", "choose"),
            Field("Submit for Review", "press it only when you have decided to submit", "choose")], approval=True,
             note="This sends the app and its in-app purchase to Apple's reviewers.")], key="submit"))
    if str(rel_a) == "manual":
        sections.append(Section("Release", f"Apps › {app_name} › {ver_label} (status: Pending Developer Release)", [
            Step("Release This Version", [Field("Release This Version", "press it, then Confirm", "choose")],
                 approval=True, note="This puts the app on the App Store for everyone. Only when you decide.")],
                                key="release"))

    growth = growth_section(kit, app_name, facts, locale)
    if growth:
        sections.append(growth[0])
        problems += [f"growth.yaml: {x}" for x in growth[1]]

    for s in sections:
        for st in s.steps:
            for f in st.fields:
                if f.kind == "copy" and not f.private_key and not f.text():
                    problems.append(f"{s.title} › {f.label}: no value")
                if f.over():
                    n, mx, unit, mn = f.count()
                    problems.append(f"{f.label} is {n} {unit}, limit {mx}" + (f" (minimum {mn})" if mn else ""))
    seen = {}
    for s in sections:
        for st in s.steps:
            st.key = st.key or f"{s.key or slug(s.title)}/{slug(st.title)}"
            if st.key in seen:  # two steps with the same title in one section: number the later one
                seen[st.key] += 1
                st.key = f"{st.key}-{seen[st.key]}"
            else:
                seen[st.key] = 1
    g = {"app": app_name, "locale": locale, "sections": sections, "problems": problems,
         "app_version": app.get("version")}
    apply_progress(g, load_yaml(kit / PROGRESS_FILE), private)
    return g


def _folder_files(root):
    """"slot: n files" for each screenshot/preview slot folder under root (one locale)."""
    out = []
    if root.is_dir():
        for slot in sorted(p for p in root.iterdir() if p.is_dir()):
            n = sum(1 for f in slot.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".mov", ".mp4", ".m4v"))
            if n:
                out.append(f"{slot.name}: {n} file(s)")
    return out


def _media_fields(kit, base, loc):
    rel = lambda p: p.relative_to(kit).as_posix()  # noqa: E731
    fields = []
    for kind in ("screenshots", "previews"):
        files = _folder_files(base / kind / loc)
        if files:
            fields.append(Field(f"App Previews and Screenshots ({loc})", f"{rel(base / kind / loc)}/: "
                                + "; ".join(files), "choose"))
    for tab, name in creative_files(base, loc):
        fields.append(Field(f"Header and Search Results › {tab} ({loc})", f"{rel(base / 'creative' / loc)}/{name}",
                            "choose"))
    return fields


def growth_section(kit, app_name, facts, locale):
    """Guide steps for KIT/growth.yaml (references/growth-marketing.md), keyed "growth/<id>". None without the file."""
    sys.path.insert(0, str(HERE))
    import growth as gr
    g = gr.load(kit)
    if not g["present"]:
        return None
    first = bool(facts.get("first_version"))
    later = " Apple allows this only once the app is live (Ready for Distribution); until then it stays prepared."
    steps = []
    for p in g["pages"]:
        f = [Field("Custom Product Pages › + › Reference Name", p["name"])]
        if p.get("deep_link"):
            f.append(Field("Deep Link", p["deep_link"], note="Works on iOS 18 and later once the page is approved."))
        for loc, v in p["locales"].items():
            if v.get("promotional_text"):
                f.append(Field(f"Promotional Text ({loc})", v["promotional_text"],
                               limit={"max": gr.PROMO_MAX, "unit": "chars"}))
            if v.get("keywords"):
                f.append(Field(f"Keywords ({loc})", ", ".join(v["keywords"]), "choose",
                               note="Pick them from the list: only keywords of the latest approved version."))
            f += _media_fields(kit, p["dir"], loc)
        f.append(Field("Add for Review", "only with your yes (asc_sync.py submit KIT --growth " + p["id"] + ")",
                       "choose"))
        steps.append(Step(f"Custom product page: {p['name']}", f, key=f"growth/{p['id']}", after_launch=first,
                          note="Changes to a live page go through Create New Version; the URL stays the same."
                               + (later if first else "")))
    for t in g["tests"]:
        f = [Field("Product Page Optimization › Create Test › Reference Name", t["name"]),
             Field("Traffic Proportion", f"{t['traffic_proportion']}%", "choose",
                   note="Split evenly across the treatments.")]
        for tr in t["treatments"]:
            f.append(Field("Treatment › Name", tr["name"]))
            if tr.get("app_icon_name"):
                f.append(Field(f"{tr['name']} › App Icon", tr["app_icon_name"], "choose",
                               note="Must already be an alternate icon in the live binary."))
            for loc in (t["locales"] or [locale]):
                f += _media_fields(kit, tr["dir"], loc)
        f.append(Field("Start Test", "only after approval and with your yes (asc_sync.py release KIT --start-test "
                       + t["id"] + ")", "choose"))
        steps.append(Step(f"Product page optimization: {t['name']}", f, key=f"growth/{t['id']}", after_launch=first,
                          note="One test at a time, up to 90 days; a started test can't be changed."
                               + (later if first else "")))
    for e in g["events"]:
        f = [Field("In-App Events › + › Reference Name", e["reference_name"],
                   limit={"max": gr.EVENT_REF_MAX, "unit": "chars"}),
             Field("Badge", (e["badge"] or "").replace("_", " ").title(), "choose")]
        if e.get("purpose"):
            f.append(Field("Event Purpose", e["purpose"].replace("_", " ").capitalize(), "choose"))
        f.append(Field("Priority", (e.get("priority") or "NORMAL").title(), "choose"))
        if e.get("deep_link"):
            f.append(Field("Deep Link", e["deep_link"]))
        for s in e["schedules"]:
            f.append(Field("Schedule", f"{', '.join(s['territories'])}: publish {s.get('publishStart') or 'at start'}, "
                                       f"{s['eventStart']} to {s['eventEnd']}", "choose"))
        for loc, row in e["locales"].items():
            for label, k, mx in (("Event Name", "name", gr.EVENT_NAME_MAX),
                                 ("Short Description", "shortDescription", gr.EVENT_SHORT_MAX),
                                 ("Long Description", "longDescription", gr.EVENT_LONG_MAX)):
                if row.get(k):
                    f.append(Field(f"{label} ({loc})", row[k], limit={"max": mx, "unit": "chars"}))
            for ptype, file in gr.event_media(e, loc).items():
                f.append(Field(f"{'Event Card' if ptype == 'EVENT_CARD_ASSET' else 'Event Details Page'} ({loc})",
                               file.relative_to(kit).as_posix(), "choose"))
        f.append(Field("Submit", "only with your yes (asc_sync.py submit KIT --growth " + e["id"] + ")", "choose"))
        steps.append(Step(f"In-app event: {e['reference_name']}", f, key=f"growth/{e['id']}",
                          note="Before the first approval the event goes in the same submission as the first version."
                          if first else "Events can be submitted on their own."))
    return Section("Growth and marketing", f"Apps › {app_name} › Growth & Marketing", steps, key="growth",
                   intro="Custom product pages, product page optimization and in-app events "
                         "(references/growth-marketing.md). Saving them changes nothing customers see; each goes to "
                         "App Review only with your yes."), g["problems"]


# ---------------------------------------------------------------------------------------------------- progress
def private_values(private):
    """Every scalar in private.yaml worth masking (nested too)."""
    out = []

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif v is not None and len(str(v).strip()) >= 4:
            out.append(str(v).strip())
    walk(private or {})
    return out


def mask(text, pvals):
    """Replace every private value in text with [private]. Phone-like values also match with other separators."""
    for v in sorted(pvals, key=len, reverse=True):
        text = text.replace(v, MASK)
        digits = re.sub(r"\D", "", v)
        if len(digits) >= 6:
            text = re.sub(r"\+?" + r"[\s().\-]*".join(digits), MASK, text)
    return text


def apply_progress(g, prog, private=None):
    """Annotate steps with status/date/live values from connect-progress.yaml and find what changed since."""
    entries = (prog or {}).get("steps") or {}
    g["progress_unknown"], g["progress_bad"] = [], []
    by_key = {st.key: st for s in g["sections"] for st in s.steps}
    for key, e in entries.items():
        st = by_key.get(key)
        if st is None:
            g["progress_unknown"].append(key)
            continue
        e = e or {}
        status = str(e.get("status") or "todo")
        if status not in STATUSES:
            g["progress_bad"].append(f"{key}: unknown status {status!r} (use {', '.join(STATUSES)})")
            status = "todo"
        st.status = status
        st.date = str(e["date"]) if e.get("date") else None
        st.live = {str(k): ("" if v is None else str(v)) for k, v in (e.get("live") or {}).items()}
        st.progress_note = e.get("note")
        fields = {f.label: f for f in st.fields}
        st.changes = []
        for label, seen in st.live.items():
            f = fields.get(label)
            if f is None:
                continue
            if f.matches(seen, private) is False:
                st.changes.append((label, seen, f.text(private) if f.private_key else f.text()))
        if any(lab == "Version" for lab, _, _ in st.changes) and g.get("app_version"):
            st.changes = [(lab, old, new + " (must equal the build's CFBundleShortVersionString)"
                           if lab == "Version" else new) for lab, old, new in st.changes]
    g["needs_update"] = [st for s in g["sections"] for st in s.steps if st.changes]


def progress_template(g, prog):
    """connect-progress.yaml with every current step; existing entries are kept as they are."""
    steps = dict((prog or {}).get("steps") or {})
    for s in g["sections"]:
        for st in s.steps:
            steps.setdefault(st.key, {"status": "todo"})
    order = [st.key for s in g["sections"] for st in s.steps]
    ordered = {k: steps[k] for k in order} | {k: v for k, v in steps.items() if k not in order}
    return {**(prog or {}), "steps": ordered}


PROGRESS_HEADER = """# App Store Connect progress: the record of what is done (read by connect_guide.py).
# status: todo | done-by-owner | done-by-claude | skipped. date: YYYY-MM-DD.
# live: field label -> the value seen on the live App Store Connect page. note: mismatch or anything to keep.
# Never write a private.yaml value here (phone, demo password): write [private] instead.
"""


def progress_counts(g):
    sts = [st for s in g["sections"] for st in s.steps]
    c = {k: sum(st.status == k for st in sts) for k in STATUSES}
    return len(sts), c


# ---------------------------------------------------------------------------------------------------- render
def fence(text):
    n = max([3] + [len(m) + 1 for m in re.findall(r"`{3,}", text)])
    return "`" * n


def count_str(f):
    c = f.count()
    if not c:
        return ""
    n, mx, unit, _ = c
    flag = " ⛔ over the limit" if f.over() else ""
    return f" ({n}/{mx} {'characters' if unit == 'chars' else 'bytes'}{flag})"


def render_md(g, private=None):
    out = [f"# App Store Connect guide: {g['app']}", "",
           "Every field in the order App Store Connect asks for it. Copy each grey block exactly as it is.",
           "", f"- {HAND} means the answer needs your judgement: read the reason, then decide.",
           f"- {STOP} means a step that only happens when you say yes at that moment: upload, submit, release.",
           "- Generated by `connect_guide.py` from the kit files. Edit those, not this file.", ""]
    out += progress_md(g)
    if g["problems"]:
        out += ["**Problems to fix first:**", ""] + [f"- {p}" for p in g["problems"]] + [""]
    for si, s in enumerate(g["sections"], 1):
        out += [f"## {si}. {s.title}", "", f"Where: {s.where}", ""]
        if s.intro:
            out += [s.intro, ""]
        for ti, st in enumerate(s.steps, 1):
            box = {"done-by-owner": "x", "done-by-claude": "x", "skipped": "-"}.get(st.status, " ")
            out += [f"### [{box}] {si}.{ti} {st.title}" + (f" {STOP} needs your yes" if st.approval else "") +
                    (f" · {WHO[st.status]}" + (f" {st.date}" if st.date else "") if st.status in WHO else "") +
                    (" · ⚠️ needs update" if st.changes else ""), "", f"<!-- progress key: {st.key} -->", ""]
            if st.guide_only:
                out += ["Guide mode only: the owner does this step; autopilot never does.", ""]
            if st.changes:
                out += ["**Needs update** (live page → kit now):", ""] + \
                       [f"- {lab}: `{one_line(old)}` → `{one_line(new)}`" for lab, old, new in st.changes] + [""]
            if st.progress_note:
                out += [f"> Progress note: {st.progress_note}", ""]
            if st.where:
                out += [f"Where: {st.where}", ""]
            for f in st.fields:
                mark = f"{HAND} " if f.judgement else ""
                txt = f.text(private)
                if f.kind == "copy":
                    out += [f"{mark}**{f.label}** → type exactly{count_str(f)}:", ""]
                    fn = fence(txt)
                    out += [fn + "text", txt, fn, ""]
                elif f.kind == "choose":
                    out += [f"{mark}**{f.label}** → {txt}", ""]
                else:
                    out += [f"{mark}**{f.label}**: {txt}", ""]
                if f.why:
                    out += [f"> Why: {f.why}", ""]
                if f.note:
                    out += [f"> {f.note}", ""]
            if st.note:
                out += [st.note, ""]
    return "\n".join(out).rstrip() + "\n"


def one_line(v, n=80):
    t = re.sub(r"\s+", " ", str(v)).strip() or "(empty)"
    return (t[:n - 1] + "…" if len(t) > n else t).replace("`", "'")


def progress_md(g):
    total, c = progress_counts(g)
    if not any(c[k] for k in WHO) and not g.get("needs_update") and not g.get("progress_unknown"):
        return [f"Progress: none recorded yet (`{PROGRESS_FILE}`).", ""]
    out = [f"**Progress** (from `{PROGRESS_FILE}`, the record): {c['done-by-owner'] + c['done-by-claude']} of {total} "
           f"steps done ({c['done-by-owner']} by the owner, {c['done-by-claude']} by Claude), {c['skipped']} skipped, "
           f"{len(g.get('needs_update', []))} need update.", ""]
    if g.get("progress_unknown"):
        out += [f"Progress entries for steps no longer in the guide: {', '.join(g['progress_unknown'])}", ""]
    for b in g.get("progress_bad", []):
        out += [f"- progress: {b}", ""]
    return out


CSS = """
:root{--bg:#f7f5f0;--card:#fff;--ink:#1d1d1f;--muted:#6e6e73;--line:#e3e0d8;--code:#f1efe9;--accent:#0a66d6;
--warn:#b45309;--stop:#b42318;--ok:#15803d}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#141414;--card:#1e1e1f;--ink:#f2f2f2;
--muted:#a1a1a6;--line:#333;--code:#262628;--accent:#5aa2ff;--warn:#f59e0b;--stop:#f87171;--ok:#4ade80}}
:root[data-theme="dark"]{--bg:#141414;--card:#1e1e1f;--ink:#f2f2f2;--muted:#a1a1a6;--line:#333;--code:#262628;
--accent:#5aa2ff;--warn:#f59e0b;--stop:#f87171;--ok:#4ade80}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text","Helvetica Neue",Arial,sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px 80px}h1{font-size:28px;margin:8px 0}
h2{font-size:21px;margin:36px 0 4px}.where{color:var(--muted);font-size:14px;margin:0 0 12px}
.legend{color:var(--muted);font-size:14px}.problems{border:1px solid var(--stop);border-radius:12px;padding:8px 16px}
details.step{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:10px 0;padding:0}
details.step>summary{list-style:none;cursor:pointer;padding:12px 14px;display:flex;gap:10px;align-items:center;
font-weight:600}details.step>summary::-webkit-details-marker{display:none}
details.step.done>summary{color:var(--muted);text-decoration:line-through}
.body{padding:0 14px 12px}.f{margin:10px 0}.lab{font-weight:600}.cnt{color:var(--muted);font-size:13px;margin-left:6px}
.over{color:var(--stop);font-weight:600}.val{display:inline}.why,.note{color:var(--muted);font-size:14px;margin:4px 0 0}
.hand{color:var(--warn)}.stop{color:var(--stop);font-size:13px;font-weight:600}
.copywrap{position:relative;margin-top:6px}pre{background:var(--code);border-radius:8px;padding:12px 76px 12px 12px;
margin:0;white-space:pre-wrap;word-break:break-word;font:14px/1.45 ui-monospace,"SF Mono",Menlo,monospace}
button.copy{position:absolute;top:8px;right:8px;border:1px solid var(--line);background:var(--card);color:var(--accent);
border-radius:8px;padding:4px 10px;font-size:13px;cursor:pointer}button.copy.ok{color:var(--ok)}
input[type=checkbox]{width:20px;height:20px;accent-color:var(--accent)}.progress{color:var(--muted);font-size:14px}
.who{color:var(--ok);font-size:13px;font-weight:600}.upd{color:var(--warn);font-size:13px;font-weight:600}
.changes{border-left:3px solid var(--warn);padding:4px 10px;margin:8px 0}.changes code{font-size:13px}
"""

JS = """
(function(){var key='connect-guide:'+document.title;var st={};try{st=JSON.parse(localStorage.getItem(key)||'{}')}catch(e){}
function save(){try{localStorage.setItem(key,JSON.stringify(st))}catch(e){}}
var boxes=document.querySelectorAll('input[data-step]');function prog(){var d=0;boxes.forEach(function(b){if(b.checked)d++});
var p=document.getElementById('progress');if(p)p.textContent=d+' of '+boxes.length+' steps ticked'}
boxes.forEach(function(b){var id=b.dataset.step;if(Object.prototype.hasOwnProperty.call(st,id))b.checked=!!st[id];
b.closest('details').classList.toggle('done',b.checked);
b.addEventListener('click',function(e){e.stopPropagation()});b.addEventListener('change',function(){st[id]=b.checked;
b.closest('details').classList.toggle('done',b.checked);if(b.checked)b.closest('details').open=false;save();prog()})});prog();
document.querySelectorAll('button.copy').forEach(function(btn){btn.addEventListener('click',function(){
var t=btn.parentNode.querySelector('pre').textContent;function ok(){btn.textContent='Copied';btn.classList.add('ok');
setTimeout(function(){btn.textContent='Copy';btn.classList.remove('ok')},1500)}
if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(ok,fallback)}else{fallback()}
function fallback(){var ta=document.createElement('textarea');ta.value=t;document.body.appendChild(ta);ta.select();
try{document.execCommand('copy');ok()}catch(e){}document.body.removeChild(ta)}})})})();
"""


def render_html(g, private=None):
    e = html.escape
    h = ["<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
         "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
         f"<title>{e(g['app'])} Connect guide</title><style>{CSS}</style></head><body><main>",
         f"<h1>App Store Connect guide: {e(g['app'])}</h1>",
         f"<p class=\"legend\">Every field in the order App Store Connect asks for it. Press Copy, paste, tick the step. "
         f"<span class=\"hand\">{HAND}</span> needs your judgement. <span class=\"stop\">{STOP}</span> happens only "
         f"when you say yes at that moment.</p><p id=\"progress\" class=\"progress\"></p>",
         f"<p class=\"note\">Steps already ticked come from {PROGRESS_FILE}, the record. Ticks you change on this "
         f"page stay in this browser only; tell Claude (or edit {PROGRESS_FILE}) to record them.</p>"]
    for ln in progress_md(g):
        if ln:
            h.append(f"<p class=\"progress\">{e(re.sub(r'[*`]', '', ln))}</p>")
    if private:
        h.append("<p class=\"stop\">Private copy: contains your personal details. Don't share or commit it.</p>")
    if g["problems"]:
        h.append("<div class=\"problems\"><p><b>Problems to fix first</b></p><ul>" +
                 "".join(f"<li>{e(p)}</li>" for p in g["problems"]) + "</ul></div>")
    for si, s in enumerate(g["sections"], 1):
        h.append(f"<h2>{si}. {e(s.title)}</h2><p class=\"where\">Where: {e(s.where)}</p>")
        if s.intro:
            h.append(f"<p class=\"note\">{e(s.intro)}</p>")
        for ti, st in enumerate(s.steps, 1):
            sid = f"{si}.{ti}"
            stop = f" <span class=\"stop\">{STOP} needs your yes</span>" if st.approval else ""
            done = st.status in WHO
            who = (f" <span class=\"who\">{WHO[st.status]}" + (f" {e(st.date)}" if st.date else "") + "</span>"
                   if done else "")
            upd = " <span class=\"upd\">needs update</span>" if st.changes else ""
            h.append(f"<details class=\"step{' done' if done and not st.changes else ''}\"{'' if done and not st.changes else ' open'}>"
                     f"<summary><input type=\"checkbox\" data-step=\"{e(st.key)}\"{' checked' if done else ''} "
                     f"aria-label=\"Done: {e(st.title)}\"><span>{sid} {e(st.title)}{stop}{who}{upd}</span></summary>"
                     f"<div class=\"body\">")
            if st.guide_only:
                h.append("<p class=\"note\">Guide mode only: the owner does this step; autopilot never does.</p>")
            if st.changes:
                h.append("<div class=\"changes\"><p class=\"upd\">Needs update (live page → kit now)</p><ul>" +
                         "".join(f"<li>{e(lab)}: <code>{e(one_line(old))}</code> → <code>{e(one_line(new))}</code></li>"
                                 for lab, old, new in st.changes) + "</ul></div>")
            if st.progress_note:
                h.append(f"<p class=\"note\">Progress note: {e(str(st.progress_note))}</p>")
            if st.where:
                h.append(f"<p class=\"where\">Where: {e(st.where)}</p>")
            for f in st.fields:
                hand = f"<span class=\"hand\">{HAND}</span> " if f.judgement else ""
                txt = f.text(private)
                cnt = count_str(f)
                cnt_html = f"<span class=\"cnt{' over' if f.over() else ''}\">{e(cnt.strip(' ()'))}</span>" if cnt else ""
                h.append("<div class=\"f\">")
                if f.kind == "copy":
                    h.append(f"<div>{hand}<span class=\"lab\">{e(f.label)}</span>{cnt_html}</div>"
                             f"<div class=\"copywrap\"><pre>{e(txt)}</pre><button class=\"copy\" type=\"button\">Copy</button></div>")
                else:
                    sep = " → " if f.kind == "choose" else ": "
                    h.append(f"<div>{hand}<span class=\"lab\">{e(f.label)}</span>{sep}<span class=\"val\">{e(txt)}</span></div>")
                if f.why:
                    h.append(f"<p class=\"why\">Why: {e(f.why)}</p>")
                if f.note:
                    h.append(f"<p class=\"note\">{e(f.note)}</p>")
                h.append("</div>")
            if st.note:
                h.append(f"<p class=\"note\">{e(st.note)}</p>")
            h.append("</div></details>")
    h.append(f"</main><script>{JS}</script></body></html>")
    return "\n".join(h) + "\n"


# ---------------------------------------------------------------------------------------------------- main
def git_ignored(path: pathlib.Path):
    """True/False if inside a git repo, None if not a repo or git is missing."""
    try:
        r = subprocess.run(["git", "check-ignore", "-q", path.name], cwd=path.parent, capture_output=True)
    except OSError:
        return None
    return {0: True, 1: False}.get(r.returncode)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kit")
    ap.add_argument("--locale")
    ap.add_argument("--rules")
    ap.add_argument("--no-private", action="store_true", help="ignore private.yaml; write no private copy")
    ap.add_argument("--check", action="store_true",
                    help="list the steps whose live values (connect-progress.yaml) differ from the kit; exit 1 if any")
    ap.add_argument("--init-progress", action="store_true",
                    help="add every step missing from connect-progress.yaml as todo (creates the file)")
    a = ap.parse_args(argv)
    kit = pathlib.Path(a.kit)
    rules_path = a.rules or (kit / "rules.json" if (kit / "rules.json").exists() else HERE / "rules.json")
    rules = json.loads(pathlib.Path(rules_path).read_text())
    priv_path = kit / "private.yaml"
    priv_raw = load_yaml(priv_path)
    private = (priv_raw.get("review_contact") or {}) | {k: v for k, v in priv_raw.items() if not isinstance(v, dict)}
    pvals = private_values(priv_raw)  # masked in everything public, even with --no-private
    g = build(kit, a.locale, rules, private)
    prog_path = kit / PROGRESS_FILE
    if a.init_progress:
        prog_path.write_text(PROGRESS_HEADER + yaml.safe_dump(progress_template(g, load_yaml(prog_path)),
                                                              sort_keys=False, allow_unicode=True, width=120))
        print(f"wrote {prog_path.name}")
    if prog_path.exists() and pvals and mask(prog_path.read_text(), pvals) != prog_path.read_text():
        print(f"WARNING: {prog_path.name} contains a private.yaml value. Replace it with {MASK}; "
              f"the public guide masks it.", file=sys.stderr)
    (kit / "CONNECT-GUIDE.md").write_text(mask(render_md(g), pvals))
    (kit / "connect-guide.html").write_text(mask(render_html(g), pvals))
    written = ["CONNECT-GUIDE.md", "connect-guide.html"]
    if priv_path.exists() and not a.no_private:
        out = kit / "connect-guide.private.html"
        out.write_text(render_html(g, private))
        written.append(out.name)
        for p in (priv_path, out):
            if git_ignored(p) is False:
                print(f"WARNING: {p.name} is not gitignored. Add it to .gitignore before committing.", file=sys.stderr)
    for p in g["problems"]:
        print(f"problem: {p}", file=sys.stderr)
    judgement = sum(f.judgement for s in g["sections"] for st in s.steps for f in st.fields)
    print(f"wrote {', '.join(written)} in {kit} ({len(g['sections'])} screens, {judgement} {HAND} answers)")
    for ln in progress_md(g):
        if ln:
            print(mask(re.sub(r"[*`]", "", ln), pvals))
    if a.check:
        if not prog_path.exists():
            print(f"check: no {PROGRESS_FILE}; nothing recorded to compare (run with --init-progress to start one)")
        for st in g["needs_update"]:
            print(mask(f"needs update: {st.key} ({st.title})", pvals))
            for lab, old, new in st.changes:
                print(mask(f"  {lab}: {one_line(old)} → {one_line(new)}", pvals))
        if not g["needs_update"]:
            print("check: every recorded live value matches the kit")
    bad = any("limit" in p or "missing" in p or "no value" in p for p in g["problems"])
    return 1 if bad or (a.check and g["needs_update"]) else 0


if __name__ == "__main__":
    sys.exit(main())
