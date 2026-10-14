"""asc_reports.py: analytics report request/fetch, the growth join, and the sales summary. Offline: a fake transport
serves the API and the pre-signed segment URLs from tests/fixtures/reports/."""
import gzip
import hashlib
import json
import pathlib
import urllib.parse

import pytest
import yaml

import asc_reports as ar
from asc_api import ASCError, Client

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "reports"
APP = {"type": "apps", "id": "1234567890", "attributes": {"bundleId": "com.example.swipr", "name": "Swipr",
                                                         "sku": "swipr"}}
GROWTH = {
    "custom_product_pages": [
        {"id": "storage", "name": "Free up storage", "locales": {"en-US": {"promotional_text": "Clear space."}}},
        {"id": "duplicates", "name": "Delete duplicates", "locales": {"en-US": {"promotional_text": "Dupes."}}},
        {"id": "clutter", "name": "Screenshots clutter", "locales": {"en-US": {"promotional_text": "Clutter."}}}],
    "experiments": [{"id": "first-shot", "name": "First screenshot in motion", "traffic_proportion": 30,
                     "treatments": [{"id": "motion", "name": "Mid-swipe first"}]}],
    "in_app_events": [{
        "id": "spring-clean", "reference_name": "Spring clean week", "badge": "challenge",
        "schedule": [{"territories": ["USA"], "event_start": "2027-03-08", "event_end": "2027-03-15"}],
        "locales": {"en-US": {"name": "Spring Clean Week", "short_description": "Clear photos in a week.",
                              "long_description": "Swipe through your library."}}}],
}


class FakeReports:
    """A tiny App Store Connect: report requests, reports, instances, segments, pre-signed files, sales."""

    def __init__(self, requests=None, sales=None):
        self.calls = []
        self.requests = list(requests or [])
        self.reports = {"rep-eng": {"name": "App Store Discovery and Engagement Detailed",
                                    "category": "APP_STORE_ENGAGEMENT"},
                        "rep-eng-std": {"name": "App Store Discovery and Engagement Standard",
                                        "category": "APP_STORE_ENGAGEMENT"},
                        "rep-dl": {"name": "App Store Downloads Detailed", "category": "COMMERCE"},
                        "rep-pre": {"name": "App Store Pre-Order Detailed", "category": "COMMERCE"}}
        self.instances = {"rep-eng": [("i1", "2026-10-10"), ("i2", "2026-10-11"), ("i0", "2026-08-01")],
                          "rep-dl": [("i3", "2026-10-11")]}
        self.segments = {"i1": "engagement-2026-10-10.tsv.gz", "i2": "engagement-2026-10-11.tsv.gz",
                         "i0": "engagement-2026-10-10.tsv.gz", "i3": "downloads-2026-10-11.tsv.gz"}
        self.sales = sales
        self.files = {}

    def _list(self, items):
        return 200, {}, json.dumps({"data": items, "links": {}}).encode()

    def __call__(self, method, url, headers, body):
        u = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        self.calls.append((method, u.netloc, u.path, q, dict(headers)))
        if u.netloc == "files.example":
            assert "Authorization" not in headers, "pre-signed URLs must not carry the JWT"
            return 200, {}, (FIX / u.path.strip("/")).read_bytes()
        p = [x for x in u.path.split("/") if x]
        if method == "GET" and p == ["v1", "apps"]:
            return self._list([APP])
        if p[-1] == "analyticsReportRequests" and method == "GET":
            return self._list(self.requests)
        if p == ["v1", "analyticsReportRequests"] and method == "POST":
            js = json.loads(body)
            new = {"type": "analyticsReportRequests", "id": f"req{len(self.requests) + 1}",
                   "attributes": {"accessType": js["data"]["attributes"]["accessType"],
                                  "stoppedDueToInactivity": False}}
            self.requests.append(new)
            return 201, {}, json.dumps({"data": new}).encode()
        if p[1] == "analyticsReportRequests" and p[-1] == "reports":
            return self._list([{"type": "analyticsReports", "id": k, "attributes": v}
                               for k, v in self.reports.items()])
        if p[1] == "analyticsReports" and p[-1] == "instances":
            assert q.get("filter[granularity]") == "DAILY"
            return self._list([{"type": "analyticsReportInstances", "id": i,
                                "attributes": {"granularity": "DAILY", "processingDate": d}}
                               for i, d in self.instances.get(p[2], [])])
        if p[1] == "analyticsReportInstances" and p[-1] == "segments":
            f = FIX / self.segments[p[2]]
            return self._list([{"type": "analyticsReportSegments", "id": "seg-" + p[2], "attributes": {
                "url": f"https://files.example/{f.name}?sig=abc", "sizeInBytes": f.stat().st_size,
                "checksum": hashlib.md5(f.read_bytes()).hexdigest()}}])
        if p == ["v1", "salesReports"]:
            assert headers.get("Authorization") == "Bearer tok"
            if self.sales is None:
                return 404, {}, json.dumps({"errors": [{"code": "NOT_FOUND", "title": "none"}]}).encode()
            return 200, {"content-type": "application/a-gzip"}, (FIX / self.sales).read_bytes()
        return 404, {}, b'{"errors": [{"code": "NOT_FOUND"}]}'

    def writes(self):
        return [(m, p) for m, _, p, _, _ in self.calls if m != "GET"]


