# Copy and ASO: name, subtitle, keywords, description

Apple's own guidance is on the [product page](https://developer.apple.com/app-store/product-page/) and the
[version information](https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information) pages.
Everything below that isn't from those pages is labelled as practice.

## Where the indexed words live

Name, subtitle and keywords are the indexed text fields. Apple says the keywords shouldn't repeat the app or
company name, and that promotional text "doesn't affect your app's search ranking".
That gives the budget:

| Field | Budget | Use it for |
|---|---|---|
| Name (30) | brand plus 1–2 core terms | "Brand: core job". Keep it easy to spell (Apple) |
| Subtitle (30) | the main benefit in plain words | no "world's best app" (Apple) |
| Keywords (100 bytes) | every other search term, once | no word that is already in the name or subtitle (practice: Apple matches across fields, so a repeat wastes bytes) |
| Promotional text (170) | news, an offer, a seasonal hook | can change any time without review; not indexed |
| Description (4000) | conversion, not ranking | first sentence carries it; then a short feature list |

## Keyword field rules

**From Apple**
- Separate terms with commas and no spaces after them. Spaces inside a phrase are fine.
- Each term must be longer than 2 characters.
- Avoid plurals of words you already have, category names, the word "app", duplicates, and `#` or `@`.
- Never use trademarks, celebrity names, competitor apps or irrelevant terms. Improper keyword use "is a common reason for App Store rejections."

**Practice**
- Prefer single words over phrases. The store combines words across the name, subtitle and keyword fields.
- Spend the bytes on intent ("declutter", "storage") rather than on adjectives.
- Count **bytes**, not characters. Accented letters, CJK and emoji take 2–4 bytes each, so localized keyword fields fill up faster.

## Description shape (Apple)

- One concise paragraph, then a short list of the main features.
- No prices: pricing is already on the page and varies by region.
- Accolades go at the end, or in the promotional text.
- Plain text only. Changing the description needs a new version.

## Claims

Every factual claim in the copy has to be in `facts.yaml` `claims:`, and `lint_metadata.py` warns when one isn't.
Claims include: "on-device", "no account", "works offline", any number, any superlative ("fastest", "#1", "only").
2.3.1 and 2.3 make inaccurate marketing a rejection reason.

## Free plus in-app purchase

- If the copy says "free", it must also say what costs extra (2.3.2).
- Practice: "Free to use with ads; an optional in-app purchase removes them."

## Localization

- Apple says localize the description, keywords, screenshots and previews for each market. The app name can be translated too.
- Write keywords per market from that language's search terms. Never machine-translate the English list.
- Apple trademarks stay in English in every language ("App Store", "iPhone").
- Each locale gets its own `metadata.<locale>.yaml`. The lint runs on all of them.

## What's New (Apple)

- List changes in order of importance, add a call to action, and say so when feedback led to a fix.
- It has to describe new features clearly (2.3.12). Not used on version 1.0.
