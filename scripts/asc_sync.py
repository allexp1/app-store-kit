#!/usr/bin/env python3
"""Sync the kit into App Store Connect through the official API (references/asc-api.md, API 4.5.1).

Usage:
  asc_sync.py status  KIT                      find the app, its versions and builds; writes KIT/connect-live.json
  asc_sync.py plan    KIT [--locale L ...] [--only AREAS]
                                               compare the kit with the live account; writes KIT/connect-plan.json
                                               and KIT/connect-plan.md (the page the owner reads before saying yes)
  asc_sync.py apply   KIT --yes [--only AREAS] [--dry-run]
                                               execute connect-plan.json in a safe order, re-read every change,
                                               write KIT/connect-assets.json and update KIT/connect-progress.yaml
  asc_sync.py submit  KIT --yes [--dry-run]    reviewSubmissions: create, add the version, submit
  asc_sync.py release KIT --yes [--pause | --resume] [--dry-run]
                                               release a PENDING_DEVELOPER_RELEASE version, or pause/resume phased release

AREAS (comma list for --only): text, media, iap, review, age, accessibility, build, release.
Creating the version itself always runs: everything else depends on it.

Auth: --key-id / --issuer-id / --key-path, else ASC_KEY_ID / ASC_ISSUER_ID / ASC_KEY_PATH, else connect.yaml
`api: {key_id, issuer_id}` with AuthKey_<KID>.p8 found where altool looks (see asc_api.py).

Kit files read: facts.yaml (app.bundle_id, app.version, app.build, locales, monetization.iap, first_version),
metadata.<locale>.yaml, connect.yaml (review_contact, content_rights, age_rating, accessibility, version.release,
version.phased_release, privacy), private.yaml (phone, demo account: sent, never written anywhere),
review-notes.md, screenshots/<locale>/<slot>/*, previews/<locale>/<slot>/*, iap/<file>, connect-assets.json.

Private values never reach the plan, the progress file or the output: they show as [private].
--dry-run prints every write that would be sent (private values masked) and changes nothing.
Exit 0 when everything worked, 1 when an item failed or a refusal applies, 2 for a missing --yes or bad input.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import connect_guide as cg  # noqa: E402
from asc_api import ASCError, Client, ConfigError, make_client  # noqa: E402

AREAS = ("text", "media", "iap", "review", "age", "accessibility", "build", "release")
ORDER = ["version", "text", "age", "build", "release", "review", "accessibility", "iap", "media"]
AREA_TITLES = {"version": "Version", "text": "Store text", "age": "Age rating", "build": "Build",
               "release": "Release", "review": "App Review information", "accessibility": "Accessibility",
               "iap": "In-app purchases", "media": "Screenshots and previews"}
EDITABLE = {"PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED", "METADATA_REJECTED", "INVALID_BINARY"}
LIVE_STATES = {"READY_FOR_DISTRIBUTION", "PROCESSING_FOR_DISTRIBUTION", "REPLACED_WITH_NEW_VERSION"}
PRIVATE = "$private"
MASK = cg.MASK

# Kit slot folder → Asset Library display class. Both iPhone Duo folders share one display class (outer first).
SLOT_CLASS = {
    "iphone-di-large": "IPHONE_DYNAMIC_ISLAND_LARGE_DISPLAY",
    "iphone-di-medium": "IPHONE_DYNAMIC_ISLAND_MEDIUM_DISPLAY",
    "iphone-faceid-large": "IPHONE_FACE_ID_LARGE_DISPLAY",
    "iphone-faceid-medium": "IPHONE_FACE_ID_MEDIUM_DISPLAY",
    "iphone-home-large": "IPHONE_HOME_BUTTON_LARGE_DISPLAY",
    "iphone-home-medium": "IPHONE_HOME_BUTTON_MEDIUM_DISPLAY",
    "iphone-duo-outer": "IPHONE_DUO",
    "iphone-duo-inner": "IPHONE_DUO",
    "ipad-13": "IPAD_13_DISPLAY",
    "ipad-11": "IPAD_11_DISPLAY",
}
IMAGE_EXT = (".png", ".jpg", ".jpeg")
VIDEO_EXT = (".mov", ".mp4", ".m4v")
# Creative assets (header + search results, iOS/iPadOS 27+): KIT/creative/<locale>/<name>.png|jpg|mp4|mov.
# "universal" fills both placements; "header" / "search" override one of them (apple-specs.md › Creative assets).
HEADER, SEARCH = "PRODUCT_PAGE_HEADER_ASSET", "APP_STORE_SEARCH_RESULTS_ASSET"
CREATIVE_NAMES = {"universal": (HEADER, SEARCH), "header": (HEADER,), "search": (SEARCH,)}
CREATIVE_LABEL = {HEADER: "Header", SEARCH: "Search results"}

FREQ_KEYS = {"alcoholTobaccoOrDrugUseOrReferences", "contests", "gamblingSimulated", "gunsOrOtherWeapons",
             "medicalOrTreatmentInformation", "profanityOrCrudeHumor", "sexualContentGraphicAndNudity",
             "sexualContentOrNudity", "horrorOrFearThemes", "matureOrSuggestiveThemes", "violenceCartoonOrFantasy",
             "violenceRealistic", "violenceRealisticProlongedGraphicOrSadistic"}
BOOL_KEYS = {"gambling", "lootBox", "unrestrictedWebAccess", "advertising", "ageAssurance", "healthOrWellnessTopics",
             "messagingAndChat", "parentalControls", "userGeneratedContent", "socialMedia", "socialMediaAgeRestricted"}
PLAIN_KEYS = {"kidsAgeBand", "koreaAgeRatingOverride", "gracRatingClassificationNumber", "developerAgeRatingInfoUrl",
              "ageRatingOverrideV2"}
AGE_IGNORE = {"expected_rating", "intro"}
FREQ = {"none": "NONE", "infrequent": "INFREQUENT", "frequent": "FREQUENT", "infrequent_or_mild": "INFREQUENT",
        "frequent_or_intense": "FREQUENT", "infrequent/mild": "INFREQUENT", "frequent/intense": "FREQUENT"}
OVERRIDE = {"not applicable": "NONE", "none": "NONE", "9+": "NINE_PLUS", "13+": "THIRTEEN_PLUS",
            "16+": "SIXTEEN_PLUS", "18+": "EIGHTEEN_PLUS", "unrated": "UNRATED"}
ACCESS = {"VoiceOver": "supportsVoiceover", "Voice Control": "supportsVoiceControl",
          "Larger Text": "supportsLargerText", "Dark Interface": "supportsDarkInterface",
          "Differentiate Without Color Alone": "supportsDifferentiateWithoutColorAlone",
          "Sufficient Contrast": "supportsSufficientContrast", "Reduced Motion": "supportsReducedMotion",
          "Captions": "supportsCaptions", "Audio Descriptions": "supportsAudioDescriptions"}
DEVICE = {"iphone": "IPHONE", "ipad": "IPAD", "apple tv": "APPLE_TV", "apple watch": "APPLE_WATCH", "mac": "MAC",
          "vision": "VISION", "apple vision pro": "VISION"}
RELEASE_TYPE = {"manual": "MANUAL", "after_approval": "AFTER_APPROVAL", "automatic": "AFTER_APPROVAL",
                "scheduled": "SCHEDULED"}
RELEASE_WORDS = {"MANUAL": cg.RELEASE["manual"], "AFTER_APPROVAL": cg.RELEASE["automatic"],
                 "SCHEDULED": cg.RELEASE["scheduled"]}
IAP_TYPE = {"non-consumable": "NON_CONSUMABLE", "consumable": "CONSUMABLE",
            "non-renewing subscription": "NON_RENEWING_SUBSCRIPTION"}
IAP_EDITABLE = {"PREPARE_FOR_SUBMISSION", "REJECTED", "DEVELOPER_ACTION_NEEDED", "MISSING_METADATA",
                "READY_TO_SUBMIT"}
CONTENT_RIGHTS = {"uses_third_party": "USES_THIRD_PARTY_CONTENT", "none": "DOES_NOT_USE_THIRD_PARTY_CONTENT"}
CATEGORIES = {"BOOKS", "BUSINESS", "DEVELOPER_TOOLS", "EDUCATION", "ENTERTAINMENT", "FINANCE", "FOOD_AND_DRINK",
              "GAMES", "GRAPHICS_AND_DESIGN", "HEALTH_AND_FITNESS", "LIFESTYLE", "MAGAZINES_AND_NEWSPAPERS",
              "MEDICAL", "MUSIC", "NAVIGATION", "NEWS", "PHOTO_AND_VIDEO", "PRODUCTIVITY", "REFERENCE",
              "SHOPPING", "SOCIAL_NETWORKING", "SPORTS", "STICKERS", "TRAVEL", "UTILITIES", "WEATHER", "KIDS"}

LIMITS = {"name": 30, "subtitle": 30, "promotionalText": 170, "description": 4000, "whatsNew": 4000}
FIELD_LABELS = {  # API attribute → the label connect_guide.py uses (progress live values)
    "promotionalText": "Promotional Text", "description": "Description", "keywords": "Keywords",
    "supportUrl": "Support URL", "marketingUrl": "Marketing URL", "whatsNew": "What's New in This Version",
}
PLAN_JSON, PLAN_MD, LIVE_JSON, ASSETS_JSON = "connect-plan.json", "connect-plan.md", "connect-live.json", \
    "connect-assets.json"


class SyncError(Exception):
    pass


# ---------------------------------------------------------------------------------------------------- kit
def _s(v):
    return "" if v is None else str(v).replace("\r\n", "\n").strip()


def truthy(v):
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("yes", "true", "on", "1")


def sha256(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def md5(p):
    return hashlib.md5(pathlib.Path(p).read_bytes()).hexdigest()


class Kit:
    def __init__(self, path, locales=None):
        self.path = pathlib.Path(path)
        self.facts = cg.load_yaml(self.path / "facts.yaml")
        self.conn = cg.load_yaml(self.path / "connect.yaml")
        raw = cg.load_yaml(self.path / "private.yaml")
        self.private = (raw.get("review_contact") or {}) | (raw.get("demo") or {}) | \
            {k: v for k, v in raw.items() if not isinstance(v, dict)}
        self.pvals = cg.private_values(raw)
        self.app = self.facts.get("app") or {}
        metas = sorted(p.name.split(".")[1] for p in self.path.glob("metadata.*.yaml"))
        primary = self.conn.get("locale") or ("en-US" if "en-US" in metas else (metas[0] if metas else "en-US"))
        declared = [str(x) for x in (self.facts.get("locales") or [])]
        self.all_locales = declared or [primary] + [m for m in metas if m != primary]
        self.primary = self.all_locales[0]
        want = [x for v in (locales or []) for x in str(v).split(",") if x.strip()]
        self.locales = [x for x in self.all_locales if not want or x in want]
        self.unknown_locales = [x for x in want if x not in self.all_locales]
        self.meta = {loc: cg.load_yaml(self.path / f"metadata.{loc}.yaml") for loc in self.all_locales}

    @property
    def version(self):
        return str(self.app.get("version") or "")

    @property
    def build(self):
        return str(self.app.get("build") or "")

    @property
    def bundle_id(self):
        return self.app.get("bundle_id")

    def answer(self, *path, default=None):
        node = self.conn
        for k in path:
            node = node.get(k) if isinstance(node, dict) else None
        a = cg.answer(node)[0] if node is not None else None
        return default if a is None else a

    def iaps(self):
        return list(self.facts.get("monetization", {}).get("iap") or [])

    def mask(self, text):
        return cg.mask(text, self.pvals)


def load_json(p, default=None):
    p = pathlib.Path(p)
    return json.loads(p.read_text()) if p.exists() else (default if default is not None else {})


def local_slots(kit, locale):
    """{(placementType, displayClass): [(slot folder, file path), ...]} for one locale, plus unmapped slot names."""
    out, unmapped = {}, []
    for base, ptype, exts in (("screenshots", "APP_SCREENSHOT", IMAGE_EXT), ("previews", "APP_PREVIEW", VIDEO_EXT)):
        root = kit.path / base / locale
        if not root.is_dir():
            continue
        slots = sorted((p for p in root.iterdir() if p.is_dir()),
                       key=lambda p: (p.name != "iphone-duo-outer", p.name))
        for slot in slots:
            files = sorted(f for f in slot.iterdir() if f.suffix.lower() in exts)
            if not files:
                continue
            cls = SLOT_CLASS.get(slot.name)
            if not cls:
                unmapped.append(f"{base}/{locale}/{slot.name}")
                continue
            out.setdefault((ptype, cls), []).extend((slot.name, f) for f in files)
    return out, unmapped


def local_creative(kit, locale):
    """{placementType: file path} for one locale's creative assets. A specific file beats "universal"."""
    root = kit.path / "creative" / locale
    out = {}
    if not root.is_dir():
        return out
    files = {f.stem.lower(): f for f in sorted(root.iterdir())
             if f.is_file() and f.suffix.lower() in IMAGE_EXT + VIDEO_EXT}
    for name in ("universal", "header", "search"):
        if name in files:
            for ptype in CREATIVE_NAMES[name]:
                out[ptype] = files[name]
    return out


