#!/usr/bin/env python3
"""Read and check KIT/growth.yaml: custom product pages, product page optimization tests and in-app events.

  growth.py KIT            print what the kit prepares and any problems; exit 1 when there are problems

This module is the kit side only (no network). asc_sync.py (area "growth") plans and applies it through the
App Store Connect API, connect_guide.py writes the guide steps ("growth/<id>"), validate_kit.py checks the images.
Facts, limits and sources: references/growth-marketing.md (read 2026-10-14).

Folders (all under KIT/growth/):
  <page id>/screenshots/<locale>/<slot>/NN.png       custom product page screenshots (slot names as KIT/screenshots)
  <page id>/previews/<locale>/<slot>/*.mov           its app previews
  <page id>/creative/<locale>/universal.png          its header + search-results asset (header.* / search.* override)
  <test id>/<treatment id>/screenshots|previews|creative/<locale>/...   one product page optimization treatment
  <event id>/media/<locale>/card.png|.mp4             in-app event card (16:9)
  <event id>/media/<locale>/details.png|.mp4          in-app event details page (9:16)
A locale without its own folder is planned without media: Apple then uses the default product page's.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

import yaml

GROWTH_FILE = "growth.yaml"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

# Limits (references/growth-marketing.md; App Store Connect Help and the API, read 2026-10-14).
MAX_CPPS = 70                 # custom product pages per app
PROMO_MAX = 170               # promotional text, as on the default product page
MAX_TREATMENTS = 3            # treatments per product page optimization test
EVENT_REF_MAX = 64            # in-app event reference name
EVENT_NAME_MAX = 30           # event name
EVENT_SHORT_MAX = 50          # short description
EVENT_LONG_MAX = 120          # long description
EVENT_MAX_DAYS = 31           # an event runs at most 31 days
EVENT_EARLY_DAYS = 14         # it can be promoted at most 14 days before it starts
EVENT_MIN_MINUTES = 15        # and lasts at least 15 minutes
EVENT_START_SPREAD_HOURS = 48  # start dates in different regions lie within 48 hours of each other
MAX_EVENTS_PUBLISHED = 10     # published (or overlapping) at a time; 15 approved per app
BADGES = ("LIVE_EVENT", "PREMIERE", "CHALLENGE", "COMPETITION", "NEW_SEASON", "MAJOR_UPDATE", "SPECIAL_EVENT")
PURPOSES = ("APPROPRIATE_FOR_ALL_USERS", "ATTRACT_NEW_USERS", "KEEP_ACTIVE_USERS_INFORMED", "BRING_BACK_LAPSED_USERS")
PRIORITIES = ("HIGH", "NORMAL")
EVENT_MEDIA = {"card": "EVENT_CARD_ASSET", "details": "EVENT_DETAILS_PAGE_ASSET"}


def _yaml(p):
    p = pathlib.Path(p)
    return (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}


def _enum(v):
    return re.sub(r"[^A-Z]+", "_", str(v or "").upper()).strip("_") or None


def _keywords(v):
    if v is None:
        return []
    items = v.split(",") if isinstance(v, str) else v
    return [str(x).strip() for x in items if str(x).strip()]


def _when(v):
    """YAML dates/times → ISO 8601 strings the API takes (a bare date means midnight UTC)."""
    if v is None:
        return None
    s = v.isoformat() if hasattr(v, "isoformat") else str(v).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        s += "T00:00:00Z"
    if re.search(r"[+-]\d{2}:\d{2}$", s) is None and not s.endswith("Z"):
        s += "Z"
    return s.replace("+00:00", "Z")


def _days(a, b):
    import datetime as dt

    def parse(s):
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return (parse(b) - parse(a)).total_seconds() / 86400


def load(kit):
    """KIT/growth.yaml, normalised: {"pages": [...], "tests": [...], "events": [...], "problems": [...]}.
    Missing file → all empty. Every list entry gets "dir" (its folder under KIT/growth)."""
    kit = pathlib.Path(kit)
    raw = _yaml(kit / GROWTH_FILE)
    out = {"pages": [], "tests": [], "events": [], "problems": [], "present": (kit / GROWTH_FILE).exists()}
    P = out["problems"].append
    seen = set()

    def check_id(kind, x):
        i = str(x.get("id") or "")
        if not ID_RE.match(i):
            P(f"{kind} {x.get('name') or x.get('reference_name') or '?'}: id {i!r} must be lower-case letters, "
              f"digits and dashes (it names the folder growth/<id>/)")
        elif i in seen:
            P(f"{kind} id {i!r} is used twice")
        seen.add(i)
        return i

    for x in raw.get("custom_product_pages") or []:
        i = check_id("custom product page", x)
        name = str(x.get("name") or "").strip()
        if not name:
            P(f"custom product page {i}: name is required")
        locs = {}
        for loc, v in (x.get("locales") or {}).items():
            v = v or {}
            promo = v.get("promotional_text")
            if promo and len(str(promo)) > PROMO_MAX:
                P(f"custom product page {i} {loc}: promotional text is {len(str(promo))} characters "
                  f"(limit {PROMO_MAX})")
            locs[str(loc)] = {"promotional_text": promo, "keywords": _keywords(v.get("keywords"))}
            if "promotional_text" in v and promo is None:
                locs[str(loc)]["promotional_text"] = ""   # present but empty: clear it on Apple's side
            elif "promotional_text" not in v:
                del locs[str(loc)]["promotional_text"]    # absent: leave Apple's value alone
        if not locs:
            P(f"custom product page {i}: add at least one language under locales:")
        deep_link = ("" if x.get("deep_link") is None else x["deep_link"]) if "deep_link" in x else None
        out["pages"].append({"id": i, "name": name, "deep_link": deep_link,
                             "visible": x.get("visible"), "audience": x.get("audience"),
                             "locales": locs, "dir": kit / "growth" / i})
    if len(out["pages"]) > MAX_CPPS:
        P(f"{len(out['pages'])} custom product pages: Apple allows {MAX_CPPS}")

    for x in raw.get("experiments") or raw.get("product_page_optimization") or []:
        i = check_id("test", x)
        name = str(x.get("name") or "").strip()
        if not name:
            P(f"test {i}: name is required")
        tp = x.get("traffic_proportion")
        if not isinstance(tp, int) or not 1 <= tp <= 100:
            P(f"test {i}: traffic_proportion must be a whole percentage from 1 to 100 (the share of visitors "
              f"who see a treatment)")
        treats = []
        for t in x.get("treatments") or []:
            ti = str(t.get("id") or "")
            if not ID_RE.match(ti):
                P(f"test {i}: treatment id {ti!r} must be lower-case letters, digits and dashes")
            if not str(t.get("name") or "").strip():
                P(f"test {i}: treatment {ti} needs a name")
            treats.append({"id": ti, "name": str(t.get("name") or "").strip(),
                           "app_icon_name": t.get("app_icon_name"), "hypothesis": t.get("hypothesis"),
                           "dir": kit / "growth" / i / ti})
        if not 1 <= len(treats) <= MAX_TREATMENTS:
            P(f"test {i}: {len(treats)} treatment(s); Apple allows 1 to {MAX_TREATMENTS}")
        out["tests"].append({"id": i, "name": name, "traffic_proportion": tp, "treatments": treats,
                             "locales": [str(x) for x in (x.get("locales") or [])],
                             "hypothesis": x.get("hypothesis"), "dir": kit / "growth" / i})
    if len(out["tests"]) > 1:
        P(f"{len(out['tests'])} tests: Apple runs one product page optimization test at a time; "
          f"keep the next ones commented out until the current one ends")

    for x in raw.get("in_app_events") or []:
        i = check_id("in-app event", x)
        ref_name = str(x.get("reference_name") or x.get("name") or "").strip()
        if not ref_name:
            P(f"in-app event {i}: reference_name is required")
        elif len(ref_name) > EVENT_REF_MAX:
            P(f"in-app event {i}: reference name is {len(ref_name)} characters (limit {EVENT_REF_MAX})")
        ev = {"id": i, "reference_name": ref_name, "badge": _enum(x.get("badge")),
              "purpose": _enum(x.get("purpose")), "priority": _enum(x.get("priority") or "normal"),
              "deep_link": x.get("deep_link"), "purchase_requirement": x.get("purchase_requirement"),
              "primary_locale": x.get("primary_locale"), "schedules": [], "locales": {},
              "dir": kit / "growth" / i}
        for key, allowed in (("badge", BADGES), ("purpose", PURPOSES), ("priority", PRIORITIES)):
            if ev[key] and ev[key] not in allowed:
                P(f"in-app event {i}: {key} {x.get(key)!r} isn't one of {', '.join(allowed)}")
        if not ev["badge"]:
            P(f"in-app event {i}: badge is required ({', '.join(BADGES)})")
        for s in x.get("schedule") or x.get("territory_schedules") or []:
            sc = {"territories": [str(t) for t in (s.get("territories") or [])],
                  "publishStart": _when(s.get("publish_start")), "eventStart": _when(s.get("event_start")),
                  "eventEnd": _when(s.get("event_end"))}
            if not sc["eventStart"] or not sc["eventEnd"]:
                P(f"in-app event {i}: every schedule needs event_start and event_end")
            else:
                if _days(sc["eventStart"], sc["eventEnd"]) > EVENT_MAX_DAYS:
                    P(f"in-app event {i}: runs {_days(sc['eventStart'], sc['eventEnd']):.0f} days; "
                      f"Apple allows {EVENT_MAX_DAYS}")
                if _days(sc["eventStart"], sc["eventEnd"]) * 24 * 60 < EVENT_MIN_MINUTES:
                    P(f"in-app event {i}: an event lasts at least {EVENT_MIN_MINUTES} minutes")
                if sc["publishStart"] and _days(sc["publishStart"], sc["eventStart"]) > EVENT_EARLY_DAYS:
                    P(f"in-app event {i}: published {_days(sc['publishStart'], sc['eventStart']):.0f} days "
                      f"before it starts; Apple allows {EVENT_EARLY_DAYS}")
            if not sc["territories"]:
                P(f"in-app event {i}: every schedule needs territories (e.g. [USA, GBR])")
            ev["schedules"].append(sc)
        starts = sorted(s["eventStart"] for s in ev["schedules"] if s["eventStart"])
        if len(starts) > 1 and _days(starts[0], starts[-1]) * 24 > EVENT_START_SPREAD_HOURS:
            P(f"in-app event {i}: start dates in different regions must lie within "
              f"{EVENT_START_SPREAD_HOURS} hours of each other")
        if not ev["schedules"]:
            P(f"in-app event {i}: add a schedule (territories, publish_start, event_start, event_end)")
        for loc, v in (x.get("locales") or {}).items():
            v = v or {}
            row = {"name": v.get("name"), "shortDescription": v.get("short_description"),
                   "longDescription": v.get("long_description")}
            for k, mx in (("name", EVENT_NAME_MAX), ("shortDescription", EVENT_SHORT_MAX),
                          ("longDescription", EVENT_LONG_MAX)):
                if not row[k]:
                    P(f"in-app event {i} {loc}: {k} is required")
                elif len(str(row[k])) > mx:
                    P(f"in-app event {i} {loc}: {k} is {len(str(row[k]))} characters (limit {mx})")
            ev["locales"][str(loc)] = row
        if not ev["locales"]:
            P(f"in-app event {i}: add at least one language under locales:")
        ev["primary_locale"] = ev["primary_locale"] or next(iter(ev["locales"]), None)
        out["events"].append(ev)
    if len(out["events"]) > MAX_EVENTS_PUBLISHED:
        P(f"{len(out['events'])} in-app events: Apple allows {MAX_EVENTS_PUBLISHED} published (or overlapping) "
          f"at a time; archive past ones in growth.yaml")
    return out


def event_media(ev, locale):
    """{placementType: file} for one event language: media/<locale>/card.* and details.*."""
    root = pathlib.Path(ev["dir"]) / "media" / locale
    out = {}
    if root.is_dir():
        for f in sorted(root.iterdir()):
            if f.is_file() and f.stem.lower() in EVENT_MEDIA and \
                    f.suffix.lower() in (".png", ".jpg", ".jpeg", ".mp4", ".mov", ".m4v"):
                out[EVENT_MEDIA[f.stem.lower()]] = f
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kit")
    a = ap.parse_args(argv)
    g = load(a.kit)
    if not g["present"]:
        print(f"no {GROWTH_FILE} in {a.kit} (copy templates/growth.example.yaml to start)")
        return 0
    for p in g["pages"]:
        print(f"custom product page {p['id']}: {p['name']} ({', '.join(p['locales'])})")
    for t in g["tests"]:
        print(f"test {t['id']}: {t['name']}, {t['traffic_proportion']}% of visitors, "
              f"{len(t['treatments'])} treatment(s)")
    for e in g["events"]:
        print(f"in-app event {e['id']}: {e['reference_name']} ({e['badge']})")
    for p in g["problems"]:
        print(f"problem: {p}")
    return 1 if g["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
