#!/usr/bin/env python3
"""Measure growth: App Store Connect analytics and sales reports joined with KIT/growth.yaml.

Usage:
  asc_reports.py request KIT [--yes] [--dry-run] [--snapshot]
                    ask Apple to start generating analytics reports for the app (ONGOING; --snapshot asks for a
                    ONE_TIME_SNAPSHOT of the history). A write: exit 2 without --yes. The first reports arrive
                    1-2 days later; after that a new daily instance arrives every day.
  asc_reports.py fetch KIT [--days 30]
                    download the report instances processed in the last N days into KIT/reports/ (a folder that
                    ignores itself in git: it holds raw store data), merge them and write KIT/reports/<report>.tsv
  asc_reports.py growth KIT [--days 30] [--live]
                    KIT/GROWTH-RESULTS.md: impressions, page views, first-time downloads and conversion per product
                    page, in-app event and source type, joined with growth.yaml; flags pages that convert below the
                    default page and samples too small to judge; proposes the next single-variable test.
                    --live also reads the live custom product pages and tests (GET only)
  asc_reports.py sales KIT --vendor N [--date YYYY-MM-DD]
                    one daily Sales and Trends summary (GET /v1/salesReports): units and proceeds by type

Reports used (references/analytics-reports.md): "App Store Discovery and Engagement" (impressions, page views, taps)
and "App Store Downloads" (download types), Detailed when present: only the Detailed reports carry Page Title,
which is how a custom product page or in-app event is told apart. There is no page id column; the join is by name.

Auth as asc_sync.py: --key-id / --issuer-id / --key-path, ASC_* env, or connect.yaml `api:`. Analytics need a key
with the Admin role to request and Admin, Sales and Reports or Finance to download; Sales needs Sales and Reports
(or Finance / Admin) and a team key (individual keys can't read Sales and Finance).
Exit 0 ok, 1 an API error or nothing to read, 2 a missing --yes or bad input.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import connect_guide as cg  # noqa: E402
import growth as gr  # noqa: E402
from asc_api import API_ORIGIN, ASCError, ConfigError, make_client, same_origin  # noqa: E402

REPORTS_DIR = "reports"
RESULTS_MD = "GROWTH-RESULTS.md"
STATE_JSON = "request.json"
# Report kind → (category, words in its name). Names: "App Store Discovery and Engagement Standard|Detailed" (doc
# example) and "App Store Downloads Standard|Detailed" (the report page's title + suffix: UNCONFIRMED exact name).
KINDS = {"engagement": ("APP_STORE_ENGAGEMENT", "discovery and engagement"),
         "downloads": ("COMMERCE", "download")}
DEFAULT_PAGE = "default product page"   # Page Title value for the default page (Apple's glossary)
MIN_VIEWS = 100          # fewer unique page views than this: too small to judge
MIN_DOWNLOADS = 5        # Apple shows a page's or test's numbers only after 5 first-time downloads
Z90 = 1.2816             # one-sided 90 % (Apple waits for 90 % confidence on tests)
TEST_ORDER = (("first screenshot", ("screenshot", "shot", "first")), ("header asset", ("header",)),
              ("app icon", ("icon",)))
# Sales report product type identifiers (App Store Connect Help › Product type identifiers, read 2026-10-15).
PRODUCT_TYPES = {
    "downloads": {"1", "1F", "1T", "F1", "1E", "1EP", "1EU", "1-B", "F1-B"},
    "redownloads": {"3", "3F"},
    "updates": {"7", "7F", "7T", "F7"},
    "in-app purchases": {"IA1", "IA1-M", "IA9", "IA9-M", "IAY", "IAY-M", "FI1"},
    "restored purchases": {"IA3"},
}


def _yaml(p):
    p = pathlib.Path(p)
    return (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}


def attrs(o):
    return (o or {}).get("attributes") or {}


def find_app(client, bundle_id):
    """The app with exactly this bundle id, or None (same lookup as asc_sync.find_app)."""
    apps = client.get_all("/v1/apps", {"filter[bundleId]": bundle_id, "limit": 200})
    return next((a for a in apps if attrs(a).get("bundleId") == bundle_id), None)


def bundle_id(kit):
    return ((_yaml(pathlib.Path(kit) / "facts.yaml").get("app")) or {}).get("bundle_id")


def reports_dir(kit):
    """KIT/reports/, created with a .gitignore of `*` so raw store data never lands in the app's repo."""
    d = pathlib.Path(kit) / REPORTS_DIR
    d.mkdir(parents=True, exist_ok=True)
    gi = d / ".gitignore"
    if not gi.exists():
        gi.write_text("# Downloaded App Store Connect reports: store data, not source. Never committed.\n*\n")
    return d