# ---------------------------------------------------------------------------------------------------- live
def get_one(client, path, params=None):
    """The `data` of a to-one GET, or None when there is none (404 or data: null)."""
    try:
        doc = client.get(path, params)
    except ASCError as e:
        if e.status == 404:
            return None
        raise
    return (doc or {}).get("data")


def attrs(obj):
    return (obj or {}).get("attributes") or {}


def rel_id(obj, name):
    d = (((obj or {}).get("relationships") or {}).get(name) or {}).get("data")
    return d.get("id") if isinstance(d, dict) else None


def find_app(client, bundle_id):
    apps = client.get_all("/v1/apps", {"filter[bundleId]": bundle_id, "limit": 200})
    exact = [a for a in apps if attrs(a).get("bundleId") == bundle_id]
    return exact[0] if exact else None


def vstate(v):
    a = attrs(v)
    return a.get("appVersionState") or a.get("appStoreState") or ""


def pick_versions(versions, kit_version):
    target = next((v for v in versions if attrs(v).get("versionString") == kit_version), None)
    editable = next((v for v in versions if vstate(v) in EDITABLE), None)
    live = next((v for v in sorted(versions, key=lambda v: attrs(v).get("createdDate") or "", reverse=True)
                 if vstate(v) in ("READY_FOR_DISTRIBUTION", "PROCESSING_FOR_DISTRIBUTION")), None)
    return target, editable, live


def is_first(versions):
    return not any(vstate(v) in LIVE_STATES for v in versions)


def placement_groups(refdata):
    """{displayClass: placementGroup id} for iOS, found anywhere in the appAssetLibraryRefData document.
    Group ids are runtime strings (asc-api.md §4a): never hard-coded."""
    found = {}

    def walk(node):
        if isinstance(node, dict):
            # Live shape (read 2026-10-14): attributes.placementProfileGroups[] =
            # {placementProfileGroupId, platform: IPHONE_APP_STORE|IPAD_APP_STORE|..., displayClassId}
            cls = node.get("displayClassId") or node.get("displayClass")
            gid = node.get("placementProfileGroupId") or node.get("placementGroup") or node.get("groupId") \
                or node.get("id")
            plat = str(node.get("platform") or "IOS").upper()
            if isinstance(cls, str) and isinstance(gid, str) and \
                    plat in ("IOS", "IPHONE_OS", "IPAD_OS", "IPHONE_APP_STORE", "IPAD_APP_STORE"):
                if not gid.startswith("IMESSAGE"):
                    found.setdefault(cls, gid)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(refdata)
    return found


