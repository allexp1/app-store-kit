import json
import pathlib
import plistlib

import yaml

import precheck as pc

MANIFEST_UD = {"NSPrivacyTracking": False, "NSPrivacyTrackingDomains": [], "NSPrivacyCollectedDataTypes": [],
               "NSPrivacyAccessedAPITypes": [{"NSPrivacyAccessedAPIType": "NSPrivacyAccessedAPICategoryUserDefaults",
                                              "NSPrivacyAccessedAPITypeReasons": ["CA92.1"]}]}
BASE_INFO = {"CFBundleDisplayName": "Demo", "CFBundleShortVersionString": "1.0", "UILaunchScreen": {},
             "ITSAppUsesNonExemptEncryption": False, "UIRequiredDeviceCapabilities": ["arm64"]}


def make_project(tmp, info=None, swift="", manifest=MANIFEST_UD, resolved=None, storekit=None,
                 xcstrings_langs=("en",), icon=True):
    """A minimal XcodeGen project: project.yml with info properties, one Swift file, optional extras."""
    root = tmp / "proj"
    app = root / "App"
    app.mkdir(parents=True)
    props = dict(BASE_INFO, **(info or {}))
    yml = {"name": "Demo", "options": {"deploymentTarget": {"iOS": "26.0"}},
           "targets": {"Demo": {"type": "application", "platform": "iOS", "sources": [{"path": "App"}],
                                "settings": {"base": {"PRODUCT_BUNDLE_IDENTIFIER": "com.acme.demo"}},
                                "info": {"path": "App/Info.plist", "properties": props}}}}
    (root / "project.yml").write_text(yaml.safe_dump(yml, sort_keys=False))
    (app / "Main.swift").write_text(swift or "import SwiftUI\nstruct V: View { var body: some View { Text(\"Hi\") } }\n")
    (app / "About.swift").write_text(
        'import SwiftUI\nstruct About: View { var body: some View { VStack {\n'
        '  Link("Privacy Policy", destination: URL(string: "https://acme.test/privacy")!)\n'
        '  Link("Contact", destination: URL(string: "mailto:help@acme.test")!)\n} } }\n')
    if manifest is not None:
        (app / "PrivacyInfo.xcprivacy").write_bytes(plistlib.dumps(manifest))
    if resolved:
        (root / "Package.resolved").write_text(json.dumps({"pins": resolved, "version": 3}))
    if storekit is not None:
        (root / "Demo.storekit").write_text(json.dumps({"products": storekit}))
    strings = {"sourceLanguage": xcstrings_langs[0], "strings": {"Hi": {"localizations": {
        lang: {"stringUnit": {"state": "translated", "value": "Hi"}} for lang in xcstrings_langs}}}}
    (app / "Localizable.xcstrings").write_text(json.dumps(strings))
    if icon:
        (app / "AppIcon.icon").mkdir()
    return root


def make_kit(tmp, facts):
    kit = tmp / "kit"
    kit.mkdir()
    (kit / "facts.yaml").write_text(yaml.safe_dump(facts))
    return kit


def run_json(root, capsys, *extra):
    code = pc.main([str(root), "--json", "--xcode", "27.0", "--today", "2026-10-14", *map(str, extra)])
    data = json.loads(capsys.readouterr().out)
    return code, data


def ids(data, sev=None):
    return [f["id"] for f in data["findings"] if sev is None or f["severity"] == sev]


def test_catalogue_parses_all_rules():
    cat = pc.load_catalogue()
    assert len([k for k in cat if k not in pc.EXTRA_CHECKS]) == 101
    assert cat["UP-05"]["severity"] == "BLOCKER"
    assert cat["DF-13"]["severity"] == "WARNING"
    assert cat["PAY-02"]["sources"][0].startswith("https://developer.apple.com")


def test_photos_without_purpose_string_is_blocker(tmp_path, capsys):
    root = make_project(tmp_path, swift="import Photos\nlet s = PHPhotoLibrary.authorizationStatus(for: .readWrite)\n")
    code, data = run_json(root, capsys)
    f = [f for f in data["findings"] if f["id"] == "UP-08"]
    assert f and f[0]["severity"] == "BLOCKER" and "NSPhotoLibraryUsageDescription" in f[0]["message"]
    assert f[0]["evidence"][0].endswith("App/Main.swift:2")
    assert code == 2


