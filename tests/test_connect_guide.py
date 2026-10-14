import re

import yaml

import connect_guide as cg

FACTS = {
    "app": {"name": "Pebble", "bundle_id": "com.example.pebble", "version": "1.0.0", "build": "3",
            "encryption_exempt": True},
    "first_version": True,
    "copyright": "2026 Example Ltd",
    "monetization": {"iap": [{"product_id": "com.example.pebble.pro", "type": "Non-Consumable",
                              "reference_name": "Pebble Pro", "price": "2.99 USD", "family_shareable": False}]},
}
META = {
    "name": "Pebble: Photo Cleaner",
    "subtitle": "Swipe to tidy your library",
    "promotional_text": "Sort a month of photos over a coffee.",
    "description": "Pebble helps you clear out your photo library.\n\n- Swipe left to delete\n- Swipe right to keep\n\n"
                   "Pebble is free with ads. An optional in-app purchase removes them.",
    "keywords": "declutter,storage,duplicates,camera roll,gallery",
    "support_url": "https://example.com/support",
    "marketing_url": "https://example.com",
    "privacy_policy_url": "https://example.com/privacy",
    "category": {"primary": "Photo & Video", "secondary": "Utilities"},
    "copyright": "2026 Example Ltd",
    "iap": [{"product_id": "com.example.pebble.pro", "display_name": "Pebble Pro", "description": "No ads, ever"}],
}
CONNECT = {
    "sku": "pebble-ios-1",
    "review_contact": {"first_name": "Ada", "last_name": "Example", "email": "ada@example.com"},
    "dsa": {"answer": "the owner decides", "judgement": True, "why": "Trader status shows contact details in the EU."},
    "age_rating": {"advertising": {"answer": True, "judgement": True, "why": "ads"}, "contests": "None"},
    "version": {"release": "manual"},
}
NOTES = "# Review notes\n\nIntro text.\n\n---\n\nPebble has sample photos.\nTap Try samples.\n\n---\n\n## Checks\n"
PRIVACY = """# App Privacy

## Answer: "Do you or your third-party partners collect data from this app?" → **Yes**

| Apple data type | Purposes | Linked to the user | Used for tracking | Who |
|---|---|---|---|---|
| Identifiers › **Device ID** | Third-Party Advertising, Analytics | **Yes** | **Yes** | Google |
| Diagnostics › **Crash Data** | Analytics | No, per the manifests (see conflict 2) | No | Google |
"""


def make_kit(tmp_path, private=None, **over):
    (tmp_path / "facts.yaml").write_text(yaml.safe_dump(FACTS))
    (tmp_path / "metadata.en-US.yaml").write_text(yaml.safe_dump({**META, **over}, allow_unicode=True))
    (tmp_path / "connect.yaml").write_text(yaml.safe_dump(CONNECT))
    (tmp_path / "review-notes.md").write_text(NOTES)
    (tmp_path / "privacy-labels.md").write_text(PRIVACY)
    if private:
        (tmp_path / "private.yaml").write_text(yaml.safe_dump(private))
    return tmp_path


def copy_blocks(md):
    """Map each copy field's label to the text inside its code block."""
    out = {}
    for m in re.finditer(r"^(?:✋ )?\*\*([^*\n]+)\*\* → type exactly[^\n]*:\n\n(`{3,})text\n(.*?)\n\2\n", md, re.S | re.M):
        out.setdefault(m.group(1), []).append(m.group(3))
    return out


def all_fields(guide):
    return [f for s in guide["sections"] for st in s.steps for f in st.fields]


def test_every_field_is_under_its_limit(tmp_path, rules):
    g = cg.build(make_kit(tmp_path), None, rules)
    limited = [f for f in all_fields(g) if f.count()]
    assert {f.label for f in limited} >= {"Name", "Subtitle", "Promotional Text", "Description", "Keywords",
                                          "Notes", "Display Name", "Reference Name", "Product ID"}
    for f in limited:
        n, mx, unit, mn = f.count()
        assert n <= mx and (not mn or n >= mn), f"{f.label}: {n}/{mx} {unit}"
    assert g["problems"] == []
    assert cg.main([str(tmp_path)]) == 0