def creative_groups(refdata):
    """{placementType: placementGroup id} for the header and search-results placements, from the specMappings of
    appAssetLibraryRefData placementTypes (live 2026-10-14: DEFAULT_PROFILE, platform ANY)."""
    found = {}

    def walk(node):
        if isinstance(node, dict):
            pid = node.get("placementTypeId")
            if pid in (HEADER, SEARCH):
                for m in node.get("specMappings") or []:
                    if isinstance(m, dict) and m.get("placementGroupId"):
                        found.setdefault(pid, m["placementGroupId"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(refdata)
    return found


def read_placements(client, loc_id):
    data, included = client.get_all(f"/v1/appStoreVersionLocalizations/{loc_id}/placements",
                                    {"sort": "placementGroupPosition", "include": "image,video", "limit": 200},
                                    include_included=True)
    assets = {i["id"]: attrs(i) for i in included if i.get("type") in ("appAssetLibraryImages",
                                                                         "appAssetLibraryVideos")}
    return data, assets


def placement_asset_id(p):
    return rel_id(p, "image") or rel_id(p, "video")


def read_live(client, kit, areas):
    """Everything plan needs from App Store Connect, read with GETs only."""
    live = {"app": find_app(client, kit.bundle_id), "warnings": []}
    app = live["app"]
    if not app:
        return live
    aid = app["id"]
    versions = client.get_all(f"/v1/apps/{aid}/appStoreVersions", {"filter[platform]": "IOS", "limit": 200})
    live["versions"] = versions
    target, editable, live_v = pick_versions(versions, kit.version)
    live.update(target=target, editable=editable, live_version=live_v, first=is_first(versions))
    if target:
        live["version_action"] = "use" if vstate(target) in EDITABLE else "locked"
        source = target
    elif editable:
        live["version_action"], source = "rename", editable
    else:
        live["version_action"], source = "create", live_v
    live["source"] = source

    infos = client.get_all(f"/v1/apps/{aid}/appInfos", {"limit": 50})
    info = next((i for i in infos if attrs(i).get("state") not in ("READY_FOR_DISTRIBUTION", "REPLACED_WITH_NEW_INFO")),
                infos[0] if infos else None)
    live["app_info"] = info
    if info and "text" in areas:
        locs = client.get_all(f"/v1/appInfos/{info['id']}/appInfoLocalizations", {"limit": 200})
        live["app_info_locs"] = {attrs(x).get("locale"): x for x in locs}
        full = get_one(client, f"/v1/appInfos/{info['id']}", {"include": "primaryCategory,secondaryCategory"})
        live["categories"] = {"primary": rel_id(full, "primaryCategory"), "secondary": rel_id(full, "secondaryCategory")}
    if info and "age" in areas:
        live["age"] = get_one(client, f"/v1/appInfos/{info['id']}/ageRatingDeclaration")

    if source and live["version_action"] != "locked":
        sid = source["id"]
        if areas & {"text", "media"}:
            locs = client.get_all(f"/v1/appStoreVersions/{sid}/appStoreVersionLocalizations", {"limit": 200})
            live["version_locs"] = {attrs(x).get("locale"): x for x in locs}
        if "review" in areas and live["version_action"] != "create":
            live["review_detail"] = get_one(client, f"/v1/appStoreVersions/{sid}/appStoreReviewDetail")
        if "build" in areas and live["version_action"] != "create":
            live["current_build"] = get_one(client, f"/v1/appStoreVersions/{sid}/build")
        if "release" in areas and live["version_action"] != "create":
            live["phased"] = get_one(client, f"/v1/appStoreVersions/{sid}/appStoreVersionPhasedRelease")
        if "media" in areas:
            live["placements"], live["assets"] = {}, {}
            for loc, obj in (live.get("version_locs") or {}).items():
                if loc in kit.locales:
                    data, assets = read_placements(client, obj["id"])
                    live["placements"][loc] = data
                    live["assets"].update(assets)
            try:
                live["groups"] = placement_groups(client.get("/v1/appAssetLibraryRefData",
                                                         {"filter[placementTypes]": "APP_SCREENSHOT,APP_PREVIEW"}))
            except ASCError as e:
                live["warnings"].append(f"could not read appAssetLibraryRefData: {e}")
                live["groups"] = {}
            if any(local_creative(kit, loc) for loc in kit.locales):
                try:
                    live["creative_groups"] = creative_groups(client.get(
                        "/v1/appAssetLibraryRefData", {"filter[placementTypes]": f"{HEADER},{SEARCH}"}))
                except ASCError as e:
                    live["warnings"].append(f"could not read the creative asset ref data: {e}")
                    live["creative_groups"] = {}
    if "build" in areas and kit.build:
        live["builds"] = client.get_all("/v1/builds", {"filter[app]": aid, "filter[version]": kit.build,
                                                       "filter[preReleaseVersion.version]": kit.version,
                                                       "limit": 50})
    if "accessibility" in areas:
        try:
            live["accessibility"] = client.get_all(f"/v1/apps/{aid}/accessibilityDeclarations", {"limit": 50})
        except ASCError as e:
            live["warnings"].append(f"could not read accessibility declarations: {e}")
            live["accessibility"] = None
    if "iap" in areas or "submit" in areas:
        live["iaps"] = {f.get("product_id"): read_iap(client, aid, f.get("product_id"), kit, "iap" in areas)
                        for f in kit.iaps()}
    return live


def read_iap(client, app_id, pid, kit, details=True):
    out = {"iap": None, "version": None, "versions": [], "locs": {}, "image": None, "image_kind": "v2",
           "price": None}
    found = client.get_all(f"/v1/apps/{app_id}/inAppPurchasesV2", {"filter[productId]": pid, "limit": 200})
    iap = next((x for x in found if attrs(x).get("productId") == pid), None)
    out["iap"] = iap
    if not iap or not details:
        return out
    iid = iap["id"]
    try:
        out["versions"] = client.get_all(f"/v2/inAppPurchases/{iid}/inAppPurchaseVersions", {"limit": 50})
    except ASCError as e:
        if e.status != 404:
            raise
        # Live 2026-10-14: "The relationship 'inAppPurchaseVersions' does not exist" on an unversioned purchase;
        # its review screenshot is the v1 appStoreReviewScreenshot.
        out["image_kind"] = "v1"
    ver = next((v for v in out["versions"] if attrs(v).get("state") in IAP_EDITABLE), None)
    out["version"] = ver
    if ver:
        locs = client.get_all(f"/v1/inAppPurchaseVersions/{ver['id']}/inAppPurchaseLocalizations", {"limit": 200})
        out["locs"] = {attrs(x).get("locale"): x for x in locs}
        try:
            doc = client.get(f"/v1/inAppPurchaseVersions/{ver['id']}/image")
            out["image"] = (doc or {}).get("data")
        except ASCError as e:
            if e.status not in (400, 404):
                raise
            out["image_kind"] = "v1"
    else:
        try:
            locs = client.get_all(f"/v2/inAppPurchases/{iid}/inAppPurchaseLocalizations", {"limit": 200})
            out["locs"] = {attrs(x).get("locale"): x for x in locs}
        except ASCError as e:
            if e.status != 404:
                raise
    if out["image_kind"] == "v1":
        out["image"] = get_one(client, f"/v2/inAppPurchases/{iid}/appStoreReviewScreenshot")
    try:
        doc = client.get(f"/v1/inAppPurchasePriceSchedules/{iid}/manualPrices",
                         {"include": "inAppPurchasePricePoint", "filter[territory]": "USA"})
        pts = [attrs(i).get("customerPrice") for i in (doc or {}).get("included") or []
               if i.get("type") == "inAppPurchasePricePoints"]
        out["price"] = pts[0] if pts else None
    except ASCError:
        out["price"] = None
    return out


# ---------------------------------------------------------------------------------------------------- plan
class Plan:
    def __init__(self, kit, live, areas):
        self.kit, self.live, self.areas = kit, live, areas
        self.items, self.notes, self.warnings, self.browser, self.person = [], [], [], [], []
        self.media_rows = []  # (locale, slot label, file, action)

    def add(self, area, op, title, **kw):
        n = sum(1 for i in self.items if i["area"] == area) + 1
        it = {"id": f"{area}-{n}", "area": area, "op": op, "title": title, "changes": [], **kw}
        self.items.append(it)
        return it


def diff(cur, desired, locale=None, private=None):
    """[(field, old, new)] for every desired value that differs from cur. Private markers compare by digits."""
    out = []
    for k, new in desired.items():
        old = cur.get(k)
        if isinstance(new, dict) and PRIVATE in new:
            want = _s((private or {}).get(new[PRIVATE]))
            digits = re.sub(r"\D", "", want)
            same = digits == re.sub(r"\D", "", _s(old)) if len(digits) >= 6 else want == _s(old)
            if want and not same:
                out.append({"locale": locale, "field": k, "old": MASK if old else "", "new": MASK})
            continue
        if isinstance(new, bool) or isinstance(old, bool):
            if bool(old) != bool(new) or old is None:
                out.append({"locale": locale, "field": k, "old": old, "new": new})
        elif _s(old) != _s(new):
            out.append({"locale": locale, "field": k, "old": old, "new": new})
    return out


def clean(d):
    return {k: v for k, v in d.items() if v is not None and v != ""}


def category_id(name):
    if not name:
        return None
    s = str(name).strip()
    if re.fullmatch(r"[A-Z_]+", s):
        return s
    return re.sub(r"[^A-Z0-9]+", "_", s.upper().replace("&", "AND")).strip("_")


def plan_text(P):
    kit, live = P.kit, P.live
    infos = live.get("app_info_locs") or {}
    urls = kit.facts.get("urls") or {}
    choices = (kit.conn.get("privacy") or {}).get("user_choices_url")
    for loc in kit.locales:
        m = kit.meta.get(loc)
        if not m:
            P.warnings.append(f"metadata.{loc}.yaml is missing: {loc} is left as it is")
            continue
        desired = clean({"name": m.get("name"), "subtitle": m.get("subtitle"),
                         "privacyPolicyUrl": m.get("privacy_policy_url") or urls.get("privacy_policy"),
                         "privacyChoicesUrl": m.get("privacy_choices_url") or choices})
        for k, mx in LIMITS.items():
            if k in desired and len(str(desired[k])) > mx:
                P.warnings.append(f"{loc} {k} is {len(str(desired[k]))} characters (limit {mx})")
        cur = infos.get(loc)
        if cur is None:
            if not desired.get("name"):
                P.warnings.append(f"{loc}: no name in metadata.{loc}.yaml, and a new language needs one")
                continue
            it = P.add("text", "appinfo_loc", f"App information ({loc}): add the language", locale=loc,
                       target_id=None, attributes=desired, desired=desired)
            it["changes"] = diff({}, desired, loc)
        else:
            ch = diff(attrs(cur), desired, loc)
            if ch:
                P.add("text", "appinfo_loc", f"App information ({loc})", locale=loc, target_id=cur["id"],
                      attributes={c["field"]: desired[c["field"]] for c in ch}, desired=desired, changes=ch)

    cat = kit.meta.get(kit.primary, {}).get("category") or kit.facts.get("category") or {}
    if cat and live.get("app_info"):
        want = {"primary": category_id(cat.get("primary")), "secondary": category_id(cat.get("secondary"))}
        for k, v in want.items():
            if v and v not in CATEGORIES:
                P.warnings.append(f"category {cat.get(k)!r} maps to {v}, which isn't a known App Store category id")
        cur = live.get("categories") or {}
        ch = [{"locale": None, "field": f"{k} category", "old": cur.get(k), "new": v}
              for k, v in want.items() if v and cur.get(k) != v]
        if ch:
            P.add("text", "categories", "Categories", target_id=live["app_info"]["id"], categories=want,
                  names={k: cat.get(k) for k in want}, changes=ch)

    cr = kit.answer("content_rights")
    if cr is not None:
        want = CONTENT_RIGHTS.get(str(cr), str(cr) if str(cr).isupper() else None)
        if not want:
            P.warnings.append(f"connect.yaml content_rights {cr!r}: use uses_third_party or none")
        elif attrs(live["app"]).get("contentRightsDeclaration") != want:
            P.add("text", "content_rights", "Content rights", value=want, answer=str(cr), changes=[
                {"locale": None, "field": "contentRightsDeclaration",
                 "old": attrs(live["app"]).get("contentRightsDeclaration"), "new": want}])

    if live.get("version_action") == "locked":
        return
    src = live.get("source")
    copyright_ = kit.meta.get(kit.primary, {}).get("copyright") or kit.facts.get("copyright")
    if copyright_ and live.get("version_action") != "create" and _s(attrs(src).get("copyright")) != _s(copyright_):
        P.add("text", "version_attrs", "Copyright", attributes={"copyright": copyright_}, changes=[
            {"locale": None, "field": "copyright", "old": attrs(src).get("copyright"), "new": copyright_}])
    vlocs = live.get("version_locs") or {}
    first = live.get("first", True)
    for loc in kit.locales:
        m = kit.meta.get(loc)
        if not m:
            continue
        kw = m.get("keywords")
        desired = clean({"description": m.get("description"),
                         "keywords": kw if isinstance(kw, str) or kw is None else ",".join(kw),
                         "promotionalText": m.get("promotional_text"),
                         "marketingUrl": m.get("marketing_url") or (kit.facts.get("urls") or {}).get("marketing"),
                         "supportUrl": m.get("support_url") or (kit.facts.get("urls") or {}).get("support"),
                         "whatsNew": None if first else m.get("whats_new")})
        if not first and not m.get("whats_new"):
            P.warnings.append(f"{loc}: an update needs What's New (whats_new in metadata.{loc}.yaml)")
        if len((desired.get("keywords") or "").encode()) > 100:
            P.warnings.append(f"{loc} keywords are over 100 bytes")
        cur = vlocs.get(loc)
        if live.get("version_action") == "create" and "whatsNew" in desired:
            cur_a = dict(attrs(cur), whatsNew=None)  # the new version starts without What's New
        else:
            cur_a = attrs(cur)
        ch = diff(cur_a, desired, loc)
        if ch:
            P.add("text", "version_loc", f"Product page text ({loc})" + ("" if cur else ": add the language"),
                  locale=loc, attributes={c["field"]: desired[c["field"]] for c in ch}, desired=desired, changes=ch)


def plan_version(P):
    kit, live = P.kit, P.live
    act = live.get("version_action")
    if act == "locked":
        P.notes.append(f"Version {kit.version} is {vstate(live['target'])}: it can't be edited. For an update, "
                       f"raise app.version in facts.yaml (release.py bumps it) and plan again.")
    elif act == "rename":
        P.add("version", "version_attrs", f"Rename the draft version {attrs(live['editable']).get('versionString')} "
              f"to {kit.version}", attributes={"versionString": kit.version}, changes=[
                  {"locale": None, "field": "versionString",
                   "old": attrs(live["editable"]).get("versionString"), "new": kit.version}])
    elif act == "create":
        copyright_ = kit.meta.get(kit.primary, {}).get("copyright") or kit.facts.get("copyright")
        a = clean({"platform": "IOS", "versionString": kit.version, "copyright": copyright_})
        rt = release_type(kit)
        if rt:
            a["releaseType"] = rt
            if rt == "SCHEDULED" and kit.answer("version", "earliest_release_date"):
                a["earliestReleaseDate"] = str(kit.answer("version", "earliest_release_date"))
        P.add("version", "create_version", f"Create version {kit.version}", attributes=a, changes=[
            {"locale": None, "field": "version", "old": attrs(live.get("live_version")).get("versionString"),
             "new": kit.version}])
        P.notes.append(f"Version {kit.version} will be created; Apple copies the text of the live version into it, "
                       f"so only what changed is sent.")


def release_type(kit):
    r = kit.answer("version", "release") or kit.answer("release")
    return RELEASE_TYPE.get(str(r).lower()) if r else None


def plan_release(P):
    kit, live = P.kit, P.live
    if live.get("version_action") in ("locked", None):
        return
    src = live.get("source")
    rt = release_type(kit)
    if rt and live["version_action"] != "create":
        a = {"releaseType": rt}
        if rt == "SCHEDULED":
            d = kit.answer("version", "earliest_release_date")
            if d:
                a["earliestReleaseDate"] = str(d)
            else:
                P.warnings.append("release is scheduled but connect.yaml has no version.earliest_release_date")
        ch = diff(attrs(src), a)
        if ch:
            P.add("release", "version_attrs", "Release option", attributes=a, changes=ch)
    if live.get("first"):
        P.notes.append("Phased release isn't offered for a first version.")
        return
    want = truthy(kit.answer("version", "phased_release", default=True))
    cur = live.get("phased")
    state = attrs(cur).get("phasedReleaseState")
    if want and not cur:
        P.add("release", "phased_release", "Phased release over 7 days: on", action="create",
              changes=[{"locale": None, "field": "phased release", "old": "off", "new": "on (7 days)"}])
    elif not want and cur:
        if state == "INACTIVE":
            P.add("release", "phased_release", "Phased release: off", action="delete", target_id=cur["id"],
                  changes=[{"locale": None, "field": "phased release", "old": "on", "new": "off"}])
        else:
            P.notes.append(f"Phased release is {state}: the kit says off, but a started one can only be paused "
                           f"or completed (release --pause).")


def plan_build(P):
    kit, live = P.kit, P.live
    if live.get("version_action") == "locked" or not kit.build:
        return
    builds = [b for b in live.get("builds") or [] if attrs(b).get("version") == kit.build]
    b = builds[0] if builds else None
    cur = live.get("current_build")
    if not b:
        P.notes.append(f"Build {kit.build} of version {kit.version} isn't in App Store Connect yet: upload it "
                       f"first, then plan again.")
    elif attrs(b).get("processingState") != "VALID":
        P.notes.append(f"Build {kit.build} is {attrs(b).get('processingState')}: it can be attached once it is VALID.")
    elif not cur or cur.get("id") != b["id"]:
        P.add("build", "version_build", f"Attach build {kit.version} ({kit.build})", build_id=b["id"], changes=[
            {"locale": None, "field": "build", "old": attrs(cur).get("version"), "new": kit.build}])


def private_marker(kit, key):
    return {PRIVATE: key} if kit.private.get(key) else None


def plan_review(P):
    kit, live = P.kit, P.live
    if live.get("version_action") == "locked":
        return
    rc = kit.conn.get("review_contact") or {}
    sign_in = truthy(kit.answer("sign_in_required", default=False))
    desired = clean({"contactFirstName": rc.get("first_name"), "contactLastName": rc.get("last_name"),
                     "contactEmail": rc.get("email"), "contactPhone": private_marker(kit, "phone"),
                     "notes": cg.review_notes_text(kit.path, kit.meta.get(kit.primary, {})) or None})
    desired["demoAccountRequired"] = sign_in
    if sign_in:
        desired.update(clean({"demoAccountName": private_marker(kit, "demo_user"),
                              "demoAccountPassword": private_marker(kit, "demo_password")}))
        if "demoAccountName" not in desired:
            P.warnings.append("sign-in is required but private.yaml has no demo_user / demo_password")
    if "contactPhone" not in desired:
        P.warnings.append("private.yaml has no review_contact.phone: App Review needs a contact phone")
    if len((desired.get("notes") or "").encode()) > 4000:
        P.warnings.append("review notes are over 4000 bytes")
    cur = live.get("review_detail")
    ch = diff(attrs(cur), desired, private=kit.private)
    if ch:
        P.add("review", "review_detail", "App Review information", target_id=(cur or {}).get("id"),
              attributes={c["field"]: desired[c["field"]] for c in ch}, desired=desired, changes=ch)


def age_answers(kit, warn):
    out = {}
    for k, v in (kit.conn.get("age_rating") or {}).items():
        a = cg.answer(v)[0]
        if k in AGE_IGNORE:
            continue
        if k == "override":
            val = OVERRIDE.get(str(a).strip().lower())
            if val:
                out["ageRatingOverrideV2"] = val
            else:
                warn(f"age_rating.override {a!r} isn't a known value; ignored")
        elif k in FREQ_KEYS:
            val = FREQ.get(str(a).strip().lower().replace(" ", "_"))
            if val:
                out[k] = val
            else:
                warn(f"age_rating.{k} {a!r}: use None, Infrequent or Frequent; ignored")
        elif k in BOOL_KEYS:
            out[k] = truthy(a)
        elif k in PLAIN_KEYS:
            out[k] = a
        else:
            warn(f"age_rating.{k} isn't an App Store Connect age-rating attribute; ignored")
    return out


def plan_age(P):
    desired = age_answers(P.kit, P.warnings.append)
    cur = P.live.get("age")
    if not desired:
        return
    if not cur:
        P.warnings.append("no age rating declaration found on the app info")
        return
    ch = diff(attrs(cur), desired)
    if ch:
        P.add("age", "age_rating", "Age rating answers", target_id=cur["id"],
              attributes={c["field"]: desired[c["field"]] for c in ch}, changes=ch)


def plan_accessibility(P):
    kit, live = P.kit, P.live
    devices = (kit.conn.get("accessibility") or {}).get("devices") or {}
    if not devices:
        return
    if live.get("accessibility") is None:
        P.warnings.append("accessibility declarations could not be read; skipped")
        return
    can_publish = bool(live.get("live_version"))
    by_family = {}
    for d in live["accessibility"]:
        by_family.setdefault(attrs(d).get("deviceFamily"), []).append(d)
    for dev, feats in devices.items():
        fam = DEVICE.get(str(dev).lower())
        if not fam:
            P.warnings.append(f"accessibility device {dev!r} isn't known; ignored")
            continue
        desired = {}
        for feat, v in (feats or {}).items():
            if feat in ACCESS:
                desired[ACCESS[feat]] = truthy(cg.answer(v)[0])
            else:
                P.warnings.append(f"accessibility {dev}: {feat!r} isn't a known feature; ignored")
        for a in ACCESS.values():
            desired.setdefault(a, False)
        existing = by_family.get(fam) or []
        cur = next((d for d in existing if attrs(d).get("state") == "DRAFT"), existing[0] if existing else None)
        ch = diff(attrs(cur), desired, dev) if cur else diff({}, {k: v for k, v in desired.items() if v}, dev)
        publish = can_publish and (bool(ch) or attrs(cur).get("state") == "DRAFT")
        if ch or publish:
            P.add("accessibility", "accessibility", f"Accessibility ({dev})", device=str(dev), device_family=fam,
                  target_id=(cur or {}).get("id"), attributes=desired, publish=publish, changes=ch)
            if not can_publish:
                P.notes.append(f"Accessibility ({dev}) stays a draft: Apple publishes it once a version is live.")


def diff_slot(files, placements, live_assets, assets_map):
    """Compare local files (in order) with the live placements of one group.
    Returns (rows, removes); a row is {pos, file, sha256, size, action, placement_id}."""
    known = (assets_map or {}).get("assets") or {}
    rows, removes = [], []
    for i, f in enumerate(files):
        sha, size = sha256(f), pathlib.Path(f).stat().st_size
        row = {"pos": i + 1, "file": str(f), "sha256": sha, "size": size, "action": "add", "placement_id": None}
        if i < len(placements):
            p = placements[i]
            aid = placement_asset_id(p)
            rec = known.get(aid) or {}
            if rec.get("sha256"):
                same, how = rec["sha256"] == sha, "sha256"
            else:
                same, how = (live_assets or {}).get(aid, {}).get("fileSize") == size, "fileSize"
            row.update(action="unchanged" if same else "replace", placement_id=p["id"], asset_id=aid, matched_by=how)
        rows.append(row)
    for p in placements[len(files):]:
        removes.append({"placement_id": p["id"], "asset_id": placement_asset_id(p)})
    return rows, removes


def group_placements(placements, group, ptype):
    sel = [p for p in placements or [] if attrs(p).get("placementGroup") == group
           and attrs(p).get("placementType", ptype) == ptype]
    return sorted(sel, key=lambda p: attrs(p).get("placementGroupPosition") or 0)


def plan_media(P):
    kit, live = P.kit, P.live
    if live.get("version_action") == "locked":
        return
    groups = live.get("groups") or {}
    assets_map = load_json(kit.path / ASSETS_JSON)
    any_local = False
    for loc in kit.locales:
        slots, unmapped = local_slots(kit, loc)
        for u in unmapped:
            P.warnings.append(f"{u}: no Asset Library display class for this slot; skipped")
        if not slots:
            if loc != kit.primary:
                P.notes.append(f"{loc} has no screenshots folder: Apple shows the {kit.primary} screenshots there.")
            continue
        any_local = True
        cur_placements = (live.get("placements") or {}).get(loc) or []
        for (ptype, cls), entries in slots.items():
            label = "+".join(dict.fromkeys(s for s, _ in entries))
            group = groups.get(cls)
            if not group:
                P.warnings.append(f"{loc} {label}: no placement group for {cls} in appAssetLibraryRefData; skipped")
                continue
            files = [f for _, f in entries]
            rows, removes = diff_slot(files, group_placements(cur_placements, group, ptype), live.get("assets"),
                                      assets_map)
            for r in rows:
                P.media_rows.append((loc, label, pathlib.Path(r["file"]).relative_to(kit.path).as_posix(), r["action"]))
            for r in removes:
                P.media_rows.append((loc, label, f"placement {r['placement_id']}", "remove"))
            if any(r["action"] != "unchanged" for r in rows) or removes:
                rel = [{**r, "file": pathlib.Path(r["file"]).relative_to(kit.path).as_posix()} for r in rows]
                P.add("media", "media_slot", f"{'Previews' if ptype == 'APP_PREVIEW' else 'Screenshots'} "
                      f"{label} ({loc})", locale=loc, slot=label, display_class=cls, group=group,
                      placement_type=ptype, rows=rel, removes=removes, changes=[
                          {"locale": loc, "field": label, "old": f"{len(group_placements(cur_placements, group, ptype))} live",
                           "new": ", ".join(f"{pathlib.Path(r['file']).name} {r['action']}" for r in rows)
                           + (f"; remove {len(removes)}" if removes else "")}])
    if not any_local:
        P.warnings.append("no screenshots found under screenshots/<locale>/<slot>/")
    plan_creative(P, assets_map)


def plan_creative(P, assets_map):
    """Header and search-results assets: one placement each per localization (maxCount 1)."""
    kit, live = P.kit, P.live
    cgroups = live.get("creative_groups") or {}
    for loc in kit.locales:
        wanted = local_creative(kit, loc)
        if not wanted:
            continue
        cur_placements = (live.get("placements") or {}).get(loc) or []
        for ptype, f in wanted.items():
            label = CREATIVE_LABEL[ptype]
            group = cgroups.get(ptype)
            if not group:
                P.warnings.append(f"{loc} {label}: no placement group for {ptype} in appAssetLibraryRefData; skipped")
                continue
            cur = group_placements(cur_placements, group, ptype)
            rows, removes = diff_slot([f], cur, live.get("assets"), assets_map)
            rel_file = pathlib.Path(f).relative_to(kit.path).as_posix()
            P.media_rows.append((loc, label, rel_file, rows[0]["action"]))
            for r in removes:
                P.media_rows.append((loc, label, f"placement {r['placement_id']}", "remove"))
            if rows[0]["action"] != "unchanged" or removes:
                P.add("media", "media_slot", f"{label} asset ({loc})", locale=loc, slot=label.lower(),
                      display_class="DEFAULT", group=group, placement_type=ptype, category="CREATIVE_ASSETS",
                      rows=[{**rows[0], "file": rel_file}], removes=removes, changes=[
                          {"locale": loc, "field": label, "old": f"{len(cur)} live",
                           "new": f"{pathlib.Path(f).name} {rows[0]['action']}"}])


def iap_review_file(kit, pid):
    c = next((i for i in kit.conn.get("iap") or [] if i.get("product_id") == pid), {})
    f = next((i for i in kit.iaps() if i.get("product_id") == pid), {})
    raw = c.get("review_screenshot") or f.get("review_screenshot")
    cands = []
    if raw:
        token = str(raw).split(" (")[0].strip().split()[0]
        cands += [kit.path / token, kit.path / "iap" / token]
    folder = kit.path / "iap"
    if folder.is_dir():
        cands += sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXT and "review" in p.name)
    return next((p for p in cands if p.is_file()), None)


def plan_iap(P):
    kit, live = P.kit, P.live
    assets_map = load_json(kit.path / ASSETS_JSON)
    for f in kit.iaps():
        pid = f.get("product_id")
        L = (live.get("iaps") or {}).get(pid) or {}
        iap = L.get("iap")
        name = f.get("display_name") or f.get("reference_name") or pid
        it = {"product_id": pid, "name": name, "iap_id": (iap or {}).get("id"), "create_iap": None,
              "version_id": (L.get("version") or {}).get("id"), "image_kind": L.get("image_kind", "v2"),
              "locs": [], "image": None}
        changes = []
        if not iap:
            typ = IAP_TYPE.get(str(f.get("type", "")).lower())
            it["create_iap"] = clean({"name": f.get("reference_name") or name, "productId": pid,
                                      "inAppPurchaseType": typ, "familySharable": bool(f.get("family_shareable"))})
            changes.append({"locale": None, "field": "in-app purchase", "old": "", "new": f"create {pid}"})
            P.notes.append(f"{pid} doesn't exist yet: creating it needs the latest Paid Apps Agreement.")
        for loc in kit.locales:
            m = next((i for i in kit.meta.get(loc, {}).get("iap") or [] if i.get("product_id") == pid), None)
            if m is None and loc != kit.primary:
                continue
            m = m or {}
            desired = clean({"name": m.get("display_name") or f.get("display_name"),
                             "description": m.get("description") or f.get("description")})
            bad = [k for k, mx in (("name", 30), ("description", 45)) if len(desired.get(k, "")) > mx]
            if bad:
                P.warnings.append(f"{pid} {loc}: {', '.join(bad)} over the limit (30 / 45 characters); skipped")
                continue
            cur = (L.get("locs") or {}).get(loc)
            ch = diff(attrs(cur), desired, loc)
            if ch:
                it["locs"].append({"locale": loc, "target_id": (cur or {}).get("id"),
                                   "attributes": {c["field"]: desired[c["field"]] for c in ch}, "desired": desired})
                changes += ch
        rf = iap_review_file(kit, pid)
        if rf:
            img = L.get("image")
            sha, size = sha256(rf), rf.stat().st_size
            rec = ((assets_map.get("assets") or {}).get((img or {}).get("id")) or {})
            if not img:
                action = "add"
            elif rec.get("sha256"):
                action = "unchanged" if rec["sha256"] == sha else "replace"
            else:
                action = "unchanged" if attrs(img).get("fileSize") == size else "replace"
            if action != "unchanged":
                it["image"] = {"file": rf.relative_to(kit.path).as_posix(), "sha256": sha, "size": size,
                               "action": action, "old_id": (img or {}).get("id")}
                changes.append({"locale": None, "field": "review screenshot", "old": attrs(img).get("fileName"),
                                "new": f"{rf.name} ({action})"})
        else:
            P.warnings.append(f"{pid}: no review screenshot found (connect.yaml iap[].review_screenshot or iap/)")
        want_price = re.search(r"\d+(?:\.\d+)?", str(f.get("price") or ""))
        if want_price and L.get("price") is not None:
            if abs(float(L["price"]) - float(want_price.group())) > 0.001:
                P.notes.append(f"{pid} price: App Store Connect says {L['price']}, the kit says {f.get('price')}. "
                               f"Prices are not changed by this tool; fix it in the browser if the kit is right.")
        elif want_price and iap:
            P.notes.append(f"{pid} price couldn't be read through the API: check it shows {f.get('price')}.")
        if changes:
            P.add("iap", "iap", f"In-app purchase {name}", changes=changes, **it)


def person_and_browser_steps(P):
    kit, live = P.kit, P.live
    prog = (cg.load_yaml(kit.path / cg.PROGRESS_FILE).get("steps") or {})

    def done(key):
        st = str((prog.get(key) or {}).get("status") or "todo")
        return st.startswith("done") or st == "skipped"

    def step(lst, text, key=None):
        lst.append({"text": text, "progress_key": key, "done": bool(key and done(key))})

    app = live.get("app")
    if not app:
        step(P.browser, f"Create the app record (Apps › + › New App) for {kit.bundle_id}: the API can't create apps.",
             "new-app/fill-in-the-new-app-dialog")
    step(P.browser, "App Privacy: data types, purposes, then Publish (no API).", "privacy/publish")
    step(P.browser, "Pricing and Availability: iPhone and iPad apps on Apple silicon Mac, and Apple Vision Pro "
                    "(no API).", "pricing/price-and-countries")
    if not live.get("first", True) and truthy(kit.answer("version", "reset_ratings", default=False)):
        step(P.browser, "Version page: Reset Overview Rating (no API).", "version/phased-release-and-rating-reset")
    if live.get("first", True) and kit.iaps():
        unapproved = [pid for pid, L in (live.get("iaps") or {}).items()
                      if attrs((L or {}).get("iap")).get("state") != "APPROVED"] or [i.get("product_id") for i in kit.iaps()]
        if unapproved:
            url = version_page_url(app)
            # Live 2026-10-14: the version page has no In-App Purchases section any more. The purchase's own page
            # says "Your first non-consumable in-app purchase must be submitted with a new app version" and has
            # "Add for Review", which puts it into the same draft submission as the version (🛑 needs a yes).
            step(P.browser, f"🛑 In-App Purchases › {', '.join(unapproved)} › Add for Review (with the owner's yes), "
                            f"then the version's Add for Review: the first purchase goes in the same submission "
                            f"as the first version; no API. {url}",
                 "version/in-app-purchases")
    step(P.person, "Paid Apps Agreement: View and Agree to Terms (the Account Holder only).",
         "business/sign-the-latest-agreements")
    step(P.person, "Tax forms and bank account (Business).", "business/tax-and-banking")
    step(P.person, "EU Digital Services Act trader status (Business › Compliance).",
         "business/eu-digital-services-act-trader-status")


def version_page_url(app):
    aid = (app or {}).get("id") or "<appId>"
    return f"https://appstoreconnect.apple.com/apps/{aid}/distribution/ios/version/inflight"


def build_plan(kit, live, areas):
    P = Plan(kit, live, areas)
    P.warnings += live.get("warnings") or []
    for u in kit.unknown_locales:
        P.warnings.append(f"--locale {u} isn't in the kit's locales ({', '.join(kit.all_locales)})")
    if not live.get("app"):
        P.warnings.append(f"No app with bundle id {kit.bundle_id} in App Store Connect.")
        person_and_browser_steps(P)
        return P
    plan_version(P)
    for area, fn in (("text", plan_text), ("age", plan_age), ("build", plan_build), ("release", plan_release),
                     ("review", plan_review), ("accessibility", plan_accessibility), ("iap", plan_iap),
                     ("media", plan_media)):
        if area in areas:
            fn(P)
    person_and_browser_steps(P)
    return P


def plan_json(P):
    live, kit = P.live, P.kit
    return {
        "generated": dt.date.today().isoformat(),
        "app_id": (live.get("app") or {}).get("id"), "bundle_id": kit.bundle_id,
        "app_info_id": (live.get("app_info") or {}).get("id"),
        "kit_version": kit.version, "build": kit.build, "primary_locale": kit.primary, "locales": kit.locales,
        "first_version": live.get("first", True),
        "version": {"action": live.get("version_action"), "id": (live.get("source") or {}).get("id")
                    if live.get("version_action") in ("use", "rename") else None,
                    "state": vstate(live.get("target") or live.get("editable")) or None,
                    "live_version": attrs(live.get("live_version")).get("versionString")},
        "areas": sorted(P.areas),
        "items": sorted(P.items, key=lambda i: ORDER.index(i["area"])),
        "notes": P.notes, "warnings": P.warnings, "browser_steps": P.browser, "person_steps": P.person,
    }


def short(v, n=70):
    if v is None or v == "":
        return "(empty)"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s if len(s) <= n else s[:n - 1] + f"… ({len(str(v))} chars)"


def cell(v):
    return short(v).replace("|", "\\|")


def render_plan_md(pj, media_rows):
    v = pj["version"]
    journey = "first release" if pj["first_version"] else "update"
    L = [f"# App Store Connect plan: {pj['bundle_id']} {pj['kit_version']} ({journey})", "",
         f"Made {pj['generated']} by asc_sync.py plan. Nothing has been sent. Say yes, then "
         f"`asc_sync.py apply KIT --yes` sends exactly this.", ""]
    if pj.get("app_id"):
        act = {"use": "edit the draft version", "rename": "rename the draft version", "create": "create a new version",
               "locked": "the version can't be edited"}.get(v["action"], v["action"])
        L += [f"- App id {pj['app_id']}; version {pj['kit_version']}: {act}"
              + (f" (state {v['state']})" if v.get("state") else "")
              + (f"; live version {v['live_version']}" if v.get("live_version") else ""),
              f"- Languages: {', '.join(pj['locales'])} (primary {pj['primary_locale']})", ""]
    items = pj["items"]
    L += [f"**{len(items)} change(s).**", ""]
    for area in ORDER:
        group = [i for i in items if i["area"] == area]
        if area == "media":
            if media_rows:
                L += [f"## {AREA_TITLES[area]}", "", "| Language | Slot | File | Action |", "|---|---|---|---|"]
                L += [f"| {loc} | {slot} | {f} | {act} |" for loc, slot, f, act in media_rows]
                L.append("")
            continue
        if not group:
            continue
        L += [f"## {AREA_TITLES[area]}", "", "| Item | Language | Field | Now | New |", "|---|---|---|---|---|"]
        for it in group:
            for c in it["changes"]:
                L.append(f"| {it['title']} | {c.get('locale') or '-'} | {c['field']} | {cell(c['old'])} | "
                         f"{cell(c['new'])} |")
            if it.get("publish"):
                L.append(f"| {it['title']} | - | publish | - | Yes |")
        L.append("")
    for title, key in (("Notes", "notes"), ("Warnings", "warnings")):
        if pj[key]:
            L += [f"## {title}", ""] + [f"- {n}" for n in pj[key]] + [""]
    for title, key, who in (("Browser steps (Claude in Chrome; the API can't do these)", "browser_steps", ""),
                            ("Person steps (only you can do these)", "person_steps", "")):
        L += [f"## {title}", ""]
        L += [f"- [{'x' if s['done'] else ' '}] {s['text']}" + (" (done, per connect-progress.yaml)" if s["done"] else "")
              for s in pj[key]]
        L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------------------------------- apply
class Ctx:
    def __init__(self, client, kit, pj, poll_wait=5, poll_tries=60):
        self.client, self.kit, self.pj = client, kit, pj
        self.app_id, self.app_info_id = pj.get("app_id"), pj.get("app_info_id")
        self.version_id = (pj.get("version") or {}).get("id")
        self.poll_wait, self.poll_tries = poll_wait, poll_tries
        self.assets = load_json(kit.path / ASSETS_JSON) or {}
        self.assets.setdefault("assets", {})
        self.progress = {}   # step key → {"live": {...}, "note": str}
        self._vlocs = None
        self._library = None
        self.creative_uploads = {}

    def need_version(self):
        if not self.version_id:
            raise SyncError("no version to change (creating it failed or the plan is stale)")
        return self.version_id

    def version_loc(self, locale, create=True):
        if self._vlocs is None and str(self.need_version()).startswith("DRYRUN"):
            self._vlocs = {}
        if self._vlocs is None:
            locs = self.client.get_all(f"/v1/appStoreVersions/{self.need_version()}/appStoreVersionLocalizations",
                                       {"limit": 200})
            self._vlocs = {attrs(x).get("locale"): x for x in locs}
        if locale not in self._vlocs and create:
            r = self.client.post("/v1/appStoreVersionLocalizations", {"data": {
                "type": "appStoreVersionLocalizations", "attributes": {"locale": locale},
                "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": self.version_id}}}}})
            self._vlocs[locale] = r["data"]
        return self._vlocs.get(locale)

    def library_id(self):
        if not self._library:
            lib = get_one(self.client, f"/v1/apps/{self.app_id}/assetLibrary")
            if not lib:
                raise SyncError("the app has no Asset Library (GET /v1/apps/{id}/assetLibrary)")
            self._library = lib["id"]
        return self._library

    def record(self, key, live=None, note=None):
        e = self.progress.setdefault(key, {"live": {}, "notes": []})
        e["live"].update({k: v for k, v in (live or {}).items() if v is not None})
        if note:
            e["notes"].append(note)


