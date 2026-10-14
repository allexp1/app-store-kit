# Growth and marketing: custom product pages, product page optimization, in-app events, Asset Library, promo and offer codes

App Store Connect's sidebar group **Growth & Marketing** holds: In-App Events, Custom Product Pages, Asset Library,
Product Page Optimization, Promo Codes and Game Center. This file covers what each one is, when it helps, its
limits, whether it works before launch, how it is reviewed, and what the API can do.

All facts were read on 2026-10-14 from Apple's own pages, with each source given. API shapes come from the
App Store Connect API 4.5.1 OpenAPI spec (`info.version` 4.5.1, file dated 2026-10-06) and its doc JSON pages.
**UNCONFIRMED** marks anything Apple's pages don't settle.

Kit side: `KIT/growth.yaml` (template `templates/growth.example.yaml`), read by `scripts/growth.py`. API side:
`asc_sync.py plan|apply KIT --only growth`, `submit KIT --growth IDS --yes` and `release KIT --start-test ID --yes`.
The guide steps are keyed `growth/<id>` (connect_guide.py). The images are checked by `validate_kit.py`.

**Sources** (read 2026-10-14):
- [CPP-mkt] https://developer.apple.com/app-store/custom-product-pages/
- [CPP-help] https://developer.apple.com/help/app-store-connect/create-custom-product-pages/configure-multiple-product-page-versions
- [CPP-submit] https://developer.apple.com/help/app-store-connect/manage-submissions-to-app-review/submit-a-custom-product-page
- [PPO-mkt] https://developer.apple.com/app-store/product-page-optimization/
- [PPO-ov] https://developer.apple.com/help/app-store-connect/create-product-page-optimization-tests/overview-of-product-page-optimization
- [PPO-create] https://developer.apple.com/help/app-store-connect/create-product-page-optimization-tests/create-a-test
- [PPO-treat] https://developer.apple.com/help/app-store-connect/create-product-page-optimization-tests/configure-test-treatments
- [PPO-run] https://developer.apple.com/help/app-store-connect/create-product-page-optimization-tests/run-a-test
- [IAE-mkt] https://developer.apple.com/app-store/in-app-events/
- [IAE-offer] https://developer.apple.com/help/app-store-connect/offer-in-app-events/offer-in-app-events
- [IAE-manage] https://developer.apple.com/help/app-store-connect/offer-in-app-events/manage-events
- [IAE-submit] https://developer.apple.com/help/app-store-connect/manage-submissions-to-app-review/submit-an-in-app-event
- [IAE-badges] https://developer.apple.com/help/app-store-connect/reference/in-app-events/in-app-event-badges
- [IAE-media] https://developer.apple.com/help/app-store-connect/reference/in-app-events/in-app-event-media-and-audio-specifications
- [AL-manage] https://developer.apple.com/help/app-store-connect/manage-app-information/manage-your-app-store-assets
- [AL-submit] https://developer.apple.com/help/app-store-connect/manage-submissions-to-app-review/submit-assets-from-asset-library
- [AL-status] https://developer.apple.com/help/app-store-connect/reference/app-information/app-store-asset-statuses
- [CA-spec] https://developer.apple.com/help/app-store-connect/reference/app-information/creative-assets-specifications
- [ABP] https://developer.apple.com/app-store/asset-best-practices/
- [PROMO] https://developer.apple.com/help/app-store-connect/offer-promo-codes/request-and-manage-promo-codes
- [NEWS-1025] https://developer.apple.com/news/?id=gf6mgrs6 (October 29, 2025)
- [OC-IAP] https://developer.apple.com/help/app-store-connect/manage-in-app-purchases/create-offer-codes-for-in-app-purchases
- [OC-SUB] https://developer.apple.com/help/app-store-connect/manage-subscriptions/set-up-subscription-offer-codes
- [API] https://developer.apple.com/sample-code/app-store-connect/app-store-connect-openapi-specification.zip and
  `https://developer.apple.com/tutorials/data/documentation/appstoreconnectapi/<page>.json`

