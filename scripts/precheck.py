#!/usr/bin/env python3
"""Pre-check an iOS/iPadOS project against Apple's upload rules and App Review Guidelines.

Usage:
  precheck.py PROJECT_DIR [--kit KIT] [--out KIT/PRECHECK.md] [--json] [--scheme NAME] [--strict]
                          [--check-urls] [--xcode VERSION] [--today YYYY-MM-DD]

The check catalogue (id, guideline, severity, detect mode, source URLs) is read from
references/precheck-rules.md, so that file stays the single source. This script only holds the
detection logic, one small function per check id.

What it reads (nothing is downloaded):
  project.yml (XcodeGen) and/or *.xcodeproj/project.pbxproj build settings, Info.plist files and
  `info: properties:` blocks, INFOPLIST_KEY_* settings, *.entitlements, PrivacyInfo.xcprivacy (app, local
  packages, and SDK manifests already present in SourcePackages/checkouts, DerivedData or Pods),
  Package.resolved / Podfile.lock / Cartfile.resolved, Swift/ObjC sources (code inside `#if DEBUG` and
  files listed in Release EXCLUDED_SOURCE_FILE_NAMES are skipped), *.xcstrings / *.lproj, asset catalogs
  and .icon files, *.storekit, and the kit (facts.yaml, metadata.<locale>.yaml, connect.yaml).

Output: PRECHECK.md with BLOCKER / LIKELY REJECTION / WARNING / PASS sections and a "For Claude to judge"
list (Semi checks: evidence plus a question). --json prints the same as JSON on stdout.
Without --kit and --out the Markdown goes to stdout.

--check-urls fetches the kit's URLs (HEAD, then GET; 10 s timeout). Off by default.
--xcode overrides the Xcode version (otherwise `xcodebuild -version`, .xcode-version, project.yml
xcodeVersion, pbxproj LastUpgradeCheck). --today overrides the date used for dated rules.

Decisions: KIT/precheck-decisions.yaml maps each unscanned check id to {decision: ok|fixed|n/a, why: evidence}.
Exit code: 2 if any BLOCKER, 1 if unscanned checks remain undecided, any LIKELY REJECTION,
or any WARNING with --strict; else 0.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import pathlib
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import urllib.error
import urllib.request

import yaml

HERE = pathlib.Path(__file__).resolve().parent
RULES_MD = HERE.parent / "references" / "precheck-rules.md"

SEVERITIES = ["BLOCKER", "LIKELY REJECTION", "WARNING"]
SHORT_SOURCES = {
    "GL": "https://developer.apple.com/app-store/review/guidelines/",
    "UR": "https://developer.apple.com/news/upcoming-requirements/",
    "AR": "https://developer.apple.com/distribute/app-review/",
}
# Checks the task needs that precheck-rules.md has no row for. Same shape as the parsed rows.
EXTRA_CHECKS = {
    "LOC-01": {"guideline": "2.3 accurate metadata: store languages the app supports", "severity": "WARNING",
               "detect": "Auto", "sources": [SHORT_SOURCES["GL"]]},
}

SKIP_DIRS = {".git", ".build", "build", "DerivedData", "Pods", "Carthage", "SourcePackages", "node_modules",
             ".swiftpm", "xcuserdata", "fastlane", ".living"}
CODE_EXT = {".swift", ".m", ".mm", ".h", ".c", ".cc", ".cpp"}
TEST_DIR = re.compile(r"(^|/)[^/]*(Tests|UITests|Spec|Specs)(/|$)")

# --------------------------------------------------------------------------- catalogue


def load_catalogue(path=RULES_MD):
    """Parse the check tables in precheck-rules.md into {id: {guideline, severity, detect, sources, what}}."""
    cat = {}
    row = re.compile(r"^\|\s*([A-Z]+-\d+)\s*\|(.*)\|\s*$")
    for line in pathlib.Path(path).read_text().splitlines():
        m = row.match(line)
        if not m:
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", m.group(2))]
        if len(cells) < 5:
            continue
        guideline, what, sev_text, detect, source = cells[0], cells[1], cells[2], cells[3], cells[4]
        cat[m.group(1)] = {"guideline": guideline, "what": what, "severity": _first_severity(sev_text),
                           "severity_text": sev_text, "detect": detect, "sources": _urls(source)}
    for k, v in EXTRA_CHECKS.items():
        cat.setdefault(k, v)
    return cat


def _first_severity(text):
    best = None
    for s in SEVERITIES:
        i = text.find("LIKELY" if s == "LIKELY REJECTION" else s)
        if i >= 0 and (best is None or i < best[0]):
            best = (i, s)
    return best[1] if best else "WARNING"


def _urls(text):
    urls = re.findall(r"https?://[^\s;,)]+", text)
    for short, url in SHORT_SOURCES.items():
        if re.search(rf"\b{short}\b", text) and url not in urls:
            urls.append(url)
    return urls or [SHORT_SOURCES["GL"]]


# --------------------------------------------------------------------------- project model


class Line:
    __slots__ = ("path", "no", "text", "debug")

    def __init__(self, path, no, text, debug):
        self.path, self.no, self.text, self.debug = path, no, text, debug


def strip_comments(lines):
    """Remove // and /* */ comments outside string literals. Returns list of code lines (same length)."""
    out, in_block = [], False
    for raw in lines:
        res, i, in_str, n = [], 0, False, len(raw)
        while i < n:
            two = raw[i:i + 2]
            if in_block:
                if two == "*/":
                    in_block, i = False, i + 2
                else:
                    i += 1
                continue
            c = raw[i]
            if in_str:
                res.append(c)
                if c == "\\" and i + 1 < n:
                    res.append(raw[i + 1])
                    i += 2
                    continue
                if c == '"':
                    in_str = False
            elif two == "//":
                break
            elif two == "/*":
                in_block, i = True, i + 2
                continue
            else:
                if c == '"':
                    in_str = True
                res.append(c)
            i += 1
        out.append("".join(res))
    return out


def debug_flags(lines):
    """True for each line compiled only in DEBUG builds (inside #if DEBUG, or #else of #if !DEBUG), and for
    Xcode previews (#Preview blocks, PreviewProvider types), which users never see."""
    stack, flags, preview, depth = [], [], False, 0
    for ln in lines:
        s = ln.strip()
        if not preview and re.match(r"#Preview\b|(struct|extension)\s+\w+\s*:\s*PreviewProvider\b", s):
            preview, depth, opened = True, 0, False
        if preview:
            depth += ln.count("{") - ln.count("}")
            opened = opened or "{" in ln
            flags.append(True)
            if opened and depth <= 0:
                preview = False
            continue
        m = re.match(r"#\s*(if|elseif|else|endif)\b(.*)", s)
        if m:
            kw, cond = m.group(1), m.group(2)
            if kw == "if":
                stack.append(_debug_kind(cond))
            elif kw in ("else", "elseif") and stack:
                k = stack[-1]
                stack[-1] = "debug" if k == "release" else ("release" if k == "debug" else None)
            elif kw == "endif" and stack:
                stack.pop()
            flags.append(True if "debug" in stack else False)
            continue
        flags.append("debug" in stack)
    return flags


def _debug_kind(cond):
    c = cond.replace(" ", "")
    if re.search(r"!DEBUG\b", c):
        return "release"
    if re.search(r"\bDEBUG\b", c) and "||" not in c:
        return "debug"
    return None


def read_plist(path):
    try:
        with open(path, "rb") as fh:
            return plistlib.load(fh)
    except Exception:
        return None


def version_tuple(v):
    nums = re.findall(r"\d+", str(v or ""))
    return tuple(int(x) for x in nums[:3]) if nums else None


