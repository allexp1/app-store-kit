"""Offline subscription contracts and safety gates; no credentials or network."""
import copy
import json
import pathlib
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

import asc_api
import subscriptions as s


class FakeSubscriptions:
    """Strict v1 routes; deliberately rejects DELETE and unknown request attributes."""
    ATTRS = {
        "subscriptionGroups": {"referenceName"},
        "subscriptions": {"name", "productId", "subscriptionPeriod", "groupLevel", "familySharable", "reviewNote"},
        "subscriptionGroupLocalizations": {"name", "locale", "customAppName"},
        "subscriptionLocalizations": {"name", "locale", "description"},
        "subscriptionPrices": {"startDate", "preserveCurrentPrice"},
        "subscriptionIntroductoryOffers": {"duration", "offerMode", "numberOfPeriods", "startDate", "endDate"},
        "subscriptionPromotionalOffers": {"duration", "offerMode", "numberOfPeriods", "name", "offerCode"},
        "subscriptionAppStoreReviewScreenshots": {"fileName", "fileSize", "uploaded", "sourceFileChecksum"},
        "subscriptionSubmissions": set(),
    }
    CHILD = {("apps", "subscriptionGroups"): ("subscriptionGroups", "app"),
             ("subscriptionGroups", "subscriptionGroupLocalizations"): ("subscriptionGroupLocalizations", "subscriptionGroup"),
             ("subscriptionGroups", "subscriptions"): ("subscriptions", "group"),
             ("subscriptions", "subscriptionLocalizations"): ("subscriptionLocalizations", "subscription"),
             ("subscriptions", "prices"): ("subscriptionPrices", "subscription"),
             ("subscriptions", "introductoryOffers"): ("subscriptionIntroductoryOffers", "subscription"),
             ("subscriptions", "promotionalOffers"): ("subscriptionPromotionalOffers", "subscription"),
             ("subscriptions", "appStoreReviewScreenshot"): ("subscriptionAppStoreReviewScreenshots", "subscription"),
             ("subscriptions", "pricePoints"): ("subscriptionPricePoints", "subscription"),
             ("subscriptionPromotionalOffers", "prices"): ("subscriptionPromotionalOfferPrices", "subscriptionPromotionalOffer")}

    def __init__(self):
        self.rows, self.calls, self.n = {}, [], 0
        self.equal = {}
        self.fail_after = None
        self.corrupt = False
        self.add("apps", {"bundleId": "com.example.app"}, rid="app")
        self.client = asc_api.Client(transport=self, max_retries=0)

    def add(self, typ, values=None, rels=None, rid=None):
        self.n += 1
        rid = rid or str(self.n)
        self.rows[rid] = s.body(typ, values or {}, rels or {}, rid)["data"]
        return self.rows[rid]

    def writes(self):
        return [c for c in self.calls if c[0] != "GET"]

    def wire(self, result):
        result = copy.deepcopy(result)
        for row in result if isinstance(result, list) else [result]:
            if row and row["type"] == "subscriptionPrices":
                row["attributes"].pop("preserveCurrentPrice", None)
                row["attributes"].setdefault("preserved", False)
                row["relationships"].pop("subscription", None)
        return result

    def __call__(self, method, url, headers, data):
        parsed = urlsplit(url)
        path, q = parsed.path, {k: v[0] for k, v in parse_qs(parsed.query).items()}
        if parsed.hostname == "upload.example":
            assert "Authorization" not in headers
            self.calls.append((method, "upload", data))
            return 200, {}, b""
        request = json.loads(data) if data else None
        self.calls.append((method, path, request))
        assert path.startswith("/v1/"), path
        assert method != "DELETE"
        parts = path.split("/")[2:]
        typ = parts[0]
        if method == "GET":
            if len(parts) == 1:
                assert typ == "apps"
                rows = [r for r in self.rows.values() if r["type"] == typ and
                        s.attrs(r).get("bundleId") == q.get("filter[bundleId]")]
                result = rows
            elif len(parts) == 2:
                assert typ != "subscriptionPrices", "Price verification must read the subscription's collection"
                result = self.rows.get(parts[1])
                if result:
                    assert result["type"] == typ
            elif parts[0] == "subscriptionPricePoints" and parts[2] == "equalizations":
                result = self.equal.get(parts[1], [])
            else:
                child, parent = self.CHILD[(typ, parts[2])]
                result = [r for r in self.rows.values() if r["type"] == child and s.rel_id(r, parent) == parts[1]]
                if "filter[territory]" in q:
                    result = [r for r in result if s.rel_id(r, "territory") == q["filter[territory]"]]
                if parts[2] == "appStoreReviewScreenshot":
                    result = result[0] if result else None
            return 200, {}, json.dumps({"data": self.wire(result), "links": {}}).encode()
        assert typ in self.ATTRS
        if self.fail_after is not None and len(self.writes()) > self.fail_after:
            return 500, {}, b'{"errors":[{"code":"TEST_FAILURE"}]}'
        d = request["data"]
        assert d["type"] == typ
        assert set(d.get("attributes", {})) <= self.ATTRS[typ]
        if typ == "subscriptions" and method == "POST":
            assert s.rel_id(d, "group")
        if typ == "subscriptionSubmissions":
            assert s.rel_id(d, "subscription")
            self.rows[s.rel_id(d, "subscription")]["attributes"]["state"] = "WAITING_FOR_REVIEW"
        if method == "POST":
            row = self.add(typ, d.get("attributes"), {k: v["data"] for k, v in d.get("relationships", {}).items()})
            if typ == "subscriptions":
                row["attributes"]["state"] = "MISSING_METADATA"
            if typ == "subscriptionAppStoreReviewScreenshots":
                row["attributes"]["uploadOperations"] = [{"method": "PUT", "url": "https://upload.example/image",
                                                           "offset": 0, "length": s.attrs(row)["fileSize"]}]
            for inc in request.get("included", []):
                rels = {k: v["data"] for k, v in inc["relationships"].items()}
                rels["subscriptionPromotionalOffer"] = s.ref(typ, row["id"])
                self.add(inc["type"], rels=rels)
        else:
            assert method == "PATCH"
            row = self.rows[parts[1]]
            row["attributes"].update(d.get("attributes", {}))
            if row["attributes"].get("uploaded"):
                row["attributes"]["assetDeliveryState"] = {"state": "COMPLETE"}
        if self.corrupt:
            row["attributes"]["name"] = "mismatch"
        return 201 if method == "POST" else 200, {}, json.dumps({"data": self.wire(row)}).encode()

    def seed(self, config, state="APPROVED"):
        group = config["groups"][0]
        sub = group["subscriptions"][0]
        g = self.add("subscriptionGroups", {"referenceName": group["reference_name"]}, {"app": s.ref("apps", "app")})
        for locale, loc in group["localizations"].items():
            values = {"locale": locale, "name": loc["name"]}
            if "custom_app_name" in loc:
                values["customAppName"] = loc["custom_app_name"]
            self.add("subscriptionGroupLocalizations", values, {"subscriptionGroup": s.ref(g["type"], g["id"])})
        values = {"productId": sub["product_id"], "name": sub["reference_name"], "subscriptionPeriod": sub["duration"],
                  "groupLevel": sub["group_level"], "state": state}
        for source, target in (("family_sharing", "familySharable"), ("review_note", "reviewNote")):
            if source in sub:
                values[target] = sub[source]
        row = self.add("subscriptions", values, {"group": s.ref(g["type"], g["id"])})
        for locale, loc in sub["localizations"].items():
            self.add("subscriptionLocalizations", {"locale": locale, **loc}, {"subscription": s.ref(row["type"], row["id"])})
        point = self.price_point(row["id"], "USA", "4.99")
        self.add("subscriptionPrices", {"startDate": None, "preserveCurrentPrice": True},
                 {"subscription": s.ref("subscriptions", row["id"]), "territory": s.ref("territories", "USA"),
                  "subscriptionPricePoint": s.ref("subscriptionPricePoints", point["id"])})
        return row

    def price_point(self, sid, territory, amount):
        return self.add("subscriptionPricePoints", {"customerPrice": amount},
                        {"subscription": s.ref("subscriptions", sid), "territory": s.ref("territories", territory)})


