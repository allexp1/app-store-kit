import hashlib
import json

import pytest
import yaml
from PIL import Image

import asc_api as api
import asc_sync as sync
from fake_asc import FakeASC

PHONE = "+1 555 010 9999"
BUNDLE = "com.example.pebble"


def jpeg(path, color, size=(60, 120)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG")
    return path


def make_kit(tmp_path, version="1.0.0", first=True):
    kit = tmp_path / "kit"
    kit.mkdir()
    facts = {"app": {"name": "Pebble", "bundle_id": BUNDLE, "version": version, "build": "3"},
             "locales": ["en-US", "de-DE"], "first_version": first, "copyright": "2026 Example Ltd",
             "urls": {"privacy_policy": "https://example.com/privacy", "support": "https://example.com/support"},
             "category": {"primary": "Photo & Video", "secondary": "Utilities"},
             "monetization": {"iap": [{"product_id": "com.example.pebble.pro", "type": "Non-Consumable",
                                       "reference_name": "Pebble Pro", "display_name": "Pebble Pro",
                                       "description": "Removes every ad.", "price": "2.99 USD"}]}}
    meta = {"en-US": {"name": "Pebble: Photo Cleaner", "subtitle": "Swipe to tidy your library",
                      "description": "Pebble clears your library.", "keywords": "declutter,storage",
                      "promotional_text": "Tidy up over a coffee.", "support_url": "https://example.com/support",
                      "whats_new": "Faster swiping.", "review_notes_file": "review-notes.md"},
            "de-DE": {"name": "Pebble: Fotos aufräumen", "subtitle": "Wischen und aufräumen",
                      "description": "Pebble räumt deine Mediathek auf.", "keywords": "speicher,ordnung",
                      "promotional_text": "Aufräumen beim Kaffee.", "whats_new": "Schneller wischen.",
                      "iap": [{"product_id": "com.example.pebble.pro", "display_name": "Pebble Pro",
                               "description": "Entfernt jede Werbung."}]}}
    conn = {"locale": "en-US",
            "review_contact": {"first_name": "Ada", "last_name": "Example", "email": "ada@example.com"},
            "sign_in_required": False,
            "content_rights": {"answer": "uses_third_party"},
            "age_rating": {"expected_rating": "4+", "advertising": {"answer": True, "why": "ads"},
                           "contests": "None", "violenceRealistic": "Infrequent", "override": "Not Applicable",
                           "madeUpQuestion": True},
            "accessibility": {"devices": {"iPhone": {"VoiceOver": {"answer": True}, "Larger Text": True}}},
            "version": {"release": {"answer": "manual"}, "phased_release": True},
            "iap": [{"product_id": "com.example.pebble.pro", "review_screenshot": "iap/pro-review.png (Settings)"}]}
    (kit / "facts.yaml").write_text(yaml.safe_dump(facts, allow_unicode=True))
    for loc, m in meta.items():
        (kit / f"metadata.{loc}.yaml").write_text(yaml.safe_dump(m, allow_unicode=True))
    (kit / "connect.yaml").write_text(yaml.safe_dump(conn, allow_unicode=True))
    (kit / "private.yaml").write_text(yaml.safe_dump({"review_contact": {"phone": PHONE}}))
    (kit / "review-notes.md").write_text("# Notes\n\n---\n\nTap Try samples to see Pebble.\n\n---\n")
    jpeg(kit / "screenshots/en-US/iphone-di-medium/01.jpg", "red")
    jpeg(kit / "screenshots/en-US/iphone-di-medium/02.jpg", "blue")
    jpeg(kit / "iap/pro-review.png", "green")
    return kit


def seed(fake, version_state="PREPARE_FOR_SUBMISSION", version="1.0.0", iap_state="READY_TO_SUBMIT"):
    app = fake.add("apps", {"bundleId": BUNDLE, "name": "Pebble", "primaryLocale": "en-US"}, id="app1")
    info = fake.add("appInfos", {"state": "PREPARE_FOR_SUBMISSION"}, {"app": ("apps", app)}, id="info1")
    fake.add("ageRatingDeclarations", {"advertising": False, "contests": "NONE"}, {"appInfo": ("appInfos", info)},
             id="age1")
    fake.add("appInfoLocalizations", {"locale": "en-US", "name": "Pebble"}, {"appInfo": ("appInfos", info)})
    v = fake.add("appStoreVersions", {"versionString": version, "appVersionState": version_state,
                                      "platform": "IOS", "createdDate": "2026-10-01"}, {"app": ("apps", app)}, id="ver1")
    fake.add("appStoreVersionLocalizations", {"locale": "en-US", "description": "old text"},
             {"appStoreVersion": ("appStoreVersions", v)}, id="vloc-en")
    fake.add("builds", {"version": "3", "processingState": "VALID"}, {"app": ("apps", app)}, id="build3")
    fake.add("appAssetLibraries", {}, {"app": ("apps", app)}, id="lib1")
    iap = fake.add("inAppPurchases", {"productId": "com.example.pebble.pro", "state": iap_state},
                   {"app": ("apps", app)}, id="iap1")
    fake.add("inAppPurchaseVersions", {"state": "PREPARE_FOR_SUBMISSION"},
             {"inAppPurchase": ("inAppPurchases", iap)}, id="iapv1")
    return app


def run(fake, *argv, dry=False):
    c = api.Client(lambda: "TOKEN", transport=fake, sleep=lambda s: None, dry_run=dry)
    return sync.main([*argv], client=c), c


# ------------------------------------------------------------------------------------------------ plan
def test_plan_first_version(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    code, client = run(fake, "plan", str(kit))
    assert code == 0
    assert all(m == "GET" for m, *_ in fake.calls), "plan must only read"
    pj = json.loads((kit / "connect-plan.json").read_text())
    by_op = {}
    for it in pj["items"]:
        by_op.setdefault(it["op"], []).append(it)
    info = {i["locale"]: i for i in by_op["appinfo_loc"]}
    assert info["de-DE"]["target_id"] is None and info["de-DE"]["desired"]["name"] == "Pebble: Fotos aufräumen"
    assert info["en-US"]["attributes"]["name"] == "Pebble: Photo Cleaner"
    vlocs = {i["locale"]: i for i in by_op["version_loc"]}
    assert set(vlocs) == {"en-US", "de-DE"}
    assert all("whatsNew" not in i["desired"] for i in vlocs.values()), "no What's New on a first version"
    media = by_op["media_slot"]
    assert len(media) == 1 and media[0]["group"] == "IPHONE_DYNAMIC_ISLAND_MEDIUM_PROFILE"
    assert [r["action"] for r in media[0]["rows"]] == ["add", "add"]
    assert by_op["categories"][0]["categories"] == {"primary": "PHOTO_AND_VIDEO", "secondary": "UTILITIES"}
    assert by_op["content_rights"][0]["value"] == "USES_THIRD_PARTY_CONTENT"
    age = by_op["age_rating"][0]["attributes"]
    assert age == {"advertising": True, "violenceRealistic": "INFREQUENT", "ageRatingOverrideV2": "NONE"}
    assert any("madeUpQuestion" in w for w in pj["warnings"])
    assert by_op["version_build"][0]["build_id"] == "build3"
    assert [i["attributes"] for i in by_op["version_attrs"]] == [{"copyright": "2026 Example Ltd"},
                                                                 {"releaseType": "MANUAL"}]
    assert "phased_release" not in by_op
    acc = by_op["accessibility"][0]
    assert acc["publish"] is False and acc["attributes"]["supportsVoiceover"] is True
    iap = by_op["iap"][0]
    assert {l["locale"] for l in iap["locs"]} == {"en-US", "de-DE"} and iap["image"]["action"] == "add"
    assert any("de-DE has no screenshots folder" in n for n in pj["notes"])
    assert any("stays a draft" in n for n in pj["notes"])
    browser = " ".join(s["text"] for s in pj["browser_steps"])
    assert "App Privacy" in browser and "apps/app1/distribution/ios/version/inflight" in browser
    assert len(pj["person_steps"]) == 3
    md = (kit / "connect-plan.md").read_text()
    assert "## Store text" in md and "| en-US | iphone-di-medium | screenshots/en-US/iphone-di-medium/01.jpg | add |" in md


def test_plan_masks_private_values(tmp_path):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    run(fake, "plan", str(kit))
    md, pj = (kit / "connect-plan.md").read_text(), (kit / "connect-plan.json").read_text()
    for text in (md, pj):
        assert PHONE not in text and "5550109999" not in text and "010 9999" not in text
    assert "contactPhone | (empty) | [private]" in md
    review = next(i for i in json.loads(pj)["items"] if i["op"] == "review_detail")
    assert review["desired"]["contactPhone"] == {"$private": "phone"}


def seed_update(fake, kit):
    """A live 1.0.0 whose text matches the kit and whose screenshots are the kit's files."""
    app = seed(fake, version_state="READY_FOR_DISTRIBUTION")
    m_en = yaml.safe_load((kit / "metadata.en-US.yaml").read_text())
    m_de = yaml.safe_load((kit / "metadata.de-DE.yaml").read_text())
    fake.store["vloc-en"]["attributes"].update(
        description=m_en["description"], keywords=m_en["keywords"], promotionalText=m_en["promotional_text"],
        supportUrl=m_en["support_url"])
    fake.add("appStoreVersionLocalizations", {
        "locale": "de-DE", "description": m_de["description"], "keywords": m_de["keywords"],
        "promotionalText": m_de["promotional_text"], "supportUrl": "https://example.com/support"},
        {"appStoreVersion": ("appStoreVersions", "ver1")}, id="vloc-de")
    assets = {"assets": {}}
    for i, name in enumerate(["01.jpg", "02.jpg"]):
        f = kit / "screenshots/en-US/iphone-di-medium" / name
        img = fake.add("appAssetLibraryImages", {"fileName": name, "fileSize": f.stat().st_size,
                                                 "state": "PREPARE_FOR_SUBMISSION"},
                       {"assetLibrary": ("appAssetLibraries", "lib1")}, id=f"img{i}")
        fake.add("appAssetLibraryPlacements", {"placementType": "APP_SCREENSHOT",
                                               "placementGroup": "IPHONE_DYNAMIC_ISLAND_MEDIUM_PROFILE",
                                               "placementGroupPosition": i + 1},
                 {"image": ("appAssetLibraryImages", img),
                  "appStoreVersionLocalization": ("appStoreVersionLocalizations", "vloc-en")}, id=f"pl{i}")
        assets["assets"][img] = {"sha256": hashlib.sha256(f.read_bytes()).hexdigest(), "file": name}
    (kit / "connect-assets.json").write_text(json.dumps(assets))
    for k, v in {"name": m_en["name"], "subtitle": m_en["subtitle"],
                 "privacyPolicyUrl": "https://example.com/privacy"}.items():
        next(r for r in fake.of_type("appInfoLocalizations"))["attributes"][k] = v
    fake.add("appInfoLocalizations", {"locale": "de-DE", "name": m_de["name"], "subtitle": m_de["subtitle"],
                                      "privacyPolicyUrl": "https://example.com/privacy"},
             {"appInfo": ("appInfos", "info1")})
    fake.store["iap1"]["attributes"]["state"] = "APPROVED"

    def copy_from_live(new_version):  # Apple copies text and placements into a new version
        for old in list(fake.of_type("appStoreVersionLocalizations")):
            if old["relationships"]["appStoreVersion"]["data"]["id"] == "ver1":
                nid = fake.add("appStoreVersionLocalizations", {k: v for k, v in old["attributes"].items()},
                               {"appStoreVersion": ("appStoreVersions", new_version["id"])})
                for p in list(fake.of_type("appAssetLibraryPlacements")):
                    if p["relationships"]["appStoreVersionLocalization"]["data"]["id"] == old["id"]:
                        fake.add("appAssetLibraryPlacements", dict(p["attributes"]),
                                 {"image": ("appAssetLibraryImages", p["relationships"]["image"]["data"]["id"]),
                                  "appStoreVersionLocalization": ("appStoreVersionLocalizations", nid)})
    fake.on_create["appStoreVersions"] = copy_from_live
    return app


def test_plan_update_creates_version_and_whats_new_only(tmp_path):
    kit = make_kit(tmp_path, version="1.1.0", first=False)
    fake = FakeASC()
    seed_update(fake, kit)
    fake.store["build3"]["attributes"]["version"] = "3"
    run(fake, "plan", str(kit), "--only", "text,media,release")
    pj = json.loads((kit / "connect-plan.json").read_text())
    assert pj["version"]["action"] == "create" and pj["first_version"] is False
    ops = [i["op"] for i in pj["items"]]
    assert ops[0] == "create_version"
    create = pj["items"][0]["attributes"]
    assert create == {"platform": "IOS", "versionString": "1.1.0", "copyright": "2026 Example Ltd",
                      "releaseType": "MANUAL"}
    vlocs = {i["locale"]: i["attributes"] for i in pj["items"] if i["op"] == "version_loc"}
    assert vlocs == {"en-US": {"whatsNew": "Faster swiping."}, "de-DE": {"whatsNew": "Schneller wischen."}}
    assert "appinfo_loc" not in ops and "media_slot" not in ops, "unchanged text and screenshots are skipped"
    assert "phased_release" in ops
    md = (kit / "connect-plan.md").read_text()
    assert "01.jpg | unchanged |" in md and "02.jpg | unchanged |" in md


def test_plan_screenshot_replace_and_size_fallback(tmp_path):
    kit = make_kit(tmp_path, version="1.1.0", first=False)
    fake = FakeASC()
    seed_update(fake, kit)
    (kit / "connect-assets.json").unlink()                      # no hash map: fall back to fileSize
    jpeg(kit / "screenshots/en-US/iphone-di-medium/02.jpg", "yellow", size=(90, 180))
    jpeg(kit / "screenshots/en-US/iphone-di-medium/03.jpg", "white")
    run(fake, "plan", str(kit), "--only", "media")
    pj = json.loads((kit / "connect-plan.json").read_text())
    slot = next(i for i in pj["items"] if i["op"] == "media_slot")
    assert [(r["action"], r.get("matched_by")) for r in slot["rows"]] == [
        ("unchanged", "fileSize"), ("replace", "fileSize"), ("add", None)]


# ------------------------------------------------------------------------------------------------ apply
def test_apply_needs_yes(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    run(fake, "plan", str(kit))
    n = len(fake.calls)
    code, _ = run(fake, "apply", str(kit))
    assert code == 2 and len(fake.calls) == n
    assert "--yes" in capsys.readouterr().out


def test_apply_dry_run_sends_nothing_and_masks(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    run(fake, "plan", str(kit))
    capsys.readouterr()
    code, client = run(fake, "apply", str(kit), "--dry-run")
    out = capsys.readouterr().out
    assert code == 0
    assert fake.writes() == [] and client.recorded
    assert "would send: PATCH /v1/appInfoLocalizations/" in out and "would send: POST /v1/appAssetLibraryImages" in out
    assert PHONE not in out and "[private]" in out
    assert not (kit / "connect-assets.json").exists() and not (kit / "connect-progress.yaml").exists()


def test_apply_first_version_order_progress_and_assets(tmp_path, capsys):
    kit = make_kit(tmp_path)
    (kit / "connect-progress.yaml").write_text(yaml.safe_dump({"steps": {"version/build": {"status": "todo"}}}))
    fake = FakeASC()
    seed(fake)
    run(fake, "plan", str(kit))
    code, _ = run(fake, "apply", str(kit), "--yes")
    out = capsys.readouterr().out
    assert code == 0, out
    writes = fake.writes()

    def first(prefix):
        return next(i for i, (_, p) in enumerate(writes) if p.startswith(prefix))
    assert first("/v1/appInfoLocalizations") < first("/v1/ageRatingDeclarations") < \
        first("/v1/appStoreVersions/ver1/relationships/build") < first("/v1/appStoreReviewDetails") < \
        first("/v1/accessibilityDeclarations") < first("/v2/inAppPurchaseLocalizations") < \
        first("/v1/appAssetLibraryImages")
    # the review detail went out with the real phone; the store now has it
    rd = fake.of_type("appStoreReviewDetails")[0]["attributes"]
    assert rd["contactPhone"] == PHONE and rd["notes"] == "Tap Try samples to see Pebble."
    # screenshots: reserve → PUT → commit → place → order
    paths = [p for _, p, *_ in fake.calls]
    assert any(p.startswith("upload:/appAssetLibraryImages") for p in paths)
    placements = [p for p in fake.of_type("appAssetLibraryPlacements")]
    assert len(placements) == 2 and fake.of_type("appAssetLibraryPlacementOrderingRequests")
    assert all(p["attributes"]["placementGroup"] == "IPHONE_DYNAMIC_ISLAND_MEDIUM_PROFILE" for p in placements)
    de = [r for r in fake.of_type("appStoreVersionLocalizations") if r["attributes"]["locale"] == "de-DE"]
    assert de and de[0]["attributes"]["description"] == "Pebble räumt deine Mediathek auf."
    assert fake.store["app1"]["attributes"]["contentRightsDeclaration"] == "USES_THIRD_PARTY_CONTENT"
    assert fake.store["ver1"]["relationships"]["build"]["data"]["id"] == "build3"
    assert fake.of_type("accessibilityDeclarations")[0]["attributes"].get("state") != "PUBLISHED"
    assets = json.loads((kit / "connect-assets.json").read_text())["assets"]
    shas = {a["sha256"] for a in assets.values()}
    assert hashlib.sha256((kit / "screenshots/en-US/iphone-di-medium/01.jpg").read_bytes()).hexdigest() in shas
    prog_text = (kit / "connect-progress.yaml").read_text()
    assert PHONE not in prog_text and prog_text.startswith("# App Store Connect progress")
    steps = yaml.safe_load(prog_text)["steps"]
    assert steps["version/build"]["status"] == "done-by-claude"
    assert steps["version/build"]["live"] == {"Build › +": "1.0.0 (3)"}
    assert steps["version/app-review-information"]["live"]["Contact › Phone number"] == "[private]"
    assert steps["app-information/name-subtitle-and-category"]["live"]["Category › Primary"] == "Photo & Video"
    assert steps["accessibility/add-iphone-support"]["live"]["Supported Features"] == "VoiceOver, Larger Text"
    assert steps["iap/pebble-pro-display-name-and-description-scroll-down-press-add"]["live"]["Display Name"] == "Pebble Pro"
    # a second plan finds nothing left to do in text and media
    run(fake, "plan", str(kit), "--only", "text,media")
    pj = json.loads((kit / "connect-plan.json").read_text())
    assert pj["items"] == []


def test_apply_update_skips_unchanged_screenshots(tmp_path):
    kit = make_kit(tmp_path, version="1.1.0", first=False)
    fake = FakeASC()
    seed_update(fake, kit)
    run(fake, "plan", str(kit), "--only", "text,media,release")
    code, _ = run(fake, "apply", str(kit), "--yes")
    assert code == 0
    new = [v for v in fake.of_type("appStoreVersions") if v["attributes"]["versionString"] == "1.1.0"][0]
    locs = [r for r in fake.of_type("appStoreVersionLocalizations")
            if r["relationships"]["appStoreVersion"]["data"]["id"] == new["id"]]
    assert {r["attributes"]["whatsNew"] for r in locs} == {"Faster swiping.", "Schneller wischen."}
    assert not any(p.startswith("/v1/appAssetLibraryImages") for _, p in fake.writes())
    assert fake.of_type("appStoreVersionPhasedReleases")[0]["relationships"]["appStoreVersion"]["data"]["id"] == new["id"]


def test_apply_continues_past_a_failure(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    run(fake, "plan", str(kit))
    fake.fail[("PATCH", "/v1/ageRatingDeclarations/age1")] = (409, "ENTITY_ERROR.ATTRIBUTE.INVALID")
    code, _ = run(fake, "apply", str(kit), "--yes")
    out = capsys.readouterr().out
    assert code == 1 and "error: Age rating answers" in out
    assert fake.of_type("appStoreReviewDetails"), "items after the failure still ran"
    steps = yaml.safe_load((kit / "connect-progress.yaml").read_text())["steps"]
    assert "app-information/age-rating-set-up-age-ratings" not in steps


def test_apply_only_limits_areas(tmp_path):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    run(fake, "plan", str(kit))
    run(fake, "apply", str(kit), "--yes", "--only", "age")
    assert [p for _, p in fake.writes()] == ["/v1/ageRatingDeclarations/age1"]


# ------------------------------------------------------------------------------------------------ submit, release
def test_submit_refuses_first_iap(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    code, _ = run(fake, "submit", str(kit), "--yes")
    out = capsys.readouterr().out
    assert code == 1 and fake.writes() == []
    assert "https://appstoreconnect.apple.com/apps/app1/distribution/iaps" in out
    assert "first in-app purchase" in out and "Add for Review" in out


def test_submit_needs_yes_then_runs_review_submission(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake, iap_state="APPROVED")
    code, _ = run(fake, "submit", str(kit))
    assert code == 2 and fake.writes() == []
    code, _ = run(fake, "submit", str(kit), "--yes")
    assert code == 0
    assert [w for w in fake.writes()] == [("POST", "/v1/reviewSubmissions"), ("POST", "/v1/reviewSubmissionItems"),
                                          ("PATCH", f"/v1/reviewSubmissions/{fake.of_type('reviewSubmissions')[0]['id']}")]
    assert fake.of_type("reviewSubmissions")[0]["attributes"]["submitted"] is True
    steps = yaml.safe_load((kit / "connect-progress.yaml").read_text())["steps"]
    assert steps["submit/add-for-review-then-submit-for-review"]["status"] == "done-by-claude"


def test_release_paths(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    code, _ = run(fake, "release", str(kit), "--yes")
    assert code == 1 and "PENDING_DEVELOPER_RELEASE" in capsys.readouterr().out
    fake.store["ver1"]["attributes"]["appVersionState"] = "PENDING_DEVELOPER_RELEASE"
    code, _ = run(fake, "release", str(kit))
    assert code == 2 and fake.writes() == []
    code, _ = run(fake, "release", str(kit), "--yes")
    assert code == 0 and fake.writes() == [("POST", "/v1/appStoreVersionReleaseRequests")]


def test_release_pause_resume(tmp_path):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake, version_state="READY_FOR_DISTRIBUTION")
    ph = fake.add("appStoreVersionPhasedReleases", {"phasedReleaseState": "ACTIVE"},
                  {"appStoreVersion": ("appStoreVersions", "ver1")})
    code, _ = run(fake, "release", str(kit), "--pause", "--yes")
    assert code == 0 and fake.store[ph]["attributes"]["phasedReleaseState"] == "PAUSED"
    code, _ = run(fake, "release", str(kit), "--resume", "--yes")
    assert code == 0 and fake.store[ph]["attributes"]["phasedReleaseState"] == "ACTIVE"


def test_status_writes_live_json(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    code, _ = run(fake, "status", str(kit))
    assert code == 0
    live = json.loads((kit / "connect-live.json").read_text())
    assert live["app"]["id"] == "app1" and live["editable_version"]["versionString"] == "1.0.0"
    assert live["latest_processed_build"]["version"] == "3" and live["first_version"] is True
    assert PHONE not in (kit / "connect-live.json").read_text()
    assert "first release" in capsys.readouterr().out


def test_missing_key_config_is_reported(tmp_path, capsys, monkeypatch):
    kit = make_kit(tmp_path)
    for k in ("ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_KEY_PATH", "API_PRIVATE_KEYS_DIR"):
        monkeypatch.delenv(k, raising=False)
    assert sync.main(["status", str(kit)]) == 2
    assert "API key" in capsys.readouterr().out


def test_submit_first_iap_goes_ahead_once_the_purchase_is_in_the_draft(tmp_path, capsys):
    """Live 2026-10-14: the first purchase joins the draft from its own page; submit then adds the version only."""
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    sub = fake.add("reviewSubmissions", {"platform": "IOS", "state": "READY_FOR_REVIEW"}, {"app": ("apps", "app1")},
                   id="sub1")
    fake.add("reviewSubmissionItems", {"state": "READY_FOR_REVIEW"},
             {"reviewSubmission": ("reviewSubmissions", sub), "inAppPurchaseV2": ("inAppPurchases", "iap1")})
    code, _ = run(fake, "submit", str(kit), "--yes")
    assert code == 0
    assert fake.writes() == [("POST", "/v1/reviewSubmissionItems"), ("PATCH", "/v1/reviewSubmissions/sub1")]


def png(path, color, size=(160, 90)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "PNG")
    return path


def test_universal_creative_asset_is_uploaded_once_and_placed_twice(tmp_path, capsys):
    kit = make_kit(tmp_path)
    png(kit / "creative/en-US/universal.png", "yellow")
    fake = FakeASC()
    seed(fake)
    run(fake, "plan", str(kit), "--only", "media")
    plan = (kit / "connect-plan.md").read_text()
    assert "Header" in plan and "Search results" in plan
    code, _ = run(fake, "apply", str(kit), "--yes")
    assert code == 0, capsys.readouterr().out
    creative = [i for i in fake.of_type("appAssetLibraryImages") if i["attributes"]["category"] == "CREATIVE_ASSETS"]
    assert len(creative) == 1
    placed = {p["attributes"]["placementType"]: p for p in fake.of_type("appAssetLibraryPlacements")
              if p["attributes"]["placementGroup"] == "DEFAULT_PROFILE"}
    assert set(placed) == {"PRODUCT_PAGE_HEADER_ASSET", "APP_STORE_SEARCH_RESULTS_ASSET"}
    assert {p["relationships"]["image"]["data"]["id"] for p in placed.values()} == {creative[0]["id"]}
    assert not any(o["attributes"]["placementGroup"] == "DEFAULT_PROFILE"
                   for o in fake.of_type("appAssetLibraryPlacementOrderingRequests"))
    steps = yaml.safe_load((kit / "connect-progress.yaml").read_text())["steps"]
    assert "version/header-and-search-results" in steps
    run(fake, "plan", str(kit), "--only", "media")
    assert json.loads((kit / "connect-plan.json").read_text())["items"] == []


def test_header_file_overrides_universal_for_the_header_only(tmp_path):
    kit = make_kit(tmp_path)
    png(kit / "creative/en-US/universal.png", "yellow")
    png(kit / "creative/en-US/header.png", "purple", size=(210, 90))
    assert sync.local_creative(sync.Kit(kit), "en-US") == {
        "PRODUCT_PAGE_HEADER_ASSET": kit / "creative/en-US/header.png",
        "APP_STORE_SEARCH_RESULTS_ASSET": kit / "creative/en-US/universal.png"}
    fake = FakeASC()
    seed(fake)
    run(fake, "plan", str(kit), "--only", "media")
    code, _ = run(fake, "apply", str(kit), "--yes")
    assert code == 0
    assert len([i for i in fake.of_type("appAssetLibraryImages")
                if i["attributes"]["category"] == "CREATIVE_ASSETS"]) == 2


def test_creative_groups_come_from_the_ref_data_not_a_constant():
    assert sync.creative_groups(FakeASC().refdata) == {"PRODUCT_PAGE_HEADER_ASSET": "DEFAULT_PROFILE",
                                                       "APP_STORE_SEARCH_RESULTS_ASSET": "DEFAULT_PROFILE"}
    # the DEFAULT_PROFILE group (platform ANY) never becomes a screenshot group
    assert "DEFAULT" not in sync.placement_groups(FakeASC().refdata)
