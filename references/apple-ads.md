# Apple Ads: the UA manager's playbook

How the kit acts as a mobile app marketer and user-acquisition manager on Apple Ads (formerly Search Ads)
for the owner's own app. Sources: the full ads.apple.com/app-store help centre, best-practice pages,
glossary and success stories, read 2026-11-10; the Apple Ads Platform API documentation on
developer.apple.com (API facts in the last section). Re-check anything marked **(changing)** before relying on it.

The script is `scripts/apple_ads.py` with `KIT/apple-ads.yaml` (template `templates/apple-ads.example.yaml`).
Money moves only through the gates in "Approvals": every campaign is created **PAUSED**, and turning it on,
raising a budget or a bid, or applying any proposal is its own yes.

## 0. Before the first dollar

Check these with the owner. Each one is a reason not to spend yet.

1. **The product page converts.** Ads land on the product page; a weak page wastes every tap. Run the
   kit's Growth journey first (custom product pages, PPO) or at least have the screenshots right. Apple: the
   title, subtitle and keyword field also decide which searches the ad is relevant for ("Review your app
   metadata", tips for no impressions). Metadata changes take up to 2 h to reach the ad.
2. **The unit economics.** What is an install worth? Ask for (or derive from App Analytics + `asc_reports.py`)
   trial-to-paid, ARPU and day-7/day-30 retention. Without them, the target is a guess; say so and pick a
   conservative test budget.
   - Affordable CPA (cost per install) = expected revenue per install over the payback window the owner accepts.
   - Starting max CPT (cost per tap) = affordable CPA × expected tap-to-install rate. Apple's own example:
     $2.50 × 40 % = $1.00. Top-of-search conversion averages over 60 %, so 40 to 50 % is a safe planning number for
     brand and category terms, lower for competitor terms.
3. **Measurement.** Apple Ads reports installs (tap-through 30 days, view-through 1 day). Revenue and
   retention come from the app: the AdServices framework (`AAAttribution.attributionToken()` posted to
   `https://api-adservices.apple.com/api/v1/` within 24 h of first launch; Apple keeps attribution data 21 days)
   or an MMP. Suggest wiring AdServices in the app before scaling, so CPA can become cost per paying user.
   Payload fields: orgId, campaignId, adGroupId, keywordId, adId, conversionType (Download / Redownload),
   claimType, clickDate, countryOrRegion, supplyPlacement.
4. **Account.** An Apple Ads **Advanced** account (Basic has no keywords, no API, cost per install, $10K/month cap
   per app; running both for one app gains nothing). The account's currency and time zone are permanent.
   Billing runs on UTC. The API needs a user with an API role and an API client; see "API access".
5. **Legal.** France (Sapin law): only an advertiser who owns both the app and the Apple Ads account may target
   France, and every FR campaign answers whether the advertiser is a French business (`french_business` in the yaml;
   the API's campaign-level CAMPAIGN_SAPIN_LAW takes FRENCH_BUSINESS / NOT_FRENCH_BUSINESS, not NOT_AGENT). Mainland China needs business and app approval first and has no product-page ads. Brazil and
   some other markets need product-page metadata and screenshots in the local language.

## 1. Placements

All four are cost per tap (CPT). 91 countries and regions; product pages in 90 (not mainland China).

| Placement | Intent | Needs | Use it for |
|---|---|---|---|
| **Search results** | highest (someone searching now) | keywords or Search Match | the core: start here, always |
| **Search tab** | browsing, before typing | one bid, no keywords; default or custom product page | cheap reach; Apple says running it with search results lowers cost |
| **Today tab** | awareness | a custom product page with approved assets | launches, big updates, seasonal moments; lifts brand searches |
| **Product pages** ("You might also like") | browsing similar apps | category refinement optional | competitor-adjacent reach |

Only search results have keywords, target CPA (Maximize Conversions), ad variations and impression share.
Deep links in ads (via a custom product page) work on iOS 18+. Apple's case studies credit multi-placement
plans with 120 to 190 % more installs; treat those as vendor marketing, but the direction is consistent.

**Order:** search results first (weeks 1 to 4). Add the Search tab when brand and category terms are stable.
Today tab and product pages when there is budget for awareness and a CPP worth showing.

## 2. Campaign structure (search results)

Apple's recommended structure, which the kit builds by default:

| Campaign | Keywords | Match | Search Match | Bid level |
|---|---|---|---|---|
| **Brand** | app and company name, misspellings | exact | off | highest (defend; cheap, ~top CR) |
| **Category** | what the app does ("budget planner") | exact | off | high |
| **Competitor** | names of similar apps | exact | off | moderate; CR is lower |
| **Discovery** | ad group A: every keyword above as **broad**; ad group B: none | broad / none | A off, B **on** | moderate / lower |

- Add every Brand, Category and Competitor keyword to Discovery as an **exact negative**, so Discovery only
  finds new terms and never competes with the exact campaigns. Keep broad and exact in separate ad groups.
- **Harvest loop** (weekly): Discovery's search-terms report → terms with installs at an acceptable CPA move
  to the right exact campaign (with a higher bid) and become exact negatives in Discovery; irrelevant terms
  become negatives. Most spend should end up on exact match.
- **Countries:** one campaign per large market (own budget, own value: US, UK, DE, JP); group smaller ones
  with similar value or language. Apple: group by customer value, language, region or finance centre;
  separate when you want to learn a market's value. Keyword lists are per language: translate by local search
  behaviour, not word for word (one case study: +14 % down-funnel conversion from that alone).
- **Customer type** per ad group: All (default), New users, Returning users, Users of my other apps.
  A separate returning-users ad group (or campaign) lets you bid for win-back differently.
- **Audience refinement (age, gender, location):** avoid. Any refinement excludes users with Personalized Ads
  off (Apple: 78 % of search volume) and makes the AdServices payload say `attribution: false`. Audience must stay
  above 5,000 people. Minimum ages: 18 US/EU, 19 CA/KR/DZ, 20 JP/TW, 21 BH/EG/KW/AE; never under 13.
  Location refinement only in single-country campaigns in the listed countries. Use tailored creative instead.
- **Limits:** keywords per ad group 5,000 (UI, upload) and targeted + negative keywords per campaign 10,000;
  ad groups per campaign 2,000; custom product pages 70, one active custom ad per ad group.
- **Names** carry the theme and market: `Brand_US`, `Category_DACH`, `Discovery_US`. The script names them so.

### Maximize Conversions (alternative)

Apple's auto-bidder for search results: set a **target CPA** and a daily budget; it bids per query.
It creates an automated ad group (Search Match on, all users) that can't be removed; you can add ad groups
with keywords and negatives but no keyword bids. Budget for at least **5 conversions a day** and wait **two weeks**
before changing the target. Not for pre-orders. Changing back to Manage Bids restores earlier bids.

**Recommendation:** owners with no data and little time: Brand (manage bids, exact) + one Maximize
Conversions campaign for everything else. Owners who want control or have more than ~$50/day: the four-campaign
structure above. The yaml picks per campaign (`strategy: manage_bids | maximize_conversions`).

## 3. Budget and bids

- **Daily budget** is an average: monthly spend ≤ daily × 30.4; a single day may go over. No lifetime budgets
  (lifetime-budget campaigns were paused in June 2026). A keyword bid must be lower than the campaign's daily budget.
- **Test budget:** enough for statistically useful taps. Rule of thumb used here: ≥ 20 installs per ad group per
  week before judging a bid, ≥ 100 taps before judging a keyword's CR.
- **Tiered bids:** exact Brand highest, exact Category/Competitor next, Discovery broad lower, Search Match lowest.
- Use Apple's **suggested bid** (shown per keyword) as a ceiling check; bid recommendations exist only for exact match.
- **CPA cap (changing):** an ad-group ceiling that limits impressions; Apple says it "will soon be unavailable".
  Don't set new ones. Removing one: lower the bid first, wait a day, then remove the cap.
- New campaigns need 24 to 48 h for data and several days before major changes. Paused ads may still serve
  for a few hours.

## 4. The weekly optimisation loop

`apple_ads.py report --days N` (default 14, at most 90) pulls campaign, keyword and search-term rows;
`apple_ads.py optimize` turns them into **proposals only** (it never applies them). Run it weekly; compare a 7-day
and a 28-day run before acting on a small keyword. These are kit rules (not Apple's), per keyword, with target CPA T.
"Auto" rows are proposed by the script; "Owner" rows are for the owner to judge from the report:

| Signal | Proposal | |
|---|---|---|
| CPA < 0.8 T and ≥ 5 installs | raise bid 15 % (capped by `max_bid` and the daily budget) | Auto |
| CPA > 1.3 T with ≥ 5 installs | lower bid 20 % | Auto |
| spend > 2 T and 0 installs | pause keyword / add exact negative (Discovery search term) | Auto |
| taps ≥ 30, CR < half the campaign CR | lower bid 15 %; check relevance | Auto |
| impressions ≈ 0 for 7 days | raise bid toward the suggested bid, check relevance, check metadata | Owner |
| Discovery search term with ≥ 2 installs at CPA ≤ T, not yet exact | harvest: exact in that market's Category campaign + exact negative in Discovery | Auto |
| campaign spends its full budget every day at CPA ≤ T | raise daily budget 20 % | Auto |
| campaign CPA > 1.5 T (and spend > 3 T) | lower daily budget 20 %; cut bids first | Auto |
| Apple recommendation (keyword, bid, target CPA, budget) | shown in the Apple Ads website with 7-day estimates; owner decides there | Owner |

Never change the same item two weeks in a row without new data; bid changes can take time to take effect.
Kit heuristic: a low TTR (below ~5 % on search results) usually means relevance or creative, not bid: try a custom product page
ad variation. Apple's stories report ~10 to 17 % better CR or CPA for ad variations over the default ad.

## 5. Creative

- The default ad uses the product page's first screenshots, so order matters (kit heuristic: in portrait
  apps the first three screenshots are what people see).
- **Ad variations** = custom product pages (made in App Store Connect; the kit's Growth journey makes them).
  Match the CPP to the ad group's theme (a "budget planner" ad group → a CPP whose first screenshot says budget).
  The CPP must match the campaign's language, country and device.
- Today tab: the CPP's assets animate behind the ad; the colour comes from the icon.

## 6. Reading the numbers

| Metric | Meaning |
|---|---|
| TTR | taps ÷ impressions: relevance and creative |
| CR (tap-through) | installs ÷ taps: product page and intent |
| Avg CPT | what a tap costs: competition |
| Avg CPA (tap-through) | spend ÷ tap-through installs: the number to steer by |
| Installs (total) | tap-through (30-day window) + view-through (1-day window); new downloads + redownloads |
| Impression share / rank | share of searches where the ad showed; rank 1 to 5 or >5; 0 to 90 % exact, then "91 to 100 %"; 12 weeks |
| Search popularity | 1 to 5 |

Data is in the account time zone (billing is UTC). Search-term rows need ≥ 10 impressions a day; age, gender and
location need ≥ 100 a day, otherwise "Low volume". For revenue (ROAS), join AdServices campaign/keyword ids
with in-app revenue; Apple Ads itself doesn't see revenue.

## 7. When nothing serves

In this order: payment method set? campaign and ad group active and inside their dates? Audience left at "all
eligible users"? Metadata relevant to the keywords? Bid near the suggested bid? Search Match or more keywords?
More countries? Apps can take up to 24 h to appear after linking.

## 8. Approvals (this module)

| Command | What changes | Gate |
|---|---|---|
| `check` | nothing (offline) | none |
| `status`, `plan`, `report`, `optimize`, `--dry-run` | nothing (GET and report POSTs that only read) | none |
| `apply` | creates the planned campaigns, ad groups, keywords, negatives, ads, **all PAUSED** | 🛑 one yes for that plan |
| `activate CAMPAIGN_ID…` | starts spending | 🛑 its own yes, shows daily budget × 30.4 |
| `apply-proposals` | the proposals the owner ticked in `apple-ads-proposals.json` | 🛑 its own yes |
| pause | stops spending | `pause CAMPAIGN_ID… --yes` (safe direction, still explicit) |

Never remove (delete) a campaign or ad group: removal is permanent in Apple Ads. Pause instead.
`apply-proposals` records each finished step in `apple-ads-proposals.json`, so a rerun after an error finishes
the rest without repeating anything. A harvest waits while its Category campaign is paused and Discovery runs.
Never iterate over the whole account changing things: every write names an id from the saved plan.

## 9. API access (Apple Ads Platform API)

The facts below are from Apple's developer documentation; confirm with `apple_ads.py status`, which reads only.
See "API reference" below for the endpoints the script uses.

1. An Account Admin opens Apple Ads → Account Settings → User Management and invites or edits a user with an
   API role (API Account Manager for writes; API Account Read Only for reports only).
2. That user signs in → Account Settings → API, and creates a client: they generate an EC P-256 key pair locally,
   paste the public key, and receive a `clientId`, `teamId` and `keyId`.
   **Shortcut:** `python3 scripts/apple_ads_key.py KIT` does steps 2 and 3 in the terminal: it makes the key pair in
   `~/.config/app-store-kit/apple-ads/` (folder 700, key 600), copies the public key to the clipboard, reads back the
   pasted clientId / teamId / keyId block, signs in once to list the ad accounts (`GET /v1/acls`, read-only) and
   writes `connect.yaml` › `apple_ads`. The private key is never printed.
3. The kit keeps the private key out of the repo (like the `.p8`): `KIT/connect.yaml`
   `apple_ads: {client_id, team_id, key_id, key_path, ad_account_id}` or the env vars `APPLE_ADS_CLIENT_ID`,
   `APPLE_ADS_TEAM_ID`, `APPLE_ADS_KEY_ID`, `APPLE_ADS_KEY_PATH`, `APPLE_ADS_AD_ACCOUNT_ID`. The ad account id is
   shown in the Apple Ads website (account menu); the API lists the ones the user can reach at `GET /v1/acls`.
4. The script signs a client-secret JWT (ES256), exchanges it at Apple's OAuth 2 token endpoint for a 1-hour
   access token, and calls the API with the header `X-AP-Context: adAccountId=<id>`.

### API reference (what `apple_ads.py` calls)

Base `https://api.ads.apple.com/v1`. The older Campaign Management API v5 (`api.searchads.apple.com/api/v5`) is
deprecated and sunsets on 2027-01-26, so the kit does not use it.

| Step | Endpoint |
|---|---|
| token | `POST https://appleid.apple.com/auth/oauth2/token` (form: `grant_type=client_credentials`, `client_id`, `client_secret`=JWT, `scope=searchadsorg`); JWT `kid`=keyId, `iss`=teamId, `sub`=clientId, `aud`=`https://appleid.apple.com`, lifetime under 180 days |
| account | `GET /v1/ad-accounts/{id}`: currency, time zone, `productFeatures` (needs `APPSTORE_APP_MANUAL`) |
| find campaigns | `POST /v1/campaigns/query` filtered on `promotedObjectId` (idempotency by campaign name) |
| create | `POST /v1/campaigns` (status `PAUSED`, `MANUAL_CPT`/`TAP`, `supplyPlacement APPSTORE_SEARCH_RESULTS`, Sapin answer for FR; name without `\|`), `/v1/adgroups` (`CPT`, Search Match flag, bid, `startTime` required). No creatives or ads: search results serve the default product page, and the API refuses Ad objects there |
| keywords | `POST /v1/keywords/bulk-create`, `/v1/negative-keywords/bulk-create`, `/v1/keywords/bulk-update` (bid, status only; text and match type never change), in chunks of 100 with `allowPartialSuccess: false` |
| switch | `PUT /v1/campaigns/{id}` with `{"status": "ENABLED" | "PAUSED"}` or a new `dailyBudget` (partial update), then `GET` to read it back |
| reports | `POST /v1/reports/apps/{campaigns,keywords,searchterms}/query` with `timeRange {start, end, timeZone ORTZ, granularity DAILY}` and a `campaignId` filter |

Learned on the first live run (2026-11-10): campaign names may not contain `|`; ad groups need `startTime`
(`yyyy-MM-ddTHH:mm:ss.SSS`); `POST /v1/ads` fails for search results campaigns (`AD_CAMPAIGN_SUPPLY_SOURCES_NOT_SUPPORTED`);
one default-product-page creative per app; `negative-keywords/query` needs an `adGroupId` filter. `apply` records every
finished step in `apple-ads-live.json`, so a stopped apply is finished by planning again.

Not used (left to the website): Maximize Conversions (no documented target-CPA field), recommendations `apply`
(changes spend), deletes. There is no server-side dry run; `--dry-run` records the writes locally. Rate limits come
back as `RateLimit-*` headers and 429 with `Retry-After`, which the client waits out. Creates are never retried on
a server error, because a lost answer could mean the object exists.