def make_kit(tmp_path, growth=GROWTH):
    kit = tmp_path / "kit"
    kit.mkdir()
    (kit / "facts.yaml").write_text(yaml.safe_dump({"app": {"bundle_id": "com.example.swipr"}}))
    if growth:
        (kit / "growth.yaml").write_text(yaml.safe_dump(growth))
    return kit


def client(fake, dry_run=False):
    return Client(token=lambda: "tok", transport=fake, dry_run=dry_run, sleep=lambda s: None)


ONGOING = {"type": "analyticsReportRequests", "id": "req1",
           "attributes": {"accessType": "ONGOING", "stoppedDueToInactivity": False}}


# ---------------------------------------------------------------------------------------------------- parsing
def test_parse_gzip_tsv_fixture():
    rows = ar.parse_table(ar.unzip((FIX / "engagement-2026-10-11.tsv.gz").read_bytes()))
    assert len(rows) == 6
    assert ar.col(rows[0], "page title") == ""
    assert ar.col(rows[1], "PAGE  TITLE") == "Default product page"
    assert ar.num(ar.col(rows[1], "Unique Counts")) == 1000


def test_parse_plain_and_comma_text():
    assert ar.unzip(b"a\tb\n1\t2\n") == "a\tb\n1\t2\n"
    assert ar.parse_table("Date,Counts\n2026-10-01,5\n") == [{"Date": "2026-10-01", "Counts": "5"}]
    assert ar.parse_table("") == []


def test_latest_instance_wins_per_date():
    old = [("2026-10-10", {"Date": "2026-10-09", "Counts": "999"}),
           ("2026-10-10", {"Date": "2026-10-08", "Counts": "1"})]
    new = [("2026-10-11", {"Date": "2026-10-09", "Counts": "1000"})]
    rows = ar.latest_per_date(old + new)
    assert sorted(r["Counts"] for r in rows) == ["1", "1000"]


# ---------------------------------------------------------------------------------------------------- request
def test_request_needs_yes(tmp_path, capsys):
    kit, fake = make_kit(tmp_path), FakeReports()
    assert ar.main(["request", str(kit)], client=client(fake)) == 2
    assert fake.writes() == []
    assert "--yes" in capsys.readouterr().out


def test_request_dry_run_prints_and_sends_nothing(tmp_path, capsys):
    kit, fake = make_kit(tmp_path), FakeReports()
    assert ar.main(["request", str(kit), "--dry-run"], client=client(fake)) == 0
    assert fake.writes() == []
    out = capsys.readouterr().out
    assert "would send: POST /v1/analyticsReportRequests" in out and '"ONGOING"' in out


