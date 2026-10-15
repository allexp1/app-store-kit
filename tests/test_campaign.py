"""campaign.py / studio: spec validation, copy rules, slicing, RTL, export checks, canvas export, rendering.

Pure tests need no network and no browser. Tests marked `chrome` render through headless Chromium and are
skipped when none is found ($CHROME or the Playwright cache). Rendering runs --offline, so no font downloads.
"""
import json
import pathlib
import re
import subprocess
import sys

import pytest
from PIL import Image

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from render import find_chrome  # noqa: E402
from studio import canvas, engines, fonts, pipeline, scene, spec as S  # noqa: E402

CHROME = find_chrome()
chrome = pytest.mark.skipif(not CHROME, reason="no headless Chromium found")
TINY = {"id": "tiny", "width": 240, "height": 520}


def _screen(path, color=(240, 240, 235), size=(240, 520)):
    im = Image.new("RGB", size, color)
    for y in range(60, size[1] - 40, 90):          # a few content blocks, so ui_blocks finds something
        im.paste((40, 120, 80), (20, y, size[0] - 20, y + 50))
    im.save(path)
    return path


def make_campaign(tmp_path, panels=3, locales=("en-US",), slot=TINY, extra=None, write_screens=True):
    (tmp_path / "screens").mkdir(exist_ok=True)
    screens = {}
    for i in range(panels):
        sid = f"s{i + 1}"
        if write_screens:
            _screen(tmp_path / "screens" / f"{sid}.png", (230 + i * 5, 236, 230))
        screens[sid] = f"screens/{sid}.png"
    raw = {
        "app": {"name": "Testapp"},
        "campaign": {"name": "Testapp", "panels": panels, "locales": list(locales), "slots": [slot],
                     "engine": "floating-3d"},
        "screens": screens,
        "design": {"type": {"preset": "modern-tech"}},
        "storyboard": [{"id": f"p{i + 1}", "screen": f"s{i + 1}",
                        "headline": {"en-US": f"Plan **trip** {i + 1}", "he": f"תכנון **טיול** {i + 1}"}}
                       for i in range(panels)],
    }
    for k, v in (extra or {}).items():
        raw[k] = S.deep_merge(raw.get(k, {}), v) if isinstance(v, dict) else v
    p = tmp_path / "campaign.yaml"
    p.write_text(S.dump(raw))
    return p


def errors(issues):
    return [i for i in issues if i[0] == "error"]


# --- spec loading and validation -------------------------------------------------------------------------

def test_valid_campaign_has_no_errors(tmp_path, rules):
    sp = S.load(make_campaign(tmp_path))
    assert errors(S.validate(sp, rules)) == []


def test_defaults_filled(tmp_path):
    sp = S.load(make_campaign(tmp_path))
    assert sp["campaign"]["primary_locale"] == "en-US"
    assert sp["design"]["palette"]["accent"].startswith("#")
    assert sp["campaign"]["rtl_flow"] == "mirror"


@pytest.mark.parametrize("text", ["[1, 2", "- just\n- a list\n"])
def test_bad_yaml_rejected(tmp_path, text):
    p = tmp_path / "c.yaml"
    p.write_text(text)
    with pytest.raises(S.SpecError):
        S.load(p)


def test_missing_file_rejected(tmp_path):
    with pytest.raises(S.SpecError):
        S.load(tmp_path / "nope.yaml")


@pytest.mark.parametrize("change,needle", [
    ({"campaign": {"panels": 11}}, "1–10"),
    ({"campaign": {"panels": 0}}, "1–10"),
    ({"campaign": {"slots": ["iphone-99"]}}, "unknown slot"),
    ({"design": {"palette": {"accent": "orange"}}}, "#hex"),
    ({"design": {"type": {"preset": "comic-sans"}}}, "comic-sans"),
    ({"campaign": {"rtl_flow": "sideways"}}, "mirror or keep"),
    ({"layers": [{"type": "hologram"}]}, "hologram"),
    ({"background": [{"type": "plaid"}]}, "plaid"),
    ({"artwork": {"bg": {"file": "nope.png"}}}, "provenance"),
])
def test_invalid_configs(tmp_path, rules, change, needle):
    sp = S.load(make_campaign(tmp_path, extra=change))
    msgs = " ".join(m for _, _, m in errors(S.validate(sp, rules)))
    assert needle in msgs


