#!/usr/bin/env python3
"""Plan, create, measure and optimise Apple Ads search results campaigns for the owner's app.

Apple Ads Platform API v1 (https://api.ads.apple.com/v1; the Campaign Management API v5 sunsets 2027-01-26).
Strategy and every rule here: references/apple-ads.md. Input: KIT/apple-ads.yaml (templates/apple-ads.example.yaml).

  check KIT                  offline: validates apple-ads.yaml, prints the structure and the money
  status KIT                 reads the ad account and this app's campaigns
  plan KIT                   reads only; writes apple-ads-plan.md/.json (what apply would create)
  apply KIT --yes            creates exactly the saved plan; every campaign is created PAUSED
  activate KIT --campaign ID --yes    starts spending (campaigns this kit created only)
  pause KIT --campaign ID --yes       stops spending (any campaign promoting this app)
  report KIT [--days N]      keyword and search-term performance → apple-ads-report.md/.json
  optimize KIT [--days N]    proposals only → apple-ads-proposals.md/.json (each "approve": false)
  apply-proposals KIT --yes  applies the proposals the owner set to "approve": true, re-checking each first

Writes refuse without --yes (also for --dry-run, which prints the requests and sends none).
Never deletes: removing a campaign or ad group is permanent in Apple Ads, so the kit pauses instead.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
import hashlib
import json as jsonlib
import os
import pathlib
import re
import sys
import time
import urllib.parse

import yaml

import asc_api

BASE_URL = "https://api.ads.apple.com"
TOKEN_URL = "https://appleid.apple.com/auth/oauth2/token"
AUDIENCE = "https://appleid.apple.com"
SECRET_LIFETIME = 86400          # the client secret may live < 180 days; one day is plenty for a CLI run
PLAN_VERSION = 1
THEMES = ("brand", "category", "competitor", "discovery")
DEFAULT_CR = {"brand": 0.6, "category": 0.4, "competitor": 0.25, "discovery": 0.3}
DEFAULT_SPLIT = {"brand": 0.15, "category": 0.35, "competitor": 0.2, "discovery": 0.3}
SEARCH_MATCH_FACTOR = Decimal("0.8")     # Search Match ad group bids below the broad ad group
MIN_BID = Decimal("0.10")
MAX_KEYWORDS_PER_AD_GROUP = 5000         # Apple help: keywords per ad group
MAX_KEYWORDS_PER_CAMPAIGN = 10000        # Apple help: targeted + negative keywords
BULK_CHUNK = 100                         # v1 bulk cap is undocumented; stay small
MONTH_DAYS = Decimal("30.4")             # Apple: monthly spend <= daily budget x 30.4
SEP = " - "                              # Apple rejects "|" in campaign names (INVALID_FORMAT_CAMPAIGN_NAME)


class AdsError(Exception):
    pass


class ApiError(AdsError):
    """An Apple Ads Platform API error: HTTP status plus error.code / message / details."""

    def __init__(self, status, error=None, method="", path=""):
        self.status, self.error = status, error or {}
        details = "; ".join(f"{d.get('code', '')} {d.get('message', '')}".strip()
                            for d in self.error.get("details") or [])
        text = f"HTTP {status} {method} {path}".strip()
        if self.error.get("code") or self.error.get("message"):
            text += f" - {self.error.get('code', '')}: {self.error.get('message') or ''}"
        super().__init__(text + (f" ({details})" if details else ""))


# ------------------------------------------------------------------------------------------------ money
def money(value, label):
    try:
        if isinstance(value, bool):
            raise InvalidOperation
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        raise AdsError(f"{label} must be a positive amount") from None
    return amount


def cents(amount):
    return Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def m(amount, currency):
    return {"amount": format(cents(amount), "f"), "currency": currency}


def amount_of(value):
    try:
        return Decimal(str((value or {}).get("amount", "0")))
    except (InvalidOperation, AttributeError):
        return Decimal(0)


def digest(value):
    return hashlib.sha256(jsonlib.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


# ------------------------------------------------------------------------------------------------ config
def _mapping(value, label, allowed):
    if not isinstance(value, dict):
        raise AdsError(f"{label} must be a mapping")
    extra = set(value) - set(allowed)
    if extra:
        raise AdsError(f"{label} has unknown fields: {', '.join(sorted(extra))}; see templates/apple-ads.example.yaml")
    return value


def _keywords(values, label):
    if values is None:
        return []
    if not isinstance(values, list) or not all(isinstance(v, str) and v.strip() for v in values):
        raise AdsError(f"{label} must be a list of non-empty strings")
    out, seen = [], set()
    for v in values:
        text = " ".join(v.split())
        if len(text) > 80:      # longer than any real App Store query; catches pasted sentences
            raise AdsError(f"{label}: '{text[:30]}…' is longer than 80 characters")
        if text.lower() not in seen:
            seen.add(text.lower())
            out.append(text)
    return out


def _keyword_sets(raw, label):
    """({theme: [keywords]} for brand/category/competitor, [negatives]); one theme per keyword."""
    kw = _mapping(raw or {}, label, set(THEMES[:3]) | {"negative"})
    keywords = {t: _keywords(kw.get(t), f"{label}.{t}") for t in THEMES[:3]}
    negatives = _keywords(kw.get("negative"), f"{label}.negative")
    seen = {}
    for theme in THEMES[:3]:
        for text in keywords[theme]:
            if text.lower() in seen:
                raise AdsError(f"{label}: '{text}' is in both {seen[text.lower()]} and {theme}; one theme per keyword")
            seen[text.lower()] = theme
    clash = [n for n in negatives if n.lower() in seen]
    if clash:
        raise AdsError(f"{label}: a negative keyword is also a targeted keyword: " + ", ".join(clash))
    return keywords, negatives


def _split(raw, label):
    split = {t: float(money(v, f"{label}.{t}")) for t, v in _mapping(raw, label, THEMES).items()}
    split = {t: split.get(t, 0.0) for t in THEMES}
    if abs(sum(split.values()) - 1) > 0.001:
        raise AdsError(f"{label} shares must add up to 1")
    return split


def validate(raw):
    raw = _mapping(raw, "apple-ads.yaml", {"app", "currency", "target_cpa", "max_bid", "expected_cr", "keywords",
                                           "strategy", "markets", "budget_split", "customer_type", "other_app_ids",
                                           "custom_product_pages", "owns_app_and_account", "french_business"})
    app = _mapping(raw.get("app") or {}, "app", {"adam_id", "name"})
    adam = str(app.get("adam_id") or "")
    if not re.fullmatch(r"\d{6,12}", adam):
        raise AdsError("app.adam_id must be the app's numeric App Store id")
    name = str(app.get("name") or "").strip()
    if not name or SEP in name or "|" in name:
        raise AdsError("app.name is required and must not contain ' - ' or '|'")
    currency = str(raw.get("currency") or "")
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise AdsError("currency must be a three-letter code such as USD (the Apple Ads account currency)")
    target = money(raw.get("target_cpa"), "target_cpa")
    cap = money(raw.get("max_bid"), "max_bid")
    cr = dict(DEFAULT_CR)
    for theme, value in (_mapping(raw.get("expected_cr") or {}, "expected_cr", THEMES)).items():
        rate = money(value, f"expected_cr.{theme}")
        if rate > 1:
            raise AdsError(f"expected_cr.{theme} is a rate between 0 and 1")
        cr[theme] = float(rate)
    keywords, negatives = _keyword_sets(raw.get("keywords"), "keywords")
    strategy = {t: "manage_bids" for t in THEMES}
    for theme, value in _mapping(raw.get("strategy") or {}, "strategy", THEMES).items():
        if value not in ("manage_bids", "maximize_conversions"):
            raise AdsError(f"strategy.{theme} must be manage_bids or maximize_conversions")
        strategy[theme] = value
    split = _split(raw.get("budget_split"), "budget_split") if raw.get("budget_split") is not None else dict(DEFAULT_SPLIT)
    markets, names, countries_seen = [], set(), {}
    for i, mk in enumerate(raw.get("markets") or []):
        mk = _mapping(mk, f"markets[{i}]", {"name", "countries", "daily_budget", "keywords", "target_cpa", "budget_split"})
        mname = str(mk.get("name") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,30}", mname) or mname in names:
            raise AdsError(f"markets[{i}].name must be unique, 1-30 letters, digits, _ or -")
        names.add(mname)
        codes = mk.get("countries")
        if not isinstance(codes, list) or not codes or not all(isinstance(c, str) and re.fullmatch(r"[A-Z]{2}", c) for c in codes):
            raise AdsError(f"markets[{i}].countries must be ISO two-letter uppercase codes such as US")
        for c in codes:
            if c in countries_seen:
                raise AdsError(f"{c} is in markets {countries_seen[c]} and {mname}; the campaigns would bid against each other")
            countries_seen[c] = mname
        if "CN" in codes:
            raise AdsError("Mainland China needs Apple's business and app approval in the Apple Ads website first; this kit does not create CN campaigns")
        if "FR" in codes and raw.get("owns_app_and_account") is not True:
            raise AdsError("France (Sapin law): only an advertiser who owns both the app and the Apple Ads account may target FR; set owns_app_and_account: true if that is you")
        if "FR" in codes and not isinstance(raw.get("french_business"), bool):
            raise AdsError("France (Sapin law): Apple asks every FR campaign whether the advertiser is a French business; "
                           "set french_business: true or false")
        # A market may bring its own keywords (its language), target CPA (its prices) and budget split; else the top level's.
        mkw, mneg = (_keyword_sets(mk["keywords"], f"markets[{i}].keywords") if mk.get("keywords") is not None
                     else (keywords, negatives))
        markets.append({"name": mname, "countries": sorted(set(codes)),
                        "daily_budget": money(mk.get("daily_budget"), f"markets[{i}].daily_budget"),
                        "keywords": mkw, "negatives": mneg,
                        "target_cpa": money(mk["target_cpa"], f"markets[{i}].target_cpa") if mk.get("target_cpa") is not None else target,
                        "split": _split(mk["budget_split"], f"markets[{i}].budget_split") if mk.get("budget_split") is not None else split})
    if not markets:
        raise AdsError("Add at least one market")
    ctype = raw.get("customer_type", "all")
    if ctype not in ("all", "new", "returning", "other_apps"):
        raise AdsError("customer_type must be all, new, returning or other_apps")
    others = [str(x) for x in raw.get("other_app_ids") or []]
    if ctype == "other_apps" and (not others or not all(re.fullmatch(r"\d{6,12}", x) for x in others)):
        raise AdsError("customer_type other_apps needs other_app_ids (numeric App Store ids of your other apps)")
    cpp = {t: str(v) for t, v in _mapping(raw.get("custom_product_pages") or {}, "custom_product_pages", THEMES).items()}
    if cap < MIN_BID:
        raise AdsError(f"max_bid must be at least {MIN_BID}")
    return {"adam_id": adam, "app_name": name, "currency": currency, "target_cpa": target, "max_bid": cap,
            "expected_cr": cr, "keywords": keywords, "negatives": negatives, "strategy": strategy, "split": split,
            "markets": markets, "customer_type": ctype, "other_app_ids": others, "cpp": cpp,
            "owns_app_and_account": raw.get("owns_app_and_account") is True,
            "french_business": raw.get("french_business")}


# ------------------------------------------------------------------------------------------------ structure
def campaign_name(cfg, theme, market):
    return SEP.join((cfg["app_name"], theme.capitalize(), market))


def theme_of(name):
    parts = (name or "").split(SEP)
    return parts[1].lower() if len(parts) == 3 and parts[1].lower() in THEMES else None


def market_of(name):
    parts = (name or "").split(SEP)
    return parts[2] if len(parts) == 3 else None


def start_bid(cfg, theme, factor=Decimal(1), target=None):
    bid = cents((target if target is not None else cfg["target_cpa"]) * Decimal(str(cfg["expected_cr"][theme])) * factor)
    return max(MIN_BID, min(bid, cfg["max_bid"]))


def targeting(cfg):
    if cfg["customer_type"] == "new":
        return {"appDownloader": {"exclude": [cfg["adam_id"]]}}
    if cfg["customer_type"] == "returning":
        return {"appDownloader": {"include": [cfg["adam_id"]]}}
    if cfg["customer_type"] == "other_apps":
        return {"appDownloader": {"include": cfg["other_app_ids"]}}
    return None


def build_structure(cfg):
    """The campaigns the yaml asks for: Apple's Brand / Category / Competitor / Discovery structure per market."""
    campaigns, manual = [], []
    for mk in cfg["markets"]:
        kws, negs, T = mk.get("keywords", cfg["keywords"]), mk.get("negatives", cfg["negatives"]), mk.get("target_cpa", cfg["target_cpa"])
        split = mk.get("split", cfg["split"])
        exact_all = [t for theme in THEMES[:3] for t in kws[theme]]
        for theme in THEMES:
            if theme != "discovery" and not kws[theme]:
                continue
            budget = cents(mk["daily_budget"] * Decimal(str(split[theme])))
            if budget <= 0:
                continue
            name = campaign_name(cfg, theme, mk["name"])
            if cfg["strategy"][theme] == "maximize_conversions":
                manual.append({"campaign": name, "countries": mk["countries"], "daily_budget": budget,
                               "target_cpa": T, "keywords": kws.get(theme, [])})
                continue
            groups = []
            if theme == "discovery":
                bid = start_bid(cfg, "discovery", target=T)
                if exact_all:
                    groups.append({"name": "Broad", "search_match": False, "bid": bid,
                                   "keywords": [{"text": t, "match": "BROAD"} for t in exact_all]})
                groups.append({"name": "Search Match", "search_match": True,
                               "bid": max(MIN_BID, cents(bid * SEARCH_MATCH_FACTOR)), "keywords": []})
                negatives = exact_all + negs
            else:
                groups.append({"name": "Exact", "search_match": False, "bid": start_bid(cfg, theme, target=T),
                               "keywords": [{"text": t, "match": "EXACT"} for t in kws[theme]]})
                negatives = list(negs)
            for g in groups:
                if g["bid"] >= budget:
                    raise AdsError(f"{name}: the starting bid {g['bid']} must be lower than its daily budget {budget}; "
                                   "raise the market budget or this theme's budget_split")
                if len(g["keywords"]) > MAX_KEYWORDS_PER_AD_GROUP:
                    raise AdsError(f"{name}: more than {MAX_KEYWORDS_PER_AD_GROUP} keywords in one ad group")
            if sum(len(g["keywords"]) for g in groups) + len(negatives) > MAX_KEYWORDS_PER_CAMPAIGN:
                raise AdsError(f"{name}: more than {MAX_KEYWORDS_PER_CAMPAIGN} keywords and negatives in one campaign")
            campaigns.append({"name": name, "theme": theme, "market": mk["name"], "countries": mk["countries"],
                              "daily_budget": budget, "ad_groups": groups,
                              "negatives": [{"text": t, "match": "EXACT"} for t in negatives],
                              "cpp": cfg["cpp"].get(theme)})
    return campaigns, manual


