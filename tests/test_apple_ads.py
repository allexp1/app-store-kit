"""Offline Apple Ads tests against a fake Platform API v1 that enforces the kit's spend rules."""
import copy
import datetime as dt
import json
import re
import shutil
import subprocess
import urllib.parse
from decimal import Decimal

import pytest
import yaml

import apple_ads as aa
import asc_api

TODAY = dt.date.today()
ACCOUNT = "4242"
EXAMPLE = {
    "app": {"adam_id": "1234567890", "name": "Example App"},
    "currency": "USD", "target_cpa": 3.00, "max_bid": 4.00,
    "keywords": {"brand": ["example app"], "category": ["budget planner", "expense tracker"],
                 "competitor": ["other budget"], "negative": ["casino"]},
    "markets": [{"name": "US", "countries": ["US"], "daily_budget": 40}],
}


class FakeAds:
    """Answers the v1 endpoints the kit uses; refuses anything created without status PAUSED (campaigns)."""

    def __init__(self):
        self.calls, self.next_id = [], 1000
        self.campaigns, self.groups, self.keywords, self.negatives, self.ads, self.creatives = {}, {}, {}, {}, {}, {}
        self.account = {"id": int(ACCOUNT), "currency": "USD", "timeZone": "America/New_York",
                        "productFeatures": ["APPSTORE_APP_MANUAL"]}
        self.reports = {"campaigns": {}, "keywords": {}, "searchterms": {}}
        self.fail_on = None
        self.force_status = None

    def new_id(self):
        self.next_id += 1
        return self.next_id

    def __call__(self, method, url, headers, body):
        parts = urllib.parse.urlsplit(url)
        path = parts.path
        data = json.loads(body) if body and headers.get("Content-Type") == "application/json" else None
        self.calls.append((method, path, data, dict(headers)))
        if url == aa.TOKEN_URL:
            form = urllib.parse.parse_qs(body.decode())
            assert form["grant_type"] == ["client_credentials"] and form["scope"] == ["searchadsorg"]
            return 200, {}, json.dumps({"access_token": "tok-1", "expires_in": 3600}).encode()
        assert parts.scheme + "://" + parts.netloc == aa.BASE_URL
        assert headers["Authorization"] == "Bearer tok-1"
        if self.fail_on and self.fail_on == (method, path):
            return 400, {}, json.dumps({"error": {"code": "INVALID", "message": "boom",
                                                  "details": [{"code": "X", "message": "bad field"}]}}).encode()
        if not path.startswith("/v1/ad-accounts"):
            assert headers.get("X-AP-Context") == f"adAccountId={ACCOUNT}"
        result = self.route(method, path, data)
        if isinstance(result, tuple):
            return result
        return 200, {"ratelimit-remaining": "100"}, json.dumps(result).encode()

    def _campaign(self, cid):
        return next((c for k, c in self.campaigns.items() if str(k) == str(cid)), {})

    def query(self, rows, data):
        for f in (data or {}).get("filters", []):
            rows = [r for r in rows if str(r.get(f["field"])) == str(f["value"])]
        return {"result": rows, "pagination": {"totalCount": len(rows)}}

    def bulk(self, store, data, check):
        out = []
        for item in data["items"]:
            d = dict(item["data"])
            check(d)
            if "id" in d:
                store[d["id"]].update(d)
                out.append({"correlationId": item["correlationId"], "success": True, "result": store[d["id"]]})
                continue
            d["id"] = self.new_id()
            store[d["id"]] = d
            out.append({"correlationId": item["correlationId"], "success": True, "result": d})
        return {"result": out}

    def route(self, method, path, data):
        if method == "GET" and path == f"/v1/ad-accounts/{ACCOUNT}":
            return {"result": self.account}
        if path == "/v1/campaigns/query":
            return self.query(list(self.campaigns.values()), data)
        if path == "/v1/adgroups/query":
            return self.query(list(self.groups.values()), data)
        if path == "/v1/keywords/query":
            rows = list(self.keywords.values())
            for f in data.get("filters", []):
                if f["field"] == "campaignId":
                    rows = [k for k in rows if str(self.groups[k["adGroupId"]]["campaignId"]) == str(f["value"])]
                else:
                    rows = [k for k in rows if str(k.get(f["field"])) == str(f["value"])]
            return {"result": rows, "pagination": {"totalCount": len(rows)}}
        if path.startswith("/v1/reports/apps/"):
            kind = path.split("/")[4]
            assert data["timeRange"]["timeZone"] == "ORTZ"
            fields = {f["field"]: f["value"] for f in data.get("filters") or []}
            if kind == "campaigns":   # live API (2026-11-13): campaignId is an unsupported filter here
                if "campaignId" in fields:
                    return 400, {}, json.dumps({"error": {"code": "VALIDATION_ERROR", "message": "INVALID_FIELD_ATTRIBUTE campaignId"}}).encode()
                adam = fields.get("promotedObjectId")
                rows = [r for cid, rs in self.reports[kind].items() for r in rs
                        if adam is None or str(self._campaign(cid).get("promotedObjectId", adam)) == str(adam)]
                return {"result": {"rows": rows}, "pagination": {"totalCount": len(rows)}}
            if "campaignId" not in fields:  # ... and required for keywords and search terms
                return 400, {}, json.dumps({"error": {"code": "VALIDATION_ERROR", "message": "campaignId filter is required"}}).encode()
            return {"result": {"rows": self.reports[kind].get(str(fields["campaignId"]), [])}, "pagination": {"totalCount": 1}}
        if path == "/v1/creatives/query":
            return self.query(list(self.creatives.values()), data)
        if method == "POST" and path == "/v1/creatives":
            assert data["destination"]["parameters"]["adamId"] == "1234567890"
            if data["creativeType"] == "DEFAULT_PRODUCT_PAGE" and any(
                    c["creativeType"] == "DEFAULT_PRODUCT_PAGE" for c in self.creatives.values()):
                return 400, {}, json.dumps({"error": {"code": "VALIDATION_ERROR", "message": "",
                                                      "details": [{"code": "DUPLICATE_DEFAULT_PRODUCT_PAGE"}]}}).encode()
            cid = self.new_id()
            self.creatives[cid] = {**data, "id": cid}
            return {"result": {**data, "id": cid}}
        if method == "POST" and path == "/v1/campaigns":
            assert data["status"] == "PAUSED", "campaigns must be created PAUSED"
            assert "|" not in data["name"], "Apple: INVALID_FORMAT_CAMPAIGN_NAME"
            assert data["adAccountId"] == int(ACCOUNT)
            assert data["bidStrategy"] == {"bidStrategyType": "MANUAL_CPT", "bidStrategyGoal": "TAP"}
            cid = self.new_id()
            self.campaigns[cid] = {**data, "id": cid, "status": self.force_status or data["status"]}
            return {"result": self.campaigns[cid]}
        if path.startswith("/v1/campaigns/"):
            cid = int(path.rsplit("/", 1)[1])
            if method == "PUT":
                self.campaigns[cid].update(data)
            return {"result": self.campaigns[cid]}
        if method == "POST" and path == "/v1/adgroups":
            assert data["campaignId"] in self.campaigns
            assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}", data.get("startTime") or ""), "startTime required"
            gid = self.new_id()
            self.groups[gid] = {**data, "id": gid}
            return {"result": self.groups[gid]}
        if method == "POST" and path == "/v1/ads":
            return 400, {}, json.dumps({"error": {"code": "VALIDATION_ERROR", "message": "",
                                                  "details": [{"code": "AD_CAMPAIGN_SUPPLY_SOURCES_NOT_SUPPORTED"}]}}).encode()
            assert data["adGroupId"] in self.groups and data["creativeId"] in self.creatives
            assert not any(a["adGroupId"] == data["adGroupId"] for a in self.ads.values()), "one ad per ad group"
            aid = self.new_id()
            self.ads[aid] = {**data, "id": aid}
            return {"result": self.ads[aid]}
        if path in ("/v1/keywords/bulk-create", "/v1/keywords/bulk-update"):
            def check(d):
                if "id" in d:
                    assert set(d) <= {"id", "bid", "status"}, "text and match type are immutable"
                else:
                    assert d["adGroupId"] in self.groups and d["matchType"] in ("EXACT", "BROAD")
            return self.bulk(self.keywords, data, check)
        if path == "/v1/negative-keywords/bulk-create":
            def check(d):
                assert ("campaignId" in d) != ("adGroupId" in d) and d["matchType"] == "EXACT"
                assert d["campaignId"] in self.campaigns
            return self.bulk(self.negatives, data, check)
        return 404, {}, json.dumps({"error": {"code": "NOT_FOUND", "message": path}}).encode()