def test_storyboard_count_must_match_panels(tmp_path, rules):
    sp = S.load(make_campaign(tmp_path))
    sp["storyboard"].pop()
    assert any("entries for 3 panels" in m for _, _, m in errors(S.validate(sp, rules)))


def test_undefined_screen_is_error(tmp_path, rules):
    sp = S.load(make_campaign(tmp_path))
    sp["storyboard"][0]["screen"] = "ghost"
    assert any("ghost" in m for _, _, m in errors(S.validate(sp, rules)))


def test_missing_screenshot_file_is_error(tmp_path, rules):
    sp = S.load(make_campaign(tmp_path, write_screens=False))
    errs = errors(S.validate(sp, rules))
    assert errs and all("not found" in m for _, _, m in errs)


def test_mockup_only_allows_missing_screens(tmp_path, rules):
    sp = S.load(make_campaign(tmp_path, write_screens=False, extra={"campaign": {"mockup_only": True}}))
    assert errors(S.validate(sp, rules)) == []


def test_missing_headline_for_locale(tmp_path, rules):
    sp = S.load(make_campaign(tmp_path, locales=("en-US", "he")))
    del sp["storyboard"][1]["headline"]["he"]
    issues = S.validate(sp, rules)
    assert any("falls back" in m for lv, _, m in issues if lv == "warn")


# --- copy rules: no invented claims, nothing the store forbids ---------------------------------------------

@pytest.mark.parametrize("text", ["The #1 hiking app", "Loved by 2M hikers", "500k+ downloads",
                                  "Award-winning maps", "Rated 4.9 stars", "★★★★★", "40% faster routes"])
def test_claims_without_evidence_are_errors(text):
    issues = []
    S.check_copy(text, "x", None, issues)
    assert errors(issues), text


def test_claim_with_evidence_is_note():
    issues = []
    S.check_copy("Loved by 2M hikers", "x", "App Store Connect, units, 2026-09", issues)
    assert not errors(issues) and issues[0][0] == "note"


def test_superlative_is_only_a_warning():
    issues = []
    S.check_copy("Your best run yet", "x", None, issues)
    assert [i[0] for i in issues] == ["warn"]


@pytest.mark.parametrize("text", ["Editor's Choice", "Visit www.example.com", "Only $4.99", "Free trial inside",
                                  "© 2026 Testapp", "Also on Google Play"])
def test_store_forbidden_copy(text):
    issues = []
    S.check_copy(text, "x", "evidence does not excuse these", issues)
    assert errors(issues), text


def test_plain_copy_passes():
    issues = []
    S.check_copy("Plan the day in **one look**", "x", None, issues)
    assert issues == []


def test_cli_check_flags_placeholders(tmp_path):
    p = make_campaign(tmp_path)
    p.write_text(p.read_text().replace("Plan **trip** 1", "[YOUR HEADLINE]"))
    r = subprocess.run([sys.executable, str(SCRIPTS / "campaign.py"), "check", str(p)], capture_output=True, text=True)
    assert r.returncode != 0
    assert "YOUR HEADLINE" in r.stdout + r.stderr


# --- slots, text, screens, tokens --------------------------------------------------------------------------

def test_slot_size_picks_largest(rules):
    sid, w, h = S.slot_size("iphone-di-large", rules)
    assert (w, h) == max((tuple(s) for s in rules["screenshots"]["slots"]["iphone-di-large"]["sizes"]),
                         key=lambda wh: wh[0] * wh[1])


def test_slot_size_custom():
    assert S.slot_size(TINY, {}) == ("tiny", 240, 520)


