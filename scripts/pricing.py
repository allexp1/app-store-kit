#!/usr/bin/env python3
"""Plan and apply app storefront pricing, availability and pre-orders.

check KIT is offline. status/plan use GET only. apply requires a saved plan and
--yes (also with --dry-run). See references/pricing-and-availability.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
from decimal import Decimal, InvalidOperation
import hashlib
import json
import pathlib
import re
import sys
from urllib.parse import quote

import yaml

import asc_api
import connect_guide as cg

PLAN_VERSION = 1
REMOVAL_WARNING = "Live customers in removed territories lose the listing."
# Shapes match OpenAPI 4.5.1. UNCONFIRMED at runtime: inline temporary IDs,
# replacement/propagation semantics and cancelling an active pre-order with
# available=false plus preOrderEnabled=false; see the reference's boundaries.


class PricingError(Exception):
    pass


def attrs(resource):
    return (resource or {}).get("attributes") or {}


def rel_id(resource, name):
    data = ((resource or {}).get("relationships", {}).get(name) or {}).get("data")
    return data.get("id") if isinstance(data, dict) else None


def link(kind, rid):
    return {"data": {"type": kind, "id": rid}}


def segment(value):
    return quote(str(value), safe="")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def mapping(value, label, allowed):
    if not isinstance(value, dict):
        raise PricingError(f"{label} must be a mapping")
    if set(value) - set(allowed):
        raise PricingError(f"{label} has unknown fields; see templates/pricing.example.yaml")
    return value


def territory(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}", value):
        raise PricingError("Territories must be Apple's three-letter uppercase codes, such as USA")
    return value


def money(value):
    try:
        if isinstance(value, bool):
            raise InvalidOperation
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise InvalidOperation
        return format(amount, "f")
    except (InvalidOperation, ValueError):
        raise PricingError("customer_price must be a nonnegative decimal amount") from None


def date_text(value, label):
    try:
        text = str(value)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            raise ValueError
        return dt.date.fromisoformat(text).isoformat()
    except ValueError:
        raise PricingError(f"{label} must be YYYY-MM-DD") from None


def overrides(value):
    if not isinstance(value, dict):
        raise PricingError("manual_overrides must map territory codes to customer prices")
    return {territory(k): money(v) for k, v in value.items()}


def validate(raw, today=None):
    today = today or dt.date.today()
    raw = mapping(raw, "pricing.yaml", {"base_territory", "customer_price", "manual_overrides",
                  "scheduled_change", "territories", "new_territories_auto_available", "pre_order"})
    base = territory(raw.get("base_territory"))
    out = {"base_territory": base, "customer_price": money(raw.get("customer_price")),
           "manual_overrides": overrides(raw.get("manual_overrides", {}))}
    if base in out["manual_overrides"]:
        raise PricingError("The base territory price belongs in customer_price, not manual_overrides")
    countries = raw.get("territories")
    if countries == "all":
        out["territories"] = "all"
    else:
        values = countries
        if isinstance(countries, dict):
            mapping(countries, "territories", {"all-except"})
            values = countries.get("all-except")
        if not isinstance(values, list) or len(set(map(str, values))) != len(values):
            raise PricingError("territories must be all, a list, or {all-except: [codes]} without duplicates")
        values = sorted(territory(x) for x in values)
        out["territories"] = {"all-except": values} if isinstance(countries, dict) else values
    auto = raw.get("new_territories_auto_available")
    if not isinstance(auto, bool):
        raise PricingError("new_territories_auto_available must be true or false")
    out["new_territories_auto_available"] = auto
    scheduled = raw.get("scheduled_change")
    out["scheduled_change"] = None
    if scheduled is not None:
        mapping(scheduled, "scheduled_change", {"start_date", "customer_price", "manual_overrides"})
        start = date_text(scheduled.get("start_date"), "scheduled_change.start_date")
        if start <= today.isoformat():
            raise PricingError("scheduled_change.start_date must be in the future; plan again after it takes effect")
        manual = overrides(scheduled.get("manual_overrides", out["manual_overrides"]))
        if base in manual:
            raise PricingError("The base territory cannot appear in scheduled manual_overrides")
        out["scheduled_change"] = {"start_date": start,
                                   "customer_price": money(scheduled.get("customer_price")),
                                   "manual_overrides": manual}
    pre = raw.get("pre_order")
    out["pre_order"] = None
    if pre is not None:
        mapping(pre, "pre_order", {"enabled", "release_date"})
        if not isinstance(pre.get("enabled"), bool):
            raise PricingError("pre_order.enabled must be true or false")
        release = None
        if pre["enabled"]:
            release = date_text(pre.get("release_date"), "pre_order.release_date")
            if not 2 <= (dt.date.fromisoformat(release) - today).days <= 180:
                raise PricingError("Pre-order release_date must be 2 to 180 days ahead")
        elif pre.get("release_date") is not None:
            raise PricingError("Omit release_date when pre_order.enabled is false")
        out["pre_order"] = {"enabled": pre["enabled"], "release_date": release}
    return out


class Kit:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.pvals = cg.private_values(cg.load_yaml(self.path / "private.yaml"))
        self.facts = cg.load_yaml(self.path / "facts.yaml")
        self.conn = cg.load_yaml(self.path / "connect.yaml")

    def mask(self, text):
        return cg.mask(text, self.pvals)

    def mask_obj(self, value):
        return cg.mask_obj(value, self.pvals)

    def config(self):
        path = self.path / "pricing.yaml"
        if not path.is_file():
            raise PricingError("No pricing.yaml; copy templates/pricing.example.yaml into KIT first")
        return validate(yaml.safe_load(path.read_text()))

    def fingerprint(self):
        # Bind the approval to input bytes and app selection, never private values.
        return digest({"pricing": (self.path / "pricing.yaml").read_text(),
                       "bundle_id": (self.facts.get("app") or {}).get("bundle_id"),
                       "app_id": (self.conn.get("api") or {}).get("app_id")})

    def write_json(self, name, value):
        # Masked as data, then serialized: the JSON stays valid whatever the private values are.
        masked = self.mask_obj(value)
        if name == "pricing-plan.json" and masked != value:
            raise PricingError("Plan overlaps private.yaml values; cannot save an executable redacted plan")
        (self.path / name).write_text(json.dumps(masked, indent=2, ensure_ascii=False) + "\n")


def resolve_app(client, kit):
    app_id = (kit.conn.get("api") or {}).get("app_id")
    bundle = (kit.facts.get("app") or {}).get("bundle_id")
    if app_id:
        app = client.get(f"/v1/apps/{segment(app_id)}")["data"]
        if bundle and attrs(app).get("bundleId") != bundle:
            raise PricingError("api.app_id does not match facts.yaml app.bundle_id")
        return app
    if not bundle:
        raise PricingError("Set facts.yaml app.bundle_id or connect.yaml api.app_id")
    apps = client.get_all("/v1/apps", {"filter[bundleId]": bundle, "limit": 200})
    exact = [a for a in apps if attrs(a).get("bundleId") == bundle]
    if len(exact) != 1:
        raise PricingError("Expected exactly one app for app.bundle_id; create or select the app first")
    return exact[0]


def optional(client, path, params=None):
    try:
        return (client.get(path, params) or {}).get("data")
    except asc_api.ASCError as error:
        if error.status == 404:
            return None
        raise


def point_info(point, code=None):
    if not point or not point.get("id") or attrs(point).get("customerPrice") is None:
        raise PricingError("Apple did not return the price point's customer price; cannot plan safely")
    code = code or rel_id(point, "territory")
    if not code:
        raise PricingError("Apple did not identify a price point's territory")
    return {"point_id": point["id"], "territory": code,
            "customer_price": money(attrs(point)["customerPrice"]), "proceeds": attrs(point).get("proceeds")}


def read_live(client, app):
    aid = segment(app["id"])
    territories = {t["id"]: attrs(t).get("currency") for t in client.get_all("/v1/territories", {"limit": 200})}
    if not territories:
        raise PricingError("Apple returned no territories")
    schedule = optional(client, f"/v1/apps/{aid}/appPriceSchedule", {"include": "baseTerritory"})
    prices = []
    base = rel_id(schedule, "baseTerritory")
    if schedule:
        sid = segment(schedule["id"])
        if not base:
            base = (client.get(f"/v1/appPriceSchedules/{sid}/baseTerritory").get("data") or {}).get("id")
        for kind in ("manualPrices", "automaticPrices"):
            rows, included = client.get_all(f"/v1/appPriceSchedules/{sid}/{kind}",
                                           {"include": "appPricePoint,territory", "limit": 200},
                                           include_included=True)
            points = {p["id"]: p for p in included if p["type"] == "appPricePoints"}
            for row in rows:
                pid = rel_id(row, "appPricePoint")
                if not pid:
                    raise PricingError("Apple returned a schedule row without an appPricePoint")
                point = points.get(pid)
                if point is None:
                    point = client.get(f"/v3/appPricePoints/{segment(pid)}")["data"]
                prices.append({**point_info(point, rel_id(row, "territory")),
                               "manual": kind == "manualPrices", "start_date": attrs(row).get("startDate"),
                               "end_date": attrs(row).get("endDate")})
    availability = optional(client, f"/v1/apps/{aid}/appAvailabilityV2")
    available = {}
    if availability:
        rows = client.get_all(f"/v2/appAvailabilities/{segment(availability['id'])}/territoryAvailabilities",
                              {"include": "territory", "limit": 200})
        for row in rows:
            code = rel_id(row, "territory")
            if code not in territories or code in available or not isinstance(attrs(row).get("available"), bool):
                raise PricingError("Apple returned incomplete or duplicate territory availability")
            available[code] = {"id": row["id"], **{k: attrs(row).get(k) for k in
                               ("available", "preOrderEnabled", "releaseDate", "contentStatuses")}}
    versions = client.get_all(f"/v1/apps/{aid}/appStoreVersions", {"limit": 200})
    states = sorted({attrs(v).get("appVersionState") or attrs(v).get("appStoreState") or "UNKNOWN" for v in versions})
    return {"app_id": app["id"], "territories": territories, "base_territory": base,
            "schedule_id": schedule["id"] if schedule else None,
            "prices": sorted(prices, key=lambda p: (p["territory"], p["start_date"] or "", p["point_id"], p["manual"])),
            "availability_id": availability["id"] if availability else None,
            "new_territories_auto_available": attrs(availability).get("availableInNewTerritories"),
            "availability": available, "version_states": states}


def select_territories(config, all_codes):
    value = config["territories"]
    specified = set(value.get("all-except", [])) if isinstance(value, dict) else set(value if isinstance(value, list) else [])
    referenced = specified | {config["base_territory"]} | set(config["manual_overrides"])
    if config["scheduled_change"]:
        referenced |= set(config["scheduled_change"]["manual_overrides"])
    if referenced - all_codes:
        raise PricingError("Unknown Apple territories: " + ", ".join(sorted(referenced - all_codes)))
    return all_codes - specified if isinstance(value, dict) else (all_codes if value == "all" else specified)


def exact_point(client, app_id, code, price, cache):
    if code not in cache:
        cache[code] = client.get_all(f"/v1/apps/{segment(app_id)}/appPricePoints",
                                    {"filter[territory]": code, "include": "territory", "limit": 200})
    matches = [p for p in cache[code] if rel_id(p, "territory") in (None, code)
               and attrs(p).get("customerPrice") is not None
               and Decimal(money(attrs(p)["customerPrice"])) == Decimal(price)]
    if len(matches) != 1:
        raise PricingError(f"{code}: customer price {price} has {'no exact' if not matches else 'multiple exact'} "
                           "API price points; choose an unambiguous price. No tier IDs are guessed.")
    return point_info(matches[0], code)


def desired_prices(client, config, live):
    cache, equal_cache, prices = {}, {}, []
    base, scheduled = config["base_territory"], config["scheduled_change"]
    phases = [(None, scheduled["start_date"] if scheduled else None, config)]
    if scheduled:
        phases.append((scheduled["start_date"], None, scheduled))
    for start, end, phase in phases:
        manual = {base: phase["customer_price"], **phase["manual_overrides"]}
        points = {code: exact_point(client, live["app_id"], code, price, cache) for code, price in manual.items()}
        pid = points[base]["point_id"]
        if pid not in equal_cache:
            eq = client.get_all(f"/v3/appPricePoints/{segment(pid)}/equalizations", {"include": "territory", "limit": 200})
            equal_cache[pid] = {rel_id(p, "territory"): point_info(p) for p in eq}
        for code in sorted(live["territories"]):
            point = points.get(code) or equal_cache[pid].get(code)
            if not point:
                raise PricingError(f"No Apple equalized price for {code}; add a manual override")
            prices.append({**point, "manual": code in manual, "start_date": start, "end_date": end})
    return prices


def price_signature(rows, today):
    return sorted((r["territory"], r["point_id"], r["manual"],
                   r["start_date"] if r["start_date"] and r["start_date"] > today else "",
                   r["end_date"] or "") for r in rows if not r["end_date"] or r["end_date"] > today)


def request(method, path, body):
    return {"method": method, "path": path, "json": body}


def build_plan(client, kit, config, live, today=None):
    today = (today or dt.date.today()).isoformat()
    selected = select_territories(config, set(live["territories"]))
    prices = desired_prices(client, config, live)
    requests, warnings = [], []
    changed_price = live["base_territory"] != config["base_territory"] or \
        price_signature(live["prices"], today) != price_signature(prices, today)
    if changed_price:
        included = [{"type": "appPrices", "id": f"${{price-{n}}}",
                     "attributes": {"startDate": p["start_date"], "endDate": p["end_date"]},
                     "relationships": {"appPricePoint": link("appPricePoints", p["point_id"])}}
                    for n, p in enumerate(p for p in prices if p["manual"])]
        requests.append(request("POST", "/v1/appPriceSchedules", {
            "data": {"type": "appPriceSchedules", "relationships": {
                "app": link("apps", live["app_id"]), "baseTerritory": link("territories", config["base_territory"]),
                "manualPrices": {"data": [{"type": p["type"], "id": p["id"]} for p in included]}}},
            "included": included}))
        warnings.append("The price schedule replaces current and future manual pricing with the phases shown; omitted overrides return to Apple's automatic prices.")
    desired = {}
    pre = config["pre_order"]
    # UNCONFIRMED: current version states cannot prove a removed territory was never released.
    # Fail closed for new pre-orders after any known release; Apple remains the eligibility authority.
    released = any(s in {"READY_FOR_SALE", "READY_FOR_DISTRIBUTION", "PROCESSING_FOR_DISTRIBUTION",
                         "REMOVED_FROM_SALE", "DEVELOPER_REMOVED_FROM_SALE", "REPLACED_WITH_NEW_VERSION"}
                   for s in live["version_states"])
    for code in sorted(live["territories"]):
        old = live["availability"].get(code, {})
        new = {k: old[k] for k in ("preOrderEnabled", "releaseDate") if old.get(k) is not None}
        new["available"] = code in selected
        if pre is not None:
            enabling = pre["enabled"] and code in selected
            if enabling:
                statuses = old.get("contentStatuses") or []
                past_date = old.get("releaseDate") and old["releaseDate"] <= today
                if "AVAILABLE" in statuses or past_date or \
                   ((released or "UNKNOWN" in live["version_states"]) and not old.get("preOrderEnabled")):
                    raise PricingError(f"{code}: cannot enable pre-order after release, or prove this territory was never released; check eligibility in App Store Connect")
            if old.get("preOrderEnabled") and not enabling and code in selected:
                raise PricingError(f"{code}: disabling an active pre-order while keeping it available may release it. Remove the territory to cancel; immediate release is a separate step")
            new["preOrderEnabled"] = enabling
            # Preserve an existing release date when disabling to avoid accidentally clearing a release schedule.
            if enabling:
                new["releaseDate"] = pre["release_date"]
        desired[code] = new
    removed = sorted(code for code, old in live["availability"].items()
                     if (old["available"] or old.get("preOrderEnabled")) and code not in selected)
    if removed:
        warnings.append(REMOVAL_WARNING + " Removed: " + ", ".join(removed))
    if pre and pre["enabled"]:
        if not selected:
            raise PricingError("A pre-order needs at least one available territory")
        warnings.append("Pre-orders can become visible in released apps immediately; customers receive the app on the release date. This does not submit or release an app version.")
    # The 4.5.1 spec has POST and GET for appAvailabilities v2, no parent PATCH.
    recreate = live["availability_id"] is None or \
        live["new_territories_auto_available"] != config["new_territories_auto_available"] or \
        any(code not in live["availability"] and new["available"] for code, new in desired.items())
    if recreate:
        included = []
        for code, new in desired.items():
            old = live["availability"].get(code, {})
            preserved = {k: old[k] for k in ("preOrderEnabled", "releaseDate") if old.get(k) is not None}
            included.append({"type": "territoryAvailabilities", "id": f"${{territory-{code}}}",
                             "attributes": {**preserved, **new},
                             "relationships": {"territory": link("territories", code)}})
        requests.append(request("POST", "/v2/appAvailabilities", {
            "data": {"type": "appAvailabilities", "attributes": {
                "availableInNewTerritories": config["new_territories_auto_available"]}, "relationships": {
                "app": link("apps", live["app_id"]), "territoryAvailabilities": {
                    "data": [{"type": r["type"], "id": r["id"]} for r in included]}}}, "included": included}))
    else:
        for code, new in desired.items():
            old = live["availability"].get(code, {})
            changes = {k: v for k, v in new.items() if old.get(k) != v}
            if changes and old.get("id"):
                requests.append(request("PATCH", f"/v1/territoryAvailabilities/{segment(old['id'])}",
                                        {"data": {"type": "territoryAvailabilities", "id": old["id"],
                                                  "attributes": changes}}))
    return {"schema": PLAN_VERSION, "input_hash": kit.fingerprint(), "day": today, "app_id": live["app_id"],
            "before": live, "desired": {"base_territory": config["base_territory"], "prices": prices,
            "availability": desired, "new_territories_auto_available": config["new_territories_auto_available"]},
            "removed_territories": removed, "warnings": warnings, "requests": requests}


def price_text(rows, code, currency):
    values = []
    for row in rows:
        if row["territory"] != code:
            continue
        proceeds = row["proceeds"] if row["proceeds"] is not None else "not returned"
        values.append(f"{row['customer_price']} {currency or ''} (proceeds {proceeds}; "
                      f"{row['start_date'] or 'now'} to {row['end_date'] or 'ongoing'}; "
                      f"{'manual' if row['manual'] else 'automatic'})")
    return "; ".join(values) or "not set"


def render_plan(plan):
    before, desired = plan["before"], plan["desired"]
    lines = ["# Pricing and availability plan", "", f"App: {plan['app_id']}. Plan date: {plan['day']}.", "",
             f"Base territory: {before['base_territory']} → {desired['base_territory']}",
             f"New territories automatically available: {before['new_territories_auto_available']} → {desired['new_territories_auto_available']}", ""]
    lines += [f"- {w}" for w in plan["warnings"]]
    lines += ["", "| Territory | Customer price and proceeds: old → new | Availability: old → new | Pre-order: old → new |",
              "|---|---|---|---|"]
    for code, currency in sorted(before["territories"].items()):
        old, new = before["availability"].get(code, {}), desired["availability"][code]
        old_pre = f"{old.get('preOrderEnabled', False)} / {old.get('releaseDate') or 'no date'}"
        new_pre = f"{new.get('preOrderEnabled', old.get('preOrderEnabled', False))} / {new.get('releaseDate', old.get('releaseDate')) or 'no date'}"
        lines.append(f"| {code} | {price_text(before['prices'], code, currency)} → {price_text(desired['prices'], code, currency)} | "
                     f"{old.get('available', False)} → {new['available']} | {old_pre} → {new_pre} |")
    lines += ["", f"{len(plan['requests'])} request(s). Show this plan before apply --yes.",
              "Territory removals also require --remove-territories-ok.", ""]
    return "\n".join(lines)


def matches(plan, live):
    desired = plan["desired"]
    if live["base_territory"] != desired["base_territory"] or \
       live["new_territories_auto_available"] != desired["new_territories_auto_available"] or \
       price_signature(live["prices"], plan["day"]) != price_signature(desired["prices"], plan["day"]):
        return False
    for code, values in desired["availability"].items():
        old = live["availability"].get(code, {"available": False, "preOrderEnabled": False})
        if any(old.get(k) != v for k, v in values.items()):
            return False
    return True


def write_progress(kit, live, done=True):
    path = kit.path / cg.PROGRESS_FILE
    progress = cg.load_yaml(path) or {}
    progress.setdefault("steps", {})["pricing/storefront-api"] = {
        "status": cg.STATUSES[2] if done else "todo", "date": dt.date.today().isoformat(),
        "live": {"Base territory": live["base_territory"],
                 "Available territories": ", ".join(sorted(k for k, v in live["availability"].items() if v["available"])),
                 "New territories automatically available": live["new_territories_auto_available"]},
        "note": ("Pricing, availability and pre-orders set through pricing.py; re-read and matching. See pricing-live.json for schedule and pre-order dates."
                 if done else "Pricing apply started; completion is not verified. Read status and plan again after a failure.")}
    # Mask values before YAML serialization so escaped or multi-line secrets cannot survive.
    path.write_text(cg.PROGRESS_HEADER + yaml.safe_dump(kit.mask_obj(progress), sort_keys=False, allow_unicode=True))


def apply(client, kit, config, args):
    path = kit.path / "pricing-plan.json"
    if not path.is_file():
        raise PricingError("No pricing-plan.json; run plan KIT and review pricing-plan.md first")
    plan = json.loads(path.read_text())
    if plan.get("schema") != PLAN_VERSION or plan.get("input_hash") != kit.fingerprint() or plan.get("day") != dt.date.today().isoformat():
        raise PricingError("Pricing inputs or plan date changed; run plan again and review it")
    live = read_live(client, resolve_app(client, kit))
    if plan.get("app_id") != live["app_id"]:
        raise PricingError("The selected app changed; plan again")
    if matches(plan, live):
        if not client.dry_run:
            kit.write_json("pricing-live.json", live)
            write_progress(kit, live)
        print("Pricing and availability already match; no writes needed")
        return 0
    if plan.get("before") != live:
        raise PricingError("Live pricing or availability changed (possibly a partial apply); plan again and review the remaining changes")
    fresh = build_plan(client, kit, config, live)
    if fresh != plan:
        raise PricingError("The saved plan or Apple's price points changed; plan again")
    if plan["removed_territories"] and not args.remove_territories_ok:
        print(REMOVAL_WARNING + " Review pricing-plan.md, then add --remove-territories-ok.")
        return 2
    for warning in plan["warnings"]:
        print(kit.mask(warning))
    if not client.dry_run and plan["requests"]:
        write_progress(kit, live, done=False)
    for op in plan["requests"]:
        if client.dry_run:
            print(kit.mask(f"would send: {op['method']} {op['path']}") + " "
                  + json.dumps(kit.mask_obj(op['json']), ensure_ascii=False))
            continue
        getattr(client, op["method"].lower())(op["path"], op["json"])
        # Re-read after every successful write; never infer success from the request body.
        live = read_live(client, resolve_app(client, kit))
        kit.write_json("pricing-live.json", live)
    if client.dry_run:
        print("dry run: no writes sent and no progress recorded")
        return 0
    if not matches(plan, live):
        raise PricingError("Apple has not returned the planned values; progress was not marked done. Check status, then plan again")
    write_progress(kit, live)
    print("Pricing and availability applied, re-read and matching; updated connect-progress.yaml")
    return 0


def main(argv=None, client=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("check", "status", "plan", "apply"))
    parser.add_argument("kit")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--remove-territories-ok", action="store_true")
    for option in ("key-id", "issuer-id", "key-path"):
        parser.add_argument("--" + option)
    args = parser.parse_args(argv)
    if args.command == "apply" and not args.yes:
        print("apply changes App Store Connect: review pricing-plan.md, then run again with --yes (also for --dry-run).")
        return 2
    kit = None
    try:
        kit = Kit(args.kit)
        config = kit.config() if args.command != "status" else None
        if args.command == "check":
            print("pricing.yaml is valid locally; plan checks exact API price points and live pre-order eligibility")
            return 0
        if client is None:
            client = asc_api.make_client(args, kit=kit.path, dry_run=args.dry_run)
        client.dry_run = client.dry_run or args.dry_run
        if args.command == "apply":
            return apply(client, kit, config, args)
        live = read_live(client, resolve_app(client, kit))
        if args.command == "status":
            kit.write_json("pricing-live.json", live)
            print(json.dumps(kit.mask_obj(live), indent=2, ensure_ascii=False))
            return 0
        plan = build_plan(client, kit, config, live)
        kit.write_json("pricing-plan.json", plan)
        (kit.path / "pricing-plan.md").write_text(kit.mask(render_plan(plan)))
        print(f"wrote pricing-plan.md and pricing-plan.json: {len(plan['requests'])} request(s)")
        for warning in plan["warnings"]:
            print(kit.mask(warning))
        return 0
    except asc_api.ConfigError as error:
        print(kit.mask(str(error)) if kit else "Cannot load API configuration")
        return 2
    except (PricingError, asc_api.ASCError) as error:
        print(kit.mask(str(error)) if kit else "Cannot load pricing configuration")
        return 1
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
        # Parser exceptions can embed entire YAML source lines, including private values.
        print("Cannot read pricing configuration, saved plan or API response; check their structure and plan again")
        return 1


if __name__ == "__main__":
    sys.exit(main())
