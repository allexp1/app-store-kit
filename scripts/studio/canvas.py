"""Export a campaign as a Claude Design canvas (the claude.ai "Design" Artifact type): the panorama and each
panel become artboards whose headlines are live text, screenshots are swappable images and every element
keeps its inline style (what the canvas's properties panel edits).

The script only prepares files. Publishing is done from the Claude session with the Artifact tool:
  1. campaign.py canvas CAMPAIGN --out DIR             -> DIR/project/*.dc.html, canvas.json, DIR/assets.json
  2. create the canvas (Artifact publish with the Design type_url, a title, nothing else)
  3. upload every file in assets.json (Artifact publish, url=<canvas>, asset: true) and write
     DIR/asset-urls.json as {"<token>": "/_blob/<id>", ...}
  4. campaign.py canvas-link DIR                        -> swaps the tokens for the uploaded urls
  5. publish project/canvas.json + the .dc.html files to the canvas (root = DIR)
A canvas is an editing surface, not the export: production PNGs still come from `campaign.py render`.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import urllib.parse

from . import fonts, pipeline, scene
from .spec import slot_size

MAX_BOARD = 8000


def _gfonts_link(finfo):
    fams = []
    for key in ("display", "text", "mono"):
        f = finfo.get(key) or {}
        if not f.get("family") or f["family"] in fams:
            continue
        fams.append(f["family"])
    for fam, subs in (finfo.get("subsets") or {}).items():
        if fam not in fams and subs is not None:
            fams.append(fam)
    q = "&".join("family=" + urllib.parse.quote_plus(f) + ":wght@400;500;600;700;800" for f in fams)
    return f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?{q}&display=swap">'


def _body_of(page):
    m = re.search(r'<div class="canvas" id="canvas">(.*)</div><pre id="__m"', page, re.S)
    return m.group(1)


def _style_of(page):
    css = re.search(r"<style>(.*?)</style>", page, re.S).group(1)
    css = re.sub(r"@font-face\s*{[^}]*}", "", css)        # fonts come from the Google Fonts link instead
    css = re.sub(r"/\*[^*]*\*/", "", css)
    return css


def _tokenize(html_text, assets):
    def rep(m):
        uri = m.group(0)
        path = urllib.parse.unquote(urllib.parse.urlparse(uri).path)
        key = assets.setdefault(path, f"__ASSET_{len(assets) + 1:03d}__")
        return key
    return re.sub(r"file://[^\"')\s]+", rep, html_text)


FLAT = re.compile(r"(?:-webkit-)?(?:backdrop-)?filter:\s*(?:[^;\"'}()]|\((?:[^()]|\([^()]*\))*\))*;?"
                  r"|mix-blend-mode:[^;\"'}]*;?|transform-style:[^;\"'}]*;?|perspective(?:-origin)?:[^;\"'}]*;?")


def _flatten(text):
    """Strip filters, blend modes and 3D context. Each of them gives an element its own compositing layer,
    and a few boards of layered 3D phones make the canvas editor's frame go blank ~20 s after load."""
    return FLAT.sub("", text)


def _drop(html_text, ids):
    """Remove the elements carrying data-id in `ids` (a whole <div>…</div> subtree, or a void <img>)."""
    for did in ids:
        m = re.search(r'<(\w+)[^>]*\bdata-id="%s"' % re.escape(did), html_text)
        if not m:
            continue
        start, tag = m.start(), m.group(1)
        if tag == "img":
            end = html_text.index(">", m.end()) + 1
        else:
            depth, pos = 0, start
            for t in re.finditer(r"<(/?)%s\b[^>]*>" % tag, html_text[start:]):
                depth += -1 if t.group(1) else 1
                if depth == 0:
                    pos = start + t.end()
                    break
            end = pos
        html_text = html_text[:start] + html_text[end:]
    return html_text


def _off_panel(measure, html_text, col, W, N, mirror):
    """data-ids that do not touch panel column `col`: measured elements outside it, text blocks of other panels."""
    lo, hi = col * W, (col + 1) * W
    out = []
    for e in measure.get("els", []):
        x, _, w, _ = e.get("outer") or e["rect"]
        if x + w <= lo or x >= hi:
            out.append(e["id"])
    for did, p in re.findall(r'data-id="(text\d+)" data-kind="text" data-panel="(\d+)"', html_text):
        if ((N - int(p)) if mirror else (int(p) - 1)) != col:
            out.append(did)
    return out


def _small_copies(assets, out, width):
    """The canvas shows boards scaled down: upload half-size screenshots instead of the full captures."""
    from PIL import Image
    d = out / "assets"
    d.mkdir(parents=True, exist_ok=True)
    files = {}
    for src, tok in assets.items():
        dst = d / f"{tok.strip('_').lower()}{pathlib.Path(src).suffix.lower() or '.png'}"
        with Image.open(src) as im:
            im.load()
            if im.width > width:
                im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
            im.save(dst)
        files[tok] = str(dst)
    return files


