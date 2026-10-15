# App Store Connect API: what it can and can't do (as of 2026-10-14)

Researched 2026-10-14 against **API version 4.5.1**, using the official OpenAPI spec (`info.version: 4.5.1`, file dated 2026-10-06, 1001 paths) and Apple's docs, Help pages and WWDC sessions.

- Spec download: https://developer.apple.com/sample-code/app-store-connect/app-store-connect-openapi-specification.zip (linked from https://developer.apple.com/documentation/appstoreconnectapi)
- Release notes index: https://developer.apple.com/documentation/appstoreconnectapi/app-store-connect-api-release-notes
- Base URL: `https://api.appstoreconnect.apple.com`. The API uses JSON:API style: `data` / `attributes` / `relationships` / `included`.

Doc-fetch tip for the skill: Apple's DocC pages render with JavaScript. The raw JSON is at `https://developer.apple.com/tutorials/data/documentation/appstoreconnectapi/<page>.json`, and the OpenAPI zip is the most reliable machine-readable source.

---

## 0. Headline changes since 2024 (they affect the skill's design)

| Version | What changed | Impact on the skill | Source |
|---|---|---|---|
| 4.0 (WWDC25) | Webhooks; **Accessibility declarations** (Accessibility Nutrition Labels) API; TestFlight feedback API; `POST appStoreVersionSubmissions` **removed**; `gamblingAndContests` and `seventeenPlus` removed from age rating | Use `reviewSubmissions`. Accessibility labels are automatable. | https://developer.apple.com/documentation/appstoreconnectapi/app-store-connect-api-4-0-release-notes |
| 4.1 | **Build uploads API** (`buildUploads` + `buildUploadFiles`); per-territory age ratings; `INFREQUENT_OR_MILD` and `FREQUENT_OR_INTENSE` deprecated (use `INFREQUENT` / `FREQUENT`); `platform` optional on review submission | Binary upload is possible over pure REST | https://developer.apple.com/documentation/appstoreconnectapi/app-store-connect-api-4-1-release-notes |
| 4.3.1 | **11 extra metadata locales** (50 languages total) | Update the locale table | https://developer.apple.com/documentation/appstoreconnectapi/app-store-connect-api-4-3-1-release-notes |
| 4.4.1 | **IAP, subscription and subscription-group metadata are now versioned** (`inAppPurchaseVersions` …). Submit them through `reviewSubmissionItems`. `inAppPurchaseSubmissions` and the v1 localization/image resources are deprecated. Age rating gains `socialMedia` and `socialMediaAgeRestricted`. | New IAP flow | https://developer.apple.com/documentation/appstoreconnectapi/app-store-connect-api-4-4-1-release-notes |
| 4.5 | Korea `ALL` / `TWELVE_PLUS` overrides; org subscriptions; performance overview | minor | https://developer.apple.com/documentation/appstoreconnectapi/app-store-connect-api-4-5-release-notes |
| **4.5.1 (latest)** | **App Asset Library** (images, videos, placements, ordering requests, ref data); `IPHONE_DUO` display class. **`appScreenshotSets`, `appScreenshots`, `appPreviewSets` and `appPreviews` are DEPRECATED** (still present in the spec), along with the app event screenshot and video clip resources. | **Build the new screenshot uploader on the Asset Library.** iPhone Duo is only reachable there. | https://developer.apple.com/documentation/appstoreconnectapi/app-store-connect-api-4-5-1-release-notes |

---

## 1. Auth

| Item | Answer | Source |
|---|---|---|
| Key types | **Team key**: covers all apps, with access set by the role you pick. **Individual key**: has the user's own access and roles. Individual keys **can't** use Provisioning, Sales and Finance, or `notaryTool`. | https://developer.apple.com/documentation/appstoreconnectapi/creating-api-keys-for-app-store-connect-api |
| Who can create one | Team keys need an **Admin** account (Users and Access, then Integrations, then App Store Connect API, then Team Keys, then Generate). Individual keys need the "Generate Individual API Keys" permission (`GENERATE_INDIVIDUAL_KEYS` role). | same |
| Role to give the key | **App Manager** is enough for metadata, IAP and the Asset Library. The docs name ACCOUNT_HOLDER / ADMIN / APP_MANAGER for the Asset Library and IAPs, and ADMIN / APP MANAGER / MARKETING for accessibility. **Admin** is needed for user management. The role needed for build uploads is not stated (UNCONFIRMED; App Manager or Developer is likely). | https://developer.apple.com/documentation/appstoreconnectapi/understanding-the-app-asset-library , https://developer.apple.com/documentation/appstoreconnectapi/managing-in-app-purchases , https://developer.apple.com/documentation/appstoreconnectapi/accessibility-declarations |
| `.p8` download | **You can download it once.** Apple keeps no copy. Revoke the key if it is lost. | creating-api-keys page |
| JWT header | `alg: ES256`, `kid: <Key ID>`, `typ: JWT` | https://developer.apple.com/documentation/appstoreconnectapi/generating-tokens-for-api-requests |
| JWT payload (team key) | `iss` = Issuer ID, `iat`, `exp`, `aud: "appstoreconnect-v1"`, optional `scope` | same |
| JWT payload (individual key) | Same as a team key, but **no `iss`**. Use `sub: "user"` instead. | same |
| Lifetime | `exp - iat` may be at most **20 minutes**. The exception: tokens of up to **6 months** are accepted if they carry a `scope` made only of `GET` entries on allow-listed resources (Xcode Cloud resources, Power and Performance metrics). Reuse a token until it expires. | same |
| `scope` | An array of strings like `"GET /v1/apps?filter[platform]=IOS"`. Query parameters can be in any order. `limit`, `cursor` and `sort` are ignored when matching. If no entry matches the request, the token is rejected. | same |
| Header | `Authorization: Bearer <jwt>` | same |

Python sketch: `jwt.encode({"iss":ISS,"iat":now,"exp":now+1200,"aud":"appstoreconnect-v1"}, p8, algorithm="ES256", headers={"kid":KID,"typ":"JWT"})`.

---

## 2. App info (applies across all versions)

