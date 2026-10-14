#!/usr/bin/env python3
"""Plan and manage auto-renewable subscriptions without deleting resources.

subscriptions.py check|status|plan|apply|submit KIT [--yes] [--dry-run] [--price-increase-ok]
See references/subscriptions.md for the schema, staged pricing and deprecated v1 workflow.
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
import time

import yaml

import asc_api
import connect_guide as cg
from locales import LOCALES

PERIODS = {"ONE_WEEK", "ONE_MONTH", "TWO_MONTHS", "THREE_MONTHS", "SIX_MONTHS", "ONE_YEAR"}
# UNCONFIRMED: full offer enum/period combinations; Apple remains the final validator.
OFFER_PERIODS = PERIODS | {"THREE_DAYS", "TWO_WEEKS"}
MODES = {"FREE_TRIAL", "PAY_AS_YOU_GO", "PAY_UP_FRONT"}
# UNCONFIRMED request details: group creation/localization writes, subscription group linkage,
# price-point/equalization reads, screenshot reserve/commit, offer creates and submission linkage.
# Public Apple pages confirm the resource families; see the per-shape verification table in the reference.
PLAN = "subscriptions-plan"
CONSENT = ("Apple may require subscriber consent based on storefront, increase thresholds and prior increases. "
           "Without required consent the subscription expires. See references/subscriptions.md; "
           "--price-increase-ok acknowledges this risk, it does not provide subscriber consent.")


class SubscriptionError(Exception):
    pass


def attrs(row):
    return (row or {}).get("attributes") or {}


def rel_id(row, key):
    data = ((row or {}).get("relationships", {}).get(key) or {}).get("data")
    return data.get("id") if isinstance(data, dict) else None


def ref(typ, rid):
    return {"type": typ, "id": rid}


def body(typ, values=None, relationships=None, rid=None):
    data = {"type": typ}
    if rid:
        data["id"] = rid
    if values is not None:
        data["attributes"] = values
    if relationships:
        data["relationships"] = {k: {"data": v} for k, v in relationships.items()}
    return {"data": data}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def redact(value, pvals):
    """Private values masked in a data structure, before it is serialized (connect_guide.mask_obj)."""
    return cg.mask_obj(value, pvals)


def load(path):
    if not path.exists():
        return {}
    value = yaml.safe_load(path.read_text()) or {}
    if not isinstance(value, dict):
        raise SubscriptionError(f"{path.name} must contain a mapping")
    return value


class Kit:
    def __init__(self, path):
        self.path = pathlib.Path(path).resolve()
        self.config = load(self.path / "subscriptions.yaml")
        self.facts = load(self.path / "facts.yaml")
        self.connect = load(self.path / "connect.yaml")
        self.pvals = cg.private_values(load(self.path / "private.yaml"))
        if not isinstance(self.facts.get("app", {}), dict) or not isinstance(self.connect.get("api", {}), dict):
            raise SubscriptionError("facts.yaml app and connect.yaml api must be mappings")

    def public(self, value):
        return redact(value, self.pvals)

    def screenshot(self, value):
        path = (self.path / value).resolve()
        if not path.is_relative_to(self.path) or path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise SubscriptionError("review_screenshot must be a PNG/JPEG inside KIT")
        if not path.is_file():
            raise SubscriptionError(f"review screenshot is missing: {value}")
        return path

    def fingerprint(self):
        files = {s["review_screenshot"]: digest(self.screenshot(s["review_screenshot"]).read_bytes())
                 for g in self.config["groups"] for s in g["subscriptions"] if s.get("review_screenshot")}
        return digest(canonical({"config": self.config, "files": files,
                                 "bundle_id": self.facts.get("app", {}).get("bundle_id"),
                                 "app_id": self.connect.get("api", {}).get("app_id")}).encode())


def check(kit):
    """Offline shape/limit validation. Never resolves keys or constructs a client."""
    # UNCONFIRMED numeric limits and subscription locale coverage are itemized in the reference.
    errors = []

    def fail(where, text):
        errors.append(f"{where}: {text}")

    def mapping(value, where, allowed):
        if not isinstance(value, dict):
            fail(where, "must be a mapping")
            return {}
        if set(value) - set(allowed):
            fail(where, "unknown fields: " + ", ".join(sorted(str(k) for k in set(value) - set(allowed))))
        return value

    def text(value, where, limit, required=True):
        if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
            fail(where, f"must be {'1' if required else '0'}–{limit} characters of text")

    def sequence(value, where, required=False):
        if not isinstance(value, list) or (required and not value):
            fail(where, "must be a nonempty list" if required else "must be a list")
            return []
        return value

    def date(value, where):
        if value is not None:
            try:
                if not isinstance(value, str) or dt.date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
            except ValueError:
                fail(where, "use a quoted YYYY-MM-DD date")

    def prices(value, where):
        value = mapping(value, where, value.keys() if isinstance(value, dict) else [])
        if not value:
            fail(where, "declare at least one territory price")
        for territory, price in value.items():
            if not isinstance(territory, str) or not re.fullmatch(r"[A-Z]{3}", territory):
                fail(where, "territories must be three uppercase letters (USA, GBR)")
            try:
                if isinstance(price, bool) or not Decimal(str(price)).is_finite() or Decimal(str(price)) < 0:
                    raise InvalidOperation()
            except (InvalidOperation, ValueError):
                fail(where, "prices must be nonnegative decimal amounts")
        return value

    def locs(value, where, group=False):
        if not isinstance(value, dict) or not value:
            fail(where, "declare at least one localization")
            return
        for locale, loc in value.items():
            at = f"{where}/{locale}"
            if locale not in LOCALES:
                fail(at, "unknown App Store locale")
            loc = mapping(loc, at, {"name", "custom_app_name"} if group else {"name", "description"})
            # UNCONFIRMED limits: group 75, custom app 30, subscription description 55.
            text(loc.get("name"), at + "/name", 75 if group else 30)
            if isinstance(loc.get("name"), str) and re.search(r"[\x00-\x1f\x7f<>]", loc["name"]):
                fail(at, "names cannot contain control characters or markup")
            if group and "custom_app_name" in loc:
                text(loc["custom_app_name"], at + "/custom_app_name", 30, False)
            if not group:
                text(loc.get("description"), at + "/description", 55)

    config = mapping(kit.config, "subscriptions.yaml", {"groups"})
    seen_groups, seen_products = set(), set()
    for gi, group in enumerate(sequence(config.get("groups"), "groups", True)):
        at = f"groups/{gi}"
        group = mapping(group, at, {"id", "reference_name", "localizations", "subscriptions"})
        text(group.get("reference_name"), at + "/reference_name", 64)
        name = str(group.get("reference_name"))
        if name in seen_groups:
            fail(at, "duplicate group reference name")
        seen_groups.add(name)
        if "id" in group:
            text(group["id"], at + "/id", 200)
        locs(group.get("localizations"), at + "/localizations", True)
        subs = sequence(group.get("subscriptions"), at + "/subscriptions", True)
        if len(subs) > 100:
            fail(at, "at most 100 subscriptions per group")
        for si, sub in enumerate(subs):
            sp = f"{at}/subscriptions/{si}"
            sub = mapping(sub, sp, {"product_id", "reference_name", "duration", "group_level", "family_sharing",
                                  "review_note", "review_screenshot", "localizations", "prices", "pricing",
                                  "introductory_offers", "promotional_offers", "offer_codes"})
            pid = sub.get("product_id")
            text(pid, sp + "/product_id", 100)
            if isinstance(pid, str) and not re.fullmatch(r"[A-Za-z0-9._-]+", pid):
                fail(sp, "product_id uses only letters, digits, dots, hyphens and underscores")
            if str(pid) in seen_products:
                fail(sp, "duplicate product_id across groups")
            seen_products.add(str(pid))
            text(sub.get("reference_name"), sp + "/reference_name", 64)
            if not isinstance(sub.get("duration"), str) or sub["duration"] not in PERIODS:
                fail(sp, "duration must be one of " + ", ".join(sorted(PERIODS)))
            level = sub.get("group_level")
            if type(level) is not int or not 1 <= level <= 100:
                fail(sp, "group_level must be an integer 1–100 (1 is highest; ties are allowed)")
            if "family_sharing" in sub and type(sub["family_sharing"]) is not bool:
                fail(sp, "family_sharing must be true or false")
            if "review_note" in sub:
                text(sub["review_note"], sp + "/review_note", 4000, False)
            if "review_screenshot" in sub:
                try:
                    if not isinstance(sub["review_screenshot"], str):
                        raise SubscriptionError("review_screenshot must be a path")
                    kit.screenshot(sub["review_screenshot"])
                except SubscriptionError as e:
                    fail(sp, str(e))
            locs(sub.get("localizations"), sp + "/localizations")
            if ("prices" in sub) == ("pricing" in sub):
                fail(sp, "declare exactly one of prices or pricing")
            if "prices" in sub:
                prices(sub["prices"], sp + "/prices")
            pricing = mapping(sub.get("pricing", {}), sp + "/pricing",
                              {"base_territory", "price", "equalize", "preserve_current_price", "start_date"})
            if "pricing" in sub:
                prices({pricing.get("base_territory"): pricing.get("price")}, sp + "/pricing")
                for key in ("equalize", "preserve_current_price"):
                    if key in pricing and type(pricing[key]) is not bool:
                        fail(sp, key + " must be true or false")
                date(pricing.get("start_date"), sp + "/pricing/start_date")
            for key in ("introductory_offers", "promotional_offers"):
                codes, territories = set(), set()
                for oi, offer in enumerate(sequence(sub.get(key, []), sp + "/" + key)):
                    op = f"{sp}/{key}/{oi}"
                    intro = key == "introductory_offers"
                    offer = mapping(offer, op, {"duration", "mode", "periods", "territory", "price", "start_date", "end_date"}
                                    if intro else {"duration", "mode", "periods", "name", "offer_code", "prices"})
                    if (not isinstance(offer.get("duration"), str) or offer["duration"] not in OFFER_PERIODS
                            or not isinstance(offer.get("mode"), str) or offer["mode"] not in MODES):
                        fail(op, "invalid offer duration or mode")
                    if type(offer.get("periods")) is not int or not 1 <= offer["periods"] <= 12:
                        fail(op, "periods must be an integer 1–12")
                    if offer.get("mode") != "PAY_AS_YOU_GO" and offer.get("periods") != 1:
                        fail(op, "FREE_TRIAL and PAY_UP_FRONT require periods: 1")
                    if intro:
                        territory = str(offer.get("territory"))
                        prices({territory: offer.get("price", 0)}, op)
                        if territory in territories:
                            fail(op, "only one declared introductory offer per territory")
                        territories.add(territory)
                        for keydate in ("start_date", "end_date"):
                            date(offer.get(keydate), op + "/" + keydate)
                        if isinstance(offer.get("start_date"), str) and isinstance(offer.get("end_date"), str):
                            if offer["end_date"] < offer["start_date"]:
                                fail(op, "end_date precedes start_date")
                        if offer.get("mode") != "FREE_TRIAL" and "price" not in offer:
                            fail(op, "paid offers require price")
                        if offer.get("mode") == "FREE_TRIAL" and str(offer.get("price", 0)) not in {"0", "0.0", "0.00"}:
                            fail(op, "FREE_TRIAL requires a zero price")
                    else:
                        text(offer.get("name"), op + "/name", 64)
                        code = offer.get("offer_code")
                        text(code, op + "/offer_code", 64)
                        if isinstance(code, str) and not re.fullmatch(r"[A-Za-z0-9._-]+", code):
                            fail(op, "offer_code uses letters, digits, dots, hyphens and underscores")
                        if str(code) in codes:
                            fail(op, "duplicate promotional offer_code")
                        codes.add(str(code))
                        prices(offer.get("prices"), op + "/prices")
                        if offer.get("mode") == "FREE_TRIAL" and isinstance(offer.get("prices"), dict):
                            if any(str(p) not in {"0", "0.0", "0.00"} for p in offer["prices"].values()):
                                fail(op, "FREE_TRIAL requires zero prices")
                if key == "promotional_offers" and isinstance(sub.get(key), list) and len(sub[key]) > 10:
                    fail(sp, "at most 10 promotional offers")
            if "offer_codes" in sub and sub["offer_codes"] != "browser":
                fail(sp, "offer_codes must be browser; code generation is a browser step")
    return errors


def one(client, path):
    try:
        return client.get(path).get("data")
    except asc_api.ASCError as e:
        if e.status == 404:
            return None
        raise


def unique(rows, key, value):
    matches = [r for r in rows if attrs(r).get(key) == value]
    if len(matches) > 1:
        raise SubscriptionError(f"Ambiguous {key}: multiple matches; use an explicit group id where applicable")
    return matches[0] if matches else None


def read_live(client, kit):
    bundle = kit.facts.get("app", {}).get("bundle_id")
    app_id = kit.connect.get("api", {}).get("app_id")
    if app_id:
        app = one(client, f"/v1/apps/{app_id}")
        if bundle and attrs(app).get("bundleId") != bundle:
            raise SubscriptionError("api.app_id does not match facts.yaml app.bundle_id")
    elif bundle:
        app = unique(client.get_all("/v1/apps", {"filter[bundleId]": bundle, "limit": 200}), "bundleId", bundle)
    else:
        raise SubscriptionError("Set facts.yaml app.bundle_id or connect.yaml api.app_id")
    if not app:
        raise SubscriptionError("App record not found; create it in App Store Connect first")
    groups = client.get_all(f"/v1/apps/{app['id']}/subscriptionGroups", {"limit": 200})
    live = {"app": app, "groups": []}
    for group in groups:
        gid = group["id"]
        entry = {"resource": group, "localizations": client.get_all(
            f"/v1/subscriptionGroups/{gid}/subscriptionGroupLocalizations", {"limit": 200}), "subscriptions": []}
        for sub in client.get_all(f"/v1/subscriptionGroups/{gid}/subscriptions", {"limit": 200}):
            sid = sub["id"]
            details = {"resource": sub}
            for key in ("subscriptionLocalizations", "prices", "introductoryOffers", "promotionalOffers"):
                details[key] = client.get_all(f"/v1/subscriptions/{sid}/{key}", {"limit": 200})
            details["screenshot"] = one(client, f"/v1/subscriptions/{sid}/appStoreReviewScreenshot")
            if details["screenshot"]:
                attrs(details["screenshot"]).pop("uploadOperations", None)  # Signed upload URLs do not belong in status files.
            entry["subscriptions"].append(details)
        live["groups"].append(entry)
    return live


class Planner:
    def __init__(self, client, kit, live):
        self.client, self.kit, self.live = client, kit, live
        self.ops, self.warnings, self.blockers, self.deferred, self.submit = [], [], [], [], []
        self.submission_blockers = []
        self.points = {}

    def upsert(self, typ, current, values, relationships, key, title):
        rid = current["id"] if current else "$" + key
        changed = {k: v for k, v in values.items() if not current or attrs(current).get(k) != v}
        if changed or not current:
            # Localizations use the requested, deprecated v1 parent-product workflow.
            request = body(typ, changed, None if current else relationships, rid if current else None)
            self.ops.append({"key": key, "title": title, "method": "PATCH" if current else "POST",
                             "path": f"/v1/{typ}" + (f"/{rid}" if current else ""), "body": request,
                             "before": {k: attrs(current).get(k) for k in changed}})
        return rid

    def point(self, sid, territory, price):
        key = sid, territory
        if key not in self.points:
            self.points[key] = self.client.get_all(f"/v1/subscriptions/{sid}/pricePoints",
                                                  {"filter[territory]": territory, "include": "territory", "limit": 200})
        matches = [p for p in self.points[key] if Decimal(str(attrs(p).get("customerPrice"))) == Decimal(str(price))
                   and rel_id(p, "territory") == territory]
        if len(matches) != 1:
            raise SubscriptionError(f"No unique Apple price point for {territory} {price}; choose an available price")
        return matches[0]

    def prices(self, sub, current, sid):
        pricing = sub.get("pricing", {})
        want = sub.get("prices") or {pricing["base_territory"]: pricing["price"]}
        points = {t: self.point(sid, t, p) for t, p in want.items()}
        if pricing.get("equalize"):
            base = points[pricing["base_territory"]]
            equal = self.client.get_all(f"/v1/subscriptionPricePoints/{base['id']}/equalizations",
                                       {"include": "territory", "limit": 200})
            if not equal:
                raise SubscriptionError("Apple returned no equalized prices")
            for p in equal:
                territory = rel_id(p, "territory")
                if not territory:
                    raise SubscriptionError("Equalized price has no territory; cannot plan safely")
                points.setdefault(territory, p)
        for territory, point in sorted(points.items()):
            existing = [p for p in current["prices"] if rel_id(p, "territory") == territory]
            start = pricing.get("start_date")
            preserve = pricing.get("preserve_current_price", True)
            receipt = load(self.kit.path / cg.PROGRESS_FILE).get("steps", {}).get(
                f"subscriptions/price/{sid}/{territory}", {}).get("live", {})
            def policy_applied(price):
                return preserve or (receipt.get("id") == price["id"] and
                                    receipt.get("requested_preserve_current_price") is False)
            same = [p for p in existing if rel_id(p, "subscriptionPricePoint") == point["id"]
                    and attrs(p).get("startDate") == start and not attrs(p).get("preserved") and policy_applied(p)]
            if same:
                continue
            # A past effective startDate also represents today's current price.
            today = dt.date.today().isoformat()
            effective = [p for p in existing if (attrs(p).get("startDate") or "0000") <= today]
            retail = [p for p in effective if not attrs(p).get("preserved")]
            newest = max((attrs(p).get("startDate") or "0000" for p in retail), default="0000")
            retail = [p for p in retail if (attrs(p).get("startDate") or "0000") == newest]
            effective = retail + [p for p in effective if attrs(p).get("preserved")]
            if start is None and any(rel_id(p, "subscriptionPricePoint") == point["id"] and policy_applied(p) for p in retail):
                continue
            old_amounts = []
            for old in effective:
                pp = one(self.client, f"/v1/subscriptionPricePoints/{rel_id(old, 'subscriptionPricePoint')}")
                if not pp or attrs(pp).get("customerPrice") is None:
                    raise SubscriptionError("Cannot read the current subscriber price; refusing price change")
                old_amounts.append(Decimal(str(attrs(pp)["customerPrice"])))
            amount = Decimal(str(attrs(point)["customerPrice"]))
            # Conservatively gate approved products: a complete subscriber cohort history is not exposed here.
            increase = bool(not preserve and (not old_amounts or amount > min(old_amounts)
                                              or attrs(current["resource"]).get("state") == "APPROVED"))
            op = {"key": f"price/{sid}/{territory}", "title": f"{sub['product_id']} price {territory}: {amount}",
                  "method": "POST", "path": "/v1/subscriptionPrices", "price_increase": increase,
                  "before": {"prices": existing},
                  "body": body("subscriptionPrices", {"startDate": start, "preserveCurrentPrice": preserve},
                               {"subscription": ref("subscriptions", sid), "territory": ref("territories", territory),
                                "subscriptionPricePoint": ref("subscriptionPricePoints", point["id"])})}
            self.ops.append(op)
            if increase:
                self.warnings.append(f"{sub['product_id']} / {territory}: existing subscriber prices may increase. " + CONSENT)

    def offers(self, sub, current, sid):
        for intro, key, typ in ((True, "introductory_offers", "subscriptionIntroductoryOffers"),
                                (False, "promotional_offers", "subscriptionPromotionalOffers")):
            existing = current["introductoryOffers" if intro else "promotionalOffers"]
            for index, offer in enumerate(sub.get(key, [])):
                values = {"duration": offer["duration"], "offerMode": offer["mode"], "numberOfPeriods": offer["periods"]}
                rels = {"subscription": ref("subscriptions", sid)}
                if intro:
                    values.update({"startDate": offer.get("start_date"), "endDate": offer.get("end_date")})
                    rels["territory"] = ref("territories", offer["territory"])
                    if offer["mode"] != "FREE_TRIAL":
                        point = self.point(sid, offer["territory"], offer["price"])
                        rels["subscriptionPricePoint"] = ref("subscriptionPricePoints", point["id"])
                    matches = [o for o in existing if rel_id(o, "territory") == offer["territory"]]
                    equal = any(all(attrs(o).get(k) == v for k, v in values.items()) and
                                all(rel_id(o, k) == v["id"] for k, v in rels.items() if k != "subscription")
                                for o in matches)
                    request = body(typ, values, rels)
                else:
                    values.update({"name": offer["name"], "offerCode": offer["offer_code"]})
                    matches = [o for o in existing if attrs(o).get("offerCode") == offer["offer_code"]]
                    wanted = {t: self.point(sid, t, p)["id"] for t, p in offer["prices"].items()}
                    equal = False
                    for old in matches:
                        rows = self.client.get_all(f"/v1/subscriptionPromotionalOffers/{old['id']}/prices", {"limit": 200})
                        have = {rel_id(p, "territory"): rel_id(p, "subscriptionPricePoint") for p in rows}
                        equal = all(attrs(old).get(k) == v for k, v in values.items()) and have == wanted
                    # UNCONFIRMED: inline promotional price linkage; see references/subscriptions.md.
                    included = []
                    for i, (territory, point_id) in enumerate(sorted(wanted.items())):
                        inline = body("subscriptionPromotionalOfferPrices", relationships={
                            "territory": ref("territories", territory),
                            "subscriptionPricePoint": ref("subscriptionPricePoints", point_id)}, rid=f"${{price-{i}}}")["data"]
                        included.append(inline)
                    rels["prices"] = [ref(p["type"], p["id"]) for p in included]
                    request = body(typ, values, rels)
                    request["included"] = included
                if equal:
                    continue
                if matches:
                    self.blockers.append(f"{sub['product_id']}: existing {key} differs; edit it in the browser. Never deleted.")
                    continue
                self.ops.append({"key": f"offer/{sid}/{key}/{index}", "title": f"{sub['product_id']} {key} {index + 1}",
                                 "method": "POST", "path": f"/v1/{typ}", "body": request, "before": None})

    def screenshot(self, sub, current, sid):
        if not sub.get("review_screenshot"):
            return
        path = self.kit.screenshot(sub["review_screenshot"])
        checksum = hashlib.md5(path.read_bytes()).hexdigest()
        old = (current or {}).get("screenshot")
        if old:
            if attrs(old).get("sourceFileChecksum") == checksum:
                state = attrs(old).get("assetDeliveryState", {}).get("state")
                if state != "COMPLETE":
                    self.blockers.append(f"{sub['product_id']}: review screenshot is {state or 'not verified complete'}; check status")
                return
            self.blockers.append(f"{sub['product_id']}: review screenshot differs or has no checksum; replace in browser (no deletes)")
            return
        self.ops.append({"key": f"screenshot/{sub['product_id']}", "title": f"{sub['product_id']} review screenshot",
                         "method": "POST", "path": "/v1/subscriptionAppStoreReviewScreenshots", "before": None,
                         "file": sub["review_screenshot"], "sha256": digest(path.read_bytes()), "md5": checksum,
                         "body": body("subscriptionAppStoreReviewScreenshots", {"fileName": path.name, "fileSize": path.stat().st_size},
                                      {"subscription": ref("subscriptions", sid)})})

    def build(self):
        all_subs = [s for g in self.live["groups"] for s in g["subscriptions"]]
        first = not any(attrs(s["resource"]).get("state") == "APPROVED" for s in all_subs)
        for gi, group in enumerate(self.kit.config["groups"]):
            matches = [g for g in self.live["groups"] if (g["resource"]["id"] == group["id"] if group.get("id") else
                        attrs(g["resource"]).get("referenceName") == group["reference_name"])]
            if len(matches) > 1 or (group.get("id") and not matches):
                raise SubscriptionError("Group id/name is ambiguous or does not belong to this app")
            current_group = matches[0] if matches else None
            gid = self.upsert("subscriptionGroups", current_group["resource"] if current_group else None,
                              {"referenceName": group["reference_name"]}, {"app": ref("apps", self.live["app"]["id"])},
                              f"group/{gi}", group["reference_name"])
            for locale, loc in group["localizations"].items():
                cur = unique(current_group["localizations"], "locale", locale) if current_group else None
                values = {"locale": locale, "name": loc["name"]}
                if "custom_app_name" in loc:
                    values["customAppName"] = loc["custom_app_name"]
                self.upsert("subscriptionGroupLocalizations", cur, values, {"subscriptionGroup": ref("subscriptionGroups", gid)},
                            f"group-loc/{gi}/{locale}", f"{group['reference_name']} / {locale}")
            for si, sub in enumerate(group["subscriptions"]):
                candidates = [s for s in all_subs if attrs(s["resource"]).get("productId") == sub["product_id"]]
                if len(candidates) > 1:
                    raise SubscriptionError("Duplicate live product IDs")
                cur = candidates[0] if candidates else None
                if cur and (not current_group or cur not in current_group["subscriptions"]):
                    raise SubscriptionError(f"{sub['product_id']}: product already belongs to another group; cannot move it")
                values = {"name": sub["reference_name"], "subscriptionPeriod": sub["duration"], "groupLevel": sub["group_level"]}
                if "review_note" in sub:
                    values["reviewNote"] = sub["review_note"]
                if "family_sharing" in sub:
                    values["familySharable"] = sub["family_sharing"]
                if cur:
                    a = attrs(cur["resource"])
                    if a.get("familySharable") and sub.get("family_sharing") is False:
                        self.blockers.append(f"{sub['product_id']}: Family Sharing cannot be turned off")
                    if a.get("subscriptionPeriod") != sub["duration"] and a.get("state") != "MISSING_METADATA":
                        self.blockers.append(f"{sub['product_id']}: duration may be immutable after submission; use the browser")
                else:
                    values["productId"] = sub["product_id"]
                sid = self.upsert("subscriptions", cur["resource"] if cur else None, values,
                                  {"group": ref("subscriptionGroups", gid)}, f"sub/{gi}/{si}", sub["product_id"])
                for locale, loc in sub["localizations"].items():
                    row = unique(cur["subscriptionLocalizations"], "locale", locale) if cur else None
                    self.upsert("subscriptionLocalizations", row, {"locale": locale, **loc},
                                {"subscription": ref("subscriptions", sid)}, f"sub-loc/{gi}/{si}/{locale}",
                                f"{sub['product_id']} / {locale}")
                self.screenshot(sub, cur, sid)
                if cur:
                    self.prices(sub, cur, sid)
                    self.offers(sub, cur, sid)
                    if attrs(cur["resource"]).get("state") == "READY_TO_SUBMIT":
                        self.submit.append({"id": sid, "product_id": sub["product_id"]})
                    elif attrs(cur["resource"]).get("state") not in {
                            "APPROVED", "WAITING_FOR_REVIEW", "IN_REVIEW", "PENDING_BINARY_APPROVAL"}:
                        self.submission_blockers.append(
                            f"{sub['product_id']}: {attrs(cur['resource']).get('state', 'unknown')}; resolve readiness in App Store Connect")
                else:
                    self.deferred.append(f"{sub['product_id']}: create first, then plan again to resolve prices and offers")
                if sub.get("offer_codes"):
                    self.warnings.append(f"{sub['product_id']}: configure offer codes in App Store Connect in the browser")
        return {"schema": 1, "kit": str(self.kit.path), "fingerprint": self.kit.fingerprint(),
                "app_id": self.live["app"]["id"], "operations": self.ops, "warnings": self.warnings,
                "blockers": self.blockers, "deferred": self.deferred, "first_subscription": first,
                "submit": self.submit, "submission_blockers": self.submission_blockers}


def write_plan(kit, plan):
    public = kit.public(plan)
    (kit.path / (PLAN + ".json")).write_text(json.dumps(public, indent=2, ensure_ascii=False) + "\n")
    lines = ["# Subscription plan", "", "Review this plan before apply --yes. Submit is a separate approval.", "",
             "Uses the deprecated v1 localization/submission workflow. No resources are deleted.", ""]
    for op in public["operations"]:
        lines += [f"## {op['title']}", "", f"{op['method']} `{op['path']}`", "", "Before:",
                  "```json", json.dumps(op["before"], indent=2, ensure_ascii=False), "```", "After:",
                  "```json", json.dumps(op["body"], indent=2, ensure_ascii=False), "```", ""]
        if op.get("file"):
            lines += [f"File: `{op['file']}`; SHA-256 `{op['sha256']}`", ""]
    for label in ("blockers", "warnings", "deferred", "submission_blockers"):
        lines += [f"- {label}: {s}" for s in public[label]]
    lines += ["", "First subscription: attach to an app version in the browser." if plan["first_subscription"] else
              "Eligible standalone submissions: " + ", ".join(s["product_id"] for s in public["submit"]), ""]
    (kit.path / (PLAN + ".md")).write_text("\n".join(lines))


def record_progress(kit, key, live, note):
    path = kit.path / cg.PROGRESS_FILE
    progress = load(path)
    progress.setdefault("steps", {})["subscriptions/" + key] = {
        "status": cg.STATUSES[2], "date": dt.date.today().isoformat(), "live": live, "note": note}
    path.write_text(cg.PROGRESS_HEADER + yaml.safe_dump(kit.public(progress), sort_keys=False, allow_unicode=True))


def resolve_refs(value, ids):
    if isinstance(value, dict):
        return {k: resolve_refs(v, ids) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_refs(v, ids) for v in value]
    if isinstance(value, str) and value.startswith("$") and not value.startswith("${"):
        if value[1:] not in ids:
            raise SubscriptionError("Unresolved plan resource: " + value)
        return ids[value[1:]]
    return value


def apply_plan(client, kit, plan, price_increase_ok=False):
    if plan["blockers"]:
        raise SubscriptionError("Resolve plan blockers before applying")
    if any(op.get("price_increase") for op in plan["operations"]) and not price_increase_ok:
        raise SubscriptionError("Refused existing subscriber price change without --price-increase-ok. " + CONSENT)
    for op in plan["operations"]:
        if op.get("file") and digest(kit.screenshot(op["file"]).read_bytes()) != op["sha256"]:
            raise SubscriptionError("Screenshot changed after approval; plan again")
    ids = {}
    for op in plan["operations"]:
        request = resolve_refs(op["body"], ids)
        result = getattr(client, op["method"].lower())(op["path"], request)
        row = (result or {}).get("data")
        rid = (row or {}).get("id") or request["data"].get("id")
        if not rid:
            raise SubscriptionError("Write returned no resource id; re-plan before retrying")
        ids[op["key"]] = rid
        path = f"/v1/{request['data']['type']}/{rid}"
        if op.get("file"):
            file_path = kit.screenshot(op["file"])
            if digest(file_path.read_bytes()) != op["sha256"]:
                raise SubscriptionError("Screenshot changed after approval; plan again")
            if not client.dry_run and not attrs(row).get("uploadOperations"):
                raise SubscriptionError("Screenshot reservation returned no upload operations")
            client.upload_operations(attrs(row).get("uploadOperations", []), file_path)
            client.patch(path, body("subscriptionAppStoreReviewScreenshots", {
                "uploaded": True, "sourceFileChecksum": op["md5"]}, rid=rid))
        if client.dry_run:
            continue
        is_price = request["data"]["type"] == "subscriptionPrices"
        if is_price:
            sid = rel_id(request["data"], "subscription")
            rows = client.get_all(f"/v1/subscriptions/{sid}/prices", {"limit": 200})
            got = next((r for r in rows if r["id"] == rid), None)
        else:
            got = one(client, path)
        if not got:
            raise SubscriptionError("Re-read failed after write; plan again")
        desired = dict(request["data"].get("attributes", {}))
        if is_price:
            desired.pop("preserveCurrentPrice", None)  # Write option; response exposes preserved cohorts instead.
            if desired.get("startDate") is None and attrs(got).get("startDate") == dt.date.today().isoformat():
                desired["startDate"] = attrs(got)["startDate"]
        if any(attrs(got).get(k) != v for k, v in desired.items()):
            raise SubscriptionError("Re-read attributes differ from the approved request; plan again")
        for key, rel in request["data"].get("relationships", {}).items():
            if is_price and key == "subscription":
                continue  # The parent collection establishes ownership; price rows have no subscription link.
            data = rel["data"]
            if isinstance(data, dict) and rel_id(got, key) != data["id"]:
                raise SubscriptionError("Re-read relationship differs from the approved request; plan again")
        if op.get("file"):
            for attempt in range(6):
                state = attrs(got).get("assetDeliveryState", {}).get("state")
                if state in {"COMPLETE", "FAILED"}:
                    break
                time.sleep(1)
                got = one(client, path)
            if state != "COMPLETE" or attrs(got).get("sourceFileChecksum") != op["md5"]:
                raise SubscriptionError("Review screenshot is not verified COMPLETE; check status before submitting")
        if request["data"]["type"] == "subscriptionPromotionalOffers":
            rows = client.get_all(f"/v1/subscriptionPromotionalOffers/{rid}/prices", {"limit": 200})
            expected = {(rel_id(p, "territory"), rel_id(p, "subscriptionPricePoint")) for p in request.get("included", [])}
            actual = {(rel_id(p, "territory"), rel_id(p, "subscriptionPricePoint")) for p in rows}
            if expected != actual:
                raise SubscriptionError("Promotional offer prices did not match on re-read")
        verified = {k: attrs(got).get(k) for k in desired}
        if is_price:
            verified["requested_preserve_current_price"] = request["data"]["attributes"]["preserveCurrentPrice"]
        if op.get("file"):
            verified.update({"sourceFileChecksum": op["md5"], "state": "COMPLETE"})
        record_progress(kit, op["key"], {"id": rid, **verified}, "Applied through subscriptions.py; re-read and matching.")


def submit_plan(client, kit, plan):
    if plan["first_subscription"]:
        # UNCONFIRMED for subscriptions: where Apple's page offers the first submission (own page vs version page).
        raise SubscriptionError("The first subscription must be submitted from the subscription's own page (Add for Review), "
                                "together with a new app version; if the page instead shows an In-App Purchases and "
                                "Subscriptions section on the version page, use that. This command cannot attach them. "
                                f"https://appstoreconnect.apple.com/apps/{plan['app_id']}/distribution")
    if plan["operations"] or plan["deferred"] or plan["blockers"]:
        raise SubscriptionError("Apply the metadata/prices, resolve blockers, then plan again before submitting")
    if plan["submission_blockers"]:
        raise SubscriptionError("Cannot submit: " + "; ".join(plan["submission_blockers"]))
    if not plan["submit"]:
        print("No subscriptions are READY_TO_SUBMIT")
        return
    for item in plan["submit"]:
        # Deprecated but explicitly requested. Do not silently substitute reviewSubmissions.
        client.post("/v1/subscriptionSubmissions", body("subscriptionSubmissions", relationships={
            "subscription": ref("subscriptions", item["id"])}))
        if not client.dry_run:
            got = one(client, f"/v1/subscriptions/{item['id']}")
            if attrs(got).get("state") not in {"WAITING_FOR_REVIEW", "IN_REVIEW", "PENDING_BINARY_APPROVAL", "APPROVED"}:
                raise SubscriptionError("Submission not confirmed on re-read; use status before retrying")
            record_progress(kit, "submit/" + item["product_id"], {"id": item["id"], "state": attrs(got)["state"]},
                            "Submitted through subscriptions.py; state re-read.")


def main(argv=None, client=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("check", "status", "plan", "apply", "submit"))
    parser.add_argument("kit")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--price-increase-ok", action="store_true")
    for key in ("key-id", "issuer-id", "key-path"):
        parser.add_argument("--" + key)
    args = parser.parse_args(argv)
    if args.command in {"apply", "submit"} and not args.yes and not args.dry_run:
        print(f"{args.command} changes App Store Connect: review subscriptions-plan.md, then run with --yes (or --dry-run).")
        return 2
    kit = None
    try:
        kit = Kit(args.kit)
        errors = check(kit)
        if errors:
            for error in errors:
                print(kit.public("error: " + error))
            return 1
        if args.command == "check":
            print("subscriptions.yaml: checks passed (see UNCONFIRMED limits in references/subscriptions.md)")
            return 0
        if client is None:
            client = asc_api.make_client(args, kit=kit.path, dry_run=args.dry_run)
        client.dry_run = args.dry_run or client.dry_run
        live = read_live(client, kit)
        if args.command == "status":
            (kit.path / "subscriptions-live.json").write_text(json.dumps(kit.public(live), indent=2, ensure_ascii=False) + "\n")
            for group in live["groups"]:
                print(kit.public(attrs(group["resource"]).get("referenceName", "")))
                for sub in group["subscriptions"]:
                    a = attrs(sub["resource"])
                    print(kit.public(f"  {a.get('productId')}: {a.get('state', 'unknown')}; level {a.get('groupLevel')}"))
            return 0
        plan = Planner(client, kit, live).build()
        if args.command == "plan":
            write_plan(kit, plan)
            print(f"wrote {PLAN}.md and .json: {len(plan['operations'])} change(s), {len(plan['blockers'])} blocker(s)")
            for message in plan["warnings"] + plan["deferred"] + plan["blockers"]:
                print(kit.public(message))
            return 1 if plan["blockers"] else 0
        saved = kit.path / (PLAN + ".json")
        if not saved.exists():
            raise SubscriptionError("Run plan KIT first and review subscriptions-plan.md")
        if json.loads(saved.read_text()) != kit.public(plan):
            raise SubscriptionError("The kit, assets, live state or plan changed. Run plan KIT and review it again")
        if args.command == "apply":
            apply_plan(client, kit, plan, args.price_increase_ok)
        else:
            submit_plan(client, kit, plan)
        if client.dry_run:
            for request in client.recorded:
                print("would send: " + json.dumps(kit.public(request), ensure_ascii=False))
            print("dry run: no writes sent")
        else:
            print("Re-read completed. Run plan KIT again before the next apply or submit.")
        return 0
    except (SubscriptionError, asc_api.ASCError, asc_api.ConfigError, OSError, ValueError, InvalidOperation, yaml.YAMLError) as e:
        message = "error: " + str(e)
        print(kit.public(message) if kit else "error: cannot read kit YAML; check file syntax and mapping structure")
        return 1


if __name__ == "__main__":
    sys.exit(main())
