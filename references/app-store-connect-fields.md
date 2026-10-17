# App Store Connect: every field, in the order you meet it

Read from Apple's own pages on **2026-10-14** (sources at the end). `connect_guide.py` turns this list into a
per-app guide. Where Apple's help doesn't name a field, its wording, or its limit, the entry says **unverified**:
the App Store Connect form itself is then the authority. Field names in **bold** are Apple's labels.

Two kinds of source:
- **Help**: App Store Connect Help pages (developer.apple.com/help/app-store-connect/...).
- **API**: the App Store Connect API schema (developer.apple.com/documentation/appstoreconnectapi/...). The API
  names every attribute the forms save, with its allowed values, so it confirms answer choices the help pages
  only show in screenshots.

## 0. Before anything (Business section)

| Field | What Apple asks | Source |
|---|---|---|
| Latest agreement | The Account Holder must sign the latest agreement in **Business** before any app can be added | Help: Add a new app |
| **Paid Apps Agreement** | Needed for a price or an In-App Purchase. Without it "you can only offer your app for free" | Help: Set a price; Set a price for an In-App Purchase |
| Tax and banking | Business section. Field-by-field: **unverified** (outside the app pages) | — |
| **Digital Services Act** (account level) | Business › Agreements › Compliance › **Complete Compliance Requirements**. Choose "This is a trader account." or "This is not a trader account." A trader enters (individual) **address or P.O. Box, phone number, email address**; (organization) phone and email, the D-U-N-S address shows automatically. Email and phone are verified by two-factor codes (manual verification possible); a document proving name and address is uploaded; **Confirm**. Shown on the product page in the 27 EU countries. "Even if you don't distribute apps in the EU, you'll still need to declare a trader status." | Help: Manage EU DSA trader requirements |

## 1. New App dialog (Apps › + › New App)

| Field | Choices / limits | Source |
|---|---|---|
| **Platforms** | iOS, macOS, tvOS, visionOS (one or more). Watch-only apps count as iOS | Help: Add a new app |
| **Name** | 2–30 characters, one app per name per localization | Help: App information |
| **Primary Language** | menu; can be changed later | Help: App information |
| **Bundle ID** | menu of registered IDs; must match Xcode; can't change after a build is uploaded | Help: App information |
| **SKU** | letters, numbers, hyphens, periods, underscores; can't start with `-`, `.` or `_`; can't be changed; never shown to customers. Length limit: **unverified** | Help: App information |
| **User Access** | **Limited Access** or **Full Access** (Limited: pick the users). Account Holder, Admin, Finance and Access to Reports always see every app | Help: Add a new app |
| Developer name | only for accounts registered as a company | Help: Add a new app |
| Buttons | **Cancel**, **Create** | Help: Add a new app |

## 2. App Information (sidebar › General › App Information)

| Field | Choices / limits | Source |
|---|---|---|
| **Name** | 2–30 characters, localizable; editable until submitted | Help: App information |
| **Subtitle** | max 30 characters, localizable | Help: App information |
| **Category** (Primary, Secondary) | menus; subcategories only for Games and Stickers | Help: App information |
| **Content Rights** | API: `DOES_NOT_USE_THIRD_PARTY_CONTENT` or `USES_THIRD_PARTY_CONTENT`. Help: apps that "contain, show, or access third-party content must have all the necessary rights". The dialog's exact wording: **unverified** | Help: App information; API: App attributes |
| **Age Rating** | required; questionnaire below (§2a) | Help: Set an app age rating |
| **License Agreement** | Apple's standard EULA by default (no link shown); **Edit** › "Apply a custom EULA to all chosen countries or regions" (plain text) | Help: Provide a custom license agreement |
| **Digital Goods and Services in Your Apps** | **Get Started** › "Can customers consume digital goods and services in this app?" Yes/No; Yes › Apple In-App Purchase only, or other payment options per region. EU choices lock for 12 months. Only appears for some apps | Help: Complete the Digital Goods and Services questionnaire |
| **App Store Regulations and Permits › Digital Services Act** | **Edit** › trader status for this app (§0) | Help: Manage EU DSA trader requirements |
| Labels and Markings URL | optional, same section | Help: Manage EU DSA trader requirements |
| **Regulated Medical Devices** | only for Health & Fitness or Medical apps in the EU/EEA, UK or U.S., or "frequent" medical information | Help: App information |
| Korea, China mainland, Vietnam availability | only for games, Korean ratings, or regulated content | Help: App information |
| **URL for App Store Server Notifications** | optional, shown only for apps with In-App Purchases | Help: App information |
| **App Encryption Documentation** | only if documentation is required (§6, export compliance) | Help: Determine and upload app encryption documentation |
| **Apple ID** | automatic, read-only | Help: App information |