| Item | Supported | Endpoint(s) | Key attributes, limits | Source |
|---|---|---|---|---|
| Create a new app record | **NO** | `/v1/apps` is GET only. "Don't use this API to create new apps." Bundle IDs *can* be created (`POST /v1/bundleIds`). | Use the browser (or Xcode Cloud "Set Up Distribution", which creates the record). | https://developer.apple.com/documentation/appstoreconnectapi/apps , https://developer.apple.com/videos/play/wwdc2026/261/ |
| App-level fields | yes | `PATCH /v1/apps/{id}` | `primaryLocale`, `contentRightsDeclaration` (`DOES_NOT_USE_THIRD_PARTY_CONTENT` / `USES_THIRD_PARTY_CONTENT`), `accessibilityUrl`, `bundleId`, `subscriptionStatusUrl*`, `streamlinedPurchasingEnabled` | https://developer.apple.com/documentation/appstoreconnectapi/appupdaterequest/data-data.dictionary/attributes-data.dictionary |
| appInfos | yes | `GET /v1/apps/{id}/appInfos`, `GET/PATCH /v1/appInfos/{id}` | Read-only: `state`, `appStoreAgeRating`, plus the deprecated country ratings. PATCH sets **categories** through relationships: `primaryCategory`, `primarySubcategoryOne/Two`, `secondaryCategory`, `secondarySubcategoryOne/Two`. | https://developer.apple.com/documentation/appstoreconnectapi/app-infos |
| Categories list | yes (read) | `GET /v1/appCategories` (+ `/{id}/subcategories`) | IDs such as `PHOTO_AND_VIDEO` | https://developer.apple.com/documentation/appstoreconnectapi/app-categories |
| appInfoLocalizations | yes | `POST /v1/appInfoLocalizations`, `GET/PATCH/DELETE /v1/appInfoLocalizations/{id}`, `GET /v1/appInfos/{id}/appInfoLocalizations` | `locale` (required), **`name` (required on create since 3.7)**, `subtitle`, `privacyPolicyUrl`, `privacyChoicesUrl`, `privacyPolicyText` (tvOS) | https://developer.apple.com/documentation/appstoreconnectapi/appinfolocalizationcreaterequest/data-data.dictionary/attributes-data.dictionary |
| Age rating | yes | `GET /v1/appInfos/{id}/ageRatingDeclaration`, `PATCH /v1/ageRatingDeclarations/{id}`, `GET /v1/appInfos/{id}/territoryAgeRatings`. **There is no `GET /v1/ageRatingDeclarations/{id}`** in Apple's list: read (and re-read after a PATCH) only through the app info. Live 2026-10-15 it answered 403. A 403 on the age-rating step makes asc_sync a browser step (App Information › Age Rating), not a failure. | See the list below | https://developer.apple.com/documentation/appstoreconnectapi/age-ratings , https://developer.apple.com/documentation/appstoreconnectapi/get-v1-appinfos-_id_-ageratingdeclaration |

