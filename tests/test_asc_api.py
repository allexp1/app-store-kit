import base64
import json
import shutil
import subprocess

import pytest

import asc_api as api


def b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ------------------------------------------------------------------------------------------------ DER → raw
def test_der_to_raw_pads_and_strips():
    r = b"\x00" + b"\x80" + b"\x11" * 31          # high bit set: DER adds a leading zero
    s = b"\x05" * 30                               # short: raw form pads it to 32 bytes
    der = b"\x30" + bytes([2 + len(r) + 2 + len(s)]) + b"\x02" + bytes([len(r)]) + r + b"\x02" + bytes([len(s)]) + s
    raw = api.der_to_raw(der)
    assert len(raw) == 64
    assert raw[:32] == b"\x80" + b"\x11" * 31
    assert raw[32:] == b"\x00\x00" + b"\x05" * 30
    assert api.der_to_raw(api.raw_to_der(raw)) == raw


def test_der_to_raw_rejects_garbage():
    with pytest.raises(ValueError):
        api.der_to_raw(b"\x02\x01\x01")


# ------------------------------------------------------------------------------------------------ JWT
@pytest.fixture
def ec_key(tmp_path):
    if not shutil.which("openssl"):
        pytest.skip("openssl not installed")
    pem, p8, pub = tmp_path / "k.pem", tmp_path / "AuthKey_TESTKID123.p8", tmp_path / "pub.pem"
    subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(pem)], check=True)
    subprocess.run(["openssl", "pkcs8", "-topk8", "-nocrypt", "-in", str(pem), "-out", str(p8)], check=True)
    subprocess.run(["openssl", "ec", "-in", str(pem), "-pubout", "-out", str(pub)], check=True, capture_output=True)
    return p8, pub


def verify_with_openssl(token, pub, tmp_path):
    head, payload, sig = token.split(".")
    (tmp_path / "msg").write_bytes(f"{head}.{payload}".encode())
    (tmp_path / "sig").write_bytes(api.raw_to_der(b64d(sig)))
    r = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(pub), "-signature", str(tmp_path / "sig"),
                        str(tmp_path / "msg")], capture_output=True)
    return r.returncode == 0


def test_team_token_structure_and_signature(ec_key, tmp_path):
    p8, pub = ec_key
    now = [1_800_000_000]
    signer = api.TokenSigner(api.Config("TESTKID123", "issuer-uuid", p8), lifetime=5000, now=lambda: now[0],
                             use_openssl=True)
    tok = signer.token()
    head, payload, sig = tok.split(".")
    assert json.loads(b64d(head)) == {"alg": "ES256", "kid": "TESTKID123", "typ": "JWT"}
    p = json.loads(b64d(payload))
    assert p["iss"] == "issuer-uuid" and p["aud"] == "appstoreconnect-v1" and "sub" not in p
    assert p["exp"] - p["iat"] == 1200          # capped at 20 minutes
    assert len(b64d(sig)) == 64
    assert verify_with_openssl(tok, pub, tmp_path)
    now[0] += 1000
    assert signer.token() == tok                # reused while more than 60 s remain
    now[0] += 141
    assert signer.token() != tok                # renewed within 60 s of expiry
    assert "TESTKID123" in repr(signer) and tok not in repr(signer)


def test_individual_key_uses_sub_user(ec_key):
    p8, _ = ec_key
    tok = api.TokenSigner(api.Config("TESTKID123", None, p8), use_openssl=True).token()
    p = json.loads(b64d(tok.split(".")[1]))
    assert p["sub"] == "user" and "iss" not in p


# ------------------------------------------------------------------------------------------------ config
def test_resolve_config_order_and_key_search(tmp_path):
    home = tmp_path / "home"
    (home / ".appstoreconnect" / "private_keys").mkdir(parents=True)
    key = home / ".appstoreconnect" / "private_keys" / "AuthKey_KIT1.p8"
    key.write_text("not a real key")
    kit = tmp_path / "kit"
    kit.mkdir()
    (kit / "connect.yaml").write_text("api:\n  key_id: KIT1\n  issuer_id: iss-kit\n")
    c = api.resolve_config(kit=kit, env={}, home=home, cwd=tmp_path)
    assert (c.key_id, c.issuer_id, c.key_path) == ("KIT1", "iss-kit", key)
    other = tmp_path / "other.p8"
    other.write_text("x")
    c = api.resolve_config(kit=kit, env={"ASC_KEY_ID": "ENV1", "ASC_KEY_PATH": str(other)}, home=home, cwd=tmp_path)
    assert c.key_id == "ENV1" and c.key_path == other and c.issuer_id == "iss-kit"
    c = api.resolve_config("ARG1", None, str(other), kit=None, env={"ASC_ISSUER_ID": "i"}, home=home, cwd=tmp_path)
    assert c.key_id == "ARG1" and c.issuer_id == "i"
    c = api.resolve_config("ARG1", None, str(other), env={}, home=home, cwd=tmp_path)
    assert c.individual