def test_photos_with_purpose_string_passes(tmp_path, capsys):
    root = make_project(tmp_path, info={"NSPhotoLibraryUsageDescription":
                                        "Demo shows your photos so you can sort them into albums on this phone."},
                        swift="import Photos\nlet s = PHPhotoLibrary.authorizationStatus(for: .readWrite)\n")
    code, data = run_json(root, capsys)
    assert "UP-08" not in ids(data)
    assert any(p["id"] == "UP-08" and "Photos" in p["message"] for p in data["passes"])
    assert code == 1


def test_placeholder_purpose_string_is_flagged(tmp_path, capsys):
    root = make_project(tmp_path, info={"NSPhotoLibraryUsageDescription": "TODO"},
                        swift="let s = PHPhotoLibrary.shared()\n")
    _, data = run_json(root, capsys)
    assert "UP-09" in ids(data, "LIKELY REJECTION")


def test_userdefaults_without_manifest_reason(tmp_path, capsys):
    root = make_project(tmp_path, swift='let d = UserDefaults.standard.bool(forKey: "x")\n',
                        manifest={"NSPrivacyTracking": False, "NSPrivacyAccessedAPITypes": []})
    code, data = run_json(root, capsys)
    f = [f for f in data["findings"] if f["id"] == "UP-05"]
    assert f and f[0]["severity"] == "BLOCKER" and "UserDefaults" in f[0]["message"]
    assert code == 2


def test_userdefaults_without_any_manifest(tmp_path, capsys):
    root = make_project(tmp_path, swift="@AppStorage(\"x\") var x = false\n", manifest=None)
    _, data = run_json(root, capsys)
    assert "UP-04" in ids(data, "BLOCKER")


def test_userdefaults_declared_passes_and_debug_code_is_ignored(tmp_path, capsys):
    swift = 'let d = UserDefaults.standard\n#if DEBUG\nlet u = UIScreen.main.bounds\n#endif\n'
    root = make_project(tmp_path, swift=swift)
    _, data = run_json(root, capsys)
    assert "UP-05" not in ids(data)
    assert "DF-13" not in ids(data)


def test_screen_assumptions_warn(tmp_path, capsys):
    root = make_project(tmp_path, swift="let w = UIScreen.main.bounds.width\n")
    code, data = run_json(root, capsys)
    assert "DF-13" in ids(data, "WARNING")
    assert code == 1
    assert pc.main([str(root), "--xcode", "27.0", "--today", "2026-10-14", "--strict", "--json"]) == 1


def test_google_mobile_ads_without_att_key(tmp_path, capsys):
    pins = [{"identity": "swift-package-manager-google-mobile-ads", "kind": "remoteSourceControl",
             "location": "https://github.com/googleads/swift-package-manager-google-mobile-ads.git",
             "state": {"version": "13.10.0"}}]
    root = make_project(tmp_path, resolved=pins, swift="import GoogleMobileAds\n")
    code, data = run_json(root, capsys)
    f = [f for f in data["findings"] if f["id"] == "PR-04"]
    assert f and "NSUserTrackingUsageDescription" in f[0]["message"]
    assert f[0]["severity"] == "LIKELY REJECTION"
    assert code == 1


def test_storekit_purchase_without_restore(tmp_path, capsys):
    swift = ('import StoreKit\nfunc buy() async throws {\n'
             '  let p = try await Product.products(for: ["com.acme.demo.pro"])\n'
             '  _ = try await p.first?.purchase()\n}\n')
    sk = [{"productID": "com.acme.demo.pro", "type": "NonConsumable"}]
    root = make_project(tmp_path, swift=swift, storekit=sk)
    _, data = run_json(root, capsys)
    assert "PAY-02" in ids(data, "LIKELY REJECTION")
    root2 = make_project(tmp_path / "b", swift=swift + "func restore() async throws { try await AppStore.sync() }\n",
                         storekit=sk)
    _, data2 = run_json(root2, capsys)
    assert "PAY-02" not in ids(data2)
    assert any(p["id"] == "PAY-03" for p in data2["passes"])


