# Creative director: screenshot campaigns

`scripts/campaign.py` turns the app's real screenshots into a designed App Store set: several creative directions
first, then one chosen direction rendered as a continuous panorama (or separate panels), cut into exact-size PNGs
for every locale and device slot. It is the "designed" alternative to `render.py`'s caption templates.

It does not talk to App Store Connect. `render --install KIT` copies validated panels into
`KIT/screenshots/<locale>/<slot>/`; from there `validate_kit.py` and `asc_sync.py` (with its own 🛑) take over.

## The workflow

| Step | Command | Who decides |
|---|---|---|
| 1. Analyze the app | `campaign.py analyze SCREENS... --icon ICON` (palette, UI blocks, light/dark), plus reading the code, the store texts and the website | Claude |
| 2. Inspiration | look at references the owner gives (or galleries such as previewed.app templates); note **techniques** (fanned phones, text between tilted devices, one dark spread), never copy layouts, art or text | Claude |
| 3. Campaign file | `campaign.py init KIT --app NAME --screens DIR [--icon] [--panels 6]` → `KIT/campaign/campaign.yaml` with a palette drawn from the icon and screens and `[PLACEHOLDER]` copy | Claude |
| 4. Copy | write the storyboard (one benefit per panel; rules below); `campaign.py check` | owner approves |
| 5. Concepts | `campaign.py concepts campaign.yaml` → `out/concepts/contact-sheet.png`: six directions, each a full low-res panorama with its rationale, type and palette | **owner picks** (or combines two) |
| 6. Render | set `campaign.engine` (or eject and edit), `campaign.py render campaign.yaml` | Claude, QA |
| 7. Review | read `report.md`, look at `presentation.png` and `store-preview.png` (the first three at search-result size); fix and re-render | owner approves |
| 8. Export | `campaign.py validate out` then `render --install KIT` | then the kit's normal pipeline |

Show the contact sheet and the final presentation to the owner as images. Never skip step 5 unless the owner already
named a direction.

## Modes

| Mode | When | How |
|---|---|---|
| A Full campaign | "make my screenshots" | all steps |
| B Concept exploration | "show me directions" | steps 1–5 only; `concepts --engines a,b,c` for a custom set, or a `concepts:` list in the file (each `{engine, name, rationale, type, palette}`) for named variants |
| C Panoramic | "one continuous scene" | engine `panoramic-flow`, `device-cluster` or `immersive`; every engine renders one master and slices it, so any element may cross a seam |
| D Redesign | existing store screenshots | `analyze` the old set; crop the real UI out of them (or recapture) into `screens:`; keep what converts, change the presentation |
| E Match brand | strict brand book | brand palette in `design.palette`, the owner's font files in `design.type.files` (referenced in place, never copied), `minimal-premium` or `editorial`; no engine palette overrides |
| F Experimental | "surprise me" | `typographic-hero`, `immersive` with generated art, `illustrated`; push rotation, scale and crops; QA rules still apply |
| G Localization | another language | add the locale to `campaign.locales`, copy per locale in the storyboard, `{locale}` in screen paths; RTL mirrors (below) |
| H Regenerate one | "panel 4 is wrong" | `render --panel 4`; the report warns if the change also altered other panels (an element crossing the seam); then re-render all |
| I Export only | new slot or size | add the slot (`iphone-di-large`, `ipad-13`, or `{id, width, height}`) and `render --slot S` |
| J Asset refresh | the app's UI changed | replace the files under `screens:` (same ids); `render`; layout, copy and tokens stay |

## The campaign file

Five parts, kept apart so one changes without the others:

