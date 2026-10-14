# The screenshot story

Apple's points come from the [product page guidance](https://developer.apple.com/app-store/product-page/).
**House preferences** are this skill's defaults: they're checked as warnings and can be overridden.

## Apple's points

- Up to 10 screenshots. Depending on orientation, **the first one to three appear in search results** when there's no preview, so they must "highlight the essence of your app".
- Focus each screenshot on **one main benefit or feature**.
- If the app supports Dark Mode, "consider including at least one screenshot" that shows it.
- Previews autoplay muted, so the first seconds must work without sound. Previews always come before the screenshots.
- Screenshots show the app in use: not a title card, splash or login screen (2.3.3). Use fictional account data (2.3.9).

## House preferences (labelled as such in rules.json `house_rules`)

- **6–8 frames, one benefit each.** Captions have **six words or fewer**, and the benefit comes before the feature ("Find any photo by describing it", not "Semantic search").
- **The first three carry the pitch.** Frame 1 is the core job, frame 2 the differentiator, frame 3 the reassurance (privacy, no account, speed).
- **Light frames first, then one dark frame** for contrast in the scroll. Use the `dark` template with a dark-appearance capture.
- **Status bar at 9:41**, full battery and full Wi-Fi bars (Apple's own convention; not a rule).
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
