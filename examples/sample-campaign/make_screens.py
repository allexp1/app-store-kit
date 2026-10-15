#!/usr/bin/env python3
"""Render the SYNTHETIC test screens of "Ridgeline", a made-up hiking app used to demonstrate campaign.py.

These are not screenshots of a real app. They exist so the engine, tests and examples have realistic UI to
compose. Usage: make_screens.py [OUT_DIR] (default: ./screens), 1320 x 2868 PNGs (iPhone 6.9", 3x).
"""
from __future__ import annotations

import math
import pathlib
import random
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "scripts"))
from studio import chrome  # noqa: E402

BASE = """<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;width:440px;height:956px;overflow:hidden;font-family:-apple-system,'SF Pro Text',system-ui,sans-serif;
background:%(bg)s;color:%(fg)s;-webkit-font-smoothing:antialiased}
.sb{height:54px;display:flex;justify-content:space-between;align-items:center;padding:14px 34px 0 46px;font-weight:600;font-size:17px}
.sb .r{display:flex;gap:6px;align-items:center}.bat{width:27px;height:13px;border:1.5px solid currentColor;border-radius:4px;padding:1.5px;opacity:.9}
.bat i{display:block;height:100%%;background:currentColor;border-radius:2px}
.pad{padding:0 20px}.h1{font-size:34px;font-weight:800;letter-spacing:-.02em;margin:10px 0 4px}
.muted{opacity:.55}.card{background:%(card)s;border-radius:22px;padding:16px;box-shadow:0 1px 0 rgba(0,0,0,.04)}
.row{display:flex;gap:12px}.stat{flex:1}.stat b{display:block;font-size:24px;letter-spacing:-.02em}.stat span{font-size:13px;opacity:.55}
.btn{background:#1F6F4A;color:#fff;border-radius:16px;text-align:center;padding:16px;font-weight:700;font-size:17px}
.chip{display:inline-block;font-size:12px;font-weight:700;padding:5px 10px;border-radius:99px;background:rgba(31,111,74,.12);color:#1F6F4A}
.tab{position:absolute;bottom:0;left:0;right:0;height:92px;background:%(tab)s;backdrop-filter:blur(20px);display:flex;
justify-content:space-around;padding-top:12px;font-size:11px;font-weight:600;border-top:1px solid rgba(0,0,0,.06)}
.tab div{display:flex;flex-direction:column;align-items:center;gap:4px;opacity:.45}.tab .on{opacity:1;color:#1F6F4A}
.tab i{width:26px;height:26px;border-radius:8px;background:currentColor;opacity:.85}
.hi{position:absolute;bottom:8px;left:50%%;width:150px;height:5px;margin-left:-75px;border-radius:3px;background:%(fg)s;opacity:.85}
</style></head><body>%(body)s<div class="hi"></div></body></html>"""

STATUS = ('<div class="sb"><span>9:41</span><span class="r"><svg width="18" height="12"><rect x="0" y="8" width="3" height="4" rx="1" fill="currentColor"/>'
          '<rect x="5" y="5" width="3" height="7" rx="1" fill="currentColor"/><rect x="10" y="2" width="3" height="10" rx="1" fill="currentColor"/>'
          '<rect x="15" y="0" width="3" height="12" rx="1" fill="currentColor"/></svg><svg width="16" height="12" viewBox="0 0 16 12">'
          '<path d="M8 11.5 5.6 9a3.4 3.4 0 0 1 4.8 0z M8 2C5.2 2 2.7 3.1.9 4.9l1.4 1.4A8 8 0 0 1 8 4a8 8 0 0 1 5.7 2.3l1.4-1.4A10 10 0 0 0 8 2z M3.7 7.7 5 9a4.3 4.3 0 0 1 6 0l1.3-1.3a6.1 6.1 0 0 0-8.6 0z" fill="currentColor"/></svg>'
          '<span class="bat"><i></i></span></span></div>')