---

## 0. Before launch vs after launch (read this first)

Nothing here goes live before the app has an approved version. Until then, items can only ride along with the
first version's submission.

| Tool | Before the first approval | After launch | Source |
|---|---|---|---|
| Custom product pages | Creating one needs "the Ready for Distribution status in at least one country or region" [CPP-help]. But [CPP-submit] says an unapproved app can "include the custom product page in the same submission as your first iOS app version". The pages disagree (**UNCONFIRMED** which one wins). **The kit waits for launch**, and the plan adds an optional browser check. | Submit with or without a version | CPP-help, CPP-submit |
| Product page optimization | **Not available.** "Your app must be in the Ready for Distribution state to test its product page" [PPO-ov]; the app must be "live on the App Store" [PPO-create]. | One test at a time | PPO-ov, PPO-create |
| In-app events | **Can be prepared now.** "If … your app hasn't been approved yet, include the In-App Event in the same submission as your first iOS app version." | Submit with or without a version | IAE-submit |
| Asset Library | Upload any time; assets wait in Prepare for Submission. Before the first approval they are reviewed with the first version. | Standalone assets can be submitted without a version | AL-submit, AL-status |
| Promo codes (free app downloads) | Not stated. Codes can't be made when the app is removed from sale everywhere, so in practice the app must be on sale somewhere (inference). | 100 per version per platform | PROMO |
| Offer codes (IAP and subscriptions) | Offers can be created "regardless of your app's current App Status". Generating one-time-use or custom codes needs the app Ready for Distribution and the purchase approved. | Yes | OC-IAP |

**For Swipr (not released yet, 2026-10-14):** prepare custom product pages and a first test in `growth.yaml` now.
Only an in-app event could go in with 1.0, and only if a real timed event is planned. Plan the pages and the test
right after launch.

---

## 1. Custom product pages

**What it is.** Extra versions of the product page, each with its own URL (`…?ppid=<id>`). Each one "can include
different screenshots, previews, promotional text, and keywords, and is localizable and shareable through a
unique URL" [CPP-help]. A page can also carry a deep link and its own header and search-results assets ([ABP],
[AL-manage]; exactly how the header is placed on a page in the browser is **UNCONFIRMED**). The **icon can't
change per page**. Pages appear in Apple Ads, StoreKit ads (`customProductPageIdentifier`), editorial and search
results [CPP-mkt].

**When it helps.**
- One page per audience or per keyword theme. Its first screenshot and header show what that audience searched
  for (e.g. Swipr: "free up storage", "delete duplicates", "screenshots clutter").
- Pages linked from ads, a website or a newsletter that talk about one feature.

**Limits.**
- Up to **70 pages** per app [CPP-help]. The limit was 35 until October 29, 2025 [NEWS-1025].
- Shown on iOS / iPadOS 15 and later. Deep links work on iOS / iPadOS 18 and later [CPP-help].
- Promotional text: 170 characters, as on the default page.
- No published limit for the reference name or the number of keywords (**UNCONFIRMED**).
- Analytics appear after 5 first-time downloads [CPP-help].

**Keywords.**
- "You can assign keywords from your latest approved app version to a custom product page", per language.
- A page is searchable for them "only after it's approved and set to visible".
- Pick "a unique set of keywords for each page" [CPP-help]: each keyword combination belongs to one page [CPP-mkt].
- Without keywords, a page is reached only through its link.

**Deep links.**
- A universal link or a custom URL, with no URL shorteners.
- "Your app deep link must be approved before it'll function": submit the page after adding one [CPP-help].

**Review.**
- Pages, and their deep links, are reviewed before they're visible, "together with your latest iOS version".
- A page's media, promotional text and keywords are locked while it is in review [CPP-submit].
- To change a live page you create a new version (Create New Version). The URL stays the same, and the change goes
  live once approved [CPP-help].

**API** (4.5.1). The kit uses all of this.

