"""Offline pricing tests with a version-strict JSON:API transport."""
import copy
import datetime as dt
import json
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

import asc_api
import pricing


def resource(kind, rid, attributes=None, relationships=None):
    return {"type": kind, "id": rid, "attributes": attributes or {}, "relationships": relationships or {}}


class PricingASC:
    """Reject unexpected versions/paths and validate the writable payload fields."""
    def __init__(self):
        self.calls = []
        self.app = resource("apps", "app1", {"bundleId": "com.example.app"})
        self.territories = [resource("territories", c, {"currency": currency})
                            for c, currency in (("USA", "USD"), ("GBR", "GBP"), ("JPN", "JPY"))]
        self.points = {}
        for c, amounts in (("USA", ("0.00", "0.99", "1.99")), ("GBR", ("0.00", "0.79", "1.79")),
                           ("JPN", ("0", "100", "200"))):
            self.points[c] = [resource("appPricePoints", f"opaque-{c}-{n}",
                                      {"customerPrice": amount, "proceeds": str(float(amount) * .7)},
                                      {"territory": pricing.link("territories", c)}) for n, amount in enumerate(amounts)]
        self.schedule = resource("appPriceSchedules", "schedule1", relationships={"baseTerritory": pricing.link("territories", "USA")})
        self.prices = []
        self.availability = resource("appAvailabilities", "availability1", {"availableInNewTerritories": True})
        self.available = {c: resource("territoryAvailabilities", "availability-" + c,
                                     {"available": True, "preOrderEnabled": False, "releaseDate": None, "contentStatuses": []},
                                     {"territory": pricing.link("territories", c)}) for c in self.points}
        self.versions = [resource("appStoreVersions", "version1", {"appVersionState": "PREPARE_FOR_SUBMISSION"})]
        self.fail = None
        self.ignore_writes = False
        self.paginate = False
        self.set_prices([{"point": self.points["USA"][0], "start": None, "end": None}])

    def set_prices(self, manual):
        self.prices = []
        for i, entry in enumerate(manual):
            point = entry["point"]
            self.prices.append(self.price_row(point, True, entry["start"], entry["end"], f"manual-{i}"))
        base = pricing.rel_id(self.schedule, "baseTerritory")
        base_phases = [r for r in self.prices if pricing.rel_id(r, "territory") == base]
        for r in base_phases:
            pid = pricing.rel_id(r, "appPricePoint")
            index = next(i for i, p in enumerate(self.points[base]) if p["id"] == pid)
            for code in self.points:
                if any(pricing.rel_id(m, "territory") == code and pricing.attrs(m)["startDate"] == pricing.attrs(r)["startDate"] for m in self.prices):
                    continue
                self.prices.append(self.price_row(self.points[code][index], False,
                    pricing.attrs(r)["startDate"], pricing.attrs(r)["endDate"], f"auto-{r['id']}-{code}"))

    def price_row(self, point, manual, start, end, rid):
        return resource("appPrices", rid, {"manual": manual, "startDate": start, "endDate": end},
                        {"territory": point["relationships"]["territory"], "appPricePoint": pricing.link("appPricePoints", point["id"])})

    def point(self, pid):
        return next(p for points in self.points.values() for p in points if p["id"] == pid)

    @property
    def writes(self):
        return [c for c in self.calls if c[0] != "GET"]

    def __call__(self, method, url, headers, body):
        assert "Authorization" not in headers
        u = urlsplit(url)
        query = {k: v[0] for k, v in parse_qs(u.query).items()}
        payload = json.loads(body) if body else None
        self.calls.append((method, u.path, query, payload))
        if self.fail == (method, u.path):
            return 409, {}, json.dumps({"errors": [{"code": "TEST_FAILURE"}]}).encode()
        if method == "GET":
            doc = self.get(u.path, query)
        else:
            doc = self.write(method, u.path, payload)
        return 200, {}, json.dumps(doc).encode()

    def get(self, path, q):
        if path == "/v1/apps":
            return {"data": [self.app] if q["filter[bundleId]"] == "com.example.app" else []}
        if path == "/v1/apps/app1":
            return {"data": self.app}
        if path == "/v1/territories":
            return {"data": self.territories}
        if path == "/v1/apps/app1/appStoreVersions":
            return {"data": self.versions}
        if path == "/v1/apps/app1/appPriceSchedule":
            return {"data": self.schedule}
        if path == "/v1/apps/app1/appAvailabilityV2":
            return {"data": self.availability}
        if path == "/v2/appAvailabilities/availability1/territoryAvailabilities":
            assert q["include"] == "territory"
            return {"data": list(self.available.values())}
        if path == "/v1/apps/app1/appPricePoints":
            code = q["filter[territory]"]
            rows = self.points[code]
            if self.paginate and not q.get("cursor"):
                return {"data": rows[:1], "links": {"next": f"https://api.appstoreconnect.apple.com{path}?filter[territory]={code}&cursor=next"}}
            return {"data": rows[1:] if self.paginate else rows}
        if path.startswith("/v3/appPricePoints/"):
            pid = path.split("/")[3]
            if path.endswith("/equalizations"):
                index = next(i for points in self.points.values() for i, p in enumerate(points) if p["id"] == pid)
                return {"data": [points[index] for points in self.points.values()]}
            return {"data": self.point(pid)}
        if path in ("/v1/appPriceSchedules/schedule1/manualPrices", "/v1/appPriceSchedules/schedule1/automaticPrices"):
            assert q["include"] == "appPricePoint,territory"
            rows = [p for p in self.prices if pricing.attrs(p)["manual"] == path.endswith("/manualPrices")]
            return {"data": rows, "included": [self.point(pricing.rel_id(p, "appPricePoint")) for p in rows]}
        raise AssertionError("Unexpected GET " + path)

    def write(self, method, path, payload):
        data = payload["data"]
        if method == "POST" and path == "/v1/appPriceSchedules":
            assert data["type"] == "appPriceSchedules"
            assert set(data["relationships"]) == {"app", "baseTerritory", "manualPrices"}
            assert pricing.rel_id(data, "app") == "app1"
            assert data["relationships"]["manualPrices"]["data"] == [{"type": p["type"], "id": p["id"]} for p in payload["included"]]
            manual = []
            for row in payload["included"]:
                assert row["type"] == "appPrices" and row["id"].startswith("$")
                assert set(row["attributes"]) == {"startDate", "endDate"}
                assert set(row["relationships"]) == {"appPricePoint"}
                manual.append({"point": self.point(pricing.rel_id(row, "appPricePoint")),
                               "start": row["attributes"]["startDate"], "end": row["attributes"]["endDate"]})
            if not self.ignore_writes:
                self.schedule = resource("appPriceSchedules", "schedule1", relationships={"baseTerritory": data["relationships"]["baseTerritory"]})
                self.set_prices(manual)
            return {"data": self.schedule}
        if method == "POST" and path == "/v2/appAvailabilities":
            assert data["type"] == "appAvailabilities"
            assert set(data["attributes"]) == {"availableInNewTerritories"}
            assert set(data["relationships"]) == {"app", "territoryAvailabilities"}
            assert data["relationships"]["territoryAvailabilities"]["data"] == [{"type": p["type"], "id": p["id"]} for p in payload["included"]]
            rows = {}
            for row in payload["included"]:
                assert set(row["attributes"]) <= {"available", "preOrderEnabled", "releaseDate"}
                code = pricing.rel_id(row, "territory")
                rows[code] = resource("territoryAvailabilities", "availability-" + code,
                    {"preOrderEnabled": False, "releaseDate": None, "contentStatuses": [], **row["attributes"]}, row["relationships"])
            if not self.ignore_writes:
                self.availability = resource("appAvailabilities", "availability1", data["attributes"])
                self.available = rows
            return {"data": self.availability}
        if method == "PATCH" and path.startswith("/v1/territoryAvailabilities/"):
            assert data["type"] == "territoryAvailabilities" and data["id"] == path.split("/")[-1]
            assert set(data["attributes"]) <= {"available", "preOrderEnabled", "releaseDate"}
            row = next(r for r in self.available.values() if r["id"] == data["id"])
            if not self.ignore_writes:
                row["attributes"].update(data["attributes"])
            return {"data": row}
        raise AssertionError("Unexpected write " + method + " " + path)


