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


def test_plan_without_a_recorded_hash_keeps_same_size_files_but_flags_them(tmp_path, capsys):
    kit = make_kit(tmp_path, version="1.1.0", first=False)
    fake = FakeASC()
    seed_update(fake, kit)
    (kit / "connect-assets.json").unlink()                      # uploaded before sha256 tracking
    jpeg(kit / "screenshots/en-US/iphone-di-medium/02.jpg", "yellow", size=(90, 180))   # another size
    jpeg(kit / "screenshots/en-US/iphone-di-medium/03.jpg", "white")
    run(fake, "plan", str(kit), "--only", "media")
    pj = json.loads((kit / "connect-plan.json").read_text())
    slot = next(i for i in pj["items"] if i["op"] == "media_slot")
    assert [(r["action"], r.get("matched_by")) for r in slot["rows"]] == [
        ("unchanged", "fileSize (unverified)"), ("replace", "fileSize"), ("add", None)]
    assert any("matched by size only" in w and "01.jpg" in w for w in pj["warnings"])
    assert "01.jpg | unchanged (matched by size only" in (kit / "connect-plan.md").read_text()
    run(fake, "plan", str(kit), "--only", "media", "--reupload-unverified")
    slot = next(i for i in json.loads((kit / "connect-plan.json").read_text())["items"] if i["op"] == "media_slot")
    assert [(r["action"], r.get("matched_by")) for r in slot["rows"]] == [
        ("replace", "unknown"), ("replace", "fileSize"), ("add", None)]
    assert "--reupload-unverified" in slot["rows"][0]["why"]


def test_apply_previews_keeps_size_matched_screenshots_untouched_on_the_next_plan(tmp_path, capsys):
    kit = make_kit(tmp_path, version="1.1.0", first=False)
    fake = FakeASC()
    seed_update(fake, kit)
    (kit / "connect-assets.json").unlink()
    for n in ("01.mp4", "02.mp4"):
        f = kit / "previews/en-US/iphone-di-medium" / n
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(n.encode() * 100)
    run(fake, "plan", str(kit), "--only", "media")
    pj = json.loads((kit / "connect-plan.json").read_text())
    assert [i["title"] for i in pj["items"] if i["op"] == "media_slot"] == ["Previews iphone-di-medium (en-US)"]
    assert run(fake, "apply", str(kit), "--yes")[0] == 0, capsys.readouterr().out
    assert len(fake.of_type("appAssetLibraryVideos")) == 2 and len(fake.of_type("appAssetLibraryImages")) == 2
    assets = json.loads((kit / "connect-assets.json").read_text())["assets"]
    assert "img0" not in assets and "img1" not in assets, "a size-matched file's sha256 is never recorded"
    run(fake, "plan", str(kit), "--only", "media")
    pj = json.loads((kit / "connect-plan.json").read_text())
    assert pj["items"] == []
    md = (kit / "connect-plan.md").read_text()
    assert "01.jpg | unchanged (matched by size only" in md and "01.mp4 | unchanged |" in md


def test_plan_compares_a_live_checksum_when_there_is_no_recorded_hash(tmp_path):
    kit = make_kit(tmp_path, version="1.1.0", first=False)
    fake = FakeASC()
    seed_update(fake, kit)
    (kit / "connect-assets.json").unlink()
    shot = kit / "screenshots/en-US/iphone-di-medium"
    fake.store["img0"]["attributes"]["sourceFileChecksum"] = hashlib.md5((shot / "01.jpg").read_bytes()).hexdigest()
    jpeg(shot / "02.jpg", "yellow")                             # other bytes, recorded as the same size
    fake.store["img1"]["attributes"]["fileSize"] = (shot / "02.jpg").stat().st_size
    fake.store["img1"]["attributes"]["sourceFileChecksum"] = "0" * 32
    run(fake, "plan", str(kit), "--only", "media")
    slot = next(i for i in json.loads((kit / "connect-plan.json").read_text())["items"] if i["op"] == "media_slot")
    assert [(r["action"], r.get("matched_by")) for r in slot["rows"]] == [("unchanged", "checksum"),
                                                                         ("replace", "checksum")]


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


# ------------------------------------------------------------------------------------------------ audit fixes
def test_private_values_compare_by_digits_only_when_they_look_like_phone_numbers():
    priv = {"phone": "+1 (555) 010-9999", "demo_password": "new123456"}
    assert sync.diff({"contactPhone": "+15550109999"}, {"contactPhone": {"$private": "phone"}}, private=priv) == []
    ch = sync.diff({"demoAccountPassword": "old123456"}, {"demoAccountPassword": {"$private": "demo_password"}},
                   private=priv)
    assert [c["field"] for c in ch] == ["demoAccountPassword"] and ch[0]["new"] == "[private]"
    assert sync.diff({"demoAccountPassword": "new123456"},
                     {"demoAccountPassword": {"$private": "demo_password"}}, private=priv) == []


def test_empty_optional_text_clears_and_absent_text_is_left_alone(tmp_path, capsys):
    kit = make_kit(tmp_path, version="1.1.0", first=False)
    fake = FakeASC()
    seed_update(fake, kit)
    fake.store["vloc-en"]["attributes"]["marketingUrl"] = "https://example.com/old"
    m = yaml.safe_load((kit / "metadata.en-US.yaml").read_text())
    m["promotional_text"] = ""                     # present and empty: clear it
    m["subtitle"] = None                           # present and null: clear it too
    m.pop("description")                           # absent: leave the live text alone
    (kit / "metadata.en-US.yaml").write_text(yaml.safe_dump(m, allow_unicode=True))
    run(fake, "plan", str(kit), "--only", "text")
    pj = json.loads((kit / "connect-plan.json").read_text())
    en = next(i for i in pj["items"] if i["op"] == "version_loc" and i["locale"] == "en-US")
    assert en["attributes"] == {"promotionalText": None, "whatsNew": "Faster swiping."}
    info = next(i for i in pj["items"] if i["op"] == "appinfo_loc" and i["locale"] == "en-US")
    assert info["attributes"] == {"subtitle": None}
    assert run(fake, "apply", str(kit), "--yes")[0] == 0, capsys.readouterr().out
    new = next(v for v in fake.of_type("appStoreVersions") if v["attributes"]["versionString"] == "1.1.0")
    loc = next(r for r in fake.of_type("appStoreVersionLocalizations") if r["attributes"]["locale"] == "en-US"
               and r["relationships"]["appStoreVersion"]["data"]["id"] == new["id"])
    assert loc["attributes"]["promotionalText"] is None and loc["attributes"]["description"]
    assert loc["attributes"]["marketingUrl"] == "https://example.com/old"   # not in the kit: untouched


