# Screenshot trends and what the kit takes from them

Research of 2026-11-21 (with Codex, web search). Re-check before relying on it after six months: App Store surfaces
and specifications move every year. Evidence (documented results) is kept apart from recommendations (judgement).
What is built: the engines in `creative-director.md`, the diversity picker (`studio/diversity.py`), app motifs
(`studio/motifs.py`) and `campaign.py art-briefs`.

## Lessons from other open screenshot skills (2026-11-21)

Read for technique only; nothing copied.
- parthjadhav/app-store-screenshots: "break the phone parade" every two or three panels (a photo, an object, a mosaic,
  a type wall); one cross-screen moment per set, at most two for 8-10 panels, crossing the seam by 10-30% through
  negative space and never through text; end on a closer (phone mosaic or feature wall); every panel must still sell
  one idea alone at about 160 px wide. → `breakout` closer, `flight-path` plane on the first seam.
- adamlyttleapps/claude-skill-aso-appstore-screenshots: a "breakout": one whole real UI panel scaled up past both
  edges of the phone with a soft shadow, only when it directly backs the headline; at most one or two supporting
  elements, never random decoration. → `breakout`, motifs limited to what the panel's words call for.
- dtthaison/app-screenshots-pro-skill: 41 layouts and named panorama patterns (wave-ride, timeline, giant-word,
  constellation, orbit, ticker). → `orbit`, `flight-path`, `type-weave`.


**Research date: 2026-11-21.** All links were accessed on this date; publication or capture dates appear where available. **Evidence** means documented behavior or reported results. **Recommendation** means creative judgment.

**Research limitation:** live listing metadata was accessible, but some screenshot images and galleries were blocked. The sequences below use identifiable published captures and gallery annotations—not an assertion that every storefront currently serves the same variant.

## 1. What changed in 2025–2026

