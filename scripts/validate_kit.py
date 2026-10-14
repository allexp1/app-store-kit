#!/usr/bin/env python3
"""Validate an App Store kit against a FROZEN rule table (rules.json).

Kit layout (all optional except what you want checked):
  KIT/rules.json                              frozen by snapshot_rules.py freeze KIT
  KIT/screenshots/<locale>/<slot>/*.png|jpg   slot ids are the keys of rules.json screenshots.slots
  KIT/previews/<locale>/<slot>/*.mov|mp4|m4v
  KIT/iap/<product_id>/promo.png              in-app purchase promotional image
  KIT/frames.yaml                             captions, colours (house-rule checks)

Usage:
  validate_kit.py KIT [--platforms iphone,ipad] [--fix] [--report OUT.md] [--rules R] [--today YYYY-MM-DD]
  validate_kit.py --pairs [--fix] [--rules R] SLOT=FILE ...      (single files, no set checks)

--fix strips the alpha channel in place (keeps the ICC profile) and re-checks.
Apple rules are errors. House rules (rules.json house_rules) are warnings, labelled "house".
Exit 0 when there are no errors, 1 otherwise.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import pathlib
import re
import sys

from PIL import Image, ImageCms

HERE = pathlib.Path(__file__).resolve().parent
SKILL_RULES = HERE / "rules.json"
PLACEHOLDER = re.compile(r"\b(lorem|ipsum|todo|tbd|fixme|placeholder|xxx+|sample text)\b", re.I)


class Report:
    def __init__(self):
        self.items = []  # (level, scope, message)

    def add(self, level, scope, msg):
        self.items.append((level, scope, msg))

    def err(self, scope, msg):
        self.add("ERROR", scope, msg)

    def warn(self, scope, msg):
        self.add("WARN", scope, msg)

    def note(self, scope, msg):
        self.add("NOTE", scope, msg)

    def ok(self, scope, msg):
        self.add("PASS", scope, msg)

    @property
    def errors(self):
        return [i for i in self.items if i[0] == "ERROR"]

    def print(self, out=None):
        out = out or sys.stdout
        for level, scope, msg in self.items:
            print(f"{level:5} [{scope}] {msg}", file=out)
        print(f"\n{len(self.errors)} error(s), {sum(1 for i in self.items if i[0] == 'WARN')} warning(s)", file=out)


def load_rules(path=None, kit=None, rep=None, today=None):
    path = pathlib.Path(path) if path else None
    if path is None and kit is not None and (pathlib.Path(kit) / "rules.json").exists():
        path = pathlib.Path(kit) / "rules.json"
    if path is None:
        path = SKILL_RULES
        if rep is not None:
            rep.warn("rules", f"no frozen KIT/rules.json; using the skill baseline {path} "
                              "(run snapshot_rules.py freeze KIT before submission)")
    rules = json.loads(path.read_text())
    if rep is not None:
        fetched = rules.get("fetched")
        rep.note("rules", f"{path} fetched {fetched}, frozen_for_kit={bool(rules.get('frozen_for_kit'))}")
        if fetched:
            age = ((today or dt.date.today()) - dt.date.fromisoformat(fetched)).days
            if age > 7:
                rep.warn("rules", f"rule table is {age} days old; re-check Apple's pages (snapshot_rules.py check)")
    return rules


def profile_name(img):
    icc = img.info.get("icc_profile")
    if not icc:
        return None
    try:
        return ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc))).strip()
    except Exception as e:  # pragma: no cover - corrupt profile
        return f"unreadable ({e})"


def has_alpha(img):
    return img.mode in ("RGBA", "LA", "PA", "RGBa", "La") or (img.mode == "P" and "transparency" in img.info)


def strip_alpha(path, img, background=(255, 255, 255)):
    icc = img.info.get("icc_profile")
    rgba = img.convert("RGBA")
    flat = Image.new("RGB", img.size, background)
    flat.paste(rgba, mask=rgba.split()[-1])
    kw = {"icc_profile": icc} if icc else {}
    if img.format == "JPEG":
        kw["quality"] = 95
    flat.save(path, format=img.format or "PNG", **kw)


def accepted_sizes(slot_rule):
    """Sizes as Apple lists them, plus the rotated size unless the slot is fixed to one orientation."""
    sizes = {tuple(s) for s in slot_rule["sizes"]}
    if not (slot_rule.get("landscape_only") or slot_rule.get("portrait_only")):
        sizes |= {(h, w) for w, h in sizes}
    return sizes


def check_image(path, sizes, rules_img, rep, scope, fix=False, label=""):
    path = pathlib.Path(path)
    try:
        img = Image.open(path)
        img.load()
    except Exception as e:
        rep.err(scope, f"{path.name}: not a readable image ({e})")
        return False
    errs = 0
    fmt = img.format
    if fmt not in rules_img.get("formats", ["PNG", "JPEG"]):
        rep.err(scope, f"{path.name}: type {fmt}, need {'/'.join(rules_img.get('formats', []))}"); errs += 1
    exts = rules_img.get("extensions")
    if exts and path.suffix.lower() not in exts:
        rep.err(scope, f"{path.name}: extension {path.suffix} not in {exts}"); errs += 1
    if img.size not in sizes:
        rep.err(scope, f"{path.name}: {img.size[0]}x{img.size[1]} is not an accepted size for {label or scope}: "
                       + ", ".join(f"{w}x{h}" for w, h in sorted(sizes))); errs += 1
    if has_alpha(img) and not rules_img.get("alpha_allowed", False):
        if fix:
            strip_alpha(path, img)
            img = Image.open(path); img.load()
            rep.note(scope, f"{path.name}: alpha channel stripped")
        if has_alpha(img):
            rep.err(scope, f"{path.name}: alpha channel present (mode {img.mode}); rerun with --fix"); errs += 1
    prof = profile_name(img)
    allowed = tuple(rules_img.get("color_profiles", ["srgb", "display p3"]))
    if prof is None:
        rep.note(scope, f"{path.name}: no ICC profile (treated as sRGB)")
    elif not prof.lower().startswith(allowed):
        rep.err(scope, f"{path.name}: colour profile '{prof}', need sRGB or Display P3"); errs += 1
    # simulator artefact seen in captures: a tiny black dot at (0,0)
    try:
        rgb = img.convert("RGB")
        if img.width > 20 and rgb.getpixel((0, 0)) == (0, 0, 0) and rgb.getpixel((6, 6)) != (0, 0, 0) \
                and rgb.getpixel((img.width - 1, 0)) != (0, 0, 0):
            rep.warn(scope, f"{path.name}: black pixel at (0,0) only; simulator capture artefact? crop or paint it out")
    except Exception:  # pragma: no cover
        pass
    if not errs:
        rep.ok(scope, f"{path.name}: {fmt} {img.size[0]}x{img.size[1]} {img.mode} profile={prof}")
    return errs == 0


def images_in(d):
    return sorted(p for p in pathlib.Path(d).iterdir()
                  if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".heic", ".webp", ".gif", ".tif", ".tiff"))


def required_slots(rules, families, today):
    out = []
    for sid, s in rules["screenshots"]["slots"].items():
        if s["family"] not in families:
            continue
        if s.get("required"):
            out.append((sid, None))
        elif s.get("required_from"):
            due = dt.date.fromisoformat(s["required_from"] + "-01") if len(s["required_from"]) == 7 else dt.date.fromisoformat(s["required_from"])
            out.append((sid, due))
    return out


def check_screenshots(kit, rules, rep, families, fix, today, missing):
    root = kit / "screenshots"
    sr = rules["screenshots"]
    slots = sr["slots"]
    locales = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []
    if not locales:
        rep.err("screenshots", f"no screenshots found under {root}/<locale>/<slot>/")
        return locales
    for loc in locales:
        present = set()
        for sd in sorted(p for p in (root / loc).iterdir() if p.is_dir()):
            sid = sd.name
            scope = f"{loc}/{sid}"
            if sid not in slots:
                rep.err(scope, f"unknown slot '{sid}'; known: {', '.join(slots)}")
                continue
            files = images_in(sd)
            n = len(files)
            if not (sr["min_per_set"] <= n <= sr["max_per_set"]):
                rep.err(scope, f"{n} screenshot(s); Apple allows {sr['min_per_set']}-{sr['max_per_set']} per size and language")
            if n:
                present.add(sid)
            for f in files:
                check_image(f, accepted_sizes(slots[sid]), sr, rep, scope, fix, slots[sid]["label"])
        for sid, due in required_slots(rules, families, today):
            if sid in present:
                continue
            if due is None:
                rep.err(loc, f"required set missing: {sid} ({slots[sid]['label']})")
                missing.setdefault(loc, []).append(sid)
            elif today >= due:
                rep.err(loc, f"set missing: {sid}. {slots[sid].get('required_note', '')}")
                missing.setdefault(loc, []).append(sid)
            else:
                rep.note(loc, f"{sid} not present; {slots[sid].get('required_note', 'required later')} (due {due})")
    return locales


def preview_family(slot_id, resolutions):
    if slot_id in resolutions:
        return slot_id
    fam = slot_id.split("-")[0]
    return fam if fam in resolutions else None


def check_previews(kit, rules, rep):
    root = kit / "previews"
    if not root.exists():
        rep.note("previews", "no previews (optional; extras are off the critical path)")
        return
    try:
        import preview_check  # same directory
    except ImportError:  # pragma: no cover
        sys.path.insert(0, str(HERE)); import preview_check
    pr = rules["previews"]
    for loc in sorted(p for p in root.iterdir() if p.is_dir()):
        for sd in sorted(p for p in loc.iterdir() if p.is_dir()):
            scope = f"{loc.name}/{sd.name} preview"
            files = sorted(p for p in sd.iterdir() if p.suffix.lower() in (".mov", ".mp4", ".m4v"))
            if len(files) > pr["max_per_set"]:
                rep.err(scope, f"{len(files)} previews; max {pr['max_per_set']} per size and language")
            fam = preview_family(sd.name, pr["resolutions"])
            for f in files:
                try:
                    probe = preview_check.ffprobe(f)
                except Exception as e:
                    rep.err(scope, f"{f.name}: ffprobe failed ({e})"); continue
                errs, warns = preview_check.check(probe, f, fam, rules)
                for e in errs:
                    rep.err(scope, f"{f.name}: {e}")
                for w in warns:
                    rep.warn(scope, f"{f.name}: {w}")
                if not errs:
                    rep.ok(scope, f"{f.name}")


def check_iap(kit, rules, rep, fix):
    root = kit / "iap"
    if not root.exists():
        return
    ir = rules["iap_promo_image"]
    ir = {**ir, "extensions": [".png", ".jpg", ".jpeg"]}
    for promo in sorted(root.glob("*/promo.*")):
        check_image(promo, {tuple(s) for s in ir["sizes"]}, ir, rep, f"iap/{promo.parent.name}", fix, "IAP promo image")


def _lum(hexcolor):
    h = hexcolor.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    vals = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in vals]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def check_frames(kit, rules, rep):
    path = kit / "frames.yaml"
    if not path.exists():
        return
    import yaml
    data = yaml.safe_load(path.read_text()) or {}
    house = rules.get("house_rules", {})
    d = data.get("defaults", {})
    frames = data.get("frames", [])
    dark = 0
    for i, fr in enumerate(frames, 1):
        fid = fr.get("id", f"frame{i}")
        caps = fr.get("caption", {})
        caps = caps if isinstance(caps, dict) else {"*": caps}
        for loc, text in caps.items():
            text = str(text or "")
            if not text.strip():
                rep.err(f"frames/{fid}", f"empty caption ({loc})")
            if PLACEHOLDER.search(text):
                rep.err(f"frames/{fid}", f"placeholder text in caption ({loc}): {text!r}")
            words = len(re.findall(r"\S+", text))
            if house.get("caption_max_words") and words > house["caption_max_words"]:
                rep.warn(f"frames/{fid}", f"house: caption has {words} words (> {house['caption_max_words']}) ({loc})")
        is_dark = fr.get("template", d.get("template")) == "dark" or fr.get("dark")
        dark += bool(is_dark)
        bg = fr.get("background", d.get("dark_background" if is_dark else "background"))
        ink = fr.get("ink", d.get("dark_ink" if is_dark else "ink"))
        if bg and ink and str(bg).startswith("#") and str(ink).startswith("#"):
            c = contrast(ink, bg)
            if c < house.get("min_contrast", 4.5):
                rep.warn(f"frames/{fid}", f"caption contrast {c:.2f}:1 < {house.get('min_contrast', 4.5)}:1")
    if frames and house.get("dark_frames_min") and dark < house["dark_frames_min"]:
        rep.warn("frames", f"house: {dark} dark frame(s); the house style wants {house['dark_frames_min']}")
    lo, hi = house.get("frames_per_set", [1, 10])
    if frames and not (lo <= len(frames) <= hi):
        rep.warn("frames", f"house: {len(frames)} frames; the house style wants {lo}-{hi}")
    rep.note("frames", "manual checks: status bar reads 9:41 (house), captions inside the safe area, "
                       "screens come from the build being submitted (2.3.3)")


def write_report(path, rep, locales, missing):
    lines = ["# Screenshot and asset validation", "",
             f"{len(rep.errors)} error(s), {sum(1 for i in rep.items if i[0] == 'WARN')} warning(s).", "",
             "## Missing per locale", "", "| Locale | Missing sets |", "|---|---|"]
    for loc in locales or ["(none)"]:
        lines.append(f"| {loc} | {', '.join(missing.get(loc, [])) or 'none'} |")
    lines += ["", "## Findings", ""]
    for level, scope, msg in rep.items:
        if level != "PASS":
            lines.append(f"- **{level}** `{scope}` {msg}")
    pathlib.Path(path).write_text("\n".join(lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("targets", nargs="*")
    ap.add_argument("--pairs", action="store_true", help="targets are SLOT=FILE pairs")
    ap.add_argument("--rules")
    ap.add_argument("--platforms", help="comma list of families the app ships on (iphone,ipad,mac,appletv,vision,watch)")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--report")
    ap.add_argument("--today")
    a = ap.parse_args(argv)
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    rep = Report()
    if a.pairs:
        rules = load_rules(a.rules, None, rep, today)
        slots = rules["screenshots"]["slots"]
        for pair in a.targets:
            slot, _, f = pair.partition("=")
            if slot not in slots:
                rep.err(slot, f"unknown slot; known: {', '.join(slots)}"); continue
            check_image(f, accepted_sizes(slots[slot]), rules["screenshots"], rep, slot, a.fix, slots[slot]["label"])
        rep.print()
        return 1 if rep.errors else 0
    if len(a.targets) != 1:
        ap.error("give one KIT directory, or --pairs SLOT=FILE ...")
    kit = pathlib.Path(a.targets[0])
    rules = load_rules(a.rules, kit, rep, today)
    shots = kit / "screenshots"
    if a.platforms:
        families = set(a.platforms.split(","))
    else:
        families = {sd.name.split("-")[0] for loc in (shots.iterdir() if shots.exists() else []) if loc.is_dir()
                    for sd in loc.iterdir() if sd.is_dir()}
        rep.note("kit", f"platforms inferred from folders: {', '.join(sorted(families)) or 'none'} (pass --platforms to be explicit)")
    missing = {}
    locales = check_screenshots(kit, rules, rep, families, a.fix, today, missing)
    check_previews(kit, rules, rep)
    check_iap(kit, rules, rep, a.fix)
    check_frames(kit, rules, rep)
    rep.print()
    if a.report:
        write_report(a.report, rep, locales, missing)
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