@pytest.fixture
def kit(tmp_path):
    (tmp_path / "apple-ads.yaml").write_text(yaml.safe_dump(EXAMPLE))
    return tmp_path


@pytest.fixture
def fake():
    return FakeAds()


def client_for(fake, dry_run=False):
    return aa.Client(lambda: "tok-1", ACCOUNT, transport=fake, dry_run=dry_run, sleep=lambda s: None, log=lambda *a: None)


def run(kit, fake, *args, dry_run=False):
    return aa.main([args[0], str(kit), *args[1:]], client=client_for(fake, dry_run))


def write_yaml(kit, **changes):
    doc = copy.deepcopy(EXAMPLE)
    doc.update(changes)
    (kit / "apple-ads.yaml").write_text(yaml.safe_dump(doc))


# ------------------------------------------------------------------ validation and structure
def test_example_template_is_valid():
    cfg = aa.validate(yaml.safe_load(open(aa.pathlib.Path(aa.__file__).parent.parent / "templates/apple-ads.example.yaml")))
    campaigns, manual = aa.build_structure(cfg)
    assert [c["theme"] for c in campaigns] == ["brand", "category", "discovery"]   # competitor list is empty
    assert not manual


def test_structure_bids_and_negatives(kit):
    cfg = aa.Kit(kit).config()
    campaigns, _ = aa.build_structure(cfg)
    by = {c["theme"]: c for c in campaigns}
    assert by["brand"]["ad_groups"][0]["bid"] == Decimal("1.80")          # 3.00 x 0.6
    assert by["competitor"]["ad_groups"][0]["bid"] == Decimal("0.75")     # 3.00 x 0.25
    disc = by["discovery"]
    assert [g["name"] for g in disc["ad_groups"]] == ["Broad", "Search Match"]
    assert disc["ad_groups"][1]["search_match"] and not disc["ad_groups"][1]["keywords"]
    assert {n["text"] for n in disc["negatives"]} == {"example app", "budget planner", "expense tracker", "other budget", "casino"}
    assert all(n["match"] == "EXACT" for c in campaigns for n in c["negatives"])
    assert sum(c["daily_budget"] for c in campaigns) == Decimal("40.00")



