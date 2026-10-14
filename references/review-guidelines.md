# App Review Guidelines that touch metadata, screenshots and review notes

Source: [App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/), read 2026-10-14.
The page shows no "last updated" date, so freeze its hash with the kit. Quotes are near-verbatim.

| Guideline | What it says | What the kit does |
|---|---|---|
| **2.1(a) App Completeness** | Submissions "should be final versions with all necessary metadata and fully functional URLs"; "placeholder text, empty websites, and other temporary content should be scrubbed". Include a demo account if the app has a login | lint flags placeholders; the readiness report checks every URL returns 200 and leads to real content |
| **2.1(b)** | In-app purchases must be "complete, up-to-date, visible to the reviewer and functional" | IAP checked in sandbox and TestFlight; submitted together with the version |
| **2.3 Accurate Metadata** | Metadata, "including privacy information, your app description, screenshots, and previews" must "accurately reflect the app's core experience" and be kept up to date | screens come from the build being submitted, never redrawn |
| **2.3.1** | No hidden, dormant or undocumented features; misleading marketing is grounds for removal | screenshot scenes stage sample content only; they never unlock or fake anything |
| **2.3.2** | Description and screenshots must "clearly indicate whether any featured items … require additional purchases" | lint warns when "free" appears without mentioning the paid tier |
| **2.3.3** | "Screenshots should show the app in use, and not merely the title art, login page, or splash screen" | every frame shows a real screen in use |
| **2.3.4** | "Previews may only use video screen captures of the app itself" | previews are built from simulator or device recordings only |
| **2.3.5** | Pick the most appropriate category | category comes from facts, and a human confirms it |
| **2.3.6** | Answer the age-rating questions honestly | answers are drafted, and a human confirms them |
| **2.3.7** | Unique name; accurate keywords; no trademarked terms, popular app names, pricing or irrelevant phrases "to game the system". **Names are limited to 30 characters**. Metadata shouldn't include prices or terms that don't fit the field | lint: limits, prices, competitor names, Apple marks in keywords |
| **2.3.8** | Metadata must suit all audiences (4+) even if the app is rated higher. "For Kids" and "For Children" are reserved for the Kids Category | lint flags both phrases |
| **2.3.9** | You must have the rights to everything in icons, screenshots and previews; show fictional account information, not a real person's data | generated sample library with a provenance manifest; never the user's own photos |
| **2.3.10** | No names, icons or imagery of other mobile platforms or alternative marketplaces | lint flags Android, Google Play and similar |
| **2.3.12** | What's New must clearly describe new features and changes | required from version 2 onward |
| **2.3.13** | In-app events must fit an App Store Connect event type and be accurate | only if the app uses events |
| **3.1.1 In-App Purchase** | Unlocking features or functionality must use in-app purchase; no license keys, QR codes and so on | readiness checks product IDs match StoreKit and restore works |
| **4 Design** | Minimum standards: "simple, refined, innovative, and easy to use" | out of scope for the kit; see the apple-hig skill |
| **5.1.1 Data Collection and Storage** | A privacy policy link is required both in App Store Connect and inside the app, and it must explain retention and deletion and how to revoke consent. Consent is needed even for "anonymous" data. If the app creates accounts, it must offer account deletion in the app | readiness checks the in-app link and that the policy names every SDK |
| **5.1.2 Data Use and Sharing** | Tracking needs App Tracking Transparency permission. Apps "may not require users to enable system functionalities (e.g. … tracking)" to use the app. Data may not be repurposed without consent | privacy labels mark tracking per data type |
| **5.2.1 Intellectual property** | No third-party trademarks or copyrighted material without permission; no copycat names or metadata | lint checks the competitor list |
| **5.2.5 Apple Products** | Don't look confusingly similar to Apple apps, interfaces or advertising themes | captions and backgrounds must not imitate Apple's ads |

## Review notes template

Notes are limited to 4000 bytes and can be in any language.

1. **What the app does,** in one sentence.
2. **How to see it without personal data.** If the app needs content (photos, contacts), describe the **release-build** path to sample content, such as a Settings switch. Don't describe DEBUG launch arguments; the reviewer can't use them.
3. **How to test the purchase:** the product ID, where the paywall is, that it works with a sandbox account, and what changes after purchase (for example, ads disappear).
4. **Permissions:** why each one is requested, and what happens if it's denied.
5. **Ads and consent:** whether a consent form (UMP) or the ATT prompt can appear, and in which regions.
6. **Contact** for the review team.