**Current `AgeRatingDeclaration` attributes (PATCH)**
(source: https://developer.apple.com/documentation/appstoreconnectapi/ageratingdeclarationupdaterequest/data-data.dictionary/attributes-data.dictionary)

- **Frequency enums**: `NONE`, `INFREQUENT`, `FREQUENT`. `INFREQUENT_OR_MILD` and `FREQUENT_OR_INTENSE` are deprecated. These attributes take a frequency:
  - `alcoholTobaccoOrDrugUseOrReferences`
  - `contests`
  - `gamblingSimulated`
  - `gunsOrOtherWeapons`
  - `medicalOrTreatmentInformation`
  - `profanityOrCrudeHumor`
  - `sexualContentGraphicAndNudity`
  - `sexualContentOrNudity`
  - `horrorOrFearThemes`
  - `matureOrSuggestiveThemes`
  - `violenceCartoonOrFantasy`
  - `violenceRealistic`
  - `violenceRealisticProlongedGraphicOrSadistic`
- **Booleans**:
  - `gambling`, `lootBox`, `unrestrictedWebAccess`
  - the 2025 questionnaire additions: `advertising`, `ageAssurance`, `healthOrWellnessTopics`, `messagingAndChat`, `parentalControls`, `userGeneratedContent`
  - the 4.4.1 additions: `socialMedia`, `socialMediaAgeRestricted`
- **Other**:
  - `kidsAgeBand`, which moved here from appInfo in 4.2
  - **`ageRatingOverrideV2`**: `NONE`, `NINE_PLUS`, `THIRTEEN_PLUS`, `SIXTEEN_PLUS`, `EIGHTEEN_PLUS`, `UNRATED`. The old `ageRatingOverride` (with `SEVENTEEN_PLUS`) is deprecated.
  - `koreaAgeRatingOverride`: `NONE`, `ALL`, `TWELVE_PLUS`, `FIFTEEN_PLUS`, `NINETEEN_PLUS`
  - `gracRatingClassificationNumber`
  - `developerAgeRatingInfoUrl`
- **Removed**: `gamblingAndContests`, `seventeenPlus` (removed in 4.0).
- **Resulting rating**: `appInfo.appStoreAgeRating` uses the `AppStoreAgeRating` enum (`FOUR_PLUS` … `THIRTEEN_PLUS`, `SIXTEEN_PLUS`, `EIGHTEEN_PLUS` …, plus `ZERO_ZERO` for Vietnam).
  - Source: https://developer.apple.com/documentation/appstoreconnectapi/appstoreagerating

---

## 3. Versions

| Item | Supported | Endpoint(s) | Notes | Source |
|---|---|---|---|---|
| Create a version (including an update to a live app) | yes | `POST /v1/appStoreVersions` | Required: `platform` (`IOS`/`MAC_OS`/`TV_OS`/`VISION_OS`), `versionString`, and the `app` relationship. Optional: `copyright`, `releaseType` (`MANUAL`/`AFTER_APPROVAL`/`SCHEDULED`), `earliestReleaseDate` (for SCHEDULED), `reviewType` (`APP_STORE`/`NOTARIZATION`), `build` relationship. | https://developer.apple.com/documentation/appstoreconnectapi/appstoreversioncreaterequest/data-data.dictionary/attributes-data.dictionary |
| Modify or delete a version | yes | `PATCH` / `DELETE /v1/appStoreVersions/{id}` | PATCH covers the same fields plus `downloadable`. State is read from **`appVersionState`** (`appStoreState` is deprecated). | https://developer.apple.com/documentation/appstoreconnectapi/app-store-versions , https://developer.apple.com/documentation/appstoreconnectapi/appversionstate |
| Select a build | yes | `PATCH /v1/appStoreVersions/{id}/relationships/build` `{"data":{"type":"builds","id":…}}`, or the `build` relationship in the version PATCH | | same |
| Version localizations | yes | `POST /v1/appStoreVersionLocalizations`, `GET/PATCH/DELETE /v1/appStoreVersionLocalizations/{id}`, `GET /v1/appStoreVersions/{id}/appStoreVersionLocalizations` | `locale`, `description`, `keywords`, `promotionalText`, `marketingUrl`, `supportUrl`, `whatsNew`. `whatsNew` is not accepted on the first version (Apple's UI hides it). That last point is UNCONFIRMED in the API docs. | https://developer.apple.com/documentation/appstoreconnectapi/appstoreversionlocalizationcreaterequest/data-data.dictionary/attributes-data.dictionary |
| Phased release | yes | `POST /v1/appStoreVersionPhasedReleases` (relationship `appStoreVersion`), `PATCH`/`DELETE /v1/appStoreVersionPhasedReleases/{id}` | `phasedReleaseState`: `INACTIVE`, `ACTIVE`, `PAUSED`, `COMPLETE`. Readable: `startDate`, `currentDayNumber`, `totalPauseDuration`. | https://developer.apple.com/documentation/appstoreconnectapi/phasedreleasestate |
| **Reset ratings summary** | **NO** | No such field or path in the 4.5.1 spec | Use the browser | spec search (no "reset" anywhere) |
| Review details | yes | `POST /v1/appStoreReviewDetails` (relationship `appStoreVersion`), `GET/PATCH /v1/appStoreReviewDetails/{id}`, `GET /v1/appStoreVersions/{id}/appStoreReviewDetail` | `contactFirstName`, `contactLastName`, `contactPhone`, `contactEmail`, `demoAccountRequired`, `demoAccountName`, `demoAccountPassword`, `notes` (Help: up to 4000 **bytes**) | https://developer.apple.com/documentation/appstoreconnectapi/appstorereviewdetailcreaterequest/data-data.dictionary/attributes-data.dictionary , https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information |
| Review attachments | yes | `POST /v1/appStoreReviewAttachments` (fileName, fileSize, relationship `appStoreReviewDetail`), then upload, then `PATCH` with `uploaded:true` + `sourceFileChecksum` (MD5) | Same asset flow as §4b | https://developer.apple.com/documentation/appstoreconnectapi/uploading-assets-to-app-store-connect |
| Manual release | yes | `POST /v1/appStoreVersionReleaseRequests` (relationship `appStoreVersion`) | Only for a version in `PENDING_DEVELOPER_RELEASE` | https://developer.apple.com/documentation/appstoreconnectapi/app-store-version-release-requests |

---

## 4. Screenshots and previews

### 4a. NEW and recommended: App Asset Library (4.5.1)

Steps:

1. **Find the library**: `GET /v1/apps/{id}/assetLibrary`. This gives the `appAssetLibraries` id, which stays stable for the life of the app.
2. **Read the specs**: `GET /v1/appAssetLibraryRefData`. You can narrow it with `fields[appAssetLibraryRefData]=imageSpecs`, `filter[features]`, `filter[placementTypes]`, and so on. It returns six arrays:
   - `features`: per feature, `placementPolicies[].groupLimits[].maxCount`
   - `placementProfileGroups`: group id mapped to platform and display class
   - `imageSpecs`: exact pixel dimensions, extensions, `maxFileSize`, `alphaAllowed: false`, `universalAsset`
   - `videoSpecs`: also `frameRates`, `duration` (ISO 8601) and `audioRequired`
   - `placementTypes`: `acceptsAssetCategories` and `specMappings`
   - `displayClasses`

   **Placement group ids are runtime strings, not an enum.** Examples: `IPHONE_DYNAMIC_ISLAND_LARGE_PROFILE`, `MAC_PROFILE`, `IMESSAGE_IPHONE_DYNAMIC_ISLAND_LARGE_PROFILE`. Do not hard-code them.
3. **Reserve the asset**:
   - Image: `POST /v1/appAssetLibraryImages` with `{fileName, fileSize, category, referenceName?}` and relationship `assetLibrary`.
   - Video: `POST /v1/appAssetLibraryVideos` with the same fields plus `previewFrameTimeCode`, e.g. `"00:00:03:00"`.
   - `category` is either `APP_SCREENSHOTS_AND_PREVIEWS` or `CREATIVE_ASSETS`. It **can't be changed later**.
4. **Upload**: PUT each `uploadOperations[]` item (`method`, `url`, `offset`, `length`, `requestHeaders`). No JWT. Parts can go in parallel.
5. **Commit**: `PATCH /v1/appAssetLibraryImages/{id}` (or `…Videos/{id}`) with `{"uploaded": true}`. **No `sourceFileChecksum` in the new flow.** The server checks the byte count against `fileSize`.
6. **Poll `state`**: `AWAITING_UPLOAD`, then `UPLOAD_COMPLETE`, then **`PREPARE_FOR_SUBMISSION`**, which means ready to place. On `FAILED`, read `stateDetails`. The response also carries `specId` (the spec your file matched) and `imageAsset.templateUrl`. For videos, `previewFrameImage.state` is `PROCESSING`/`COMPLETE`/`FAILED`.
7. **Place**: `POST /v1/appAssetLibraryPlacements` with:
   - `placementType` + `placementGroup`
   - **exactly one** of `image` / `video`
   - **exactly one** target: `appStoreVersionLocalization`, `appCustomProductPageLocalization`, `appEventLocalization`, or `appStoreVersionExperimentTreatmentLocalization`

   Placements are immutable. To replace one, delete it and create a new one. The parent must be editable; placing on an approved version returns 409 `STATE_ERROR.INVALID_STATE`.
8. **Order**: `POST /v1/appAssetLibraryPlacementOrderingRequests` with `{placementGroup}` and relationships `orderedPlacements[]` + the localization. You order one group per localization at a time. To read the order back, use `GET /v1/appStoreVersionLocalizations/{id}/placements?sort=placementGroupPosition&include=image`.
9. **Limits** for App Store versions: **10 screenshots, 3 previews and 1 product page header per group**. Read the real values from `groupLimits`.
10. **Delete**: delete the placements first, then the asset. Deleting an asset that still has placements returns 409 `STATE_ERROR.ASSET_HAS_PLACEMENTS`. Archiving (`archived:true`) works only on APPROVED assets.
11. **Review**: placements go through review with their parent. Standalone asset review is also possible with a `reviewSubmissionItems` relationship `appAssetLibraryImage` / `appAssetLibraryVideo`.

Apple Watch (kit folder `screenshots/<locale>/watch/`): asc_sync picks the display class per file by its pixel size,
and the placement group from `placementProfileGroups` with platform `WATCH_APP_STORE`
(`AppAssetLibraryPlacementPlatform`: `IPHONE_APP_STORE`, `IPAD_APP_STORE`, `WATCH_APP_STORE`, `IMESSAGE_APP_STORE`,
`VISION_PRO_APP_STORE`, `MAC_APP_STORE`, `TV_APP_STORE`, `ANY`):

| Pixels (portrait) | Watch | Display class |
|---|---|---|
| 422 × 514 | Ultra 3 | `WATCH_ULTRA` (UNCONFIRMED: the enum has one Ultra class) |
| 410 × 502 | Ultra, Ultra 2 | `WATCH_ULTRA` |
| 416 × 496 | Series 10/11, 46 mm | `WATCH_SERIES_10` |
| 396 × 484 | Series 7/8/9, 45 mm | `WATCH_SERIES_7` |
| 368 × 448 | Series 4-6, SE, 44 mm | `WATCH_SERIES_4` |
| 312 × 390 | Series 3, 42 mm | `WATCH_SERIES_3` |

UNCONFIRMED: the live watch group ids (the kit's test fake uses `WATCH_SERIES_10_PROFILE`; asc_sync only ever reads
them from the ref data) and whether the ref data lists watch groups for an iOS app record with an embedded watch app.
A file of another size is skipped with a warning. Source:
https://developer.apple.com/documentation/appstoreconnectapi/appassetlibraryplacementplatform

Enums:
- **`AppAssetLibraryPlacementType`**: `APP_SCREENSHOT`, `IMESSAGE_APP_SCREENSHOT`, `APP_PREVIEW`, `PRODUCT_PAGE_HEADER_ASSET`, `APP_STORE_SEARCH_RESULTS_ASSET`, `SEARCH_RESULTS_ADS_ASSET`, `TODAY_TAB_ADS_ASSET`, `EVENT_CARD_ASSET`, `EVENT_DETAILS_PAGE_ASSET`, `RETENTION_MESSAGE_ASSET`
- **`AppAssetLibraryDisplayClass`**: `DEFAULT`, `WATCH_ULTRA`, `WATCH_SERIES_10/7/4/3`, **`IPHONE_DUO`**, `IPHONE_DYNAMIC_ISLAND_LARGE_DISPLAY`, `IPHONE_DYNAMIC_ISLAND_MEDIUM_DISPLAY`, `IPHONE_FACE_ID_LARGE/MEDIUM_DISPLAY`, `IPHONE_HOME_BUTTON_LARGE/MEDIUM/40/35_DISPLAY`, `IPAD_13/11/129/105/97_DISPLAY`
- **`AppAssetLibraryFeature`**: `APP_STORE_VERSIONS`, `CUSTOM_PRODUCT_PAGES`, `PRODUCT_PAGE_OPTIMIZATIONS`, `IN_APP_EVENTS`, `IN_APP_PURCHASES`, `SUBSCRIPTIONS`, `RETENTION_MESSAGING`, `GAME_CENTER`, `APP_CLIPS`, `APPLE_ADS`
- **Placement states**: `ASSET_PROCESSING`, `FAILED`, `PARENT_PREPARE_FOR_SUBMISSION` … `PARENT_APPROVED`

Sources:
- https://developer.apple.com/documentation/appstoreconnectapi/understanding-the-app-asset-library
- https://developer.apple.com/documentation/appstoreconnectapi/uploading-and-managing-image-assets
- https://developer.apple.com/documentation/appstoreconnectapi/uploading-and-managing-video-assets
- https://developer.apple.com/documentation/appstoreconnectapi/placing-assets-on-your-app-store-surfaces
- https://developer.apple.com/documentation/appstoreconnectapi/discovering-asset-specifications
- https://developer.apple.com/documentation/appstoreconnectapi/migrating-to-the-app-asset-library
- https://developer.apple.com/documentation/appstoreconnectapi/appassetlibraryplacementtype
- https://developer.apple.com/documentation/appstoreconnectapi/appassetlibrarydisplayclass

### 4b. DEPRECATED (still works): set-based flow

1. `POST /v1/appScreenshotSets` with `{screenshotDisplayType}` and relationship `appStoreVersionLocalization`.
2. `POST /v1/appScreenshots` with `{fileName, fileSize}` and relationship `appScreenshotSet`. This returns `uploadOperations`.
3. PUT the chunks.
4. `PATCH /v1/appScreenshots/{id}` with `{uploaded:true, sourceFileChecksum:<MD5 of the whole file>}`.
5. Poll `assetDeliveryState.state`: `AWAITING_UPLOAD`, then `UPLOAD_COMPLETE`, then `COMPLETE` or `FAILED`. FAILED is terminal: delete and retry. Reservations expire after about a week (the `Expires` parameter in the URL).
6. Order with `PATCH /v1/appScreenshotSets/{id}/relationships/appScreenshots` (ordered id list).

Previews work the same way with `appPreviewSets` (`previewType`) and `appPreviews`. Options: `previewFrameTimeCode` and `mimeType`. Read state from `videoDeliveryState`; `assetDeliveryState` and `previewImage` are deprecated since 3.7 in favour of `previewFrameImage`.

Sources:
- https://developer.apple.com/documentation/appstoreconnectapi/uploading-assets-to-app-store-connect
- https://developer.apple.com/documentation/appstoreconnectapi/uploading-app-previews

**`ScreenshotDisplayType` (2026)**
- `APP_IPHONE_67`, `_65`, `_61`, `_58`, `_55`, `_47`, `_40`, `_35`
- `APP_IPAD_PRO_3GEN_129`, `APP_IPAD_PRO_3GEN_11`, `APP_IPAD_PRO_129`, `APP_IPAD_105`, `APP_IPAD_97`
- `APP_WATCH_ULTRA`, `APP_WATCH_SERIES_10`, `_7`, `_4`, `_3`
- `APP_DESKTOP`, `APP_APPLE_TV`, `APP_APPLE_VISION_PRO`
- `IMESSAGE_APP_*` (iPhone 67…40, iPad sizes)

**There is NO iPhone Duo value.** iPhone Duo is only in the Asset Library (`IPHONE_DUO`).

**`PreviewType`**: `IPHONE_67`, `61`, `65`, `58`, `55`, `47`, `40`, `35`, `IPAD_PRO_3GEN_129`, `IPAD_PRO_3GEN_11`, `IPAD_PRO_129`, `IPAD_105`, `IPAD_97`, `DESKTOP`, `APPLE_TV`, `APPLE_VISION_PRO`.

Sources:
- https://developer.apple.com/documentation/appstoreconnectapi/screenshotdisplaytype
- https://developer.apple.com/documentation/appstoreconnectapi/previewtype

**Help specs (2026)**
Source: https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications

- Required screenshots: iPhone **with Dynamic Island (medium display)**, and iPad 13-inch if the app supports iPad.
- Format: 1–10 images per size, .jpeg/.jpg/.png, no alpha.
- iPhone Duo:
  - outer display 1398×2034 / 2034×1398
  - inner display 2007×2853 / 2853×2007
  - "Starting in April 2027, screenshots will be required for any app using the iOS 27.1 SDK or later."
- 6.9-inch large Dynamic Island: 1260×2736, 1290×2796, 1320×2868.
- 6.3-inch medium: 1179×2556, 1206×2622.
- Smaller sizes are scaled down automatically from the largest one you provide.

---

## 5. Localization

- **Accepted locale codes (50 languages)**: ar-SA, bn-BD, ca, zh-Hans, zh-Hant, hr, cs, da, nl-NL, en-AU, en-CA, en-GB, en-US, fi, fr-FR, fr-CA, de-DE, el, gu-IN, he, hi, hu, id, it, ja, kn-IN, ko, ms, ml-IN, mr-IN, no, or-IN, pl, pt-BR, pt-PT, pa-IN, ro, ru, sk, sl-SI, es-MX, es-ES, sv, ta-IN, te-IN, th, tr, uk, ur-PK, vi.
  - Source: https://developer.apple.com/documentation/appstoreconnectapi/managing-metadata-in-your-app-by-using-locale-shortcodes
- **Adding a locale**:
  - Version level: `POST /v1/appStoreVersionLocalizations` (`locale` + relationship `appStoreVersion`).
  - App level: `POST /v1/appInfoLocalizations` (`locale` + `name` required + relationship `appInfo`).
  - When added in the UI, a version-level locale is added to the shared App Information automatically. The API doesn't document whether it does the same (UNCONFIRMED), so create both explicitly.
- **Fallbacks** (Help):
  - A new language's screenshots and properties **default to the primary language's, except description and keywords**.
  - Storefronts without your language show the primary language.
  - A missing app preview falls back to the "next best available language".
  - Sources: https://developer.apple.com/help/app-store-connect/manage-app-information/localize-app-information , screenshot-specifications page
- **Limits** (Help):

  | Field | Limit |
  |---|---|
  | name | 2–30 characters |
  | subtitle | 30 characters |
  | keywords | **100 bytes** |
  | promotionalText | 170 characters |
  | description | 4000 characters, plain text |
  | whatsNew | 4000 characters |
  | review notes | 4000 bytes |

  The API docs give no maxLength. Validate on your side.
  - Sources: https://developer.apple.com/help/app-store-connect/reference/app-information/app-information , https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information

---

## 6. In-app purchases (v2, version-based since 4.4.1)

> Kit notes (2026-10-15, UNCONFIRMED shapes): price changes POST `/v1/inAppPurchasePriceSchedules` with
> `inAppPurchase`, `baseTerritory`, `manualPrices` and inline `inAppPurchasePrices` (startDate null; the price point
> from `GET /v2/inAppPurchases/{id}/pricePoints?filter[territory]=…`). A later purchase goes to review as a
> `reviewSubmissionItems` `inAppPurchaseVersion`; an unversioned one through the `inAppPurchaseV2` relationship.
> Clearing keywords and review notes sends null ("" is the fallback). asc_api refuses any redirect that would carry
> the token to another origin.

Source: https://developer.apple.com/documentation/appstoreconnectapi/managing-in-app-purchases

| Step | Endpoint | Notes |
|---|---|---|
| Create the IAP | `POST /v2/inAppPurchases` | `name`, `productId`, `inAppPurchaseType` (CONSUMABLE / NON_CONSUMABLE / NON_RENEWING_SUBSCRIPTION), `reviewNote`, `familySharable`, relationship `app`. List them with `GET /v1/apps/{id}/inAppPurchasesV2`. |
| Version (draft container) | `POST /v1/inAppPurchaseVersions` (relationship `inAppPurchase`); list with **`GET /v2/inAppPurchases/{id}/versions`** (the relationship is `versions`, not `inAppPurchaseVersions`: that name answers 404 "The relationship 'inAppPurchaseVersions' does not exist") | States (`InAppPurchaseVersion.state`): PREPARE_FOR_SUBMISSION, READY_FOR_REVIEW, WAITING_FOR_REVIEW, IN_REVIEW, ACCEPTED, APPROVED, REPLACED_WITH_NEW_VERSION, REJECTED, DEVELOPER_REJECTED. Only PREPARE_FOR_SUBMISSION takes edits. The POST documents 409: a second version beside the in-flight one is refused (live 2026-10-15), so asc_sync reuses the editable version, makes a new one only when none is in flight, and skips (with a warning) a purchase whose version is READY_FOR_REVIEW / WAITING_FOR_REVIEW / IN_REVIEW. UNCONFIRMED: whether a new version copies the previous version's localizations (asc_sync looks for each locale on it first, then creates). Source: https://developer.apple.com/documentation/appstoreconnectapi/working-with-in-app-purchase-versions |
| Localizations | `POST /v2/inAppPurchaseLocalizations` (`locale`, `name`, `description`, relationship **`version`** → `inAppPurchaseVersions`); `GET`/`PATCH`/`DELETE /v2/inAppPurchaseLocalizations/{id}`; list with **`GET /v1/inAppPurchaseVersions/{id}/localizations`** | Deprecated but still working for a purchase with no `versions`: `POST /v1/inAppPurchaseLocalizations` (relationship `inAppPurchaseV2`), `PATCH /v1/inAppPurchaseLocalizations/{id}`, list `GET /v2/inAppPurchases/{id}/inAppPurchaseLocalizations`. A locale that is already there is changed, not posted again (asc_sync re-reads on a 409). Sources: https://developer.apple.com/documentation/appstoreconnectapi/post-v2-inapppurchaselocalizations , https://developer.apple.com/documentation/appstoreconnectapi/migrating-in-app-purchase-metadata-to-v2 |
| Review screenshot or images | Old: `POST /v1/inAppPurchaseAppStoreReviewScreenshots`, then PUT, then PATCH (`uploaded` + MD5). New: version-scoped `POST /v2/inAppPurchaseImages` (relationship **`version`**) (+ `GET /v1/inAppPurchaseVersions/{id}/image`). | Apple's own docs disagree on which one carries the *review* screenshot. Support both; prefer v2 (UNCONFIRMED). |
| Price | `GET /v2/inAppPurchases/{id}/pricePoints?filter[territory]=USA`, then `POST /v1/inAppPurchasePriceSchedules` | Relationships `inAppPurchase`, `baseTerritory`, `manualPrices[]`, with `included` inline `inAppPurchasePrices` (`startDate` null = now). Price increases can't be reverted. |
| Availability | `POST /v1/inAppPurchaseAvailabilities` | `availableInNewTerritories` + `availableTerritories[]` |
| Submit (later IAPs) | `POST /v1/reviewSubmissions`, then `POST /v1/reviewSubmissionItems` with `inAppPurchaseVersion`, then `PATCH submitted:true` | `POST /v1/inAppPurchaseSubmissions` is deprecated in 4.4.1 |
| **Submit the FIRST IAP** | **Browser.** Apple: "Submit your first In-App Purchase together with an app binary submission through appstoreconnect.apple.com. The review-submission API calls … don't apply to that first submission." | Gap. The skill should hand this step to the person (select the IAP on the version page before submitting). |
| Promoted purchases | `POST /v1/promotedPurchases` | `promotedPurchaseImages` were **removed** in 3.8 and replaced by IAP and subscription images |

Subscriptions follow the same pattern: `subscriptionGroups`, `subscriptions`, `subscriptionVersions`, `subscriptionGroupVersions`. 4.4 added `subscriptionPlanAvailabilities` (for monthly plans with a 12-month commitment).

---

## 7. App pricing and availability

| Item | Supported | Endpoint(s) | Source |
|---|---|---|---|
| Price | yes | `GET /v1/apps/{id}/appPricePoints?filter[territory]=USA`, then `POST /v1/appPriceSchedules` with relationships `app`, `baseTerritory`, `manualPrices[]` and `included` `appPrices` (inline `AppPriceV2InlineCreate`, `startDate`/`endDate`). Free = the 0.00 price point. | https://developer.apple.com/documentation/appstoreconnectapi/apps |
| Territories (v2) | yes | `POST /v2/appAvailabilities` with `availableInNewTerritories` + `territoryAvailabilities[]` (inline). Read with `GET /v1/apps/{id}/appAvailabilityV2` and `GET /v2/appAvailabilities/{id}/territoryAvailabilities`. Change one territory with `PATCH /v1/territoryAvailabilities/{id}` (`available`, `releaseDate`, `preOrderEnabled`). End a pre-order with `POST /v1/endAppAvailabilityPreOrders`. `contentStatuses` shows blockers such as `TRADER_STATUS_NOT_PROVIDED`, `BRAZIL_REQUIRED_TAX_ID`, `ICP_NUMBER_MISSING`, `MISSING_RATING`. v1 `appAvailabilities` and `appPreOrders` were removed in 3.7. | https://developer.apple.com/documentation/appstoreconnectapi/app-availability |
| iPhone/iPad app on Apple silicon Mac (store availability) | **NO** | Not in the spec. The only flag is `betaGroups.iosBuildsAvailableForAppleSiliconMac` (TestFlight). Use the browser: Pricing and Availability, then "iPhone and iPad Apps on Apple Silicon Mac". | https://developer.apple.com/help/app-store-connect/manage-your-apps-availability/manage-availability-of-iphone-and-ipad-apps-on-macs-with-apple-silicon |
| iPhone/iPad app on Apple Vision Pro (store availability) | **NO** (spec) | Only `betaGroups.iosBuildsAvailableForAppleVision` (TestFlight). Use the browser. | spec search |

---

## 8. Submission

| Item | Endpoint | Notes | Source |
|---|---|---|---|
| Create a submission | `POST /v1/reviewSubmissions` (relationship `app`; `platform` optional since 4.1) | | https://developer.apple.com/documentation/appstoreconnectapi/review-submissions |
| Add items | `POST /v1/reviewSubmissionItems` (relationship `reviewSubmission` + one of `appStoreVersion`, `appCustomProductPageVersion`, `appEvent`, `appStoreVersionExperimentV2`, `inAppPurchaseVersion`, `subscriptionVersion`, `subscriptionGroupVersion`, `appAssetLibraryImage`, `appAssetLibraryVideo`, `backgroundAssetVersion`, Game Center versions); remove with `DELETE /v1/reviewSubmissionItems/{id}` | | https://developer.apple.com/documentation/appstoreconnectapi/reviewsubmissionitemcreaterequest/data-data.dictionary/relationships-data.dictionary |
| Submit | `PATCH /v1/reviewSubmissions/{id}` `{submitted:true}` | Fails with errors if anything required is missing | ReviewSubmissionUpdateRequest |
| Cancel | `PATCH /v1/reviewSubmissions/{id}` `{canceled:true}` | | same |
| Old flow | `POST /v1/appStoreVersionSubmissions` was **removed in 4.0**. Only a deprecated `DELETE` remains. | | 4.0 release notes |
| Release | `POST /v1/appStoreVersionReleaseRequests` | | §3 |
| Status | Poll `appVersionState`, or use the webhook `APP_STORE_VERSION_APP_VERSION_STATE_UPDATED` | | https://developer.apple.com/documentation/appstoreconnectapi/webhook-notifications |

---

## 9. Builds and TestFlight

| Item | Supported | Endpoint(s) and attributes | Source |
|---|---|---|---|
| List builds | yes | `GET /v1/builds?filter[app]=…&filter[version]=…&filter[preReleaseVersion.version]=…`, `GET /v1/apps/{id}/builds`. Attributes: `version` (CFBundleVersion), `processingState` (`PROCESSING`/`FAILED`/`INVALID`/`VALID`), `uploadedDate`, `expired`, `minOsVersion`, `usesNonExemptEncryption`, `buildAudienceType` | spec, https://developer.apple.com/documentation/appstoreconnectapi/builds |
| Encryption | yes | `PATCH /v1/builds/{id}` `{usesNonExemptEncryption:false}` (or set `ITSAppUsesNonExemptEncryption` in Info.plist). Declarations: `POST /v1/appEncryptionDeclarations` (`appDescription`, `containsProprietaryCryptography`, `containsThirdPartyCryptography`, `availableOnFrenchStore`), plus `appEncryptionDeclarationDocuments` upload. Assign with `PATCH /v1/builds/{id}/relationships/appEncryptionDeclaration`. | spec; https://developer.apple.com/documentation/appstoreconnectapi/app-encryption-declarations |
| Attach a build to a version | yes | `PATCH /v1/appStoreVersions/{id}/relationships/build` | §3 |
| Beta app info | yes | `betaAppLocalizations` (`description` is **required before external beta review** since 3.7, plus `feedbackEmail`, `marketingUrl`, `privacyPolicyUrl`), `betaBuildLocalizations` (`whatsNew`), `betaAppReviewDetails` (contact and demo account), `betaGroups` (+ `/relationships/builds`, `/betaTesters`), `betaAppReviewSubmissions` (POST with relationship `build`), `buildBetaNotifications`, `betaRecruitmentCriteria` | https://developer.apple.com/documentation/appstoreconnectapi/prerelease-versions-and-beta-testers |
| **Upload a binary through the REST API** | **YES (since 4.1, WWDC25)** | See the flow below | https://developer.apple.com/documentation/appstoreconnectapi/build-uploads , https://developer.apple.com/videos/play/wwdc2025/324/ |

**REST build upload flow**
1. `POST /v1/buildUploads` with `cfBundleShortVersionString`, `cfBundleVersion`, `platform`, and relationship `app`.
2. `POST /v1/buildUploadFiles` with `fileName`, `fileSize`, `assetType` (`ASSET` / `ASSET_DESCRIPTION` / `ASSET_SPI`), `uti` (`com.apple.ipa` / `com.apple.pkg` / plist / zip) and relationship `buildUpload`. This returns `uploadOperations`.
3. PUT the chunks.
4. `PATCH /v1/buildUploadFiles/{id}` with `uploaded:true` + `sourceFileChecksums` (an MD5 checksum in the `file` sub-object, UNCONFIRMED).
5. Poll `GET /v1/buildUploads/{id}`: `state.state` is `AWAITING_UPLOAD`, `PROCESSING`, `FAILED` or `COMPLETE`, with `errors`/`warnings`/`infos`. Alternatively use the webhook `BUILD_UPLOAD_STATE_UPDATED`, which is signed with HMAC-SHA256 in `X-Apple-SIGNATURE`.

Apple has no worked example for a plain .ipa. When an `ASSET_DESCRIPTION` or `ASSET_SPI` file is required is UNCONFIRMED. The `apps` page still says "This API doesn't permit you to directly upload your builds", which is stale and contradicts the 4.1 notes.

**Recommendation:** use the CLI tools below as the primary path and REST as optional/experimental.

**Build facts from Help (read 2026-10-14)**, https://developer.apple.com/help/app-store-connect/manage-builds/view-builds-and-metadata :
- The web statuses are Processing, Failed and Complete. After a **Failed** upload the same build number can be reused.
- Processing for more than 24 hours means something is wrong: file Feedback Assistant (Developer Tools & Resources › TestFlight).
- A yellow warning (and an email) appears when a device variant exceeds the **200 MB** over-the-air download limit.
- Complete builds can still carry warnings; read `warnings` on the `buildUploads` state before the next upload.

**Recommended commands (verified against local Xcode 27.0 / altool 27.0.5 `--help`)**

```sh
# 1) archive
xcodebuild -scheme <Scheme> -configuration Release -destination 'generic/platform=iOS' \
  -archivePath build/App.xcarchive archive \
  -allowProvisioningUpdates -authenticationKeyPath AuthKey_<KID>.p8 \
  -authenticationKeyID <KID> -authenticationKeyIssuerID <ISSUER>

# 2a) export AND upload in one step (ExportOptions.plist: method=app-store-connect, destination=upload,
#     optional manageAppVersionAndBuildNumber=NO, uploadSymbols=YES, testFlightInternalTestingOnly=NO)
xcodebuild -exportArchive -archivePath build/App.xcarchive -exportOptionsPlist ExportOptions.plist \
  -exportPath build/export -allowProvisioningUpdates \
  -authenticationKeyPath AuthKey_<KID>.p8 -authenticationKeyID <KID> -authenticationKeyIssuerID <ISSUER>

# 2b) or export with destination=export, then upload the .ipa with altool
xcrun altool --validate-app build/export/App.ipa --api-key <KID> --api-issuer <ISSUER> --p8-file-path AuthKey_<KID>.p8
xcrun altool --upload-package build/export/App.ipa --api-key <KID> --api-issuer <ISSUER> --p8-file-path AuthKey_<KID>.p8 --wait --output-format json
xcrun altool --build-status --apple-id <APP_ID> --bundle-version <CFBundleVersion> --bundle-short-version-string <ver> --platform ios --api-key <KID> --api-issuer <ISSUER> --wait
```

Notes:
- `method` values: `app-store-connect`, `release-testing`, `enterprise`, `debugging`, `developer-id`, `mac-application`, `validation`. `app-store` is deprecated.
- altool looks for `AuthKey_<KID>.p8` in `./private_keys`, `~/private_keys`, `~/.private_keys`, `~/.appstoreconnect/private_keys` and `$API_PRIVATE_KEYS_DIR`.
- New in altool 27: `--app-store-text <folder> --upload|--download` and `--beta-app-store-text`, which push or pull version text metadata. The folder format is undocumented in `--help` (UNCONFIRMED).
- Transporter.app / iTMSTransporter is still needed only for Aspera/Signiant (`--transport`).

---

## 10. Gaps (not in the public API 4.5.1: use the browser or the person)

| Area | In API? | Unofficial route | Skill action |
|---|---|---|---|
| **App Privacy "nutrition label"** (data types, purposes, linked/tracking) + Publish | **NO**. No path or schema in the spec. | fastlane `upload_app_privacy_details_to_app_store` uses the private web session (spaceship) and **needs an Apple ID with owner/admin**. fastlane: "not available on the official App Store Connect API so the App Store Connect API Key cannot be used". https://docs.fastlane.tools/uploading-app-privacy-details/ | Browser or person (Help: https://developer.apple.com/help/app-store-connect/manage-app-information/manage-app-privacy). The privacy policy URL itself *is* in the API (`appInfoLocalizations.privacyPolicyUrl`). |
| **Accessibility Nutrition Labels** | **YES (4.0)** | — | `POST /v1/accessibilityDeclarations` with `deviceFamily` (`IPHONE`/`IPAD`/`APPLE_TV`/`APPLE_WATCH`/`MAC`/`VISION`) + `supports*` booleans (`Voiceover`, `VoiceControl`, `LargerText`, `DarkInterface`, `DifferentiateWithoutColorAlone`, `SufficientContrast`, `ReducedMotion`, `Captions`, `AudioDescriptions`); omitted ones default to false. `PATCH` with `publish:true`. Help: you can only publish for devices with a **live** version, so for a new app publish after the first release. `accessibilityUrl` is set on `PATCH /v1/apps/{id}`. https://developer.apple.com/documentation/appstoreconnectapi/accessibility-declarations , https://developer.apple.com/help/app-store-connect/manage-app-accessibility/manage-accessibility-nutrition-labels |
| Agreements (Paid Apps acceptance), tax, banking | **NO** | none | **Person (Account Holder)** in Business. You can't create an IAP or paid app until the latest Paid Apps Agreement is accepted. https://developer.apple.com/help/app-store-connect/manage-agreements/sign-and-update-agreements |
| EU DSA trader status, per-app trader toggle, labels & markings URL | **NO** (read-only effect: `territoryAvailabilities.contentStatuses` `TRADER_STATUS_*`) | none | Person (Account Holder/Admin; 2FA email/phone verification + documents). https://developer.apple.com/help/app-store-connect/manage-compliance-information/manage-european-union-digital-services-act-trader-requirements |
| Other "App Store Regulations and Permits" (e.g. regulated medical device declaration, Korea GRAC is partly via `gracRatingClassificationNumber`, China ICP number) | **NO** (except the GRAC number) | fastlane PR #30271 (open, 2026-09-26) reads the medical device declaration via spaceship | Browser. |
| "Digital goods questionnaire" | Not found in the spec or docs (UNCONFIRMED what this refers to) | — | Browser. |
| Create the app record | **NO** | Xcode/Xcode Cloud "Set Up Distribution"; fastlane `produce` (spaceship) | Browser or person. |
| Reset rating summary | **NO** | — | Browser. |
| Apple silicon Mac / Vision Pro store availability of iOS apps | **NO** | — | Browser. |
| First IAP or subscription submission with the first binary | **NO** (Apple's docs) | — | Browser: the purchase's own page › Add for Review (live page, 2026-10-14; the version page's section is gone), then submit the version with it. |
| App Review messages, rejection reasons, replies, appeals | **NO** (no path or schema in 4.5.1) | — | Browser; `scripts/rejection.py`, references/rejection-handling.md |
| Product page optimization results (impressions, conversion, lift) | **NO** (tests carry only name, state, dates) | — | App Analytics in the browser; `scripts/asc_reports.py` covers custom product pages and sources |

**Client safety (asc_api.py):** the JWT is attached only to `https://api.appstoreconnect.apple.com`; `links.next` or
any absolute URL on another origin is refused. Pre-signed upload and report-download URLs carry their own auth and get
no JWT.

**UNCONFIRMED, used by asc_sync.py (verify on the next live read-only run):** the `include=` names on
`reviewSubmissionItems`; sending `null` to clear optional texts and a custom product page's `deepLink`;
`sourceFileChecksum` on Asset Library assets; the list paths for IAP versions and localizations.
| Swapping header/search-results assets on an already-live version ("Publish" without a new version) | Not documented. Placements on approved parents return 409. | — | Browser (UNCONFIRMED whether the API can do it). The Help page (read 2026-10-14) documents the UI: live version › Header and Search Results › Header or Search Results › **Browse Assets** › an **approved** asset › **Next** › **Publish**. https://developer.apple.com/help/app-store-connect/manage-app-information/manage-your-app-store-assets |

---

## 11. Rate limits, errors, pagination

- **Rate limit**: every response has `X-Rate-Limit: user-hour-lim:3500;user-hour-rem:500;` (example values). The window is a **rolling hour per API key**. Over the limit you get **429 `RATE_LIMIT_EXCEEDED`**. Back off and requeue.
  - Source: https://developer.apple.com/documentation/appstoreconnectapi/identifying-rate-limits
- **Errors**: `{"errors":[{id, status, code, title, detail, source:{pointer}|{parameter}, links, meta}]}`.
  - `code` is hierarchical, e.g. `ENTITY_ERROR.ATTRIBUTE.INVALID`, `STATE_ERROR.INVALID_STATE`, `STATE_ERROR.ASSET_HAS_PLACEMENTS`.
  - Branch on the HTTP status first, then on `code`.
  - Source: https://developer.apple.com/documentation/appstoreconnectapi/interpreting-and-handling-errors
- **Pagination**: `?limit=` (max **200** on most collections), `links.next` (follow it as is; it holds `cursor`), and `meta.paging.{total, limit, nextCursor}`. Use `include=` / `fields[type]=` / `limit[relationship]=` to cut calls.
  - Source: https://developer.apple.com/documentation/appstoreconnectapi/large-data-sets ; spec `PagingInformation`.
- **Webhooks** (4.0+): `POST /v1/webhooks` (url, secret, eventTypes).
  - Events: `APP_STORE_VERSION_APP_VERSION_STATE_UPDATED`, `BUILD_UPLOAD_STATE_UPDATED`, `BUILD_BETA_DETAIL_EXTERNAL_BUILD_STATE_UPDATED`, `BETA_FEEDBACK_*`, background-asset and alt-distribution events.
  - Payloads are HMAC-SHA256 signed in `X-Apple-SIGNATURE`.
  - They need a public HTTPS listener, which is likely overkill for a CLI skill; polling is fine.

---

## 12. Tools

- **fastlane** is actively maintained: release 2.241.0 on 2026-10-10.
  - Source: https://github.com/fastlane/fastlane/releases
  - `deliver` (metadata + screenshots + submit) and `pilot` (TestFlight) use the official API key where possible. `precheck` lints metadata for rejected words and placeholder text.
  - App privacy and app creation (`produce`) still use the private Apple ID session.
  - Asset Library and header/search-result support is **not merged yet**: PR #30442 was opened 2026-10-12. Source: https://github.com/fastlane/fastlane/pull/30442
- **Apple's CLI tools**: `xcodebuild` (archive / exportArchive + upload with API key flags), `xcrun altool` 27 (upload / validate / build-status / app-store-text / list-apps / generate-jwt), and Transporter / iTMSTransporter.
- **Xcode Cloud** (WWDC26 session 261): it can now create the app record, register the bundle ID and SKU during "Set Up Distribution", and has its own webhooks. It is driven through `ciProducts` / `ciWorkflows` / `ciBuildRuns` in the API.
  - Source: https://developer.apple.com/videos/play/wwdc2026/261/
- **Recommendation**: a small Python client (PyJWT[crypto] + `requests` or urllib) is enough.
  - Generate the token per process and reuse it for 20 minutes.
  - Write one helper for the reserve-PUT-commit pattern; it serves Asset Library images and videos, review attachments, IAP images and build files.
  - Add a pager that follows `links.next`.
  - Add 429 backoff.

---

## 13. WWDC26 (June 2026) App Store Connect news and API coverage

Help pages read 2026-10-14 add: creative assets are optional and separate from screenshots, previews, IAP images and editorial artwork; they show on iOS/iPadOS 27 or later; an asset can be submitted standalone only after the app has an approved version (the first time it goes with the first version); and a standalone asset is reviewed against the app's latest version. Asset statuses in the web UI: Uploading, Processing, Prepare for Submission, Ready for Review, Waiting for Review, In Review, Accepted, Approved, Rejected, Archived (https://developer.apple.com/help/app-store-connect/reference/app-information/app-store-asset-statuses). The product page optimization page says PPO tests app icons, screenshots and previews; the asset best-practices page adds header visuals.

| Feature | What it is | API coverage | Source |
|---|---|---|---|
| **Product Page Header** + **Search Results** asset ("Header and Search Results" tab; called "creative assets") | Image or video above the product page and in search results; iOS/iPadOS 27+. A "universal" asset can serve both. | **Yes**: Asset Library placements `PRODUCT_PAGE_HEADER_ASSET`, `APP_STORE_SEARCH_RESULTS_ASSET`, category `CREATIVE_ASSETS`, 1 header per group | https://developer.apple.com/videos/play/wwdc2026/205/ , https://developer.apple.com/help/app-store-connect/manage-app-information/manage-your-app-store-assets |
| **Asset Library** | Central store; standalone review of assets; approved assets reusable without re-review; live header swap without a new version (UI) | **Yes** (4.5.1). Standalone submission via `reviewSubmissionItems` `appAssetLibraryImage/Video`. Live swap via API: UNCONFIRMED. | same + 4.5.1 notes |
| **iPhone Duo** screenshots/previews | Outer 1398×2034, inner 2007×2853 (+ landscape) | **Asset Library only** (`IPHONE_DUO` display class; group ids from ref data). Not in `ScreenshotDisplayType`. | 4.5.1 notes; screenshot-specifications Help |
| Product page **Preview** tool | See the page before review | UI only (no API found) | session 205 |
| Custom Product Pages | Now get header/search assets and deep links (`deepLink` since 3.5) | **Yes**: `appCustomProductPages` / `…Versions` / `…Localizations` + placements (target `appCustomProductPageLocalization`) + `reviewSubmissionItems.appCustomProductPageVersion` | spec; 3.5 notes |
| Product Page Optimization | A/B tests | **Yes**: `/v2/appStoreVersionExperiments` + treatments + treatment localizations (+ placements); v1 experiments deprecated | spec |
| Apple Ads assets (`SEARCH_RESULTS_ADS_ASSET`, `TODAY_TAB_ADS_ASSET`) | Ads creatives | Placement types exist; ad setup itself goes through the separate Apple Ads Platform API | session 205 |
| Retention Messaging | Session 309 | `RETENTION_MESSAGE_ASSET` placement type exists; the rest is outside this research | https://developer.apple.com/videos/play/wwdc2026/309/ |

---

### Skill design takeaways

1. Automate these through the API:
   - auth
   - app info, categories and age rating
   - versions, localizations and review details
   - Asset Library screenshots/previews (including iPhone Duo and header/search assets)
   - pricing and availability
   - accessibility labels
   - encryption
   - build attach
   - TestFlight
   - review submission and release
2. Upload the binary with `xcodebuild -exportArchive` (destination=upload) or `altool --upload-package` using the API key. Treat REST `buildUploads` as optional.
3. These steps go to the browser or the person:
   - create the app record
   - Paid Apps agreement, tax and banking
   - DSA trader status
   - App Privacy label
   - first-IAP selection on the version
   - Apple silicon Mac and Vision Pro availability
   - reset ratings
   - other regulatory declarations


## Live findings (first real run, 2026-10-14)

Read on a live account with an App Manager team key. They override anything above that disagrees.

- **Token lifetime:** Apple checks `exp` against its own clock. With the Mac 0.75 s fast, `exp = iat + 1200` was
  refused intermittently (401 NOT_AUTHORIZED). Use about 18 minutes (`asc_api.DEFAULT_LIFETIME = 1080`).
- **`GET /v1/appAssetLibraryRefData` without a filter returns 401.** With `filter[placementTypes]=APP_SCREENSHOT,APP_PREVIEW`
  it returns one object whose attributes are `features`, `placementProfileGroups`, `imageSpecs`, `videoSpecs`,
  `placementTypes`, `displayClasses`. Groups look like
  `{"placementProfileGroupId": "IPHONE_DYNAMIC_ISLAND_MEDIUM_PROFILE", "platform": "IPHONE_APP_STORE", "displayClassId": "IPHONE_DYNAMIC_ISLAND_MEDIUM_DISPLAY"}`
  (iPad: `IPAD_APP_STORE`; Duo: `IPHONE_DUO_PROFILE` / `IPHONE_DUO`). Up to 10 screenshots per group.
- **`GET /v1/appStoreVersions?filter[app]=…` is forbidden (no GET_COLLECTION).** Use `GET /v1/apps/{id}/appStoreVersions`.
- **In-app purchase versions:** `GET /v2/inAppPurchases/{id}/inAppPurchaseVersions` → 404 "The relationship
  'inAppPurchaseVersions' does not exist". That was the wrong relationship name (Apple's is `versions`), not proof the
  purchase is unversioned; corrected 2026-10-15 after the kit POSTed a second version beside the in-flight one and got
  409. The review screenshot is `GET /v2/inAppPurchases/{id}/appStoreReviewScreenshot`
  (`inAppPurchaseAppStoreReviewScreenshots`, `assetDeliveryState.state` COMPLETE, MD5 `sourceFileChecksum`).
  The API state is `READY_TO_SUBMIT` while the page shows "Prepare for Submission".
- **Price:** `GET /v1/inAppPurchasePriceSchedules/{iapId}/manualPrices?include=inAppPurchasePricePoint&filter[territory]=USA`
  works; the schedule id is the purchase id.
- **First in-app purchase:** no API route found. The purchase page's "Add for Review" puts it into the draft
  `reviewSubmission`; `asc_sync.py submit` then adds only the version (draft items read from
  `GET /v1/reviewSubmissions/{id}/items`; the relationship name of an IAP item is UNCONFIRMED).
- **Second live run (JetSetAlarm 1.0, 2026-10-15):** `GET /v1/ageRatingDeclarations/{id}` → 403 with a key that could
  write everything else (Apple lists no such GET; read through `GET /v1/appInfos/{id}/ageRatingDeclaration`).
  `POST /v1/inAppPurchaseVersions` → 409 while the purchase's version was in flight; the browser added ru and uk to that
  same version. A partly applied plan can now be finished with `apply --retry-failed --yes` (only the items marked
  failed are re-sent, after the same checks as the first apply).
