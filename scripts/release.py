#!/usr/bin/env python3
"""Bump, archive, upload and wait for a new build of an iOS app.

Usage:
  release.py bump PROJECT_DIR [--version 1.1.0 | --major | --minor | --patch] [--build auto|N] [--last-build N]
             [--dry-run]
  release.py archive PROJECT_DIR --scheme S [--xcodegen] [--out DIR] [--kit KIT] [--dry-run]
  release.py upload ARCHIVE --kit KIT --yes [--out DIR] [--project DIR] [--team-id T] [--internal-only] [--dry-run]
  release.py wait --kit KIT --version V --build B [--app-id ID] [--dry-run]

bump edits MARKETING_VERSION / CURRENT_PROJECT_VERSION in PROJECT_DIR/project.yml (XcodeGen; a text edit, the
rest of the file is untouched) or, without project.yml, every occurrence in *.xcodeproj/project.pbxproj.
--build auto = max(local build, --last-build) + 1 (--last-build is the highest build already uploaded).

archive runs `xcodegen generate` (with --xcodegen and a project.yml), then `xcodebuild archive` for generic iOS.
upload writes ExportOptions.plist (app-store-connect, destination upload, symbols, the build number as set) and runs
`xcodebuild -exportArchive`, which uploads to App Store Connect. It needs --yes: uploading is the owner's call.
wait runs `xcrun altool --build-status ... --wait` until App Store Connect has processed the build.

API key (never printed; commands show it as <key>): env ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_PATH; else KIT/connect.yaml
  api: {key_id, issuer_id, key_path, app_id}
and, with a key id but no path, AuthKey_<KEY_ID>.p8 in altool's folders (./private_keys, ~/private_keys,
~/.private_keys, ~/.appstoreconnect/private_keys, $API_PRIVATE_KEYS_DIR). Without a key, Xcode's signed-in account
is used. --dry-run prints every command instead of running it.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import plistlib
import re
import shlex
import subprocess
import sys

import yaml

KEY_MASK = "<key>"
ALTOOL_DIRS = ["./private_keys", "~/private_keys", "~/.private_keys", "~/.appstoreconnect/private_keys"]


# ---- one way to run anything ------------------------------------------------------------------------

def run(cmd: list[str], *, dry_run: bool, cwd=None, secrets=(), env=None) -> int:
    """Print the command (secrets shown as <key>) and run it unless dry_run. Returns the exit code."""
    shown = [KEY_MASK if str(c) in {str(s) for s in secrets if s} else str(c) for c in cmd]
    where = f"(cd {shlex.quote(str(cwd))}) " if cwd else ""
    where += "".join(f"{k}=<key dir> " for k in (env or {}))
    print(("would run: " if dry_run else "$ ") + where + " ".join(c if c == KEY_MASK else shlex.quote(c) for c in shown),
          flush=True)
    if dry_run:
        return 0
    full_env = {**os.environ, **(env or {})} if env else None
    return subprocess.run([str(c) for c in cmd], cwd=cwd, env=full_env).returncode


# ---- API key ----------------------------------------------------------------------------------------

def load_yaml(p: pathlib.Path):
    try:
        return (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}
    except yaml.YAMLError:
        return {}


def api_config(kit) -> dict:
    conn = load_yaml(pathlib.Path(kit) / "connect.yaml") if kit else {}
    api = conn.get("api") if isinstance(conn, dict) and isinstance(conn.get("api"), dict) else {}
    return api


def find_altool_key(key_id: str) -> pathlib.Path | None:
    dirs = ALTOOL_DIRS + ([os.environ["API_PRIVATE_KEYS_DIR"]] if os.environ.get("API_PRIVATE_KEYS_DIR") else [])
    for d in dirs:
        p = pathlib.Path(os.path.expanduser(d)) / f"AuthKey_{key_id}.p8"
        if p.is_file():
            return p
    return None


def resolve_key(kit=None) -> dict | None:
    """{key_id, issuer_id, key_path} or None. Reads only the location, never the key itself."""
    api = api_config(kit)
    key_id = os.environ.get("ASC_KEY_ID") or api.get("key_id")
    issuer = os.environ.get("ASC_ISSUER_ID") or api.get("issuer_id")
    path = os.environ.get("ASC_KEY_PATH") or api.get("key_path")
    if not key_id:
        return None
    if path:
        path = pathlib.Path(os.path.expanduser(str(path)))
        if not path.is_absolute() and kit:
            path = (pathlib.Path(kit) / path).resolve()
    else:
        path = find_altool_key(str(key_id))
    if not path:
        return None
    return {"key_id": str(key_id), "issuer_id": str(issuer) if issuer else None, "key_path": path}


def xcode_auth_flags(key: dict | None) -> list[str]:
    if not key:
        return []
    flags = ["-authenticationKeyPath", str(key["key_path"]), "-authenticationKeyID", key["key_id"]]
    if key["issuer_id"]:
        flags += ["-authenticationKeyIssuerID", key["issuer_id"]]
    return flags


def secrets_of(key):
    return [str(key["key_path"])] if key else []


# ---- bump -------------------------------------------------------------------------------------------

VERSION_RX = re.compile(r"^\d+(\.\d+){0,2}$")


def parse_version(v: str) -> tuple[int, int, int]:
    if not VERSION_RX.match(v):
        raise ValueError(f"'{v}' is not a version (one to three integers separated by periods)")
    parts = [int(x) for x in v.split(".")] + [0, 0]
    return parts[0], parts[1], parts[2]


def fmt_version(t) -> str:
    return ".".join(str(x) for x in t)


def project_file(project_dir: pathlib.Path) -> tuple[pathlib.Path, str]:
    if project_dir.is_file():
        return project_dir, "yml" if project_dir.suffix in (".yml", ".yaml") else "pbxproj"
    yml = project_dir / "project.yml"
    if yml.exists():
        return yml, "yml"
    pbx = sorted(project_dir.glob("*.xcodeproj/project.pbxproj"))
    if len(pbx) == 1:
        return pbx[0], "pbxproj"
    if len(pbx) > 1:
        raise ValueError(f"several Xcode projects in {project_dir}: pass the project.pbxproj path")
    raise ValueError(f"no project.yml or *.xcodeproj/project.pbxproj in {project_dir}")


def _patterns(kind: str, key: str) -> re.Pattern:
    if kind == "yml":  # MARKETING_VERSION: "1.0.0"   (quotes optional, trailing comment kept)
        return re.compile(rf"(?m)^(?P<pre>[ \t]*{key}[ \t]*:[ \t]*)(?P<q>[\"']?)(?P<val>[^\"'\s#]+)(?P=q)")
    return re.compile(rf"(?P<pre>\b{key}[ \t]*=[ \t]*)(?P<q>\"?)(?P<val>[^\";\s]+)(?P=q)(?=[ \t]*;)")


def read_values(text: str, kind: str, key: str) -> list[str]:
    return [m.group("val") for m in _patterns(kind, key).finditer(text)]


def replace_values(text: str, kind: str, key: str, new: str) -> tuple[str, int]:
    return _patterns(kind, key).subn(lambda m: f"{m.group('pre')}{m.group('q')}{new}{m.group('q')}", text)


def cmd_bump(a) -> int:
    try:
        path, kind = project_file(pathlib.Path(a.project))
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    text = path.read_text()
    versions = read_values(text, kind, "MARKETING_VERSION")
    builds = read_values(text, kind, "CURRENT_PROJECT_VERSION")
    if not versions or not builds:
        print(f"error: {path.name} has no MARKETING_VERSION / CURRENT_PROJECT_VERSION to bump", file=sys.stderr)
        return 2
    try:
        old_v = max(parse_version(v) for v in versions if not v.startswith("$"))
        old_b = max(int(b) for b in builds if b.isdigit())
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if a.version:
        new_v = parse_version(a.version)
    elif a.major:
        new_v = (old_v[0] + 1, 0, 0)
    elif a.minor:
        new_v = (old_v[0], old_v[1] + 1, 0)
    elif a.patch:
        new_v = (old_v[0], old_v[1], old_v[2] + 1)
    else:
        new_v = old_v
    if new_v < old_v:
        print(f"error: {fmt_version(new_v)} is lower than the current {fmt_version(old_v)}", file=sys.stderr)
        return 1
    floor = max(old_b, a.last_build or 0)
    if a.build in (None, "auto"):
        new_b = floor + 1
    elif str(a.build).isdigit():
        new_b = int(a.build)
        if new_b <= (a.last_build or 0):
            print(f"error: build {new_b} must be higher than the last upload {a.last_build}", file=sys.stderr)
            return 1
    else:
        print(f"error: --build must be auto or a number, not '{a.build}'", file=sys.stderr)
        return 2
    new_text, nv = replace_values(text, kind, "MARKETING_VERSION", fmt_version(new_v))
    new_text, nb = replace_values(new_text, kind, "CURRENT_PROJECT_VERSION", str(new_b))
    mixed = " (values differed: " + ", ".join(sorted(set(versions))) + ")" if len(set(versions)) > 1 else ""
    print(f"{path}")
    print(f"  version {fmt_version(old_v)} → {fmt_version(new_v)}  ({nv} place{'s' if nv != 1 else ''}){mixed}")
    print(f"  build   {old_b} → {new_b}  ({nb} place{'s' if nb != 1 else ''})"
          + (f"; last upload {a.last_build}" if a.last_build else ""))
    if a.dry_run:
        print("dry run: nothing written")
        return 0
    path.write_text(new_text)
    if kind == "yml":
        print("run `xcodegen generate` (or release.py archive --xcodegen) so the Xcode project picks it up")
    return 0


# ---- archive ----------------------------------------------------------------------------------------

def cmd_archive(a) -> int:
    proj = pathlib.Path(a.project).resolve()
    out = pathlib.Path(a.out).resolve() if a.out else proj / "build"
    archive = out / "App.xcarchive"
    key = resolve_key(a.kit)
    if (proj / "project.yml").exists() and a.xcodegen:
        rc = run(["xcodegen", "generate"], dry_run=a.dry_run, cwd=proj)
        if rc:
            return rc
    cmd = ["xcodebuild"]
    workspaces = [w for w in proj.glob("*.xcworkspace")]
    if len(workspaces) == 1:
        cmd += ["-workspace", workspaces[0].name]
    cmd += ["-scheme", a.scheme, "-configuration", "Release", "-destination", "generic/platform=iOS",
            "-archivePath", str(archive), "archive", "-allowProvisioningUpdates", *xcode_auth_flags(key)]
    if not key:
        print("note: no App Store Connect API key configured; xcodebuild uses the account signed in to Xcode")
    rc = run(cmd, dry_run=a.dry_run, cwd=proj, secrets=secrets_of(key))
    if rc == 0 and not a.dry_run:
        print(f"archive: {archive}")
    return rc


# ---- upload -----------------------------------------------------------------------------------------

def team_from_archive(archive: pathlib.Path) -> str | None:
    info = archive / "Info.plist"
    if not info.exists():
        return None
    try:
        data = plistlib.loads(info.read_bytes())
    except Exception:
        return None
    return (data.get("ApplicationProperties") or {}).get("Team")


def team_from_project(project: pathlib.Path | None) -> str | None:
    if not project or not project.exists():
        return None
    files = [project / "project.yml", *project.glob("*.xcodeproj/project.pbxproj"), *project.glob("**/*.xcconfig")]
    rx = re.compile(r"DEVELOPMENT_TEAM\s*[:=]\s*[\"']?([A-Z0-9]{10})\b")
    for f in files:
        if f.is_file() and "DerivedData" not in f.parts:
            m = rx.search(f.read_text(errors="ignore"))
            if m:
                return m.group(1)
    return None


def export_options(team: str | None, internal_only: bool) -> dict:
    opts = {"method": "app-store-connect", "destination": "upload", "signingStyle": "automatic",
            "uploadSymbols": True, "manageAppVersionAndBuildNumber": False}
    if internal_only:
        opts["testFlightInternalTestingOnly"] = True
    if team:
        opts["teamID"] = team
    return opts


def cmd_upload(a) -> int:
    if not a.yes:
        print("refused: uploading a build to App Store Connect needs the owner's yes. Show them the version and "
              "build, ask, then run again with --yes.", file=sys.stderr)
        return 3
    archive = pathlib.Path(a.archive).resolve()
    if not archive.exists() and not a.dry_run:
        print(f"error: no archive at {archive}", file=sys.stderr)
        return 2
    out = pathlib.Path(a.out).resolve() if a.out else archive.parent / "export"
    team = a.team_id or team_from_archive(archive) or team_from_project(pathlib.Path(a.project) if a.project else None)
    if not team:
        print("note: no team ID found in the archive or project; Xcode picks the team")
    out.mkdir(parents=True, exist_ok=True)
    plist = out / "ExportOptions.plist"
    plist.write_bytes(plistlib.dumps(export_options(team, a.internal_only)))
    print(f"wrote {plist}")
    key = resolve_key(a.kit)
    if not key:
        print("note: no App Store Connect API key configured; xcodebuild uses the account signed in to Xcode")
    cmd = ["xcodebuild", "-exportArchive", "-archivePath", str(archive), "-exportOptionsPlist", str(plist),
           "-exportPath", str(out), "-allowProvisioningUpdates", *xcode_auth_flags(key)]
    return run(cmd, dry_run=a.dry_run, secrets=secrets_of(key))


# ---- wait -------------------------------------------------------------------------------------------

def app_id_from_kit(kit) -> str | None:
    api = api_config(kit)
    conn = load_yaml(pathlib.Path(kit) / "connect.yaml") if kit else {}
    facts = load_yaml(pathlib.Path(kit) / "facts.yaml") if kit else {}
    for v in (api.get("app_id"), conn.get("app_id"), conn.get("apple_id"),
              (facts.get("app") or {}).get("apple_id") if isinstance(facts.get("app"), dict) else None):
        if v:
            return str(v)
    return None


def cmd_wait(a) -> int:
    app_id = a.app_id or app_id_from_kit(a.kit)
    if not app_id:
        print("error: the app's Apple ID is unknown: pass --app-id or add api.app_id to connect.yaml "
              "(App Store Connect → App Information → Apple ID)", file=sys.stderr)
        return 2
    key = resolve_key(a.kit)
    cmd = ["xcrun", "altool", "--build-status", "--apple-id", app_id, "--bundle-version", str(a.build),
           "--bundle-short-version-string", a.version, "--platform", "ios"]
    env = None
    if key:
        cmd += ["--api-key", key["key_id"]]
        if key["issuer_id"]:
            cmd += ["--api-issuer", key["issuer_id"]]
        kp = pathlib.Path(key["key_path"])
        if kp.name == f"AuthKey_{key['key_id']}.p8":
            env = {"API_PRIVATE_KEYS_DIR": str(kp.parent)}  # altool's documented lookup; path stays off the line
        else:
            cmd += ["--p8-file-path", str(kp)]
    else:
        print("note: no API key configured; altool needs --api-key/--api-issuer (or -u/-p) to check status")
    cmd += ["--wait"]
    return run(cmd, dry_run=a.dry_run, secrets=secrets_of(key), env=env)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("bump")
    b.add_argument("project")
    g = b.add_mutually_exclusive_group()
    g.add_argument("--version")
    g.add_argument("--major", action="store_true")
    g.add_argument("--minor", action="store_true")
    g.add_argument("--patch", action="store_true")
    b.add_argument("--build", default="auto")
    b.add_argument("--last-build", type=int, help="highest build number already uploaded")
    b.add_argument("--dry-run", action="store_true")

    r = sub.add_parser("archive")
    r.add_argument("project")
    r.add_argument("--scheme", required=True)
    r.add_argument("--xcodegen", action="store_true")
    r.add_argument("--out")
    r.add_argument("--kit")
    r.add_argument("--dry-run", action="store_true")

    u = sub.add_parser("upload")
    u.add_argument("archive")
    u.add_argument("--kit")
    u.add_argument("--yes", action="store_true")
    u.add_argument("--out")
    u.add_argument("--project", help="project folder, to find DEVELOPMENT_TEAM if the archive lacks it")
    u.add_argument("--team-id")
    u.add_argument("--internal-only", action="store_true", help="testFlightInternalTestingOnly")
    u.add_argument("--dry-run", action="store_true")

    w = sub.add_parser("wait")
    w.add_argument("--kit")
    w.add_argument("--version", required=True)
    w.add_argument("--build", required=True)
    w.add_argument("--app-id")
    w.add_argument("--dry-run", action="store_true")

    a = ap.parse_args(argv)
    return {"bump": cmd_bump, "archive": cmd_archive, "upload": cmd_upload, "wait": cmd_wait}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
