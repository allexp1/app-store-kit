# Storefront pricing, availability and pre-orders

`scripts/pricing.py` manages the app's download price and storefront availability,
not In-App Purchase or subscription prices. Input: `KIT/pricing.yaml`, starting
from `templates/pricing.example.yaml`. App selection and key resolution follow
`connect.yaml api:` and `facts.yaml app.bundle_id`; `asc_api.py` handles credentials.
An explicit `api.app_id` must match the bundle ID when both are supplied.

## Workflow

```sh
python3 scripts/pricing.py check KIT
python3 scripts/pricing.py status KIT
python3 scripts/pricing.py plan KIT
# Show pricing-plan.md to the owner, then on their approval:
python3 scripts/pricing.py apply KIT --yes --dry-run
python3 scripts/pricing.py apply KIT --yes
# When the approved plan removes any currently available territories:
python3 scripts/pricing.py apply KIT --yes --remove-territories-ok
```

- `check` validates locally without resolving a key or making network requests.
  It cannot prove a customer price exists or that a pre-order is eligible.
- `status` uses GET only, prints the current manual/automatic schedule, territory
  currencies and availability, pre-order flags/dates and content blockers, and
  writes `pricing-live.json`. It works without `pricing.yaml`.
- `plan` uses GET only and writes `pricing-plan.md` and `pricing-plan.json`.
  Every territory has old → new price, proceeds when returned, effective dates,
  availability and pre-order settings. The JSON contains the exact requests.
- `apply` exits **2 without `--yes`**, including dry runs. `--dry-run` prints the
  requests without sending writes or recording completion; it still needs GETs
  and normal API credentials. Territory removals also require
  `--remove-territories-ok`, including dry runs. **Live customers in removed
  territories lose the listing.** This is not an uninstall of their existing app.
- Apply checks the input fingerprint, app, plan date, live snapshot and newly
  looked-up prices. If any changed, re-plan and review. Plans expire at the next
  local calendar day. After each write it re-reads, saves `pricing-live.json`, and
  after a matching final read records `pricing/storefront-api` in
  `connect-progress.yaml`, preserving other steps and masking private values
  through `connect_guide`. It does not claim that tax, agreements or browser-only
  availability switches are complete.
- A response mismatch or partial failure leaves progress incomplete. Read status,
  re-plan, and approve the remaining changes. Replaying a fully applied plan is
  a no-op. No parent resource is deleted. Exit 1 means validation/API/staleness
  failure; exit 2 also covers the missing removal acknowledgement or credentials.

## Input and price resolution

| Field | Meaning |
|---|---|
| `base_territory` | Apple's three-letter territory code, for example `USA` |
| `customer_price` | Quoted nonnegative decimal in the base territory's customer currency; `"0.00"` is free |
| `manual_overrides` | Optional mapping such as `{GBR: "0.99", JPN: "100"}`; each amount is in that territory's currency |
| `scheduled_change` | Optional `start_date` (`YYYY-MM-DD`, future), `customer_price`, and optional `manual_overrides` |
| `territories` | `all`, a list such as `[USA, GBR]`, or `{all-except: [CHN]}`; `[]` removes all storefront listings |
| `new_territories_auto_available` | Required boolean; controls newly introduced Apple storefronts |
| `pre_order` | Optional `{enabled: true, release_date: "YYYY-MM-DD"}` or `{enabled: false}`; omit to preserve existing settings |

The base and every manual override are resolved by paginating
`GET /v1/apps/{id}/appPricePoints?filter[territory]=CODE`. Decimal amounts must
match exactly; missing or ambiguous points stop planning. IDs are opaque API
values, never derived from a tier number or guessed. Omit the base territory from
manual overrides. Unknown territory codes and misspelled configuration keys fail.

Other territories use Apple's `appPricePoints` equalizations, not a local currency
conversion. Missing equalizations stop planning until a manual override supplies
an exact point. Proceeds are Apple's returned values, not a commission calculation;
missing proceeds are displayed as “not returned.”

The YAML describes the complete desired current and future manual schedule. A new
schedule uses inline `appPrices` for the current base/overrides, plus an optional
second phase with a start date. The current phase ends when the scheduled phase
starts. Scheduled overrides inherit the current mapping when omitted; an explicit
`{}` returns other territories to automatic pricing in the second phase. Existing
future phases and manual overrides absent from this configuration are replaced;
review the full old → new table. Historical price rows are displayed but not
recreated. Once the scheduled date passes, move its prices to the current fields,
remove `scheduled_change`, and plan again.

