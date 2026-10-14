# App Review Guidelines that touch metadata, screenshots and review notes

Source: [App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/), read in full 2026-10-14.
The page ends with **"Last Updated: June 8, 2026"**. Freeze its hash with the kit anyway, because Apple edits it in place. Quotes are near-verbatim.

| Guideline | What it says | What the kit does |
|---|---|---|
| **2.1(a) App Completeness** | Submissions "should be final versions with all necessary metadata and fully functional URLs"; "placeholder text, empty websites, and other temporary content should be scrubbed". Include a demo account if the app has a login | lint flags placeholders; the readiness report checks every URL returns 200 and leads to real content |
| **2.1(b)** | In-app purchases must be "complete, up-to-date, visible to the reviewer and functional" | IAP checked in sandbox and TestFlight; submitted together with the version |
| **2.3 Accurate Metadata** | Metadata, "including privacy information, your app description, screenshots, and previews" must "accurately reflect the app's core experience" and be kept up to date | screens come from the build being submitted, never redrawn |
| **2.3.1(a)** | No hidden, dormant or undocumented features. "All new features, functionality, and product changes must be described with specificity in the Notes for Review section of App Store Connect (**generic descriptions will be rejected**)." Misleading marketing, or promoting a false price inside or outside the App Store, is grounds for removal | screenshot scenes stage sample content only; review notes name each new feature and where to find it |
| **2.3.2** | Description, screenshots and previews must "clearly indicate whether any featured items, levels, subscriptions, etc. require additional purchases". A promoted IAP's display name, screenshot and description must suit a public audience | lint warns when "free" appears without mentioning the paid tier |
| **2.3.3** | "Screenshots should show the app in use, and not merely the title art, login page, or splash screen." They "may also include text and image overlays (e.g. to demonstrate input mechanisms, such as an animated touch point or Apple Pencil)" | every frame shows a real screen in use; captions are allowed overlays |
| **2.3.4** | "Previews may only use video screen captures of the app itself." Sticker and iMessage apps may show the experience in Messages. "You can add narration and video or textual overlays" | previews are built from simulator or device recordings only; captions and voice-over are allowed |
| **2.3.5** | Pick the most appropriate category | category comes from facts, and a human confirms it |
| **2.3.6** | Answer the age-rating questions honestly | answers are drafted, and a human confirms them |
| **2.3.7** | Unique name; accurate keywords; no trademarked terms, popular app names, pricing or irrelevant phrases "to game the system". **Names are limited to 30 characters**. "Metadata such as app names, subtitles, screenshots, and previews should not include prices, terms, or descriptions that are not specific to the metadata type." Subtitles "should not include inappropriate content, reference other apps, or make unverifiable product claims." Apple may change inappropriate keywords | lint: limits, prices, competitor names, Apple marks in keywords; claims in the subtitle must be in `facts.yaml` |
| **2.3.8** | Metadata must suit all audiences: "app and in-app purchase icons, screenshots, and previews adhere to a 4+ age rating even if your app is rated higher". "For Kids" and "For Children" are reserved for the Kids Category. Keep the app name and every icon (small, large, Apple Watch, alternate) similar so they don't confuse | lint flags both phrases |
| **2.3.9** | You must have the rights to everything in icons, screenshots and previews; show fictional account information, not a real person's data | generated sample library with a provenance manifest; never the user's own photos |
| **2.3.10** | No names, icons or imagery of other mobile platforms or alternative marketplaces "unless there is specific, approved interactive functionality". Keep metadata focused on the app; "Don't include irrelevant information" | lint flags Android, Google Play and similar |
| **2.3.11** | Pre-order apps must be complete and deliverable as submitted; the released app must not differ materially from what was advertised | only if the app uses pre-order |
| **2.3.12** | What's New must clearly describe new features and changes. "Simple bug fixes, security updates, and performance improvements may rely on a generic description, but more significant changes must be listed" | required from version 2 onward |
| **2.3.13** | In-app events must fit an App Store Connect event type and be accurate | only if the app uses events |
| **2.4.3, 2.5.1, 2.5.12, 4.4** | The metadata must say when a game controller is required (tvOS), must name the framework a HealthKit/HomeKit-style integration uses, must identify call/SMS blocking and spam features and their criteria, and must disclose the app's extensions | copy checklist, only when the app has these features |
| **3.1.1 In-App Purchase** | Unlocking features or functionality must use in-app purchase; no license keys, QR codes and so on | readiness checks product IDs match StoreKit and restore works |
| **3.2.2(x)** | Apps must not force people to rate, review, or download other apps to use the app | precheck PAY-09 |
| **4 Design** | Minimum standards: "simple, refined, innovative, and easy to use" | out of scope for the kit; see the apple-hig skill |
| **5.1.1 Data Collection and Storage** | A privacy policy link is required both in App Store Connect and inside the app, and it must explain retention and deletion and how to revoke consent. Consent is needed even for "anonymous" data. If the app creates accounts, it must offer account deletion in the app | readiness checks the in-app link and that the policy names every SDK |
| **5.1.2 Data Use and Sharing** | Tracking needs App Tracking Transparency permission. Apps "may not require users to enable system functionalities (e.g. … tracking)" to use the app. Data may not be repurposed without consent | privacy labels mark tracking per data type |
| **4.1(c)** | "You cannot use another developer's icon, brand, or product name in your app's icon or name, without approval" | lint checks the competitor list against name and icon |
| **4.5.6** | Unicode characters that render as Apple emoji may be used in the app and its metadata; Apple emoji images may not be embedded | emoji in text fields are fine |
| **5.1.2(i)** | "You must clearly disclose where personal data will be shared with third parties, including with third-party AI" | precheck PR-08 |
| **5.1.4** | "Apps not in the Kids Category cannot include any terms in app name, subtitle, icon, screenshots or description that imply the main audience for the app is children" | lint flags kid-audience wording outside the Kids Category |
| **5.2.1 Intellectual property** | No third-party trademarks or copyrighted material without permission; no copycat names or metadata | lint checks the competitor list |
| **5.2.4 Apple Endorsements** | Don't suggest Apple is the source of the app or endorses it. "If your app is selected as an 'Editor's Choice,' Apple will apply the badge automatically" | never put Editor's Choice, App of the Day or Apple Design Award marks in screenshots or text |
| **5.2.5 Apple Products** | Don't look confusingly similar to Apple apps, interfaces or advertising themes | captions and backgrounds must not imitate Apple's ads |
| **5.6.1 App Store Reviews** | Replies to customer reviews: respectful, targeted, no personal information, spam or marketing. Use the provided API for rating prompts; custom review prompts are disallowed | reply drafts follow this; precheck PAY-10 |
| **After You Submit** | It can take up to 24 hours for a released app to appear on every storefront. One appeal route via App Store Connect; bug fixes for live apps are not held up except for legal or safety issues | release plan allows 24 h |