@pytest.fixture
def env(tmp_path):
    config = {"base_territory": "USA", "customer_price": "0.99", "manual_overrides": {},
              "territories": "all", "new_territories_auto_available": True, "pre_order": {"enabled": False}}
    (tmp_path / "pricing.yaml").write_text(yaml.safe_dump(config))
    (tmp_path / "facts.yaml").write_text("app:\n  bundle_id: com.example.app\n")
    fake = PricingASC()
    return tmp_path, config, fake, asc_api.Client(transport=fake)


def put(env, **updates):
    path, config, _, _ = env
    config.update(updates)
    (path / "pricing.yaml").write_text(yaml.safe_dump(config))


def run(env, command, *flags):
    return pricing.main([command, str(env[0]), *flags], client=env[3])


def saved(env):
    return json.loads((env[0] / "pricing-plan.json").read_text())


def test_check_offline_no_client_creation(env, monkeypatch):
    monkeypatch.setattr(asc_api, "make_client", lambda *a, **k: pytest.fail("must stay offline"))
    assert pricing.main(["check", str(env[0])]) == 0
    assert not env[2].calls


@pytest.mark.parametrize("dry", [[], ["--dry-run"]])
def test_apply_requires_yes_before_config_or_client(tmp_path, dry):
    assert pricing.main(["apply", str(tmp_path), *dry]) == 2


