# Measuring growth: Analytics Reports API, custom product page and test results, Sales and Trends

How the kit measures whether its custom product pages, tests and events work (`scripts/asc_reports.py`), and what
Apple's API can and can't tell. Read on 2026-10-15 from Apple's doc JSON pages and App Store Connect Help.
**UNCONFIRMED** marks anything Apple's pages don't settle.

**Sources** (read 2026-10-15):
- [AR] https://developer.apple.com/documentation/appstoreconnectapi/analytics (doc JSON:
  `https://developer.apple.com/tutorials/data/documentation/appstoreconnectapi/analytics.json`)
- [AR-dl] https://developer.apple.com/documentation/appstoreconnectapi/downloading-analytics-reports
- [AR-list] https://developer.apple.com/documentation/analytics-reports (the report catalogue)
- [AR-eng] https://developer.apple.com/documentation/analytics-reports/app-store-discovery-and-engagement
- [AR-dlr] https://developer.apple.com/documentation/analytics-reports/app-download
- [AR-dcc] https://developer.apple.com/documentation/analytics-reports/data-completeness-corrections
- [API objects] `analyticsreportrequest`, `analyticsreport`, `analyticsreportinstance`, `analyticsreportsegment`
  (their `attributes-data.dictionary` pages), `post-v1-analyticsreportrequests`, `get-v1-salesreports`
- [CPP-an] https://developer.apple.com/help/app-store-connect-analytics/acquisition/custom-product-pages
- [PPO-an] https://developer.apple.com/help/app-store-connect-analytics/acquisition/product-page-optimization
- [PPO-run] https://developer.apple.com/help/app-store-connect/create-product-page-optimization-tests/run-a-test
- [PTI] https://developer.apple.com/help/app-store-connect/reference/reporting/product-type-identifiers

---

## 1. The Analytics Reports API

| Step | Request | Notes |
|---|---|---|
| Ask for reports | `POST /v1/analyticsReportRequests` `{"data": {"type": "analyticsReportRequests", "attributes": {"accessType": "ONGOING"}, "relationships": {"app": {"data": {"type": "apps", "id": APP}}}}}` | `ONGOING`: new data every day, at daily, weekly and monthly granularity. `ONE_TIME_SNAPSHOT`: the history (one per month). 201 on success; 409 is listed (**UNCONFIRMED** when: probably a duplicate request). **Apple generates nothing until a request exists.** |
| First data | – | "Your first report request generates in 1–2 days. Subsequent `ONGOING` reports are available daily." [AR-dl] |
| List requests | `GET /v1/apps/{id}/analyticsReportRequests` | attributes `accessType`, `stoppedDueToInactivity`. A request nobody reads for a long time stops; then make a new one. |
| Reports of a request | `GET /v1/analyticsReportRequests/{id}/reports` `filter[category]`, `filter[name]` | attributes `name`, `category` (`APP_USAGE`, `APP_STORE_ENGAGEMENT`, `COMMERCE`, `FRAMEWORK_USAGE`, `PERFORMANCE`). The kit reads `APP_STORE_ENGAGEMENT` and `COMMERCE`. |
| Instances | `GET /v1/analyticsReports/{id}/instances` `filter[granularity]=DAILY|WEEKLY|MONTHLY`, `filter[processingDate]` | attributes `granularity`, `processingDate`. Instances are deleted after **35 days**. |
| Segments (files) | `GET /v1/analyticsReportInstances/{id}/segments` | attributes `url` (download link), `checksum` (**md5**), `sizeInBytes`. Download every segment of an instance. |
| Delete a request | `DELETE /v1/analyticsReportRequests/{id}` | the kit never deletes |

**Roles** [AR]: Admin creates and deletes requests; Admin, Sales and Reports or Finance list and download.