def money_summary(campaigns, manual):
    daily = sum((c["daily_budget"] for c in campaigns), Decimal(0)) + sum((x["daily_budget"] for x in manual), Decimal(0))
    return cents(daily), cents(daily * MONTH_DAYS)


# ------------------------------------------------------------------------------------------------ auth + client
@dataclasses.dataclass
class Credentials:
    client_id: str
    team_id: str
    key_id: str
    key_path: pathlib.Path
    ad_account_id: str


def resolve_credentials(kit=None, env=None):
    env = os.environ if env is None else env
    conf = {}
    if kit and (pathlib.Path(kit) / "connect.yaml").is_file():
        conf = (yaml.safe_load((pathlib.Path(kit) / "connect.yaml").read_text()) or {}).get("apple_ads") or {}
    get = lambda key, var: env.get(var) or conf.get(key)  # noqa: E731
    values = {"client_id": get("client_id", "APPLE_ADS_CLIENT_ID"), "team_id": get("team_id", "APPLE_ADS_TEAM_ID"),
              "key_id": get("key_id", "APPLE_ADS_KEY_ID"), "key_path": get("key_path", "APPLE_ADS_KEY_PATH"),
              "ad_account_id": get("ad_account_id", "APPLE_ADS_AD_ACCOUNT_ID")}
    missing = [k for k, v in values.items() if not v]
    if missing:
        raise asc_api.ConfigError("Apple Ads API credentials missing: " + ", ".join(missing) +
                                  ". Set connect.yaml apple_ads: {client_id, team_id, key_id, key_path, ad_account_id} "
                                  "or the APPLE_ADS_* variables; see references/apple-ads.md 'API access'.")
    path = pathlib.Path(str(values["key_path"])).expanduser()
    if not path.is_absolute() and kit and (pathlib.Path(kit) / path).is_file():
        path = pathlib.Path(kit) / path
    if not path.is_file():
        raise asc_api.ConfigError("The Apple Ads private key file (key_path) was not found")
    if not re.fullmatch(r"\d+", str(values["ad_account_id"])):
        raise asc_api.ConfigError("ad_account_id must be the numeric ad account id (Apple Ads website account menu, or GET /v1/acls)")
    return Credentials(str(values["client_id"]), str(values["team_id"]), str(values["key_id"]), path,
                       str(values["ad_account_id"]))