def test_over_limit_is_reported_and_fails(tmp_path, rules):
    kit = make_kit(tmp_path, name="N" * 31, keywords="ü" * 51)
    g = cg.build(kit, None, rules)
    assert any("Name is 31 chars, limit 30" in p for p in g["problems"])
    assert any("Keywords is 102 bytes, limit 100" in p for p in g["problems"])
    md = cg.render_md(g)
    assert "31/30 characters ⛔ over the limit" in md
    assert cg.main([str(kit)]) == 1


def test_copy_blocks_match_the_metadata_exactly(tmp_path, rules):
    kit = make_kit(tmp_path)
    cg.main([str(kit)])
    blocks = copy_blocks((kit / "CONNECT-GUIDE.md").read_text())
    expect = {
        "Name": META["name"], "Subtitle": META["subtitle"], "Promotional Text": META["promotional_text"],
        "Keywords": META["keywords"], "Support URL": META["support_url"],
        "Marketing URL": META["marketing_url"], "Privacy Policy URL": META["privacy_policy_url"],
        "Copyright": META["copyright"], "Display Name": META["iap"][0]["display_name"],
        "SKU": CONNECT["sku"], "Product ID": "com.example.pebble.pro",
        "Notes": "Pebble has sample photos.\nTap Try samples.",
    }
    for label, value in expect.items():
        assert label in blocks, label
        assert all(b == value for b in blocks[label]), (label, blocks[label])
    # The app and the IAP both have a "Description": exactly those two texts, nothing else.
    assert sorted(blocks["Description"]) == sorted([META["description"], META["iap"][0]["description"]])
    # The HTML carries the same texts, escaped, inside <pre>.
    page = (kit / "connect-guide.html").read_text()
    pres = [cg.html.unescape(p) for p in re.findall(r"<pre>(.*?)</pre>", page, re.S)]
    for value in (META["description"], META["keywords"], META["name"], "Pebble has sample photos.\nTap Try samples."):
        assert value in pres


def test_missing_private_yaml_gives_placeholder_and_no_private_file(tmp_path):
    kit = make_kit(tmp_path)
    assert cg.main([str(kit)]) == 0
    md = (kit / "CONNECT-GUIDE.md").read_text()
    assert "your phone number" in md
    assert not (kit / "connect-guide.private.html").exists()


def test_private_yaml_only_reaches_the_private_html(tmp_path):
    phone = "+15550100999"
    kit = make_kit(tmp_path, private={"review_contact": {"phone": phone}})
    assert cg.main([str(kit)]) == 0
    assert phone not in (kit / "CONNECT-GUIDE.md").read_text()
    assert phone not in (kit / "connect-guide.html").read_text()
    assert "your phone number" in (kit / "CONNECT-GUIDE.md").read_text()
    assert phone in (kit / "connect-guide.private.html").read_text()
    cg.main([str(kit), "--no-private"])  # still writes the public files, never touches private data
    assert phone not in (kit / "connect-guide.html").read_text()


def test_judgement_and_approval_marks(tmp_path, rules):
    g = cg.build(make_kit(tmp_path), None, rules)
    md = cg.render_md(g)
    assert "✋ **Capabilities › Advertising** → Yes" in md
    assert "✋ **Digital Services Act › Complete Compliance Requirements** → the owner decides" in md
    # unanswered age-rating items are asked, not guessed
    assert "✋ **Violence › Realistic Violence** → decide" in md
    # privacy doubt from privacy-labels.md becomes a ✋ on that one answer
    assert "✋ **Linked to the user's identity?** → No" in md
    approvals = [st.title for s in g["sections"] for st in s.steps if st.approval]
    assert len(approvals) == 4 and any("upload" in t.lower() for t in approvals)
    assert any("Submit" in t for t in approvals) and any("Release" in t for t in approvals)
    assert "In-App Purchases" in approvals  # the first purchase's Add for Review (moved off the version page)


def test_screens_come_in_visiting_order(tmp_path, rules):
    titles = [s.title for s in cg.build(make_kit(tmp_path), None, rules)["sections"]]
    order = ["Before you start", "Create the app record", "App Information", "Pricing and Availability",
             "In-App Purchases", "App Privacy", "Upload the build", "The version page", "Submit for review", "Release"]
    idx = [next(i for i, t in enumerate(titles) if t.startswith(o)) for o in order]
    assert idx == sorted(idx)


