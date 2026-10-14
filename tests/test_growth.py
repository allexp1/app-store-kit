"""Growth and marketing: growth.yaml, and asc_sync.py's "growth" area against the fake App Store Connect."""
import json

import yaml

import growth as gr
from fake_asc import FakeASC
from test_asc_sync import jpeg, make_kit, png, run, seed

GROWTH = {
    "custom_product_pages": [{
        "id": "storage", "name": "Free up storage", "deep_link": "https://example.com/open/storage",
        "locales": {"en-US": {"promotional_text": "Clear gigabytes in minutes.", "keywords": ["storage", "declutter"]},
                    "de-DE": {"promotional_text": "Gigabytes in Minuten frei."}}}],
    "experiments": [{
        "id": "first-shot", "name": "First screenshot in motion", "traffic_proportion": 30,
        "treatments": [{"id": "motion", "name": "Mid-swipe first"}]}],
    "in_app_events": [{
        "id": "spring-clean", "reference_name": "Spring clean week", "badge": "challenge",
        "purpose": "attract new users", "schedule": [{"territories": ["USA"], "publish_start": "2027-03-01",
                                                      "event_start": "2027-03-08", "event_end": "2027-03-15"}],
        "locales": {"en-US": {"name": "Spring Clean Week", "short_description": "Clear 1,000 photos in a week.",
                              "long_description": "Swipe through your library and free space before spring."}}}],
}


def growth_kit(tmp_path, data=GROWTH):
    kit = make_kit(tmp_path)
    (kit / "growth.yaml").write_text(yaml.safe_dump(data, allow_unicode=True))
    jpeg(kit / "growth/storage/screenshots/en-US/iphone-di-medium/01.jpg", "orange")
    jpeg(kit / "growth/storage/screenshots/en-US/iphone-di-medium/02.jpg", "purple")
    jpeg(kit / "growth/first-shot/motion/screenshots/en-US/iphone-di-medium/01.jpg", "teal")
    png(kit / "growth/spring-clean/media/en-US/card.png", "pink")
    return kit


def live_app(fake):
    """An app whose 1.0.0 is on the App Store."""
    seed(fake, version_state="READY_FOR_DISTRIBUTION", iap_state="APPROVED")
    fake.app_keywords["en-US"] = ["storage", "declutter"]


def plan(fake, kit):
    run(fake, "plan", str(kit), "--only", "growth")
    return json.loads((kit / "connect-plan.json").read_text())


# ------------------------------------------------------------------------------------------------ growth.yaml
def test_growth_yaml_is_normalised_and_checked(tmp_path):
    (tmp_path / "growth.yaml").write_text(yaml.safe_dump({
        "custom_product_pages": [{"id": "Bad Id", "name": "X", "locales": {"en-US": {"promotional_text": "x" * 171}}}],
        "experiments": [{"id": "t", "name": "T", "traffic_proportion": 0,
                         "treatments": [{"id": f"a{i}", "name": f"A{i}"} for i in range(4)]}],
        "in_app_events": [{"id": "e", "reference_name": "E", "badge": "live event",
                           "schedule": [{"territories": ["USA"], "event_start": "2027-01-01", "event_end": "2027-03-01",
                                         "publish_start": "2026-12-01"}],
                           "locales": {"en-US": {"name": "N" * 31, "short_description": "s",
                                                 "long_description": "l"}}}]}))
    g = gr.load(tmp_path)
    text = "\n".join(g["problems"])
    for bit in ("lower-case letters", "171 characters (limit 170)", "traffic_proportion", "4 treatment(s)",
                "Apple allows 31", "Apple allows 14", "name is 31 characters (limit 30)"):
        assert bit in text, bit
    ev = g["events"][0]
    assert ev["badge"] == "LIVE_EVENT" and ev["priority"] == "NORMAL" and ev["primary_locale"] == "en-US"
    assert ev["schedules"][0]["eventStart"] == "2027-01-01T00:00:00Z"
    assert gr.load(tmp_path / "nothing")["present"] is False
    assert gr.main([str(tmp_path)]) == 1