# ---------------------------------------------------------------------------------------------------- raw download
def raw_get(client, url, params=None, auth=False, accept="application/a-gzip"):
    """GET bytes (a report file). Segment URLs are pre-signed: no JWT. /v1/salesReports needs the JWT."""
    headers = {"Accept": accept}
    if auth:
        full = client._url(url, params)      # Apple's API host only (the client refuses any other)
        if getattr(client, "_token", None):
            # The same rule as Client.request: the JWT goes to Apple's API origin only (a base_url elsewhere is
            # refused), and the default transport refuses a redirect that would carry it off that origin.
            if not same_origin(full, API_ORIGIN):
                raise ASCError(0, [], "GET", "", message=f"refused to send the API token outside {API_ORIGIN}")
            headers["Authorization"] = "Bearer " + client._token()
    else:
        if not str(url).startswith("https://"):
            raise ASCError(0, [], "GET", "", message="a report segment URL must be https")
        full = url                           # pre-signed download link: no JWT goes with it
    status, _, raw = client.transport("GET", full, headers, None)
    if status >= 400:
        try:
            errors = json.loads(raw or b"{}").get("errors")
        except ValueError:
            errors = None
        raise ASCError(status, errors, "GET", full.replace(client.base_url, "").split("?")[0])
    return raw or b""


def unzip(raw):
    """Report bytes → text. Apple serves gzip; a plain file passes through."""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8-sig", errors="replace")