def test_market_overrides_keywords_target_and_split():
    raw = {**EXAMPLE, "markets": [
        {"name": "US", "countries": ["US"], "daily_budget": 40},
        {"name": "DE", "countries": ["DE", "AT", "CH"], "daily_budget": 2, "target_cpa": 0.50,
         "budget_split": {"category": 1.0},
         "keywords": {"brand": ["opa benny"], "category": ["gutenachtgeschichten"], "negative": ["kostenlos"]}}]}
    cfg = aa.validate(raw)
    campaigns, _ = aa.build_structure(cfg)
    us = [c for c in campaigns if c["market"] == "US"]
    de = [c for c in campaigns if c["market"] == "DE"]
    assert {c["theme"] for c in us} == {"brand", "category", "competitor", "discovery"}   # top level unchanged
    assert [c["theme"] for c in de] == ["category"]                                       # brand share 0: skipped
    assert de[0]["daily_budget"] == Decimal("2.00") and de[0]["countries"] == ["AT", "CH", "DE"]
    assert [k["text"] for k in de[0]["ad_groups"][0]["keywords"]] == ["gutenachtgeschichten"]
    assert de[0]["ad_groups"][0]["bid"] == Decimal("0.20")                                # 0.50 x 0.4, not 3.00 x 0.4
    assert [n["text"] for n in de[0]["negatives"]] == ["kostenlos"]
    assert "budget planner" not in str(de) and "opa benny" not in str(us)


def test_optimize_uses_the_market_target_cpa():
    cfg = aa.validate({**EXAMPLE, "markets": [
        {"name": "US", "countries": ["US"], "daily_budget": 40},
        {"name": "IN", "countries": ["IN"], "daily_budget": 5, "target_cpa": 0.50}]})
    def camp(name, market):
        return {"id": 1 if market == "US" else 2, "name": name, "theme": "category", "market": market, "daily_budget": "5",
                "totals": {"spend": "2", "taps": 10, "installs": 0, "cpa": None}, "search_terms": [],
                "keywords": [{"id": 9, "text": "x", "match": "EXACT", "status": "ENABLED", "spend": "2", "installs": 0,
                              "taps": 10, "cpa": None, "bid": "0.20", "ad_group_id": 7}]}
    rep = {"days": 7, "campaigns": [camp("A - Category - US", "US"), camp("A - Category - IN", "IN")]}
    paused = {p["campaign"] for p in aa.propose(rep, cfg) if p["kind"] == "pause_keyword"}
    assert paused == {"A - Category - IN"}        # 2.00 spent: over 2 x 0.50 in IN, under 2 x 3.00 in US


@pytest.mark.parametrize("market, message", [
    ({"keywords": {"brand": ["x"], "category": ["x"]}}, "markets[0].keywords: 'x'"),
    ({"budget_split": {"category": 0.5}}, "markets[0].budget_split shares"),
    ({"target_cpa": 0}, "markets[0].target_cpa"),
])
def test_market_override_validation(market, message):
    with pytest.raises(aa.AdsError, match=re.escape(message)):
        aa.validate({**EXAMPLE, "markets": [{"name": "US", "countries": ["US"], "daily_budget": 40, **market}]})

@pytest.mark.parametrize("change, message", [
    ({"currency": "usd"}, "currency"),
    ({"markets": [{"name": "FR", "countries": ["FR"], "daily_budget": 10}]}, "Sapin"),
    ({"markets": [{"name": "CN", "countries": ["CN"], "daily_budget": 10}]}, "China"),
    ({"markets": [{"name": "A", "countries": ["US"], "daily_budget": 10}, {"name": "B", "countries": ["US"], "daily_budget": 10}]}, "bid against"),
    ({"budget_split": {"brand": 0.5, "category": 0.6}}, "add up"),
    ({"keywords": {"brand": ["x"], "category": ["x"]}}, "one theme"),
    ({"keywords": {"brand": ["x"], "negative": ["x"]}}, "negative keyword"),
    ({"target_cpa": -1}, "target_cpa"),
    ({"customer_type": "other_apps"}, "other_app_ids"),
    ({"org_id": 1}, "unknown fields"),
    ({"markets": [{"name": "US", "countries": ["US"], "daily_budget": 2}]}, "lower than its daily budget"),
])
def test_validation_refuses(kit, change, message, capsys):
    write_yaml(kit, **change)
    assert aa.main(["check", str(kit)]) == 1
    assert message in capsys.readouterr().out