def body(typ, attributes=None, id=None, relationships=None):
    d = {"type": typ}
    if id:
        d["id"] = id
    if attributes is not None:
        d["attributes"] = attributes
    if relationships:
        d["relationships"] = {k: {"data": v} for k, v in relationships.items()}
    return {"data": d}


def ref(typ, id):
    return {"type": typ, "id": id}


def resolve_private(kit, attributes):
    out = {}
    for k, v in attributes.items():
        if isinstance(v, dict) and PRIVATE in v:
            val = kit.private.get(v[PRIVATE])
            if not val:
                raise SyncError(f"{k}: private.yaml has no {v[PRIVATE]}")
            out[k] = str(val)
        else:
            out[k] = v
    return out


def verify(ctx, path, desired):
    """Re-read an object and check every desired attribute (private ones by presence only)."""
    if ctx.client.dry_run:
        return dict(desired)
    got = attrs(get_one(ctx.client, path))
    bad = []
    for k, v in desired.items():
        if isinstance(v, dict) and PRIVATE in v:
            if not got.get(k):
                bad.append(k)
        elif isinstance(v, bool):
            if bool(got.get(k)) != v:
                bad.append(k)
        elif _s(got.get(k)) != _s(v):
            bad.append(k)
    if bad:
        raise SyncError(f"re-read of {path} differs in {', '.join(bad)}")
    return got