def test_example_template_is_clean():
    import pathlib
    tpl = pathlib.Path(__file__).resolve().parent.parent / "templates" / "growth.example.yaml"
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        shutil.copy(tpl, pathlib.Path(d) / "growth.yaml")
        g = gr.load(d)
    assert g["problems"] == [] and g["pages"] and g["tests"] and g["events"]


# ------------------------------------------------------------------------------------------------ before launch
def test_first_version_refuses_pages_and_tests_but_plans_events(tmp_path):
    kit = growth_kit(tmp_path)
    fake = FakeASC()
    seed(fake)                                   # 1.0.0 in PREPARE_FOR_SUBMISSION: never approved
    pj = plan(fake, kit)
    ops = {i["op"] for i in pj["items"]}
    assert "cpp" not in ops and "test" not in ops
    assert "event" in ops and "growth_slot" in ops
    notes = " ".join(pj["notes"])
    assert "Ready for Distribution" in notes and "live on the App Store" in notes
    assert "same submission as the first version" in notes
    assert any(s["progress_key"] == "growth/storage" for s in pj["browser_steps"])
    assert all(m == "GET" for m, *_ in fake.calls)
    code, _ = run(fake, "submit", str(kit), "--growth", "first-shot", "--yes")
    assert code == 1 and fake.writes() == []


def test_event_goes_with_the_first_version(tmp_path):
    kit = growth_kit(tmp_path)
    fake = FakeASC()
    seed(fake, iap_state="APPROVED")
    plan(fake, kit)
    assert run(fake, "apply", str(kit), "--yes")[0] == 0
    ev = fake.of_type("appEvents")[0]["attributes"]
    assert ev["badge"] == "CHALLENGE" and ev["purpose"] == "ATTRACT_NEW_USERS"
    assert ev["territorySchedules"][0]["eventEnd"] == "2027-03-15T00:00:00Z"
    card = [p for p in fake.of_type("appAssetLibraryPlacements") if p["attributes"]["placementType"] == "EVENT_CARD_ASSET"]
    assert len(card) == 1 and "appEventLocalization" in card[0]["relationships"]
    assert not fake.of_type("appAssetLibraryPlacementOrderingRequests"), "event placements aren't ordered"
    n = len(fake.writes())
    code, _ = run(fake, "submit", str(kit), "--growth", "spring-clean", "--yes")
    assert code == 0
    items = fake.of_type("reviewSubmissionItems")
    assert {next(iter(k for k in i["relationships"] if k != "reviewSubmission")) for i in items} == \
        {"appStoreVersion", "appEvent"}
    assert len(fake.writes()) == n + 4