class Project:
    def __init__(self, root, kit=None, scheme=None):
        self.root = pathlib.Path(root).resolve()
        self.kit = pathlib.Path(kit).resolve() if kit else None
        self.scheme = scheme
        self.notes = []
        self.yml = self._load_yaml(self.root / "project.yml")
        self.pbx = self._load_pbxproj()
        self.app_target = None
        self.targets = {}          # name -> {"type", "sources": [dirs/files], "excludes": {dir: [globs]}}
        self.settings = {}         # merged build settings for the app target
        self.release_excluded = []  # EXCLUDED_SOURCE_FILE_NAMES patterns of the Release config
        self._discover_targets()
        self.info, self.info_where = self._load_info()
        self.entitlements = self._load_entitlements()
        self.code = self._load_code()     # list[Line], app + extensions (no tests, no DEBUG flag removed)
        self.ext_code = [l for l in self.code if self._file_target_types(l.path) - {"application"}
                         and "application" not in self._file_target_types(l.path)]
        self.deps = self._load_deps()     # list of (name, version, source file)
        self.manifests = self._load_manifests()  # [(path, dict)] app + local packages
        self.sdk_manifests = self._find_sdk_manifests()  # {lower name: path}
        self.languages = self._load_languages()  # {lang: evidence}
        self.storekit = self._load_storekit()
        self.facts = self._load_yaml(self.kit / "facts.yaml") if self.kit else {}
        self.metadata = self._load_metadata()
        self.connect = self._load_yaml(self.kit / "connect.yaml") if self.kit else {}

    # ---- helpers
    def rel(self, p):
        p = pathlib.Path(p)
        for base in (self.root, self.kit.parent if self.kit else None):
            if base:
                try:
                    return str(p.resolve().relative_to(base))
                except ValueError:
                    pass
        return str(p)

    @staticmethod
    def _load_yaml(path):
        try:
            data = yaml.safe_load(pathlib.Path(path).read_text())
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def walk(self, base=None, skip=SKIP_DIRS):
        base = pathlib.Path(base or self.root)
        if base.is_file():
            yield base
            return
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for f in filenames:
                yield pathlib.Path(dirpath) / f

    def find(self, pattern, base=None):
        """Files under base whose name matches pattern (directories like *.icon included)."""
        out = []
        for dirpath, dirnames, filenames in os.walk(base or self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in dirnames + filenames:
                if fnmatch.fnmatch(name, pattern):
                    out.append(pathlib.Path(dirpath) / name)
        return out

    def locate(self, path, needle):
        """'path:line' of the first line containing needle, or 'path'."""
        try:
            for i, line in enumerate(pathlib.Path(path).read_text(errors="ignore").splitlines(), 1):
                if needle in line:
                    return f"{self.rel(path)}:{i}"
        except OSError:
            pass
        return self.rel(path)

    # ---- targets and settings
    def _load_pbxproj(self):
        projs = sorted(self.root.glob("*.xcodeproj/project.pbxproj"))
        if not projs:
            return None
        text = projs[0].read_text(errors="ignore")
        configs, names = [], []
        for m in re.finditer(r"buildSettings = \{(.*?)\n\t\t\t\};", text, re.S):
            settings = {}
            for k, v in re.findall(r"^\s*\"?([A-Za-z0-9_\[\]=*\"~ -]+?)\"? = (.*?);\s*$", m.group(1), re.M):
                settings[k.strip()] = v.strip().strip('"')
            configs.append(settings)
            # XCBuildConfiguration writes `name = Release;` right after its buildSettings block
            name = re.match(r"\s*name = \"?([^\";]+)\"?;", text[m.end():])
            names.append(name.group(1) if name else "")
        upgrade = re.search(r"LastUpgradeCheck = (\d+);", text)
        return {"path": projs[0], "text": text, "configs": configs, "config_names": names,
                "last_upgrade": upgrade.group(1) if upgrade else None}

    def _discover_targets(self):
        if self.yml:
            self._targets_from_yml()
        elif self.pbx:
            self._targets_from_pbx()
        if not self.targets:  # plain folder: everything is the app
            self.targets["App"] = {"type": "application", "sources": [self.root], "excludes": {}}
            self.app_target = "App"

    def _targets_from_yml(self):
        y = self.yml
        base_settings = dict((y.get("settings") or {}).get("base") or {})
        for name, t in (y.get("targets") or {}).items():
            ttype = str(t.get("type", ""))
            if "test" in ttype:
                continue
            srcs, excl = [], {}
            for s in t.get("sources") or []:
                p = s if isinstance(s, str) else s.get("path")
                if not p:
                    continue
                full = (self.root / p).resolve()
                srcs.append(full)
                if isinstance(s, dict) and s.get("excludes"):
                    excl[full] = list(s["excludes"])
            self.targets[name] = {"type": "application" if ttype == "application" else ttype,
                                  "sources": srcs, "excludes": excl, "yml": t}
        apps = [n for n, t in self.targets.items() if t["type"] == "application"]
        self.app_target = self.scheme if self.scheme in self.targets else (apps[0] if apps else None)
        for pname, p in (y.get("packages") or {}).items():
            if isinstance(p, dict) and p.get("path"):
                pkg = (self.root / p["path"]).resolve()
                srcs = [pkg / "Sources"] if (pkg / "Sources").is_dir() else [pkg]
                self.targets[f"package:{pname}"] = {"type": "package", "sources": srcs, "excludes": {}}
        t = self.targets.get(self.app_target, {}).get("yml") or {}
        settings = dict(base_settings)
        settings.update(((t.get("settings") or {}).get("base")) or {})
        rel_cfg = (((t.get("settings") or {}).get("configs") or {}).get("Release") or {})
        settings.update({k: v for k, v in rel_cfg.items() if k != "EXCLUDED_SOURCE_FILE_NAMES"})
        self.release_excluded = str(rel_cfg.get("EXCLUDED_SOURCE_FILE_NAMES", "")).split()
        opts = y.get("options") or {}
        dt_ = t.get("deploymentTarget") or (opts.get("deploymentTarget") or {}).get("iOS")
        if isinstance(dt_, dict):
            dt_ = dt_.get("iOS")
        if dt_ and "IPHONEOS_DEPLOYMENT_TARGET" not in settings:
            settings["IPHONEOS_DEPLOYMENT_TARGET"] = str(dt_)
        # xcconfig files of the Release config
        cfgfile = ((t.get("configFiles") or {}).get("Release"))
        if cfgfile:
            settings = {**self._read_xcconfig(self.root / cfgfile), **settings}
        if self.pbx and not settings.get("PRODUCT_BUNDLE_IDENTIFIER"):
            settings = {**self._pbx_app_settings(), **settings}
        self.settings = {k: str(v) for k, v in settings.items()}

    def _read_xcconfig(self, path, depth=0):
        out = {}
        try:
            for line in pathlib.Path(path).read_text().splitlines():
                line = line.split("//")[0].strip()
                inc = re.match(r'#include\??\s+"([^"]+)"', line)
                if inc and depth < 3:
                    out.update(self._read_xcconfig(pathlib.Path(path).parent / inc.group(1), depth + 1))
                elif "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip()
        except OSError:
            pass
        return out

    def _pbx_app_settings(self):
        best = {}
        for c in self.pbx["configs"]:
            bid = c.get("PRODUCT_BUNDLE_IDENTIFIER", "")
            if not bid or bid.lower().endswith(("tests", "uitests")) or "TEST_HOST" in c:
                if not bid:
                    best = {**c, **best}  # project-level defaults
                continue
            if c.get("WRAPPER_EXTENSION") == "appex" or "widget" in bid.lower() and not self.scheme:
                continue
            if self.scheme and self.scheme not in (c.get("PRODUCT_NAME", ""), c.get("INFOPLIST_FILE", "")) \
                    and self.scheme not in c.get("INFOPLIST_FILE", ""):
                continue
            best.update(c)
        return best

    def _pbx_setting(self, key):
        """A build setting from the pbxproj, Release config first: the app target's, then project-level."""
        if not self.pbx:
            return ""
        bid = self.settings.get("PRODUCT_BUNDLE_IDENTIFIER", "")
        ranked = []
        for c, name in zip(self.pbx["configs"], self.pbx.get("config_names", [])):
            v = c.get(key, "").strip()
            cbid = c.get("PRODUCT_BUNDLE_IDENTIFIER", "")
            if not v or (cbid and cbid != bid):
                continue  # other targets (tests, extensions) carry their own values
            ranked.append(((0 if cbid else 2) + (0 if name == "Release" else 1), v))
        return min(ranked)[1] if ranked else ""

    def info_value(self, key, setting):
        """(value, where) of an Info.plist key as the built app gets it. With GENERATE_INFOPLIST_FILE the
        key is often absent from the source plist, or a $(SETTING) reference: fall back to
        INFOPLIST_KEY_<key>, then the build setting (pbxproj Release config first)."""
        v = str(self.info.get(key, "") or "").strip()
        where = self.info_where.get(key, "Info.plist")
        for _ in range(3):  # follow $(A) -> $(B) a few levels
            ref = re.fullmatch(r"\$[({](\w+)(?::[^)}]*)?[)}]", v)
            if v and not ref:
                return v, where
            name = ref.group(1) if ref else setting
            if not ref and self.settings.get(f"INFOPLIST_KEY_{key}", "").strip():
                v, where = self.settings[f"INFOPLIST_KEY_{key}"].strip(), f"build setting INFOPLIST_KEY_{key}"
                continue
            merged = self.settings.get(name, "").strip()  # XcodeGen: already the Release config
            v = (merged or self._pbx_setting(name)) if self.yml else (self._pbx_setting(name) or merged)
            where = f"build setting {name}"
            if not v:
                # an xcconfig the pbxproj points at may define it; unknown is not empty
                if ref and self.pbx and "baseConfigurationReference" in self.pbx["text"]:
                    return ref.group(0), f"{where} (xcconfig, not read)"
                return "", where
        return v, where

    def _targets_from_pbx(self):
        self.settings = self._pbx_app_settings()
        self.targets["App"] = {"type": "application", "sources": [self.root], "excludes": {}}
        self.app_target = "App"

    def _file_target_types(self, relpath):
        p = (self.root / relpath).resolve()
        types = set()
        for t in self.targets.values():
            for s in t["sources"]:
                if p == s or s in p.parents:
                    types.add(t["type"])
        if not self.yml:  # infer extensions by an Info.plist with NSExtension in an ancestor dir
            for parent in p.parents:
                if parent == self.root:
                    break
                ip = read_plist(parent / "Info.plist")
                if ip and "NSExtension" in ip:
                    return {"app-extension"}
        return types or {"application"}

    # ---- Info.plist
    def _load_info(self):
        info, where = {}, {}
        t = self.targets.get(self.app_target, {}).get("yml") or {}
        plist_path = None
        if t.get("info", {}).get("path"):
            plist_path = self.root / t["info"]["path"]
        elif self.settings.get("INFOPLIST_FILE"):
            plist_path = self.root / self.settings["INFOPLIST_FILE"].replace("$(SRCROOT)/", "")
        else:
            cands = [p for p in self.find("Info.plist") if not TEST_DIR.search(self.rel(p))]
            cands = [p for p in cands if "NSExtension" not in (read_plist(p) or {})]
            plist_path = cands[0] if cands else None
        if plist_path and plist_path.exists():
            data = read_plist(plist_path) or {}
            info.update(data)
            for k in data:
                where[k] = self.locate(plist_path, f"<key>{k}</key>")
        for k, v in (t.get("info", {}).get("properties") or {}).items():
            info[k] = v
            where[k] = self.locate(self.root / "project.yml", f"{k}:")
        for k, v in self.settings.items():
            if k.startswith("INFOPLIST_KEY_"):
                key = k[len("INFOPLIST_KEY_"):]
                info.setdefault(key, v)
                where.setdefault(key, f"build setting {k}")
        self.info_path = plist_path
        return info, where

    def _load_entitlements(self):
        t = self.targets.get(self.app_target, {}).get("yml") or {}
        paths = []
        if (t.get("entitlements") or {}).get("path"):
            paths.append(self.root / t["entitlements"]["path"])
        if self.settings.get("CODE_SIGN_ENTITLEMENTS"):
            paths.append(self.root / self.settings["CODE_SIGN_ENTITLEMENTS"])
        if not paths:
            for s in self.targets.get(self.app_target, {}).get("sources", []):
                paths += self.find("*.entitlements", s) if s.is_dir() else []
        ent = {}
        for p in paths:
            ent.update(read_plist(p) or {})
        ent.update(((t.get("entitlements") or {}).get("properties")) or {})
        return ent

    # ---- source code
    def _excluded(self, path):
        rel = self.rel(path)
        if TEST_DIR.search(rel):
            return True
        for pat in self.release_excluded:
            if any(fnmatch.fnmatch(part, pat) for part in pathlib.Path(rel).parts):
                return True
        for t in self.targets.values():
            for src, globs in t["excludes"].items():
                if src in path.parents:
                    r = str(path.relative_to(src))
                    if any(fnmatch.fnmatch(r, g) or r.startswith(g.rstrip("*/") + "/") for g in globs):
                        return True
        return False

    def source_files(self, exts=CODE_EXT):
        seen = set()
        for t in self.targets.values():
            for s in t["sources"]:
                if not s.exists():
                    continue
                for f in self.walk(s):
                    if f.suffix in exts and f not in seen and not self._excluded(f):
                        seen.add(f)
                        yield f

    def _load_code(self):
        out = []
        for f in self.source_files():
            try:
                raw = f.read_text(errors="ignore").splitlines()
            except OSError:
                continue
            code, dbg = strip_comments(raw), debug_flags(raw)
            rel = self.rel(f)
            out.extend(Line(rel, i + 1, c, d) for i, (c, d) in enumerate(zip(code, dbg)))
        return out

    def grep(self, pattern, flags=0, include_debug=False, lines=None):
        rx = re.compile(pattern, flags)
        return [l for l in (self.code if lines is None else lines)
                if (include_debug or not l.debug) and rx.search(l.text)]

    # ---- dependencies and manifests
    def _load_deps(self):
        deps = []
        for p in self._dep_files("Package.resolved"):
            try:
                d = json.loads(p.read_text())
            except Exception:
                continue
            pins = d.get("pins") or (d.get("object") or {}).get("pins") or []
            for pin in pins:
                ident = pin.get("identity") or pin.get("package") or ""
                loc = pin.get("location") or pin.get("repositoryURL") or ""
                name = ident or loc.rstrip("/").split("/")[-1].removesuffix(".git")
                deps.append((name, (pin.get("state") or {}).get("version"), self.rel(p), loc))
        for p in self._dep_files("Podfile.lock"):
            in_pods = False
            for line in p.read_text(errors="ignore").splitlines():
                if line.startswith("PODS:"):
                    in_pods = True
                    continue
                if in_pods and line and not line.startswith(" "):
                    break
                m = re.match(r"^  - \"?([^ /\"(]+)(?:/[^ ]+)? \(([^)]+)\)", line)
                if in_pods and m:
                    deps.append((m.group(1), m.group(2), self.rel(p), ""))
        for p in self._dep_files("Cartfile.resolved"):
            for line in p.read_text(errors="ignore").splitlines():
                m = re.match(r'\w+ "([^"]+)" "([^"]+)"', line)
                if m:
                    deps.append((m.group(1).split("/")[-1], m.group(2), self.rel(p), m.group(1)))
        for name, p in ((self.yml or {}).get("packages") or {}).items():
            if isinstance(p, dict) and p.get("url") and not any(d[3] == p["url"] for d in deps):
                deps.append((name, p.get("exactVersion") or p.get("from") or p.get("version"),
                             "project.yml", p["url"]))
        return deps

    def _dep_files(self, name):
        out = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS - {".swiftpm"} and d != "spikes"]
            if name in filenames:
                out.append(pathlib.Path(dirpath) / name)
        return out

    def _load_manifests(self):
        out = []
        for t in self.targets.values():
            if t["type"] not in ("application", "package"):
                continue
            for s in t["sources"]:
                for f in (self.find("PrivacyInfo.xcprivacy", s) if s.is_dir() else []):
                    if not self._excluded(f):
                        out.append((f, read_plist(f)))
        return out

    def _find_sdk_manifests(self):
        roots = [self.root / "SourcePackages", self.root / "Pods"]
        roots += list(self.root.glob("DerivedData/*/SourcePackages"))
        roots += list(self.root.glob("*/SourcePackages"))
        name = self.root.name if not self.yml else str(self.yml.get("name", self.root.name))
        dd = pathlib.Path.home() / "Library/Developer/Xcode/DerivedData"
        if dd.is_dir():
            roots += list(dd.glob(f"{name}-*/SourcePackages"))
        found = {}
        for r in roots:
            for sub in ("checkouts", "artifacts", ""):
                base = r / sub if sub else r
                if not base.is_dir():
                    continue
                for pkg in base.iterdir():
                    if pkg.is_dir() and pkg.name.lower() not in found:
                        hits = list(pkg.rglob("PrivacyInfo.xcprivacy"))
                        if hits:
                            found[pkg.name.lower()] = hits[0]
        return found

    # ---- languages, StoreKit, kit
    def _load_languages(self):
        langs = {}
        for f in self.source_files({".xcstrings"}):
            try:
                d = json.loads(f.read_text())
            except Exception:
                continue
            if d.get("sourceLanguage"):
                langs.setdefault(d["sourceLanguage"], self.rel(f))
            for v in (d.get("strings") or {}).values():
                for lang in (v.get("localizations") or {}):
                    langs.setdefault(lang, self.rel(f))
        for t in self.targets.values():
            for s in t["sources"]:
                for d in (self.find("*.lproj", s) if s.is_dir() else []):
                    if d.stem != "Base":
                        langs.setdefault(d.stem, self.rel(d))
        return langs

    def _load_storekit(self):
        files = self.find("*.storekit")
        products = []
        for f in files:
            try:
                d = json.loads(f.read_text())
            except Exception:
                continue
            for p in d.get("products") or []:
                products.append({"id": p.get("productID"), "type": p.get("type"), "file": self.rel(f)})
            for g in d.get("subscriptionGroups") or []:
                for p in g.get("subscriptions") or []:
                    products.append({"id": p.get("productID"), "type": "RecurringSubscription",
                                     "group": g.get("name"), "file": self.rel(f)})
        return {"files": files, "products": products}

    def _load_metadata(self):
        out = {}
        if not self.kit:
            return out
        for f in sorted(self.kit.glob("metadata.*.yaml")):
            out[f.name[len("metadata."):-len(".yaml")]] = (f, self._load_yaml(f))
        return out

    # ---- convenience facts
    def dep_matches(self, *needles):
        """Dependencies whose name/url contains any needle (case-insensitive, separators ignored)."""
        def norm(s):
            return re.sub(r"[^a-z0-9]", "", s.lower())
        ns = [norm(n) for n in needles]
        return [d for d in self.deps if any(n in norm(d[0]) or n in norm(d[3]) for n in ns)]

    def imports(self, *modules):
        rx = "|".join(re.escape(m) for m in modules)
        return self.grep(rf"^\s*(@import|import|#import\s*<)\s*({rx})\b")

    def declared_api_types(self):
        types = {}
        for path, d in self.manifests:
            for entry in (d or {}).get("NSPrivacyAccessedAPITypes") or []:
                t = entry.get("NSPrivacyAccessedAPIType", "")
                types.setdefault(t, set()).update(entry.get("NSPrivacyAccessedAPITypeReasons") or [])
        return types

    def xcode_version(self, override=None):
        if override:
            return override, "--xcode"
        if shutil.which("xcodebuild"):
            try:
                out = subprocess.run(["xcodebuild", "-version"], capture_output=True, text=True, timeout=20).stdout
                m = re.search(r"Xcode (\d+(?:\.\d+)*)", out)
                if m:
                    return m.group(1), "xcodebuild -version"
            except Exception:
                pass
        xv = self.root / ".xcode-version"
        if xv.exists():
            return xv.read_text().strip(), ".xcode-version"
        if self.yml and (self.yml.get("options") or {}).get("xcodeVersion"):
            return str(self.yml["options"]["xcodeVersion"]), "project.yml options.xcodeVersion"
        if self.pbx and self.pbx["last_upgrade"]:
            lu = self.pbx["last_upgrade"]
            return f"{int(lu[:-2])}.{int(lu[-2])}", "project.pbxproj LastUpgradeCheck"
        return None, None

    def user_strings(self):
        """(text, evidence) of user-facing strings: string catalogs + common SwiftUI/UIKit literals."""
        out = []
        for f in self.source_files({".xcstrings"}):
            try:
                d = json.loads(f.read_text())
            except Exception:
                continue
            for key, v in (d.get("strings") or {}).items():
                if v.get("shouldTranslate") is False or v.get("extractionState") == "stale":
                    continue
                out.append((key, self.locate(f, json.dumps(key)[1:-1][:60])))
                for loc in (v.get("localizations") or {}).values():
                    val = (loc.get("stringUnit") or {}).get("value")
                    if val and val != key:
                        out.append((val, self.rel(f)))
        rx = re.compile(r'(?:\bText|\bLabel|\bButton|navigationTitle|\bToggle|\bSection|String\(localized:|'
                        r'LocalizedStringKey|\.alert|\.confirmationDialog|\btitle:|\bmessage:)\s*\(?\s*"([^"\\]*)"')
        for l in self.code:
            if not l.debug:
                for m in rx.finditer(l.text):
                    out.append((m.group(1), f"{l.path}:{l.no}"))
        return out

    def metadata_texts(self):
        for loc, (f, d) in self.metadata.items():
            for k, v in d.items():
                if isinstance(v, str):
                    yield loc, k, v, self.locate(f, f"{k}:")


# --------------------------------------------------------------------------- findings


class Result:
    def __init__(self, cat):
        self.cat = cat
        self.findings, self.passes, self.candidates, self.ran = [], [], [], []
        self.decisions = {}

    def _meta(self, cid):
        c = self.cat.get(cid) or {}
        return c.get("guideline", ""), (c.get("sources") or [SHORT_SOURCES["GL"]])[0]

    def fail(self, cid, msg, evidence=(), fix="", severity=None):
        g, src = self._meta(cid)
        sev = severity or (self.cat.get(cid) or {}).get("severity", "WARNING")
        self.findings.append({"id": cid, "severity": sev, "guideline": g, "message": msg,
                              "evidence": list(evidence)[:8], "fix": fix, "source": src})

    def ok(self, cid, msg):
        g, src = self._meta(cid)
        self.passes.append({"id": cid, "guideline": g, "message": msg})

    def ask(self, cid, question, evidence=()):
        g, src = self._meta(cid)
        self.candidates.append({"id": cid, "guideline": g, "question": question,
                                "evidence": list(evidence)[:8], "source": src})