def test_plan_reads_only_customer_price_and_proceeds(env):
    assert run(env, "plan") == 0
    assert not env[2].writes
    text = (env[0] / "pricing-plan.md").read_text()
    assert "0.99 USD" in text and "proceeds" in text and "→" in text
    assert "0.79 GBP" in text and "100 JPY" in text
    op = saved(env)["requests"][0]
    assert pricing.rel_id(op["json"]["included"][0], "appPricePoint") == "opaque-USA-1"


def test_exact_point_pagination(env):
    env[2].paginate = True
    assert run(env, "plan") == 0
    assert any(c[2].get("cursor") == "next" for c in env[2].calls)


def test_missing_exact_point_fails_without_guessing(env, capsys):
    put(env, customer_price="0.98")
    assert run(env, "plan") == 1
    assert "no exact API price points" in capsys.readouterr().out
    assert not (env[0] / "pricing-plan.json").exists()
    assert not env[2].writes


def test_ambiguous_point_fails(env):
    env[2].points["USA"].append(copy.deepcopy(env[2].points["USA"][1]))
    assert run(env, "plan") == 1


def test_zero_exact_and_noop(env):
    put(env, customer_price="0")
    assert run(env, "plan") == 0
    assert saved(env)["requests"] == []
    assert run(env, "apply", "--yes") == 0
    assert not env[2].writes


def test_overrides_and_scheduled_price(env):
    future = (dt.date.today() + dt.timedelta(days=15)).isoformat()
    put(env, manual_overrides={"GBR": "1.79"}, scheduled_change={"start_date": future, "customer_price": "1.99"})
    assert run(env, "plan") == 0
    rows = saved(env)["requests"][0]["json"]["included"]
    assert len(rows) == 4
    assert {r["attributes"]["startDate"] for r in rows} == {None, future}
    assert {r["attributes"]["endDate"] for r in rows} == {None, future}
    assert run(env, "apply", "--yes") == 0