| Action | Request |
|---|---|
| List | `GET /v1/apps/{id}/appCustomProductPages`; `GET /v1/appCustomProductPages/{id}/appCustomProductPageVersions` (state: PREPARE_FOR_SUBMISSION, READY_FOR_REVIEW, WAITING_FOR_REVIEW, IN_REVIEW, ACCEPTED, APPROVED, REPLACED_WITH_NEW_VERSION, REJECTED) |
| Create | `POST /v1/appCustomProductPages` with `attributes.name`, relationships `app`, optional `appStoreVersionTemplate` (copies a version's media) or `customProductPageTemplate`, and `appCustomProductPageVersions: [{id: "${new-version}"}]` plus `included` with the inline version (`deepLink`) and localization (`locale`, `promotionalText`). This is Apple's own example. |
| Page | `PATCH /v1/appCustomProductPages/{id}` `{name, visible}` |
| New version of an approved page | `POST /v1/appCustomProductPageVersions` `{deepLink?}`, relationship `appCustomProductPage`. There is no DELETE. Whether Apple copies the old localizations and placements into it is **UNCONFIRMED**; the kit re-reads and fills in what's missing. |
| Text | `POST /v1/appCustomProductPageLocalizations` `{locale, promotionalText}`, relationship `appCustomProductPageVersion`. PATCH changes only `promotionalText`. |
| Keywords | `POST` / `DELETE /v1/appCustomProductPageLocalizations/{id}/relationships/searchKeywords` `{"data": [{"type": "appKeywords", "id": …}]}`. The app's keyword ids come from `GET /v1/apps/{id}/searchKeywords?filter[locale]=…`. An `appKeywords` object has no attributes; **UNCONFIRMED** whether its id is the keyword text (the kit assumes so and warns when a keyword isn't found). |
| Media | Asset Library placements with relationship `appCustomProductPageLocalization` (screenshots, previews, header, search results), ordered with `appAssetLibraryPlacementOrderingRequests`. A placement on an approved version returns 409 `STATE_ERROR.INVALID_STATE`. The old `appScreenshotSets` route is deprecated. |
| Review | `reviewSubmissionItems` relationship `appCustomProductPageVersion` |

**Rules.**
- The same rules as the default page: guideline 2.3, no prices, no other platforms, and 4+ imagery [ABP].
- The screenshots must show the real app.
- Don't use a page to promise a feature the app lacks.

---

## 2. Product page optimization (A/B tests of the default page)

**What it is.** Up to three treatments of the default product page, shown to a share of visitors. Each treatment
can change the **app icon** (an alternate icon already in the binary), the **header and search-results assets**,
and the **screenshots and previews**; anything left alone falls back to the original [PPO-treat].

**When it helps.** Once the app has steady traffic. Test one idea at a time, and test the first thing people see:
- the first screenshot (e.g. Swipr: the swipe in motion vs the screen at rest);
- the header asset;
- the icon (only if an alternate icon is already in the live binary).

**Limits.**
- One test at a time, up to 3 treatments, up to 90 days [PPO-mkt].
- A started test can't be changed, and a stopped test can't be restarted [PPO-mkt, PPO-run].
- Traffic is split evenly: 30 % across 3 treatments means 10 % each [PPO-create].
- Results appear after 5 first-time downloads. Apple suggests waiting for at least 90 % confidence before applying a
  treatment; applying one ends the test [PPO-mkt].
- Not available for custom product pages, Apple Watch or iMessage [PPO-ov].
- Shown on iOS / iPadOS 15 and later.
- Releasing a new version during a test may skew it [PPO-ov].
- **Alternate icons**: "must be part of the app binary for the current App Store version", built with Xcode 13 or
  later, at 1024 × 1024 [PPO-treat]. Every variant must be in the published binary [PPO-mkt].

**Review.**
- New treatment media is reviewed before the test can start.
- Tests without alternate icons "can be submitted for review independent of a new app version" [PPO-mkt].
- Reordering existing screenshots, or changing only the icon, needs no new review [PPO-treat].

