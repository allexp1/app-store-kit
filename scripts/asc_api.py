#!/usr/bin/env python3
"""A small App Store Connect API client (API 4.5.1; facts in references/asc-api.md).

Auth     ES256 JWT from the owner's API key (.p8). Team key: iss = Issuer ID. Individual key: no issuer, sub = "user".
         Signs with `cryptography` when it is installed, else with the `openssl` CLI (the DER signature is
         converted to the raw r||s form JWT needs). exp = iat + 1200 s at most; the token is reused until 60 s
         before it expires. The key contents and the token are never printed or logged.
Config   resolve_config(): CLI args, then env (ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_PATH), then KIT/connect.yaml
         `api: {key_id, issuer_id, key_path?}`. Without a key path the key file AuthKey_<KID>.p8 is looked for
         where altool looks: ./private_keys, ~/private_keys, ~/.private_keys, ~/.appstoreconnect/private_keys,
         $API_PRIVATE_KEYS_DIR.
Client   request(method, path, params, json) over urllib (JSON:API); get_all() follows links.next; 429 (and 5xx on GET/PATCH/DELETE) is retried
         with Retry-After or exponential backoff; errors raise ASCError(status, errors[]). X-Rate-Limit is parsed
         into client.rate_limit. upload_operations() PUTs the parts of an asset reservation (no JWT on those).
         The transport is pluggable (tests inject a fake). dry_run=True records every non-GET call in
         client.recorded instead of sending it and answers with a made-up id so a flow can continue.
"""
from __future__ import annotations

import base64
import dataclasses
import json as jsonlib
import os
import pathlib
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

import yaml

BASE_URL = "https://api.appstoreconnect.apple.com"
AUDIENCE = "appstoreconnect-v1"
MAX_LIFETIME = 1200          # Apple: exp - iat at most 20 minutes
# Apple rejects exp more than 20 minutes after ITS clock, so a Mac running a second fast fails with exactly 1200 s
# (seen live 2026-10-14: intermittent 401 NOT_AUTHORIZED). Stay well under.
DEFAULT_LIFETIME = 1080
REFRESH_MARGIN = 60          # renew a token this many seconds before it expires


class ASCError(Exception):
    """An App Store Connect error response: HTTP status plus the JSON:API errors[] (code, title, detail)."""

    def __init__(self, status, errors=None, method="", path="", message=None):
        self.status, self.errors, self.method, self.path = status, list(errors or []), method, path
        super().__init__(message or self._text())

    def _text(self):
        parts = [f"{e.get('code', '')}: {e.get('title', '')} {e.get('detail', '')}".strip() for e in self.errors]
        where = f"{self.method} {self.path}".strip()
        return f"HTTP {self.status} {where}" + (" - " + "; ".join(parts) if parts else "")

    @property
    def codes(self):
        return [e.get("code", "") for e in self.errors]


class ConfigError(Exception):
    pass


# ---------------------------------------------------------------------------------------------------- config
@dataclasses.dataclass
class Config:
    key_id: str
    issuer_id: str | None
    key_path: pathlib.Path

    @property
    def individual(self):
        return not self.issuer_id


def key_dirs(env=None, home=None, cwd=None):
    """The folders altool searches for AuthKey_<KID>.p8, in its order."""
    env = os.environ if env is None else env
    home = pathlib.Path(home) if home else pathlib.Path.home()
    cwd = pathlib.Path(cwd) if cwd else pathlib.Path.cwd()
    dirs = [cwd / "private_keys", home / "private_keys", home / ".private_keys",
            home / ".appstoreconnect" / "private_keys"]
    if env.get("API_PRIVATE_KEYS_DIR"):
        dirs.append(pathlib.Path(env["API_PRIVATE_KEYS_DIR"]).expanduser())
    return dirs