# ------------------------------------------------------------------------------------------------ after launch
def test_custom_product_page_plan_and_apply(tmp_path, capsys):
    kit = growth_kit(tmp_path, {"custom_product_pages": GROWTH["custom_product_pages"]})
    fake = FakeASC()
    live_app(fake)
    pj = plan(fake, kit)
    cpp = next(i for i in pj["items"] if i["op"] == "cpp")
    assert cpp["page_id"] is None and cpp["template_version_id"] == "ver1"
    assert [l["locale"] for l in cpp["locs"]] == ["en-US", "de-DE"]
    assert cpp["locs"][0]["keywords_add"] == ["storage", "declutter"]
    slots = [i for i in pj["items"] if i["op"] == "growth_slot"]
    assert len(slots) == 1 and [r["action"] for r in slots[0]["rows"]] == ["add", "add"]
    assert "Custom product page Free up storage" in (kit / "connect-plan.md").read_text()

    code, _ = run(fake, "apply", str(kit), "--yes")
    assert code == 0, capsys.readouterr().out
    create = next(js for m, p, _, js in fake.calls if m == "POST" and p == "/v1/appCustomProductPages")
    assert create["data"]["relationships"]["appStoreVersionTemplate"]["data"]["id"] == "ver1"
    assert {i["type"] for i in create["included"]} == {"appCustomProductPageVersions",
                                                       "appCustomProductPageLocalizations"}
    assert create["included"][0]["attributes"]["deepLink"] == "https://example.com/open/storage"
    locs = {r["attributes"]["locale"]: r for r in fake.of_type("appCustomProductPageLocalizations")}
    assert locs["de-DE"]["attributes"]["promotionalText"] == "Gigabytes in Minuten frei."
    assert locs["en-US"]["keywords"] == ["storage", "declutter"]
    placed = [p for p in fake.of_type("appAssetLibraryPlacements")
              if "appCustomProductPageLocalization" in p["relationships"]]
    assert len(placed) == 2
    assert {p["relationships"]["appCustomProductPageLocalization"]["data"]["id"] for p in placed} == \
        {locs["en-US"]["id"]}
    order = fake.of_type("appAssetLibraryPlacementOrderingRequests")[0]
    assert "appCustomProductPageLocalization" in order["relationships"]
    steps = yaml.safe_load((kit / "connect-progress.yaml").read_text())["steps"]
    assert steps["growth/storage"]["status"] == "done-by-claude"
    assert plan(fake, kit)["items"] == [], "a second plan finds nothing left to do"

    # an approved page changes through a new version
    for v in fake.of_type("appCustomProductPageVersions"):
        v["attributes"]["state"] = "APPROVED"
    data = yaml.safe_load((kit / "growth.yaml").read_text())
    data["custom_product_pages"][0]["locales"]["en-US"]["promotional_text"] = "Clear gigabytes today."
    (kit / "growth.yaml").write_text(yaml.safe_dump(data))
    pj = plan(fake, kit)
    assert pj["items"][0]["version_id"] is None and pj["items"][0]["page_id"]
    assert run(fake, "apply", str(kit), "--yes")[0] == 0
    assert ("POST", "/v1/appCustomProductPageVersions") in fake.writes()


def test_submit_growth_after_launch_needs_yes_and_skips_the_version(tmp_path):
    kit = growth_kit(tmp_path, {"custom_product_pages": GROWTH["custom_product_pages"]})
    fake = FakeASC()
    live_app(fake)
    plan(fake, kit)
    run(fake, "apply", str(kit), "--yes")
    n = len(fake.writes())
    assert run(fake, "submit", str(kit), "--growth", "storage")[0] == 2 and len(fake.writes()) == n
    assert run(fake, "submit", str(kit), "--growth", "storage", "--yes")[0] == 0
    item = fake.of_type("reviewSubmissionItems")[0]["relationships"]
    assert "appCustomProductPageVersion" in item and "appStoreVersion" not in item
    assert fake.of_type("reviewSubmissions")[0]["attributes"]["submitted"] is True


