import json
import pathlib

import pytest
import yaml
from PIL import Image

import validate_kit as vk

IPHONE = (1206, 2622)
IPAD = (2064, 2752)


def png(path, size, mode="RGB", color=(240, 236, 228)):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    c = color + (255,) if mode == "RGBA" else color
    Image.new(mode, size, c).save(path)
    return path


def kit_with(tmp_path, sets):
    for (loc, slot), (size, n) in sets.items():
        for i in range(n):
            png(tmp_path / "screenshots" / loc / slot / f"{i + 1:02d}.png", size)
    return tmp_path


def run(argv):
    return vk.main([str(a) for a in argv])


def test_rgba_png_fails_and_fix_strips_alpha(tmp_path, capsys):
    p = png(tmp_path / "a.png", IPHONE, "RGBA")
    assert run(["--pairs", f"iphone-di-medium={p}"]) == 1
    assert "alpha channel present" in capsys.readouterr().out
    assert run(["--pairs", "--fix", f"iphone-di-medium={p}"]) == 0
    assert Image.open(p).mode == "RGB"


def test_wrong_size_fails_and_landscape_passes(tmp_path, capsys):
    bad = png(tmp_path / "bad.png", (1200, 2600))
    land = png(tmp_path / "land.png", (2622, 1206))
    assert run(["--pairs", f"iphone-di-medium={bad}"]) == 1
    assert "not an accepted size" in capsys.readouterr().out
    assert run(["--pairs", f"iphone-di-medium={land}"]) == 0


def test_non_image_type_fails(tmp_path):
    p = tmp_path / "a.webp"
    Image.new("RGB", IPHONE).save(p, "WEBP")
    assert run(["--pairs", f"iphone-di-medium={p}"]) == 1


def test_complete_kit_passes_and_report_written(tmp_path):
    kit = kit_with(tmp_path, {("en-US", "iphone-di-medium"): (IPHONE, 3), ("en-US", "ipad-13"): (IPAD, 3)})
    report = tmp_path / "report.md"
    assert run([kit, "--platforms", "iphone,ipad", "--today", "2026-10-14", "--report", report]) == 0
    assert "| en-US | none |" in report.read_text()


def test_missing_required_ipad_set_is_reported_per_locale(tmp_path):
    kit = kit_with(tmp_path, {("en-US", "iphone-di-medium"): (IPHONE, 2), ("de-DE", "iphone-di-medium"): (IPHONE, 2),
                              ("de-DE", "ipad-13"): (IPAD, 2)})
    report = tmp_path / "report.md"
    assert run([kit, "--platforms", "iphone,ipad", "--today", "2026-10-14", "--report", report]) == 1
    text = report.read_text()
    assert "| en-US | ipad-13 |" in text and "| de-DE | none |" in text


def test_more_than_ten_screenshots_fails(tmp_path, capsys):
    kit = kit_with(tmp_path, {("en-US", "iphone-di-medium"): (IPHONE, 11)})
    assert run([kit, "--platforms", "iphone", "--today", "2026-10-14"]) == 1
    assert "11 screenshot(s)" in capsys.readouterr().out


def test_duo_becomes_required_in_april_2027(tmp_path, capsys):
    kit = kit_with(tmp_path, {("en-US", "iphone-di-medium"): (IPHONE, 1)})
    assert run([kit, "--platforms", "iphone", "--today", "2026-10-14"]) == 0
    assert run([kit, "--platforms", "iphone", "--today", "2027-04-02"]) == 1
    assert "iphone-duo-inner" in capsys.readouterr().out


def test_frozen_kit_rules_are_used(tmp_path, rules, capsys):
    kit = kit_with(tmp_path, {("en-US", "iphone-di-medium"): (IPHONE, 1)})
    frozen = json.loads(json.dumps(rules))
    frozen["screenshots"]["slots"]["iphone-di-medium"]["sizes"] = [[1179, 2556]]
    frozen["frozen_for_kit"] = True
    frozen["fetched"] = "2026-10-14"
    (kit / "rules.json").write_text(json.dumps(frozen))
    assert run([kit, "--platforms", "iphone", "--today", "2026-10-15"]) == 1
    out = capsys.readouterr().out
    assert "1206x2622 is not an accepted size" in out
    assert "frozen_for_kit=True" in out