def test_text_for_fallbacks():
    v = {"en-US": "Hello", "he": "שלום"}
    assert S.text_for(v, "he-IL", "en-US") == ("שלום", "he")
    assert S.text_for(v, "ru", "en-US") == ("Hello", "en-US")
    assert S.text_for("Same", "ru", "en-US") == ("Same", "*")


def test_screen_path_locale_template(tmp_path):
    (tmp_path / "en-US").mkdir()
    _screen(tmp_path / "en-US" / "a.png")
    sp = S.normalize({"screens": {"a": "{locale}/a.png"}, "campaign": {"locales": ["en-US", "he"]}})
    sp["_base"] = str(tmp_path)
    p, localized = S.screen_path(sp, "a", "en-US", "iphone-di-large")
    assert p.exists() and localized
    p, localized = S.screen_path(sp, "a", "he", "iphone-di-large")   # falls back to the primary locale
    assert p.exists() and not localized


def test_screen_path_per_device(tmp_path):
    _screen(tmp_path / "phone.png")
    _screen(tmp_path / "pad.png")
    sp = S.normalize({"screens": {"a": {"iphone": "phone.png", "ipad": "pad.png"}}})
    sp["_base"] = str(tmp_path)
    assert S.screen_path(sp, "a", "en-US", "ipad-13")[0].name == "pad.png"
    assert S.screen_path(sp, "a", "en-US", "iphone-di-large")[0].name == "phone.png"


def test_tokens_have_units(tmp_path):
    t = S.tokens(S.load(make_campaign(tmp_path)))
    assert {"palette", "type", "device", "units"} <= set(t)


# --- fonts / scripts / RTL -------------------------------------------------------------------------------

def test_scripts_detected():
    assert "hebrew" in fonts.scripts_in("שלום")
    assert "cyrillic" in fonts.scripts_in("Привет")
    assert fonts.is_rtl("he") and fonts.is_rtl("ar-SA") and not fonts.is_rtl("ru")


def test_every_preset_has_display_and_text():
    for name, p in fonts.PRESETS.items():
        assert p.get("display") and p.get("text"), name


def test_rtl_mirrors_x_and_rotation(tmp_path):
    sp = S.load(make_campaign(tmp_path, panels=4))
    ctx = scene.Ctx(sp, "he", "tiny", 240, 520, mirror=True)
    assert ctx.X(0) == 4 * 240 and ctx.X(4) == 0
    assert ctx.rot((5, 20, -8)) == (5, -20, 8)
    ltr = scene.Ctx(sp, "en-US", "tiny", 240, 520, mirror=False)
    assert ltr.X(1.5) == 1.5 * 240 and ltr.rot((5, 20, -8)) == (5, 20, -8)


def test_mirror_respects_keep(tmp_path):
    sp = S.load(make_campaign(tmp_path, locales=("en-US", "he"), extra={"campaign": {"rtl_flow": "keep"}}))
    assert not pipeline.mirror_for(sp, "he")
    sp["campaign"]["rtl_flow"] = "mirror"
    assert pipeline.mirror_for(sp, "he") and not pipeline.mirror_for(sp, "en-US")


# --- engines ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("panels", [1, 3, 6, 10])
@pytest.mark.parametrize("name", sorted(engines.ENGINES))
def test_every_engine_lays_out_any_panel_count(tmp_path, name, panels):
    sp = S.load(make_campaign(tmp_path, panels=panels))
    g = engines.generate(sp, name, None)
    texts = [L for L in g["layers"] if L["type"] == "text"]
    assert {L["panel"] for L in texts} == set(range(1, panels + 1)), name
    assert g["background"]


def test_engine_is_deterministic(tmp_path):
    sp = S.load(make_campaign(tmp_path, panels=6))
    assert json.dumps(engines.generate(sp, "panoramic-flow")) == json.dumps(engines.generate(sp, "panoramic-flow"))


def test_default_six_are_distinct_engines():
    assert len(set(engines.DEFAULT_SIX)) == 6 and set(engines.DEFAULT_SIX) <= set(engines.ENGINES)


