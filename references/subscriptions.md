# Auto-renewable subscriptions

`scripts/subscriptions.py` reads `KIT/subscriptions.yaml`; start from
`templates/subscriptions.example.yaml`. It imports the shared API client and guide masking/progress
helpers, and does not import `asc_sync.py`. No command deletes an Apple resource.

## Commands and approvals

```sh
python3 scripts/subscriptions.py check KIT
python3 scripts/subscriptions.py status KIT
python3 scripts/subscriptions.py plan KIT
python3 scripts/subscriptions.py apply KIT --dry-run
python3 scripts/subscriptions.py apply KIT --yes
python3 scripts/subscriptions.py plan KIT
python3 scripts/subscriptions.py submit KIT --dry-run
python3 scripts/subscriptions.py submit KIT --yes
```

- `check` is offline, including key resolution. It validates types, enums, lengths, locale codes,
  duplicate product IDs, group levels, offer dates and screenshot paths. Exit 1 means invalid input.
- `status` uses GET only and writes masked `subscriptions-live.json` with groups, subscription states,
  localizations, prices, offers and review screenshot information.
- `plan` uses GET only and writes `subscriptions-plan.md` and `.json`: old values, exact requests,
  screenshot hashes, blockers, deferred pricing and standalone submission targets.
- `apply` and `submit` exit 2 without `--yes`, unless `--dry-run` is given. Dry-run reads live state,
  prints the proposed requests, sends no writes and does not record completion.
- Apply compares a fresh plan against the saved plan. Changed input, target app, file contents,
  live changes that affect the plan, or edited JSON require another plan and review. API writes are
  not transactional; after partial failure, inspect status and plan again. Completed creates are
  rediscovered, so the next plan does not create duplicates. An old plan is refused after state changes.
- Every successful write is re-read. Screenshot uploads reserve, PUT, commit and check delivery state
  and checksum. Only confirmed operations enter `connect-progress.yaml` via the guide's existing schema.
  It preserves other steps and masks private values before JSON/YAML serialization.
- App resolution uses `connect.yaml api.app_id`, checked against `facts.yaml app.bundle_id` if both
  exist, or an exact bundle-ID lookup. Authentication is entirely `asc_api.make_client`: explicit key
  options, `ASC_*` environment, then kit configuration and the client's key-directory resolution.

