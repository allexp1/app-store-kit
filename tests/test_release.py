import plistlib

import pytest

import release as rl

PROJECT_YML = """name: App
settings:
  base:
    SWIFT_VERSION: "6.0"
    MARKETING_VERSION: "1.0.0"   # shown on the store
    CURRENT_PROJECT_VERSION: "22"
targets:
  App:
    info:
      properties:
        CFBundleShortVersionString: $(MARKETING_VERSION)
        CFBundleVersion: $(CURRENT_PROJECT_VERSION)
"""

PBXPROJ = """/* Begin XCBuildConfiguration section */
		A1 /* Debug */ = {
			buildSettings = {
				CURRENT_PROJECT_VERSION = 7;
				DEVELOPMENT_TEAM = ABCDE12345;
				MARKETING_VERSION = 1.2;
			};
		};
		A2 /* Release */ = {
			buildSettings = {
				CURRENT_PROJECT_VERSION = 7;
				MARKETING_VERSION = 1.2;
			};
		};
"""


@pytest.fixture(autouse=True)
def no_env_key(monkeypatch, tmp_path):
    for k in ("ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_KEY_PATH", "API_PRIVATE_KEYS_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(rl.subprocess, "run", lambda *a, **k: pytest.fail("subprocess must not run in tests"))


def yml_project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    (p / "project.yml").write_text(PROJECT_YML)
    return p


def test_bump_project_yml_minor_and_auto_build(tmp_path, capsys):
    p = yml_project(tmp_path)
    assert rl.main(["bump", str(p), "--minor", "--last-build", "30"]) == 0
    text = (p / "project.yml").read_text()
    assert 'MARKETING_VERSION: "1.1.0"   # shown on the store' in text
    assert 'CURRENT_PROJECT_VERSION: "31"' in text
    assert "$(MARKETING_VERSION)" in text and 'SWIFT_VERSION: "6.0"' in text
    assert text.replace("1.1.0", "1.0.0").replace('"31"', '"22"') == PROJECT_YML
    assert "1.0.0 → 1.1.0" in capsys.readouterr().out


def test_bump_dry_run_writes_nothing(tmp_path, capsys):
    p = yml_project(tmp_path)
    assert rl.main(["bump", str(p), "--version", "2.0.0", "--build", "40", "--dry-run"]) == 0
    assert (p / "project.yml").read_text() == PROJECT_YML
    out = capsys.readouterr().out
    assert "1.0.0 → 2.0.0" in out and "22 → 40" in out


def test_bump_refuses_lower_version_and_stale_build(tmp_path):
    p = yml_project(tmp_path)
    assert rl.main(["bump", str(p), "--version", "0.9.0"]) == 1
    assert rl.main(["bump", str(p), "--build", "25", "--last-build", "25"]) == 1
    assert (p / "project.yml").read_text() == PROJECT_YML


def test_bump_pbxproj_all_occurrences(tmp_path):
    p = tmp_path / "proj"
    (p / "App.xcodeproj").mkdir(parents=True)
    pbx = p / "App.xcodeproj" / "project.pbxproj"
    pbx.write_text(PBXPROJ)
    assert rl.main(["bump", str(p), "--patch"]) == 0
    text = pbx.read_text()
    assert text.count("MARKETING_VERSION = 1.2.1;") == 2
    assert text.count("CURRENT_PROJECT_VERSION = 8;") == 2
    assert "DEVELOPMENT_TEAM = ABCDE12345;" in text
    assert rl.team_from_project(p) == "ABCDE12345"


def test_upload_refuses_without_yes(tmp_path, capsys):
    assert rl.main(["upload", str(tmp_path / "App.xcarchive"), "--kit", str(tmp_path)]) == 3
    assert "owner's yes" in capsys.readouterr().err
    assert not (tmp_path / "export").exists()


def key_kit(tmp_path):
    kit = tmp_path / "kit"
    kit.mkdir()
    keydir = tmp_path / "home" / ".appstoreconnect" / "private_keys"
    keydir.mkdir(parents=True)
    (keydir / "AuthKey_KEY123.p8").write_text("-----BEGIN PRIVATE KEY-----\nSECRET\n")
    (kit / "connect.yaml").write_text("api:\n  key_id: KEY123\n  issuer_id: ISS-1\n  app_id: '6700000000'\n")
    return kit, keydir / "AuthKey_KEY123.p8"


def test_upload_dry_run_writes_export_options_and_masks_key(tmp_path, capsys):
    kit, keyfile = key_kit(tmp_path)
    archive = tmp_path / "build" / "App.xcarchive"
    archive.mkdir(parents=True)
    (archive / "Info.plist").write_bytes(plistlib.dumps({"ApplicationProperties": {"Team": "TEAM987654"}}))
    assert rl.main(["upload", str(archive), "--kit", str(kit), "--yes", "--dry-run"]) == 0
    out = capsys.readouterr().out
    opts = plistlib.loads((tmp_path / "build" / "export" / "ExportOptions.plist").read_bytes())
    assert opts["method"] == "app-store-connect" and opts["destination"] == "upload"
    assert opts["uploadSymbols"] is True and opts["manageAppVersionAndBuildNumber"] is False
    assert opts["teamID"] == "TEAM987654"
    line = next(ln for ln in out.splitlines() if ln.startswith("would run:"))
    for flag in ["xcodebuild", "-exportArchive", "-exportOptionsPlist", "-allowProvisioningUpdates",
                 "-authenticationKeyPath <key>", "-authenticationKeyID KEY123", "-authenticationKeyIssuerID ISS-1"]:
        assert flag in line
    assert str(keyfile) not in out and "SECRET" not in out


def test_archive_dry_run_command(tmp_path, capsys, monkeypatch):
    p = yml_project(tmp_path)
    monkeypatch.setenv("ASC_KEY_ID", "ENV1")
    monkeypatch.setenv("ASC_ISSUER_ID", "ISS-ENV")
    monkeypatch.setenv("ASC_KEY_PATH", str(tmp_path / "secret" / "k.p8"))
    assert rl.main(["archive", str(p), "--scheme", "Swipr", "--xcodegen", "--dry-run"]) == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("would run:")]
    assert lines[0].endswith("xcodegen generate")
    cmd = lines[1]
    for flag in ["xcodebuild -scheme Swipr -configuration Release -destination generic/platform=iOS",
                 f"-archivePath {p / 'build' / 'App.xcarchive'} archive", "-allowProvisioningUpdates",
                 "-authenticationKeyPath <key>", "-authenticationKeyID ENV1", "-authenticationKeyIssuerID ISS-ENV"]:
        assert flag in cmd
    assert "secret" not in cmd


def test_archive_without_xcodegen_flag_or_key(tmp_path, capsys):
    p = yml_project(tmp_path)
    assert rl.main(["archive", str(p), "--scheme", "S", "--out", str(tmp_path / "o"), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "xcodegen generate" not in out and "-authentication" not in out and "signed in to Xcode" in out


def test_wait_dry_run(tmp_path, capsys):
    kit, keyfile = key_kit(tmp_path)
    assert rl.main(["wait", "--kit", str(kit), "--version", "1.1.0", "--build", "31", "--dry-run"]) == 0
    line = next(ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("would run:"))
    for flag in ["xcrun altool --build-status", "--apple-id 6700000000", "--bundle-version 31",
                 "--bundle-short-version-string 1.1.0", "--platform ios", "--api-key KEY123", "--api-issuer ISS-1",
                 "--wait"]:
        assert flag in line
    assert str(keyfile.parent) not in line


def test_wait_needs_app_id(tmp_path):
    assert rl.main(["wait", "--version", "1.1.0", "--build", "31", "--dry-run"]) == 2
