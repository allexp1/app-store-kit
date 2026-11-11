"""Offline tests for the Apple Ads key setup script."""
import json
import shutil
import stat

import pytest
import yaml

import apple_ads_key as ak

BLOCK = """clientId SEARCHADS.aeb3ef5f-0c5a-4f2a-99c8-fca83f25a9
teamId SEARCHADS.hgw3ef3p-0w7a-8a2n-77c8-scv83f25a7
keyId a273d0d3-4d9e-458c-a173-0db8619ca7d7"""
NO_COPY = lambda text: False  # noqa: E731
needs_openssl = pytest.mark.skipif(not shutil.which("openssl"), reason="openssl not installed")


def fake_api(accounts):
    calls = []

    def transport(method, url, headers, body):
        calls.append((method, url, headers))
        if url.endswith("/oauth2/token"):
            return 200, {}, b'{"access_token": "tok", "expires_in": 3600}'
        assert url == "https://api.ads.apple.com/v1/acls" and "X-AP-Context" not in headers
        return 200, {}, json.dumps({"result": {"acls": [{"adAccount": {"id": i, "name": n}, "roles": ["API Account Manager"]}
                                                       for i, n in accounts]}}).encode()
    transport.calls = calls
    return transport


def answers(*lines):
    it = iter(lines)

    def ask(_prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None
    return ask


def test_parse_ids_reads_apples_block():
    assert ak.parse_ids(BLOCK) == {"client_id": "SEARCHADS.aeb3ef5f-0c5a-4f2a-99c8-fca83f25a9",
                                   "team_id": "SEARCHADS.hgw3ef3p-0w7a-8a2n-77c8-scv83f25a7",
                                   "key_id": "a273d0d3-4d9e-458c-a173-0db8619ca7d7"}
    assert ak.parse_ids('{"clientId": "SEARCHADS.x", "teamId": "SEARCHADS.y", "keyId": "k"}')["team_id"] == "SEARCHADS.y"


def test_write_connect_keeps_other_lines_and_replaces_old_block(tmp_path):
    (tmp_path / "connect.yaml").write_text("# my notes\napp: x\napple_ads:\n  client_id: old\n  key_id: old\nother: 1\n")
    ak.write_connect(tmp_path, {"client_id": "c", "team_id": "t", "key_id": "k", "key_path": "/p", "ad_account_id": "42"})
    text = (tmp_path / "connect.yaml").read_text()
    assert text.startswith("# my notes\napp: x\nother: 1\n") and "old" not in text
    assert yaml.safe_load(text)["apple_ads"] == {"client_id": "c", "team_id": "t", "key_id": "k", "key_path": "/p",
                                                 "ad_account_id": "42"}


@needs_openssl
def test_full_run_makes_a_private_key_and_saves_ids(tmp_path, capsys):
    kit, keys = tmp_path / "kit", tmp_path / "keys"
    kit.mkdir()
    api = fake_api([(4242, "My Apps")])
    assert ak.main([str(kit), "--key-dir", str(keys)], prompt=answers(*BLOCK.splitlines()), transport=api, copy=NO_COPY) == 0
    out = capsys.readouterr().out
    assert "BEGIN PUBLIC KEY" in out and "PRIVATE KEY-----\n" not in out          # only the public half is shown
    assert stat.S_IMODE((keys / "private-key.pem").stat().st_mode) == 0o600
    assert stat.S_IMODE(keys.stat().st_mode) == 0o700
    conf = yaml.safe_load((kit / "connect.yaml").read_text())["apple_ads"]
    assert conf["ad_account_id"] == "4242" and conf["key_path"] == str(keys / "private-key.pem")
    first = (keys / "private-key.pem").read_text()
    assert ak.main([str(kit), "--key-dir", str(keys), "--no-verify", "--ad-account-id", "4242",
                    "--client-id", "c", "--team-id", "t", "--key-id", "k"]) == 0
    assert (keys / "private-key.pem").read_text() == first                         # reused, not replaced


@needs_openssl
def test_new_key_keeps_the_old_one(tmp_path):
    kit, keys = tmp_path / "kit", tmp_path / "keys"
    kit.mkdir()
    ak.make_key(keys)
    first = (keys / "private-key.pem").read_text()
    ak.make_key(keys, new=True)
    assert (keys / "private-key.pem").read_text() != first
    assert any(p.read_text() == first for p in keys.glob("private-key.*.pem"))


@needs_openssl
def test_several_accounts_ask_which_and_bad_answer_saves_nothing(tmp_path):
    kit, keys = tmp_path / "kit", tmp_path / "keys"
    kit.mkdir()
    api = fake_api([(1, "A"), (2, "B")])
    assert ak.main([str(kit), "--key-dir", str(keys)], prompt=answers(*BLOCK.splitlines(), "", "9", "x"), transport=api,
                   copy=NO_COPY) == 1                                           # runs out of answers: nothing saved
    assert not (kit / "connect.yaml").exists()
    assert ak.main([str(kit), "--key-dir", str(keys)], prompt=answers(*BLOCK.splitlines(), "", "", "2"), transport=api, copy=NO_COPY) == 0
    assert yaml.safe_load((kit / "connect.yaml").read_text())["apple_ads"]["ad_account_id"] == "2"


@needs_openssl
def test_refused_sign_in_saves_nothing(tmp_path, capsys):
    kit, keys = tmp_path / "kit", tmp_path / "keys"
    kit.mkdir()
    refuse = lambda *a: (400, {}, b'{"error": "invalid_client"}')  # noqa: E731
    assert ak.main([str(kit), "--key-dir", str(keys)], prompt=answers(*BLOCK.splitlines()), transport=refuse, copy=NO_COPY) == 1
    assert "Nothing was saved" in capsys.readouterr().out and not (kit / "connect.yaml").exists()


def test_key_inside_the_kit_is_refused(tmp_path):
    assert ak.main([str(tmp_path), "--key-dir", str(tmp_path / "keys")]) == 2
