"""Device mockups drawn in HTML/CSS 3D: a real screenshot on the screen plane, a lit metal band, a solid
edge built from stacked slices (so a tilted phone has thickness), screen glare and silhouette shadows.

The screenshot is an <img> on the front plane, so the browser projects it at the final resolution: the UI stays
sharp and geometrically correct under perspective. The frame is drawn, not a vendor bitmap, so there is no
licence question and it scales to any size.
"""
from __future__ import annotations

import html
import math

# Generic finish names (no trademarked colour names). base / light / dark of the metal band.
FINISHES = {
    "titanium": ("#b9b4aa", "#ece8df", "#7d786f"),
    "graphite": ("#3a3a3d", "#77777c", "#18181a"),
    "silver": ("#cfd1d4", "#f7f8f9", "#9a9da2"),
    "black": ("#1d1d1f", "#4c4c50", "#0a0a0b"),
    "white": ("#e9e9ea", "#ffffff", "#bdbdc0"),
    "sand": ("#cdb59a", "#efe0cc", "#9c8670"),
    "navy": ("#3b4658", "#6d7a90", "#1f2633"),
    "orange": ("#d9733b", "#f6a273", "#9c4a1f"),
    "sage": ("#9aa68f", "#c9d3bf", "#6a7562"),
}

MODELS = {
    # band, bezel, outer corner radius as a fraction of the outer width; depth as a fraction of width
    "iphone": {"band": 0.0115, "bezel": 0.026, "radius": 0.158, "depth": 0.072, "island": True},
    "ipad": {"band": 0.0075, "bezel": 0.036, "radius": 0.052, "depth": 0.032, "island": False},
    "screen": {"band": 0.0, "bezel": 0.0, "radius": 0.12, "depth": 0.0, "island": False},  # frameless card
}


def finish_colors(finish):
    if isinstance(finish, dict):
        return finish["base"], finish.get("light", finish["base"]), finish.get("dark", finish["base"])
    if isinstance(finish, str) and finish.startswith("#"):
        return finish, finish, finish
    if finish not in FINISHES:
        raise ValueError(f"unknown device finish {finish!r}; one of {', '.join(FINISHES)} or a #hex or a dict")
    return FINISHES[finish]


def geometry(model: str, outer_w: float, aspect: float):
    """Outer box and screen box for a device whose screen shows an image of height/width = aspect."""
    m = MODELS[model]
    band, bezel = m["band"] * outer_w, m["bezel"] * outer_w
    sw = outer_w - 2 * (band + bezel)
    sh = sw * aspect
    oh = sh + 2 * (band + bezel)
    r = m["radius"] * outer_w
    return {"w": outer_w, "h": oh, "band": band, "bezel": bezel, "sw": sw, "sh": sh, "r": r,
            "r_in": max(0.0, r - band), "r_screen": max(0.0, r - band - bezel), "depth": m["depth"] * outer_w}


def _shadows(g, shadow, rot, light_deg):
    if not shadow or shadow == "none":
        return ""
    style = shadow if isinstance(shadow, str) else shadow.get("style", "soft")
    k = 1.0 if isinstance(shadow, str) else float(shadow.get("strength", 1.0))
    color = "0,0,0" if isinstance(shadow, str) else shadow.get("rgb", "0,0,0")
    h = g["h"]
    # shadow falls away from the light; light_deg is where the light comes from (0 = top, 90 = right)
    lx, ly = -math.sin(math.radians(light_deg)), math.cos(math.radians(light_deg))
    lift = {"soft": 0.03, "float": 0.07, "contact": 0.012, "long": 0.11}.get(style, 0.03)
    blur = {"soft": 0.05, "float": 0.075, "contact": 0.018, "long": 0.06}.get(style, 0.05)
    a1 = min(0.75, 0.32 * k)
    a2 = min(0.5, 0.16 * k)
    return (f"drop-shadow({lx * lift * h:.1f}px {ly * lift * h:.1f}px {blur * h:.1f}px rgba({color},{a1:.3f})) "
            f"drop-shadow(0px {0.01 * h:.1f}px {0.16 * h:.1f}px rgba({color},{a2:.3f}))")