def topo(w, h, seed, dark=False, lines=26):
    rnd = random.Random(seed)
    cx, cy = rnd.uniform(.3, .7) * w, rnd.uniform(.3, .6) * h
    paths = []
    for k in range(lines):
        r = 20 + k * (max(w, h) / lines) * 0.75
        pts = []
        for j in range(48):
            a = j / 48 * math.tau
            rr = r * (1 + 0.18 * math.sin(3 * a + k * 0.4 + seed) + 0.08 * math.cos(5 * a + seed))
            pts.append(f"{cx + rr * math.cos(a) * 1.15:.1f},{cy + rr * math.sin(a):.1f}")
        col = "rgba(140,200,160,.22)" if dark else "rgba(60,110,70,.16)"
        paths.append(f'<polygon points="{" ".join(pts)}" fill="none" stroke="{col}" stroke-width="{1.6 if k % 5 == 0 else .8}"/>')
    return "".join(paths)


def route(w, h, seed, color="#FF6B3D"):
    rnd = random.Random(seed + 9)
    pts = [(w * 0.18, h * 0.82)]
    for k in range(9):
        x, y = pts[-1]
        pts.append((min(w * .9, max(w * .1, x + rnd.uniform(-20, 60))), y - h * rnd.uniform(.05, .1)))
    d = "M" + " L".join(f"{x:.0f},{y:.0f}" for x, y in pts)
    s, e = pts[0], pts[-1]
    return (f'<path d="{d}" fill="none" stroke="white" stroke-width="10" stroke-linejoin="round" stroke-linecap="round" opacity=".9"/>'
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="5.5" stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{s[0]:.0f}" cy="{s[1]:.0f}" r="9" fill="#1F6F4A" stroke="white" stroke-width="3"/>'
            f'<circle cx="{e[0]:.0f}" cy="{e[1]:.0f}" r="9" fill="{color}" stroke="white" stroke-width="3"/>')


def mountains(w, h, seed, a="#9CC5A1", b="#2E6B4F", sky=("#F7D9B5", "#BFD9E8")):
    rnd = random.Random(seed)
    def ridge(base, amp, col):
        pts = [(0, h)]
        x = 0
        while x <= w:
            pts.append((x, base - rnd.uniform(0, amp)))
            x += w / 7
        pts.append((w, h))
        return f'<polygon points="{" ".join(f"{x:.0f},{y:.0f}" for x, y in pts)}" fill="{col}"/>'
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}"><defs><linearGradient id="s{seed}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{sky[1]}"/><stop offset="1" stop-color="{sky[0]}"/></linearGradient></defs>'
            f'<rect width="{w}" height="{h}" fill="url(#s{seed})"/><circle cx="{w * .72}" cy="{h * .3}" r="{h * .12}" fill="#FFF3DC" opacity=".9"/>'
            + ridge(h * .55, h * .3, a) + ridge(h * .78, h * .22, b) + "</svg>")


def tabbar(on):
    names = ["Today", "Map", "Trails", "Stats"]
    return '<div class="tab">' + "".join(f'<div class="{"on" if n == on else ""}"><i></i>{n}</div>' for n in names) + "</div>"


def s_home():
    body = STATUS + f"""<div class="pad"><div class="muted" style="font-size:15px;font-weight:600;margin-top:8px">SATURDAY, 14 JUNE</div>
<div class="h1">Good morning, Sam</div>
<div class="card" style="padding:0;overflow:hidden;margin-top:14px;position:relative">
<svg width="400" height="300" style="display:block;background:#EAF0E4">{topo(400, 300, 3)}{route(400, 300, 3)}</svg>
<div style="position:absolute;left:14px;top:14px" class="chip" >Planned · Eagle Ridge Loop</div></div>
<div class="card" style="margin-top:12px"><div class="row"><div class="stat"><b>12.4 km</b><span>Distance</span></div>
<div class="stat"><b>640 m</b><span>Elevation</span></div><div class="stat"><b>3h 10m</b><span>Est. time</span></div></div></div>
<div class="card" style="margin-top:12px;display:flex;gap:14px;align-items:center"><div style="width:52px;height:52px;border-radius:14px;background:#FFE7DA;display:grid;place-items:center;font-size:24px">☀︎</div>
<div style="flex:1"><b style="font-size:17px">Clear until 4 pm</b><div class="muted" style="font-size:14px">Start before 10:30 to finish in daylight</div></div></div>
<div class="btn" style="margin-top:16px">Start hike</div></div>""" + tabbar("Today")
    return BASE % {"bg": "#F5F3EE", "fg": "#14201A", "card": "#FFFFFF", "tab": "rgba(250,249,246,.92)", "body": body}