def op_create_version(ctx, it):
    r = ctx.client.post("/v1/appStoreVersions", body("appStoreVersions", it["attributes"],
                                                     relationships={"app": ref("apps", ctx.app_id)}))
    ctx.version_id = r["data"]["id"]
    ctx._vlocs = None
    verify(ctx, f"/v1/appStoreVersions/{ctx.version_id}", {"versionString": it["attributes"]["versionString"]})


def op_version_attrs(ctx, it):
    vid = ctx.need_version()
    ctx.client.patch(f"/v1/appStoreVersions/{vid}", body("appStoreVersions", it["attributes"], id=vid))
    got = verify(ctx, f"/v1/appStoreVersions/{vid}", it["attributes"])
    if "releaseType" in it["attributes"]:
        ctx.record("version/app-store-version-release",
                   {"Release option": RELEASE_WORDS.get(got.get("releaseType"), got.get("releaseType"))})
    if "copyright" in it["attributes"]:
        ctx.record("version/product-page-text", {"Version": ctx.kit.version, "Copyright": got.get("copyright")})


def op_version_build(ctx, it):
    vid = ctx.need_version()
    ctx.client.patch(f"/v1/appStoreVersions/{vid}/relationships/build", {"data": ref("builds", it["build_id"])})
    if not ctx.client.dry_run:
        b = get_one(ctx.client, f"/v1/appStoreVersions/{vid}/build")
        if not b or b.get("id") != it["build_id"]:
            raise SyncError("re-read shows another build on the version")
    ctx.record("version/build", {"Build › +": f"{ctx.kit.version} ({ctx.kit.build})"})