@pytest.fixture
def kit(tmp_path):
    config = {"groups": [{"reference_name": "Premium", "localizations": {"en-US": {"name": "Premium"}},
                           "subscriptions": [{"product_id": "com.example.month", "reference_name": "Monthly",
                                              "duration": "ONE_MONTH", "group_level": 1, "family_sharing": False,
                                              "review_note": "Open Settings, then Upgrade.",
                                              "localizations": {"en-US": {"name": "Monthly Premium", "description": "All features"}},
                                              "prices": {"USA": "4.99"}}]}]}
    (tmp_path / "subscriptions.yaml").write_text(yaml.safe_dump(config))
    (tmp_path / "facts.yaml").write_text("app:\n  bundle_id: com.example.app\n")
    return s.Kit(tmp_path)


def save(kit):
    (kit.path / "subscriptions.yaml").write_text(yaml.safe_dump(kit.config))


def sub(kit):
    return kit.config["groups"][0]["subscriptions"][0]


def run(kit, fake, command, *flags):
    return s.main([command, str(kit.path), *flags], client=fake.client)


def test_check_offline_without_key(kit, monkeypatch):
    monkeypatch.setattr(asc_api, "make_client", lambda *a, **k: pytest.fail("offline check touched auth"))
    assert s.main(["check", str(kit.path)]) == 0