def test_france_allowed_for_owner_with_sapin_answer(kit, fake):
    write_yaml(kit, owns_app_and_account=True, french_business=False, markets=[{"name": "FR", "countries": ["FR"], "daily_budget": 40}])
    assert run(kit, fake, "plan") == 0
    plan = json.loads((kit / "apple-ads-plan.json").read_text())
    camp = next(o for o in plan["ops"] if o["op"] == "campaign")
    assert camp["body"]["regulationResponses"] == [{"regulationType": "CAMPAIGN_SAPIN_LAW", "responseValue": "NOT_FRENCH_BUSINESS"}]


def test_france_needs_the_french_business_answer(kit, capsys):
    write_yaml(kit, owns_app_and_account=True, markets=[{"name": "FR", "countries": ["FR"], "daily_budget": 40}])
    assert aa.main(["check", str(kit)]) == 1
    assert "french_business" in capsys.readouterr().out


def test_maximize_conversions_is_a_guided_step(kit, fake):
    write_yaml(kit, strategy={"category": "maximize_conversions"})
    assert run(kit, fake, "plan") == 0
    plan = json.loads((kit / "apple-ads-plan.json").read_text())
    assert [x["campaign"] for x in plan["manual_steps"]] == ["Example App - Category - US"]
    assert not any(o["body"]["name"] == "Example App - Category - US" for o in plan["ops"] if o["op"] == "campaign")
    assert "Maximize Conversions" in (kit / "apple-ads-plan.md").read_text()


# ------------------------------------------------------------------ plan / apply
def test_plan_reads_only_and_apply_creates_everything_paused(kit, fake, capsys):
    assert run(kit, fake, "plan") == 0
    assert all(c[0] == "GET" or c[1].endswith("/query") for c in fake.calls)
    md = (kit / "apple-ads-plan.md").read_text()
    assert "40.00 USD a day" in md and "1216.00 USD a month" in md
    assert run(kit, fake, "apply", "--yes") == 0
    assert len(fake.campaigns) == 4 and all(c["status"] == "PAUSED" for c in fake.campaigns.values())
    assert len(fake.groups) == 5 and not fake.ads
    assert len(fake.keywords) == 4 + 4                                     # 4 exact + 4 broad in Discovery
    assert all(k["status"] == "ENABLED" for k in fake.keywords.values())
    live = json.loads((kit / "apple-ads-live.json").read_text())
    assert {c["id"] for c in live["created"]} == set(fake.campaigns)
    assert "all PAUSED" in capsys.readouterr().out


def test_apply_needs_yes_and_a_fresh_plan(kit, fake, capsys):
    assert run(kit, fake, "apply") == 2
    assert run(kit, fake, "apply", "--yes") == 1                           # no plan yet
    assert run(kit, fake, "plan") == 0
    write_yaml(kit, target_cpa=5)
    assert run(kit, fake, "apply", "--yes") == 1
    assert "changed since the plan" in capsys.readouterr().out
    assert not fake.campaigns


def test_apply_refuses_when_account_changed_after_plan(kit, fake, capsys):
    assert run(kit, fake, "plan") == 0
    fake.campaigns[1] = {"id": 1, "name": "Example App - Brand - US", "promotedObjectId": "1234567890", "status": "PAUSED",
                         "dailyBudget": {"value": {"amount": "6", "currency": "USD"}}}
    assert run(kit, fake, "apply", "--yes") == 1
    assert "account changed" in capsys.readouterr().out
    assert len(fake.campaigns) == 1


def test_plan_is_idempotent_by_name(kit, fake):
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "apply", "--yes") == 0
    assert run(kit, fake, "plan") == 0
    plan = json.loads((kit / "apple-ads-plan.json").read_text())
    assert plan["campaigns"] == [] and not plan["ops"]
    assert "left untouched" in plan["warnings"][-1]


def test_dry_run_sends_no_writes(kit, fake, capsys):
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "apply", "--yes", "--dry-run", dry_run=True) == 0
    assert not fake.campaigns and not fake.keywords
    assert "would send POST /v1/campaigns" in capsys.readouterr().out


def test_campaign_that_comes_back_enabled_is_paused_again(kit, fake, capsys):
    assert run(kit, fake, "plan") == 0
    fake.force_status = "ENABLED"
    assert run(kit, fake, "apply", "--yes") == 1
    assert [c["status"] for c in fake.campaigns.values()] == ["PAUSED"]
    assert "paused again" in capsys.readouterr().out


