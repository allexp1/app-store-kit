# Header and search-results assets ("creative assets")

New with iOS / iPadOS 27 (WWDC26 session 205). In App Store Connect: the version page › **Header | Search Results**
tabs, each "0 of 1 … Asset", Browse Assets / Upload / Remove, a **Preview** button, and "Explore templates".
If no search-results asset is added, the screenshots and previews are shown in search instead. Read live
2026-10-14 (the page, the API ref data and Apple's Figma template).

## What to make

**One universal image does both.** A 5244×2950 PNG is accepted as the header and as the search-results asset.
Make that first; add a separate `header` or `search` file only when the crop of the universal one doesn't work.

| Kit file | Placement(s) | Images | Videos |
|---|---|---|---|
| `creative/<locale>/universal.png` | header + search results | 5244×2950 (16:9), PNG only | none: Apple has no 16:9 video |
| `creative/<locale>/header.png\|jpg\|mov` | header only | 3840×1646 (21:9) PNG or JPEG, or 5244×2950 PNG | 3840×1646, 30 or 60 fps, 5–30 s |
| `creative/<locale>/search.png\|jpg\|mov` | search results only | 3:2 from 1920×1280 to 3840×2560 PNG or JPEG, or 5244×2950 PNG | 3:2 from 1920×1280 to 3840×2560, 30 or 60 fps, 5–30 s |

No alpha or transparency anywhere. Video files: .mov, .m4v or .mp4. Videos loop. In search results they are muted
and can't be unmuted; on the product page they start muted and people can unmute them, so design for silence and,
if there is sound, keep it a clean-looping brand texture. In App Store Connect a universal asset gets the option
"Use header asset in search results". Sources: https://developer.apple.com/help/app-store-connect/reference/app-information/creative-assets-specifications
(read 2026-10-14), the live version page and `appAssetLibraryRefData` (`i5244x2950a0`, `i3840x1646a0`,
`i3x2w1920~3840`). In-app event cards (16:9) and event details (9:16) use the same Asset Library; see that page. `scripts/validate_kit.py`
checks these; a frozen `rules.json` may carry its own `creative_assets` block.

## Safe areas (Apple's Figma template)

Templates: Figma (universal), Photoshop and Pixelmator (header, search results, universal), Sketch (universal),
linked from the best-practices page. The Figma one: https://developer.apple.com/go/?id=figma-creative-assets-templates (a `.fig` file, "Creative Assets
Templates", dated 2026-08-05). Each frame has an **Art Safe Area**. Keep the one idea of the picture (the app's
key screen, the subject) inside it; everything else is supporting art that may be cropped or covered.

| Frame | Size | Art safe area (x0, y0 → x1, y1) |
|---|---|---|
| Universal | 5244×2950 | 1921, 660 → 3323, 1622 (1402×962) |
| Search | 3840×2560 | 836, 765 → 3004, 1795 |
| Header | 3840×1646 | 1097, 493 → 2743, 1154 |

The safe area is small, centred and a little high. Apple's placeholder art puts the heads in it and lets the
bodies run below. On a universal image the header shows roughly a centred 21:9 band and search a centred 3:2
band (UNCONFIRMED how Apple scales it: always check with the **Preview** button in App Store Connect).
`scripts/render_creative.py --guides` draws all of this on a small preview.

## Rules (Apple's guidance for these assets)

Source: https://developer.apple.com/app-store/asset-best-practices/ (read 2026-10-14). Unlike screenshots and
previews, creative assets don't have to show the app in use: Apple calls them images or videos of the app's
"overarching value, brand, or excitement", which may show brand, seasonal offers or new content. They must still
relate to what the app does.

- Header: one clear idea, not dense, for a first-time visitor (PPO can test header visuals).
- Search results: "state the obvious", the purpose clear at a glance; show the firsthand experience (interface,
  content or gameplay).
- Current visuals and the latest UI; one clear focal point, centred, inside the safe area.
- Video: a poster frame that works alone (locked after approval), start with the value, no quick cuts or fast
  motion, loop seamlessly.
- **Show the core interaction, not a still pose.** If the app's main action is a gesture (swipe, drag, pinch),
  catch it mid-gesture: the card tilted on its way out, the stamp or colour the app shows, the next item
  underneath, or make it a video. Lesson from Swipr (2026-10-14): a resting card with the buttons below did not
  say "swipe left or right" to the owner.
- Text is optional. If used: a short phrase that adds something rather than describing the picture, inside the
  safe area, and localized per locale.
- Not allowed: specific prices or discounts, website URLs, ©, unverifiable claims or awards, other platforms'
  or marketplaces' logos, Apple recognitions (Editor's Choice, App of the Day, Game of the Day, Apple Design
  Award), anything above 4+; in games, gore or weapons pointed at a person or the viewer. Guideline 2.3 and
  Apple's Advertising Policies apply.
- The same review rules as screenshots: what is shown must be in the app.

## Making it

1. Start from `templates/creative-universal.html` (a device with the key screen in the safe area and supporting
   cards around it). Change the story to fit the app; only the frame class and the size are fixed.
2. Render: `render_creative.py templates/creative-universal.html --out KIT/creative/en-US/universal.png
   --guides /tmp/guides.jpg --set SCREEN=captures/... --set LEFT_BG=#... ...` (placeholders `{{NAME}}` are
   filled with files as data URIs, or with plain values).
3. Look at the guides preview, then show the owner the asset itself.
4. `validate_kit.py KIT`, then `asc_sync.py plan KIT --only media`: the plan lists "Header asset" and
   "Search results asset" per locale.
5. Upload is part of the one 🛑 apply yes. A universal file is uploaded once (category `CREATIVE_ASSETS`) and
   placed twice.

## API

Asset Library, as for screenshots (`asc-api.md` §4a), with three differences:
- category **`CREATIVE_ASSETS`** (fixed at upload; it can't be changed later);
- placement types `PRODUCT_PAGE_HEADER_ASSET` and `APP_STORE_SEARCH_RESULTS_ASSET`; the group comes from the
  ref data `placementTypes[].specMappings[].placementGroupId` (live: `DEFAULT_PROFILE`, platform `ANY`), read
  with `filter[placementTypes]=PRODUCT_PAGE_HEADER_ASSET,APP_STORE_SEARCH_RESULTS_ASSET`;
- max one placement per group per localization, so there is no ordering request.

## Review and going live

- They go live when the version is released. The first time, they go to review with the first app version.
- After an app version has been approved, an asset can also go to review on its own from Asset Library. An asset
  placed on a version, custom product page, PPO test or event is reviewed with that and can't go on its own.
- **Swap on a live app without a new version** (browser): the live version › Header and Search Results › Browse
  Assets › an approved asset › Next › **Publish**. Through the API: UNCONFIRMED.
- Remove: Delete on the placement; the asset stays in Asset Library. Statuses: Uploading, Processing, Prepare for
  Submission, Ready for Review, Waiting for Review, In Review, Accepted, Approved, Rejected, Archived.
- Roles: Account Holder, Admin, App Manager or Marketing manage assets; Account Holder, Admin or App Manager
  submit them. Source: https://developer.apple.com/help/app-store-connect/manage-app-information/manage-your-app-store-assets

Custom product pages and product page optimization treatments take their own header and search assets (same
limits).