def test_html_has_a_copy_button_per_copy_field_and_a_checkbox_per_step(tmp_path, rules):
    kit = make_kit(tmp_path)
    cg.main([str(kit)])
    g = cg.build(kit, None, rules)
    page = (kit / "connect-guide.html").read_text()
    copies = sum(f.kind == "copy" for f in all_fields(g))
    steps = sum(len(s.steps) for s in g["sections"])
    assert page.count('<button class="copy"') == copies
    assert page.count('type="checkbox" data-step=') == steps
    assert "http" not in re.sub(r'https://example\.com[^"<\s]*', "", page.split("<script>")[0]).replace(
        "http-equiv", ""), "page must be self-contained"


# ---------------------------------------------------------------------------------------------------- progress
IAP_TOP = "iap/pebble-pro-top-of-the-page"
TEXT = "version/product-page-text"
NEW_APP = "new-app/fill-in-the-new-app-dialog"


def write_progress(kit, steps):
    (kit / cg.PROGRESS_FILE).write_text(yaml.safe_dump({"steps": steps}, allow_unicode=True))


def test_step_keys_are_stable_and_unique(tmp_path, rules):
    g = cg.build(make_kit(tmp_path), None, rules)
    keys = [st.key for s in g["sections"] for st in s.steps]
    assert len(keys) == len(set(keys))
    assert {IAP_TOP, TEXT, NEW_APP, "build/upload"} <= set(keys)


def test_progress_ticks_done_steps_in_md_and_html(tmp_path):
    kit = make_kit(tmp_path)
    write_progress(kit, {NEW_APP: {"status": "done-by-owner", "date": "2026-10-14"},
                         IAP_TOP: {"status": "done-by-claude", "date": "2026-10-15",
                                   "live": {"Family Sharing": "Off", "Price Schedule › Price": "2.99 USD"}},
                         "release/release-this-version": {"status": "todo"}})
    assert cg.main([str(kit)]) == 0
    md = (kit / "CONNECT-GUIDE.md").read_text()
    assert re.search(r"^### \[x\] 2\.1 Fill in the New App dialog · done by owner 2026-10-14$", md, re.M)
    assert re.search(r"^### \[x\] \d+\.\d+ Pebble Pro: top of the page · done by Claude 2026-10-15$", md, re.M)
    assert re.search(r"^### \[ \] \d+\.\d+ Release This Version", md, re.M)
    assert "2 of" in md and "needs update" not in md.split("## 1.")[1]
    page = (kit / "connect-guide.html").read_text()
    assert re.search(rf'data-step="{NEW_APP}" checked', page)
    assert re.search(rf'data-step="{IAP_TOP}" checked', page)
    assert 'data-step="release/release-this-version" aria' in page  # todo: not checked
    assert "done by owner 2026-10-14" in page and "done by Claude 2026-10-15" in page
    assert "stay in this browser only" in page


def test_check_flags_changed_description_and_price(tmp_path, capsys):
    kit = make_kit(tmp_path)
    write_progress(kit, {
        TEXT: {"status": "done-by-owner", "date": "2026-10-14",
               "live": {"Description": META["description"], "Keywords": META["keywords"]}},
        IAP_TOP: {"status": "done-by-owner", "date": "2026-10-14",
                  "live": {"Price Schedule › Price": "2.99 USD", "Family Sharing": "Off",
                           "Price Schedule › + (Base Country or Region)": "United States (USD)"}}})
    assert cg.main([str(kit), "--check"]) == 0  # nothing changed yet
    assert "every recorded live value matches" in capsys.readouterr().out
    facts = yaml.safe_load((kit / "facts.yaml").read_text())
    facts["monetization"]["iap"][0]["price"] = "3.99 USD"
    (kit / "facts.yaml").write_text(yaml.safe_dump(facts))
    new_desc = "Pebble clears out your photo library, one swipe at a time."
    (kit / "metadata.en-US.yaml").write_text(yaml.safe_dump({**META, "description": new_desc}, allow_unicode=True))
    assert cg.main([str(kit), "--check"]) == 1
    out = capsys.readouterr().out
    assert f"needs update: {TEXT}" in out and f"needs update: {IAP_TOP}" in out
    assert "Price Schedule › Price: 2.99 USD → 3.99 USD" in out
    assert "Description: Pebble helps you clear out" in out and "→ Pebble clears out" in out
    assert "Keywords" not in out and "Family Sharing" not in out and "Base Country" not in out
    md = (kit / "CONNECT-GUIDE.md").read_text()
    assert "⚠️ needs update" in md and "- Price Schedule › Price: `2.99 USD` → `3.99 USD`" in md
    page = (kit / "connect-guide.html").read_text()
    assert "Needs update (live page → kit now)" in page and "<code>3.99 USD</code>" in page


