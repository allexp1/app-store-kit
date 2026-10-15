"""Render, slice, check and export a campaign."""
from __future__ import annotations

import hashlib
import html
import json
import pathlib
import shutil

from PIL import Image, ImageCms, ImageDraw, ImageStat

from . import analyze, chrome, engines, fonts, scene
from .spec import screen_path, slot_size, text_for, tokens

THUMB_PT = 115     # an App Store search-result screenshot is about this wide on an iPhone, in points
MIN_THUMB_PT = 10.5  # a headline smaller than this at thumbnail size stops reading


def layout_for(spec, engine=None, blocks=None):
    """The layers to render: the spec's own (ejected or hand-written) or an engine's, plus extra_layers."""
    if spec.get("layers") and not engine:
        out = {"background": spec.get("background") or [{"type": "solid", "color": "bg"}],
               "layers": spec["layers"], "engine": spec["campaign"].get("engine") or "custom"}
    else:
        name = engine or spec["campaign"].get("engine") or "floating-3d"
        g = engines.generate(spec, name, blocks)
        out = {"background": spec.get("background") or g["background"], "layers": g["layers"], "engine": name}
    out["layers"] = list(out["layers"]) + list(spec.get("extra_layers") or [])
    return out


def screen_blocks(spec, locale, slot):
    blocks = {}
    for sid in spec["screens"]:
        p, _ = screen_path(spec, sid, locale, slot)
        if p and p.exists():
            with Image.open(p) as im:
                blocks[sid] = analyze.ui_blocks(im.convert("RGB"))
    return blocks


def locale_scripts(spec, locale):
    s = set()
    prim = spec["campaign"]["primary_locale"]
    for p in spec["storyboard"]:
        for f in ("headline", "sub", "kicker"):
            t, _ = text_for(p.get(f), locale, prim)
            if t:
                s |= fonts.scripts_in(t, locale)
    for L in spec.get("layers") or []:
        if L.get("type") == "display":
            t, _ = text_for(L.get("text"), locale, prim)
            s |= fonts.scripts_in(t or "", locale)
    return s


def mirror_for(spec, locale):
    return fonts.is_rtl(locale) and spec["campaign"]["rtl_flow"] == "mirror"


def render_master(spec, layout, locale, slot, workdir: pathlib.Path, scale=1.0, offline=False, chrome_bin=None):
    """Two passes: measure (fit text, boxes, fonts) then shoot. Returns paths, measure, notes."""
    sid, W, H = slot
    N = spec["campaign"]["panels"]
    MW = N * W
    workdir.mkdir(parents=True, exist_ok=True)
    type_cfg = spec["design"]["type"]
    if "serif" in json.dumps(layout.get("layers") or []) or type_cfg.get("accent_style") == "serif":
        type_cfg = {**type_cfg, "extra_faces": list(type_cfg.get("extra_faces") or []) + [scene.SERIF_ACCENT]}
    finfo, font_css, notes = fonts.resolve(type_cfg, locale_scripts(spec, locale), pathlib.Path(spec["_base"]),
                                           offline)
    mirror = mirror_for(spec, locale)
    page, meta = scene.build(spec, locale, sid, W, H, layout, finfo, font_css, mirror=mirror, measure=True)
    mp = workdir / "measure.html"
    mp.write_text(page)
    m = scene.parse_measure(chrome.dump_dom(mp, MW, H, chrome_bin))
    if not m.get("ok"):
        raise RuntimeError(f"measuring failed: {m.get('error')}")
    fit = {t["tid"]: t["fs"] for t in m["texts"]}
    page, meta = scene.build(spec, locale, sid, W, H, layout, finfo, font_css, fit=fit, mirror=mirror, measure=False)
    hp = workdir / "scene.html"
    hp.write_text(page)
    png = workdir / ("master.png" if scale == 1 else f"master@{scale:g}.png")
    chrome.screenshot(hp, png, MW, H, scale, chrome_bin)
    return {"html": hp, "png": png, "measure": m, "meta": meta, "fonts": finfo, "font_notes": notes,
            "fit": fit, "mirror": mirror, "font_css": font_css}