def ev(lines, n=6):
    return [f"{l.path}:{l.no}" for l in lines[:n]]


CHECKS = []


def check(*ids):
    def deco(fn):
        CHECKS.append((ids, fn))
        return fn
    return deco


# --------------------------------------------------------------------------- A. upload blockers


@check("UP-01", "UP-02")
def chk_xcode(p, r, opt):
    ver, src = p.xcode_version(opt.xcode)
    if not ver:
        r.ask("UP-01", "Which Xcode builds the release archive? Uploads need Xcode 26+ with the iOS 26 SDK.")
        return
    major = (version_tuple(ver) or (0,))[0]
    if major < 26:
        r.fail("UP-01", f"Xcode {ver} is too old: uploads must be built with Xcode 26+ and the iOS 26 SDK.",
               [src], "Install Xcode 26 or later and archive with it.")
    else:
        r.ok("UP-01", f"Xcode {ver} ({src}) meets the Xcode 26 / iOS 26 SDK upload minimum.")
    if major < 27:
        sev = "BLOCKER" if opt.today >= dt.date(2027, 4, 1) else "WARNING"
        r.fail("UP-02", f"Xcode {ver}: from April 2027 uploads must use the iOS 27 SDK (Xcode 27).", [src],
               "Plan the move to Xcode 27 before April 2027.", severity=sev)
    else:
        r.ok("UP-02", f"Xcode {ver} already meets the April 2027 iOS 27 SDK minimum.")


@check("UP-03")
def chk_deployment(p, r, opt):
    v = p.settings.get("IPHONEOS_DEPLOYMENT_TARGET")
    t = version_tuple(v)
    if not t:
        r.ask("UP-03", "No IPHONEOS_DEPLOYMENT_TARGET found. What is the minimum iOS version (must be 13+)?")
    elif t < (13,):
        r.fail("UP-03", f"Deployment target iOS {v} is below the iOS 13 minimum for uploads.", ["build settings"],
               "Raise IPHONEOS_DEPLOYMENT_TARGET to 13.0 or later.", severity="BLOCKER")
    elif t < (15,):
        r.fail("UP-03", f"Deployment target iOS {v}: from April 2027 Apple's Submitting page asks for iOS 15+.",
               ["build settings"], "Plan raising the deployment target to iOS 15.", severity="WARNING")
    else:
        r.ok("UP-03", f"Deployment target iOS {v}.")


RR_APIS = {  # category -> (regex, valid reasons)
    "NSPrivacyAccessedAPICategoryFileTimestamp": (
        r"\bcreationDateKey\b|\bcontentModificationDateKey\b|\bcontentModificationDate\b|"
        r"FileAttributeKey\.(creationDate|modificationDate)|\[\s*\.(creationDate|modificationDate)\s*\]|"
        r"NSFile(Creation|Modification)Date|\bfileModificationDate\b|\b[fl]?stat(at)?\s*\([^)]*&|"
        r"\bgetattrlist(bulk|at)?\s*\(|\bfgetattrlist\s*\(",
        {"DDA9.1", "C617.1", "3B52.1", "0A2A.1"}),
    "NSPrivacyAccessedAPICategorySystemBootTime": (
        r"\bsystemUptime\b|\bmach_absolute_time\s*\(", {"35F9.1", "8FFB.1", "3D61.1"}),
    "NSPrivacyAccessedAPICategoryDiskSpace": (
        r"\bvolume(Available|Total)Capacity\w*Key\b|\bsystemFreeSize\b|\bsystemSize\b|\bf?statv?fs\s*\([^)]*&",
        {"85F4.1", "E174.1", "7D9E.1", "B728.1"}),
    "NSPrivacyAccessedAPICategoryActiveKeyboards": (r"\bactiveInputModes\b", {"3EC4.1", "54BD.1"}),
    "NSPrivacyAccessedAPICategoryUserDefaults": (
        r"\bUserDefaults\b|\bNSUserDefaults\b|@AppStorage\b", {"CA92.1", "1C8F.1", "C56D.1", "AC6B.1"}),
}


def rr_uses(p):
    return {cat: hits for cat, (rx, _) in RR_APIS.items() if (hits := p.grep(rx))}


@check("UP-04")
def chk_manifest_present(p, r, opt):
    uses = rr_uses(p)
    if not p.manifests:
        if uses:
            r.fail("UP-04", "No PrivacyInfo.xcprivacy in the app, but it uses required-reason APIs.",
                   [f"{c.split('Category')[-1]}: {ev(h, 1)[0]}" for c, h in uses.items()],
                   "Add PrivacyInfo.xcprivacy to the app target's resources (File > New > App Privacy).")
        else:
            r.fail("UP-04", "No PrivacyInfo.xcprivacy in the app target.", [],
                   "Add a privacy manifest; every app should declare tracking and collected data.",
                   severity="WARNING")
        return
    bad = [pp for pp, d in p.manifests if d is None]
    if bad:
        r.fail("UP-04", "A privacy manifest is not a valid property list.", [p.rel(b) for b in bad],
               "Fix it until `plutil -lint` passes.", severity="BLOCKER")
    else:
        r.ok("UP-04", "Privacy manifest present: " + ", ".join(p.rel(m) for m, _ in p.manifests))


@check("UP-05")
def chk_required_reason(p, r, opt):
    uses, declared = rr_uses(p), p.declared_api_types()
    for cat, hits in uses.items():
        short = cat.replace("NSPrivacyAccessedAPICategory", "")
        valid = RR_APIS[cat][1]
        if cat not in declared:
            r.fail("UP-05", f"Code uses {short} APIs but the privacy manifest declares no {short} reason.",
                   ev(hits), f"Add {cat} to NSPrivacyAccessedAPITypes with the right reason "
                             f"({', '.join(sorted(valid))}).")
            continue
        wrong = declared[cat] - valid
        if wrong or not declared[cat]:
            r.fail("UP-05", f"{short}: reason codes {sorted(wrong) or 'missing'} are not valid for this category.",
                   [p.rel(m) for m, _ in p.manifests], f"Use one of {', '.join(sorted(valid))}.")
            continue
        r.ok("UP-05", f"{short} used ({len(hits)} places) and declared ({', '.join(sorted(declared[cat]))}).")
        if cat.endswith("UserDefaults"):
            suite = p.grep(r"UserDefaults\s*\(\s*suiteName:")
            if suite and "1C8F.1" not in declared[cat]:
                r.fail("UP-05", "UserDefaults(suiteName:) (App Group) is used but reason 1C8F.1 is not declared.",
                       ev(suite), "Add 1C8F.1 if the suite is an App Group shared with extensions.",
                       severity="WARNING")
        r.ask("UP-05", f"Does the declared {short} reason ({', '.join(sorted(declared[cat]))}) match what "
                       f"the code does with it?", ev(hits, 3))
    for cat in set(declared) - set(uses):
        if cat in RR_APIS:
            r.ok("UP-05", f"{cat.replace('NSPrivacyAccessedAPICategory', '')} declared though no direct use "
                          "was found (harmless; maybe used through a wrapper).")


APPLE_SDK_LIST = [  # https://developer.apple.com/support/third-party-SDK-requirements/
    "Abseil", "AFNetworking", "Alamofire", "AppAuth", "BoringSSL", "openssl_grpc", "Capacitor", "Charts",
    "connectivity_plus", "Cordova", "device_info_plus", "DKImagePickerController", "DKPhotoGallery", "FBAEMKit",
    "FBLPromises", "FBSDKCoreKit", "FBSDKCoreKit_Basics", "FBSDKLoginKit", "FBSDKShareKit", "file_picker",
    "FirebaseABTesting", "FirebaseAuth", "FirebaseCore", "FirebaseCoreDiagnostics", "FirebaseCoreExtension",
    "FirebaseCoreInternal", "FirebaseCrashlytics", "FirebaseDynamicLinks", "FirebaseFirestore",
    "FirebaseInstallations", "FirebaseMessaging", "FirebaseRemoteConfig", "Flutter", "flutter_inappwebview",
    "flutter_local_notifications", "fluttertoast", "FMDB", "geolocator_apple", "GoogleDataTransport",
    "GoogleSignIn", "GoogleToolboxForMac", "GoogleUtilities", "grpcpp", "GTMAppAuth", "GTMSessionFetcher",
    "hermes", "image_picker_ios", "IQKeyboardManager", "IQKeyboardManagerSwift", "Kingfisher", "leveldb",
    "Lottie", "MBProgressHUD", "nanopb", "OneSignal", "OneSignalCore", "OneSignalExtension", "OneSignalOutcomes",
    "OpenSSL", "OrderedSet", "package_info", "package_info_plus", "path_provider", "path_provider_ios",
    "Promises", "Protobuf", "Reachability", "RealmSwift", "RxCocoa", "RxRelay", "RxSwift", "SDWebImage",
    "share_plus", "shared_preferences_ios", "SnapKit", "sqflite", "Starscream", "SVProgressHUD", "SwiftyGif",
    "SwiftyJSON", "Toast", "UnityFramework", "url_launcher", "video_player_avfoundation", "wakelock",
    "webview_flutter_wkwebview"]
SDK_PACKAGE_ALIASES = {"firebaseiossdk": "Firebase*", "lottieios": "Lottie", "lottiespm": "Lottie",
                       "realmswift": "RealmSwift", "googlesigniniOS": "GoogleSignIn", "facebookiossdk": "FBSDK*",
                       "gtmsessionfetcher": "GTMSessionFetcher", "appauthios": "AppAuth",
                       "onesignalxcframework": "OneSignal", "abseilcppbinary": "Abseil", "grpcbinary": "grpcpp"}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


@check("UP-06")
def chk_sdk_manifests(p, r, opt):
    listed = {_norm(n): n for n in APPLE_SDK_LIST}
    facts_sdks = {_norm(str(s.get("name", ""))): s for s in (p.facts.get("sdks") or []) if isinstance(s, dict)}
    hits = []
    for name, ver, src, loc in p.deps:
        n = _norm(name)
        for suffix in ("ios", "swift", "sdk", "xcframework", "spm"):
            n2 = n.removesuffix(suffix)
            if n2 in listed or n2 in SDK_PACKAGE_ALIASES:
                n = n2
                break
        sdk = listed.get(n) or SDK_PACKAGE_ALIASES.get(n) or SDK_PACKAGE_ALIASES.get(_norm(name))
        if sdk:
            hits.append((sdk, name, ver, src))
    for imp in p.grep(r"^\s*import\s+(\w+)"):
        mod = re.match(r"^\s*import\s+(\w+)", imp.text).group(1)
        if _norm(mod) in listed and not any(h[0] == listed[_norm(mod)] for h in hits):
            hits.append((listed[_norm(mod)], mod, None, f"{imp.path}:{imp.no}"))
    if not hits:
        r.ok("UP-06", f"No SDK from Apple's privacy-impacting list among {len(p.deps)} dependencies.")
        return
    for sdk, name, ver, src in hits:
        local = p.sdk_manifests.get(name.lower())
        fact = next((v for k, v in facts_sdks.items() if _norm(name) in k or k in _norm(name)), None)
        if local or (fact and fact.get("privacy_manifest")):
            r.ok("UP-06", f"{sdk} ({name} {ver or ''}) ships a privacy manifest "
                          f"({p.rel(local) if local else 'kit facts.yaml'}).")
        else:
            r.fail("UP-06", f"{sdk} ({name} {ver or '?'}) is on Apple's list; no privacy manifest found locally "
                            "to confirm it ships one.", [src],
                   "Use a version that ships PrivacyInfo.xcprivacy (and a signature if binary). "
                   "Resolve packages locally to verify.", severity="WARNING")


@check("UP-07")
def chk_tracking_domains(p, r, opt):
    for path, d in p.manifests:
        d = d or {}
        if d.get("NSPrivacyTracking") and not d.get("NSPrivacyTrackingDomains"):
            r.fail("UP-07", "NSPrivacyTracking is true but NSPrivacyTrackingDomains is empty.", [p.rel(path)],
                   "List the domains that track, or set NSPrivacyTracking false if nothing tracks.")
            return
    trackers = tracking_sdks(p)
    if trackers and not any((d or {}).get("NSPrivacyTracking") for _, d in p.manifests):
        r.ask("UP-07", f"Tracking/ad SDKs are linked ({', '.join(sorted(trackers))}) while the app manifest says "
                       "NSPrivacyTracking false. Do the SDKs' own manifests declare their tracking domains, and does "
                       "the app itself track?", sorted({e for v in trackers.values() for e in v})[:4])
    else:
        r.ok("UP-07", "Tracking flag and tracking domains are consistent.")


PURPOSE = [  # (label, code regex, required keys (any of), extra note)
    ("Photos", r"\bPHPhotoLibrary\b|\bPHAsset\.fetch|\bPHAssetCollection\.fetch|\bPHImageManager\b|\bPHCachingImageManager\b",
     ["NSPhotoLibraryUsageDescription"]),
    ("Photos (add only)", r"\bUIImageWriteToSavedPhotosAlbum\b|\bPHAssetCreationRequest\b|\bPHAssetChangeRequest\.creationRequest",
     ["NSPhotoLibraryAddUsageDescription", "NSPhotoLibraryUsageDescription"]),
    ("Camera", r"\bAVCaptureDevice\b|\bAVCaptureSession\b|sourceType\s*=\s*\.camera\b|\bDataScannerViewController\b",
     ["NSCameraUsageDescription"]),
    ("Microphone", r"\bAVAudioRecorder\b|\.inputNode\b|requestRecordPermission|\.playAndRecord\b|\.record\b\s*[,)]",
     ["NSMicrophoneUsageDescription"]),
    ("Speech recognition", r"\bSFSpeechRecognizer\b", ["NSSpeechRecognitionUsageDescription"]),
    ("Location", r"\bCLLocationManager\b|\bCLLocationUpdate\b|\bCLMonitor\b|\bCLServiceSession\b",
     ["NSLocationWhenInUseUsageDescription", "NSLocationAlwaysAndWhenInUseUsageDescription"]),
    ("Location (always)", r"\brequestAlwaysAuthorization\b", ["NSLocationAlwaysAndWhenInUseUsageDescription"]),
    ("Contacts", r"\bCNContactStore\b", ["NSContactsUsageDescription"]),
    ("Calendars", r"requestFullAccessToEvents|requestWriteOnlyAccessToEvents|requestAccess\(\s*to:\s*\.event",
     ["NSCalendarsFullAccessUsageDescription", "NSCalendarsWriteOnlyAccessUsageDescription",
      "NSCalendarsUsageDescription"]),
    ("Reminders", r"requestFullAccessToReminders|requestAccess\(\s*to:\s*\.reminder",
     ["NSRemindersFullAccessUsageDescription", "NSRemindersUsageDescription"]),
    ("Health (read)", r"\bHKHealthStore\b", ["NSHealthShareUsageDescription"]),
    ("Health (write)", r"toShare:\s*(?!nil\b|\[\]|Set\(\))\S", ["NSHealthUpdateUsageDescription"]),
    ("Bluetooth", r"\bCBCentralManager\b|\bCBPeripheralManager\b", ["NSBluetoothAlwaysUsageDescription"]),
    ("Motion", r"\bCMMotionManager\b|\bCMPedometer\b|\bCMMotionActivityManager\b|\bCMAltimeter\b",
     ["NSMotionUsageDescription"]),
    ("Face ID", r"\bdeviceOwnerAuthenticationWithBiometrics\b|\.deviceOwnerAuthentication\b",
     ["NSFaceIDUsageDescription"]),
    ("Tracking (ATT)", r"\bATTrackingManager\b", ["NSUserTrackingUsageDescription"]),
    ("Local network", r"\bNWBrowser\b|\bNetServiceBrowser\b|\bNWListener\b|\bMCNearbyService\w+|\bMCBrowserViewController\b",
     ["NSLocalNetworkUsageDescription"]),
    ("Bonjour services", r"\bNWBrowser\b|\bNetServiceBrowser\b|\bMCNearbyServiceBrowser\b", ["NSBonjourServices"]),
    ("Media library", r"\bMPMediaLibrary\b|\bMPMediaQuery\b|\bMusicAuthorization\b", ["NSAppleMusicUsageDescription"]),
    ("HomeKit", r"\bHMHomeManager\b", ["NSHomeKitUsageDescription"]),
    ("NFC", r"\bNFCNDEFReaderSession\b|\bNFCTagReaderSession\b", ["NFCReaderUsageDescription"]),
    ("Siri", r"requestSiriAuthorization", ["NSSiriUsageDescription"]),
    ("Nearby Interaction", r"\bNISession\b", ["NSNearbyInteractionUsageDescription"]),
]