def test_missing_progress_file_works(tmp_path, capsys):
    kit = make_kit(tmp_path)
    assert cg.main([str(kit), "--check"]) == 0
    out = capsys.readouterr().out
    assert "no connect-progress.yaml" in out
    md = (kit / "CONNECT-GUIDE.md").read_text()
    assert "Progress: none recorded yet" in md and "[x]" not in md
    assert ' checked' not in (kit / "connect-guide.html").read_text()


def test_init_progress_lists_every_step_and_keeps_entries(tmp_path, rules):
    kit = make_kit(tmp_path)
    write_progress(kit, {NEW_APP: {"status": "done-by-owner", "date": "2026-10-14"}})
    assert cg.main([str(kit), "--init-progress"]) == 0
    prog = yaml.safe_load((kit / cg.PROGRESS_FILE).read_text())["steps"]
    g = cg.build(kit, None, rules)
    assert list(prog) == [st.key for s in g["sections"] for st in s.steps]
    assert prog[NEW_APP]["status"] == "done-by-owner"
    assert all(v["status"] == "todo" for k, v in prog.items() if k != NEW_APP)


def test_private_phone_in_progress_live_values_is_masked_in_public_outputs(tmp_path, capsys):
    phone = "+15550100999"
    kit = make_kit(tmp_path, private={"review_contact": {"phone": phone}})
    review = "version/app-review-information"
    write_progress(kit, {review: {"status": "done-by-owner", "date": "2026-10-14",
                                  "live": {"Contact › Phone number": "+1 555 010 0999",
                                           "Contact › Email": "old@example.com"},
                                  "note": f"phone on the page was {phone}"}})
    cg.main([str(kit), "--check"])
    out, err = capsys.readouterr()
    for name in ("CONNECT-GUIDE.md", "connect-guide.html"):
        text = (kit / name).read_text()
        assert phone not in text and "5550100999" not in text and "555 010 0999" not in text, name
        assert "[private]" in text
    assert phone not in out and "555 010 0999" not in out
    assert "contains a private.yaml value" in err
    # the email changed, so the step still needs update; the phone matches private.yaml so isn't flagged
    md = (kit / "CONNECT-GUIDE.md").read_text()
    assert "Contact › Email: `old@example.com` → `ada@example.com`" in md
    assert "Contact › Phone number:" not in md.split("Needs update")[1].split("###")[0]
    assert phone in (kit / "connect-guide.private.html").read_text()


def test_choose_fields_tolerate_live_wording(tmp_path):
    f = cg.Field("Availability", "All countries or regions (the same as the app)", "choose")
    assert f.matches("All countries or regions selected")
    assert cg.Field("Base", "United States", "choose").matches("United States (USD)")
    assert cg.Field("Price", "4.99 USD", "choose").matches("2.99 USD") is False
    assert cg.Field("Name", "Pebble", "copy").matches("Pebble (old)") is False
    assert cg.Field("Build › +", "1.0.0 (22)", "choose").matches("1.0.0 (18)") is False


def test_header_and_search_results_step_lists_the_creative_files(tmp_path, rules):
    kit = make_kit(tmp_path)
    (kit / "creative/en-US").mkdir(parents=True)
    (kit / "creative/en-US/universal.png").write_bytes(b"x")
    (kit / "creative/en-US/search.png").write_bytes(b"x")
    g = cg.build(kit, None, rules)
    st = next(st for s in g["sections"] for st in s.steps if st.title == "Header and Search Results")
    assert st.key == "version/header-and-search-results"
    assert [(f.label, f.value) for f in st.fields] == [("Header tab › Upload", "creative/en-US/universal.png"),
                                                       ("Search Results tab › Upload", "creative/en-US/search.png")]