def op_appinfo_loc(ctx, it):
    if it.get("target_id"):
        lid = it["target_id"]
        ctx.client.patch(f"/v1/appInfoLocalizations/{lid}", body("appInfoLocalizations", it["attributes"], id=lid))
    else:
        r = ctx.client.post("/v1/appInfoLocalizations", body(
            "appInfoLocalizations", {"locale": it["locale"], **it["desired"]},
            relationships={"appInfo": ref("appInfos", ctx.app_info_id)}))
        lid = r["data"]["id"]
    got = verify(ctx, f"/v1/appInfoLocalizations/{lid}", it["attributes"])
    if it["locale"] == ctx.kit.primary:
        if {"name", "subtitle"} & set(it["attributes"]):
            ctx.record("app-information/name-subtitle-and-category",
                       {"Name": got.get("name"), "Subtitle": got.get("subtitle")})
        if {"privacyPolicyUrl", "privacyChoicesUrl"} & set(it["attributes"]):
            ctx.record("privacy/privacy-policy-edit", {"Privacy Policy URL": got.get("privacyPolicyUrl")})


def op_categories(ctx, it):
    rels = {}
    for k, name in (("primary", "primaryCategory"), ("secondary", "secondaryCategory")):
        if it["categories"].get(k):
            rels[name] = ref("appCategories", it["categories"][k])
    iid = it["target_id"]
    ctx.client.patch(f"/v1/appInfos/{iid}", body("appInfos", id=iid, relationships=rels))
    if not ctx.client.dry_run:
        full = get_one(ctx.client, f"/v1/appInfos/{iid}", {"include": "primaryCategory,secondaryCategory"})
        for name, r in rels.items():
            if rel_id(full, name) != r["id"]:
                raise SyncError(f"re-read shows another {name}")
    ctx.record("app-information/name-subtitle-and-category",
               {"Category › Primary": it["names"].get("primary"), "Category › Secondary": it["names"].get("secondary")})


def op_content_rights(ctx, it):
    ctx.client.patch(f"/v1/apps/{ctx.app_id}", body("apps", {"contentRightsDeclaration": it["value"]}, id=ctx.app_id))
    verify(ctx, f"/v1/apps/{ctx.app_id}", {"contentRightsDeclaration": it["value"]})
    text = {"USES_THIRD_PARTY_CONTENT": "Yes, it contains, shows, or accesses third-party content, and I have the "
                                        "necessary rights",
            "DOES_NOT_USE_THIRD_PARTY_CONTENT": "No, it does not contain, show, or access third-party content"}
    ctx.record("app-information/content-rights", {"Content Rights": text.get(it["value"])})


def op_version_loc(ctx, it):
    cur = ctx.version_loc(it["locale"], create=False)
    if cur:
        lid = cur["id"]
        a = {k: v for k, v in it["desired"].items() if k in it["attributes"]}
        ctx.client.patch(f"/v1/appStoreVersionLocalizations/{lid}", body("appStoreVersionLocalizations", a, id=lid))
    else:
        r = ctx.client.post("/v1/appStoreVersionLocalizations", body(
            "appStoreVersionLocalizations", {"locale": it["locale"], **it["desired"]},
            relationships={"appStoreVersion": ref("appStoreVersions", ctx.need_version())}))
        lid = r["data"]["id"]
        ctx._vlocs[it["locale"]] = r["data"]
    got = verify(ctx, f"/v1/appStoreVersionLocalizations/{lid}", it["attributes"])
    if it["locale"] == ctx.kit.primary:
        ctx.record("version/product-page-text", {FIELD_LABELS[k]: got.get(k) for k in it["attributes"]
                                                 if k in FIELD_LABELS})


def op_review_detail(ctx, it):
    vid = ctx.need_version()
    cur = None if str(vid).startswith("DRYRUN") else get_one(ctx.client,
                                                             f"/v1/appStoreVersions/{vid}/appStoreReviewDetail")
    if cur and cur.get("id"):
        rid = cur["id"]
        a = resolve_private(ctx.kit, it["attributes"])
        ctx.client.patch(f"/v1/appStoreReviewDetails/{rid}", body("appStoreReviewDetails", a, id=rid))
    else:
        a = resolve_private(ctx.kit, it["desired"])
        r = ctx.client.post("/v1/appStoreReviewDetails", body(
            "appStoreReviewDetails", a, relationships={"appStoreVersion": ref("appStoreVersions", vid)}))
        rid = r["data"]["id"]
    got = verify(ctx, f"/v1/appStoreReviewDetails/{rid}", it["attributes"])
    ctx.record("version/app-review-information", {
        "Contact › First name": got.get("contactFirstName"), "Contact › Last name": got.get("contactLastName"),
        "Contact › Phone number": MASK if got.get("contactPhone") else None,
        "Contact › Email": got.get("contactEmail")})


def op_age_rating(ctx, it):
    rid = it["target_id"]
    ctx.client.patch(f"/v1/ageRatingDeclarations/{rid}", body("ageRatingDeclarations", it["attributes"], id=rid))
    verify(ctx, f"/v1/ageRatingDeclarations/{rid}", it["attributes"])
    ctx.record("app-information/age-rating-set-up-age-ratings", note="Answers set through the API")


def op_accessibility(ctx, it):
    a = it["attributes"]
    if it.get("target_id"):
        did = it["target_id"]
        if it["changes"]:
            ctx.client.patch(f"/v1/accessibilityDeclarations/{did}", body("accessibilityDeclarations", a, id=did))
    else:
        r = ctx.client.post("/v1/accessibilityDeclarations", body(
            "accessibilityDeclarations", {"deviceFamily": it["device_family"], **a},
            relationships={"app": ref("apps", ctx.app_id)}))
        did = r["data"]["id"]
    verify(ctx, f"/v1/accessibilityDeclarations/{did}", a)
    if it.get("publish"):
        ctx.client.patch(f"/v1/accessibilityDeclarations/{did}",
                         body("accessibilityDeclarations", {"publish": True}, id=did))
    feats = [k for k, v in ACCESS.items() if a.get(v)]
    ctx.record(f"accessibility/add-{cg.slug(it['device'])}-support",
               {"Supported Features": ", ".join(feats) or "None"},
               note="Published" if it.get("publish") else "Saved as a draft; Apple publishes it once a version is live")


def op_phased_release(ctx, it):
    if it["action"] == "create":
        vid = ctx.need_version()
        ctx.client.post("/v1/appStoreVersionPhasedReleases", body(
            "appStoreVersionPhasedReleases", {"phasedReleaseState": "INACTIVE"},
            relationships={"appStoreVersion": ref("appStoreVersions", vid)}))
    else:
        ctx.client.delete(f"/v1/appStoreVersionPhasedReleases/{it['target_id']}")
    ctx.record("version/phased-release-and-rating-reset",
               note="Phased release " + ("on (7 days)" if it["action"] == "create" else "off"))


def wait_ready(ctx, path, ok=("PREPARE_FOR_SUBMISSION",)):
    if ctx.client.dry_run:
        return
    for _ in range(ctx.poll_tries):
        a = attrs(get_one(ctx.client, path))
        state = a.get("state") or (a.get("assetDeliveryState") or {}).get("state")
        if state in ok or state == "COMPLETE":
            return
        if state == "FAILED":
            raise SyncError(f"{path} FAILED: {a.get('stateDetails') or a.get('assetDeliveryState')}")
        ctx.client.sleep(ctx.poll_wait)
    raise SyncError(f"{path} still processing after {ctx.poll_tries} checks")


