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


COMPLETE_NOTES = ("Tested on iPhone 17, iOS 26. Same in every region. "
                  "Added filters: open the Library tab. Demo account credentials are in Review Information. "
                  "A test account has an expired subscription. Required hardware video is attached. "
                  "External services: AI provider, payment processor and authentication provider.")


def review_warnings(rules, notes="See the app.", **facts):
    return [w for w in lm.lint({**GOOD, "review_notes": notes}, facts, rules).warnings if "MD-14" in w]


def test_review_basics_are_warnings_with_source(rules):
    warnings = review_warnings(rules)
    assert len(warnings) == 2
    assert [w for w in review_warnings(rules, "") if "no review notes" in w]
    assert all("2.1 / Before You Submit" in w and lm.REVIEW_HELP in w for w in warnings)
    assert review_warnings(rules, COMPLETE_NOTES) == []


def test_review_applicable_checks(rules):
    cases = [({"first_version": False}, "what changed"),
             ({"app": {"version": "1.1"}}, "what changed"),
             ({"version": "2.0"}, "what changed"),
             ({"has_subscription": True}, "expired-subscription"),
             ({"monetization": {"iap": [{"type": "Auto-Renewable Subscription"}]}}, "expired-subscription"),
             ({"has_login": True}, "credentials"),
             ({"sign_in_required": True}, "credentials"),
             ({"review": {"hardware": True}}, "video"),
             ({"review": {"external_services": ["provider"]}}, "external services"),
             ({"third_party_ai": True}, "external services"),
             ({"payment_services": ["processor"]}, "external services"),
             ({"auth_services": ["provider"]}, "external services")]
    for facts, expected in cases:
        assert any(expected in w for w in review_warnings(rules, **facts))
        assert review_warnings(rules, COMPLETE_NOTES, **facts) == []
    assert review_warnings(rules, COMPLETE_NOTES, has_login=False, review={"hardware": False}) == []


def test_review_update_requires_changes_and_navigation(rules):
    for notes in ("Added filters.", "Open Library."):
        f = lm.lint({**GOOD, "whats_new": "Filters", "review_notes": notes}, {}, rules)
        assert any("what changed" in w for w in f.warnings)
    f = lm.lint({**GOOD, "version": "2.0", "review_notes": "Added filters: tap Library."}, {}, rules)
    assert not any("what changed" in w for w in f.warnings)


def test_review_demo_mode_and_expired_account(rules):
    assert not any("credentials" in w for w in review_warnings(rules, "Use demo mode.", has_login=True))
    assert any("expired-subscription" in w for w in review_warnings(
        rules, "Demo account has an active subscription.", has_subscription=True))


def test_review_resolves_file_and_delimiters_before_inline(tmp_path, rules, capsys):
    meta = {**GOOD, "review_notes": "x" * 4001, "review_notes_file": "custom.md"}
    (tmp_path / "metadata.en-US.yaml").write_text(yaml.safe_dump(meta))
    (tmp_path / "custom.md").write_text("Ignored instructions\n---\n" + COMPLETE_NOTES + "\n---\n" + "x" * 5000)
    assert lm.main([str(tmp_path), "--json"]) == 0
    assert "MD-14" not in capsys.readouterr().out
    (tmp_path / "custom.md").unlink()
    assert lm.main([str(tmp_path)]) == 1
    assert "4001 bytes" in capsys.readouterr().out


def test_review_utf8_limit_and_default_file(tmp_path, rules):
    for text, error in [("é" * 2000, False), ("é" * 2001, True), ("", False)]:
        (tmp_path / "review-notes.md").write_text(text)
        f = lm.lint({**GOOD, "review_notes": COMPLETE_NOTES}, {}, rules, kit=tmp_path)
        assert any("limit 4000" in e for e in f.errors) is error
        f = lm.lint({**GOOD, "review_notes": text}, {}, rules)
        assert any("limit 4000" in e for e in f.errors) is error


def test_review_inapp_purchase_alone_does_not_require_expired_account(rules):
    warnings = review_warnings(rules, "Tested on iOS 26. All countries.", first_version=True,
                               has_login=False, review={"hardware": False, "external_services": []},
                               monetization={"iap": [{"type": "Non-Consumable"}]})
    assert warnings == []


def test_review_findings_never_echo_notes_or_private_password(tmp_path, capsys):
    secret = "unique-private-password"
    (tmp_path / "private.yaml").write_text(yaml.safe_dump({"demo": {"demo_password": secret}}))
    (tmp_path / "review-notes.md").write_text(secret + "é" * 2001)
    (tmp_path / "metadata.en-US.yaml").write_text(yaml.safe_dump(GOOD))
    assert lm.main([str(tmp_path), "--json"]) == 1
    assert secret not in capsys.readouterr().out


def test_review_notes_linted_once_per_kit(tmp_path, capsys):
    for loc in ("en-US", "de-DE", "fr-FR"):
        (tmp_path / f"metadata.{loc}.yaml").write_text(yaml.safe_dump({**GOOD, "review_notes": "See the app."}))
    lm.main([str(tmp_path), "--json"])
    assert capsys.readouterr().out.count("may be missing devices") == 1


def test_maintenance_update_needs_no_navigation(rules):
    f = lm.lint({**GOOD, "whats_new": "Bug fixes", "review_notes": "Fixed a crash on startup."}, {}, rules)
    assert not any("what changed" in w for w in f.warnings)