### 2a. Age rating questionnaire (App Information › **Set Up Age Ratings**)

Flow (Help: Set an app age rating): step 1 in-app controls and capabilities (tick what applies) › content
sections, each with **NONE / INFREQUENT / FREQUENT** or **YES / NO** › **Additional Information** with the
calculated rating › **Age Categories and Override**: **Not Applicable**, **Made for Kids** (age range; only for
4+ or 9+; locked once approved), or **Override to Higher Age Rating** (9+, 13+, 16+, 18+, or Unrated for EU
alternative distribution) › optional **Age Suitability URL** › **Save**.

The help page shows only step 5 (Chance-Based Activities) in a screenshot. The full question list and answer
types below come from the API (`AgeRatingDeclaration`) and the help page "Age ratings values and definitions".
The order of sections follows the definitions page; the exact question sentences are **unverified**.

| Section | Item (API name) | Answer | Lowest rating it triggers (Apple global) |
|---|---|---|---|
| In-App Controls | Parental Controls (`parentalControls`) | Yes/No | 4+ |
| In-App Controls | Age Assurance (`ageAssurance`) | Yes/No | 4+ |
| Capabilities | Unrestricted Web Access (`unrestrictedWebAccess`) | Yes/No | 16+ |
| Capabilities | User-Generated Content (`userGeneratedContent`) | Yes/No | 4+ |
| Capabilities | Social Media (`socialMedia`) | Yes/No | 13+ |
| Capabilities | Social Media Disabled for Users Under 13 (`socialMediaAgeRestricted`) | Yes/No | 13+ |
| Capabilities | Messaging and Chat (`messagingAndChat`) | Yes/No | 4+ |
| Capabilities | Advertising (`advertising`) | Yes/No | 4+ |
| Mature Themes | Profanity or Crude Humor | None/Infrequent/Frequent | 9+ / 13+ |
| Mature Themes | Horror/Fear Themes | None/Infrequent/Frequent | 9+ / 13+ |
| Mature Themes | Alcohol, Tobacco, or Drug Use or References | None/Infrequent/Frequent | 13+ / 18+ |
| Medical or Wellness | Medical or Treatment Information | None/Infrequent/Frequent | 13+ / 16+ |
| Medical or Wellness | Health or Wellness Topics (`healthOrWellnessTopics`) | Yes/No | 9+ |
| Sexuality or Nudity | Mature or Suggestive Themes | None/Infrequent/Frequent | 9+ / 16+ |
| Sexuality or Nudity | Sexual Content or Nudity | None/Infrequent/Frequent | 13+ / 18+ |
| Sexuality or Nudity | Graphic Sexual Content and Nudity | None/Infrequent/Frequent | Unrated (can't be on the App Store) |
| Violence | Cartoon or Fantasy Violence | None/Infrequent/Frequent | 9+ / 13+ |
| Violence | Realistic Violence | None/Infrequent/Frequent | 13+ / 18+ |
| Violence | Prolonged Graphic or Sadistic Realistic Violence | None/Infrequent/Frequent | Unrated |
| Violence | Guns or Other Weapons | None/Infrequent/Frequent | 9+ / 13+ |
| Chance-Based Activities | Simulated Gambling | None/Infrequent/Frequent | 13+ / 18+ |
| Chance-Based Activities | Contests | None/Infrequent/Frequent | 4+ / 13+ |
| Chance-Based Activities | Gambling (`gambling`) | Yes/No | 18+ |
| Chance-Based Activities | Loot Boxes (`lootBox`) | Yes/No | 9+ |

Definitions worth quoting (Help: Age ratings values and definitions):
- **Advertising:** "Paid promotion of products or services within the app. May include: banner ads, video and playable ads, rich media ads, or native ad formats." Allowed at 4+.
- **User-Generated Content:** "the broad distribution of content created by users as a component of the app's intended user experience."
- **Unrestricted Web Access:** "Users can navigate to any webpage within the app or freely browse the web."
- **Contests:** "Events that allow users to compete with one another for rankings, rewards, or the achievement of personal goals."
- **Age Assurance:** "declared age range API; age estimation capabilities; age verification via government-issued" ID.
- Regional ratings (Australia, Brazil, Korea) are derived from the same answers; Korea may ask for an RCN later.

## 3. Pricing and Availability (sidebar › Monetization › Pricing and Availability)

| Field | Choices | Source |
|---|---|---|
| **Price Schedule › Add Pricing** | **Base Country or Region**, then **Price** (Free or a price point; "See Additional Prices" for more) › **Next** › review the other 174 storefronts › **Next** › **Confirm** | Help: Set a price |
| **App Availability › Set Up Availability** | **All Countries or Regions** (175, plus future ones), **Specific Countries or Regions** (tick list, plus a box for future countries), or **Publish as Pre-Order** (release date + countries) › **Next** › **Confirm** | Help: Manage availability |
| **iPhone and iPad Apps on Apple Silicon Mac** | checkbox **Make this app available**; default state **unverified** | Help: Macs with Apple silicon |
| **iPhone and iPad Apps on Apple Vision Pro** | checkbox **Make this app available on Apple Vision Pro**; available by default | Help: Apple Vision Pro |
| **Tax Category** | default **App Store software**; other categories only if they describe the app | Help: Set a tax category |

## 4. App Privacy (sidebar › App Privacy)

| Field | Choices | Source |
|---|---|---|
| **Privacy Policy** › Edit | **Privacy Policy URL** (required for all apps) and **User Privacy Choices URL** (optional) | Help: Manage app privacy; App privacy |
| **Get Started** › data question | "Yes, we collect data from this app" › **Next**, or "No, we do not collect data from this app" › **Save** | Help: Manage app privacy |
| Data types | tick every type you or partners collect › **Save** (list below) | Help: Manage app privacy |
| Per data type | purposes, linked to the user, tracking. The per-type question sentences are **unverified** (not on the help page); the choices are Apple's purposes and Yes/No | Help: Manage app privacy; App privacy details |
| **Product Page Preview** › **Publish** | confirm in "Publish Your App Privacy Responses?" | Help: Manage app privacy |

Data types: Contact Info (Name, Email Address, Phone Number, Physical Address, Other User Contact Info); Health &
Fitness (Health, Fitness); Financial Info (Payment Info, Credit Info, Other Financial Info); Location (Precise
Location, Coarse Location); Sensitive Info; Contacts; User Content (Emails or Text Messages, Photos or Videos,
Audio Data, Gameplay Content, Customer Support, Other User Content); Browsing History; Search History;
Identifiers (User ID, Device ID); Purchases (Purchase History); Usage Data (Product Interaction, Advertising Data,
Other Usage Data); Diagnostics (Crash Data, Performance Data, Other Diagnostic Data); Surroundings (Environment
Scanning); Body (Hands, Head); Other Data (Other Data Types).

Purposes: Third-Party Advertising; Developer's Advertising or Marketing; Analytics; Product Personalization;
App Functionality; Other Purposes. Definitions of "linked" and "tracking": `references/privacy-labels.md`.

## 5. App Accessibility (sidebar › App Accessibility) — Accessibility Nutrition Labels

- Voluntary today; Apple says it will become required "over time". No date announced.
- **Get Started** › pick devices › **Add [Device] Support** › "Select Yes if your app supports any of the
  accessibility features on the selected device, or No" › tick features › **Next** › saved as a draft ›
  **Publish**.
- "You can only publish support for devices that have a live version on the App Store." For a first version the
  answers stay a draft until release. The **Accessibility URL** (optional) goes live with the first release.
- Features: **VoiceOver**, **Voice Control** (not Apple TV/Watch), **Larger Text** (200% or more; not Mac),
  **Dark Interface**, **Differentiate Without Color Alone**, **Sufficient Contrast**, **Reduced Motion**,
  **Captions**, **Audio Descriptions**.
- Rule: declare a feature only if every common task (first launch, main function, login, purchase, settings)
  works with it.

Sources: Help: Overview of Accessibility Nutrition Labels; Manage Accessibility Nutrition Labels.

## 6. The iOS version page (sidebar › iOS App › 1.0)

| Field | Limits / choices | Source |
|---|---|---|
| **App Previews and Screenshots** | per device tab: previews (up to 3, optional), screenshots 1–10 (required). Drag into the well, or **Browse Assets** (Asset Library). Other sizes: **View All Sizes in Media Manager** | Help: Platform version information; Manage your App Store assets |
| **Promotional Text** | 170 characters; changeable without a new version | Help: Platform version information |
| **Description** | 4000 characters, plain text | same |
| **Keywords** | 100 bytes, each keyword more than 2 characters | same |
| **Support URL** | required, full URL; must lead to real contact information | same |
| **Marketing URL** | optional, full URL | same |
| **Version** | the version number shown on the product page | same |
| **Copyright** | required, "2014 Example, Inc."; © added automatically | same |
| **Routing App Coverage File** | only for routing (navigation) apps, .geojson | same |
| **What's New in This Version** | 4000 characters; not available for the first version | same |
| **Build** | **+** next to Build › pick one in **Add Build** › **Done** › **Save**. A build in **Missing Compliance** needs the export compliance answers first | Help: Choose a build to submit |
| Export compliance | if Info.plist has `ITSAppUsesNonExemptEncryption` = NO, no questions: "your app … either uses no encryption, or only uses encryption that's exempt". Without the key the questionnaire appears for every upload; its question wording is **unverified** | API docs: ITSAppUsesNonExemptEncryption; Help: Provide export compliance information for beta builds |
| **Game Center** | a version-page section for Game Center apps; its exact layout is **unverified** | Help: Manage an app version for Game Center (not read) |
| **App Review Information › Sign-in required** | user name and password of a demo account that doesn't expire; only if the app needs a login. App Review Help (2026-10-17): one account per account type, an account with an expired subscription where relevant, and any authentication code given in advance; both name and password (`asc_sync.py` warns when private.yaml has only one) | Help: Platform version information; [complete review](https://developer.apple.com/help/app-review/before-submitting-for-review/complete-review) |
| Contact (name, email, phone) | first name, last name, phone, email (API: `contactFirstName`, `contactLastName`, `contactPhone`, `contactEmail`). Phone in international format with `+` and country code; digits only is rejected | Help: Platform version information; API: AppStoreReviewDetail |
| **Notes** | 4000 bytes, any language (over the limit is an error in `lint_metadata.py` and the sync plan). Apple's list: concept and business model (new app) or what changed and where (update), purpose and audience, devices and OS tested, external services, regional differences, demo access, regulated-field documents; required hardware as a video. Template in `review-guidelines.md` | Help: Platform version information; [complete review](https://developer.apple.com/help/app-review/before-submitting-for-review/complete-review) |
| Attachment | "Choose File (Optional)". Not on the help page; seen on the live page 2026-10-14 | live page |
| **App Store Version Release** | "Manually release this version", "Automatically release this version", or "Automatically release this version after App Review, no earlier than" + date | Help: Select an App Store version release option |
| **Phased Release for Automatic Updates** | "Release update to all users immediately" or "Release update over 7-day period using phased release". Updates only (not a first version) | Help: Release a version update in phases |
| **Reset Overview Rating** | updates only | Help: Platform version information; Required, localizable, and editable properties |
| **First in-app purchase** | MOVED (live 2026-10-14): the version page has no In-App Purchases section. Open In-App Purchases › the purchase › **Add for Review** (banner: "Your first non-consumable in-app purchase must be submitted with a new app version"), then the version's Add for Review; both sit in one draft until Submit for Review | live page; Help: Submit an In-App Purchase |
| **Add for Review** › **Submit for Review** | two steps; the second sends it to Apple | Help: Submit an app |
| **Release This Version** › **Confirm** | after approval, status Pending Developer Release (manual release only) | Help: Select an App Store version release option |

### Advertising identifier (IDFA) question

The old "Does this app use the Advertising Identifier (IDFA)?" question is gone: the API attribute
`AppStoreVersion.usesIdfa` is marked **deprecated**, and no current help page mentions it. Tracking is now
declared in App Privacy (Device ID › tracking) and in the app's App Tracking Transparency prompt.

### 6a. Previews, screenshots and creative assets: where they are managed (read 2026-10-14)

Source: Help: [Manage your App Store assets](https://developer.apple.com/help/app-store-connect/manage-app-information/manage-your-app-store-assets),
[Submit assets from Asset Library](https://developer.apple.com/help/app-store-connect/manage-submissions-to-app-review/submit-assets-from-asset-library),
[App Store asset statuses](https://developer.apple.com/help/app-store-connect/reference/app-information/app-store-asset-statuses).

| Place | What you can do |
|---|---|
| **Product Page Information** (version page, Custom Product Pages, Product Page Optimization) | upload, sort, set or remove placements, **Browse Assets**, set a poster frame; scoped to that version, page or treatment |
| **Media Manager** (**View All Sizes in Media Manager**) | per device size and localization: add from Asset Library, reorder, remove placements, poster frames; also where iMessage and watchOS screenshots and scaled sizes are managed |
| **Asset Library** (sidebar) | upload (+ › **Upload Creative Assets** or **Previews and Screenshots**), name an asset (internal only), see **Works With** and **Recent Usage**, set a poster frame, delete, archive, filter by Type, Status, Format |

- Roles: managing assets needs Account Holder, Admin, App Manager or **Marketing**; submitting from Asset Library needs Account Holder, Admin or App Manager.
- Upload or edit previews and screenshots only while the version is Prepare for Submission, Invalid Binary, Rejected, Metadata Rejected or Developer Rejected.
- Removing a screenshot or preview also removes it from every display size that uses the scaled version. Removing it from Product Page Information keeps it in Asset Library.
- A poster frame applies everywhere the asset is used, and **can't be edited after the asset is approved**.
- Delete is possible only while the asset is **Prepare for Submission**. Archived assets can't be used in new placements; **Unarchive Asset** restores one.
- Asset statuses: Uploading › Processing › Prepare for Submission › Ready for Review › Waiting for Review › In Review › Accepted (others in the same submission still rejected) / Approved / Rejected; Archived (replaced by a newer version's asset; hidden unless filtered).
- First version: assets must go in the same submission as the first app version. After an approved version, assets can be submitted standalone (**Edit** › select › **Add for Review** › existing or new draft › **Submit for Review**); they are reviewed against the latest version of the platform you pick. Assets assigned to a version, custom product page, PPO test or in-app event are reviewed with it and can't be submitted separately.
- **Header and Search Results** tab (iOS/iPadOS 27 or later): **Header** or **Search Results** › drag in or **Browse Assets** › **Save**. "Use header asset in search results" works only for a universal asset. **Preview** shows iPhone and iPad, orientations and languages. They go live when the version is released. On the live version, swap in an approved asset with **Browse Assets** › **Next** › **Publish** (no new version). **Delete** removes it from the placement, not from Asset Library. Specs: `creative-assets.md`.

### 6b. Custom product pages and product page optimization (read 2026-10-14)

| Item | Limit / rule | Source |
|---|---|---|
| Custom product pages | up to **70** additional pages (iPhone and iPad); vary screenshots, promotional text and previews; start blank or from a copy of the default page; fully localizable; work for pre-order apps | https://developer.apple.com/app-store/custom-product-pages/ |
| CPP keywords | assign keywords so the page appears in search for them instead of the default page; each keyword combination must be unique to one page | same |
| CPP deep link | one per page; opens a place in the app; iOS/iPadOS 18 or later | same |
| CPP review | metadata goes to review, independent of an app update; can be automated with the API | same |
| CPP URL | the default product page URL plus a product page ID parameter; ad networks pass it as `customProductPageIdentifier` (SKOverlay) or `SKStoreProductParameterCustomProductPageIdentifier` | same |
| PPO test | **one** test at a time, up to **3 treatments** against the original, for up to **90 days**; reference name up to **64** characters; choose traffic share; can't be changed once started | https://developer.apple.com/app-store/product-page-optimization/ |
| PPO elements | app icon, screenshots, previews (and header visuals, per asset best practices); shown on iOS/iPadOS 15 or later | same; https://developer.apple.com/app-store/asset-best-practices/ |
| PPO review | new treatment metadata must be approved before the test starts. Alternate icons must all be in the published binary; tests without alternate icons can be submitted without a new version | same |
| PPO results | in App Analytics; wait for at least **90% confidence** before applying a treatment; applying one ends the test; an applied alternate icon must ship in the next version | same |

### 6c. Build metadata (TestFlight › a build › Build Metadata) (read 2026-10-14)

Source: Help: [View builds and metadata](https://developer.apple.com/help/app-store-connect/manage-builds/view-builds-and-metadata).

- Roles: Account Holder, Admin, App Manager or Developer. Some builds may disappear after the app is released.
- **App File Sizes**: install size (also shown on the product page) and download size per device variant. A yellow warning appears, plus an email, if any variant exceeds the **200 MB over-the-air download limit**. The final size after DRM can be larger and can't be known in advance.
- **Build Uploads** statuses: **Processing**, **Failed**, **Complete** (email for each). A Failed upload's build number **can be reused**. Processing for more than **24 hours** means a problem: file Feedback Assistant (Developer Tools & Resources › TestFlight) or contact Apple. Complete can still carry warnings; read them before the next upload.
- Device requirements: Minimum iOS version = `MinimumOSVersion`; the minimum macOS is computed by Apple.
- dSYM download exists only for old bitcode builds; since Xcode 14 there is no bitcode and no dSYM here.

## 7. In-App Purchases (sidebar › Monetization › In-App Purchases › +)

Seen on the live page 2026-10-14, top to bottom: Status, Product ID, Reference Name (64), Apple ID, Family Sharing (Turn On), Availability, Price Schedule (+, Base Country or Region, Prices), Offer Codes, **Display Name and Description** (Add), **Image (Optional)** 1024×1024, **Tax Category** (Edit; "Match to parent app"), **Review Information** (Screenshot, Review Notes (Optional) 4000), Delete This In-App Purchase. Buttons: Save, Add for Review. A banner says the first non-consumable must be submitted with a new app version. The help pages call the name section "App Store Localization"; the page says "Display Name and Description".

| Field | Limits / choices | Source |
|---|---|---|
| **Type** | Consumable or Non-Consumable (subscriptions are under Subscriptions) | Help: Create consumable or non-consumable In-App Purchases |
| **Reference Name** | up to 64 characters; internal only | Help: In-App Purchase information |
| **Product ID** | letters, numbers, hyphens, periods, underscores; up to 100 characters; never editable or reusable | same |
| **Availability › Set Up Availability** | countries or regions, or "Remove from sale" › **Done** | Help: Set availability for In-App Purchases |
| **Price Schedule › Add Pricing** | base country or region › price › **Next** › other storefronts › **Next** › **Confirm** | Help: Set a price for an In-App Purchase |
| **Tax Category** | default "Match to parent app" | Help: Set a tax category for In-App Purchases |
| **Family Sharing** | **Turn On** › **Confirm**. "once you turn on Family Sharing … you can't turn it off". Non-consumables and auto-renewables only | Help: Turn on Family Sharing for In-App Purchases |
| **App Store Localization** | **Display Name** 2–30 characters; **Description** max 45 characters; at least one language | Help: In-App Purchase information |
| **Review Information** | **App Review Screenshot** (any accepted screenshot size; can be replaced, not removed) and **Review Notes** (max 4000 characters) | same |
| **Image** (promotional) | 1024 × 1024 JPG/PNG, 72 dpi, RGB, flattened, no rounded corners; only needed to promote the IAP, win-back offers or offer codes | same; View and edit In-App Purchase information |

## 8. TestFlight › Test Information (TestFlight tab › Additional › Test Information)

| Field | Limits | Source |
|---|---|---|
| **Beta App Description** | required; limit **unverified** | Help: Provide test information; API: BetaAppLocalization |
| **Feedback Email** | testers' contact address and the invite reply-to | same |
| **Marketing URL**, **Privacy Policy URL** | API attributes `marketingUrl`, `privacyPolicyUrl`; labels **unverified** | API: BetaAppLocalization |
| Invitation Experience › **App Information** | ticked by default | Help: Provide test information |
| **Beta App Review Information** | contact first name, last name, phone, email; sign-in required + user name/password; notes. Limits **unverified** | API: BetaAppReviewDetail |
| **What to Test** (per build) | API `BetaBuildLocalization.whatsNew`; limit **unverified** | API: BetaBuildLocalization |

## Live-page corrections

What the live App Store Connect pages showed when they differed from, or added to, the help pages above. The
live page wins. Each entry: date seen, the screen, what it shows. When a new difference turns up (an owner's
screenshot in guide mode, or `read_page` in autopilot), add it here, change `scripts/connect_guide.py` to match,
log it in `.living/CHANGELOG.md`, and regenerate the guide.

### 2026-10-14 · In-App Purchase page (Monetization › In-App Purchases › a purchase)

- Top to bottom: Status, Product ID, Reference Name (64), Apple ID, **Family Sharing** (Turn On), **Availability**,
  **Price Schedule** (+, Base Country or Region, Prices), **Offer Codes**, **Display Name and Description** (Add),
  **Image (Optional)** 1024×1024, **Tax Category** (Edit; "Match to parent app"), **Review Information**
  (Screenshot, Review Notes (Optional) 4000), **Delete This In-App Purchase**. Buttons: **Save**, **Add for Review**.
- A banner says the first non-consumable must be submitted with a new app version.
- The help pages call the name section "App Store Localization"; the page says "Display Name and Description".
- Availability shows "All countries or regions selected"; the price schedule shows the base country with its
  currency, e.g. "United States (USD)", and the count of storefronts (175).

### 2026-10-14 · Apps list

- Banner "Apple Developer Program License Agreement Updated": the Account Holder must accept it before anything can
  be submitted. Guide mode only (autopilot never accepts agreements).

### 2026-10-14 · Sidebar of an app

- **General**: App Information, App Review, History.
- **App Store**, in groups:
  - TRUST & SAFETY: App Privacy, App Accessibility, Ratings and Reviews;
  - GROWTH & MARKETING: In-App Events, Custom Product Pages, Asset Library, Product Page Optimization, Promo Codes,
    Game Center;
  - MONETIZATION: Pricing and Availability, In-App Purchases, Subscriptions;
  - FEATURING: Nominations.

### 2026-10-14 · Version page (sidebar › iOS App › the version)

- Heading "iOS App Version <version>"; texts sit in the section **Product Page Information**, with a language
  selector.
- A new tab **Header and Search Results** next to **App Previews and Screenshots**: an optional header asset,
  0 of 1, 5244×2950 or 3840×1646, picked from the **Asset Library**.
- iPhone Duo screenshot sets can already be uploaded.
- Field ids on the page: `promotionalText`, `description`, `keywords`, `supportUrl`, `marketingUrl`,
  `versionString`, `copyright`. Useful for `find`/`form_input` in autopilot.
- **App Review Information**: a "Sign-in required" checkbox, First name, Last name, Phone number, Email, Notes
  (4,000), and Attachment "Choose File (Optional)". This confirms the attachment field.
- **App Store Version Release** radios: Manually / Automatically / Automatically after a date. **Automatically is
  selected by default**, so a kit that wants manual release must change it.
- A version record made earlier can still carry an old version string (Swipr: 0.56) and old text from an earlier
  build. The Version field must equal the build's `CFBundleShortVersionString`; every text is replaced with the
  kit's. `connect_guide.py --check` flags both once the live values are in `connect-progress.yaml`.

### 2026-10-14 · App Information › Content Rights

- A dialog with two radios: "Yes, it contains, shows, or accesses third-party content, and I have the necessary
  rights" and "No, it does not contain, show, or access third-party content". It is an attestation, so autopilot
  asks for an explicit yes first.

### 2026-10-14 · Pricing and Availability

- Price "Free (0.00 USD)"; Availability shows the count of countries or regions (175).
- Below it, two separate checkboxes: Mac (Apple silicon) "Make this app available" and Apple Vision Pro. Turn them off
  when the kit says iPhone and iPad only.

### 2026-10-14 · In-App Purchase › Display Name and Description dialog

- The live dialog allows Display Name 35 and Description 55 characters (the help page says 30 and 45). The kit
  keeps the stricter 30/45, so text that passes the kit always fits.

### 2026-10-14 · App Privacy

- The flow:
  1. Privacy Policy › Edit (URL; the User Privacy Choices URL is optional).
  2. Get Started › Data Collection (Yes/No) › Next › tick the data types › Save (later edits say Continue).
  3. One "Set Up <data type>" per type, a wizard of three steps:
     - tick the purposes, then Next;
     - Linked to the user's identity (Yes/No), then Next, then two information pages, each with Next;
     - Used for tracking (Yes/No), then Save.
  4. Publish, then confirm "Publish Your App Privacy Responses?".
- An "Additional Setup Required" dialog (OK) can appear before the first Set Up; press OK, then Set Up again.
- After the first publish, the last button of each wizard says **Publish**, and it updates the product page straight
  away. A data type added later shows "You need to finish setting up the following data types before leaving this
  page".
- Autopilot: the checkboxes ignore `form_input`. Click them, or click from script inside the top dialog.
- Check the Product Page Preview against privacy-labels.md, e.g. "Data Used to Track You: Identifiers".

### 2026-10-14 · App Accessibility

- Get Started opens "Select Device" (iPhone, iPad, Apple Watch). Save, then one card per device: "Add iPhone
  Support" asks:
  1. "Does your app support any of the above features?" (Yes/No), then Next;
  2. Select Features: nine checkboxes;
  3. Confirm, then Save.
- The cards stay drafts ("Drafts (2)"): Publish works only for devices that have a released version.

### 2026-10-14 · Version page › App Previews and Screenshots

- Tabs: iPhone with Dynamic Island (medium display), iPhone Duo, iPad 13" display, Apple Watch.
- Each slot has "0 of 3 App Previews · 0 of 10 App Screenshots · Browse Assets · Upload · Remove All".
- Autopilot: put the files straight into the slot's file input (one call per slot, in order 01..05). The upload keeps
  the file order. An "App Previews, Screenshots, and Localizations" dialog (OK) appears once per slot.
- Uploads save themselves (the Save button stays greyed out); reload the page to confirm the counts.

### 2026-10-14 · First In-App Purchase and the version page

- The review screenshot upload (Review Information › Choose File) saves on its own, like the version screenshots.
- SUPERSEDED the same day: with every agreement Active the version page still has no In-App Purchases section. The
  first purchase is added from its own page (Add for Review), see the version-page table above. A pending Paid
  Applications agreement still blocks paid content: check Business first.

## Unverified (check on the live form)

- SKU maximum length.
- The exact sentences of the age-rating questions and the content-rights dialog (answer types are verified).
- The per-data-type privacy question sentences.
- The export compliance questions shown when the Info.plist key is missing.
- The Game Center version section; the IAP section label on the version page. (The App Review attachment
  field is confirmed: see Live-page corrections.)
- TestFlight field limits.
- The default of the Apple silicon Mac checkbox.
- Tax and banking forms.

## Sources (read 2026-10-14)

Help pages, prefix `https://developer.apple.com/help/app-store-connect/`:
`create-an-app-record/add-a-new-app`, `reference/app-information/app-information`,
`manage-app-information/set-an-app-age-rating`, `reference/app-information/age-ratings-values-and-definitions`,
`manage-app-information/provide-a-custom-license-agreement`,
`manage-app-information/complete-the-digital-goods-and-services-questionnaire`,
`manage-compliance-information/manage-european-union-digital-services-act-trader-requirements`,
`manage-app-pricing/set-a-price`, `manage-your-apps-availability/manage-availability-for-your-app-on-the-app-store`,
`manage-your-apps-availability/manage-availability-of-iphone-and-ipad-apps-on-macs-with-apple-silicon`,
`manage-your-apps-availability/manage-availability-of-iphone-and-ipad-apps-on-apple-vision-pro`,
`manage-app-information/set-a-tax-category`, `manage-app-information/manage-app-privacy`,
`reference/app-information/app-privacy`, `manage-app-accessibility/overview-of-accessibility-nutrition-labels`,
`manage-app-accessibility/manage-accessibility-nutrition-labels`,
`reference/app-information/platform-version-information`,
`reference/app-information/required-localizable-and-editable-properties`,
`manage-app-information/manage-your-app-store-assets`, `manage-builds/choose-a-build-to-submit`,
`manage-app-information/overview-of-export-compliance`,
`manage-app-information/determine-and-upload-app-encryption-documentation`,
`reference/app-information/export-compliance-documentation-for-encryption`,
`test-a-beta-version/provide-export-compliance-information-for-beta-builds`,
`manage-your-apps-availability/select-an-app-store-version-release-option`,
`update-your-app/release-a-version-update-in-phases`, `manage-submissions-to-app-review/submit-an-app`,
`manage-submissions-to-app-review/submit-an-in-app-purchase`,
`manage-in-app-purchases/create-consumable-or-non-consumable-in-app-purchases`,
`reference/in-app-purchases-and-subscriptions/in-app-purchase-information`,
`reference/in-app-purchases-and-subscriptions/in-app-purchase-types`,
`manage-in-app-purchases/set-availability-for-in-app-purchases`,
`manage-in-app-purchases/set-a-price-for-an-in-app-purchase`,
`manage-in-app-purchases/view-and-edit-in-app-purchase-information`,
`configure-in-app-purchase-settings/set-a-tax-category-for-in-app-purchases`,
`configure-in-app-purchase-settings/turn-on-family-sharing-for-in-app-purchases`,
`test-a-beta-version/provide-test-information`.

Also read 2026-10-14: `manage-submissions-to-app-review/submit-assets-from-asset-library`,
`reference/app-information/app-store-asset-statuses`, `reference/app-information/creative-assets-specifications`,
`manage-builds/view-builds-and-metadata`.

Other Apple pages:
- https://developer.apple.com/app-store/custom-product-pages/ and https://developer.apple.com/app-store/product-page-optimization/
- https://developer.apple.com/app-store/app-privacy-details/
- https://developer.apple.com/documentation/bundleresources/information-property-list/itsappusesnonexemptencryption
- App Store Connect API attribute pages, prefix `https://developer.apple.com/documentation/appstoreconnectapi/`:
  `ageratingdeclaration/attributes-data.dictionary`, `app/attributes-data.dictionary`,
  `appstoreversion/attributes-data.dictionary`, `appstorereviewdetail/attributes-data.dictionary`,
  `betaapplocalization/attributes-data.dictionary`, `betaappreviewdetail/attributes-data.dictionary`,
  `betabuildlocalization/attributes-data.dictionary`.

- **First in-app purchase (live 2026-10-14):** with the agreements Active, the version page still shows no In-App Purchases section. The route is the purchase page's **Add for Review** (banner: "Your first non-consumable in-app purchase must be submitted with a new app version"), then the version's Add for Review; both go into one draft submission. The API reports the purchase `READY_TO_SUBMIT` while the page shows "Prepare for Submission". An unversioned purchase has no `inAppPurchaseVersions` relationship (404); its review screenshot is `GET /v2/inAppPurchases/{id}/appStoreReviewScreenshot`.
- **App-level DSA trader status (live 2026-10-14):** App Information › App Store Regulations & Permits › Digital Services Act
  reads "This developer has identified itself as a non-trader for this app" with **Get Started** until the account's
  trader contact details are verified (the link goes to `/business?collectContactInfo=true`). After that the link is
  **Edit**, which opens "Digital Services Act Compliance" with two radios, "This is a trader app" / "This is a
  non-trader app", and Save. Owner only. Once a trader, an **Add Labels and Markings** link appears in the same block.
