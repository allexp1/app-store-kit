# Apple specs: sizes, limits and where Apple publishes them

Read from Apple's pages on **2026-10-14** (re-checked against every live page the same day). These numbers are also in `scripts/rules.json`, which is what
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
- Scaling chain, as each row's note says (read 2026-10-14): Dynamic Island large missing → Face ID large is used; Face ID large missing → Dynamic Island large; Dynamic Island medium missing → Face ID large; Face ID medium missing → Dynamic Island medium; Home button large missing → Face ID medium; then Home button medium → 4" → 3.5" each fall back to the next larger one. iPad 12.9" and 11" fall back to 13"; 10.5" to 12.9"; 9.7" to 10.5".
- Legacy sizes not in `rules.json` (optional, rarely needed): iPhone 4" 640 × 1096 / 640 × 1136 (with status bar), landscape 1136 × 600 / 1136 × 640; iPhone 3.5" 640 × 920 / 640 × 960, landscape 960 × 600 / 960 × 640; iPad 9.7" 1536 × 2008 / 1536 × 2048 and 768 × 1004 / 768 × 1024 (landscape 2048 × 1496 / 2048 × 1536, 1024 × 748 / 1024 × 768).
- Search results: depending on orientation, the first one to three screenshots appear in search results when no app preview is available ([Product page](https://developer.apple.com/app-store/product-page/)). From iOS 27 a search-results creative asset can replace them; see `creative-assets.md`.

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

- **Count and order:** up to 3 per device size and language. Previews are optional, and they always show before the screenshots (iPhone, iPad, Mac, Apple TV), even if you reorder them in the app record.
- **Different aspect ratio:** "If you upload an app preview in an aspect ratio that differs from your screenshots, it appears in the 'A Closer Look' section on your product page" instead of before the screenshots.
- **Orientation:** iOS previews may be portrait or landscape (they rotate to their original orientation on play). macOS, tvOS and visionOS previews are landscape only.
- **Not available:** App Store for iMessage apps, and iPhone 3.5" displays.
- **Poster frame:** you choose it; it shows on the product page and during app install, and whenever the video doesn't autoplay. It applies everywhere the asset is used and **can't be edited after the asset is approved** ([Manage your App Store assets](https://developer.apple.com/help/app-store-connect/manage-app-information/manage-your-app-store-assets)).
- **Playback:** previews autoplay with muted audio, so the first seconds must work silently ([Product page](https://developer.apple.com/app-store/product-page/)). Up to three previews may also appear in search results ([Asset best practices](https://developer.apple.com/app-store/asset-best-practices/)).
- **Length:** 15–30 s. The poster frame defaults to 5 s. Processing can take up to 24 h.
- **File:** 500 MB at most.
- **H.264:** `.mov`, `.m4v` or `.mp4`, 10–12 Mbps target, progressive, up to High Profile Level 4.0, at most 30 fps.
- **ProRes 422 (HQ only):** `.mov`, about 220 Mbps VBR, progressive, at most 30 fps.
- **Audio:** stereo, AAC 256 kbps (PCM is also allowed with ProRes, at 16, 24 or 32 bit), 44.1 or 48 kHz. Use either one track with two channels or two mono tracks, all enabled. With H.264 the page lists AAC only.
- **Missing language:** the preview in the "next best available language" is shown and also played at install.
- **Content:** App Review 2.3.4 says only screen captures of the app itself.

| Display | Accepted portrait (landscape = swapped) |
|---|---|
| Every iPhone with Dynamic Island or Face ID, and iPhone Duo | **886 × 1920** |
| iPhone Home button large (5.5") and 4" | 1080 × 1920 |
| iPhone Home button medium (4.7") | 750 × 1334 |
| iPad 13", 11", 10.5" | **1200 × 1600** |
| iPad 12.9" 2nd gen | 1200 × 1600 or 900 × 1200 |
| iPad 9.7" | 900 × 1200 |
| iPhone 3.5" | no previews |
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

**Badge, more rules (read 2026-10-14)**
- Badges come in 50 localizations, for the App Store (iPhone and iPad), the Mac App Store and Apple TV.
- Use the **pre-order** badge only while the app is on pre-order; swap it for the download badge at launch.
- Never use other icons, logos or images from apple.com, never use the Apple logo in place of the word Apple, and never the standalone Apple logo.
- In print, the badge may be one colour when black and white inks aren't used, if contrast stays clear.

**Product images (device frames)**
- Use Apple-provided bezels, unmodified, of the latest devices the app supports.
- "Modifications" includes reflections, shadows, highlights, graphics that enter or leave the screen, cropping, tilting, obstructing, animating, flipping or spinning, and making buttons or icons from a device image.
- Copy and "violators" go beside the device, never on top of it.
- Minimum device size: **200 px tall on screen**, 25 mm in print. Keep the correct relative scale between devices.
- Not allowed: 3D renderings or any simulation of an Apple product; illustrations of Apple products (except instructional material); die-cut shapes; graphics or logotypes that stand for an Apple product.
- Generic device illustrations must not show details unique to Apple products (Home button, sensor housing, Ring/Silent switch, volume controls).
- Show Apple products on their own: no competing products in the same image, no cases or covers.
- Show the screen as the app really looks, on the latest OS, with fictional account data. Never a blank screen.
- **Status bar:** full network (or product designator), full Wi-Fi and full battery. A full-screen app may extend over the status bar. Show 5G only if the app is optimized for 5G.
- **Home Screen:** don't show one, except to show the app's own widget with no third-party content.
- **Push notifications:** one notification from your app, on the Lock Screen; never several, never other apps'.
- For apps inside Messages, Siri, Phone or Maps, show the app inside Apple's UI exactly as it appears.

**Photography and video of devices**
- Straight-on shots preferred; no extreme angles; colour, shape and size accurate; nothing "fantastic or unrealistic".
- Show the back only in natural use; don't feature or hide the Apple logo.
- Video: after an establishing shot of the whole device you may pan and zoom; use simple fades or dissolves; don't use Apple gestures (Multi-Touch, trackpad swipes) as transitions.
- Start with the app open. If sequences are shortened, show a "sequences shortened" disclaimer. Use the app's own sounds, never the device's native sounds.
- End a video with Apple's trademark credit lines.

**Words**
- Write *App Store*, *iPhone*, *iPad* exactly like that. Product names are singular and never in all caps. *iPhone* starts with a lowercase i even at the start of a sentence.
- Say "available on the App Store" or "download from the App Store", never "at the App Store", "downloadable", "Apple App Store" or "iPhone App Store".
- Say "app name for iPhone" (or "works with iPhone"), not "iPhone app name". With a company name: "Company App for iPhone and iPad".
- List every Apple product the app runs on, and none it doesn't. Don't say "smartphone" or "tablet".
- Avoid naming iOS, macOS, tvOS or watchOS in marketing.
- **Apple Vision Pro:** three words, no "the", never "headset". It can't be in the app name, but it can be in the description. Call the app a "spatial computing app", not AR, VR, XR or MR.
- **Apple Watch:** no "the", don't pun on "watch" or "time"; name the series when features depend on it.
- **Apple In-App Purchase** is title case, no "the"; use Apple's mark artwork, never your own localized version.
- When other platforms are named in copy, list Apple products first; never show Apple product images next to other products.
- URLs may contain an Apple trademark only after your company or product name (`company.com/app/iphone`), never at the start (`iphoneapp.com`).
- **Never translate:** App Store, Apple Pay, Apple Pencil, Apple TV, Apple Vision Pro, Apple Watch, iMac, iPad, iPhone, iPod touch, MacBook Air, MacBook Pro, Siri.
- **Trademark symbols** (™, ℠, ®) only in communications distributed only in the United States, after the first mention in body copy; never in headlines or on the badge.
- **Credit lines** are needed worldwide wherever legal notices appear, once per communication; outside the US use "… are trademarks of Apple Inc., registered in the U.S. and other countries." The legal notice may be translated, the trademarks not.
- Nothing may suggest an association with, or endorsement by, Apple.

**Smart App Banner**
- The marketing page doesn't cover it. The meta tag is `<meta name="apple-itunes-app" content="app-id=NNNNNNNNN">`.
- Add it once the app has an App Store ID.

## App icon (store and device)

Sources: [HIG App icons](https://developer.apple.com/design/human-interface-guidelines/app-icons) (change log: "June 8, 2026 · Refined guidance for Liquid Glass"),
[Icon Composer](https://developer.apple.com/icon-composer/), read 2026-10-14.

| Platform | Layout | After system mask | Canvas | Style | Appearances |
|---|---|---|---|---|---|
| iOS, iPadOS, macOS | square | rounded rectangle | **1024 × 1024 px** | layered | default, dark, clear light, clear dark, tinted light, tinted dark |
| tvOS | landscape rectangle | rounded rectangle | 800 × 480 px | layered (parallax, 2–5 layers) | n/a |
| visionOS | square | circle | 1024 × 1024 px | layered (3D, background + 1–2 layers) | n/a |
| watchOS | square | circle | **1088 × 1088 px** | layered | n/a |

- Colour spaces: sRGB, Gray Gamma 2.2, Display P3 (not on visionOS).
- Build layered icons in **Icon Composer** (in Xcode and as a download; the download needs **macOS Tahoe 26.4 or later**). One design serves iPhone, iPad, Mac and Apple Watch; it can be customised per platform. Icon Composer annotates **Default, Dark and Mono** modes, and exports a flattened version for marketing.
- Icon Composer adds Liquid Glass: specular highlights (inside, outside or automatic), refraction per layer, translucency, shadows, and a vertical light angle from above. Older `.icon` files render with the new material automatically.
- People choose default, dark, clear or tinted Home Screen icons. The system generates any variant you don't provide. Keep core features the same in every appearance.
- Provide **square, unmasked layers**; pre-masked corners spoil the highlights and make edges jagged. Keep content centred. Prefer clear edges over soft or feathered ones.
- Prefer vector layers (SVG or PDF); PNG for mesh gradients and raster art. Background: solid or gradient, set in Icon Composer; an imported background must be full-bleed and opaque.
- Don't add your own highlights, drop shadows, bevels, blurs or glows; the system adds dynamic ones.
- Text only if essential (a single letter mnemonic is fine). No "Watch", "Play", "New" or "For visionOS". Prefer illustrations to photos. Don't copy standard UI components or screenshots. **Never Apple hardware replicas.**
- watchOS: don't use a black background.
- Alternate icons (iOS, iPadOS, tvOS, visionOS) need their own dark, clear and tinted variants and are reviewed.
- Product page optimization can test alternate icons, but every icon variant must be in the published binary ([PPO](https://developer.apple.com/app-store/product-page-optimization/)).

## Creative assets (product page header, search results, in-app events)

New with iOS and iPadOS 27. Sizes, durations and rules: `creative-assets.md`. Sources:
[Creative assets specifications](https://developer.apple.com/help/app-store-connect/reference/app-information/creative-assets-specifications),
[Asset best practices](https://developer.apple.com/app-store/asset-best-practices/).