def test_apply_refuses_when_a_planned_file_changed(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    run(fake, "plan", str(kit))
    assert json.loads((kit / "connect-plan.json").read_text())["fingerprint"]["files"]
    jpeg(kit / "screenshots/en-US/iphone-di-medium/01.jpg", "black")
    capsys.readouterr()
    code, _ = run(fake, "apply", str(kit), "--yes")
    out = capsys.readouterr().out
    assert code == 1 and fake.writes() == []
    assert "re-run plan" in out.lower() and "01.jpg changed after the plan" in out


def test_apply_refuses_when_the_live_media_changed(tmp_path, capsys):
    kit = make_kit(tmp_path, version="1.0.0")
    fake = FakeASC()
    seed(fake)
    run(fake, "plan", str(kit), "--only", "media")
    fake.add("appAssetLibraryImages", {"fileName": "x.jpg", "fileSize": 1}, id="imgX")
    fake.add("appAssetLibraryPlacements", {"placementType": "APP_SCREENSHOT",
                                           "placementGroup": "IPHONE_DYNAMIC_ISLAND_MEDIUM_PROFILE",
                                           "placementGroupPosition": 1},
             {"image": ("appAssetLibraryImages", "imgX"),
              "appStoreVersionLocalization": ("appStoreVersionLocalizations", "vloc-en")})
    code, _ = run(fake, "apply", str(kit), "--yes")
    assert code == 1 and fake.writes() == []
    assert "live files changed after the plan" in capsys.readouterr().out


def test_apply_media_runs_only_the_plans_rows(tmp_path):
    kit = make_kit(tmp_path, version="1.1.0", first=False)
    fake = FakeASC()
    seed_update(fake, kit)
    jpeg(kit / "screenshots/en-US/iphone-di-medium/02.jpg", "yellow", size=(90, 180))
    run(fake, "plan", str(kit), "--only", "media")
    assert run(fake, "apply", str(kit), "--yes")[0] == 0
    new = next(v for v in fake.of_type("appStoreVersions") if v["attributes"]["versionString"] == "1.1.0")
    new_loc = next(r["id"] for r in fake.of_type("appStoreVersionLocalizations") if r["attributes"]["locale"] == "en-US"
                   and r["relationships"]["appStoreVersion"]["data"]["id"] == new["id"])
    placed = sorted((p for p in fake.of_type("appAssetLibraryPlacements")
                     if p["relationships"]["appStoreVersionLocalization"]["data"]["id"] == new_loc),
                    key=lambda p: p["attributes"]["placementGroupPosition"])
    assert placed[0]["relationships"]["image"]["data"]["id"] == "img0"      # kept
    assert placed[1]["relationships"]["image"]["data"]["id"] not in ("img0", "img1")   # replaced
    assert len([w for w in fake.writes() if w[0] == "DELETE"]) == 1


def test_replayed_plan_is_refused(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    run(fake, "plan", str(kit))
    assert run(fake, "apply", str(kit), "--yes")[0] == 0
    pj = json.loads((kit / "connect-plan.json").read_text())
    assert pj["applied"]["at"] and all(r["result"] == "done" for r in pj["applied"]["results"])
    n = len(fake.writes())
    capsys.readouterr()
    code, _ = run(fake, "apply", str(kit), "--yes")
    assert code == 1 and len(fake.writes()) == n and "already applied" in capsys.readouterr().out


def test_apply_only_consumes_just_those_areas(tmp_path):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    run(fake, "plan", str(kit))
    assert run(fake, "apply", str(kit), "--yes", "--only", "age")[0] == 0
    assert run(fake, "apply", str(kit), "--yes", "--only", "age")[0] == 1
    assert run(fake, "apply", str(kit), "--yes", "--only", "review")[0] == 0


def test_partial_failure_then_replan_picks_up_what_exists(tmp_path, capsys):
    kit = make_kit(tmp_path, version="1.1.0", first=False)
    fake = FakeASC()
    seed_update(fake, kit)
    run(fake, "plan", str(kit), "--only", "text,release")
    fail_on = [None]

    def fail_whats_new(r):   # the new version exists; its localization PATCH will fail
        loc = next(x for x in fake.of_type("appStoreVersionLocalizations") if x["attributes"]["locale"] == "de-DE"
                   and x["relationships"]["appStoreVersion"]["data"]["id"] != "ver1")
        fail_on[0] = loc["id"]
        fake.fail[("PATCH", f"/v1/appStoreVersionLocalizations/{loc['id']}")] = (409, "ENTITY_ERROR")
    orig = fake.on_create["appStoreVersions"]
    fake.on_create["appStoreVersions"] = lambda r: (orig(r), fail_whats_new(r))
    code, _ = run(fake, "apply", str(kit), "--yes")
    assert code == 1
    assert run(fake, "apply", str(kit), "--yes")[0] == 1, "a partly applied plan isn't replayed"
    del fake.fail[("PATCH", f"/v1/appStoreVersionLocalizations/{fail_on[0]}")]
    run(fake, "plan", str(kit), "--only", "text,release")
    pj = json.loads((kit / "connect-plan.json").read_text())
    assert pj["version"]["action"] == "use"
    assert [(i["op"], i.get("locale")) for i in pj["items"]] == [("version_loc", "de-DE")]
    assert run(fake, "apply", str(kit), "--yes")[0] == 0
    assert len([v for v in fake.of_type("appStoreVersions") if v["attributes"]["versionString"] == "1.1.0"]) == 1
    assert len(fake.of_type("appStoreVersionPhasedReleases")) == 1


def test_create_steps_reuse_what_an_earlier_run_made(tmp_path):
    kit = make_kit(tmp_path, version="1.1.0", first=False)
    fake = FakeASC()
    seed_update(fake, kit)
    run(fake, "plan", str(kit), "--only", "text,release")
    fake.add("appStoreVersions", {"versionString": "1.1.0", "appVersionState": "PREPARE_FOR_SUBMISSION",
                                  "platform": "IOS"}, {"app": ("apps", "app1")}, id="ver2")
    fake.add("appStoreVersionPhasedReleases", {"phasedReleaseState": "INACTIVE"},
             {"appStoreVersion": ("appStoreVersions", "ver2")})
    assert run(fake, "apply", str(kit), "--yes")[0] == 0
    assert ("POST", "/v1/appStoreVersions") not in fake.writes()
    assert ("POST", "/v1/appStoreVersionPhasedReleases") not in fake.writes()


def draft(fake, *targets):
    sub = fake.add("reviewSubmissions", {"platform": "IOS", "state": "READY_FOR_REVIEW"}, {"app": ("apps", "app1")},
                   id="sub1")
    for rel, typ, oid in targets:
        fake.add("reviewSubmissionItems", {"state": "READY_FOR_REVIEW"},
                 {"reviewSubmission": ("reviewSubmissions", sub), rel: (typ, oid)})
    return sub


def test_submit_refuses_a_draft_with_items_nobody_asked_for(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake, iap_state="APPROVED")
    fake.add("appEvents", {"referenceName": "Old event", "eventState": "READY_FOR_REVIEW"}, id="ev9")
    draft(fake, ("appEvent", "appEvents", "ev9"))
    code, _ = run(fake, "submit", str(kit), "--yes")
    out = capsys.readouterr().out
    assert code == 1 and fake.writes() == []
    assert "in-app event ev9" in out and "--include-draft-items" in out
    assert run(fake, "submit", str(kit), "--include-draft-items")[0] == 2 and fake.writes() == []
    code, _ = run(fake, "submit", str(kit), "--include-draft-items", "--yes")
    assert code == 0
    assert fake.writes() == [("POST", "/v1/reviewSubmissionItems"), ("PATCH", "/v1/reviewSubmissions/sub1")]


def test_submit_adds_the_requested_version_even_when_another_version_is_in_the_draft(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake, iap_state="APPROVED")
    fake.add("appStoreVersions", {"versionString": "0.9", "appVersionState": "PREPARE_FOR_SUBMISSION", "platform": "IOS"},
             {"app": ("apps", "app1")}, id="ver0")
    draft(fake, ("appStoreVersion", "appStoreVersions", "ver0"))
    assert run(fake, "submit", str(kit), "--yes")[0] == 1
    assert "app version 0.9 (ver0)" in capsys.readouterr().out
    assert run(fake, "submit", str(kit), "--yes", "--include-draft-items")[0] == 0
    items = {i["relationships"]["appStoreVersion"]["data"]["id"] for i in fake.of_type("reviewSubmissionItems")}
    assert items == {"ver0", "ver1"}


def test_submit_does_not_add_a_version_twice(tmp_path):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake, iap_state="APPROVED")
    draft(fake, ("appStoreVersion", "appStoreVersions", "ver1"))
    assert run(fake, "submit", str(kit), "--yes")[0] == 0
    assert fake.writes() == [("PATCH", "/v1/reviewSubmissions/sub1")]


def test_submit_first_iap_check_needs_that_purchase_in_the_draft(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    fake.add("appEvents", {"referenceName": "Old event", "eventState": "READY_FOR_REVIEW"}, id="ev9")
    draft(fake, ("appEvent", "appEvents", "ev9"))
    code, _ = run(fake, "submit", str(kit), "--yes", "--include-draft-items")
    assert code == 1 and fake.writes() == []
    assert "first in-app purchase" in capsys.readouterr().out


def test_submit_first_iap_by_its_version_in_the_draft(tmp_path):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    draft(fake, ("inAppPurchaseVersion", "inAppPurchaseVersions", "iapv1"))
    assert run(fake, "submit", str(kit), "--yes")[0] == 0
    assert fake.writes() == [("POST", "/v1/reviewSubmissionItems"), ("PATCH", "/v1/reviewSubmissions/sub1")]


def test_submit_refuses_automatic_release_without_the_owners_ok(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake, iap_state="APPROVED")
    fake.store["ver1"]["attributes"]["releaseType"] = "AFTER_APPROVAL"
    code, _ = run(fake, "submit", str(kit), "--yes")
    out = capsys.readouterr().out
    assert code == 1 and fake.writes() == []
    assert "approval will release the app automatically" in out.lower() and "--auto-release-ok" in out
    assert run(fake, "submit", str(kit), "--yes", "--auto-release-ok")[0] == 0


def test_plan_and_apply_say_when_approval_releases_automatically(tmp_path, capsys):
    kit = make_kit(tmp_path)
    c = yaml.safe_load((kit / "connect.yaml").read_text())
    c["version"]["release"] = "after_approval"
    (kit / "connect.yaml").write_text(yaml.safe_dump(c))
    fake = FakeASC()
    seed(fake)
    run(fake, "plan", str(kit), "--only", "release")
    pj = json.loads((kit / "connect-plan.json").read_text())
    assert pj["auto_release"] == "AFTER_APPROVAL"
    assert "approval will release the app automatically" in (kit / "connect-plan.md").read_text()
    capsys.readouterr()
    run(fake, "apply", str(kit), "--yes")
    assert "approval will release the app automatically" in capsys.readouterr().out


def test_release_all_completes_a_running_phased_release(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake, version_state="READY_FOR_DISTRIBUTION")
    ph = fake.add("appStoreVersionPhasedReleases", {"phasedReleaseState": "INACTIVE"},
                  {"appStoreVersion": ("appStoreVersions", "ver1")})
    assert run(fake, "release", str(kit), "--all", "--yes")[0] == 1
    fake.store[ph]["attributes"]["phasedReleaseState"] = "PAUSED"
    assert run(fake, "release", str(kit), "--all")[0] == 2 and fake.writes() == []
    assert run(fake, "release", str(kit), "--all", "--yes")[0] == 0
    assert fake.store[ph]["attributes"]["phasedReleaseState"] == "COMPLETE"
    assert run(fake, "release", str(kit), "--all", "--pause", "--yes")[0] == 2


def test_top_level_phased_release_is_an_alias(tmp_path):
    kit = make_kit(tmp_path, version="1.1.0", first=False)
    c = yaml.safe_load((kit / "connect.yaml").read_text())
    c["version"].pop("phased_release")
    c["phased_release"] = False
    (kit / "connect.yaml").write_text(yaml.safe_dump(c))
    fake = FakeASC()
    seed_update(fake, kit)
    run(fake, "plan", str(kit), "--only", "release")
    assert "phased_release" not in [i["op"] for i in json.loads((kit / "connect-plan.json").read_text())["items"]]


def test_fake_rejects_wrong_api_version_and_body_shape():
    fake = FakeASC()
    seed(fake)
    c = api.Client(lambda: "TOKEN", transport=fake, sleep=lambda s: None)
    with pytest.raises(AssertionError, match="lives under /v2"):
        c.get("/v1/inAppPurchases/iap1/inAppPurchaseVersions")
    with pytest.raises(AssertionError, match="lives under /v1"):
        c.get("/v2/apps/app1")
    with pytest.raises(AssertionError, match="doesn't match the path"):
        c.post("/v1/appStoreVersions", {"data": {"type": "appStoreVersion", "attributes": {}}})
    with pytest.raises(AssertionError, match="relationship"):
        c.post("/v1/appStoreVersions", {"data": {"type": "appStoreVersions",
                                                 "relationships": {"app": {"type": "apps", "id": "app1"}}}})
    with pytest.raises(AssertionError, match="isn't the path's id"):
        c.patch("/v1/apps/app1", {"data": {"type": "apps", "id": "app2", "attributes": {}}})


def test_growth_apply_never_changes_visibility_release_does(tmp_path, capsys):
    from test_growth import GROWTH, growth_kit, live_app, plan   # test_growth imports this module
    data = {"custom_product_pages": [dict(GROWTH["custom_product_pages"][0], visible=False)]}
    kit = growth_kit(tmp_path, data)
    fake = FakeASC()
    live_app(fake)
    pj = plan(fake, kit)
    run(fake, "apply", str(kit), "--yes")
    page = fake.of_type("appCustomProductPages")[0]
    assert page["attributes"]["visible"] is True
    assert not any(m == "PATCH" and p.startswith("/v1/appCustomProductPages/") for m, p in fake.writes())
    pj = plan(fake, kit)
    assert any("--cpp-visibility storage=off" in n for n in pj["notes"])
    n = len(fake.writes())
    assert run(fake, "release", str(kit), "--cpp-visibility", "storage=off")[0] == 2 and len(fake.writes()) == n
    assert run(fake, "release", str(kit), "--cpp-visibility", "storage=off", "--yes")[0] == 0
    assert page["attributes"]["visible"] is False
    assert run(fake, "release", str(kit), "--cpp-visibility", "nope=on", "--yes")[0] == 2


def test_cpp_deep_link_set_empty_clears_it(tmp_path, capsys):
    from test_growth import GROWTH, growth_kit, live_app, plan
    kit = growth_kit(tmp_path, {"custom_product_pages": GROWTH["custom_product_pages"]})
    fake = FakeASC()
    live_app(fake)
    plan(fake, kit)
    assert run(fake, "apply", str(kit), "--yes")[0] == 0
    data = yaml.safe_load((kit / "growth.yaml").read_text())
    data["custom_product_pages"][0]["deep_link"] = ""
    (kit / "growth.yaml").write_text(yaml.safe_dump(data))
    pj = plan(fake, kit)
    assert any(c["field"] == "deep link" for c in pj["items"][0]["changes"])
    assert run(fake, "apply", str(kit), "--yes")[0] == 0, capsys.readouterr().out
    assert fake.of_type("appCustomProductPageVersions")[0]["attributes"]["deepLink"] is None


@pytest.mark.parametrize("change, words", [
    (lambda fake: fake.store["ver1"]["attributes"].update(versionString="9.0"), "is now 9.0"),
    (lambda fake: fake.store["ver1"]["attributes"].update(appVersionState="WAITING_FOR_REVIEW"),
     "is now WAITING_FOR_REVIEW"),
    (lambda fake: fake.store.pop("ver1"), "is gone"),
])
def test_apply_refuses_when_the_planned_version_moved(tmp_path, capsys, change, words):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    run(fake, "plan", str(kit), "--only", "age")
    fp = json.loads((kit / "connect-plan.json").read_text())["fingerprint"]
    assert fp["version_id"] == "ver1" and fp["version_string"] == "1.0.0"
    assert fp["version_state"] == "PREPARE_FOR_SUBMISSION"
    change(fake)
    capsys.readouterr()
    code, _ = run(fake, "apply", str(kit), "--yes")
    out = capsys.readouterr().out
    assert code == 1 and fake.writes() == []
    assert "Refused" in out and words in out


def test_submit_refuses_an_unreadable_draft_item_without_the_automatic_release_ok(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake, iap_state="APPROVED")
    sub = draft(fake)
    fake.add("reviewSubmissionItems", {"state": "READY_FOR_REVIEW"}, {"reviewSubmission": ("reviewSubmissions", sub)})
    code, _ = run(fake, "submit", str(kit), "--yes", "--include-draft-items")
    out = capsys.readouterr().out
    assert code == 1 and fake.writes() == [] and "can't be read" in out
    assert run(fake, "submit", str(kit), "--yes", "--include-draft-items", "--auto-release-ok")[0] == 0


def test_numeric_password_is_not_compared_like_a_phone():
    ch = sync.diff({"demoAccountPassword": "123-456"}, {"demoAccountPassword": {"$private": "demo_password"}},
                   private={"demo_password": "123456"})
    assert [c["field"] for c in ch] == ["demoAccountPassword"]
    assert sync.diff({"contactPhone": "123-456"}, {"contactPhone": {"$private": "phone"}},
                     private={"phone": "123456"}) == []


def test_one_character_private_value_keeps_the_plan_valid_json(tmp_path):
    kit = make_kit(tmp_path)
    c = yaml.safe_load((kit / "connect.yaml").read_text())
    c["sign_in_required"] = True
    (kit / "connect.yaml").write_text(yaml.safe_dump(c))
    (kit / "private.yaml").write_text(yaml.safe_dump({"review_contact": {"phone": PHONE},
                                                      "demo": {"demo_user": "ada", "demo_password": "1"}}))
    fake = FakeASC()
    seed(fake)
    assert run(fake, "plan", str(kit))[0] == 0
    pj = json.loads((kit / "connect-plan.json").read_text())       # valid JSON
    review = next(i for i in pj["items"] if i["op"] == "review_detail")
    assert review["desired"]["demoAccountPassword"] == {"$private": "demo_password"}
    assert "screenshots/en-US/iphone-di-medium/01.jpg" in (kit / "connect-plan.md").read_text()
    assert run(fake, "apply", str(kit), "--yes", "--only", "review")[0] == 0
    detail = fake.of_type("appStoreReviewDetails")[0]["attributes"]
    assert detail["demoAccountPassword"] == "1"
    json.loads((kit / "connect-plan.json").read_text())             # still valid once marked applied


def test_write_progress_masks_a_multiline_secret(tmp_path):
    kit = make_kit(tmp_path)
    (kit / "private.yaml").write_text(yaml.safe_dump({"review_contact": {"phone": PHONE},
                                                      "notes": "alpha-secret-line\nbeta-secret-line"}))
    k = sync.Kit(kit)
    sync.write_progress(k, {"review/x": {"live": {"Notes": "alpha-secret-line\nbeta-secret-line"},
                                         "notes": ["kept alpha-secret-line"]}})
    text = (kit / "connect-progress.yaml").read_text()
    assert "alpha-secret-line" not in text and "beta-secret-line" not in text
    assert yaml.safe_load(text)["steps"]["review/x"]["live"]["Notes"] == "[private]"


# ------------------------------------------------------------------------------------------------ IAP price, type
def price_points(fake, iap, *prices):
    return {p: fake.add("inAppPurchasePricePoints", {"customerPrice": p, "proceeds": p},
                        {"inAppPurchase": ("inAppPurchases", iap)}) for p in prices}


def set_price(fake, iap, point):
    fake.add("inAppPurchasePrices", {"startDate": None}, {"inAppPurchaseV2": ("inAppPurchases", iap),
                                                         "inAppPurchasePricePoint": ("inAppPurchasePricePoints", point)})


def test_iap_price_is_planned_from_apples_price_points_and_applied(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    pts = price_points(fake, "iap1", "1.99", "2.99", "3.99")
    set_price(fake, "iap1", pts["1.99"])
    run(fake, "plan", str(kit), "--only", "iap")
    pj = json.loads((kit / "connect-plan.json").read_text())
    it = next(i for i in pj["items"] if i["op"] == "iap")
    assert it["price"] == {"territory": "USA", "customer_price": "2.99", "point_id": pts["2.99"], "old": "1.99",
                           "old_point": pts["1.99"]}
    assert any(c["field"] == "price (USA)" for c in it["changes"])
    assert any("replaces the purchase's manual prices" in w for w in pj["warnings"])
    assert run(fake, "apply", str(kit), "--yes")[0] == 0, capsys.readouterr().out
    post = next(js for m, p, _, js in fake.calls if m == "POST" and p == "/v1/inAppPurchasePriceSchedules")
    assert post["data"]["relationships"]["baseTerritory"]["data"] == {"type": "territories", "id": "USA"}
    assert post["included"][0]["relationships"]["inAppPurchasePricePoint"]["data"]["id"] == pts["2.99"]
    prices = fake.of_type("inAppPurchasePrices")
    assert len(prices) == 1 and prices[0]["relationships"]["inAppPurchasePricePoint"]["data"]["id"] == pts["2.99"]
    run(fake, "plan", str(kit), "--only", "iap")
    pj = json.loads((kit / "connect-plan.json").read_text())
    assert not any(i.get("price") for i in pj["items"])


def test_iap_price_without_an_exact_point_is_left_alone(tmp_path):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    pts = price_points(fake, "iap1", "1.99", "3.99")
    set_price(fake, "iap1", pts["1.99"])
    run(fake, "plan", str(kit), "--only", "iap")
    pj = json.loads((kit / "connect-plan.json").read_text())
    assert not any(i.get("price") for i in pj["items"])
    assert any("no price point of exactly 2.99 in USA" in w for w in pj["warnings"])


def test_iap_price_moved_after_the_plan_is_refused(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    pts = price_points(fake, "iap1", "1.99", "2.99", "4.99")
    set_price(fake, "iap1", pts["1.99"])
    run(fake, "plan", str(kit), "--only", "iap")
    for p in fake.of_type("inAppPurchasePrices"):
        p["relationships"]["inAppPurchasePricePoint"]["data"]["id"] = pts["4.99"]
    capsys.readouterr()
    assert run(fake, "apply", str(kit), "--yes")[0] == 1
    assert "live price changed" in capsys.readouterr().out and fake.writes() == []


def test_new_iap_is_priced_after_it_is_created(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    del fake.store["iapv1"], fake.store["iap1"]
    made = {}
    fake.on_create["inAppPurchases"] = lambda r: made.update(price_points(fake, r["id"], "0.99", "2.99"))
    run(fake, "plan", str(kit), "--only", "iap")
    it = next(i for i in json.loads((kit / "connect-plan.json").read_text())["items"] if i["op"] == "iap")
    assert it["create_iap"]["inAppPurchaseType"] == "NON_CONSUMABLE" and it["price"]["point_id"] is None
    assert run(fake, "apply", str(kit), "--yes")[0] == 0, capsys.readouterr().out
    post = next(js for m, p, _, js in fake.calls if m == "POST" and p == "/v1/inAppPurchasePriceSchedules")
    assert post["included"][0]["relationships"]["inAppPurchasePricePoint"]["data"]["id"] == made["2.99"]


def test_unsupported_iap_type_is_a_plan_error(tmp_path, capsys):
    kit = make_kit(tmp_path)
    facts = yaml.safe_load((kit / "facts.yaml").read_text())
    facts["monetization"]["iap"][0]["type"] = "Auto-Renewable Subscription"
    (kit / "facts.yaml").write_text(yaml.safe_dump(facts))
    fake = FakeASC()
    seed(fake)
    del fake.store["iapv1"], fake.store["iap1"]
    code, _ = run(fake, "plan", str(kit), "--only", "iap")
    out = capsys.readouterr().out
    pj = json.loads((kit / "connect-plan.json").read_text())
    assert code == 1 and "error:" in out and "Auto-Renewable Subscription" in pj["errors"][0]
    assert not any(i["op"] == "iap" for i in pj["items"])
    assert "## Errors" in (kit / "connect-plan.md").read_text()
    assert run(fake, "apply", str(kit), "--yes")[0] == 1 and fake.writes() == []


def launched_with_purchases(fake):
    seed(fake, version_state="READY_FOR_DISTRIBUTION", iap_state="APPROVED")
    iap2 = fake.add("inAppPurchases", {"productId": "com.example.pebble.tips", "state": "READY_TO_SUBMIT"},
                    {"app": ("apps", "app1")}, id="iap2")
    fake.add("inAppPurchaseVersions", {"state": "PREPARE_FOR_SUBMISSION"},
             {"inAppPurchase": ("inAppPurchases", iap2)}, id="iapv2")


def kit_with_tips(tmp_path, first=False):
    kit = make_kit(tmp_path, first=first)
    facts = yaml.safe_load((kit / "facts.yaml").read_text())
    facts["monetization"]["iap"].append({"product_id": "com.example.pebble.tips", "type": "Consumable",
                                         "reference_name": "Tips", "display_name": "Tip jar",
                                         "description": "Say thanks.", "price": "0.99 USD"})
    (kit / "facts.yaml").write_text(yaml.safe_dump(facts))
    return kit


def test_submit_iap_after_launch_sends_only_that_purchase_version(tmp_path, capsys):
    kit = kit_with_tips(tmp_path)
    fake = FakeASC()
    launched_with_purchases(fake)
    assert run(fake, "submit", str(kit), "--iap", "com.example.pebble.tips")[0] == 2 and fake.writes() == []
    assert run(fake, "submit", str(kit), "--iap", "com.example.pebble.tips", "--yes")[0] == 0
    items = fake.of_type("reviewSubmissionItems")
    assert len(items) == 1 and items[0]["relationships"]["inAppPurchaseVersion"]["data"]["id"] == "iapv2"
    assert fake.of_type("reviewSubmissions")[0]["attributes"]["submitted"] is True
    steps = yaml.safe_load((kit / "connect-progress.yaml").read_text())["steps"]
    assert steps["iap/tip-jar-image-optional-tax-category-review-information"]["status"] == "done-by-claude"


def test_submit_iap_keeps_the_draft_rules_and_refuses_the_first_purchase(tmp_path, capsys):
    kit = kit_with_tips(tmp_path)
    fake = FakeASC()
    launched_with_purchases(fake)
    fake.add("appEvents", {"referenceName": "Old event", "eventState": "READY_FOR_REVIEW"}, id="ev9")
    draft(fake, ("appEvent", "appEvents", "ev9"))
    assert run(fake, "submit", str(kit), "--iap", "com.example.pebble.tips", "--yes")[0] == 1
    assert "in-app event ev9" in capsys.readouterr().out and fake.writes() == []
    assert run(fake, "submit", str(kit), "--iap", "com.example.nope", "--yes")[0] == 1
    # an app with no approved purchase: the first one goes from its own page with a version
    fake2 = FakeASC()
    seed(fake2, version_state="READY_FOR_DISTRIBUTION")
    capsys.readouterr()
    assert run(fake2, "submit", str(kit), "--iap", "com.example.pebble.pro", "--yes")[0] == 1
    out = capsys.readouterr().out
    assert "first purchase" in out and "Add for Review" in out and fake2.writes() == []


def test_empty_keywords_and_review_notes_clear_and_absent_ones_stay(tmp_path, capsys):
    kit = make_kit(tmp_path, version="1.1.0", first=False)
    fake = FakeASC()
    seed_update(fake, kit)
    m = yaml.safe_load((kit / "metadata.en-US.yaml").read_text())
    m["keywords"] = []                              # present and empty: clear the live keywords
    (kit / "metadata.en-US.yaml").write_text(yaml.safe_dump(m, allow_unicode=True))
    (kit / "review-notes.md").write_text("# Notes\n\n---\n\n---\n")   # the notes file is there but empty
    run(fake, "plan", str(kit), "--only", "text,review")
    pj = json.loads((kit / "connect-plan.json").read_text())
    en = next(i for i in pj["items"] if i["op"] == "version_loc" and i["locale"] == "en-US")
    assert en["attributes"]["keywords"] is None
    rd = next(i for i in pj["items"] if i["op"] == "review_detail")
    assert rd["desired"]["notes"] is None
    # absent: no keywords key and no notes file leave both alone
    m.pop("keywords")
    (kit / "metadata.en-US.yaml").write_text(yaml.safe_dump(m, allow_unicode=True))
    (kit / "review-notes.md").unlink()
    run(fake, "plan", str(kit), "--only", "text,review")
    pj = json.loads((kit / "connect-plan.json").read_text())
    for i in pj["items"]:
        if i.get("locale") in ("en-US", None):
            assert "keywords" not in (i.get("desired") or {}) and "notes" not in (i.get("desired") or {}), i


# ------------------------------------------------------------------------------------------------ live run 2026-10-15
def test_age_rating_is_reread_through_the_app_info_not_by_id(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()   # like Apple: GET /v1/ageRatingDeclarations/{id} answers 403
    seed(fake)
    run(fake, "plan", str(kit), "--only", "age")
    code, _ = run(fake, "apply", str(kit), "--yes")
    assert code == 0, capsys.readouterr().out
    gets = [p for m, p, *_ in fake.calls if m == "GET"]
    assert "/v1/ageRatingDeclarations/age1" not in gets and "/v1/appInfos/info1/ageRatingDeclaration" in gets
    assert fake.store["age1"]["attributes"]["violenceRealistic"] == "INFREQUENT"


def test_age_rating_403_is_a_browser_warning_not_a_failed_step(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    run(fake, "plan", str(kit), "--only", "age,review")
    fake.fail[("PATCH", "/v1/ageRatingDeclarations/age1")] = (403, "FORBIDDEN_ERROR")
    capsys.readouterr()
    code, _ = run(fake, "apply", str(kit), "--yes")
    out = capsys.readouterr().out
    assert code == 0, out
    assert "warning: Age rating answers" in out and "App Information › Age Rating" in out and "error:" not in out
    pj = json.loads((kit / "connect-plan.json").read_text())
    res = {r["title"]: r["result"] for r in pj["applied"]["results"]}
    assert res["Age rating answers"] == "browser" and res["App Review information"] == "done"
    steps = yaml.safe_load((kit / "connect-progress.yaml").read_text())["steps"]
    assert "app-information/age-rating-set-up-age-ratings" not in steps
    # a key that can't even read it: plan says so and hands it to the browser
    fake.fail[("GET", "/v1/appInfos/info1/ageRatingDeclaration")] = (403, "FORBIDDEN_ERROR")
    assert run(fake, "plan", str(kit), "--only", "age")[0] == 0
    pj = json.loads((kit / "connect-plan.json").read_text())
    assert not pj["items"] and any("403" in w and "Age Rating" in w for w in pj["warnings"])
    assert any("Age Rating" in s["text"] for s in pj["browser_steps"])


def iap_kit_with_new_locales(tmp_path):
    """The JetSetAlarm case: the purchase's in-flight version has en-US; the kit adds two more languages."""
    kit = make_kit(tmp_path)
    facts = yaml.safe_load((kit / "facts.yaml").read_text())
    facts["locales"] = ["en-US", "ru", "uk"]
    (kit / "facts.yaml").write_text(yaml.safe_dump(facts))
    for loc, name in (("ru", "Pebble Про"), ("uk", "Pebble Про")):
        (kit / f"metadata.{loc}.yaml").write_text(yaml.safe_dump(
            {"iap": [{"product_id": "com.example.pebble.pro", "display_name": name, "description": "Без рекламы."}]},
            allow_unicode=True))
    return kit


def test_iap_localizations_join_the_in_flight_version_instead_of_a_new_one(tmp_path, capsys):
    kit = iap_kit_with_new_locales(tmp_path)
    fake = FakeASC()
    seed(fake)
    fake.add("inAppPurchaseLocalizations", {"locale": "en-US", "name": "Old name", "description": "Removes every ad."},
             {"version": ("inAppPurchaseVersions", "iapv1")}, id="iaploc-en")
    # what the old code did: a second version beside the in-flight one is refused, like Apple did
    c = api.Client(lambda: "TOKEN", transport=fake, sleep=lambda s: None)
    with pytest.raises(api.ASCError) as e:
        c.post("/v1/inAppPurchaseVersions", {"data": {"type": "inAppPurchaseVersions", "relationships": {
            "inAppPurchase": {"data": {"type": "inAppPurchases", "id": "iap1"}}}}})
    assert e.value.status == 409
    with pytest.raises(api.ASCError) as e:   # nor is the relationship the old code read
        c.get("/v2/inAppPurchases/iap1/inAppPurchaseVersions")
    assert e.value.status == 404
    run(fake, "plan", str(kit), "--only", "iap")
    pj = json.loads((kit / "connect-plan.json").read_text())
    it = next(i for i in pj["items"] if i["op"] == "iap")
    assert it["version_id"] == "iapv1" and it["versioned"] is True
    assert {(l["locale"], l["target_id"]) for l in it["locs"]} == {("en-US", "iaploc-en"), ("ru", None), ("uk", None)}
    capsys.readouterr()
    n = len(fake.writes())
    code, _ = run(fake, "apply", str(kit), "--yes")
    assert code == 0, capsys.readouterr().out
    assert ("POST", "/v1/inAppPurchaseVersions") not in fake.writes()[n:]
    assert ("PATCH", "/v2/inAppPurchaseLocalizations/iaploc-en") in fake.writes()[n:]
    locs = {r["attributes"]["locale"]: r for r in fake.of_type("inAppPurchaseLocalizations")}
    assert set(locs) == {"en-US", "ru", "uk"} and locs["en-US"]["attributes"]["name"] == "Pebble Pro"
    assert all(r["relationships"]["version"]["data"]["id"] == "iapv1" for r in locs.values())
    img = fake.of_type("inAppPurchaseImages")[0]
    assert img["relationships"]["version"]["data"]["id"] == "iapv1"


def test_iap_localization_made_meanwhile_is_changed_not_posted_twice(tmp_path, capsys):
    kit = iap_kit_with_new_locales(tmp_path)
    fake = FakeASC()
    seed(fake)
    run(fake, "plan", str(kit), "--only", "iap")
    # the owner added ru in the browser after the plan: the POST would be a 409, so apply changes that one
    fake.add("inAppPurchaseLocalizations", {"locale": "ru", "name": "x", "description": "y"},
             {"version": ("inAppPurchaseVersions", "iapv1")}, id="iaploc-ru")
    assert run(fake, "apply", str(kit), "--yes")[0] == 0, capsys.readouterr().out
    assert len([r for r in fake.of_type("inAppPurchaseLocalizations") if r["attributes"]["locale"] == "ru"]) == 1
    assert fake.store["iaploc-ru"]["attributes"]["name"] == "Pebble Про"


def test_unversioned_iap_gets_localizations_on_the_purchase_and_no_version(tmp_path, capsys):
    kit = iap_kit_with_new_locales(tmp_path)
    fake = FakeASC()
    seed(fake)
    del fake.store["iapv1"]
    fake.fail[("GET", "/v2/inAppPurchases/iap1/versions")] = (404, "NOT_FOUND")
    run(fake, "plan", str(kit), "--only", "iap")
    it = next(i for i in json.loads((kit / "connect-plan.json").read_text())["items"] if i["op"] == "iap")
    assert it["versioned"] is False and it["image_kind"] == "v1"
    assert run(fake, "apply", str(kit), "--yes")[0] == 0, capsys.readouterr().out
    posts = [p for m, p in fake.writes() if m == "POST"]
    assert "/v1/inAppPurchaseVersions" not in posts and posts.count("/v1/inAppPurchaseLocalizations") == 3
    assert all(r["relationships"]["inAppPurchaseV2"]["data"]["id"] == "iap1"
               for r in fake.of_type("inAppPurchaseLocalizations"))


def test_iap_version_in_review_is_left_alone_with_a_warning(tmp_path):
    kit = iap_kit_with_new_locales(tmp_path)
    fake = FakeASC()
    seed(fake)
    fake.store["iapv1"]["attributes"]["state"] = "WAITING_FOR_REVIEW"
    run(fake, "plan", str(kit), "--only", "iap")
    pj = json.loads((kit / "connect-plan.json").read_text())
    it = next((i for i in pj["items"] if i["op"] == "iap"), {"locs": [], "image": None})
    assert not it["locs"] and not it["image"]
    assert any("WAITING_FOR_REVIEW" in w for w in pj["warnings"])


def test_retry_failed_resends_only_what_failed(tmp_path, capsys):
    kit = make_kit(tmp_path)
    fake = FakeASC()
    seed(fake)
    run(fake, "plan", str(kit), "--only", "age,review,accessibility")
    fake.fail[("PATCH", "/v1/ageRatingDeclarations/age1")] = (409, "ENTITY_ERROR.ATTRIBUTE.INVALID")
    assert run(fake, "apply", str(kit), "--yes")[0] == 1
    del fake.fail[("PATCH", "/v1/ageRatingDeclarations/age1")]
    n = len(fake.writes())
    capsys.readouterr()
    assert run(fake, "apply", str(kit), "--yes")[0] == 1 and len(fake.writes()) == n
    assert "--retry-failed" in capsys.readouterr().out
    assert run(fake, "apply", str(kit), "--retry-failed")[0] == 2 and len(fake.writes()) == n, "still needs --yes"
    assert run(fake, "apply", str(kit), "--retry-failed", "--dry-run")[0] == 0 and len(fake.writes()) == n
    assert run(fake, "apply", str(kit), "--retry-failed", "--yes")[0] == 0
    assert fake.writes()[n:] == [("PATCH", "/v1/ageRatingDeclarations/age1")]
    pj = json.loads((kit / "connect-plan.json").read_text())
    assert [r["result"] for r in pj["applied"]["results"] if r["title"] == "Age rating answers"] == ["failed", "done"]
    capsys.readouterr()
    assert run(fake, "apply", str(kit), "--retry-failed", "--yes")[0] == 0
    assert "Nothing to retry" in capsys.readouterr().out and len(fake.writes()) == n + 1


def test_retry_failed_uses_the_version_the_first_run_created(tmp_path, capsys):
    kit = make_kit(tmp_path, version="1.1.0", first=False)
    fake = FakeASC()
    seed_update(fake, kit)
    run(fake, "plan", str(kit), "--only", "text,release")
    fail_on = []

    def fail_de(r):
        loc = next(x for x in fake.of_type("appStoreVersionLocalizations") if x["attributes"]["locale"] == "de-DE"
                   and x["relationships"]["appStoreVersion"]["data"]["id"] != "ver1")
        fail_on.append(("PATCH", f"/v1/appStoreVersionLocalizations/{loc['id']}"))
        fake.fail[fail_on[0]] = (409, "ENTITY_ERROR")
    orig = fake.on_create["appStoreVersions"]
    fake.on_create["appStoreVersions"] = lambda r: (orig(r), fail_de(r))
    assert run(fake, "apply", str(kit), "--yes")[0] == 1
    del fake.fail[fail_on[0]]
    n = len(fake.writes())
    assert run(fake, "apply", str(kit), "--retry-failed", "--yes")[0] == 0, capsys.readouterr().out
    assert fake.writes()[n:] == [fail_on[0]]
    assert len([v for v in fake.of_type("appStoreVersions") if v["attributes"]["versionString"] == "1.1.0"]) == 1


def test_watch_screenshots_map_to_the_watch_display_class_by_pixel_size(tmp_path, capsys):
    kit = make_kit(tmp_path)
    for i in range(5):
        png(kit / f"screenshots/en-US/watch/0{i + 1}.png", "teal", size=(416, 496))
    png(kit / "screenshots/en-US/watch/odd.png", "teal", size=(400, 400))
    fake = FakeASC()
    seed(fake)
    assert run(fake, "plan", str(kit), "--only", "media")[0] == 0
    pj = json.loads((kit / "connect-plan.json").read_text())
    watch = [i for i in pj["items"] if i["op"] == "media_slot" and i["slot"] == "watch"]
    assert len(watch) == 1
    assert watch[0]["display_class"] == "WATCH_SERIES_10" and watch[0]["group"] == "WATCH_SERIES_10_PROFILE"
    assert [r["action"] for r in watch[0]["rows"]] == ["add"] * 5
    assert not any("no Asset Library display class" in w for w in pj["warnings"])
    assert any("watch/odd.png" in w and "400×400" in w for w in pj["warnings"])
    assert sync.watch_class(kit / "screenshots/en-US/watch/01.png") == ("WATCH_SERIES_10", None)