@pytest.mark.parametrize("value,removed", [(["USA"], ["GBR", "JPN"]), ({"all-except": ["GBR"]}, ["GBR"]), ([], ["GBR", "JPN", "USA"])])
def test_territory_removal_gate_and_apply(env, value, removed, capsys):
    put(env, territories=value)
    assert run(env, "plan") == 0
    assert saved(env)["removed_territories"] == removed
    assert run(env, "apply", "--yes") == 2
    assert not env[2].writes
    assert "Live customers in removed territories lose the listing" in capsys.readouterr().out
    assert run(env, "apply", "--yes", "--remove-territories-ok") == 0
    assert all(not env[2].available[c]["attributes"]["available"] for c in removed)


def test_apply_dry_run_prints_without_writes_or_progress(env, capsys):
    assert run(env, "plan") == 0
    assert run(env, "apply", "--yes", "--dry-run") == 0
    assert "would send: POST /v1/appPriceSchedules" in capsys.readouterr().out
    assert not env[2].writes
    assert not (env[0] / "connect-progress.yaml").exists()


def test_removal_dry_run_still_requires_acknowledgement(env):
    put(env, territories=["USA"])
    assert run(env, "plan") == 0
    assert run(env, "apply", "--yes", "--dry-run") == 2
    assert not env[2].writes


def test_apply_rereads_after_every_write_and_records_progress(env):
    put(env, new_territories_auto_available=False)
    assert run(env, "plan") == 0
    assert run(env, "apply", "--yes") == 0
    calls = env[2].calls
    for i, call in enumerate(calls):
        if call[0] != "GET":
            assert calls[i + 1][0] == "GET"
    progress = yaml.safe_load((env[0] / "connect-progress.yaml").read_text())
    assert progress["steps"]["pricing/storefront-api"]["live"]["Base territory"] == "USA"
    writes = len(env[2].writes)
    assert run(env, "apply", "--yes") == 0
    assert len(env[2].writes) == writes


def test_create_initial_schedule_and_availability(env):
    env[2].schedule = env[2].availability = None
    env[2].available = {}
    assert run(env, "plan") == 0
    assert run(env, "apply", "--yes") == 0
    assert len(env[2].writes) == 2


def test_changed_input_rejected(env):
    assert run(env, "plan") == 0
    put(env, customer_price="1.99")
    assert run(env, "apply", "--yes") == 1
    assert not env[2].writes


def test_changed_live_rejected(env):
    assert run(env, "plan") == 0
    env[2].available["USA"]["attributes"]["available"] = False
    assert run(env, "apply", "--yes") == 1
    assert not env[2].writes


def test_tampered_request_rejected(env):
    assert run(env, "plan") == 0
    plan = saved(env)
    plan["requests"][0]["path"] = "/v1/apps/app1"
    (env[0] / "pricing-plan.json").write_text(json.dumps(plan))
    assert run(env, "apply", "--yes") == 1
    assert not env[2].writes


def test_changed_api_price_point_rejected(env):
    assert run(env, "plan") == 0
    env[2].points["USA"][1]["attributes"]["proceeds"] = "0.50"
    assert run(env, "apply", "--yes") == 1
    assert not env[2].writes


def test_partial_failure_requires_replan(env):
    put(env, new_territories_auto_available=False)
    assert run(env, "plan") == 0
    env[2].fail = ("POST", "/v2/appAvailabilities")
    assert run(env, "apply", "--yes") == 1
    assert yaml.safe_load((env[0] / "connect-progress.yaml").read_text())["steps"]["pricing/storefront-api"]["status"] == "todo"
    assert (env[0] / "pricing-live.json").exists()
    writes = len(env[2].writes)
    assert run(env, "apply", "--yes") == 1
    assert len(env[2].writes) == writes
    env[2].fail = None
    assert run(env, "plan") == 0
    assert len(saved(env)["requests"]) == 1
    assert run(env, "apply", "--yes") == 0


