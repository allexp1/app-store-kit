#!/usr/bin/env python3
"""Freeze the rule table for one kit, or check whether Apple's pages changed.

  snapshot_rules.py freeze KIT_DIR          copy rules.json into KIT_DIR/rules.json, fetch every
                                            source, record today's date and a hash of each page's text
  snapshot_rules.py check  [RULES_JSON]     re-fetch the sources and report which pages changed
                                            since the hashes in RULES_JSON (default: the skill's own)
  snapshot_rules.py hash   URL              print the text hash for one page

The hash is over the page's visible text (scripts, styles and tags removed, whitespace collapsed),
because the raw HTML of developer.apple.com changes on every request. A changed hash means
"re-read this page", not "the rules changed": a human or Claude must read it and update rules.json.
Exit code of `check`: 0 unchanged, 3 at least one page changed or could not be fetched.
"""
import datetime as dt
import hashlib
import html
import json
import pathlib
import re
import sys
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_RULES = HERE / "rules.json"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) app-store-kit/1"


def page_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<!--.*?-->", " ", raw)
    # keep only the main content when the page marks it, to ignore nav/footer churn
    m = re.search(r"(?is)<main\b.*?</main>", raw)
    if m:
        raw = m.group(0)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", raw))
    return re.sub(r"\s+", " ", text).strip()


def fetch(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def text_hash(url: str) -> str:
    return hashlib.sha256(page_text(fetch(url)).encode()).hexdigest()


def load(path):
    return json.loads(pathlib.Path(path).read_text())


def check(rules_path) -> int:
    rules = load(rules_path)
    changed = 0
    for s in rules["sources"]:
        if not s.get("text_sha256"):
            print(f"no baseline {s['id']}: {s['url']}")
            changed += 1
            continue
        try:
            h = text_hash(s["url"])
        except Exception as e:  # network errors are reported, never hidden
            print(f"ERROR   {s['id']}: {e}")
            changed += 1
            continue
        if s["text_sha256"] == h:
            print(f"same    {s['id']}")
        else:
            print(f"CHANGED {s['id']}: {s['url']}\n        was {s['text_sha256'][:16]}… now {h[:16]}…  -> re-read the page")
            changed += 1
    print(f"rules fetched {rules.get('fetched')}; {changed} page(s) need a re-read")
    return 3 if changed else 0


def freeze(kit_dir) -> int:
    kit = pathlib.Path(kit_dir)
    kit.mkdir(parents=True, exist_ok=True)
    rules = load(DEFAULT_RULES)
    baseline = {s["id"]: s.get("text_sha256") for s in rules["sources"]}
    drift, failed = [], []
    today = dt.date.today().isoformat()
    for s in rules["sources"]:
        s.setdefault("fetched", rules.get("fetched"))
        try:
            s["text_sha256"] = text_hash(s["url"])
        except Exception as e:
            print(f"ERROR fetching {s['id']}: {e}")
            failed.append(s["id"])
            continue
        s["fetched"] = today
        if not baseline[s["id"]] or baseline[s["id"]] != s["text_sha256"]:
            drift.append(s["id"])
    rules["skill_baseline_fetched"] = rules.get("fetched")
    if not failed:
        rules["fetched"] = today
    rules["frozen_for_kit"] = True
    out = kit / "rules.json"
    out.write_text(json.dumps(rules, indent=2) + "\n")
    print(f"wrote {out}")
    if failed:
        print("WARNING: fetch failed; baseline hashes and fetched dates retained: " + ", ".join(failed))
    if drift:
        print("WARNING: these pages differ from or have no skill baseline; read them and update "
              f"{out} before validating: {', '.join(drift)}")
        return 3
    return 3 if failed else 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] not in ("freeze", "check", "hash"):
        sys.exit(__doc__)
    if a[0] == "freeze" and len(a) == 2:
        sys.exit(freeze(a[1]))
    if a[0] == "check":
        sys.exit(check(a[1] if len(a) > 1 else DEFAULT_RULES))
    if a[0] == "hash" and len(a) == 2:
        print(text_hash(a[1]))
        sys.exit(0)
    sys.exit(__doc__)