def upload_library_asset(ctx, path, video=False, category="APP_SCREENSHOTS_AND_PREVIEWS"):
    """Asset Library reserve → PUT → PATCH uploaded → poll (asc-api.md §4a). Returns the asset id."""
    typ = "appAssetLibraryVideos" if video else "appAssetLibraryImages"
    a = {"fileName": path.name, "fileSize": path.stat().st_size, "category": category}
    if video:
        a["previewFrameTimeCode"] = "00:00:03:00"
    r = ctx.client.post(f"/v1/{typ}", body(typ, a, relationships={"assetLibrary": ref("appAssetLibraries",
                                                                                        ctx.library_id())}))
    aid = r["data"]["id"]
    ctx.client.upload_operations(attrs(r["data"]).get("uploadOperations") or [], path)
    ctx.client.patch(f"/v1/{typ}/{aid}", body(typ, {"uploaded": True}, id=aid))
    wait_ready(ctx, f"/v1/{typ}/{aid}")
    return aid


def op_media_slot(ctx, it):
    kit = ctx.kit
    loc = ctx.version_loc(it["locale"])
    data, live_assets = read_placements(ctx.client, loc["id"]) if not str(loc["id"]).startswith("DRYRUN") else ([], {})
    current = group_placements(data, it["group"], it["placement_type"])
    files = [kit.path / r["file"] for r in it["rows"]]
    rows, removes = diff_slot(files, current, live_assets, ctx.assets)
    if all(r["action"] == "unchanged" for r in rows) and not removes:
        return
    category = it.get("category") or "APP_SCREENSHOTS_AND_PREVIEWS"
    video = it["placement_type"] == "APP_PREVIEW" or (category == "CREATIVE_ASSETS"
                                                      and files[0].suffix.lower() in VIDEO_EXT)
    for r in removes + [r for r in rows if r["action"] == "replace"]:
        ctx.client.delete(f"/v1/appAssetLibraryPlacements/{r['placement_id']}")
    ordered = []
    for r in rows:
        if r["action"] == "unchanged":
            ordered.append(r["placement_id"])
            continue
        path = pathlib.Path(r["file"])
        # A universal creative asset is uploaded once and placed as both header and search results.
        aid = ctx.creative_uploads.get(r["sha256"]) if category == "CREATIVE_ASSETS" else None
        if not aid:
            aid = upload_library_asset(ctx, path, video, category)
            if category == "CREATIVE_ASSETS":
                ctx.creative_uploads[r["sha256"]] = aid
        p = ctx.client.post("/v1/appAssetLibraryPlacements", body(
            "appAssetLibraryPlacements", {"placementType": it["placement_type"], "placementGroup": it["group"]},
            relationships={("video" if video else "image"): ref("appAssetLibraryVideos" if video
                                                                else "appAssetLibraryImages", aid),
                           "appStoreVersionLocalization": ref("appStoreVersionLocalizations", loc["id"])}))
        ordered.append(p["data"]["id"])
        ctx.assets["assets"][aid] = {"sha256": r["sha256"], "file": path.relative_to(kit.path).as_posix(),
                                     "fileSize": r["size"], "locale": it["locale"], "group": it["group"]}
    if category == "CREATIVE_ASSETS":
        # One placement per group (maxCount 1): nothing to order.
        if it["locale"] == kit.primary:
            ctx.record("version/header-and-search-results",
                       note=f"{it['slot']}: {pathlib.Path(rows[0]['file']).name} placed")
        return
    ctx.client.post("/v1/appAssetLibraryPlacementOrderingRequests", body(
        "appAssetLibraryPlacementOrderingRequests", {"placementGroup": it["group"]},
        relationships={"orderedPlacements": [ref("appAssetLibraryPlacements", x) for x in ordered],
                       "appStoreVersionLocalization": ref("appStoreVersionLocalizations", loc["id"])}))
    if not ctx.client.dry_run:
        data, _ = read_placements(ctx.client, loc["id"])
        got = [p["id"] for p in group_placements(data, it["group"], it["placement_type"])]
        if got != ordered:
            raise SyncError(f"re-read of {it['slot']} ({it['locale']}) shows {len(got)} placements in another order")
    if it["locale"] == kit.primary:
        ctx.record("version/app-previews-and-screenshots", note=f"{it['slot']}: {len(rows)} files placed in order")


def op_iap(ctx, it):
    kit, c = ctx.kit, ctx.client
    iid = it.get("iap_id")
    if it.get("create_iap"):
        r = c.post("/v2/inAppPurchases", body("inAppPurchases", it["create_iap"],
                                              relationships={"app": ref("apps", ctx.app_id)}))
        iid = r["data"]["id"]
    vid = it.get("version_id")
    if not vid and (it["locs"] or it.get("image")):
        r = c.post("/v1/inAppPurchaseVersions", body("inAppPurchaseVersions", None,
                                                    relationships={"inAppPurchase": ref("inAppPurchases", iid)}))
        vid = r["data"]["id"]
    for loc in it["locs"]:
        if loc.get("target_id"):
            lid = loc["target_id"]
            c.patch(f"/v2/inAppPurchaseLocalizations/{lid}", body("inAppPurchaseLocalizations", loc["attributes"],
                                                                  id=lid))
        else:
            r = c.post("/v2/inAppPurchaseLocalizations", body(
                "inAppPurchaseLocalizations", {"locale": loc["locale"], **loc["desired"]},
                relationships={"inAppPurchaseVersion": ref("inAppPurchaseVersions", vid)}))
            lid = r["data"]["id"]
        got = verify(ctx, f"/v2/inAppPurchaseLocalizations/{lid}", loc["attributes"])
        if loc["locale"] == kit.primary:
            ctx.record(f"iap/{cg.slug(it['name'])}-display-name-and-description-scroll-down-press-add",
                       {"Display Name": got.get("name"), "Description": got.get("description")})
    img = it.get("image")
    if img:
        path = kit.path / img["file"]
        if it.get("image_kind") == "v1":
            typ, coll, rel = "inAppPurchaseAppStoreReviewScreenshots", "/v1/inAppPurchaseAppStoreReviewScreenshots", \
                {"inAppPurchaseV2": ref("inAppPurchases", iid)}
        else:
            typ, coll, rel = "inAppPurchaseImages", "/v2/inAppPurchaseImages", \
                {"inAppPurchaseVersion": ref("inAppPurchaseVersions", vid)}
        if img.get("old_id"):
            c.delete(f"{coll}/{img['old_id']}")
        r = c.post(coll, body(typ, {"fileName": path.name, "fileSize": path.stat().st_size}, relationships=rel))
        aid = r["data"]["id"]
        c.upload_operations(attrs(r["data"]).get("uploadOperations") or [], path)
        commit = {"uploaded": True}
        if it.get("image_kind") == "v1":
            commit["sourceFileChecksum"] = md5(path)
        c.patch(f"{coll}/{aid}", body(typ, commit, id=aid))
        wait_ready(ctx, f"{coll}/{aid}", ok=("PREPARE_FOR_SUBMISSION", "UPLOAD_COMPLETE", "COMPLETE", "APPROVED"))
        ctx.assets["assets"][aid] = {"sha256": img["sha256"], "file": img["file"], "fileSize": img["size"],
                                     "product_id": it["product_id"]}
        ctx.record(f"iap/{cg.slug(it['name'])}-image-optional-tax-category-review-information",
                   note=f"Review screenshot {path.name} uploaded")


OPS = {"create_version": op_create_version, "version_attrs": op_version_attrs, "version_build": op_version_build,
       "appinfo_loc": op_appinfo_loc, "categories": op_categories, "content_rights": op_content_rights,
       "version_loc": op_version_loc, "review_detail": op_review_detail, "age_rating": op_age_rating,
       "accessibility": op_accessibility, "phased_release": op_phased_release, "media_slot": op_media_slot,
       "iap": op_iap}


def run_apply(ctx, only=None, log=print):
    """Execute the plan's items in a safe order. Returns the list of (item title, error)."""
    errors, failed_keys = [], set()
    items = sorted(ctx.pj["items"], key=lambda i: (ORDER.index(i["area"]), ctx.pj["items"].index(i)))
    for it in items:
        if only and it["area"] != "version" and it["area"] not in only:
            continue
        before = set(ctx.progress)
        try:
            OPS[it["op"]](ctx, it)
            log(f"done: {it['title']}")
        except (ASCError, SyncError, OSError) as e:
            errors.append((it["title"], ctx.kit.mask(str(e))))
            failed_keys |= set(ctx.progress) - before
            log(f"FAILED: {it['title']}: {ctx.kit.mask(str(e))}")
            if it["op"] == "create_version":
                log("the version could not be created; the version-scoped items will fail too")
    for k in failed_keys:
        ctx.progress.pop(k, None)
    return errors


def write_progress(kit, progress, when=None):
    """Mark the mapped steps done-by-claude with their re-read live values. Never writes a private value."""
    if not progress:
        return
    path = kit.path / cg.PROGRESS_FILE
    prog = cg.load_yaml(path) or {}
    steps = prog.setdefault("steps", {})
    when = when or dt.date.today().isoformat()
    for key, e in progress.items():
        entry = dict(steps.get(key) or {})
        entry["status"] = "done-by-claude"
        entry["date"] = when
        live = dict(entry.get("live") or {})
        live.update({k: kit.mask(str(v)) for k, v in e["live"].items()})
        if live:
            entry["live"] = live
        note = "Set through the App Store Connect API (asc_sync.py apply), re-read and matching."
        if e["notes"]:
            note += " " + "; ".join(e["notes"]) + "."
        entry["note"] = kit.mask(note)
        steps[key] = entry
    path.write_text(cg.PROGRESS_HEADER + kit.mask(yaml.safe_dump(prog, sort_keys=False, allow_unicode=True,
                                                                  width=120)))


# ---------------------------------------------------------------------------------------------------- commands
def print_recorded(client, kit, out=print):
    for r in client.recorded:
        out(kit.mask(f"would send: {r['method']} {r['path']}" +
                     (f" {json.dumps(r['json'], ensure_ascii=False)}" if r.get("json") else "") +
                     (f" ({r['file']}, {r['bytes']} bytes)" if r.get("file") else "")))