```yaml
app: {name: Ridgeline, icon: icon.png}
campaign:                     # EXPORT
  name: Ridgeline launch
  panels: 6                   # 1–10
  slots: [iphone-di-large]    # rules.json slot ids (the largest accepted size is used) or {id, width, height}
  locales: [en-US, he, ru]
  primary_locale: en-US
  engine: panoramic-flow      # see `campaign.py engines`
  rtl_flow: mirror            # mirror | keep
  mockup_only: false          # true only for concepts the owner asked for without real screens; never installs
design:                       # TOKENS, propagate to every panel
  palette: {bg, bg2, ink, muted, accent, accent2, dark, light}   # #hex; refer to them by name, "accent@0.4" for alpha
  type: {preset: friendly-consumer, accent_style: color|italic|marker|pill|circle|underline|box|serif|gradient, display: {family, weights}, files: [{family, src, weight}]}
  device: {model: iphone|ipad|screen, finish: titanium|graphite|silver|black|white|sand|navy|orange|sage|"#hex",
           shadow: soft|float|contact|long, glare: 0.08, focal: 2.6, light: 315}
  grain: 0.035
  safe: {side: 0.07, top: 0.05, bottom: 0.035}
screens:                      # CONTENT: real captures; a path, or {iphone:, ipad:} or per-slot; {locale}/{lang} allowed
  map: screens/{locale}/map.png
storyboard:                   # COPY, one per panel in store order
  - id: hero
    role: hero                # hero value differentiator experience secondary closing feature proof
    screen: map               # the main screen; `screens: [home]` adds more for engines that show two phones
    kicker: {en-US: "Trail maps"}
    headline: {en-US: "Find the **trail** worth the climb", he: "..."}   # **word** = the accent
    sub: {en-US: "..."}
    chips: {en-US: [Offline maps, Elevation], he: [...]}   # optional feature chips, 1–3 words each, one list per locale
    stat: "4/5"               # optional stat callout (needs evidence:), with
    stat_label: {en-US: "of hikers plan faster after a week"}
    footnote: {en-US: "*In-app survey of 1,200 hikers, Sept 2026."}   # small print a stat or claim needs
    evidence: "..."           # required for any number, ranking, rating or award (see Copy)
artwork:                      # ARTWORK with provenance (image layers, immersive backgrounds)
  dawn: {file: art/dawn.jpg, role: scene, source: "generated, tool X, prompt in art/dawn.txt", licence: "owner's"}
background: [...]             # LAYOUT, only after `eject` (otherwise the engine supplies it)
layers: [...]
extra_layers: [...]           # added on top of an engine's layers without ejecting
```

`campaign.py eject campaign.yaml --engine E` writes the engine's layout into the file as plain layers, so a designer
(or Claude) can move any element by hand. Rendering a file with `layers:` uses them as written.

### Units

- `x` is in **panels** from the left edge of panel 1 (`x: 2.5` is the middle of panel 3); elements may cross seams.
- `y` is a fraction of the panel height.
- `w`, sizes and radii are in `u = min(panel width, panel height / 2.17)`, so a layout holds across iPhone and iPad.
- Text blocks are per panel: `panel`, then `x`, `y`, `w` as fractions of that panel; `anchor: top|bottom|center`,
  `align: start|center|end`.
- Rotation `[rx, ry, rz]` in degrees (CSS 3D, perspective from `design.device.focal`).

### Layers

| type | main keys (an ejected file shows complete examples) |
|---|---|
| `device` | `screen`, `x`, `y`, `w`, `rotate`, `finish`, `model`, `shadow`, `glare`, `island`, `z` |
| `card` | a real crop of a screen lifted out in 3D: `screen`, `crop: [x, y, w, h]` (fractions), `x`, `y`, `w`, `rotate`, `radius`, `shadow` |
| `text` | `panel`, `x`, `y`, `w`, `align`, `anchor`, `color`, `accent`, `accent_style`, `shadow`, `chip_style: glass\|solid\|outline\|sticker`, `chip_fill`, `items: [{role: kicker\|headline\|sub\|chips\|stat\|label\|footnote, copy: <id>.<field>, size, color, opacity}]` |
| `display` | giant decorative text (`text`, `x`, `y`, `size`, `outline`, `opacity`, `tracking`): never the only place a claim is made |
| `shape` | `kind: blob\|wave\|ring\|circle\|path\|rect\|dots\|arc`, `fill`, `stroke`, `blur`, `opacity` and kind-specific keys |
| `glow` | soft light: `x`, `y`, `r`, `color`, `opacity`, `blend` |
| `image` | `art` (from `artwork:`), `x`, `y`, `w`, `h`, `fit`, `blend`, `mask: blob` (an organic rounded crop) |
| `icon` | the app icon (`app.icon`): `x`, `y`, `w` |

Backgrounds: `solid`, `linear` (`angle`, `stops`), `radial`, `conic`, `panel` (a colour for one panel: the dark
spread), `image` (`art`).

## Composition engines

`campaign.py engines` lists them. Each takes the storyboard and the analysed screens and returns layers.

| Engine | Pattern |
|---|---|
| `panoramic-flow` | one brand-colour wave runs through every panel; paired phones lean across the seams, text alternates top and bottom |
| `floating-3d` | studio product shots: phones in lit space at three-quarter angles, a second phone for depth |
| `editorial` | magazine grid, big serif headline, numbered kickers, one inverted dark spread |
| `typographic-hero` | the words are the picture; the app name runs behind every panel in outline |
| `feature-explosion` | the screen's own UI cards float out of the phone (detected automatically from the screenshot) |
| `cinematic` | dark stage, rim light, graphite phones; accent chosen for contrast |
| `minimal-premium` | lots of air, one phone per panel, small type |
| `device-cluster` | overlapping groups of phones at different depths |
| `immersive` | a full-bleed scene (`artwork` with `role: scene`) behind the phones; a procedural scene if none |
| `illustrated` | flat shapes and blobs in the palette, playful type |
| `big-type` | saturated colour-block panels, the first headline fills its panel, one phone straddles the first seam |
| `before-after` | a dim "before" panel meets a bright "after" across one phone; later panels pair a small phone with a sourced stat |
| `glass` | pale gradient light, glass chips under the headline, a real UI card floating off the phone, one word in italic serif |
| `sticker-pop` | sky gradient, the key word in a gradient pill, feature chips stuck on as tilted stickers above a big phone |

