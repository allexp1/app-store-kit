import json

import yaml

import locales as lc


def test_table_has_the_50_api_codes():
    assert len(lc.LOCALES) == 50
    for code in ["ar-SA", "de-DE", "no", "ur-PK", "kn-IN", "zh-Hans", "zh-Hant", "pt-BR", "en-US", "sl-SI"]:
        assert lc.is_valid(code)
    for bad in ["ar", "de", "nb", "zh-CN", "en"]:
        assert not lc.is_valid(bad)
    assert {c for c, v in lc.LOCALES.items() if v["rtl"]} == {"ar-SA", "he", "ur-PK"}
    assert lc.LOCALES["no"]["app_codes"][0] == "nb"
    assert "iw" in lc.LOCALES["he"]["app_codes"]
    assert lc.LOCALES["de-DE"]["app_codes"][0] == "de"


def test_list_prints_every_code(capsys):
    assert lc.main(["list"]) == 0
    out = capsys.readouterr().out
    assert all(code in out for code in lc.LOCALES)


def make_kit(tmp_path, facts_text=None):
    kit = tmp_path / "AppStore"
    kit.mkdir()
    (kit / "metadata.en-US.yaml").write_text(yaml.safe_dump({
        "name": "Pebble", "subtitle": "Tidy photos", "keywords": "declutter,storage",
        "description": "Long text", "support_url": "https://example.com/s",
        "privacy_policy_url": "https://example.com/p", "category": {"primary": "Photo & Video"},
        "copyright": "2026 Example", "iap": [{"product_id": "pro", "display_name": "Pro", "description": "No ads"}]}))
    if facts_text is not None:
        (kit / "facts.yaml").write_text(facts_text)
    shots = kit / "screenshots" / "en-US" / "iphone-6.9"
    shots.mkdir(parents=True)
    (shots / "01.png").write_bytes(b"x")
    app = tmp_path / "App"
    app.mkdir()
    (app / "Localizable.xcstrings").write_text(json.dumps({"sourceLanguage": "en", "version": "1.0", "strings": {
        "Keep": {"localizations": {"de": {"stringUnit": {"state": "translated", "value": "Behalten"}}}},
        "Delete": {"localizations": {"de": {"stringUnit": {"state": "translated", "value": "Löschen"}}}},
        "Undo": {},
        "%@": {"shouldTranslate": False},
    }}))
    return kit


def test_check_reports_metadata_screenshots_and_app_coverage(tmp_path, capsys):
    kit = make_kit(tmp_path, "company: Example\nlocales: [en-US, de-DE, ja]\n")
    (kit / "metadata.de-DE.yaml").write_text("name: x\n")
    rc = lc.main(["check", str(kit), "--project", str(tmp_path / "App")])
    out = capsys.readouterr().out
    assert rc == 0
    lines = {ln.split()[0]: ln for ln in out.splitlines() if ln[:2] in ("en", "de", "ja")}
    assert "own" in lines["en-US"] and "en 3/3" in lines["en-US"]
    assert "uses primary screenshots" in lines["de-DE"] and "de 2/3" in lines["de-DE"]
    assert "MISSING" in lines["ja"] and "no (" in lines["ja"]
    assert "warn: ja: the app itself is not translated" in out


def test_check_invalid_code_exits_1(tmp_path, capsys):
    kit = make_kit(tmp_path, "locales: [en-US, de]\n")
    assert lc.main(["check", str(kit), "--project", str(tmp_path / "App")]) == 1
    assert "did you mean de-DE" in capsys.readouterr().out


def test_check_defaults_to_metadata_files_and_lproj(tmp_path, capsys):
    kit = make_kit(tmp_path)
    (kit / "metadata.fr-FR.yaml").write_text("name: x\n")
    proj = tmp_path / "Other"
    (proj / "fr.lproj").mkdir(parents=True)
    assert lc.kit_locales(kit) == ["en-US", "fr-FR"]
    lc.main(["check", str(kit), "--project", str(proj)])
    out = capsys.readouterr().out
    assert "fr.lproj" in out


def test_scaffold_creates_skeleton_keeps_existing_and_updates_flow_list(tmp_path, capsys):
    kit = make_kit(tmp_path, "# top comment\nlocales: [en-US]   # primary first\ncompany: Example  # keep me\n")
    (kit / "metadata.ja.yaml").write_text("name: existing\n")
    assert lc.main(["scaffold", str(kit), "de-DE", "ja"]) == 0
    de = (kit / "metadata.de-DE.yaml").read_text()
    assert "ADAPTS" in de and "100 BYTES" in de
    data = yaml.safe_load(de)
    assert data["name"] == "" and data["description"] == "" and data["keywords"] == ""
    assert data["support_url"] == "https://example.com/s" and data["category"] == {"primary": "Photo & Video"}
    assert data["iap"] == [{"product_id": "pro", "display_name": "", "description": ""}]
    assert (kit / "metadata.ja.yaml").read_text() == "name: existing\n"
    facts = (kit / "facts.yaml").read_text()
    assert facts.startswith("# top comment\nlocales: [en-US, de-DE, ja]   # primary first\n")
    assert "# keep me" in facts


def test_scaffold_block_list_and_absent_key(tmp_path):
    kit = make_kit(tmp_path, "locales:\n  - en-US  # primary\n# note\nother: 1\n")
    lc.main(["scaffold", str(kit), "he"])
    facts = (kit / "facts.yaml").read_text()
    assert yaml.safe_load(facts)["locales"] == ["en-US", "he"]
    assert "# primary" in facts and "# note" in facts
    assert "Right-to-left" in (kit / "metadata.he.yaml").read_text()

    kit2 = make_kit(tmp_path / "b", "company: Example # c\n") if (tmp_path / "b").mkdir() is None else None
    lc.main(["scaffold", str(kit2), "ko"])
    facts2 = (kit2 / "facts.yaml").read_text()
    assert "company: Example # c" in facts2
    assert yaml.safe_load(facts2)["locales"] == ["en-US", "ko"]


def test_scaffold_rejects_invalid_code(tmp_path):
    kit = make_kit(tmp_path, "locales: [en-US]\n")
    assert lc.main(["scaffold", str(kit), "nb"]) == 1
    assert not (kit / "metadata.nb.yaml").exists()
