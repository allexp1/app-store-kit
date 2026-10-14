# Apple specs: sizes, limits and where Apple publishes them

Read from Apple's pages on **2026-10-14**. These numbers are also in `scripts/rules.json`, which is what
the scripts check against. Before a real submission, freeze a fresh copy into the kit
(`snapshot_rules.py freeze KIT`) and re-read any page whose hash changed. Blog posts are only hints.
Today, for example, they disagree about whether 6.9-inch or 6.3-inch is the required iPhone size.
Apple's page says the required one is the **medium Dynamic Island size**.

## Screenshots

Source: [Screenshot specifications](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications)

- 1 to 10 screenshots per device size and language. Formats are `.jpeg`, `.jpg` and `.png`.
- **Screenshots can't have an alpha channel or transparency.** Figma exports and simulator captures are RGBA, so always strip alpha (`validate_kit.py --fix`).
- Required for iPhone: at least one screenshot for **iPhone with Dynamic Island (medium display)**.
- Required for iPad, if the app runs on iPad: at least one screenshot for the **iPad 13-inch display**.
- If your UI is the same across sizes, upload only the highest required resolution. App Store Connect scales it down for smaller devices.

| Slot id (rules.json) | Apple's name | Portrait px (landscape = swapped) | Status |
|---|---|---|---|
| `iphone-duo-outer` | iPhone Duo, outer display | 1398 × 2034 | Required from **April 2027** for apps built with the iOS 27.1 SDK or later |
| `iphone-duo-inner` | iPhone Duo, inner display | 2007 × 2853 | Same as the outer display |
| `iphone-di-large` | Dynamic Island, large (Air, 18 Pro Max, 17 Pro Max, 16 Pro Max/Plus, 15 Pro Max/Plus, 14 Pro Max) | 1260 × 2736, 1290 × 2796, 1320 × 2868 | Optional (scaled from Face ID large if missing) |
| `iphone-faceid-large` | Face ID, large (14 Plus, 13/12/11 Pro Max, 11, XS Max, XR) | 1284 × 2778, 1242 × 2688 | Required only if `iphone-di-large` is missing |
| `iphone-di-medium` | Dynamic Island, medium (18 Pro, 17 Pro, 17, 16 Pro, 16, 15 Pro, 15, 14 Pro) | **1206 × 2622**, 1179 × 2556 | **Required** |
| `iphone-faceid-medium` | Face ID, medium (17e, 16e, 14, 13 family, 12 family, 11 Pro, XS, X) | 1170 × 2532, 1125 × 2436, 1080 × 2340 | Optional |
| `iphone-home-large` | Home button, large (8 Plus …) | 1242 × 2208 | Optional |
| `iphone-home-medium` | Home button, medium (SE 2/3, 8 …) | 750 × 1334 | Optional |
| `ipad-13` | iPad 13" (Pro M5/M4, Pro 3rd–6th gen, Air M2–M4) | **2064 × 2752**, 2048 × 2732 | **Required if the app runs on iPad** |
| `ipad-12.9` | iPad Pro 12.9" 2nd gen | 2048 × 2732 | Optional (scaled from 13") |
| `ipad-11` | iPad 11" family | 1488 × 2266, 1668 × 2420, 1668 × 2388, 1640 × 2360 | Optional (scaled from 13") |
| `ipad-10.5` | iPad 10.5" | 1668 × 2224 | Optional |
| `mac` | Mac (16:10, landscape) | 1280 × 800, 1440 × 900, 2560 × 1600, 2880 × 1800 | Required for Mac apps |
| `appletv` | Apple TV | 1920 × 1080, 3840 × 2160 | Required for tvOS apps |
| `vision` | Apple Vision Pro | 3840 × 2160 | Required for visionOS apps |
| `watch` | Apple Watch, Ultra 4/3: 422 × 514; Ultra 2/1: 410 × 502; S12–S10: 416 × 496; S9–S7: 396 × 484; S6–S4/SE: 368 × 448; S3–S1: 312 × 390 | as listed | Required for watchOS apps. Use the same size in every localization |

Native simulator captures that land exactly on a required size: **iPhone 17 = 1206 × 2622**,
iPhone 17 Pro Max = 1320 × 2868, iPad Pro 13-inch (M5) = 2064 × 2752. Check the numbers again when new devices ship.

## App previews

