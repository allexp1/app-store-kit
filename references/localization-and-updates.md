# App Store localization and live-app updates: research (2026-10-14)

Sources are primary Apple pages unless marked **SECONDARY**. Anything not confirmed is marked **UNCONFIRMED**. Local `xcodebuild -help` output is from Xcode 27.0 (27A266a) on this Mac.

Key URLs (short names used below):
- [LOC] https://developer.apple.com/help/app-store-connect/reference/app-information/app-store-localizations
- [CODES] https://developer.apple.com/documentation/appstoreconnectapi/managing-metadata-in-your-app-by-using-locale-shortcodes
- [PROPS] https://developer.apple.com/help/app-store-connect/reference/app-information/required-localizable-and-editable-properties
- [VERINFO] https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information
- [APPINFO] https://developer.apple.com/help/app-store-connect/reference/app-information/app-information
- [LOCALIZE] https://developer.apple.com/help/app-store-connect/manage-app-information/localize-app-information
- [SHOTS] https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications
- [PREVIEWS] https://developer.apple.com/help/app-store-connect/reference/app-information/app-preview-specifications
- [ASSETS] https://developer.apple.com/help/app-store-connect/manage-app-information/manage-your-app-store-assets/
- [PP] https://developer.apple.com/app-store/product-page/
- [L10N] https://developer.apple.com/localization/
- [ARG] https://developer.apple.com/app-store/review/guidelines/ (last updated June 8, 2026)
- [NEWVER] https://developer.apple.com/help/app-store-connect/update-your-app/create-a-new-version
- [PHASED] https://developer.apple.com/help/app-store-connect/update-your-app/release-a-version-update-in-phases
- [RELOPT] https://developer.apple.com/help/app-store-connect/manage-your-apps-availability/select-an-app-store-version-release-option
- [REVIEW] https://developer.apple.com/distribute/app-review/
- [EXPEDITE] https://developer.apple.com/help/app-review/after-submitting-for-review/request-expedited-review
- [REMOVE] https://developer.apple.com/help/app-store-connect/manage-submissions-to-app-review/remove-a-submission-from-review
- [UNRESOLVED] https://developer.apple.com/help/app-store-connect/manage-submissions-to-app-review/manage-a-submission-with-unresolved-issues
- [STATUS] https://developer.apple.com/help/app-store-connect/reference/app-information/app-and-submission-statuses
- [UPLOAD] https://developer.apple.com/help/app-store-connect/manage-builds/upload-builds

---

## 1. App Store localizations (50 languages, API locale codes)

Apple: "The App Store is available in 175 regions and 50 languages … Use these locale short codes to manage localized metadata with App Store Connect API." [CODES]. Names and codes below are copied from [CODES]; [LOC] lists the same 50 by name (it spells some differently, e.g. "Bangla", "Odia", "Slovenia").

| Language | Code | Language | Code |
|---|---|---|---|
| Arabic | `ar-SA` | Japanese | `ja` |
| Bengali (Bangla) | `bn-BD` | Kannada | `kn-IN` |
| Catalan | `ca` | Korean | `ko` |
| Chinese (Simplified) | `zh-Hans` | Malay | `ms` |
| Chinese (Traditional) | `zh-Hant` | Malayalam | `ml-IN` |
| Croatian | `hr` | Marathi | `mr-IN` |
| Czech | `cs` | Norwegian | `no` |
| Danish | `da` | Oriya (Odia) | `or-IN` |
| Dutch | `nl-NL` | Polish | `pl` |
| English (Australia) | `en-AU` | Portuguese (Brazil) | `pt-BR` |
| English (Canada) | `en-CA` | Portuguese (Portugal) | `pt-PT` |
| English (U.K.) | `en-GB` | Punjabi | `pa-IN` |
| English (U.S.) | `en-US` | Romanian | `ro` |
| Finnish | `fi` | Russian | `ru` |
| French | `fr-FR` | Slovak | `sk` |
| French (Canada) | `fr-CA` | Slovenian | `sl-SI` |
| German | `de-DE` | Spanish (Mexico) | `es-MX` |
| Greek | `el` | Spanish (Spain) | `es-ES` |
| Gujarati | `gu-IN` | Swedish | `sv` |
| Hebrew | `he` | Tamil | `ta-IN` |
| Hindi | `hi` | Telugu | `te-IN` |
| Hungarian | `hu` | Thai | `th` |
| Indonesian | `id` | Turkish | `tr` |
| Italian | `it` | Ukrainian | `uk` |
| | | Urdu | `ur-PK` |
| | | Vietnamese | `vi` |

