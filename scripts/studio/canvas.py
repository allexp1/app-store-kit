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
    page = pathlib.Path(r["html"]).read_text()
    inner = _body_of(page)
    inner = re.sub(r'<div class="grain"[^>]*></div>', "", inner)   # data: URIs are not allowed on a canvas
    css = _style_of(page).replace("html,body", "body")
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
        (proj / name).write_text(board(name, f"Panel {k + 1}", inner, css, link, W, H, offset_x=col * W))
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
    up = [{"token": t, "file": p} for p, t in assets.items()]
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