def test_unknown_engine(tmp_path):
    sp = S.load(make_campaign(tmp_path))
    with pytest.raises(Exception):
        engines.generate(sp, "no-such-engine")


def test_layout_prefers_handwritten_layers(tmp_path):
    sp = S.load(make_campaign(tmp_path))
    sp["layers"] = [{"type": "text", "panel": 1, "items": [{"role": "headline", "text": "x"}]}]
    sp["extra_layers"] = [{"type": "glow", "x": 1, "y": 0.5}]
    lay = pipeline.layout_for(sp)
    assert lay["engine"] in ("custom", "floating-3d") and len(lay["layers"]) == 2


# --- scene HTML --------------------------------------------------------------------------------------------

def test_scene_html_is_self_contained(tmp_path):
    sp = S.load(make_campaign(tmp_path))
    lay = pipeline.layout_for(sp)
    finfo, css, _ = fonts.resolve(sp["design"]["type"], {"latin"}, tmp_path, offline=True)
    page = scene.build(sp, "en-US", "tiny", 240, 520, lay, finfo, css)
    page = page[0] if isinstance(page, tuple) else page
    assert "<html" in page and 'id="__m"' in page
    assert "https://" not in page.replace("http://www.w3.org", "")      # no network at render time
    assert "screens/s1.png" in page                                        # the real screenshot, not a mockup


# --- slicing, reassembly, export checks --------------------------------------------------------------------

def _master(path, N, W, H):
    im = Image.new("RGBA", (N * W, H))
    for k in range(N):
        im.paste((20 * k, 250 - 20 * k, 90, 255), (k * W, 0, (k + 1) * W, H))
        im.paste((255, 255, 255, 255), (k * W + 5, 10, k * W + 25, 30))   # not one flat colour
    im.save(path)
    return path