def board(name, title, inner, css, link, w, h, offset_x=0):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
{link}
<style>
body{{margin:0}}
{css}
</style>
</helmet>
<div style="width: {w}px; height: {h}px; position: relative; overflow: hidden">
<div class="canvas" style="position: absolute; left: {-offset_x}px; top: 0px">
{inner}
</div>
</div>
</x-dc>
<script type="text/x-dc" data-dc-script data-props='{{"$preview":{{"width":{w},"height":{h}}}}}'>
class Component extends DCLogic {{
renderVals() {{
return {{}};
}}
}}
</script>
</body>
</html>
"""


def export(spec, rules, out: pathlib.Path, locale=None, slot=None, offline=False):
    locale = locale or spec["campaign"]["primary_locale"]
    sid, W, H = slot_size(slot or spec["campaign"]["slots"][0], rules)
    N = spec["campaign"]["panels"]
    blocks = pipeline.screen_blocks(spec, locale, sid)
    lay = pipeline.layout_for(spec, None, blocks)
    work = out / ".work"
    r = pipeline.render_master(spec, lay, locale, (sid, W, H), work, scale=0.2, offline=offline)
    # rebuild with thin phones (4 slices, not 22): seven boards of full 3D stacks stall the canvas editor
    page, _ = scene.build(spec, locale, sid, W, H, lay, r["fonts"], r["font_css"], fit=r["fit"],
                          mirror=r["mirror"], measure=False, slices=4)
    inner = _body_of(page)
    inner = re.sub(r'<div class="grain"[^>]*></div>', "", inner)   # data: URIs are not allowed on a canvas
    inner = _flatten(inner)          # flat phones: the canvas is for editing copy and layout, PNGs come from render
    css = _flatten(_style_of(page).replace("html,body", "body"))
    assets = {}
    inner = _tokenize(inner, assets)
    link = _gfonts_link(r["fonts"])
    proj = out / "project"
    proj.mkdir(parents=True, exist_ok=True)
    boards, order = {}, []
    MW = N * W
    if MW <= MAX_BOARD:
        (proj / "Main.dc.html").write_text(board("Main", f"{spec['campaign']['name']} panorama", inner, css, link, MW, H))
        boards["Main.dc.html"] = {"x": 0, "y": 0, "w": MW, "h": H, "title": "Panorama (all panels)"}
        order.append("Main.dc.html")
        y0 = H + 360
    else:
        y0 = 0
    ids = [p["id"] for p in spec["storyboard"]]
    for k in range(N):
        col = (N - 1 - k) if r["mirror"] else k
        name = "Main.dc.html" if (k == 0 and not order) else f"Panel-{k + 1:02d}-{re.sub(r'[^A-Za-z0-9-]', '-', ids[k])}.dc.html"
        mine = _drop(inner, _off_panel(r["measure"], inner, col, W, N, r["mirror"]))
        (proj / name).write_text(board(name, f"Panel {k + 1}", mine, css, link, W, H, offset_x=col * W))
        boards[name] = {"x": k * (W + 80), "y": y0, "w": W, "h": H, "title": f"{k + 1:02d} · {ids[k]}"}
        order.append(name)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    canvas = {"v": 3, "createdOnFiles": {"v": 1, "at": now}, "title": spec["campaign"]["name"],
              "launch": {"view": "canvas"}, "pages": [], "boards": boards, "order": order,
              "notes": {"t1": {"x": 0, "y": y0 - 300, "text": f"{spec['campaign']['name']} · {locale}",
                               "kind": "title1", "maxW": min(MW, 7000)}},
              "designSystems": []}
    if not order[0] == "Main.dc.html":
        raise RuntimeError("internal: the first artboard must be Main.dc.html")
    (proj / "canvas.json").write_text(json.dumps(canvas, indent=1))
    small = _small_copies(assets, out, max(1, W // 2))
    up = [{"token": tok, "file": small[tok], "source": src} for src, tok in assets.items()]
    (out / "assets.json").write_text(json.dumps(up, indent=2))
    print(f"wrote {proj} ({len(order)} artboards) and {out / 'assets.json'} ({len(up)} images to upload)")
    print("next: upload each asset to the canvas (asset: true), write asset-urls.json {token: url}, "
          "then `campaign.py canvas-link DIR`")
    return 0


def link(out: pathlib.Path):
    urls = json.loads((out / "asset-urls.json").read_text())
    proj = out / "project"
    missing = set()
    for f in proj.glob("*.dc.html"):
        t = f.read_text()
        for tok in set(re.findall(r"__ASSET_\d{3}__", t)):
            if tok in urls:
                t = t.replace(tok, urls[tok])
            else:
                missing.add(tok)
        f.write_text(t)
    if missing:
        print(f"missing urls for {sorted(missing)}")
        return 1
    print(f"linked {len(urls)} assets in {proj}")
    return 0