def to_rgb(im):
    im.load()
    if im.mode == "RGB":
        return im.copy()
    rgba = im.convert("RGBA")
    out = Image.new("RGB", im.size, (255, 255, 255))
    out.paste(rgba, mask=rgba.split()[-1])
    return out


def srgb_bytes():
    b = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    b[24:36] = bytes(12)   # the header's creation date: zeroed so the same render gives the same bytes
    return bytes(b)


def slice_panels(master_png, N, W, H, mirror, out_dir: pathlib.Path, ids):
    """Cut the master into N exact panels. Store order: panel 1 first (rightmost when the flow is mirrored)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    icc = srgb_bytes()
    with Image.open(master_png) as im:
        im.load()
        if im.size != (N * W, H):
            raise RuntimeError(f"master is {im.size}, expected {(N * W, H)}")
        rgb = to_rgb(im)
    files = []
    for k in range(N):
        col = (N - 1 - k) if mirror else k
        tile = rgb.crop((col * W, 0, (col + 1) * W, H))
        f = out_dir / f"{k + 1:02d}-{ids[k]}.png"
        tile.save(f, "PNG", icc_profile=icc, optimize=False)
        files.append(f)
    rgb.save(out_dir.parent / "panorama.png", "PNG", icc_profile=icc)
    return files


def reassemble_ok(files, master_png, N, W, H, mirror):
    """Pixel-exact: the panels put back side by side must equal the master."""
    with Image.open(master_png) as m:
        m = to_rgb(m)
        for k, f in enumerate(files):
            col = (N - 1 - k) if mirror else k
            with Image.open(f) as t:
                if t.size != (W, H) or t.tobytes() != m.crop((col * W, 0, (col + 1) * W, H)).tobytes():
                    return False
    return True


def _inter(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    return max(0, x1 - x0) * max(0, y1 - y0)


def contrast(a, b):
    la, lb = a, b
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def rel_lum(rgb):
    lin = [(c / 255) / 12.92 if c / 255 <= 0.03928 else (((c / 255) + 0.055) / 1.055) ** 2.4 for c in rgb[:3]]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def qa(spec, r, slot, notext_png=None, notext_scale=0.25):
    """Objective checks on one rendered master. Returns [(level, where, msg)]."""
    sid, W, H = slot
    N = spec["campaign"]["panels"]
    u = scene.unit(W, H)
    safe = spec["design"]["safe"]
    m = r["measure"]
    issues = []
    for lvl, msg in r["font_notes"]:
        issues.append((lvl, "fonts", msg))
    for src in m.get("images_broken") or []:
        issues.append(("error", "assets", f"image did not load: {src}"))
    for fam, ok in (m.get("fonts") or {}).items():
        if not ok:
            issues.append(("warn", "fonts", f"{fam} did not load; a system face was used"))
    by_tid = {t["tid"]: t for t in r["meta"]["texts"]}
    texts = m["texts"]
    nt = None
    if notext_png:
        nt = Image.open(notext_png).convert("RGB")
    for t in texts:
        info = by_tid.get(t["tid"], {})
        p = info.get("panel") or t.get("panel")
        col = (N - p) if r["mirror"] else (p - 1)
        where = f"panel {p} {t['role']}"
        x, y, w, h = t["rect"]
        left, right = col * W, (col + 1) * W
        if x < left - 0.5 or x + w > right + 0.5:
            issues.append(("error", where, f"text crosses the panel edge: {info.get('text', '')!r}"))
        elif x < left + safe["side"] * W * 0.6 or x + w > right - safe["side"] * W * 0.6:
            issues.append(("warn", where, "text is inside the side safe margin"))
        if y < safe["top"] * H * 0.5 or y + h > H - safe["bottom"] * H * 0.5:
            issues.append(("warn", where, "text is inside the top/bottom safe margin"))
        if t.get("min_hit") or t.get("overflow"):
            issues.append(("error", where, f"does not fit even at the minimum size ({t['lines']} lines): "
                                           f"{info.get('text', '')!r}; shorten it or widen the box"))
        if not t.get("font_ok", True):
            issues.append(("warn", where, f"{info.get('family')} lacks glyphs for this text; a fallback face drew them"))
        if t["role"] == "headline":
            thumb = t["fs"] * THUMB_PT / W
            if p <= 3 and thumb < MIN_THUMB_PT:
                issues.append(("warn", where, f"headline is {thumb:.1f} pt at search-result size "
                                              f"(aim ≥ {MIN_THUMB_PT} pt): the first three carry the pitch"))
        if nt is not None and t["role"] in ("headline", "sub"):
            s = notext_scale
            box = (int(x * s), int(y * s), int((x + w) * s) + 1, int((y + h) * s) + 1)
            if box[2] > box[0] and box[3] > box[1]:
                region = nt.crop(box)
                med = ImageStat.Stat(region).median
                # darkest / lightest tenth also matter: busy backgrounds
                ink = r["meta"]
                txt_col = _text_color(r, t["tid"])
                if txt_col:
                    cr = contrast(rel_lum(txt_col), rel_lum(med))
                    lvl = "error" if cr < 2.0 else "warn" if cr < 3.0 else None
                    if lvl:
                        issues.append((lvl, where, f"contrast {cr:.1f}:1 against the background behind it (≥ 3:1)"))
    for a in texts:
        for b in texts:
            if a["tid"] < b["tid"] and _inter(a["rect"], b["rect"]) > 0.08 * min(a["rect"][2] * a["rect"][3],
                                                                                 b["rect"][2] * b["rect"][3]):
                if a["tid"].split("-")[0] != b["tid"].split("-")[0]:
                    issues.append(("error", "text", f"two text blocks overlap ({a['tid']}, {b['tid']})"))
    screens = [e for e in m["els"] if e["kind"] in ("device", "card", "image")]
    for t in texts:
        if t["role"] != "headline":
            continue
        for e in screens:
            if e["kind"] == "device" and _inter(t["rect"], e["rect"]) > 0.2 * t["rect"][2] * t["rect"][3]:
                issues.append(("warn", f"panel {t.get('panel')} headline", "headline sits over the phone screen"))
    for k in range(N):
        col = (N - 1 - k) if r["mirror"] else k
        pr = [col * W, 0, W, H]
        cover = sum(_inter(pr, e["rect"]) for e in screens if e["kind"] in ("device", "card"))
        if cover < 0.08 * W * H:
            issues.append(("warn", f"panel {k + 1}", "little or no real UI in this panel"))
        if k == 0:
            best = max((_inter(pr, e["rect"]) for e in screens if e["kind"] == "device"), default=0)
            if best < 0.16 * W * H:
                issues.append(("warn", "panel 1", "the hero phone screen is small; the first panel sells the app"))
    return issues


def _text_color(r, tid):
    import re as _re
    page = pathlib.Path(r["html"]).read_text()
    mm = _re.search(r'data-tid="%s"[^>]*style="[^"]*?;color:(#[0-9A-Fa-f]{6}|rgba?\([^)]*\))' % _re.escape(tid), page)
    if not mm:
        return None
    c = mm.group(1)
    if c.startswith("#"):
        return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
    nums = [float(v) for v in _re.findall(r"[\d.]+", c)[:3]]
    return tuple(int(v) for v in nums)


def notext_pass(spec, layout, locale, slot, r, workdir, scale=0.25, chrome_bin=None):
    sid, W, H = slot
    page, _ = scene.build(spec, locale, sid, W, H, layout, r["fonts"], r["font_css"], fit=r["fit"],
                          mirror=r["mirror"], hide_text=True, measure=False)
    hp = workdir / "notext.html"
    hp.write_text(page)
    png = workdir / "notext.png"
    chrome.screenshot(hp, png, spec["campaign"]["panels"] * W, H, scale, chrome_bin)
    return png


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def store_preview(files, out_png, height=520, gap=18):
    """The first three panels at roughly search-result scale, for the at-a-glance read."""
    tiles = []
    for f in files[:3]:
        with Image.open(f) as im:
            w = int(im.width * height / im.height)
            tiles.append(im.convert("RGB").resize((w, height), Image.LANCZOS))
    W = sum(t.width for t in tiles) + gap * (len(tiles) + 1)
    sheet = Image.new("RGB", (W, height + 2 * gap), (242, 242, 247))
    x = gap
    for t in tiles:
        mask = Image.new("L", t.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, t.width - 1, t.height - 1), radius=int(t.width * 0.06), fill=255)
        sheet.paste(t, (x, gap), mask)
        x += t.width + gap
    sheet.save(out_png)


def presentation(files, out_png, width=3600, gap=None, bg=(236, 236, 240), rtl=False):
    """All panels in a row with gutters, as on a product page (right to left for an RTL storefront)."""
    files = list(reversed(files)) if rtl else list(files)
    n = len(files)
    with Image.open(files[0]) as im:
        W, H = im.size
    gap = gap or int(width * 0.012)
    tw = (width - gap * (n + 1)) / n
    th = int(H * tw / W)
    sheet = Image.new("RGB", (width, th + 2 * gap), bg)
    for k, f in enumerate(files):
        with Image.open(f) as im:
            t = im.convert("RGB").resize((int(tw), th), Image.LANCZOS)
        mask = Image.new("L", t.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, t.width - 1, t.height - 1), radius=int(t.width * 0.05), fill=255)
        sheet.paste(t, (int(gap + k * (tw + gap)), gap), mask)
    sheet.save(out_png)


def export_checks(files, W, H, N):
    issues = []
    if len(files) != N:
        issues.append(("error", "export", f"{len(files)} files for {N} panels"))
    names = [f.name for f in files]
    if names != sorted(names):
        issues.append(("error", "export", "file names do not sort in store order"))
    for f in files:
        try:
            with Image.open(f) as im:
                im.verify()
            with Image.open(f) as im:
                if im.format != "PNG":
                    issues.append(("error", f.name, f"format {im.format}, expected PNG"))
                if im.size != (W, H):
                    issues.append(("error", f.name, f"{im.size[0]}x{im.size[1]}, expected {W}x{H}"))
                if im.mode != "RGB":
                    issues.append(("error", f.name, f"mode {im.mode}: App Store screenshots must not have alpha"))
                if not im.info.get("icc_profile"):
                    issues.append(("warn", f.name, "no colour profile (sRGB assumed)"))
                ext = im.getextrema()
                if all(lo == hi for lo, hi in ext):
                    issues.append(("error", f.name, "the image is one flat colour (render failed?)"))
        except Exception as e:
            issues.append(("error", f.name, f"unreadable: {e}"))
    return issues


def write_report(path, title, issues, extra_lines=()):
    lv = {"error": 0, "warn": 1, "note": 2}
    lines = [f"# {title}", ""]
    errs = sum(1 for i in issues if i[0] == "error")
    warns = sum(1 for i in issues if i[0] == "warn")
    lines.append(f"**{'PASS' if not errs else 'FAIL'}**: {errs} error(s), {warns} warning(s)")
    lines.append("")
    lines += list(extra_lines)
    for lvl, where, msg in sorted(issues, key=lambda i: lv.get(i[0], 3)):
        lines.append(f"- **{lvl}** `{where}`: {msg}")
    pathlib.Path(path).write_text("\n".join(lines) + "\n")
    return errs


CONTACT_CSS = """
body{margin:0;background:#101012;color:#ECEBE7;font-family:'Geist',system-ui,sans-serif}
.sheet{width:%(W)dpx;padding:72px 80px 90px;box-sizing:border-box}
h1{font-size:54px;letter-spacing:-.02em;margin:0 0 6px;font-weight:700}
.lede{font-size:24px;color:#A3A19B;margin:0 0 54px}
.row{display:grid;grid-template-columns:420px 1fr;gap:44px;padding:38px 0;border-top:1px solid #2A2A2E}
.tag{display:inline-block;font:600 18px 'Geist Mono',monospace;letter-spacing:.14em;color:#101012;background:#ECEBE7;
  padding:6px 12px;border-radius:6px}
.concept{font:600 15px 'Geist Mono',monospace;letter-spacing:.2em;color:#FF6B4A;margin-left:12px}
h2{font-size:40px;margin:18px 0 10px;letter-spacing:-.02em}
.p{font-size:20px;line-height:1.45;color:#C9C7C1;margin:0 0 14px}
.k{color:#7E7C76;font:500 15px 'Geist Mono',monospace;letter-spacing:.08em;text-transform:uppercase;margin-top:18px}
.sw{display:flex;gap:8px;margin-top:8px}.sw i{width:34px;height:34px;border-radius:8px;border:1px solid #333}
.img img{width:100%%;display:block;border-radius:14px}
.foot{margin-top:40px;color:#7E7C76;font-size:18px}
"""


def contact_sheet(concepts, out_png, title, width=3000, chrome_bin=None, font_css=""):
    rows = []
    for c in concepts:
        sw = "".join(f'<i style="background:{html.escape(v)}"></i>' for v in c["palette_swatches"])
        rows.append(f"""<div class="row"><div><span class="tag">{html.escape(c['letter'])}</span>
<span class="concept">CONCEPT · NOT FINAL</span><h2>{html.escape(c['label'])}</h2>
<p class="p">{html.escape(c['mood'])}</p><p class="p">{html.escape(c.get('rationale') or '')}</p>
<div class="k">Composition</div><p class="p">{html.escape(c['pattern'])}</p>
<div class="k">Type · {html.escape(c['type'])}</div><p class="p">{html.escape(c['type_mood'])}</p>
<div class="k">Palette</div><div class="sw">{sw}</div></div>
<div class="img"><img src="{pathlib.Path(c['preview']).resolve().as_uri()}"></div></div>""")
    page = (f"<!doctype html><html><head><meta charset='utf-8'><style>{font_css}{CONTACT_CSS % {'W': width}}</style>"
            f"</head><body><div class='sheet'><h1>{html.escape(title)}</h1><p class='lede'>"
            f"{len(concepts)} creative directions, rendered from the app's real screenshots at preview resolution. "
            f"Pick one, combine two, or ask for alternatives.</p>{''.join(rows)}"
            f"<p class='foot'>Concept previews: low resolution, copy and layout not final. "
            f"Screens: the app's own captures.</p></div></body></html>")
    hp = pathlib.Path(out_png).with_suffix(".html")
    hp.write_text(page)
    # height: measure via a generous window, then trim the empty bottom
    h = 400 + 760 * len(concepts)
    chrome.screenshot(hp, out_png, width, h, 1.0, chrome_bin)
    with Image.open(out_png) as im:
        rgb = to_rgb(im)
    bbox = Image.eval(rgb.convert("L"), lambda v: 255 if v > 22 else 0).getbbox()
    if bbox:
        rgb = rgb.crop((0, 0, width, min(h, bbox[3] + 90)))
    rgb.save(out_png)
    return out_png


def manifest_entry(files):
    out = []
    for f in files:
        with Image.open(f) as im:
            out.append({"file": str(f), "size": list(im.size), "sha256": sha(f)})
    return out


def install(files, kit_dir: pathlib.Path, locale, slot_id):
    """Copy validated panels into KIT/screenshots/<locale>/<slot>/ (the layout validate_kit / asc_sync read)."""
    dest = kit_dir / "screenshots" / locale / slot_id
    dest.mkdir(parents=True, exist_ok=True)
    old = sorted(dest.glob("*.png"))
    for o in old:
        o.unlink()
    for f in files:
        shutil.copy2(f, dest / f.name)
    return dest, [o.name for o in old]


def campaign_tokens(spec):
    return tokens(spec)


def write_json(path, obj):
    pathlib.Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def slot_tuple(slot, rules):
    return slot_size(slot, rules)