def client_secret(creds, now=None, use_openssl=False):
    """ES256 JWT: kid = keyId, iss = teamId, sub = clientId, aud = https://appleid.apple.com, exp < 180 days."""
    now = int(now if now is not None else time.time())
    header = {"alg": "ES256", "kid": creds.key_id}
    payload = {"sub": creds.client_id, "aud": AUDIENCE, "iat": now, "exp": now + SECRET_LIFETIME, "iss": creds.team_id}
    signing = (asc_api.b64url(jsonlib.dumps(header, separators=(",", ":")).encode()) + "." +
               asc_api.b64url(jsonlib.dumps(payload, separators=(",", ":")).encode()))
    sig = asc_api.der_to_raw(asc_api._sign_der(creds.key_path, signing.encode(), use_openssl))
    return signing + "." + asc_api.b64url(sig)


class AccessToken:
    """OAuth 2 client credentials: the client secret is exchanged for a one-hour access token, renewed early."""

    def __init__(self, creds, transport, now=time.time, secret=client_secret):
        self.creds, self.transport, self.now, self.secret = creds, transport, now, secret
        self._token, self._exp = None, 0

    def __call__(self):
        if self._token and self.now() < self._exp - 120:
            return self._token
        body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": self.creds.client_id,
                                       "client_secret": self.secret(self.creds), "scope": "searchadsorg"}).encode()
        status, _, raw = self.transport("POST", TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded",
                                                            "Accept": "application/json"}, body)
        try:
            doc = jsonlib.loads(raw or b"{}")
        except ValueError:
            doc = {}
        if status != 200 or not doc.get("access_token"):
            # Apple answers invalid_client for a wrong client id / team id / key id or an unreadable key.
            raise asc_api.ConfigError(f"Apple refused the Apple Ads credentials (HTTP {status} {doc.get('error', '')}); "
                                      "check client_id, team_id, key_id and that the public key is the one uploaded")
        self._token, self._exp = doc["access_token"], self.now() + int(doc.get("expires_in", 3600))
        return self._token

    def __repr__(self):
        return "AccessToken(<hidden>)"


def is_read(method, path):
    return method == "GET" or path.split("?")[0].endswith("/query")


class Client:
    def __init__(self, token, ad_account_id, transport=None, dry_run=False, sleep=time.sleep, max_retries=5, log=print):
        self.token, self.account = token, str(ad_account_id)
        self.transport = transport or asc_api.urllib_transport
        self.dry_run, self.sleep, self.max_retries, self.log = dry_run, sleep, max_retries, log
        self.recorded, self.sent, self._n = [], [], 0

    def request(self, method, path, json=None, scoped=True):
        url = BASE_URL + path
        if not asc_api.same_origin(url, BASE_URL):
            raise AdsError("refused to send the Apple Ads token outside " + BASE_URL)
        if not is_read(method, path) and self.dry_run:
            self.recorded.append({"method": method, "path": path, "json": json})
            self._n += 1
            return {"result": {**(json or {}), "id": -self._n, "status": (json or {}).get("status", "PAUSED")}}
        headers = {"Authorization": "Bearer " + self.token(), "Accept": "application/json"}
        if scoped:
            headers["X-AP-Context"] = f"adAccountId={self.account}"
        body = None
        if json is not None:
            body = jsonlib.dumps(json).encode()
            headers["Content-Type"] = "application/json"
        attempt = 0
        while True:
            status, rh, raw = self.transport(method, url, headers, body)
            rh = {str(k).lower(): v for k, v in (rh or {}).items()}
            retry = status == 429 or (status in (500, 502, 503, 504) and (is_read(method, path) or method == "PUT"))
            if retry and attempt < self.max_retries:
                try:
                    wait = float(rh.get("retry-after") or rh.get("ratelimit-reset"))
                except (TypeError, ValueError):
                    wait = min(2 ** (attempt + 1), 60)
                self.log(f"Apple Ads answered {status}; waiting {wait:g} s")
                self.sleep(wait)
                attempt += 1
                continue
            break
        try:
            doc = jsonlib.loads(raw) if raw else {}
        except ValueError:
            doc = {}
        if status >= 400:
            raise ApiError(status, (doc or {}).get("error"), method, path)
        if not is_read(method, path):
            self.sent.append((method, path))
        try:
            remaining = int(rh.get("ratelimit-remaining"))
            if remaining <= 2:
                self.sleep(float(rh.get("ratelimit-reset") or 5))
        except (TypeError, ValueError):
            pass
        return doc

    def get(self, path, scoped=True):
        return (self.request("GET", path, scoped=scoped) or {}).get("result")

    def query(self, path, body=None, page=500):
        """Every row of a /query endpoint, following offset pagination."""
        body, rows, offset = dict(body or {}), [], 0
        while True:
            body["pagination"] = {"offset": offset, "pageSize": page, "fetchTotalCount": True}
            doc = self.request("POST", path, body) or {}
            result = doc.get("result")
            chunk = result.get("rows", []) if isinstance(result, dict) else (result or [])
            rows += chunk
            total = (doc.get("pagination") or {}).get("totalCount")
            offset += len(chunk)
            if not chunk or len(chunk) < page or (total is not None and offset >= total):
                return rows

    def post(self, path, json):
        return (self.request("POST", path, json) or {}).get("result")

    def put(self, path, json):
        return (self.request("PUT", path, json) or {}).get("result")

    def bulk(self, path, items):
        """Bulk create/update in chunks, all-or-nothing per chunk; returns the per-item results in order."""
        out = []
        for i in range(0, len(items), BULK_CHUNK):
            chunk = items[i:i + BULK_CHUNK]
            doc = self.request("POST", path, {"allowPartialSuccess": False,
                                              "items": [{"correlationId": n, "data": d} for n, d in enumerate(chunk)]})
            results = (doc or {}).get("result") or []
            if self.dry_run:
                results = [{"correlationId": n, "success": True, "result": {**d, "id": -(i + n + 1)}} for n, d in enumerate(chunk)]
            if (doc or {}).get("error") or len(results) != len(chunk) or not all(r.get("success") for r in results):
                bad = [r for r in results if not r.get("success")]
                raise ApiError(200, (doc or {}).get("error") or (bad[0].get("error") if bad else {"message": "incomplete bulk result"}),
                               "POST", path)
            out += sorted(results, key=lambda r: r.get("correlationId", 0))
        return out