def test_api_error_is_reported_with_details(kit, fake, capsys):
    assert run(kit, fake, "plan") == 0
    fake.fail_on = ("POST", "/v1/adgroups")
    assert run(kit, fake, "apply", "--yes") == 1
    out = capsys.readouterr().out
    assert "HTTP 400" in out and "bad field" in out
    assert "Already created, all PAUSED" in out and "Example App - Brand - US" in out


# ------------------------------------------------------------------ activate / pause
def test_activate_only_kit_campaigns_with_yes(kit, fake, capsys):
    run(kit, fake, "plan")
    run(kit, fake, "apply", "--yes")
    cid = str(next(iter(fake.campaigns)))
    assert run(kit, fake, "activate", "--campaign", cid) == 2
    assert run(kit, fake, "activate", "--campaign", cid, "--yes") == 0
    assert fake.campaigns[int(cid)]["status"] == "ENABLED"
    assert "a month" in capsys.readouterr().out
    fake.campaigns[7] = {"id": 7, "name": "Hand made", "promotedObjectId": "1234567890", "status": "PAUSED",
                         "dailyBudget": {"value": {"amount": "5", "currency": "USD"}}}
    assert run(kit, fake, "activate", "--campaign", "7", "--yes") == 1
    fake.campaigns[8] = {"id": 8, "name": "Other app", "promotedObjectId": "999999", "status": "ENABLED"}
    assert run(kit, fake, "pause", "--campaign", "8", "--yes") == 1
    assert fake.campaigns[8]["status"] == "ENABLED"
    assert run(kit, fake, "pause", "--campaign", cid, "--yes") == 0
    assert fake.campaigns[int(cid)]["status"] == "PAUSED"


# ------------------------------------------------------------------ report / optimise
def kw_row(k, spend, taps, installs, impressions=1000):
    return {"metadata": {"id": k["id"], "text": k["text"], "matchType": k["matchType"], "adGroupId": k["adGroupId"],
                         "status": "ENABLED"},
            "totalMetrics": {"localSpend": {"amount": str(spend), "currency": "USD"}, "impressions": impressions,
                             "taps": taps, "tapInstalls": installs}}


def seed_reports(fake):
    by_name = {c["name"]: c["id"] for c in fake.campaigns.values()}
    kws = {k["text"] + "/" + k["matchType"]: k for k in fake.keywords.values()}
    cat, disc = by_name["Example App - Category - US"], by_name["Example App - Discovery - US"]
    fake.reports["keywords"][str(cat)] = [kw_row(kws["budget planner/EXACT"], 30, 60, 20),     # CPA 1.50: raise
                                          kw_row(kws["expense tracker/EXACT"], 9, 20, 0)]       # 9 > 2 x 3: pause
    fake.reports["campaigns"][str(cat)] = [{"metadata": {"id": cat},
                                            "totalMetrics": {"localSpend": {"amount": "39", "currency": "USD"},
                                                             "impressions": 2000, "taps": 80, "tapInstalls": 20}}]
    fake.reports["searchterms"][str(disc)] = [
        {"metadata": {"searchTermText": "money planner", "searchTermSource": "AUTO"},
         "totalMetrics": {"localSpend": {"amount": "4", "currency": "USD"}, "taps": 5, "tapInstalls": 3}},
        {"metadata": {"searchTermText": "free stuff", "searchTermSource": "AUTO"},
         "totalMetrics": {"localSpend": {"amount": "8", "currency": "USD"}, "taps": 9, "tapInstalls": 0}},
        # the same term in both Discovery ad groups: 0 installs in one, 3 in the other → judged together, no negative
        {"metadata": {"searchTermText": "Split Term", "searchTermSource": "AUTO"},
         "totalMetrics": {"localSpend": {"amount": "7", "currency": "USD"}, "taps": 9, "tapInstalls": 0}},
        {"metadata": {"searchTermText": "split term", "searchTermSource": "TARGETED"},
         "totalMetrics": {"localSpend": {"amount": "2", "currency": "USD"}, "taps": 4, "tapInstalls": 3}}]
    return cat, disc, kws


def test_optimize_proposes_and_changes_nothing(kit, fake):
    run(kit, fake, "plan")
    run(kit, fake, "apply", "--yes")
    seed_reports(fake)
    before = copy.deepcopy((fake.campaigns, fake.keywords, fake.negatives))
    n = len(fake.calls)
    assert run(kit, fake, "optimize", "--days", "1") == 0
    assert all(c[0] == "GET" or c[1].endswith("/query") for c in fake.calls[n:])
    assert (fake.campaigns, fake.keywords, fake.negatives) == before
    doc = json.loads((kit / "apple-ads-proposals.json").read_text())
    kinds = {(p["kind"], p.get("keyword") or p.get("term")) for p in doc["proposals"]}
    assert ("set_bid", "budget planner") in kinds and ("pause_keyword", "expense tracker") in kinds
    assert ("harvest", "money planner") in kinds and ("add_negative", "free stuff") in kinds
    assert ("set_budget", None) in kinds
    assert ("add_negative", "Split Term") not in kinds
    assert [p["term"] for p in doc["proposals"] if p["kind"] == "harvest"] == ["money planner", "Split Term"]
    assert len({p["id"] for p in doc["proposals"]}) == len(doc["proposals"])
    assert all(p["approve"] is False for p in doc["proposals"])
    bid = next(p for p in doc["proposals"] if p["kind"] == "set_bid")
    assert (bid["from"], bid["to"]) == ("1.20", "1.38")
    assert "Nothing has been changed" in (kit / "apple-ads-proposals.md").read_text()
    assert "Example App - Category - US" in (kit / "apple-ads-report.json").read_text()


