#!/usr/bin/env python3
"""Draft "What's New" from the git log since the last release, and record releases.

Usage:
  whats_new.py PROJECT_GIT_DIR [--since auto|TAG|SHA] [--kit KIT] [--json]
  whats_new.py [PROJECT_GIT_DIR] --record KIT --version 1.1.0 [--commit SHA] [--date YYYY-MM-DD]

--since auto (default): the newest tag reachable from HEAD matching v* or release-*; else `last_release_commit`
from KIT/release-history.yaml, then KIT/connect-progress.yaml; else the whole history (with a note).

The draft is RAW: commit subjects grouped into new features (feat), fixes (fix), improvements (perf) and other
changes, with chores dropped (docs, test, ci, chore, refactor, style, build, merges, wip). Claude rewrites it in
plain words for customers (what they can now do, what works better), at most 4,000 characters, and the owner
approves the primary text (guideline 2.3.12: describe new features and product changes clearly).

--record appends {version, date, commit} to KIT/release-history.yaml and sets `last_release_commit`
(--commit defaults to HEAD of PROJECT_GIT_DIR).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys

import yaml

HISTORY = "release-history.yaml"
CONVENTIONAL = re.compile(r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?:\s*(?P<subject>.+)$")
CHORE_TYPES = {"docs", "doc", "test", "tests", "ci", "chore", "refactor", "style", "build", "release", "deps", "wip"}
GROUPS = [("feat", "New"), ("fix", "Fixes"), ("perf", "Improvements"), ("other", "Other changes")]
TYPE_ALIASES = {"feature": "feat", "bugfix": "fix", "hotfix": "fix", "improve": "perf", "improvement": "perf"}


def git(repo, *args) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def load_yaml(p: pathlib.Path):
    try:
        return (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}
    except yaml.YAMLError:
        return {}


def last_tag(repo) -> str | None:
    out = git(repo, "tag", "--merged", "HEAD", "--sort=-creatordate", "--list", "v*", "release-*")
    tags = [t for t in out.split() if t]
    return tags[0] if tags else None


def recorded_commit(kit: pathlib.Path | None) -> tuple[str | None, str | None]:
    if not kit:
        return None, None
    for name in (HISTORY, "connect-progress.yaml"):
        data = load_yaml(kit / name)
        if isinstance(data, dict):
            sha = data.get("last_release_commit")
            if not sha and isinstance(data.get("releases"), list) and data["releases"]:
                sha = (data["releases"][-1] or {}).get("commit")
            if sha:
                return str(sha), name
    return None, None


def resolve_since(repo, since: str, kit) -> tuple[str | None, str]:
    if since and since != "auto":
        return since, since
    tag = last_tag(repo)
    if tag:
        return tag, f"tag {tag}"
    sha, src = recorded_commit(pathlib.Path(kit) if kit else None)
    if sha:
        return sha, f"{src} last_release_commit {sha[:12]}"
    return None, "no tag (v*/release-*) and no recorded release: whole history"


def classify(subject: str) -> tuple[str | None, str, str | None]:
    """(group or None for a chore, cleaned subject, scope)."""
    s = subject.strip()
    if not s or re.match(r"^(merge\b|wip\b|fixup!|squash!)", s, re.I) or re.search(r"\bwip\b", s, re.I):
        return None, s, None
    m = CONVENTIONAL.match(s)
    if m:
        t = TYPE_ALIASES.get(m.group("type").lower(), m.group("type").lower())
        if t in CHORE_TYPES:
            return None, m.group("subject"), m.group("scope")
        group = t if t in ("feat", "fix", "perf") else "other"
        return group, m.group("subject"), m.group("scope")
    low = s.lower()
    if re.match(r"^(update|bump)\s+(readme|docs?|changelog|deps|dependencies)\b", low) or low.startswith("revert "):
        return None, s, None
    if re.match(r"^(fix|fixes|fixed)\b", low):
        return "fix", s, None
    if re.match(r"^(add|adds|added|new)\b", low):
        return "feat", s, None
    return "other", s, None


def collect(repo, since: str | None) -> list[dict]:
    rng = [f"{since}..HEAD"] if since else ["HEAD"]
    out = git(repo, "log", "--no-merges", "--format=%H%x1f%s", *rng)
    commits = []
    for line in out.splitlines():
        if "\x1f" not in line:
            continue
        sha, subject = line.split("\x1f", 1)
        group, clean, scope = classify(subject)
        commits.append({"sha": sha, "subject": subject, "group": group, "text": clean, "scope": scope})
    return commits


def draft(commits: list[dict], source: str) -> str:
    kept = [c for c in commits if c["group"]]
    lines = [f"# What's New: RAW draft from git ({source}); {len(kept)} of {len(commits)} commits kept",
             "# Claude rewrites this for customers: plain words, what they can do now, no commit jargon,",
             "# no internal names; <= 4,000 characters; then adapt per locale. The owner approves the primary.", ""]
    for key, title in GROUPS:
        items = [c for c in kept if c["group"] == key]
        if not items:
            continue
        lines.append(f"{title}:")
        seen = set()
        for c in reversed(items):  # oldest first reads like a story
            text = c["text"][:1].upper() + c["text"][1:]
            if text.lower() in seen:
                continue
            seen.add(text.lower())
            lines.append(f"- {text}" + (f"  [{c['scope']}]" if c["scope"] else "") + f"  ({c['sha'][:7]})")
        lines.append("")
    if not kept:
        lines.append("(no user-facing commits found: a generic 'Bug fixes and performance improvements' is only "
                     "acceptable for simple bug-fix releases, guideline 2.3.12)")
    return "\n".join(lines).rstrip() + "\n"


def record(kit: pathlib.Path, version: str, commit: str, date: str) -> pathlib.Path:
    """Append a release; text edits keep comments. Re-dumps only if the file shape is unexpected."""
    path = kit / HISTORY
    entry = f'  - {{version: "{version}", date: "{date}", commit: "{commit}"}}\n'
    if not path.exists():
        path.write_text("# Releases shipped from this kit (whats_new.py --record). Newest last.\n"
                        f'last_release_commit: "{commit}"\nreleases:\n' + entry)
        return path
    text = path.read_text()
    if re.search(r"(?m)^last_release_commit\s*:.*$", text):
        text = re.sub(r"(?m)^last_release_commit\s*:.*$", f'last_release_commit: "{commit}"', text, count=1)
    else:
        text = f'last_release_commit: "{commit}"\n' + text
    if not text.endswith("\n"):
        text += "\n"
    if not re.search(r"(?m)^releases\s*:\s*$", text):
        text += "releases:\n"
    candidate = text + entry
    data = yaml.safe_load(candidate) or {}
    rel = data.get("releases") if isinstance(data, dict) else None
    if not (isinstance(rel, list) and rel and rel[-1].get("commit") == commit):
        data = load_yaml(path) or {}
        data["last_release_commit"] = commit
        data["releases"] = (data.get("releases") or []) + [{"version": version, "date": date, "commit": commit}]
        candidate = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    path.write_text(candidate)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", nargs="?", help="the app's git folder")
    ap.add_argument("--since", default="auto")
    ap.add_argument("--kit")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--record", metavar="KIT")
    ap.add_argument("--version")
    ap.add_argument("--commit")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args(argv)

    if a.record:
        if not a.version:
            ap.error("--record needs --version")
        commit = a.commit
        if not commit:
            if not a.repo:
                ap.error("--record needs --commit or PROJECT_GIT_DIR (to use HEAD)")
            commit = git(a.repo, "rev-parse", "HEAD").strip()
        path = record(pathlib.Path(a.record), a.version, commit, a.date)
        print(f"recorded {a.version} ({commit[:12]}, {a.date}) in {path}")
        return 0

    if not a.repo:
        ap.error("PROJECT_GIT_DIR is required")
    try:
        since, source = resolve_since(a.repo, a.since, a.kit)
        commits = collect(a.repo, since)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps({"since": since, "source": source, "commits": commits}, indent=2))
    else:
        print(draft(commits, source), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