@check("UP-08")
def chk_purpose_strings(p, r, opt):
    used = 0
    for label, rx, keys in PURPOSE:
        hits = p.grep(rx)
        if not hits:
            continue
        used += 1
        have = [k for k in keys if k in p.info]
        if have:
            r.ok("UP-08", f"{label}: used and {have[0]} is set.")
        else:
            r.fail("UP-08", f"{label} API is used but {keys[0]} is missing from Info.plist.", ev(hits),
                   f"Add {keys[0]} with a concrete reason (what and why) to the app's Info.plist.")
    if not used:
        r.ok("UP-08", "No protected-resource API found in the app code.")


PLACEHOLDER_PURPOSE = re.compile(r"^\s*$|\b(todo|tbd|fixme|lorem|placeholder|test)\b|^\$\(PRODUCT_NAME\)|"
                                 r"^we need (access|permission)\.?$|^(this app|app) (needs|requires) access", re.I)


@check("UP-09")
def chk_purpose_quality(p, r, opt):
    keys = [k for k in p.info if k.endswith("UsageDescription") or k == "NFCReaderUsageDescription"]
    for k in keys:
        v = str(p.info[k] or "")
        if PLACEHOLDER_PURPOSE.search(v) or len(v.strip()) < 25:
            r.fail("UP-09", f"{k} is empty, generic or a placeholder: \"{v}\".", [p.info_where.get(k, k)],
                   "Say what the app does with the data and why, with an example (5.1.1(ii)).")
        else:
            r.ok("UP-09", f"{k} has a specific text ({len(v)} characters).")
    if keys:
        r.ask("UP-09", "Does each purpose string say concretely what the access is used for (with an example)?",
              [f"{k}: {str(p.info[k])[:90]}" for k in keys])


@check("UP-10")
def chk_launch(p, r, opt):
    i, s = p.info, p.settings
    if "UILaunchScreen" in i or "UILaunchStoryboardName" in i or \
            str(s.get("INFOPLIST_KEY_UILaunchScreen_Generation", "")).upper() == "YES":
        key = "UILaunchScreen" if "UILaunchScreen" in i else "UILaunchStoryboardName"
        r.ok("UP-10", f"Launch screen declared ({key}).")
    elif "UILaunchImages" in i:
        r.fail("UP-10", "Only legacy UILaunchImages: a launch storyboard or UILaunchScreen is required.",
               [p.info_where.get("UILaunchImages", "")], "Add UILaunchScreen (dict) or a launch storyboard.")
    else:
        r.fail("UP-10", "No launch screen (UILaunchScreen or UILaunchStoryboardName) in Info.plist.",
               [p.rel(p.info_path) if p.info_path else "Info.plist"],
               "Add `UILaunchScreen: {}` or a LaunchScreen storyboard.")