def test_request_creates_once_and_rereads(tmp_path, capsys):
    kit, fake = make_kit(tmp_path), FakeReports()
    assert ar.main(["request", str(kit), "--yes"], client=client(fake)) == 0
    assert fake.writes() == [("POST", "/v1/analyticsReportRequests")]
    out = capsys.readouterr().out
    assert "1-2 days" in out
    state = json.loads((kit / "reports" / "request.json").read_text())
    assert state["accessType"] == "ONGOING" and state["id"] == "req1"
    assert (kit / "reports" / ".gitignore").read_text().strip().endswith("*")
    # a second run finds it and writes nothing
    assert ar.main(["request", str(kit), "--yes"], client=client(fake)) == 0
    assert fake.writes() == [("POST", "/v1/analyticsReportRequests")]
    assert "already exists" in capsys.readouterr().out


def test_request_replaces_a_stopped_one(tmp_path, capsys):
    stopped = {"type": "analyticsReportRequests", "id": "old",
               "attributes": {"accessType": "ONGOING", "stoppedDueToInactivity": True}}
    kit, fake = make_kit(tmp_path), FakeReports([stopped])
    assert ar.main(["request", str(kit), "--yes"], client=client(fake)) == 0
    assert "stopped" in capsys.readouterr().out
    assert len(fake.writes()) == 1


def test_snapshot_request(tmp_path):
    kit, fake = make_kit(tmp_path), FakeReports([ONGOING])
    assert ar.main(["request", str(kit), "--snapshot", "--yes"], client=client(fake)) == 0
    assert fake.requests[-1]["attributes"]["accessType"] == "ONE_TIME_SNAPSHOT"


# ---------------------------------------------------------------------------------------------------- fetch
def test_fetch_without_request(tmp_path, capsys):
    kit, fake = make_kit(tmp_path), FakeReports()
    assert ar.main(["fetch", str(kit)], client=client(fake)) == 1
    assert "request KIT --yes" in capsys.readouterr().out


def test_fetch_downloads_merges_and_skips_old(tmp_path, capsys):
    import datetime as dt
    kit, fake = make_kit(tmp_path), FakeReports([ONGOING])
    assert ar.main(["fetch", str(kit), "--days", "30"], client=client(fake), today=dt.date(2026, 10, 12)) == 0
    assert fake.writes() == []
    raw = sorted(p.name for p in (kit / "reports" / "raw").rglob("*.gz"))
    assert raw == ["2026-10-10-seg-i1.gz", "2026-10-11-seg-i2.gz", "2026-10-11-seg-i3.gz"]  # i0 is too old
    eng = ar.read_table(kit / "reports" / "engagement.tsv")
    default_0909 = [r for r in eng if r["Date"] == "2026-10-09" and r["Page Title"] == "Default product page"]
    assert [r["Unique Counts"] for r in default_0909] == ["1000"]   # the newer instance replaced 999
    # only the Detailed engagement report and the downloads report (not Pre-Order) were read
    paths = [p for _, _, p, _, _ in fake.calls]
    assert "/v1/analyticsReports/rep-eng-std/instances" not in paths
    assert "/v1/analyticsReports/rep-pre/instances" not in paths
    assert (kit / "reports" / ".gitignore").exists()
    # a second fetch re-uses the files whose checksum matches
    n = sum(1 for c in fake.calls if c[1] == "files.example")
    assert ar.main(["fetch", str(kit)], client=client(fake), today=dt.date(2026, 10, 12)) == 0
    assert sum(1 for c in fake.calls if c[1] == "files.example") == n


def test_fetch_rejects_bad_checksum(tmp_path, capsys):
    import datetime as dt
    kit, fake = make_kit(tmp_path), FakeReports([ONGOING])
    real = fake.__call__

    def broken(method, url, headers, body):
        status, h, raw = real(method, url, headers, body)
        if "files.example" in url and "downloads" in url:
            raw = gzip.compress(b"Date\tCounts\n")
        return status, h, raw
    c = Client(token=lambda: "tok", transport=broken)
    assert ar.main(["fetch", str(kit)], client=c, today=dt.date(2026, 10, 12)) == 0
    assert "checksum doesn't match" in capsys.readouterr().out
    assert not list((kit / "reports" / "raw").glob("downloads/*.gz"))