def test_experiment_with_a_treatment(tmp_path, capsys):
    kit = growth_kit(tmp_path, {"experiments": GROWTH["experiments"]})
    fake = FakeASC()
    live_app(fake)
    pj = plan(fake, kit)
    test = next(i for i in pj["items"] if i["op"] == "test")
    assert test["treatments"][0]["locales"] == ["en-US", "de-DE"]
    code, _ = run(fake, "apply", str(kit), "--yes")
    assert code == 0, capsys.readouterr().out
    exp = fake.of_type("appStoreVersionExperiments")[0]
    assert exp["attributes"] == {"name": "First screenshot in motion", "trafficProportion": 30, "platform": "IOS",
                                 "state": "PREPARE_FOR_SUBMISSION"}
    tr = fake.of_type("appStoreVersionExperimentTreatments")[0]
    assert tr["relationships"]["appStoreVersionExperimentV2"]["data"]["id"] == exp["id"]
    tlocs = fake.of_type("appStoreVersionExperimentTreatmentLocalizations")
    assert sorted(t["attributes"]["locale"] for t in tlocs) == ["de-DE", "en-US"]
    placed = [p for p in fake.of_type("appAssetLibraryPlacements")
              if "appStoreVersionExperimentTreatmentLocalization" in p["relationships"]]
    assert len(placed) == 1
    assert plan(fake, kit)["items"] == []
    # starting waits for approval, then for its own yes
    assert run(fake, "release", str(kit), "--start-test", "first-shot", "--yes")[0] == 1
    exp["attributes"]["state"] = "APPROVED"
    assert run(fake, "release", str(kit), "--start-test", "first-shot")[0] == 2
    assert run(fake, "release", str(kit), "--start-test", "first-shot", "--yes")[0] == 0
    assert exp["attributes"]["started"] is True
    # a started test is never changed
    exp["attributes"]["state"] = "IN_REVIEW"
    assert not plan(fake, kit)["items"]


def test_dry_run_sends_nothing(tmp_path, capsys):
    kit = growth_kit(tmp_path)
    fake = FakeASC()
    live_app(fake)
    plan(fake, kit)
    capsys.readouterr()
    code, client = run(fake, "apply", str(kit), "--dry-run")
    out = capsys.readouterr().out
    assert code == 0 and fake.writes() == []
    for call in ("POST /v1/appCustomProductPages", "POST /v2/appStoreVersionExperiments", "POST /v1/appEvents",
                 "POST /v1/appAssetLibraryPlacements"):
        assert f"would send: {call}" in out, call


# ------------------------------------------------------------------------------------------------ guide, board, validation
def test_guide_and_board_show_growth_steps(tmp_path):
    import connect_guide as cg
    import status_board as sb
    from test_connect_guide import make_kit as guide_kit
    kit = guide_kit(tmp_path)
    (kit / "growth.yaml").write_text(yaml.safe_dump(GROWTH, allow_unicode=True))
    rules = json.loads((cg.HERE / "rules.json").read_text())
    g = cg.build(kit, None, rules, {})
    sec = g["sections"][-1]
    assert sec.key == "growth"
    assert [st.key for st in sec.steps] == ["growth/storage", "growth/first-shot", "growth/spring-clean"]
    labels = {f.label: f for st in sec.steps for f in st.fields}
    assert labels["Promotional Text (en-US)"].limit == {"max": 170, "unit": "chars"}
    assert labels["Event Name (en-US)"].text() == "Spring Clean Week"
    md = sb.render(kit)
    assert "⏸ Custom product page: Free up storage" in md and "⏸ Product page optimization" in md
    assert "⬜ In-app event: Spring clean week" in md
    assert "2 growth step(s) wait for launch" in md
    assert "Free up storage" not in next(l for l in md.splitlines() if l.startswith("**Next:**"))


def test_validate_kit_checks_growth_images(tmp_path, capsys):
    import validate_kit as vk
    from PIL import Image
    kit = tmp_path

    def img(rel, size):
        p = kit / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size, (200, 180, 160)).save(p)
    img("screenshots/en-US/iphone-di-medium/01.png", (1206, 2622))
    img("growth/storage/screenshots/en-US/iphone-di-medium/01.png", (1206, 2622))
    img("growth/storage/creative/en-US/universal.png", (5244, 2950))
    img("growth/spring/media/en-US/card.png", (3840, 2160))
    img("growth/spring/media/en-US/details.png", (1080, 1920))
    assert vk.main([str(kit), "--platforms", "iphone"]) == 0, capsys.readouterr().out
    img("growth/first-shot/motion/screenshots/en-US/iphone-di-medium/01.png", (1000, 2000))
    img("growth/spring/media/en-US/card.png", (1080, 1920))
    capsys.readouterr()
    assert vk.main([str(kit), "--platforms", "iphone"]) == 1
    out = capsys.readouterr().out
    assert "growth/first-shot/motion/screenshots/en-US/iphone-di-medium" in out and "not an accepted size" in out
    assert "in-app event card (16:9" in out