def test_product_id_mismatch_between_kit_and_storekit(tmp_path, capsys):
    swift = 'let p = try await Product.products(for: ["com.acme.demo.pro"])\nAppStore.sync()\n'
    root = make_project(tmp_path, swift=swift, storekit=[{"productID": "com.acme.demo.pro", "type": "NonConsumable"}])
    kit = make_kit(tmp_path, {"monetization": {"iap": [{"product_id": "com.acme.demo.premium"}]}})
    _, data = run_json(root, capsys, "--kit", kit, "--out", tmp_path / "out.md")
    msgs = [f["message"] for f in data["findings"] if f["id"] == "PAY-03"]
    assert any("com.acme.demo.premium" in m for m in msgs)


def test_store_locale_missing_from_app(tmp_path, capsys):
    root = make_project(tmp_path, xcstrings_langs=("en",))
    kit = make_kit(tmp_path, {"locales": ["en-US", "de-DE"], "urls": {"privacy_policy": "https://acme.test/p",
                                                                    "support": "https://acme.test/s"},
                              "copyright": "2026 Acme"})
    code, data = run_json(root, capsys, "--kit", kit, "--out", tmp_path / "out.md")
    f = [f for f in data["findings"] if f["id"] == "LOC-01"]
    assert len(f) == 1 and "de-DE" in f[0]["message"] and f[0]["severity"] == "WARNING"
    root2 = make_project(tmp_path / "b", xcstrings_langs=("en", "de"))
    _, data2 = run_json(root2, capsys, "--kit", kit, "--out", tmp_path / "out2.md")
    assert "LOC-01" not in ids(data2)


def test_markdown_report_sections_and_exit_codes(tmp_path, capsys):
    root = make_project(tmp_path, swift="import Photos\nlet s = PHPhotoLibrary.shared()\n")
    kit = make_kit(tmp_path, {"urls": {"privacy_policy": "https://acme.test/p", "support": "https://acme.test/s"},
                              "copyright": "2026 Acme"})
    out = tmp_path / "PRECHECK.md"
    code = pc.main([str(root), "--kit", str(kit), "--out", str(out), "--xcode", "27.0", "--today", "2026-10-14"])
    assert code == 2
    md = out.read_text()
    for head in ("## BLOCKER", "## LIKELY REJECTION", "## WARNING", "## PASS", "## For Claude to judge"):
        assert head in md
    assert "App/Main.swift:2" in md and "https://developer.apple.com" in md


def test_unscanned_project_is_incomplete_and_old_xcode_blocks(tmp_path, capsys):
    root = make_project(tmp_path)
    code, data = run_json(root, capsys)
    assert code == 1, data["findings"]
    code2, data2 = run_json(root, capsys, "--xcode", "16.4")
    assert code2 == 2 and "UP-01" in ids(data2, "BLOCKER")


def test_missing_launch_screen_icon_and_encryption_key(tmp_path, capsys):
    root = make_project(tmp_path, icon=False)
    yml = yaml.safe_load((root / "project.yml").read_text())
    props = yml["targets"]["Demo"]["info"]["properties"]
    del props["UILaunchScreen"], props["ITSAppUsesNonExemptEncryption"]
    (root / "project.yml").write_text(yaml.safe_dump(yml))
    _, data = run_json(root, capsys)
    assert {"UP-10", "UP-11"} <= set(ids(data, "BLOCKER"))
    assert "UP-12" in ids(data, "WARNING")


def test_third_party_ai_and_login_without_siwa(tmp_path, capsys):
    swift = ('let u = URL(string: "https://api.openai.com/v1/chat/completions")!\n'
             'GIDSignIn.sharedInstance.signIn(withPresenting: vc)\n')
    root = make_project(tmp_path, swift=swift)
    _, data = run_json(root, capsys)
    assert "PR-08" in ids(data, "WARNING")
    assert "AC-03" in ids(data, "LIKELY REJECTION")
    assert "AC-01" in ids(data, "LIKELY REJECTION")