@pytest.mark.parametrize("key,value", [("duration", "MONTHLY"), ("group_level", 0), ("group_level", 101),
                                      ("group_level", True), ("family_sharing", "yes"), ("product_id", "bad id"),
                                      ("reference_name", "x" * 65), ("review_note", "x" * 4001),
                                      ("offer_codes", []), ("prices", {"US": 2}), ("prices", {"USA": "NaN"})])
def test_bad_fields(kit, key, value):
    sub(kit)[key] = value
    assert s.check(kit)


@pytest.mark.parametrize("key,limit", [("name", 30), ("description", 55)])
def test_localized_limits(kit, key, limit):
    sub(kit)["localizations"]["en-US"][key] = "é" * limit
    assert not s.check(kit)
    sub(kit)["localizations"]["en-US"][key] += "é"
    assert s.check(kit)


def test_duplicate_ids_and_tied_levels(kit):
    other = copy.deepcopy(sub(kit))
    kit.config["groups"][0]["subscriptions"].append(other)
    assert s.check(kit)
    other["product_id"] = "com.example.year"
    assert not s.check(kit)


def test_screenshot_outside_kit(kit, tmp_path):
    sub(kit)["review_screenshot"] = "../outside.png"
    assert s.check(kit)


@pytest.mark.parametrize("command", ["apply", "submit"])
def test_gate_before_client(kit, command, monkeypatch):
    monkeypatch.setattr(asc_api, "make_client", lambda *a, **k: pytest.fail("gate touched auth"))
    assert s.main([command, str(kit.path)]) == 2


def test_plan_get_only_creation_and_staged_pricing(kit):
    fake = FakeSubscriptions()
    assert run(kit, fake, "plan") == 0
    plan = json.loads((kit.path / "subscriptions-plan.json").read_text())
    assert not fake.writes()
    assert plan["deferred"]
    assert len(plan["operations"]) == 4
    assert run(kit, fake, "apply", "--yes") == 0
    assert len(fake.writes()) == 4
    assert all(fake.calls[i + 1][0] == "GET" for i, c in enumerate(fake.calls[:-1]) if c[0] == "POST")
    progress = yaml.safe_load((kit.path / "connect-progress.yaml").read_text())
    assert progress["steps"]["subscriptions/sub/0/0"]["live"]["id"]
    assert all(x[0] != "DELETE" for x in fake.calls)


def test_dry_run_prints_requests_no_writes_or_progress(kit, capsys):
    fake = FakeSubscriptions()
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "apply", "--dry-run") == 0
    assert not fake.writes()
    assert not (kit.path / "connect-progress.yaml").exists()
    assert 'would send:' in capsys.readouterr().out
    assert len(fake.client.recorded) == 4


@pytest.mark.parametrize("change", ["kit", "live", "plan", "screenshot"])
def test_stale_plan_refused_before_write(kit, change):
    fake = FakeSubscriptions()
    row = fake.seed(kit.config)
    if change == "screenshot":
        (kit.path / "review.png").write_bytes(b"first")
        sub(kit)["review_screenshot"] = "review.png"
        save(kit)
    assert run(kit, fake, "plan") == 0
    if change == "kit":
        sub(kit)["reference_name"] = "Edited"
        save(kit)
    elif change == "live":
        row["attributes"]["name"] = "Other editor"
    elif change == "plan":
        path = kit.path / "subscriptions-plan.json"
        data = json.loads(path.read_text()); data["app_id"] = "wrong"
        path.write_text(json.dumps(data))
    else:
        (kit.path / "review.png").write_bytes(b"other")
    assert run(kit, fake, "apply", "--yes") == 1
    assert not fake.writes()