def test_cpp_null_clears_and_absent_leaves_alone(tmp_path):
    (tmp_path / "growth.yaml").write_text(
        "custom_product_pages:\n"
        "  - id: a\n    name: A\n    deep_link:\n    locales:\n      en-US:\n        promotional_text:\n"
        "  - id: b\n    name: B\n    locales:\n      en-US:\n        keywords: [storage]\n")
    pages = {p["id"]: p for p in gr.load(tmp_path)["pages"]}
    assert pages["a"]["deep_link"] == "" and pages["a"]["locales"]["en-US"]["promotional_text"] == ""
    assert pages["b"]["deep_link"] is None and "promotional_text" not in pages["b"]["locales"]["en-US"]


def test_keywords_only_locale_plans_and_leaves_promotional_text_alone(tmp_path, capsys):
    page = {"id": "storage", "name": "Free up storage",
            "locales": {"en-US": {"keywords": ["storage"]}}}
    kit = growth_kit(tmp_path, {"custom_product_pages": [page]})
    fake = FakeASC()
    live_app(fake)
    pj = plan(fake, kit)
    cpp = next(i for i in pj["items"] if i["op"] == "cpp")
    assert cpp["locs"][0]["desired"] == {} and cpp["locs"][0]["keywords_add"] == ["storage"]
    assert cpp["deep_link"] is None
    assert run(fake, "apply", str(kit), "--yes")[0] == 0, capsys.readouterr().out
    loc = fake.of_type("appCustomProductPageLocalizations")[0]
    assert "promotionalText" not in loc["attributes"]
    # A live promotional text stays when the kit doesn't mention it.
    loc["attributes"]["promotionalText"] = "Set in App Store Connect."
    pj = plan(fake, kit)
    assert not any(c["field"] == "promotionalText" for i in pj["items"] for c in i.get("changes") or [])


def test_growth_submit_after_launch_keeps_the_automatic_release_gate(tmp_path, capsys):
    """A draft holding an app version that releases itself on approval can't ride along with a growth submission
    (submit --growth ... --include-draft-items) without the owner's --auto-release-ok."""
    kit = growth_kit(tmp_path, {"custom_product_pages": GROWTH["custom_product_pages"]})
    fake = FakeASC()
    live_app(fake)
    plan(fake, kit)
    run(fake, "apply", str(kit), "--yes")
    fake.add("appStoreVersions", {"versionString": "1.1.0", "appVersionState": "PREPARE_FOR_SUBMISSION",
                                  "platform": "IOS", "releaseType": "AFTER_APPROVAL"}, {"app": ("apps", "app1")},
             id="ver2")
    sub = fake.add("reviewSubmissions", {"platform": "IOS", "state": "READY_FOR_REVIEW"}, {"app": ("apps", "app1")},
                   id="sub1")
    fake.add("reviewSubmissionItems", {"state": "READY_FOR_REVIEW"},
             {"reviewSubmission": ("reviewSubmissions", sub), "appStoreVersion": ("appStoreVersions", "ver2")})
    n = len(fake.writes())
    capsys.readouterr()
    code, _ = run(fake, "submit", str(kit), "--growth", "storage", "--include-draft-items", "--yes")
    out = capsys.readouterr().out
    assert code == 1 and len(fake.writes()) == n
    assert "app version 1.1.0 (ver2)" in out and "AFTER_APPROVAL" in out and "--auto-release-ok" in out
    assert fake.store["sub1"]["attributes"].get("submitted") is not True
    code, _ = run(fake, "submit", str(kit), "--growth", "storage", "--include-draft-items", "--yes",
                  "--auto-release-ok")
    assert code == 0 and fake.store["sub1"]["attributes"]["submitted"] is True
