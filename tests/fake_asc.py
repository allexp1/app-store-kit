"""An in-memory stand-in for the App Store Connect API, used as the client's transport in tests. No network.

Resources live in a dict keyed by id: {"type", "id", "attributes", "relationships"}. Paths follow the JSON:API
conventions asc_sync.py uses: /vN/<type>[/<id>[/<child>|/relationships/<rel>]].

The fake is strict where a real mistake would fail against Apple: the path's /v1 or /v2 must be the one
references/asc-api.md gives for that resource, a request body must have the JSON:API top-level shape
(data.type matching the path, attributes and relationships objects, nothing else), and a PATCH must name the
resource it changes. A violation raises AssertionError, so the test fails instead of the code seeing a 404.
"""
from __future__ import annotations

import json
import urllib.parse

# Child path segment → resource type (to-one children are found by a forward or reverse relationship).
CHILD = {"items": "reviewSubmissionItems", 
    "appStoreVersions": "appStoreVersions", "appInfos": "appInfos", "appInfoLocalizations": "appInfoLocalizations",
    "ageRatingDeclaration": "ageRatingDeclarations", "appStoreVersionLocalizations": "appStoreVersionLocalizations",
    "appStoreReviewDetail": "appStoreReviewDetails", "build": "builds",
    "appStoreVersionPhasedRelease": "appStoreVersionPhasedReleases", "placements": "appAssetLibraryPlacements",
    "assetLibrary": "appAssetLibraries", "accessibilityDeclarations": "accessibilityDeclarations",
    "inAppPurchasesV2": "inAppPurchases", "inAppPurchaseVersions": "inAppPurchaseVersions",
    "inAppPurchaseLocalizations": "inAppPurchaseLocalizations", "image": "inAppPurchaseImages",
    "appStoreReviewScreenshot": "inAppPurchaseAppStoreReviewScreenshots", "manualPrices": "inAppPurchasePrices",
    "pricePoints": "inAppPurchasePricePoints",
    # growth: custom product pages, product page optimization, in-app events
    "appCustomProductPages": "appCustomProductPages", "appCustomProductPageVersions": "appCustomProductPageVersions",
    "appCustomProductPageLocalizations": "appCustomProductPageLocalizations",
    "appStoreVersionExperimentsV2": "appStoreVersionExperiments",
    "appStoreVersionExperimentTreatments": "appStoreVersionExperimentTreatments",
    "appStoreVersionExperimentTreatmentLocalizations": "appStoreVersionExperimentTreatmentLocalizations",
    "appEvents": "appEvents", "localizations": "appEventLocalizations",
}
# Relationship names a placement can hang on (exactly one per placement).
PLACEMENT_PARENTS = ("appStoreVersionLocalization", "appCustomProductPageLocalization",
                     "appStoreVersionExperimentTreatmentLocalization", "appEventLocalization")
TO_ONE = {"ageRatingDeclaration", "appStoreReviewDetail", "build", "appStoreVersionPhasedRelease", "assetLibrary",
          "image", "appStoreReviewScreenshot"}
UPLOADABLE = {"appAssetLibraryImages", "appAssetLibraryVideos", "inAppPurchaseImages",
              "inAppPurchaseAppStoreReviewScreenshots"}
# Path roots served under /v2 (asc-api.md §6 and growth-marketing.md); every other root is /v1.
V2_ROOTS = {"inAppPurchases", "inAppPurchaseLocalizations", "inAppPurchaseImages", "appStoreVersionExperiments"}
# Path roots whose ids are another type's ids (Apple: a purchase's price schedule id is the purchase id).
ID_ALIAS = {"inAppPurchasePriceSchedules": "inAppPurchases"}
DATA_KEYS = {"type", "id", "attributes", "relationships"}


def check_version(path):
    segs = [p for p in path.split("/") if p]
    assert len(segs) >= 2 and segs[0] in ("v1", "v2"), f"{path}: no /v1 or /v2 prefix"
    want = "v2" if segs[1] in V2_ROOTS else "v1"
    assert segs[0] == want, f"{path}: {segs[1]} lives under /{want}, not /{segs[0]}"


