import json

import yaml

import status_board as sb
from test_connect_guide import make_kit


def progress(kit, steps):
    (kit / "connect-progress.yaml").write_text(yaml.safe_dump({"steps": steps}))


def test_board_marks_done_person_yes_and_next(tmp_path):
    kit = make_kit(tmp_path)
    progress(kit, {"new-app/fill-in-the-new-app-dialog": {"status": "done-by-owner", "date": "2026-10-14"}})
    md = sb.render(kit)
    assert "✅ Fill in the New App dialog — owner, 2026-10-14" in md
    assert "✋" in md  # agreements, tax, banking are the owner's
    assert "🛑" in md  # submit / release need a yes
    nxt = next(l for l in md.splitlines() if l.startswith("**Next:**"))
    assert "Fill in the New App dialog" not in nxt
    assert "Progress: 1 of" in md


def test_precheck_blockers_take_over_next(tmp_path):
    kit = make_kit(tmp_path)
    (kit / "PRECHECK.md").write_text("# Pre-check\n\n## BLOCKER (2)\n\n## LIKELY REJECTION (0)\n\n"
                                     "## WARNING (1)\n\n## PASS (30)\n\n## For Claude to judge (4)\n")
    md = sb.render(kit)
    assert "**Next:** 🛑 fix the 2 blocker(s)" in md
    assert "2 blocker(s), 0 likely rejection(s), 1 warning(s), 30 passed, 4 for Claude to judge" in md


def test_missing_precheck_and_plan_are_fine(tmp_path):
    md = sb.render(make_kit(tmp_path))
    assert "Not run yet" in md
    assert "App Store Connect (API)" not in md


def test_plan_shows_waiting_changes_and_open_steps(tmp_path):
    kit = make_kit(tmp_path)
    (kit / "connect-plan.json").write_text(json.dumps({
        "generated": "2026-10-14", "kit_version": "1.0.0", "build": "3",
        "version": {"action": "use", "state": "PREPARE_FOR_SUBMISSION"},
        "items": [{"area": "text"}, {"area": "media"}], "warnings": ["price differs"],
        "browser_steps": [{"text": "App Privacy: Publish", "done": False}, {"text": "Pricing", "done": True}],
        "person_steps": [{"text": "Paid Apps Agreement", "done": False}]}))
    md = sb.render(kit)
    assert "2 change(s) waiting for your yes" in md
    assert "🌐 App Privacy: Publish" in md and "🌐 Pricing" not in md
    assert "✋ Paid Apps Agreement" in md
    assert "⚠️ price differs" in md


def test_main_writes_status_md_and_never_reads_private(tmp_path):
    kit = make_kit(tmp_path, private={"review_contact": {"phone": "+1 555 0100"}, "demo_password": "s3cret"})
    assert sb.main([str(kit)]) == 0
    text = (kit / "STATUS.md").read_text()
    assert "555 0100" not in text and "s3cret" not in text
    assert sb.main([str(tmp_path / "nope")]) == 2


def _platforms(kit, fams):
    facts = yaml.safe_load((kit / "facts.yaml").read_text()) or {}
    facts["platforms"] = fams
    (kit / "facts.yaml").write_text(yaml.safe_dump(facts))


def _shots(kit, loc, slot, size, n):
    from PIL import Image
    d = kit / "screenshots" / loc / slot
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        Image.new("RGB", size, (200, 200, 200)).save(d / f"{i + 1:02d}.png")


def test_watch_screenshots_missing_is_red_until_present(tmp_path):
    kit = make_kit(tmp_path)
    _platforms(kit, ["iphone", "watch"])
    _shots(kit, "en-US", "iphone-di-medium", (1206, 2622), 3)
    md = sb.render(kit)
    assert "🔴 Apple Watch screenshots missing" in md and "en-US" in md
    _shots(kit, "en-US", "watch", (416, 496), 5)
    md = sb.render(kit)
    assert "🔴" not in md and "✅ Apple Watch screenshots in every locale." in md


def test_watch_detected_from_project(tmp_path):
    (tmp_path / "kit").mkdir()
    kit = make_kit(tmp_path / "kit")
    proj = tmp_path / "App" / "App.xcodeproj"
    proj.mkdir(parents=True)
    (proj / "project.pbxproj").write_text("buildSettings = { WATCHOS_DEPLOYMENT_TARGET = 11.0; };")
    md = sb.render(kit, tmp_path / "App")
    assert "🔴 Apple Watch screenshots missing" in md and "WATCHOS_DEPLOYMENT_TARGET" in md


def test_header_asset_is_an_open_item_not_a_blocker(tmp_path):
    kit = make_kit(tmp_path)
    md = sb.render(kit)
    line = next(l for l in md.splitlines() if "Header and search-results asset" in l)
    assert line.startswith("- ⬜") and "Ask the owner" in line
    assert "fix the" not in next(l for l in md.splitlines() if l.startswith("**Next:**"))
    from PIL import Image
    (kit / "creative/en-US").mkdir(parents=True)
    Image.new("RGB", (5244, 2950)).save(kit / "creative/en-US/universal.png")
    assert "✅ Header and search-results asset: 1 file(s)" in sb.render(kit)
