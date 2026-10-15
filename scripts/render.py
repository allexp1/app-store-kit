#!/usr/bin/env python3
"""Render App Store screenshot frames: frames.yaml + templates/*.html -> exact-size, alpha-free PNGs.

Usage:
  render.py KIT/frames.yaml [--out KIT] [--locale en-US] [--slot iphone-di-medium] [--only ID]
            [--html-only] [--embed-srgb] [--renderer auto|playwright|chrome] [--rules R]

Writes OUT/screenshots/<locale>/<slot>/<NN>-<id>.png (the layout validate_kit.py reads) and
OUT/html/<locale>/<slot>/<NN>-<id>.html. With --html-only it also writes OUT/html/<locale>/<slot>/figma-seed.html,
every frame of the set on one page with class="frame" roots, ready for Figma's html_to_figma
(cssSelector ".frame"). Captures are inlined as data URIs, so the HTML is self-contained.

Renderers: Playwright for Python if importable, else the bare chrome-headless-shell / Chromium binary
from the Playwright cache (~/Library/Caches/ms-playwright) or $CHROME. Output is converted to RGB
(alpha stripped) and checked to be exactly W x H.
"""
from __future__ import annotations

import argparse
import base64
import glob
import html
import json
import mimetypes
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import yaml
from PIL import Image, ImageCms

HERE = pathlib.Path(__file__).resolve().parent
TEMPLATES = HERE.parent / "templates"
PLACE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")


def data_uri(path: pathlib.Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def split_template(name: str):
    src = (TEMPLATES / f"{name}.html").read_text()
    style = re.search(r"(?is)<style>(.*?)</style>", src).group(1)
    body = re.search(r"(?is)<body[^>]*>(.*?)</body>", src).group(1).strip()
    return style, body


def fill(body: str, values: dict) -> str:
    def rep(m):
        k = m.group(1)
        if k not in values:
            raise KeyError(f"template placeholder {{{{{k}}}}} has no value")
        return values[k]
    return PLACE.sub(rep, body)


def layout(w, h, cap_aspect, slot_cfg, caption_lines=3):
    """Whole-pixel geometry shared by all templates. cap_aspect = capture height / width."""
    fs = int(slot_cfg.get("font_px", round(w * (0.076 if h / w > 1.6 else 0.05))))
    side = int(slot_cfg.get("caption_side", round(w * 0.1)))
    cap_top = int(slot_cfg.get("caption_top", round(h * 0.057)))
    bezel = int(slot_cfg.get("bezel", max(8, round(w * 0.018))))
    radius = int(slot_cfg.get("radius", round(w * (0.1 if h / w > 1.8 else 0.015))))
    bottom = int(round(h * 0.035))
    cap_area = cap_top + int(caption_lines * fs * 1.08) + int(h * 0.03)
    scale = float(slot_cfg.get("device_scale", 0.73))
    dev_w = int(round(w * scale))
    max_h = h - cap_area - bottom - 2 * bezel
    if dev_w * cap_aspect > max_h:
        dev_w = int(max_h / cap_aspect)
    dev_h = int(round(dev_w * cap_aspect))
    dev_x = (w - dev_w - 2 * bezel) // 2
    dev_y = h - bottom - dev_h - 2 * bezel
    return {
        "--w": f"{w}px", "--h": f"{h}px", "--fs": f"{fs}px", "--cap-side": f"{side}px", "--cap-top": f"{cap_top}px",
        "--bezel": f"{bezel}px", "--radius": f"{radius}px", "--dev-w": f"{dev_w}px", "--dev-h": f"{dev_h}px",
        "--dev-x": f"{dev_x}px", "--dev-y": f"{dev_y}px", "--dev-y-bottom": f"{bottom}px",
        "--band-h": f"{cap_area}px", "--fade": f"{int(h * 0.04)}px", "--hairline": f"{max(1, w // 600)}px",
    }


def slot_size(slot_id, cfg, rules):
    if cfg.get("width") and cfg.get("height"):
        return int(cfg["width"]), int(cfg["height"])
    s = rules["screenshots"]["slots"][slot_id]["sizes"][0]
    return int(s[0]), int(s[1])


def build_frames(spec_path: pathlib.Path, rules: dict, locales=None, slots=None, only=None):
    spec = yaml.safe_load(spec_path.read_text())
    base = spec_path.parent
    d = spec.get("defaults", {})
    out = []  # (locale, slot, index, id, template, w, h, html_body, style)
    for loc in locales or spec.get("locales", ["en-US"]):
        for slot_id, scfg in (spec.get("slots") or {}).items():
            if slots and slot_id not in slots:
                continue
            w, h = slot_size(slot_id, scfg or {}, rules)
            for i, fr in enumerate(spec.get("frames", []), 1):
                if only and fr["id"] not in only:
                    continue
                screens = fr.get("screen", {})
                spath = screens.get(slot_id) if isinstance(screens, dict) else screens
                if not spath:
                    continue
                spath = base / str(spath).format(locale=loc)
                if not spath.exists():
                    raise FileNotFoundError(f"frame {fr['id']} ({loc}/{slot_id}): capture {spath} not found")
                cap = fr.get("caption", "")
                cap = cap.get(loc, cap.get("*", "")) if isinstance(cap, dict) else cap
                tpl = fr.get("template", d.get("template", "caption-top"))
                dark = tpl == "dark" or fr.get("dark")
                with Image.open(spath) as im:
                    aspect = im.height / im.width
                geo = layout(w, h, aspect, {**(scfg or {}), **fr.get("layout", {})})
                geo.update({
                    "--bg": fr.get("background", d.get("dark_background" if dark else "background", "#FFFFFF")),
                    "--ink": fr.get("ink", d.get("dark_ink" if dark else "ink", "#111111")),
                    "--device": fr.get("device", d.get("dark_device" if dark else "device", "#111111")),
                    "--font": d.get("font", '-apple-system, system-ui, sans-serif'),
                })
                style, body = split_template(tpl)
                values = {
                    "ID": f"{loc}-{slot_id}-{i:02d}-{fr['id']}",
                    "VARS": html.escape(";".join(f"{k}:{v}" for k, v in geo.items()), quote=True),
                    "CAPTION": html.escape(str(cap)),
                    "SCREEN": data_uri(spath),
                }
                out.append((loc, slot_id, i, fr["id"], tpl, w, h, fill(body, values), style))
    return out


def page(styles, bodies):
    css = "\n".join(dict.fromkeys(styles))
    return ("<!doctype html><html><head><meta charset='utf-8'><style>*{box-sizing:content-box}"
            f"body{{margin:0}}\n{css}</style></head><body>\n" + "\n".join(bodies) + "\n</body></html>")


def find_chrome():
    if os.environ.get("CHROME"):
        return os.environ["CHROME"]
    pats = [
        "~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell",
        "~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell",
        "~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
    ]
    for p in pats:
        hits = sorted(glob.glob(os.path.expanduser(p)))
        if hits:
            return hits[-1]
    for name in ("chrome-headless-shell", "chromium", "google-chrome", "chromium-browser"):
        if shutil.which(name):
            return shutil.which(name)
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    return mac if os.path.exists(mac) else None


def shoot_playwright(html_path, png_path, w, h):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception:
            # the pip package's pinned browser may be missing; any cached Chromium works
            chrome = find_chrome()
            if not chrome:
                raise
            b = p.chromium.launch(executable_path=chrome)
        pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
        pg.goto(pathlib.Path(html_path).resolve().as_uri())
        pg.evaluate("document.fonts.ready")
        pg.locator(".frame").first.screenshot(path=str(png_path))
        b.close()


def shoot_chrome(html_path, png_path, w, h, chrome):
    cmd = [chrome, "--headless", "--hide-scrollbars", "--force-device-scale-factor=1", "--disable-gpu",
           f"--window-size={w},{h}", "--default-background-color=00000000",
           f"--screenshot={png_path}", pathlib.Path(html_path).resolve().as_uri()]
    if "headless-shell" in chrome:
        cmd.remove("--headless")
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)