def test_reread_mismatch_does_not_mark_done(env):
    assert run(env, "plan") == 0
    env[2].ignore_writes = True
    assert run(env, "apply", "--yes") == 1
    assert yaml.safe_load((env[0] / "connect-progress.yaml").read_text())["steps"]["pricing/storefront-api"]["status"] == "todo"


@pytest.mark.parametrize("days,valid", [(1, False), (2, True), (180, True), (181, False), (-1, False)])
def test_preorder_dates(env, days, valid):
    put(env, pre_order={"enabled": True, "release_date": (dt.date.today() + dt.timedelta(days=days)).isoformat()})
    assert run(env, "check") == (0 if valid else 1)
    if valid:
        assert run(env, "plan") == 0
        assert run(env, "apply", "--yes") == 0
        assert all(r["attributes"]["preOrderEnabled"] for r in env[2].available.values())


@pytest.mark.parametrize("state", ["READY_FOR_SALE", "READY_FOR_DISTRIBUTION", "DEVELOPER_REMOVED_FROM_SALE"])
def test_preorder_cannot_reenable_after_release(env, state):
    env[2].versions[0]["attributes"]["appVersionState"] = state
    put(env, pre_order={"enabled": True, "release_date": (dt.date.today() + dt.timedelta(days=10)).isoformat()})
    assert run(env, "plan") == 1
    assert not env[2].writes


def test_preorder_past_release_and_available_status_block(env):
    env[2].available["USA"]["attributes"]["releaseDate"] = dt.date.today().isoformat()
    put(env, pre_order={"enabled": True, "release_date": (dt.date.today() + dt.timedelta(days=10)).isoformat()})
    assert run(env, "plan") == 1
    env[2].available["USA"]["attributes"]["releaseDate"] = None
    env[2].available["USA"]["attributes"]["contentStatuses"] = ["AVAILABLE"]
    assert run(env, "plan") == 1


def test_disabling_active_preorder_cannot_release_implicitly(env):
    env[2].available["USA"]["attributes"]["preOrderEnabled"] = True
    assert run(env, "plan") == 1
    put(env, territories={"all-except": ["USA"]})
    assert run(env, "plan") == 0
    assert run(env, "apply", "--yes", "--remove-territories-ok") == 0


def test_omitted_preorder_preserves_it_when_recreating_availability(env):
    env[1].pop("pre_order")
    put(env, new_territories_auto_available=False)
    env[2].available["USA"]["attributes"].update(preOrderEnabled=True, releaseDate="2027-01-01")
    assert run(env, "plan") == 0
    assert run(env, "apply", "--yes") == 0
    assert env[2].available["USA"]["attributes"]["releaseDate"] == "2027-01-01"
    assert env[2].available["USA"]["attributes"]["preOrderEnabled"] is True


def test_status_without_pricing_yaml(env, capsys):
    (env[0] / "pricing.yaml").unlink()
    assert run(env, "status") == 0
    out = capsys.readouterr().out
    assert '"prices"' in out and '"preOrderEnabled"' in out
    assert not env[2].writes


def test_app_id_requires_bundle_match(env):
    (env[0] / "connect.yaml").write_text("api:\n  app_id: app1\n")
    (env[0] / "facts.yaml").write_text("app:\n  bundle_id: wrong.app\n")
    assert run(env, "plan") == 1
    assert not env[2].writes


@pytest.mark.parametrize("updates", [
    {"customer_price": "NaN"}, {"customer_price": "-1"}, {"customer_price": True},
    {"base_territory": "US"}, {"territories": "USA"}, {"territories": ["USA", "USA"]},
    {"new_territories_auto_available": "yes"}, {"pre_order": {"enabled": "false"}},
    {"pre_order": {"enabled": False, "release_date": "2027-01-01"}},
    {"manual_overrides": {"USA": "1"}}, {"unknown": "x"},
    {"scheduled_change": {"start_date": "2020-01-01", "customer_price": "1.99"}},
    {"scheduled_change": {"start_date": "nonsense", "customer_price": "1.99"}},
])
def test_invalid_configuration(env, updates):
    put(env, **updates)
    assert run(env, "check") == 1
    assert not env[2].calls