def device_html(*, did, screen_uri, aspect, cx, cy, width, model="iphone", finish="titanium",
                rotate=(0, 0, 0), focal=2.6, shadow="soft", glare=0.08, island=None, light=315,
                z=None, opacity=1.0, slices=None, extra_style=""):
    """One device, centred at (cx, cy) in canvas pixels, `width` px wide (outer frame)."""
    if model not in MODELS:
        raise ValueError(f"unknown device model {model!r}; one of {', '.join(MODELS)}")
    g = geometry(model, width, aspect)
    rx, ry, rz = (list(rotate) + [0, 0, 0])[:3]
    base, light_c, dark = finish_colors(finish) if model != "screen" else ("#000", "#000", "#000")
    persp = max(g["h"] * float(focal), 1.0)
    island = MODELS[model]["island"] if island is None else island
    tilted = abs(rx) > 0.5 or abs(ry) > 0.5
    depth = g["depth"] if tilted else 0.0
    n = slices if slices is not None else (max(6, min(22, int(depth / 2.5))) if depth else 0)
    # which side of the band catches the light, from the yaw
    lit = 0.5 + 0.5 * math.sin(math.radians(ry))
    edge = (f"linear-gradient(90deg,{dark} 0%,{base} {20 + 30 * lit:.0f}%,{light_c} {50 + 20 * lit:.0f}%,"
            f"{base} 85%,{dark} 100%)")
    band_grad = (f"linear-gradient({light + 90}deg,{light_c} 0%,{base} 18%,{dark} 48%,{base} 70%,{light_c} 92%,"
                 f"{base} 100%)")
    parts = []
    for k in range(n, 0, -1):
        t = -depth * k / n
        shade = 0.55 + 0.45 * (k / n)
        parts.append(f'<div class="dv-slice" style="transform:translateZ({t:.2f}px);border-radius:{g["r"]:.1f}px;'
                     f'background:{edge};filter:brightness({shade:.2f})"></div>')
    gl = ""
    if glare:
        ang = 112 + ry * 0.9
        gl = (f'<div class="dv-glare" style="background:linear-gradient({ang:.0f}deg,rgba(255,255,255,0) 32%,'
              f'rgba(255,255,255,{glare:.3f}) 46%,rgba(255,255,255,{glare * 0.35:.3f}) 52%,rgba(255,255,255,0) 64%)">'
              f'</div>')
    isl = ""
    if island:
        iw, ih = 0.315 * g["sw"], 0.093 * g["sw"]
        isl = (f'<div class="dv-island" style="width:{iw:.1f}px;height:{ih:.1f}px;top:{0.03 * g["sw"]:.1f}px;'
               f'left:{(g["sw"] - iw) / 2:.1f}px;border-radius:{ih / 2:.1f}px"></div>')
    if model == "screen":
        front = (f'<div class="dv-front" style="border-radius:{g["r"]:.1f}px;overflow:hidden">'
                 f'<img class="dv-img" src="{html.escape(screen_uri, quote=True)}" alt="">{gl}</div>')
    else:
        front = (f'<div class="dv-front" style="border-radius:{g["r"]:.1f}px;background:{band_grad};'
                 f'padding:{g["band"]:.2f}px">'
                 f'<div class="dv-bezel" style="border-radius:{g["r_in"]:.1f}px;padding:{g["bezel"]:.2f}px">'
                 f'<div class="dv-screen" data-screen="{did}" style="width:{g["sw"]:.2f}px;height:{g["sh"]:.2f}px;'
                 f'border-radius:{g["r_screen"]:.1f}px">'
                 f'<img class="dv-img" src="{html.escape(screen_uri, quote=True)}" alt="">{isl}{gl}</div></div></div>')
    zs = f"z-index:{z};" if z is not None else ""
    return (f'<div class="dv" data-id="{did}" data-kind="device" style="left:{cx - g["w"] / 2:.2f}px;'
            f'top:{cy - g["h"] / 2:.2f}px;width:{g["w"]:.2f}px;height:{g["h"]:.2f}px;{zs}opacity:{opacity};'
            f'filter:{_shadows(g, shadow, (rx, ry, rz), light) or "none"};{extra_style}">'
            f'<div class="dv-stage" style="perspective:{persp:.0f}px">'
            f'<div class="dv-body" style="transform:rotateZ({rz}deg) rotateX({rx}deg) rotateY({ry}deg)">'
            + "".join(parts) + front + "</div></div></div>")


def card_html(*, cid, screen_uri, shot_w, shot_h, crop, cx, cy, width, radius=0.06, rotate=(0, 0, 0),
              focal=3.0, shadow="float", z=None, light=315, border=None, lift=0):
    """A real piece of the app's UI, cropped from a screenshot, floating as its own card."""
    x, y, w, h = crop
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > shot_w or y + h > shot_h:
        raise ValueError(f"card {cid}: crop {crop} is outside the {shot_w}x{shot_h} screenshot")
    s = width / w
    ch = h * s
    rx, ry, rz = (list(rotate) + [0, 0, 0])[:3]
    g = {"h": ch}
    zs = f"z-index:{z};" if z is not None else ""
    bd = f"outline:{border};" if border else ""
    return (f'<div class="cd" data-id="{cid}" data-kind="card" style="left:{cx - width / 2:.2f}px;top:{cy - ch / 2:.2f}px;'
            f'width:{width:.2f}px;height:{ch:.2f}px;{zs}filter:{_shadows(g, shadow, (rx, ry, rz), light) or "none"}">'
            f'<div class="dv-stage" style="perspective:{max(ch, width) * focal:.0f}px">'
            f'<div class="cd-body" style="transform:rotateZ({rz}deg) rotateX({rx}deg) rotateY({ry}deg) '
            f'translateZ({lift}px);border-radius:{radius * width:.1f}px;{bd}">'
            f'<img src="{html.escape(screen_uri, quote=True)}" alt="" style="width:{shot_w * s:.2f}px;'
            f'height:{shot_h * s:.2f}px;left:{-x * s:.2f}px;top:{-y * s:.2f}px"></div></div></div>')


DEVICE_CSS = """
.dv,.cd{position:absolute;pointer-events:none}
.dv-stage{position:absolute;inset:0;perspective-origin:50% 50%}
.dv-body{position:absolute;inset:0;transform-style:preserve-3d}
.dv-slice{position:absolute;inset:0;backface-visibility:visible}
.dv-front{position:absolute;inset:0;box-sizing:border-box}
.dv-bezel{width:100%;height:100%;box-sizing:border-box;background:#050506}
.dv-screen{position:relative;overflow:hidden;background:#000}
.dv-front>.dv-img,.dv-screen>.dv-img{display:block;width:100%;height:100%}
.dv-island{position:absolute;background:#000}
.dv-glare{position:absolute;inset:0;pointer-events:none;mix-blend-mode:screen}
.cd-body{position:absolute;inset:0;overflow:hidden;background:#fff}
.cd-body>img{position:absolute;max-width:none}
"""
