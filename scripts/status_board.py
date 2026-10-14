#!/usr/bin/env python3
"""The one page the owner reads: KIT/STATUS.md.

  status_board.py KIT [--project DIR] [--print]

Reads what the other scripts leave in the kit and writes KIT/STATUS.md:
  - PRECHECK.md        (precheck.py): blockers, likely rejections, warnings, items for Claude to judge
  - connect-progress.yaml + the guide steps (connect_guide.py): every App Store Connect step, in order
  - connect-plan.json  (asc_sync.py plan): changes waiting for the owner's yes, browser and person steps
  - connect-live.json  (asc_sync.py status): the live version and its state

Each step gets one mark:
  ✅ done   ✋ your turn (only the owner can do it)   🛑 needs your yes   🌐 Claude in Chrome   ⬜ to do
The first open step is repeated at the top as "Next". Private values are never read into the board.
"""
import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import connect_guide as cg  # noqa: E402

DONE, PERSON, YES, BROWSER, TODO = "✅", "✋", "🛑", "🌐", "⬜"
# Steps the API can't do; Claude does them in Chrome (references/person-and-browser-steps.md).
BROWSER_KEYS = ("new-app/", "privacy/", "pricing/", "version/in-app-purchases",
                "version/phased-release-and-rating-reset")
# Compliance answers only the owner can give (the app-level DSA trader status).
PERSON_KEYS = ("app-information/app-store-regulations-and-permits-digital-services-act",)
SEVERITY_RE = re.compile(r"^## (BLOCKER|LIKELY REJECTION|WARNING|PASS|For Claude to judge) \((\d+)\)", re.M)


def load_json(p):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def precheck_counts(kit):
    p = kit / "PRECHECK.md"
    if not p.exists():
        return None
    return {k: int(v) for k, v in SEVERITY_RE.findall(p.read_text())}


def mark(step, status):
    if status.startswith("done") or status == "skipped":
        return DONE
    if step.guide_only or (step.key and step.key.startswith(PERSON_KEYS)):
        return PERSON
    if step.approval:
        return YES
    if step.key and step.key.startswith(BROWSER_KEYS):
        return BROWSER
    return TODO


def guide_steps(kit):
    rules_path = kit / "rules.json" if (kit / "rules.json").exists() else HERE / "rules.json"
    rules = json.loads(rules_path.read_text())
    g = cg.build(kit, None, rules, {})
    prog = (cg.load_yaml(kit / cg.PROGRESS_FILE).get("steps") or {})
    out = []
    for s in g["sections"]:
        rows = []
        for st in s.steps:
            entry = prog.get(st.key) or {}
            status = str(entry.get("status") or "todo")
            rows.append({"title": st.title, "key": st.key, "status": status, "mark": mark(st, status),
                         "date": entry.get("date"), "who": status.replace("done-by-", "") if status.startswith("done-by-") else ""})
        out.append({"title": s.title, "rows": rows})
    return out


def render(kit):
    L = ["# App Store status", "",
         f"{DONE} done · {PERSON} your turn · {YES} needs your yes · {BROWSER} Claude in Chrome · {TODO} to do", ""]
    sections = guide_steps(kit)
    open_rows = [r for s in sections for r in s["rows"] if r["mark"] != DONE]
    total = sum(len(s["rows"]) for s in sections)
    nxt = open_rows[0] if open_rows else None
    pc = precheck_counts(kit)
    if pc and pc.get("BLOCKER"):
        L.append(f"**Next:** 🛑 fix the {pc['BLOCKER']} blocker(s) in PRECHECK.md before uploading.")
    elif nxt:
        L.append(f"**Next:** {nxt['mark']} {nxt['title']} (`{nxt['key']}`)")
    else:
        L.append("**Next:** nothing open. Every step is done.")
    L += ["", f"Progress: {total - len(open_rows)} of {total} steps done.", ""]

    L += ["## Code pre-check", ""]
    if pc is None:
        L.append(f"{TODO} Not run yet: `precheck.py PROJECT --kit KIT`.")
    else:
        b, lr, w = pc.get("BLOCKER", 0), pc.get("LIKELY REJECTION", 0), pc.get("WARNING", 0)
        icon = "🛑" if b else ("⚠️" if lr else DONE)
        L.append(f"{icon} {b} blocker(s), {lr} likely rejection(s), {w} warning(s), "
                 f"{pc.get('PASS', 0)} passed, {pc.get('For Claude to judge', 0)} for Claude to judge. See PRECHECK.md.")
    L.append("")

    live = load_json(kit / "connect-live.json")
    plan = load_json(kit / "connect-plan.json")
    if live or plan:
        L += ["## App Store Connect (API)", ""]
        if plan:
            v = plan.get("version") or {}
            L.append(f"- Version {plan.get('kit_version')} (build {plan.get('build')}): {v.get('action') or '?'}"
                     + (f", state {v['state']}" if v.get("state") else "")
                     + (f"; live now: {v['live_version']}" if v.get("live_version") else ""))
            items = plan.get("items") or []
            L.append(f"- {YES} Plan from {plan.get('generated')}: {len(items)} change(s) waiting for your yes "
                     f"(read connect-plan.md)." if items else f"- {DONE} The live account matches the kit.")
            for kind, sym in (("browser_steps", BROWSER), ("person_steps", PERSON)):
                for s in plan.get(kind) or []:
                    if not s.get("done"):
                        L.append(f"- {sym} {s.get('text')}")
            for w in plan.get("warnings") or []:
                L.append(f"- ⚠️ {w}")
        elif live:
            L.append("- Live state read; run `asc_sync.py plan KIT` for the changes.")
        L.append("")

    for s in sections:
        done = sum(r["mark"] == DONE for r in s["rows"])
        L += [f"## {s['title']} ({done}/{len(s['rows'])})", ""]
        for r in s["rows"]:
            extra = f" — {r['who']}, {r['date']}" if r["mark"] == DONE and r["who"] else ""
            L.append(f"- {r['mark']} {r['title']}{extra}")
        L.append("")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kit")
    ap.add_argument("--print", action="store_true", help="print instead of writing KIT/STATUS.md")
    a = ap.parse_args(argv)
    kit = pathlib.Path(a.kit)
    if not (kit / "facts.yaml").exists():
        print(f"not a kit (no facts.yaml): {kit}", file=sys.stderr)
        return 2
    md = render(kit)
    if a.print:
        print(md)
    else:
        (kit / "STATUS.md").write_text(md)
        print(f"wrote {kit / 'STATUS.md'}: " + md.splitlines()[4])
    return 0


if __name__ == "__main__":
    sys.exit(main())