Watch out: these are not always BCP-47 codes. Use `ar-SA` (not `ar`), `de-DE` (not `de`), `kn-IN`/`ml-IN`/`mr-IN`/`or-IN`/`pa-IN`/`ta-IN`/`te-IN`/`ur-PK` (not bare codes), and `no` (not `nb`). The 2025–26 Indic additions come with their region suffixes. A skill should hard-code this table and not guess.

## 2. Which fields are localized, and where

From the [PROPS] tables. That page says the "Editable" column marks properties "that can be … edited at any time without submitting a new version of your app."

**App level (App Information; API `appInfoLocalizations`)**: per locale, Name (required, 2–30 chars [APPINFO]), Subtitle (optional, 30), Privacy Policy URL (required), Privacy Choices URL (optional). None of these is "Editable" in [PROPS], so a change ships with the next version. The API resource holds "Locale, Name, Subtitle, Privacy policy URL, Privacy policy text (tvOS)" — https://developer.apple.com/documentation/appstoreconnectapi/app-info-localizations. Not localized: age rating, categories, primary language, bundle ID, SKU, content rights [PROPS].

**Version level (API `appStoreVersionLocalizations`)**: per locale, Description (4,000), Keywords (100 bytes), Promotional Text (170), What's New (4,000; updates only), Support URL (required), Marketing URL (optional), plus screenshots and previews [VERINFO]. The API docs say: "You can update the Promotional Text for your version at any time. Update other attributes when your app is in an editable state." — https://developer.apple.com/documentation/appstoreconnectapi/app-store-version-localizations. Copyright is version level but not localized, and it is Editable [PROPS].

