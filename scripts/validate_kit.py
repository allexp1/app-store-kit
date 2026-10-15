#!/usr/bin/env python3
"""Validate an App Store kit against a FROZEN rule table (rules.json).

Kit layout (all optional except what you want checked):
  KIT/rules.json                              frozen by snapshot_rules.py freeze KIT
  KIT/screenshots/<locale>/<slot>/*.png|jpg   slot ids are the keys of rules.json screenshots.slots
  KIT/previews/<locale>/<slot>/*.mov|mp4|m4v
  KIT/iap/<product_id>/promo.png              in-app purchase promotional image
  KIT/creative/<locale>/universal|header|search.png|jpg|mp4|mov   header and search-results assets (iOS 27+)
  KIT/frames.yaml                             captions, colours (house-rule checks)
  KIT/growth/**/screenshots|previews|creative/<locale>/...   custom product pages and test treatments (growth.yaml)
  KIT/growth/<event>/media/<locale>/card|details.png|mp4     in-app event card (16:9) and details page (9:16)

Usage:
  validate_kit.py KIT [--platforms iphone,ipad] [--project DIR|APP.ipa] [--fix] [--report OUT.md] [--rules R]
                  [--today YYYY-MM-DD]
  validate_kit.py --pairs [--fix] [--rules R] SLOT=FILE ...      (single files, no set checks)

Platforms: --platforms, else facts.yaml `platforms:` plus the slot folders present. A watch app found in --project
(or facts.yaml `project:`) adds watch either way: a target with WATCHOS_DEPLOYMENT_TARGET, an embedded Watch/
bundle in a built .app, .xcarchive or .ipa. Apple refuses "Add for Review" without Apple Watch screenshots then.
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


FAMILY_ALIASES = {"ios": "iphone", "iphoneos": "iphone", "ipados": "ipad", "macos": "mac", "tvos": "appletv",
                  "visionos": "vision", "watchos": "watch", "applewatch": "watch", "apple-watch": "watch"}
SKIP_SCAN = {"DerivedData", "Pods", "Carthage", "node_modules", ".git", ".build"}


def detect_watch(path):
    """Where the app embeds a watch app: a description of the evidence, or None."""
    import zipfile
    path = pathlib.Path(path).expanduser()
    if path.is_file() and path.suffix.lower() == ".ipa":
        try:
            with zipfile.ZipFile(path) as z:
                hit = next((n for n in z.namelist() if re.search(r"\.app/Watch/[^/]+\.app/", n)), None)
        except zipfile.BadZipFile:
            return None
        return f"{path.name}: {hit.split('/Watch/')[1].split('/')[0]} in Watch/" if hit else None
    if not path.is_dir():
        return None
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            children = list(d.iterdir())
        except OSError:
            continue
        for c in children:
            if c.is_dir():
                if c.name == "Watch" and c.parent.suffix == ".app" and any(c.glob("*.app")):
                    return f"{c.relative_to(path)}: embedded watch app"
                if c.name not in SKIP_SCAN:
                    stack.append(c)
            elif c.name == "project.pbxproj":
                if "WATCHOS_DEPLOYMENT_TARGET" in c.read_text(errors="ignore"):
                    return f"{c.relative_to(path)}: a target sets WATCHOS_DEPLOYMENT_TARGET"
    return None


def kit_families(kit, explicit=None, project=None):
    """(families, notes): --platforms, else facts.yaml platforms + slot folders; a detected watch app adds watch."""
    import yaml
    facts_path = kit / "facts.yaml"
    facts = (yaml.safe_load(facts_path.read_text()) or {}) if facts_path.exists() else {}
    facts = facts if isinstance(facts, dict) else {}
    notes = []
    if explicit:
        fams = set(explicit.split(","))
    else:
        declared = facts.get("platforms") or []
        declared = [declared] if isinstance(declared, str) else declared
        fams = {FAMILY_ALIASES.get(str(x).lower().replace(" ", ""), str(x).lower()) for x in declared}
        shots = kit / "screenshots"
        folders = {sd.name.split("-")[0] for loc in (shots.iterdir() if shots.exists() else []) if loc.is_dir()
                   for sd in loc.iterdir() if sd.is_dir()}
        fams |= folders
        notes.append(f"platforms from facts.yaml and folders: {', '.join(sorted(fams)) or 'none'} "
                     f"(pass --platforms to be explicit)")
    project = project or facts.get("project")
    if project and "watch" not in fams:
        p = pathlib.Path(str(project)).expanduser()
        if not p.is_absolute():
            p = kit / p
        hit = detect_watch(p)
        if hit:
            fams.add("watch")
            notes.append(f"watch app found ({hit}); Apple Watch screenshots are required")
    return fams, notes


def images_in(d):
    return sorted(p for p in pathlib.Path(d).iterdir()
                  if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".heic", ".webp", ".gif", ".tif", ".tiff"))


def build_sdk(facts):
    """The release build SDK, not deployment target or installed Xcode."""
    build = facts.get("build") or {}
    app = facts.get("app") or {}
    value = facts.get("sdk") or facts.get("build_sdk")
    if not value and isinstance(build, dict):
        value = build.get("sdk") or build.get("SDK")
    if not value and isinstance(app, dict):
        value = app.get("sdk") or app.get("build_sdk")
    if isinstance(value, dict):
        value = f"{value.get('name', 'iOS')} {value.get('version', '')}"
    match = re.fullmatch(r"(?:iOS\s*|iphoneos\s*)?(\d+)(?:\.(\d+))?(?:\.\d+)?(?:\s*SDK)?", str(value), re.I)
    return (int(match[1]), int(match[2] or 0)) if match else None


def slot_requirement(slot, today, facts, present):
    """required, recommended, future, unknown, or optional; unknown SDKs never become errors."""
    unless = slot.get("required_unless")
    if not unless:
        match = re.search(r"Required only if ([\w-]+) is not provided", slot.get("required_note", ""))
        unless = match[1] if match else None
    if unless:
        # Apple bolds only the medium Dynamic Island set as Required; this row's note conflicts with that, so a
        # missing large set is a warning, not an error (references/apple-specs.md, scaling chain).
        return "optional" if unless in present else "recommended"
    if slot.get("required"):
        return "required"
    date = slot.get("required_from")
    if not date:
        return "optional"
    sdk = slot.get("required_sdk")
    if not sdk:
        match = re.search(r"iOS ([\d.]+) SDK", slot.get("required_note", ""))
        sdk = "iOS " + match[1] if match else None
    if sdk:
        actual, minimum = build_sdk(facts), build_sdk({"sdk": sdk})
        if actual is None or minimum is None:
            return "unknown"
        if actual < minimum:
            return "optional"
    due = dt.date.fromisoformat(date + "-01" if len(date) == 7 else date)
    return "required" if today >= due else "future"


def required_slots(rules, families, today):
    return [(sid, s.get("required_from")) for sid, s in rules["screenshots"]["slots"].items()
            if s["family"] in families and (s.get("required") or s.get("required_from")
                                            or s.get("required_unless") or s.get("required_note"))]


def check_screenshots(kit, rules, rep, families, fix, today, missing):
    import yaml
    facts_path = kit / "facts.yaml"
    facts = yaml.safe_load(facts_path.read_text()) or {} if facts_path.exists() else {}
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
            state = slot_requirement(slots[sid], today, facts, present)
            note = slots[sid].get("required_note", "")
            if state == "required":
                rep.err(loc, f"required set missing: {sid} ({slots[sid]['label']}). {note}")
                missing.setdefault(loc, []).append(sid)
            elif state == "recommended":
                rep.warn(loc, f"{sid} not present ({slots[sid]['label']}). {note}; Apple's page marks only "
                              f"iphone-di-medium as Required, so add one of the large sets to be safe.")
            elif state == "unknown":
                rep.warn(loc, f"{sid} not present; build SDK is unknown in facts.yaml, so the SDK condition "
                              f"cannot be checked. {note}")
            elif state == "future":
                rep.note(loc, f"{sid} not present; {note} (due {due})")
    return locales


def preview_family(slot_id, resolutions):
    if slot_id in resolutions:
        return slot_id
    fam = slot_id.split("-")[0]
    return fam if fam in resolutions else None


def check_previews(kit, rules, rep, root=None, prefix=""):
    root = root or kit / "previews"
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
            scope = f"{prefix}{loc.name}/{sd.name} preview"
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


# Header and search-results assets, read from appAssetLibraryRefData 2026-10-14 (apple-specs.md › Creative assets).
# A frozen rules.json may carry its own "creative_assets" block; this is the fallback.
CREATIVE_DEFAULT = {
    "images": {
        "universal": {"sizes": [[5244, 2950]], "formats": ["PNG"]},
        "header": {"sizes": [[5244, 2950], [3840, 1646]], "formats": ["PNG", "JPEG"], "png_only": [[5244, 2950]]},
        "search": {"sizes": [[5244, 2950]], "ratio_3x2_widths": [1920, 3840], "formats": ["PNG", "JPEG"],
                   "png_only": [[5244, 2950]]},
    },
    "videos": {
        "header": {"sizes": [[3840, 1646]], "fps": [30, 60], "seconds": [5, 30]},
        "search": {"ratio": [3, 2], "widths": [1920, 3840], "fps": [30, 60], "seconds": [5, 30]},
    },
}


def creative_image_sizes(kind, spec, actual):
    sizes = {tuple(x) for x in spec.get("sizes", [])}
    lo_hi = spec.get("ratio_3x2_widths")
    if lo_hi and actual[0] * 2 == actual[1] * 3 and lo_hi[0] <= actual[0] <= lo_hi[1]:
        sizes.add(tuple(actual))
    return sizes


def check_creative(kit, rules, rep, fix, root=None, prefix=""):
    root = root or kit / "creative"
    if not root.exists():
        return
    cr = rules.get("creative_assets") or CREATIVE_DEFAULT
    try:
        import locales
    except ImportError:  # pragma: no cover
        sys.path.insert(0, str(HERE)); import locales
    for loc in sorted(p for p in root.iterdir() if p.is_dir()):
        if loc.name not in locales.LOCALES:
            rep.warn(f"{prefix}{loc.name}/creative", f"'{loc.name}' is not an App Store locale code; skipped "
                                                     "(keep the asset's sources in KIT/creative-src/)")
            continue
        files = [f for f in sorted(loc.iterdir()) if f.is_file() and not f.name.startswith(".")]
        for f in files:
            kind = f.stem.lower()
            scope = f"{prefix}{loc.name}/creative {kind}"
            if kind not in ("universal", "header", "search"):
                if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".mp4", ".mov", ".m4v"):
                    rep.warn(scope, f"{f.name}: name it universal, header or search; it is not uploaded")
                continue
            if f.suffix.lower() in (".mp4", ".mov", ".m4v"):
                check_creative_video(f, kind, cr["videos"], rep, scope)
                continue
            spec = cr["images"][kind]
            try:
                with Image.open(f) as im:
                    actual = im.size
            except Exception:
                actual = (0, 0)
            formats = ["PNG"] if list(actual) in spec.get("png_only", []) else spec["formats"]
            img_rules = {**rules["screenshots"], "formats": formats, "extensions": None}
            check_image(f, creative_image_sizes(kind, spec, actual), img_rules, rep, scope, fix,
                        f"{kind} creative asset")


# In-app event media (App Store Connect Help › In-app event media and audio specifications, read 2026-10-14):
# card 16:9 from 1920x1080 to 3840x2160, details page 9:16 from 1080x1920 to 2160x3840; JPEG or PNG; video
# .mov/.m4v/.mp4 at 30 or 60 fps, 15 to 30 s (creative-assets specifications), 500 MB at most.
EVENT_MEDIA = {"card": {"ratio": (16, 9), "min": (1920, 1080), "max": (3840, 2160)},
               "details": {"ratio": (9, 16), "min": (1080, 1920), "max": (2160, 3840)}}
EVENT_VIDEO = {"fps": [30, 60], "seconds": [15, 30], "max_bytes": 500_000_000}


def check_growth(kit, rules, rep, fix):
    """Custom product page and treatment screenshots (the slot sizes, 1-10 per set; no required sets: a missing
    language or size falls back to the default product page), their creative assets, and event media."""
    root = kit / "growth"
    if not root.exists():
        return
    sr, slots = rules["screenshots"], rules["screenshots"]["slots"]
    for shots in sorted(root.rglob("screenshots")):
        for loc in sorted(p for p in shots.iterdir() if p.is_dir()):
            for sd in sorted(p for p in loc.iterdir() if p.is_dir()):
                scope = sd.relative_to(kit).as_posix()
                if sd.name not in slots:
                    rep.err(scope, f"unknown slot '{sd.name}'; known: {', '.join(slots)}")
                    continue
                files = images_in(sd)
                if not (sr["min_per_set"] <= len(files) <= sr["max_per_set"]):
                    rep.err(scope, f"{len(files)} screenshot(s); Apple allows {sr['min_per_set']}-{sr['max_per_set']}")
                for f in files:
                    check_image(f, accepted_sizes(slots[sd.name]), sr, rep, scope, fix, slots[sd.name]["label"])
    for previews in sorted(root.rglob("previews")):
        if previews.is_dir():
            check_previews(kit, rules, rep, previews, previews.relative_to(kit).as_posix() + "/")
    for creative in sorted(root.rglob("creative")):
        check_creative(kit, rules, rep, fix, creative, creative.parent.relative_to(kit).as_posix() + "/")
    for media in sorted(root.glob("*/media")):
        for loc in sorted(p for p in media.iterdir() if p.is_dir()):
            for f in sorted(x for x in loc.iterdir() if x.is_file() and not x.name.startswith(".")):
                scope = f.relative_to(kit).as_posix()
                spec = EVENT_MEDIA.get(f.stem.lower())
                if not spec:
                    rep.warn(scope, "name it card or details; it is not uploaded")
                elif f.suffix.lower() in (".mp4", ".mov", ".m4v"):
                    check_event_video(f, spec, rep, scope)
                else:
                    check_event_image(f, spec, rules, rep, scope, fix)


def _fits(w, h, spec):
    rw, rh = spec["ratio"]
    return w * rh == h * rw and spec["min"][0] <= w <= spec["max"][0]


def check_event_image(f, spec, rules, rep, scope, fix):
    try:
        with Image.open(f) as im:
            w, h = im.size
    except Exception:
        w, h = 0, 0
    sizes = {(w, h)} if _fits(w, h, spec) else {spec["min"]}
    check_image(f, sizes, {**rules["screenshots"], "formats": ["PNG", "JPEG"], "extensions": None}, rep, scope, fix,
                f"in-app event {f.stem.lower()} ({spec['ratio'][0]}:{spec['ratio'][1]}, {spec['min'][0]}x{spec['min'][1]} "
                f"to {spec['max'][0]}x{spec['max'][1]})")


def check_event_video(f, spec, rep, scope):
    try:
        import preview_check
    except ImportError:  # pragma: no cover
        sys.path.insert(0, str(HERE)); import preview_check
    try:
        probe = preview_check.ffprobe(f)
    except Exception as e:
        rep.err(scope, f"ffprobe failed ({e})"); return
    v = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)
    if not v:
        rep.err(scope, "no video stream"); return
    w, h = int(v.get("width", 0)), int(v.get("height", 0))
    dur = float(probe.get("format", {}).get("duration") or 0)
    fps = preview_check._rate(v.get("avg_frame_rate")) or 0
    bad = []
    size = max(f.stat().st_size, int(probe.get("format", {}).get("size") or 0))
    if size > EVENT_VIDEO["max_bytes"]:
        bad.append(f"{size} bytes, maximum 500 MB")
    if not _fits(w, h, spec):
        bad.append(f"{w}x{h}, need {spec['ratio'][0]}:{spec['ratio'][1]} from {spec['min'][0]}x{spec['min'][1]} to "
                   f"{spec['max'][0]}x{spec['max'][1]}")
    if not EVENT_VIDEO["seconds"][0] <= dur <= EVENT_VIDEO["seconds"][1]:
        bad.append(f"{dur:.1f} s, need 15 to 30 s")
    if not any(abs(fps - x) < 0.5 for x in EVENT_VIDEO["fps"]):
        bad.append(f"{fps:.2f} fps, need 30 or 60")
    for b in bad:
        rep.err(scope, b)
    if not bad:
        rep.ok(scope, f"{w}x{h} {dur:.1f} s")


def check_creative_video(f, kind, vspec, rep, scope):
    if kind == "universal":
        rep.err(scope, f"{f.name}: Apple has no 16:9 video size; a universal asset is a 5244x2950 image. Use header.mov and search.mov")
        return
    spec = vspec[kind]
    try:
        import preview_check
    except ImportError:  # pragma: no cover
        sys.path.insert(0, str(HERE)); import preview_check
    try:
        probe = preview_check.ffprobe(f)
    except Exception as e:
        rep.err(scope, f"{f.name}: ffprobe failed ({e})"); return
    v = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)
    if not v:
        rep.err(scope, f"{f.name}: no video stream"); return
    w, h = int(v.get("width", 0)), int(v.get("height", 0))
    dur = float(probe.get("format", {}).get("duration") or 0)
    errs = 0
    if "sizes" in spec and [w, h] not in spec["sizes"]:
        rep.err(scope, f"{f.name}: {w}x{h}, need " + ", ".join(f"{a}x{b}" for a, b in spec["sizes"])); errs += 1
    if "ratio" in spec and (w * spec["ratio"][1] != h * spec["ratio"][0]
                            or not spec["widths"][0] <= w <= spec["widths"][1]):
        rep.err(scope, f"{f.name}: {w}x{h}, need {spec['ratio'][0]}:{spec['ratio'][1]} from "
                       f"{spec['widths'][0]} to {spec['widths'][1]} wide"); errs += 1
    lo, hi = spec["seconds"]
    if not lo <= dur <= hi:
        rep.err(scope, f"{f.name}: {dur:.1f} s, need {lo} to {hi} s"); errs += 1
    if "fps" in spec:
        fps = preview_check._rate(v.get("avg_frame_rate")) or 0
        if not any(abs(fps - x) < 0.5 for x in spec["fps"]):
            rep.err(scope, f"{f.name}: {fps:.2f} fps, need " + " or ".join(map(str, spec["fps"]))); errs += 1
    if not errs:
        rep.ok(scope, f"{f.name}: {w}x{h} {dur:.1f} s")


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
    ap.add_argument("--project", help="Xcode project folder, built .app/.xcarchive or .ipa (watch app detection)")
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
    families, notes = kit_families(kit, a.platforms, a.project)
    for n in notes:
        rep.note("kit", n)
    missing = {}
    locales = check_screenshots(kit, rules, rep, families, a.fix, today, missing)
    check_previews(kit, rules, rep)
    check_iap(kit, rules, rep, a.fix)
    check_creative(kit, rules, rep, a.fix)
    check_growth(kit, rules, rep, a.fix)
    check_frames(kit, rules, rep)
    rep.print()
    if a.report:
        write_report(a.report, rep, locales, missing)
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