def parse_table(text):
    """Tab-separated (or comma-separated) report text → list of dicts keyed by the header names as written.
    Apple: rely on column names, not positions; values are not case sensitive."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    delim = "\t" if "\t" in lines[0] else ","
    rows = list(csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delim))
    return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in rows]


def col(row, name):
    """A column by name, ignoring case and spacing."""
    want = re.sub(r"\s+", " ", name).strip().lower()
    for k, v in row.items():
        if re.sub(r"\s+", " ", k).strip().lower() == want:
            return v
    return ""


def num(v):
    try:
        return float(str(v).replace(",", "")) if str(v).strip() else 0.0
    except ValueError:
        return 0.0


def latest_per_date(tagged):
    """[(processingDate, row)] → rows, keeping for each Date only the rows of the latest processingDate.
    Apple: a newer instance overwrites an older one for the same Date; merging both double counts."""
    best = {}
    for pdate, row in tagged:
        d = col(row, "Date")
        if pdate > best.get(d, ""):
            best[d] = pdate
    return [row for pdate, row in tagged if pdate == best.get(col(row, "Date"))]


# ---------------------------------------------------------------------------------------------------- request
def list_requests(client, app_id):
    return client.get_all(f"/v1/apps/{app_id}/analyticsReportRequests", {"limit": 200})


def active_request(reqs, access="ONGOING"):
    return next((r for r in reqs if attrs(r).get("accessType") == access and
                 not attrs(r).get("stoppedDueToInactivity")), None)


def cmd_request(client, kit, app, args):
    access = "ONE_TIME_SNAPSHOT" if args.snapshot else "ONGOING"
    reqs = list_requests(client, app["id"])
    have = active_request(reqs, access)
    if have:
        print(f"An {access} report request already exists ({have['id']}); nothing to do. Run fetch to download.")
        _save_state(kit, have)
        return 0
    stopped = [r for r in reqs if attrs(r).get("accessType") == access and attrs(r).get("stoppedDueToInactivity")]
    if stopped:
        print(f"The earlier {access} request stopped because nobody downloaded for a long time; a new one is needed.")
    what = ("Ask Apple for a one-time snapshot of the app's report history (one per month)" if args.snapshot else
            "Ask Apple to start generating the app's analytics reports every day")
    if not args.yes and not client.dry_run:
        print(f"{what}: POST /v1/analyticsReportRequests (accessType {access}). Customers see nothing, but it is a "
              f"change on the account and needs an Admin key: ask the owner, then run again with --yes.")
        return 2
    body = {"data": {"type": "analyticsReportRequests", "attributes": {"accessType": access},
                     "relationships": {"app": {"data": {"type": "apps", "id": app["id"]}}}}}
    doc = client.post("/v1/analyticsReportRequests", body)
    if client.dry_run:
        for r in client.recorded:
            print(f"would send: {r['method']} {r['path']} {json.dumps(r['json'])}")
        return 0
    new = (doc or {}).get("data") or {}
    again = next((r for r in list_requests(client, app["id"]) if r.get("id") == new.get("id")), None)
    if not again:
        print(f"Apple accepted the request ({new.get('id')}) but it doesn't show in the list yet; run request again "
              f"later to check.")
        return 1
    _save_state(kit, again)
    print(f"Report request {again['id']} ({access}) created. Apple generates the first reports in 1-2 days; then "
          f"`asc_reports.py fetch KIT` downloads them. Fetch at least every few weeks: a request nobody reads stops "
          f"(stoppedDueToInactivity), and instances are deleted after 35 days.")
    return 0


def _save_state(kit, req):
    p = reports_dir(kit) / STATE_JSON
    p.write_text(json.dumps({"id": req.get("id"), **attrs(req), "checked": dt.date.today().isoformat()}, indent=2))


# ---------------------------------------------------------------------------------------------------- fetch
def pick_reports(reports):
    """{kind: report} preferring the Detailed report (it has Page Title) over the Standard one."""
    out = {}
    for kind, (cat, words) in KINDS.items():
        cands = [r for r in reports if attrs(r).get("category") == cat and
                 words in str(attrs(r).get("name", "")).lower()]
        if kind == "downloads":  # not "Pre-Order", not the web preview report
            cands = [r for r in cands if "pre-order" not in attrs(r)["name"].lower()]
        cands.sort(key=lambda r: (0 if "detailed" in attrs(r)["name"].lower() else 1, attrs(r)["name"]))
        if cands:
            out[kind] = cands[0]
    return out


def cmd_fetch(client, kit, app, args, today=None):
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=args.days)).isoformat()
    reqs = list_requests(client, app["id"])
    use = [r for r in reqs if not attrs(r).get("stoppedDueToInactivity")]
    if not use:
        msg = "stopped (nobody downloaded for a long time)" if reqs else "none yet"
        print(f"No active analytics report request ({msg}). Run `asc_reports.py request KIT --yes` first; the "
              f"first data arrives 1-2 days later.")
        return 1
    out = reports_dir(kit)
    raw_dir = out / "raw"
    found, manifest = {}, {"fetched": today.isoformat(), "days": args.days, "reports": {}}
    for req in use:
        reports = client.get_all(f"/v1/analyticsReportRequests/{req['id']}/reports", {"limit": 200})
        for kind, rep in pick_reports(reports).items():
            found.setdefault(kind, []).append(rep)
    if not found:
        print("The request exists but Apple hasn't generated any reports yet (allow 1-2 days after the request).")
        return 1
    for kind, reps in found.items():
        tagged, names, n_files = [], set(), 0
        for rep in reps:
            name = attrs(rep).get("name", kind)
            names.add(name)
            insts = client.get_all(f"/v1/analyticsReports/{rep['id']}/instances",
                                   {"filter[granularity]": "DAILY", "limit": 200})
            for inst in insts:
                pdate = str(attrs(inst).get("processingDate") or "")
                if pdate < since:
                    continue
                for seg in client.get_all(f"/v1/analyticsReportInstances/{inst['id']}/segments", {"limit": 200}):
                    a = attrs(seg)
                    dest = raw_dir / kind / f"{pdate}-{seg['id']}.gz"
                    if not dest.exists() or (a.get("checksum") and
                                             hashlib.md5(dest.read_bytes()).hexdigest() != a["checksum"]):
                        data = raw_get(client, a["url"])
                        if a.get("checksum") and hashlib.md5(data).hexdigest() != a["checksum"]:
                            print(f"{name} {pdate}: checksum doesn't match; skipped (fetch again later)")
                            continue
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(data)
                    n_files += 1
                    tagged += [(pdate, r) for r in parse_table(unzip(dest.read_bytes()))]
        rows = latest_per_date(tagged)
        write_table(out / f"{kind}.tsv", rows)
        manifest["reports"][kind] = {"names": sorted(names), "files": n_files, "rows": len(rows)}
        print(f"{kind}: {', '.join(sorted(names))}: {n_files} file(s), {len(rows)} row(s) → "
              f"{(out / f'{kind}.tsv').relative_to(kit)}")
        if not any("detailed" in n.lower() for n in names):
            print(f"  only the Standard report: it has no Page Title, so custom product pages and events can't be "
                  f"told apart (Apple adds the Detailed report when its privacy thresholds are met)")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"KIT/{REPORTS_DIR}/ ignores itself in git (it has its own .gitignore). Next: asc_reports.py growth KIT")
    return 0


def write_table(path, rows):
    cols = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, delimiter="\t", lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    pathlib.Path(path).write_text(buf.getvalue())


def read_table(path):
    p = pathlib.Path(path)
    return parse_table(p.read_text()) if p.exists() else []


# ---------------------------------------------------------------------------------------------------- growth
def window(rows, days):
    """Rows whose Date lies in the last `days` days of the data (by the newest Date present)."""
    dates = sorted({col(r, "Date")[:10] for r in rows if col(r, "Date")})
    if not dates:
        return rows, None, None
    end = dt.date.fromisoformat(dates[-1])
    start = (end - dt.timedelta(days=days - 1)).isoformat()
    first = next(x for x in dates if x >= start)
    return [r for r in rows if col(r, "Date")[:10] >= start], first, end.isoformat()


def _key(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def aggregate(eng, dls):
    """{(page type, page title)} and {source type} → impressions, page views, taps, first-time downloads."""
    pages, sources, label = {}, {}, {}

    def src(r):
        v = col(r, "Source Type") or "Unavailable"
        return label.setdefault(_key(v), v)

    def bucket(d, k):
        return d.setdefault(k, {"impressions": 0.0, "views": 0.0, "unique_views": 0.0, "taps": 0.0,
                                "downloads": 0.0, "reminders": 0.0})
    for r in eng:
        ev, cnt = _key(col(r, "Event")), num(col(r, "Counts"))
        uniq = num(col(r, "Unique Counts")) or cnt
        page = (_key(col(r, "Page Type")), _key(col(r, "Page Title")))
        for b in (bucket(pages, page), bucket(sources, src(r))):
            if ev == "impression":
                b["impressions"] += uniq
            elif ev == "page view":
                b["views"] += cnt
                b["unique_views"] += uniq
            elif ev == "tap":
                b["taps"] += cnt
                if _key(col(r, "Engagement Type")) == "iae reminder":
                    b["reminders"] += cnt
    for r in dls:
        if _key(col(r, "Download Type")) not in ("first-time download", "first time download"):
            continue
        cnt = num(col(r, "Counts"))
        page = (_key(col(r, "Page Type")), _key(col(r, "Page Title")))
        bucket(pages, page)["downloads"] += cnt
        bucket(sources, src(r))["downloads"] += cnt
    return pages, sources


def conv(b):
    v = b["unique_views"] or b["views"]
    return b["downloads"] / v if v else None


def z_below(b, base):
    """One-sided two-proportion z: how sure we are that `b` converts below `base` (positive = below)."""
    n1, n2 = b["unique_views"] or b["views"], base["unique_views"] or base["views"]
    if not n1 or not n2:
        return 0.0
    p1, p2 = min(b["downloads"] / n1, 1), min(base["downloads"] / n2, 1)
    p = min((b["downloads"] + base["downloads"]) / (n1 + n2), 1)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2)) if 0 < p < 1 else 0
    return (p2 - p1) / se if se else 0.0


def judge(b, base):
    if (b["unique_views"] or b["views"]) < MIN_VIEWS or b["downloads"] < MIN_DOWNLOADS:
        return "too small to judge"
    if not base or conv(base) is None:
        return "no default page numbers to compare"
    if conv(b) < conv(base):
        return "BELOW default (90 % sure)" if z_below(b, base) >= Z90 else "below default, not yet clear"
    return "at or above default"


def pct(x):
    return "–" if x is None else f"{x * 100:.1f} %"


def n(x):
    return f"{int(round(x)):,}"


def live_growth(client, app_id):
    """GET only: live custom product pages (name, url, visible) and tests (state, dates) by name."""
    pages = {_key(attrs(p).get("name")): {"id": p["id"], **attrs(p)}
             for p in client.get_all(f"/v1/apps/{app_id}/appCustomProductPages", {"limit": 200})}
    tests = {_key(attrs(t).get("name")): {"id": t["id"], **attrs(t)}
             for t in client.get_all(f"/v1/apps/{app_id}/appStoreVersionExperimentsV2", {"limit": 50})}
    return {"pages": pages, "tests": tests}


def tested_variables(tests):
    """Which of first screenshot / header / icon the growth.yaml tests already cover (by their words)."""
    done = set()
    for t in tests:
        words = " ".join(str(x or "") for x in [t["name"], t.get("hypothesis")] +
                         [y for tr in t["treatments"] for y in (tr["name"], tr.get("hypothesis"))]).lower()
        if any(tr.get("app_icon_name") for tr in t["treatments"]):
            done.add("app icon")
        for var, keys in TEST_ORDER:
            if any(k in words for k in keys):
                done.add(var)
    return done


def next_experiment(g, live, base, flagged):
    """Recommendation text following references/growth-marketing.md §7: one variable per test."""
    L = []
    running = [t for t in g["tests"] if (live or {}).get("tests", {}).get(_key(t["name"]), {}).get("state")
               in ("ACCEPTED", "APPROVED") and live["tests"][_key(t["name"])].get("startDate")
               and not live["tests"][_key(t["name"])].get("endDate")]
    if running:
        t = running[0]
        return [f"Test **{t['name']}** is running. Let it run until a treatment reaches 90 % confidence or 90 days "
                f"(App Analytics › Acquisition › Product Page Optimization), and don't release a new version "
                f"mid-test unless you must. Apply a winner in the browser."]
    views = (base or {}).get("unique_views") or (base or {}).get("views") or 0
    if views < 10 * MIN_VIEWS:
        L.append(f"The default page had {n(views)} unique page views in this window. A test splits that traffic, so "
                 f"it would take months to reach 90 % confidence: grow traffic first (custom product pages for ads "
                 f"and links, keywords), then test.")
    done = tested_variables(g["tests"])
    var = next((v for v, _ in TEST_ORDER if v not in done), None)
    if var:
        icon = " (only with an alternate icon already in the live binary)" if var == "app icon" else ""
        L.append(f"Next test: the **{var}**{icon} of the default product page, and nothing else. One treatment "
                 f"against the original, 30-50 % of traffic, run until 90 % confidence or 90 days. In growth.yaml:")
        slug = re.sub(r"[^a-z0-9]+", "-", var).strip("-")
        L += ["", "```yaml", "experiments:", f"  - id: {slug}-test", f"    name: {var.capitalize()} test",
              "    traffic_proportion: 30", f"    hypothesis: <why a different {var} would convert better>",
              "    treatments:", f"      - id: {slug}-b", f"        name: New {var}", "```"]
    else:
        L.append("First screenshot, header and icon have all been tested: test the next screenshot in the set, "
                 "still one change at a time.")
    for p in flagged:
        L.append(f"Custom product page **{p}** converts below the default page with 90 % confidence. Tests don't "
                 f"run on custom product pages, so change one thing (its first screenshot first), create a new "
                 f"version of the page and compare the next 30 days with these.")
    return L


def cmd_growth(kit, args, live=None):
    kit = pathlib.Path(kit)
    d = kit / REPORTS_DIR
    eng_all, dl_all = read_table(d / "engagement.tsv"), read_table(d / "downloads.tsv")
    if not eng_all and not dl_all:
        print("No reports in KIT/reports/ yet: run `asc_reports.py fetch KIT` (after `request KIT --yes` and 1-2 "
              "days).")
        return 1
    eng, start, end = window(eng_all, args.days)
    dls, s2, e2 = window(dl_all, args.days)
    start = min([x for x in (start, s2) if x] or ["?"])
    end = max([x for x in (end, e2) if x] or ["?"])
    pages, sources = aggregate(eng, dls)
    g = gr.load(kit)
    detailed = any(_key(k) == "page title" for r in eng[:1] + dls[:1] for k in r)
    base = pages.get(("product page", DEFAULT_PAGE))

    L = [f"# Growth results: {start} to {end}", "",
         f"From App Store Connect analytics reports downloaded by `asc_reports.py fetch` (KIT/{REPORTS_DIR}/). "
         f"Page views and impressions are daily unique counts, summed; downloads are first-time downloads; conversion = "
         f"first-time downloads ÷ unique product page views (close to App Analytics' page conversion; "
         f"App Analytics may count differently). Apple adds noise to small numbers for privacy.", ""]
    if not detailed:
        L += ["**Only the Standard reports are here:** they have no Page Title, so the numbers below can't be split "
              "by custom product page or in-app event.", ""]

    # product pages
    L += ["## Product pages", "",
          "| Page | growth.yaml id | Unique page views | First-time downloads | Conversion | vs default |",
          "|---|---|---:|---:|---:|---|"]
    flagged = []
    if base:
        L.append(f"| Default product page | – | {n(base['unique_views'] or base['views'])} | {n(base['downloads'])} | "
                 f"{pct(conv(base))} | baseline |")
    by_name = {_key(p["name"]): p for p in g["pages"]}
    seen = set()
    for (ptype, title), b in sorted(pages.items(), key=lambda kv: -kv[1]["unique_views"]):
        if ptype != "product page" or title in ("", DEFAULT_PAGE, "no page", "null"):
            continue
        seen.add(title)
        p = by_name.get(title)
        verdict = judge(b, base)
        if verdict.startswith("BELOW"):
            flagged.append(p["name"] if p else title)
        lp = ((live or {}).get("pages") or {}).get(title)
        label = (p["name"] if p else title) + (f" ([link]({lp['url']}))" if lp and lp.get("url") else "")
        L.append(f"| {label} | {p['id'] if p else 'not in growth.yaml'} | {n(b['unique_views'] or b['views'])} | "
                 f"{n(b['downloads'])} | {pct(conv(b))} | {verdict} |")
    for key, p in by_name.items():
        if key not in seen:
            L.append(f"| {p['name']} | {p['id']} | 0 | 0 | – | no data (not live yet, under 5 first-time downloads, "
                     f"or only the Standard report) |")
    L += ["", f"Too small to judge: under {MIN_VIEWS} unique page views or under {MIN_DOWNLOADS} first-time "
          f"downloads. \"BELOW default (90 % sure)\" uses a one-sided two-proportion test against the default page.",
          ""]

    # sources
    L += ["## Where visitors came from", "",
          "| Source type | Unique impressions | Unique page views | First-time downloads | Downloads ÷ page views |",
          "|---|---:|---:|---:|---:|"]
    for s, b in sorted(sources.items(), key=lambda kv: -kv[1]["downloads"]):
        L.append(f"| {s} | {n(b['impressions'])} | {n(b['unique_views'] or b['views'])} | "
                 f"{n(b['downloads'])} | {pct(conv(b))} |")
    L.append("")

    # events
    if g["events"]:
        L += ["## In-app events", "", "| Event | Unique page views | Reminders | First-time downloads |", "|---|---:|---:|---:|"]
        for e in g["events"]:
            names = {_key(e["reference_name"])} | {_key(v.get("name")) for v in e["locales"].values()}
            b = {"views": 0.0, "reminders": 0.0, "downloads": 0.0}
            for (ptype, title), x in pages.items():
                if ptype == "in-app event" and title in names:
                    b["views"] += x["unique_views"] or x["views"]
                    b["reminders"] += x["reminders"]
                    b["downloads"] += x["downloads"]
            L.append(f"| {e['reference_name']} ({e['id']}) | {n(b['views'])} | {n(b['reminders'])} | "
                     f"{n(b['downloads'])} |")
        L += ["", "Matched by the event's reference name or any of its localized names (Page Title; which one Apple "
              "writes is UNCONFIRMED).", ""]

    # tests
    if g["tests"]:
        L += ["## Product page optimization", ""]
        for t in g["tests"]:
            lt = ((live or {}).get("tests") or {}).get(_key(t["name"]))
            state = f"{lt.get('state')}, started {lt.get('startDate') or '–'}, ended {lt.get('endDate') or '–'}" \
                if lt else "live state not read (use --live)"
            L.append(f"- **{t['name']}** ({t['id']}, {t['traffic_proportion']} % of traffic): {state}.")
        L += ["", "Test results (conversion per treatment, lift, confidence) are only in App Analytics › Acquisition "
              "› Product Page Optimization: the API has no results endpoint and the analytics reports have no "
              "treatment column (UNCONFIRMED whether a treatment ever shows as a Page Title). Read them there; apply "
              "a winner at 90 % confidence.", ""]

    L += ["## Next experiment", ""] + next_experiment(g, live, base, flagged) + [""]
    # Names and Page Titles come from growth.yaml and Apple's reports: private.yaml values never reach the file.
    pv = cg.private_values(_yaml(kit / "private.yaml"))
    out = kit / RESULTS_MD
    out.write_text(cg.mask("\n".join(L), pv))
    print(cg.mask(f"wrote {out}" + (f"; below the default page: {', '.join(flagged)}" if flagged else ""), pv))
    return 0


# ---------------------------------------------------------------------------------------------------- sales
def summarize_sales(rows, app_apple_id=None, app_sku=None):
    """Units by kind (product type identifier) and proceeds by currency, for this app (its Apple Identifier) and
    its in-app purchases (Parent Identifier = the app's SKU). The report covers every app of the vendor."""
    units, proceeds, other = {}, {}, 0.0
    for r in rows:
        if app_apple_id and col(r, "Apple Identifier") != str(app_apple_id) and \
                not (app_sku and col(r, "Parent Identifier") == app_sku):
            continue
        ptype, u = col(r, "Product Type Identifier").upper(), num(col(r, "Units"))
        kind = next((k for k, ids in PRODUCT_TYPES.items() if ptype in ids), None)
        if kind:
            units[kind] = units.get(kind, 0) + u
        else:
            other += u
        cur = col(r, "Currency of Proceeds")
        if cur:
            proceeds[cur] = proceeds.get(cur, 0) + u * num(col(r, "Developer Proceeds"))
    if other:
        units["other"] = other
    return units, proceeds


def cmd_sales(client, kit, app, args):
    if not str(args.vendor or "").isdigit():
        print("--vendor is your vendor number (App Store Connect › Payments and Financial Reports, top left).")
        return 2
    params = {"filter[frequency]": "DAILY", "filter[reportType]": "SALES", "filter[reportSubType]": "SUMMARY",
              "filter[vendorNumber]": args.vendor, "filter[version]": "1_0", "filter[reportDate]": args.date}
    try:
        raw = raw_get(client, "/v1/salesReports", params, auth=True)
    except ASCError as e:
        if e.status == 404:
            print(f"No sales report for {args.date or 'the latest day'} yet (Apple posts daily reports the next day; "
                  f"a day without sales has no report).")
            return 1
        raise
    rows = parse_table(unzip(raw))
    d = reports_dir(kit) / "sales"
    d.mkdir(exist_ok=True)
    day = col(rows[0], "Begin Date") if rows else (args.date or "latest")
    fname = re.sub(r"[^0-9A-Za-z-]", "-", day)
    (d / f"{fname}.tsv").write_text(unzip(raw))
    units, proceeds = summarize_sales(rows, app.get("id") if app else None, attrs(app).get("sku"))
    print(f"Sales summary {day}" + (f" for {attrs(app).get('name')}" if app else "") + ":")
    for k, v in units.items():
        print(f"  {k}: {n(v)}")
    for cur, v in proceeds.items():
        print(f"  proceeds: {v:,.2f} {cur}")
    if not units:
        print("  no units for this app")
    return 0


# ---------------------------------------------------------------------------------------------------- main
def main(argv=None, client=None, today=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=["request", "fetch", "growth", "sales"])
    ap.add_argument("kit")
    ap.add_argument("--yes", action="store_true", help="request: the owner said yes")
    ap.add_argument("--dry-run", action="store_true", help="request: print the write instead of sending it")
    ap.add_argument("--snapshot", action="store_true", help="request: a ONE_TIME_SNAPSHOT of the history instead")
    ap.add_argument("--days", type=int, default=30, help="fetch/growth: how many days back (default 30)")
    ap.add_argument("--live", action="store_true", help="growth: also read live pages and tests (GET only)")
    ap.add_argument("--vendor", help="sales: your vendor number")
    ap.add_argument("--date", help="sales: YYYY-MM-DD (default: the latest day)")
    ap.add_argument("--key-id")
    ap.add_argument("--issuer-id")
    ap.add_argument("--key-path")
    a = ap.parse_args(argv)
    kit = pathlib.Path(a.kit)
    if a.days < 1:
        print("--days must be 1 or more")
        return 2
    if a.date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.date):
        print("--date is YYYY-MM-DD")
        return 2
    if a.command == "growth" and not a.live:
        return cmd_growth(kit, a)
    bid = bundle_id(kit)
    if not bid:
        print("facts.yaml has no app.bundle_id")
        return 2
    if client is None:
        try:
            client = make_client(a, kit=kit, dry_run=a.dry_run)
        except ConfigError as e:
            print(f"API key: {e}")
            return 2
    client.dry_run = client.dry_run or a.dry_run
    try:
        app = find_app(client, bid)
        if not app:
            print(f"No app with bundle id {bid} in App Store Connect.")
            return 1
        if a.command == "request":
            return cmd_request(client, kit, app, a)
        if a.command == "fetch":
            return cmd_fetch(client, kit, app, a, today=today)
        if a.command == "sales":
            return cmd_sales(client, kit, app, a)
        return cmd_growth(kit, a, live=live_growth(client, app["id"]))
    except ASCError as e:
        hint = " (the key needs the Admin role to request reports; Sales and Reports, Finance or Admin to read)" \
            if e.status == 403 else ""
        print(f"App Store Connect error: {e}{hint}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