Source: [App preview specifications](https://developer.apple.com/help/app-store-connect/reference/app-information/app-preview-specifications)

- **Count and order:** up to 3 per device size and language. Previews are optional, and they always show before the screenshots.
- **Length:** 15–30 s. The poster frame defaults to 5 s. Processing can take up to 24 h.
- **File:** 500 MB at most.
- **H.264:** `.mov`, `.m4v` or `.mp4`, 10–12 Mbps target, progressive, up to High Profile Level 4.0, at most 30 fps.
- **ProRes 422 (HQ only):** `.mov`, about 220 Mbps VBR, progressive, at most 30 fps.
- **Audio:** stereo, AAC 256 kbps (PCM is also allowed with ProRes), 44.1 or 48 kHz. Use either one track with two channels or two mono tracks, all enabled.
- **Content:** App Review 2.3.4 says only screen captures of the app itself.

| Display | Accepted portrait (landscape = swapped) |
|---|---|
| Every iPhone with Dynamic Island or Face ID, and iPhone Duo | **886 × 1920** |
| iPhone Home button large (5.5") and 4" | 1080 × 1920 |
| iPhone Home button medium (4.7") | 750 × 1334 |
| iPad 13", 11", 10.5" | **1200 × 1600** |
| iPad 12.9" 2nd gen | 1200 × 1600 or 900 × 1200 |
| iPad 9.7" | 900 × 1200 |
| Mac, Apple TV | 1920 × 1080 (landscape only) |
| Apple Vision Pro | 3840 × 2160 (landscape only) |

## Text fields

Sources: [App information](https://developer.apple.com/help/app-store-connect/reference/app-information/app-information),
[Platform version information](https://developer.apple.com/help/app-store-connect/reference/app-information/platform-version-information),
[In-app purchase information](https://developer.apple.com/help/app-store-connect/reference/in-app-purchases-and-subscriptions/in-app-purchase-information),
[Product page](https://developer.apple.com/app-store/product-page/)

| Field | Limit | Notes |
|---|---|---|
| Name | 2–30 characters | Guideline 2.3.7 also says 30. Localizable |
| Subtitle | 30 characters | Shown under the name everywhere on the App Store |
| Promotional text | 170 characters | Can change any time without a new version. Doesn't affect search |
| Description | 4000 characters | Plain text, no HTML. Changing it needs a new version. The first sentence is what people read before "more" |
| Keywords | **100 bytes** | Commas, no spaces after commas. Each term must be more than 2 characters. Don't repeat the app or company name. No other apps' or companies' names |
| What's New | 4000 characters | Not available on version 1.0; required for every later version |
| Support URL | full URL with protocol | Must lead to real contact information |
| Marketing URL | full URL | Optional |
| Privacy Policy URL | URL | Required for iOS and macOS |
| Copyright | "2026 Example, Inc." | App Store Connect adds the © itself |
| Review notes | **4000 bytes** | IAP review notes: 4000 characters |
| Review contact phone | `+` and country code | Digits-only numbers are rejected |
| Sign-in info | demo account that doesn't expire | Only if the app needs login |
| IAP display name | 2–30 characters | The product page says 35 for promoted items. Keep 30 |
| IAP description | 45 characters | The product page says 55 for promoted items. Keep 45 |
| IAP promotional image | **1024 × 1024**, JPG/PNG, RGB, 72 dpi, flattened, no rounded corners | Only matters if the IAP is promoted on the App Store |
| IAP review screenshot | any accepted screenshot size | Can be replaced but not removed |
| Promoted IAPs | up to 20 items in total | In-app purchases and subscriptions together |

## Website badge and marketing

Source: [App Store marketing guidelines](https://developer.apple.com/app-store/marketing/guidelines/).
Badge artwork comes from <https://toolbox.marketingtools.apple.com/app-store/>, after you accept the artwork licence.

**The badge**
- Use the **black badge** by default. Its grey border is part of the artwork.
- The white badge is only for a layout with one badge where black looks too heavy.
- When other stores' badges appear too, use black and put the App Store badge first.
- Minimum height is **40 px on screen** (10 mm in print).
- Leave clear space of ¼ of the badge height (1/10 in very tight banners).
- Use one badge per layout or video, in a place below the main image or message.
- Never modify, angle or animate the badge. Use only Apple's localized artwork. "App Store" stays in English.
- When the badge is used, credit Apple: "Apple and the Apple logo are trademarks of Apple Inc., registered in the U.S. and other countries."

**Product images**
- Use Apple-provided bezels, unmodified, of the latest devices the app supports.
- Copy goes beside the device, never on top of it.
- Show the screen as the app really looks, on the latest OS, with fictional account data.

**Words**
- Write *App Store*, *iPhone*, *iPad* exactly like that. Product names are singular and never in all caps.
- Say "available on the App Store", never "at the App Store".
- Say "app name for iPhone", not "iPhone app name".
- Avoid naming iOS in marketing.

**Smart App Banner**
- The marketing page doesn't cover it. The meta tag is `<meta name="apple-itunes-app" content="app-id=NNNNNNNNN">`.
- Add it once the app has an App Store ID.