def test_pick_reports_prefers_detailed():
    reps = [{"id": "s", "attributes": {"name": "App Store Downloads Standard", "category": "COMMERCE"}},
            {"id": "d", "attributes": {"name": "App Store Downloads Detailed", "category": "COMMERCE"}}]
    assert ar.pick_reports(reps)["downloads"]["id"] == "d"
    assert ar.pick_reports(reps[:1])["downloads"]["id"] == "s"


# ---------------------------------------------------------------------------------------------------- growth
def fetched_kit(tmp_path, growth=GROWTH):
    import datetime as dt
    kit, fake = make_kit(tmp_path, growth), FakeReports([ONGOING])
    assert ar.main(["fetch", str(kit)], client=client(fake), today=dt.date(2026, 10, 12)) == 0
    return kit


def test_growth_needs_reports(tmp_path, capsys):
    kit = make_kit(tmp_path)
    assert ar.main(["growth", str(kit)]) == 1
    assert "fetch" in capsys.readouterr().out


def test_growth_results(tmp_path, capsys):
    kit = fetched_kit(tmp_path)
    assert ar.main(["growth", str(kit)]) == 0
    md = (kit / "GROWTH-RESULTS.md").read_text()
    lines = md.splitlines()
    row = {ln.split("|")[1].strip().split(" (")[0]: ln for ln in lines if ln.startswith("| ")}
    assert "| 2,000 | 400 | 20.0 % | baseline |" in row["Default product page"]
    assert "storage" in row["Free up storage"] and "| 600 | 60 | 10.0 % | BELOW default (90 % sure) |" in \
        row["Free up storage"]
    assert "duplicates" in row["Delete duplicates"] and "too small to judge" in row["Delete duplicates"]
    assert "no data" in row["Screenshots clutter"]
    assert "| Spring clean week (spring-clean) | 80 | 10 | 4 |" in md
    assert "| Web referrer | 0 | 600 | 60 | 10.0 % |" in md
    assert "| App Store search | 4,000 |" in md
    # §7: the test covers the first screenshot, so the next one is the header, one variable only
    nxt = md.split("## Next experiment")[1]
    assert "**header asset**" in nxt and "traffic_proportion: 30" in nxt
    assert "Free up storage" in nxt and "first screenshot" in nxt
    assert "no results endpoint" in md
    assert "Free up storage" in capsys.readouterr().out


def test_growth_window_days(tmp_path):
    kit = fetched_kit(tmp_path)
    assert ar.main(["growth", str(kit), "--days", "1"]) == 0
    md = (kit / "GROWTH-RESULTS.md").read_text()
    assert md.startswith("# Growth results: 2026-10-10 to 2026-10-10")
    assert "Default product page" not in md.split("## Where")[0]
    assert "| Free up storage | storage | 0 | 0 |" in md


def test_growth_low_traffic_and_all_tested(tmp_path):
    g = dict(GROWTH, experiments=[
        {"id": "a", "name": "Screenshot", "traffic_proportion": 30, "treatments": [{"id": "x", "name": "x"}]},
        {"id": "b", "name": "Header", "traffic_proportion": 30, "treatments": [{"id": "y", "name": "y"}]},
        {"id": "c", "name": "Icon", "traffic_proportion": 30,
         "treatments": [{"id": "z", "name": "z", "app_icon_name": "Night"}]}])
    kit = fetched_kit(tmp_path, g)
    assert ar.main(["growth", str(kit)]) == 0
    nxt = (kit / "GROWTH-RESULTS.md").read_text().split("## Next experiment")[1]
    assert "have all been tested" in nxt
    base = {"views": 200, "unique_views": 200, "downloads": 20}
    out = ar.next_experiment({"tests": []}, None, base, [])
    assert "grow traffic first" in out[0] and "first screenshot" in out[1]


def test_growth_running_test_and_live_links(tmp_path):
    kit = fetched_kit(tmp_path)
    live = {"pages": {"free up storage": {"id": "cpp1", "url": "https://apps.apple.com/app/id1?ppid=cpp1"}},
            "tests": {"first screenshot in motion": {"state": "APPROVED", "startDate": "2026-10-01",
                                                     "endDate": None}}}
    args = type("A", (), {"days": 30})()
    assert ar.cmd_growth(kit, args, live=live) == 0
    md = (kit / "GROWTH-RESULTS.md").read_text()
    assert "[link](https://apps.apple.com/app/id1?ppid=cpp1)" in md
    assert "APPROVED, started 2026-10-01" in md
    assert "is running" in md.split("## Next experiment")[1]


