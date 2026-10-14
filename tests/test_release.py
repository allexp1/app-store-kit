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


def fake_build_client(monkeypatch, builds, apps=None):
    calls = []
    config = object()
    monkeypatch.setattr(rl.asc_api, 'resolve_config', lambda **kw: calls.append(('config', kw)) or config)
    monkeypatch.setattr(rl.asc_api, 'TokenSigner', lambda c: config if c is config else pytest.fail('wrong config'))
    class Client:
        def __init__(self, token):
            assert token is config
        def get(self, path, params):
            calls.append((path, params))
            return {'data': (apps if apps is not None else [{'id': 'APP'}]) if path == '/v1/apps' else builds}
    monkeypatch.setattr(rl.asc_api, 'Client', Client)
    return calls


def test_last_build_auto_reads_latest_and_uses_api_key_resolution(tmp_path, monkeypatch):
    import yaml
    project = yml_project(tmp_path)
    kit = tmp_path / 'kit'
    kit.mkdir()
    (kit / 'facts.yaml').write_text(yaml.safe_dump({'app': {'bundle_id': 'com.example.app'}}))
    calls = fake_build_client(monkeypatch, [{'attributes': {'version': '40'}}])
    assert rl.main(['bump', str(project), '--last-build', 'auto', '--kit', str(kit)]) == 0
    assert 'CURRENT_PROJECT_VERSION: "41"' in (project / 'project.yml').read_text()
    assert calls == [('config', {'kit': str(kit)}),
                     ('/v1/apps', {'filter[bundleId]': 'com.example.app', 'limit': 2}),
                     ('/v1/builds', {'filter[app]': 'APP', 'sort': '-uploadedDate', 'limit': 1})]


def test_last_build_auto_without_key_explains_manual_fallback(tmp_path, monkeypatch, capsys):
    project = yml_project(tmp_path)
    def no_key(**kwargs):
        raise rl.asc_api.ConfigError('not configured')
    monkeypatch.setattr(rl.asc_api, 'resolve_config', no_key)
    assert rl.main(['bump', str(project), '--last-build', 'auto', '--bundle-id', 'com.example.app']) == 2
    assert 'no usable App Store Connect API key configured' in capsys.readouterr().err
    assert (project / 'project.yml').read_text() == PROJECT_YML


@pytest.mark.parametrize('builds,code,new_build', [([], 0, '23'), ([{'attributes': {'version': '10'}}], 0, '23'),
    ([{'attributes': {'version': '1.2'}}], 2, '22')])
def test_last_build_auto_empty_older_and_noninteger(tmp_path, monkeypatch, builds, code, new_build):
    project = yml_project(tmp_path)
    fake_build_client(monkeypatch, builds)
    assert rl.main(['bump', str(project), '--last-build', 'auto', '--bundle-id', 'com.example.app']) == code
    assert f'CURRENT_PROJECT_VERSION: "{new_build}"' in (project / 'project.yml').read_text()


def test_last_build_auto_project_bundle_dry_run_and_stale_build(tmp_path, monkeypatch):
    project = yml_project(tmp_path)
    path = project / 'project.yml'
    original = PROJECT_YML.replace('    SWIFT_VERSION:', '    PRODUCT_BUNDLE_IDENTIFIER: com.example.app\n    SWIFT_VERSION:')
    path.write_text(original)
    calls = fake_build_client(monkeypatch, [{'attributes': {'version': '40'}}])
    assert rl.main(['bump', str(project), '--last-build', 'auto', '--dry-run']) == 0
    assert calls[1][1]['filter[bundleId]'] == 'com.example.app'
    assert path.read_text() == original
    assert rl.main(['bump', str(project), '--last-build', 'auto', '--build', '40']) == 1
    assert path.read_text() == original