def test_replay_rejected_and_replan_no_duplicates(kit):
    fake = FakeSubscriptions()
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "apply", "--yes") == 0
    writes = len(fake.writes())
    row = next(r for r in fake.rows.values() if r["type"] == "subscriptions")
    fake.price_point(row["id"], "USA", "4.99")
    assert run(kit, fake, "apply", "--yes") == 1
    assert len(fake.writes()) == writes
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "apply", "--yes") == 0
    assert len(fake.writes()) == writes + 1
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "apply", "--yes") == 0
    assert len(fake.writes()) == writes + 1


def test_partial_failure_requires_replan(kit):
    fake = FakeSubscriptions()
    fake.fail_after = 1
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "apply", "--yes") == 1
    fake.fail_after = None
    writes = len(fake.writes())
    assert run(kit, fake, "apply", "--yes") == 1
    assert len(fake.writes()) == writes
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "apply", "--yes") == 0
    assert sum(r["type"] == "subscriptionGroups" for r in fake.rows.values()) == 1


@pytest.mark.parametrize("preserve,flag,expected", [(False, False, 1), (False, True, 0), (True, False, 0)])
def test_existing_subscriber_increase_gate(kit, preserve, flag, expected, capsys):
    fake = FakeSubscriptions()
    row = fake.seed(kit.config)
    fake.price_point(row["id"], "USA", "9.99")
    sub(kit).pop("prices")
    sub(kit)["pricing"] = {"base_territory": "USA", "price": "9.99", "preserve_current_price": preserve}
    save(kit)
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "apply", "--yes", *(["--price-increase-ok"] if flag else [])) == expected
    if expected:
        assert not fake.writes()
        assert "subscriber consent" in capsys.readouterr().out


def test_equalization_plans_exact_territories(kit):
    fake = FakeSubscriptions()
    row = fake.seed(kit.config)
    base = fake.price_point(row["id"], "USA", "9.99")
    gb = fake.price_point(row["id"], "GBR", "8.99")
    fake.equal[base["id"]] = [gb]
    sub(kit).pop("prices")
    sub(kit)["pricing"] = {"base_territory": "USA", "price": "9.99", "equalize": True}
    save(kit)
    assert run(kit, fake, "plan") == 0
    plan = json.loads((kit.path / "subscriptions-plan.json").read_text())
    assert {s.rel_id(o["body"]["data"], "territory") for o in plan["operations"]} == {"USA", "GBR"}
    assert not fake.writes()
    assert run(kit, fake, "apply", "--yes") == 0


def test_first_subscription_refused_even_with_existing_app(kit, capsys):
    fake = FakeSubscriptions()
    fake.seed(kit.config, "READY_TO_SUBMIT")
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "submit", "--yes") == 1
    assert not fake.writes()
    out = capsys.readouterr().out
    assert "from the subscription's own page (Add for Review), together with a new app version" in out
    assert "In-App Purchases and Subscriptions section on the version page, use that" in out


def later(kit, fake):
    row = fake.seed(kit.config, "READY_TO_SUBMIT")
    fake.add("subscriptions", {"productId": "unrelated.approved", "state": "APPROVED"},
             {"group": s.ref("subscriptionGroups", s.rel_id(row, "group"))})
    return row


def test_later_submit_exact_id_and_reread(kit):
    fake = FakeSubscriptions()
    row = later(kit, fake)
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "submit", "--yes") == 0
    assert len(fake.writes()) == 1
    method, path, request = fake.writes()[0]
    assert path == "/v1/subscriptionSubmissions"
    assert s.rel_id(request["data"], "subscription") == row["id"]
    assert fake.calls[-1][:2] == ("GET", "/v1/subscriptions/" + row["id"])
    assert run(kit, fake, "submit", "--yes") == 1
    assert len(fake.writes()) == 1


def test_submit_dry_run(kit):
    fake = FakeSubscriptions(); later(kit, fake)
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "submit", "--dry-run") == 0
    assert not fake.writes()
    assert fake.client.recorded[0]["path"] == "/v1/subscriptionSubmissions"


def test_submit_refuses_pending_changes(kit):
    fake = FakeSubscriptions(); row = later(kit, fake)
    row["attributes"]["name"] = "old"
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "submit", "--yes") == 1
    assert not fake.writes()