def png_info(path):
    """(width, height, has_alpha) from a PNG header, stdlib only."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(33)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        w, h, _, color = struct.unpack(">IIBB", head[16:26])
        return w, h, color in (4, 6)
    except OSError:
        return None


@check("UP-11")
def chk_icon(p, r, opt):
    name = p.settings.get("ASSETCATALOG_COMPILER_APPICON_NAME", "AppIcon")
    icons = [f for f in p.find(f"{name}.icon") if f.is_dir()]
    if icons:
        r.ok("UP-11", f"Icon Composer file {p.rel(icons[0])} (Xcode generates all sizes and appearances).")
        return
    sets = [f for f in p.find(f"{name}.appiconset") if not TEST_DIR.search(p.rel(f))]
    if not sets:
        r.fail("UP-11", f"No app icon: neither {name}.icon nor {name}.appiconset found.", [],
               "Add an Icon Composer .icon or an AppIcon set with a 1024x1024 opaque PNG.")
        return
    contents = json.loads((sets[0] / "Contents.json").read_text()) if (sets[0] / "Contents.json").exists() else {}
    images = [im for im in contents.get("images", []) if im.get("filename")]
    big = [im for im in images if im.get("size") in ("1024x1024",)]
    if not big:
        r.fail("UP-11", "App icon set has no 1024x1024 image.", [p.rel(sets[0])], "Add the 1024x1024 marketing icon.")
        return
    for im in big:
        if im.get("appearances"):
            continue
        pi = png_info(sets[0] / im["filename"])
        if pi and (pi[:2] != (1024, 1024) or pi[2]):
            r.fail("UP-11", f"{im['filename']} is {pi[0]}x{pi[1]}{' with alpha' if pi[2] else ''}; "
                            "it must be 1024x1024 and opaque.", [p.rel(sets[0] / im["filename"])],
                   "Export the icon as an opaque 1024x1024 PNG.")
            return
    r.ok("UP-11", f"App icon set {p.rel(sets[0])} with a 1024x1024 image.")
    if not any(im.get("appearances") for im in images):
        r.fail("UP-11", "App icon has no dark or tinted variants.", [p.rel(sets[0])],
               "Add dark and tinted appearances (or move to an Icon Composer .icon).", severity="WARNING")


@check("UP-12")
def chk_encryption(p, r, opt):
    v = p.info.get("ITSAppUsesNonExemptEncryption")
    if v is None:
        r.fail("UP-12", "ITSAppUsesNonExemptEncryption is missing: every build waits for the export-compliance "
                        "questions in App Store Connect.", [p.rel(p.info_path) if p.info_path else "Info.plist"],
               "Add ITSAppUsesNonExemptEncryption = NO if the app only uses exempt (HTTPS/OS) encryption.")
        return
    truthy = str(v).lower() in ("true", "yes", "1")
    if truthy and "ITSEncryptionExportComplianceCode" not in p.info:
        r.fail("UP-12", "ITSAppUsesNonExemptEncryption is YES but ITSEncryptionExportComplianceCode is missing.",
               [p.info_where.get("ITSAppUsesNonExemptEncryption", "")], "Add the compliance code from App Store Connect.")
        return
    r.ok("UP-12", f"ITSAppUsesNonExemptEncryption = {'YES' if truthy else 'NO'}.")
    crypto = p.grep(r"\bCCCrypt\b|\bimport\s+(OpenSSL|CryptoSwift|Sodium|BoringSSL)\b|\bEVP_\w+\(|\bcrypto_box\w*\(")
    crypto += [type("D", (), {"path": d[2], "no": 0})() for d in p.dep_matches("openssl", "cryptoswift", "libsodium")]
    if not truthy and crypto:
        r.ask("UP-12", "The key says no non-exempt encryption, but crypto libraries/calls are present. Is all of it "
                       "exempt (HTTPS, OS crypto, authentication only)?",
              [f"{c.path}:{c.no}" if c.no else c.path for c in crypto[:5]])


@check("UP-13")
def chk_device_caps(p, r, opt):
    if "UIRequiredDeviceCapabilities" in p.info:
        r.ok("UP-13", f"UIRequiredDeviceCapabilities = {p.info['UIRequiredDeviceCapabilities']}.")
        r.ask("UP-13", "For an update: does UIRequiredDeviceCapabilities keep or relax the last release's list "
                       "(never add requirements)?", [p.info_where.get("UIRequiredDeviceCapabilities", "")])
    else:
        r.fail("UP-13", "UIRequiredDeviceCapabilities is not set. Apple's key reference says apps must include it; "
                        "current Xcode templates omit it and uploads without it are accepted (UNCONFIRMED either way).",
               [p.rel(p.info_path) if p.info_path else "Info.plist"],
               "Optional: add UIRequiredDeviceCapabilities [arm64] (never add requirements in a later update).",
               severity="WARNING")


@check("UP-14")
def chk_game_center(p, r, opt):
    hits = p.grep(r"\bGKLocalPlayer\b|\bGKGameCenterViewController\b|^\s*import\s+GameKit\b")
    if not hits:
        return
    if p.entitlements.get("com.apple.developer.game-center"):
        r.ok("UP-14", "GameKit used and the Game Center entitlement is present.")
    else:
        r.fail("UP-14", "GameKit is used but the com.apple.developer.game-center entitlement is missing.", ev(hits),
               "Enable the Game Center capability and configure Game Center in App Store Connect.")


@check("UP-15")
def chk_receipts(p, r, opt):
    hits = p.grep(r"\bappStoreReceiptURL\b|\bPKCS7\b|AppleIncRootCertificate")
    if hits:
        r.ask("UP-15", "On-device receipt validation found. Does it support SHA-256 certificates? StoreKit 2 "
                       "AppTransaction/Transaction is the safer route.", ev(hits))


@check("UP-16")
def chk_private_api(p, r, opt):
    hits = p.grep(r'NSClassFromString\(\s*@?"_|performSelector[:(]\s*(NSSelectorFromString\()?\s*@?"_|'
                  r'dlopen\(.*PrivateFrameworks|valueForKey[:(]\s*@?"_|\bLSApplicationWorkspace\b|'
                  r'UIApplication\.shared\.perform\(|NSSelectorFromString\(\s*@?"_')
    if hits:
        r.ask("UP-16", "Possible private API use (Apple scans binaries for these). Are these public APIs?", ev(hits))
    else:
        r.ok("UP-16", "No private-API patterns found.")


@check("UP-17")
def chk_downloaded_code(p, r, opt):
    hits = p.grep(r"\bdlopen\s*\(|\bJSContext\b.*evaluateScript|\.evaluateScript\(|Bundle\(\s*path:|"
                  r"NSBundle\s+bundleWithPath|\bCodePush\b|\bexpo-updates\b|\bEXUpdates\b")
    hits += [type("D", (), {"path": d[2], "no": 0})() for d in p.dep_matches("codepush", "expoupdates")]
    if hits:
        r.ask("UP-17", "Code loading or evaluation at runtime found. Does any of it run code downloaded after "
                       "review that changes features (2.5.2)?", [f"{h.path}:{h.no}" if h.no else h.path for h in hits[:6]])


@check("UP-18")
def chk_bundle_id(p, r, opt):
    bid = p.settings.get("PRODUCT_BUNDLE_IDENTIFIER", "")
    if re.match(r"(com\.example|org\.reactjs\.native\.example|com\.yourcompany)\b", bid, re.I):
        r.fail("UP-18", f"Bundle identifier {bid} is a template placeholder.", ["PRODUCT_BUNDLE_IDENTIFIER"],
               "Use your own reverse-DNS bundle ID.", severity="BLOCKER")
    elif bid:
        r.ok("UP-18", f"Bundle identifier {bid}.")
    # resolved like the build does: plist value, $(MARKETING_VERSION) reference, INFOPLIST_KEY_, build setting
    ver, ver_where = p.info_value("CFBundleShortVersionString", "MARKETING_VERSION")
    if not ver:
        r.fail("UP-18", "CFBundleShortVersionString is empty (no plist value, INFOPLIST_KEY_ or MARKETING_VERSION).",
               ["Info.plist", ver_where], "Set MARKETING_VERSION.", severity="BLOCKER")
    name = str(p.info.get("CFBundleDisplayName", "") or "")
    if len(name) > 30:
        r.fail("UP-18", f"CFBundleDisplayName is {len(name)} characters (over 30).",
               [p.info_where.get("CFBundleDisplayName", "")], "Shorten the home-screen name.",
               severity="LIKELY REJECTION")
    elif name and name.lower() in ("myapp", "my app", "app", "untitled", "helloworld", "hello world"):
        r.fail("UP-18", f"Display name '{name}' looks like a template name.", [p.info_where.get("CFBundleDisplayName", "")],
               "Use the real app name.", severity="LIKELY REJECTION")
    kit_build = str((p.facts.get("app") or {}).get("build", "") or "")
    proj_build, build_where = p.info_value("CFBundleVersion", "CURRENT_PROJECT_VERSION")
    if kit_build and proj_build and kit_build != proj_build:
        r.fail("UP-18", f"Kit facts say build {kit_build} but the project has CFBundleVersion {proj_build} "
                        f"({build_where}).",
               ["facts.yaml app.build"], "Update facts.yaml; each upload needs a new, higher build number.",
               severity="WARNING")


# --------------------------------------------------------------------------- B. privacy

AD_SDKS = {"GoogleMobileAds": ("googlemobileads", "GoogleMobileAds"), "AppLovin": ("applovin", "AppLovinSDK"),
           "Meta Audience Network": ("fbaudiencenetwork", "FBAudienceNetwork"), "Unity Ads": ("unityads", "UnityAds"),
           "ironSource": ("ironsource", "IronSource"), "Vungle/Liftoff": ("vungle", "VungleAdsSDK"),
           "InMobi": ("inmobi", "InMobiSDK"), "Chartboost": ("chartboost", "ChartboostSDK"),
           "Mintegral": ("mintegral", "MTGSDK"), "Pangle": ("pangle", "PAGAdSDK"),
           "Yandex Ads": ("yandexmobileads", "YandexMobileAds")}
ATTRIBUTION_SDKS = {"AppsFlyer": ("appsflyer", "AppsFlyerLib"), "Adjust": ("adjust", "AdjustSdk"),
                    "Branch": ("branch", "BranchSDK"), "Singular": ("singular", "Singular"),
                    "Kochava": ("kochava", "KochavaTracker"), "Facebook SDK": ("facebookiossdk", "FBSDKCoreKit"),
                    "Tenjin": ("tenjin", "TenjinSDK")}
ANALYTICS_SDKS = {"Firebase Analytics": ("firebaseanalytics", "FirebaseAnalytics"), "Mixpanel": ("mixpanel", "Mixpanel"),
                  "Amplitude": ("amplitude", "AmplitudeSwift"), "Segment": ("segment", "Segment"),
                  "PostHog": ("posthog", "PostHog"), "Sentry": ("sentry", "Sentry"),
                  "Crashlytics": ("crashlytics", "FirebaseCrashlytics"), "Datadog": ("datadog", "DatadogCore"),
                  "Bugsnag": ("bugsnag", "Bugsnag"), "TelemetryDeck": ("telemetrydeck", "TelemetryDeck"),
                  "App Center": ("appcenter", "AppCenter")}


def sdk_present(p, table):
    out = {}
    for label, (dep, module) in table.items():
        e = [d[2] for d in p.dep_matches(dep)] + ev(p.imports(module), 2)
        if e:
            out[label] = e
    return out


def tracking_sdks(p):
    return {**sdk_present(p, AD_SDKS), **sdk_present(p, ATTRIBUTION_SDKS)}


@check("PR-01")
def chk_privacy_in_app(p, r, opt):
    url_hits = p.grep(r"https?://[^\s\"]*privacy", re.I)
    files = sorted({f for t in p.targets.values() if t["type"] == "application" for s in t["sources"] if s.is_dir()
             for f in p.find("*rivacy*", s) if f.suffix in (".md", ".html", ".txt", ".rtf", ".pdf")})
    strings = [s for s, _ in p.user_strings() if re.search(r"privacy", s, re.I)]
    if url_hits or files:
        r.ok("PR-01", "Privacy policy reachable in the app: " +
             (", ".join(ev(url_hits, 2)) if url_hits else ", ".join(p.rel(f) for f in files[:2])))
    elif strings:
        r.ask("PR-01", "A 'privacy' string exists but no privacy URL or bundled policy was found. Where does it "
                       "lead?", strings[:3])
    else:
        r.fail("PR-01", "No privacy policy link or bundled policy found in the app.", [],
               "Add a Privacy Policy link (e.g. Settings › About) to a live page.")


@check("PR-02")
def chk_privacy_url_kit(p, r, opt):
    if not p.kit:
        return
    urls = p.facts.get("urls") or {}
    meta = [d.get("privacy_policy_url") or d.get("privacy_url") for _, (f, d) in p.metadata.items()]
    url = urls.get("privacy_policy") or next((m for m in meta if m), None)
    if url:
        r.ok("PR-02", f"Privacy policy URL in the kit: {url}")
    else:
        r.fail("PR-02", "No privacy policy URL in the kit (facts.yaml urls.privacy_policy).",
               [p.rel(p.kit / "facts.yaml")], "Add the live privacy policy URL; App Store Connect requires it.",
               severity="BLOCKER")


@check("PR-03")
def chk_label_vs_code(p, r, opt):
    sdks = {**tracking_sdks(p), **sdk_present(p, ANALYTICS_SDKS)}
    collected = sorted({c.get("NSPrivacyCollectedDataType", "?") for _, d in p.manifests
                        for c in (d or {}).get("NSPrivacyCollectedDataTypes") or []})
    has_label = p.kit and any(p.kit.glob("privacy*"))
    if sdks or collected:
        r.ask("PR-03", f"Do the App Privacy answers{' in the kit' if has_label else ''} cover the data these collect? "
                       f"SDKs: {', '.join(sorted(sdks)) or 'none'}; app manifest collected types: "
                       f"{', '.join(collected) or 'none'}.", sorted({e for v in sdks.values() for e in v})[:4])


@check("PR-04")
def chk_att(p, r, opt):
    trackers = tracking_sdks(p)
    idfa = p.grep(r"\badvertisingIdentifier\b|ASIdentifierManager")
    tracking_flag = any((d or {}).get("NSPrivacyTracking") for _, d in p.manifests)
    if not (trackers or idfa or tracking_flag):
        r.ok("PR-04", "No tracking SDK, IDFA access or NSPrivacyTracking: ATT not needed.")
        return
    why = ", ".join(sorted(trackers)) or ("IDFA access" if idfa else "NSPrivacyTracking true")
    evid = sorted({e for v in trackers.values() for e in v})[:4] + ev(idfa, 2)
    if "NSUserTrackingUsageDescription" not in p.info:
        r.fail("PR-04", f"Tracking-capable code is linked ({why}) but NSUserTrackingUsageDescription is missing.",
               evid, "Add NSUserTrackingUsageDescription and call ATTrackingManager.requestTrackingAuthorization "
                     "before any tracking.")
        return
    req = p.grep(r"requestTrackingAuthorization")
    if not req:
        r.fail("PR-04", f"NSUserTrackingUsageDescription is set ({why}) but requestTrackingAuthorization is never "
                        "called.", evid, "Ask for ATT before the SDK tracks (or drop the key if nothing tracks).")
        return
    r.ok("PR-04", f"ATT: NSUserTrackingUsageDescription set and requestTrackingAuthorization called ({why}).")
    r.ask("PR-04", "Is the ATT prompt shown before the tracking/ad SDK starts or loads its first ad?",
          ev(req, 3) + ev(p.grep(r"MobileAds\.shared\.start|GADMobileAds|AppsFlyerLib\.shared\(\)\.start|"
                                 r"Adjust\.(appDidLaunch|initSdk)"), 3))


@check("PR-05")
def chk_att_eu(p, r, opt):
    hits = p.grep(r"preferExpandedInterface")
    if hits and "NSUserTrackingMarkdownUsageDescription" not in p.info:
        r.fail("PR-05", "The expanded (EU) ATT prompt is requested but NSUserTrackingMarkdownUsageDescription is "
                        "missing.", ev(hits), "Add NSUserTrackingMarkdownUsageDescription (iOS 27.2+).")


@check("PR-06")
def chk_forced_permissions(p, r, opt):
    hits = p.grep(r"requestAuthorization\(|requestTrackingAuthorization|requestWhenInUseAuthorization|"
                  r"requestAlwaysAuthorization|requestAccess\(")
    if hits:
        r.ask("PR-06", "Can the user decline each permission and still use the app (no gate, no 'Continue'-only "
                       "pre-prompt, no reward for allowing)?", ev(hits))


@check("PR-07")
def chk_minimization(p, r, opt):
    full = p.grep(r"PHPhotoLibrary\.requestAuthorization|PHPhotoLibrary\.authorizationStatus")
    contacts = p.grep(r"\bCNContactStore\b")
    if full or contacts:
        r.ask("PR-07", "Full Photos/Contacts access is requested. Does the core feature need it, or would "
                       "PhotosPicker / CNContactPickerViewController do (5.1.1(iii))?", ev(full + contacts))


AI_ENDPOINTS = (r"api\.openai\.com|api\.anthropic\.com|generativelanguage\.googleapis\.com|api\.mistral\.ai|"
                r"api\.x\.ai|api\.replicate\.com|replicate\.com/v1|openrouter\.ai|api\.groq\.com|api\.cohere\.|"
                r"api\.deepseek\.com|api\.perplexity\.ai|aiplatform\.googleapis\.com|api\.together\.xyz")
AI_SDKS = {"OpenAI": ("openai", "OpenAI"), "Anthropic": ("anthropic", "Anthropic"),
           "Google Generative AI": ("generativeaiswift", "GoogleGenerativeAI"),
           "Firebase AI Logic / Vertex AI": ("firebaseai", "FirebaseAI"), "MacPaw OpenAI": ("macpawopenai", "OpenAI"),
           "SwiftAnthropic": ("swiftanthropic", "SwiftAnthropic"), "SwiftOpenAI": ("swiftopenai", "SwiftOpenAI")}


@check("PR-08")
def chk_third_party_ai(p, r, opt):
    hits = p.grep(AI_ENDPOINTS, re.I)
    sdks = sdk_present(p, AI_SDKS)
    if not (hits or sdks):
        fm = p.imports("FoundationModels")
        r.ok("PR-08", "No third-party AI endpoint or SDK found" +
             (" (Foundation Models runs on device)." if fm else "."))
        return
    evid = ev(hits, 4) + sorted({e for v in sdks.values() for e in v})[:4]
    r.fail("PR-08", "Third-party AI is called (" + ", ".join(sorted(sdks) or ["AI endpoint"]) +
           "). 5.1.2(i): disclose what personal data goes to it and get explicit permission before the first send.",
           evid, "Add a consent screen naming the AI provider; store the choice before any request.",
           severity="WARNING")
    r.ask("PR-08", "Is personal data (user text, photos, voice) sent to the AI provider, and is there an explicit "
                   "opt-in shown before the first request?", evid)


@check("PR-10")
def chk_recording(p, r, opt):
    hits = p.grep(r"\bRPScreenRecorder\b|\bAVAudioRecorder\b|\bAVCaptureSession\b|\.inputNode\b")
    if hits:
        r.ask("PR-10", "Camera/microphone/screen capture is used. Is there explicit consent and a visible "
                       "indicator while recording (2.5.14)?", ev(hits))


@check("PR-11")
def chk_healthkit(p, r, opt):
    hits = p.grep(r"\bHKHealthStore\b")
    if hits:
        r.ask("PR-11", "HealthKit is used. Is health data kept out of iCloud, analytics and ads, and does the "
                       "description mention the HealthKit integration?", ev(hits))


@check("PR-12")
def chk_contacts_upload(p, r, opt):
    hits = p.grep(r"enumerateContacts|unifiedContacts\(")
    if hits:
        r.ask("PR-12", "Contacts are enumerated. Is the whole contact book ever uploaded or messaged without "
                       "per-contact user action (5.1.2(iv))?", ev(hits))


@check("PR-13")
def chk_safari_hidden(p, r, opt):
    files = {l.path for l in p.grep(r"\bSFSafariViewController\b")}
    hidden = [l for l in p.grep(r"\.alpha\s*=\s*0(\.0)?\b|frame:\s*\.zero|isHidden\s*=\s*true") if l.path in files]
    if hidden:
        r.ask("PR-13", "SFSafariViewController appears next to hiding code. Is it ever hidden or used to track?",
              ev(hidden))


@check("PR-14")
def chk_location_always(p, r, opt):
    hits = p.grep(r"requestAlwaysAuthorization|allowsBackgroundLocationUpdates")
    if hits or "location" in (p.info.get("UIBackgroundModes") or []):
        r.ask("PR-14", "Always/background location is used. Is there a clear user-facing feature that needs it, "
                       "and a manual fallback when denied (5.1.5)?", ev(hits))


@check("PR-15")
def chk_kids_data(p, r, opt):
    if not p.facts.get("kids_category"):
        return
    sdks = {**sdk_present(p, ANALYTICS_SDKS), **sdk_present(p, ATTRIBUTION_SDKS)}
    if sdks:
        r.fail("PR-15", "Kids Category app links third-party analytics/attribution SDKs: " + ", ".join(sorted(sdks)),
               sorted({e for v in sdks.values() for e in v})[:6], "Remove them (1.3, 5.1.4).")
    idfa = p.grep(r"\badvertisingIdentifier\b|identifierForVendor")
    if idfa:
        r.fail("PR-15", "Kids Category app reads device identifiers.", ev(idfa), "Remove IDFA/IDFV use.")


SECRET_RX = (r'"sk-[A-Za-z0-9_-]{20,}"|"sk-ant-[A-Za-z0-9_-]{20,}"|"AIza[0-9A-Za-z_-]{35}"|'
             r'"(ghp|gho|github_pat)_[A-Za-z0-9_]{20,}"|(api[_-]?key|secret|token)\s*[:=]\s*"[A-Za-z0-9_\-]{24,}"')


@check("PR-16")
def chk_data_security(p, r, opt):
    ats = p.info.get("NSAppTransportSecurity") or {}
    if isinstance(ats, dict) and str(ats.get("NSAllowsArbitraryLoads", "")).lower() in ("true", "yes", "1"):
        r.fail("PR-16", "NSAllowsArbitraryLoads is YES: App Transport Security is off.",
               [p.info_where.get("NSAppTransportSecurity", "Info.plist")], "Allow only the domains that need it.")
    http = [l for l in p.grep(r'"http://(?!localhost|127\.0\.0\.1|www\.apple\.com/DTDs)', re.I)]
    if http:
        r.fail("PR-16", "Plain http:// URLs in shipped code.", ev(http), "Use https://.")
    secrets = p.grep(SECRET_RX, re.I)
    if secrets:
        r.fail("PR-16", "Hard-coded API keys or secrets in the source.", ev(secrets),
               "Move secrets to a server or the Keychain; rotate any key that shipped.")
    ud = p.grep(r"UserDefaults.*\b(set|forKey)\b.*\b(token|password|secret|apiKey)\b", re.I)
    if ud:
        r.fail("PR-16", "Tokens or passwords stored in UserDefaults.", ev(ud), "Store them in the Keychain.")
    if not (http or secrets or ud):
        r.ok("PR-16", "No plain-HTTP URLs, hard-coded secrets or credentials in UserDefaults found.")


# --------------------------------------------------------------------------- C. payments

PURCHASE_RX = r"\bProduct\.products\(for:|\.purchase\(|\bSKPaymentQueue\b|\bSKProductsRequest\b|\bStoreView\b|" \
              r"\bProductView\b|\bSubscriptionStoreView\b|\bRevenueCat\b|\bPurchases\.shared\b"
RESTORE_RX = r"AppStore\.sync\(|restoreCompletedTransactions|\.restorePurchases\b|restorePurchases\(|" \
             r"Purchases\.shared\.restorePurchases"


@check("PAY-01")
def chk_external_payments(p, r, opt):
    sdks = p.dep_matches("stripe", "paypal", "braintree", "paddle", "adyen")
    hits = p.grep(r"\b(Stripe|PayPal|Braintree|PaymentSheet)\b|license\s*key|promo\s*code|redeem\s*code", re.I)
    if sdks or hits:
        r.ask("PAY-01", "External payment or code-redemption signals found. Do they unlock digital content or "
                        "features (must use IAP, 3.1.1) or only physical goods/services?",
              [d[2] for d in sdks][:3] + ev(hits, 4))


@check("PAY-02")
def chk_restore(p, r, opt):
    buys = p.grep(PURCHASE_RX)
    prods = p.storekit["products"]
    if not buys and not prods:
        r.ok("PAY-02", "No in-app purchase code found.")
        return
    if prods and all(x.get("type") == "Consumable" for x in prods):
        r.ok("PAY-02", "Only consumable products: no restore needed.")
        return
    restore = p.grep(RESTORE_RX)
    if restore:
        r.ok("PAY-02", f"Restore mechanism present ({ev(restore, 1)[0]}).")
        r.ask("PAY-02", "Is the Restore Purchases control visible to the user (not only called at launch)?",
              ev(restore, 3))
    elif p.grep(r"Transaction\.currentEntitlements"):
        r.fail("PAY-02", "Purchases exist and entitlements are refreshed, but there is no explicit Restore "
                         "Purchases action (AppStore.sync()).", ev(buys, 3),
               "Add a visible Restore Purchases button that calls AppStore.sync().")
    else:
        r.fail("PAY-02", "In-app purchase code found but no restore mechanism.", ev(buys, 3),
               "Add a visible Restore Purchases button (StoreKit 2: AppStore.sync()).")


def code_product_ids(p):
    known = {x["id"] for x in p.storekit["products"] if x.get("id")}
    out = {}
    for l in p.grep(r"(?i)product|sku|iap"):
        for m in re.finditer(r'"([A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){2,})"', l.text):
            out.setdefault(m.group(1), f"{l.path}:{l.no}")
    for l in p.code:
        for m in re.finditer(r'"([^"]+)"', l.text):
            if m.group(1) in known:
                out.setdefault(m.group(1), f"{l.path}:{l.no}")
    bid = p.settings.get("PRODUCT_BUNDLE_IDENTIFIER", "")
    return {k: v for k, v in out.items() if k in known or (bid and k.startswith(bid.rsplit(".", 1)[0]) and k != bid
                                                           and not k.startswith(bid + ".widgets"))}


@check("PAY-03")
def chk_product_ids(p, r, opt):
    sk = {x["id"]: x for x in p.storekit["products"] if x.get("id")}
    kit = {}
    for item in ((p.facts.get("monetization") or {}).get("iap") or []):
        if isinstance(item, dict) and item.get("product_id"):
            kit[item["product_id"]] = "facts.yaml"
    for loc, (f, d) in p.metadata.items():
        for item in d.get("iap") or []:
            if isinstance(item, dict) and item.get("product_id"):
                kit.setdefault(item["product_id"], p.rel(f))
    code = code_product_ids(p) if p.grep(PURCHASE_RX) else {}
    if not (sk or kit or code):
        return
    problems = False
    if sk:
        for pid, where in code.items():
            if pid not in sk and not re.search(r"\.(widgets?|index|viewPhoto)$", pid):
                if any(pid.startswith(k) for k in sk) or "pro" in pid or "premium" in pid or "sub" in pid:
                    r.fail("PAY-03", f"Product ID {pid} is used in code but not in the StoreKit configuration.",
                           [where], "Add it to the .storekit file and App Store Connect, or fix the ID.")
                    problems = True
    for pid, where in kit.items():
        if sk and pid not in sk:
            r.fail("PAY-03", f"Kit lists product {pid} but the StoreKit configuration does not.", [where],
                   "Make the kit, the .storekit file and App Store Connect use the same IDs.")
            problems = True
    for pid, x in sk.items():
        if kit and pid not in kit:
            r.fail("PAY-03", f"StoreKit product {pid} is missing from the kit's IAP list.", [x["file"]],
                   "Add it to facts.yaml monetization.iap and metadata iap.", severity="WARNING")
            problems = True
        if code and pid not in code:
            r.fail("PAY-03", f"StoreKit product {pid} is never referenced in code.", [x["file"]],
                   "Remove it or load it with Product.products(for:).", severity="WARNING")
            problems = True
    if not problems:
        r.ok("PAY-03", f"Product IDs agree across code, StoreKit config and kit: {', '.join(sorted(sk or kit))}.")
    r.ask("PAY-03", "Are these IAPs created in App Store Connect and attached to this version for review?",
          sorted(sk or kit))


@check("PAY-04")
def chk_paywall_prices(p, r, opt):
    hard = p.grep(r'"[^"]*([$€£¥]\s?\d+[.,]\d{2}|\d+[.,]\d{2}\s?(USD|EUR|€))[^"]*"')
    if hard:
        r.fail("PAY-04", "Hard-coded prices in the UI; show Product.displayPrice instead.", ev(hard),
               "Use Product.displayPrice so every storefront sees its own price.")
    subs = [x for x in p.storekit["products"] if x.get("type") == "RecurringSubscription"] or \
        p.grep(r"\bsubscriptionPeriod\b|\bSubscriptionStoreView\b")
    if subs:
        r.ask("PAY-04", "Does the paywall show, before purchase, what the user gets, price per period, period, "
                        "trial terms, auto-renew wording, and Terms/Privacy links (3.1.2(c))?",
              ev(p.grep(r"displayPrice|introductoryOffer|subscriptionPeriod"), 4))


@check("PAY-06")
def chk_sub_groups(p, r, opt):
    groups = {x.get("group") for x in p.storekit["products"] if x.get("group")}
    if len(groups) > 1:
        r.ask("PAY-06", f"{len(groups)} subscription groups ({', '.join(sorted(groups))}). Are they really different "
                        "services, not tiers of one thing (3.1.2(b))?", [p.rel(f) for f in p.storekit["files"]])


@check("PAY-07")
def chk_paywall_dark_patterns(p, r, opt):
    files = {l.path for l in p.code if re.search(r"paywall|upgrade|subscribe", l.path, re.I)}
    hits = [l for l in p.grep(r"\.delay\(|opacity\(\s*0(\.0\d*)?\s*\)|countdown|Timer\.publish")
            if l.path in files]
    if hits:
        r.ask("PAY-07", "Paywall code delays or hides elements or uses timers. Is the close button visible at once, "
                        "and are there no fake countdowns or pre-selected expensive plans?", ev(hits))


@check("PAY-10")
def chk_review_prompt(p, r, opt):
    custom = p.grep(r"action=write-review|itms-apps://")
    native = p.grep(r"requestReview|SKStoreReviewController")
    if custom and not native:
        r.fail("PAY-10", "Custom review prompt deep-links to the App Store write-review page instead of the "
                         "system prompt.", ev(custom), "Use requestReview (StoreKit) for in-app review prompts.")
    elif custom:
        r.ask("PAY-10", "Both the system review prompt and a write-review deep link exist. Is the deep link only "
                        "behind an explicit 'Write a review' action?", ev(custom))
    elif native:
        r.ok("PAY-10", "Review prompts use the system API.")


# --------------------------------------------------------------------------- D. accounts

SIGNUP_RX = (r"\bcreateUser\(|\bAuth\.auth\(\)|\bsignUp\(|\bregister(User|Account)\(|\"/(register|signup|sign-up)\b|"
             r"\bAuth0\b|\bCognito\b|Amplify\.Auth|supabase\.auth|\bClerk\b|\bASAuthorizationAppleIDProvider\b|"
             r"\bsignInAnonymously\(|\bGIDSignIn\b|\bLoginManager\(\)")
SOCIAL_RX = (r"\bGIDSignIn\b|\bFBSDKLoginKit\b|\bLoginManager\(\)|\bFBLoginButton\b|accounts\.google\.com/o/oauth2|"
             r"facebook\.com/(v[\d.]+/)?dialog/oauth|api\.twitter\.com/oauth|twitter\.com/i/oauth2|"
             r"linkedin\.com/oauth|amazon\.com/ap/oa|\bLineSDK\b|\bWXApi\b|\bTwitterKit\b")
SIWA_RX = r"\bASAuthorizationAppleIDButton\b|\bSignInWithAppleButton\b|\bASAuthorizationAppleIDProvider\b"


def account_signals(p):
    hits = p.grep(SIGNUP_RX)
    deps = p.dep_matches("firebaseauth", "auth0", "supabase", "amplify", "googlesignin", "clerk", "facebookiossdk")
    return hits, deps


@check("AC-01")
def chk_account_deletion(p, r, opt):
    hits, deps = account_signals(p)
    if not (hits or deps):
        r.ok("AC-01", "No account creation found: account deletion not required.")
        return
    delete = p.grep(r"\bdeleteUser\b|\bdeleteAccount\b|user\??\.delete\(|\"DELETE\".*account|account.*\"DELETE\"|"
                    r"delete[_ ]?account|Delete Account", re.I)
    ui = [s for s, w in p.user_strings() if re.search(r"delete (my |your )?account", s, re.I)]
    evid = ev(hits, 4) + [d[2] for d in deps][:2]
    if delete or ui:
        r.ok("AC-01", "Account creation found and an account-deletion path exists.")
        r.ask("AC-01", "Does in-app account deletion fully delete the account (not deactivate) without email/phone "
                       "steps, and is it easy to find?", ev(delete, 4))
    else:
        r.fail("AC-01", "Accounts can be created but no in-app account deletion was found.", evid,
               "Add Settings › Delete Account that deletes the account and its data (5.1.1(v)).")


@check("AC-02")
def chk_siwa_revoke(p, r, opt):
    siwa = p.grep(r"\bASAuthorizationAppleIDProvider\b") or p.entitlements.get("com.apple.developer.applesignin")
    if siwa and not p.grep(r"auth/revoke|revokeToken|revoke_token", re.I):
        r.ask("AC-02", "Sign in with Apple is used. Does account deletion revoke the Apple token server-side "
                       "(appleid.apple.com/auth/revoke)?", ev(siwa) if isinstance(siwa, list) else ["entitlements"])


@check("AC-03")
def chk_login_equivalent(p, r, opt):
    social = p.grep(SOCIAL_RX) + [type("D", (), {"path": d[2], "no": 0})()
                                  for d in p.dep_matches("googlesignin", "facebookiossdk", "linesdk")]
    if not social:
        return
    if p.grep(SIWA_RX) or p.entitlements.get("com.apple.developer.applesignin"):
        r.ok("AC-03", "Third-party login is offered together with Sign in with Apple.")
    else:
        r.fail("AC-03", "Third-party login (Google/Facebook/...) without Sign in with Apple or an equivalent "
                        "privacy-preserving option (4.8).",
               [f"{h.path}:{h.no}" if h.no else h.path for h in social[:6]],
               "Add Sign in with Apple, unless an exemption applies (company/education accounts, that service's client).")


@check("AC-04", "AC-05", "AC-07")
def chk_login_wall(p, r, opt):
    hits, deps = account_signals(p)
    if not (hits or deps):
        return
    r.ask("AC-04", "Can the core features be used without logging in? If they are local-only, a login wall is "
                   "a rejection (5.1.1(v)).", ev(hits, 3))
    r.ask("AC-05", "Are name/email fields optional unless the feature truly needs them?",
          ev(p.grep(r"\bemail\b", re.I), 3))
    notes = p.kit and any(p.kit.glob("review-notes*"))
    r.ask("AC-07", "Login exists: is there a working demo account in the review notes" +
          (" (review-notes found in the kit)" if notes else "") + ", and is the backend reachable?", [])


@check("AC-06")
def chk_relay_domain(p, r, opt):
    hits = p.grep(r"privaterelay\.appleid\.com")
    if hits and not p.grep(r"private\.icloud\.com"):
        r.fail("AC-06", "Code checks for privaterelay.appleid.com but not the new private.icloud.com relay domain.",
               ev(hits), "Accept both relay domains.")


@check("AC-08")
def chk_face_auth(p, r, opt):
    hits = p.grep(r"\bARFaceTrackingConfiguration\b|\bARFaceAnchor\b")
    if hits:
        r.ask("AC-08", "ARKit face tracking is used. Is it ever used for authentication (must be LocalAuthentication)?",
              ev(hits))


# --------------------------------------------------------------------------- E. content and safety


@check("CS-01")
def chk_ugc(p, r, opt):
    hits = p.grep(r"\b(postComment|sendMessage|createPost|uploadPost|publishPost|StreamChat|SendbirdChat|"
                  r"PubNub|TwilioConversations|ChatClient)\b")
    if hits:
        r.ask("CS-01", "User-generated content or chat found. Are a content filter, Report, Block and published "
                       "contact info all present (1.2)?", ev(hits))


ADS_RX = r"\b(GADBannerView|BannerView|InterstitialAd|GADInterstitialAd|RewardedAd|NativeAd|GADNativeAd|MAAdView)\b"


def ads_present(p):
    return sdk_present(p, AD_SDKS)


@check("CS-04")
def chk_kids_ads(p, r, opt):
    if not p.facts.get("kids_category"):
        return
    ads = ads_present(p)
    if ads:
        r.fail("CS-04", "Kids Category app with third-party ads: " + ", ".join(sorted(ads)),
               sorted({e for v in ads.values() for e in v})[:6],
               "Remove ads or use a kids-certified ad service with human-reviewed ads (1.3).")
    links = p.grep(r"UIApplication\.shared\.open|\bopenURL\b|\bLink\(|SFSafariViewController")
    if links:
        r.ask("CS-04", "Kids Category: is every external link and purchase behind a parental gate?", ev(links))


@check("CS-05")
def chk_age_rating(p, r, opt):
    signals = []
    web = p.grep(r"\bWKWebView\b|\bSFSafariViewController\b")
    if web:
        signals.append(f"web content ({ev(web, 1)[0]}) → Unrestricted Web Access if users can browse any URL")
    if ads_present(p):
        signals.append("ads SDK → Advertising: yes")
    if p.grep(r"\b(StreamChat|SendbirdChat|postComment|sendMessage)\b"):
        signals.append("chat/UGC → User-Generated Content, Messaging")
    rating = p.connect.get("age_rating") if isinstance(p.connect, dict) else None
    if isinstance(rating, dict):
        rating = rating.get("expected_rating") or rating.get("rating") or "answers present"
    r.ask("CS-05", "Do the age-rating answers match the code signals" + (f" (kit: {rating})" if rating else "") +
          "? " + ("; ".join(signals) or "no web view, ads or UGC found") +
          ". The social-media questions are required since September 2026.", [])


@check("CS-07")
def chk_medical(p, r, opt):
    rx = re.compile(r"blood pressure|glucose|spo2|oxygen saturation|body temperature|heart rate", re.I)
    hits = [(s, w) for s, w in p.user_strings() if rx.search(s)]
    hits += [(v, w) for _, _, v, w in p.metadata_texts() if rx.search(v)]
    if hits:
        r.ask("CS-07", "Medical measurements are mentioned. Does the app claim to measure them with device sensors "
                       "alone, and does it remind users to consult a doctor (1.4.1)?", [w for _, w in hits[:5]])


@check("CS-09")
def chk_ads_in_extensions(p, r, opt):
    bad = []
    for name, t in p.targets.items():
        if t["type"] in ("application", "package", "framework", "library.static", "library.dynamic"):
            continue
        deps = [d.get("package") or d.get("framework") or "" for d in (t.get("yml") or {}).get("dependencies") or []]
        bad += [f"{name} depends on {d}" for d in deps if any(_norm(k) in _norm(d) or _norm(v[1]) in _norm(d)
                                                                for k, v in AD_SDKS.items())]
    mods = "|".join(v[1] for v in AD_SDKS.values())
    bad += ev(p.grep(rf"^\s*import\s+({mods})\b", lines=p.ext_code))
    if bad:
        r.fail("CS-09", "Ad SDK used in an extension; ads are allowed only in the main app binary (2.5.18).", bad,
               "Remove the ad SDK from widget/notification/keyboard/App Clip targets.")
    elif ads_present(p):
        r.ok("CS-09", "Ads only in the main app target.")
        r.ask("CS-09", "Do the ads match the age rating, offer a way to report an ad, and have a visible "
                       "close/skip on interstitials?", ev(p.grep(ADS_RX), 3))


@check("CS-10")
def chk_push_live_activities(p, r, opt):
    reg = p.grep(r"registerForRemoteNotifications")
    if reg and "aps-environment" not in p.entitlements:
        r.fail("CS-10", "registerForRemoteNotifications is called but the aps-environment entitlement is missing.",
               ev(reg), "Enable the Push Notifications capability.", severity="WARNING")
    la = p.grep(r"\bActivity<|Activity\.request\(|\bActivityConfiguration\b|ActivityAttributes\b", include_debug=False)
    if p.info.get("NSSupportsLiveActivities") or la:
        evid = [p.info_where.get("NSSupportsLiveActivities", "")] if p.info.get("NSSupportsLiveActivities") else []
        r.ask("CS-10", "Live Activities are present. 4.5.3 (June 2026): they must not be used for spam, phishing "
                       "or unsolicited messages. Are they only started by a user action for that task?",
              [e for e in evid if e] + ev(la, 3))
    marketing = p.grep(r"(?i)marketing|promo(tional)?\s*notification")
    if reg and marketing:
        r.ask("CS-10", "Marketing pushes: is there explicit opt-in and an in-app opt-out (4.5.4)?", ev(marketing, 3))


@check("CS-11")
def chk_media_download(p, r, opt):
    hits = p.grep(r"(youtube|instagram|soundcloud|tiktok)[^\n]*(download|save)|(download|save)[^\n]*"
                  r"(youtube|instagram|soundcloud|tiktok)", re.I)
    if hits:
        r.ask("CS-11", "Third-party media download/save found. Is it authorized by that service (5.2.3)?", ev(hits))


@check("CS-12")
def chk_regulated(p, r, opt):
    hits = p.grep(r"\bNEVPNManager\b|\bNETunnelProviderManager\b|^\s*import\s+(web3|Web3|WalletConnect\w*)\b")
    if hits:
        r.ask("CS-12", "VPN or crypto features found. Is the developer account an organization with the needed "
                       "licences (5.1.1(ix), 5.4)?", ev(hits))


# --------------------------------------------------------------------------- F. design and functionality

PLACEHOLDER_RX = re.compile(r"\blorem\b|\bipsum\b|\bTODO\b|\bTBD\b|\bFIXME\b|\bplaceholder\b|\basdf\b|"
                            r"hello,? world|coming soon|\[title\]|test@|example\.com|item at \\\(", re.I)


@check("DF-01")
def chk_placeholders(p, r, opt):
    found = [(s, w) for s, w in p.user_strings() if PLACEHOLDER_RX.search(s)]
    meta = [(v, w) for _, k, v, w in p.metadata_texts() if k not in ("review_notes",) and
            (PLACEHOLDER_RX.search(v) or re.search(r"\btest(ing)?\b", v, re.I))]
    for s, w in (found + meta)[:10]:
        r.fail("DF-01", f"Placeholder text in user-facing copy: \"{s[:70]}\"", [w],
               "Replace it with the real text.")
    nimpl = p.grep(r'fatalError\(\s*"(Not implemented|TODO|unimplemented)', re.I)
    if nimpl:
        r.fail("DF-01", "fatalError(\"Not implemented\") in shipped code.", ev(nimpl), "Implement or remove it.")
    stale = []
    for f in p.source_files({".xcstrings"}):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        src = d.get("sourceLanguage")
        for key, v in (d.get("strings") or {}).items():
            for lang, loc in (v.get("localizations") or {}).items():
                if lang != src and (loc.get("stringUnit") or {}).get("state") in ("new", "needs_review"):
                    stale.append(f"{p.rel(f)} [{lang}] {key[:40]}")
    if stale:
        r.fail("DF-01", f"{len(stale)} translations are untranslated or need review.", stale[:6],
               "Translate or review them in the String Catalog.", severity="WARNING")
    if not (found or meta or nimpl):
        r.ok("DF-01", "No placeholder text in UI strings, string catalogs or kit metadata.")


@check("DF-02")
def chk_crash_patterns(p, r, opt):
    hits = p.grep(r"\bfatalError\(|\btry!\s|\bas!\s")
    if hits:
        r.ask("DF-02", f"{len(hits)} crash points (fatalError, try!, as!) in shipped code. Can any of them be "
                       "hit with real data (network, JSON, user library)?", ev(hits))


@check("DF-03")
def chk_debug_beta(p, r, opt):
    staging = p.grep(r'"[^"]*(localhost|127\.0\.0\.1|staging\.|\.ngrok|ngrok\.io|192\.168\.)[^"]*"', re.I)
    if staging:
        r.fail("DF-03", "Staging or local server URL in shipped (non-DEBUG) code.", ev(staging),
               "Wrap it in #if DEBUG or remove it.")
    beta = [(s, w) for s, w in p.user_strings() if re.search(r"\b(beta|trial version|demo version)\b", s, re.I)]
    beta += [(v, w) for _, k, v, w in p.metadata_texts() if k in ("name", "subtitle") and
             re.search(r"\b(beta|demo|trial)\b", v, re.I)]
    for s, w in beta[:5]:
        r.fail("DF-03", f"Beta/demo wording in user-facing text: \"{s[:70]}\"", [w], "Remove it (2.2).")
    menus = p.grep(r"\b(struct|class)\s+\w*Debug\w*(View|Menu|Panel|Settings)\b|\"Debug (Menu|Settings)\"")
    tf = p.grep(r"isTestFlight|sandboxReceipt")
    if menus or tf:
        r.ask("DF-03", "Debug menus or TestFlight checks outside #if DEBUG. Can a reviewer reach them, or do they "
                       "expose unfinished features?", ev(menus + tf))
    if not (staging or beta):
        r.ok("DF-03", "No staging URLs or beta wording in shipped code and copy.")


def kit_urls(p):
    out = []
    for k, v in (p.facts.get("urls") or {}).items():
        if isinstance(v, str) and v.startswith("http"):
            out.append((v, f"facts.yaml urls.{k}"))
    for loc, (f, d) in p.metadata.items():
        for k, v in d.items():
            if k.endswith("url") and isinstance(v, str) and v.startswith("http"):
                out.append((v, p.locate(f, f"{k}:")))
    return out


def fetch_status(url, timeout=10):
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method, headers={"User-Agent": "app-store-kit-precheck"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            if method == "GET" or e.code not in (403, 405, 501):
                return e.code
        except Exception as e:  # DNS, TLS, timeout
            if method == "GET":
                return str(e)[:60]
    return None


@check("DF-04")
def chk_links(p, r, opt):
    urls = kit_urls(p)
    links = p.grep(r'Link\(\s*destination:\s*URL\(string:\s*"https?://|openURL.*"https?://|'
                   r'UIApplication\.shared\.open\(URL\(string:\s*"https?://')
    for l in links:
        m = re.search(r'"(https?://[^"]+)"', l.text)
        if m:
            urls.append((m.group(1), f"{l.path}:{l.no}"))
    bad = [(u, w) for u, w in urls if re.search(r"example\.com|localhost|your(domain|site)", u, re.I)]
    for u, w in bad:
        r.fail("DF-04", f"Placeholder URL {u}.", [w], "Use the real, live URL.")
    if not urls:
        return
    if not opt.check_urls:
        r.ask("DF-04", f"{len(urls)} URLs were not fetched (run with --check-urls). Do they all load real pages?",
              [f"{u} ({w})" for u, w in urls[:6]])
        return
    for u, w in dict((u, w) for u, w in urls).items():
        st = fetch_status(u)
        if st == 200 or (isinstance(st, int) and 200 <= st < 400):
            r.ok("DF-04", f"{u} → {st}")
        else:
            r.fail("DF-04", f"{u} does not load (status {st}).", [w], "Fix the page or the link.")


@check("DF-05")
def chk_contact(p, r, opt):
    hits = p.grep(r"mailto:|support@|/contact|/support", re.I)
    strings = [w for s, w in p.user_strings() if re.search(r"contact|support|feedback|get help", s, re.I)]
    if hits or strings:
        r.ok("DF-05", "In-app contact/support entry found (" + (ev(hits, 1) or strings[:1])[0] + ").")
    else:
        r.fail("DF-05", "No in-app way to contact the developer (mailto, support link) was found.", [],
               "Add a Contact/Support row with an email or the support URL (1.5).", severity="WARNING")


@check("DF-06")
def chk_web_wrapper(p, r, opt):
    web = p.grep(r"\bWKWebView\b")
    views = p.grep(r":\s*(some\s+)?View\b|:\s*UIViewController\b")
    if web and len(views) < 8:
        r.ask("DF-06", f"WKWebView with only {len(views)} native views. Is the app more than a wrapped website (4.2)?",
              ev(web))


@check("DF-08")
def chk_first_download(p, r, opt):
    hits = p.grep(r"\bBADownloadManager\b|\bBAManifest\b|\bNSBundleResourceRequest\b|downloadTask\(|"
                  r"URLSession\.shared\.download\(|\.download\(from:")
    if hits:
        r.ask("DF-08", "The app downloads content. Is the size stated and does the user start it (no silent large "
                       "first-launch download), and does the app work without it (4.2.3)?", ev(hits))


BG_MODES = {
    "audio": r"\.playback\b|\.playAndRecord\b|AVAudioSession.*setCategory",
    "location": r"allowsBackgroundLocationUpdates|startMonitoringSignificantLocationChanges|CLBackgroundActivitySession",
    "voip": r"\bPKPushRegistry\b",
    "fetch": r"BGAppRefreshTask|setMinimumBackgroundFetchInterval|\.appRefresh\(",
    "processing": r"BGProcessingTask|BGContinuedProcessingTask",
    "remote-notification": r"registerForRemoteNotifications|didReceiveRemoteNotification",
    "bluetooth-central": r"\bCBCentralManager\b",
    "bluetooth-peripheral": r"\bCBPeripheralManager\b",
    "external-accessory": r"\bEAAccessoryManager\b|\bEASession\b",
    "nearby-interaction": r"\bNISession\b",
}


@check("DF-09")
def chk_background_modes(p, r, opt):
    modes = p.info.get("UIBackgroundModes") or []
    where = p.info_where.get("UIBackgroundModes", "Info.plist")
    permitted = set(p.info.get("BGTaskSchedulerPermittedIdentifiers") or [])
    for mode in modes:
        rx = BG_MODES.get(mode)
        if not rx:
            continue
        hits = p.grep(rx)
        if not hits:
            r.fail("DF-09", f"UIBackgroundModes declares '{mode}' but no code uses it.", [where],
                   f"Remove '{mode}' or add the feature that needs it (2.5.4).")
            continue
        if mode in ("processing", "fetch") and not permitted:
            r.fail("DF-09", f"'{mode}' background mode without BGTaskSchedulerPermittedIdentifiers.", [where],
                   "List every task identifier in BGTaskSchedulerPermittedIdentifiers.")
            continue
        r.ok("DF-09", f"Background mode '{mode}' is used ({ev(hits, 1)[0]}).")
    reg_ids = {}
    for l in p.grep(r'forTaskWithIdentifier:\s*"([^"]+)"|BG\w+TaskRequest\(identifier:\s*"([^"]+)"|'
                    r'\.(appRefresh|urlSession)\(\s*"([^"]+)"'):
        for m in re.finditer(r'"([^"]+)"', l.text):
            reg_ids.setdefault(m.group(1), f"{l.path}:{l.no}")
    missing = {k: v for k, v in reg_ids.items() if k not in permitted and "." in k}
    if missing:
        r.fail("DF-09", "Background task identifiers used in code but not in BGTaskSchedulerPermittedIdentifiers "
                        "(scheduling fails at runtime): " + ", ".join(sorted(missing)), list(missing.values()),
               "Add them to BGTaskSchedulerPermittedIdentifiers.", severity="WARNING")
    if p.grep(r"BGProcessingTaskRequest") and "processing" not in modes:
        r.fail("DF-09", "BGProcessingTaskRequest is used but 'processing' is not in UIBackgroundModes.",
               ev(p.grep(r"BGProcessingTaskRequest"), 2), "Add 'processing' to UIBackgroundModes.",
               severity="WARNING")
    if "audio" in modes:
        r.ask("DF-09", "'audio' background mode: is audio actually audible to the user (no silent audio to keep "
                       "the app alive)?", [where])


@check("DF-10")
def chk_liquid_glass_optout(p, r, opt):
    v = p.info.get("UIDesignRequiresCompatibility")
    if str(v).lower() in ("true", "yes", "1"):
        major = (version_tuple(p.xcode_version(opt.xcode)[0]) or (0,))[0]
        extra = " With Xcode 27 / the iOS 27 SDK the key is already ignored." if major >= 27 else \
            " It is ignored once you build with the iOS 27 SDK (required from April 2027)."
        r.fail("DF-10", "UIDesignRequiresCompatibility = YES opts out of Liquid Glass temporarily." + extra,
               [p.info_where.get("UIDesignRequiresCompatibility", "")], "Remove it and test the UI in the new design.")
    else:
        r.ok("DF-10", "No Liquid Glass compatibility opt-out.")


@check("DF-11")
def chk_ipad_full_screen(p, r, opt):
    if str(p.info.get("UIRequiresFullScreen", "")).lower() in ("true", "yes", "1"):
        r.fail("DF-11", "UIRequiresFullScreen is deprecated in iPadOS 26 and forces compatibility mode in windowed "
                        "iPad multitasking.", [p.info_where.get("UIRequiresFullScreen", "")],
               "Remove it and support resizable layouts.")
    fam = p.settings.get("TARGETED_DEVICE_FAMILY", "1")
    if "2" in fam:
        ipad = p.info.get("UISupportedInterfaceOrientations~ipad") or p.info.get("UISupportedInterfaceOrientations")
        if not ipad or len(ipad) < 4:
            r.fail("DF-11", "iPad is supported but not all four orientations are declared for iPad.",
                   [p.info_where.get("UISupportedInterfaceOrientations~ipad", "Info.plist")],
                   "Declare all four orientations in UISupportedInterfaceOrientations~ipad.")
        else:
            r.ok("DF-11", "iPad declares all four orientations.")


@check("DF-12")
def chk_iphone_only(p, r, opt):
    fam = p.settings.get("TARGETED_DEVICE_FAMILY", "1")
    if "2" not in fam:
        r.ask("DF-12", "iPhone-only app: reviewers may run it on iPad in compatibility mode. Does every screen "
                       "work there (2.4.1)?", ev(p.grep(r"userInterfaceIdiom\s*==\s*\.pad"), 3))


@check("DF-13")
def chk_screen_assumptions(p, r, opt):
    hits = p.grep(r"UIScreen\.main\.(bounds|scale|nativeBounds)|UIDevice\.current\.orientation|"
                  r"statusBarOrientation|\binterfaceOrientation\b|userInterfaceIdiom\s*[!=]=\s*\.(pad|phone)|"
                  r"UIWindow\(frame:\s*UIScreen\.main|[=<>]=?\s*(844|852|874|896|926|932|956)\b")
    if hits:
        r.fail("DF-13", f"{len(hits)} screen-size or device assumptions (UIScreen.main, idiom, orientation). "
                        "Apple's iPhone Duo guide flags these; with the iOS 27.1 SDK bars become vertical.", ev(hits),
               "Use the view's own size (GeometryReader, size classes, trait collection) instead.")
    else:
        r.ok("DF-13", "No UIScreen.main / idiom / orientation layout assumptions found.")


@check("DF-14")
def chk_ipv4(p, r, opt):
    hits = [l for l in p.grep(r'"[^"]*\b\d{1,3}(\.\d{1,3}){3}\b[^"]*"|\binet_addr\(|\bAF_INET\b(?!6)')
            if not re.search(r'"\d+\.\d+\.\d+\.\d+"\s*[,)]?\s*//\s*version', l.text)]
    hits = [l for l in hits if not re.search(r"version|\bv\d", l.text, re.I)]
    if hits:
        r.fail("DF-14", "IPv4 literal addresses or IPv4-only sockets; App Review tests on IPv6-only networks.",
               ev(hits), "Use host names and dual-stack APIs (URLSession, Network.framework).")


@check("DF-15")
def chk_browser_engines(p, r, opt):
    deps = p.dep_matches("geckoview", "chromium", "cef", "blink")
    if deps:
        r.fail("DF-15", "Bundled third-party browser engine: " + ", ".join(d[0] for d in deps), [d[2] for d in deps],
               "Use WebKit unless you hold the browser-engine entitlement (EU/Japan).")


@check("DF-19")
def chk_keyboard_ext(p, r, opt):
    kb = []
    for f in p.find("Info.plist"):
        d = read_plist(f) or {}
        if ((d.get("NSExtension") or {}).get("NSExtensionPointIdentifier")) == "com.apple.keyboard-service":
            kb.append(f)
    for t in p.targets.values():
        ext = (((t.get("yml") or {}).get("info") or {}).get("properties") or {}).get("NSExtension") or {}
        if ext.get("NSExtensionPointIdentifier") == "com.apple.keyboard-service":
            kb.append(p.root / "project.yml")
    if not kb:
        return
    if p.grep(r"advanceToNextInputMode|handleInputModeList"):
        r.ok("DF-19", "Keyboard extension has a next-keyboard control.")
    else:
        r.fail("DF-19", "Keyboard extension without a next-keyboard button (advanceToNextInputMode).",
               [p.rel(k) for k in kb], "Add the globe/next-keyboard key (4.4.1).")
    r.ask("DF-19", "Does the keyboard work without Full Access (RequestsOpenAccess) and never launch other apps?",
          [p.rel(k) for k in kb])


@check("DF-22")
def chk_framework_mentioned(p, r, opt):
    uses = {"HealthKit": r"\bHKHealthStore\b", "HomeKit": r"\bHMHomeManager\b", "SiriKit": r"\bINExtension\b|"
            r"\bINIntent\b"}
    desc = " ".join(str(d.get("description", "")) for _, (f, d) in p.metadata.items())
    for fw, rx in uses.items():
        hits = p.grep(rx)
        if hits and p.metadata and fw.replace("Kit", "").lower() not in desc.lower():
            r.ask("DF-22", f"{fw} is used but the store description does not mention it (2.5.1). Should it?", ev(hits, 3))


@check("DF-23")
def chk_js_bridges(p, r, opt):
    hits = p.grep(r"\bWKScriptMessageHandler\b|addScriptMessageHandler")
    if hits:
        r.ask("DF-23", "Native APIs are exposed to web content via script message handlers. Can downloaded code "
                       "reach camera/location/contacts without per-use consent (4.7)?", ev(hits))


# --------------------------------------------------------------------------- G. metadata


@check("MD-01")
def chk_store_name(p, r, opt):
    disp = str(p.info.get("CFBundleDisplayName", "") or "")
    for loc, (f, d) in p.metadata.items():
        name = str(d.get("name", "") or "")
        if not name:
            continue
        if len(name) > 30:
            r.fail("MD-01", f"[{loc}] App Store name is {len(name)} characters (max 30).",
                   [p.locate(f, "name:")], "Shorten it to 30 characters.", severity="BLOCKER")
        elif disp and not disp.startswith("$(") and disp.lower() not in name.lower():
            r.fail("MD-01", f"[{loc}] Store name \"{name}\" does not contain the home-screen name \"{disp}\".",
                   [p.locate(f, "name:"), p.info_where.get("CFBundleDisplayName", "")],
                   "Keep the two names similar (2.3.8).", severity="WARNING")
        else:
            r.ok("MD-01", f"[{loc}] Store name \"{name}\" ({len(name)}/30) matches the display name.")


@check("MD-02")
def chk_other_platforms(p, r, opt):
    rx = re.compile(r"\b(android|google play|play store|windows phone|\bapk\b)", re.I)
    hits = [w for _, k, v, w in p.metadata_texts() if k != "review_notes" and rx.search(v)]
    hits += [w for s, w in p.user_strings() if rx.search(s)]
    if hits:
        r.fail("MD-02", "Other platforms (Android, Google Play...) are mentioned in metadata or UI.", hits,
               "Remove references to other platforms (2.3.10).")
    elif p.metadata:
        r.ok("MD-02", "No other platforms mentioned.")


@check("MD-03")
def chk_free_claims(p, r, opt):
    paid = p.facts.get("has_iap") or p.facts.get("has_ads") or p.facts.get("has_subscription")
    price = re.compile(r"[$€£]\s?\d|\d+[.,]\d{2}\s?(usd|eur)", re.I)
    for loc, k, v, w in p.metadata_texts():
        if k in ("name", "subtitle") and price.search(v):
            r.fail("MD-03", f"[{loc}] Price in the {k}: \"{v}\".", [w], "Remove prices from name and subtitle.")
        if paid and k in ("name", "subtitle", "promotional_text") and \
                re.search(r"\b(free|no ads|lifetime|unlimited)\b", v, re.I):
            r.ask("MD-03", f"[{loc}] {k} says \"{v[:60]}\" while the app has IAP/ads. Is the claim accurate (2.3.2)?",
                  [w])


@check("MD-04")
def chk_duo_screens(p, r, opt):
    if not p.kit or not (p.kit / "screenshots").is_dir():
        return
    from validate_kit import load_rules, slot_requirement, images_in
    rules = load_rules(kit=p.kit)
    for loc in sorted(x for x in (p.kit / "screenshots").iterdir() if x.is_dir()):
        present = {d.name for d in loc.iterdir() if d.is_dir() and images_in(d)}
        if not any(s.startswith("iphone-") for s in present):
            continue
        for sid, slot in rules["screenshots"]["slots"].items():
            if not sid.startswith("iphone-duo-") or sid in present:
                continue
            state = slot_requirement(slot, opt.today, p.facts, present)
            if state == "optional":
                continue
            detail = " Build SDK is unknown in facts.yaml; the SDK condition cannot be checked." if state == "unknown" else ""
            r.fail("MD-04", f"[{loc.name}] Missing {sid}. {slot.get('required_note', '')}{detail}",
                   [p.rel(loc)], "Record the release build SDK in facts.yaml and add required captures.",
                   severity="BLOCKER" if state == "required" else "WARNING")



@check("MD-05")
def chk_for_kids(p, r, opt):
    if p.facts.get("kids_category"):
        return
    hits = [w for _, k, v, w in p.metadata_texts() if re.search(r"\bfor (kids|children)\b", v, re.I)]
    if hits:
        r.fail("MD-05", "\"For Kids/Children\" wording outside the Kids Category.", hits, "Remove it (2.3.8).")


@check("MD-07")
def chk_whats_new(p, r, opt):
    if not p.metadata or p.facts.get("first_version", True):
        return
    for loc, (f, d) in p.metadata.items():
        if not str(d.get("whats_new", "") or "").strip():
            r.fail("MD-07", f"[{loc}] What's New is empty for an update.", [p.rel(f)],
                   "Describe the significant changes (2.3.12).")


@check("MD-09")
def chk_required_fields(p, r, opt):
    if not p.kit:
        return
    urls = p.facts.get("urls") or {}
    for loc, (f, d) in p.metadata.items() or [("facts", (p.kit / "facts.yaml", {}))]:
        support = d.get("support_url") or urls.get("support")
        copyright_ = d.get("copyright") or p.facts.get("copyright")
        kw = d.get("keywords")
        kw = ",".join(kw) if isinstance(kw, list) else str(kw or "")
        missing = [n for n, v in (("support URL", support), ("copyright", copyright_)) if not v]
        if missing:
            r.fail("MD-09", f"[{loc}] Missing required field(s): {', '.join(missing)}.", [p.rel(f)],
                   "Fill them in the kit before App Store Connect.")
        elif len(kw.encode()) > 100:
            r.fail("MD-09", f"[{loc}] Keywords are {len(kw.encode())} bytes (max 100).", [p.locate(f, "keywords:")],
                   "Trim the keywords.")
        else:
            r.ok("MD-09", f"[{loc}] Support URL, copyright and keywords ({len(kw.encode())}/100 bytes) present.")


def _store_languages(p):
    locs = list(p.facts.get("locales") or [])
    locs += [l for l in p.metadata if l not in locs]
    return locs


def _lang_supported(store_loc, app_langs):
    s = store_loc.replace("_", "-")
    cands = {s, s.split("-")[0]}
    if s.startswith("zh"):
        cands = {s, "zh-Hans" if s in ("zh-Hans", "zh-CN") else "zh-Hant", "zh"}
    if s == "es-MX":
        cands |= {"es-419"}
    return any(c in app_langs for c in cands) or any(a.split("-")[0] == s.split("-")[0] for a in app_langs
                                                     if not s.startswith("zh"))


@check("LOC-01")
def chk_store_languages(p, r, opt):
    if not p.kit:
        return
    store = _store_languages(p)
    app = set(p.languages)
    if not store or not app:
        return
    missing = [s for s in store if not _lang_supported(s, app)]
    for s in missing:
        r.fail("LOC-01", f"Store locale {s} is listed in the kit but the app has no {s.split('-')[0]} "
                         f"localization (app: {', '.join(sorted(app))}).", [p.rel(p.kit / 'facts.yaml')],
               f"Add {s.split('-')[0]} to the String Catalogs, or drop {s} from the store languages.")
    if not missing:
        r.ok("LOC-01", f"Every store locale ({', '.join(store)}) has an app localization.")


# --------------------------------------------------------------------------- run and report


def run(p, cat, opt):
    r = Result(cat)
    for ids, fn in CHECKS:
        try:
            fn(p, r, opt)
        except Exception as e:  # one broken check must not hide the rest
            r.ask(ids[0], f"Check crashed ({type(e).__name__}: {e}); review {', '.join(ids)} by hand.")
        r.ran.extend(ids)
    if p.kit:
        decisions = p._load_yaml(p.kit / "precheck-decisions.yaml")
        if isinstance(decisions, dict):
            r.decisions = {cid: row for cid, row in decisions.items() if isinstance(row, dict)
                           and row.get("decision") in ("ok", "fixed", "n/a")
                           and isinstance(row.get("why"), str) and row["why"].strip()}
    return r


def undecided(r):
    return [cid for cid in not_covered(r.cat) if cid not in r.decisions]


def implemented_counts(cat):
    ids = {i for ids, _ in CHECKS for i in ids}
    auto = sorted(i for i in ids if cat.get(i, {}).get("detect", "").startswith("Auto"))
    semi = sorted(i for i in ids if i not in auto)
    return auto, semi


def summary(r):
    s = {sev: sum(1 for f in r.findings if f["severity"] == sev) for sev in SEVERITIES}
    s["PASS"] = len(r.passes)
    s["FOR CLAUDE"] = len(r.candidates)
    s["NOT SCANNED"] = len(undecided(r))
    return s


def exit_code(r, strict=False):
    sevs = {f["severity"] for f in r.findings}
    if "BLOCKER" in sevs:
        return 2
    if undecided(r) or "LIKELY REJECTION" in sevs or (strict and "WARNING" in sevs):
        return 1
    return 0


def not_covered(cat):
    ids = {i for ids, _ in CHECKS for i in ids}
    return sorted(k for k in cat if k not in ids)


def to_markdown(p, r, cat, opt):
    s = summary(r)
    out = [f"# Pre-check: {p.yml.get('name') if p.yml else p.root.name}", "",
           f"Project `{p.root}`" + (f", kit `{p.kit}`" if p.kit else "") + f". Run {opt.today.isoformat()} "
           "against references/precheck-rules.md (App Review Guidelines of June 8, 2026).", "",
           "| BLOCKER | LIKELY REJECTION | WARNING | PASS | For Claude to judge | Not scanned, undecided |", "|---|---|---|---|---|---|",
           f"| {s['BLOCKER']} | {s['LIKELY REJECTION']} | {s['WARNING']} | {s['PASS']} | {s['FOR CLAUDE']} | {s['NOT SCANNED']} |", ""]
    for sev in SEVERITIES:
        items = [f for f in r.findings if f["severity"] == sev]
        out += [f"## {sev} ({len(items)})", ""]
        if not items:
            out += ["None.", ""]
        for f in items:
            out.append(f"- **{f['id']}** ({f['guideline']}): {f['message']}")
            if f["evidence"]:
                out.append(f"  - Evidence: {', '.join('`' + e + '`' for e in f['evidence'] if e)}")
            if f["fix"]:
                out.append(f"  - Fix: {f['fix']}")
            out.append(f"  - Source: {f['source']}")
        out.append("")
    out += [f"## PASS ({len(r.passes)})", ""]
    out += [f"- {x['id']}: {x['message']}" for x in r.passes] + [""]
    out += [f"## For Claude to judge ({len(r.candidates)})", "",
            "Read the evidence in the code and answer each question; promote real problems to findings.", ""]
    for c in r.candidates:
        out.append(f"- [ ] **{c['id']}** ({c['guideline']}): {c['question']}")
        if c["evidence"]:
            out.append(f"  - Evidence: {', '.join('`' + e + '`' for e in c['evidence'] if e)}")
    out += ["", "## Not scanned — Claude must decide", "",
            "Record each decision in KIT/precheck-decisions.yaml as `id: {decision: ok|fixed|n/a, why: evidence}`.", ""]
    for cid in not_covered(cat):
        row = cat[cid]
        decision = r.decisions.get(cid)
        out.append(f"- [{'x' if decision else ' '}] **{cid}** ({row.get('guideline', '')}): {row.get('what', '')}")
        if decision:
            out.append(f"  - Decision: {decision['decision']} — {decision['why']}")
    if undecided(r):
        out += ["", "Readiness: incomplete; unscanned checks remain undecided.", ""]
    return "\n".join(out)


def to_json(p, r, cat):
    auto, semi = implemented_counts(cat)
    return {"project": str(p.root), "kit": str(p.kit) if p.kit else None, "summary": summary(r),
            "findings": r.findings, "passes": r.passes, "candidates": r.candidates,
            "implemented": {"auto": auto, "semi": semi}, "not_scanned": not_covered(cat),
            "undecided": undecided(r), "decisions": r.decisions}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("--kit")
    ap.add_argument("--out")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--scheme")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--check-urls", action="store_true")
    ap.add_argument("--xcode", help="Xcode version to assume (skips xcodebuild)")
    ap.add_argument("--today", help="YYYY-MM-DD for dated rules")
    ap.add_argument("--rules", default=str(RULES_MD), help="path to precheck-rules.md")
    opt = ap.parse_args(argv)
    opt.today = dt.date.fromisoformat(opt.today) if opt.today else dt.date.today()
    root = pathlib.Path(opt.project)
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    cat = load_catalogue(opt.rules)
    p = Project(root, opt.kit, opt.scheme)
    r = run(p, cat, opt)
    md = to_markdown(p, r, cat, opt)
    out = opt.out or (str(pathlib.Path(opt.kit) / "PRECHECK.md") if opt.kit else None)
    if out:
        pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(out).write_text(md)
    if opt.json:
        print(json.dumps(to_json(p, r, cat), indent=2, default=str))
    elif out:
        s = summary(r)
        print(f"{out}: " + ", ".join(f"{k} {v}" for k, v in s.items()))
    else:
        print(md)
    return exit_code(r, opt.strict)


if __name__ == "__main__":
    sys.exit(main())