def test_resolve_config_errors(tmp_path):
    with pytest.raises(api.ConfigError, match="key id"):
        api.resolve_config(env={}, home=tmp_path, cwd=tmp_path)
    with pytest.raises(api.ConfigError, match="AuthKey_NOPE.p8"):
        api.resolve_config("NOPE", env={}, home=tmp_path, cwd=tmp_path)


# ------------------------------------------------------------------------------------------------ client
class Scripted:
    """A transport that answers from a list of (status, headers, json) and records requests."""

    def __init__(self, answers):
        self.answers, self.seen = list(answers), []

    def __call__(self, method, url, headers, body):
        self.seen.append((method, url, dict(headers), body))
        status, h, doc = self.answers.pop(0)
        return status, h, json.dumps(doc).encode() if doc is not None else b""


def client(tr, **kw):
    return api.Client(lambda: "TOKEN", transport=tr, sleep=kw.pop("sleep", lambda s: None), **kw)


def test_get_all_follows_links_next():
    tr = Scripted([
        (200, {}, {"data": [{"id": "1"}, {"id": "2"}], "links": {"next": "https://api.appstoreconnect.apple.com/v1/apps?cursor=AB"}}),
        (200, {"X-Rate-Limit": "user-hour-lim:3500;user-hour-rem:42;"}, {"data": [{"id": "3"}], "links": {}}),
    ])
    c = client(tr)
    assert [d["id"] for d in c.get_all("/v1/apps", {"filter[bundleId]": "a.b", "limit": 200})] == ["1", "2", "3"]
    assert "filter[bundleId]=a.b" in tr.seen[0][1] and tr.seen[1][1].endswith("cursor=AB")
    assert tr.seen[0][2]["Authorization"] == "Bearer TOKEN"
    assert c.rate_remaining == 42 and c.rate_limit["user-hour-lim"] == 3500


def test_429_backoff_retry_after_then_exponential():
    waits = []
    tr = Scripted([(429, {"Retry-After": "7"}, {"errors": [{"code": "RATE_LIMIT_EXCEEDED"}]}),
                   (429, {}, {"errors": []}),
                   (200, {}, {"data": {"id": "x"}})])
    c = client(tr, sleep=waits.append)
    assert c.get("/v1/apps/x")["data"]["id"] == "x"
    assert waits == [7.0, 2]


def test_429_gives_up_after_max_retries():
    tr = Scripted([(429, {}, {"errors": [{"code": "RATE_LIMIT_EXCEEDED", "title": "t", "detail": "d"}]})] * 3)
    with pytest.raises(api.ASCError) as e:
        client(tr, max_retries=2).get("/v1/apps")
    assert e.value.status == 429 and e.value.codes == ["RATE_LIMIT_EXCEEDED"]


def test_error_carries_status_and_errors():
    tr = Scripted([(409, {}, {"errors": [{"status": "409", "code": "STATE_ERROR.INVALID_STATE", "title": "Bad",
                                          "detail": "approved parent"}]})])
    with pytest.raises(api.ASCError) as e:
        client(tr).post("/v1/appAssetLibraryPlacements", {"data": {"type": "appAssetLibraryPlacements"}})
    assert e.value.status == 409 and e.value.errors[0]["detail"] == "approved parent"
    assert "STATE_ERROR.INVALID_STATE" in str(e.value) and "TOKEN" not in str(e.value)


def test_dry_run_records_writes_and_still_reads():
    tr = Scripted([(200, {}, {"data": []})])
    c = client(tr, dry_run=True)
    c.get("/v1/apps")
    r = c.post("/v1/appStoreVersions", {"data": {"type": "appStoreVersions", "attributes": {"versionString": "2"}}})
    c.patch("/v1/apps/1", {"data": {"type": "apps", "id": "1", "attributes": {}}})
    c.delete("/v1/appAssetLibraryPlacements/9")
    assert len(tr.seen) == 1
    assert [x["method"] for x in c.recorded] == ["POST", "PATCH", "DELETE"]
    assert r["data"]["id"].startswith("DRYRUN") and r["data"]["attributes"]["versionString"] == "2"


def test_upload_operations_puts_slices_without_jwt(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"0123456789")
    tr = Scripted([(200, {}, None), (200, {}, None)])
    c = client(tr)
    c.upload_operations([{"method": "PUT", "url": "https://u/1", "offset": 0, "length": 4,
                          "requestHeaders": [{"name": "Content-Type", "value": "image/png"}]},
                         {"method": "PUT", "url": "https://u/2", "offset": 4, "length": 6, "requestHeaders": []}], f)
    assert [s[3] for s in tr.seen] == [b"0123", b"456789"]
    assert all("Authorization" not in s[2] for s in tr.seen)
    assert tr.seen[0][2]["Content-Type"] == "image/png"


def test_upload_failure_raises(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"x")
    with pytest.raises(api.ASCError):
        client(Scripted([(500, {}, None)])).upload_operations([{"url": "https://u/1", "offset": 0, "length": 1}], f)


def test_default_token_lifetime_stays_under_apples_limit_with_clock_skew():
    import asc_api
    assert asc_api.DEFAULT_LIFETIME <= asc_api.MAX_LIFETIME - 60