def find_key_file(key_id, env=None, home=None, cwd=None):
    for d in key_dirs(env, home, cwd):
        p = d / f"AuthKey_{key_id}.p8"
        if p.is_file():
            return p
    return None


def resolve_config(key_id=None, issuer_id=None, key_path=None, kit=None, env=None, home=None, cwd=None):
    """Config from CLI args, then env, then KIT/connect.yaml `api:`. Raises ConfigError with what is missing."""
    env = os.environ if env is None else env
    api = {}
    if kit:
        p = pathlib.Path(kit) / "connect.yaml"
        if p.exists():
            api = (yaml.safe_load(p.read_text()) or {}).get("api") or {}
    kid = key_id or env.get("ASC_KEY_ID") or api.get("key_id")
    iss = issuer_id or env.get("ASC_ISSUER_ID") or api.get("issuer_id")
    path = key_path or env.get("ASC_KEY_PATH") or api.get("key_path")
    if not kid:
        raise ConfigError("No API key id: pass --key-id, set ASC_KEY_ID, or add api: {key_id: ...} to connect.yaml.")
    if path:
        path = pathlib.Path(str(path)).expanduser()
        if not path.is_absolute() and kit:
            cand = pathlib.Path(kit) / path
            path = cand if cand.exists() else path
    else:
        path = find_key_file(str(kid), env, home, cwd)
    if not path or not pathlib.Path(path).is_file():
        where = ", ".join(str(d) for d in key_dirs(env, home, cwd))
        raise ConfigError(f"Key file AuthKey_{kid}.p8 not found (looked in {where}). "
                          "Pass --key-path or set ASC_KEY_PATH.")
    return Config(str(kid), str(iss) if iss else None, pathlib.Path(path))


# ---------------------------------------------------------------------------------------------------- JWT
def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _der_len(buf, i):
    n = buf[i]
    if n < 0x80:
        return n, i + 1
    k = n & 0x7F
    return int.from_bytes(buf[i + 1:i + 1 + k], "big"), i + 1 + k


def der_to_raw(der: bytes, size: int = 32) -> bytes:
    """ECDSA signature: DER SEQUENCE{INTEGER r, INTEGER s} → raw r||s, each left-padded to `size` bytes."""
    if not der or der[0] != 0x30:
        raise ValueError("not a DER ECDSA signature")
    _, i = _der_len(der, 1)
    out = b""
    for _ in range(2):
        if der[i] != 0x02:
            raise ValueError("bad DER integer")
        n, i = _der_len(der, i + 1)
        v = der[i:i + n].lstrip(b"\x00")
        i += n
        if len(v) > size:
            raise ValueError("integer longer than the curve size")
        out += v.rjust(size, b"\x00")
    return out


def raw_to_der(raw: bytes) -> bytes:
    """The reverse of der_to_raw (used to verify signatures with openssl)."""
    half = len(raw) // 2

    def integer(b):
        b = b.lstrip(b"\x00") or b"\x00"
        if b[0] & 0x80:
            b = b"\x00" + b
        return b"\x02" + bytes([len(b)]) + b
    body = integer(raw[:half]) + integer(raw[half:])
    return b"\x30" + bytes([len(body)]) + body


def _sign_der(key_path, message: bytes, use_openssl=False) -> bytes:
    if not use_openssl:
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec
        except ImportError:
            use_openssl = True
    if use_openssl:
        r = subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(key_path)], input=message,
                           capture_output=True)
        if r.returncode != 0:
            raise ConfigError("openssl could not sign with the key file (is it an EC .p8 key?)")
        return r.stdout
    key = serialization.load_pem_private_key(pathlib.Path(key_path).read_bytes(), password=None)
    return key.sign(message, ec.ECDSA(hashes.SHA256()))