def test_report_reads_campaign_totals_without_a_campaign_filter(kit, fake):
    """Live 2026-11-13: the campaigns report refuses a campaignId filter; totals come from one per-app query."""
    run(kit, fake, "plan")
    run(kit, fake, "apply", "--yes")
    cat, disc, _ = seed_reports(fake)
    n = len(fake.calls)
    assert run(kit, fake, "report", "--days", "4") == 0
    camp_calls = [c for c in fake.calls[n:] if c[1] == "/v1/reports/apps/campaigns/query"]
    assert len(camp_calls) == 1
    assert {f["field"] for f in camp_calls[0][2]["filters"]} == {"promotedObjectId"}
    rep = json.loads((kit / "apple-ads-report.json").read_text())
    totals = {c["id"]: c["totals"] for c in rep["campaigns"]}
    assert totals[cat] == {"impressions": 2000, "taps": 80, "installs": 20, "spend": "39.00", "cpa": "1.95"}
    assert totals[disc]["spend"] == "0.00" and totals[disc]["installs"] == 0


def test_bids_never_exceed_max_bid(kit, fake):
    run(kit, fake, "plan")
    run(kit, fake, "apply", "--yes")
    _, _, kws = seed_reports(fake)
    fake.keywords[kws["budget planner/EXACT"]["id"]]["bid"] = {"amount": "3.90", "currency": "USD"}
    run(kit, fake, "optimize", "--days", "1")
    doc = json.loads((kit / "apple-ads-proposals.json").read_text())
    assert all(Decimal(p["to"]) <= Decimal("4.00") for p in doc["proposals"] if p["kind"] == "set_bid")


def test_apply_proposals_only_approved_and_rechecked(kit, fake, capsys):
    run(kit, fake, "plan")
    run(kit, fake, "apply", "--yes")
    cat, disc, kws = seed_reports(fake)
    run(kit, fake, "optimize", "--days", "1")
    path = kit / "apple-ads-proposals.json"
    doc = json.loads(path.read_text())
    assert run(kit, fake, "apply-proposals", "--yes") == 0
    assert "nothing to do" in capsys.readouterr().out
    for p in doc["proposals"]:
        p["approve"] = p["kind"] in ("set_bid", "harvest", "add_negative")
    path.write_text(json.dumps(doc))
    assert run(kit, fake, "apply-proposals") == 2
    assert run(kit, fake, "apply-proposals", "--yes") == 0
    assert fake.keywords[kws["budget planner/EXACT"]["id"]]["bid"]["amount"] == "1.38"
    assert fake.keywords[kws["expense tracker/EXACT"]["id"]].get("status") == "ENABLED"   # pause was not approved
    harvested = [k for k in fake.keywords.values() if k["text"] == "money planner"]
    assert len(harvested) == 1 and harvested[0]["matchType"] == "EXACT"
    assert fake.groups[harvested[0]["adGroupId"]]["campaignId"] == cat
    assert {n["text"] for n in fake.negatives.values() if n["campaignId"] == disc} >= {"money planner", "free stuff"}
    budget = fake.campaigns[cat]["dailyBudget"]["value"]["amount"]
    assert budget == "14.00"                                                              # budget not approved


def test_apply_proposals_skips_stale_bid(kit, fake, capsys):
    run(kit, fake, "plan")
    run(kit, fake, "apply", "--yes")
    _, _, kws = seed_reports(fake)
    run(kit, fake, "optimize", "--days", "1")
    path = kit / "apple-ads-proposals.json"
    doc = json.loads(path.read_text())
    for p in doc["proposals"]:
        p["approve"] = p["kind"] == "set_bid"
    path.write_text(json.dumps(doc))
    fake.keywords[kws["budget planner/EXACT"]["id"]]["bid"] = {"amount": "2.00", "currency": "USD"}
    assert run(kit, fake, "apply-proposals", "--yes") == 0
    assert "skipped" in capsys.readouterr().out
    assert fake.keywords[kws["budget planner/EXACT"]["id"]]["bid"]["amount"] == "2.00"


# ------------------------------------------------------------------ auth + transport safety
def test_client_refuses_other_origins(fake):
    c = client_for(fake)
    with pytest.raises(aa.AdsError):
        c.request("GET", "@evil.example/v1/me")


