# Copy and ASO: name, subtitle, keywords, description

Apple's own guidance is on the [product page](https://developer.apple.com/app-store/product-page/) and the
[version information](https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information) pages.
Everything below that isn't from those pages is labelled as practice. Re-read against the live product page and
App Review Guidelines (Last Updated June 8, 2026) on 2026-10-14.

## Where the indexed words live

Name, subtitle and keywords are the indexed text fields. Apple says the keywords shouldn't repeat the app or
company name, and that promotional text "doesn't affect your app's search ranking".
That gives the budget:

| Field | Budget | Use it for |
|---|---|---|
| Name (30) | brand plus 1–2 core terms | "Brand: core job". Simple, memorable, easy to spell, hints at what the app does; avoid generic terms and names close to existing apps (Apple) |
| Subtitle (30) | the main benefit in plain words | no "world's best app"; highlight features or typical uses. 2.3.7: no other apps' names, no unverifiable claims. Can only change with a new version (Apple) |
| Keywords (100 bytes) | every other search term, once | no word that is already in the name or subtitle (practice: Apple matches across fields, so a repeat wastes bytes) |
| Promotional text (170) | news, an offer, a seasonal hook | can change any time without review; not indexed |
| Description (4000) | conversion, not ranking | first sentence carries it; then a short feature list |

## Keyword field rules

**From Apple**
- Separate terms with commas and no spaces after them. Spaces inside a phrase are fine.
- Each term must be longer than 2 characters.
- Avoid plurals of words you already have, category names, the word "app", duplicates, and `#` or `@` (special characters "don't carry extra weight", unless they're part of the brand).
- Never use trademarks, celebrity names, competitor apps or irrelevant, inappropriate or offensive terms. Improper keyword use "is a common reason for App Store rejections."
- Promotional text "doesn't affect your app's search ranking so it should not be used to display keywords."
- Trade-off (Apple): popular functional terms ("jobs", "social") bring traffic but are highly competitive; rarer terms bring less traffic but rank more easily.

**Practice**
- Prefer single words over phrases. The store combines words across the name, subtitle and keyword fields.
- Spend the bytes on intent ("declutter", "storage") rather than on adjectives.
- Count **bytes**, not characters. Accented letters, CJK and emoji take 2–4 bytes each, so localized keyword fields fill up faster.

## Description shape (Apple)

- One concise paragraph, then a short list of the main features. Say what makes the app unique, in the brand's tone.
- The first sentence matters most: it's what people read without tapping "more".
- Don't add unnecessary keywords to the description to improve search.
- No prices: pricing is already on the page and varies by region.
- Accolades go at the end, or in the promotional text.
- Plain text only. Changing the description needs a new version; use promotional text for news in between.

## Apple product names in copy (marketing guidelines, read 2026-10-14)

Source: [Marketing guidelines](https://developer.apple.com/app-store/marketing/guidelines/).
- "Brand for iPhone and iPad", never "iPhone Brand". List only the Apple products the app runs on.
- Exact spelling and case: iPhone, iPad, Apple Watch, Apple Vision Pro, App Store. Never all caps, never plural, never translated.
- "Apple Vision Pro" can't be in the app name (it can be in the description). Say "spatial computing", not AR/VR/MR.
- Don't name iOS, macOS, watchOS or tvOS in marketing copy; don't call devices "smartphones" or "tablets".
- No ™/® symbols outside US-only communications, and never in headlines.

## Claims

Every factual claim in the copy has to be in `facts.yaml` `claims:`, and `lint_metadata.py` warns when one isn't.
Claims include: "on-device", "no account", "works offline", any number, any superlative ("fastest", "#1", "only").
2.3.1 and 2.3 make inaccurate marketing a rejection reason.

## Free plus in-app purchase

- If the copy says "free", it must also say what costs extra (2.3.2).
- Practice: "Free to use with ads; an optional in-app purchase removes them."
- Promoted in-app purchases (product page): up to 20 items across in-app purchases and subscriptions, order chosen by you; display name up to 35 and description up to 55 characters there (the kit keeps 30/45, see `apple-specs.md`).

## Localization

- Apple says localize the description, keywords, screenshots and previews for each market. The app name can be translated too.
- Write keywords per market from that language's search terms. Never machine-translate the English list.
- Apple (2026) now offers coding agents in Xcode for translating strings, and says machine translation must be checked by native speakers ([Localization](https://developer.apple.com/localization/)). The same applies to store text.
- Apple trademarks stay in English in every language ("App Store", "iPhone").
- Each locale gets its own `metadata.<locale>.yaml`. The lint runs on all of them.

## What's New (Apple)

- List changes in order of importance, add a call to action, and say so when feedback led to a fix. It shows on the product page and in the Updates tab.
- It has to describe new features clearly (2.3.12). Bug fixes, security and performance updates may use a generic line; significant changes must be listed. Not used on version 1.0.

## Ratings (Apple)

- `SKStoreReviewController` can prompt up to three times in 365 days; custom review prompts are disallowed (5.6.1).
- Replies to reviews: respectful, on point, no personal information, spam or marketing (5.6.1). Only the latest review and reply per user shows.

## Category (Apple)

- The primary category decides browsing, search filters and which tab the app appears in. An irrelevant category can cause rejection (product page; 2.3.5).