class TokenSigner:
    """Makes and caches the ES256 JWT. Call token() before each request."""

    def __init__(self, config: Config, lifetime=None, now=time.time, use_openssl=False):
        self.config, self.now, self.use_openssl = config, now, use_openssl
        self.lifetime = min(int(lifetime or DEFAULT_LIFETIME), MAX_LIFETIME)
        self._token, self._exp = None, 0

    def token(self) -> str:
        now = int(self.now())
        if self._token and now < self._exp - REFRESH_MARGIN:
            return self._token
        header = {"alg": "ES256", "kid": self.config.key_id, "typ": "JWT"}
        payload = {"iat": now, "exp": now + self.lifetime, "aud": AUDIENCE}
        if self.config.issuer_id:
            payload["iss"] = self.config.issuer_id
        else:
            payload["sub"] = "user"
        signing_input = (b64url(jsonlib.dumps(header, separators=(",", ":")).encode()) + "." +
                         b64url(jsonlib.dumps(payload, separators=(",", ":")).encode()))
        sig = der_to_raw(_sign_der(self.config.key_path, signing_input.encode(), self.use_openssl))
        self._token, self._exp = signing_input + "." + b64url(sig), payload["exp"]
        return self._token

    def __repr__(self):  # never show the token
        return f"TokenSigner(key_id={self.config.key_id!r})"


# ---------------------------------------------------------------------------------------------------- transport
def urllib_transport(method, url, headers, body, timeout=120):
    """(method, url, headers, body bytes|None) → (status, headers dict lower-cased, body bytes)."""
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read() or b""