def test_background_processing_needs_identifiers(tmp_path, capsys):
    root = make_project(tmp_path, info={"UIBackgroundModes": ["processing", "audio"]},
                        swift='let r = BGProcessingTaskRequest(identifier: "com.acme.demo.index")\n')
    _, data = run_json(root, capsys)
    msgs = " ".join(f["message"] for f in data["findings"] if f["id"] == "DF-09")
    assert "BGTaskSchedulerPermittedIdentifiers" in msgs and "'audio'" in msgs


def test_kids_category_with_ads(tmp_path, capsys):
    root = make_project(tmp_path, swift="import GoogleMobileAds\n",
                        info={"NSUserTrackingUsageDescription": "Ads may use your activity in other apps to be relevant."})
    kit = make_kit(tmp_path, {"kids_category": True})
    _, data = run_json(root, capsys, "--kit", kit, "--out", tmp_path / "o.md")
    assert "CS-04" in ids(data, "LIKELY REJECTION")


def test_comments_and_previews_are_not_code(tmp_path, capsys):
    swift = ('// let s = PHPhotoLibrary.shared()\n/* CLLocationManager() */\n'
             '#Preview {\n  let d = UserDefaults(suiteName: "p")!\n  return Text("$4.99")\n}\n')
    root = make_project(tmp_path, swift=swift, manifest=MANIFEST_UD)
    _, data = run_json(root, capsys)
    assert not {"UP-08", "UP-05", "PAY-04"} & set(ids(data))


def test_unscanned_checks_have_actionable_report_and_decisions(tmp_path, capsys):
    root = make_project(tmp_path)
    kit = make_kit(tmp_path, {})
    code, data = run_json(root, capsys, '--kit', kit)
    assert code != 0 and data['summary']['NOT SCANNED'] == len(data['not_scanned']) > 0
    md = (kit / 'PRECHECK.md').read_text()
    assert 'Not scanned — Claude must decide' in md
    cat = pc.load_catalogue()
    for cid in data['not_scanned']:
        assert f"**{cid}** ({cat[cid]['guideline']}): {cat[cid]['what']}" in md
    decisions = {cid: {'decision': ['ok', 'fixed', 'n/a'][i % 3], 'why': 'Reviewed with evidence.'}
                 for i, cid in enumerate(data['not_scanned'])}
    (kit / 'precheck-decisions.yaml').write_text(yaml.safe_dump(decisions))
    _, data = run_json(root, capsys, '--kit', kit)
    assert data['summary']['NOT SCANNED'] == 0 and not data['undecided']
    assert data['decisions'] == decisions
    assert 'Readiness: incomplete' not in (kit / 'PRECHECK.md').read_text()
    # An unsupported decision or missing evidence cannot close a check.
    for value in ({'decision': 'skip', 'why': 'looked'}, {'decision': 'ok', 'why': ''}, 'ok'):
        decisions[next(iter(decisions))] = value
        (kit / 'precheck-decisions.yaml').write_text(yaml.safe_dump(decisions))
        _, data = run_json(root, capsys, '--kit', kit)
        assert data['summary']['NOT SCANNED'] == 1


def test_unscanned_decisions_control_exit_code():
    cat = {'MANUAL-01': {'guideline': '2.1', 'what': 'Install the release build.'}}
    result = pc.Result(cat)
    assert pc.exit_code(result) == 1
    result.decisions = {'MANUAL-01': {'decision': 'ok', 'why': 'Installed and checked.'}}
    assert pc.exit_code(result) == 0
    result.fail('MANUAL-01', 'Known blocker', severity='BLOCKER')
    assert pc.exit_code(result) == 2