def s_map():
    elev = " ".join(f"{i * 9.5:.0f},{70 - 40 * math.sin(i / 6) - 18 * math.sin(i / 2.3) - i * .6:.0f}" for i in range(39))
    body = (f'<svg width="440" height="956" style="position:absolute;inset:0;background:#E7EEDD">{topo(440, 956, 7, lines=40)}'
            f'{route(440, 760, 7)}</svg><div style="position:relative">{STATUS}</div>'
            f"""<div style="position:absolute;left:12px;right:12px;bottom:100px" class="card">
<div style="display:flex;justify-content:space-between;align-items:center"><div><b style="font-size:21px">Eagle Ridge Loop</b>
<div class="muted" style="font-size:14px">Moderate · 12.4 km · loop</div></div><span class="chip">Offline ready</span></div>
<svg width="376" height="86" style="margin-top:12px"><polyline points="0,86 {elev} 370,86" fill="rgba(31,111,74,.14)" stroke="#1F6F4A" stroke-width="2.5"/></svg>
<div class="row" style="margin-top:6px"><div class="stat"><b>640 m</b><span>Climb</span></div><div class="stat"><b>1,912 m</b><span>Highest point</span></div></div>
</div>""" + tabbar("Map"))
    return BASE % {"bg": "#E7EEDD", "fg": "#14201A", "card": "rgba(255,255,255,.97)", "tab": "rgba(250,249,246,.94)", "body": body}


def s_trails():
    items = [("Eagle Ridge Loop", "Moderate", "12.4 km · 640 m", ("#9CC5A1", "#2E6B4F")),
             ("Silver Lake Path", "Easy", "6.1 km · 120 m", ("#A9C8DA", "#3C6E8F")),
             ("North Col Traverse", "Hard", "18.9 km · 1,410 m", ("#C9B79C", "#6B5537"))]
    cards = ""
    for k, (n, lvl, meta, (a, b)) in enumerate(items):
        cards += (f'<div class="card" style="padding:0;overflow:hidden;margin-top:14px">{mountains(400, 150, k + 2, a, b)}'
                  f'<div style="padding:14px 16px"><div style="display:flex;justify-content:space-between"><b style="font-size:19px">{n}</b>'
                  f'<span class="chip">{lvl}</span></div><div class="muted" style="font-size:14px;margin-top:4px">{meta}</div></div></div>')
    body = STATUS + f"""<div class="pad"><div class="h1">Trails near you</div>
<div style="display:flex;gap:8px;margin-top:8px"><span class="chip" style="background:#1F6F4A;color:#fff">All</span><span class="chip">Loops</span>
<span class="chip">Under 10 km</span><span class="chip">Lakes</span></div>{cards}</div>""" + tabbar("Trails")
    return BASE % {"bg": "#F5F3EE", "fg": "#14201A", "card": "#FFFFFF", "tab": "rgba(250,249,246,.92)", "body": body}