def parse_rate_limit(value):
    """'user-hour-lim:3500;user-hour-rem:500;' → {'user-hour-lim': 3500, 'user-hour-rem': 500}."""
    out = {}
    for part in (value or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            try:
                out[k.strip()] = int(v.strip())
            except ValueError:
                out[k.strip()] = v.strip()
    return out


class Client:
    def __init__(self, token=None, transport=None, dry_run=False, base_url=BASE_URL, sleep=time.sleep,
                 max_retries=5, log=None):
        """token: a TokenSigner or a zero-arg callable returning the JWT. transport: see urllib_transport."""
        self._token = token.token if hasattr(token, "token") else token
        self.transport = transport or urllib_transport
        self.dry_run, self.base_url, self.sleep, self.max_retries = dry_run, base_url.rstrip("/"), sleep, max_retries
        self.log = log
        self.rate_limit = {}
        self.recorded = []       # dry-run: every non-GET call that would have been sent
        self.sent = []           # every non-GET call actually sent (method, path), for summaries
        self._dry_n = 0

    @property
    def rate_remaining(self):
        return self.rate_limit.get("user-hour-rem")

    def _url(self, path, params):
        url = path if path.startswith("http") else self.base_url + (path if path.startswith("/") else "/" + path)
        if params:
            q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, safe="[],:")
            url += ("&" if "?" in url else "?") + q
        return url

    def _fake(self, method, path, body):
        """Dry-run answer for a non-GET call: echo the body with a made-up id."""
        if method == "DELETE" or not body:
            return None
        self._dry_n += 1
        data = dict((body or {}).get("data") or {})
        if isinstance(data, dict):
            data.setdefault("id", f"DRYRUN-{self._dry_n}")
            attrs = dict(data.get("attributes") or {})
            if data.get("type") in ("appAssetLibraryImages", "appAssetLibraryVideos", "inAppPurchaseImages",
                                    "inAppPurchaseAppStoreReviewScreenshots"):
                attrs.setdefault("uploadOperations", [])
                attrs.setdefault("state", "PREPARE_FOR_SUBMISSION")
            data["attributes"] = attrs
        return {"data": data}

    def request(self, method, path, params=None, json=None):
        method = method.upper()
        url = self._url(path, params)
        if method != "GET" and self.dry_run:
            self.recorded.append({"method": method, "path": url.replace(self.base_url, ""), "json": json})
            return self._fake(method, path, json)
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = "Bearer " + self._token()
        body = None
        if json is not None:
            body = jsonlib.dumps(json).encode()
            headers["Content-Type"] = "application/json"
        attempt = 0
        while True:
            status, rh, raw = self.transport(method, url, headers, body)
            rh = {str(k).lower(): v for k, v in (rh or {}).items()}
            if "x-rate-limit" in rh:
                self.rate_limit = parse_rate_limit(rh["x-rate-limit"])
            if status == 429 and attempt < self.max_retries:
                wait = rh.get("retry-after")
                try:
                    wait = float(wait)
                except (TypeError, ValueError):
                    wait = min(2 ** attempt, 60)
                if self.log:
                    self.log(f"rate limited; waiting {wait:g} s")
                self.sleep(wait)
                attempt += 1
                continue
            # A one-off 500/502/503/504 (seen live 2026-10-14 on PATCH appAssetLibraryImages {"uploaded": true}; the
            # same PATCH succeeded a minute later). Only requests that are safe to repeat; a POST could create twice.
            if status in (500, 502, 503, 504) and method in ("GET", "PATCH", "DELETE") and attempt < self.max_retries:
                wait = min(5 * 2 ** attempt, 60)
                if self.log:
                    self.log(f"HTTP {status} from Apple; trying again in {wait:g} s")
                self.sleep(wait)
                attempt += 1
                continue
            break
        doc = None
        if raw:
            try:
                doc = jsonlib.loads(raw)
            except ValueError:
                doc = None
        if status >= 400:
            raise ASCError(status, (doc or {}).get("errors") if isinstance(doc, dict) else None, method,
                           url.replace(self.base_url, ""))
        if method != "GET":
            self.sent.append((method, url.replace(self.base_url, "")))
        return doc

    def get(self, path, params=None):
        return self.request("GET", path, params)

    def get_all(self, path, params=None, include_included=False):
        """Every item of a collection, following links.next. With include_included, returns (data, included)."""
        data, included = [], []
        doc = self.request("GET", path, params)
        while True:
            d = (doc or {}).get("data")
            data += d if isinstance(d, list) else ([d] if d else [])
            included += (doc or {}).get("included") or []
            nxt = ((doc or {}).get("links") or {}).get("next")
            if not nxt:
                break
            doc = self.request("GET", nxt)
        return (data, included) if include_included else data

    def post(self, path, json):
        return self.request("POST", path, json=json)

    def patch(self, path, json):
        return self.request("PATCH", path, json=json)

    def delete(self, path, json=None):
        """DELETE; relationship deletes (e.g. .../relationships/searchKeywords) carry a linkage body."""
        return self.request("DELETE", path, json=json)

    def upload_operations(self, ops, file_path):
        """PUT each upload operation's slice of the file (no JWT; Apple's upload URLs carry their own auth)."""
        file_path = pathlib.Path(file_path)
        if self.dry_run:
            self.recorded.append({"method": "PUT", "path": f"{len(ops or [])} upload part(s)",
                                  "file": file_path.name, "bytes": file_path.stat().st_size})
            return
        data = file_path.read_bytes()
        for op in ops or []:
            off, length = int(op.get("offset", 0)), int(op.get("length", len(data)))
            headers = {h["name"]: h["value"] for h in op.get("requestHeaders") or []}
            status, _, _ = self.transport(op.get("method", "PUT"), op["url"], headers, data[off:off + length])
            if status >= 300:
                raise ASCError(status, [], op.get("method", "PUT"), "upload part",
                               message=f"upload of {file_path.name} bytes {off}-{off + length} failed: HTTP {status}")


def make_client(args=None, kit=None, dry_run=False, log=None):
    """Client from argparse args (key_id, issuer_id, key_path) / env / connect.yaml."""
    cfg = resolve_config(getattr(args, "key_id", None), getattr(args, "issuer_id", None),
                         getattr(args, "key_path", None), kit=kit)
    return Client(TokenSigner(cfg), dry_run=dry_run, log=log)