def test_baseline_rules_warn_when_not_frozen_or_old(tmp_path, capsys):
    kit = kit_with(tmp_path, {("en-US", "iphone-di-medium"): (IPHONE, 1)})
    run([kit, "--platforms", "iphone", "--today", "2027-01-01"])
    out = capsys.readouterr().out
    assert "no frozen KIT/rules.json" in out
    assert "days old" in out


def test_iap_promo_image(tmp_path, capsys):
    kit = kit_with(tmp_path, {("en-US", "iphone-di-medium"): (IPHONE, 1)})
    png(kit / "iap" / "pro" / "promo.png", (1024, 1024), "RGBA")
    assert run([kit, "--platforms", "iphone", "--today", "2026-10-14"]) == 1
    assert "iap/pro" in capsys.readouterr().out
    assert run([kit, "--platforms", "iphone", "--today", "2026-10-14", "--fix"]) == 0


def test_frames_house_rules_and_placeholders(tmp_path, capsys):
    kit = kit_with(tmp_path, {("en-US", "iphone-di-medium"): (IPHONE, 1)})
    (kit / "frames.yaml").write_text(yaml.safe_dump({
        "defaults": {"background": "#FFFFFF", "ink": "#BBBBBB"},
        "frames": [{"id": "a", "caption": {"en-US": "This caption is much too long for a frame"}},
                   {"id": "b", "caption": {"en-US": "Lorem ipsum"}}]}))
    assert run([kit, "--platforms", "iphone", "--today", "2026-10-14"]) == 1
    out = capsys.readouterr().out
    assert "house: caption has 9 words" in out
    assert "contrast" in out
    assert "placeholder" in out
    assert "dark frame" in out


def test_simulator_corner_dot_warns(tmp_path, capsys):
    p = png(tmp_path / "dot.png", IPHONE, color=(255, 255, 255))
    im = Image.open(p)
    for x in range(3):
        for y in range(3):
            im.putpixel((x, y), (0, 0, 0))
    im.save(p)
    assert run(["--pairs", f"iphone-di-medium={p}"]) == 0
    assert "artefact" in capsys.readouterr().out


def test_accepted_sizes_orientation(rules):
    s = rules["screenshots"]["slots"]
    assert (2622, 1206) in vk.accepted_sizes(s["iphone-di-medium"])
    assert (800, 1280) not in vk.accepted_sizes(s["mac"])
    assert (514, 422) not in vk.accepted_sizes(s["watch"])


def test_creative_assets_sizes(tmp_path, capsys):
    kit = kit_with(tmp_path, {("en-US", "iphone-di-medium"): (IPHONE, 3), ("en-US", "ipad-13"): (IPAD, 3)})
    png(kit / "creative/en-US/universal.png", (5244, 2950))
    png(kit / "creative/en-US/search.png", (2400, 1600))      # any 3:2 width from 1920 to 3840
    assert run([kit, "--platforms", "iphone,ipad", "--today", "2026-10-14"]) == 0
    png(kit / "creative/en-US/header.png", (3840, 2560))      # 3:2 is for search results, not the header
    assert run([kit, "--platforms", "iphone,ipad", "--today", "2026-10-14"]) == 1
    assert "3840x2560 is not an accepted size for header creative asset" in capsys.readouterr().out


def test_creative_universal_png_with_alpha_fails(tmp_path, capsys):
    kit = kit_with(tmp_path, {("en-US", "iphone-di-medium"): (IPHONE, 3), ("en-US", "ipad-13"): (IPAD, 3)})
    png(kit / "creative/en-US/universal.png", (5244, 2950), mode="RGBA")
    assert run([kit, "--platforms", "iphone,ipad", "--today", "2026-10-14"]) == 1
    assert "alpha channel present" in capsys.readouterr().out


def test_creative_jpeg_is_fine_for_21_9_header_but_not_for_16_9(tmp_path, capsys):
    kit = kit_with(tmp_path, {("en-US", "iphone-di-medium"): (IPHONE, 3), ("en-US", "ipad-13"): (IPAD, 3)})
    (kit / "creative/en-US").mkdir(parents=True)
    Image.new("RGB", (3840, 1646), (10, 180, 100)).save(kit / "creative/en-US/header.jpg", "JPEG")
    assert run([kit, "--platforms", "iphone,ipad", "--today", "2026-10-14"]) == 0
    Image.new("RGB", (5244, 2950), (10, 180, 100)).save(kit / "creative/en-US/search.jpg", "JPEG")
    assert run([kit, "--platforms", "iphone,ipad", "--today", "2026-10-14"]) == 1
    assert "type JPEG, need PNG" in capsys.readouterr().out