Every engine also places what the storyboard asks for: `chips` and a `stat` join the panel's caption block (so they
never collide with it), and a `footnote` goes to the free edge of the panel on a quiet backing that stays readable
over a phone. `before-after` reads best when panel 1's copy is the "before" (`sub` as short lines) and panel 2's
the "after"; `concepts --engines big-type,before-after,glass,sticker-pop,...` shows them beside the defaults.

### Accent styles

`**word**` in a headline marks the accent; `design.type.accent_style` (or `accent_style` on one text layer) sets how
it looks: `color`, `italic`, `marker` (highlighter), `pill` (the word on a gradient pill), `circle` (a hand-drawn
ring), `underline` (a curved swash), `box` (a selection box with handles), `serif` (the word in Instrument Serif
italic, loaded only when used), `gradient` (accent to accent2 text fill). One accent per headline reads best.

The six defaults for `concepts` are the first six. Adding an engine: write a function in
`scripts/studio/engines.py` decorated with `@engine(name, label=, pattern=, type_preset=, mood=)` that returns
`{"background": [...], "layers": [...]}`, using the helpers `e.cap(panel, ...)`, `e.dev(panel, x, y, w, rotate)`,
`e.cards_for(panel)`; add it to the test parametrization (it runs automatically for every registered engine).

## Typography presets

`campaign.py presets`. Open-licence Google Fonts, cached in `~/.cache/app-store-kit/fonts` (`--offline` uses only
the cache; a missing face falls back to the system and QA says so). Hebrew, Cyrillic, Arabic, Greek, CJK and Thai get
a matching fallback face when the preset lacks the script.

| Preset | Display / text | For |
|---|---|---|
| `premium-editorial` | Instrument Serif / Geist | lifestyle, travel, finance with taste |
| `bold-geometric` | Unbounded / Manrope | utility, finance, confident |
| `modern-tech` | Geist / Geist (+ Mono) | developer, productivity |
| `friendly-consumer` | Bricolage Grotesque / DM Sans | consumer, health, outdoors |
| `luxury-minimal` | Cormorant Garamond / Jost | fashion, beauty, premium |
| `dynamic-sport` | Anton / Barlow | fitness, sport, games |
| `playful-illustration` | Fredoka / Nunito | kids, casual, social |

## Copy rules (enforced by `check`)

- One benefit per panel, 3–8 words; the first three panels carry the pitch (they show in search results).
- **No invented claims.** Rankings, user counts, ratings, stars, awards and percentages are errors without
  `evidence:` (where the number comes from). Superlatives ("best") warn: fine as everyday language, not as a claim.
- Store-forbidden (errors even with evidence): Apple recognitions, URLs, prices and discounts, ©, other platforms.
- A `stat` is an error without `evidence:` and warns without a `footnote:` saying what it measures. Chips are checked
  like any copy, and one chip list shared by several languages warns (give one list per locale).
- Laurels, "Featured by Apple", "As seen in" press logos and award badges are what store sets imitate most and what
  this kit refuses to invent: Apple recognitions are never allowed, and third-party logos and awards need the
  owner's evidence and rights.
- `[PLACEHOLDER]` copy blocks a render. Quote copy that starts with `[` (YAML reads it as a list).
- Translations are written per language, not word for word; a locale falling back to another language warns.
- A translated headline over untranslated UI warns: capture localized screens (`{locale}` in the path) when they exist.

## Rendering

