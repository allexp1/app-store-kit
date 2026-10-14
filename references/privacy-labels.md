# Privacy nutrition labels (App Privacy in App Store Connect)

Primary sources, read 2026-10-14:
- [App privacy details on the App Store](https://developer.apple.com/app-store/app-privacy-details/) (Apple)
- [Privacy manifest files](https://developer.apple.com/documentation/bundleresources/privacy-manifest-files) and [Describing data use in privacy manifests](https://developer.apple.com/documentation/bundleresources/describing-data-use-in-privacy-manifests) (Apple)
- [Google Mobile Ads SDK: App Store data disclosure](https://developers.google.com/admob/ios/privacy/data-disclosure), last updated 2026-10-13 (Google)

## Definitions that decide the answers (Apple)

- **Collect:** data is sent off the device so that you or a partner can access it for longer than it takes to serve the request in real time.
- **Third-party partners:** analytics tools, ad networks, third-party SDKs, or other vendors whose code is in the app. **Their collection is yours to disclose.**
  Apple's frameworks are the exception: you're not responsible for disclosing data Apple collects.
- **Tracking:** linking data collected in your app about a user or device with third-party data for targeted advertising or ad measurement, or sharing it with a data broker.
- **Linked to the user:** the default. Data counts as unlinked only if it's de-identified before collection. "Personal data" under privacy law always counts as linked.
- **Purposes:** Third-Party Advertising; Developer's Advertising or Marketing; Analytics; Product Personalization; App Functionality; Other Purposes.
- **Optional disclosure** applies only if *all* of the criteria are met:
  - the data is not used for tracking or advertising;
  - collection is infrequent, optional and not part of the main function;
  - the user enters the data in the interface and knowingly chooses to submit it each time.
  Apple's page also lists criteria for product-improvement programs, regulated financial services and health research. If even one criterion fails, disclose.

## Data types (Apple's categories)

| Category | Types |
|---|---|
| Contact Info | Name, Email Address, Phone Number, Physical Address, Other User Contact Info |
| Health & Fitness | Health, Fitness |
| Financial Info | Payment Info (not collected if a payment service handles it and you never see it), Credit Info, Other Financial Info |
| Location | Precise Location (3 or more decimal places), Coarse Location |
| Sensitive Info | Sensitive Info |
| Contacts | Contacts |
| User Content | Emails or Text Messages, Photos or Videos, Audio Data, Gameplay Content, Customer Support, Other User Content |
| Browsing History | Browsing History |
| Search History | Search History |
| Identifiers | User ID, Device ID (advertising identifier or other device-level ID) |
| Purchases | Purchase History |
| Usage Data | Product Interaction, Advertising Data, Other Usage Data |
| Diagnostics | Crash Data, Performance Data, Other Diagnostic Data |
| Surroundings | Environment Scanning |
| Body | Hands, Head |
| Other Data | Other Data Types |

## Method: one row per data type

Put this in `kit/privacy.yaml`. Every collected type gets a row with these columns:

| Data type | Purposes | Linked? | Tracking? | Who receives it | Source (SDK and version, or own code) | Evidence |
|---|---|---|---|---|---|---|

1. **List what the app sends,** from your own code: network calls, analytics, crash reporting.
2. **List every SDK and its version** from the lockfile (`Package.resolved`, `Podfile.lock`).
3. **Generate the archive's privacy report:** Xcode › Organizer › select the archive › Generate Privacy Report. It merges your `PrivacyInfo.xcprivacy` with every SDK's manifest.
   - This is the ground truth for what the binary declares.
   - An app manifest that declares "nothing collected" is still correct *for your own code*. The SDKs bring their own manifests, and the label has to cover them.
4. **Read each SDK vendor's disclosure page** (below) and add its rows.
5. **"Used for tracking"** describes what the app *can* do once someone grants consent. If the app can track after an ATT "Allow", answer Yes.
   A user who says no to ATT stops the tracking only. **The other data types are still collected and still disclosed.**
6. **Where the vendor page is silent,** for example on whether a type is linked, assume linked. Write down why in the Evidence column.
7. **Cross-check:**
   - every label row needs a matching mention in the privacy policy (Guideline 5.1.1);
   - if any row says tracking, the app needs `NSUserTrackingUsageDescription` and the ATT prompt before tracking (5.1.2(i)).
8. **A human confirms the final answers** in App Store Connect. The kit drafts them; it doesn't submit them.

## SDK example: Google Mobile Ads (AdMob) and User Messaging Platform (UMP)

From Google's data-disclosure page. Google lists what the SDK *may* collect "to improve AdMob performance".

| Apple data type | What Google says | Purposes to declare | Linked | Tracking |
|---|---|---|---|---|
| Location › **Coarse Location** | IP address "to estimate the general location of a device" | Third-Party Advertising, Analytics | Not stated, so answer Yes | Yes if the app shows personalised ads after ATT/UMP consent |
| Identifiers › **Device ID** | "advertising identifier or app- or developer-bounded identifiers" used for third-party advertising and analytics | Third-Party Advertising, Analytics | Yes | **Yes** (IDFA after ATT allow) |
| Usage Data › **Advertising Data** | "advertisements the user has seen", for analytics and advertising | Third-Party Advertising, Analytics | Yes | Yes, same condition |
| Usage Data › **Product Interaction** | app launch, taps, video views, "to improve advertising performance" | Third-Party Advertising, Analytics | Yes | Yes, same condition |
| Diagnostics › **Crash Data** | "non-user related crash logs" for diagnosing the SDK, may be used for ads and analytics | Third-Party Advertising, Analytics, App Functionality | Google says non-user-related, so No is defensible; write that down | No |
| Diagnostics › **Performance Data** | launch time, hang rate, energy use; "user-associated"; may be shared with entities that display ads | Third-Party Advertising, Analytics | Yes | Yes, same condition |

Notes from Google's page:
- The disclosures describe the SDK as of version 7.68.0. Versions 11.2.0 and later ship a privacy manifest, so check yours in the privacy report.
- Optional features such as advanced reporting or feature tests may collect more. Mediation adapters need versions that ship their own manifests.
- **UMP:** Google's [privacy and messaging page](https://developers.google.com/admob/ios/privacy) gives *no* data-collection statement for the UMP SDK. Take UMP's declared types from its manifest in the archive privacy report. Don't guess.

**Worked example (Swipr, 2026-10).**
- Swipr's own `PrivacyInfo.xcprivacy` declares no data collected and no tracking. That's correct for Swipr's code, which keeps everything on the device.
- AdMob and UMP ship in the free tier, so the label is the AdMob table above: Coarse Location, Device ID, Advertising Data, Product Interaction, Crash Data and Performance Data.
- Photos never leave the device, so **User Content › Photos or Videos is not collected**.
- Buying the Pro in-app purchase removes ads. The label still has to describe the free tier.

## Other common SDKs (vendor pages, not read on 2026-10-14; read them before use)

| SDK | Vendor disclosure page |
|---|---|
| Firebase (Analytics, Crashlytics, …) | https://firebase.google.com/docs/ios/app-store-data-collection |
| RevenueCat | https://www.revenuecat.com/docs/platform-resources/apple-platform-resources/apple-app-privacy |
| Sentry | https://docs.sentry.io/platforms/apple/data-management/apple-privacy-manifest/ |
| Anything else | the vendor's "App Store privacy" or "privacy manifest" page, and always its `PrivacyInfo.xcprivacy` in the archive |