def make_client(kit, dry_run=False, transport=None):
    creds = resolve_credentials(kit)
    transport = transport or asc_api.urllib_transport
    return Client(AccessToken(creds, transport), creds.ad_account_id, transport=transport, dry_run=dry_run)


# ------------------------------------------------------------------------------------------------ live reads
def eq(field, value):
    return {"field": field, "operator": "EQUALS", "value": value}


def read_account(client):
    acct = client.get(f"/v1/ad-accounts/{client.account}") or {}
    return {"id": str(acct.get("id", client.account)), "currency": acct.get("currency"),
            "time_zone": acct.get("timeZone"), "product_features": acct.get("productFeatures") or []}


def app_campaigns(client, adam_id):
    rows = client.query("/v1/campaigns/query", {"filters": [eq("promotedObjectId", str(adam_id))]})
    return [{"id": r.get("id"), "name": r.get("name"), "status": r.get("status"),
             "daily_budget": format(amount_of((r.get("dailyBudget") or {}).get("value")), "f")}
            for r in rows if str(r.get("promotedObjectId")) == str(adam_id) and not r.get("deleted")]


def check_account(cfg, account):
    if account["currency"] and account["currency"] != cfg["currency"]:
        raise AdsError(f"The ad account pays in {account['currency']}, apple-ads.yaml says {cfg['currency']}; "
                       "fix the yaml (an account currency never changes)")
    if account["product_features"] and "APPSTORE_APP_MANUAL" not in account["product_features"]:
        raise AdsError("This ad account cannot run App Store campaigns (no APPSTORE_APP_MANUAL); pick the App Store ad account")


# ------------------------------------------------------------------------------------------------ plan
class Kit:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        if not self.path.is_dir():
            raise AdsError(f"No kit folder at {self.path}")

    def config(self):
        p = self.path / "apple-ads.yaml"
        if not p.is_file():
            raise AdsError("No apple-ads.yaml; copy templates/apple-ads.example.yaml into KIT first")
        return validate(yaml.safe_load(p.read_text()))

    def fingerprint(self, account_id):
        return digest({"yaml": (self.path / "apple-ads.yaml").read_text(), "account": str(account_id)})

    def write(self, name, value):
        text = value if isinstance(value, str) else jsonlib.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n"
        (self.path / name).write_text(text)

    def read_json(self, name, default=None):
        p = self.path / name
        return jsonlib.loads(p.read_text()) if p.is_file() else default


def build_plan(kit, cfg, account, existing, today=None, live=None):
    campaigns, manual = build_structure(cfg)
    have = {c["name"]: c["id"] for c in existing}
    live = live or {}
    done, kit_ids = set(live.get("done") or []), live.get("ids") or {}
    cur, ops = cfg["currency"], []
    # A campaign this kit started but did not finish (an apply that stopped half-way) is completed, not skipped.
    resume = {c["name"] for c in campaigns if c["name"] in have and kit_ids.get(f"campaign:{c['name']}") == have[c["name"]]}
    skipped = sorted(c["name"] for c in campaigns if c["name"] in have and c["name"] not in resume)
    create = [c for c in campaigns if c["name"] not in have or c["name"] in resume]
    # Search results campaigns serve the app's default product page on their own: Apple's API refuses Ad objects
    # there (AD_CAMPAIGN_SUPPLY_SOURCES_NOT_SUPPORTED, live 2026-11-10), so the kit creates no creatives or ads.
    for c in create:
        cref = f"campaign:{c['name']}"
        body = {"name": c["name"], "adAccountId": int(account["id"]), "promotedObjectType": "APPSTORE_APP",
                "promotedObjectId": cfg["adam_id"], "billingEvent": "TAPS", "status": "PAUSED",
                "dailyBudget": {"value": m(c["daily_budget"], cur)},
                "targeting": {"countryOrRegion": {"include": c["countries"]}, "supplySource": {"include": ["APPSTORE"]},
                              "supplyPlacement": {"include": ["APPSTORE_SEARCH_RESULTS"]}},
                "bidStrategy": {"bidStrategyType": "MANUAL_CPT", "bidStrategyGoal": "TAP"}}
        if "FR" in c["countries"]:
            # Live API (2026-11-10): CAMPAIGN_SAPIN_LAW refuses NOT_AGENT (Apple's own example); it takes the
            # French-business answer. AGENT / NOT_AGENT belong to the organisation-level question.
            body["regulationResponses"] = [{"regulationType": "CAMPAIGN_SAPIN_LAW",
                                            "responseValue": "FRENCH_BUSINESS" if cfg["french_business"] else "NOT_FRENCH_BUSINESS"}]
        ops.append({"op": "campaign", "ref": cref, "body": body})
        if c["negatives"]:
            ops.append({"op": "negatives", "ref": f"{cref}/negatives", "items": [
                {"campaignId": cref, "text": n["text"], "matchType": n["match"], "status": "ENABLED"} for n in c["negatives"]]})
        for g in c["ad_groups"]:
            gref = f"{cref}/{g['name']}"
            gbody = {"name": g["name"], "campaignId": cref, "pricingModel": "CPT", "status": "ENABLED",
                     "automatedKeywordsOptIn": g["search_match"],
                     "bidStrategy": {"bidStrategyType": "MANUAL_CPT", "bidStrategyGoal": "TAP", "bid": m(g["bid"], cur)}}
            if targeting(cfg):
                gbody["targeting"] = targeting(cfg)
            ops.append({"op": "adgroup", "ref": gref, "body": gbody})
            if g["keywords"]:
                ops.append({"op": "keywords", "ref": f"{gref}/keywords", "items": [
                    {"adGroupId": gref, "text": k["text"], "matchType": k["match"], "status": "ENABLED"} for k in g["keywords"]]})
    ops = [o for o in ops if o["ref"] not in done]
    finished = {c["name"] for c in create if c["name"] in resume and not any(
        o["ref"].startswith(f"campaign:{c['name']}") for o in ops)}
    create = [c for c in create if c["name"] not in finished]
    skipped = sorted(set(skipped) | finished)
    warnings = []
    if resume - finished:
        warnings.append("Finishing what an earlier apply left half-built: " + ", ".join(sorted(resume - finished)))
    cpps = sorted({f"{c['name']}: {c['cpp']}" for c in create if c["cpp"]})
    if cpps:
        warnings.append("Custom product page ad variations are set in the Apple Ads website (ad group › Ads › Create Ad); "
                        "the API does not take them for search results: " + "; ".join(cpps))
    if cfg["customer_type"] != "all":
        warnings.append("Customer type is not 'all': Apple excludes users with Personalized Ads off from refined audiences.")
    if skipped:
        warnings.append("Already in the account, left untouched: " + ", ".join(skipped))
    daily, monthly = money_summary(create, manual)
    return {"schema": PLAN_VERSION, "day": (today or dt.date.today()).isoformat(),
            "input_hash": kit.fingerprint(account["id"]), "account": account, "existing": sorted(have),
            "campaigns": [{**c, "daily_budget": format(c["daily_budget"], "f"),
                           "ad_groups": [{**g, "bid": format(g["bid"], "f")} for g in c["ad_groups"]]} for c in create],
            "manual_steps": [{**x, "daily_budget": format(x["daily_budget"], "f"), "target_cpa": format(x["target_cpa"], "f")}
                             for x in manual],
            "daily_total": format(daily, "f"), "monthly_max": format(monthly, "f"), "currency": cur,
            "warnings": warnings, "ops": ops}