def check_resource(d, where, typ=None, need_id=False):
    assert isinstance(d, dict), f"{where}: data must be an object"
    assert set(d) <= DATA_KEYS, f"{where}: unexpected key(s) {sorted(set(d) - DATA_KEYS)} in data"
    assert isinstance(d.get("type"), str) and d["type"], f"{where}: data.type is missing"
    if typ:
        assert d["type"] == typ, f"{where}: data.type {d['type']!r} doesn't match the path ({typ!r})"
    if need_id:
        assert isinstance(d.get("id"), str), f"{where}: data.id is missing"
    if "attributes" in d:
        assert isinstance(d["attributes"], dict), f"{where}: attributes must be an object"
        assert not {"id", "type"} & set(d["attributes"]), f"{where}: id/type belong in data, not attributes"
    for k, v in (d.get("relationships") or {}).items():
        assert isinstance(v, dict) and set(v) == {"data"}, f"{where}: relationship {k} must be {{data: ...}}"
        refs = v["data"] if isinstance(v["data"], list) else [v["data"]]
        for r in refs:
            assert isinstance(r, dict) and set(r) == {"type", "id"}, f"{where}: relationship {k} needs type + id"


def check_linkage(js, where, to_many=True):
    assert isinstance(js, dict) and set(js) == {"data"}, f"{where}: a relationship body is {{data: ...}}"
    refs = js["data"]
    if to_many:
        assert isinstance(refs, list), f"{where}: a to-many relationship body is a list"
    else:
        refs = [refs]
    for r in refs:
        assert isinstance(r, dict) and set(r) == {"type", "id"}, f"{where}: linkage needs type + id only"