| Change | Evidence | Renderer implication |
|---|---|---|
| **Search-intent-specific campaigns** | WWDC25 introduced keyword assignments for custom product pages. [Apple, June 2025](https://developer.apple.com/videos/play/wwdc2025/328/) | Separate `audience/message` from `visualEngine`. Different search intents need different proof, not merely different backgrounds. |
| **Headers and search artwork become separate creative surfaces** | iOS/iPadOS 27 support product-page headers and search-result images/videos. Search artwork can replace the default screenshot presentation. [Apple, June 2026](https://developer.apple.com/videos/play/wwdc2026/205/); [release announcement, 2026-10-05](https://developer-mdn.apple.com/news/?id=ljpl7kyn) | Produce screenshot sets **and** independently composed discovery artwork. Don’t stretch screenshot 1 into a banner. |
| **One universal asset can feed both placements** | Header: **3840×1646**. Search: **1920×1280–3840×2560**. Universal: **5244×2950**, with a **1402×962** central safe area at **1921,660**. [Apple specifications, undated/current](https://developer.apple.com/help/app-store-connect/reference/app-information/creative-assets-specifications) | Add placement-specific crop previews. Prefer separate compositions when the universal safe area makes the subject too small. |
| **Screenshot compliance is more explicit** | Apple now explicitly requires **more than half** the screenshots, per device and localization, to show the app in use. Tiny UI behind dominant advertising is a negative example. [Apple screenshot guidance, undated/current](https://developer.apple.com/help/app-review/guideline-reference/2-3-3-screenshots) | Store provenance and `showsAppInUse` metadata. Six panels require at least four qualifying panels. |

**Do not equate iOS 26’s Liquid Glass with a requirement to put glass everywhere.** It is a platform aesthetic, not published evidence that translucent screenshot backgrounds convert better.

## 2. Specific apps: what their first three screenshots do

These are reference sequences, not approval precedents.

| App / evidence date | Screenshot 1 → 2 → 3 | Useful lesson |
|---|---|---|
| **Duolingo — documented October 2025 creative** | Breadth of subjects → speed of learning → short, playful lessons. Orange, blue and purple panels combine large copy, characters and lesson UI. [Designer’s portfolio, undated; embedded capture dated 2025-10-19](https://www.danwirtheim.com/duolingo-doors) | Different colors create rhythm without abandoning one brand. Duolingo identified itself as the top-grossing Education app globally on both stores in its [2025-02-28 filing](https://duolingo.gcs-web.com/static-files/8f01b324-2c4b-4460-a499-6f364340eff7). |
| **Tiimo — 2026-01-30 analysis** | Award/visual-planner positioning → visual-day promise, continuing hand-held-device imagery → AI brain-dump functionality with UI callouts. [Gummicube](https://www.gummicube.com/blog/how-tiimo-can-remain-competitive-in-the-ai-planner-mobile-space) | Human context and alternating composition create a sequence. The analyst flags thin, small text as a thumbnail weakness. Tiimo was Apple’s [2025 iPhone App of the Year, December 2025](https://www.apple.com/newsroom/2025/12/apple-unveils-the-winners-of-the-2025-app-store-awards/). **Do not reproduce the award treatment.** |
| **Tinder — gallery accessed 2026-11-21; capture date unspecified** | Lifestyle-photo brand hook → profile/UI collage about compatibility → flat UI presentation of dating with friends. [Screenspo](https://www.screenspo.com/apps/tinder) | Change the composition between panels: photograph, collage, interface. |
| **Headspace — gallery accessed 2026-11-21; capture date unspecified** | Awards → colorful content-category tiles → a concrete meditation-course screen. Gallery lists category grossing rank #13, without a historical ranking window. [Screenies](https://screenies.app/apps/493145008-headspace-sleep-meditation) | Move from broad promise to tangible product evidence. Borrow the illustrated content system, **not awards or price claims**. |
| **Strava — published 2025 listing capture** | Activity tracking/map → Watch recognition/integration → community activity feed. Orange branding holds together maps, devices and social content. [CatDoes, 2025 article](https://catdoes.com/blog/react-native-app-examples) | Product evidence can change scale and content while retaining recognition. The current listing independently confirms Editors’ Choice status. [App Store, accessed 2026-11-21](https://apps.apple.com/us/app/strava-run-bike-walk/id426826309) |

## 3. Current visual directions

These are **observed directions and creative interpretations**, not a statistically representative prevalence ranking. Search-size assessments are my judgment.

| Trend | Two-line description | Examples | Core layout technique | Search-result survival |
|---|---|---|---|---|
| **Color as sequence** | Distinct panel colors make separate benefits recognizable.<br>Consistency comes from illustration and typography rather than identical backgrounds. | Duolingo; Headspace | Flat saturated fields; large UI; heavy sans; one dominant hue per panel. | **Strong** when headline and silhouette remain simple. |
| **Human context before interface** | Establish the situation or desired feeling first.<br>Follow promptly with real UI proving the promise. | Tinder; Tiimo; Strava | Full-bleed photography or hand-held device; asymmetrical crops; restrained text; brand accent over natural color. | **Conditional:** faces survive; small UI and nuanced copy do not. |
| **Oversized product evidence** | A meaningful UI region becomes the main image.<br>The device frame becomes optional rather than mandatory. | Tinder’s flat UI panels; Tiimo’s AI callouts; Headspace’s course screen | Enlarge a genuine capture region; crop outside the focal action; use quiet backgrounds and short labels. | **Strong** for recognizable actions; weak for dense dashboards. |
| **Illustration as brand language** | Characters and content artwork convey a distinctive emotional tone.<br>Real product screens establish what the app actually does. | Duolingo; Headspace | Large character/content shapes; flat illustration; rounded typography; warm or vivid color blocks. | **Strong brand recognition; conditional functional clarity.** |
| **Mixed-composition storytelling** | A set changes visual structure as the argument progresses.<br>Photo → collage → UI is more varied than six repeated phone cards. | Tinder; Tiimo | Alternate scale, alignment and media; repeat a small number of brand constants; keep each panel independently understandable. | **Strong** if panel 1 does not depend on a later reveal. |
| **Intent-specific proof** | Screenshots answer the reason someone searched or tapped an ad.<br>Localization changes scenarios and emphasis as well as language. | Headspace; Paper by FiftyThree | Reorder captures; change relevant content and captions; retain a coherent visual system within each variant. | **Strong relevance hypothesis; measured support exists below.** |

Sources for these directions: the app references above; [Headspace/M+C Saatchi, MAU May 2025](https://pages.mcsaatchiperformance.com/hubfs/Global%20Resources/Events/MAU%202025/MAU2025_MCSP_Headspace%20FINAL%20May13.pdf); [FiftyThree/SplitMetrics, undated historical case](https://splitmetrics.com/customers/fiftythree-localizes-screenshots-for-app-store/).

### What the requested research sources actually support

| Source | Finding and evidence quality |
|---|---|
| **AppTweak / SplitMetrics** | Their [creative-trends article, updated 2025-03-27](https://www.apptweak.com/en/aso-blog/7-app-store-creative-trends-you-can-t-miss), recommends lifestyle imagery, vivid colors and storytelling—but still discusses **2022’s Very Peri**. An updated date is not proof of a new trend. |
| **Phiture** | Reports average improvements from intent-based CPPs; supports audience/message matching more directly than any specific visual fashion. [2023-07-12](https://phiture.com/mobilegrowthstack/aso-ua-data-to-strengthen-crm/) |
| **MobileAction** | Offers a practical [2026-01-04 screenshot guide](https://www.mobileaction.co/guide/app-screenshot-sizes-and-guidelines-for-the-app-store/). Use Apple’s current specifications over third-party size tables. |
| **Appfigures** | Its [2025-07-31 teardown](https://appfigures.com/resources/videos/screenshot-tips-proven-to-convert-live-product-page-teardown) emphasizes readable benefits and intent matching. Screenshot-OCR ranking claims are explicitly the presenter’s findings, **not an Apple-confirmed ranking specification**. |
| **ASOMobile** | Its [2026-09-22 guide](https://asomobile.net/en/blog/screenshots-for-app-store-and-google-play-in-2025-a-complete-guide/) favors authentic UI, coherent sequences and localization. The “70% conversion weight” assertion lacks a disclosed study there; exclude it from forecasts. |
| **Storemaven** | Searches surfaced an [undated mirrored FAQ](https://www.thestoremaven.store/faq/) claiming screenshot gains exceeding 35%. Without a verified original experiment, sample and dates, **do not treat this as measured evidence**. |
| **Behance / Dribbble** | [Behance, 2026-03-04](https://www.behance.net/gallery/245211467/Mobile-App-Store-Screenshots-Design): dark/orange, large-type campaign. [Headspace Dribbble project, undated](https://dribbble.com/shots/26524767-App-Store-Screenshots-App-Store-Preview-Headspace): colorful illustrated world. Useful art direction; no demonstrated conversion causality. |
| **Screenlane / Mobbin** | [Screenlane](https://screenlane.com) was blocked. [Mobbin](https://mobbin.com), accessed 2026-11-21, exposes shipped UI/flow references; I could not verify dedicated store-marketing sequences. Do not confuse in-app screens with acquisition creative. |

## 4. Measured conversion versus fashion

| Evidence | Reported result | What it establishes—and does not |
|---|---:|---|
| **Episode screenshot A/B refresh**, SplitMetrics; publication year unspecified, experiment labeled May 31 | **+10% iOS conversion** | A particular refreshed screenshot set beat its control. No isolated attribution to typography, illustration or layout; public sample/confidence details are absent. [Case study](https://splitmetrics.com/customers/how-splitmetrics-optimize-helped-episode-boost-cr/) |
| **Hobnob screenshot background test**, historical, undated | **−20% iOS conversion** from the same-background treatment | A treatment that won on Android lost on iOS. Strong counterexample to universal style rules. [Case study](https://splitmetrics.com/customers/hobnob-app-optimizing-with-splitmetrics/) |
| **Paper localization A/B testing**, historical, undated | **+33% installs** | Localized creative can matter materially; not evidence that translating captions alone produces this lift. [Case study](https://splitmetrics.com/customers/fiftythree-localizes-screenshots-for-app-store/) |
| **Headspace tailored storefront program**, May 2025 | **+26% average CVR; −25% average CPI** | Program-level results spanning tailored listings; not an isolated screenshot-layout experiment. [MAU presentation](https://pages.mcsaatchiperformance.com/hubfs/Global%20Resources/Events/MAU%202025/MAU2025_MCSP_Headspace%20FINAL%20May13.pdf) |
| **Duolingo redesign**, portfolio with October 2025 capture | **+15% CVR** | Designer-reported outcome; public page does not disclose randomization, sample or confidence interval. [Portfolio](https://www.danwirtheim.com/duolingo-doors) |
| **Phiture intent-based CPP portfolio**, 2023-07-12 | **+30% average CVR; −25% CPA** | Agency aggregate, not a current randomized comparison of aesthetic styles. [Article](https://phiture.com/mobilegrowthstack/aso-ua-data-to-strengthen-crm/) |

**Not established by this evidence:** glass, indigo gradients, 3D phones, handwritten captions, panoramic continuity or oversized typography universally increasing conversion.

**Testing recommendation:** compare materially different concepts first, holding offer, feature order and traffic constant. Then isolate the winning concept’s variables. Predefine sample size, minimum detectable effect and stopping rule; report relative lift, absolute percentage-point change and uncertainty. Measure activation alongside installs.

# Twelve creative engines

**All recipes below are proposals.** References indicate a related technique, not an exact existing implementation.

**Notation:** `R(x,y,w,h)` gives a rectangle in percentages of panel width/height. Preserve screenshot aspect ratio inside it; crop with an explicit focal point, never stretch UI. Use a 6% outer safety margin unless intentional bleeding is specified.

**Axes:** device / composition / background / typography / color / eye path.

**Novelty:** **NEW** means structurally absent from the supplied engine names, provisionally; source-code inspection could reveal overlap. **OVERLAP** means a disciplined implementation of an existing family.

## 1. Interface Monument — OVERLAP: immersive, minimal-premium

**Idea:** the product itself fills the poster.

- **CSS:** real UI fills `R(0,0,100,100)`; use a 120–150% crop only where it preserves context. Place one caption in a quiet area at `R(6,76,88,18)`. No outer phone or decorative card.
- **Axes:** UI only / zoomed detail / flat / compact bold sans / monochrome / repeated focal anchor.
- **Suits:** utilities, maps, cameras, music tools.
- **Risk:** an attractive crop can conceal what the feature does.
- **Reference:** Tinder’s flat UI presentations; Headspace’s course proof.
- **Art:** none behind the UI; generate an optional monochrome material plate for the separate header.

## 2. Specimen Sheet — NEW

**Idea:** present features as precisely arranged exhibits.

- **CSS:** two-column grid within `R(6,18,88,72)`, 4%W gutters. One real capture spans both columns and 46%H; two detail crops occupy the remaining row. Labels sit outside capture bounds.
- **Axes:** UI only / grid / flat / mono / cool neutral with one accent / row-by-row scan.
- **Suits:** analytics, developer tools, scanners, professional utilities.
- **Risk:** small cells become unreadable; never give three regions equal priority.
- **Reference:** Headspace’s grouped content tiles; applied here as a stricter specimen system.
- **Art:** subtle scanned-paper grain, almost imperceptible; grid and rules remain CSS.

## 3. Field Journal — OVERLAP: editorial

**Idea:** a product demonstration annotated like a working notebook.

- **CSS:** full capture in `R(31,12,63,74)`; marginal notes in `R(6,20,21,58)`; bottom caption at `R(6,89,88,7)`. Alternate the margin side between panels.
- **Axes:** full device / editorial column / paper texture / small editorial serif / parchment and ink / alternating margins.
- **Suits:** journaling, reading, travel, research.
- **Risk:** editorial notes fail at search size; one larger benefit must remain.
- **Reference:** Paper by FiftyThree’s creation-centered presentation.
- **Art:** paper fibers, pencil smudges and restrained botanical fragments—no written notes.

## 4. Contact Sheet — NEW

**Idea:** a photographic essay with the app visible inside the story.

- **CSS:** collage cells at `R(0,0,58,42)`, `R(62,0,38,42)` and `R(0,46,100,54)`. On qualifying panels, the large cell contains a genuine capture. One short handwritten-style caption occupies a reserved gap.
- **Axes:** UI only / collage / photography / handwritten / muted natural colors / diagonal hop.
- **Suits:** photography, travel, food, social products.
- **Risk:** lifestyle photography can overwhelm product evidence.
- **Reference:** Tinder’s photo-to-collage sequence.
- **Art:** original environmental photographs without devices or recognizable real people; use licensed photography where authenticity matters.

## 5. Type Weave — OVERLAP: typographic-hero, big-type

**Idea:** words and product interlock instead of sitting in separate bands.

- **CSS:** three display lines across `R(-3,7,106,77)`; oversized capture crosses them in `R(24,27,82,69)`. Layer selected decorative glyphs behind the capture; preserve the complete readable message elsewhere.
- **Axes:** cropped device / poster / type-as-background / giant stacked words / duotone / zigzag through text and UI.
- **Suits:** fitness, music, expressive consumer tools.
- **Risk:** localization breaks the choreography.
- **Reference:** Duolingo’s forceful hierarchy; Spotify’s oversized device treatment.
- **Art:** optional ink texture only. All typography is HTML.

## 6. Terrain Ribbon — OVERLAP: panoramic-flow, cinematic

**Idea:** a shared landscape guides the eye across independently useful panels.

- **CSS:** one background canvas spans `N×W`; each panel samples its segment. Horizon sits at 58%H. Captures occupy 72–90%W, with alternating centers at 45% and 62%H. Keep captions wholly inside each panel.
- **Axes:** cropped device / panorama / photography / wide display sans / earth colors / continuous horizontal sweep.
- **Suits:** outdoor, travel, weather, location products.
- **Risk:** a connected picture can become meaningless when only one panel is visible.
- **Reference:** Tiimo’s linked opening composition; Strava’s outdoor/map context.
- **Art:** one continuous landscape, generated as a wide master; no invented route or map data.

## 7. Action–Result Diptych — OVERLAP: before-after

**Idea:** show the input and its actual consequence.

- **CSS:** upper region `R(6,14,88,31)` shows the action capture; lower region `R(6,53,88,39)` shows the result capture. A narrow connective band occupies 45–53%H. Use genuine sequential states.
- **Axes:** UI only / split / flat / strong humanist sans / warm–cool contrast / top-to-bottom cause and effect.
- **Suits:** editors, automation, planners, translation.
- **Risk:** implying a transformation the app cannot deliver.
- **Reference:** Tiimo’s brain-dump-to-plan proposition; Duolingo’s exercise demonstrations.
- **Art:** abstract connective marks only; both states must come from the app.

## 8. Task Comic — NEW

**Idea:** explain one task through three readable beats.

- **CSS:** three horizontal strips at y=7%, 35%, 63%, each 26%H. Place real capture crops inside the strips; captions occupy a consistent 24%W side rail. Alternate rail sides only between panels.
- **Axes:** UI only / sequential strips / illustrated / conversational sans / vivid per-panel / stepped reading.
- **Suits:** onboarding-heavy tools, education, messaging, workflows.
- **Risk:** too much explanation; keep each beat to a verb and visible action.
- **Reference:** Duolingo’s lesson storytelling; Episode’s narrative approach.
- **Art:** original character reactions in the margin; never generated speech text or UI.

## 9. Card Conveyor — NEW

**Idea:** genuine product cards form a flowing stack.

- **CSS:** three screenshot-derived card crops at `R(6,13,80,29)`, `R(14,38,80,29)`, `R(6,63,80,29)`. Add a contextual full-screen capture on the next panel. Use soft shadow and 0–3° rotation.
- **Axes:** UI only / stacked cards / pattern / rounded bold sans / pastel / descending cascade.
- **Suits:** task lists, recipes, content discovery, habits.
- **Risk:** detached elements can look like fabricated functionality.
- **Reference:** Headspace’s content tiles; Tinder’s profile collage.
- **Art:** a bespoke low-contrast repeating motif tied to the subject.

## 10. Machine Diagram — NEW

**Idea:** make one feature feel understandable through an annotated technical drawing.

- **CSS:** full capture in `R(26,15,68,73)`; one true detail crop in `R(4,58,42,27)`; up to two leader lines and numbered labels. Headline occupies `R(6,5,88,8)`.
- **Axes:** full device / annotated zoom / fine pattern / mono / dark charcoal and signal amber / radial inspection.
- **Suits:** audio, camera, engineering, measurement.
- **Risk:** technical clutter or invented specifications.
- **Reference:** Strava’s measurable activity proof; Tiimo’s feature callouts.
- **Art:** optional material texture; construct measurement lines in CSS, and never invent measurement values.

## 11. Character Stage — OVERLAP: illustrated, sticker-pop

**Idea:** a recognizable character introduces the benefit, then makes room for proof.

- **CSS:** optional art-only opener: character `R(8,25,84,60)`, copy `R(6,6,88,18)`. Remaining panels: genuine capture `R(6,24,88,68)`, character cropped into a corner occupying at most 16% of panel area.
- **Axes:** none on opener, UI thereafter / poster / generated illustration / rounded display / bright complementary colors / character-led handoff.
- **Suits:** education, family, habits, wellbeing.
- **Risk:** illustration becomes the advertised product instead of supporting it.
- **Reference:** Duolingo; Headspace.
- **Art:** an original character sheet with consistent proportions, poses and lighting. Never imitate their mascots.

## 12. Multi-Screen Choreography — OVERLAP: device-cluster, floating-3d

**Idea:** several screens show an actual relationship: create, review, complete.

- **CSS:** foreground full device at `R(17,24,66,69)`; two secondary devices at `R(-18,10,52,55)` and `R(70,43,48,51)`. Maximum ±6° rotation. Place copy in the remaining upper-right region.
- **Axes:** multiple devices / diagonal cluster / flat / condensed display / near-black and electric lime / diagonal relay.
- **Suits:** collaboration, multi-step workflows, cross-device products.
- **Risk:** foreground screen too small; misleading cross-device availability.
- **Reference:** Structured’s cross-device demonstration, documented in [Gummicube, 2026-01-30](https://www.gummicube.com/blog/how-tiimo-can-remain-competitive-in-the-ai-planner-mobile-space).
- **Art:** isolated abstract sculptural props; actual frames and screens are deterministic assets.

Spotify reference for engine 5: [Kit, listing version dated 2026-10-19](https://kit.directory/apps/spotify). Other engine references refer to the dated evidence tables above.

# Selecting six genuinely different concepts

## Structural selection rule

Represent every concept with six categorical values:

```text
device, composition, background, typography, colorStrategy, eyePath
```

For every pair:

```text
distance(a,b) = count of axes with materially different values
require distance(a,b) >= 3
require >= 2 differences among device/composition/background/eyePath
```

The second condition prevents a palette and font change from disguising the same layout.

1. Filter out engines that lack suitable real captures.
2. Evaluate all six-engine combinations—only **924** combinations for twelve engines.
3. Reject any combination violating the pairwise rules.
4. Maximize the minimum pairwise distance, then total distance.
5. Reject sets whose grayscale thumbnails still look substantially identical.

**Suggested starting six:** Interface Monument, Field Journal, Contact Sheet, Type Weave, Task Comic, Multi-Screen Choreography. They span frameless immersion, editorial framing, collage, poster typography, sequential explanation and device relationships.

Treat “eye path” as actual geometry. Renaming two centered vertical stacks does not create a difference.

## Palette and typography exclusivity

Assign each selected concept one exclusive `paletteFamilyId` and `typePresetId`. Reserve them across the six concepts before generating any panels.

| Concept | Exclusive palette family | Exclusive typography preset |
|---|---|---|
| Interface Monument | Achromatic white/graphite | Compact grotesk, bold, sentence case |
| Field Journal | Parchment/sepia | Editorial serif with restrained sans captions |
| Contact Sheet | Sage/terracotta, natural photography | Handwritten accent with plain sans primary copy |
| Type Weave | Cobalt/coral duotone | Giant condensed display, stacked lines |
| Task Comic | Candy multicolor | Rounded conversational sans |
| Multi-Screen Choreography | Near-black/electric lime | Squared technical display |

**Enforcement:** palette IDs encode dominant hue range, lightness and saturation—not just hex codes. Typography IDs encode family, width, weight, case, hierarchy and line treatment. Two different font filenames do not automatically count as different presets.

Real screenshots retain their original colors. Exclusivity applies to the **campaign wrapper**, not recoloring product evidence.

# Image-model workflow and compliance

## Generate art assets, then compose deterministically

Each engine gets a separate art brief specifying:

```text
subject + medium + palette family + lighting + crop
+ reserved empty regions + intended placement + exclusions
```

Generate a master art asset and related variants using the same reference. Feed the renderer **art layers only**; insert real captures, approved frames and localized HTML text afterward.

**Never generate:**

- Apple hardware, logos or counterfeit device mockups.
- App screens, buttons, charts, notifications, results or fictional capabilities.
- Headlines, labels, testimonials, awards or other campaign text.
- Competitor characters, recognizable protected artwork or fake endorsements.

**Important distinction:** “no generated hardware, UI or text” is a production rule for this renderer. Apple permits explanatory text/image overlays; it does **not** impose a blanket ban on text or accurate hardware presentations. Its rule is truthful product representation. [Apple Review Guidelines §2.3, current/undated](https://developer.apple.com/app-store/review/guidelines/)

## Submission rules

- Require `floor(N/2)+1` qualifying app-in-use panels for **every device/localization**; target five of six where possible.
- A full phone containing a login screen does not qualify. A tiny capture behind a giant slogan should not qualify.
- Preserve capture provenance: app build, device, locale, scenario and original image hash.
- Exclude prices, URLs, copyright symbols, awards and other-platform references from campaign overlays. Apple specifically discourages Apple-designated recognitions; your blanket award exclusion is stricter. [Apple asset guidance, current/undated](https://developer.apple.com/app-store/asset-best-practices/)
- Disclose paid-feature requirements without inserting prohibited pricing. Use fictional account data captured in the real app. [Apple §2.3.2 and §2.3.9, current/undated](https://developer.apple.com/app-store/review/guidelines/)

## Nine-language production

- Use locale-specific **real captures**, not translated text pasted over UI.
- Store captions as semantic message keys with approved short/long variants.
- Give each text region a line budget and measured bounds; fail the render on overflow rather than silently shrinking text.
- Reserve approximately **35% expansion capacity** as an engineering allowance, then test actual translations.
- Provide Latin/Cyrillic and language-appropriate CJK font mappings. Preserve each concept’s typographic character through weight, density and hierarchy.
- Disable Latin-style tracking and forced uppercase for CJK. Keep handwritten text supplementary; never make comprehension depend on it.
- Reflow Type Weave and editorial columns per locale; do not freeze English line breaks.
- Verify full-resolution exports, isolated panels, and a **100–130 CSS-pixel-wide thumbnail stress test**. That width is a QA heuristic, not an Apple specification.
- Preview header/search crops separately in App Store Connect. Keep every panel understandable without seeing its neighbors.