def test_retry_after_on_429(fake):
    calls = []

    def transport(method, url, headers, body):
        calls.append(url)
        if len(calls) == 1:
            return 429, {"Retry-After": "3"}, b""
        return 200, {}, b'{"result": {"id": 1}}'
    waits = []
    c = aa.Client(lambda: "t", ACCOUNT, transport=transport, sleep=waits.append, log=lambda *a: None)
    assert c.get("/v1/me", scoped=False) == {"id": 1}
    assert waits == [3.0]


def test_post_is_not_retried_on_server_error():
    calls = []

    def transport(method, url, headers, body):
        calls.append(method)
        return 503, {}, b""
    c = aa.Client(lambda: "t", ACCOUNT, transport=transport, sleep=lambda s: None, log=lambda *a: None)
    with pytest.raises(aa.ApiError):
        c.post("/v1/campaigns", {"name": "x"})
    assert calls == ["POST"]


def test_access_token_is_cached_and_hidden(fake):
    creds = aa.Credentials("SEARCHADS.abc", "SEARCHADS.abc", "key1", aa.pathlib.Path("/nonexistent"), ACCOUNT)
    now = [1000.0]
    token = aa.AccessToken(creds, fake, now=lambda: now[0], secret=lambda c: "jwt")
    assert token() == "tok-1" and token() == "tok-1"
    assert sum(1 for c in fake.calls if c[1] == "/auth/oauth2/token") == 1
    now[0] += 3600
    token()
    assert sum(1 for c in fake.calls if c[1] == "/auth/oauth2/token") == 2
    assert "tok-1" not in repr(token)


def test_refused_credentials_are_a_config_error():
    creds = aa.Credentials("a", "b", "c", aa.pathlib.Path("/x"), ACCOUNT)
    token = aa.AccessToken(creds, lambda *a: (400, {}, b'{"error": "invalid_client"}'), secret=lambda c: "jwt")
    with pytest.raises(asc_api.ConfigError, match="invalid_client"):
        token()


@pytest.mark.skipif(not shutil.which("openssl"), reason="openssl not installed")
def test_client_secret_claims(tmp_path):
    key = tmp_path / "private-key.pem"
    subprocess.run(["openssl", "ecparam", "-genkey", "-name", "prime256v1", "-noout", "-out", str(key)], check=True)
    creds = aa.Credentials("SEARCHADS.client", "SEARCHADS.team", "kid-1", key, ACCOUNT)
    jwt = aa.client_secret(creds, now=1_700_000_000)
    head, body, sig = jwt.split(".")
    pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
    import base64
    header = json.loads(base64.urlsafe_b64decode(pad(head)))
    claims = json.loads(base64.urlsafe_b64decode(pad(body)))
    assert header == {"alg": "ES256", "kid": "kid-1"}
    assert claims["iss"] == "SEARCHADS.team" and claims["sub"] == "SEARCHADS.client"
    assert claims["aud"] == "https://appleid.apple.com"
    assert claims["exp"] - claims["iat"] < 180 * 86400
    assert len(base64.urlsafe_b64decode(pad(sig))) == 64


def test_credentials_from_env_and_missing(tmp_path):
    key = tmp_path / "k.pem"
    key.write_text("x")
    env = {"APPLE_ADS_CLIENT_ID": "c", "APPLE_ADS_TEAM_ID": "t", "APPLE_ADS_KEY_ID": "k",
           "APPLE_ADS_KEY_PATH": str(key), "APPLE_ADS_AD_ACCOUNT_ID": ACCOUNT}
    assert aa.resolve_credentials(tmp_path, env).ad_account_id == ACCOUNT
    with pytest.raises(asc_api.ConfigError, match="ad_account_id"):
        aa.resolve_credentials(tmp_path, {k: v for k, v in env.items() if k != "APPLE_ADS_AD_ACCOUNT_ID"})


def test_currency_mismatch_stops_plan(kit, fake, capsys):
    fake.account["currency"] = "EUR"
    assert run(kit, fake, "plan") == 1
    assert "pays in EUR" in capsys.readouterr().out


def test_harvest_is_judged_per_market():
    cfg = aa.validate({**EXAMPLE, "markets": [{"name": "US", "countries": ["US"], "daily_budget": 40},
                                              {"name": "UK", "countries": ["GB"], "daily_budget": 40}]})
    zero = {"impressions": 0, "taps": 0, "installs": 0, "spend": "0.00", "cpa": None}
    def camp(cid, theme, market, keywords=(), terms=()):
        return {"id": cid, "name": f"Example App - {theme.capitalize()} - {market}", "status": "ENABLED", "daily_budget": "10",
                "theme": theme, "market": market, "totals": zero, "keywords": list(keywords), "search_terms": list(terms)}
    harvested = {"id": 1, "text": "money planner", "match": "EXACT", "ad_group_id": 9, "status": "ENABLED", "bid": None, **zero}
    term = {"text": "money planner", "source": "AUTO", "spend": "4.00", "installs": 3, "cpa": "1.33", "taps": 5}
    rep = {"days": 7, "campaigns": [camp(10, "category", "US", [harvested]), camp(20, "category", "UK"),
                                   camp(11, "discovery", "US", terms=[term]), camp(21, "discovery", "UK", terms=[term])]}
    harvests = [p for p in aa.propose(rep, cfg) if p["kind"] == "harvest"]
    assert [p["to_campaign_id"] for p in harvests] == [20]