**New products need two passes.** Apple price points are scoped to an existing subscription. The first
plan creates groups, products, localizations and review screenshots; its deferred list identifies pricing
and offers. Apply it, then plan again to inspect actual price-point IDs, all equalized territories and
amounts before applying prices/offers. Submit refuses any outstanding changes or deferred work.
Source: [Managing subscriptions](https://developer.apple.com/documentation/appstoreconnectapi/managing-auto-renewable-subscriptions).

## Declaration and limits

Groups have `reference_name`, optional existing `id`, `localizations`, and `subscriptions`.
A localization maps an App Store locale to `name`, plus optional `custom_app_name` for groups.
Subscription localizations require `name` and `description`. Omission leaves optional text unchanged;
empty `custom_app_name` or `review_note` explicitly requests clearing it. Use an existing group ID
when changing its reference name. Product IDs cannot be moved between groups or renamed.

| Field | Offline rule | Verification / Apple source |
|---|---|---|
| Subscription display name | 1–30 characters | Confirmed: [Promoting In-App Purchases](https://developer.apple.com/app-store/promoting-in-app-purchases/) |
| Subscription description | 1–55 characters | **UNCONFIRMED** in retrieved pages; subscription-specific limit, not the 45-character general promoted-IAP description. [Subscription information](https://developer.apple.com/help/app-store-connect/reference/in-app-purchases-and-subscriptions/auto-renewable-subscription-information/) |
| Reference names / product ID / review note | 64 / 100 / 4000 characters | **UNCONFIRMED** numerical limits in this verification. Product IDs use ASCII letters, digits, `.`, `_`, `-`. [In-App Purchase information](https://developer.apple.com/help/app-store-connect/reference/in-app-purchases-and-subscriptions/in-app-purchase-information/) |
| Group localized name / custom app name | 75 / 30 characters | **UNCONFIRMED** numerical limits. [Group localization fields](https://developer.apple.com/documentation/appstoreconnectapi/subscriptiongrouplocalization/attributes-data.dictionary) |
| Duration | `ONE_WEEK`, `ONE_MONTH`, `TWO_MONTHS`, `THREE_MONTHS`, `SIX_MONTHS`, `ONE_YEAR` | Confirmed: [Subscription create attributes](https://developer.apple.com/documentation/appstoreconnectapi/subscriptioncreaterequest/data-data.dictionary/attributes-data.dictionary) |
| Group level | Integer 1–100; ties allowed | Level 1 is highest; equal benefits can share a level. The 100 ceiling and maximum 100 products per group are **UNCONFIRMED**. [Subscription levels](https://developer.apple.com/help/app-store-connect/reference/in-app-purchases-and-subscriptions/auto-renewable-subscription-information/) |
| Names | Reject control characters and angle brackets | Apple's restrictions also cover markup and some special characters; this check is not a full Unicode policy implementation. [Subscription information](https://developer.apple.com/help/app-store-connect/reference/in-app-purchases-and-subscriptions/auto-renewable-subscription-information/) |
| Locales | Codes in `scripts/locales.py` | The shared metadata locale list is used; subscription-specific locale differences are **UNCONFIRMED**. [Managing locales](https://developer.apple.com/documentation/appstoreconnectapi/managing-metadata-in-your-app-by-using-locale-shortcodes) |
| Offer modes | `FREE_TRIAL`, `PAY_AS_YOU_GO`, `PAY_UP_FRONT` | **UNCONFIRMED** full enum/combination schema in retrieved pages. [Offer mode](https://developer.apple.com/documentation/appstoreconnectapi/subscriptionoffermode) |
| Offer duration / periods | Subscription durations plus `THREE_DAYS`, `TWO_WEEKS`; 1–12 periods; free trial/up front require 1 | **UNCONFIRMED** full duration/payment-mode/product-duration matrix; local validation is deliberately incomplete. Apple decides eligible combinations. [Offer duration](https://developer.apple.com/documentation/appstoreconnectapi/subscriptionofferduration) |
| Promotional offers | At most 10; name/code at most 64 characters | **UNCONFIRMED** numerical limits. `offer_code` is the promotional identifier used by StoreKit, not a redeemable offer code. [Promotional offers](https://developer.apple.com/help/app-store-connect/manage-subscriptions/set-up-promotional-offers-for-auto-renewable-subscriptions/) |

Dates and decimal amounts should be quoted YAML strings. An introductory offer has `territory`,
`mode`, `duration`, `periods`, optional `start_date`/`end_date`, and `price` for paid offers. A promotional
offer has `name`, `offer_code`, `mode`, `duration`, `periods`, and territory-to-amount `prices`.
Free-trial amounts must be zero. Only one declared introductory offer per territory is accepted.
Existing identical offers are kept; a conflicting offer blocks apply rather than replacing it.

## Review and the first subscription

A subscription needs complete localized metadata, pricing, a review screenshot showing the purchase
in the app, and reviewer instructions that explain how to reach it. Test purchase and restore behavior
in sandbox/TestFlight, and ensure the paid agreement, tax and banking are ready. Store availability
is a separate browser step; this script does not set availability or verify the purchase implementation.
The screenshot path must be an existing PNG/JPEG within KIT; image dimensions/content still need review.
App Review tests purchases in the same sandbox ([Configure In-App Purchases for review](https://developer.apple.com/help/app-review/before-submitting-for-review/configure-in-app-purchases), read 2026-10-17):
the Paid Apps Agreement must be **in effect** (paid purchases don't work in review before that); fetch products
with StoreKit before showing them so the paywall matches App Store Connect (no hard-coded prices); if purchases are
limited by storefront or device, say so in the review notes; in-app purchases don't need prior approval to work in
review. Give the reviewer an account with an expired subscription as well as the demo account (complete-review).
See [Offer subscriptions](https://developer.apple.com/help/app-store-connect/manage-subscriptions/offer-auto-renewable-subscriptions/)
and [Submit an In-App Purchase](https://developer.apple.com/help/app-store-connect/manage-submissions-to-app-review/submit-an-in-app-purchase/).

**The first subscription goes with an app version and binary.** A previously released app does not
establish that its first subscription has been reviewed. `submit` refuses standalone submission unless
at least one subscription in this app is currently `APPROVED`. Submit the first subscription from its own
page (Add for Review), together with a new app version, as Apple now does for the first in-app purchase; if the live
page instead shows an In-App Purchases and Subscriptions section on the version page, use that (UNCONFIRMED for
subscriptions; record what the live page shows).
The script conservatively refuses when all formerly approved subscriptions are removed from sale and
it cannot establish approval history. Later products must be `READY_TO_SUBMIT`; submit targets only the
IDs listed in the plan and re-reads their states. See
[Submitting subscriptions for review](https://developer.apple.com/documentation/appstoreconnectapi/submitting-subscriptions-and-subscription-groups-for-app-review).

Family Sharing cannot be disabled once enabled. The script blocks that change. Duration changes on
anything beyond `MISSING_METADATA` also block: Apple locks duration after submission. See
[Family Sharing](https://developer.apple.com/help/app-store-connect/configure-in-app-purchase-settings/turn-on-family-sharing-for-in-app-purchases/)
and [Subscription duration](https://developer.apple.com/help/app-store-connect/reference/in-app-purchases-and-subscriptions/auto-renewable-subscription-information/).

**Compatibility:** this feature uses the specifically requested `POST /v1/subscriptionSubmissions`
and matching v1 localizations. Apple deprecated these in API 4.4.1; its migration guide says the old
endpoints remain available. The newer workflow creates subscription/group versions and submits them
through review submission items. This implementation does not mix those two workflows or fall back
silently if the legacy API rejects a request. See
[Migration guide](https://developer.apple.com/documentation/appstoreconnectapi/migrating-in-app-purchase-metadata-to-v2)
and [Deprecated submission endpoint](https://developer.apple.com/documentation/appstoreconnectapi/post-v1-subscriptionsubmissions).

## Price changes

Use either `prices: {USA: "4.99", GBR: "4.99"}` (preserves current subscriber prices), or
`pricing: {base_territory: USA, price: "4.99", equalize: true, preserve_current_price: true}`.
The latter accepts optional `start_date`; `equalize: false` limits it to the base territory.
Equalization reads Apple's current equivalents and expands them into explicit per-territory requests.
It is not a promise of future automatic equalization. Amounts must match a unique Apple price point.
Source: [Managing subscription prices](https://developer.apple.com/documentation/appstoreconnectapi/managing-auto-renewable-subscriptions).

`preserve_current_price` defaults to true. Setting it false can affect existing subscribers. Apply
requires `--price-increase-ok` as well as `--yes` for an increase, an unknown existing price, or an
approved product whose older preserved cohorts cannot be priced from this read. This deliberately
conservative gate may also catch decreases. The plan warns before any writes. Current prices and
scheduled rows are included in the comparison; changed schedules require a new plan. The request policy is recorded separately from returned values because Apple returns `preserved`
cohort rows rather than the `preserveCurrentPrice` option. Successful request receipts plus a matching
re-read price ID prevent repeating a nonpreserving change. The flag does
not override Apple's consent rules or substitute for subscriber consent.

Apple requires consent where the storefront mandates it, when the subscriber already experienced
an increase within 12 months, or when the rise exceeds both 50% and the applicable monetary threshold
(approximately US$5 per nonannual period or US$50 annually; storefront equivalents vary). Without
required consent, the subscription expires. Otherwise Apple sends notice. Notice periods vary by
subscription duration; a late change may leave an additional renewal at the old price. Price decreases
that take effect cannot be undone, and a new future schedule can overwrite an earlier one. Check the
current storefront rules before applying, including special rules for India, South Korea and multiseat
purchases. This script supports ordinary subscriptions, not commitment/multiseat plans.
Sources: [Pricing and consent](https://developer.apple.com/help/app-store-connect/manage-subscriptions/manage-pricing-for-auto-renewable-subscriptions/),
[Storefront thresholds](https://developer.apple.com/help/app-store-connect/reference/in-app-purchases-and-subscriptions/auto-renewable-subscription-price-increase-thresholds/).

## API shapes and verification

All JSON requests are JSON:API `{data: {type, attributes?, relationships?, id?}}`. Relationship values
are `{data: {type, id}}`; POST omits the resource ID, PATCH includes it. All reads use `Client.get` /
`get_all` and the shared client's pagination. All writes use `Client.post` / `patch`; uploads use
`upload_operations` without an API JWT on asset URLs. No account or credentialed endpoint was contacted
during development. Offline fake tests establish implementation behavior, not Apple's acceptance.

Public pages were checked on 2026-10-15. “Confirmed” means the retrieved public documentation supports
the endpoint or listed fields; it does not mean a live account test. **UNCONFIRMED** marks request
shapes that could not be fully retrieved and are also flagged in the script.

| Purpose / endpoints | Shape and verification | Apple source |
|---|---|---|
| Resolve app: `GET /v1/apps?filter[bundleId]=…`, `GET /v1/apps/{id}` | Confirmed in `asc-api.md`; exact match required | [Apps](https://developer.apple.com/documentation/appstoreconnectapi/apps) |
| Groups: `GET /v1/apps/{id}/subscriptionGroups`, `POST /v1/subscriptionGroups`, `GET/PATCH /v1/subscriptionGroups/{id}` | Read confirmed; create/patch `referenceName`, relationship `app: apps` **UNCONFIRMED** full write shape | [Groups](https://developer.apple.com/documentation/appstoreconnectapi/creating-auto-renewable-subscription-groups) |
| Products: `GET /v1/subscriptionGroups/{id}/subscriptions`, `POST /v1/subscriptions`, `GET/PATCH /v1/subscriptions/{id}` | Attributes `name`, `productId` (create only), `subscriptionPeriod`, `groupLevel`, `familySharable`, `reviewNote` confirmed. Create relationship `group: subscriptionGroups` **UNCONFIRMED** create shape; read relationship confirmed | [Create attributes](https://developer.apple.com/documentation/appstoreconnectapi/subscriptioncreaterequest/data-data.dictionary/attributes-data.dictionary), [Group reads](https://developer.apple.com/documentation/appstoreconnectapi/get-v1-apps-_id_-subscriptiongroups) |
| Group localization: `GET /v1/subscriptionGroups/{id}/subscriptionGroupLocalizations`, `POST /v1/subscriptionGroupLocalizations`, `GET/PATCH /v1/subscriptionGroupLocalizations/{id}` | `locale`, `name`, `customAppName`; parent `subscriptionGroup`. Read fields confirmed; full writes **UNCONFIRMED**, deprecated | [Group localization](https://developer.apple.com/documentation/appstoreconnectapi/get-v1-subscriptiongrouplocalizations-_id_) |
| Product localization: `GET /v1/subscriptions/{id}/subscriptionLocalizations`, `POST /v1/subscriptionLocalizations`, `GET/PATCH /v1/subscriptionLocalizations/{id}` | `locale`, `name`, `description`; parent `subscription`. Family confirmed by migration guide, full write shape **UNCONFIRMED**, deprecated | [Migration](https://developer.apple.com/documentation/appstoreconnectapi/migrating-in-app-purchase-metadata-to-v2) |
| Prices: `GET /v1/subscriptions/{id}/pricePoints?filter[territory]=…&include=territory`, `GET /v1/subscriptionPricePoints/{id}`, `GET /v1/subscriptionPricePoints/{id}/equalizations?include=territory` | Uses `customerPrice`, territory linkage and point IDs. Full query/response shapes **UNCONFIRMED** | [Price points](https://developer.apple.com/documentation/appstoreconnectapi/subscription-price-points-and-subscription-prices) |
| Price changes: `GET /v1/subscriptions/{id}/prices`, `POST /v1/subscriptionPrices`, `GET /v1/subscriptions/{id}/prices` (re-read) | `startDate`, `preserveCurrentPrice` confirmed; relationships `subscription`, `territory`, `subscriptionPricePoint`; full write relationship shape **UNCONFIRMED**; read collection confirmed and returns `startDate`, `preserved`, territory/point links, not `preserveCurrentPrice` | [Price attributes](https://developer.apple.com/documentation/appstoreconnectapi/subscriptionpricecreaterequest/data-data.dictionary/attributes-data.dictionary), [Price collection](https://developer.apple.com/documentation/appstoreconnectapi/get-v1-subscriptions-_id_-prices) |
| Intro offers: `GET /v1/subscriptions/{id}/introductoryOffers`, `POST /v1/subscriptionIntroductoryOffers`, `GET /v1/subscriptionIntroductoryOffers/{id}` | `duration`, `offerMode`, `numberOfPeriods`, `startDate`, `endDate`; `subscription`, `territory`, optional paid `subscriptionPricePoint`. Read fields/relationships confirmed; complete POST constraints **UNCONFIRMED** | [Intro offer fields](https://developer.apple.com/documentation/appstoreconnectapi/get-v1-subscriptions-_id_-introductoryoffers), [Create relationships](https://developer.apple.com/documentation/appstoreconnectapi/subscriptionintroductoryoffercreaterequest/data-data.dictionary/relationships-data.dictionary) |
| Promo offers: `GET /v1/subscriptions/{id}/promotionalOffers`, `POST /v1/subscriptionPromotionalOffers`, `GET /v1/subscriptionPromotionalOffers/{id}`, `GET /v1/subscriptionPromotionalOffers/{id}/prices` | `name`, `offerCode`, `duration`, `offerMode`, `numberOfPeriods`; `subscription` + `prices[]` inline `subscriptionPromotionalOfferPrices` with `territory` and `subscriptionPricePoint`. **UNCONFIRMED** full POST, inline IDs/linkage and price read shape | [Promotional offer resources](https://developer.apple.com/documentation/appstoreconnectapi/subscription-promotional-offers) |
| Review screenshot: `GET /v1/subscriptions/{id}/appStoreReviewScreenshot`, `POST /v1/subscriptionAppStoreReviewScreenshots`, `GET/PATCH /v1/subscriptionAppStoreReviewScreenshots/{id}`, reserved upload PUT URLs | Reserve `fileName`, `fileSize`, parent `subscription`; commit `uploaded: true`, `sourceFileChecksum` (MD5); check `assetDeliveryState.state: COMPLETE`. Parent targeting confirmed by migration guide; complete upload/read shape **UNCONFIRMED** | [Review screenshots](https://developer.apple.com/documentation/appstoreconnectapi/subscription-app-store-review-screenshots) |
| Submit: `POST /v1/subscriptionSubmissions`; verify `GET /v1/subscriptions/{id}` | Endpoint/deprecation confirmed; relationship `subscription: subscriptions` **UNCONFIRMED** complete request schema. Re-read must show waiting/in-review/pending-binary/approved | [Submit](https://developer.apple.com/documentation/appstoreconnectapi/post-v1-subscriptionsubmissions) |

Offer codes (`offer_codes: browser`), availability, billing grace periods, offer signing keys, app-side
StoreKit implementation, and version-based metadata migration remain outside this command. Offer codes
stay in the browser even though Apple has API resources for them. Existing review screenshots with a
missing/different checksum need browser replacement; no size-only match is trusted. Existing offers
that differ also need browser editing. See [Offer codes](https://developer.apple.com/documentation/appstoreconnectapi/subscription-offer-codes).