def test_screenshot_reserve_upload_commit_verify(kit):
    fake = FakeSubscriptions(); fake.seed(kit.config)
    (kit.path / "review.png").write_bytes(b"fake screenshot")
    sub(kit)["review_screenshot"] = "review.png"; save(kit)
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "apply", "--yes") == 0
    assert [c[0] for c in fake.writes()] == ["POST", "PUT", "PATCH"]
    assert run(kit, fake, "plan") == 0
    assert not json.loads((kit.path / "subscriptions-plan.json").read_text())["operations"]
    (kit.path / "review.png").write_bytes(b"other screenshot")
    assert run(kit, fake, "plan") == 1
    count = len(fake.writes())
    assert run(kit, fake, "apply", "--yes") == 1
    assert len(fake.writes()) == count


def test_offers_create_idempotent_and_conflicting_offer_blocks(kit):
    fake = FakeSubscriptions(); row = fake.seed(kit.config)
    fake.price_point(row["id"], "USA", "1.99")
    sub(kit)["introductory_offers"] = [{"territory": "USA", "mode": "FREE_TRIAL", "duration": "ONE_WEEK", "periods": 1}]
    sub(kit)["promotional_offers"] = [{"name": "Welcome back", "offer_code": "welcome", "mode": "PAY_UP_FRONT",
                                       "duration": "ONE_MONTH", "periods": 1, "prices": {"USA": "1.99"}}]
    save(kit)
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "apply", "--yes") == 0
    assert {c[1] for c in fake.writes()} == {"/v1/subscriptionIntroductoryOffers", "/v1/subscriptionPromotionalOffers"}
    assert run(kit, fake, "plan") == 0
    assert not json.loads((kit.path / "subscriptions-plan.json").read_text())["operations"]
    sub(kit)["promotional_offers"][0]["name"] = "Changed"; save(kit)
    assert run(kit, fake, "plan") == 1
    assert run(kit, fake, "apply", "--yes") == 1
    assert len(fake.writes()) == 2


def test_family_sharing_irreversible(kit):
    fake = FakeSubscriptions(); row = fake.seed(kit.config)
    row["attributes"]["familySharable"] = True
    assert run(kit, fake, "plan") == 1
    assert run(kit, fake, "apply", "--yes") == 1
    assert not fake.writes()


def test_status_is_read_only(kit):
    fake = FakeSubscriptions(); fake.seed(kit.config)
    assert run(kit, fake, "status") == 0
    assert not fake.writes()
    assert (kit.path / "subscriptions-live.json").exists()


def test_private_values_masked_before_serialization(kit, capsys):
    secret = 'pass"\\<word>'
    (kit.path / "private.yaml").write_text(yaml.safe_dump({"demo": {"password": secret}}))
    sub(kit)["review_note"] = secret; save(kit)
    fake = FakeSubscriptions()
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "apply", "--dry-run") == 0
    for path in kit.path.glob("subscriptions-plan.*"):
        output = path.read_text()
        assert secret not in output and json.dumps(secret)[1:-1] not in output
        assert "[private]" in output
    output = capsys.readouterr().out
    assert secret not in output and json.dumps(secret)[1:-1] not in output


def test_re_read_mismatch_not_recorded_done(kit):
    fake = FakeSubscriptions(); row = fake.seed(kit.config)
    row["attributes"]["name"] = "before"
    assert run(kit, fake, "plan") == 0
    fake.corrupt = True
    assert run(kit, fake, "apply", "--yes") == 1
    assert not (kit.path / "connect-progress.yaml").exists()


def test_app_id_cross_check(kit):
    (kit.path / "connect.yaml").write_text("api:\n  app_id: app\n")
    fake = FakeSubscriptions(); fake.rows["app"]["attributes"]["bundleId"] = "wrong"
    assert run(kit, fake, "plan") == 1
    assert not fake.writes()


@pytest.mark.parametrize("key,value", [("duration", []), ("promotional_offers", None), ("introductory_offers", "bad"),
                                      ("localizations", []), ("pricing", []), ("review_screenshot", 12)])
def test_malformed_yaml_fields_report_errors(kit, key, value):
    sub(kit)[key] = value
    assert s.check(kit)


def test_example_passes_check(tmp_path):
    example = pathlib.Path(s.__file__).resolve().parent.parent / "templates/subscriptions.example.yaml"
    (tmp_path / "subscriptions.yaml").write_text(example.read_text())
    assert not s.check(s.Kit(tmp_path))