Apple explains base territory and automatic adjustments in
[Set a price](https://developer.apple.com/help/app-store-connect/manage-app-pricing/set-a-price/)
and scheduling in
[Schedule price changes](https://developer.apple.com/help/app-store-connect/manage-app-pricing/schedule-price-changes/).

## Pre-order rules and boundaries

Apple's [Publish for pre-order](https://developer.apple.com/help/app-store-connect/manage-your-apps-availability/publish-for-pre-order/)
says a first launch can be scheduled **2–180 days ahead**. Once released in a
country or region, the app cannot become a pre-order there again. Apple now allows
2–365 days for some launches in additional countries; this script deliberately
keeps the requested **180-day maximum** for all pre-orders. Dates use the machine's
local calendar; Apple's rollout times vary by storefront.

The global YAML setting applies to the selected territories. Existing active
pre-orders can have their future date changed. Past release dates and an
`AVAILABLE` content status block re-enabling. New pre-orders after a known released
or removed app version are refused conservatively: the API's current state does
not prove a territory has never been released. Configure an eligible new-country
expansion in App Store Connect when this check blocks it.

Disabling an active pre-order while retaining availability is refused because it
could mean immediate release. To cancel the offer, remove that territory in the
reviewed availability plan and use the removal acknowledgement. Enabling a
pre-order does not submit an app version or press Release This Version. Review and
release remain separate approved steps. A pre-order on an already released app
may become visible immediately; its release date later controls customer delivery.

See also [Manage availability](https://developer.apple.com/help/app-store-connect/manage-your-apps-availability/manage-availability-for-your-app-on-the-app-store/).
Mac/Apple Vision Pro compatibility switches, agreements, banking and tax remain
outside this command.

## API contract and verification

Resource versions, fields, relationships, pagination parameters and inline create
shapes were checked against the cached official **OpenAPI 4.5.1** specification on
2026-10-15 and `references/asc-api.md` §7. Official download:
[App Store Connect OpenAPI specification](https://developer.apple.com/sample-code/app-store-connect/app-store-connect-openapi-specification.zip).
The implementation uses the following endpoints; it has not been tested against
a credentialed account.

| Method and endpoint | Use |
|---|---|
| `GET /v1/apps?filter[bundleId]=…`, `GET /v1/apps/{id}` | Resolve and verify app |
| `GET /v1/territories` | Complete storefront catalogue and currency |
| `GET /v1/apps/{id}/appStoreVersions` | Conservative release-history guard |
| `GET /v1/apps/{id}/appPriceSchedule` | Current schedule |
| `GET /v1/appPriceSchedules/{id}/baseTerritory` | Base territory fallback |
| `GET /v1/appPriceSchedules/{id}/manualPrices` | Full manual timeline, including price points |
| `GET /v1/appPriceSchedules/{id}/automaticPrices` | Full automatic timeline, including price points |
| `GET /v1/apps/{id}/appPricePoints?filter[territory]=…` | Exact customer-price lookup |
| `GET /v3/appPricePoints/{id}` | Price-point detail fallback |
| `GET /v3/appPricePoints/{id}/equalizations` | Apple's automatic local prices |
| `POST /v1/appPriceSchedules` | App, base territory and inline `appPrices` linked by `manualPrices` |
| `GET /v1/apps/{id}/appAvailabilityV2` | Current app availability |
| `GET /v2/appAvailabilities/{id}/territoryAvailabilities` | Territory flags, release dates and content statuses |
| `POST /v2/appAvailabilities` | Initial availability, changed new-territory policy, or new territory records; full inline `territoryAvailabilities` |
| `PATCH /v1/territoryAvailabilities/{id}` | Existing territory availability/pre-order/date changes |

The v2 availability schema has no parent PATCH: changing
`availableInNewTerritories` uses POST with the full intended territory settings.
Existing pre-order/date fields are preserved when omitted from YAML. The inline
app price's relationship is **only `appPricePoint`**; territory comes from the
point. Equalizations and point detail use **v3**, even though app price-point
listing is under `/v1/apps`. The removed v1 `appPreOrders` API and
`POST /v1/endAppAvailabilityPreOrders` are not used.

**UNCONFIRMED (runtime, not endpoint/schema existence):** the account-specific
acceptance and replacement semantics of posting an existing schedule/availability,
inline temporary-ID handling, end-date boundaries, automatic-price propagation
and consistency delays have not been exercised with credentials. The code uses
Apple's documented inline shapes and re-reads; a mismatch does not mark completion.
**UNCONFIRMED:** a complete territory release-history test is not available from
these reads; conservative refusal can block a genuinely eligible new-country
pre-order. **UNCONFIRMED:** cancellation by `available: false` plus
`preOrderEnabled: false` needs live-account verification for active offers. No
claim is made that a successful flag update clears Apple's content blockers.

Offline tests use a strict fake transport that checks versioned paths and writable
payload fields. They verify price resolution/pagination, scheduling, territory
selection, pre-orders, approvals, stale/tampered plans, partial failures, re-reads,
idempotent replay and private-value masking. They are not live API certification.