**In-App Purchases and subscriptions**: per locale, Display Name (2–30 chars) and Description (max 45 chars). Both are required for at least one language. They are marked Editable, but "Changes to the localized information require review. The existing text displays on the store until the new text is approved." (https://developer.apple.com/help/app-store-connect/reference/in-app-purchases-and-subscriptions/in-app-purchase-information). Subscription Group Display Name and App Name Display Options are also localized [PROPS].

**2026 API note**: "Manage version media with the App Asset Library and placements. The app preview set and app screenshot set relationships are deprecated." (app-store-version-localizations doc above). Screenshot upload scripts built on the old `appScreenshotSets` model should move to the asset library and placements model.

## 3. Screenshot and preview fallback across locales

- "When you add a language to your app, screenshots and the properties for the new language default to those of the primary language, except for the description and keywords." [LOCALIZE]. So a locale without its own screenshots shows the primary language's screenshots.
- Each locale can have its own set: "you can upload specific screenshots and app previews tailored to each device size and localization." [SHOTS]
- Scaling: "If your app's user interface is consistent across multiple device sizes and localizations, you only need to provide screenshots for the highest required resolution." [SHOTS]. The required iPhone size is now **Dynamic Island (medium display)**, 1206×2622 or 1179×2556. Each size names its own fallback (re-read 2026-10-14): Dynamic Island large ↔ Face ID large fall back to each other, Dynamic Island medium falls back to Face ID large, Face ID medium to Dynamic Island medium, and the Home-button sizes to the next larger one [SHOTS]. So do not assume the 6.9" set feeds the medium size; upload the required medium set yourself.
- Previews: "If a localized app preview is missing … the app preview in the next best available language is used" [PREVIEWS]. You can add up to 3 previews per device size per localization [VERINFO], and up to 10 screenshots [PP].
- Media Manager: "Manage app preview and screenshot placements for each supported device size and localization. You can add assets from the Asset Library, reorder … remove placements, and choose poster frames." You pick a language from the pop-up at the top right [ASSETS]. "After you remove a screenshot or app preview, it's also removed for all other display sizes using scaled versions." [ASSETS]
- Upload or edit is allowed only when the version is in Prepare for Submission, Invalid Binary, Rejected, Metadata Rejected or Developer Rejected [ASSETS]. In Waiting for Review "you can't upload or edit screenshots or app previews" [STATUS].
- Changing the primary language later: the new primary's screenshots must already be approved and match the current primary's sizes. If they were derived from another localization, you must upload real ones and ship a version first [LOCALIZE].

## 4. Keyword indexing across locales and storefronts

**Apple primary (2 statements):**
1. "If you localize your app metadata in French … Users can search for your app using localized keywords in all countries or regions where the App Store supports French." [LOCALIZE]
2. [LOC] has a table that gives every storefront a default language and "additional supported languages". Examples:
   - **USA**: default English (US); additional Arabic, Chinese (Simplified), Chinese (Traditional), French, Korean, Portuguese (Brazil), Russian, Spanish (Mexico), Vietnamese.
   - **Canada**: en-CA + fr-CA.
   - **UK**: en-GB only.
   - **Germany, France, Italy, Netherlands, Sweden, Brazil, Mexico, Korea**: local language + English (U.K.).
   - **Japan**: ja + English (US).
   - **China**: zh-Hans + en-GB.
   - **Switzerland**: de + en-GB, fr, it.
   - **Spain**: es-ES + Catalan + en-GB.
   - **India**: en-GB + 11 Indic languages.
   - **Israel**: en-GB + Hebrew.
   - **Saudi Arabia/UAE**: en-GB + Arabic.
   - **Most other storefronts**: default English (U.K.).

   Taken together, statements 1 and 2 mean a storefront's search covers its default language plus its additional languages.
- Apple does not explicitly say on these pages that keywords in an "additional" locale rank in that storefront (**UNCONFIRMED** wording), though statement 1 implies it.
- **SECONDARY** (widely cited ASO practice): "for the U.S. store … Apple indexes keywords from both English (U.S.) and Spanish (Mexico) localizations … up to 200 characters of keyword space" (https://trysonar.app/blog/app-store-keyword-field.md; also https://asomobile.net/en/blog/app-store-localization/). Apple's table lists 9 additional languages for the US, so the "only en-US + es-MX" folklore is narrower than Apple's own table. Whether all 9 add ranking weight is **UNCONFIRMED**.
- **SECONDARY**: "do not repeat words already in your title or subtitle because the algorithm already indexes those" (https://passion.io/blog/app-store-localization-expand-your-reach-with-aso). Apple says the same for the app and company names: "Don't duplicate the app or company name, since those are already searchable." [VERINFO]
- Apple's own keyword tips: separate terms with commas and no spaces, and don't use plurals of words you already have, category names, the word "app", duplicates, or special characters. "Promotional text doesn't affect your app's search ranking." [PP]

## 5. Rules for localized metadata

| Field | Limit | Source |
|---|---|---|
| Name | 2–30 characters | [APPINFO], [ARG 2.3.7] |
| Subtitle | 30 characters | [APPINFO], [PP] |
| Keywords | **100 bytes**; each keyword more than 2 characters | [VERINFO] (Apple's [PP] marketing page says "100 characters", but the ASC reference says bytes. Treat it as bytes: CJK is 3 bytes per character in UTF-8, so about 33 CJK characters) |
| Promotional text | 170 characters | [VERINFO], [PP] |
| Description | 4,000 characters, plain text, no HTML | [VERINFO] |
| What's New | 4,000 characters, required for updates only | [VERINFO], [PROPS] |
| Review notes | 4,000 bytes | [VERINFO] |
| IAP display name / description | 30 / 45 characters | IAP reference above |

Content rules:
- **Unique name, no stuffing.** Guideline 2.3.7: "Choose a unique app name, assign keywords that accurately describe your app, and don't try to pack any of your metadata with trademarked terms, popular app names, pricing information, or other irrelevant phrases … Apple may modify inappropriate keywords at any time." Subtitles must "not … reference other apps, or make unverifiable product claims" [ARG].
- **No competitor names in keywords.** "Names of other apps or companies aren't allowed." [VERINFO]
- **No prices in metadata.** [ARG 2.3.7], and "avoid including specific prices in your app description" [PP].
- **No other platforms.** No names or imagery of other mobile platforms (2.3.10); metadata must suit a 4+ rating (2.3.8) [ARG].
- **Screenshots must show the app in use** (2.3.3) [ARG].
- **What's New must describe significant changes.** Guideline 2.3.12: "Apps must clearly describe new features and product changes in their 'What's New' text. Simple bug fixes … may rely on a generic description" [ARG].
- **Uniqueness across locales** (same name reused in different locales by different developers) is **UNCONFIRMED**. The App Store Connect help states names must be unique, but how that applies per locale isn't documented on the pages read.

## 6. In-app localization vs. store localization

- Store metadata languages are separate from binary languages: "This differs from adding languages to your app in Xcode when you localize your binary." [LOCALIZE] and "The languages you add to an appInfoLocalizations resource only affect your app's metadata. To add languages to your app's binary, see …" (app-info-localizations API doc).
- **The product page's "Languages" line comes from the binary.** An Apple DTS engineer wrote that it "is determined by the existence of the .lproj folders in your app bundle (for apps that don't use .lproj folders … inferred from the CFBundleLocalizations Info.plist entry)" (https://developer.apple.com/forums/thread/836440). This is an Apple forum answer, not a help page, so treat it as primary-ish. Xcode only emits a `<lang>.lproj` if the String Catalog has at least one translated string for that language (same thread).
- **Apple does not require the app to support a language before you list store metadata in it.** No guideline forbids it; [LOCALIZE] lets you add any of the 50 independently. A store page in a language the app doesn't support could still breach 2.3 / 2.3.1 accuracy ("Customers should know what they're getting"), but a direct guideline on advertising unsupported languages is **UNCONFIRMED** (none found in [ARG]). Practical rule: don't claim in localized text or screenshots that the app is in language X unless the binary ships X.
- Apple also suggests localizing permission purpose strings (InfoPlist.strings) and the privacy policy [L10N].

## 7. Translating store text: Apple guidance, RTL

- "Localize your App Store metadata … description, keywords, app previews … You can also translate your app's name and tailor your screenshots to reflect the values of each market." [L10N]. "Tailor your keywords to reflect the values of each market." [PP]. Keywords should be researched per market, not translated word for word.
- Cultural adaptation: "refine certain elements for cultural relevance … market-specific content or cultural moments … consider any local policies and market regulations, as well as any political or religious sensitivities" [L10N].
- Machine translation: "If using any machine translation … be sure to have native speakers … test your app or game's translation and provide feedback." Give translators a glossary and "screenshots that show where the translations will be used" [L10N].
- Screenshots: Xcode's "Localization Screenshots feature" generates localized screenshots from UI tests "for use in … your App Store product page" [L10N]. The first 1–3 screenshots appear in search results [PP].
- Testing: use TestFlight with testers in the market [L10N].
- **New in 2026 [L10N], read 2026-10-14:** Xcode's coding agents can add languages, update string catalogs, translate strings and add language-specific plural variants; Xcode gives them context and per-language style guidelines. Apple advises a model "with a large context window" for translation work, and native-speaker testing of any machine translation. For an external service, give a playbook: character names, explanations of humour, a glossary, and screenshots of where each string appears.
- On iOS and iPadOS people can pick the app's language separately from the device language [L10N], so the in-app language list should match the store languages.
- Localize purpose strings and consider localizing the privacy policy [L10N].
- Localize all marketing material for each market too: screenshots, banners, ads. App Store badges exist in localized versions; "App Store" itself is never translated (marketing guidelines). Apple Ads runs in 91 countries and regions [L10N].
- Pricing: App Store price tiers are pre-adjusted per region; auto-renewable subscriptions can choose from 800 price points, plus 100 higher ones on request [L10N].
- Creative assets (product page header, search results, iOS 27+) are localizable like screenshots; text in them must be localized for every supported language, and the App Store Connect Preview tool shows them per language and orientation ([Asset best practices](https://developer.apple.com/app-store/asset-best-practices/), [ASSETS]).
- Custom product pages and product page optimization treatments are localizable too; a PPO test limited to fewer localizations may take longer to reach a result (https://developer.apple.com/app-store/product-page-optimization/).
- **RTL (Arabic `ar-SA`, Hebrew `he`, Urdu `ur-PK`)**: Apple's HIG covers mirrored UI (https://developer.apple.com/design/human-interface-guidelines/right-to-left), and [L10N] says to test for "issues with right-to-left formatting". For RTL locales, capture screenshots with the device or simulator in that language so the UI is genuinely mirrored. Set caption text right-aligned and RTL, and, in a multi-image panorama, consider the reading order. The screenshot-specific RTL advice is **SECONDARY/UNCONFIRMED**: no Apple page found that states it for screenshots specifically. 2.3.3 still requires real in-app UI.

---

## 8. Creating a new version of a live app

- Steps: Apps → app → **+ next to the platform** in the sidebar → enter "an incremental App Store version number" → Create → review metadata → Save. Then upload a new build ("increment the build string before uploading"), attach it, and submit [NEWVER].
- Precondition: the current version must be **Ready for Distribution** to start a new one [NEWVER].
- No rollback: "it's not possible to revert to a previous version on the App Store … You must create and submit a new version." [NEWVER]
- Version numbers: `CFBundleShortVersionString` must be "three period-separated integers, such as 10.14.1", digits and periods only. `CFBundleVersion` (the build) is one to three integers (https://developer.apple.com/documentation/bundleresources/information-property-list/cfbundleshortversionstring, …/cfbundleversion).
  - The new App Store version must be higher than the live one: "incremental" [NEWVER]. The exact comparison rule (numeric per component) is standard but its wording here is **UNCONFIRMED**.
  - A build is identified by bundle ID + version + build string, and "the build string is used to uniquely identify the build" [UPLOAD]. In practice each upload for a version needs a new, higher build number (**SECONDARY**, https://heartbeat.comet.ml/full-stack-ios-continuous-delivery-with-xcodebuild-and-exportoptions-plist-28c48620593c).
- What carries over: "the metadata from the current version is automatically transferred to the new version." [NEWVER]. Screenshots and previews are not explicitly mentioned. In practice they carry over as placements; [ASSETS] mentions "a new version of a placement … the archived asset is carried over". Treat screenshot carry-over as **UNCONFIRMED** in docs and verify in Media Manager after creating the version.
- What must be entered: **What's New in This Version** (required for updates, localized per locale, 4,000 chars) [VERINFO][PROPS]. Also the release option and, optionally, phased release and reset rating [PROPS].
- Editable without a new version ([PROPS] "Editable" column):
  - Promotional Text [VERINFO][PP], copyright, App Review information, primary language, price/availability, privacy data types, accessibility labels, IAP metadata (IAP metadata still goes through review).
  - Korea/China availability items: "Can be entered at any time, but will be submitted for review with the next version submission" [PROPS].
- Changes only with a new version: Name, Subtitle, Privacy Policy URL, Privacy Choices URL, Support URL, Marketing URL, Description, Keywords, What's New, screenshots, age rating, categories [PROPS]. [PP] says the same: "You can update your subtitle when submitting a new version", and likewise for the description.

## 9. Release controls

- Release options [RELOPT]:
  - **Manually release this version**: the version sits in Pending Developer Release. Apple emails a reminder after 30 days. "After manually releasing … it may take up to 24 hours for it to appear on the App Store." You can Cancel This Release.
  - **Automatically release this version**.
  - **Automatically release … after App Review, no earlier than** a date and time.
  - The option is per platform.
- **Phased release** (iOS, automatic updates only) [PHASED]:
  - Schedule: day 1 = 1%, then 2%, 5%, 10%, 20%, 50%, 100% by day 7.
  - "you may pause the release for up to 30 days, with no limit on the number of pauses". The 30 days is a running total, and a resumed rollout picks up on the day it left off.
  - "can be manually downloaded from the App Store by anyone at any time".
  - "Release to All Users" is available at any time.
  - Can be set in Prepare for Submission, Waiting for Review, In Review, Pending Developer Release or Rejected.
  - Removing the app from sale stops it for good.
  - API: PATCH `appStoreVersionPhasedReleases` can pause, resume or complete it (https://developer.apple.com/documentation/appstoreconnectapi/patch-v1-appstoreversionphasedreleases-_id_).
- **Reset overview rating** (set on the version, applied at release) (https://developer.apple.com/help/app-store-connect/monitor-ratings-and-reviews/reset-an-app-overview-rating/):
  - Can't be undone, and applies to all countries.
  - Written reviews stay.
  - Apple advises using it sparingly (https://developer.apple.com/app-store/ratings-and-reviews/).
- **Expedited review** [EXPEDITE]:
  - Only for submissions already sent to App Review.
  - Use the form at https://developer.apple.com/contact/app-store/?topic=expedite.
  - For critical bug fixes, put repro steps in Review Notes. For events, give the event, its date and your association with it.
  - "reserved for matters of genuine urgency"; abuse can lead to future requests being rejected [ARG].
- **Editing after submission ("Developer Rejected")** [REMOVE]:
  - From Waiting for Export Compliance, Waiting for Review, In Review, Pending Developer Release or Pending Apple Release, click "remove this version from review". The status becomes Developer Rejected, and on resubmission "the review process will start over".
  - Alternatively, App Review → submission → Cancel Submission.
  - Developer Rejected lets you edit screenshots and metadata again [ASSETS].
- **Rejection and resubmission** [UNRESOLVED][STATUS]:
  - If any item is rejected, the submission shows **Unresolved Issues**. Either edit (once) and Add for Review → Resubmit to App Review, or remove the rejected items so the rest can be released.
  - Metadata Rejected: "edit the metadata to resolve the issue, and reply to the message from App Review". No new build is needed for this.
  - Reply via App Review → Resolve → Reply to App Review (4,000-char field with attachments) (https://developer.apple.com/help/app-store-connect/manage-submissions-to-app-review/reply-to-app-review-messages/).
- Submission limits: one app-version submission under review per platform, plus one non-version submission (IAP, in-app events, custom product pages, PPO tests) (https://developer.apple.com/help/app-store-connect/manage-submissions-to-app-review/overview-of-submitting-for-review).

## 10. Bug-fix submissions and review times

- [ARG] "Bug Fix Submissions: For apps that are already on the App Store … bug fixes will not be delayed over guideline violations except for those related to legal or safety issues. If your app has been rejected, and qualifies … use App Store Connect to communicate directly with the App Review team … and plan to address the issue in your next submission."
- [REVIEW] "To accept, simply reply to the offer message in App Store Connect and indicate you would like the current submission to be approved."
- Appeals: one appeal per rejected submission, filed with the App Review Board via https://developer.apple.com/contact/app-store/?topic=appeal [REVIEW][ARG]. Apple also offers 30-minute App Review appointments [REVIEW].
- 2025–26 changes: the "updated experience" lets you remove rejected items and continue with accepted ones, and submit IAP, events and custom product pages without a version [REVIEW]. A dated 2025 bug-fix policy change was not found (**UNCONFIRMED**).
- Review time (Apple): "typically reviewing at least 50% of submissions in less than 24 hours and 90% in less than 48 hours" [REVIEW][EXPEDITE].
  - **SECONDARY**: some blogs quote "90% in under 24 hours" or a June 2026 "average 1.5 days" (https://axonbuild.com/blog/how-long-does-app-store-review-take/). This is **UNCONFIRMED**; use Apple's 50%/24h, 90%/48h.

## 11. The App Store Connect app (iPhone/iPad)

- Apple: "monitor your app's sales and downloads, reply to App Store Review, get notified of new reviews, respond to reviews, and more" (https://developer.apple.com/app-store-connect/). Review status can also be checked "on the App Store Connect app for iPhone and iPad" [REVIEW].
- It is handy for the human steps: watching status pushes, replying to App Review, and replying to customer reviews.
- Releasing a Pending Developer Release version or pausing a phased release from the phone is **UNCONFIRMED**. Apple documents these steps only for the web, and an old forum post says "Cancel this release" is web-only (https://developer.apple.com/forums/thread/53463).

---

## Efficient update workflow for a solo developer

1. **Version and build bump** (automate). Set `MARKETING_VERSION` (→ CFBundleShortVersionString, x.y.z) and `CURRENT_PROJECT_VERSION` (→ CFBundleVersion). Alternatively, let Xcode manage the build number at export: the ExportOptions key `manageAppVersionAndBuildNumber` "Should Xcode manage the app's build number when uploading to App Store Connect? Defaults to YES." (local `xcodebuild -help`). With XcodeGen, bump the values in `project.yml`.
2. **Archive**:
   ```
   xcodebuild -scheme Swipr -configuration Release -destination 'generic/platform=iOS' -archivePath build/Swipr.xcarchive archive
   ```
   The `archive` action is documented in `xcodebuild -help`, and the Xcode equivalent is Product > Archive (https://developer.apple.com/documentation/xcode/distributing-your-app-for-beta-testing-and-releases).
3. **Export and upload in one step** (local `xcodebuild -help`, Xcode 27):
   ```
   xcodebuild -exportArchive -archivePath <xcarchive> -exportPath <dir> -exportOptionsPlist ExportOptions.plist [-allowProvisioningUpdates]
   ```
   ExportOptions.plist keys:
   - `method` = `app-store-connect` ("app-store (deprecated: use app-store-connect)")
   - `destination` = `upload` ("Options are export or upload … Defaults to export")
   - `teamID`, `signingStyle` = `automatic`
   - `uploadSymbols` = YES
   - optional `testFlightInternalTestingOnly` = YES for builds that must never reach the App Store

   Authentication: an Xcode-signed-in account, or `-authenticationKeyPath/-authenticationKeyID/-authenticationKeyIssuerID` with an App Store Connect API key (confirmed present in local Xcode 27 `xcodebuild -help`).
4. **Alternatives for the upload** [UPLOAD]:
   - altool: `xcrun altool --validate-app -f file -t platform …` and `xcrun altool --upload-app -f file -t platform -u username [-p password]`.
   - The Transporter app, or the Transporter CLI with API-key JWTs.
   - The App Store Connect API `buildUploads` endpoint (https://developer.apple.com/documentation/appstoreconnectapi/post-v1-builduploads).
   - [UPLOAD] notes that 2026 upload requirements apply ("Learn about upcoming upload requirements").
5. **TestFlight**: the build appears after processing (an email is sent). Internal testers get it immediately. External testers need beta review (https://developer.apple.com/testflight/).
6. **Store metadata per language** (automate with the App Store Connect API). Do these after creating the version (`POST appStoreVersions`, linked from [NEWVER]):
   - PATCH each `appStoreVersionLocalizations` with `whatsNew` (and description or keywords if changed). Keep release notes in the repo as `release-notes/<version>/<locale>.txt` using the codes from §1.
   - Check keyword byte length (≤100 bytes) and every 4,000/170/30 limit before sending.
   - Promotional text can be pushed any time without a release.
   - Screenshots go through the new Asset Library / placements API (the screenshot-set relationships are deprecated, see §2).
7. **Submit**: attach the build, set the release option (manual is recommended for solo developers so you control timing) and phased release ON, then submit. Submit via the API with `reviewSubmissions` / `reviewSubmissionItems` (https://developer.apple.com/documentation/appstoreconnectapi/app_store/review_submission_items).
8. **Human steps left**: answer the export-compliance prompt (or set `ITSAppUsesNonExemptEncryption` in Info.plist to skip it; standard practice, **UNCONFIRMED** here), respond to App Review, and press Release / watch the phased rollout. You can watch status from the App Store Connect iPhone app.
9. **Xcode Cloud option**: workflows build, test, and deliver to TestFlight from git pushes. Membership includes 25 compute hours a month; paid tiers run from 100 h at $49.99 to 10,000 h at $3,999.99 per month (https://developer.apple.com/xcode-cloud/). It removes local signing and upload scripting, but store metadata still needs the API or the web UI.

Open items to verify by hand: whether screenshots carry over to a new version (check Media Manager), whether every "additional language" ranks in its storefront, whether release and phased-release controls work in the iPhone app.