## Rules for store images beyond the guidelines

Source: [App Store asset best practices](https://developer.apple.com/app-store/asset-best-practices/), read 2026-10-14. Apple says these "reflect our overarching policies as well as how we evaluate artwork for featuring".

- No specific pricing, discounts, website URLs or copyright symbols in assets.
- No claims that can't be verified (awards or recognition the app hasn't received).
- No logos or references to other platforms or marketplaces.
- No Apple-designated recognitions: Editor's Choice, App of the Day, Game of the Day, Apple Design Award winner.
- Every asset must meet a **4+** rating, whatever the app's own rating. Games may show action, but no gore and no weapons pointed at a person or the viewer.
- Screenshots: don't use the whole image for accolades or a call to action; stay on the core experience.

## Review notes template

Notes are limited to 4000 bytes and can be in any language. Guideline 2.3.1(a): new features must be described "with specificity"; generic notes are rejected.

1. **What the app does,** in one sentence.
2. **How to see it without personal data.** If the app needs content (photos, contacts), describe the **release-build** path to sample content, such as a Settings switch. Don't describe DEBUG launch arguments; the reviewer can't use them.
3. **How to test the purchase:** the product ID, where the paywall is, that it works with a sandbox account, and what changes after purchase (for example, ads disappear).
4. **Permissions:** why each one is requested, and what happens if it's denied.
5. **Ads and consent:** whether a consent form (UMP) or the ATT prompt can appear, and in which regions.
6. **Contact** for the review team.