1. The engine (or the file's layers) → one HTML scene the width of all panels (`N × W` by `H`).
2. A measuring pass in headless Chromium fits every text block to its box, records element boxes and checks that
   every glyph rendered in the intended face.
3. The shooting pass renders the master PNG at full size; a second pass without text measures contrast behind each
   headline.
4. The master is cut into exact `W × H` panels (`NN-<id>.png`, store order), RGB with an sRGB profile; the panels are
   checked to reassemble into the master pixel for pixel. Output is deterministic: the same file gives the same bytes.

Devices are CSS 3D (stacked slices for thickness, lit band, glare, dynamic island, silhouette shadows), not ray-traced.
Screens are the real PNGs, never redrawn.

Per locale and slot the render writes `panels/`, `panorama.png`, `presentation.png` (as on a product page, right to
left for RTL), `store-preview.png`, `report.md` and `source/` (scene.html, layout.yaml, notext.png); plus
`design-tokens.json` and `campaign-manifest.json` (sizes and sha256 of every file).

## QA (in report.md)

Errors block `--install`; warnings are for Claude and the owner to judge.

Before anything renders, the spec check (`studio/spec.py`, run by `campaign.py`) refuses a set where **half or fewer**
of the panels show the app in use: Apple approves screenshots only when more than half of them, per device type and
language, show the app in use (2.3.3, [help](https://developer.apple.com/help/app-review/guideline-reference/2-3-3-screenshots)).
A panel counts when a device or card covers at least a fifth of it with a real screen; login, sign-in, sign-up,
splash, launch, title or welcome screens don't count. A phone that spans two panels counts for both.

| Error | Warning |
|---|---|
| text crossing a panel seam | text inside the safe margins |
| text that does not fit even at the minimum size | a face did not load, or lacked glyphs (a fallback drew them) |
| two text blocks overlapping | headline under 10.5 pt at search-result size (panels 1–3) |
| contrast under 2:1 behind a text block (measured on the no-text pass) | contrast under 3:1 |
| an image that did not load | a headline over a phone screen; a panel with little real UI; a small hero phone |
| export: count, names in store order, PNG, exact size, alpha, one flat colour | export: no colour profile |

## Localization and RTL

Each locale renders its own master. For RTL locales with `rtl_flow: mirror` the whole scene mirrors: x positions,
y-rotations and z-rotations flip, text aligns to the right, shapes mirror, and panel 1 is cut from the **right** end
(the App Store shows RTL sets right to left). Screens and text are never mirrored. `rtl_flow: keep` keeps the
left-to-right layout and only right-aligns the text.

## Reference images and generated art

- References the owner gives are read for technique only; nothing from them is placed in the output.
- Background art goes under `artwork:` with `source` and `licence` (validation refuses it otherwise). Generated art
  also records the tool and prompt (`references/image-generation.md`). Generated art never shows UI, devices with fake
  screens, Apple products as the subject, logos, or text.
- Image generation is optional: every engine works without it.

## Editable outputs

- **Claude Design canvas** (claude.ai): `campaign.py canvas campaign.yaml --out DIR` writes `DIR/project/canvas.json`,
  `Main.dc.html` (the whole panorama, when it is at most 8000 px wide) and one artboard per panel, with live text and
  inline styles the canvas edits, and `DIR/assets.json` (half-size copies of the screenshots to upload). Each panel
  artboard holds only the elements that touch its column. The export is deliberately lighter than the render:
  thin phones (4 slices, not 22), and no filters, blend modes or 3D context (`perspective`, `preserve-3d`). Each of
  those gets its own compositing layer, and a canvas of several 3D-phone boards loads, then goes blank about 20 s
  later. If a canvas goes blank after loading, look for these first. Then, from the session:
  0. check that the account has the Design type: Artifact `action: "list"`, `scope: "types"` (or a quickstart with
     `intent: "design"`). Artifact types are per account, and some sessions' Artifact tool has no `type_url` at all.
     If no Design type is listed, there is no canvas: use the **review page** below instead, and tell the owner the
     editable canvas needs the Design type on their account;
  1. create the canvas: Artifact publish with the Design type's `type_url`, a `title`, `auto_open: "after_first_write"`;
  2. upload every file in `assets.json` to it (`asset: true`, `file_paths`) and write `DIR/asset-urls.json` as
     `{"__ASSET_001__": "/_blob/<id>", ...}` (token order = `assets.json` order);
  3. `campaign.py canvas-link DIR`;
  4. publish `project/canvas.json` + `project/Main.dc.html` (`root: DIR`), then the panel artboards in one more call.
  The canvas is for review and hand edits. The App Store files still come from `render`.
- **Review page** (no Design type, or the owner only wants to look): after `render` (and `concepts`),
  `campaign.py review-page OUT [--locale L] [--slot S] [--file F]` writes one self-contained `OUT/review.html`:
  the presentation, every panel of that locale and slot, the concepts contact sheet and `report.md`, as embedded
  JPEGs sized to stay under 16 MB. Publish it as a plain Artifact page. It is read-only: changes go back through
  `campaign.yaml` and `render`.
- **Figma**: open `source/scene.html` in a browser and use `html_to_figma` (see `references/figma.md`), or rebuild
  from `layout.yaml`. Export at scale 1 and run `validate_kit.py`.

## Limitations

- Devices are CSS 3D, not physically rendered (no Blender); no hands or photographed people unless supplied as art.
- `feature-explosion` finds UI cards with a row-variance heuristic; on busy screens set `card` layers by hand.
- Fonts download once from Google Fonts; offline without a cache, a system face is used and QA warns.
- Concepts render at 30% scale; the final QA runs only on the full render.
- The canvas export is a snapshot of one locale and slot; edits there do not flow back into `campaign.yaml`.
  Its phones are flat (no shading, shadows or perspective), so judge depth and lighting on the rendered PNGs.
