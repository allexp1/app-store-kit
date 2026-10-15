"""One self-contained HTML review page for a rendered campaign: the concepts contact sheet, the presentation, every
panel of one locale and slot, and the QA report. The fallback when the Claude Design canvas is not available on
the account: publish this page as a plain Artifact instead. Images are embedded as JPEG data URIs, sized down
until the page fits under 16 MB (the Artifact limit)."""
from __future__ import annotations

import base64
import html
import io
import pathlib

from PIL import Image

LIMIT = 16 * 1024 * 1024


def _jpeg(path, width):
    with Image.open(path) as im:
        im = im.convert("RGB")
        if im.width > width:
            im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=84, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _pick(out, locale, slot):
    locs = sorted(p for p in out.iterdir() if p.is_dir() and p.name != "concepts" and not p.name.startswith("."))
    locs = [p for p in locs if any(p.glob("*/panels/*.png"))]
    if not locs:
        raise SystemExit(f"no rendered panels under {out}/<locale>/<slot>/panels/ (run `campaign.py render` first)")
    loc = out / locale if locale else locs[0]
    slots = sorted(p for p in loc.iterdir() if (p / "panels").is_dir()) if loc.is_dir() else []
    d = loc / slot if slot else (slots[0] if slots else loc / "?")
    if not (d / "panels").is_dir():
        raise SystemExit(f"no panels for {loc.name}/{d.name}; rendered: "
                         + ", ".join(f"{p.parent.parent.name}/{p.parent.name}" for p in sorted(out.glob("*/*/panels"))))
    return d


def build(out: pathlib.Path, locale=None, slot=None, title=None, scale=1.0):
    d = _pick(out, locale, slot)
    loc, sid = d.parent.name, d.name
    panels = sorted((d / "panels").glob("*.png"))
    sheet = out / "concepts" / "contact-sheet.png"
    pres = d / "presentation.png"
    report = d / "report.md"
    w = lambda n: max(240, int(n * scale))  # noqa: E731
    fig = lambda cap, src, cls="": (f'<figure class="{cls}"><img alt="" src="{src}">'  # noqa: E731
                                    f'<figcaption>{html.escape(cap)}</figcaption></figure>')
    top = fig("Presentation", _jpeg(pres, w(2400)), "wide") if pres.exists() else ""
    grid = "".join(fig(f"Panel {k + 1} · {p.stem}", _jpeg(p, w(700))) for k, p in enumerate(panels))
    bottom = fig("Creative directions (concepts)", _jpeg(sheet, w(2400)), "wide") if sheet.exists() else ""
    title = title or f"Campaign review · {loc} · {sid}"
    rep = html.escape(report.read_text()) if report.exists() else "No report.md yet."
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root{{--bg:#f6f6f4;--fg:#18181a;--muted:#5e5e66;--card:#fff;--line:#e2e2de}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#151517;--fg:#ececee;--muted:#a0a0a8;--card:#1f1f23;--line:#2e2e34}}}}
:root[data-theme="dark"]{{--bg:#151517;--fg:#ececee;--muted:#a0a0a8;--card:#1f1f23;--line:#2e2e34}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,sans-serif;padding:24px 16px 64px}}
main{{max-width:1200px;margin:0 auto}}
h1{{font-size:24px;margin:0 0 4px}} p.sub{{color:var(--muted);margin:0 0 24px}}
figure{{margin:0;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px}}
figure img{{display:block;width:100%;height:auto;border-radius:6px}}
figcaption{{color:var(--muted);font-size:13px;margin-top:6px}}
.wide{{margin-bottom:20px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;margin-bottom:24px}}
pre{{white-space:pre-wrap;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;
  font-size:13px;overflow-x:auto}}
</style></head><body><main>
<h1>{html.escape(title)}</h1>
<p class="sub">{len(panels)} panel(s), exact App Store size, in upload order. The PNGs themselves are in {html.escape(str(d / 'panels'))}.</p>
{top}
<div class="grid">{grid}</div>
{bottom}
<h2>QA report</h2>
<pre>{rep}</pre>
</main></body></html>
"""
    return page, len(panels)


def write(out: pathlib.Path, dest: pathlib.Path | None = None, locale=None, slot=None, title=None):
    dest = dest or out / "review.html"
    scale = 1.0
    while True:
        page, n = build(out, locale, slot, title, scale)
        if len(page.encode()) <= LIMIT or scale < 0.2:
            break
        scale *= 0.7
    if len(page.encode()) > LIMIT:
        raise SystemExit(f"review page is {len(page.encode()) / 1e6:.1f} MB even at small sizes; pick one slot")
    dest.write_text(page)
    return dest, n, len(page.encode())
