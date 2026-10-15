"""render_creative.py: placeholder checks, and the universal template's cards filled with real images."""
import pathlib
import sys

import pytest
from PIL import Image

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
TEMPLATE = SCRIPTS.parent / "templates" / "creative-universal.html"
sys.path.insert(0, str(SCRIPTS))
import render  # noqa: E402
import render_creative  # noqa: E402

chrome = pytest.mark.skipif(not render.find_chrome(), reason="no headless Chromium found")

# card (left, top) from the template; a card is 640x853 and rotates about its centre
CARDS = {"LEFT_1": (300, 760), "LEFT_2": (860, 1180), "LEFT_3": (1330, 560),
         "RIGHT_1": (3274, 560), "RIGHT_2": (3744, 1180), "RIGHT_3": (4304, 760)}
COLOURS = {"LEFT_1": (220, 30, 30), "LEFT_2": (30, 160, 60), "LEFT_3": (30, 60, 220),
           "RIGHT_1": (230, 160, 20), "RIGHT_2": (150, 40, 200), "RIGHT_3": (20, 180, 190)}


def test_placeholder_pattern_allows_digits():
    assert render.PLACE.findall("{{LEFT_1}} {{RIGHT_3}} {{INK}} {{1X}}") == ["LEFT_1", "RIGHT_3", "INK"]


def _sets(tmp_path):
    sets = []
    for name, rgb in COLOURS.items():
        f = tmp_path / f"{name}.png"
        Image.new("RGB", (120, 260), rgb).save(f)
        sets += ["--set", f"{name}={f}"]
    for name in ("LEFT_ICON", "RIGHT_ICON", "SCREEN"):
        f = tmp_path / f"{name}.png"
        Image.new("RGB", (60, 130), (250, 250, 250)).save(f)
        sets += ["--set", f"{name}={f}"]
    for name, v in {"INK": "#111111", "PAPER": "#ffffff", "LEFT_BG": "#333366", "RIGHT_BG": "#663333"}.items():
        sets += ["--set", f"{name}={v}"]
    return sets


def test_unknown_set_name_fails(tmp_path, capsys):
    rc = render_creative.main([str(TEMPLATE), "--out", str(tmp_path / "o.png"), *_sets(tmp_path),
                               "--set", "LEFT_4=#fff"])
    assert rc == 2 and "LEFT_4" in capsys.readouterr().err
    assert not (tmp_path / "o.png").exists()


def test_missing_value_fails(tmp_path, capsys):
    rc = render_creative.main([str(TEMPLATE), "--out", str(tmp_path / "o.png"), *_sets(tmp_path)[:-2]])
    assert rc == 2 and "RIGHT_BG" in capsys.readouterr().err


def test_leftover_placeholder_fails(tmp_path, capsys):
    page = tmp_path / "p.html"
    page.write_text('<div class="frame" style="background:{{INK}}">{{left-1}}</div>')
    rc = render_creative.main([str(page), "--out", str(tmp_path / "o.png"), "--set", "INK=#000"])
    assert rc == 2 and "{{left-1}}" in capsys.readouterr().err


@chrome
def test_universal_cards_show_their_images(tmp_path):
    out = tmp_path / "universal.png"
    assert render_creative.main([str(TEMPLATE), "--out", str(out), *_sets(tmp_path)]) == 0
    im = Image.open(out).convert("RGB")
    assert im.size == (5244, 2950)
    for name, (x, y) in CARDS.items():
        cx, cy = x + 320, y + 426
        patch = im.crop((cx - 20, cy - 20, cx + 20, cy + 20)).resize((1, 1), Image.BILINEAR).getpixel((0, 0))
        assert max(abs(a - b) for a, b in zip(patch, (0xDD,) * 3)) > 30, f"{name} is still placeholder grey"
        assert max(abs(a - b) for a, b in zip(patch, COLOURS[name])) < 30, f"{name} shows {patch}"