def approve(kit, kinds):
    path = kit / "apple-ads-proposals.json"
    doc = json.loads(path.read_text())
    for p in doc["proposals"]:
        p["approve"] = p["kind"] in kinds
    path.write_text(json.dumps(doc))


def test_harvest_waits_while_its_destination_is_paused(kit, fake, capsys):
    run(kit, fake, "plan")
    run(kit, fake, "apply", "--yes")
    cat, disc, _ = seed_reports(fake)
    fake.campaigns[disc]["status"] = "ENABLED"                     # Discovery runs, Category still paused
    run(kit, fake, "optimize", "--days", "1")
    approve(kit, {"harvest"})
    assert run(kit, fake, "apply-proposals", "--yes") == 0
    assert "is paused" in capsys.readouterr().out
    assert not [n for n in fake.negatives.values() if n["text"] == "money planner"]
    assert not [k for k in fake.keywords.values() if k["text"] == "money planner"]


def test_harvest_resumes_after_a_failed_step_without_duplicates(kit, fake, capsys):
    run(kit, fake, "plan")
    run(kit, fake, "apply", "--yes")
    seed_reports(fake)
    run(kit, fake, "optimize", "--days", "1")
    approve(kit, {"harvest", "set_bid"})
    fake.fail_on = ("POST", "/v1/negative-keywords/bulk-create")
    assert run(kit, fake, "apply-proposals", "--yes") == 1
    fake.fail_on = None
    bid_calls = sum(1 for c in fake.calls if c[1] == "/v1/keywords/bulk-update")
    assert run(kit, fake, "apply-proposals", "--yes") == 0
    assert len([k for k in fake.keywords.values() if k["text"] == "money planner"]) == 1
    assert len([n for n in fake.negatives.values() if n["text"] == "money planner"]) == 1
    assert sum(1 for c in fake.calls if c[1] == "/v1/keywords/bulk-update") == bid_calls   # the bid change ran once
    assert run(kit, fake, "apply-proposals", "--yes") == 0
    assert "nothing to do" in capsys.readouterr().out


def test_harvest_will_not_negate_when_the_exact_keyword_is_paused(kit, fake, capsys):
    run(kit, fake, "plan")
    run(kit, fake, "apply", "--yes")
    cat, _, _ = seed_reports(fake)
    run(kit, fake, "optimize", "--days", "1")
    approve(kit, {"harvest"})
    group = next(g for g in fake.groups.values() if g["campaignId"] == cat and g["name"] == "Exact")
    fake.keywords[1] = {"id": 1, "adGroupId": group["id"], "text": "Money Planner", "matchType": "EXACT", "status": "PAUSED"}
    assert run(kit, fake, "apply-proposals", "--yes") == 0
    assert "but paused" in capsys.readouterr().out
    assert not [n for n in fake.negatives.values() if n["text"] == "money planner"]
    assert len([k for k in fake.keywords.values() if k["text"].lower() == "money planner"]) == 1


def test_search_results_campaigns_get_no_creatives_or_ads(kit, fake):
    assert run(kit, fake, "plan") == 0
    plan = json.loads((kit / "apple-ads-plan.json").read_text())
    assert {o["op"] for o in plan["ops"]} == {"campaign", "adgroup", "keywords", "negatives"}
    write_yaml(kit, custom_product_pages={"category": "abc-123"})
    assert run(kit, fake, "plan") == 0
    assert "Apple Ads website" in " ".join(json.loads((kit / "apple-ads-plan.json").read_text())["warnings"])


def test_half_built_campaign_is_finished_by_the_next_plan(kit, fake, capsys):
    assert run(kit, fake, "plan") == 0
    fake.fail_on = ("POST", "/v1/adgroups")
    assert run(kit, fake, "apply", "--yes") == 1
    assert len(fake.campaigns) == 1 and not fake.groups and fake.negatives          # campaign + its negatives exist
    fake.fail_on = None
    assert run(kit, fake, "plan") == 0
    plan = json.loads((kit / "apple-ads-plan.json").read_text())
    assert "Finishing" in " ".join(plan["warnings"])
    assert run(kit, fake, "apply", "--yes") == 0
    assert len(fake.campaigns) == 4 and len(fake.groups) == 5 and not fake.ads
    texts = [(n["campaignId"], n["text"]) for n in fake.negatives.values()]
    assert len(texts) == len(set(texts))                                           # negatives not repeated
    assert run(kit, fake, "plan") == 0
    assert not json.loads((kit / "apple-ads-plan.json").read_text())["ops"]