@pytest.mark.parametrize("N,W,H", [(1, 60, 130), (3, 60, 130), (5, 90, 120), (10, 40, 87)])
@pytest.mark.parametrize("mirror", [False, True])
def test_slice_exact_and_reassembles(tmp_path, N, W, H, mirror):
    m = _master(tmp_path / "master.png", N, W, H)
    files = pipeline.slice_panels(m, N, W, H, mirror, tmp_path / "panels", [f"id{k}" for k in range(N)])
    assert [f.name for f in files] == [f"{k + 1:02d}-id{k}.png" for k in range(N)]
    assert pipeline.reassemble_ok(files, m, N, W, H, mirror)
    assert pipeline.export_checks(files, W, H, N) == []
    with Image.open(files[0]) as first:
        col = (N - 1) if mirror else 0
        assert first.getpixel((W // 2, H // 2)) == (20 * col, 250 - 20 * col, 90)  # panel 1 = rightmost in RTL
        assert first.mode == "RGB" and first.info.get("icc_profile")
    assert (tmp_path / "panorama.png").exists()


def test_slice_rejects_wrong_master_size(tmp_path):
    m = _master(tmp_path / "m.png", 3, 60, 130)
    with pytest.raises(RuntimeError):
        pipeline.slice_panels(m, 4, 60, 130, False, tmp_path / "p", list("abcd"))


def test_reassemble_detects_tampering(tmp_path):
    m = _master(tmp_path / "m.png", 3, 60, 130)
    files = pipeline.slice_panels(m, 3, 60, 130, False, tmp_path / "p", list("abc"))
    Image.new("RGB", (60, 130), (1, 2, 3)).save(files[1])
    assert not pipeline.reassemble_ok(files, m, 3, 60, 130, False)


def test_export_checks_catch_problems(tmp_path):
    good = tmp_path / "01-a.png"
    Image.new("RGB", (60, 130), (9, 9, 9)).save(good)
    alpha = tmp_path / "02-b.png"
    Image.new("RGBA", (60, 130), (9, 9, 9, 128)).save(alpha)
    wrong = tmp_path / "03-c.jpg"
    Image.new("RGB", (50, 130), (9, 9, 9)).save(wrong, "JPEG")
    msgs = " ".join(m for _, _, m in pipeline.export_checks([good, alpha, wrong], 60, 130, 4))
    for needle in ("3 files for 4 panels", "alpha", "expected PNG", "expected 60x130", "flat colour"):
        assert needle in msgs


def test_presentation_and_store_preview(tmp_path):
    m = _master(tmp_path / "m.png", 4, 60, 130)
    files = pipeline.slice_panels(m, 4, 60, 130, False, tmp_path / "p", list("abcd"))
    pipeline.presentation(files, tmp_path / "pres.png", width=600)
    pipeline.store_preview(files, tmp_path / "sp.png", height=100)
    assert Image.open(tmp_path / "pres.png").width == 600
    assert Image.open(tmp_path / "sp.png").height == 136


def test_install_into_kit_layout(tmp_path):
    m = _master(tmp_path / "m.png", 2, 60, 130)
    files = pipeline.slice_panels(m, 2, 60, 130, False, tmp_path / "p", ["a", "b"])
    kit = tmp_path / "kit"
    (kit / "screenshots" / "en-US" / "tiny").mkdir(parents=True)
    (kit / "screenshots" / "en-US" / "tiny" / "old.png").write_bytes(b"x")
    dest, replaced = pipeline.install(files, kit, "en-US", "tiny")
    assert sorted(p.name for p in dest.glob("*.png")) == ["01-a.png", "02-b.png"] and replaced == ["old.png"]


def test_report(tmp_path):
    n = pipeline.write_report(tmp_path / "r.md", "T", [("error", "a", "bad"), ("warn", "b", "meh")])
    text = (tmp_path / "r.md").read_text()
    assert n == 1 and "FAIL" in text and text.index("bad") < text.index("meh")


# --- canvas export (Claude Design) -------------------------------------------------------------------------

def test_canvas_tokenize_and_link(tmp_path):
    assets = {}
    out = canvas._tokenize('<img src="file:///a/b%20c.png"><i style="background:url(file:///a/d.png)">', assets)
    assert "file://" not in out and assets == {"/a/b c.png": "__ASSET_001__", "/a/d.png": "__ASSET_002__"}
    proj = tmp_path / "project"
    proj.mkdir()
    (proj / "Main.dc.html").write_text(out)
    (tmp_path / "asset-urls.json").write_text(json.dumps({"__ASSET_001__": "/_blob/1"}))
    assert canvas.link(tmp_path) == 1                                     # one token still has no url
    (tmp_path / "asset-urls.json").write_text(json.dumps({"__ASSET_002__": "/_blob/2"}))
    assert canvas.link(tmp_path) == 0
    assert "__ASSET_" not in (proj / "Main.dc.html").read_text()


def test_canvas_board_shape():
    b = canvas.board("Main", "T", "<div>x</div>", ".a{}", "<link>", 300, 650)
    assert '<script src="./support.js"></script>' in b
    assert "class Component extends DCLogic" in b and '"$preview":{"width":300,"height":650}' in b


def test_canvas_flatten_strips_layered_effects():
    s = ('a{transform-style:preserve-3d;perspective-origin:50% 50%}'
         '<i style="perspective:900px;filter:brightness(0.8) drop-shadow(0 2px 9px rgba(0,0,0,.2));'
         'mix-blend-mode:screen;opacity:1;transform:rotateY(8deg)">')
    out = canvas._flatten(s)
    for gone in ("filter", "drop-shadow", "mix-blend", "preserve-3d", "perspective"):
        assert gone not in out
    assert "opacity:1;" in out and "transform:rotateY(8deg)" in out and out.startswith("a{}")


def test_canvas_drop_removes_whole_subtrees():
    h = ('<div data-id="a"><div><b>x</b></div></div><img data-id="b" src="s.png">'
         '<div data-id="c">keep</div><span data-id="d">y</span>')
    out = canvas._drop(h, ["a", "b", "d", "missing"])
    assert out == '<div data-id="c">keep</div>'


def test_canvas_off_panel_by_rect_and_text_panel():
    measure = {"els": [{"id": "dev1", "rect": [10, 0, 80, 100]},
                       {"id": "dev2", "rect": [110, 0, 80, 100], "outer": [150, 0, 80, 100]},
                       {"id": "bg", "rect": [0, 0, 300, 100]}]}
    html = ('<div data-id="text1" data-kind="text" data-panel="1"></div>'
            '<div data-id="text2" data-kind="text" data-panel="2"></div>')
    assert sorted(canvas._off_panel(measure, html, 0, 100, 3, False)) == ["dev2", "text2"]
    assert sorted(canvas._off_panel(measure, html, 1, 100, 3, False)) == ["dev1", "text1"]
    # RTL: panel 1 sits in the rightmost column; dev2's outer rect (shadow, tilt) reaches into it
    assert sorted(canvas._off_panel(measure, html, 2, 100, 3, True)) == ["dev1", "text2"]


def test_canvas_small_copies(tmp_path):
    big, small = tmp_path / "big.png", tmp_path / "small.png"
    Image.new("RGB", (400, 800), (200, 10, 10)).save(big)
    Image.new("RGB", (100, 200), (10, 200, 10)).save(small)
    files = canvas._small_copies({str(big): "__ASSET_001__", str(small): "__ASSET_002__"}, tmp_path / "o", 200)
    with Image.open(files["__ASSET_001__"]) as a, Image.open(files["__ASSET_002__"]) as b:
        assert a.size == (200, 400) and b.size == (100, 200)
    with Image.open(big) as src:
        assert src.size == (400, 800)                                       # the source is never touched


@chrome
def test_canvas_export_per_panel_boards(tmp_path):
    p = make_campaign(tmp_path, panels=3)
    out = tmp_path / "cv"
    r = subprocess.run([sys.executable, str(SCRIPTS / "campaign.py"), "canvas", str(p), "--out", str(out),
                        "--offline"], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    proj = out / "project"
    cv = json.loads((proj / "canvas.json").read_text())
    assert cv["order"][0] == "Main.dc.html" and len(cv["order"]) == 4
    for k, name in enumerate(cv["order"][1:], start=1):
        t = (proj / name).read_text()
        panels = re.findall(r'data-kind="text" data-panel="(\d+)"', t)
        assert panels and set(panels) == {str(k)}
        assert not re.search(r"filter:|mix-blend-mode|preserve-3d|perspective", t)
    main = (proj / "Main.dc.html").read_text()
    assert set(re.findall(r'data-kind="text" data-panel="(\d+)"', main)) == {"1", "2", "3"}
    up = json.loads((out / "assets.json").read_text())
    assert len(up) == 3 and all(pathlib.Path(u["file"]).exists() and u["file"] != u["source"] for u in up)


# --- rendering through headless Chromium ---------------------------------------------------------------------

def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPTS / "campaign.py"), *map(str, args)],
                          capture_output=True, text=True, timeout=600)