**API** (4.5.1; the v1 experiments endpoints are deprecated).

| Action | Request |
|---|---|
| List | `GET /v1/apps/{id}/appStoreVersionExperimentsV2` (state: PREPARE_FOR_SUBMISSION, READY_FOR_REVIEW, WAITING_FOR_REVIEW, IN_REVIEW, ACCEPTED, APPROVED, REJECTED, COMPLETED, STOPPED) |
| Create | `POST /v2/appStoreVersionExperiments` type `appStoreVersionExperiments`, `{name, platform: "IOS", trafficProportion}` (all required), relationship `app`. A second draft returns 409 `STATE_ERROR` ("another experiment is in draft state"). |
| Change, start | `PATCH /v2/appStoreVersionExperiments/{id}` `{name, trafficProportion, started}`. There is no stop attribute in v2. |
| Treatment | `POST /v1/appStoreVersionExperimentTreatments` `{name, appIconName?}`, relationship `appStoreVersionExperimentV2` (type `appStoreVersionExperiments`) |
| Treatment language | `POST /v1/appStoreVersionExperimentTreatmentLocalizations` `{locale}` (no PATCH), relationship `appStoreVersionExperimentTreatment`; its media are placements with relationship `appStoreVersionExperimentTreatmentLocalization` |
| Review | `reviewSubmissionItems` relationship `appStoreVersionExperimentV2` |
| Apply the winner | `POST /v1/appStoreVersionPromotions` (relationships `appStoreVersion` and `appStoreVersionExperimentTreatment`). The kit leaves this to the owner in the browser. |

---

## 3. In-app events

**What it is.** A timed happening inside the app (a challenge, a premiere, a live event, a major update). It
appears as an event card on the product page, in search and in editorial, with a details page and a deep link.
Shown on iOS / iPadOS 15 and later [IAE-mkt].