def test_price_request_option_not_read_attribute_and_replay_noop(kit):
    fake = FakeSubscriptions(); row = fake.seed(kit.config)
    fake.price_point(row["id"], "USA", "9.99")
    sub(kit).pop("prices")
    sub(kit)["pricing"] = {"base_territory": "USA", "price": "9.99", "preserve_current_price": False,
                            "start_date": "2030-01-01"}
    save(kit)
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "apply", "--yes", "--price-increase-ok") == 0
    assert fake.calls[-1][:2] == ("GET", f"/v1/subscriptions/{row['id']}/prices")
    assert run(kit, fake, "plan") == 0
    assert not json.loads((kit.path / "subscriptions-plan.json").read_text())["operations"]
    assert run(kit, fake, "apply", "--yes") == 0
    assert len(fake.writes()) == 1


def test_missing_preserved_cohort_still_requires_increase_acknowledgement(kit):
    fake = FakeSubscriptions(); fake.seed(kit.config)
    sub(kit).pop("prices")
    sub(kit)["pricing"] = {"base_territory": "USA", "price": "4.99", "preserve_current_price": False}
    save(kit)
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "apply", "--yes") == 1
    assert not fake.writes()


def test_preserved_price_does_not_hide_current_retail_change(kit):
    fake = FakeSubscriptions(); row = fake.seed(kit.config)
    old = next(r for r in fake.rows.values() if r["type"] == "subscriptionPrices")
    old["attributes"]["preserved"] = True
    point = fake.price_point(row["id"], "USA", "9.99")
    fake.add("subscriptionPrices", {"startDate": None, "preserved": False},
             {"subscription": s.ref("subscriptions", row["id"]), "territory": s.ref("territories", "USA"),
              "subscriptionPricePoint": s.ref("subscriptionPricePoints", point["id"])})
    assert run(kit, fake, "plan") == 0
    ops = json.loads((kit.path / "subscriptions-plan.json").read_text())["operations"]
    assert len(ops) == 1 and ops[0]["path"] == "/v1/subscriptionPrices"


def test_malformed_offer_rules(kit):
    sub(kit)["introductory_offers"] = [{"territory": "USA", "mode": "FREE_TRIAL", "duration": [],
                                        "periods": 3, "price": "1.00", "start_date": "2030-02-01",
                                        "end_date": "2030-01-01"}]
    errors = s.check(kit)
    assert len(errors) >= 4


def test_existing_progress_preserved_and_compatible_status(kit):
    (kit.path / "connect-progress.yaml").write_text("steps:\n  existing:\n    status: todo\n")
    fake = FakeSubscriptions(); fake.seed(kit.config)
    sub(kit)["reference_name"] = "New reference"; save(kit)
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "apply", "--yes") == 0
    progress = yaml.safe_load((kit.path / "connect-progress.yaml").read_text())
    assert progress["steps"]["existing"]["status"] == "todo"
    assert progress["steps"]["subscriptions/sub/0/0"]["status"] in s.cg.STATUSES


def test_screenshot_dry_run_never_uploads(kit, capsys):
    fake = FakeSubscriptions(); fake.seed(kit.config)
    (kit.path / "review.png").write_bytes(b"fake image")
    sub(kit)["review_screenshot"] = "review.png"; save(kit)
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "apply", "--dry-run") == 0
    assert not fake.writes()
    assert [r["method"] for r in fake.client.recorded] == ["POST", "PUT", "PATCH"]
    assert "sourceFileChecksum" in capsys.readouterr().out


def test_offer_codes_are_browser_only(kit):
    fake = FakeSubscriptions(); fake.seed(kit.config)
    sub(kit)["offer_codes"] = "browser"; save(kit)
    assert run(kit, fake, "plan") == 0
    plan = json.loads((kit.path / "subscriptions-plan.json").read_text())
    assert not plan["operations"] and any("offer codes" in warning for warning in plan["warnings"])
    assert run(kit, fake, "apply", "--yes") == 0
    assert not fake.writes()


def test_submit_reports_missing_metadata(kit, capsys):
    fake = FakeSubscriptions(); row = later(kit, fake)
    row["attributes"]["state"] = "MISSING_METADATA"
    assert run(kit, fake, "plan") == 0
    assert run(kit, fake, "submit", "--yes") == 1
    assert not fake.writes()
    assert "MISSING_METADATA" in capsys.readouterr().out