def cell(text):
    """A value safe inside a Markdown table cell (campaign names contain '|')."""
    return str(text).replace("|", "\\|")


def render_plan(plan):
    cur = plan["currency"]
    lines = ["# Apple Ads plan", "", f"Ad account {plan['account']['id']} ({cur}). Plan date {plan['day']}.", "",
             f"**Money once switched on:** {plan['daily_total']} {cur} a day in total, at most "
             f"{plan['monthly_max']} {cur} a month (Apple: daily budget × 30.4). Nothing spends until `activate`.", ""]
    lines += [f"- {w}" for w in plan["warnings"]]
    lines += ["", "| Campaign (created PAUSED) | Countries | Daily budget | Ad groups: bid, keywords | Negatives |", "|---|---|---|---|---|"]
    for c in plan["campaigns"]:
        groups = "; ".join(f"{g['name']}: {g['bid']} {cur}, " +
                           (f"{len(g['keywords'])} {g['keywords'][0]['match'].lower()}" if g["keywords"] else "Search Match")
                           for g in c["ad_groups"])
        lines.append(f"| {cell(c['name'])} | {', '.join(c['countries'])} | {c['daily_budget']} {cur} | {groups} | {len(c['negatives'])} exact |")
    for c in plan["campaigns"]:
        for g in c["ad_groups"]:
            if g["keywords"]:
                lines.append(f"\n{c['name']} / {g['name']}: " + ", ".join(k["text"] for k in g["keywords"]))
    if plan["manual_steps"]:
        lines += ["", "## Maximize Conversions: set up in the Apple Ads website", "",
                  "Apple's API documents no field for the target CPA, so the kit does not guess it. In ads.apple.com: "
                  "Create Campaign → your app → Search results → Maximize Conversions; status Pause.", ""]
        for x in plan["manual_steps"]:
            lines.append(f"- {x['campaign']}: countries {', '.join(x['countries'])}, daily budget {x['daily_budget']} {cur}, "
                         f"target CPA {x['target_cpa']} {cur}" + (f", keywords in an extra ad group: {', '.join(x['keywords'])}" if x["keywords"] else ""))
    lines += ["", f"{len(plan['ops'])} API step(s). Show this plan to the owner before `apply KIT --yes`.", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------------ apply
def _resolve(value, ids):
    if isinstance(value, str) and value in ids:
        return ids[value]
    if isinstance(value, str) and re.match(r"^(campaign|creative):", value):
        raise AdsError(f"internal: {value} was not created before it was needed")
    return value


def _fill(body, ids):
    return {k: _resolve(v, ids) for k, v in body.items()}


def record_live(kit, live):
    kit.write("apple-ads-live.json", live)


def apply_plan(client, kit, cfg):
    plan = kit.read_json("apple-ads-plan.json")
    if not plan:
        raise AdsError("No apple-ads-plan.json; run plan KIT and show apple-ads-plan.md first")
    account = read_account(client)
    if plan.get("schema") != PLAN_VERSION or plan.get("day") != dt.date.today().isoformat() or \
            plan.get("input_hash") != kit.fingerprint(account["id"]):
        raise AdsError("apple-ads.yaml, the account or the date changed since the plan; run plan again and review it")
    check_account(cfg, account)
    live = kit.read_json("apple-ads-live.json", {"created": []})
    fresh = build_plan(kit, cfg, account, app_campaigns(client, cfg["adam_id"]), live=live)
    if fresh["ops"] != plan["ops"]:
        raise AdsError("The account changed since the plan (a campaign was added or removed); run plan again")
    ids, made = dict(live.get("ids") or {}), []
    try:
        _run_ops(client, kit, plan, live, ids, made)
    except AdsError as error:
        if made:
            raise AdsError(f"{error}\nAlready created, all PAUSED (ids in apple-ads-live.json): {', '.join(made)}. "
                           "Run plan again: it leaves these alone, so finish or pause them in the Apple Ads website.") from None
        raise
    if client.dry_run:
        print(f"dry run: {len(client.recorded)} request(s) would be sent, none were")
        for r in client.recorded:
            print(f"  would send {r['method']} {r['path']}")
        return 0
    print(f"Created {len(plan['campaigns'])} campaign(s), all PAUSED. Nothing spends until "
          "activate KIT --campaign ID --yes. Ids are in apple-ads-live.json.")
    return 0


def _done(client, kit, live, ref, new_id=None):
    """Record a finished step so a rerun after a failure completes the rest instead of repeating or skipping it."""
    if client.dry_run:
        return
    live.setdefault("done", []).append(ref)
    if new_id is not None:
        live.setdefault("ids", {})[ref] = new_id
    record_live(kit, live)


def _run_ops(client, kit, plan, live, ids, made):
    for op in plan["ops"]:
        if op["op"] in ("keywords", "negatives"):
            path = "/v1/keywords/bulk-create" if op["op"] == "keywords" else "/v1/negative-keywords/bulk-create"
            client.bulk(path, [_fill(i, ids) for i in op["items"]])
            _done(client, kit, live, op["ref"])
            continue
        path = {"campaign": "/v1/campaigns", "adgroup": "/v1/adgroups"}[op["op"]]
        body = _fill(op["body"], ids)
        if op["op"] == "adgroup":
            # Apple requires startTime on ad groups (live API, 2026-11-10); "now" is safe because the campaign is paused.
            body["startTime"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000")
        result = client.post(path, body) or {}
        if result.get("id") is None:
            raise AdsError(f"Apple returned no id for {op['ref']}; check status before trying again")
        ids[op["ref"]] = result["id"]
        if op["op"] == "campaign":
            if not client.dry_run:
                live["created"].append({"id": result["id"], "name": op["body"]["name"], "day": plan["day"]})
                made.append(op["body"]["name"])
                _done(client, kit, live, op["ref"], result["id"])
                # Never trust the request body: re-read and force PAUSED if Apple says anything else.
                status = (client.get(f"/v1/campaigns/{result['id']}") or {}).get("status")
                if status != "PAUSED":
                    client.put(f"/v1/campaigns/{result['id']}", {"status": "PAUSED"})
                    raise AdsError(f"{op['body']['name']} came back {status}; it was paused again. Stopped; run status")
        else:
            _done(client, kit, live, op["ref"], result["id"])


def set_status(client, kit, cfg, campaign_ids, status):
    mine = {str(c["id"]): c for c in app_campaigns(client, cfg["adam_id"])}
    created = {str(c["id"]) for c in (kit.read_json("apple-ads-live.json", {"created": []})["created"])}
    for cid in campaign_ids:
        if cid not in mine:
            raise AdsError(f"Campaign {cid} does not promote this app; nothing changed")
        if status == "ENABLED" and cid not in created:
            raise AdsError(f"Campaign {cid} was not created by this kit; switch it on in the Apple Ads website if you mean to")
    for cid in campaign_ids:
        c = mine[cid]
        if status == "ENABLED":
            print(f"Starting {c['name']}: {c['daily_budget']} {cfg['currency']} a day, at most "
                  f"{cents(Decimal(c['daily_budget']) * MONTH_DAYS)} {cfg['currency']} a month")
        client.put(f"/v1/campaigns/{cid}", {"status": status})
        if not client.dry_run:
            now = (client.get(f"/v1/campaigns/{cid}") or {}).get("status")
            if now != status:
                raise AdsError(f"{c['name']} reads back {now}, not {status}; check the Apple Ads website")
    print("dry run: no writes sent" if client.dry_run else f"{len(campaign_ids)} campaign(s) now {status}"
          + (" (paused ads can still show for a few hours)" if status == "PAUSED" else ""))
    return 0


# ------------------------------------------------------------------------------------------------ report
def metrics(row):
    t = row.get("totalMetrics") or {}
    spend = amount_of(t.get("localSpend"))
    installs = int(t.get("tapInstalls") or 0)
    return {"impressions": int(t.get("impressions") or 0), "taps": int(t.get("taps") or 0), "installs": installs,
            "spend": format(cents(spend), "f"), "cpa": format(cents(spend / installs), "f") if installs else None}


def collect(client, cfg, days, today=None):
    today = today or dt.date.today()
    end = today - dt.timedelta(days=1)
    start = end - dt.timedelta(days=days - 1)
    span = {"start": start.isoformat(), "end": end.isoformat(), "timeZone": "ORTZ"}
    if days > 1:
        span["granularity"] = "DAILY"
    out = {"from": span["start"], "to": span["end"], "days": days, "currency": cfg["currency"], "campaigns": []}
    # The campaigns report refuses a campaignId filter (INVALID_FIELD_ATTRIBUTE) and lists only campaigns with
    # activity, so it is read once per app; the keyword and search term reports require the campaignId filter.
    by_id = {str((r.get("metadata") or {}).get("id")): r for r in client.query(
        "/v1/reports/apps/campaigns/query", {"timeRange": span, "filters": [eq("promotedObjectId", str(cfg["adam_id"]))]})}
    for c in app_campaigns(client, cfg["adam_id"]):
        f = {"timeRange": span, "filters": [eq("campaignId", str(c["id"]))]}
        crow = [by_id[str(c["id"])]] if str(c["id"]) in by_id else []
        bids = {r.get("id"): format(amount_of(r.get("bid")), "f") if r.get("bid") else None
                for r in client.query("/v1/keywords/query", {"filters": [eq("campaignId", c["id"])]})}
        kws = [{"id": (r.get("metadata") or {}).get("id"), "text": (r.get("metadata") or {}).get("text"),
                "match": (r.get("metadata") or {}).get("matchType"), "ad_group_id": (r.get("metadata") or {}).get("adGroupId"),
                "status": (r.get("metadata") or {}).get("status"), "bid": bids.get((r.get("metadata") or {}).get("id")),
                **metrics(r)} for r in client.query("/v1/reports/apps/keywords/query", f)]
        terms = [{"text": (r.get("metadata") or {}).get("searchTermText"),
                  "source": (r.get("metadata") or {}).get("searchTermSource"),
                  "ad_group_id": (r.get("metadata") or {}).get("adGroupId"),
                  "keyword": ((r.get("metadata") or {}).get("keyword") or {}).get("text"), **metrics(r)}
                 for r in client.query("/v1/reports/apps/searchterms/query", f)]
        out["campaigns"].append({**c, "theme": theme_of(c["name"]), "market": market_of(c["name"]),
                                 "totals": metrics(crow[0]) if crow else metrics({}), "keywords": kws, "search_terms": terms})
    return out


def render_report(rep):
    cur = rep["currency"]
    lines = [f"# Apple Ads report {rep['from']} to {rep['to']}", "",
             "| Campaign | Status | Budget/day | Spend | Impr. | Taps | TTR | Installs | CR | CPA |", "|---|---|---|---|---|---|---|---|---|---|"]
    for c in rep["campaigns"]:
        t = c["totals"]
        ttr = f"{t['taps'] / t['impressions']:.1%}" if t["impressions"] else "-"
        cr = f"{t['installs'] / t['taps']:.0%}" if t["taps"] else "-"
        lines.append(f"| {cell(c['name'])} | {c['status']} | {c['daily_budget']} | {t['spend']} {cur} | {t['impressions']} | {t['taps']} | "
                     f"{ttr} | {t['installs']} | {cr} | {t['cpa'] or '-'} |")
    for c in rep["campaigns"]:
        top = sorted(c["keywords"], key=lambda k: -Decimal(k["spend"]))[:15]
        if top:
            lines += ["", f"## {c['name']}: keywords by spend", "", "| Keyword | Match | Bid | Spend | Taps | Installs | CPA |", "|---|---|---|---|---|---|---|"]
            lines += [f"| {cell(k['text'])} | {k['match']} | {k['bid'] or 'group'} | {k['spend']} | {k['taps']} | {k['installs']} | {k['cpa'] or '-'} |" for k in top]
    lines += ["", "Installs are tap-through (30-day window). Search terms under 10 impressions a day are hidden by Apple.", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------------ optimise
def _pid(*parts):
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:10]


def propose(rep, cfg, ad_group_bids=None):
    """Proposal-only rules from references/apple-ads.md §4. Nothing here writes."""
    cap, cur, out = cfg["max_bid"], cfg["currency"], []
    market_T = {mk["name"]: mk.get("target_cpa", cfg["target_cpa"]) for mk in cfg.get("markets") or []}
    ad_group_bids = ad_group_bids or {}
    exact_texts = {}
    for c in rep["campaigns"]:
        exact_texts.setdefault(c["market"], set()).update(k["text"].lower() for k in c["keywords"] if k["match"] == "EXACT")
    by_market = {(c["theme"], c["market"]): c for c in rep["campaigns"]}
    for c in rep["campaigns"]:
        budget = Decimal(c["daily_budget"] or "0")
        T = market_T.get(c["market"], cfg["target_cpa"])
        t = c["totals"]
        camp_cr = t["installs"] / t["taps"] if t["taps"] else None
        for k in c["keywords"]:
            if k["status"] != "ENABLED":
                continue
            spend, inst = Decimal(k["spend"]), k["installs"]
            bid = Decimal(k["bid"]) if k["bid"] else ad_group_bids.get(k["ad_group_id"])
            base = {"campaign_id": c["id"], "campaign": c["name"], "keyword_id": k["id"], "keyword": k["text"], "match": k["match"],
                    "ad_group_id": k["ad_group_id"]}
            if inst == 0 and spend > 2 * T:
                out.append({**base, "kind": "pause_keyword", "from": "ENABLED", "to": "PAUSED",
                            "reason": f"spent {k['spend']} {cur} (over 2 × target CPA) with no installs"})
                continue
            if bid is None:
                continue
            new, why = None, None
            if inst >= 5 and Decimal(k["cpa"]) < T * Decimal("0.8") and bid < cap:
                new, why = bid * Decimal("1.15"), f"CPA {k['cpa']} is under 80 % of target {T}: room to win more auctions"
            elif inst >= 5 and Decimal(k["cpa"]) > T * Decimal("1.3"):
                new, why = bid * Decimal("0.8"), f"CPA {k['cpa']} is over 130 % of target {T}"
            elif k["taps"] >= 30 and camp_cr and inst / k["taps"] < camp_cr / 2:
                new, why = bid * Decimal("0.85"), f"conversion {inst}/{k['taps']} is under half the campaign's; check relevance"
            if new is not None:
                new = max(MIN_BID, min(cents(new), cap, budget - Decimal("0.01")))
                if new != bid:
                    out.append({**base, "kind": "set_bid", "from": format(bid, "f"), "to": format(new, "f"), "reason": why})
        if c["theme"] == "discovery":
            terms = {}
            for s in c["search_terms"]:      # one term can show in both Discovery ad groups: judge the campaign total
                text = " ".join((s["text"] or "").split())
                if not text or text.lower() == "other":
                    continue
                agg = terms.setdefault(text.lower(), {"text": text, "spend": Decimal(0), "installs": 0, "sources": set()})
                agg["spend"] += Decimal(s["spend"])
                agg["installs"] += s["installs"]
                agg["sources"].add(s["source"] or "search")
            for s in terms.values():
                text, spend = s["text"], s["spend"]
                s["cpa"] = format(cents(spend / s["installs"]), "f") if s["installs"] else None
                s["source"] = "/".join(sorted(s["sources"]))
                s["spend"] = format(cents(spend), "f")
                base = {"campaign_id": c["id"], "campaign": c["name"], "term": text}
                if s["installs"] >= 2 and Decimal(s["cpa"]) <= T and text.lower() not in exact_texts.get(c["market"], set()):
                    target = by_market.get(("category", c["market"]))
                    out.append({**base, "kind": "harvest", "to_campaign": target["name"] if target else None,
                                "to_campaign_id": target["id"] if target else None,
                                "bid": format(min(cap, max(MIN_BID, cents(T * Decimal(str(cfg["expected_cr"]["category"]))))), "f"),
                                "reason": f"{s['installs']} installs at {s['cpa']} {cur} via {s['source'] or 'search'}; "
                                          "add as exact (Category) and as an exact negative here"})
                elif s["installs"] == 0 and spend > 2 * T:
                    out.append({**base, "kind": "add_negative", "reason": f"spent {s['spend']} {cur} with no installs"})
        spend, days = Decimal(t["spend"]), Decimal(rep["days"])
        if budget and t["installs"] and spend >= budget * days * Decimal("0.95") and Decimal(t["cpa"]) <= T:
            out.append({"kind": "set_budget", "campaign_id": c["id"], "campaign": c["name"], "from": format(budget, "f"),
                        "to": format(cents(budget * Decimal("1.2")), "f"),
                        "reason": f"spends its whole budget at CPA {t['cpa']} (target {T})"})
        elif budget and t["installs"] and spend > 3 * T and Decimal(t["cpa"]) > T * Decimal("1.5"):
            out.append({"kind": "set_budget", "campaign_id": c["id"], "campaign": c["name"], "from": format(budget, "f"),
                        "to": format(max(MIN_BID * 10, cents(budget * Decimal("0.8"))), "f"),
                        "reason": f"CPA {t['cpa']} is over 150 % of target; cut bids first, then budget"})
    for p in out:
        p["id"] = _pid(p["kind"], p.get("campaign_id"), p.get("keyword_id"), p.get("term"), p.get("to"))
        p["approve"] = False
    return out


def render_proposals(doc):
    lines = ["# Apple Ads proposals", "", f"Data {doc['from']} to {doc['to']}. Nothing has been changed.",
             "To apply: set `\"approve\": true` on the chosen items in apple-ads-proposals.json, then "
             "`apply-proposals KIT --yes` (the same day).", ""]
    if not doc["proposals"]:
        lines.append("No changes proposed: not enough data or everything is within target. Check again in a week.")
    for p in doc["proposals"]:
        what = {"set_bid": f"bid {p.get('from')} → {p.get('to')} on '{p.get('keyword')}'",
                "pause_keyword": f"pause '{p.get('keyword')}'",
                "harvest": f"'{p.get('term')}' → exact in {p.get('to_campaign') or 'a Category campaign (none yet)'} at {p.get('bid')}",
                "add_negative": f"exact negative '{p.get('term')}'",
                "set_budget": f"daily budget {p.get('from')} → {p.get('to')}"}[p["kind"]]
        lines.append(f"- `{p['id']}` {p['campaign']}: {what}. {p['reason']}")
    return "\n".join(lines) + "\n"


def apply_proposals(client, kit, cfg):
    doc = kit.read_json("apple-ads-proposals.json")
    if not doc:
        raise AdsError("No apple-ads-proposals.json; run optimize KIT first")
    if doc.get("day") != dt.date.today().isoformat() or doc.get("input_hash") != kit.fingerprint(client.account):
        raise AdsError("The proposals are from another day or another apple-ads.yaml; run optimize again")
    chosen = [p for p in doc["proposals"] if p.get("approve") is True and not p.get("applied")]
    if not chosen:
        print("No approved proposal is left to apply (\"approve\": true, not yet applied); nothing to do")
        return 0

    def step_done(p, step=None):
        # Progress is saved after every write so a rerun after a failure finishes the rest and repeats nothing.
        if client.dry_run:
            return
        if step:
            p.setdefault("steps", []).append(step)
        else:
            p["applied"] = dt.datetime.now().isoformat(timespec="seconds")
        kit.write("apple-ads-proposals.json", doc)
    mine = {c["id"]: c for c in app_campaigns(client, cfg["adam_id"])}
    cur, cap = cfg["currency"], cfg["max_bid"]
    done = skipped = 0
    for p in chosen:
        if p["campaign_id"] not in mine:
            print(f"skipped {p['id']}: campaign no longer promotes this app")
            skipped += 1
            continue
        if p["kind"] in ("set_bid", "pause_keyword"):
            rows = client.query("/v1/keywords/query", {"filters": [eq("id", p["keyword_id"])]})
            k = rows[0] if rows else {}
            current = amount_of(k.get("bid")) if k.get("bid") else None
            if current is None and p["kind"] == "set_bid":     # keywords without their own bid use the ad group's
                groups = client.query("/v1/adgroups/query", {"filters": [eq("id", k.get("adGroupId") or p.get("ad_group_id"))]})
                bid = ((groups[0].get("bidStrategy") or {}).get("bid")) if groups else None
                current = amount_of(bid) if bid else None
            if not k or (k.get("status") == "PAUSED" and p["kind"] == "set_bid"):
                print(f"skipped {p['id']}: the keyword is gone or paused")
                skipped += 1
                continue
            if p["kind"] == "set_bid" and (current is None or current != Decimal(p["from"]) or Decimal(p["to"]) > cap):
                print(f"skipped {p['id']}: the bid is now {current}, not {p['from']}")
                skipped += 1
                continue
            data = {"id": p["keyword_id"], "bid": m(Decimal(p["to"]), cur)} if p["kind"] == "set_bid" else \
                {"id": p["keyword_id"], "status": "PAUSED"}
            client.bulk("/v1/keywords/bulk-update", [data])
        elif p["kind"] == "add_negative":
            client.bulk("/v1/negative-keywords/bulk-create",
                        [{"campaignId": p["campaign_id"], "text": p["term"], "matchType": "EXACT", "status": "ENABLED"}])
        elif p["kind"] == "harvest":
            if not p.get("to_campaign_id") or p["to_campaign_id"] not in mine:
                print(f"skipped {p['id']}: no Category campaign for this market; add the term to apple-ads.yaml instead")
                skipped += 1
                continue
            groups = client.query("/v1/adgroups/query", {"filters": [eq("campaignId", p["to_campaign_id"])]})
            exact = [g for g in groups if g.get("name") == "Exact" and not g.get("deleted")]
            if len(exact) != 1 or Decimal(p["bid"]) > cap:
                print(f"skipped {p['id']}: the Category campaign has no single 'Exact' ad group")
                skipped += 1
                continue
            # Excluding the term from a running Discovery campaign is only safe when its new home can serve it.
            if mine[p["campaign_id"]]["status"] == "ENABLED" and (
                    mine[p["to_campaign_id"]]["status"] != "ENABLED" or exact[0].get("status") == "PAUSED"):
                print(f"skipped {p['id']}: {mine[p['to_campaign_id']]['name']} (or its Exact ad group) is paused; "
                      "activate it first or the term would stop showing")
                skipped += 1
                continue
            have = [k for k in client.query("/v1/keywords/query", {"filters": [eq("adGroupId", exact[0]["id"])]})
                    if (k.get("text") or "").lower() == p["term"].lower() and k.get("matchType") == "EXACT"
                    and not k.get("deleted")]
            if have and not any(k.get("status") == "ENABLED" for k in have):
                print(f"skipped {p['id']}: '{p['term']}' is in {mine[p['to_campaign_id']]['name']} but paused; "
                      "enable it there first or Discovery would stop showing the term")
                skipped += 1
                continue
            if not have and "keyword" in p.get("steps", []) and not client.dry_run:
                raise AdsError(f"'{p['term']}' was created for {p['id']} but is no longer in the Exact ad group; run optimize again")
            if not have:
                client.bulk("/v1/keywords/bulk-create", [{"adGroupId": exact[0]["id"], "text": p["term"],
                                                          "matchType": "EXACT", "bid": m(Decimal(p["bid"]), cur),
                                                          "status": "ENABLED"}])
                step_done(p, "keyword")
            client.bulk("/v1/negative-keywords/bulk-create",
                        [{"campaignId": p["campaign_id"], "text": p["term"], "matchType": "EXACT", "status": "ENABLED"}])
        elif p["kind"] == "set_budget":
            now = mine[p["campaign_id"]]["daily_budget"]
            if Decimal(now) != Decimal(p["from"]):
                print(f"skipped {p['id']}: the budget is now {now}, not {p['from']}")
                skipped += 1
                continue
            client.put(f"/v1/campaigns/{p['campaign_id']}", {"dailyBudget": {"value": m(Decimal(p["to"]), cur)}})
        step_done(p)
        done += 1
        print(f"{'would apply' if client.dry_run else 'applied'} {p['id']} ({p['kind']}, {p['campaign']})")
    print(f"{done} applied, {skipped} skipped" + (" (dry run: nothing sent)" if client.dry_run else ""))
    return 0


# ------------------------------------------------------------------------------------------------ main
def main(argv=None, client=None, today=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("check", "status", "plan", "apply", "activate", "pause", "report",
                                            "optimize", "apply-proposals"))
    parser.add_argument("kit")
    parser.add_argument("--campaign", action="append", default=[])
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    writes = args.command in ("apply", "activate", "pause", "apply-proposals")
    if writes and not args.yes:
        print(f"{args.command} changes the Apple Ads account (and what it spends). Show the owner the plan or the "
              "proposals, then run again with --yes (also needed for --dry-run).")
        return 2
    if args.command in ("activate", "pause") and not args.campaign:
        print("Name the campaign(s): --campaign ID (ids are in apple-ads-live.json or status)")
        return 2
    if not 1 <= args.days <= 90:
        print("--days must be 1 to 90")
        return 2
    try:
        kit = Kit(args.kit)
        cfg = kit.config()
        if args.command == "check":
            campaigns, manual = build_structure(cfg)
            daily, monthly = money_summary(campaigns, manual)
            print(f"apple-ads.yaml is valid: {len(campaigns)} API campaign(s), {len(manual)} Maximize Conversions "
                  f"campaign(s) for the website; {daily} {cfg['currency']} a day, at most {monthly} a month once switched on.")
            for c in campaigns:
                print(f"  {c['name']}: {c['daily_budget']}/day, " + ", ".join(
                    f"{g['name']} {g['bid']} ({len(g['keywords']) or 'Search Match'})" for g in c["ad_groups"]))
            return 0
        if client is None:
            client = make_client(kit.path, dry_run=args.dry_run)
        client.dry_run = client.dry_run or args.dry_run
        if args.command == "status":
            account = read_account(client)
            check_account(cfg, account)
            camps = app_campaigns(client, cfg["adam_id"])
            print(f"Ad account {account['id']}: {account['currency']}, time zone {account['time_zone']}")
            for c in camps:
                print(f"  {c['id']}  {c['status']:8} {c['daily_budget']:>8}/day  {c['name']}")
            if not camps:
                print("  no campaigns for this app yet")
            return 0
        if args.command == "plan":
            account = read_account(client)
            check_account(cfg, account)
            plan = build_plan(kit, cfg, account, app_campaigns(client, cfg["adam_id"]),
                              live=kit.read_json("apple-ads-live.json", {}))
            kit.write("apple-ads-plan.json", plan)
            kit.write("apple-ads-plan.md", render_plan(plan))
            print(f"wrote apple-ads-plan.md and .json: {len(plan['campaigns'])} campaign(s) to create PAUSED, "
                  f"{plan['daily_total']} {cfg['currency']}/day once switched on")
            for w in plan["warnings"]:
                print("-", w)
            return 0
        if args.command == "apply":
            return apply_plan(client, kit, cfg)
        if args.command in ("activate", "pause"):
            return set_status(client, kit, cfg, [str(c) for c in args.campaign],
                              "ENABLED" if args.command == "activate" else "PAUSED")
        if args.command == "report":
            rep = collect(client, cfg, args.days, today)
            kit.write("apple-ads-report.json", rep)
            kit.write("apple-ads-report.md", render_report(rep))
            print(f"wrote apple-ads-report.md: {len(rep['campaigns'])} campaign(s), {rep['from']} to {rep['to']}")
            return 0
        if args.command == "optimize":
            rep = collect(client, cfg, args.days, today)
            groups = {}
            for c in rep["campaigns"]:
                for g in client.query("/v1/adgroups/query", {"filters": [eq("campaignId", c["id"])]}):
                    bid = ((g.get("bidStrategy") or {}).get("bid"))
                    if bid:
                        groups[g.get("id")] = amount_of(bid)
            doc = {"day": (today or dt.date.today()).isoformat(), "input_hash": kit.fingerprint(client.account),
                   "from": rep["from"], "to": rep["to"], "proposals": propose(rep, cfg, groups)}
            kit.write("apple-ads-report.json", rep)
            kit.write("apple-ads-proposals.json", doc)
            kit.write("apple-ads-proposals.md", render_proposals(doc))
            print(f"wrote apple-ads-proposals.md: {len(doc['proposals'])} proposal(s), none applied")
            return 0
        return apply_proposals(client, kit, cfg)
    except asc_api.ConfigError as error:
        print(error)
        return 2
    except AdsError as error:
        print(error)
        return 1
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as error:
        print(f"Cannot read apple-ads.yaml, a saved file or Apple's answer: {type(error).__name__}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
