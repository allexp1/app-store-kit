#!/usr/bin/env python3
"""Set up the Apple Ads API key from the terminal, once per kit.

  python3 scripts/apple_ads_key.py KIT

1. Makes an EC P-256 key pair (Apple's recipe) in ~/.config/app-store-kit/apple-ads/ (folder 700, key 600),
   or reuses the one already there. The private key never leaves this Mac and is never printed.
2. Prints the PUBLIC key and copies it to the clipboard. You paste it in Apple Ads → Account Settings → API → Save.
3. You paste back the clientId / teamId / keyId block Apple then shows.
4. It signs in once (read-only), lists the ad accounts the key can reach, and you pick one.
5. It writes KIT/connect.yaml › apple_ads (other lines in the file are kept as they are).

Options: --key-dir DIR, --new-key (start over with a fresh key; the old one is kept with a date suffix),
--client-id/--team-id/--key-id/--ad-account-id to skip the prompts, --no-verify to skip the sign-in.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys

import apple_ads
import asc_api

DEFAULT_DIR = pathlib.Path("~/.config/app-store-kit/apple-ads").expanduser()


def make_key(key_dir, new=False, run=subprocess.run):
    """Return (private, public) paths, generating the pair with openssl when needed."""
    key_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(key_dir, 0o700)
    private, public = key_dir / "private-key.pem", key_dir / "public-key.pem"
    if private.exists() and new:
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        private.rename(key_dir / f"private-key.{stamp}.pem")
        if public.exists():
            public.rename(key_dir / f"public-key.{stamp}.pem")
    if not private.exists():
        if not shutil.which("openssl"):
            raise SystemExit("openssl is needed (it ships with macOS).")
        old = os.umask(0o077)
        try:
            run(["openssl", "ecparam", "-genkey", "-name", "prime256v1", "-noout", "-out", str(private)], check=True)
        finally:
            os.umask(old)
        print(f"Made a new private key: {private}")
    else:
        print(f"Using the existing private key: {private}  (--new-key starts over)")
    os.chmod(private, 0o600)
    run(["openssl", "ec", "-in", str(private), "-pubout", "-out", str(public)], check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return private, public


def parse_ids(text):
    """clientId / teamId / keyId from the block Apple shows after saving the public key."""
    found = {}
    for field, key in (("clientId", "client_id"), ("teamId", "team_id"), ("keyId", "key_id")):
        m = re.search(rf"{field}\W*\s*([A-Za-z0-9._-]+)", text)
        if m:
            found[key] = m.group(1)
    return found


def read_block(prompt=input):
    print("\nPaste the block Apple shows above the public key (clientId, teamId, keyId), then press Enter on an empty line:")
    lines = []
    while True:
        try:
            line = prompt("")
        except EOFError:
            break
        if not line.strip():
            if lines:
                break
            continue
        lines.append(line)
        if len(parse_ids("\n".join(lines))) == 3:
            break
    return parse_ids("\n".join(lines))


def ad_accounts(creds, transport=None):
    """[(id, name, roles)] the key can reach, via GET /v1/acls (read-only, no account header)."""
    transport = transport or asc_api.urllib_transport
    client = apple_ads.Client(apple_ads.AccessToken(creds, transport), creds.ad_account_id or "0", transport=transport)
    result = client.get("/v1/acls", scoped=False) or {}
    out = []
    for acl in result.get("acls") or []:
        acct = acl.get("adAccount") or {}
        if acct.get("id") is not None:
            out.append((str(acct["id"]), acct.get("name") or "", ", ".join(acl.get("roles") or [])))
    return out


def write_connect(kit, values):
    """Replace (or add) the top-level apple_ads: block in KIT/connect.yaml, keeping every other line and comment."""
    path = pathlib.Path(kit) / "connect.yaml"
    lines = path.read_text().splitlines() if path.exists() else []
    out, skipping = [], False
    for line in lines:
        if re.match(r"^apple_ads\s*:", line):
            skipping = True
            continue
        if skipping and (line.startswith((" ", "\t")) or not line.strip()):
            continue
        skipping = False
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    block = ["", "# Apple Ads API (scripts/apple_ads_key.py). Ids only; the private key stays at key_path, outside git.",
             "apple_ads:"] + [f"  {k}: \"{values[k]}\"" for k in ("client_id", "team_id", "key_id", "key_path", "ad_account_id")]
    path.write_text("\n".join(out + block) + "\n")
    return path


def to_clipboard(text):
    if shutil.which("pbcopy"):
        subprocess.run(["pbcopy"], input=text.encode(), check=False)
        return True
    return False


def main(argv=None, prompt=input, transport=None, run=subprocess.run, copy=to_clipboard):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("kit")
    ap.add_argument("--key-dir", default=str(DEFAULT_DIR))
    ap.add_argument("--new-key", action="store_true")
    ap.add_argument("--client-id")
    ap.add_argument("--team-id")
    ap.add_argument("--key-id")
    ap.add_argument("--ad-account-id")
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args(argv)
    kit = pathlib.Path(args.kit)
    if not kit.is_dir():
        print(f"No kit folder at {kit}")
        return 2
    key_dir = pathlib.Path(args.key_dir).expanduser()
    if key_dir.resolve().is_relative_to(kit.resolve()):
        print("Keep the key outside the kit and the repo; use the default --key-dir")
        return 2
    private, public = make_key(key_dir, args.new_key, run)

    ids = {k: v for k, v in (("client_id", args.client_id), ("team_id", args.team_id), ("key_id", args.key_id)) if v}
    if len(ids) < 3:
        pub = public.read_text()
        print("\n" + pub)
        if copy(pub):
            print("The public key above is on your clipboard.")
        print("Now, signed in to Apple Ads as the API user:\n"
              "  ads.apple.com → Sign In → Advanced → your name (top right) → Account Settings → API\n"
              "  paste the public key in the Public Key field → Save")
        ids = {**read_block(prompt), **ids}
    missing = [k for k in ("client_id", "team_id", "key_id") if not ids.get(k)]
    if missing:
        print("Could not read " + ", ".join(missing) + " from that; run again and paste the whole block.")
        return 1

    account = args.ad_account_id
    if not args.no_verify:
        creds = apple_ads.Credentials(ids["client_id"], ids["team_id"], ids["key_id"], private, account or "")
        try:
            accounts = ad_accounts(creds, transport)
        except (asc_api.ConfigError, apple_ads.AdsError, OSError) as error:
            print(f"Sign-in test failed: {error}\nNothing was saved. If you just saved the key, wait a minute and run again.")
            return 1
        print("\nSigned in. Ad accounts this key can use:")
        for n, (aid, name, roles) in enumerate(accounts, 1):
            print(f"  {n}. {aid}  {name}  ({roles})")
        if not accounts:
            print("  none: the user has no API role on an ad account yet (Account Settings → User Management).")
            return 1
        if account and account not in [a[0] for a in accounts]:
            print(f"--ad-account-id {account} is not one of them")
            return 1
        if not account:
            if len(accounts) == 1:
                account = accounts[0][0]
            else:
                pick = ""
                for _ in range(10):        # a paste often leaves a blank line behind: ask again, don't give up
                    try:
                        pick = prompt(f"Which one (1-{len(accounts)})? ").strip()
                    except EOFError:
                        pick = ""
                        break
                    if pick.isdigit() and 1 <= int(pick) <= len(accounts):
                        break
                    if pick:
                        print(f"Type a number from 1 to {len(accounts)}.")
                if not (pick.isdigit() and 1 <= int(pick) <= len(accounts)):
                    print("No account picked; nothing saved.")
                    return 1
                account = accounts[int(pick) - 1][0]
    if not account or not account.isdigit():
        print("An ad account id is needed (--ad-account-id, digits)")
        return 1
    path = write_connect(kit, {**ids, "key_path": str(private), "ad_account_id": account})
    print(f"\nSaved to {path} (ad account {account}).\nNext, copy {kit / 'apple-ads.yaml'} from templates/apple-ads.example.yaml, "
          f"then: {shlex.quote(sys.executable)} scripts/apple_ads.py check {shlex.quote(str(kit))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