@chrome
def test_render_end_to_end_ltr_and_rtl(tmp_path):
    p = make_campaign(tmp_path, panels=3, locales=("en-US", "he"))
    out = tmp_path / "out"
    r = _run("render", p, "--out", out, "--offline")
    assert r.returncode == 0, r.stdout + r.stderr
    for loc in ("en-US", "he"):
        d = out / loc / "tiny"
        files = sorted((d / "panels").glob("*.png"))
        assert [f.name for f in files] == ["01-p1.png", "02-p2.png", "03-p3.png"]
        assert pipeline.export_checks(files, 240, 520, 3) == []
        assert (d / "panorama.png").exists() and (d / "report.md").exists() and (d / "presentation.png").exists()
        assert (d / "source" / "scene.html").exists()
    assert (out / "design-tokens.json").exists()
    man = json.loads((out / "campaign-manifest.json").read_text())
    assert man
    # Hebrew panel 1 is cut from the right end of its master
    he = out / "he" / "tiny"
    with Image.open(he / "panorama.png") as pano, Image.open(he / "panels" / "01-p1.png") as p1:
        assert p1.tobytes() == pano.convert("RGB").crop((480, 0, 720, 520)).tobytes()


@chrome
def test_render_is_deterministic(tmp_path):
    p = make_campaign(tmp_path, panels=2)
    a, b = _run("render", p, "--out", tmp_path / "a", "--offline"), _run("render", p, "--out", tmp_path / "b", "--offline")
    assert a.returncode == 0 and b.returncode == 0, a.stdout + b.stdout
    for f in ("01-p1.png", "02-p2.png"):
        assert pipeline.sha(tmp_path / "a/en-US/tiny/panels" / f) == pipeline.sha(tmp_path / "b/en-US/tiny/panels" / f)