**Files.** A segment downloads as gzip; the content is tab-separated with a header row (the object page says "CSV
data"; the kit accepts tabs or commas). "Rely on column names instead of column positions"; "Report values are not
case sensitive" [AR-list]. The download link is pre-signed: the kit sends no JWT with it (**UNCONFIRMED** that Apple
would refuse one, but the JWT must never leave Apple's API host).

**Overlapping instances** [AR-dcc]. A daily instance can hold several Dates (late events, corrections). "Instances from
a more recent `processingDate` overwrite instances with an earlier `processingDate` … Don't merge records for a Date
… across two report instances to avoid double counting. Use the latest instance." The kit keeps, for each Date, only
the rows of the newest instance.

**Privacy.** Apple adds noise or crowd anonymity and reports totals only above a threshold [AR]. Many reports come in
two levels: **Standard** (fields not easily tied to a person) and **Detailed** (all fields, more privacy measures).

## 2. The two reports the kit reads

| Report (name + " Standard" / " Detailed") | Category | Columns the kit uses |
|---|---|---|
| App Store Discovery and Engagement [AR-eng] | `APP_STORE_ENGAGEMENT` | Date, Event (`Impression`, `Page view`, `Tap`), Page Type, **Page Title (Detailed only)**, Source Type, Engagement Type, Counts, Unique Counts |
| App Store Downloads [AR-dlr] | `COMMERCE` | Date, Download Type (`First-time download`, `Redownload`, `Manual update`, `Auto-update`, `Restore`), Page Type, **Page Title (Detailed only)**, Source Type, Counts |

- The engagement report name is confirmed by Apple's example (`"App Store Discovery and Engagement Detailed"`). The
  downloads report's exact `name` is **UNCONFIRMED** (the page title is "App Store Downloads"): the kit matches any
  `COMMERCE` report whose name contains "download" and isn't the pre-order report, and prefers "Detailed".
- Availability: daily every day; complete within 3 days (engagement) or 2 days (downloads). History on request from
  January 1, 2024.
- Page Type values: `Product page`, `In-app event`, `Store sheet`, `No page`, `Notification`, version history,
  privacy, developer page, accessibility, media view.
- **Page Title**: "The name of the product page or in-app event page … Possible values include the name you set for
  your page in App Store Connect, default product page, no page, or null." So a custom product page is identified
  **by its name** (growth.yaml `name`), not by its id: **there is no ppid / Product Page ID column** in either report.
  Renaming a page splits its history. For in-app events, whether Page Title is the reference name or the localized
  event name is **UNCONFIRMED** (the kit matches both).
- Source Type values: `App Store search`, `App Store browse`, `App referrer`, `Web referrer`, `App Clip`,
  `Notification`, `Unavailable` (+ `Institutional purchase` for downloads). Source Info (referrer) and Campaign are
  Detailed only.
- [CPP-an]: "To export Custom Product Page data in bulk, use the Analytics reports … Data about individual Custom
  Product Pages is only available for export in the detailed reports." A page's data appears after **5 first-time
  downloads**. Apple's own dashboard per page: product page views, total downloads, conversion rate.

**Conversion in the kit:** first-time downloads ÷ unique product page views, both for the same Page Title. Daily unique
counts are summed over the window, so a person who visits on two days counts twice. App Analytics' own definition
for a page isn't on the Help page (**UNCONFIRMED** that the numbers match exactly).

## 3. Product page optimization results: not in the API

- The test resources (`GET /v1/apps/{id}/appStoreVersionExperimentsV2`, `appStoreVersionExperimentTreatments`) carry
  only `name`, `platform`, `trafficProportion`, `state` (… `COMPLETED`, `STOPPED`), `reviewRequired`, `startDate`,
  `endDate`, and per treatment `name`, `appIcon`, `appIconName`, `promotedDate`. **No impressions, conversion, lift or
  confidence.**
- No analytics report in the catalogue [AR-list] is about product page optimization, and neither report above has a
  treatment column. Whether a treatment's views show up under a Page Title is **UNCONFIRMED** (not documented).
- Results live in App Analytics › Acquisition › Product Page Optimization [PPO-an]: per variant Unique Impressions,
  Conversion Rate ("the percentage of viewers who downloaded your app"), Improvement (lift vs the baseline) and
  Confidence (Bayesian; a 90 % credible interval). Labels: Performing Better / Performing Worse (at 90 % confidence),
  Collecting Data, Likely to be Inconclusive. Shown after 5 first-time downloads; updated daily [PPO-run].
- So `asc_reports.py growth --live` shows a test's state and dates, and the owner reads the result in the browser.
  Applying a winner (`POST /v1/appStoreVersionPromotions`) stays a browser step (growth-marketing.md).

## 4. Sales and Trends (`GET /v1/salesReports`)

- Query: `filter[vendorNumber]` (App Store Connect › Payments and Financial Reports), `filter[reportType]`,
  `filter[reportSubType]`, `filter[frequency]`, `filter[version]`, `filter[reportDate]` (YYYY-MM-DD; not needed for
  the latest DAILY report). The kit asks for `SALES` / `SUMMARY` / `DAILY` / `1_0`.
- Response: 200 with a **gzip** file (tab-separated), not JSON. A day without a report answers 404 (**UNCONFIRMED**
  for days without sales; the kit says "no report yet").
- Roles: Sales and Reports (also Finance and Admin). Individual API keys can't use Sales and Finance (asc-api.md).
- The file covers **every app of the vendor**: the kit keeps rows whose Apple Identifier is the app, plus purchases
  whose Parent Identifier is the app's SKU.
- Product type identifiers [PTI]: app downloads `1 1F 1T F1 1E 1EP 1EU 1-B F1-B`; redownloads `3 3F`; updates `7 7F 7T F7`; in-app purchases `IA1 IA1-M IA9 IA9-M IAY IAY-M FI1`;
  restored `IA3`.
- Other report types (allowed combinations in the endpoint's table): `SUBSCRIPTION`, `SUBSCRIPTION_EVENT`,
  `SUBSCRIBER` (1_3), `INSTALLS`, `PRE_ORDER`, `SUBSCRIPTION_OFFER_CODE_REDEMPTION`, `WIN_BACK_ELIGIBILITY`, … The kit
  doesn't read them yet.

## 5. The kit's loop

1. After launch: `asc_reports.py request KIT --yes` (once; an Admin key). Wait 1–2 days.
2. Every week or so: `asc_reports.py fetch KIT [--days 30]` → `KIT/reports/` (raw gzip files under `raw/`, merged
   `engagement.tsv` and `downloads.tsv`). The folder carries its own `.gitignore` (`*`): it is store data and never
   committed. Fetching regularly also keeps the request from stopping.
3. `asc_reports.py growth KIT [--days 30] [--live]` → `KIT/GROWTH-RESULTS.md`:
   - per product page (default + every growth.yaml page): unique page views, first-time downloads, conversion;
   - "too small to judge" under 100 unique page views or 5 first-time downloads (Apple's own display threshold);
   - "BELOW default (90 % sure)" when a one-sided two-proportion z-test against the default page reaches 90 %
     (the confidence Apple asks for before applying a test treatment); otherwise "below default, not yet clear";
   - per source type: impressions, page views, downloads; per in-app event: page views, reminders, downloads;
   - tests: live state and dates (with `--live`), and where to read their results;
   - the next experiment, per growth-marketing.md §7: one variable at a time, in the order first screenshot →
     header → icon (icon only with an alternate icon in the live binary); a waiting note while a test runs or when
     the default page has under 1,000 unique views in the window; for a page clearly below the default, change one
     thing in a new page version (tests don't run on custom product pages).
4. Optional: `asc_reports.py sales KIT --vendor N [--date D]` prints a daily summary and keeps the file in
   `KIT/reports/sales/`.