def finish_png(png_path, w, h, embed_srgb=False):
    with Image.open(png_path) as im:
        im.load()
        if im.size != (w, h):
            raise RuntimeError(f"{png_path}: renderer produced {im.size[0]}x{im.size[1]}, expected {w}x{h}")
        rgb = Image.new("RGB", im.size, (255, 255, 255))
        rgba = im.convert("RGBA")
        rgb.paste(rgba, mask=rgba.split()[-1])
    kw = {}
    if embed_srgb:
        kw["icc_profile"] = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    rgb.save(png_path, "PNG", **kw)


def pick_renderer(choice):
    if choice in ("auto", "playwright"):
        try:
            import playwright.sync_api  # noqa: F401
            return "playwright", None
        except ImportError:
            if choice == "playwright":
                sys.exit("playwright is not installed (pip install playwright && playwright install chromium)")
    chrome = find_chrome()
    if not chrome:
        sys.exit("no renderer: install Playwright for Python, or set $CHROME to a Chromium/chrome-headless-shell binary")
    return "chrome", chrome


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("frames")
    ap.add_argument("--out")
    ap.add_argument("--locale", action="append")
    ap.add_argument("--slot", action="append")
    ap.add_argument("--only", action="append")
    ap.add_argument("--html-only", action="store_true")
    ap.add_argument("--embed-srgb", action="store_true")
    ap.add_argument("--renderer", default="auto", choices=["auto", "playwright", "chrome"])
    ap.add_argument("--rules")
    a = ap.parse_args(argv)
    spec = pathlib.Path(a.frames)
    out = pathlib.Path(a.out or spec.parent)
    rules_p = pathlib.Path(a.rules) if a.rules else (spec.parent / "rules.json" if (spec.parent / "rules.json").exists() else HERE / "rules.json")
    rules = json.loads(rules_p.read_text())
    frames = build_frames(spec, rules, a.locale, a.slot, a.only)
    if not frames:
        sys.exit("no frames matched")
    sets = {}
    for loc, slot, i, fid, tpl, w, h, body, style in frames:
        hdir = out / "html" / loc / slot
        hdir.mkdir(parents=True, exist_ok=True)
        hp = hdir / f"{i:02d}-{fid}.html"
        hp.write_text(page([style], [body]))
        sets.setdefault((loc, slot), []).append((style, body))
        if a.html_only:
            continue
        kind, chrome = pick_renderer(a.renderer)
        pdir = out / "screenshots" / loc / slot
        pdir.mkdir(parents=True, exist_ok=True)
        pp = pdir / f"{i:02d}-{fid}.png"
        with tempfile.TemporaryDirectory() as td:
            raw = pathlib.Path(td) / "raw.png"
            (shoot_playwright if kind == "playwright" else lambda *x: shoot_chrome(*x, chrome))(hp, raw, w, h)
            shutil.move(raw, pp)
        finish_png(pp, w, h, a.embed_srgb)
        print(f"{pp}  {w}x{h}  ({kind})")
    for (loc, slot), items in sets.items():
        seed = out / "html" / loc / slot / "figma-seed.html"
        seed.write_text(page([s for s, _ in items], [b for _, b in items]))
        print(f"{seed}  ({len(items)} frames, for html_to_figma cssSelector='.frame')")
    return 0


if __name__ == "__main__":
    sys.exit(main())