@chrome
def test_render_refuses_missing_screens(tmp_path):
    p = make_campaign(tmp_path, panels=2, write_screens=False)
    r = _run("render", p, "--out", tmp_path / "o", "--offline")
    assert r.returncode != 0
    assert not list((tmp_path / "o").rglob("*.png")) if (tmp_path / "o").exists() else True


@chrome
def test_ipad_aspect(tmp_path):
    p = make_campaign(tmp_path, panels=2, slot={"id": "pad", "width": 400, "height": 533})
    r = _run("render", p, "--out", tmp_path / "o", "--offline", "--engine", "editorial")
    assert r.returncode == 0, r.stdout + r.stderr
    with Image.open(tmp_path / "o/en-US/pad/panels/01-p1.png") as im:
        assert im.size == (400, 533)


@chrome
def test_concepts_contact_sheet(tmp_path):
    p = make_campaign(tmp_path, panels=3)
    r = _run("concepts", p, "--out", tmp_path / "c", "--offline", "--engines", "floating-3d,editorial",
             "--scale", "0.5")
    assert r.returncode == 0, r.stdout + r.stderr
    sheet = tmp_path / "c" / "concepts" / "contact-sheet.png"
    assert sheet.exists() and Image.open(sheet).height > 300
    assert (tmp_path / "c" / "concepts" / "A-floating-3d.png").exists()


# --- skill structure, template and sample ----------------------------------------------------------------------

ROOT = SCRIPTS.parent


def test_skill_discovers_campaign():
    skill = (ROOT / "SKILL.md").read_text()
    assert "scripts/campaign.py" in skill and "references/creative-director.md" in skill
    assert (ROOT / "references" / "creative-director.md").exists()
    r = subprocess.run([sys.executable, str(SCRIPTS / "campaign.py"), "engines"], capture_output=True, text=True)
    assert r.returncode == 0 and all(e in r.stdout for e in engines.ENGINES)


def test_template_parses_and_validates_shape(rules):
    sp = S.load(ROOT / "templates" / "campaign.example.yaml")
    sp["campaign"]["mockup_only"] = True          # the template's screens are not shipped
    assert errors(S.validate(sp, rules)) == []


def test_sample_campaign_is_valid(rules):
    sample = ROOT / "examples" / "sample-campaign" / "campaign.yaml"
    sp = S.load(sample)
    if not (sample.parent / "screens" / "map.png").exists():
        sp["campaign"]["mockup_only"] = True      # npm install: screens are made by make_screens.py
    assert errors(S.validate(sp, rules)) == []
    assert sp["campaign"]["panels"] == len(sp["storyboard"]) == 6


def test_screenshot_loading(tmp_path):
    sp = S.load(make_campaign(tmp_path))
    ctx = scene.Ctx(sp, "en-US", "tiny", 240, 520, mirror=False)
    uri, w, h = ctx.shot("s1")
    assert uri.startswith("file://") and (w, h) == (240, 520)
    (tmp_path / "screens" / "s2.png").unlink()
    with pytest.raises(FileNotFoundError):
        ctx.shot("s2")