def cmd_status(client, kit, args):
    app = find_app(client, kit.bundle_id)
    if not app:
        print(f"No app with bundle id {kit.bundle_id}. Create the app record in the browser (Apps › + › New App).")
        return 1
    versions = client.get_all(f"/v1/apps/{app['id']}/appStoreVersions", {"filter[platform]": "IOS", "limit": 200})
    target, editable, live_v = pick_versions(versions, kit.version)
    builds = client.get_all("/v1/builds", {"filter[app]": app["id"], "sort": "-uploadedDate", "limit": 20})
    processed = next((b for b in builds if attrs(b).get("processingState") == "VALID"), None)

    def v(x):
        return {"id": x["id"], "versionString": attrs(x).get("versionString"), "appVersionState": vstate(x),
                "releaseType": attrs(x).get("releaseType"), "createdDate": attrs(x).get("createdDate")} if x else None

    def b(x):
        return {"id": x["id"], "version": attrs(x).get("version"), "processingState": attrs(x).get("processingState"),
                "uploadedDate": attrs(x).get("uploadedDate"), "expired": attrs(x).get("expired")} if x else None
    out = {"read": dt.datetime.now().isoformat(timespec="seconds"),
           "app": {"id": app["id"], "name": attrs(app).get("name"), "bundleId": attrs(app).get("bundleId"),
                   "primaryLocale": attrs(app).get("primaryLocale")},
           "kit_version": kit.version, "kit_build": kit.build,
           "versions": [v(x) for x in versions], "kit_version_on_connect": v(target), "editable_version": v(editable),
           "live_version": v(live_v), "first_version": is_first(versions), "builds": [b(x) for x in builds],
           "latest_processed_build": b(processed), "rate_limit_remaining": client.rate_remaining}
    (kit.path / LIVE_JSON).write_text(kit.mask(json.dumps(out, indent=2, ensure_ascii=False)) + "\n")
    print(f"{out['app']['name']} (app id {app['id']}, {kit.bundle_id})")
    for x in out["versions"]:
        print(f"  version {x['versionString']}: {x['appVersionState']}")
    print(f"  editable: {editable and attrs(editable).get('versionString') or 'none'}; "
          f"live: {live_v and attrs(live_v).get('versionString') or 'none'}; "
          f"{'first release' if out['first_version'] else 'update'} journey")
    if processed:
        print(f"  latest processed build: {attrs(processed).get('version')} ({attrs(processed).get('uploadedDate')})")
    else:
        print("  no processed build yet")
    print(f"wrote {LIVE_JSON}")
    return 0


def parse_only(s):
    if not s:
        return set(AREAS)
    out = {x.strip() for x in s.split(",") if x.strip()}
    bad = out - set(AREAS)
    if bad:
        raise SystemExit(f"--only: unknown area(s) {', '.join(sorted(bad))}; use {', '.join(AREAS)}")
    return out


def cmd_plan(client, kit, args):
    areas = parse_only(args.only)
    live = read_live(client, kit, areas)
    P = build_plan(kit, live, areas)
    pj = plan_json(P)
    (kit.path / PLAN_JSON).write_text(kit.mask(json.dumps(pj, indent=2, ensure_ascii=False)) + "\n")
    (kit.path / PLAN_MD).write_text(kit.mask(render_plan_md(pj, P.media_rows)) + "\n")
    print(f"wrote {PLAN_JSON} and {PLAN_MD}: {len(pj['items'])} change(s), {len(pj['warnings'])} warning(s), "
          f"{sum(not s['done'] for s in pj['browser_steps'])} browser step(s), "
          f"{sum(not s['done'] for s in pj['person_steps'])} person step(s) open")
    for w in pj["warnings"]:
        print(kit.mask(f"warning: {w}"))
    return 0 if live.get("app") else 1


def cmd_apply(client, kit, args, poll_wait=5):
    path = kit.path / PLAN_JSON
    if not path.exists():
        print(f"No {PLAN_JSON}: run `asc_sync.py plan KIT` first and show connect-plan.md to the owner.")
        return 2
    pj = json.loads(path.read_text())
    if not pj.get("app_id"):
        print("The plan has no app: create the app record first, then plan again.")
        return 1
    ctx = Ctx(client, kit, pj, poll_wait=poll_wait)
    errors = run_apply(ctx, parse_only(args.only) if args.only else None)
    if client.dry_run:
        print_recorded(client, kit)
        print(f"dry run: {len(client.recorded)} call(s) would be sent; nothing changed")
    else:
        (kit.path / ASSETS_JSON).write_text(json.dumps(ctx.assets, indent=2, ensure_ascii=False) + "\n")
        write_progress(kit, ctx.progress)
        print(f"applied {len(pj['items']) - len(errors)} of {len(pj['items'])} item(s); "
              f"updated {cg.PROGRESS_FILE} ({len(ctx.progress)} step(s)) and {ASSETS_JSON}")
    for title, err in errors:
        print(f"error: {title}: {err}")
    return 1 if errors else 0


def draft_item_kinds(client, submission_id):
    """Relationship names that carry data on a draft submission's items (appStoreVersion, inAppPurchaseV2, ...).
    UNCONFIRMED shape: items list their target as a relationship with data when included."""
    kinds = set()
    try:
        items = client.get_all(f"/v1/reviewSubmissions/{submission_id}/items", {"limit": 50})
    except ASCError:
        return kinds
    for it in items:
        for name, rel in (it.get("relationships") or {}).items():
            if isinstance(rel, dict) and rel.get("data"):
                kinds.add(name)
        if not it.get("relationships"):
            kinds.add("unknown")
    return kinds


def cmd_submit(client, kit, args):
    app = find_app(client, kit.bundle_id)
    if not app:
        print(f"No app with bundle id {kit.bundle_id}.")
        return 1
    versions = client.get_all(f"/v1/apps/{app['id']}/appStoreVersions", {"filter[platform]": "IOS", "limit": 200})
    target, _, _ = pick_versions(versions, kit.version)
    if not target or vstate(target) not in EDITABLE:
        print(f"Version {kit.version} is {vstate(target) or 'missing'}: nothing to submit.")
        return 1
    existing = client.get_all("/v1/reviewSubmissions", {"filter[app]": app["id"], "filter[platform]": "IOS",
                                                         "filter[state]": "READY_FOR_REVIEW", "limit": 20})
    draft_items = draft_item_kinds(client, existing[0]["id"]) if existing else set()
    if is_first(versions) and kit.iaps():
        pending = []
        for f in kit.iaps():
            L = read_iap(client, app["id"], f.get("product_id"), kit, details=False)
            if attrs(L.get("iap")).get("state") != "APPROVED":
                pending.append(f.get("product_id"))
        # The first purchase can't be added through the API. It is in the draft once the owner (or Chrome, with a
        # yes) pressed Add for Review on the purchase's page: the draft then holds an item that isn't the version.
        if pending and not (draft_items - {"appStoreVersion"}):
            print("Refused: this is the app's first version and its first in-app purchase "
                  f"({', '.join(pending)}) has never been approved. Apple takes the first purchase only in the "
                  "same submission as the version, and only from the purchase's own page (the API can't add it). "
                  "Open In-App Purchases › the purchase › Add for Review (a yes), then run this again:\n  "
                  f"https://appstoreconnect.apple.com/apps/{app['id']}/distribution/iaps")
            return 1
    if not args.yes and not client.dry_run:
        print("Submitting sends the app to App Review: ask the owner, then run again with --yes.")
        return 2
    if existing:
        sid = existing[0]["id"]
    else:
        r = client.post("/v1/reviewSubmissions", body("reviewSubmissions", {"platform": "IOS"},
                                                      relationships={"app": ref("apps", app["id"])}))
        sid = r["data"]["id"]
    if "appStoreVersion" not in draft_items:
        client.post("/v1/reviewSubmissionItems", body("reviewSubmissionItems", None, relationships={
            "reviewSubmission": ref("reviewSubmissions", sid),
            "appStoreVersion": ref("appStoreVersions", target["id"])}))
    client.patch(f"/v1/reviewSubmissions/{sid}", body("reviewSubmissions", {"submitted": True}, id=sid))
    if client.dry_run:
        print_recorded(client, kit)
        return 0
    write_progress(kit, {"submit/add-for-review-then-submit-for-review":
                         {"live": {}, "notes": [f"Version {kit.version} submitted for review"]}})
    print(f"submitted version {kit.version} for review (submission {sid})")
    return 0


def cmd_release(client, kit, args):
    if args.pause and args.resume:
        print("--pause and --resume together make no sense")
        return 2
    app = find_app(client, kit.bundle_id)
    if not app:
        print(f"No app with bundle id {kit.bundle_id}.")
        return 1
    versions = client.get_all(f"/v1/apps/{app['id']}/appStoreVersions", {"filter[platform]": "IOS", "limit": 200})
    target, _, live_v = pick_versions(versions, kit.version)
    if args.pause or args.resume:
        v = target or live_v
        ph = get_one(client, f"/v1/appStoreVersions/{v['id']}/appStoreVersionPhasedRelease") if v else None
        if not ph:
            print(f"Version {kit.version} has no phased release.")
            return 1
        want = "PAUSED" if args.pause else "ACTIVE"
        if attrs(ph).get("phasedReleaseState") == want:
            print(f"Phased release is already {want}.")
            return 0
        if not args.yes and not client.dry_run:
            print(f"Changing the phased release to {want}: ask the owner, then run again with --yes.")
            return 2
        client.patch(f"/v1/appStoreVersionPhasedReleases/{ph['id']}",
                     body("appStoreVersionPhasedReleases", {"phasedReleaseState": want}, id=ph["id"]))
        if client.dry_run:
            print_recorded(client, kit)
        else:
            print(f"phased release {want.lower()}")
        return 0
    if not target or vstate(target) != "PENDING_DEVELOPER_RELEASE":
        print(f"Version {kit.version} is {vstate(target) or 'missing'}: only a version in PENDING_DEVELOPER_RELEASE "
              f"can be released.")
        return 1
    if not args.yes and not client.dry_run:
        print("Releasing puts the version on the App Store for everyone: ask the owner, then run again with --yes.")
        return 2
    client.post("/v1/appStoreVersionReleaseRequests", body("appStoreVersionReleaseRequests", None, relationships={
        "appStoreVersion": ref("appStoreVersions", target["id"])}))
    if client.dry_run:
        print_recorded(client, kit)
        return 0
    write_progress(kit, {"release/release-this-version": {"live": {}, "notes": [f"Version {kit.version} released"]}})
    print(f"released version {kit.version}")
    return 0


COMMANDS = {"status": cmd_status, "plan": cmd_plan, "apply": cmd_apply, "submit": cmd_submit, "release": cmd_release}


def main(argv=None, client=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=list(COMMANDS))
    ap.add_argument("kit")
    ap.add_argument("--locale", action="append", help="limit to these locales (repeat or comma list)")
    ap.add_argument("--only", help="comma list of areas: " + ",".join(AREAS))
    ap.add_argument("--dry-run", action="store_true", help="print the writes instead of sending them")
    ap.add_argument("--yes", action="store_true", help="the owner said yes to this exact step")
    ap.add_argument("--pause", action="store_true", help="release: pause the phased release")
    ap.add_argument("--resume", action="store_true", help="release: resume the phased release")
    ap.add_argument("--key-id")
    ap.add_argument("--issuer-id")
    ap.add_argument("--key-path")
    a = ap.parse_args(argv)
    kit = Kit(a.kit, a.locale)
    if not kit.bundle_id:
        print("facts.yaml has no app.bundle_id")
        return 2
    if a.command == "apply" and not a.yes and not a.dry_run:
        print("apply changes App Store Connect: show connect-plan.md to the owner, then run again with --yes "
              "(or use --dry-run to see the calls).")
        return 2
    if client is None:
        try:
            client = make_client(a, kit=kit.path, dry_run=a.dry_run)
        except ConfigError as e:
            print(f"API key: {e}")
            return 2
    client.dry_run = client.dry_run or a.dry_run
    try:
        return COMMANDS[a.command](client, kit, a)
    except ASCError as e:
        print(kit.mask(f"App Store Connect error: {e}"))
        return 1


if __name__ == "__main__":
    sys.exit(main())