def test_judge_thresholds():
    base = {"views": 2000, "unique_views": 2000, "downloads": 400}
    assert ar.judge({"views": 99, "unique_views": 99, "downloads": 50}, base) == "too small to judge"
    assert ar.judge({"views": 500, "unique_views": 500, "downloads": 4}, base) == "too small to judge"
    assert ar.judge({"views": 120, "unique_views": 120, "downloads": 22}, base) == "below default, not yet clear"
    assert ar.judge({"views": 500, "unique_views": 500, "downloads": 150}, base) == "at or above default"


# ---------------------------------------------------------------------------------------------------- sales
def test_sales_summary(tmp_path, capsys):
    kit, fake = make_kit(tmp_path), FakeReports(sales="sales-2026-10-10.tsv.gz")
    assert ar.main(["sales", str(kit), "--vendor", "85000000", "--date", "2026-10-10"], client=client(fake)) == 0
    q = next(c[3] for c in fake.calls if c[2] == "/v1/salesReports")
    assert q == {"filter[frequency]": "DAILY", "filter[reportType]": "SALES", "filter[reportSubType]": "SUMMARY",
                 "filter[vendorNumber]": "85000000", "filter[version]": "1_0", "filter[reportDate]": "2026-10-10"}
    out = capsys.readouterr().out
    assert "downloads: 120" in out and "updates: 40" in out and "in-app purchases: 7" in out
    assert "77" not in out                       # another app of the same vendor
    assert "34.95 USD" in out and "15.00 EUR" in out
    assert list((kit / "reports" / "sales").glob("*.tsv"))
    assert fake.writes() == []


def test_sales_bad_input_and_missing_day(tmp_path, capsys):
    kit, fake = make_kit(tmp_path), FakeReports(sales=None)
    assert ar.main(["sales", str(kit), "--vendor", "abc"], client=client(fake)) == 2
    assert ar.main(["sales", str(kit), "--vendor", "1", "--date", "10/10/2026"], client=client(fake)) == 2
    assert ar.main(["sales", str(kit), "--vendor", "1"], client=client(fake)) == 1
    assert "No sales report" in capsys.readouterr().out


def test_no_app(tmp_path, capsys):
    kit = make_kit(tmp_path)
    (kit / "facts.yaml").write_text(yaml.safe_dump({"app": {"bundle_id": "com.example.other"}}))
    assert ar.main(["fetch", str(kit)], client=client(FakeReports([ONGOING]))) == 1
    assert "No app with bundle id" in capsys.readouterr().out


def test_authenticated_download_refuses_a_base_url_off_apples_api():
    seen = []

    def tr(method, url, headers, body):
        seen.append(headers)
        return 200, {}, b""
    c = Client(token=lambda: "tok", transport=tr, base_url="https://proxy.example")
    with pytest.raises(ASCError, match="token"):
        ar.raw_get(c, "/v1/salesReports", {"filter[vendorNumber]": "1"}, auth=True)
    assert seen == []
    # A pre-signed segment URL still goes without the JWT.
    ar.raw_get(c, "https://cdn.example/segment.gz")
    assert "Authorization" not in seen[0]


def test_default_transport_is_the_redirect_guarded_one():
    import asc_api
    c = Client(token=lambda: "tok")
    assert c.transport is asc_api.urllib_transport
    assert any(isinstance(h, asc_api.AuthRedirectGuard) for h in asc_api._OPENER.handlers)


def test_growth_results_mask_private_values(tmp_path, capsys):
    kit = fetched_kit(tmp_path)
    (kit / "private.yaml").write_text(yaml.safe_dump({"review_contact": {"phone": "+1 555 010 9999"},
                                                      "notes": "Free up storage"}))
    assert ar.main(["growth", str(kit)]) == 0
    md = (kit / "GROWTH-RESULTS.md").read_text()
    out = capsys.readouterr().out
    assert "Free up storage" not in md and "Free up storage" not in out
    assert "[private]" in md
