# The screenshot story

Apple's points come from the [product page guidance](https://developer.apple.com/app-store/product-page/).
**House preferences** are this skill's defaults: they're checked as warnings and can be overridden.

## Apple's points

- Up to 10 screenshots. Depending on orientation, **the first one to three appear in search results** when there's no preview, so they must "highlight the essence of your app".
- Focus each screenshot on **one main benefit or feature**.
- If the app supports Dark Mode, "consider including at least one screenshot" that shows it.
- Previews autoplay muted, so the first seconds must work without sound. Previews always come before the screenshots. A preview in a different aspect ratio from the screenshots moves to the "A Closer Look" section instead.
- Screenshots show the app in use (2.3.3). Apple's [screenshot help](https://developer.apple.com/help/app-review/guideline-reference/2-3-3-screenshots) makes it a count: **more than half** of the screenshots of each device type and language must show the app in use (3 need 2, 4 need 3); the rest may be marketing (title card, value statement). A splash, login or sign-in screen doesn't count. Overlays are allowed as long as the app stays visible, and an app image may span several screenshots. Use fictional account data (2.3.9).
- **House preference:** every panel shows a real screen. That is stricter than Apple and can be relaxed for one marketing panel; `studio/spec.py` makes Apple's majority an error and a panel without a screen only a warning (set `no_screen: true` to mean it).

## Apple's asset best practices (read 2026-10-14)

Source: [App Store asset best practices](https://developer.apple.com/app-store/asset-best-practices/).

- **Show what people can expect.** Depict the app in use; "avoid using the entire asset to highlight general accolades or call-to-action statements".
- **Lead with your best features,** sequenced "so they tell a cohesive story that's reflective of how someone would use your app".
- Text: "use a short phrase that enhances your visual rather than describes it", and localize it for every language the app supports.
- Keep key elements legible and inside a safe area; keep the focal point centred to avoid clipping.
- Feel current: use the latest UI. Aim for one clear focal point per image.
- Use one visual system across all assets (palette, iconography, fonts, message, tone).
- Never in an asset: specific prices or discounts, website URLs, copyright symbols, unverifiable awards, other platforms' logos, or Apple recognitions (Editor's Choice, App of the Day, Apple Design Award).
- Every asset must be 4+, even if the app is rated higher.
- Previews: real UI, strong first seconds, a beginning, middle and end; pick a poster frame that works alone. Up to three previews may appear in search results.

## Device frames and the status bar (Apple's marketing guidelines)

Source: [Marketing guidelines](https://developer.apple.com/app-store/marketing/guidelines/). These rules govern marketing materials; on the App Store itself a device frame is optional (2.3.3 only asks for the app in use). When the kit draws a device, follow them anyway:

- Use Apple's own product bezels, of the latest devices the app supports, unmodified: no tilt, crop, shadow, reflection, 3D render or anything coming out of the screen.
- Captions sit beside the device, never on top of it.
- Status bar: full signal, full Wi-Fi, full battery (Apple's rule). The 9:41 time is Apple's convention, not a rule.
- No Home Screen, except your own widget with no third-party content. One push notification at most, on the Lock Screen.

## House preferences (labelled as such in rules.json `house_rules`)

- **6–8 frames, one benefit each.** Captions have **six words or fewer**, and the benefit comes before the feature ("Find any photo by describing it", not "Semantic search").
- **The first three carry the pitch.** Frame 1 is the core job, frame 2 the differentiator, frame 3 the reassurance (privacy, no account, speed).
- **Light frames first, then one dark frame** for contrast in the scroll. Use the `dark` template with a dark-appearance capture.
- **Status bar at 9:41** (Apple's own convention; not a rule). Full battery, full Wi-Fi and full signal are Apple's rule for marketing images (see above).
- Captions contrast at least 4.5:1 with the background (WCAG AA for large text is 3:1; this skill asks for more).
- Keep captions inside the top 20% and clear of the device.
- One visual system across the set: same background, same type and size, same device treatment. Variety comes from the screens.

## Frame patterns

| Pattern | Template | When |
|---|---|---|
| Caption above device | `caption-top` | Default. Most legible in search results |
| Caption below device | `caption-bottom` | When the screen's key content sits at the top |
| Full-bleed screen | `full-bleed` | Immersive content (photos, maps, games). The caption band hides the status bar |
| Dark | `dark` | The one dark-mode frame |

## Workflow

1. Write the story in `frames.yaml`: id, caption per locale, which screen.
2. Get 2–3 **directions** first, side by side (Claude Design or rendered HTML): caption style, colour, device or none. Let the human pick one before producing every size.
3. Capture the screens (`capture.sh`), render or compose, then validate.
4. Re-check wrapping in every locale. German and French captions run about 30% longer.

## Content inside the screens

- Use the generated sample library only, see `image-generation.md`.
- Pick the most attractive photos for frames 1–3.
- Real people's faces, brands, logos and documents never appear.
