import pathlib

import yaml

import lint_metadata as lm

GOOD = {
    "name": "Pebble: Photo Cleaner",
    "subtitle": "Swipe to tidy your library",
    "promotional_text": "Sort a month of photos over a coffee.",
    "description": "Pebble helps you clear out your photo library one swipe at a time.\n\n"
                   "- Swipe left to delete, right to keep\n- Everything stays on your device\n\n"
                   "Pebble is free to use with ads. An optional in-app purchase removes them.",
    "keywords": "declutter,storage,duplicates,camera roll,gallery,organizer,cleanup,burst,screenshots",
    "support_url": "https://example.com/support",
    "privacy_policy_url": "https://example.com/privacy",
    "marketing_url": "https://example.com",
    "category": {"primary": "Photo & Video", "secondary": "Utilities"},
    "copyright": "2026 Example Ltd",
    "iap": [{"product_id": "pro", "display_name": "Pebble Pro", "description": "No ads, ever"}],
}
FACTS = {"company": "Example", "first_version": True, "has_iap": True, "has_ads": True,
         "claims": ["stays on your device"], "competitors": ["Snapclean"]}


def lint(rules, **over):
    meta = {**GOOD, **over}
    return lm.lint(meta, FACTS, rules)


def test_good_metadata_has_no_errors(rules):
    f = lint(rules)
    assert f.errors == []


def test_planted_31_char_name_is_an_error(rules):
    name = "A" * 31
    assert len(name) == 31
    f = lint(rules, name=name)
    assert any("name is 31 chars, limit 30" in e for e in f.errors)


def test_30_char_name_is_fine(rules):
    f = lint(rules, name="B" * 30)
    assert not any(e.startswith("name") for e in f.errors)


def test_subtitle_and_promo_limits(rules):
    f = lint(rules, subtitle="x" * 31, promotional_text="y" * 171)
    assert any("subtitle is 31" in e for e in f.errors)
    assert any("promotional_text is 171" in e for e in f.errors)


def test_keywords_count_bytes_not_characters(rules):
    kw = "überall," * 11 + "größe"  # 79 characters, but more than 100 bytes
    assert len(kw) <= 100 < len(kw.encode())
    f = lint(rules, keywords=kw)
    assert any("keywords are" in e and "bytes" in e for e in f.errors)


def test_keyword_hygiene_warnings(rules):
    f = lint(rules, keywords="photo, cleaner,storage,storages,app tools")
    w = " | ".join(f.warnings)
    assert "spaces around commas" in w
    assert "repeats photo" in w and "repeats cleaner" in w
    assert "plural of 'storage'" in w
    assert "word 'app'" in w


def test_short_term_trademark_and_competitor_are_errors(rules):
    f = lint(rules, keywords="ok,iphone cleaner,snapclean,storage")
    e = " | ".join(f.errors)
    assert "'ok' is shorter than 3" in e
    assert "Apple trademark 'iphone'" in e
    assert "competitor" in e


def test_prices_other_platforms_kids_placeholders(rules):
    f = lint(rules, promotional_text="Now $0.99 for Pro! Also on Android.",
             description="Made for kids. TODO write this. " + GOOD["description"])
    e = " | ".join(f.errors)
    assert "price" in e
    assert "another platform" in e
    assert "Kids Category" in e
    assert "placeholder" in e


def test_free_without_iap_disclosure_warns(rules):
    f = lint(rules, description="Totally free photo cleaning.", promotional_text="Free forever.")
    assert any("'free'" in w for w in f.warnings)


def test_unbacked_claim_warns_and_backed_claim_does_not(rules):
    f = lint(rules, promotional_text="The fastest cleaner in the world.")
    assert any("claim 'fastest'" in w for w in f.warnings)
    f = lint(rules, promotional_text="Only Pebble keeps it all: everything stays on your device.")
    assert not any("promotional_text: claim" in w for w in f.warnings)


def test_mistyped_apple_marks_warn(rules):
    f = lint(rules, description=GOOD["description"] + " Download it on the AppStore for your Iphone.")
    w = " | ".join(f.warnings)
    assert "App Store" in w and "iPhone" in w


def test_required_urls_and_copyright(rules):
    f = lint(rules, privacy_policy_url=None, support_url="example.com", copyright="")
    e = " | ".join(f.errors)
    assert "privacy_policy_url is required" in e
    assert "full URL" in e
    assert "copyright is required" in e


def test_whats_new_required_after_first_version(rules):
    f = lm.lint({**GOOD}, {**FACTS, "first_version": False}, rules)
    assert any("whats_new is required" in e for e in f.errors)


def test_iap_limits(rules):
    f = lint(rules, iap=[{"product_id": "pro", "display_name": "P" * 31, "description": "d" * 46}])
    e = " | ".join(f.errors)
    assert "display_name is 31" in e and "description is 46" in e


def test_cli_on_kit_dir(tmp_path):
    (tmp_path / "facts.yaml").write_text(yaml.safe_dump(FACTS))
    (tmp_path / "metadata.en-US.yaml").write_text(yaml.safe_dump(GOOD))
    assert lm.main([str(tmp_path)]) == 0
    (tmp_path / "metadata.de-DE.yaml").write_text(yaml.safe_dump({**GOOD, "name": "N" * 31}))
    assert lm.main([str(tmp_path)]) == 1