class FakeASC:
    def __init__(self):
        self.store, self.calls, self.n = {}, [], 0
        self.refdata = {"data": [{"type": "appAssetLibraryRefData", "id": "ref", "attributes": {
            "placementProfileGroups": [
                # the live shape, read 2026-10-14 (data is a list; one object)
                {"placementProfileGroupId": "MAC_PROFILE", "platform": "MAC_APP_STORE", "displayClassId": "DEFAULT"},
                {"placementProfileGroupId": "IPHONE_DYNAMIC_ISLAND_MEDIUM_PROFILE", "platform": "IPHONE_APP_STORE",
                 "displayClassId": "IPHONE_DYNAMIC_ISLAND_MEDIUM_DISPLAY"},
                {"placementProfileGroupId": "IMESSAGE_IPHONE_DYNAMIC_ISLAND_MEDIUM_PROFILE",
                 "platform": "IPHONE_APP_STORE", "displayClassId": "IPHONE_DYNAMIC_ISLAND_MEDIUM_DISPLAY"},
                {"placementProfileGroupId": "IPAD_13_PROFILE", "platform": "IPAD_APP_STORE",
                 "displayClassId": "IPAD_13_DISPLAY"},
                {"placementProfileGroupId": "DEFAULT_PROFILE", "platform": "ANY", "displayClassId": "DEFAULT"}],
            "placementTypes": [
                {"placementTypeId": "PRODUCT_PAGE_HEADER_ASSET", "acceptsAssetCategories": ["CREATIVE_ASSETS"],
                 "specMappings": [{"placementGroupId": "DEFAULT_PROFILE", "specs": ["s1", "s2"]}]},
                {"placementTypeId": "APP_STORE_SEARCH_RESULTS_ASSET", "acceptsAssetCategories": ["CREATIVE_ASSETS"],
                 "specMappings": [{"placementGroupId": "DEFAULT_PROFILE", "specs": ["s1", "s3"]}]}]}}]}
        self.refdata["data"][0]["attributes"]["placementTypes"] += [
            {"placementTypeId": t, "acceptsAssetCategories": ["CREATIVE_ASSETS"],
             "specMappings": [{"placementGroupId": "DEFAULT_PROFILE", "specs": ["e1"]}]}
            for t in ("EVENT_CARD_ASSET", "EVENT_DETAILS_PAGE_ASSET")]
        self.app_keywords = {}  # locale → [keyword id] for GET /v1/apps/{id}/searchKeywords
        self.fail = {}        # (method, path) → (status, code) to return instead
        self.on_create = {}   # type → callback(resource)

    # ---------------------------------------------------------------- seeding
    def add(self, typ, attributes=None, rels=None, id=None):
        self.n += 1
        id = id or f"{typ[:6]}{self.n}"
        self.store[id] = {"type": typ, "id": id, "attributes": dict(attributes or {}),
                          "relationships": {k: {"data": {"type": t, "id": i}} for k, (t, i) in (rels or {}).items()}}
        return id

    def of_type(self, typ):
        return [r for r in self.store.values() if r["type"] == typ]

    def writes(self):
        return [(m, p) for m, p, _, _ in self.calls if m not in ("GET",) and not p.startswith("upload:")]

    # ---------------------------------------------------------------- transport
    def __call__(self, method, url, headers, body):
        u = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        js = json.loads(body) if body and u.netloc != "upload.example" else None
        if u.netloc == "upload.example":
            assert "Authorization" not in headers, "upload parts must not carry the JWT"
            self.calls.append((method, "upload:" + u.path, q, len(body or b"")))
            return 200, {}, b""
        assert u.scheme == "https" and u.netloc == "api.appstoreconnect.apple.com", f"request to {url}"
        check_version(u.path)
        self.calls.append((method, u.path, q, js))
        if (method, u.path) in self.fail:
            status, code = self.fail[(method, u.path)]
            return self._err(status, code)
        parts = [p for p in u.path.split("/") if p][1:]  # the version was checked above
        self._check_body(method, parts, js, u.path)
        try:
            if method == "GET":
                doc = self._get(parts, q)
            elif method == "POST" and len(parts) == 4 and parts[2] == "relationships":
                r = self.store[parts[1]]
                r["keywords"] = r.get("keywords", []) + [d["id"] for d in js["data"]]
                return 204, {}, b""
            elif method == "POST":
                doc = self._post(parts, js)
                return 201, {"x-rate-limit": "user-hour-lim:3500;user-hour-rem:3400;"}, json.dumps(doc).encode()
            elif method == "PATCH":
                doc = self._patch(parts, js)
            elif method == "DELETE" and len(parts) == 4 and parts[2] == "relationships":
                r = self.store[parts[1]]
                gone = {d["id"] for d in js["data"]}
                r["keywords"] = [k for k in r.get("keywords", []) if k not in gone]
                return 204, {}, b""
            elif method == "DELETE":
                self.store.pop(parts[1], None)
                return 204, {}, b""
            else:
                return self._err(405, "METHOD")
        except KeyError:
            return self._err(404, "NOT_FOUND")
        return 200, {"x-rate-limit": "user-hour-lim:3500;user-hour-rem:3400;"}, json.dumps(doc).encode()

    def _check_body(self, method, parts, js, path):
        rel = len(parts) == 4 and parts[2] == "relationships"
        if method == "GET":
            assert js is None, f"GET {path} with a body"
            if len(parts) >= 2 and parts[1] in self.store:
                want = ID_ALIAS.get(parts[0], parts[0])
                got = self.store[parts[1]]["type"]
                assert got == want or (len(parts) > 2 and parts[0] in ID_ALIAS), \
                    f"GET {path}: {parts[1]} is a {got}, not a {parts[0]}"
            return
        if rel:
            check_linkage(js, f"{method} {path}", to_many=method != "PATCH")
            return
        if method == "DELETE":
            assert js is None and len(parts) == 2, f"DELETE {path}: delete one resource, without a body"
            return
        assert isinstance(js, dict) and "data" in js and set(js) <= {"data", "included"}, \
            f"{method} {path}: the body is {{data, included?}}"
        if method == "POST":
            assert len(parts) == 1, f"POST {path}: create on the collection path"
            check_resource(js["data"], f"POST {path}", typ=parts[0])
            assert "id" not in js["data"], f"POST {path}: a new resource has no id"
            for inc in js.get("included") or []:
                check_resource(inc, f"POST {path} included", need_id=True)
        elif method == "PATCH":
            assert len(parts) == 2, f"PATCH {path}: patch one resource"
            check_resource(js["data"], f"PATCH {path}", typ=parts[0], need_id=True)
            assert js["data"]["id"] == parts[1], f"PATCH {path}: data.id {js['data']['id']!r} isn't the path's id"
            if parts[1] in self.store:
                assert self.store[parts[1]]["type"] == parts[0], f"PATCH {path}: the id is another type"

    def _err(self, status, code):
        return status, {}, json.dumps({"errors": [{"status": str(status), "code": code, "title": "fake error",
                                                   "detail": f"{code} from the fake"}]}).encode()

    def _get(self, parts, q):
        if parts == ["appAssetLibraryRefData"]:
            return self.refdata
        if len(parts) == 1:
            return {"data": self._filter(self.of_type(parts[0]), q), "links": {}}
        if len(parts) == 2:
            r = self.store[parts[1]]
            return {"data": r, "included": self._included(r, q)}
        parent, seg = self.store[parts[1]], parts[2]
        if seg == "searchKeywords":
            ids = self.app_keywords.get(q.get("filter[locale]"), []) if parent["type"] == "apps" \
                else parent.get("keywords", [])
            return {"data": [{"type": "appKeywords", "id": k} for k in ids], "links": {}}
        typ = CHILD[seg]
        if seg in TO_ONE:
            fwd = (parent["relationships"].get(seg) or {}).get("data")
            if fwd:
                return {"data": self.store.get(fwd["id"])}
            hit = self._children(parent, typ)
            return {"data": hit[0] if hit else None}
        data = self._filter(self._children(parent, typ), q)
        if q.get("sort") == "placementGroupPosition":
            data.sort(key=lambda r: r["attributes"].get("placementGroupPosition") or 0)
        inc = [i for r in data for i in self._included(r, q)]
        return {"data": data, "included": inc, "links": {}}

    def _children(self, parent, typ):
        return [r for r in self.store.values() if r["type"] == typ and any(
            (v.get("data") or {}).get("id") == parent["id"] for v in r["relationships"].values()
            if isinstance(v.get("data"), dict))]

    def _included(self, r, q):
        names = [x for x in (q.get("include") or "").split(",") if x]
        out = []
        for n in names:
            d = (r["relationships"].get(n) or {}).get("data")
            if isinstance(d, dict) and d.get("id") in self.store:
                out.append(self.store[d["id"]])
        return out

    def _filter(self, rows, q):
        for k, v in q.items():
            if not k.startswith("filter[") or "." in k:
                continue
            name, vals = k[7:-1], v.split(",")
            if name in ("territory",):
                continue
            rows = [r for r in rows if str(r["attributes"].get(name)) in vals
                    or ((r["relationships"].get(name) or {}).get("data") or {}).get("id") in vals]
        return rows

    def _post(self, parts, js):
        d = js["data"]
        typ = d["type"]
        a = dict(d.get("attributes") or {})
        if typ in UPLOADABLE:
            a["uploadOperations"] = [{"method": "PUT", "url": f"https://upload.example/{typ}/{self.n + 1}",
                                      "offset": 0, "length": a.get("fileSize", 0),
                                      "requestHeaders": [{"name": "Content-Type", "value": "image/jpeg"}]}]
            a["state"] = "AWAITING_UPLOAD"
        rels = {k: (v["data"]["type"], v["data"]["id"]) for k, v in (d.get("relationships") or {}).items()
                if isinstance(v.get("data"), dict)}
        rid = self.add(typ, a, rels)
        r = self.store[rid]
        for k, v in (d.get("relationships") or {}).items():
            if isinstance(v.get("data"), list):
                r["relationships"][k] = {"data": v["data"]}
        if typ == "appAssetLibraryPlacements":
            parent = next(k for k in PLACEMENT_PARENTS if k in rels)
            loc = rels[parent][1]
            n = len([p for p in self.of_type(typ) if ((p["relationships"].get(parent) or {}).get("data") or {})
                     .get("id") == loc and p["attributes"].get("placementGroup") == a.get("placementGroup")])
            r["attributes"]["placementGroupPosition"] = n
        if typ == "appAssetLibraryPlacementOrderingRequests":
            for i, ref in enumerate(d["relationships"]["orderedPlacements"]["data"]):
                self.store[ref["id"]]["attributes"]["placementGroupPosition"] = i + 1
        if typ == "appCustomProductPages":  # inline version + localization, as Apple's example request
            r["attributes"].setdefault("visible", True)
            new = {}
            for inc in js.get("included") or []:
                if inc["type"] == "appCustomProductPageVersions":
                    new[inc["id"]] = self.add(inc["type"], {**(inc.get("attributes") or {}), "version": "1",
                                                            "state": "PREPARE_FOR_SUBMISSION"},
                                              {"appCustomProductPage": (typ, rid)})
            for inc in js.get("included") or []:
                if inc["type"] == "appCustomProductPageLocalizations":
                    self.add(inc["type"], inc.get("attributes"),
                             {"appCustomProductPageVersion": ("appCustomProductPageVersions", next(iter(new.values())))})
            r["relationships"].pop("appCustomProductPageVersions", None)
        if typ == "appCustomProductPageVersions":
            r["attributes"].setdefault("state", "PREPARE_FOR_SUBMISSION")
        if typ == "appStoreVersionExperiments":
            r["attributes"].setdefault("state", "PREPARE_FOR_SUBMISSION")
        if typ == "appEvents":
            r["attributes"].setdefault("eventState", "DRAFT")
        if typ == "appStoreVersions":
            r["attributes"].setdefault("appVersionState", "PREPARE_FOR_SUBMISSION")
        if typ == "inAppPurchasePriceSchedules":  # replaces the purchase's manual prices (inline included prices)
            iap = rels["inAppPurchase"][1]
            for old in [x for x in self.of_type("inAppPurchasePrices")
                        if (x["relationships"].get("inAppPurchaseV2") or {}).get("data", {}).get("id") == iap]:
                del self.store[old["id"]]
            for inc in js.get("included") or []:
                assert inc["type"] == "inAppPurchasePrices", "included: inline inAppPurchasePrices only"
                pt = inc["relationships"]["inAppPurchasePricePoint"]["data"]["id"]
                assert self.store[pt]["type"] == "inAppPurchasePricePoints", f"{pt} isn't a price point"
                self.add("inAppPurchasePrices", inc.get("attributes"), {
                    "inAppPurchaseV2": ("inAppPurchases", iap), "inAppPurchasePricePoint": ("inAppPurchasePricePoints", pt)})
        if typ in self.on_create:
            self.on_create[typ](r)
        return {"data": r}

    def _patch(self, parts, js):
        if len(parts) == 4 and parts[2] == "relationships":
            r = self.store[parts[1]]
            r["relationships"][parts[3]] = {"data": js["data"]}
            return None
        r = self.store[parts[1]]
        a = dict(js["data"].get("attributes") or {})
        if a.pop("uploaded", None) and r["type"] in UPLOADABLE:
            r["attributes"]["state"] = "PREPARE_FOR_SUBMISSION"
            a.pop("sourceFileChecksum", None)
        if a.pop("publish", None):
            r["attributes"]["state"] = "PUBLISHED"
        r["attributes"].update(a)
        for k, v in (js["data"].get("relationships") or {}).items():
            r["relationships"][k] = v
        return {"data": r}