def test_unknown_territory_rejected_from_api_list(env):
    put(env, territories=["ZZZ"])
    assert run(env, "plan") == 1
    assert not env[2].writes


def test_missing_equalization_fails(env):
    env[2].territories.append(resource("territories", "CAN", {"currency": "CAD"}))
    assert run(env, "plan") == 1
    assert not env[2].writes


def test_private_values_redacted_in_errors_and_status(env, capsys):
    (env[0] / "private.yaml").write_text(yaml.safe_dump({"password": 'secret"\\value'}))
    env[2].available["USA"]["attributes"]["contentStatuses"] = ['secret"\\value']
    assert run(env, "status") == 0
    output = capsys.readouterr().out + (env[0] / "pricing-live.json").read_text()
    assert "secret" not in output
    assert "[private]" in output


def test_private_overlap_refuses_executable_plan(env):
    (env[0] / "private.yaml").write_text("password: opaque-USA-1\n")
    assert run(env, "plan") == 1
    assert not (env[0] / "pricing-plan.json").exists()


def test_missing_plan_and_malformed_yaml(env, capsys):
    assert run(env, "apply", "--yes") == 1
    (env[0] / "pricing.yaml").write_text('customer_price: [secret: [')
    assert run(env, "check") == 1
    assert "secret" not in capsys.readouterr().out


def test_preorder_listing_removal_needs_ack_even_if_available_false(env):
    env[2].available["USA"]["attributes"].update(available=False, preOrderEnabled=True)
    put(env, territories={"all-except": ["USA"]})
    assert run(env, "plan") == 0
    assert "USA" in saved(env)["removed_territories"]
    assert run(env, "apply", "--yes") == 2
    assert not env[2].writes


def test_unknown_release_state_fails_closed(env):
    env[2].versions[0]["attributes"] = {}
    put(env, pre_order={"enabled": True, "release_date": (dt.date.today() + dt.timedelta(days=10)).isoformat()})
    assert run(env, "plan") == 1


def test_failed_apply_clears_prior_completion_and_preserves_other_steps(env):
    (env[0] / "connect-progress.yaml").write_text(yaml.safe_dump({"steps": {
        "pricing/storefront-api": {"status": pricing.cg.STATUSES[2]},
        "other/step": {"status": "done-by-owner", "note": "keep this"}}}))
    assert run(env, "plan") == 0
    env[2].fail = ("POST", "/v1/appPriceSchedules")
    assert run(env, "apply", "--yes") == 1
    progress = yaml.safe_load((env[0] / "connect-progress.yaml").read_text())
    assert progress["steps"]["pricing/storefront-api"]["status"] == "todo"
    assert progress["steps"]["other/step"]["note"] == "keep this"


def test_expired_plan_rejected(env):
    assert run(env, "plan") == 0
    plan = saved(env)
    plan["day"] = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    (env[0] / "pricing-plan.json").write_text(json.dumps(plan))
    assert run(env, "apply", "--yes") == 1
    assert not env[2].writes


def test_omitted_preorder_is_verified_after_availability_post(env):
    env[1].pop("pre_order")
    put(env, new_territories_auto_available=False)
    env[2].available["USA"]["attributes"].update(preOrderEnabled=True, releaseDate="2027-01-01")
    assert run(env, "plan") == 0
    plan = saved(env)
    assert plan["desired"]["availability"]["USA"]["preOrderEnabled"] is True
    assert plan["desired"]["availability"]["USA"]["releaseDate"] == "2027-01-01"
    assert run(env, "apply", "--yes") == 0
    live = pricing.read_live(env[3], env[2].app)
    live["availability"]["USA"]["preOrderEnabled"] = False
    assert not pricing.matches(plan, live)
