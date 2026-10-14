---
last_updated: 2026-10-14
review_interval_days: 7
mode: advisory
spec: living-skills/1.1
---

# App Store submission: current facts

> Baseline (2026-10-14): SKILL.md, references/ and scripts/rules.json were written
> on this date from the same PRIMARY pages and already contain everything below.
> From here on this file carries what changes after 2026-10-14. Rule numbers that
> the scripts enforce live in scripts/rules.json; when they change, offer the edit.

## Screenshots (App Store Connect Help, "Screenshot specifications")

- 1–10 per device size and language; .jpeg/.jpg/.png; **no alpha channel or transparency**.
- **Required:** iPhone with Dynamic Island (medium display), 1206×2622 or 1179×2556
  (iPhone 18 Pro, 17 Pro, 17, 16 Pro, 16, 15 Pro, 15, 14 Pro); iPad 13-inch,
  2064×2752 or 2048×2732, when the app runs on iPad.
- Optional large Dynamic Island: 1260×2736, 1290×2796, 1320×2868 (iPhone Air,
  18 Pro Max, 17 Pro Max …). Face ID large 1284×2778 / 1242×2688 is required only
  when the large Dynamic Island set is missing.
- **iPhone Duo:** outer 1398×2034, inner 2007×2853 (landscape swapped); required
  from **April 2027** for apps using the iOS 27.1 SDK or later.
- Highest required resolution is scaled down for smaller devices when the UI is
  the same.

## App previews ("App preview specifications")

- 15–30 s, ≤ 30 fps, ≤ 500 MB, up to 3 per size and language, always shown before
  screenshots, poster frame default 5 s, processing up to 24 h.
- H.264 (.mov/.m4v/.mp4) 10–12 Mbps, progressive, ≤ High Profile Level 4.0; or
  ProRes 422 HQ (.mov) ~220 Mbps VBR.
- Audio stereo, AAC 256 kbps (PCM allowed with ProRes), 44.1 or 48 kHz.
- iPhone (all Dynamic Island / Face ID sizes and Duo) **886×1920**; iPad 13"/11"/
  10.5" **1200×1600**; Mac/Apple TV 1920×1080; Vision Pro 3840×2160.

## Text limits

- Name 2–30 chars; subtitle 30; promotional text 170 (editable any time, not
  indexed); description 4000 (plain text); **keywords 100 bytes**, terms > 2 chars,
  don't repeat app/company name; What's New 4000 (not on version 1.0).
- Review notes 4000 bytes; review phone in + country-code format; demo account
  must not expire.
- IAP: display name 2–30, description 45 (product page says 35/55 for promoted
  items); promo image 1024×1024 RGB flattened, no rounded corners; up to 20
  promoted items.

## App Review Guidelines (no date shown on the page)

- 2.3.7: app names limited to 30 characters; no trademarks, popular app names,
  prices or irrelevant phrases in metadata.
- 2.3.3 screenshots show the app in use; 2.3.4 previews only screen captures of
  the app; 2.3.8 "For Kids"/"For Children" reserved; 2.3.10 no other platforms;
  2.3.12 What's New must describe changes.
- 5.1.1 privacy policy link in App Store Connect and in the app; account deletion
  in-app when accounts exist. 5.1.2(i) tracking needs ATT permission; apps may not
  require enabling tracking to work.

## Privacy labels

- You disclose third-party SDK collection; not Apple's own frameworks.
- "Tracking" = linking with third-party data for targeted ads / ad measurement, or
  sharing with a data broker. Data is "linked" unless de-identified before
  collection.
- Google Mobile Ads (page updated 2026-10-13): may collect IP-derived coarse
  location, device ID, advertising data, product interaction, crash data,
  performance data; manifest shipped from SDK 11.2.0. UMP page gives no
  data-collection statement.

## Marketing

- Black badge preferred, App Store badge first among store badges, ≥ 40 px high
  onscreen, clear space ¼ of height, one per layout, never modified; "App Store"
  never translated; credit line required.

## Tooling facts (observed 2026-10-14)

- iPhone 17 simulator captures at exactly 1206×2622; iPad Pro 13-inch (M5) at
  2064×2752; captures are RGBA with an sRGB profile.
- Figma `download_assets` (scale 1) and `get_screenshot` (maxDimension = height)
  export exact-size RGBA PNGs without ICC; alpha must be stripped.
- Codex CLI 0.162.1 image generation outputs 1086×1448 for portrait 3:4 prompts.