def test_precheck_duo_matches_frozen_rules_and_sdk(tmp_path):
    import datetime as dt
    from types import SimpleNamespace
    root = make_project(tmp_path)
    kit = make_kit(tmp_path, {})
    folder = kit / 'screenshots/en-US/iphone-di-medium'
    folder.mkdir(parents=True)
    (folder / '01.png').write_bytes(b'x')
    rules = json.loads((pc.HERE / 'rules.json').read_text())
    for sid in ('iphone-duo-inner', 'iphone-duo-outer'):
        rules['screenshots']['slots'][sid]['required_sdk'] = 'iOS 28.1'
    (kit / 'rules.json').write_text(json.dumps(rules))
    for sdk, day, expected in [('iOS 28.0', '2027-04-01', None), (None, '2027-04-01', 'WARNING'),
                               ('iOS 28.1', '2027-03-31', 'WARNING'), ('iOS 28.1', '2027-04-01', 'BLOCKER')]:
        (kit / 'facts.yaml').write_text(yaml.safe_dump({'build': {'sdk': sdk}}))
        result = pc.Result(pc.load_catalogue())
        pc.chk_duo_screens(pc.Project(root, kit), result, SimpleNamespace(today=dt.date.fromisoformat(day)))
        assert {f['severity'] for f in result.findings} == ({expected} if expected else set())
        if sdk is None:
            assert all('SDK is unknown' in f['message'] for f in result.findings)


GENERATED_PLIST = pathlib.Path(__file__).resolve().parent / "fixtures" / "precheck-generated-plist"


def copy_generated_plist_project(tmp_path):
    """The Xcode-template layout: GENERATE_INFOPLIST_FILE = YES, MARKETING_VERSION = 1.0, no version in Info.plist."""
    import shutil
    root = tmp_path / "proj"
    shutil.copytree(GENERATED_PLIST, root)
    return root


def version_findings(data):
    return [f for f in data["findings"] if f["id"] == "UP-18" and "CFBundleShortVersionString" in f["message"]]


def test_generated_plist_version_comes_from_marketing_version(tmp_path, capsys):
    root = copy_generated_plist_project(tmp_path)
    assert "CFBundleShortVersionString" not in plistlib.loads((root / "Demo/Info.plist").read_bytes())
    _, data = run_json(root, capsys)
    assert version_findings(data) == []
    assert pc.Project(root).info_value("CFBundleShortVersionString", "MARKETING_VERSION") == \
        ("1.0", "build setting MARKETING_VERSION")
    assert pc.Project(root).info_value("CFBundleVersion", "CURRENT_PROJECT_VERSION")[0] == "7"


def test_generated_plist_with_empty_marketing_version_still_blocks(tmp_path, capsys):
    root = copy_generated_plist_project(tmp_path)
    pbx = root / "Demo.xcodeproj/project.pbxproj"
    pbx.write_text(pbx.read_text().replace("MARKETING_VERSION = 1.0;", 'MARKETING_VERSION = "";'))
    _, data = run_json(root, capsys)
    assert [f["severity"] for f in version_findings(data)] == ["BLOCKER"]


def test_marketing_version_reference_in_plist_resolves(tmp_path, capsys):
    root = copy_generated_plist_project(tmp_path)
    plist = root / "Demo/Info.plist"
    for ref in ("$(MARKETING_VERSION)", "${MARKETING_VERSION}"):
        info = plistlib.loads(plist.read_bytes())
        info["CFBundleShortVersionString"] = ref
        plist.write_bytes(plistlib.dumps(info))
        _, data = run_json(root, capsys)
        assert version_findings(data) == []
        assert pc.Project(root).info_value("CFBundleShortVersionString", "MARKETING_VERSION")[0] == "1.0"


def test_release_config_wins_and_infoplist_key_is_used(tmp_path):
    root = copy_generated_plist_project(tmp_path)
    pbx = root / "Demo.xcodeproj/project.pbxproj"
    text = pbx.read_text()
    debug_end = text.index("name = Debug;", text.index("MARKETING_VERSION"))
    text = text[:debug_end].replace("MARKETING_VERSION = 1.0;", "MARKETING_VERSION = 0.9;") + text[debug_end:]
    pbx.write_text(text)
    assert pc.Project(root).info_value("CFBundleShortVersionString", "MARKETING_VERSION")[0] == "1.0"
    pbx.write_text(text.replace("MARKETING_VERSION = 1.0;", 'MARKETING_VERSION = "";').replace(
        "MARKETING_VERSION = 0.9;", "INFOPLIST_KEY_CFBundleShortVersionString = 2.1;"))
    assert pc.Project(root).info_value("CFBundleShortVersionString", "MARKETING_VERSION") == \
        ("2.1", "build setting INFOPLIST_KEY_CFBundleShortVersionString")
