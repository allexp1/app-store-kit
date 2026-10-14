"""An in-memory stand-in for the App Store Connect API, used as the client's transport in tests. No network.

Resources live in a dict keyed by id: {"type", "id", "attributes", "relationships"}. Paths follow the JSON:API
conventions asc_sync.py uses: /vN/<type>[/<id>[/<child>|/relationships/<rel>]].
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
}
TO_ONE = {"ageRatingDeclaration", "appStoreReviewDetail", "build", "appStoreVersionPhasedRelease", "assetLibrary",
          "image", "appStoreReviewScreenshot"}
UPLOADABLE = {"appAssetLibraryImages", "appAssetLibraryVideos", "inAppPurchaseImages",
              "inAppPurchaseAppStoreReviewScreenshots"}


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
                 "displayClassId": "IPAD_13_DISPLAY"}]}}]}
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
        self.calls.append((method, u.path, q, js))
        if (method, u.path) in self.fail:
            status, code = self.fail[(method, u.path)]
            return self._err(status, code)
        parts = [p for p in u.path.split("/") if p][1:]  # drop v1/v2
        try:
            if method == "GET":
                doc = self._get(parts, q)
            elif method == "POST":
                doc = self._post(parts, js)
                return 201, {"x-rate-limit": "user-hour-lim:3500;user-hour-rem:3400;"}, json.dumps(doc).encode()
            elif method == "PATCH":
                doc = self._patch(parts, js)
            elif method == "DELETE":
                self.store.pop(parts[1], None)
                return 204, {}, b""
            else:
                return self._err(405, "METHOD")
        except KeyError:
            return self._err(404, "NOT_FOUND")
        return 200, {"x-rate-limit": "user-hour-lim:3500;user-hour-rem:3400;"}, json.dumps(doc).encode()

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
            loc = rels["appStoreVersionLocalization"][1]
            n = len([p for p in self.of_type(typ) if p["relationships"]["appStoreVersionLocalization"]["data"]["id"]
                     == loc and p["attributes"].get("placementGroup") == a.get("placementGroup")])
            r["attributes"]["placementGroupPosition"] = n
        if typ == "appAssetLibraryPlacementOrderingRequests":
            for i, ref in enumerate(d["relationships"]["orderedPlacements"]["data"]):
                self.store[ref["id"]]["attributes"]["placementGroupPosition"] = i + 1
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