def s_stats():
    vals = [3.2, 0, 6.8, 4.1, 0, 12.4, 8.0]
    bars = "".join(f'<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:6px"><div style="width:30px;height:{v * 11 + 4:.0f}px;'
                   f'border-radius:8px;background:{"#FF6B3D" if v == max(vals) else "#1F6F4A"}"></div><span class="muted" style="font-size:12px">{d}</span></div>'
                   for v, d in zip(vals, "MTWTFSS"))
    def ring(p, col, r):
        c = 2 * math.pi * r
        return (f'<circle cx="80" cy="80" r="{r}" fill="none" stroke="{col}" stroke-opacity=".18" stroke-width="14"/>'
                f'<circle cx="80" cy="80" r="{r}" fill="none" stroke="{col}" stroke-width="14" stroke-linecap="round" '
                f'stroke-dasharray="{c * p:.1f} {c:.1f}" transform="rotate(-90 80 80)"/>')
    body = STATUS + f"""<div class="pad"><div class="h1">This week</div>
<div class="card" style="margin-top:12px;display:flex;align-items:center;gap:18px"><svg width="160" height="160">{ring(.82, '#FF6B3D', 66)}{ring(.64, '#1F6F4A', 46)}{ring(.45, '#3C6E8F', 26)}</svg>
<div><div class="stat"><b>34.5 km</b><span>of 42 km goal</span></div><div class="stat" style="margin-top:10px"><b>2,180 m</b><span>climbed</span></div></div></div>
<div class="card" style="margin-top:12px"><b style="font-size:17px">Distance</b><div style="display:flex;align-items:flex-end;height:170px;margin-top:10px">{bars}</div></div>
<div class="card" style="margin-top:12px"><div class="row"><div class="stat"><b>5</b><span>Hikes</span></div><div class="stat"><b>11h 40m</b><span>Moving</span></div>
<div class="stat"><b>3</b><span>New trails</span></div></div></div></div>""" + tabbar("Stats")
    return BASE % {"bg": "#F5F3EE", "fg": "#14201A", "card": "#FFFFFF", "tab": "rgba(250,249,246,.92)", "body": body}


def s_night():
    body = (f'<svg width="440" height="956" style="position:absolute;inset:0;background:#0F1A16">{topo(440, 956, 11, dark=True, lines=40)}'
            f'{route(440, 800, 11, "#FFB23D")}<circle cx="215" cy="470" r="34" fill="rgba(80,170,255,.25)"/><circle cx="215" cy="470" r="11" fill="#4DA3FF" stroke="white" stroke-width="3"/></svg>'
            f'<div style="position:relative">{STATUS}</div>'
            """<div style="position:absolute;left:12px;right:12px;top:70px" class="card"><div style="display:flex;gap:14px;align-items:center">
<div style="width:48px;height:48px;border-radius:14px;background:#FFB23D;display:grid;place-items:center;color:#111;font-weight:900;font-size:22px">↱</div>
<div><b style="font-size:21px">Turn right in 120 m</b><div class="muted" style="font-size:14px">onto Ridge Trail · 2.3 km to summit</div></div></div></div>
<div style="position:absolute;left:12px;right:12px;bottom:100px" class="card"><div class="row"><div class="stat"><b>7.8 km</b><span>Done</span></div>
<div class="stat"><b>1h 52m</b><span>Moving</span></div><div class="stat"><b>sunset 8:47</b><span>Daylight</span></div></div></div>"""
            + tabbar("Map"))
    return BASE % {"bg": "#0F1A16", "fg": "#EEF3EF", "card": "rgba(30,42,37,.96)", "tab": "rgba(16,24,20,.94)", "body": body}


SCREENS = {"home": s_home, "map": s_map, "trails": s_trails, "stats": s_stats, "night": s_night}


def main(out=None):
    out = pathlib.Path(out or HERE / "screens")
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        for name, fn in SCREENS.items():
            hp = pathlib.Path(td) / f"{name}.html"
            hp.write_text(fn())
            chrome.screenshot(hp, out / f"{name}.png", 440, 956, 3.0)
            print(out / f"{name}.png")
    # app icon (synthetic)
    icon = pathlib.Path(td if False else out) / "icon.html"
    icon.write_text("<!doctype html><body style='margin:0'><svg width='1024' height='1024'><defs><linearGradient id='g' x1='0' y1='0' x2='0' y2='1'>"
                    "<stop offset='0' stop-color='#2B8A5E'/><stop offset='1' stop-color='#14432F'/></linearGradient></defs>"
                    "<rect width='1024' height='1024' fill='url(#g)'/><polygon points='120,780 400,330 560,560 680,420 904,780' fill='#F5F3EE'/>"
                    "<polygon points='400,330 470,440 430,470 380,420 340,470' fill='#FF6B3D'/></svg></body>")
    chrome.screenshot(icon, out.parent / "icon.png", 1024, 1024, 1.0)
    icon.unlink()
    print(out.parent / "icon.png")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