**When it helps.**
- Only for a **real, timed** happening that brings new content, features or goods (e.g. Swipr: "Spring Clean
  Week", a one-week challenge with a real in-app goal).
- Not for "Repetitive activities such as daily tasks or rewards", "Price promotions that don't introduce any new
  content, features, or goods", or "General promotions that raise awareness about your app or game" [IAE-mkt].

**Limits** [IAE-offer, IAE-mkt].

| Item | Limit |
|---|---|
| Events at a time | Up to 10 published at a time; up to 15 approved per app; up to 10 with overlapping start times (approved or draft) |
| Length | At least 15 minutes; the end at most 31 days after the start |
| Publish date | At most 14 days before the start |
| Region start dates | Within 48 hours of each other |
| Reference name | 64 characters, unique |
| Event name | 30 characters (title case) |
| Short description | 50 characters (sentence case; on the card) |
| Long description | 120 characters (on the details page) |

- **Badges:** Challenge, Competition, Live Event, Major Update, New Season, Premiere, Special Event [IAE-badges].
  API enum: `LIVE_EVENT PREMIERE CHALLENGE COMPETITION NEW_SEASON MAJOR_UPDATE SPECIAL_EVENT`.
- **Purpose** (personalisation only): `APPROPRIATE_FOR_ALL_USERS ATTRACT_NEW_USERS KEEP_ACTIVE_USERS_INFORMED
  BRING_BACK_LAPSED_USERS`.
- **Priority:** `HIGH` events are listed before `NORMAL` ones.
- **In-App Purchase required** is a flag; subscription apps set it only when the event itself costs extra. In the API
  it is the free string `purchaseRequirement`; its values are **UNCONFIRMED**.
- **Media** [IAE-media, CA-spec]:

  | Placement | Size | Formats |
  |---|---|---|
  | Event card | 16:9, 1920 × 1080 to 3840 × 2160 | Image: JPEG or PNG. Video: .mov / .m4v / .mp4 at 30 or 60 fps, 15–30 s ([CA-spec]; [IAE-media] gives no length), 500 MB at most |
  | Details page | 9:16, 1080 × 1920 to 2160 × 3840 | Same as the card |

  Apple adds the crops and gradients itself: no borders, no gradients, and avoid text and logos.

**Rules** [IAE-mkt].
- "Including specific pricing will lead to rejection by App Review."
- No all-caps text and no multiple exclamation points.
- No unverifiable claims ("the best", "#1") and no filler words such as "game event".
- The name is the event's real name, not a call to action.
- The description doesn't promote the app or its services.

**Editing** [IAE-manage].
- Before publication: regions, priority, and the start, end and publish dates (when they are in the future).
- After publication: only the start and end dates.
- After the event starts: only the end date.
- Draft, Archived or Approved events can be deleted. The kit never deletes.
- Since October 2025, events can be submitted while an app version is in review [NEWS-1025].

**API** (4.5.1).

| Action | Request |
|---|---|
| Event | `POST /v1/appEvents` `{referenceName*, badge, deepLink, purchaseRequirement, primaryLocale, priority, purpose, territorySchedules: [{territories, publishStart, eventStart, eventEnd}]}`, relationship `app`; `PATCH /v1/appEvents/{id}`. The state is `eventState`: DRAFT, READY_FOR_REVIEW, WAITING_FOR_REVIEW, IN_REVIEW, REJECTED, ACCEPTED, APPROVED, PUBLISHED, PAST, ARCHIVED. |
| Language | `POST /v1/appEventLocalizations` `{locale, name, shortDescription, longDescription}`, relationship `appEvent`; `GET /v1/appEvents/{id}/localizations` |
| Media | Asset Library placements `EVENT_CARD_ASSET` / `EVENT_DETAILS_PAGE_ASSET` with relationship `appEventLocalization`; category from ref data (CREATIVE_ASSETS); one asset per placement type, **not orderable**. `appEventScreenshots` / `appEventVideoClips` are deprecated in 4.5.1. |
| Review | `reviewSubmissionItems` relationship `appEvent` |

---

## 4. Asset Library (new in App Store Connect, 2026)

**What it is.** "Use Asset Library to submit and manage your app's images and videos across platforms, sizes,
and placements, including app previews, screenshots, and custom creative assets like the product page header and
in-app event cards" [AL-manage]. Approved assets can be reused on the product page, custom product pages, tests
and events through "Browse Assets", with no new review [CPP-help, PPO-treat, IAE-offer].

**Creative assets.**
- Header and search-results assets show on iOS / iPadOS 27 and later.
- Sizes are in `references/creative-assets.md`.
- With no search asset, App Store search shows events, previews and screenshots [ABP].

**Review.**
- Assets "submit on their own, independent of an app version" once the app has an approved version. Before that
  they go with the first version [AL-submit].
- Standalone assets are "reviewed against your app's latest version" [AL-manage].
- Assets placed on a version, page, test or event are reviewed with it and "can't [be submitted] separately"
  [AL-submit].
- On a live version, the header or search asset can be swapped for an approved one with **Publish**, without a new
  version [AL-manage]. This is browser-only; whether the API can do it is **UNCONFIRMED**.
- An asset can be deleted only in Prepare for Submission [AL-manage].

**Roles.** Account Holder, Admin, App Manager or Marketing manage assets. Submitting from the library needs Account
Holder, Admin or App Manager [AL-manage, AL-submit].

**API.**
- The kit uses the Asset Library for everything: `upload_library_asset` + `place_slot` in `asc_sync.py`, with
  placements on any of the four parents.
- Standalone asset review is `reviewSubmissionItems` `appAssetLibraryImage` / `appAssetLibraryVideo` (not used by the
  kit).
- Placement limits per feature (`CUSTOM_PRODUCT_PAGES`, `PRODUCT_PAGE_OPTIMIZATIONS`, `IN_APP_EVENTS`) come from
  `appAssetLibraryRefData` `features[].placementPolicies[].groupLimits[].maxCount`. Their live values are **UNCONFIRMED**
  until the first read-only run with the key.

**Rules** [ABP].
- No prices, discounts, URLs or ©.
- No other platforms or stores.
- No Apple awards.
- 4+ imagery.
- Key content inside the safe area.
- Guideline 2.3.

---

## 5. Promo codes

- Free downloads of the app: "up to 100 promo codes per version of each platform your app supports". Each code is
  valid for four weeks and can be used once. People who redeem a code can't rate or review the app [PROMO].
- **Promo codes for In-App Purchases ended:** "Starting March 26, 2026, you'll no longer be able to create promo
  codes for In-App Purchases". Use offer codes instead [NEWS-1025].
- **No API** (none in the 4.5.1 spec): browser only, under Growth & Marketing › Promo Codes. The kit doesn't
  automate it. Ask the owner how many codes they want, and for whom (press, reviewers, testers outside
  TestFlight).

## 6. Offer codes (IAP and subscriptions)

- They now work for every In-App Purchase type [NEWS-1025, OC-IAP].
- **Limits:**
  - 1 million codes per app per quarter.
  - 10 active offers per app (IAP) or per subscription.
  - One-time-use codes come in batches of 500 to 25,000.
  - A custom code is up to 64 characters and can be redeemed up to 25,000 times.
  - Codes expire after at most 6 months.
  - An offer can't be edited after it is created [OC-IAP, OC-SUB].
- **Eligibility (IAP):** never purchased, purchased in the last 30 days, or purchased more than 30 days ago.
- **API:**
  - IAP: `POST /v1/inAppPurchaseOfferCodes` `{name, customerEligibilities: NON_SPENDER|ACTIVE_SPENDER|CHURNED_SPENDER}`
    with `prices` in `included`, then `POST /v1/inAppPurchaseOfferCodeOneTimeUseCodes` or `…CustomCodes`.
  - Subscriptions: the `subscriptionOfferCodes` equivalents.
  - The kit doesn't automate these yet. Offers are permanent and cost money, so do them in the browser with the
    owner, or add them later with their own plan and yes.

## 7. Recipes (how to choose)

1. **Before launch:** write `growth.yaml` with 2–4 custom product pages and one test idea, plus their screenshots.
   Don't plan an event unless a real one is dated.
2. **Custom product pages, one per intent:**
   - Pick the audience or keyword theme: what they searched or which ad they clicked.
   - The first screenshot and the header answer that intent in a few words.
   - Promotional text names the benefit.
   - Assign 2–5 keywords from the approved version's list, never shared with another page.
   - Add a deep link to the matching screen when there is one.
3. **Product page optimization, one variable per test:**
   - In this order: first screenshot, then header, then icon.
   - 30–50 % of traffic; run until 90 % confidence or 90 days.
   - Don't release a version mid-test unless you must.
   - Apply the winner in the browser.
4. **In-app events:** only a dated happening with something new inside the app.
   - Name it as the event is called.
   - Card media without text.
   - Publish up to 14 days early so it can be discovered.
   - Deep link straight into the event.
5. **Promo codes:** for press and reviewers at launch (browser).
6. **Offer codes:** for win-back or partner campaigns (browser).

## 8. What the kit does and doesn't do

- `asc_sync.py plan KIT --only growth` reads the live pages, tests and events (GET only) and plans:
  - create or update of pages, versions, texts, keywords and media;
  - tests and treatments with their media;
  - events with their languages and media.
- It refuses pages and tests before launch, with a note (and an optional browser check for pages), and leaves
  started tests, items in review and published events alone.
- `apply KIT --yes` saves drafts only: nothing customers see changes.
- `submit KIT --growth IDS --yes` sends them to App Review:
  - after launch, on their own;
  - before launch (events only), together with the first version.
- `release KIT --start-test ID --yes` starts an approved test. It is a separate yes, because it can't be undone.
- Never automated:
  - deleting anything;
  - applying a winning treatment (`appStoreVersionPromotions`);
  - promo codes and offer codes;
  - Publish of a live header swap;
  - Game Center.
