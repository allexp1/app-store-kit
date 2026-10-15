"""Headless Chromium: one pass to measure (fit text, read boxes, check fonts), one pass to take the picture.

Uses the chrome-headless-shell / Chromium from the Playwright cache, or $CHROME. No Python Playwright needed.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from render import find_chrome  # noqa: E402  (the kit's own finder, shared with render.py)

BUDGET_MS = 20000


def chrome_or_die():
    c = find_chrome()
    if not c:
        raise SystemExit("no renderer: set $CHROME to a Chromium / chrome-headless-shell binary, or run "
                         "`npx playwright install chromium-headless-shell` once")
    return c


def _base(chrome, w, h, scale):
    cmd = [chrome, "--hide-scrollbars", f"--force-device-scale-factor={scale}", f"--window-size={w},{h}",
           "--allow-file-access-from-files", "--disable-gpu", "--font-render-hinting=none",
           f"--virtual-time-budget={BUDGET_MS}", "--run-all-compositor-stages-before-draw"]
    if "headless-shell" not in chrome:
        cmd.insert(1, "--headless")
    return cmd


def dump_dom(html_path, w, h, chrome=None) -> str:
    chrome = chrome or chrome_or_die()
    cmd = _base(chrome, w, h, 1) + ["--dump-dom", pathlib.Path(html_path).resolve().as_uri()]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"chrome --dump-dom failed: {r.stderr[-800:]}")
    return r.stdout


def screenshot(html_path, png_path, w, h, scale=1.0, chrome=None):
    chrome = chrome or chrome_or_die()
    cmd = _base(chrome, w, h, scale) + ["--default-background-color=00000000", f"--screenshot={png_path}",
                                        pathlib.Path(html_path).resolve().as_uri()]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not pathlib.Path(png_path).exists():
        raise RuntimeError(f"chrome --screenshot failed: {r.stderr[-800:]}")
    if scale != 1:
        # headless Chrome does not always honour a fractional scale exactly; normalise to the asked size
        from PIL import Image
        want = (round(w * scale), round(h * scale))
        with Image.open(png_path) as im:
            im.load()
            if im.size != want:
                im.resize(want, Image.LANCZOS).save(png_path)
